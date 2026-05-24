from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Report
from app.db.session import get_db
from app.schemas.report import ReportResponse

router = APIRouter(prefix="/runs/{run_id}/report", tags=["reports"])


@router.get("", response_model=ReportResponse)
def get_report(run_id: str, db: Session = Depends(get_db)):
    report = db.query(Report).filter(Report.run_id == run_id).first()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    return report
