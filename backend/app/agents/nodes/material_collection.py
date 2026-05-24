from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from app.agents.state import AgentState
from app.providers.search.base import SearchProvider

ProgressCallback = Callable[[str, str, dict[str, Any]], None]

ANALYSIS_DIMENSIONS = ["产品定位", "核心功能", "价格与商业模式", "用户评价与痛点"]
COMMODITY_MARKERS = ["保温杯", "水杯", "硬件", "商品", "消费品", "电商", "mug", "cup", "bottle"]

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
    "产品定位": {"brand_official_product_page", "official_site", "news_article", "professional_review"},
    "核心功能": {"brand_official_product_page", "official_site", "official_docs", "professional_review", "ecommerce_product_page"},
    "价格与商业模式": {"official_pricing_page", "ecommerce_product_page", "marketplace_listing_unknown_seller"},
    "用户评价与痛点": {"ecommerce_user_review", "review_site", "social_review_post", "community_discussion", "professional_review"},
}


def material_collection_node(state: AgentState, search: SearchProvider, progress: ProgressCallback | None = None) -> AgentState:
    product_queries = _plan_material_queries(state["selected_competitors"], state.get("requirement", {}))
    _emit(progress, "material_query_planning", "为已确认竞品按分析维度和来源类型生成资料采集 query", {"product_count": len(product_queries), "query_count": sum(len(item["queries"]) for item in product_queries), "source_weights": SOURCE_WEIGHTS})

    sources = []
    evidence = []
    seen_urls = set()
    for product_query in product_queries:
        competitor = product_query["competitor"]
        product_source_count = 0
        for query_item in product_query["queries"]:
            results = search.search(query_item["query"], limit=4)
            classified_results = _classify_and_rank_results(results, state.get("requirement", {}), query_item)
            for ranked_result in classified_results[:2]:
                result = ranked_result["result"]
                source_key = f"{competitor['id']}::{query_item['dimension']}::{result.url}"
                if source_key in seen_urls:
                    continue
                seen_urls.add(source_key)
                source_type = ranked_result["source_type"]
                credibility_score = ranked_result["credibility_score"]
                source = {
                    "competitor_id": competitor["id"],
                    "title": result.title,
                    "url": result.url,
                    "snippet": result.snippet,
                    "source_type": source_type,
                    "provider": search.name,
                    "raw_content": result.raw_content,
                    "metadata_json": _metadata_json(credibility_score, ranked_result["rank_score"], source_type, ranked_result["label"], ranked_result["reason"], query_item),
                }
                sources.append(source)
                product_source_count += 1
                evidence.append(
                    {
                        "competitor_id": competitor["id"],
                        "related_product": competitor["name"],
                        "related_dimension": query_item["dimension"],
                        "quote": (result.raw_content or result.snippet)[:800],
                        "summary": f"[{ranked_result['label']}｜权重 {credibility_score:.2f}] {result.snippet}",
                        "confidence": min(0.95, max(0.5, credibility_score - 0.04)),
                        "source_url": result.url,
                    }
                )
        _emit(progress, "source_search", "按来源类型召回并重排序候选网页", {"product": competitor["name"], "source_count": product_source_count})

    coverage_report = _build_coverage_report(state["selected_competitors"], evidence)
    _emit(progress, "source_classification", "完成来源分类、可信度评分和召回结果重排序", {"source_count": len(sources), "source_type_counts": _count_source_types(sources)})
    _emit(progress, "evidence_extraction", "从来源摘要和正文中抽取结构化证据", {"evidence_count": len(evidence)})
    _emit(progress, "coverage_checking", "检查资料维度覆盖度和信息缺口", {"overall_status": coverage_report["overall_status"], "warning_count": len(coverage_report["warnings"])})
    return {**state, "sources": sources, "evidence": evidence, "coverage_report": coverage_report}



def _emit(progress: ProgressCallback | None, stage: str, message: str, metadata: dict[str, Any]) -> None:
    if progress is not None:
        progress(stage, message, metadata)



def _plan_material_queries(competitors: list[dict], requirement: dict) -> list[dict]:
    planned = []
    for competitor in competitors:
        name = competitor["name"]
        is_commodity = _is_commodity_domain(requirement) or _is_commodity_domain({"domain": competitor.get("description", "")})
        queries = _plan_commodity_queries(name) if is_commodity else _plan_saas_queries(name)
        planned.append({"competitor": competitor, "queries": queries})
    return planned


def _plan_saas_queries(name: str) -> list[dict]:
    return [
        {"query": f"{name} official product positioning features", "dimension": "产品定位"},
        {"query": f"{name} docs features integrations platform", "dimension": "核心功能"},
        {"query": f"{name} pricing plans enterprise official", "dimension": "价格与商业模式"},
        {"query": f"{name} reviews user feedback pros cons G2 Capterra Reddit", "dimension": "用户评价与痛点"},
    ]


def _plan_commodity_queries(name: str) -> list[dict]:
    return [
        {"query": f"{name} 品牌 官网 商品介绍 参数", "dimension": "产品定位"},
        {"query": f"{name} 功能 参数 测评 使用体验", "dimension": "核心功能"},
        {"query": f"{name} 京东 天猫 淘宝 价格", "dimension": "价格与商业模式"},
        {"query": f"{name} 用户评价 小红书 知乎 B站 京东 差评", "dimension": "用户评价与痛点"},
    ]



def _classify_and_rank_results(results: list, requirement: dict, query_item: dict) -> list[dict]:
    classified = []
    for result in results:
        source_type, credibility_score, reason = _classify_source(result.url, result.title, result.snippet, requirement, query_item["dimension"])
        dimension_bonus = 0.08 if source_type in DIMENSION_SOURCE_BONUS.get(query_item["dimension"], set()) else 0
        rank_score = min(1.0, credibility_score + dimension_bonus)
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


def _classify_source(url: str, title: str, snippet: str, requirement: dict, dimension: str) -> tuple[str, float, str]:
    lowered = f"{url} {title} {snippet}".lower()
    domain = urlparse(url).netloc.lower()
    source_type = _classify_commodity_source(domain, lowered) if _is_commodity_domain(requirement) else _classify_saas_source(domain, lowered)
    if source_type == "unknown":
        source_type = _classify_common_source(domain, lowered)
    reason = f"按领域、域名、标题关键词和“{dimension}”维度匹配为{SOURCE_TYPE_LABELS[source_type]}。"
    return source_type, SOURCE_WEIGHTS[source_type], reason


def _classify_commodity_source(domain: str, lowered: str) -> str:
    if any(item in domain for item in ["jd.com", "jingdong", "tmall.com", "taobao.com", "suning.com", "pinduoduo.com"]):
        if any(item in lowered for item in ["评价", "评论", "review", "口碑", "差评", "晒单"]):
            return "ecommerce_user_review"
        return "ecommerce_product_page"
    if any(item in domain for item in ["xiaohongshu.com", "douyin.com", "weibo.com", "bilibili.com", "youtube.com", "instagram.com"]):
        return "social_review_post"
    if any(item in domain for item in ["zhihu.com", "reddit.com", "douban.com", "chiphell.com", "smzdm.com"]):
        return "community_discussion"
    if any(item in lowered for item in ["测评", "评测", "review", "体验", "开箱"]):
        return "professional_review"
    if _looks_official_domain(domain):
        return "brand_official_product_page"
    return "unknown"


def _classify_saas_source(domain: str, lowered: str) -> str:
    if any(item in lowered for item in ["pricing", "price", "plans", "定价", "价格"]):
        return "official_pricing_page" if _looks_official_domain(domain) else "review_site"
    if any(item in lowered for item in ["docs", "help", "support", "developer", "文档", "帮助中心"]):
        return "official_docs"
    if any(item in domain for item in ["g2.com", "capterra.com", "producthunt.com", "trustradius.com"]):
        return "review_site"
    if any(item in domain for item in ["reddit.com", "zhihu.com", "v2ex.com", "news.ycombinator.com"]):
        return "community_discussion"
    if any(item in domain for item in ["x.com", "twitter.com", "linkedin.com", "youtube.com"]):
        return "social_review_post"
    if _looks_official_domain(domain):
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
    blocked = ["google.com", "bing.com", "duckduckgo.com", "wikipedia.org", "reddit.com", "youtube.com", "xiaohongshu.com", "taobao.com", "tmall.com", "jd.com"]
    return bool(domain and not any(item in domain for item in blocked))


def _metadata_json(credibility_score: float, rank_score: float, source_type: str, source_label: str, classification_reason: str, query_item: dict) -> str:
    import json

    return json.dumps(
        {
            "credibility_score": credibility_score,
            "rank_score": rank_score,
            "source_type_label": source_label,
            "query": query_item["query"],
            "dimension": query_item["dimension"],
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
        product_evidence = [item for item in evidence if item["competitor_id"] == competitor["id"]]
        dimension_coverage = {}
        for dimension in ANALYSIS_DIMENSIONS:
            count = len([item for item in product_evidence if item["related_dimension"] == dimension])
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
    return {"products": products, "overall_status": overall_status, "warnings": warnings}
