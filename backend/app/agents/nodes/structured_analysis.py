from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from typing import Any
from uuid import uuid4

from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider

try:
    from app.services import call_tracer
except ModuleNotFoundError:
    class _NoopCallTracer:
        @staticmethod
        def get_trace_context() -> dict[str, Any] | None:
            return None

        @staticmethod
        def set_worker_trace_context(trace_ctx: dict[str, Any] | None) -> None:
            return None

    call_tracer = _NoopCallTracer()

logger = logging.getLogger(__name__)


def structured_analysis_node(state: AgentState, llm: LLMProvider) -> AgentState:
    competitors = state.get("selected_competitors", [])
    evidence = state.get("evidence", [])
    focus_items = _active_focus_items(state.get("requirement", {}))
    existing_analyses = _dedupe_analyses_by_competitor(
        state.get("analyses", []), competitors
    )
    existing_by_competitor = {
        str(item.get("competitor_id")): item
        for item in existing_analyses
        if item.get("competitor_id")
    }
    retry_ids = state.get("qa_retry_analysis_ids")
    retry_queries = state.get("qa_retry_queries")
    qa_retry_guidance_map = state.get("qa_retry_guidance_map")
    qa_repair_tasks = state.get("qa_repair_tasks") or []
    qa_bad_evidence_ids = {str(item) for item in state.get("qa_bad_evidence_ids", [])}

    affected_ids = set(retry_ids or [])
    if not affected_ids and retry_queries:
        query_names = {
            rq.get("competitor_name")
            for rq in retry_queries
            if rq.get("competitor_name")
        }
        name_to_id: dict[str, str] = {}
        for c in competitors:
            name_to_id.setdefault(c["name"], c["id"])
        matched_ids = {name_to_id[n] for n in query_names if n in name_to_id}
        if not matched_ids and query_names:
            from difflib import get_close_matches

            for qn in query_names:
                matches = get_close_matches(qn, name_to_id.keys(), n=1, cutoff=0.6)
                if matches:
                    matched_ids.add(name_to_id[matches[0]])
        affected_ids = matched_ids

    if affected_ids and existing_analyses:
        keep = [
            a for a in existing_analyses if a.get("competitor_id") not in affected_ids
        ]
        retry_competitors = [c for c in competitors if c["id"] in affected_ids]
    elif existing_analyses and (retry_ids or retry_queries):
        logger.warning(
            "QA retry requested but no competitors matched; skipping re-analysis. "
            "retry_names=%s available_names=%s",
            {rq.get("competitor_name") for rq in (retry_queries or [])},
            [c["name"] for c in competitors],
        )
        return {**state, "analyses": existing_analyses}
    else:
        keep = []
        retry_competitors = competitors

    def analyze_one(competitor: dict, trace_ctx: dict | None) -> dict:
        call_tracer.set_worker_trace_context(trace_ctx)
        competitor_evidence = [
            item
            for item in evidence
            if item.get("competitor_id") == competitor["id"]
            or item.get("related_product") == competitor.get("name")
        ]
        if qa_bad_evidence_ids:
            competitor_evidence = [
                item
                for item in competitor_evidence
                if str(item.get("id") or "") not in qa_bad_evidence_ids
            ]
        comp = competitor
        feedback = (qa_retry_guidance_map or {}).get(competitor["name"])
        repair_tasks = _repair_tasks_for_competitor(qa_repair_tasks, competitor)
        if focus_items or (feedback and (retry_ids or retry_queries)) or repair_tasks:
            comp = {**competitor}
            if focus_items:
                comp["_focus_schema"] = [
                    {
                        "key": f["key"],
                        "label": f["label"],
                        "evidence_expectation": f.get("evidence_expectation", ""),
                    }
                    for f in focus_items
                ]
            if feedback and (retry_ids or retry_queries):
                comp["_qa_feedback"] = feedback
            if repair_tasks:
                comp["_qa_repair_tasks"] = repair_tasks
        analysis = llm.analyze_competitor(comp, competitor_evidence)
        analysis["custom_focus_analysis_json"] = _normalize_custom_focus_analysis(
            analysis.get("custom_focus_analysis_json"),
            focus_items,
            competitor_evidence,
        )
        analysis["id"] = f"ana_{uuid4().hex[:12]}"
        analysis["analysis_iteration"] = state.get("feedback_loop_count", 0)
        # Preserve LLM-returned evidence_ids_json when valid; only fall back to full
        # evidence set when the LLM didn't provide one.
        llm_evidence_ids = _parse_json_list(analysis.get("evidence_ids_json"))
        valid_ev_ids = {item.get("id") for item in competitor_evidence if item.get("id")}
        if llm_evidence_ids and all(str(eid) in valid_ev_ids for eid in llm_evidence_ids):
            # LLM returned valid evidence IDs — keep them as-is (already ev_xxx after
            # the ref_id→ev_id conversion in the provider layer).
            filtered_ids = [
                str(eid) for eid in llm_evidence_ids if str(eid) not in qa_bad_evidence_ids
            ]
            analysis["evidence_ids_json"] = json.dumps(filtered_ids, ensure_ascii=False)
        else:
            analysis["evidence_ids_json"] = json.dumps(
                [item["id"] for item in competitor_evidence if item.get("id")],
                ensure_ascii=False,
            )
        return {
            **analysis,
            "competitor_id": competitor["id"],
            "competitor_name": competitor["name"],
        }

    new_analyses = []
    if not retry_competitors:
        return {**state, "analyses": _dedupe_analyses_by_competitor(keep, competitors)}
    trace_ctx = call_tracer.get_trace_context()
    with ThreadPoolExecutor(max_workers=min(4, len(retry_competitors))) as executor:
        futures = {executor.submit(analyze_one, c, trace_ctx): c for c in retry_competitors}
        try:
            for future in as_completed(futures, timeout=300):
                new_analyses.append(future.result())
        except TimeoutError:
            for f in futures:
                if f.done():
                    try:
                        new_analyses.append(f.result())
                    except Exception:
                        pass
            timed_out = [futures[f]["name"] for f in futures if not f.done()]
            logger.error(
                "Structured analysis timed out for competitors: %s",
                ", ".join(timed_out),
            )

    accepted_new_analyses = _accept_non_regressive_analyses(
        new_analyses,
        retry_competitors,
        existing_by_competitor,
        qa_repair_tasks,
    )
    analyses = _dedupe_analyses_by_competitor(keep + accepted_new_analyses, competitors)
    analyses.sort(
        key=lambda a: next(
            (i for i, c in enumerate(competitors) if c["id"] == a["competitor_id"]), 0
        )
    )
    return {**state, "analyses": analyses}


def _accept_non_regressive_analyses(
    candidates: list[dict[str, Any]],
    retry_competitors: list[dict[str, Any]],
    previous_by_competitor: dict[str, dict[str, Any]],
    repair_tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidate_by_competitor = {
        str(item.get("competitor_id")): item
        for item in _dedupe_analyses_by_competitor(candidates, retry_competitors)
        if item.get("competitor_id")
    }
    accepted: list[dict[str, Any]] = []
    for competitor in retry_competitors:
        cid = str(competitor.get("id") or "")
        candidate = candidate_by_competitor.get(cid)
        previous = previous_by_competitor.get(cid)
        if candidate is None:
            if previous is not None:
                accepted.append(previous)
            continue
        tasks = _repair_tasks_for_competitor(repair_tasks, competitor)
        if previous is not None and _is_regressive_analysis(candidate, previous, tasks):
            logger.warning(
                "Structured analysis regression detected for %s; keeping previous analysis",
                competitor.get("name") or cid,
            )
            accepted.append(previous)
        else:
            accepted.append(candidate)
    return accepted


def _is_regressive_analysis(
    candidate: dict[str, Any],
    previous: dict[str, Any],
    repair_tasks: list[dict[str, Any]],
) -> bool:
    if _analysis_quality_score(candidate) + 2 < _analysis_quality_score(previous):
        return True
    for task in repair_tasks:
        for field in task.get("fields") or []:
            if _is_placeholder(candidate.get(field)) and not _is_placeholder(
                previous.get(field)
            ):
                return True
    return False


def _analysis_quality_score(analysis: dict[str, Any]) -> int:
    fields = (
        "positioning",
        "target_users",
        "core_features_json",
        "pricing_summary",
        "strengths_json",
        "weaknesses_json",
        "opportunities_json",
    )
    score = 0
    for field in fields:
        score += 2 if not _is_placeholder(analysis.get(field)) else -2
    evidence_count = len(_parse_json_list(analysis.get("evidence_ids_json")))
    score += min(evidence_count, 8)
    return score


def _dedupe_analyses_by_competitor(
    analyses: list[dict[str, Any]], competitors: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    competitor_order = {
        str(competitor.get("id")): index
        for index, competitor in enumerate(competitors)
        if competitor.get("id")
    }
    latest: dict[str, dict[str, Any]] = {}
    original_order: dict[str, int] = {}
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
        original_order.setdefault(key, index)
        existing = latest.get(key)
        if existing is None or _analysis_sort_key(analysis, index) >= _analysis_sort_key(
            existing, latest_index[key]
        ):
            latest[key] = analysis
            latest_index[key] = index
    return sorted(
        latest.values(),
        key=lambda item: (
            competitor_order.get(str(item.get("competitor_id")), len(competitor_order)),
            original_order.get(
                str(
                    item.get("competitor_id")
                    or item.get("competitor_name")
                    or item.get("id")
                    or ""
                ),
                0,
            ),
        ),
    )


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


def _is_placeholder(value: Any) -> bool:
    if isinstance(value, list):
        return len([item for item in value if not _is_placeholder(item)]) == 0
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return True
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return True
            if isinstance(parsed, list):
                return _is_placeholder(parsed)
            return True
        lowered = text.lower()
        return any(
            marker in lowered
            for marker in (
                "暂无",
                "未涉及",
                "无相关",
                "待补充",
                "占位",
                "mock",
                "n/a",
                "unknown",
            )
        )
    return value is None


def _active_focus_items(requirement: dict) -> list[dict]:
    """Return user-explicit focus items from the normalized focus profile."""
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
            items.append(f)
    return items[:6]


def _repair_tasks_for_competitor(
    tasks: list[dict[str, Any]], competitor: dict[str, Any]
) -> list[dict[str, Any]]:
    result = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("competitor_id") and task.get("competitor_id") == competitor.get("id"):
            result.append(task)
        elif task.get("competitor_name") == competitor.get("name"):
            result.append(task)
    return result


def _normalize_custom_focus_analysis(
    value: object, focus_items: list[dict], evidence: list[dict]
) -> str:
    if not focus_items:
        return "[]"
    focus_by_key = {
        str(item.get("key") or ""): item
        for item in focus_items
        if isinstance(item, dict) and item.get("key") and item.get("label")
    }
    focus_by_label = {
        str(item.get("label") or "").strip(): item
        for item in focus_items
        if isinstance(item, dict) and item.get("key") and item.get("label")
    }
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = []
    if not isinstance(parsed, list):
        parsed = []
    valid_evidence_ids = {item.get("id") for item in evidence if item.get("id")}
    normalized = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        raw_key = str(item.get("focus_key") or item.get("key") or "").strip()
        raw_label = str(item.get("label") or "").strip()
        focus_schema_item = focus_by_key.get(raw_key) or focus_by_label.get(raw_label)
        if not focus_schema_item:
            continue
        focus_key = str(focus_schema_item.get("key") or "").strip()
        label = str(focus_schema_item.get("label") or "").strip()
        evidence_ids = (
            [
                str(evidence_id)
                for evidence_id in item.get("evidence_ids", [])
                if evidence_id in valid_evidence_ids
            ]
            if isinstance(item.get("evidence_ids"), list)
            else []
        )
        normalized.append(
            {
                "focus_key": focus_key[:64],
                "label": label[:80],
                "verdict": str(item.get("verdict") or "证据中未涉及")[:800],
                "evidence_ids": evidence_ids[:6],
                "confidence": _bounded_confidence(item.get("confidence")),
            }
        )
    if normalized:
        return json.dumps(normalized[:6], ensure_ascii=False)
    empty_items = [
        {
            "focus_key": item["key"],
            "label": item["label"],
            "verdict": "证据中未涉及",
            "evidence_ids": [],
            "confidence": 0.0,
        }
        for item in focus_items
    ]
    return json.dumps(empty_items, ensure_ascii=False)


def _bounded_confidence(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score > 1:
        score = score / 100
    return min(1.0, max(0.0, score))


def _parse_json_list(value: Any) -> list[str]:
    """Parse a JSON string or list into a flat list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    return []
