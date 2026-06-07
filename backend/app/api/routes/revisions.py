from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.revision import RevisionResponse, RevisionTraceResponse
from app.services.revision_service import list_revision_traces, list_revisions

router = APIRouter(tags=["revisions"])


@router.get("/runs/{run_id}/revisions", response_model=list[RevisionResponse])
def get_run_revisions(run_id: str, db: Session = Depends(get_db)):
    return [
        RevisionResponse.model_validate(item) for item in list_revisions(db, run_id)
    ]


@router.get(
    "/revisions/{revision_id}/timeline", response_model=list[RevisionTraceResponse]
)
def get_revision_timeline(revision_id: str, db: Session = Depends(get_db)):
    traces = list_revision_traces(db, revision_id)
    if not traces:
        return []
    return [RevisionTraceResponse.model_validate(item) for item in traces]
