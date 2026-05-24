from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider


def report_generation_node(state: AgentState, llm: LLMProvider) -> AgentState:
    report = llm.generate_report(
        {
            "title": state.get("requirement", {}).get("domain", "竞品分析任务"),
            "user_requirement": state["user_requirement"],
            "requirement_summary": state.get("requirement", {}).get("summary"),
        },
        state["analyses"],
        state["sources"],
    )
    return {**state, "report": report}
