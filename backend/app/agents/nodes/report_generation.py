import json
from typing import Any

from app.agents.evidence_policy import (
    CLAIM_DIMENSION_MAP,
    CLAIM_FIELD_MAP,
    dimension_matches_any,
    parse_field_evidence_ids,
    parse_item_evidence_bindings,
)
from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider
from app.schemas.analysis import parse_focus_analysis_json


def report_generation_node(state: AgentState, llm: LLMProvider) -> AgentState:
    sources = state.get("sources", [])
    analyses = state.get("analyses", [])
    focus_dimensions = _extract_focus_dimensions(state.get("requirement", {}))
    citation_bundle = _build_citation_bundle(
        analyses,
        state.get("evidence", []),
        focus_dimensions,
    )
    report = llm.generate_report(
        {
            "title": state.get("requirement", {}).get("domain", "竞品分析任务"),
            "user_requirement": state.get("user_requirement", ""),
            "requirement_summary": state.get("requirement", {}).get("summary"),
            "citation_bundle": citation_bundle,
            "focus_dimensions": focus_dimensions,
            "qa_analysis_guidance": state.get("qa_analysis_guidance"),
        },
        analyses,
        sources,
    )
    return {**state, "report": report}


def _build_citation_bundle(
    analyses: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    focus_dimensions: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    evidence_by_id = {item.get("id"): item for item in evidence if item.get("id")}
    allowed_focuses = _focus_dimension_allowlist(focus_dimensions or [])
    bundle = []

    for analysis in analyses:
        comp_id = analysis.get("competitor_id")
        comp_name = analysis.get("competitor_name")

        evidence_ids = _json_list(analysis.get("evidence_ids_json"))
        field_evidence_ids = parse_field_evidence_ids(
            _json_dict(analysis.get("field_evidence_ids_json"))
        )
        item_evidence_bindings = parse_item_evidence_bindings(
            _json_dict(analysis.get("item_evidence_bindings_json"))
        )
        linked_evidence = [
            evidence_by_id[item] for item in evidence_ids if item in evidence_by_id
        ]

        comp_evidence = [
            item
            for item in evidence
            if item.get("competitor_id") == comp_id
            or item.get("related_product") == comp_name
        ]

        if not linked_evidence:
            linked_evidence = comp_evidence

        def evidence_for_claim(
            claim_type: str, preferred_dimensions: set[str]
        ) -> list[dict[str, Any]]:
            field = CLAIM_FIELD_MAP.get(claim_type)
            if field:
                item_linked = []
                for row in item_evidence_bindings.get(field, []):
                    for evidence_id in row.get("evidence_ids") or []:
                        if evidence_id in evidence_by_id:
                            item_linked.append(evidence_by_id[evidence_id])
                if item_linked:
                    return _dedupe_evidence(item_linked)
                field_linked = [
                    evidence_by_id[evidence_id]
                    for evidence_id in field_evidence_ids.get(field, [])
                    if evidence_id in evidence_by_id
                ]
                if field_linked:
                    return field_linked
            if not linked_evidence:
                return []
            dim_matched = [
                item
                for item in linked_evidence
                if _dimension_matches_any(
                    item.get("related_dimension", ""), preferred_dimensions
                )
            ]
            if dim_matched:
                return dim_matched
            if comp_evidence:
                dim_matched_comp = [
                    item
                    for item in comp_evidence
                    if _dimension_matches_any(
                        item.get("related_dimension", ""), preferred_dimensions
                    )
                ]
                if dim_matched_comp:
                    return dim_matched_comp
            return []

        bundle.append(
            {
                "analysis_id": analysis.get("id"),
                "competitor_id": comp_id,
                "competitor_name": comp_name,
                "claims": [
                    _claim(
                        "positioning",
                        "产品定位",
                        analysis.get("positioning", ""),
                        evidence_for_claim("positioning", CLAIM_DIMENSION_MAP["positioning"]),
                    ),
                    _claim(
                        "target_users",
                        "目标用户",
                        _join_json_list(analysis.get("target_users")),
                        evidence_for_claim("target_users", CLAIM_DIMENSION_MAP["target_users"]),
                    ),
                    _claim(
                        "core_features",
                        "核心功能",
                        _join_json_list(analysis.get("core_features_json")),
                        evidence_for_claim("core_features", CLAIM_DIMENSION_MAP["core_features"]),
                    ),
                    _claim(
                        "pricing",
                        "定价策略",
                        analysis.get("pricing_summary", ""),
                        evidence_for_claim("pricing", CLAIM_DIMENSION_MAP["pricing"]),
                    ),
                    _claim(
                        "strengths",
                        "优势",
                        _join_json_list(analysis.get("strengths_json")),
                        evidence_for_claim("strengths", CLAIM_DIMENSION_MAP["strengths"]),
                    ),
                    _claim(
                        "weaknesses",
                        "劣势或痛点",
                        _join_json_list(analysis.get("weaknesses_json")),
                        evidence_for_claim("weaknesses", CLAIM_DIMENSION_MAP["weaknesses"]),
                    ),
                    _claim(
                        "opportunities",
                        "机会点",
                        _join_json_list(analysis.get("opportunities_json")),
                        evidence_for_claim("opportunities", CLAIM_DIMENSION_MAP["opportunities"]),
                    ),
                ]
                + _custom_focus_claims(
                    analysis,
                    evidence_by_id,
                    linked_evidence,
                    comp_evidence,
                    allowed_focuses,
                ),
            }
        )
    return bundle


def _dedupe_evidence(evidence_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence_list:
        evidence_id = str(item.get("id") or "")
        if evidence_id and evidence_id not in seen:
            seen.add(evidence_id)
            result.append(item)
    return result


def _dimension_matches_any(dimension: str, preferred: set[str]) -> bool:
    return dimension_matches_any(dimension, preferred)


def _claim(
    claim_type: str,
    label: str,
    text: str,
    evidence_list: list[dict[str, Any]],
) -> dict[str, Any]:
    if not evidence_list:
        return {
            "claim_type": claim_type,
            "label": label,
            "text": text,
            "evidence": [],
        }
    seen_ref_ids: set[int] = set()
    seen_none = False
    deduped_refs: list[dict[str, Any]] = []
    for item in evidence_list[:8]:
        ref_id = item.get("reference_id")
        if ref_id is None:
            if seen_none:
                continue
            seen_none = True
        else:
            if ref_id in seen_ref_ids:
                continue
            seen_ref_ids.add(ref_id)
        deduped_refs.append(_evidence_ref(item))
        if len(deduped_refs) >= 4:
            break
    allowed_ids = sorted({ref for ref in seen_ref_ids if isinstance(ref, int)})
    return {
        "claim_type": claim_type,
        "label": label,
        "text": text,
        "evidence": deduped_refs,
        "allowed_reference_ids": allowed_ids,
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
    comp_evidence: list[dict[str, Any]],
    allowed_focuses: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    if not allowed_focuses:
        return []
    claims = []
    for item in parse_focus_analysis_json(analysis.get("custom_focus_analysis_json")):
        key = str(item.get("focus_key") or item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        focus_dimension = allowed_focuses.get(f"key:{key}") or allowed_focuses.get(
            f"label:{label}"
        )
        if not focus_dimension:
            continue
        focus_key = focus_dimension["key"]
        label = focus_dimension["label"]
        evidence_ids = _json_list(item.get("evidence_ids"))
        matched = [
            evidence_by_id[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in evidence_by_id
        ]
        if not matched:
            matched = [
                evidence
                for evidence in fallback_evidence
                if _dimension_matches(label, str(evidence.get("related_dimension", "")))
            ]
        if not matched:
            matched = [
                evidence
                for evidence in comp_evidence
                if _dimension_matches(label, str(evidence.get("related_dimension", "")))
            ]
        seen_ref_ids: set[int] = set()
        seen_none = False
        deduped_refs: list[dict[str, Any]] = []
        for evidence in matched[:8]:
            ref_id = evidence.get("reference_id")
            if ref_id is None:
                if seen_none:
                    continue
                seen_none = True
            else:
                if ref_id in seen_ref_ids:
                    continue
                seen_ref_ids.add(ref_id)
            deduped_refs.append(_evidence_ref(evidence))
            if len(deduped_refs) >= 4:
                break
        allowed_ids = sorted({ref for ref in seen_ref_ids if isinstance(ref, int)})
        claims.append(
            {
                "claim_type": f"focus:{focus_key or len(claims) + 1}",
                "label": label,
                "text": str(item.get("verdict") or "证据中未涉及"),
                "evidence": deduped_refs,
                "allowed_reference_ids": allowed_ids,
            }
        )
    return claims


def _focus_dimension_allowlist(
    focus_dimensions: list[dict[str, str]]
) -> dict[str, dict[str, str]]:
    allowed: dict[str, dict[str, str]] = {}
    for item in focus_dimensions:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        normalized = {"key": key, "label": label}
        if key:
            allowed[f"key:{key}"] = normalized
        allowed[f"label:{label}"] = normalized
    return allowed


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


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _join_json_list(value: Any) -> str:
    return "；".join(_json_list(value))


def _extract_focus_dimensions(requirement: dict) -> list[dict[str, str]]:
    """Extract ordered user-explicit focus dimensions for table headers."""
    profile = (
        requirement.get("focus_profile")
        if isinstance(requirement.get("focus_profile"), dict)
        else {}
    )
    if not isinstance(profile, dict):
        return []
    items = []
    for f in profile.get("explicit_focuses") or []:
        if isinstance(f, dict) and f.get("label"):
            items.append(
                {
                    "key": str(f.get("key") or ""),
                    "label": str(f.get("label") or ""),
                    "priority": str(f.get("priority") or "medium"),
                }
            )
    return items[:6]


def _dimension_matches(label: str, dimension: str) -> bool:
    if not label or not dimension:
        return False
    if dimension == label:
        return True
    for part in (
        dimension.replace("、", ",").replace("；", ",").replace("，", ",").split(",")
    ):
        if part.strip() == label:
            return True
    return False
