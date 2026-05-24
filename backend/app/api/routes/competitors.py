from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Competitor, Run
from app.db.session import get_db
from app.schemas.competitor import CompetitorResponse

router = APIRouter(prefix="/runs/{run_id}/competitors", tags=["competitors"])


@router.get("", response_model=list[CompetitorResponse])
def list_competitors(run_id: str, db: Session = Depends(get_db)):
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return db.query(Competitor).filter(Competitor.run_id == run_id).order_by(Competitor.confidence.desc()).all()
