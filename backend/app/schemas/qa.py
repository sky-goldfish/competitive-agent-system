from datetime import datetime

from pydantic import BaseModel, Field


class QAIssueResponse(BaseModel):
    id: str | None = None
    dimension: str
    severity: str
    competitor_name: str
    description: str
    fix_suggestion: str
    status: str | None = None
    first_seen_iteration: int | None = None
    last_seen_iteration: int | None = None
    resolved_iteration: int | None = None
    resolution_reason: str | None = None


class QARetryQueryResponse(BaseModel):
    competitor_name: str
    slot: str
    query: str


class QAResultResponse(BaseModel):
    id: str
    run_id: str
    iteration: int
    overall_score: float
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    decision: str
    check_phase: str = "full_check"
    issues: list[QAIssueResponse]
    issue_checklist: list[QAIssueResponse] = Field(default_factory=list)
    retry_instructions: str | None = None
    retry_queries: list[QARetryQueryResponse] = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_db(cls, qa_result) -> "QAResultResponse":
        import json
        issues_raw = qa_result.issues_json or "[]"
        try:
            issues_list = json.loads(issues_raw)
        except (json.JSONDecodeError, TypeError):
            issues_list = []
        if not isinstance(issues_list, list):
            issues_list = []
        scores_raw = getattr(qa_result, "dimension_scores_json", None) or "{}"
        try:
            scores_dict = json.loads(scores_raw)
        except (json.JSONDecodeError, TypeError):
            scores_dict = {}
        if not isinstance(scores_dict, dict):
            scores_dict = {}
        checklist_raw = getattr(qa_result, "issue_checklist_json", None) or "[]"
        try:
            checklist_list = json.loads(checklist_raw)
        except (json.JSONDecodeError, TypeError):
            checklist_list = []
        if not isinstance(checklist_list, list):
            checklist_list = []
        queries_raw = getattr(qa_result, "retry_queries_json", None) or "[]"
        try:
            queries_list = json.loads(queries_raw)
        except (json.JSONDecodeError, TypeError):
            queries_list = []
        if not isinstance(queries_list, list):
            queries_list = []
        return cls(
            id=qa_result.id,
            run_id=qa_result.run_id,
            iteration=qa_result.iteration,
            overall_score=qa_result.overall_score,
            dimension_scores={
                str(key): float(value)
                for key, value in scores_dict.items()
                if isinstance(value, int | float)
            },
            decision=qa_result.decision,
            check_phase=getattr(qa_result, "check_phase", None) or "full_check",
            issues=[QAIssueResponse(**i) for i in issues_list if isinstance(i, dict)],
            issue_checklist=[QAIssueResponse(**i) for i in checklist_list if isinstance(i, dict)],
            retry_instructions=qa_result.retry_instructions,
            retry_queries=[QARetryQueryResponse(**q) for q in queries_list if isinstance(q, dict)],
            created_at=qa_result.created_at,
        )
