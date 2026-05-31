import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, computed_field


class SourceResponse(BaseModel):
    id: str
    run_id: str
    competitor_id: str | None = None
    title: str
    url: str
    snippet: str
    source_type: str
    provider: str
    retrieved_at: datetime
    metadata_json: str | None = None

    @computed_field
    @property
    def source_type_label(self) -> str | None:
        return _metadata_value(self.metadata_json, "source_type_label")

    @computed_field
    @property
    def credibility_score(self) -> float | None:
        return _metadata_value(self.metadata_json, "credibility_score")

    @computed_field
    @property
    def rank_score(self) -> float | None:
        return _metadata_value(self.metadata_json, "rank_score")

    @computed_field
    @property
    def classification_reason(self) -> str | None:
        return _metadata_value(self.metadata_json, "classification_reason")

    @computed_field
    @property
    def reference_id(self) -> int | None:
        value = _metadata_value(self.metadata_json, "reference_id")
        return int(value) if isinstance(value, (int, float)) else None

    model_config = {"from_attributes": True}


def _metadata_value(metadata_json: str | None, key: str) -> Any:
    if not metadata_json:
        return None
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    return metadata.get(key)
