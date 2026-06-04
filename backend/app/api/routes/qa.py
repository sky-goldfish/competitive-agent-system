from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import QAResult, Run
from app.db.session import get_db
from app.schemas.qa import QAResultResponse

router = APIRouter(prefix="/runs/{run_id}/qa", tags=["qa"])


@router.get("/results", response_model=list[QAResultResponse])
def get_qa_results(run_id: str, db: Session = Depends(get_db)):
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    results = (
        db.query(QAResult)
        .filter(QAResult.run_id == run_id)
        .order_by(QAResult.iteration.asc())
        .all()
    )
    return [QAResultResponse.from_db(r) for r in results]
