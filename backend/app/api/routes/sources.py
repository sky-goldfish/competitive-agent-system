from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import Evidence, Source
from app.db.session import get_db
from app.schemas.evidence import EvidenceResponse
from app.schemas.source import SourceResponse

router = APIRouter(prefix="/runs/{run_id}", tags=["sources"])


@router.get("/sources", response_model=list[SourceResponse])
def list_sources(run_id: str, db: Session = Depends(get_db)):
    return db.query(Source).filter(Source.run_id == run_id).order_by(Source.retrieved_at.asc()).all()


@router.get("/evidence", response_model=list[EvidenceResponse])
def list_evidence(run_id: str, db: Session = Depends(get_db)):
    return db.query(Evidence).filter(Evidence.run_id == run_id).all()
