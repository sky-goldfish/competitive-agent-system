from datetime import datetime

from pydantic import BaseModel


class TraceResponse(BaseModel):
    id: str
    run_id: str
    stage: str
    status: str
    input_json: str | None = None
    output_json: str | None = None
    error_message: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
