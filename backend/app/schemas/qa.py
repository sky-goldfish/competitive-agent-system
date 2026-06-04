from datetime import datetime

from pydantic import BaseModel


class QAIssueResponse(BaseModel):
    dimension: str
    severity: str
    competitor_name: str
    description: str
    fix_suggestion: str


class QAResultResponse(BaseModel):
    id: str
    run_id: str
    iteration: int
    overall_score: float
    decision: str
    issues: list[QAIssueResponse]
    retry_instructions: str | None = None
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
        return cls(
            id=qa_result.id,
            run_id=qa_result.run_id,
            iteration=qa_result.iteration,
            overall_score=qa_result.overall_score,
            decision=qa_result.decision,
            issues=[QAIssueResponse(**i) for i in issues_list if isinstance(i, dict)],
            retry_instructions=qa_result.retry_instructions,
            created_at=qa_result.created_at,
        )
