from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import AgentTrace, Run
from app.db.session import get_db
from app.schemas.trace import TraceResponse

router = APIRouter(prefix="/runs/{run_id}/timeline", tags=["timeline"])


@router.get("", response_model=list[TraceResponse])
def list_timeline(run_id: str, db: Session = Depends(get_db)):
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return db.query(AgentTrace).filter(AgentTrace.run_id == run_id).order_by(AgentTrace.created_at.asc()).all()
