from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.models import Analysis, Run
from app.db.session import get_db
from app.schemas.analysis import AnalysisResponse
from app.services.analysis_service import latest_analyses_by_competitor

router = APIRouter(prefix="/runs/{run_id}/analyses", tags=["analyses"])


@router.get("", response_model=list[AnalysisResponse])
def list_analyses(
    run_id: str,
    include_history: bool = Query(False),
    db: Session = Depends(get_db),
):
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    if not include_history:
        return latest_analyses_by_competitor(db, run_id)
    return db.query(Analysis).filter(Analysis.run_id == run_id).order_by(Analysis.created_at.asc()).all()
