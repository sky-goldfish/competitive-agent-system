import json
import logging
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
1. name 字段必须是一个具体的产品名、品牌名、App名或服务名。例如：”Litter-Robot”、”CATLINK”、”小佩”、”Stripe”、”PayPal”。
2. name 绝对不能是：
   - 行业/市场描述（如”宠物智能用品行业”、”全球智能猫砂盒市场”）
   - 数字/金额（如”亿元”、”年的”、”2024年”）
   - 句子片段或中文短语（如”此外”、”其中”、”但是”）
   - 泛概念词（如”竞品”、”替代方案”、”主要玩家”）
3. 优先从搜索结果中出现的品牌名、产品名、公司名提取。
4. 如果搜索结果中提到了具体品牌（如”CATLINK智能猫砂盆”），提取品牌名”CATLINK”。
5. 排除目标产品自身。
6. 输出 3-5 个候选竞品。

输出严格 JSON，不要输出 Markdown 代码块。
JSON schema:
{{
  “competitors”: [
    {{
      “name”: “具体的产品名或品牌名（2-30个字符）”,
      “website”: “官网或最相关 URL”,
      “description”: “用中文解释它是什么产品，以及为什么和目标对象竞争”,
      “category”: “direct_competitor | indirect_competitor | substitute_solution | adjacent_product”,
      “reason”: “推荐理由”,
      “matched_dimensions”: [“产品定位”, “目标用户”, “核心功能”, “使用场景”],
      “source_ids”: [“支撑来源 URL”],
      “evidence_ids”: [],
      “selected_by_default”: true,
      “confidence”: 0.0
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
        evidence_summary = "\n".join(
            f"- [{e.get('related_dimension', '未知')}] {e.get('summary', '')[:300]}"
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
  "evidence_ids_json": ["引用的证据来源URL"]
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
            [{"title": s.get("title", "")[:80], "url": s.get("url", ""), "source_type": s.get("source_type", ""), "credibility_score": s.get("credibility_score", 0)} for s in sources[:20]],
            ensure_ascii=False,
        )
        prompt = f"""
你是报告撰写 Agent。请基于以下分析结果和来源，生成一份专业的中文 Markdown 竞品分析报告。

用户需求：{run.get('user_requirement', '')}
分析结果：{analyses_summary}
来源列表：{sources_summary}

报告要求：
1. 标题应该准确反映分析对象和领域，不要用"通用产品"这种泛泛标题
2. 每个竞品的分析必须基于上面的分析结果，引用具体的功能、定价、优劣势信息
3. 不要使用"MVP Mock 数据显示"这类字样
4. 来源与证据章节必须标注来源类型和权重
5. 如果某些信息不确定或缺失，明确说明而不是编造

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
