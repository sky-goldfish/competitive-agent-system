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


class RunResponse(BaseModel):
    id: str
    title: str
    user_requirement: str
    requirement_summary: str | None = None
    status: str
    current_stage: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}
