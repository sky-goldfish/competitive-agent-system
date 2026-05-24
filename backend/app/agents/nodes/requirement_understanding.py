from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider


def requirement_understanding_node(state: AgentState, llm: LLMProvider) -> AgentState:
    requirement = llm.understand_requirement(state["user_requirement"])
    return {**state, "requirement": requirement}
