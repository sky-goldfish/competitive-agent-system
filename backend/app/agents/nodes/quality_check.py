import logging
import json
import re
from typing import Any
from uuid import uuid4

from app.agents.evidence_policy import (
    FIELD_DIMENSION_REQUIREMENTS,
    SCHEMA_FIELDS,
    claim_required_dimensions,
    dimension_matches_any,
    evidence_matches_claim_policy,
    parse_field_evidence_ids,
    parse_item_evidence_bindings,
)
from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)

MAX_FEEDBACK_LOOPS = 3
MAX_ISSUE_VERIFICATION_LOOPS = 2
QA_PASS_THRESHOLD = 0.7
QA_MIN_FORCED_PASS_SCORE = 0.5
VALID_RETRY_SLOTS = {
    "relationship_evidence",
    "positioning",
    "core_features",
    "pricing",
    "user_feedback",
    "market_signal",
    "risk_opportunity",
}

COLLECTION_DIMENSIONS = {"coverage_gaps"}
DIMENSION_SCORE_WEIGHTS = {
    "evidence_grounding": 0.25,
    "citation_accuracy": 0.15,
    "schema_completeness": 0.2,
    "coverage_gaps": 0.2,
    "cross_competitor_consistency": 0.1,
    "factual_plausibility": 0.1,
}

_ANALYSES_CAP = 15
_MIN_EVIDENCE_PER_COMPETITOR = 3
_PASS_DECISIONS = {"pass", "pass_with_quality_warning"}
_OPEN_STATUSES = {"open"}
_NOT_RESOLVED_STATUSES = {"open", "unresolved"}
_SCHEMA_FIELDS = SCHEMA_FIELDS
_FIELD_DIMENSION_REQUIREMENTS = {
    field: dimensions
    for field, dimensions in FIELD_DIMENSION_REQUIREMENTS.items()
    if dimensions
}
_ISSUE_FIELD_HINTS = {
    "定位": "positioning",
    "目标用户": "target_users",
    "核心功能": "core_features_json",
    "功能": "core_features_json",
    "价格": "pricing_summary",
    "定价": "pricing_summary",
    "优势": "strengths_json",
    "劣势": "weaknesses_json",
    "痛点": "weaknesses_json",
    "机会": "opportunities_json",
}
_PLACEHOLDER_MARKERS = (
    "暂无",
    "未涉及",
    "无相关",
    "待补充",
    "占位",
    "mock",
    "n/a",
    "unknown",
)


def quality_check_node(state: AgentState, llm: LLMProvider) -> AgentState:
    current_analyses = _latest_analyses_by_competitor(state.get("analyses", []))
    raw_count = state.get("feedback_loop_count", 0)
    issue_verification_count = state.get("qa_issue_verification_count", 0)
    previous_score = None
    prev_qa = state.get("qa_result")
    if prev_qa and isinstance(prev_qa, dict):
        previous_score = _coerce_score(prev_qa.get("overall_score"))
    checklist = _normalize_checklist(state.get("qa_issue_checklist", []))
    open_issues = _open_issues(checklist)
    unresolved_terminal_issues = _terminal_unresolved_issues(checklist)
    phase = "full_check"
    retry_queries = None
    retry_instructions = None
    feedback_count = raw_count
    forced_pass = False
    dimension_scores: dict[str, float] = {d: 0.0 for d in DIMENSION_SCORE_WEIGHTS}
    overall_score: float = 0.0
    decision = "pass"
    issues: list[dict[str, Any]] = []

    # feedback_loop_count tracks full checks only; issue verification has its own counter.

    if open_issues and not forced_pass:
        phase = "issue_verification"
        if issue_verification_count >= MAX_ISSUE_VERIFICATION_LOOPS:
            logger.info(
                "QA: issue_verification retry limit reached (%d consecutive rounds)",
                issue_verification_count,
            )
            if feedback_count >= MAX_FEEDBACK_LOOPS:
                forced_pass = True
                checklist = _close_open_issues(checklist, feedback_count)
                open_issues = _open_issues(checklist)
                issues = _terminal_unresolved_issues(checklist)
                dimension_scores, overall_score = _recalculate_scores_after_verification(
                    prev_qa, checklist
                )
                decision = _forced_pass_decision(overall_score, checklist)
                logger.info(
                    "QA: finishing after final issue verification group at max full-check loops"
                )
            else:
                open_issues = []
                phase = "full_check"
        else:
            verification_raw = llm.qa_verify_issues(
                _cap_analyses(current_analyses),
                state.get("evidence", []),
                open_issues,
            )
            resolutions = _normalize_issue_resolutions(verification_raw.get("resolutions"))
            checklist = _apply_issue_resolutions(
                checklist,
                resolutions,
                feedback_count,
                current_analyses,
                state.get("evidence", []),
            )
            next_issue_verification_count = issue_verification_count + 1
            open_issues = _open_issues(checklist)
            if open_issues:
                issue_verification_count = next_issue_verification_count
                retry_queries = _retry_queries_from_resolutions(
                    resolutions
                ) or _fallback_retry_queries(open_issues)
                retry_instructions = verification_raw.get(
                    "retry_instructions"
                ) or _retry_instructions_from_issues(open_issues)
                decision = _derive_retry_decision(open_issues)
                issues = open_issues
                dimension_scores, overall_score = _recalculate_scores_after_verification(
                    prev_qa, checklist
                )
                if (
                    feedback_count >= MAX_FEEDBACK_LOOPS
                    and issue_verification_count >= MAX_ISSUE_VERIFICATION_LOOPS
                ):
                    forced_pass = True
                    checklist = _close_open_issues(checklist, feedback_count)
                    open_issues = _open_issues(checklist)
                    issues = _terminal_unresolved_issues(checklist)
                    decision = _forced_pass_decision(overall_score, checklist)
                    retry_queries = None
                    retry_instructions = None
            else:
                if feedback_count >= MAX_FEEDBACK_LOOPS:
                    forced_pass = True
                    issue_verification_count = next_issue_verification_count
                    issues = []
                    dimension_scores, overall_score = _recalculate_scores_after_verification(
                        prev_qa, checklist
                    )
                    decision = _forced_pass_decision(overall_score, checklist)
                    retry_queries = None
                    retry_instructions = None
                else:
                    phase = "full_check"

    if (
        not open_issues
        and unresolved_terminal_issues
        and raw_count >= MAX_FEEDBACK_LOOPS
        and not forced_pass
    ):
        forced_pass = True
        issues = unresolved_terminal_issues
        dimension_scores, overall_score = _recalculate_scores_after_verification(
            prev_qa, checklist
        )
        decision = _forced_pass_decision(overall_score, checklist)
    if not open_issues and not forced_pass:
        feedback_count = raw_count + 1
        issue_verification_count = 0
        qa_raw = llm.qa_check_report(
            _cap_analyses(current_analyses),
            state.get("evidence", []),
        )
        dimension_scores = _normalize_dimension_scores(qa_raw.get("dimension_scores"))
        llm_issues = _normalize_new_issues(qa_raw.get("issues"), feedback_count)
        deterministic_issues = _deterministic_quality_issues(
            current_analyses,
            state.get("evidence", []),
            feedback_count,
        )
        issues = _merge_issues(llm_issues, deterministic_issues)
        dimension_scores = _apply_issue_score_caps(dimension_scores, issues)
        overall_score = _calculate_overall_score(dimension_scores)
        # --- Fix #4: mixed decision — handle both collection and analysis issues ---
        decision = _derive_decision(overall_score, dimension_scores, issues)
        checklist = _reconcile_checklist_after_full_check(
            checklist,
            issues,
            feedback_count,
            current_analyses,
            state.get("evidence", []),
        )
        issues = _visible_unresolved_issues(checklist)
        dimension_scores = _apply_issue_score_caps(
            _normalize_dimension_scores(qa_raw.get("dimension_scores")),
            issues,
        )
        overall_score = _calculate_overall_score(dimension_scores)
        decision = _derive_decision(overall_score, dimension_scores, issues)
        retry_queries = qa_raw.get("retry_queries") if decision != "pass" else None
        retry_instructions = (
            qa_raw.get("retry_instructions") if decision != "pass" else None
        )
        if (
            decision != "pass"
            and previous_score is not None
            and overall_score <= previous_score
            and feedback_count < MAX_FEEDBACK_LOOPS
        ):
            logger.info(
                "QA: score did not improve (%.2f <= %.2f); continuing within retry budget",
                overall_score,
                previous_score,
            )
    elif forced_pass:
        pass

    issues = _merge_issue_records(issues, _visible_unresolved_issues(checklist))
    blocking_unresolved = [
        issue
        for issue in issues
        if issue.get("severity") in {"critical", "major"}
        and issue.get("status") in _NOT_RESOLVED_STATUSES
    ]
    if decision == "pass" and blocking_unresolved:
        if forced_pass or feedback_count >= MAX_FEEDBACK_LOOPS:
            decision = "pass_with_quality_warning"
            issues = _merge_issue_records(issues, blocking_unresolved)
            retry_queries = None
            retry_instructions = None
        else:
            issues = _merge_issue_records(issues, blocking_unresolved)
            decision = _derive_retry_decision(blocking_unresolved)
            retry_instructions = _retry_instructions_from_issues(blocking_unresolved)

    retry_guidance_map = None
    retry_analysis_ids = None
    retry_analysis_guidance = None
    repair_tasks = None
    bad_evidence_ids = None
    if decision == "retry_collection":
        retry_queries = _normalize_retry_queries(
            retry_queries
        ) or _fallback_retry_queries(issues)
        retry_guidance_map = _build_retry_guidance_map(issues)
        retry_analysis_guidance = retry_instructions
        repair_tasks = _build_repair_tasks(issues, current_analyses)
        bad_evidence_ids = _identify_bad_evidence_ids(issues, state.get("evidence", []))
    elif decision == "retry_analysis":
        retry_guidance_map = _build_retry_guidance_map(issues)
        retry_analysis_ids = _identify_retry_analyses(issues, current_analyses)
        retry_analysis_guidance = retry_instructions
        repair_tasks = _build_repair_tasks(issues, current_analyses)
        bad_evidence_ids = _identify_bad_evidence_ids(issues, state.get("evidence", []))
    elif decision == "retry_collection_and_analysis":
        retry_queries = _normalize_retry_queries(
            retry_queries
        ) or _fallback_retry_queries(issues)
        retry_guidance_map = _build_retry_guidance_map(issues)
        retry_analysis_ids = _identify_retry_analyses(
            [i for i in issues if i.get("dimension") not in COLLECTION_DIMENSIONS],
            current_analyses,
        )
        retry_analysis_guidance = retry_instructions
        repair_tasks = _build_repair_tasks(issues, current_analyses)
        bad_evidence_ids = _identify_bad_evidence_ids(issues, state.get("evidence", []))

    quality_warning = (
        decision == "pass_with_quality_warning"
        or forced_pass
        or _has_unresolved_blocking_issues(checklist)
        or any(score < QA_PASS_THRESHOLD for score in dimension_scores.values())
    )
    final_issues = _merge_issue_records(issues, _visible_unresolved_issues(checklist))

    qa_result: dict[str, Any] = {
        "overall_score": overall_score,
        "dimension_scores": dimension_scores,
        "decision": decision,
        "retry_instructions": retry_instructions,
        "issues": final_issues,
        "issue_checklist": checklist,
        "check_phase": phase,
        "iteration": feedback_count,
        "forced_pass": forced_pass,
        "quality_warning": quality_warning,
        "previous_score": previous_score,
    }

    logger.info(
        "QA iteration %d: score=%.2f decision=%s issues=%d forced_pass=%s",
        feedback_count,
        overall_score,
        decision,
        len(issues),
        forced_pass,
    )

    new_state: dict[str, Any] = {
        **state,
        "qa_result": qa_result,
        "qa_issue_checklist": checklist,
        "qa_issue_verification_count": issue_verification_count,
        "feedback_loop_count": feedback_count,
    }
    for stale_key in (
        "qa_retry_guidance_map",
        "qa_retry_queries",
        "qa_retry_analysis_ids",
        "qa_analysis_guidance",
        "qa_repair_tasks",
        "qa_bad_evidence_ids",
    ):
        new_state.pop(stale_key, None)
    if retry_guidance_map is not None:
        new_state["qa_retry_guidance_map"] = retry_guidance_map
    if retry_queries is not None:
        new_state["qa_retry_queries"] = retry_queries
    if retry_analysis_ids is not None:
        new_state["qa_retry_analysis_ids"] = retry_analysis_ids
    if retry_analysis_guidance is not None:
        new_state["qa_analysis_guidance"] = retry_analysis_guidance
    if repair_tasks is not None:
        new_state["qa_repair_tasks"] = repair_tasks
    if bad_evidence_ids is not None:
        new_state["qa_bad_evidence_ids"] = bad_evidence_ids
    return new_state  # type: ignore[return-value]


def qa_route(state: AgentState) -> str:
    qa_result = state.get("qa_result", {})
    if not isinstance(qa_result, dict):
        return "end"
    decision = qa_result.get("decision", "pass")
    if decision == "retry_collection":
        return "retry_collection"
    if decision == "retry_analysis":
        return "retry_analysis"
    if decision == "retry_collection_and_analysis":
        return "retry_collection_and_analysis"
    if decision not in _PASS_DECISIONS:
        logger.warning("Unknown QA decision '%s', treating as end", decision)
    return "end"


def _derive_decision(
    overall_score: float,
    dimension_scores: dict[str, float],
    issues: list[dict[str, Any]],
) -> str:
    if overall_score >= 0.85 and issues and all(
        issue.get("severity") == "minor" for issue in issues
    ):
        return "pass"
    has_collection_issue = any(
        issue.get("dimension") in COLLECTION_DIMENSIONS for issue in issues
    )
    has_analysis_issue = any(
        issue.get("dimension") not in COLLECTION_DIMENSIONS
        and issue.get("competitor_name") not in {"system", None}
        for issue in issues
    )
    if has_collection_issue and has_analysis_issue:
        return "retry_collection_and_analysis"
    if has_collection_issue:
        return "retry_collection"
    if _has_blocking_analysis_issue(issues):
        return "retry_analysis"
    all_dimensions_pass = all(
        score >= QA_PASS_THRESHOLD for score in dimension_scores.values()
    )
    if all_dimensions_pass and overall_score >= QA_MIN_FORCED_PASS_SCORE:
        return "pass"
    if has_analysis_issue:
        return "retry_analysis"
    if all_dimensions_pass and overall_score < QA_MIN_FORCED_PASS_SCORE:
        return "retry_collection"
    return "retry_collection"


def _derive_retry_decision(issues: list[dict[str, Any]]) -> str:
    has_collection_issue = any(
        issue.get("dimension") in COLLECTION_DIMENSIONS for issue in issues
    )
    has_analysis_issue = any(
        issue.get("dimension") not in COLLECTION_DIMENSIONS
        and issue.get("competitor_name") not in {"system", None}
        for issue in issues
    )
    if has_collection_issue and has_analysis_issue:
        return "retry_collection_and_analysis"
    if has_collection_issue:
        return "retry_collection"
    if has_analysis_issue:
        return "retry_analysis"
    return "retry_collection"


def _normalize_new_issues(raw_issues: Any, iteration: int) -> list[dict[str, Any]]:
    if not isinstance(raw_issues, list):
        return []
    issues = []
    for raw in raw_issues:
        if not isinstance(raw, dict):
            continue
        description = str(raw.get("description") or "").strip()
        fix_suggestion = str(raw.get("fix_suggestion") or "").strip()
        if not description and not fix_suggestion:
            continue
        issue = {
            "id": str(raw.get("id") or f"qai_{uuid4().hex[:12]}"),
            "source": str(raw.get("source") or "llm"),
            "dimension": str(raw.get("dimension") or "unknown"),
            "severity": _normalize_severity(raw.get("severity")),
            "competitor_name": str(raw.get("competitor_name") or "system"),
            "description": description,
            "fix_suggestion": fix_suggestion,
            "status": "open",
            "first_seen_iteration": int(
                raw.get("first_seen_iteration") or iteration
            ),
            "last_seen_iteration": iteration,
            "resolved_iteration": None,
            "resolution_reason": None,
        }
        for key in (
            "fields",
            "bad_evidence_ids",
            "required_evidence_ids",
            "preferred_evidence_ids",
            "suggested_evidence_ids",
            "forbidden_evidence_ids",
            "must_remove_evidence_ids",
        ):
            if key in raw and isinstance(raw.get(key), list):
                issue[key] = [str(value) for value in raw.get(key) if value]
        for key in ("claim", "issue_type", "verification_mode"):
            if raw.get(key):
                issue[key] = str(raw.get(key))
        issues.append(_enrich_issue_metadata(issue))
    return issues


def _normalize_checklist(raw_checklist: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_checklist, list):
        return []
    issues = []
    for raw in raw_checklist:
        if not isinstance(raw, dict):
            continue
        normalized = _normalize_new_issues(
            [raw], int(raw.get("first_seen_iteration") or 1)
        )
        if not normalized:
            continue
        issue = normalized[0]
        issue["status"] = (
            raw.get("status")
            if raw.get("status") in {"open", "resolved", "stale", "superseded", "unresolved"}
            else "open"
        )
        issue["last_seen_iteration"] = int(
            raw.get("last_seen_iteration") or issue["first_seen_iteration"]
        )
        issue["resolved_iteration"] = raw.get("resolved_iteration")
        issue["resolution_reason"] = raw.get("resolution_reason")
        issues.append(_enrich_issue_metadata(issue))
    return issues


def _enrich_issue_metadata(issue: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(issue)
    fields = _fields_for_issue(enriched)
    if fields:
        enriched["fields"] = fields
    bad_ids = sorted(
        set(enriched.get("bad_evidence_ids") or [])
        | set(enriched.get("forbidden_evidence_ids") or [])
        | _evidence_ids_requiring_removal(enriched)
    )
    if bad_ids:
        enriched["bad_evidence_ids"] = bad_ids
        enriched["forbidden_evidence_ids"] = bad_ids
        enriched["must_remove_evidence_ids"] = bad_ids
    preferred_ids = sorted(
        set(enriched.get("preferred_evidence_ids") or [])
        | set(enriched.get("suggested_evidence_ids") or [])
        | _evidence_ids_preferred_for_use(enriched)
    )
    if preferred_ids:
        enriched["preferred_evidence_ids"] = preferred_ids
    required_ids = sorted(
        set(enriched.get("required_evidence_ids") or [])
        | _evidence_ids_required_for_use(enriched)
    )
    if required_ids:
        enriched["required_evidence_ids"] = required_ids
    enriched.setdefault("issue_type", _infer_issue_type(enriched))
    enriched.setdefault(
        "verification_mode", _verification_mode_for_issue_type(enriched["issue_type"])
    )
    return enriched


def _infer_issue_type(issue: dict[str, Any]) -> str:
    text = f"{issue.get('description', '')} {issue.get('fix_suggestion', '')}"
    dimension = issue.get("dimension")
    issue_id = str(issue.get("id") or "")
    if dimension == "coverage_gaps":
        return "coverage_gap"
    if dimension == "schema_completeness" or _issue_mentions_absent_or_placeholder(issue):
        return "placeholder_content"
    if issue_id.startswith("det_item_ev_") or "item_evidence_bindings_json" in text or "条目级" in text:
        return "missing_item_binding"
    if "field_evidence_ids_json" in text or "字段级证据绑定" in text:
        return "missing_field_binding"
    if "未发现明显" in text and ("劣势" in text or "痛点" in text):
        return "stale_claim"
    if _evidence_ids_requiring_removal(issue) or any(
        marker in text
        for marker in ("不能支撑", "无法支撑", "不支撑", "正面用户评价", "不匹配")
    ):
        return "bad_evidence_binding"
    if dimension == "factual_plausibility" or "矛盾" in text:
        return "factual_contradiction"
    if dimension == "cross_competitor_consistency":
        return "consistency_gap"
    return "generic"


def _verification_mode_for_issue_type(issue_type: str) -> str:
    if issue_type in {
        "coverage_gap",
        "placeholder_content",
        "missing_field_binding",
        "missing_item_binding",
        "stale_claim",
    }:
        return "rule"
    if issue_type == "bad_evidence_binding":
        return "hybrid"
    if issue_type in {"factual_contradiction", "consistency_gap"}:
        return "semantic"
    return "hybrid"


def _normalize_issue_resolutions(raw_resolutions: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_resolutions, list):
        return []
    resolutions = []
    for raw in raw_resolutions:
        if not isinstance(raw, dict):
            continue
        issue_id = str(raw.get("issue_id") or raw.get("id") or "").strip()
        if not issue_id:
            continue
        status = str(raw.get("status") or "").strip()
        if status not in {"resolved", "open", "still_open"}:
            status = "open"
        resolutions.append(
            {
                "issue_id": issue_id,
                "status": "open" if status == "still_open" else status,
                "resolution_reason": str(
                    raw.get("resolution_reason") or raw.get("reason") or ""
                ).strip(),
                "retry_queries": _normalize_retry_queries(raw.get("retry_queries")),
            }
        )
    return resolutions


def _apply_issue_resolutions(
    checklist: list[dict[str, Any]],
    resolutions: list[dict[str, Any]],
    iteration: int,
    analyses: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    resolution_by_id = {item["issue_id"]: item for item in resolutions}
    updated = []
    for issue in checklist:
        if issue.get("status") not in _OPEN_STATUSES:
            updated.append(issue)
            continue
        resolution = resolution_by_id.get(str(issue.get("id")))
        accepted, rejection_reason = _accept_issue_resolution(
            issue,
            resolution,
            analyses or [],
            evidence or [],
        )
        if _coverage_issue_has_sufficient_evidence(issue, evidence or []):
            updated.append(
                {
                    **issue,
                    "status": "resolved",
                    "last_seen_iteration": iteration,
                    "resolved_iteration": iteration,
                    "resolution_reason": (
                        "系统复核确认：采集证据库已满足覆盖要求；"
                        "结构化分析允许选择部分代表性证据"
                    ),
                }
            )
        elif resolution and resolution["status"] == "resolved" and accepted:
            updated.append(
                {
                    **issue,
                    "status": "resolved",
                    "last_seen_iteration": iteration,
                    "resolved_iteration": iteration,
                    "resolution_reason": resolution.get("resolution_reason")
                    or "质检复核确认已解决",
                }
            )
        else:
            updated.append(
                {
                    **issue,
                    "status": "open",
                    "last_seen_iteration": iteration,
                    "resolution_reason": rejection_reason
                    or (resolution or {}).get("resolution_reason")
                    or issue.get("resolution_reason"),
                }
            )
    return updated


def _reconcile_checklist_after_full_check(
    checklist: list[dict[str, Any]],
    current_issues: list[dict[str, Any]],
    iteration: int,
    analyses: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issue_by_id = {str(issue.get("id") or ""): issue for issue in current_issues}
    current_keys = {
        _issue_match_key(issue): issue for issue in current_issues
    }
    updated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for issue in checklist:
        issue_id = str(issue.get("id") or "")
        seen_ids.add(issue_id)
        if issue.get("status") not in _NOT_RESOLVED_STATUSES:
            updated.append(issue)
            continue

        current = issue_by_id.get(issue_id) or current_keys.get(_issue_match_key(issue))
        if current is not None:
            merged_issue = _enrich_issue_metadata(
                {
                    **issue,
                    **current,
                    "id": issue_id or current.get("id"),
                    "first_seen_iteration": issue.get("first_seen_iteration")
                    or current.get("first_seen_iteration"),
                    "last_seen_iteration": iteration,
                    "resolved_iteration": None,
                }
            )
            resolved, reason = _deterministically_resolve_stale_issue(
                merged_issue, analyses, evidence
            )
            if resolved:
                updated.append(
                    {
                        **merged_issue,
                        "status": "resolved",
                        "last_seen_iteration": iteration,
                        "resolved_iteration": iteration,
                        "resolution_reason": reason,
                    }
                )
                continue
            updated.append(
                {
                    **merged_issue,
                    "status": "open",
                    "last_seen_iteration": iteration,
                    "resolved_iteration": None,
                }
            )
            continue

        resolved, reason = _deterministically_resolve_stale_issue(
            issue, analyses, evidence
        )
        if resolved:
            updated.append(
                {
                    **issue,
                    "status": "resolved",
                    "last_seen_iteration": iteration,
                    "resolved_iteration": iteration,
                    "resolution_reason": reason,
                }
            )
        else:
            updated.append(
                {**issue, "status": "unresolved", "last_seen_iteration": iteration}
            )

    for issue in current_issues:
        issue_id = str(issue.get("id") or "")
        if issue_id and issue_id in seen_ids:
            continue
        if _issue_match_key(issue) in {_issue_match_key(item) for item in updated}:
            continue
        updated.append(issue)
    return updated


def _issue_match_key(issue: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(issue.get("dimension") or ""),
        str(issue.get("competitor_name") or ""),
        _normalize_issue_text(str(issue.get("description") or "")),
    )


def _deterministically_resolve_stale_issue(
    issue: dict[str, Any],
    analyses: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    if _coverage_issue_has_sufficient_evidence(issue, evidence):
        return (
            True,
            "系统复核确认：采集证据库已满足覆盖要求；结构化分析允许选择部分代表性证据",
        )

    analysis = _analysis_for_issue(issue, analyses)
    if not analysis:
        return False, None

    issue_type = str(issue.get("issue_type") or _infer_issue_type(issue))
    if issue_type == "stale_claim" and _stale_claim_no_longer_present(issue, analysis):
        return (
            True,
            "系统复核确认：原问题指向的旧结论已不存在，最新字段已改为实质分析。",
        )

    consistency_resolved, consistency_reason = _deterministically_resolve_consistency_issue(
        issue, analysis
    )
    if consistency_resolved:
        return True, consistency_reason

    item_resolved, item_reason = _deterministically_resolve_item_binding_issue(
        issue, analysis, evidence
    )
    if item_resolved:
        return True, item_reason

    fields = _fields_for_issue(issue)
    dimension = issue.get("dimension")
    if not fields:
        if dimension == "schema_completeness":
            fields = list(_SCHEMA_FIELDS)
        elif dimension in {"evidence_grounding", "factual_plausibility"}:
            fields = _fields_from_text(issue) or ["weaknesses_json"]
        elif dimension == "cross_competitor_consistency":
            fields = _fields_from_text(issue)

    if fields and any(_is_empty_or_placeholder(analysis.get(field)) for field in fields):
        return False, None

    binding_resolved, binding_reason = _deterministically_resolve_bad_binding_issue(
        issue,
        analysis,
        fields,
        evidence,
    )
    if binding_resolved:
        return True, binding_reason

    if (
        dimension in {"evidence_grounding", "factual_plausibility"}
        and fields
        and not _analysis_has_matching_field_evidence(analysis, fields, evidence)
    ):
        return False, None

    if (
        dimension == "citation_accuracy"
        and fields
        and _issue_mentions_field_evidence_binding(issue)
        and _analysis_has_matching_field_evidence(analysis, fields, evidence)
    ):
        return (
            True,
            "系统复核确认：最新结构化分析已具备对应字段的有效证据绑定。",
        )

    if fields and _issue_mentions_absent_or_placeholder(issue):
        return (
            True,
            "系统复核确认：最新结构化分析已补齐相关字段，不再使用占位或“无”表述。",
        )

    return False, None


def _deterministically_resolve_consistency_issue(
    issue: dict[str, Any], analysis: dict[str, Any]
) -> tuple[bool, str | None]:
    if str(issue.get("issue_type") or _infer_issue_type(issue)) != "consistency_gap":
        return False, None
    if issue.get("dimension") != "cross_competitor_consistency":
        return False, None

    text = f"{issue.get('description', '')} {issue.get('fix_suggestion', '')}"
    if not any(
        marker in text
        for marker in (
            "简略",
            "深度不足",
            "仅列",
            "仅写",
            "补充",
            "扩展",
            "不充分",
            "不够充分",
        )
    ):
        return False, None

    fields = _fields_for_issue(issue)
    if not fields:
        return False, None

    insufficient: list[str] = []
    for field in fields:
        if field not in _SCHEMA_FIELDS:
            continue
        claims = _field_claims(analysis.get(field))
        required_count = _consistency_required_claim_count(field, text)
        if len(claims) < required_count:
            insufficient.append(
                f"{_SCHEMA_FIELDS.get(field, field)}={len(claims)}/{required_count}"
            )
    if insufficient:
        return False, None
    return (
        True,
        "系统复核确认：最新结构化分析已补足原问题指出的信息深度不足字段。",
    )


def _consistency_required_claim_count(field: str, issue_text: str) -> int:
    if field == "core_features_json":
        return 4
    if field == "target_users":
        return 2
    if field in {"strengths_json", "weaknesses_json", "opportunities_json"}:
        return 2
    return 1


def _stale_claim_no_longer_present(
    issue: dict[str, Any], analysis: dict[str, Any]
) -> bool:
    fields = _fields_for_issue(issue) or ["weaknesses_json"]
    old_claim = str(issue.get("claim") or "").strip()
    issue_text = f"{issue.get('description', '')} {issue.get('fix_suggestion', '')}"
    stale_markers = ("未发现明显", "未发现劣势", "未发现明显劣势", "未发现明显的劣势")
    if old_claim:
        stale_markers = (*stale_markers, old_claim)
    for field in fields:
        claims = _field_claims(analysis.get(field))
        if not claims:
            return False
        current_text = " ".join(claims)
        if any(marker and marker in current_text for marker in stale_markers):
            return False
        if "未发现明显" in issue_text and claims:
            return True
    return False


def _deterministically_resolve_bad_binding_issue(
    issue: dict[str, Any],
    analysis: dict[str, Any],
    fields: list[str],
    evidence: list[dict[str, Any]],
    *,
    require_expected: bool = True,
) -> tuple[bool, str | None]:
    bad_ids = set(issue.get("bad_evidence_ids") or []) | set(
        issue.get("forbidden_evidence_ids") or []
    )
    preferred_ids = set(issue.get("preferred_evidence_ids") or []) | set(
        issue.get("suggested_evidence_ids") or []
    )
    required_ids = set(issue.get("required_evidence_ids") or [])
    if not bad_ids and not preferred_ids and not required_ids:
        return False, None
    referenced = _analysis_field_evidence_ids(analysis, fields)
    if bad_ids and bad_ids & referenced:
        return False, None
    expected = required_ids or preferred_ids
    if require_expected and expected and not expected & referenced:
        return False, None
    if fields and not _analysis_has_matching_field_evidence(analysis, fields, evidence):
        return False, None
    return (
        True,
        "系统复核确认：错误证据已移除，且最新字段已绑定可支撑该结论的证据。",
    )


def _analysis_field_evidence_ids(analysis: dict[str, Any], fields: list[str]) -> set[str]:
    result: set[str] = set()
    field_evidence_ids = parse_field_evidence_ids(
        _parse_json_dict(analysis.get("field_evidence_ids_json"))
    )
    item_bindings = parse_item_evidence_bindings(
        _parse_json_dict(analysis.get("item_evidence_bindings_json"))
    )
    for field in fields:
        result.update(field_evidence_ids.get(field, []))
        for row in item_bindings.get(field, []):
            result.update(str(eid) for eid in row.get("evidence_ids") or [] if eid)
    return result


def _deterministically_resolve_item_binding_issue(
    issue: dict[str, Any],
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    parsed = _item_issue_field_and_index(issue)
    if not parsed:
        return False, None
    field, item_index = parsed
    claims = _field_claims(analysis.get(field))
    if item_index >= len(claims):
        return (
            True,
            "系统复核确认：原问题指向的条目在最新结构化分析中已不存在。",
        )
    if _analysis_item_has_valid_binding(analysis, field, item_index, evidence):
        return (
            True,
            "系统复核确认：最新结构化分析中该条目已有有效证据绑定。",
        )
    issue_claim = str(issue.get("claim") or "")
    if issue_claim and not _task_claim_matches_for_qa(claims[item_index], issue_claim):
        all_bound = all(
            _analysis_item_has_valid_binding(analysis, field, idx, evidence)
            for idx in range(len(claims))
        )
        if all_bound:
            return (
                True,
                "系统复核确认：原问题指向的结论已被改写，最新条目均已有有效证据绑定。",
            )
    return False, None


def _item_issue_field_and_index(issue: dict[str, Any]) -> tuple[str, int] | None:
    issue_id = str(issue.get("id") or "")
    for field in _SCHEMA_FIELDS:
        match = re.search(rf"_{re.escape(field)}_(\d+)$", issue_id)
        if match:
            return field, int(match.group(1))
    return None


def _analysis_item_has_valid_binding(
    analysis: dict[str, Any],
    field: str,
    item_index: int,
    evidence: list[dict[str, Any]],
) -> bool:
    evidence_by_id = {str(item.get("id")): item for item in evidence if item.get("id")}
    item_bindings = parse_item_evidence_bindings(
        _parse_json_dict(analysis.get("item_evidence_bindings_json"))
    )
    rows = item_bindings.get(field, [])
    row_by_index = {
        int(row.get("item_index") or index): row for index, row in enumerate(rows)
    }
    row = row_by_index.get(item_index)
    if not row:
        return False
    claims = _field_claims(analysis.get(field))
    if item_index >= len(claims):
        return False
    competitor_id = str(analysis.get("competitor_id") or "")
    competitor_name = str(analysis.get("competitor_name") or "")
    for evidence_id in row.get("evidence_ids") or []:
        eid = str(evidence_id)
        item = evidence_by_id.get(eid)
        if (
            item
            and _evidence_belongs_to_competitor(item, competitor_id, competitor_name)
            and evidence_matches_claim_policy(item, field, claims[item_index], evidence)
        ):
            return True
    return False


def _task_claim_matches_for_qa(claim: str, task_claim: str) -> bool:
    claim_tokens = _qa_claim_tokens(claim)
    task_tokens = _qa_claim_tokens(task_claim)
    if not claim_tokens or not task_tokens:
        return True
    return len(claim_tokens & task_tokens) >= 2


def _qa_claim_tokens(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", str(text or "").lower())
    tokens = set(re.findall(r"[a-z0-9]{3,}", normalized))
    for index in range(max(0, len(normalized) - 1)):
        tokens.add(normalized[index : index + 2])
    return tokens


def _issue_mentions_field_evidence_binding(issue: dict[str, Any]) -> bool:
    text = f"{issue.get('description', '')} {issue.get('fix_suggestion', '')}"
    return "field_evidence_ids_json" in text or "字段级证据绑定" in text


def _analysis_has_matching_field_evidence(
    analysis: dict[str, Any], fields: list[str], evidence: list[dict[str, Any]]
) -> bool:
    evidence_by_id = {str(item.get("id")): item for item in evidence if item.get("id")}
    item_bindings = parse_item_evidence_bindings(
        _parse_json_dict(analysis.get("item_evidence_bindings_json"))
    )
    field_evidence_ids = parse_field_evidence_ids(
        _parse_json_dict(analysis.get("field_evidence_ids_json"))
    )
    global_referenced_ids = _parse_evidence_ids(analysis.get("evidence_ids_json"))
    for field in fields:
        if field == "opportunities_json":
            continue
        dimensions = _FIELD_DIMENSION_REQUIREMENTS.get(field)
        if not dimensions:
            continue
        required_dimensions = claim_required_dimensions(
            field,
            _field_claims(analysis.get(field)),
            evidence,
        ) or dimensions
        item_ids = {
            evidence_id
            for row in item_bindings.get(field, [])
            for evidence_id in (row.get("evidence_ids") or [])
        }
        if item_ids:
            if not any(
                eid in evidence_by_id
                and evidence_matches_claim_policy(
                    evidence_by_id[eid],
                    field,
                    _field_claims(analysis.get(field)),
                    evidence,
                )
                and _dimension_matches_any(
                    evidence_by_id[eid].get("related_dimension"), required_dimensions
                )
                for eid in item_ids
            ):
                return False
            continue
        referenced_ids = set(field_evidence_ids.get(field, [])) or global_referenced_ids
        if not referenced_ids:
            return False
        if not any(
            eid in evidence_by_id
            and evidence_matches_claim_policy(
                evidence_by_id[eid],
                field,
                _field_claims(analysis.get(field)),
                evidence,
            )
            and _dimension_matches_any(
                evidence_by_id[eid].get("related_dimension"), required_dimensions
            )
            for eid in referenced_ids
        ):
            return False
    return True


def _coverage_issue_has_sufficient_evidence(
    issue: dict[str, Any], evidence: list[dict[str, Any]]
) -> bool:
    if issue.get("dimension") != "coverage_gaps":
        return False
    competitor_name = str(issue.get("competitor_name") or "")
    if not competitor_name:
        return False
    required_dimensions = _coverage_dimensions_for_issue(issue)
    counts = _evidence_counts_for_competitor(evidence, competitor_name)
    return all(
        counts.get(label, 0) >= _MIN_EVIDENCE_PER_COMPETITOR
        for label in required_dimensions
    )


def _close_open_issues(
    checklist: list[dict[str, Any]], iteration: int
) -> list[dict[str, Any]]:
    """Mark remaining open issues as unresolved rather than silently dropping them."""
    updated = []
    for issue in checklist:
        if issue.get("status") in _OPEN_STATUSES:
            updated.append(
                {**issue, "status": "unresolved", "last_seen_iteration": iteration}
            )
        else:
            updated.append(issue)
    return updated


def _open_issues(checklist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        issue
        for issue in checklist
        if issue.get("status") in _OPEN_STATUSES
    ]


def _terminal_unresolved_issues(checklist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [issue for issue in checklist if issue.get("status") == "unresolved"]


def _visible_unresolved_issues(checklist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        issue
        for issue in checklist
        if issue.get("status") in _NOT_RESOLVED_STATUSES
    ]


def _merge_issue_records(
    primary: list[dict[str, Any]], secondary: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue in [*primary, *secondary]:
        issue_id = str(issue.get("id") or "")
        key = issue_id or "|".join(
            [
                str(issue.get("dimension") or ""),
                str(issue.get("competitor_name") or ""),
                _normalize_issue_text(str(issue.get("description") or "")),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(issue)
    return merged


def _normalize_retry_queries(raw_queries: Any) -> list[dict[str, str]]:
    if not isinstance(raw_queries, list):
        return []
    queries = []
    for raw in raw_queries:
        if not isinstance(raw, dict):
            continue
        competitor_name = str(raw.get("competitor_name") or "").strip()
        query = str(raw.get("query") or "").strip()
        if not competitor_name or not query:
            continue
        for slot in _normalize_retry_slots(raw.get("slot")):
            queries.append(
                {"competitor_name": competitor_name, "slot": slot, "query": query}
            )
    return queries


def _normalize_retry_slots(raw_slot: Any) -> list[str]:
    raw_text = str(raw_slot or "core_features").strip()
    parts = [
        part.strip()
        for part in raw_text.replace("，", ",").replace("/", ",").split(",")
        if part.strip()
    ]
    slots = [_map_retry_slot(part) for part in (parts or [raw_text])]
    deduped = []
    for slot in slots:
        if slot not in deduped:
            deduped.append(slot)
    return deduped or ["core_features"]


def _map_retry_slot(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in VALID_RETRY_SLOTS:
        return normalized
    if any(keyword in value for keyword in ["关系", "竞品关系", "重叠", "替代"]):
        return "relationship_evidence"
    if any(keyword in value for keyword in ["定位", "场景", "用户", "适配", "落地"]):
        return "positioning"
    if any(keyword in value for keyword in ["价格", "定价", "商业", "收费", "pricing"]):
        return "pricing"
    if any(keyword in value for keyword in ["评价", "反馈", "痛点", "口碑", "review"]):
        return "user_feedback"
    if any(keyword in value for keyword in ["市场", "增长", "融资", "新闻", "趋势"]):
        return "market_signal"
    if any(
        keyword in value for keyword in ["风险", "机会", "优势", "劣势", "问题", "缺点"]
    ):
        return "risk_opportunity"
    if any(keyword in value for keyword in ["功能", "能力", "特性", "feature", "core"]):
        return "core_features"
    return "core_features"


def _retry_queries_from_resolutions(
    resolutions: list[dict[str, Any]],
) -> list[dict[str, str]]:
    queries = []
    for resolution in resolutions:
        queries.extend(resolution.get("retry_queries") or [])
    return queries


def _fallback_retry_queries(issues: list[dict[str, Any]]) -> list[dict[str, str]]:
    queries = []
    for issue in issues:
        competitor_name = issue.get("competitor_name")
        if not competitor_name or competitor_name == "system":
            continue
        dimension = issue.get("dimension")
        is_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in competitor_name)
        if dimension in {"coverage_gaps", "evidence_grounding"}:
            if is_cjk:
                queries.append(
                    {
                        "competitor_name": competitor_name,
                        "slot": "core_features",
                        "query": f"{competitor_name} 核心功能 特点",
                    }
                )
                queries.append(
                    {
                        "competitor_name": competitor_name,
                        "slot": "pricing",
                        "query": f"{competitor_name} 价格 套餐 收费",
                    }
                )
            else:
                queries.append(
                    {
                        "competitor_name": competitor_name,
                        "slot": "core_features",
                        "query": f"{competitor_name} core features evidence",
                    }
                )
                queries.append(
                    {
                        "competitor_name": competitor_name,
                        "slot": "pricing",
                        "query": f"{competitor_name} pricing plans evidence",
                    }
                )
        elif dimension == "schema_completeness":
            if is_cjk:
                queries.append(
                    {
                        "competitor_name": competitor_name,
                        "slot": "pricing",
                        "query": f"{competitor_name} 价格 定价方案",
                    }
                )
            else:
                queries.append(
                    {
                        "competitor_name": competitor_name,
                        "slot": "pricing",
                        "query": f"{competitor_name} pricing plans",
                    }
                )
    return queries


def _retry_instructions_from_issues(issues: list[dict[str, Any]]) -> str | None:
    suggestions = [
        issue.get("fix_suggestion") for issue in issues if issue.get("fix_suggestion")
    ]
    return "; ".join(suggestions) if suggestions else None


def _normalize_severity(value: Any) -> str:
    severity = str(value or "").strip()
    return severity if severity in {"critical", "major", "minor"} else "major"


def _accept_issue_resolution(
    issue: dict[str, Any],
    resolution: dict[str, Any] | None,
    analyses: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    if not resolution or resolution.get("status") != "resolved":
        return False, None
    dimension = issue.get("dimension")
    competitor_name = str(issue.get("competitor_name") or "")
    analysis = _analysis_for_issue(issue, analyses)
    checked = False

    if dimension == "schema_completeness" and analysis:
        checked = True
        fields = _fields_for_issue(issue)
        if not fields:
            fields = list(_SCHEMA_FIELDS)
        missing = [
            _SCHEMA_FIELDS.get(field, field)
            for field in fields
            if _is_empty_or_placeholder(analysis.get(field))
        ]
        if missing:
            return (
                False,
                f"系统复核未通过：字段仍为空或占位：{', '.join(missing)}",
            )

    if dimension == "citation_accuracy" and analysis:
        checked = True
        fields = _fields_for_issue(issue)
        binding_resolved, _binding_reason = _deterministically_resolve_bad_binding_issue(
            issue,
            analysis,
            fields,
            evidence,
            require_expected=False,
        )
        if binding_resolved:
            return True, None
        bad_ids = _reference_ids_requiring_removal(issue)
        if bad_ids:
            referenced = _analysis_reference_ids(analysis, evidence)
            still_used = sorted(bad_ids & referenced)
            if still_used:
                return (
                    False,
                    "系统复核未通过：分析仍引用被质检标记的问题证据 "
                    + ", ".join(f"[{ref}]" for ref in still_used),
                )

    if dimension == "coverage_gaps":
        checked = True
        required_dimensions = _coverage_dimensions_for_issue(issue)
        counts = _evidence_counts_for_competitor(evidence, competitor_name)
        weak_dimensions = [
            label
            for label in required_dimensions
            if counts.get(label, 0) < _MIN_EVIDENCE_PER_COMPETITOR
        ]
        if weak_dimensions:
            return (
                False,
                "系统复核未通过：有效证据仍不足："
                + ", ".join(
                    f"{label}={counts.get(label, 0)}" for label in weak_dimensions
                ),
            )
        if resolution.get("status") == "resolved":
            return True, None

    if dimension == "evidence_grounding" and analysis:
        checked = True
        resolved, _reason = _deterministically_resolve_stale_issue(
            issue, analyses, evidence
        )
        if resolved:
            return True, None
        bad_ids = _reference_ids_requiring_removal(issue)
        if bad_ids and bad_ids & _analysis_reference_ids(analysis, evidence):
            return False, "系统复核未通过：问题证据仍在分析引用中"
        bad_evidence_ids = _evidence_ids_requiring_removal(issue)
        if bad_evidence_ids and bad_evidence_ids & _all_analysis_evidence_ids(analysis):
            return False, "系统复核未通过：问题 evidence_id 仍在分析引用中"
        fields = _fields_for_issue(issue)
        if fields and not _analysis_has_matching_field_evidence(
            analysis, fields, evidence
        ):
            return False, "系统复核未通过：相关字段仍缺少有效证据绑定"

    if dimension == "cross_competitor_consistency" and analysis:
        checked = True
        resolved, _reason = _deterministically_resolve_consistency_issue(
            issue, analysis
        )
        if resolved:
            return True, None
        return False, "系统复核未通过：原问题指出的信息深度不足仍未达到关闭条件"

    reason = str(resolution.get("resolution_reason") or "").strip()
    if not checked and _is_weak_resolution_reason(reason):
        return False, "系统复核未通过：复核理由过于笼统，未证明原问题已解决"
    return True, None


def _is_weak_resolution_reason(reason: str) -> bool:
    normalized = reason.strip()
    if not normalized:
        return True
    weak_markers = (
        "当前证据数为",
        "引用均已核实",
        "已核实",
        "问题已解决",
        "已解决",
    )
    return len(normalized) < 18 or normalized in weak_markers


def _analysis_for_issue(
    issue: dict[str, Any], analyses: list[dict[str, Any]]
) -> dict[str, Any] | None:
    name = str(issue.get("competitor_name") or "")
    for analysis in _latest_analyses_by_competitor(analyses):
        if str(analysis.get("competitor_name") or "") == name:
            return analysis
    return None


def _latest_analyses_by_competitor(
    analyses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    order: dict[str, int] = {}
    latest_index: dict[str, int] = {}
    for index, analysis in enumerate(analyses or []):
        if not isinstance(analysis, dict):
            continue
        key = str(
            analysis.get("competitor_id")
            or analysis.get("competitor_name")
            or analysis.get("id")
            or index
        )
        order.setdefault(key, index)
        existing = latest.get(key)
        if existing is None or _analysis_sort_key(analysis, index) >= _analysis_sort_key(
            existing, latest_index[key]
        ):
            latest[key] = analysis
            latest_index[key] = index
    return [latest[key] for key in sorted(latest, key=lambda item: order[item])]


def _analysis_sort_key(analysis: dict[str, Any], index: int) -> tuple[int, str, int, str]:
    return (
        _safe_int(analysis.get("analysis_iteration")),
        str(analysis.get("created_at") or ""),
        index,
        str(analysis.get("id") or ""),
    )


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _fields_for_issue(issue: dict[str, Any]) -> list[str]:
    explicit_fields = [
        str(field)
        for field in (issue.get("fields") or [])
        if str(field) in _SCHEMA_FIELDS
    ]
    if explicit_fields:
        return explicit_fields
    text = f"{issue.get('description', '')} {issue.get('fix_suggestion', '')}"
    return _fields_from_text({"description": text})


def _fields_from_text(issue: dict[str, Any]) -> list[str]:
    text = f"{issue.get('description', '')} {issue.get('fix_suggestion', '')}"
    result = []
    for keyword, field in _ISSUE_FIELD_HINTS.items():
        if keyword in text and field not in result:
            result.append(field)
    return result


def _issue_mentions_absent_or_placeholder(issue: dict[str, Any]) -> bool:
    text = f"{issue.get('description', '')} {issue.get('fix_suggestion', '')}".lower()
    return any(
        marker in text
        for marker in [
            "写'无'",
            "写“无”",
            "仅写'无'",
            "仅写“无”",
            "无劣势",
            "证据中未涉及",
            "占位",
            "缺乏实质",
            "无实质",
            "字段不完整",
        ]
    )


def _reference_ids_mentioned(issue: dict[str, Any]) -> set[int]:
    text = f"{issue.get('description', '')} {issue.get('fix_suggestion', '')}"
    ids: set[int] = set()
    for token in text.replace("【", "[").replace("】", "]").split("["):
        candidate = token.split("]", 1)[0].strip()
        if candidate.isdigit():
            ids.add(int(candidate))
    return ids


def _reference_ids_requiring_removal(issue: dict[str, Any]) -> set[int]:
    if _is_generic_source_ref_format_issue(issue):
        return set()
    return _reference_ids_mentioned(issue)


_EVIDENCE_ID_RE = re.compile(r"(?<![A-Za-z0-9_])ev_[A-Za-z0-9_]+")


def _evidence_id_mentions(text: Any) -> set[str]:
    return set(_EVIDENCE_ID_RE.findall(str(text or "")))


def _evidence_ids_requiring_removal(issue: dict[str, Any]) -> set[str]:
    explicit = {
        str(value)
        for value in issue.get("bad_evidence_ids", [])
        if value
    }
    text = "。".join(
        str(issue.get(key) or "")
        for key in ("description", "fix_suggestion", "acceptance_criteria", "resolution_reason")
    )
    result: set[str] = set(explicit)
    negative_markers = (
        "不能支撑",
        "无法支撑",
        "未直接支撑",
        "不支撑",
        "不匹配",
        "不合适",
        "无关",
        "与弱点无关",
        "与劣势无关",
        "正面用户评价",
        "错误引用",
        "引用错误",
        "错误证据",
        "需替换",
    )
    skip_markers = (
        "未引用",
        "缺少",
        "补充",
        "增加",
        "加入",
        "例如",
        "如 ",
        "如ev_",
    )
    for sentence in re.split(r"[。；;.\n]", text):
        if any(marker in sentence for marker in ("移除", "删除", "去除")):
            removal_segment = re.split(
                r"(?:添加|加入|替换为|改用|并引用|同时引用|或替换|，或|, or)",
                sentence,
                maxsplit=1,
            )[0]
            result.update(_evidence_id_mentions(removal_segment))
            continue
        if not any(marker in sentence for marker in negative_markers):
            continue
        if any(marker in sentence for marker in skip_markers):
            continue
        result.update(_evidence_id_mentions(sentence))
    return result


def _is_generic_source_ref_format_issue(issue: dict[str, Any]) -> bool:
    text = f"{issue.get('description', '')} {issue.get('fix_suggestion', '')}".lower()
    return (
        "source_ref" in text
        and "evidence_id" in text
        and any(marker in text for marker in ("而非", "不是", "instead of"))
    )


def _analysis_reference_ids(
    analysis: dict[str, Any], evidence: list[dict[str, Any]]
) -> set[int]:
    evidence_by_id = {str(item.get("id")): item for item in evidence if item.get("id")}
    refs = set()
    for evidence_id in _all_analysis_evidence_ids(analysis):
        item = evidence_by_id.get(evidence_id)
        ref = item.get("reference_id") if item else None
        if isinstance(ref, int):
            refs.add(ref)
    return refs


def _coverage_dimensions_for_issue(issue: dict[str, Any]) -> list[str]:
    text = f"{issue.get('description', '')} {issue.get('fix_suggestion', '')}"
    labels = []
    for label in ("产品定位", "核心功能", "价格与商业模式", "用户评价与痛点"):
        if any(part in text for part in label.split("与")) or label in text:
            labels.append(label)
    return labels or ["产品定位", "核心功能", "价格与商业模式", "用户评价与痛点"]


def _evidence_counts_for_competitor(
    evidence: list[dict[str, Any]], competitor_name: str
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in evidence:
        if str(item.get("related_product") or "") != competitor_name:
            continue
        dimension = str(item.get("related_dimension") or "")
        if not dimension:
            continue
        counts[dimension] = counts.get(dimension, 0) + 1
    return counts


def _build_retry_guidance_map(issues: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for issue in issues:
        name = issue.get("competitor_name", "")
        description = issue.get("description", "")
        suggestion = issue.get("fix_suggestion", "")
        if not (description or suggestion):
            continue
        if name == "system":
            name = "__report__"
        if name:
            result.setdefault(name, "")
            dimension = issue.get("dimension", "unknown")
            severity = issue.get("severity", "unknown")
            guidance = suggestion or description
            result[name] += (
                f"- [{severity}/{dimension}] {description}；改进建议：{guidance}\n"
            )
    return result


def _build_repair_tasks(
    issues: list[dict[str, Any]], analyses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    name_to_id = {
        str(analysis.get("competitor_name") or ""): analysis.get("competitor_id")
        for analysis in analyses
    }
    tasks = []
    for issue in issues:
        competitor_name = str(issue.get("competitor_name") or "")
        if not competitor_name or competitor_name == "system":
            continue
        fields = _fields_for_issue(issue)
        if not fields:
            fields = _default_repair_fields(issue.get("dimension"))
        tasks.append(
            {
                "issue_id": issue.get("id"),
                "competitor_name": competitor_name,
                "competitor_id": name_to_id.get(competitor_name),
                "dimension": issue.get("dimension"),
                "severity": issue.get("severity"),
                "issue_type": issue.get("issue_type"),
                "verification_mode": issue.get("verification_mode"),
                "fields": fields,
                "must_remove_reference_ids": sorted(
                    _reference_ids_requiring_removal(issue)
                ),
                "must_remove_evidence_ids": sorted(
                    _evidence_ids_requiring_removal(issue)
                ),
                "forbidden_evidence_ids": sorted(
                    _evidence_ids_requiring_removal(issue)
                ),
                "required_evidence_ids": sorted(
                    _evidence_ids_required_for_use(issue)
                ),
                "preferred_evidence_ids": sorted(
                    _evidence_ids_preferred_for_use(issue)
                ),
                "suggested_evidence_ids": [
                    str(value)
                    for value in issue.get("suggested_evidence_ids", [])
                    if value
                ],
                "claim": issue.get("claim"),
                "acceptance_criteria": issue.get("fix_suggestion")
                or issue.get("description")
                or "",
            }
        )
    return tasks


def _evidence_ids_required_for_use(issue: dict[str, Any]) -> set[str]:
    explicit = {
        str(value)
        for value in issue.get("required_evidence_ids", [])
        if value
    }
    return explicit - _evidence_ids_requiring_removal(issue)


def _evidence_ids_preferred_for_use(issue: dict[str, Any]) -> set[str]:
    result = {
        str(value)
        for value in issue.get("suggested_evidence_ids", [])
        if value
    }
    text = "。".join(
        str(issue.get(key) or "")
        for key in ("fix_suggestion", "description", "acceptance_criteria")
    )
    positive_markers = (
        "加入",
        "添加",
        "引用",
        "替换为",
        "应引用",
        "使用",
        "建议",
        "例如",
        "如",
    )
    negative_markers = (
        "移除",
        "删除",
        "不得",
        "不能",
        "无法支撑",
        "不支撑",
        "不匹配",
        "错误",
    )
    for sentence in re.split(r"[。；;.\n]", text):
        if any(marker in sentence for marker in negative_markers) and not any(
            marker in sentence for marker in ("替换为", "应引用", "建议", "例如", "如")
        ):
            continue
        if any(marker in sentence for marker in positive_markers):
            result.update(_evidence_id_mentions(sentence))
    return result - _evidence_ids_requiring_removal(issue)


def _default_repair_fields(dimension: Any) -> list[str]:
    if dimension == "schema_completeness":
        return list(_SCHEMA_FIELDS)
    if dimension == "citation_accuracy":
        return ["field_evidence_ids_json", "evidence_ids_json"]
    if dimension == "coverage_gaps":
        return ["positioning", "core_features_json", "pricing_summary", "weaknesses_json"]
    if dimension == "cross_competitor_consistency":
        return list(_SCHEMA_FIELDS)
    if dimension == "factual_plausibility":
        return ["positioning", "pricing_summary", "relationship_reason"]
    return ["field_evidence_ids_json", "evidence_ids_json"]


def _identify_bad_evidence_ids(
    issues: list[dict[str, Any]], evidence: list[dict[str, Any]]
) -> list[str]:
    ref_ids = set()
    evidence_ids = set()
    for issue in issues:
        if issue.get("dimension") in {"citation_accuracy", "evidence_grounding"}:
            ref_ids.update(_reference_ids_requiring_removal(issue))
            evidence_ids.update(_evidence_ids_requiring_removal(issue))
    result = []
    for item in evidence:
        if item.get("reference_id") in ref_ids and item.get("id"):
            result.append(str(item["id"]))
    result.extend(evidence_ids)
    return sorted(set(result))


def _identify_retry_analyses(
    issues: list[dict[str, Any]], analyses: list[dict[str, Any]]
) -> list[str]:
    flagged_names = {
        issue.get("competitor_name")
        for issue in issues
        if issue.get("competitor_name") not in {"system", None}
    }
    if not flagged_names:
        all_ids = [
            a.get("competitor_id", "") for a in analyses if a.get("competitor_id")
        ]
        return all_ids
    retry_ids = []
    for analysis in analyses:
        name = analysis.get("competitor_name", "")
        cid = analysis.get("competitor_id", "")
        if name in flagged_names and cid:
            retry_ids.append(cid)
    return (
        retry_ids
        if retry_ids
        else [a.get("competitor_id", "") for a in analyses if a.get("competitor_id")][
            :1
        ]
    )


def _deterministic_quality_issues(
    analyses: list[dict[str, Any]], evidence: list[dict[str, Any]], iteration: int
) -> list[dict[str, Any]]:
    """Apply cheap deterministic checks that should not depend on LLM judgment."""
    issues: list[dict[str, Any]] = []
    evidence_ids = {str(e.get("id")) for e in evidence if e.get("id")}
    evidence_by_id = {str(e.get("id")): e for e in evidence if e.get("id")}
    evidence_count_by_competitor: dict[str, int] = {}
    evidence_count_by_name: dict[str, int] = {}
    for item in evidence:
        cid = str(item.get("competitor_id") or "")
        name = str(item.get("related_product") or "")
        if cid:
            evidence_count_by_competitor[cid] = (
                evidence_count_by_competitor.get(cid, 0) + 1
            )
        if name:
            evidence_count_by_name[name] = evidence_count_by_name.get(name, 0) + 1

    for analysis in analyses:
        name = str(
            analysis.get("competitor_name") or analysis.get("name") or "未知竞品"
        )
        cid = str(analysis.get("competitor_id") or "")
        evidence_count = evidence_count_by_competitor.get(
            cid, evidence_count_by_name.get(name, 0)
        )
        if evidence_count < _MIN_EVIDENCE_PER_COMPETITOR:
            issues.append(
                _make_issue(
                    iteration=iteration,
                    dimension="coverage_gaps",
                    severity="critical" if evidence_count == 0 else "major",
                    competitor_name=name,
                    description=(
                        f"{name} 仅有 {evidence_count} 条证据，低于"
                        f" {_MIN_EVIDENCE_PER_COMPETITOR} 条的最低覆盖要求"
                    ),
                    fix_suggestion=f"补充采集 {name} 的产品定位、核心功能、定价和用户反馈证据",
                    issue_id=f"det_coverage_{_stable_issue_token(cid or name)}",
                )
            )

        missing_fields = [
            label
            for field, label in _SCHEMA_FIELDS.items()
            if _is_empty_or_placeholder(analysis.get(field))
        ]
        if missing_fields:
            issues.append(
                _make_issue(
                    iteration=iteration,
                    dimension="schema_completeness",
                    severity="major",
                    competitor_name=name,
                    description=f"{name} 的结构化分析字段不完整：{', '.join(missing_fields)}",
                    fix_suggestion=f"重新分析 {name}，补齐缺失字段并避免占位文本",
                    issue_id=f"det_schema_{_stable_issue_token(cid or name)}",
                )
            )
        issues.extend(
            _pricing_factual_issues(
                analysis,
                evidence,
                name,
                iteration,
                cid,
            )
        )

        referenced_ids = _all_analysis_evidence_ids(analysis)
        dangling_ids = sorted(eid for eid in referenced_ids if eid not in evidence_ids)
        if dangling_ids:
            issues.append(
                _make_issue(
                    iteration=iteration,
                    dimension="citation_accuracy",
                    severity="major",
                    competitor_name=name,
                    description=(
                        f"{name} 引用了 {len(dangling_ids)} 条不存在的证据 ID"
                    ),
                    fix_suggestion="重新核验 evidence_ids，移除无效引用或补齐对应证据",
                    issue_id=f"det_citation_{_stable_issue_token(cid or name)}",
                )
            )
        invalid_refs = [
            eid
            for eid in referenced_ids
            if eid in evidence_by_id and evidence_by_id[eid].get("reference_id") is None
        ]
        if invalid_refs:
            issues.append(
                _make_issue(
                    iteration=iteration,
                    dimension="citation_accuracy",
                    severity="major",
                    competitor_name=name,
                    description=(
                        f"{name} 引用了 {len(invalid_refs)} 条缺少来源编号的证据"
                    ),
                    fix_suggestion="重新采集或修复 evidence 的 source_ref，禁止引用 source_ref 为空的证据",
                    issue_id=f"det_null_ref_{_stable_issue_token(cid or name)}",
                )
            )
        issues.extend(
            _field_evidence_binding_issues(
                analysis,
                evidence,
                referenced_ids,
                name,
                iteration,
                cid,
            )
        )
    return issues


def _pricing_factual_issues(
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
    competitor_name: str,
    iteration: int,
    competitor_id: str,
) -> list[dict[str, Any]]:
    pricing_summary = str(analysis.get("pricing_summary") or "").strip()
    if _is_empty_or_placeholder(pricing_summary):
        return []
    competitor_evidence = [
        item
        for item in evidence
        if (
            str(item.get("competitor_id") or "") == competitor_id
            or str(item.get("related_product") or "") == competitor_name
        )
        and _dimension_matches_any(item.get("related_dimension"), {"价格与商业模式"})
    ]
    pricing_text = " ".join(
        str(item.get(key) or "")
        for item in competitor_evidence
        for key in ("claim", "summary", "quote")
    )
    has_specific_price = bool(
        re.search(
            r"(\$\s*\d+|\d+\s*(美元|美金|usd|元)\s*/?\s*(月|年|month|year)?)",
            pricing_text,
            flags=re.IGNORECASE,
        )
    ) or any(
        marker in pricing_text
        for marker in ("Free", "Pro", "Business", "Enterprise", "免费", "套餐")
    )
    if not has_specific_price:
        return []

    vague_markers = (
        "未提供具体",
        "没有具体",
        "未涉及",
        "未明确",
        "暂无具体",
    )
    subscription_markers = (
        "订阅",
        "套餐",
        "免费",
        "free",
        "pro",
        "business",
        "enterprise",
        "$",
        "美元",
    )
    summary_lower = pricing_summary.lower()
    if any(marker in pricing_summary for marker in vague_markers) or (
        "按用量" in pricing_summary
        and not any(marker in summary_lower or marker in pricing_summary for marker in subscription_markers)
    ):
        return [
            _make_issue(
                iteration=iteration,
                dimension="factual_plausibility",
                severity="major",
                competitor_name=competitor_name,
                description=(
                    f"{competitor_name} 的定价字段未准确反映证据中的具体价格或套餐信息。"
                ),
                fix_suggestion=(
                    "根据价格证据补充具体套餐、金额或订阅信息，避免写成未提供具体价格或仅按用量计费。"
                ),
                issue_id=f"det_pricing_fact_{_stable_issue_token(competitor_id or competitor_name)}",
                extra={"fields": ["pricing_summary", "field_evidence_ids_json"]},
            )
        ]
    return []


def _field_evidence_binding_issues(
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
    referenced_ids: set[str],
    competitor_name: str,
    iteration: int,
    competitor_id: str,
) -> list[dict[str, Any]]:
    evidence_by_id = {str(item.get("id")): item for item in evidence if item.get("id")}
    item_bindings = parse_item_evidence_bindings(
        _parse_json_dict(analysis.get("item_evidence_bindings_json"))
    )
    field_evidence_ids = parse_field_evidence_ids(
        _parse_json_dict(analysis.get("field_evidence_ids_json"))
    )
    competitor_evidence = [
        item
        for item in evidence
        if str(item.get("competitor_id") or "") == competitor_id
        or str(item.get("related_product") or "") == competitor_name
    ]
    result: list[dict[str, Any]] = []
    for field, dimensions in _FIELD_DIMENSION_REQUIREMENTS.items():
        if field == "opportunities_json":
            continue
        if _is_empty_or_placeholder(analysis.get(field)):
            continue
        claims = _field_claims(analysis.get(field))
        required_dimensions = claim_required_dimensions(
            field,
            claims,
            competitor_evidence,
        ) or dimensions
        available = [
            item
            for item in competitor_evidence
            if evidence_matches_claim_policy(item, field, claims, competitor_evidence)
            and _dimension_matches_any(item.get("related_dimension"), required_dimensions)
        ]
        if not available:
            continue
        if item_bindings.get(field):
            item_issues = _item_evidence_binding_issues_for_field(
                analysis,
                field,
                item_bindings.get(field, []),
                evidence_by_id,
                competitor_id,
                competitor_name,
                iteration,
                available,
            )
            if item_issues:
                result.extend(item_issues)
                continue
        candidate_ids = set(field_evidence_ids.get(field, [])) or referenced_ids
        linked = [
            evidence_by_id[eid]
            for eid in candidate_ids
            if eid in evidence_by_id
            and evidence_matches_claim_policy(
                evidence_by_id[eid], field, claims, competitor_evidence
            )
            and _dimension_matches_any(
                evidence_by_id[eid].get("related_dimension"), required_dimensions
            )
        ]
        if linked:
            continue
        result.append(
            _make_issue(
                iteration=iteration,
                dimension="evidence_grounding",
                severity="major" if field in {"weaknesses_json", "core_features_json", "pricing_summary"} else "minor",
                competitor_name=competitor_name,
                description=(
                    f"{competitor_name} 的{_SCHEMA_FIELDS[field]}字段已有实质内容，"
                    f"但字段级证据绑定未引用{', '.join(sorted(dimensions))}维度证据。"
                ),
                fix_suggestion=(
                    "将能直接支撑该字段的 evidence_id 加入 field_evidence_ids_json 对应字段，"
                    f"例如 {', '.join(_top_evidence_ids(available))}。"
                ),
                issue_id=f"det_field_ev_{_stable_issue_token(competitor_id or competitor_name)}_{field}",
            )
        )
    return result


def _item_evidence_binding_issues_for_field(
    analysis: dict[str, Any],
    field: str,
    rows: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    competitor_id: str,
    competitor_name: str,
    iteration: int,
    available: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if field == "opportunities_json":
        return []

    claims = _field_claims(analysis.get(field))
    if not claims:
        return []
    row_by_index = {
        int(row.get("item_index") or index): row for index, row in enumerate(rows)
    }
    result: list[dict[str, Any]] = []
    for index, claim in enumerate(claims):
        row = row_by_index.get(index)
        evidence_ids = [
            str(eid)
            for eid in ((row or {}).get("evidence_ids") or [])
            if str(eid)
        ]
        valid_ids = [
            eid
            for eid in evidence_ids
            if eid in evidence_by_id
            and _evidence_belongs_to_competitor(
                evidence_by_id[eid], competitor_id, competitor_name
            )
            and evidence_matches_claim_policy(
                evidence_by_id[eid], field, claim, list(evidence_by_id.values())
            )
        ]
        if valid_ids:
            continue
        bad_ids = [
            eid for eid in evidence_ids if eid in evidence_by_id and eid not in valid_ids
        ]
        result.append(
            _make_issue(
                iteration=iteration,
                dimension="evidence_grounding",
                severity="major"
                if field in {"weaknesses_json", "core_features_json", "pricing_summary"}
                else "minor",
                competitor_name=competitor_name,
                description=(
                    f"{competitor_name} 的{_SCHEMA_FIELDS[field]}第 {index + 1} 条"
                    "缺少条目级有效证据绑定，或绑定证据的维度/情绪与结论不匹配。"
                ),
                fix_suggestion=(
                    "更新 item_evidence_bindings_json 对应条目，绑定能直接支撑该结论的 evidence_id；"
                    f"建议候选：{', '.join(_top_evidence_ids(available))}。"
                ),
                issue_id=(
                    f"det_item_ev_{_stable_issue_token(competitor_id or competitor_name)}"
                    f"_{field}_{index}"
                ),
                extra={
                    "fields": [field, "item_evidence_bindings_json"],
                    "bad_evidence_ids": bad_ids,
                    "suggested_evidence_ids": _top_evidence_ids(available),
                    "claim": claim,
                },
            )
        )
    return result


def _field_claims(value: Any) -> list[str]:
    if _is_empty_or_placeholder(value):
        return []
    parsed = _try_parse_json_list(value) if isinstance(value, str) else None
    if parsed is None and isinstance(value, list):
        parsed = value
    if parsed:
        return [str(item).strip() for item in parsed if not _is_empty_or_placeholder(item)]
    text = str(value).strip()
    return [text] if text and not _is_empty_or_placeholder(text) else []


def _evidence_belongs_to_competitor(
    evidence: dict[str, Any], competitor_id: str, competitor_name: str
) -> bool:
    return (
        str(evidence.get("competitor_id") or "") == str(competitor_id)
        or str(evidence.get("related_product") or "") == str(competitor_name)
    )


def _dimension_matches_any(dimension: Any, preferred: set[str]) -> bool:
    return dimension_matches_any(dimension, preferred)


def _top_evidence_ids(evidence: list[dict[str, Any]]) -> list[str]:
    ranked = sorted(
        evidence,
        key=lambda item: (
            1 if item.get("support_type") == "direct" else 0,
            _coerce_score(item.get("relevance_score")),
            _coerce_score(item.get("confidence")),
        ),
        reverse=True,
    )
    return [str(item.get("id")) for item in ranked[:3] if item.get("id")]


def _make_issue(
    *,
    iteration: int,
    dimension: str,
    severity: str,
    competitor_name: str,
    description: str,
    fix_suggestion: str,
    issue_id: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue = {
        "id": issue_id,
        "source": "deterministic",
        "dimension": dimension,
        "severity": _normalize_severity(severity),
        "competitor_name": competitor_name,
        "description": description,
        "fix_suggestion": fix_suggestion,
        "status": "open",
        "first_seen_iteration": iteration,
        "last_seen_iteration": iteration,
        "resolved_iteration": None,
        "resolution_reason": None,
    }
    if extra:
        issue.update(extra)
    return _enrich_issue_metadata(issue)


def _merge_issues(
    primary: list[dict[str, Any]], secondary: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in [*primary, *secondary]:
        key = (
            str(issue.get("dimension") or ""),
            str(issue.get("competitor_name") or ""),
            _normalize_issue_text(str(issue.get("description") or "")),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(issue)
    return merged


def _apply_issue_score_caps(
    dimension_scores: dict[str, float], issues: list[dict[str, Any]]
) -> dict[str, float]:
    adjusted = dict(dimension_scores)
    caps: dict[str, float] = {}
    for issue in issues:
        dimension = issue.get("dimension")
        if dimension not in DIMENSION_SCORE_WEIGHTS:
            continue
        cap = _issue_score_cap(issue)
        caps[dimension] = min(caps.get(dimension, 1.0), cap)
    for dimension, cap in caps.items():
        adjusted[dimension] = max(0.0, min(adjusted.get(dimension, 0.0), cap))
    return adjusted


def _issue_score_cap(issue: dict[str, Any]) -> float:
    severity = issue.get("severity")
    dimension = issue.get("dimension")
    if severity == "critical":
        return 0.35
    if severity == "major":
        if dimension in {"citation_accuracy", "schema_completeness"}:
            return 0.6
        return 0.65
    if severity == "minor":
        return 0.8
    return 1.0


def _has_blocking_analysis_issue(issues: list[dict[str, Any]]) -> bool:
    return any(
        issue.get("dimension") not in COLLECTION_DIMENSIONS
        and issue.get("competitor_name") not in {"system", None}
        and issue.get("severity") in {"critical", "major"}
        for issue in issues
    )


def _forced_pass_decision(
    overall_score: float, checklist: list[dict[str, Any]] | None = None
) -> str:
    if (
        overall_score < QA_PASS_THRESHOLD
        or _has_unresolved_blocking_issues(checklist or [])
    ):
        return "pass_with_quality_warning"
    return "pass"


def _has_unresolved_blocking_issues(checklist: list[dict[str, Any]]) -> bool:
    return any(
        issue.get("status") in _NOT_RESOLVED_STATUSES
        and issue.get("severity") in {"critical", "major"}
        for issue in checklist
    )


def _all_analysis_evidence_ids(analysis: dict[str, Any]) -> set[str]:
    ids = set(_parse_evidence_ids(analysis.get("evidence_ids_json")))
    field_evidence_ids = parse_field_evidence_ids(
        _parse_json_dict(analysis.get("field_evidence_ids_json"))
    )
    for values in field_evidence_ids.values():
        ids.update(values)
    item_bindings = parse_item_evidence_bindings(
        _parse_json_dict(analysis.get("item_evidence_bindings_json"))
    )
    for rows in item_bindings.values():
        for row in rows:
            ids.update(str(eid) for eid in row.get("evidence_ids", []) if eid)
    return ids


def _parse_evidence_ids(raw_ids: Any) -> set[str]:
    if isinstance(raw_ids, str):
        try:
            parsed = json.loads(raw_ids)
        except (TypeError, ValueError):
            parsed = []
    else:
        parsed = raw_ids
    if not isinstance(parsed, list):
        return set()
    return {str(item) for item in parsed if item}


def _parse_json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _is_empty_or_placeholder(value: Any) -> bool:
    if isinstance(value, list):
        return len([item for item in value if not _is_empty_or_placeholder(item)]) == 0
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return True
        parsed = _try_parse_json_list(text)
        if parsed is not None:
            return _is_empty_or_placeholder(parsed)
        lowered = text.lower()
        return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)
    return value is None


def _try_parse_json_list(value: str) -> list[Any] | None:
    if not value.startswith("["):
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, list) else None


def _normalize_issue_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _stable_issue_token(value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    return safe[:40] or uuid4().hex[:12]


def _normalize_dimension_scores(raw_scores: Any) -> dict[str, float]:
    if not isinstance(raw_scores, dict):
        return {dimension: 0.0 for dimension in DIMENSION_SCORE_WEIGHTS}
    normalized: dict[str, float] = {
        dimension: 0.0 for dimension in DIMENSION_SCORE_WEIGHTS
    }
    for key, value in raw_scores.items():
        dimension = str(key)
        if dimension not in DIMENSION_SCORE_WEIGHTS:
            continue
        try:
            score = float(value)
        except (TypeError, ValueError):
            continue
        normalized[dimension] = min(1.0, max(0.0, score))
    return normalized


def _previous_dimension_scores(prev_qa: Any) -> dict[str, float]:
    if isinstance(prev_qa, dict):
        return _normalize_dimension_scores(prev_qa.get("dimension_scores"))
    return {dimension: 0.0 for dimension in DIMENSION_SCORE_WEIGHTS}


def _recalculate_scores_after_verification(
    prev_qa: Any,
    checklist: list[dict[str, Any]],
) -> tuple[dict[str, float], float]:
    """Recalculate dimension and overall scores based on remaining open issues.

    After issue verification resolves some issues, lift caps on dimensions
    that no longer have open issues so the score reflects the improvement.
    """
    dimension_scores = _previous_dimension_scores(prev_qa)
    open_issues = [i for i in checklist if i.get("status") == "open"]
    dimension_scores = _apply_issue_score_caps(dimension_scores, open_issues)
    overall_score = _calculate_overall_score(dimension_scores)
    return dimension_scores, overall_score


def _calculate_overall_score(dimension_scores: dict[str, float]) -> float:
    total = sum(
        dimension_scores.get(dimension, 0.0) * weight
        for dimension, weight in DIMENSION_SCORE_WEIGHTS.items()
    )
    return round(min(1.0, max(0.0, total)), 2)


def _cap_analyses(
    analyses: list[dict[str, Any]], cap: int = _ANALYSES_CAP
) -> list[dict[str, Any]]:
    if len(analyses) <= cap:
        return analyses
    return analyses[:cap]


def _coerce_score(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
