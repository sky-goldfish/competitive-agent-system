import re
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider
from app.providers.search.base import SearchProvider


BLOCKED_SOURCE_DOMAINS = {
    "reddit.com",
    "www.reddit.com",
    "linkedin.com",
    "www.linkedin.com",
    "youtube.com",
    "www.youtube.com",
}
CONTENT_HINTS = [
    "alternative",
    "alternatives",
    "competitor",
    "competitors",
    "best",
    "review",
    "blog",
    "vs",
]
INVALID_COMPETITOR_NAMES = {
    "gie",
    "outscraper",
    "通用",
    "視点",
    "products",
    "the",
    "epd",
    "industrial",
    "similarweb",
    "and",
    "or",
    "of",
    "for",
    "with",
    "around",
    "围绕",
    "同类产品",
    "的同类产品",
    "亿元",
    "万元",
    "百万",
    "千万",
    "十亿",
    "美元",
    "人民币",
    "市场规模",
    "行业",
    "全球",
    "中国",
    "国内",
    "海外",
    "市场",
    "赛道",
    "趋势",
    "增长",
    "年的",
    "我想做",
    "我要做",
    "想做",
    "要做",
    "同类产品榜单",
    "与竞品对比",
    "竞品对比",
}
GENERIC_CANDIDATE_TERMS = {
    "竞品",
    "竞争",
    "对手",
    "替代",
    "方案",
    "分析",
    "报告",
    "用户",
    "需求",
    "功能",
    "场景",
    "同类",
    "主要",
    "工具",
    "图表",
    "构筑",
    "护城",
    "纷纷",
    "入局",
    "领域",
    "机会",
    "是否",
    "此外",
    "其中",
    "以及",
    "但是",
    "因此",
    "所以",
    "目前",
    "可以",
    "通过",
    "年的",
    "全球",
    "市场",
    "行业",
    "方面",
    "这些",
    "一个",
    "这个",
    "那个",
    "如何",
    "什么",
    "围绕",
    "同类产品",
    "的同类产品",
    "我想做",
    "我要做",
    "想做",
    "要做",
    "同类产品榜单",
    "与竞品对比",
    "竞品对比",
    "alternatives",
    "alternative",
    "competitors",
    "competitor",
    "review",
    "reviews",
    "pricing",
    "product",
    "products",
    "top",
    "best",
    "and",
    "or",
    "of",
    "for",
    "with",
}
CHINESE_STOPWORDS = {
    "的",
    "了",
    "在",
    "是",
    "我",
    "有",
    "和",
    "就",
    "不",
    "人",
    "都",
    "一",
    "个",
    "上",
    "也",
    "很",
    "到",
    "说",
    "要",
    "去",
    "你",
    "会",
    "着",
    "没有",
    "看",
    "好",
    "自己",
    "这",
    "他",
    "她",
    "它",
    "吗",
    "把",
    "那",
    "里",
    "让",
    "给",
    "此外",
    "其中",
    "以及",
    "但是",
    "因此",
    "所以",
    "目前",
    "可以",
    "通过",
    "如何",
    "什么",
    "这些",
    "那些",
    "年的",
}
KNOWN_PRODUCT_ALIASES = {
    "微信": "微信",
    "wechat": "微信",
    "qq": "QQ",
    "soul": "Soul",
    "tim": "TIM",
    "icq": "ICQ",
    "抖音": "抖音",
    "douyin": "抖音",
    "小红书": "小红书",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "line": "LINE",
    "支付宝": "支付宝",
    "alipay": "支付宝",
}
OFFICIAL_DOMAIN_HINTS = {
    "钉钉": ["dingtalk.com"],
    "企业微信": ["work.weixin.qq.com"],
    "wecom": ["work.weixin.qq.com"],
    "slack": ["slack.com"],
    "microsoft teams": ["microsoft.com", "teams.microsoft.com"],
    "google workspace": ["workspace.google.com", "google.com"],
    "notion": ["notion.so", "notion.com"],
    "coda ai": ["coda.io"],
    "confluence ai": ["atlassian.com"],
    "clickup ai": ["clickup.com"],
    "mem": ["mem.ai"],
    "guru": ["getguru.com"],
    "perplexity": ["perplexity.ai"],
    "chatgpt deep research": ["openai.com", "chatgpt.com"],
    "similarweb": ["similarweb.com"],
    "crayon": ["crayon.co"],
    "kompyte": ["kompyte.com", "semrush.com"],
    "klue": ["klue.com"],
    "ember mug": ["ember.com"],
    "fellow carter": ["fellowproducts.com"],
    "小米智能保温杯": ["mi.com", "xiaomi"],
    "vanow 智能保温杯": ["vanow"],
}
BLOCKED_PRODUCT_DOMAINS = {
    "钉钉": ["zh-dingdingtalk.com.cn", "e-dingding.com.cn", "dingtaikk.com"],
    "mem": ["mems25.org"],
    "crayon": ["lois.co.jp", "crayola", "wikipedia.org"],
    "ember mug": ["instagram.com", "youtube.com", "facebook.com", "rakuten.co.jp"],
    "chatgpt deep research": ["wikipedia.org"],
    "perplexity": ["wikipedia.org"],
}
CONFIDENCE_THRESHOLD = 0.85
MIN_CANDIDATES = 3
MAX_CANDIDATES = 12


ProgressCallback = Callable[[str, str, dict[str, Any]], None]


def competitor_discovery_node(
    state: AgentState,
    llm: LLMProvider,
    search: SearchProvider,
    progress: ProgressCallback | None = None,
) -> AgentState:
    requirement = state["requirement"]
    t0 = datetime.utcnow()
    target_queries = _plan_target_queries(requirement)
    _emit(
        progress,
        "target_query_planning",
        "生成目标理解搜索 query",
        {
            "query_count": len(target_queries),
            "queries": [item["query"] for item in target_queries],
            "query_purposes": [item["purpose"] for item in target_queries],
        },
        start_time=t0,
    )

    t0 = datetime.utcnow()
    target_search_results = _run_queries(target_queries, search, limit=4)
    _emit(
        progress,
        "target_search",
        "搜索目标产品/想法相关资料",
        {
            "query_count": len(target_queries),
            "result_count": len(target_search_results),
        },
        start_time=t0,
    )

    t0 = datetime.utcnow()
    target_understanding = llm.understand_target(requirement, target_search_results)
    _emit(
        progress,
        "target_understanding",
        "归纳目标对象定位、用户和核心能力",
        {
            "target": target_understanding.get("name")
            or requirement.get("target_product"),
            "category": target_understanding.get("category")
            or requirement.get("domain"),
            "capability_count": len(target_understanding.get("core_capabilities", [])),
        },
        start_time=t0,
    )

    t0 = datetime.utcnow()
    competitor_queries = _plan_competitor_queries(requirement, target_understanding)
    _emit(
        progress,
        "competitor_query_planning",
        "基于目标画像生成竞品发现 query",
        {
            "query_count": len(competitor_queries),
            "queries": [item["query"] for item in competitor_queries],
            "query_purposes": [item["purpose"] for item in competitor_queries],
        },
        start_time=t0,
    )

    t0 = datetime.utcnow()
    search_results = _run_queries(competitor_queries, search, limit=5)
    _emit(
        progress,
        "competitor_search",
        "搜索候选竞品来源",
        {"query_count": len(competitor_queries), "result_count": len(search_results)},
        start_time=t0,
    )

    t0 = datetime.utcnow()
    competitors = llm.extract_competitors(
        requirement, target_understanding, search_results
    )
    _emit(
        progress,
        "candidate_extraction",
        "抽取候选竞品并解释推荐理由",
        {
            "candidate_count": len(competitors),
            "candidates": [item.get("name") for item in competitors[:6]],
        },
        start_time=t0,
    )

    seen_names = set()
    valid_candidates = []
    for item in competitors:
        name = str(item.get("name", "")).strip()
        if (
            not name
            or name.lower() in seen_names
            or name.lower() in INVALID_COMPETITOR_NAMES
            or _looks_generic_name(name)
        ):
            continue
        if _is_target_product(name, target_understanding, requirement):
            continue
        if not _is_domain_relevant_candidate(name, target_understanding, requirement):
            continue
        seen_names.add(name.lower())
        valid_candidates.append(item)
    filtered_candidates = _threshold_candidates(
        valid_candidates,
        threshold=CONFIDENCE_THRESHOLD,
        min_candidates=MIN_CANDIDATES,
        max_candidates=MAX_CANDIDATES,
    )

    t0 = datetime.utcnow()
    product_results: dict[str, dict | None] = {}
    with ThreadPoolExecutor(
        max_workers=min(4, max(1, len(filtered_candidates)))
    ) as executor:
        futures = {
            executor.submit(
                _resolve_product_result, item["name"], requirement, search
            ): item["name"]
            for item in filtered_candidates
        }
        try:
            for future in as_completed(futures, timeout=120):
                try:
                    product_results[futures[future]] = future.result()
                except Exception:
                    pass
        except TimeoutError:
            for f, name in futures.items():
                if name not in product_results:
                    product_results[name] = None
        except Exception:
            for f, name in futures.items():
                if name not in product_results:
                    product_results[name] = None
    _emit(
        progress,
        "official_site_resolution",
        "并行解析候选竞品官网",
        {"names": [c.get("name") for c in filtered_candidates]},
        start_time=t0,
    )

    normalized = []
    extra_search_results = []
    for item in filtered_candidates:
        name = str(item["name"]).strip()
        product_result = product_results.get(name)
        if product_result:
            extra_search_results.append(product_result)
        website = product_result.get("url") if product_result else item.get("website")
        evidence_snippet = (
            product_result.get("snippet") if product_result else item.get("description")
        )
        description_item = {**item}
        if website and not description_item.get("source_ids"):
            description_item["source_ids"] = [website]
        normalized.append(
            {
                "name": name[:80],
                "website": website,
                "description": _build_description(
                    name,
                    requirement,
                    target_understanding,
                    evidence_snippet,
                    description_item,
                ),
                "category": item.get("category") or "direct_competitor",
                "region": _normalize_region(item.get("region")),
                "confidence": float(item.get("confidence") or 0.7),
                "discovery_source": item.get("discovery_source")
                or f"{llm.name}+{search.name}",
            }
        )
    if not normalized:
        t0 = datetime.utcnow()
        fallback_competitors = _extract_fallback_competitors(
            requirement, target_understanding, search_results
        )
        _emit(
            progress,
            "candidate_fallback_extraction",
            "LLM 候选过滤后为空，基于搜索结果进行通用候选兜底",
            {
                "candidate_count": len(fallback_competitors),
                "candidates": [item.get("name") for item in fallback_competitors],
            },
            start_time=t0,
        )
        for item in fallback_competitors:
            name = str(item.get("name", "")).strip()
            if (
                not name
                or name.lower() in seen_names
                or name.lower() in INVALID_COMPETITOR_NAMES
                or _looks_generic_name(name)
            ):
                continue
            if _is_target_product(name, target_understanding, requirement):
                continue
            seen_names.add(name.lower())
            normalized.append(
                {
                    "name": name[:80],
                    "website": item.get("website"),
                    "description": _build_description(
                        name,
                        requirement,
                        target_understanding,
                        item.get("description"),
                        item,
                    ),
                    "category": item.get("category") or "direct_competitor",
                    "region": _normalize_region(item.get("region")),
                    "confidence": float(item.get("confidence") or 0.62),
                    "discovery_source": item.get("discovery_source")
                    or f"fallback+{search.name}",
                }
            )
            if len(normalized) >= MAX_CANDIDATES:
                break
    return {
        **state,
        "target_understanding": target_understanding,
        "target_search_results": target_search_results,
        "competitor_search_results": search_results,
        "competitors": normalized,
        "search_results": target_search_results + search_results + extra_search_results,
    }


def _emit(
    progress: ProgressCallback | None,
    stage: str,
    message: str,
    metadata: dict[str, Any],
    start_time: datetime | None = None,
) -> None:
    if progress is not None:
        if start_time is not None:
            # Pass additional timing info in metadata for progress callback to use
            metadata = {**metadata, "_start_time": start_time.isoformat()}
        progress(stage, message, metadata)


def _plan_target_queries(requirement: dict) -> list[dict]:
    focus_terms = _focus_query_terms(requirement)
    if (
        requirement.get("queries")
        and isinstance(requirement["queries"], list)
        and len(requirement["queries"]) >= 2
    ):
        queries = []
        for idx, q in enumerate(requirement["queries"][:3]):
            queries.append({"query": str(q)[:40], "purpose": f"hybrid_search_{idx}"})
        if focus_terms:
            queries.append(
                {
                    "query": f"{requirement.get('domain', '')} {focus_terms[0]}"[:40],
                    "purpose": "focus_target_understanding",
                }
            )
        return queries

    target_product = requirement.get("target_product")
    domain = requirement.get("possible_market_category") or requirement.get(
        "domain", ""
    )
    if target_product:
        return [
            {
                "query": f'"{target_product}" features pricing 2026',
                "purpose": "global_target_understanding",
            },
            {
                "query": f"{target_product} 官方 功能 定价 目标用户",
                "purpose": "local_target_understanding",
            },
            {
                "query": f"{target_product} 竞品 替代品 对比",
                "purpose": "initial_competitor_discovery",
            },
        ]
    description = (
        requirement.get("product_description") or requirement.get("summary") or domain
    )
    return [
        {
            "query": f'"{domain}" alternatives competitors 2026',
            "purpose": "global_solution_discovery",
        },
        {"query": f"{description} 相似产品 竞品", "purpose": "local_market_discovery"},
    ]


def _plan_competitor_queries(
    requirement: dict, target_understanding: dict
) -> list[dict]:
    name = (
        target_understanding.get("name")
        or requirement.get("target_product")
        or requirement.get("domain", "目标产品")
    )
    category = (
        target_understanding.get("competitor_search_category")
        or target_understanding.get("category")
        or requirement.get("domain", "")
    )
    capabilities = " ".join(target_understanding.get("core_capabilities", [])[:3])
    use_cases = " ".join(target_understanding.get("primary_use_cases", [])[:2])
    search_terms = [
        str(item).strip()
        for item in target_understanding.get("competitor_search_terms", [])
        if str(item).strip()
    ]
    queries = [
        {
            "query": f'"{category}" competitors alternatives 2026'[:90],
            "purpose": "positioning_global_competitor_discovery",
        },
        {
            "query": f"{category} 竞品 替代品 对比"[:90],
            "purpose": "positioning_local_competitor_discovery",
        },
        {
            "query": f"{category} 主要产品 品牌 排行"[:90],
            "purpose": "local_indirect_discovery",
        },
    ]
    for idx, term in enumerate(search_terms[:5]):
        queries.append(
            {"query": term[:90], "purpose": f"target_positioning_term_{idx}"}
        )
    if capabilities:
        queries.append(
            {
                "query": f"{category} {capabilities} tools competitors"[:90],
                "purpose": "capability_based_discovery",
            }
        )
    if use_cases:
        queries.append(
            {
                "query": f"{category} {use_cases} 竞品"[:90],
                "purpose": "use_case_based_discovery",
            }
        )
    queries.append(
        {
            "query": f'"{name}" alternatives competitors'[:90],
            "purpose": "target_name_cross_check",
        }
    )
    for idx, term in enumerate(_focus_query_terms(requirement)[:2]):
        queries.append(
            {
                "query": f"{category} {term} alternatives"[:90],
                "purpose": f"focus_competitor_discovery_{idx}",
            }
        )
    seen = set()
    deduped = []
    for item in queries:
        query = item["query"].strip()
        if not query or query.lower() in seen:
            continue
        seen.add(query.lower())
        deduped.append({**item, "query": query})
    return deduped[:10]


def _focus_query_terms(requirement: dict) -> list[str]:
    profile = (
        requirement.get("focus_profile")
        if isinstance(requirement.get("focus_profile"), dict)
        else {}
    )
    focuses = []
    if isinstance(profile, dict):
        focuses.extend(profile.get("explicit_focuses") or [])
        focuses.extend(profile.get("inferred_focuses") or [])
    terms = []
    for focus in focuses:
        if not isinstance(focus, dict):
            continue
        query_terms = (
            focus.get("query_terms")
            if isinstance(focus.get("query_terms"), list)
            else []
        )
        if query_terms:
            terms.append(str(query_terms[0]))
        elif focus.get("label"):
            terms.append(str(focus["label"]))
    return [term for term in terms if term.strip()]


def _run_queries(
    queries: list[dict], search: SearchProvider, *, limit: int
) -> list[dict]:
    def _search_one(query_item: dict) -> list[dict]:
        try:
            results = search.search(query_item["query"], limit=limit)
        except Exception:
            return []
        batch = []
        for rank, result in enumerate(results, start=1):
            serialized = _serialize_result(result, search.name)
            serialized["query"] = query_item["query"]
            serialized["purpose"] = query_item.get("purpose")
            serialized["rank"] = rank
            batch.append(serialized)
        return batch

    collected = []
    seen_urls: set[str] = set()
    with ThreadPoolExecutor(max_workers=min(4, len(queries))) as executor:
        futures = {executor.submit(_search_one, q): q for q in queries}
        try:
            for future in as_completed(futures, timeout=60):
                for item in future.result():
                    if item["url"] not in seen_urls:
                        seen_urls.add(item["url"])
                        collected.append(item)
        except (TimeoutError, Exception):
            for f in futures:
                if not f.done():
                    f.cancel()
    return collected


def _serialize_result(result, provider: str) -> dict:
    return {
        "title": result.title,
        "url": result.url,
        "snippet": result.snippet,
        "provider": provider,
        "source_type": result.source_type,
    }


def _resolve_product_result(
    name: str, requirement: dict, search: SearchProvider
) -> dict | None:
    query = f"{name} official site product"
    try:
        results = search.search(query, limit=5)
    except Exception:
        return None
    serialized = [_serialize_result(result, search.name) for result in results]
    filtered = [
        result for result in serialized if not _is_blocked_product_domain(name, result)
    ]
    has_official_hint = _has_official_domain_hint(name)
    for result in filtered:
        if _is_known_official_domain(name, result):
            return result
    if has_official_hint:
        return None
    for result in filtered:
        if _looks_like_product_page(name, result):
            return result
    relevant = [
        result for result in filtered if _is_candidate_result_relevant(name, result)
    ]
    return relevant[0] if relevant else None


def _extract_fallback_competitors(
    requirement: dict, target_understanding: dict, search_results: list[dict]
) -> list[dict]:
    target_name = str(
        target_understanding.get("name") or requirement.get("target_product") or ""
    )
    aliases = _target_aliases(target_name)
    counts: Counter[str] = Counter()
    evidence: dict[str, dict] = {}
    for result in search_results:
        text = f"{result.get('title', '')} {result.get('snippet', '')}"
        for name in _extract_known_product_names(text):
            if name.lower() in aliases:
                continue
            counts[name] += 3
            evidence.setdefault(name, result)
        for name in _extract_candidate_names_from_text(text):
            if name.lower() in aliases:
                continue
            counts[name] += 1
            evidence.setdefault(name, result)
    competitors = []
    for index, (name, count) in enumerate(counts.most_common(20)):
        if name.lower() in INVALID_COMPETITOR_NAMES or _looks_generic_name(name):
            continue
        result = evidence.get(name, {})
        competitors.append(
            {
                "name": name,
                "website": result.get("url"),
                "description": f"{name} 是从搜索结果标题或摘要中识别出的候选竞品线索。搜索证据摘要：{result.get('snippet', '')[:180]}",
                "category": "direct_competitor" if index < 2 else "indirect_competitor",
                "reason": f"搜索结果将 {name} 与 {target_name or '目标产品'} 放在同类、替代、竞品或相关使用场景中讨论。",
                "matched_dimensions": ["产品定位", "目标用户", "核心功能", "使用场景"],
                "source_ids": [result.get("url")] if result.get("url") else [],
                "confidence": min(
                    0.9, max(0.62, 0.68 + min(count, 6) * 0.04 - index * 0.01)
                ),
                "discovery_source": "search_result_fallback",
            }
        )
        if len(competitors) >= MAX_CANDIDATES:
            break
    return _threshold_candidates(
        competitors,
        threshold=CONFIDENCE_THRESHOLD,
        min_candidates=MIN_CANDIDATES,
        max_candidates=MAX_CANDIDATES,
    )


def _target_aliases(target_name: str) -> set[str]:
    lowered = target_name.lower().replace(" ", "")
    aliases = {lowered} if lowered else set()
    alias_map = {
        "qq": {"qq", "腾讯qq"},
        "腾讯qq": {"qq", "腾讯qq"},
        "微信": {"微信", "wechat", "weixin"},
        "wechat": {"微信", "wechat", "weixin"},
        "weixin": {"微信", "wechat", "weixin"},
        "飞书": {"飞书", "lark", "feishu"},
        "lark": {"飞书", "lark", "feishu"},
        "feishu": {"飞书", "lark", "feishu"},
        "钉钉": {"钉钉", "dingtalk"},
        "dingtalk": {"钉钉", "dingtalk"},
        "抖音": {"抖音", "douyin", "tiktok"},
        "douyin": {"抖音", "douyin", "tiktok"},
        "tiktok": {"抖音", "douyin", "tiktok"},
        "小红书": {"小红书", "xiaohongshu", "rednote"},
    }
    if lowered in alias_map:
        aliases.update(alias_map[lowered])
    aliases.add(target_name.lower())
    return aliases


def _extract_known_product_names(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for alias, canonical in KNOWN_PRODUCT_ALIASES.items():
        if alias in lowered and canonical not in found:
            found.append(canonical)
    return found


def _extract_candidate_names_from_text(text: str) -> list[str]:
    candidates = []
    brand_patterns = [
        r"([A-Z][a-z]+(?:[A-Z][a-z]+)+)",
        r"「([^」]{2,15})」",
    ]
    for pattern in brand_patterns:
        for match in re.findall(pattern, text):
            name = match.strip()
            if len(name) >= 2 and not _looks_generic_name(name):
                candidates.append(name)
    patterns = [
        r"\b[A-Z][A-Za-z0-9]*(?:[-\.][A-Za-z0-9]+)*\b",
        r"[\u4e00-\u9fa5]{2,6}(?:AI|会议|听见|纪要|助手|通|浏览器)?",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text):
            name = match.strip(" .,;:!?[]()（）【】《》\"'“”‘’")
            if len(name) < 2 or _looks_generic_name(name):
                continue
            candidates.append(name)
    return candidates


def _looks_generic_name(name: str) -> bool:
    lowered = name.lower().strip()
    stripped = lowered.replace(" ", "")
    if stripped in GENERIC_CANDIDATE_TERMS or stripped in CHINESE_STOPWORDS:
        return True
    if stripped.startswith(("我想", "我要", "想做", "要做")):
        return True
    if any(
        term in stripped
        for term in ["同类产品榜单", "竞品对比", "替代方案讨论", "用户需求"]
    ):
        return True
    if len(name) <= 1:
        return True
    cn_chars = [ch for ch in name if "一" <= ch <= "鿿"]
    en_chars = [ch for ch in name if ch.isascii() and ch.isalpha()]
    if cn_chars and len(cn_chars) > 10:
        return True
    sentence_markers = [
        "的",
        "了",
        "在",
        "是",
        "有",
        "和",
        "与",
        "或",
        "从",
        "将",
        "被",
        "等",
        "也",
        "都",
        "而",
        "但",
        "到",
        "为",
    ]
    marker_count = sum(1 for m in sentence_markers if m in name)
    if marker_count >= 2:
        return True
    generic_suffixes = [
        "行业",
        "市场",
        "赛道",
        "领域",
        "品类",
        "方面",
        "方向",
        "趋势",
        "规模",
        "分析",
        "报告",
    ]
    if any(name.endswith(s) for s in generic_suffixes):
        return True
    unit_patterns = ["亿", "万", "元", "美金", "美元", "人民币", "%", "年"]
    if cn_chars and any(p in name for p in unit_patterns) and not en_chars:
        return True
    return False


def _balanced_candidates(candidates: list[dict], *, limit: int) -> list[dict]:
    if len(candidates) <= limit:
        return candidates
    buckets = {
        "global": [
            item
            for item in candidates
            if _normalize_region(item.get("region")) == "global"
        ],
        "china": [
            item
            for item in candidates
            if _normalize_region(item.get("region")) == "china"
        ],
        "unknown": [
            item
            for item in candidates
            if _normalize_region(item.get("region")) not in {"global", "china"}
        ],
    }
    if not buckets["global"] or not buckets["china"]:
        return candidates[:limit]

    selected: list[dict] = []
    for region in ("global", "china"):
        selected.extend(buckets[region][: max(1, limit // 2)])

    selected_ids = {id(item) for item in selected}
    for item in candidates:
        if len(selected) >= limit:
            break
        if id(item) not in selected_ids:
            selected.append(item)
            selected_ids.add(id(item))
    return selected[:limit]


def _threshold_candidates(
    candidates: list[dict],
    *,
    threshold: float,
    min_candidates: int,
    max_candidates: int,
) -> list[dict]:
    scored = sorted(
        candidates, key=lambda item: _safe_candidate_confidence(item), reverse=True
    )
    selected = [
        item for item in scored if _safe_candidate_confidence(item) >= threshold
    ]
    if len(selected) < min_candidates:
        selected = scored[: min(min_candidates, len(scored))]
    return selected[:max_candidates]


def _safe_candidate_confidence(item: dict) -> float:
    try:
        value = float(item.get("confidence") or 0)
    except (TypeError, ValueError):
        return 0.0
    if value > 1:
        value = value / 100
    return max(0.0, min(value, 1.0))


def _normalize_region(value: object) -> str | None:
    region = str(value or "").strip().lower()
    return region if region in {"global", "china"} else None


def _is_domain_relevant_candidate(
    name: str, target_understanding: dict, requirement: dict
) -> bool:
    return True


def _is_target_product(
    name: str, target_understanding: dict, requirement: dict
) -> bool:
    candidate = name.lower().replace(" ", "")
    targets = [
        str(target_understanding.get("name") or ""),
        str(requirement.get("target_product") or ""),
    ]
    return any(
        target and candidate == target.lower().replace(" ", "") for target in targets
    )


def _has_official_domain_hint(name: str) -> bool:
    return name.lower() in OFFICIAL_DOMAIN_HINTS or name in OFFICIAL_DOMAIN_HINTS


def _is_blocked_product_domain(name: str, result: dict) -> bool:
    domain = urlparse(result.get("url") or "").netloc.lower()
    blocked = BLOCKED_PRODUCT_DOMAINS.get(name.lower()) or BLOCKED_PRODUCT_DOMAINS.get(
        name
    )
    return bool(blocked and any(item in domain for item in blocked))


def _is_known_official_domain(name: str, result: dict) -> bool:
    domain = urlparse(result.get("url") or "").netloc.lower()
    hints = OFFICIAL_DOMAIN_HINTS.get(name.lower()) or OFFICIAL_DOMAIN_HINTS.get(name)
    return bool(hints and any(hint in domain for hint in hints))


def _is_candidate_result_relevant(name: str, result: dict) -> bool:
    haystack = f"{result.get('title', '')} {result.get('snippet', '')} {result.get('url', '')}".lower()
    lowered = name.lower()
    return lowered.replace(".ai", "").replace(" ", "") in haystack.replace(
        ".ai", ""
    ).replace(" ", "")


def _looks_like_product_page(name: str, result: dict) -> bool:
    url = result.get("url") or ""
    title = (result.get("title") or "").lower()
    domain = urlparse(url).netloc.lower()
    if domain in BLOCKED_SOURCE_DOMAINS:
        return False
    if name.lower().replace(".ai", "") in domain.replace(".ai", ""):
        return True
    return name.lower() in title and not any(hint in title for hint in CONTENT_HINTS)


def _build_description(
    name: str,
    requirement: dict,
    target_understanding: dict,
    evidence_snippet: str | None,
    item: dict,
) -> str:
    domain = target_understanding.get("category") or requirement.get(
        "domain", "目标产品"
    )
    reason = (
        item.get("reason")
        or item.get("description")
        or f"{name} 是从真实搜索结果中识别出的候选竞品，和“{domain}”相关。"
    )
    matched = item.get("matched_dimensions") or []
    matched_text = f"匹配维度：{', '.join(matched)}。" if matched else ""
    source_ids = item.get("source_ids") or []
    source_text = f"推荐来源：{source_ids[0]}。" if source_ids else ""
    base = f"{reason} {matched_text}{source_text}".strip()
    if evidence_snippet and evidence_snippet not in base:
        return f"{base} 二次搜索证据：{evidence_snippet[:180]}"[:500]
    return str(base)[:500]
