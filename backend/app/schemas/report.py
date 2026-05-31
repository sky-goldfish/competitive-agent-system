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


class CitationBundleEvidenceRef(BaseModel):
    source_reference_id: int | None = None
    source_title: str | None = None
    source_url: str | None = None
    related_dimension: str | None = None
    summary: str | None = None
    quote: str | None = None
    confidence: float | None = None


class CitationBundleClaim(BaseModel):
    claim_type: str
    label: str
    text: str
    evidence: list[CitationBundleEvidenceRef]


class CitationBundleCompetitor(BaseModel):
    competitor_id: str
    competitor_name: str
    claims: list[CitationBundleClaim]
