from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class KnowledgeItemResponse(BaseModel):
    id: str
    product_name: str
    dimension: str
    claim: str
    summary: str
    confidence: float
    source_type: str
    source_title: str | None = None
    source_url: str | None = None
    run_id: str | None = None
    evidence_id: str | None = None
    metadata_json: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeSearchParams(BaseModel):
    q: str | None = None
    product_name: str | None = None
    dimension: str | None = None
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("q", "product_name", "dimension")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class KnowledgeRebuildResponse(BaseModel):
    run_id: str
    created_count: int
    updated_count: int
    skipped_count: int


class KnowledgeClearResponse(BaseModel):
    deleted_count: int
