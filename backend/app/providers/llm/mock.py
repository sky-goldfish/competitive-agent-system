import json
import re
from collections import Counter
from typing import Any

TARGET_PATTERNS = [
    r"(?:分析|研究|看看|调研|了解)\s*([\w\u4e00-\u9fa5][\w\u4e00-\u9fa5 .&+\-]{0,40}?)(?:\s*的)?(?:竞品|竞争对手|替代品|对标)",
    r"([\w\u4e00-\u9fa5][\w\u4e00-\u9fa5 .&+\-]{0,40}?)(?:\s*的)?(?:竞品|竞争对手|替代品|对标)(?:分析|调研)?",
]
FILLER_WORDS = ["我想", "帮我", "请", "一下", "一个", "这个", "产品", "应用", "软件", "平台"]


def _parse_metadata(metadata_json: str | None) -> dict[str, Any]:
    if not metadata_json:
        return {}
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        return {}
    return metadata if isinstance(metadata, dict) else {}



def _clean_name(title: str) -> str:
    name = title.split(" - ")[0].split(" | ")[0].split("（")[0].strip()
    for prefix in ["官网", "官方网站", "首页"]:
        name = name.removeprefix(prefix).strip()
    return name[:80]


def _cleanup_target_name(value: str) -> str | None:
    name = value.strip(" ，。,.；;：:!?？（）()【】[]\"'“”‘’")
    for word in FILLER_WORDS:
        name = name.replace(word, "")
    name = re.sub(r"\s+", " ", name).strip(" 的")
    if not name or len(name) > 40:
        return None
    if name in {"竞品", "竞争对手", "替代品", "对标", "分析", "调研"}:
        return None
    return name


def _infer_input_type(user_requirement: str) -> str:
    lowered = user_requirement.lower()
    existing_markers = ["竞品", "分析", "替代", "alternative", "competitor", "竞争对手", "对标"]
    idea_markers = ["我想做", "想做一个", "产品想法", "可能有哪些", "面向"]
    if _extract_target_product(user_requirement) and any(marker in lowered for marker in existing_markers):
        return "existing_product"
    if any(marker in lowered for marker in idea_markers):
        return "product_idea"
    return "product_idea"


def _extract_target_product(user_requirement: str) -> str | None:
    for pattern in TARGET_PATTERNS:
        match = re.search(pattern, user_requirement, flags=re.IGNORECASE)
        if match:
            target = _cleanup_target_name(match.group(1))
            if target:
                return target
    return None


def _build_discovery_query(domain: str, target_product: str | None = None) -> str:
    if target_product:
        return f"{target_product} 竞品 替代品 对比 alternatives competitors"
    if "会议" in domain or "meeting" in domain.lower():
        return "best AI meeting notes tools alternatives Otter Fireflies Fathom competitors"
    if "AI 知识管理" in domain or "knowledge management" in domain.lower() or "协作文档" in domain:
        return "Notion AI alternatives competitors Coda AI Confluence AI ClickUp AI Mem"
    if "CRM" in domain.upper():
        return "best CRM software alternatives HubSpot Salesforce Pipedrive competitors"
    if "AI 自动竞品分析" in domain or "市场调研" in domain or "Market Intelligence" in domain:
        return "AI competitor analysis market research tools Perplexity Similarweb Crayon Kompyte"
    if "智能保温杯" in domain or "办公水杯" in domain:
        return "smart thermos mug competitors Ember Mug Fellow Carter Xiaomi smart cup"
    if "社交通讯" in domain or "即时通讯" in domain:
        return "微信 竞品 QQ 支付宝 抖音 小红书 Telegram WhatsApp"
    if "企业协作" in domain or "办公" in domain or "协同" in domain:
        return "飞书 竞品 钉钉 企业微信 协同办公"
    return f"{domain} alternatives competitors products"


def _extract_product_names(search_results: list[dict[str, Any]], target_name: str | None = None) -> list[str]:
    collaboration_names = ["钉钉", "企业微信", "WeCom", "Slack", "Microsoft Teams", "Google Workspace", "Notion"]
    knowledge_names = ["Coda AI", "Confluence AI", "ClickUp AI", "Mem", "Guru", "Slite", "Craft"]
    meeting_names = ["Otter.ai", "Fireflies.ai", "Fathom", "tl;dv"]
    research_names = ["Perplexity", "ChatGPT Deep Research", "Similarweb", "Crayon", "Kompyte", "Klue"]
    smart_cup_names = ["Ember Mug", "Fellow Carter", "小米智能保温杯", "AQUAPHOR 智能杯", "Vanow 智能保温杯"]
    text = "\n".join(f"{item.get('title', '')} {item.get('snippet', '')}" for item in search_results)
    smart_cup_matches = [name for name in smart_cup_names if name.lower() in text.lower()]
    if smart_cup_matches:
        return smart_cup_matches
    research_matches = [name for name in research_names if name.lower() in text.lower()]
    if research_matches:
        return research_matches
    meeting_matches = [name for name in meeting_names if name.lower() in text.lower()]
    if meeting_matches:
        return meeting_matches
    knowledge_matches = [name for name in knowledge_names if name.lower() in text.lower()]
    if knowledge_matches:
        return knowledge_matches
    collaboration_matches = [name for name in collaboration_names if name.lower() in text.lower()]
    if collaboration_matches:
        return collaboration_matches

    stop_words = {
        "AI", "Best", "Alternatives", "Alternative", "Competitors", "Tools", "Tool", "Compared", "Review",
        "Reviews", "Top", "Updated", "September", "Meeting", "Notes", "Notetakers", "Notetaker",
        "Products", "Product", "The", "Enterprise", "Industrial", "GIE", "EPD", "Outscraper",
        "会议纪要", "工具", "哪个", "最好用", "热门", "测评", "排名", "最新版", "通用", "視点",
        "候选竞品", "围绕", "直接竞品", "间接竞品", "接竞品", "目标产品", "相关赛道",
        "同类产品", "替代方案", "替代品", "主要竞争", "竞争对手", "榜单", "对比",
    }
    candidates: Counter[str] = Counter()
    patterns = [
        r"\b[A-Z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)?\b",
        r"[\u4e00-\u9fa5]{2,8}(?:AI|会议|听见|纪要|助手|通)?",
    ]
    generic_phrases = [
        "用户", "需求", "场景", "核心", "功能", "替代", "方案", "讨论", "覆盖", "相似", "主要", "竞争", "对手", "产品",
        "迁移", "成本", "价格", "生态", "兼容", "角度", "比较", "渠道", "差异", "筛选", "发现",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text):
            name = match.strip(" .,;:!?[]()（）【】")
            if len(name) < 2 or name in stop_words or name.lower() in {word.lower() for word in stop_words}:
                continue
            if any(word in name for word in stop_words if any("\u4e00" <= char <= "\u9fff" for char in word)):
                continue
            if name.lower() in {"https", "http", "www", "com", "blog", "app", "apps", "crm", "soc"}:
                continue
            if any(phrase in name for phrase in generic_phrases):
                continue
            candidates[name] += 1
    preferred_order = ["Otter.ai", "Fireflies", "Fathom", "tl;dv", "Granola", "Fellow", "Jamie", "ScreenApp", "Grain", "HappyScribe", "讯飞听见", "听脑AI", "科会通"]
    ordered = [name for name in preferred_order if any(name.lower() == candidate.lower() for candidate in candidates)]
    target_lower = (target_name or "").lower()
    for name, _ in candidates.most_common():
        canonical = next((preferred for preferred in preferred_order if preferred.lower() == name.lower()), name)
        if target_lower and canonical.lower() == target_lower:
            continue
        if canonical not in ordered:
            ordered.append(canonical)
    return ordered


def _find_related_result(name: str, search_results: list[dict[str, Any]]) -> dict[str, Any]:
    for result in search_results:
        haystack = f"{result.get('title', '')} {result.get('snippet', '')}".lower()
        if name.lower() in haystack:
            return result
    return search_results[0] if search_results else {}


def _matched_dimensions(target_understanding: dict[str, Any]) -> list[str]:
    dimensions = ["产品定位", "目标用户", "核心功能", "使用场景"]
    if target_understanding.get("category"):
        dimensions.append("所属赛道")
    return dimensions


def _build_candidate_reason(name: str, target_understanding: dict[str, Any]) -> str:
    target_name = target_understanding.get("name") or "目标对象"
    category = target_understanding.get("category") or "相关赛道"
    capabilities = "、".join(target_understanding.get("core_capabilities", [])[:3])
    if capabilities:
        return f"{name} 与 {target_name} 同处“{category}”方向，并在{capabilities}等核心能力上存在用户需求重叠。"
    return f"{name} 与 {target_name} 同处“{category}”方向，可能争夺相似用户需求和预算。"


def _describe_candidate(name: str, result: dict[str, Any], requirement: dict[str, Any]) -> str:
    domain = requirement.get("domain", "目标产品")
    snippet = result.get("snippet", "")
    if snippet:
        return f"{name} 是从真实搜索结果中识别出的候选竞品，和“{domain}”相关。搜索证据摘要：{snippet[:180]}"
    return f"{name} 是从真实搜索结果中识别出的候选竞品，和“{domain}”相关。"


class MockLLMProvider:
    name = "mock"

    def understand_requirement(self, user_requirement: str) -> dict[str, Any]:
        lowered = user_requirement.lower()
        if any(keyword in lowered for keyword in ["会议", "meeting", "纪要"]):
            domain = "AI 会议纪要工具"
            target_users = ["销售团队", "客户成功团队", "远程协作团队"]
            analysis_dimensions = ["转写准确率", "摘要质量", "协作能力", "集成生态", "价格门槛"]
        elif "notion ai" in lowered:
            domain = "AI 知识管理与协作文档工具"
            target_users = ["知识工作者", "产品团队", "协作文档团队", "企业知识库用户"]
            analysis_dimensions = ["文档 AI 能力", "知识库问答", "协作体验", "集成生态", "价格与企业能力"]
        elif any(keyword in lowered for keyword in ["crm", "客户"]):
            domain = "CRM 工具"
            target_users = ["销售团队", "市场团队", "客户运营团队"]
            analysis_dimensions = ["线索管理", "销售管道", "自动化", "报表分析", "集成能力"]
        elif any(keyword in lowered for keyword in ["竞品分析", "市场调研", "公开资料", "生成报告"]):
            domain = "AI 自动竞品分析与市场调研工具"
            target_users = ["中小企业", "产品经理", "市场分析人员"]
            analysis_dimensions = ["资料搜索", "来源引用", "报告生成", "竞品监控", "市场洞察"]
        elif any(keyword in lowered for keyword in ["保温杯", "智能杯", "水杯", "办公室人群"]):
            domain = "智能保温杯与办公水杯"
            target_users = ["办公室人群", "通勤用户", "健康饮水用户"]
            analysis_dimensions = ["温控能力", "容量与便携", "材质设计", "价格带", "使用体验"]
        elif any(keyword in lowered for keyword in ["飞书", "feishu", "lark", "协作", "协同", "办公平台"]):
            domain = "企业协作办公平台"
            target_users = ["企业管理者", "知识工作者", "项目团队", "中大型组织"]
            analysis_dimensions = ["即时沟通", "文档协作", "日程会议", "项目管理", "开放平台", "组织管理", "定价与部署"]
        else:
            domain = "通用产品"
            target_users = ["产品团队", "运营团队", "中小企业决策者"]
            analysis_dimensions = ["定位", "核心功能", "目标用户", "商业模式", "差异化机会"]

        target_product = _extract_target_product(user_requirement)
        input_type = _infer_input_type(user_requirement)
        if target_product and domain == "通用产品":
            domain = f"{target_product} 所在产品赛道"
            target_users = ["目标产品的现有用户", "同类需求用户", "潜在替代方案购买者"]
            analysis_dimensions = ["产品定位", "核心功能", "目标用户", "价格与商业模式", "差异化机会"]
        return {
            "input_type": input_type,
            "target_product": target_product,
            "product_description": None if target_product else user_requirement,
            "domain": domain,
            "summary": f"围绕“{user_requirement}”开展竞品发现、资料采集和结构化分析。",
            "target_users": target_users,
            "core_capabilities": [],
            "use_cases": [],
            "possible_market_category": domain,
            "analysis_dimensions": analysis_dimensions,
            "needs_clarification": False,
            "clarification_questions": [],
            "confidence": 0.78,
            "warnings": [],
            "query": _build_discovery_query(domain, target_product),
        }

    def understand_target(self, requirement: dict[str, Any], target_search_results: list[dict[str, Any]]) -> dict[str, Any]:
        name = requirement.get("target_product") or requirement.get("product_description") or requirement.get("domain", "目标对象")
        domain = requirement.get("possible_market_category") or requirement.get("domain", "通用产品")
        text = "\n".join(f"{item.get('title', '')} {item.get('snippet', '')}" for item in target_search_results)
        if "企业协作" in domain or "办公" in domain:
            capabilities = ["即时沟通", "文档协作", "会议", "日程", "项目协作", "开放平台"]
            use_cases = ["内部沟通", "团队协作", "知识管理", "会议协同", "组织管理"]
            positioning = f"{name} 是面向组织的企业协作办公平台，覆盖沟通、文档、会议和组织协同场景。"
        elif "AI 知识管理" in domain or "协作文档" in domain:
            capabilities = ["文档生成", "内容总结", "知识库问答", "团队协作", "信息整理"]
            use_cases = ["文档写作", "知识管理", "团队协作", "项目资料沉淀"]
            positioning = f"{name} 是面向文档和知识管理场景的 AI 助手。"
        elif "会议" in domain:
            capabilities = ["会议转写", "自动摘要", "发言人识别", "团队共享"]
            use_cases = ["商务会议", "销售沟通", "远程协作"]
            positioning = f"{name} 面向会议场景提供记录、转写和摘要能力。"
        elif "竞品分析" in domain or "市场调研" in domain:
            capabilities = ["公开资料搜索", "来源引用", "竞品识别", "结构化报告生成"]
            use_cases = ["竞品调研", "市场分析", "产品决策", "报告自动化"]
            positioning = f"{name} 面向产品和市场团队提供 AI 调研与竞品分析自动化能力。"
        elif "保温杯" in domain or "水杯" in domain:
            capabilities = ["温度控制", "保温保冷", "便携设计", "饮水提醒"]
            use_cases = ["办公室饮水", "通勤携带", "健康管理"]
            positioning = f"{name} 面向办公室和通勤人群，解决饮水保温、温控和便携需求。"
        else:
            capabilities = requirement.get("core_capabilities") or ["核心流程自动化", "信息整理", "报告生成"]
            use_cases = requirement.get("use_cases") or ["业务调研", "团队协作"]
            positioning = f"{name} 属于“{domain}”方向，具体定位需结合公开资料进一步确认。"
        return {
            "name": str(name),
            "category": domain,
            "positioning": positioning,
            "target_users": requirement.get("target_users", []),
            "core_capabilities": capabilities,
            "primary_use_cases": use_cases,
            "source_ids": [item.get("url") for item in target_search_results[:3] if item.get("url")],
            "evidence_ids": [],
            "confidence": 0.84 if text else 0.62,
            "warnings": [] if text else ["目标理解缺少搜索结果支撑"],
        }

    def extract_competitors(
        self,
        requirement: dict[str, Any],
        target_understanding: dict[str, Any],
        search_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        categories = ["direct_competitor", "direct_competitor", "indirect_competitor", "substitute_solution"]
        target_name = str(target_understanding.get("name") or requirement.get("target_product") or "")
        names = _extract_product_names(search_results, target_name)
        target_category = target_understanding.get("category") or requirement.get("domain", "")
        target_name_lower = target_name.lower()
        names = [name for name in names if name.lower() != target_name_lower]
        if "企业协作" in target_category or "办公" in target_category:
            preferred = ["钉钉", "企业微信", "Slack", "Microsoft Teams", "Google Workspace", "Notion"]
            names = [name for name in preferred if name in names] + [name for name in names if name not in preferred]
            names = names or preferred
        elif "AI 知识管理" in target_category or "协作文档" in target_category:
            preferred = ["Coda AI", "Confluence AI", "ClickUp AI", "Mem", "Guru"]
            names = [name for name in preferred if name in names] + [name for name in names if name not in preferred and name.lower() != target_name_lower]
            names = names or preferred
        elif "会议" in target_category:
            preferred = ["Otter.ai", "Fireflies.ai", "Fathom", "tl;dv"]
            names = [name for name in preferred if name in names] + [name for name in names if name not in preferred]
            names = names or preferred
        elif "竞品分析" in target_category or "市场调研" in target_category:
            preferred = ["Perplexity", "ChatGPT Deep Research", "Similarweb", "Crayon", "Kompyte"]
            names = [name for name in preferred if name in names] + [name for name in names if name not in preferred]
            names = names or preferred
        elif "保温杯" in target_category or "水杯" in target_category:
            preferred = ["Ember Mug", "Fellow Carter", "小米智能保温杯", "AQUAPHOR 智能杯", "Vanow 智能保温杯"]
            names = [name for name in preferred if name in names] + [name for name in names if name not in preferred]
            names = names or preferred
        if target_name and not names and search_results:
            names = [f"{target_name} 同类产品", f"{target_name} 替代方案", f"{target_name} 间接竞品"]
        elif not names:
            names = ["同类产品", "替代方案", "间接竞品"]
        competitors = []
        for index, name in enumerate(names[:4]):
            related_result = _find_related_result(name, search_results)
            competitors.append(
                {
                    "name": name,
                    "website": related_result.get("url"),
                    "description": _describe_candidate(name, related_result, requirement),
                    "category": categories[index] if index < len(categories) else "direct_competitor",
                    "reason": _build_candidate_reason(name, target_understanding),
                    "matched_dimensions": _matched_dimensions(target_understanding),
                    "source_ids": [related_result.get("url")] if related_result.get("url") else [],
                    "evidence_ids": [],
                    "selected_by_default": index < 3,
                    "confidence": max(0.55, 0.82 - index * 0.07),
                    "discovery_source": "search_heuristic",
                }
            )
        return competitors

    def analyze_competitor(self, competitor: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        name = competitor["name"]
        evidence_ids = [item.get("id") or item.get("source_url") or item.get("related_dimension", "evidence") for item in evidence]
        return {
            "positioning": f"{name} 面向目标用户提供较完整的相关工作流，强调效率提升和团队协作。",
            "target_users": json.dumps(["业务团队", "产品团队", "管理者"], ensure_ascii=False),
            "core_features_json": json.dumps(["核心流程自动化", "信息整理", "团队协作", "第三方集成"], ensure_ascii=False),
            "pricing_summary": "MVP Mock 数据显示其通常采用免费试用或分层订阅模式，具体价格需以后续真实采集为准。",
            "strengths_json": json.dumps(["功能覆盖较完整", "使用门槛较低", "适合快速试用"], ensure_ascii=False),
            "weaknesses_json": json.dumps(["深度定制能力有限", "不同来源信息仍需人工复核"], ensure_ascii=False),
            "opportunities_json": json.dumps(["可在垂直场景、证据可信度和中文本地化体验上做差异化"], ensure_ascii=False),
            "evidence_ids_json": json.dumps(evidence_ids, ensure_ascii=False),
        }

    def generate_report(self, run: dict[str, Any], analyses: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, str]:
        title = f"{run.get('title', '竞品分析任务')}报告"
        lines = [
            f"# {title}",
            "",
            "## 1. 分析背景",
            run.get("requirement_summary") or run.get("user_requirement", ""),
            "",
            "## 2. 竞品分析摘要",
        ]

        for item in analyses:
            lines.extend(
                [
                    f"### {item['competitor_name']}",
                    f"- 定位：{item['positioning']}",
                    f"- 价格摘要：{item['pricing_summary']}",
                    f"- 核心功能：{', '.join(json.loads(item['core_features_json']))}",
                    f"- 优势：{', '.join(json.loads(item['strengths_json']))}",
                    f"- 风险/短板：{', '.join(json.loads(item['weaknesses_json']))}",
                    f"- 机会点：{', '.join(json.loads(item['opportunities_json']))}",
                    "",
                ]
            )

        lines.extend(["## 3. 来源与证据", ""])
        for index, source in enumerate(sources, start=1):
            metadata = _parse_metadata(source.get("metadata_json"))
            source_label = metadata.get("source_type_label") or source.get("source_type", "来源")
            credibility = metadata.get("credibility_score")
            weight_text = f"，权重 {credibility:.2f}" if isinstance(credibility, int | float) else ""
            lines.append(f"{index}. [{source['title']}]({source['url']}) - {source_label}{weight_text} - {source['snippet']}")

        lines.extend(
            [
                "",
                "## 4. MVP 说明",
                "当前报告由 Mock Provider 生成，用于验证端到端流程、人在环确认和证据链展示。接入真实搜索与 LLM 后，可替换 Provider 获得真实资料。",
            ]
        )
        return {
            "title": title,
            "summary": "已完成候选竞品确认、资料采集、结构化分析和 Markdown 报告生成。",
            "markdown_content": "\n".join(lines),
        }
