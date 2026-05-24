from datetime import datetime

from pydantic import BaseModel


class AnalysisResponse(BaseModel):
    id: str
    run_id: str
    competitor_id: str
    positioning: str
    target_users: str
    core_features_json: str
    pricing_summary: str
    strengths_json: str
    weaknesses_json: str
    opportunities_json: str
    evidence_ids_json: str
    created_at: datetime

    model_config = {"from_attributes": True}
