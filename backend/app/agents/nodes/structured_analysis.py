from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider


def structured_analysis_node(state: AgentState, llm: LLMProvider) -> AgentState:
    analyses = []
    for competitor in state["selected_competitors"]:
        competitor_evidence = [item for item in state["evidence"] if item["competitor_id"] == competitor["id"]]
        analysis = llm.analyze_competitor(competitor, competitor_evidence)
        analyses.append({**analysis, "competitor_id": competitor["id"], "competitor_name": competitor["name"]})
    return {**state, "analyses": analyses}
