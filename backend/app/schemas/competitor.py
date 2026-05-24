from datetime import datetime

from pydantic import BaseModel


class CompetitorResponse(BaseModel):
    id: str
    run_id: str
    name: str
    website: str | None = None
    description: str
    category: str
    confidence: float
    selected: bool
    discovery_source: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CustomCompetitorInput(BaseModel):
    name: str
    website: str | None = None
    category: str = "direct_competitor"


class ConfirmCompetitorsRequest(BaseModel):
    competitor_ids: list[str]
    custom_competitors: list[CustomCompetitorInput] = []
