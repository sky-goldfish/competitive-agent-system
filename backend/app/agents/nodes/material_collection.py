import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

from app.agents.state import AgentState
from app.db.models import new_id
from app.providers.search.base import SearchProvider
from app.services import call_tracer
from app.services.knowledge_service import retrieve_for_material_collection

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, str, dict[str, Any]], None]

ANALYSIS_DIMENSIONS = ["产品定位", "核心功能", "价格与商业模式", "用户评价与痛点"]
CORE_SCHEMA_SLOTS = ["positioning", "core_features", "pricing", "user_feedback"]
SCHEMA_SLOT_DIMENSIONS = {
    "relationship_evidence": "竞争关系",
    "positioning": "产品定位",
    "core_features": "核心功能",
    "pricing": "价格与商业模式",
    "user_feedback": "用户评价与痛点",
    "market_signal": "产品定位",
    "risk_opportunity": "用户评价与痛点",
}
SLOT_LABELS = {
    "relationship_evidence": "竞品关系、竞争需求、重叠点、替代路径",
    "positioning": "定位、所属公司、官网、目标用户",
    "core_features": "核心能力、特色功能、平台/参数",
    "pricing": "价格、套餐、企业版或电商价格",
    "user_feedback": "评价、痛点、差评、优缺点",
    "market_signal": "新闻、测评、版本更新、榜单",
    "risk_opportunity": "限制、机会点、替代方案",
}
COMMODITY_MARKERS = [
    "保温杯",
    "水杯",
    "硬件",
    "商品",
    "消费品",
    "电商",
    "家电",
    "家具",
    "食品",
    "饮料",
    "服装",
    "鞋",
    "箱包",
    "配件",
    "美妆",
    "护肤",
    "清洁",
    "宠物用品",
    "玩具",
    "母婴",
    "猫砂",
    "猫粮",
    "狗粮",
    "宠物",
    "智能家居",
    "耳机",
    "音箱",
    "手表",
    "手环",
    "mug",
    "cup",
    "bottle",
    "hardware",
    "appliance",
    "gadget",
    "device",
    "pet",
    "toy",
    "furniture",
    "cosmetic",
    "skincare",
]

SOURCE_TYPE_LABELS = {
    "brand_official_product_page": "品牌官网/商品介绍",
    "official_site": "官网介绍",
    "official_docs": "官方文档/帮助中心",
    "official_pricing_page": "官方价格页",
    "ecommerce_product_page": "电商商品页",
    "ecommerce_user_review": "电商用户评价",
    "professional_review": "专业测评",
    "review_site": "第三方评价站",
    "social_review_post": "社交平台评价",
    "community_discussion": "社区讨论",
    "news_article": "新闻/媒体报道",
    "marketplace_listing_unknown_seller": "电商/渠道页",
    "unknown": "未分类来源",
}

SOURCE_WEIGHTS = {
    "brand_official_product_page": 0.95,
    "official_site": 0.94,
    "official_docs": 0.92,
    "official_pricing_page": 0.93,
    "ecommerce_product_page": 0.86,
    "professional_review": 0.82,
    "ecommerce_user_review": 0.78,
    "news_article": 0.78,
    "review_site": 0.72,
    "social_review_post": 0.66,
    "community_discussion": 0.62,
    "marketplace_listing_unknown_seller": 0.56,
    "unknown": 0.42,
}

DIMENSION_SOURCE_BONUS = {
    "竞争关系": {
        "official_site",
        "brand_official_product_page",
        "review_site",
        "professional_review",
        "community_discussion",
        "news_article",
    },
    "产品定位": {
        "brand_official_product_page",
        "official_site",
        "news_article",
        "professional_review",
    },
    "核心功能": {
        "brand_official_product_page",
        "official_site",
        "official_docs",
        "professional_review",
        "ecommerce_product_page",
    },
    "价格与商业模式": {
        "official_pricing_page",
        "ecommerce_product_page",
        "marketplace_listing_unknown_seller",
    },
    "用户评价与痛点": {
        "ecommerce_user_review",
        "review_site",
        "social_review_post",
        "community_discussion",
        "professional_review",
    },
}


def material_collection_node(
    state: AgentState, search: SearchProvider, progress: ProgressCallback | None = None
) -> AgentState:
    requirement = state.get("requirement", {})
    if state.get("target_understanding"):
        requirement = {
            **{
                k: v
                for k, v in state["target_understanding"].items()
                if v and k not in requirement
            },
            **requirement,
        }
    competitors = state.get("selected_competitors", [])
    qa_retry_queries = state.get("qa_retry_queries")
    initial_sources = state.get("sources", [])
    initial_evidence = state.get("evidence", [])
    if competitors and not qa_retry_queries:
        knowledge_sources, knowledge_evidence = retrieve_for_material_collection(
            state.get("run_id", ""),
            competitors,
            requirement,
            dimensions=ANALYSIS_DIMENSIONS,
        )
        initial_sources, initial_evidence = _merge_knowledge_context(
            initial_sources, initial_evidence, knowledge_sources, knowledge_evidence
        )
        _emit(
            progress,
            "knowledge_retrieval",
            "检索历史知识库并注入可复用证据",
            {
                "source_count": len(knowledge_sources),
                "evidence_count": len(knowledge_evidence),
                "matched_products": sorted(
                    {
                        item.get("related_product")
                        for item in knowledge_evidence
                        if item.get("related_product")
                    }
                ),
            },
        )

    if qa_retry_queries:
        product_queries = _build_retry_product_queries(
            competitors, qa_retry_queries, requirement
        )
    else:
        product_queries = _plan_material_queries(
            competitors,
            requirement,
            initial_evidence,
            initial_sources,
        )
    quarts = [quart for item in product_queries for quart in item["queries"]]
    product_types = sorted({quart["product_type"] for quart in quarts})
    missing_slots = sorted({quart["target_slot"] for quart in quarts})
    _emit(
        progress,
        "quart_planning",
        "基于竞品关系、产品类型和知识 Schema 缺口生成检索 Quart",
        {
            "product_count": len(product_queries),
            "quart_count": len(quarts),
            "product_types": product_types,
            "missing_slots": missing_slots,
            "relationship_quart_count": len(
                [
                    quart
                    for quart in quarts
                    if quart["target_slot"] == "relationship_evidence"
                ]
            ),
            "competitor_types": sorted({quart["competitor_type"] for quart in quarts}),
            "relationship_claims": [
                quart["relation_claim"]
                for quart in quarts
                if quart["target_slot"] == "relationship_evidence"
            ][:4],
            "queries": [quart["query"] for quart in quarts[:8]],
            "query_purposes": [quart["target_slot"] for quart in quarts[:8]],
        },
    )
    _emit(
        progress,
        "material_query_planning",
        "为已确认竞品按检索 Quart 规划资料采集 query",
        {
            "product_count": len(product_queries),
            "query_count": len(quarts),
            "source_weights": SOURCE_WEIGHTS,
        },
    )

    existing_sources = initial_sources
    existing_evidence = initial_evidence
    is_retry = bool(qa_retry_queries)
    if is_retry and len(existing_sources) > 120:
        ranked = sorted(
            existing_sources,
            key=lambda s: float(s.get("credibility_score") or 0),
            reverse=True,
        )
        existing_sources = ranked[:100]
    sources = list(existing_sources)
    evidence = list(existing_evidence)
    seen_urls = {
        f"{s.get('competitor_id', '')}::{s.get('url', '')}"
        for s in existing_sources
        if s.get("url")
    }
    seen_bare_urls = {s.get("url") for s in existing_sources if s.get("url")}
    collection_iteration = state.get("feedback_loop_count", 0)

    def _safe_ref_id(s: dict) -> int:
        v = s.get("reference_id", 0)
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    _next_ref_id = max((_safe_ref_id(s) for s in existing_sources), default=0) + 1
    for product_query in product_queries:
        competitor = product_query["competitor"]
        product_source_count = 0

        def _search_one_dimension(query_item: dict, trace_ctx: dict | None) -> list[dict]:
            call_tracer.set_worker_trace_context(trace_ctx)
            try:
                results = search.search(
                    query_item.get("query", ""), limit=query_item.get("limit", 4)
                )
            except Exception:
                return []
            return _classify_and_rank_results(results, requirement, query_item)

        if not product_query["queries"]:
            _emit(
                progress,
                "source_search",
                "该竞品已有足够证据，跳过检索",
                {"product": competitor["name"], "source_count": 0},
            )
            continue
        trace_ctx = call_tracer.get_trace_context()
        with ThreadPoolExecutor(
            max_workers=min(4, len(product_query["queries"]))
        ) as executor:
            futures = {
                executor.submit(_search_one_dimension, qi, trace_ctx): qi
                for qi in product_query["queries"]
            }
            try:
                for future in as_completed(futures, timeout=60):
                    query_item = futures[future]
                    try:
                        classified_results = future.result()
                    except Exception:
                        continue
                    for ranked_result in classified_results[:2]:
                        result = ranked_result["result"]
                        source_key = f"{competitor.get('id', '')}::{result.url}"
                        source_type = ranked_result["source_type"]
                        credibility_score = ranked_result["credibility_score"]
                        if (
                            source_key not in seen_urls
                            and result.url not in seen_bare_urls
                        ):
                            seen_urls.add(source_key)
                            seen_bare_urls.add(result.url)
                            ref_id = _next_ref_id
                            _next_ref_id += 1
                            source_title = result.title
                            source = {
                                "competitor_id": competitor["id"],
                                "title": source_title,
                                "url": result.url,
                                "snippet": result.snippet,
                                "source_type": source_type,
                                "provider": search.name,
                                "raw_content": result.raw_content,
                                "credibility_score": credibility_score,
                                "reference_id": ref_id,
                                "metadata_json": _metadata_json(
                                    credibility_score,
                                    ranked_result["rank_score"],
                                    source_type,
                                    ranked_result["label"],
                                    ranked_result["reason"],
                                    query_item,
                                    collection_iteration,
                                ),
                            }
                            sources.append(source)
                            product_source_count += 1
                        else:
                            ref_id = next(
                                (
                                    s["reference_id"]
                                    for s in sources
                                    if s.get("competitor_id") == competitor["id"]
                                    and s.get("url") == result.url
                                ),
                                None,
                            )
                            source_title = next(
                                (
                                    s["title"]
                                    for s in sources
                                    if s.get("competitor_id") == competitor["id"]
                                    and s.get("url") == result.url
                                ),
                                result.title,
                            )
                        evidence.append(
                            {
                                "id": new_id("ev"),
                                "competitor_id": competitor["id"],
                                "related_product": competitor["name"],
                                "related_dimension": query_item.get("dimension", ""),
                                "quote": (result.raw_content or result.snippet)[:800],
                                "summary": _evidence_summary(
                                    query_item, result.snippet
                                ),
                                "confidence": min(
                                    0.95, max(0.5, credibility_score - 0.04)
                                ),
                                "source_url": result.url,
                                "source_title": source_title,
                                "reference_id": ref_id,
                                "source_type": source_type,
                            }
                        )
            except TimeoutError:
                logger.warning(
                    "material_collection as_completed timed out for competitor %s",
                    competitor.get("name", "?"),
                )
        _emit(
            progress,
            "source_search",
            "按来源类型召回并重排序候选网页",
            {"product": competitor["name"], "source_count": product_source_count},
        )

    coverage_report = _build_coverage_report(state["selected_competitors"], evidence)
    _emit(
        progress,
        "source_classification",
        "完成来源分类、可信度评分和召回结果重排序",
        {
            "source_count": len(sources),
            "source_type_counts": _count_source_types(sources),
        },
    )
    _emit(
        progress,
        "evidence_extraction",
        "从来源摘要和正文中抽取结构化证据",
        {"evidence_count": len(evidence)},
    )
    _emit(
        progress,
        "coverage_checking",
        "检查资料维度覆盖度和信息缺口",
        {
            "overall_status": coverage_report["overall_status"],
            "warning_count": len(coverage_report["warnings"]),
        },
    )
    return {
        **state,
        "sources": sources,
        "evidence": evidence,
        "coverage_report": coverage_report,
    }


def _emit(
    progress: ProgressCallback | None,
    stage: str,
    message: str,
    metadata: dict[str, Any],
) -> None:
    if progress is not None:
        progress(stage, message, metadata)


def _merge_knowledge_context(
    existing_sources: list[dict],
    existing_evidence: list[dict],
    knowledge_sources: list[dict],
    knowledge_evidence: list[dict],
) -> tuple[list[dict], list[dict]]:
    if not knowledge_sources and not knowledge_evidence:
        return list(existing_sources), list(existing_evidence)

    sources = list(existing_sources)
    evidence = list(existing_evidence)
    source_key_to_ref: dict[tuple[str, str], int] = {}
    seen_source_keys: set[tuple[str, str]] = set()
    max_ref_id = 0
    for source in sources:
        key = (str(source.get("competitor_id") or ""), str(source.get("url") or ""))
        if key[1]:
            seen_source_keys.add(key)
            ref_id = _safe_int(source.get("reference_id"))
            if ref_id:
                source_key_to_ref[key] = ref_id
                max_ref_id = max(max_ref_id, ref_id)

    old_ref_to_new: dict[int, int] = {}
    for source in knowledge_sources:
        key = (str(source.get("competitor_id") or ""), str(source.get("url") or ""))
        old_ref_id = _safe_int(source.get("reference_id"))
        if key in seen_source_keys:
            if old_ref_id and key in source_key_to_ref:
                old_ref_to_new[old_ref_id] = source_key_to_ref[key]
            continue
        max_ref_id += 1
        merged = {**source, "reference_id": max_ref_id}
        merged["metadata_json"] = _rewrite_metadata_reference_id(
            merged.get("metadata_json"), max_ref_id
        )
        sources.append(merged)
        seen_source_keys.add(key)
        source_key_to_ref[key] = max_ref_id
        if old_ref_id:
            old_ref_to_new[old_ref_id] = max_ref_id

    seen_evidence_keys = {
        (
            item.get("competitor_id"),
            item.get("related_dimension"),
            item.get("source_url"),
            item.get("quote"),
        )
        for item in evidence
    }
    for item in knowledge_evidence:
        key = (
            item.get("competitor_id"),
            item.get("related_dimension"),
            item.get("source_url"),
            item.get("quote"),
        )
        if key in seen_evidence_keys:
            continue
        old_ref_id = _safe_int(item.get("reference_id"))
        ref_id = old_ref_to_new.get(old_ref_id, old_ref_id)
        evidence.append({**item, "reference_id": ref_id})
        seen_evidence_keys.add(key)
    return sources, evidence


def _rewrite_metadata_reference_id(metadata_json: object, reference_id: int) -> str:
    metadata = {}
    if isinstance(metadata_json, str) and metadata_json:
        try:
            parsed = json.loads(metadata_json)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            metadata = parsed
    metadata["reference_id"] = reference_id
    return json.dumps(metadata, ensure_ascii=False)


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _plan_material_queries(
    competitors: list[dict],
    requirement: dict,
    evidence: list[dict] | None = None,
    sources: list[dict] | None = None,
) -> list[dict]:
    planned = []
    quarts = _plan_retrieval_quarts(
        competitors, requirement, evidence or [], sources or []
    )
    for competitor in competitors:
        queries = [
            quart for quart in quarts if quart["competitor_id"] == competitor["id"]
        ]
        planned.append({"competitor": competitor, "queries": queries})
    return planned


def _build_retry_product_queries(
    competitors: list[dict], retry_queries: list[dict], requirement: dict
) -> list[dict]:
    competitor_by_name: dict[str, dict] = {}
    for comp in competitors:
        competitor_by_name[comp["name"].lower()] = comp
        competitor_by_name[comp["name"]] = comp
    product_map: dict[str, list[dict]] = {}
    for rq in retry_queries:
        comp_name = rq.get("competitor_name", "")
        comp = competitor_by_name.get(comp_name.lower()) or competitor_by_name.get(
            comp_name
        )
        if not comp:
            continue
        product_type = _detect_product_type(requirement)
        competitor_type = comp.get("category") or "direct_competitor"
        relationship_model = _build_relationship_model(comp, requirement)
        slot = rq.get("slot", "core_features")
        query = rq.get("query", "")
        if not query:
            continue
        quart = {
            "competitor_id": comp["id"],
            "competitor_name": comp["name"],
            "product_type": product_type,
            "competitor_type": competitor_type,
            "relation_claim": relationship_model["relation_claim"],
            "competed_need": relationship_model["competed_need"],
            "overlap_points": relationship_model["overlap_points"],
            "target_slot": slot,
            "dimension": SCHEMA_SLOT_DIMENSIONS.get(slot, "核心功能"),
            "query": query,
            "query_locale": _query_locale_for_competitor(comp, product_type),
            "preferred_source_types": _preferred_source_types(
                product_type, competitor_type, slot
            ),
            "avoid_source_types": ["unknown"],
            "priority": "high",
            "limit": 4,
            "success_criteria": _success_criteria(slot, relationship_model),
        }
        product_map.setdefault(comp["id"], {"competitor": comp, "queries": []})
        product_map[comp["id"]]["queries"].append(quart)
    for comp in competitors:
        if comp["id"] not in product_map:
            product_map[comp["id"]] = {"competitor": comp, "queries": []}
    return list(product_map.values())


def _plan_retrieval_quarts(
    competitors: list[dict],
    requirement: dict,
    evidence: list[dict] | None = None,
    sources: list[dict] | None = None,
) -> list[dict]:
    quarts = []
    evidence = evidence or []
    sources = sources or []
    product_type = _detect_product_type(requirement)
    focus_items = _focus_items(requirement)
    for competitor in competitors:
        competitor_type = competitor.get("category") or "direct_competitor"
        relationship_model = _build_relationship_model(competitor, requirement)
        covered_slots = _covered_schema_slots(competitor, evidence, sources)
        candidate_slots = [
            slot
            for slot in _priority_slots_for_competitor_type(competitor_type)
            if slot not in covered_slots
        ]
        if len(candidate_slots) < 5:
            for slot in ["market_signal", "risk_opportunity"]:
                if slot not in covered_slots and slot not in candidate_slots:
                    candidate_slots.append(slot)
        for slot in candidate_slots:
            quarts.append(
                _build_retrieval_quart(
                    competitor, product_type, competitor_type, slot, relationship_model
                )
            )
        for focus in focus_items:
            quarts.append(
                _build_focus_quart(
                    competitor, product_type, competitor_type, focus, relationship_model
                )
            )
    return quarts


def _detect_product_type(requirement: dict) -> str:
    return "commodity" if _is_commodity_domain(requirement) else "software"


def _priority_slots_for_competitor_type(competitor_type: str) -> list[str]:
    if competitor_type == "substitute_solution":
        return [
            "relationship_evidence",
            "positioning",
            "user_feedback",
            "risk_opportunity",
            "pricing",
            "core_features",
        ]
    if competitor_type == "indirect_competitor":
        return [
            "relationship_evidence",
            "positioning",
            "core_features",
            "user_feedback",
            "pricing",
            "market_signal",
        ]
    if competitor_type == "adjacent_product":
        return [
            "relationship_evidence",
            "positioning",
            "core_features",
            "market_signal",
            "risk_opportunity",
            "pricing",
        ]
    return [
        "relationship_evidence",
        "positioning",
        "core_features",
        "pricing",
        "user_feedback",
        "market_signal",
    ]


def _covered_schema_slots(
    competitor: dict, evidence: list[dict], sources: list[dict]
) -> set[str]:
    source_by_id = {
        source.get("reference_id"): source
        for source in sources
        if source.get("reference_id")
    }
    covered = set()
    for item in evidence:
        if item.get("competitor_id") and item.get("competitor_id") != competitor.get(
            "id"
        ):
            continue
        if item.get("related_product") and item.get(
            "related_product"
        ) != competitor.get("name"):
            continue
        if float(item.get("confidence") or 0) < 0.75:
            continue
        dimension = item.get("related_dimension")
        slot = _slot_for_dimension(dimension)
        if slot == "pricing":
            source = source_by_id.get(item.get("reference_id"), {})
            if source and source.get("source_type") not in {
                "official_pricing_page",
                "ecommerce_product_page",
                "marketplace_listing_unknown_seller",
            }:
                continue
        if slot:
            covered.add(slot)
    return covered


def _slot_for_dimension(dimension: object) -> str | None:
    for slot, mapped_dimension in SCHEMA_SLOT_DIMENSIONS.items():
        if dimension == mapped_dimension:
            return slot
    return None


def _build_relationship_model(competitor: dict, requirement: dict) -> dict:
    target_name = str(
        requirement.get("name")
        or requirement.get("target_product")
        or requirement.get("domain")
        or "目标产品"
    )
    category = str(
        requirement.get("category")
        or requirement.get("possible_market_category")
        or requirement.get("domain")
        or "目标市场"
    )
    capabilities = _string_list(requirement.get("core_capabilities"))[:3]
    use_cases = _string_list(requirement.get("primary_use_cases"))[:3]
    overlap_points = _string_list(
        competitor.get("overlap_points")
    ) or _extract_overlap_points(competitor.get("description"), capabilities, use_cases)
    competed_need = str(
        competitor.get("competed_need")
        or _infer_competed_need(
            competitor.get("category"), category, use_cases, capabilities
        )
    )
    competitor_type = str(competitor.get("category") or "direct_competitor")
    relation_claim = str(
        competitor.get("relation_claim")
        or _relation_claim_for_type(
            competitor["name"],
            target_name,
            competitor_type,
            competed_need,
            overlap_points,
        )
    )
    return {
        "target_name": target_name,
        "category": category,
        "relation_claim": relation_claim,
        "competed_need": competed_need,
        "overlap_points": overlap_points,
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _extract_overlap_points(
    description: object, capabilities: list[str], use_cases: list[str]
) -> list[str]:
    description_text = str(description or "")
    candidates = capabilities + use_cases
    matched = [item for item in candidates if item and item in description_text]
    if matched:
        return matched[:4]
    if candidates:
        return candidates[:3]
    return ["目标用户", "使用场景", "核心任务"]


def _infer_competed_need(
    competitor_type: object,
    category: str,
    use_cases: list[str],
    capabilities: list[str],
) -> str:
    if competitor_type == "substitute_solution":
        return use_cases[0] if use_cases else f"{category}的替代完成路径"
    if competitor_type == "indirect_competitor":
        return use_cases[0] if use_cases else f"{category}中的相似任务"
    return category


def _relation_claim_for_type(
    name: str,
    target_name: str,
    competitor_type: str,
    competed_need: str,
    overlap_points: list[str],
) -> str:
    overlap_text = "、".join(overlap_points[:3]) if overlap_points else "核心使用场景"
    if competitor_type == "substitute_solution":
        return f"{name} 不是同类产品，但可能作为用户完成“{competed_need}”的替代路径，与 {target_name} 在{overlap_text}上形成替代关系。"
    if competitor_type == "indirect_competitor":
        return f"{name} 与 {target_name} 产品形态不完全相同，但都服务“{competed_need}”，在{overlap_text}场景中构成间接竞争。"
    return f"{name} 与 {target_name} 面向相近用户和“{competed_need}”需求，在{overlap_text}上构成直接竞争。"


def _build_retrieval_quart(
    competitor: dict,
    product_type: str,
    competitor_type: str,
    slot: str,
    relationship_model: dict,
) -> dict:
    name = competitor["name"]
    query_locale = _query_locale_for_competitor(competitor, product_type)
    query = _quart_query(
        name, product_type, competitor_type, slot, query_locale, relationship_model
    )
    preferred_source_types = _preferred_source_types(
        product_type, competitor_type, slot
    )
    return {
        "competitor_id": competitor["id"],
        "competitor_name": name,
        "product_type": product_type,
        "competitor_type": competitor_type,
        "relation_claim": relationship_model["relation_claim"],
        "competed_need": relationship_model["competed_need"],
        "overlap_points": relationship_model["overlap_points"],
        "target_slot": slot,
        "dimension": SCHEMA_SLOT_DIMENSIONS[slot],
        "query": query,
        "query_locale": query_locale,
        "preferred_source_types": preferred_source_types,
        "avoid_source_types": ["unknown"],
        "priority": "high"
        if slot == "relationship_evidence" or slot in CORE_SCHEMA_SLOTS
        else "medium",
        "limit": 4,
        "success_criteria": _success_criteria(slot, relationship_model),
    }


def _build_focus_quart(
    competitor: dict,
    product_type: str,
    competitor_type: str,
    focus: dict,
    relationship_model: dict,
) -> dict:
    name = competitor["name"]
    query_locale = _query_locale_for_competitor(competitor, product_type)
    query = _focus_query(name, focus, query_locale)
    support_slot = _slot_for_focus(focus)
    return {
        "competitor_id": competitor["id"],
        "competitor_name": name,
        "product_type": product_type,
        "competitor_type": competitor_type,
        "relation_claim": relationship_model["relation_claim"],
        "competed_need": relationship_model["competed_need"],
        "overlap_points": relationship_model["overlap_points"],
        "target_slot": f"focus:{focus.get('key', 'custom')}",
        "dimension": f"个性化关注点：{focus.get('label', '用户关注点')}",
        "query": query,
        "query_locale": query_locale,
        "preferred_source_types": _preferred_source_types(
            product_type, competitor_type, support_slot
        ),
        "avoid_source_types": ["unknown"],
        "priority": focus.get("priority") or "high",
        "limit": 4,
        "success_criteria": focus.get("evidence_expectation")
        or f"找到可回答“{focus.get('label', '用户关注点')}”的公开证据。",
        "focus_label": focus.get("label"),
    }


def _focus_items(requirement: dict) -> list[dict]:
    profile = (
        requirement.get("focus_profile")
        if isinstance(requirement.get("focus_profile"), dict)
        else {}
    )
    if not isinstance(profile, dict):
        return []
    items = []
    for focus in (profile.get("explicit_focuses") or []) + (
        profile.get("inferred_focuses") or []
    ):
        if isinstance(focus, dict) and focus.get("label"):
            items.append(focus)
    return items[:4]


def _focus_query(name: str, focus: dict, query_locale: str) -> str:
    terms = (
        focus.get("query_terms") if isinstance(focus.get("query_terms"), list) else []
    )
    label = str(focus.get("label") or "用户关注点")
    term_text = " ".join(str(term) for term in terms[:3]) if terms else label
    if query_locale == "china":
        return f"{name} {term_text} 官方 文档 评价"
    return f"{name} {term_text} official docs reviews"


def _slot_for_focus(focus: dict) -> str:
    text = f"{focus.get('key', '')} {focus.get('label', '')}".lower()
    if any(token in text for token in ["price", "pricing", "价格", "收费", "套餐"]):
        return "pricing"
    if any(
        token in text for token in ["review", "pain", "评价", "痛点", "迁移", "成本"]
    ):
        return "user_feedback"
    return "core_features"


def _query_locale_for_competitor(competitor: dict, product_type: str) -> str:
    if product_type == "commodity":
        return "china"
    region = competitor.get("region")
    if region in {"global", "china"}:
        return region
    return "china" if _contains_chinese(str(competitor.get("name", ""))) else "global"


def _contains_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _quart_query(
    name: str,
    product_type: str,
    competitor_type: str,
    slot: str,
    query_locale: str,
    relationship_model: dict,
) -> str:
    target_name = relationship_model["target_name"]
    competed_need = relationship_model["competed_need"]
    overlap_text = " ".join(relationship_model["overlap_points"][:2])
    if product_type == "commodity":
        if slot == "relationship_evidence":
            if competitor_type == "substitute_solution":
                return f"{competed_need} 传统方案 替代方案 用户经验"
            if competitor_type == "indirect_competitor":
                return f"{competed_need} 替代产品 推荐 测评 {name}"
            return f"{target_name} {name} 对比 测评 参数 价格"
        templates = _commodity_templates_for_type(competitor_type)
        return templates[slot].format(
            product=name, target=target_name, need=competed_need, overlap=overlap_text
        )

    software_templates = {
        "global": {
            "relationship_evidence": _software_relationship_query(
                name,
                target_name,
                competed_need,
                overlap_text,
                competitor_type,
                "global",
            ),
            "positioning": "{product} official website product positioning features",
            "core_features": "{product} docs help features integrations API",
            "pricing": "{product} pricing plans enterprise",
            "user_feedback": "{product} reviews pros cons G2 Capterra Reddit",
            "market_signal": "{product} news launch funding product update",
            "risk_opportunity": "{product} limitations alternatives risks switching cost",
        },
        "china": {
            "relationship_evidence": _software_relationship_query(
                name, target_name, competed_need, overlap_text, competitor_type, "china"
            ),
            "positioning": "{product} 官网 产品介绍 功能 目标用户",
            "core_features": "{product} 帮助中心 文档 功能 集成 开放平台",
            "pricing": "{product} 价格 收费 套餐 企业版",
            "user_feedback": "{product} 用户评价 知乎 小红书 差评 替代品",
            "market_signal": "{product} 新闻 发布 版本更新 融资",
            "risk_opportunity": "{product} 缺点 问题 替代品 迁移成本",
        },
    }
    locale = "china" if query_locale == "china" else "global"
    return software_templates[locale][slot].format(product=name)


def _software_relationship_query(
    name: str,
    target_name: str,
    competed_need: str,
    overlap_text: str,
    competitor_type: str,
    locale: str,
) -> str:
    if locale == "china":
        if competitor_type == "substitute_solution":
            return f"{competed_need} 人工流程 表格 PPT 替代方案"
        if competitor_type == "indirect_competitor":
            return f"{name} {competed_need} 场景 团队 协作 {overlap_text}".strip()
        return f"{target_name} 和 {name} 对比 替代 竞品 {competed_need}"
    if competitor_type == "substitute_solution":
        return f"{competed_need} manual workflow spreadsheet PPT alternative"
    if competitor_type == "indirect_competitor":
        return f"{name} {competed_need} use cases team workflow {overlap_text}".strip()
    return f"{target_name} vs {name} features pricing reviews alternative"


def _commodity_templates_for_type(competitor_type: str) -> dict[str, str]:
    if competitor_type == "substitute_solution":
        return {
            "positioning": "{need} 传统方案 替代方案",
            "core_features": "{need} 低成本方案 使用体验",
            "pricing": "{need} 成本 价格 购买渠道",
            "user_feedback": "{need} 用户经验 小红书 知乎 差评",
            "market_signal": "{need} 推荐 榜单 测评",
            "risk_opportunity": "{need} 缺点 问题 值不值得",
        }
    if competitor_type == "indirect_competitor":
        return {
            "positioning": "{product} 使用场景 适合人群 对比",
            "core_features": "{product} 功能 参数 测评 使用体验",
            "pricing": "{product} 京东 天猫 淘宝 价格",
            "user_feedback": "{product} 用户评价 小红书 知乎 B站 差评",
            "market_signal": "{product} 推荐 榜单 测评 对比",
            "risk_opportunity": "{product} 缺点 问题 替代品 值不值得买",
        }
    return {
        "positioning": "{product} 品牌 官网 商品介绍 参数",
        "core_features": "{product} 功能 参数 测评 使用体验",
        "pricing": "{product} 京东 天猫 淘宝 价格",
        "user_feedback": "{product} 用户评价 小红书 知乎 B站 京东 差评",
        "market_signal": "{product} 测评 对比 推荐 榜单",
        "risk_opportunity": "{product} 缺点 问题 替代品 值不值得买",
    }


def _preferred_source_types(
    product_type: str, competitor_type: str, slot: str
) -> list[str]:
    if slot == "relationship_evidence":
        if competitor_type == "substitute_solution":
            return [
                "community_discussion",
                "social_review_post",
                "professional_review",
                "news_article",
            ]
        if competitor_type == "indirect_competitor":
            return [
                "official_site",
                "official_docs",
                "professional_review",
                "community_discussion",
                "news_article",
            ]
        return [
            "official_site",
            "review_site",
            "professional_review",
            "community_discussion",
            "news_article",
        ]
    _commodity_slot_map = {
        "positioning": ["brand_official_product_page", "ecommerce_product_page"],
        "core_features": [
            "brand_official_product_page",
            "professional_review",
            "ecommerce_product_page",
        ],
        "pricing": ["ecommerce_product_page", "marketplace_listing_unknown_seller"],
        "user_feedback": [
            "ecommerce_user_review",
            "social_review_post",
            "community_discussion",
        ],
        "market_signal": ["professional_review", "news_article"],
        "risk_opportunity": [
            "ecommerce_user_review",
            "social_review_post",
            "community_discussion",
            "professional_review",
        ],
    }
    if product_type == "commodity":
        return _commodity_slot_map.get(slot, ["official_site", "professional_review"])
    _software_slot_map = {
        "positioning": ["official_site", "news_article"],
        "core_features": ["official_docs", "official_site"],
        "pricing": ["official_pricing_page"],
        "user_feedback": ["review_site", "community_discussion", "social_review_post"],
        "market_signal": ["news_article", "official_site"],
        "risk_opportunity": ["review_site", "community_discussion", "news_article"],
    }
    return _software_slot_map.get(slot, ["official_site", "professional_review"])


def _success_criteria(slot: str, relationship_model: dict) -> str:
    if slot == "relationship_evidence":
        return (
            f"找到可支撑“{relationship_model['relation_claim']}”的公开来源，"
            f"并明确体现竞争需求“{relationship_model['competed_need']}”或至少 1 个重叠点。"
        )
    return f"找到可支撑“{SLOT_LABELS[slot]}”的公开来源，并抽取至少 1 条 evidence。"


def _evidence_summary(query_item: dict, snippet: str) -> str:
    if query_item.get("target_slot") == "relationship_evidence":
        return (
            f"关系假设：{query_item.get('relation_claim')} "
            f"竞争需求：{query_item.get('competed_need')}。证据摘要：{snippet}"
        )
    if str(query_item.get("target_slot", "")).startswith("focus:"):
        return f"用户关注点“{query_item.get('focus_label') or query_item.get('dimension')}”：{snippet}"
    return snippet


def _classify_and_rank_results(
    results: list, requirement: dict, query_item: dict
) -> list[dict]:
    classified = []
    for result in results:
        source_type, credibility_score, reason = _classify_source(
            result.url,
            result.title,
            result.snippet,
            requirement,
            query_item.get("dimension", ""),
        )
        dimension_bonus = (
            0.08
            if source_type
            in DIMENSION_SOURCE_BONUS.get(query_item.get("dimension", ""), set())
            else 0
        )
        preferred_bonus = (
            0.06
            if source_type in set(query_item.get("preferred_source_types", []))
            else 0
        )
        relationship_bonus = _relationship_match_bonus(result, query_item)
        rank_score = min(
            1.0,
            credibility_score + dimension_bonus + preferred_bonus + relationship_bonus,
        )
        classified.append(
            {
                "result": result,
                "source_type": source_type,
                "label": SOURCE_TYPE_LABELS[source_type],
                "credibility_score": credibility_score,
                "rank_score": rank_score,
                "reason": reason,
            }
        )
    return sorted(classified, key=lambda item: item["rank_score"], reverse=True)


def _relationship_match_bonus(result: object, query_item: dict) -> float:
    if query_item.get("target_slot") != "relationship_evidence":
        return 0
    haystack = f"{getattr(result, 'title', '')} {getattr(result, 'snippet', '')} {getattr(result, 'raw_content', '')}".lower()
    needles = [
        str(query_item.get("competed_need") or "").lower(),
        str(query_item.get("competitor_name") or "").lower(),
        " vs ",
        "对比",
        "替代",
        "alternative",
        "competitor",
        "workflow",
        "场景",
    ]
    needles.extend(
        str(item).lower() for item in query_item.get("overlap_points", []) if item
    )
    matches = sum(1 for needle in needles if needle and needle in haystack)
    return min(0.1, matches * 0.025)


def _classify_source(
    url: str, title: str, snippet: str, requirement: dict, dimension: str
) -> tuple[str, float, str]:
    lowered = f"{url} {title} {snippet}".lower()
    domain = urlparse(url).netloc.lower()
    source_type = (
        _classify_commodity_source(domain, lowered)
        if _is_commodity_domain(requirement)
        else _classify_saas_source(domain, lowered)
    )
    if source_type == "unknown":
        source_type = _classify_common_source(domain, lowered)
    reason = f"按领域、域名、标题关键词和“{dimension}”维度匹配为{SOURCE_TYPE_LABELS[source_type]}。"
    return source_type, SOURCE_WEIGHTS[source_type], reason


def _classify_commodity_source(domain: str, lowered: str) -> str:
    if any(
        item in domain
        for item in [
            "jd.com",
            "jingdong",
            "tmall.com",
            "taobao.com",
            "suning.com",
            "pinduoduo.com",
        ]
    ):
        if any(
            item in lowered
            for item in ["评价", "评论", "review", "口碑", "差评", "晒单"]
        ):
            return "ecommerce_user_review"
        return "ecommerce_product_page"
    if any(
        item in domain
        for item in [
            "xiaohongshu.com",
            "douyin.com",
            "weibo.com",
            "bilibili.com",
            "youtube.com",
            "instagram.com",
        ]
    ):
        return "social_review_post"
    if any(
        item in domain
        for item in [
            "zhihu.com",
            "reddit.com",
            "douban.com",
            "chiphell.com",
            "smzdm.com",
        ]
    ):
        return "community_discussion"
    if any(item in lowered for item in ["测评", "评测", "review", "体验", "开箱"]):
        return "professional_review"
    return "unknown"


def _classify_saas_source(domain: str, lowered: str) -> str:
    if any(
        item in domain
        for item in ["g2.com", "capterra.com", "producthunt.com", "trustradius.com"]
    ):
        return "review_site"
    if any(
        item in domain
        for item in ["reddit.com", "zhihu.com", "v2ex.com", "news.ycombinator.com"]
    ):
        return "community_discussion"
    if any(
        item in domain
        for item in ["x.com", "twitter.com", "linkedin.com", "youtube.com"]
    ):
        return "social_review_post"
    if _looks_official_domain(domain):
        if any(
            item in lowered for item in ["pricing", "price", "plans", "定价", "价格"]
        ):
            return "official_pricing_page"
        if any(
            item in lowered
            for item in ["docs", "help", "support", "developer", "文档", "帮助中心"]
        ):
            return "official_docs"
        return "official_site"
    return "unknown"


def _classify_common_source(domain: str, lowered: str) -> str:
    if any(item in lowered for item in ["news", "techcrunch", "36kr", "媒体", "报道"]):
        return "news_article"
    if any(item in domain for item in ["amazon.", "ebay.", "rakuten.", "aliexpress."]):
        return "marketplace_listing_unknown_seller"
    return "unknown"


def _is_commodity_domain(requirement: dict) -> bool:
    text = f"{requirement.get('domain', '')} {requirement.get('summary', '')} {requirement.get('query', '')}".lower()
    return any(marker.lower() in text for marker in COMMODITY_MARKERS)


def _looks_official_domain(domain: str) -> bool:
    if not domain:
        return False
    noise_domains = [
        "google.com",
        "bing.com",
        "duckduckgo.com",
        "wikipedia.org",
        "reddit.com",
        "youtube.com",
        "xiaohongshu.com",
        "taobao.com",
        "tmall.com",
        "jd.com",
        "facebook.com",
        "twitter.com",
        "x.com",
        "linkedin.com",
        "instagram.com",
        "medium.com",
        "substack.com",
        "wordpress.com",
        "blogspot.com",
        "weibo.com",
        "zhihu.com",
        "douban.com",
        "bilibili.com",
        "douyin.com",
        "tiktok.com",
        "pinterest.com",
        "quora.com",
        "news.ycombinator.com",
        "v2ex.com",
        "amazon.com",
        "ebay.com",
        "aliexpress.com",
        "pinduoduo.com",
        "suning.com",
        "g2.com",
        "capterra.com",
        "producthunt.com",
        "trustradius.com",
        "smzdm.com",
        "chiphell.com",
        "36kr.com",
        "techcrunch.com",
        "github.com",
        "gitlab.com",
        "stackoverflow.com",
        "relay.app",
        "zapier.com",
        "ifttt.com",
        "pragmaticinstitute.com",
        "hubspot.com",
        "mindtheproduct.com",
        "kaizen.com",
        "checkthat.ai",
        "relevanceai.com",
    ]
    return not any(item in domain for item in noise_domains)


def _metadata_json(
    credibility_score: float,
    rank_score: float,
    source_type: str,
    source_label: str,
    classification_reason: str,
    query_item: dict,
    collection_iteration: int = 0,
) -> str:
    import json

    return json.dumps(
        {
            "credibility_score": credibility_score,
            "rank_score": rank_score,
            "source_type_label": source_label,
            "collection_iteration": collection_iteration,
            "query": query_item.get("query", ""),
            "dimension": query_item.get("dimension", ""),
            "target_slot": query_item.get("target_slot"),
            "product_type": query_item.get("product_type"),
            "competitor_type": query_item.get("competitor_type"),
            "relation_claim": query_item.get("relation_claim"),
            "competed_need": query_item.get("competed_need"),
            "overlap_points": query_item.get("overlap_points"),
            "focus_label": query_item.get("focus_label"),
            "query_locale": query_item.get("query_locale"),
            "success_criteria": query_item.get("success_criteria"),
            "classification_reason": classification_reason,
            "rerank_reason": "召回后按来源类型基础权重与维度匹配加权重排序，优先保留更适合当前分析维度的来源。",
        },
        ensure_ascii=False,
    )


def _count_source_types(sources: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source in sources:
        source_type = source.get("source_type", "unknown")
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts


def _build_coverage_report(competitors: list[dict], evidence: list[dict]) -> dict:
    products = []
    warnings = []
    for competitor in competitors:
        product_evidence = [
            item for item in evidence if item["competitor_id"] == competitor["id"]
        ]
        dimension_coverage = {}
        for dimension in ANALYSIS_DIMENSIONS:
            count = len(
                [
                    item
                    for item in product_evidence
                    if item["related_dimension"] == dimension
                ]
            )
            if count >= 2:
                dimension_coverage[dimension] = "sufficient"
            elif count == 1:
                dimension_coverage[dimension] = "weak"
                warnings.append(f"{competitor['name']} 的{dimension}资料较少。")
            else:
                dimension_coverage[dimension] = "missing"
                warnings.append(f"{competitor['name']} 缺少{dimension}资料。")
        products.append(
            {
                "product": competitor["name"],
                "dimension_coverage": dimension_coverage,
                "evidence_count": len(product_evidence),
            }
        )
    overall_status = "sufficient" if not warnings else "partial"
    return {
        "products": products,
        "overall_status": overall_status,
        "warnings": warnings,
    }
