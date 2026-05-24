import re
from collections import Counter
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider
from app.providers.search.base import SearchProvider


BLOCKED_SOURCE_DOMAINS = {"reddit.com", "www.reddit.com", "linkedin.com", "www.linkedin.com", "youtube.com", "www.youtube.com"}
CONTENT_HINTS = ["alternative", "alternatives", "competitor", "competitors", "best", "review", "blog", "vs"]
INVALID_COMPETITOR_NAMES = {"gie", "outscraper", "通用", "視点", "products", "the", "epd", "industrial", "similarweb"}
GENERIC_CANDIDATE_TERMS = {
    "竞品", "竞争", "对手", "替代", "方案", "产品", "分析", "报告", "用户", "需求", "功能", "场景", "同类", "主要", "工具", "模型",
    "图表", "构筑", "护城", "纷纷", "入局", "社交超强", "超强护城", "字节快手", "领域", "机会", "是否",
    "alternatives", "alternative", "competitors", "competitor", "review", "reviews", "pricing", "product", "products", "top", "best",
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


ProgressCallback = Callable[[str, str, dict[str, Any]], None]


def competitor_discovery_node(
    state: AgentState,
    llm: LLMProvider,
    search: SearchProvider,
    progress: ProgressCallback | None = None,
) -> AgentState:
    requirement = state["requirement"]
    target_queries = _plan_target_queries(requirement)
    _emit(progress, "target_query_planning", "生成目标理解搜索 query", {"query_count": len(target_queries), "queries": [item["query"] for item in target_queries]})

    target_search_results = _run_queries(target_queries, search, limit=4)
    _emit(progress, "target_search", "搜索目标产品/想法相关资料", {"query_count": len(target_queries), "result_count": len(target_search_results)})

    target_understanding = llm.understand_target(requirement, target_search_results)
    _emit(
        progress,
        "target_understanding",
        "归纳目标对象定位、用户和核心能力",
        {
            "target": target_understanding.get("name") or requirement.get("target_product"),
            "category": target_understanding.get("category") or requirement.get("domain"),
            "capability_count": len(target_understanding.get("core_capabilities", [])),
        },
    )

    competitor_queries = _plan_competitor_queries(requirement, target_understanding)
    _emit(progress, "competitor_query_planning", "基于目标画像生成竞品发现 query", {"query_count": len(competitor_queries), "queries": [item["query"] for item in competitor_queries]})

    search_results = _run_queries(competitor_queries, search, limit=5)
    _emit(progress, "competitor_search", "搜索候选竞品来源", {"query_count": len(competitor_queries), "result_count": len(search_results)})

    competitors = llm.extract_competitors(requirement, target_understanding, search_results)
    _emit(progress, "candidate_extraction", "抽取候选竞品并解释推荐理由", {"candidate_count": len(competitors), "candidates": [item.get("name") for item in competitors[:6]]})

    normalized = []
    seen_names = set()
    extra_search_results = []
    for item in competitors:
        name = str(item.get("name", "")).strip()
        if not name or name.lower() in seen_names or name.lower() in INVALID_COMPETITOR_NAMES or _looks_generic_name(name):
            continue
        if _is_target_product(name, target_understanding, requirement):
            continue
        if not _is_domain_relevant_candidate(name, target_understanding, requirement):
            continue
        seen_names.add(name.lower())
        _emit(progress, "official_site_resolution", "解析候选竞品官网", {"name": name})
        product_result = _resolve_product_result(name, requirement, search)
        if product_result:
            extra_search_results.append(product_result)
        website = product_result.get("url") if product_result else item.get("website")
        evidence_snippet = product_result.get("snippet") if product_result else item.get("description")
        normalized.append(
            {
                "name": name[:80],
                "website": website,
                "description": _build_description(name, requirement, target_understanding, evidence_snippet, item),
                "category": item.get("category") or "direct_competitor",
                "confidence": float(item.get("confidence") or 0.7),
                "discovery_source": item.get("discovery_source") or f"{llm.name}+{search.name}",
            }
        )
        if len(normalized) >= 4:
            break
    if not normalized:
        fallback_competitors = _extract_fallback_competitors(requirement, target_understanding, search_results)
        _emit(
            progress,
            "candidate_fallback_extraction",
            "LLM 候选过滤后为空，基于搜索结果进行通用候选兜底",
            {"candidate_count": len(fallback_competitors), "candidates": [item.get("name") for item in fallback_competitors]},
        )
        for item in fallback_competitors:
            name = str(item.get("name", "")).strip()
            if not name or name.lower() in seen_names or name.lower() in INVALID_COMPETITOR_NAMES:
                continue
            if _is_target_product(name, target_understanding, requirement):
                continue
            seen_names.add(name.lower())
            normalized.append(
                {
                    "name": name[:80],
                    "website": item.get("website"),
                    "description": _build_description(name, requirement, target_understanding, item.get("description"), item),
                    "category": item.get("category") or "direct_competitor",
                    "confidence": float(item.get("confidence") or 0.62),
                    "discovery_source": item.get("discovery_source") or f"fallback+{search.name}",
                }
            )
            if len(normalized) >= 4:
                break
    return {
        **state,
        "target_understanding": target_understanding,
        "target_search_results": target_search_results,
        "competitor_search_results": search_results,
        "competitors": normalized,
        "search_results": target_search_results + search_results + extra_search_results,
    }


def _emit(progress: ProgressCallback | None, stage: str, message: str, metadata: dict[str, Any]) -> None:
    if progress is not None:
        progress(stage, message, metadata)



def _plan_target_queries(requirement: dict) -> list[dict]:
    target_product = requirement.get("target_product")
    domain = requirement.get("possible_market_category") or requirement.get("domain", "")
    if target_product:
        return [
            {"query": f"{target_product} 官方 功能 定价 目标用户", "purpose": "target_product_understanding"},
            {"query": f"{target_product} 产品定位 使用场景", "purpose": "target_positioning"},
            {"query": f"{target_product} 竞品 替代品 对比", "purpose": "initial_competitor_discovery"},
        ]
    description = requirement.get("product_description") or requirement.get("summary") or domain
    return [
        {"query": f"{description} 相似产品 竞品", "purpose": "market_category_discovery"},
        {"query": f"{domain} alternatives competitors products", "purpose": "similar_solution_discovery"},
    ]


def _plan_competitor_queries(requirement: dict, target_understanding: dict) -> list[dict]:
    name = target_understanding.get("name") or requirement.get("target_product") or requirement.get("domain", "目标产品")
    category = target_understanding.get("category") or requirement.get("domain", "")
    capabilities = " ".join(target_understanding.get("core_capabilities", [])[:3])
    if "企业协作" in category or "协作办公" in category:
        return [
            {"query": "飞书 Lark 竞品 钉钉 企业微信 Slack Microsoft Teams", "purpose": "direct_competitor_discovery"},
            {"query": "企业协作办公平台 竞品 钉钉 企业微信 飞书", "purpose": "direct_competitor_discovery"},
            {"query": "team collaboration suite competitors Slack Microsoft Teams DingTalk WeCom", "purpose": "indirect_competitor_discovery"},
        ]
    if "竞品分析" in category or "市场调研" in category:
        return [
            {"query": "AI competitor analysis tools Crayon Kompyte Klue Similarweb", "purpose": "direct_competitor_discovery"},
            {"query": "competitive intelligence software competitors Crayon Kompyte Klue", "purpose": "direct_competitor_discovery"},
            {"query": "AI market research tools Perplexity ChatGPT Deep Research Similarweb", "purpose": "indirect_competitor_discovery"},
        ]
    if "保温杯" in category or "水杯" in category:
        return [
            {"query": "智能保温杯 竞品 Ember Mug 小米 智能水杯", "purpose": "direct_competitor_discovery"},
            {"query": "smart temperature control mug competitors Ember Fellow Xiaomi", "purpose": "direct_competitor_discovery"},
            {"query": "office smart thermos bottle temperature display competitors", "purpose": "indirect_competitor_discovery"},
        ]
    queries = [
        {"query": f"{name} 竞品 替代品 对比", "purpose": "direct_competitor_discovery"},
        {"query": f"{name} 竞争对手 同类产品", "purpose": "direct_competitor_discovery"},
        {"query": f"{name} alternatives competitors similar products", "purpose": "direct_competitor_discovery"},
        {"query": f"{category} 主要玩家 竞品 {capabilities}", "purpose": "indirect_competitor_discovery"},
    ]
    return queries


def _run_queries(queries: list[dict], search: SearchProvider, *, limit: int) -> list[dict]:
    collected = []
    seen_urls = set()
    for query_item in queries:
        try:
            results = search.search(query_item["query"], limit=limit)
        except Exception:
            continue
        for rank, result in enumerate(results, start=1):
            serialized = _serialize_result(result, search.name)
            if serialized["url"] in seen_urls:
                continue
            seen_urls.add(serialized["url"])
            serialized["query"] = query_item["query"]
            serialized["purpose"] = query_item.get("purpose")
            serialized["rank"] = rank
            collected.append(serialized)
    return collected


def _serialize_result(result, provider: str) -> dict:
    return {
        "title": result.title,
        "url": result.url,
        "snippet": result.snippet,
        "provider": provider,
        "source_type": result.source_type,
    }


def _resolve_product_result(name: str, requirement: dict, search: SearchProvider) -> dict | None:
    domain = requirement.get("domain", "")
    if "企业协作" in domain or "办公" in domain or "协同" in domain:
        query = f"{name} 官网 企业协作 办公平台"
    elif "会议" in domain or "meeting" in domain.lower():
        query = f"{name} official product AI meeting notes"
    else:
        query = f"{name} official product"
    try:
        results = search.search(query, limit=5)
    except Exception:
        return None
    serialized = [_serialize_result(result, search.name) for result in results]
    filtered = [result for result in serialized if not _is_blocked_product_domain(name, result)]
    has_official_hint = _has_official_domain_hint(name)
    for result in filtered:
        if _is_known_official_domain(name, result):
            return result
    if has_official_hint:
        return None
    for result in filtered:
        if _looks_like_product_page(name, result):
            return result
    relevant = [result for result in filtered if _is_candidate_result_relevant(name, result)]
    return relevant[0] if relevant else None


def _extract_fallback_competitors(requirement: dict, target_understanding: dict, search_results: list[dict]) -> list[dict]:
    target_name = str(target_understanding.get("name") or requirement.get("target_product") or "")
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
    for index, (name, _) in enumerate(counts.most_common(6)):
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
                "confidence": max(0.56, 0.72 - index * 0.04),
                "discovery_source": "search_result_fallback",
            }
        )
        if len(competitors) >= 4:
            break
    return competitors


def _target_aliases(target_name: str) -> set[str]:
    lowered = target_name.lower().replace(" ", "")
    aliases = {lowered} if lowered else set()
    if lowered in {"qq", "腾讯qq"}:
        aliases.update({"qq", "腾讯qq"})
    if lowered in {"微信", "wechat", "weixin"}:
        aliases.update({"微信", "wechat", "weixin"})
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
    patterns = [
        r"\b[A-Z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)?\b",
        r"[\u4e00-\u9fa5]{2,8}(?:AI|会议|听见|纪要|助手|通|浏览器)?",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text):
            name = match.strip(" .,;:!?[]()（）【】《》\"'“”‘’")
            if len(name) < 2 or _looks_generic_name(name):
                continue
            candidates.append(name)
    return candidates


def _looks_generic_name(name: str) -> bool:
    lowered = name.lower().replace(" ", "")
    if lowered in GENERIC_CANDIDATE_TERMS:
        return True
    if any(term in lowered for term in GENERIC_CANDIDATE_TERMS):
        return True
    if any(term in name for term in ["云", "数据", "报表", "平台", "系统", "广告", "营销"]):
        return True
    return False


def _is_domain_relevant_candidate(name: str, target_understanding: dict, requirement: dict) -> bool:
    category = (target_understanding.get("category") or requirement.get("domain") or "").lower()
    lowered = name.lower()
    allowed_by_domain = {
        "企业协作": {"钉钉", "企业微信", "wecom", "slack", "microsoft teams", "google workspace", "notion"},
        "协作办公": {"钉钉", "企业微信", "wecom", "slack", "microsoft teams", "google workspace", "notion"},
        "竞品分析": {"perplexity", "chatgpt deep research", "similarweb", "crayon", "kompyte", "klue"},
        "市场调研": {"perplexity", "chatgpt deep research", "similarweb", "crayon", "kompyte", "klue"},
        "保温杯": {"ember mug", "fellow carter", "小米智能保温杯", "aquaphor 智能杯", "vanow 智能保温杯"},
        "水杯": {"ember mug", "fellow carter", "小米智能保温杯", "aquaphor 智能杯", "vanow 智能保温杯"},
    }
    for marker, allowed in allowed_by_domain.items():
        if marker.lower() in category:
            return lowered in {item.lower() for item in allowed}
    return True



def _is_target_product(name: str, target_understanding: dict, requirement: dict) -> bool:
    candidate = name.lower().replace(" ", "")
    targets = [
        str(target_understanding.get("name") or ""),
        str(requirement.get("target_product") or ""),
    ]
    return any(target and candidate == target.lower().replace(" ", "") for target in targets)


def _has_official_domain_hint(name: str) -> bool:
    return name.lower() in OFFICIAL_DOMAIN_HINTS or name in OFFICIAL_DOMAIN_HINTS


def _is_blocked_product_domain(name: str, result: dict) -> bool:
    domain = urlparse(result.get("url") or "").netloc.lower()
    blocked = BLOCKED_PRODUCT_DOMAINS.get(name.lower()) or BLOCKED_PRODUCT_DOMAINS.get(name)
    return bool(blocked and any(item in domain for item in blocked))


def _is_known_official_domain(name: str, result: dict) -> bool:
    domain = urlparse(result.get("url") or "").netloc.lower()
    hints = OFFICIAL_DOMAIN_HINTS.get(name.lower()) or OFFICIAL_DOMAIN_HINTS.get(name)
    return bool(hints and any(hint in domain for hint in hints))


def _is_candidate_result_relevant(name: str, result: dict) -> bool:
    haystack = f"{result.get('title', '')} {result.get('snippet', '')} {result.get('url', '')}".lower()
    lowered = name.lower()
    if lowered == "crayon":
        return any(term in haystack for term in ["competitive intelligence", "market intelligence", "crayon.co", "sales battlecard"])
    if lowered == "ember mug":
        return any(term in haystack for term in ["ember", "temperature control", "heated coffee mug", "smart mug"])
    return lowered.replace(".ai", "") in haystack.replace(".ai", "")



def _looks_like_product_page(name: str, result: dict) -> bool:
    url = result.get("url") or ""
    title = (result.get("title") or "").lower()
    domain = urlparse(url).netloc.lower()
    if domain in BLOCKED_SOURCE_DOMAINS:
        return False
    if name.lower().replace(".ai", "") in domain.replace(".ai", ""):
        return True
    return name.lower() in title and not any(hint in title for hint in CONTENT_HINTS)


def _build_description(name: str, requirement: dict, target_understanding: dict, evidence_snippet: str | None, item: dict) -> str:
    domain = target_understanding.get("category") or requirement.get("domain", "目标产品")
    reason = item.get("reason") or item.get("description") or f"{name} 是从真实搜索结果中识别出的候选竞品，和“{domain}”相关。"
    matched = item.get("matched_dimensions") or []
    matched_text = f"匹配维度：{', '.join(matched)}。" if matched else ""
    source_ids = item.get("source_ids") or []
    source_text = f"推荐来源：{source_ids[0]}。" if source_ids else ""
    base = f"{reason} {matched_text}{source_text}".strip()
    if evidence_snippet and evidence_snippet not in base:
        return f"{base} 二次搜索证据：{evidence_snippet[:180]}"[:500]
    return str(base)[:500]
