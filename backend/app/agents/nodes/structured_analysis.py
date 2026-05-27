from concurrent.futures import ThreadPoolExecutor, as_completed
import json

from app.agents.state import AgentState
from app.db.models import new_id
from app.providers.llm.base import LLMProvider


def structured_analysis_node(state: AgentState, llm: LLMProvider) -> AgentState:
    competitors = state["selected_competitors"]
    evidence = state["evidence"]

    def analyze_one(competitor: dict) -> dict:
        competitor_evidence = [item for item in evidence if item["competitor_id"] == competitor["id"]]
        analysis = llm.analyze_competitor(competitor, competitor_evidence)
        analysis["id"] = new_id("ana")
        analysis["evidence_ids_json"] = json.dumps([item["id"] for item in competitor_evidence if item.get("id")], ensure_ascii=False)
        return {**analysis, "competitor_id": competitor["id"], "competitor_name": competitor["name"]}

    analyses = []
    with ThreadPoolExecutor(max_workers=min(4, len(competitors))) as executor:
        futures = {executor.submit(analyze_one, c): c for c in competitors}
        for future in as_completed(futures):
            analyses.append(future.result())
    analyses.sort(key=lambda a: next((i for i, c in enumerate(competitors) if c["id"] == a["competitor_id"]), 0))
    return {**state, "analyses": analyses}
