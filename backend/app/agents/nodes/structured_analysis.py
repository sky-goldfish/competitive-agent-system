from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from typing import Any

from app.agents.state import AgentState
from app.db.models import new_id
from app.providers.llm.base import LLMProvider
from app.services import call_tracer

logger = logging.getLogger(__name__)


def structured_analysis_node(state: AgentState, llm: LLMProvider) -> AgentState:
    competitors = state.get("selected_competitors", [])
    evidence = state.get("evidence", [])
    focus_items = _active_focus_items(state.get("requirement", {}))
    existing_analyses = state.get("analyses", [])
    retry_ids = state.get("qa_retry_analysis_ids")
    retry_queries = state.get("qa_retry_queries")
    qa_retry_guidance_map = state.get("qa_retry_guidance_map")

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
        comp = competitor
        feedback = (qa_retry_guidance_map or {}).get(competitor["name"])
        if focus_items or (feedback and (retry_ids or retry_queries)):
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
        analysis = llm.analyze_competitor(comp, competitor_evidence)
        analysis["custom_focus_analysis_json"] = _normalize_custom_focus_analysis(
            analysis.get("custom_focus_analysis_json"),
            focus_items,
            competitor_evidence,
        )
        analysis["id"] = new_id("ana")
        analysis["analysis_iteration"] = state.get("feedback_loop_count", 0)
        # Preserve LLM-returned evidence_ids_json when valid; only fall back to full
        # evidence set when the LLM didn't provide one.
        llm_evidence_ids = _parse_json_list(analysis.get("evidence_ids_json"))
        valid_ev_ids = {item.get("id") for item in competitor_evidence if item.get("id")}
        if llm_evidence_ids and all(
            str(eid) in valid_ev_ids for eid in llm_evidence_ids
        ):
            # LLM returned valid evidence IDs — keep them as-is (already ev_xxx after
            # the ref_id→ev_id conversion in the provider layer).
            pass
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
        return {**state, "analyses": keep + new_analyses}
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

    analyses = keep + new_analyses
    analyses.sort(
        key=lambda a: next(
            (i for i, c in enumerate(competitors) if c["id"] == a["competitor_id"]), 0
        )
    )
    return {**state, "analyses": analyses}


def _active_focus_items(requirement: dict) -> list[dict]:
    """Return active focus items from the already-normalized focus profile."""
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
            items.append(f)
    return items[:6]


def _normalize_custom_focus_analysis(
    value: object, focus_items: list[dict], evidence: list[dict]
) -> str:
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
        label = str(item.get("label") or "").strip()
        if not label:
            continue
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
                "focus_key": str(
                    item.get("focus_key")
                    or item.get("key")
                    or f"focus_{len(normalized) + 1}"
                )[:64],
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
