from datetime import datetime

from pydantic import BaseModel


class ReportResponse(BaseModel):
    id: str
    run_id: str
    title: str
    markdown_content: str
    summary: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
