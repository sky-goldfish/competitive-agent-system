from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Analysis, Run
from app.db.session import get_db
from app.schemas.analysis import AnalysisResponse

router = APIRouter(prefix="/runs/{run_id}/analyses", tags=["analyses"])


@router.get("", response_model=list[AnalysisResponse])
def list_analyses(run_id: str, db: Session = Depends(get_db)):
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return db.query(Analysis).filter(Analysis.run_id == run_id).order_by(Analysis.created_at.asc()).all()
