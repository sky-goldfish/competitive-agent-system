import json
from typing import Any

from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider
from app.schemas.analysis import parse_focus_analysis_json


def report_generation_node(state: AgentState, llm: LLMProvider) -> AgentState:
    sources = state["sources"]
    citation_bundle = _build_citation_bundle(state["analyses"], state["evidence"])
    report = llm.generate_report(
        {
            "title": state.get("requirement", {}).get("domain", "竞品分析任务"),
            "user_requirement": state["user_requirement"],
            "requirement_summary": state.get("requirement", {}).get("summary"),
            "citation_bundle": citation_bundle,
            "qa_report_guidance": state.get("qa_report_guidance"),
        },
        state["analyses"],
        sources,
    )
    return {**state, "report": report}


def _build_citation_bundle(analyses: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                    _claim("positioning", "产品定位", analysis.get("positioning", ""), linked_evidence, {"产品定位"}),
                    _claim("target_users", "目标用户", _join_json_list(analysis.get("target_users")), linked_evidence, {"产品定位", "用户评价与痛点"}),
                    _claim("core_features", "核心功能", _join_json_list(analysis.get("core_features_json")), linked_evidence, {"核心功能"}),
                    _claim("pricing", "定价策略", analysis.get("pricing_summary", ""), linked_evidence, {"价格与商业模式"}),
                    _claim("strengths", "优势", _join_json_list(analysis.get("strengths_json")), linked_evidence, {"产品定位", "核心功能"}),
                    _claim("weaknesses", "劣势或痛点", _join_json_list(analysis.get("weaknesses_json")), linked_evidence, {"用户评价与痛点"}),
                    _claim("opportunities", "机会点", _join_json_list(analysis.get("opportunities_json")), linked_evidence, set()),
                ] + _custom_focus_claims(analysis, evidence_by_id, linked_evidence),
            }
        )
    return bundle


def _claim(
    claim_type: str,
    label: str,
    text: str,
    evidence_list: list[dict[str, Any]],
    preferred_dimensions: set[str],
) -> dict[str, Any]:
    matched = [item for item in evidence_list if item.get("related_dimension") in preferred_dimensions] if preferred_dimensions else evidence_list
    if not matched:
        matched = evidence_list
    return {
        "claim_type": claim_type,
        "label": label,
        "text": text,
        "evidence": [_evidence_ref(item) for item in matched[:4]],
    }


def _evidence_ref(evidence_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_reference_id": evidence_item.get("reference_id"),
        "source_title": evidence_item.get("source_title"),
        "source_url": evidence_item.get("source_url"),
    }


def _custom_focus_claims(
    analysis: dict[str, Any],
    evidence_by_id: dict[Any, dict[str, Any]],
    fallback_evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    claims = []
    for item in parse_focus_analysis_json(analysis.get("custom_focus_analysis_json")):
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        evidence_ids = _json_list(item.get("evidence_ids"))
        matched = [evidence_by_id[evidence_id] for evidence_id in evidence_ids if evidence_id in evidence_by_id]
        if not matched:
            matched = [
                evidence
                for evidence in fallback_evidence
                if label in str(evidence.get("related_dimension", ""))
            ]
        claims.append(
            {
                "claim_type": f"focus:{item.get('focus_key') or len(claims) + 1}",
                "label": label,
                "text": str(item.get("verdict") or "证据中未涉及"),
                "evidence": [_evidence_ref(evidence) for evidence in matched[:4]],
            }
        )
    return claims


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
