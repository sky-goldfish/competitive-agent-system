import json
from typing import Any

from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider
from app.schemas.analysis import parse_focus_analysis_json


def report_generation_node(state: AgentState, llm: LLMProvider) -> AgentState:
    sources = state.get("sources", [])
    analyses = state.get("analyses", [])
    citation_bundle = _build_citation_bundle(analyses, state.get("evidence", []))
    focus_dimensions = _extract_focus_dimensions(state.get("requirement", {}))
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
    analyses: list[dict[str, Any]], evidence: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    evidence_by_id = {item.get("id"): item for item in evidence if item.get("id")}
    bundle = []

    for analysis in analyses:
        comp_id = analysis.get("competitor_id")
        comp_name = analysis.get("competitor_name")

        evidence_ids = _json_list(analysis.get("evidence_ids_json"))
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

        def evidence_for_claim(preferred_dimensions: set[str]) -> list[dict[str, Any]]:
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
                        evidence_for_claim({"产品定位"}),
                    ),
                    _claim(
                        "target_users",
                        "目标用户",
                        _join_json_list(analysis.get("target_users")),
                        evidence_for_claim({"产品定位", "用户评价与痛点"}),
                    ),
                    _claim(
                        "core_features",
                        "核心功能",
                        _join_json_list(analysis.get("core_features_json")),
                        evidence_for_claim({"核心功能"}),
                    ),
                    _claim(
                        "pricing",
                        "定价策略",
                        analysis.get("pricing_summary", ""),
                        evidence_for_claim({"价格与商业模式"}),
                    ),
                    _claim(
                        "strengths",
                        "优势",
                        _join_json_list(analysis.get("strengths_json")),
                        evidence_for_claim({"产品定位", "核心功能"}),
                    ),
                    _claim(
                        "weaknesses",
                        "劣势或痛点",
                        _join_json_list(analysis.get("weaknesses_json")),
                        evidence_for_claim({"用户评价与痛点"}),
                    ),
                    _claim(
                        "opportunities",
                        "机会点",
                        _join_json_list(analysis.get("opportunities_json")),
                        evidence_for_claim(set()),
                    ),
                ]
                + _custom_focus_claims(
                    analysis, evidence_by_id, linked_evidence, comp_evidence
                ),
            }
        )
    return bundle


_DIMENSION_ALIASES: dict[str, set[str]] = {
    "产品定位": {"产品定位", "定位", "市场定位", "产品定位与目标用户"},
    "核心功能": {"核心功能", "功能", "产品功能", "功能特性", "核心能力"},
    "价格与商业模式": {
        "价格与商业模式",
        "定价策略",
        "价格",
        "定价",
        "商业模式",
        "收费模式",
    },
    "用户评价与痛点": {"用户评价与痛点", "用户评价", "痛点", "用户反馈", "口碑"},
    "市场信号": {"市场信号", "市场趋势", "市场动态"},
    "风险与机会": {"风险与机会", "风险", "机会", "风险与机遇"},
}


def _dimension_matches_any(dimension: str, preferred: set[str]) -> bool:
    if not dimension or not preferred:
        return False
    dim_stripped = dimension.strip()
    for pref in preferred:
        if dim_stripped == pref:
            return True
        aliases = _DIMENSION_ALIASES.get(pref, set())
        if dim_stripped in aliases:
            return True
        for alias in aliases:
            if alias in dim_stripped or dim_stripped in alias:
                return True
    return False


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
) -> list[dict[str, Any]]:
    claims = []
    for item in parse_focus_analysis_json(analysis.get("custom_focus_analysis_json")):
        label = str(item.get("label") or "").strip()
        if not label:
            continue
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
                "claim_type": f"focus:{item.get('focus_key') or len(claims) + 1}",
                "label": label,
                "text": str(item.get("verdict") or "证据中未涉及"),
                "evidence": deduped_refs,
                "allowed_reference_ids": allowed_ids,
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


def _extract_focus_dimensions(requirement: dict) -> list[dict[str, str]]:
    """Extract ordered dimension list from focus profile for table headers."""
    profile = (
        requirement.get("focus_profile")
        if isinstance(requirement.get("focus_profile"), dict)
        else {}
    )
    if not isinstance(profile, dict):
        return []
    items = []
    for f in (profile.get("explicit_focuses") or []) + (
        profile.get("inferred_focuses") or []
    ):
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
