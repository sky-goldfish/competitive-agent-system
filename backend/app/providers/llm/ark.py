import json
import logging
import re
from typing import Any

from openai import OpenAI

from app.core.config import get_settings
from app.providers.llm.mock import MockLLMProvider

logger = logging.getLogger(__name__)


def _safe_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.72
    if confidence > 1:
        confidence = confidence / 100
    return min(max(confidence, 0.0), 1.0)


def _parse_source_metadata(source: dict[str, Any]) -> dict[str, Any]:
    metadata = source.get("metadata")
    if not isinstance(metadata, dict):
        metadata_json = source.get("metadata_json")
        if isinstance(metadata_json, str) and metadata_json:
            try:
                parsed = json.loads(metadata_json)
            except json.JSONDecodeError:
                parsed = {}
            metadata = parsed if isinstance(parsed, dict) else {}
        else:
            metadata = {}
    return metadata


def _source_report_summary(source: dict[str, Any], reference_id: int | None = None) -> dict[str, Any]:
    metadata = _parse_source_metadata(source)
    summary = {
        "title": str(source.get("title", ""))[:80],
        "url": source.get("url", ""),
        "source_type": source.get("source_type", ""),
        "source_type_label": metadata.get("source_type_label"),
        "credibility_score": metadata.get("credibility_score", source.get("credibility_score", 0)),
        "rank_score": metadata.get("rank_score", source.get("rank_score", 0)),
        "dimension": metadata.get("dimension"),
        "query": metadata.get("query"),
        "classification_reason": metadata.get("classification_reason"),
    }
    if reference_id is not None:
        summary["reference_id"] = reference_id
    return summary


def _format_reference_section(sources: list[dict[str, Any]], cited_ids: set[int] | None = None) -> str:
    if not sources:
        return ""
    lines = ["## 参考来源", ""]
    for source in sources:
        reference_id = source.get("reference_id")
        if not isinstance(reference_id, int):
            continue
        if cited_ids is not None and reference_id not in cited_ids:
            continue
        summary = _source_report_summary(source, reference_id)
        title = str(summary.get("title") or f"来源 {reference_id}").replace("\n", " ").strip()
        url = str(summary.get("url") or "").strip()
        source_label = summary.get("source_type_label") or summary.get("source_type") or "来源"
        credibility = summary.get("credibility_score")
        weight_text = f"，权重 {float(credibility):.2f}" if isinstance(credibility, int | float) else ""
        if url:
            lines.append(f"{reference_id}. [[{reference_id}]]({url}) [{title}]({url}) - {source_label}{weight_text}")
        else:
            lines.append(f"{reference_id}. [{reference_id}] {title} - {source_label}{weight_text}")
    return "\n".join(lines)


def _normalize_inline_citations(markdown_content: str, max_reference_id: int | None = None) -> str:
    normalized = re.sub(r"(?<!\[)\[(\d{1,2})\]\((https?://[^)\s]+)\)", r"[[\1]](\2)", markdown_content)
    if max_reference_id is None:
        return normalized

    def keep_known_reference(match: re.Match[str]) -> str:
        reference_id = int(match.group(1))
        if 1 <= reference_id <= max_reference_id:
            return match.group(0)
        return ""

    return re.sub(r"\[\[(\d{1,2})\]\]\((https?://[^)\s]+)\)", keep_known_reference, normalized)


def _ensure_reference_section(markdown_content: str, sources: list[dict[str, Any]]) -> str:
    stripped = markdown_content.strip()
    body_only = re.sub(r"\n*##\s*(?:(?:\d+|[一二三四五六七八九十]+)[\.、]\s*)?(?:参考来源|参考文献|References)\s*\n[\s\S]*$", "", stripped).strip()
    cited_ids = {int(m) for m in re.findall(r"\[\[(\d+)\]\]", body_only)}
    reference_section = _format_reference_section(sources, cited_ids if cited_ids else None)
    max_reference_id = max((s.get("reference_id", 0) for s in sources if isinstance(s.get("reference_id"), int)), default=0)
    if not reference_section:
        return _normalize_inline_citations(stripped)
    normalized = _normalize_inline_citations(stripped, max_reference_id=max_reference_id)
    pattern = r"\n*##\s*(?:(?:\d+|[一二三四五六七八九十]+)[\.、]\s*)?(?:参考来源|参考文献|References)\s*\n[\s\S]*$"
    if re.search(pattern, normalized):
        return re.sub(pattern, f"\n\n{reference_section}", normalized).strip()
    return f"{normalized}\n\n{reference_section}".strip()


class ArkLLMProvider:
    name = "ark"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.ark_api_key:
            raise ValueError("ARK_API_KEY is required when LLM_PROVIDER=ark.")
        self.model = settings.ark_endpoint_id or settings.ark_model
        self.client = OpenAI(api_key=settings.ark_api_key, base_url=settings.ark_base_url)
        self.temperature: float | None = 0.2
        self.fallback = MockLLMProvider()

    def understand_requirement(self, user_requirement: str) -> dict[str, Any]:
        fallback = self.fallback.understand_requirement(user_requirement)
        prompt = f"""
你是竞品分析系统的需求理解 Agent。请把用户输入解析成严格 JSON，不要输出 Markdown。

用户输入：{user_requirement}

=== 内部两步思考逻辑（无需输出） ===
1. 意图解析：分析用户文本，隐式提取出核心客群 (Target User)、核心能力 (Core Features)、行业领域 (Domain)。
2. 关键词组装：摒弃自然语言陈述（如"我想做..."、"如何实现..."），将核心标签翻译成精准搜索词组。

=== 混合检索 Query 生成规则 ===
1. 数量限制：根据用户需求的复杂度，灵活生成 1~3 个并行的搜索 Query。
2. 长度限制：每个 Query 必须极其严苛地控制在 40 个字符（Characters）以内。
3. 语言与市场分发策略（核心）：
   - 严禁在单个 Query 中进行中英文混杂。
   - 采用混合检索：至少包含 1 个针对全球市场的纯英文 Query（寻找海外前沿技术模型）；以及 1 个针对国内市场的纯中文 Query（寻找本土落地竞品）。
   - 英文 Query 优先使用英文专业术语，善用双引号精确匹配，可适当加入 2026 获取最新资讯。
   - 中文 Query 专注本土市场，寻找国内同类产品和竞品。

JSON schema:
{{
  "input_type": "existing_product | product_idea | mixed | unclear",
  "target_product": "已有产品名称或 null",
  "product_description": "产品想法描述或 null",
  "domain": "产品或赛道名称",
  "summary": "一句话说明分析目标",
  "target_users": ["目标用户1", "目标用户2"],
  "core_capabilities": ["核心能力1"],
  "use_cases": ["场景1"],
  "possible_market_category": "可能赛道",
  "analysis_dimensions": ["维度1", "维度2", "维度3"],
  "needs_clarification": false,
  "clarification_questions": [],
  "confidence": 0.0,
  "warnings": [],
  "queries": ["混合检索Query1（英文）", "混合检索Query2（中文）", "混合检索Query3（可选）"],
  "query": "用于搜索竞品的中文查询词（兼容旧版）"
}}
"""
        return self._json_chat(prompt, fallback)

    def extract_focus_profile(self, user_requirement: str, requirement: dict[str, Any]) -> dict[str, Any]:
        fallback = self.fallback.extract_focus_profile(user_requirement, requirement)
        prompt = f"""
你是竞品分析系统的个性化关注点识别 Agent。请根据用户原始输入和已结构化需求，判断报告是否需要围绕特定侧重点展开。

用户原始输入：{user_requirement}
结构化需求：{json.dumps(requirement, ensure_ascii=False)}

判断规则：
- 如果用户明确表达了关注点，例如本地存储、隐私安全、AI 能力、价格、团队协作、迁移成本、开放 API、特定人群等，放入 explicit_focuses。
- 如果用户没有明确表达，但领域天然暗示常见决策维度，可以放入 inferred_focuses，priority 用 medium，不要过度臆测。
- 判断是否反问，不要依据文本长度，而要依据“缺少偏好是否会改变竞品选择、资料检索方向、报告排序和最终建议”。
- 如果用户只给出一个宽泛品类或赛道，并要求做竞品分析，但没有说明决策场景或关注维度，必须设置 clarification_needed=true。典型例子：
  - “我想分析笔记软件的竞品” -> 必须反问，因为本地存储/隐私、AI 能力、团队协作、价格、迁移成本会导向不同竞品和证据。
  - “分析 AI 会议纪要工具竞品” -> 必须反问，因为转写质量、CRM 集成、数据安全、团队协作、价格会导向不同报告重点。
  - “帮我看看 CRM 工具竞品” -> 必须反问，因为销售团队规模、集成生态、价格、行业方案会改变分析口径。
- 如果用户已经给出足够清晰的目标和侧重点，例如“重点关注笔记软件是否本地存储和隐私安全”，不要反问，直接放入 explicit_focuses。
- 如果用户没有明确侧重点，但需求已经包含具体决策目标，例如“给 20 人销售团队选便宜的会议纪要工具”，可以不反问，并把“价格/团队落地”放入 inferred_focuses 或 explicit_focuses。
- 反问只能问 1 个问题，且要给出 4-6 个可选方向，方便用户快速回答。
- 如果 clarification_needed=true，clarifying_question 不能为空；如果 clarification_needed=false，clarifying_question 必须为 null。

输出严格 JSON，不要输出 Markdown。
JSON schema:
{{
  "explicit_focuses": [
    {{
      "key": "snake_case_key",
      "label": "用户可读的关注点名称",
      "priority": "high|medium|low",
      "evidence_expectation": "需要什么类型证据来回答这个关注点",
      "query_terms": ["用于检索的中文或英文关键词"]
    }}
  ],
  "inferred_focuses": [
    {{
      "key": "snake_case_key",
      "label": "推断关注点名称",
      "priority": "high|medium|low",
      "evidence_expectation": "证据要求",
      "query_terms": ["关键词"]
    }}
  ],
  "clarification_needed": false,
  "clarifying_question": null,
  "assumptions": ["继续分析时采用的假设"]
}}
"""
        return self._json_chat(prompt, fallback)

    def understand_target(self, requirement: dict[str, Any], target_search_results: list[dict[str, Any]]) -> dict[str, Any]:
        fallback = self.fallback.understand_target(requirement, target_search_results)
        prompt = f"""
你是竞品分析系统中的目标理解 Agent。请基于需求理解和目标搜索结果，先形成目标对象画像，不要直接推荐竞品。

需求理解：{json.dumps(requirement, ensure_ascii=False)}
目标搜索结果：{json.dumps(target_search_results, ensure_ascii=False)}

要求：
- category 必须是具体赛道，例如"即时通讯与社交平台""移动支付与生活服务""企业协作办公平台"，不要输出"某某所在产品赛道"这类占位。
- core_capabilities 必须来自目标产品真实能力或搜索结果，不要输出"核心流程自动化、信息整理、报告生成"这类通用占位。
- 如果搜索结果混入广告平台、开发者文档、企业版或同品牌其他产品，要区分它们与目标产品本体，不要让噪声主导画像。
- 对 QQ、微信、小红书、B站、抖音、淘宝等 C 端产品，优先识别消费级社交、内容、交易、支付、社区等真实用户场景。

输出严格 JSON，不要输出 Markdown。
JSON schema:
{{
  "name": "目标产品或产品想法名称",
  "category": "所属赛道",
  "positioning": "产品定位",
  "target_users": ["目标用户"],
  "core_capabilities": ["核心能力"],
  "primary_use_cases": ["使用场景"],
  "source_ids": ["支撑来源 URL"],
  "evidence_ids": [],
  "confidence": 0.0,
  "warnings": []
}}
"""
        result = self._json_chat(prompt, fallback)
        if result is fallback:
            return fallback
        return result

    def extract_competitors(
        self,
        requirement: dict[str, Any],
        target_understanding: dict[str, Any],
        search_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        fallback = self.fallback.extract_competitors(requirement, target_understanding, search_results)
        prompt = f"""
你是竞品发现 Agent。请从真实搜索结果中提取与目标对象同赛道的具体产品/品牌/服务名称。

需求理解：{json.dumps(requirement, ensure_ascii=False)}
目标对象理解：{json.dumps(target_understanding, ensure_ascii=False)}
竞品发现搜索结果：{json.dumps(search_results, ensure_ascii=False)}

严格要求：
1. name 字段必须是一个具体的产品名、品牌名、App名或服务名。例如："Litter-Robot"、"CATLINK"、"小佩"、"Stripe"、"PayPal"。
2. name 绝对不能是：
   - 行业/市场描述（如"宠物智能用品行业"、"全球智能猫砂盒市场"）
   - 数字/金额（如"亿元"、"年的"、"2024年"）
   - 句子片段或中文短语（如"此外"、"其中"、"但是"）
   - 泛概念词（如"竞品"、"替代方案"、"主要玩家"）
3. 优先从搜索结果中出现的品牌名、产品名、公司名提取。
4. 如果搜索结果中提到了具体品牌（如"CATLINK智能猫砂盆"），提取品牌名"CATLINK"。
5. 排除目标产品自身。
6. 分两组输出：
   - 国外产品组：2~4 个来自海外市场的国际产品
   - 国内产品组：2~4 个来自中国本土市场的产品
7. 每个竞品必须增加 region 字段：
   - "global" 表示国外/海外产品
   - "china" 表示国内/中国本土产品

输出严格 JSON，不要输出 Markdown 代码块。
JSON schema:
{{
  "competitors": [
    {{
      "name": "具体的产品名或品牌名（2-30个字符）",
      "website": "官网或最相关 URL",
      "description": "用中文解释它是什么产品，以及为什么和目标对象竞争",
      "category": "direct_competitor | indirect_competitor | substitute_solution | adjacent_product",
      "region": "global | china",
      "reason": "推荐理由",
      "matched_dimensions": ["产品定位", "目标用户", "核心功能", "使用场景"],
      "source_ids": ["支撑来源 URL"],
      "evidence_ids": [],
      "selected_by_default": true,
      "confidence": 0.0
    }}
  ]
}}
"""
        result = self._json_chat(prompt, {"competitors": []})
        competitors = result.get("competitors")
        if not isinstance(competitors, list) or not competitors:
            return fallback
        cleaned = []
        global_count = 0
        china_count = 0
        for item in competitors:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            region = str(item.get("region", "global")).lower()
            if region not in {"global", "china"}:
                region = "global"
            if region == "global" and global_count >= 4:
                continue
            if region == "china" and china_count >= 4:
                continue
            cleaned.append(
                {
                    "name": str(item.get("name", ""))[:80],
                    "website": item.get("website"),
                    "description": str(item.get("description") or "由真实搜索结果和大模型提取的候选竞品。")[:500],
                    "category": item.get("category") if item.get("category") in {"direct_competitor", "indirect_competitor", "substitute_solution", "adjacent_product"} else "direct_competitor",
                    "region": region,
                    "reason": str(item.get("reason") or item.get("description") or "基于目标对象理解和搜索结果推荐。")[:500],
                    "matched_dimensions": item.get("matched_dimensions") if isinstance(item.get("matched_dimensions"), list) else [],
                    "source_ids": item.get("source_ids") if isinstance(item.get("source_ids"), list) else [],
                    "evidence_ids": item.get("evidence_ids") if isinstance(item.get("evidence_ids"), list) else [],
                    "selected_by_default": bool(item.get("selected_by_default", len(cleaned) < 3)),
                    "confidence": _safe_confidence(item.get("confidence")),
                    "discovery_source": f"{self.name}+search",
                }
            )
            if region == "global":
                global_count += 1
            else:
                china_count += 1
            if global_count >= 4 and china_count >= 4:
                break
        return cleaned or fallback

    def analyze_competitor(self, competitor: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        fallback = self.fallback.analyze_competitor(competitor, evidence)
        evidence_summary = "\n".join(
            f"- evidence_id={e.get('id', '')}；维度={e.get('related_dimension', '未知')}；"
            f"来源类型={e.get('source_type', '未知')}；置信度={e.get('confidence', 0)}；"
            f"来源={e.get('source_url', '')}；摘要={e.get('summary', '')[:300]}"
            for e in evidence[:12]
        )
        focus_schema = competitor.get("_focus_schema") if isinstance(competitor.get("_focus_schema"), list) else []
        focus_schema_section = ""
        if focus_schema:
            focus_schema_section = f"""

动态关注点 Schema：
{json.dumps(focus_schema, ensure_ascii=False)}

请为动态关注点 Schema 中的每一项生成一条 custom_focus_analysis_json。它们是结构化分析的动态字段，必须基于证据，不要新增 Schema 外的关注点。
"""
        qa_feedback_section = ""
        qa_feedback = competitor.get("_qa_feedback")
        if qa_feedback:
            qa_feedback_section = f"""

【质检反馈——请务必改进以下问题】
{qa_feedback}

请特别注意：上次分析存在上述问题，请务必在本次分析中改进。
"""
        prompt = f"""
你是竞品分析师 Agent。请仔细阅读以下证据材料，基于证据中的真实信息对竞品进行分析。
不要编造证据中没有的信息。如果某个字段在证据中没有找到相关内容，请如实写"证据中未涉及"。

竞品名称：{competitor.get('name', '')}
竞品描述：{competitor.get('description', '')[:300]}

已采集证据（请基于这些内容分析）：
{evidence_summary}
{focus_schema_section}
{qa_feedback_section}
输出严格 JSON，不要输出 Markdown。
JSON schema:
{{
  "positioning": "基于证据总结该产品的定位，引用具体证据内容",
  "target_users": ["从证据中提取的目标用户"],
  "core_features_json": ["从证据中提取的核心功能"],
  "pricing_summary": "从证据中提取的定价信息，无则写'证据中未涉及'",
  "strengths_json": ["从证据中提取的优势"],
  "weaknesses_json": ["从证据中提取的劣势或用户痛点"],
  "opportunities_json": ["基于证据分析的机会点"],
  "custom_focus_analysis_json": [
    {{
      "focus_key": "必须来自动态关注点 Schema 的 key",
      "label": "必须来自动态关注点 Schema 的 label",
      "verdict": "围绕该关注点的结构化结论；如果证据不足，写'证据中未涉及'",
      "evidence_ids": ["支撑该结论的 evidence_id，必须来自已采集证据"],
      "confidence": 0.0
    }}
  ],
  "evidence_ids_json": ["引用的 evidence_id，必须来自已采集证据中的 evidence_id"],
  "relationship_type": "direct/indirect/substitute 之一。direct=直接竞品，indirect=间接竞品，substitute=替代方案",
  "relationship_reason": "简要说明为什么是该竞争类型，它竞争的是什么需求或场景，基于证据",
  "overlap_dimensions": [
    {{
      "dimension": "产品定位|目标用户|核心功能|使用场景|商业模式 之一",
      "detail": "具体说明在该维度上如何与目标产品重叠，需要引用证据中的具体内容。例如：'都专注于团队知识管理场景'或'目标用户都是 25-45 岁的专业知识工作者'"
    }}
  ]，必须包含 2-4 个维度的具体重叠点，每个维度必须有具体说明，不能笼统"
}}
"""
        result = self._json_chat(prompt, fallback)
        for key in ["target_users", "core_features_json", "strengths_json", "weaknesses_json", "opportunities_json", "evidence_ids_json", "custom_focus_analysis_json"]:
            if isinstance(result.get(key), list):
                result[key] = json.dumps(result[key], ensure_ascii=False)
        if result is fallback:
            return fallback
        return result

    def generate_report(self, run: dict[str, Any], analyses: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, str]:
        fallback = self.fallback.generate_report(run, analyses, sources)
        citation_bundle = json.dumps(run.get("citation_bundle", []), ensure_ascii=False)
        qa_guidance = run.get("qa_report_guidance")
        qa_guidance_section = ""
        if qa_guidance:
            qa_guidance_section = f"""

【上次质检反馈——请务必在本次报告中改进以下问题】
{qa_guidance}

请特别注意：上次报告存在上述问题，请在本次报告中针对性改进。
"""
        prompt = f"""
你是报告撰写 Agent。请基于以下 citation_bundle 生成一份专业的中文 Markdown 竞品分析报告。

用户需求：{run.get('user_requirement', '')}
citation_bundle：{citation_bundle}{qa_guidance_section}

报告要求：
1. 标题应该准确反映分析对象和领域，不要用"通用产品"这种泛泛标题
2. 每个竞品的分析必须覆盖 citation_bundle 中提供的全部 claims。claims 来自结构化分析结果，可能包含默认字段和用户关注点动态字段；不得自行新增 citation_bundle 之外的分析维度
3. 不要使用"MVP Mock 数据显示"这类字样
4. 禁止使用 Markdown 表格；不要输出任何 `| 来源标题 |` 这类表格
5. 每个 claim 的关键结论必须引用该 claim 下 evidence 中提供的 source_reference_id。Markdown 原文写成 `[[1]](URL)`；禁止写成 `[1](URL)`
6. 【重要】不同 claim 有各自不同的 evidence 和 source_reference_id。你必须为每个 claim 使用该 claim 自己的 evidence 中的 source_reference_id，严禁把同一个 source_reference_id 用于所有 claim。示例：产品定位 claim 的 evidence 包含 source_reference_id 3 和 4，定价策略 claim 的 evidence 包含 source_reference_id 7 和 8，则产品定位的结论应引用 [[3]] 或 [[4]]，定价策略的结论应引用 [[7]] 或 [[8]]，不得混用
7. 每个关键结论应就近引用其支撑来源，不要在段落末尾集中引用
8. 不要自行生成 `## 参考来源` 部分，系统会自动补充
9. 如果某些信息不确定或缺失，如实写"证据中未涉及"，不要编造

输出严格 JSON，不要输出 Markdown 代码块。
JSON schema:
{{
  "title": "报告标题（应包含具体产品或领域名称）",
  "summary": "报告摘要（2-3句话概括核心发现）",
  "markdown_content": "完整 Markdown 报告"
}}
"""
        result = self._json_chat(prompt, fallback)
        if result is fallback:
            return fallback
        result["markdown_content"] = _ensure_reference_section(result.get("markdown_content", ""), sources)
        return result

    def qa_check_report(
        self,
        report: dict[str, str],
        analyses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        fallback = self.fallback.qa_check_report(report, analyses, evidence)
        analyses_summary = "\n".join(
            f"- 竞品={a.get('competitor_name', '')}；定位={a.get('positioning', '')}；"
            f"定价={a.get('pricing_summary', '')}；证据数={len(_json_list(a.get('evidence_ids_json')))}"
            for a in analyses
        )
        evidence_summary = "\n".join(
            f"- [{e.get('reference_id', '?')}] 竞品={e.get('related_product', '')}；维度={e.get('related_dimension', '')}；"
            f"来源类型={e.get('source_type', '')}；置信度={e.get('confidence', 0)}；摘要={e.get('summary', '')}"
            for e in evidence
        )
        report_content = report.get("markdown_content", "")
        prompt = f"""
你是竞品分析系统的质检 Agent。请对以下报告和支撑数据进行多维度质量检查。

## 报告内容
{report_content}

## 分析摘要
{analyses_summary}

## 证据摘要（含引用号）
{evidence_summary}

## 质检维度

请从以下 6 个维度评估，每个维度打分 0.0-1.0：

1. **evidence_grounding（证据支撑度）**：分析结论是否被证据支撑？是否有幻觉内容？
2. **citation_accuracy（引用准确性）**：报告中的 `[[N]](URL)` 引用是否指向真实来源？
3. **schema_completeness（Schema 完整度）**：每个竞品的 7 个分析字段是否都有实质内容？
4. **coverage_gaps（覆盖缺口）**：每个竞品的 4 个核心维度（产品定位、核心功能、价格与商业模式、用户评价与痛点）证据是否充足？
5. **cross_competitor_consistency（跨竞品一致性）**：各竞品分析深度是否一致？
6. **factual_plausibility（事实合理性）**：是否有明显不合理内容？

输出严格 JSON，不要输出 Markdown 代码块，不要输出 schema 外字段。
JSON schema:
{{
  "dimension_scores": {{
    "evidence_grounding": 0.0,
    "citation_accuracy": 0.0,
    "schema_completeness": 0.0,
    "coverage_gaps": 0.0,
    "cross_competitor_consistency": 0.0,
    "factual_plausibility": 0.0
  }},
  "retry_instructions": "具体的改进指导（有 issues 时填写，面向人类阅读）",
  "retry_queries": [
    {{
      "competitor_name": "竞品名称",
      "slot": "core_features | pricing | positioning | user_feedback | market_signal | risk_opportunity | relationship_evidence",
      "query": "用于搜索引擎的具体检索关键词，15-40字，精准有效"
    }}
  ],
  "issues": [
    {{
      "dimension": "维度名",
      "severity": "critical | major | minor",
      "competitor_name": "单个竞品名，或 report，或 system。严禁填入多个竞品名（如\"A、B\"或\"全部竞品\"）",
      "description": "问题描述",
      "fix_suggestion": "修复建议"
    }}
  ]
}}

【issues 生成规则】
- 每条 issue 必须对应且只对应一个竞品。如果一个问题同时影响多个竞品（如\"A 和 B 都缺少用户评价\"），必须拆成多条独立的 issue，每条只关联一个竞品
- 对于 cross_competitor_consistency 类问题，每条 issue 只需列出受影响的一方（如\"A 的分析深度高于 B\"，应拆为一条针对 A 的 issue 和一条针对 B 的 issue）

【retry_queries 生成规则】
- 当 issue 需要补采公开资料时填写，尤其是 coverage_gaps 或 evidence_grounding 问题
- 每个需要补采的 issue 对应生成 1-2 条 query
- query 必须是有效的搜索关键词，不要包含自然语言指令（如"补充搜索"）
- 根据竞品名称的语言选择中英文 query：英文竞品用英文，中文竞品用中文
- 每条 query 控制在 15-40 个字符，精准命中信息缺口
- 示例：{{"competitor_name": "Otter.ai", "slot": "core_features", "query": "Otter.ai feature list integrations API documentation"}}
"""
        result = self._json_chat(prompt, fallback)
        if result is fallback:
            return fallback
        issues = result.get("issues")
        if not isinstance(issues, list):
            result["issues"] = []
        return result

    def qa_verify_issues(
        self,
        report: dict[str, str],
        analyses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        open_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        fallback = self.fallback.qa_verify_issues(report, analyses, evidence, open_issues)
        issues_json = json.dumps(open_issues, ensure_ascii=False)
        analyses_summary = "\n".join(
            f"- 竞品={a.get('competitor_name', '')}；定位={a.get('positioning', '')}；"
            f"定价={a.get('pricing_summary', '')}；证据数={len(_json_list(a.get('evidence_ids_json')))}"
            for a in analyses
        )
        evidence_summary = "\n".join(
            f"- [{e.get('reference_id', '?')}] 竞品={e.get('related_product', '')}；维度={e.get('related_dimension', '')}；"
            f"来源类型={e.get('source_type', '')}；置信度={e.get('confidence', 0)}；摘要={e.get('summary', '')}"
            for e in evidence
        )
        prompt = f"""
你是竞品分析系统的质检复核 Agent。请只检查以下历史未解决问题是否已经被本轮报告、分析和证据解决。

## 历史未解决 issues
{issues_json}

## 报告内容
{report.get('markdown_content', '')}

## 分析摘要
{analyses_summary}

## 证据摘要
{evidence_summary}

输出严格 JSON，不要输出 Markdown 代码块，不要输出 schema 外字段。
JSON schema:
{{
  "resolutions": [
    {{
      "issue_id": "必须来自历史 issue 的 id",
      "status": "resolved | open",
      "resolution_reason": "说明为什么已解决或仍未解决",
      "retry_queries": [
        {{
          "competitor_name": "竞品名称",
          "slot": "core_features | pricing | positioning | user_feedback | market_signal | risk_opportunity | relationship_evidence",
          "query": "如果仍需补采，给出具体搜索关键词；否则为空数组"
        }}
      ]
    }}
  ],
  "retry_instructions": "如果仍有 open issue，给出下一步修复指引；否则为空"
}}

规则：
- 每个历史 issue 必须返回一条 resolution。
- 只有在新报告/新分析/新证据已经直接覆盖原问题时，status 才能是 resolved。
- 如果证据仍不足、字段仍空泛、引用仍无法核验，status 必须是 open。
"""
        result = self._json_chat(prompt, fallback)
        if result is fallback:
            return fallback
        resolutions = result.get("resolutions")
        if not isinstance(resolutions, list):
            result["resolutions"] = []
        return result

    def _json_chat(self, prompt: str, fallback: dict[str, Any]) -> dict[str, Any]:
        try:
            request: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "你是严谨的竞品分析多 Agent 系统。必须只输出纯 JSON，不要包含 ```json 代码块标记，不要输出任何解释文字。"},
                    {"role": "user", "content": prompt},
                ],
            }
            if self.temperature is not None:
                request["temperature"] = self.temperature
            response = self.client.chat.completions.create(**request)
            content = (response.choices[0].message.content or "").strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3].strip()
            if not content:
                logger.warning("LLM returned empty content, using fallback")
                return fallback
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                logger.warning("LLM returned non-dict JSON, using fallback")
                return fallback
            return parsed
        except json.JSONDecodeError:
            logger.warning("LLM returned invalid JSON: %s", content[:200] if content else "empty")
            return fallback
        except Exception:
            logger.exception("LLM API call failed, using fallback")
            return fallback


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
