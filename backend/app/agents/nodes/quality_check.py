import logging
from typing import Any
from uuid import uuid4

from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)

MAX_FEEDBACK_LOOPS = 3
QA_PASS_THRESHOLD = 0.7

COLLECTION_DIMENSIONS = {"evidence_grounding", "coverage_gaps"}
DIMENSION_SCORE_WEIGHTS = {
    "evidence_grounding": 0.25,
    "citation_accuracy": 0.15,
    "schema_completeness": 0.2,
    "coverage_gaps": 0.2,
    "cross_competitor_consistency": 0.1,
    "factual_plausibility": 0.1,
}


def quality_check_node(state: AgentState, llm: LLMProvider) -> AgentState:
    raw_count = state.get("feedback_loop_count", 0)
    issue_verification_count = state.get("qa_issue_verification_count", 0)
    previous_score = None
    prev_qa = state.get("qa_result")
    if prev_qa and isinstance(prev_qa, dict):
        previous_score = _coerce_score(prev_qa.get("overall_score"))
    checklist = _normalize_checklist(state.get("qa_issue_checklist", []))
    open_issues = [issue for issue in checklist if issue.get("status") == "open"]
    phase = "full_check"
    retry_queries = None
    retry_instructions = None
    feedback_count = raw_count
    forced_pass = False
    dimension_scores: dict[str, float] = {d: 0.0 for d in DIMENSION_SCORE_WEIGHTS}
    overall_score: float = 0.0
    decision = "pass"
    issues: list[dict[str, Any]] = []

    if open_issues:
        phase = "issue_verification"
        verification_raw = llm.qa_verify_issues(
            state.get("report", {}),
            state.get("analyses", []),
            state.get("evidence", []),
            open_issues,
        )
        resolutions = _normalize_issue_resolutions(verification_raw.get("resolutions"))
        checklist = _apply_issue_resolutions(checklist, resolutions, raw_count + 1)
        open_issues = [issue for issue in checklist if issue.get("status") == "open"]
        if open_issues:
            if raw_count + 1 >= MAX_FEEDBACK_LOOPS:
                forced_pass = True
                decision = "pass"
                issues = open_issues
                dimension_scores = _previous_dimension_scores(prev_qa)
                overall_score = previous_score if previous_score is not None else _calculate_overall_score(dimension_scores)
                logger.info("QA: forcing pass — max feedback loops (%d) reached (issue_verification)", MAX_FEEDBACK_LOOPS)
            elif issue_verification_count >= 2:
                logger.info("QA: issue_verification retry limit reached (%d consecutive rounds) — falling through to full_check", issue_verification_count)
                open_issues = []
                phase = "full_check"
            else:
                issue_verification_count += 1
                dimension_scores = _previous_dimension_scores(prev_qa)
                overall_score = previous_score if previous_score is not None else _calculate_overall_score(dimension_scores)
                decision = _derive_retry_decision(open_issues)
                issues = open_issues
                retry_queries = _retry_queries_from_resolutions(resolutions) or _fallback_retry_queries(open_issues)
                retry_instructions = verification_raw.get("retry_instructions") or _retry_instructions_from_issues(open_issues)
        else:
            phase = "full_check"

    if not open_issues or forced_pass:
        feedback_count = raw_count + 1
        issue_verification_count = 0
        if not forced_pass:
            qa_raw = llm.qa_check_report(
                state.get("report", {}),
                state.get("analyses", []),
                state.get("evidence", []),
            )
            dimension_scores = _normalize_dimension_scores(qa_raw.get("dimension_scores"))
            overall_score = _calculate_overall_score(dimension_scores)
            issues = _normalize_new_issues(qa_raw.get("issues"), feedback_count)
            decision = _derive_decision(overall_score, dimension_scores, issues)
            checklist = _close_open_issues(checklist, feedback_count)
            if decision != "pass":
                checklist += issues
            retry_queries = qa_raw.get("retry_queries") if decision == "retry_collection" else None
            retry_instructions = qa_raw.get("retry_instructions") if decision != "pass" else None
            if feedback_count >= MAX_FEEDBACK_LOOPS:
                forced_pass = True
                decision = "pass"
                logger.info("QA: forcing pass — max feedback loops (%d) reached (full_check)", MAX_FEEDBACK_LOOPS)
            elif decision != "pass" and previous_score is not None and overall_score <= previous_score:
                forced_pass = True
                decision = "pass"
                logger.info("QA: forcing pass — score did not improve (%.2f <= %.2f)", overall_score, previous_score)

    retry_guidance_map = None
    retry_analysis_ids = None
    retry_report_guidance = None
    if decision == "retry_collection":
        retry_queries = _normalize_retry_queries(retry_queries) or _fallback_retry_queries(issues)
        retry_guidance_map = _build_retry_guidance_map(issues)
        retry_report_guidance = retry_instructions
    elif decision == "retry_analysis":
        retry_guidance_map = _build_retry_guidance_map(issues)
        retry_analysis_ids = _identify_retry_analyses(issues, state.get("analyses", []))
        retry_report_guidance = retry_instructions

    qa_result: dict[str, Any] = {
        "overall_score": overall_score,
        "dimension_scores": dimension_scores,
        "decision": decision,
        "retry_instructions": retry_instructions,
        "issues": issues,
        "issue_checklist": checklist,
        "check_phase": phase,
        "iteration": feedback_count,
        "forced_pass": forced_pass,
        "previous_score": previous_score,
    }

    logger.info(
        "QA iteration %d: score=%.2f decision=%s issues=%d forced_pass=%s",
        feedback_count, overall_score, decision, len(issues), forced_pass,
    )

    new_state: dict[str, Any] = {
        **state,
        "qa_result": qa_result,
        "qa_issue_checklist": checklist,
        "qa_issue_verification_count": issue_verification_count,
        "feedback_loop_count": feedback_count,
    }
    for stale_key in ("qa_retry_guidance_map", "qa_retry_queries", "qa_retry_analysis_ids", "qa_report_guidance"):
        new_state.pop(stale_key, None)
    if retry_guidance_map is not None:
        new_state["qa_retry_guidance_map"] = retry_guidance_map
    if retry_queries is not None:
        new_state["qa_retry_queries"] = retry_queries
    if retry_analysis_ids is not None:
        new_state["qa_retry_analysis_ids"] = retry_analysis_ids
    if retry_report_guidance is not None:
        new_state["qa_report_guidance"] = retry_report_guidance
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
    return "end"


def _derive_decision(_overall_score: float, dimension_scores: dict[str, float], issues: list[dict[str, Any]]) -> str:
    for issue in issues:
        if issue.get("dimension") in COLLECTION_DIMENSIONS:
            return "retry_collection"
    if all(score >= QA_PASS_THRESHOLD for score in dimension_scores.values()):
        return "pass"
    return "retry_analysis"


def _derive_retry_decision(issues: list[dict[str, Any]]) -> str:
    for issue in issues:
        if issue.get("dimension") in COLLECTION_DIMENSIONS:
            return "retry_collection"
    return "retry_analysis"


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
        issues.append(
            {
                "id": str(raw.get("id") or f"qai_{uuid4().hex[:12]}"),
                "dimension": str(raw.get("dimension") or "unknown"),
                "severity": _normalize_severity(raw.get("severity")),
                "competitor_name": str(raw.get("competitor_name") or "system"),
                "description": description,
                "fix_suggestion": fix_suggestion,
                "status": "open",
                "first_seen_iteration": int(raw.get("first_seen_iteration") or iteration),
                "last_seen_iteration": iteration,
                "resolved_iteration": None,
                "resolution_reason": None,
            }
        )
    return issues


def _normalize_checklist(raw_checklist: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_checklist, list):
        return []
    issues = []
    for raw in raw_checklist:
        if not isinstance(raw, dict):
            continue
        normalized = _normalize_new_issues([raw], int(raw.get("first_seen_iteration") or 1))
        if not normalized:
            continue
        issue = normalized[0]
        issue["status"] = raw.get("status") if raw.get("status") in {"open", "resolved", "superseded", "unresolved"} else "open"
        issue["last_seen_iteration"] = int(raw.get("last_seen_iteration") or issue["first_seen_iteration"])
        issue["resolved_iteration"] = raw.get("resolved_iteration")
        issue["resolution_reason"] = raw.get("resolution_reason")
        issues.append(issue)
    return issues


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
                "resolution_reason": str(raw.get("resolution_reason") or raw.get("reason") or "").strip(),
                "retry_queries": _normalize_retry_queries(raw.get("retry_queries")),
            }
        )
    return resolutions


def _apply_issue_resolutions(checklist: list[dict[str, Any]], resolutions: list[dict[str, Any]], iteration: int) -> list[dict[str, Any]]:
    resolution_by_id = {item["issue_id"]: item for item in resolutions}
    updated = []
    for issue in checklist:
        if issue.get("status") != "open":
            updated.append(issue)
            continue
        resolution = resolution_by_id.get(str(issue.get("id")))
        if resolution and resolution["status"] == "resolved":
            updated.append(
                {
                    **issue,
                    "status": "resolved",
                    "last_seen_iteration": iteration,
                    "resolved_iteration": iteration,
                    "resolution_reason": resolution.get("resolution_reason") or "质检复核确认已解决",
                }
            )
        else:
            updated.append(
                {
                    **issue,
                    "status": "open",
                    "last_seen_iteration": iteration,
                    "resolution_reason": (resolution or {}).get("resolution_reason") or issue.get("resolution_reason"),
                }
            )
    return updated


def _close_open_issues(checklist: list[dict[str, Any]], iteration: int) -> list[dict[str, Any]]:
    """Mark remaining open issues as unresolved rather than silently dropping them."""
    updated = []
    for issue in checklist:
        if issue.get("status") == "open":
            updated.append({**issue, "status": "unresolved", "last_seen_iteration": iteration})
        else:
            updated.append(issue)
    return updated


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
        queries.append(
            {
                "competitor_name": competitor_name,
                "slot": str(raw.get("slot") or "core_features"),
                "query": query,
            }
        )
    return queries


def _retry_queries_from_resolutions(resolutions: list[dict[str, Any]]) -> list[dict[str, str]]:
    queries = []
    for resolution in resolutions:
        queries.extend(resolution.get("retry_queries") or [])
    return queries


def _fallback_retry_queries(issues: list[dict[str, Any]]) -> list[dict[str, str]]:
    queries = []
    for issue in issues:
        competitor_name = issue.get("competitor_name")
        if not competitor_name or competitor_name in {"report", "system"}:
            continue
        dimension = issue.get("dimension")
        if dimension in {"coverage_gaps", "evidence_grounding"}:
            queries.append({"competitor_name": competitor_name, "slot": "core_features", "query": f"{competitor_name} core features evidence"})
            queries.append({"competitor_name": competitor_name, "slot": "pricing", "query": f"{competitor_name} pricing plans evidence"})
        elif dimension == "schema_completeness":
            queries.append({"competitor_name": competitor_name, "slot": "pricing", "query": f"{competitor_name} pricing plans"})
    return queries


def _retry_instructions_from_issues(issues: list[dict[str, Any]]) -> str | None:
    suggestions = [issue.get("fix_suggestion") for issue in issues if issue.get("fix_suggestion")]
    return "; ".join(suggestions) if suggestions else None


def _normalize_severity(value: Any) -> str:
    severity = str(value or "").strip()
    return severity if severity in {"critical", "major", "minor"} else "major"


def _build_retry_guidance_map(issues: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for issue in issues:
        name = issue.get("competitor_name", "")
        description = issue.get("description", "")
        suggestion = issue.get("fix_suggestion", "")
        if name and name not in {"report", "system"} and (description or suggestion):
            result.setdefault(name, "")
            dimension = issue.get("dimension", "unknown")
            severity = issue.get("severity", "unknown")
            guidance = suggestion or description
            result[name] += f"- [{severity}/{dimension}] {description}；改进建议：{guidance}\n"
    return result


def _identify_retry_analyses(issues: list[dict[str, Any]], analyses: list[dict[str, Any]]) -> list[str]:
    flagged_names = {
        issue.get("competitor_name")
        for issue in issues
        if issue.get("dimension") not in COLLECTION_DIMENSIONS and issue.get("competitor_name") not in {"report", "system", None}
    }
    if not flagged_names:
        return [a.get("competitor_id", "") for a in analyses if a.get("competitor_id")]
    retry_ids = []
    for analysis in analyses:
        name = analysis.get("competitor_name", "")
        cid = analysis.get("competitor_id", "")
        if name in flagged_names and cid:
            retry_ids.append(cid)
    return retry_ids if retry_ids else [a.get("competitor_id", "") for a in analyses if a.get("competitor_id")]


def _normalize_dimension_scores(raw_scores: Any) -> dict[str, float]:
    if not isinstance(raw_scores, dict):
        return {dimension: 0.0 for dimension in DIMENSION_SCORE_WEIGHTS}
    normalized: dict[str, float] = {dimension: 0.0 for dimension in DIMENSION_SCORE_WEIGHTS}
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


def _calculate_overall_score(dimension_scores: dict[str, float]) -> float:
    total = sum(
        dimension_scores.get(dimension, 0.0) * weight
        for dimension, weight in DIMENSION_SCORE_WEIGHTS.items()
    )
    return round(min(1.0, max(0.0, total)), 2)


def _coerce_score(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
