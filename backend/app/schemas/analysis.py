import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel


def parse_focus_analysis_json(raw_json: str | None) -> list[dict[str, Any]]:
    """Parse Analysis.custom_focus_analysis_json into a list of validated dict items."""
    if not raw_json:
        return []
    try:
        parsed = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


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
    custom_focus_analysis_json: str = "[]"
    item_evidence_bindings_json: str = "{}"
    field_evidence_ids_json: str = "{}"
    evidence_ids_json: str
    analysis_iteration: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}
