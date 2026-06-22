from pydantic import BaseModel


class EvidenceResponse(BaseModel):
    id: str
    run_id: str
    source_id: str
    related_product: str
    related_dimension: str
    claim: str = ""
    quote: str
    summary: str
    confidence: float
    sentiment: str = "neutral"
    evidence_role: str = "background"
    support_type: str = "direct"
    relevance_score: float = 0.8
    source_credibility: float = 0.8
    extraction_method: str = "llm_extraction"

    model_config = {"from_attributes": True}
