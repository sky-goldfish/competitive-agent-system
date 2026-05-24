import json
from typing import Any

from openai import OpenAI

from app.core.config import get_settings
from app.providers.llm.mock import MockLLMProvider


def _safe_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.72
    if confidence > 1:
        confidence = confidence / 100
    return min(max(confidence, 0.0), 1.0)


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
  "query": "用于搜索竞品的中文查询词"
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
        return {**fallback, **result}

    def extract_competitors(
        self,
        requirement: dict[str, Any],
        target_understanding: dict[str, Any],
        search_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        fallback = self.fallback.extract_competitors(requirement, target_understanding, search_results)
        prompt = f"""
你是竞品发现 Agent。请从真实搜索结果中提取“产品/公司/服务”级别的候选竞品，过滤文章标题、榜单页、新闻页、泛概念词和无关结果。

需求理解：{json.dumps(requirement, ensure_ascii=False)}
目标对象理解：{json.dumps(target_understanding, ensure_ascii=False)}
竞品发现搜索结果：{json.dumps(search_results, ensure_ascii=False)}

要求：
- 优先从搜索结果标题和摘要中明确出现的产品名、App 名、服务名里提取候选，例如微信、Soul、TIM、ICQ、抖音、小红书、Telegram、WhatsApp。
- 不要把流量分析工具、竞品分析方法文章、报告平台、媒体站点、泛概念词抽成竞品，除非它们确实和目标对象同赛道。
- 如果搜索结果里出现“X 和 Y”“X、Y 都属于”“同类聊天软件有哪些”等句式，要把 Y 作为候选线索。
- 排除目标产品自身、文章标题、榜单名称、新闻标题和“竞品分析/替代方案/主要玩家”等泛词。

输出严格 JSON，不要输出 Markdown。
JSON schema:
{{
  "competitors": [
    {{
      "name": "竞品名称",
      "website": "官网或最相关 URL",
      "description": "用中文解释它是什么，以及为什么和目标对象相关",
      "category": "direct_competitor | indirect_competitor | substitute_solution | adjacent_product",
      "reason": "推荐理由，说明它与目标对象在定位、用户、核心功能或场景上的重叠",
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
        for item in competitors:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            cleaned.append(
                {
                    "name": str(item.get("name", ""))[:80],
                    "website": item.get("website"),
                    "description": str(item.get("description") or "由真实搜索结果和大模型提取的候选竞品。")[:500],
                    "category": item.get("category") if item.get("category") in {"direct_competitor", "indirect_competitor", "substitute_solution", "adjacent_product"} else "direct_competitor",
                    "reason": str(item.get("reason") or item.get("description") or "基于目标对象理解和搜索结果推荐。")[:500],
                    "matched_dimensions": item.get("matched_dimensions") if isinstance(item.get("matched_dimensions"), list) else [],
                    "source_ids": item.get("source_ids") if isinstance(item.get("source_ids"), list) else [],
                    "evidence_ids": item.get("evidence_ids") if isinstance(item.get("evidence_ids"), list) else [],
                    "selected_by_default": bool(item.get("selected_by_default", len(cleaned) < 3)),
                    "confidence": _safe_confidence(item.get("confidence")),
                    "discovery_source": "ark+search",
                }
            )
            if len(cleaned) >= 4:
                break
        return cleaned or fallback

    def analyze_competitor(self, competitor: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        fallback = self.fallback.analyze_competitor(competitor, evidence)
        prompt = f"""
你是竞品分析师 Agent。基于竞品信息和证据，输出严格 JSON，不要输出 Markdown。

竞品：{json.dumps(competitor, ensure_ascii=False)}
证据：{json.dumps(evidence, ensure_ascii=False)}

分析要求：优先参考高权重来源；官网/官方文档适合判断定位、功能、定价，评价站、社区、电商评价和社交平台更适合判断用户痛点。若证据摘要中包含来源类型和权重，请在结论中体现不同来源的差异，不要把低权重来源当成唯一事实。

JSON schema:
{{
  "positioning": "定位总结",
  "target_users": "JSON 字符串数组",
  "core_features_json": "JSON 字符串数组",
  "pricing_summary": "定价摘要",
  "strengths_json": "JSON 字符串数组",
  "weaknesses_json": "JSON 字符串数组",
  "opportunities_json": "JSON 字符串数组",
  "evidence_ids_json": "JSON 字符串数组"
}}
"""
        result = self._json_chat(prompt, fallback)
        for key in ["target_users", "core_features_json", "strengths_json", "weaknesses_json", "opportunities_json", "evidence_ids_json"]:
            if isinstance(result.get(key), list):
                result[key] = json.dumps(result[key], ensure_ascii=False)
        return {**fallback, **result}

    def generate_report(self, run: dict[str, Any], analyses: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, str]:
        fallback = self.fallback.generate_report(run, analyses, sources)
        prompt = f"""
你是报告撰写 Agent。请基于分析结果生成一份中文 Markdown 竞品分析报告，并输出严格 JSON，不要输出 Markdown 代码块。

任务：{json.dumps(run, ensure_ascii=False)}
分析：{json.dumps(analyses, ensure_ascii=False)}
来源：{json.dumps(sources, ensure_ascii=False)}

报告要求：来源与证据章节必须标注来源类型、权重或可信度；综合结论要说明信息来自哪些不同角度，例如官网/商品页、价格页、电商评价、社交平台、社区讨论、媒体测评等。不同来源冲突时，优先采用高权重来源，并注明低权重来源只作为用户情绪或线索参考。

JSON schema:
{{
  "title": "报告标题",
  "summary": "报告摘要",
  "markdown_content": "完整 Markdown 报告，必须包含来源与证据章节"
}}
"""
        result = self._json_chat(prompt, fallback)
        return {**fallback, **result}

    def _json_chat(self, prompt: str, fallback: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是严谨的竞品分析多 Agent 系统，只输出可解析 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                return fallback
            return {**fallback, **parsed}
        except Exception:
            return fallback
