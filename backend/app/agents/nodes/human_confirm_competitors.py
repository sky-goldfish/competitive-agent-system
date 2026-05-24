from app.agents.state import AgentState


def human_confirm_competitors_node(state: AgentState) -> AgentState:
    return {**state, "status": "waiting_for_human"}
