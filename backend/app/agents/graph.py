from collections.abc import Callable

from langgraph.graph import END, StateGraph

from app.agents.nodes.competitor_discovery import competitor_discovery_node
from app.agents.nodes.human_confirm_competitors import human_confirm_competitors_node
from app.agents.nodes.material_collection import material_collection_node
from app.agents.nodes.report_generation import report_generation_node
from app.agents.nodes.requirement_understanding import requirement_understanding_node
from app.agents.nodes.structured_analysis import structured_analysis_node
from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider
from app.providers.search.base import SearchProvider

TraceCallback = Callable[[str, AgentState, Callable[[], AgentState]], AgentState]
ProgressCallback = Callable[[str, str, dict], None]


def build_competitor_discovery_graph(
    llm: LLMProvider,
    search: SearchProvider,
    trace: TraceCallback | None = None,
    progress: ProgressCallback | None = None,
):
    graph = StateGraph(AgentState)

    def requirement_understanding(state: AgentState) -> AgentState:
        return _run_node(trace, "requirement_understanding", state, lambda: requirement_understanding_node(state, llm))

    def competitor_discovery(state: AgentState) -> AgentState:
        return _run_node(trace, "competitor_discovery", state, lambda: competitor_discovery_node(state, llm, search, progress=progress))

    def human_confirm_competitors(state: AgentState) -> AgentState:
        return _run_node(trace, "human_confirm_competitors", state, lambda: human_confirm_competitors_node(state))

    graph.add_node("requirement_understanding", requirement_understanding)
    graph.add_node("competitor_discovery", competitor_discovery)
    graph.add_node("human_confirm_competitors", human_confirm_competitors)
    graph.set_entry_point("requirement_understanding")
    graph.add_edge("requirement_understanding", "competitor_discovery")
    graph.add_edge("competitor_discovery", "human_confirm_competitors")
    graph.add_edge("human_confirm_competitors", END)
    return graph.compile()


def build_report_generation_graph(
    llm: LLMProvider,
    search: SearchProvider,
    trace: TraceCallback | None = None,
    progress: ProgressCallback | None = None,
):
    graph = StateGraph(AgentState)

    def material_collection(state: AgentState) -> AgentState:
        return _run_node(trace, "material_collection", state, lambda: material_collection_node(state, search, progress=progress))

    def structured_analysis(state: AgentState) -> AgentState:
        return _run_node(trace, "structured_analysis", state, lambda: structured_analysis_node(state, llm))

    def report_generation(state: AgentState) -> AgentState:
        return _run_node(trace, "report_generation", state, lambda: report_generation_node(state, llm))

    graph.add_node("material_collection", material_collection)
    graph.add_node("structured_analysis", structured_analysis)
    graph.add_node("report_generation", report_generation)
    graph.set_entry_point("material_collection")
    graph.add_edge("material_collection", "structured_analysis")
    graph.add_edge("structured_analysis", "report_generation")
    graph.add_edge("report_generation", END)
    return graph.compile()


def _run_node(trace: TraceCallback | None, stage: str, state: AgentState, action: Callable[[], AgentState]) -> AgentState:
    if trace is None:
        return action()
    return trace(stage, state, action)
