from datetime import datetime

from pydantic import BaseModel


class RevisionResponse(BaseModel):
    id: str
    run_id: str
    base_report_iteration: int
    target_report_iteration: int | None = None
    user_message: str
    intent: str | None = None
    status: str
    error_message: str | None = None
    summary: str | None = None
    chat_user_message_id: str | None = None
    chat_assistant_message_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class RevisionTraceResponse(BaseModel):
    id: str
    revision_id: str
    stage: str
    status: str
    input_json: str | None = None
    output_json: str | None = None
    error_message: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None

    model_config = {"from_attributes": True}
