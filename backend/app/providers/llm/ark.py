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


def _format_reference_section(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return ""
    lines = ["## 参考来源", ""]
    for index, source in enumerate(sources, start=1):
        summary = _source_report_summary(source, index)
        title = str(summary.get("title") or f"来源 {index}").replace("\n", " ").strip()
        url = str(summary.get("url") or "").strip()
        source_label = summary.get("source_type_label") or summary.get("source_type") or "来源"
        credibility = summary.get("credibility_score")
        weight_text = f"，权重 {float(credibility):.2f}" if isinstance(credibility, int | float) else ""
        if url:
            lines.append(f"{index}. [[{index}]]({url}) [{title}]({url}) - {source_label}{weight_text}")
        else:
            lines.append(f"{index}. [{index}] {title} - {source_label}{weight_text}")
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
    reference_section = _format_reference_section(sources)
    max_reference_id = len(sources)
    if not reference_section:
        return _normalize_inline_citations(markdown_content)
    stripped = _normalize_inline_citations(markdown_content.strip(), max_reference_id=max_reference_id)
    pattern = r"\n*##\s*(?:(?:\d+|[一二三四五六七八九十]+)[\.、]\s*)?(?:参考来源|参考文献|References)\s*\n[\s\S]*$"
    if re.search(pattern, stripped):
        return re.sub(pattern, f"\n\n{reference_section}", stripped).strip()
    return f"{stripped}\n\n{reference_section}".strip()


class ArkLLMProvider:
    name = "ark"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.ark_api_key:
            raise ValueError("ARK_API_KEY is required when LLM_PROVIDER=ark.")
        self.model = settings.ark_endpoint_id or settings.ark_model
        self.client = OpenAI(api_key=settings.ark_api_key, base_url=settings.ark_base_url)
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

    def understand_target(self, requirement: dict[str, Any], target_search_results: list[dict[str, Any]]) -> dict[str, Any]:
        fallback = self.fallback.understand_target(requirement, target_search_results)
        prompt = f"""
你是竞品分析系统中的目标理解 Agent。请基于需求理解和目标搜索结果，先形成目标对象画像，不要直接推荐竞品。

需求理解：{json.dumps(requirement, ensure_ascii=False)}
目标搜索结果：{json.dumps(target_search_results, ensure_ascii=False)}

要求：
- category 必须是具体赛道，例如“即时通讯与社交平台”“移动支付与生活服务”“企业协作办公平台”，不要输出“某某所在产品赛道”这类占位。
- core_capabilities 必须来自目标产品真实能力或搜索结果，不要输出“核心流程自动化、信息整理、报告生成”这类通用占位。
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
                    "discovery_source": "ark+search",
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
            f"- evidence_id={e.get('id', '')}；维度={e.get('related_dimension', '未知')}；来源={e.get('source_url', '')}；摘要={e.get('summary', '')[:300]}"
            for e in evidence[:12]
        )
        prompt = f"""
你是竞品分析师 Agent。请仔细阅读以下证据材料，基于证据中的真实信息对竞品进行分析。
不要编造证据中没有的信息。如果某个字段在证据中没有找到相关内容，请如实写"证据中未涉及"。

竞品名称：{competitor.get('name', '')}
竞品描述：{competitor.get('description', '')[:300]}

已采集证据（请基于这些内容分析）：
{evidence_summary}

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
  "evidence_ids_json": ["引用的 evidence_id，必须来自已采集证据中的 evidence_id"]
}}
"""
        result = self._json_chat(prompt, fallback)
        for key in ["target_users", "core_features_json", "strengths_json", "weaknesses_json", "opportunities_json", "evidence_ids_json"]:
            if isinstance(result.get(key), list):
                result[key] = json.dumps(result[key], ensure_ascii=False)
        if result is fallback:
            return fallback
        return result

    def generate_report(self, run: dict[str, Any], analyses: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, str]:
        fallback = self.fallback.generate_report(run, analyses, sources)
        analyses_summary = json.dumps(analyses, ensure_ascii=False)[:4000]
        sources_summary = json.dumps(
            [_source_report_summary(source, index) for index, source in enumerate(sources, start=1)],
            ensure_ascii=False,
        )
        citation_bundle = json.dumps(run.get("citation_bundle", []), ensure_ascii=False)[:12000]
        prompt = f"""
你是报告撰写 Agent。请基于以下分析结果和来源，生成一份专业的中文 Markdown 竞品分析报告。

用户需求：{run.get('user_requirement', '')}
分析结果：{analyses_summary}
来源列表：{sources_summary}
严格引用链路 citation_bundle：{citation_bundle}

报告要求：
1. 标题应该准确反映分析对象和领域，不要用"通用产品"这种泛泛标题
2. 每个竞品的分析必须基于上面的分析结果和 citation_bundle，引用具体的功能、定价、优劣势信息
3. 不要使用"MVP Mock 数据显示"这类字样
4. 禁止使用 Markdown 表格；不要输出任何 `| 来源标题 |` 这类表格
5. 正文中涉及关键结论、事实、数据、价格、功能、用户评价时，必须在对应句子末尾标注可点击引用编号。Markdown 原文必须写成 `[[1]](URL)`、`[[2]](URL)`，这样页面会显示为 `[1]`、`[2]`；禁止写成 `[1](URL)`，因为页面会只显示裸数字 `1`。
6. 每个正文引用都必须遵守"报告结论 -> citation_bundle.claim -> evidence.evidence_id -> source_reference_id/source_url"的链路。某条结论只能引用同一 claim.evidence 中提供的 source_reference_id 和 source_url，禁止引用该 claim 下不存在的来源编号。
7. 不要只在段落末尾集中引用；每个关键结论应就近引用其支撑来源，例如："A 产品采用分层订阅模式[[3]](https://example.com/pricing)。"，不要输出"分层订阅模式3"。
8. 报告末尾必须使用 `## 参考来源`，用有序列表列出引用来源，编号必须与正文引用一致，格式为 `1. [[1]](URL) [来源标题](URL) - 来源类型/标签，权重 0.xx`
9. `## 参考来源` 必须列出来源列表中的全部来源，按 reference_id 从小到大排列，不得漏列、重排或改号。
10. 如果某些信息不确定或缺失，明确说明而不是编造

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

    def _json_chat(self, prompt: str, fallback: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是严谨的竞品分析多 Agent 系统。必须只输出纯 JSON，不要包含 ```json 代码块标记，不要输出任何解释文字。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
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
