from datetime import datetime

from pydantic import BaseModel, field_validator


class ChatRequest(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("消息不能为空")
        if len(v) > 2000:
            raise ValueError("消息不能超过 2000 字")
        return v


class ChatMessageResponse(BaseModel):
    id: str
    run_id: str
    role: str
    content: str
    intent: str | None = None
    action_type: str | None = None
    report_version: int | None = None
    metadata_json: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatResponse(BaseModel):
    message: ChatMessageResponse
    report_version: int | None = None
    intent: str | None = None
    action_type: str | None = None
