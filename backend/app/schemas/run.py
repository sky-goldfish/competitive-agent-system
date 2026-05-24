from datetime import datetime

from pydantic import BaseModel


class RunCreateRequest(BaseModel):
    user_requirement: str


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
