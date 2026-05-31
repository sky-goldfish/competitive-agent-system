from datetime import datetime

from pydantic import BaseModel


class OverlapDimension(BaseModel):
    dimension: str
    detail: str


class CompetitorResponse(BaseModel):
    id: str
    run_id: str
    name: str
    website: str | None = None
    description: str
    category: str
    region: str | None = None
    confidence: float
    selected: bool
    discovery_source: str
    relationship_type: str = "direct"
    relationship_reason: str | None = None
    overlap_dimensions: list[OverlapDimension] | None = None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def from_orm_with_parsed_dimensions(obj):
        import json
        data = {
            "id": obj.id,
            "run_id": obj.run_id,
            "name": obj.name,
            "website": obj.website,
            "description": obj.description,
            "category": obj.category,
            "region": obj.region,
            "confidence": obj.confidence,
            "selected": obj.selected,
            "discovery_source": obj.discovery_source,
            "relationship_type": obj.relationship_type,
            "relationship_reason": obj.relationship_reason,
            "overlap_dimensions": None,
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
        }
        if obj.overlap_dimensions_json:
            try:
                data["overlap_dimensions"] = json.loads(obj.overlap_dimensions_json)
            except (json.JSONDecodeError, TypeError):
                data["overlap_dimensions"] = None
        return CompetitorResponse(**data)

    model_config = {"from_attributes": True}


class CustomCompetitorInput(BaseModel):
    name: str
    website: str | None = None
    category: str = "direct_competitor"
    region: str | None = None


class ConfirmCompetitorsRequest(BaseModel):
    competitor_ids: list[str]
    custom_competitors: list[CustomCompetitorInput] = []
