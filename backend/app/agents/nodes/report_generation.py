import json
from typing import Any

from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider


def report_generation_node(state: AgentState, llm: LLMProvider) -> AgentState:
    sources = state["sources"]
    citation_bundle = _build_citation_bundle(state["analyses"], state["evidence"], sources)
    report = llm.generate_report(
        {
            "title": state.get("requirement", {}).get("domain", "竞品分析任务"),
            "user_requirement": state["user_requirement"],
            "requirement_summary": state.get("requirement", {}).get("summary"),
            "citation_bundle": citation_bundle,
        },
        state["analyses"],
        sources,
    )
    return {**state, "report": report}


def _build_citation_bundle(analyses: list[dict[str, Any]], evidence: list[dict[str, Any]], sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_reference_by_url = {source.get("url"): index for index, source in enumerate(sources, start=1)}
    source_by_url = {source.get("url"): source for source in sources}
    evidence_by_id = {item.get("id"): item for item in evidence if item.get("id")}
    bundle = []

    for analysis in analyses:
        evidence_ids = _json_list(analysis.get("evidence_ids_json"))
        linked_evidence = [evidence_by_id[item] for item in evidence_ids if item in evidence_by_id]
        if not linked_evidence:
            linked_evidence = [item for item in evidence if item.get("competitor_id") == analysis.get("competitor_id")]

        bundle.append(
            {
                "analysis_id": analysis.get("id"),
                "competitor_id": analysis.get("competitor_id"),
                "competitor_name": analysis.get("competitor_name"),
                "claims": [
                    _claim("positioning", "产品定位", analysis.get("positioning", ""), linked_evidence, source_reference_by_url, source_by_url, {"产品定位"}),
                    _claim("target_users", "目标用户", _join_json_list(analysis.get("target_users")), linked_evidence, source_reference_by_url, source_by_url, {"产品定位", "用户评价与痛点"}),
                    _claim("core_features", "核心功能", _join_json_list(analysis.get("core_features_json")), linked_evidence, source_reference_by_url, source_by_url, {"核心功能"}),
                    _claim("pricing", "定价策略", analysis.get("pricing_summary", ""), linked_evidence, source_reference_by_url, source_by_url, {"价格与商业模式"}),
                    _claim("strengths", "优势", _join_json_list(analysis.get("strengths_json")), linked_evidence, source_reference_by_url, source_by_url, {"产品定位", "核心功能"}),
                    _claim("weaknesses", "劣势或痛点", _join_json_list(analysis.get("weaknesses_json")), linked_evidence, source_reference_by_url, source_by_url, {"用户评价与痛点"}),
                    _claim("opportunities", "机会点", _join_json_list(analysis.get("opportunities_json")), linked_evidence, source_reference_by_url, source_by_url, set()),
                ],
            }
        )
    return bundle


def _claim(
    claim_type: str,
    label: str,
    text: str,
    evidence: list[dict[str, Any]],
    source_reference_by_url: dict[str | None, int],
    source_by_url: dict[str | None, dict[str, Any]],
    preferred_dimensions: set[str],
) -> dict[str, Any]:
    matched = [item for item in evidence if item.get("related_dimension") in preferred_dimensions] if preferred_dimensions else evidence
    if not matched:
        matched = evidence
    return {
        "claim_type": claim_type,
        "label": label,
        "text": text,
        "evidence": [_evidence_ref(item, source_reference_by_url, source_by_url) for item in matched[:4]],
    }


def _evidence_ref(evidence: dict[str, Any], source_reference_by_url: dict[str | None, int], source_by_url: dict[str | None, dict[str, Any]]) -> dict[str, Any]:
    source_url = evidence.get("source_url")
    source = source_by_url.get(source_url, {})
    return {
        "source_reference_id": source_reference_by_url.get(source_url),
        "source_title": source.get("title"),
        "source_url": source_url,
    }


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


def _join_json_list(value: Any) -> str:
    return "；".join(_json_list(value))
