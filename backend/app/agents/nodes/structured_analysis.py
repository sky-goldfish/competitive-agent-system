from concurrent.futures import ThreadPoolExecutor, as_completed
import json

from app.agents.state import AgentState
from app.db.models import new_id
from app.providers.llm.base import LLMProvider


def structured_analysis_node(state: AgentState, llm: LLMProvider) -> AgentState:
    competitors = state["selected_competitors"]
    evidence = state["evidence"]
    focus_items = _active_focus_items(state.get("requirement", {}))
    existing_analyses = state.get("analyses", [])
    retry_ids = state.get("qa_retry_analysis_ids")
    retry_queries = state.get("qa_retry_queries")
    qa_retry_guidance_map = state.get("qa_retry_guidance_map")

    affected_ids = set(retry_ids or [])
    if not affected_ids and retry_queries:
        affected_ids = {rq["competitor_name"] for rq in retry_queries if rq.get("competitor_name")}
        name_to_id = {c["name"]: c["id"] for c in competitors}
        affected_ids = {name_to_id[n] for n in affected_ids if n in name_to_id}

    if affected_ids and existing_analyses:
        keep = [a for a in existing_analyses if a.get("competitor_id") not in affected_ids]
        retry_competitors = [c for c in competitors if c["id"] in affected_ids]
    else:
        keep = []
        retry_competitors = competitors

    def analyze_one(competitor: dict) -> dict:
        competitor_evidence = [item for item in evidence if item["competitor_id"] == competitor["id"]]
        comp = competitor
        feedback = (qa_retry_guidance_map or {}).get(competitor["name"])
        if focus_items or (feedback and (retry_ids or retry_queries)):
            comp = {**competitor}
            if focus_items:
                comp["_focus_schema"] = [
                    {"key": f["key"], "label": f["label"], "evidence_expectation": f.get("evidence_expectation", "")}
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
        analysis["evidence_ids_json"] = json.dumps([item["id"] for item in competitor_evidence if item.get("id")], ensure_ascii=False)
        return {**analysis, "competitor_id": competitor["id"], "competitor_name": competitor["name"]}

    new_analyses = []
    with ThreadPoolExecutor(max_workers=min(4, len(retry_competitors))) as executor:
        futures = {executor.submit(analyze_one, c): c for c in retry_competitors}
        for future in as_completed(futures):
            new_analyses.append(future.result())

    analyses = keep + new_analyses
    analyses.sort(key=lambda a: next((i for i, c in enumerate(competitors) if c["id"] == a["competitor_id"]), 0))
    return {**state, "analyses": analyses}


def _active_focus_items(requirement: dict) -> list[dict]:
    """Return active focus items from the already-normalized focus profile."""
    profile = requirement.get("focus_profile") if isinstance(requirement.get("focus_profile"), dict) else {}
    if not isinstance(profile, dict):
        return []
    items = []
    for f in (profile.get("explicit_focuses") or []) + (profile.get("inferred_focuses") or []):
        if isinstance(f, dict) and f.get("label"):
            items.append(f)
    return items[:6]


def _normalize_custom_focus_analysis(value: object, focus_items: list[dict], evidence: list[dict]) -> str:
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
        evidence_ids = [
            str(evidence_id)
            for evidence_id in item.get("evidence_ids", [])
            if evidence_id in valid_evidence_ids
        ] if isinstance(item.get("evidence_ids"), list) else []
        normalized.append(
            {
                "focus_key": str(item.get("focus_key") or item.get("key") or f"focus_{len(normalized) + 1}")[:64],
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
