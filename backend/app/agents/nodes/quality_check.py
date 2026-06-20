import logging
import json
from typing import Any
from uuid import uuid4

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

COLLECTION_DIMENSIONS = {"evidence_grounding", "coverage_gaps"}
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
_SCHEMA_FIELDS = {
    "positioning": "产品定位",
    "target_users": "目标用户",
    "core_features_json": "核心功能",
    "pricing_summary": "定价信息",
    "strengths_json": "优势",
    "weaknesses_json": "劣势或痛点",
    "opportunities_json": "机会点",
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
        checklist = _close_open_issues(checklist, feedback_count)
        if decision != "pass":
            checklist += issues
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
        issues.append(
            {
                "id": str(raw.get("id") or f"qai_{uuid4().hex[:12]}"),
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
        )
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
            if raw.get("status") in {"open", "resolved", "superseded", "unresolved"}
            else "open"
        )
        issue["last_seen_iteration"] = int(
            raw.get("last_seen_iteration") or issue["first_seen_iteration"]
        )
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
        bad_ids = _reference_ids_requiring_removal(issue)
        if bad_ids and bad_ids & _analysis_reference_ids(analysis, evidence):
            return False, "系统复核未通过：问题证据仍在分析引用中"

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
    text = f"{issue.get('description', '')} {issue.get('fix_suggestion', '')}"
    result = []
    for keyword, field in _ISSUE_FIELD_HINTS.items():
        if keyword in text and field not in result:
            result.append(field)
    return result


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
    for evidence_id in _parse_evidence_ids(analysis.get("evidence_ids_json")):
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
                "fields": fields,
                "must_remove_reference_ids": sorted(
                    _reference_ids_requiring_removal(issue)
                ),
                "acceptance_criteria": issue.get("fix_suggestion")
                or issue.get("description")
                or "",
            }
        )
    return tasks


def _default_repair_fields(dimension: Any) -> list[str]:
    if dimension == "schema_completeness":
        return list(_SCHEMA_FIELDS)
    if dimension == "citation_accuracy":
        return ["evidence_ids_json"]
    if dimension == "coverage_gaps":
        return ["positioning", "core_features_json", "pricing_summary", "weaknesses_json"]
    if dimension == "cross_competitor_consistency":
        return list(_SCHEMA_FIELDS)
    if dimension == "factual_plausibility":
        return ["positioning", "pricing_summary", "relationship_reason"]
    return ["evidence_ids_json"]


def _identify_bad_evidence_ids(
    issues: list[dict[str, Any]], evidence: list[dict[str, Any]]
) -> list[str]:
    ref_ids = set()
    for issue in issues:
        if issue.get("dimension") in {"citation_accuracy", "evidence_grounding"}:
            ref_ids.update(_reference_ids_requiring_removal(issue))
    if not ref_ids:
        return []
    result = []
    for item in evidence:
        if item.get("reference_id") in ref_ids and item.get("id"):
            result.append(str(item["id"]))
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

        referenced_ids = _parse_evidence_ids(analysis.get("evidence_ids_json"))
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
    return issues


def _make_issue(
    *,
    iteration: int,
    dimension: str,
    severity: str,
    competitor_name: str,
    description: str,
    fix_suggestion: str,
    issue_id: str,
) -> dict[str, Any]:
    return {
        "id": issue_id,
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
