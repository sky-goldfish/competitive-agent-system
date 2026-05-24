from pydantic import BaseModel


class EvidenceResponse(BaseModel):
    id: str
    run_id: str
    source_id: str
    related_product: str
    related_dimension: str
    quote: str
    summary: str
    confidence: float

    model_config = {"from_attributes": True}
