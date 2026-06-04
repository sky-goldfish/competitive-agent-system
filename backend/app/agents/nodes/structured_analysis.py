from concurrent.futures import ThreadPoolExecutor, as_completed
import json

from app.agents.state import AgentState
from app.db.models import new_id
from app.providers.llm.base import LLMProvider


def structured_analysis_node(state: AgentState, llm: LLMProvider) -> AgentState:
    competitors = state["selected_competitors"]
    evidence = state["evidence"]
    existing_analyses = state.get("analyses", [])
    retry_ids = state.get("qa_retry_analysis_ids")
    qa_retry_guidance = state.get("qa_retry_guidance")
    retry_queries = state.get("qa_retry_queries")

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
        if qa_retry_guidance and (retry_ids or retry_queries):
            comp = {**competitor, "_qa_feedback": qa_retry_guidance}
        analysis = llm.analyze_competitor(comp, competitor_evidence)
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
