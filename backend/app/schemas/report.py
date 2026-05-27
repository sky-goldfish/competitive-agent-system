from datetime import datetime

from pydantic import BaseModel

from app.schemas.evidence import EvidenceResponse
from app.schemas.source import SourceResponse


class ReportResponse(BaseModel):
    id: str
    run_id: str
    title: str
    markdown_content: str
    summary: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CitationAnalysisRef(BaseModel):
    id: str
    competitor_id: str
    competitor_name: str
    claim_types: list[str]


class CitationMapItem(BaseModel):
    reference_id: int
    source: SourceResponse
    evidence: list[EvidenceResponse]
    analyses: list[CitationAnalysisRef]
