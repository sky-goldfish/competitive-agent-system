from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    run_id: str
    user_requirement: str
    requirement: dict[str, Any]
    target_understanding: dict[str, Any]
    target_search_results: list[dict[str, Any]]
    competitor_search_results: list[dict[str, Any]]
    competitors: list[dict[str, Any]]
    selected_competitors: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    analyses: list[dict[str, Any]]
    report: dict[str, str]
    qa_result: dict[str, Any]
    qa_retry_queries: list[dict[str, Any]]
    feedback_loop_count: int
