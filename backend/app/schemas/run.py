from datetime import datetime

from pydantic import BaseModel, field_validator


class RunCreateRequest(BaseModel):
    user_requirement: str

    @field_validator("user_requirement")
    @classmethod
    def validate_requirement(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("需求描述不能为空")
        if len(v) > 2000:
            raise ValueError("需求描述不能超过 2000 字")
        return v


class ClarificationAnswerRequest(BaseModel):
    answer: str

    @field_validator("answer")
    @classmethod
    def validate_answer(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("补充说明不能为空")
        if len(v) > 1000:
            raise ValueError("补充说明不能超过 1000 字")
        return v


class RunResponse(BaseModel):
    id: str
    title: str
    user_requirement: str
    requirement_summary: str | None = None
    status: str
    current_stage: str
    error_message: str | None = None
    clarification_question: str | None = None
    feedback_loop_count: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}
