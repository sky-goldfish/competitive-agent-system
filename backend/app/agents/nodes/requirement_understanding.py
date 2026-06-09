from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider


def requirement_understanding_node(state: AgentState, llm: LLMProvider) -> AgentState:
    if state.get("requirement"):
        # Resuming — requirement already parsed and enriched
        return {**state}
    requirement = llm.understand_requirement(state.get("user_requirement", ""))
    return {**state, "requirement": requirement}
