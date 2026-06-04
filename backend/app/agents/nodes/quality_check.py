import logging
from typing import Any

from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)

MAX_FEEDBACK_LOOPS = 2
QA_PASS_THRESHOLD = 0.7

COLLECTION_DIMENSIONS = {"evidence_grounding", "coverage_gaps"}


def quality_check_node(state: AgentState, llm: LLMProvider) -> AgentState:
    qa_raw = llm.qa_check_report(
        state.get("report", {}),
        state.get("analyses", []),
        state.get("evidence", []),
        state.get("sources", []),
    )

    feedback_count = state.get("feedback_loop_count", 0) + 1
    overall_score = float(qa_raw.get("overall_score", 0))
    issues = qa_raw.get("issues", [])
    decision = qa_raw.get("decision", "pass")

    previous_score = None
    prev_qa = state.get("qa_result")
    if prev_qa and isinstance(prev_qa, dict):
        previous_score = prev_qa.get("overall_score")

    forced_pass = False
    if feedback_count >= MAX_FEEDBACK_LOOPS:
        forced_pass = True
        decision = "pass"
        logger.info("QA: forcing pass — max feedback loops (%d) reached", MAX_FEEDBACK_LOOPS)
    elif overall_score >= QA_PASS_THRESHOLD and decision != "pass":
        decision = "pass"
    elif overall_score < QA_PASS_THRESHOLD and decision == "pass":
        decision = _infer_decision(issues)
    elif previous_score is not None and overall_score <= previous_score:
        forced_pass = True
        decision = "pass"
        logger.info("QA: forcing pass — score did not improve (%.2f <= %.2f)", overall_score, previous_score)

    retry_guidance = None
    retry_queries = None
    retry_analysis_ids = None
    if decision == "retry_collection":
        retry_queries = qa_raw.get("retry_queries") or []
        retry_guidance = qa_raw.get("retry_instructions") or _build_collection_retry_guidance(issues)
    elif decision == "retry_analysis":
        retry_analysis_ids = _identify_retry_analyses(issues, state.get("analyses", []))

    qa_result: dict[str, Any] = {
        "overall_score": overall_score,
        "decision": decision,
        "retry_instructions": qa_raw.get("retry_instructions"),
        "issues": issues,
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
        "feedback_loop_count": feedback_count,
    }
    if retry_guidance is not None:
        new_state["qa_retry_guidance"] = retry_guidance
    if retry_queries is not None:
        new_state["qa_retry_queries"] = retry_queries
    if retry_analysis_ids is not None:
        new_state["qa_retry_analysis_ids"] = retry_analysis_ids
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


def _infer_decision(issues: list[dict[str, Any]]) -> str:
    for issue in issues:
        if issue.get("dimension") in COLLECTION_DIMENSIONS and issue.get("severity") == "critical":
            return "retry_collection"
    return "retry_analysis"


def _build_collection_retry_guidance(issues: list[dict[str, Any]]) -> str:
    guidance_parts = []
    for issue in issues:
        if issue.get("dimension") in COLLECTION_DIMENSIONS:
            competitor = issue.get("competitor_name", "")
            suggestion = issue.get("fix_suggestion", "")
            if competitor and suggestion:
                guidance_parts.append(f"{competitor}: {suggestion}")
    return "; ".join(guidance_parts) if guidance_parts else "补充采集缺失维度的证据"


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
