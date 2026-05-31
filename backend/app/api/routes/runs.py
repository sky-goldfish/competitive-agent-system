from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Run
from app.db.session import get_db
from app.schemas.competitor import ConfirmCompetitorsRequest
from app.schemas.run import RunCreateRequest, RunResponse
from app.services.run_service import (
    InvalidRunStateError,
    RunNotFoundError,
    confirm_and_continue_run,
    execute_discovery_run,
    execute_report_run,
    get_run_or_raise,
    regenerate_report,
    start_run,
)

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
def create_run(payload: RunCreateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    run = start_run(db, payload.user_requirement)
    background_tasks.add_task(execute_discovery_run, run.id)
    return run


@router.get("", response_model=list[RunResponse])
def list_runs(db: Session = Depends(get_db)):
    return db.query(Run).order_by(Run.created_at.desc()).limit(50).all()


@router.get("/{run_id}", response_model=RunResponse)
def get_run(run_id: str, db: Session = Depends(get_db)):
    try:
        return get_run_or_raise(db, run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{run_id}/competitors/confirm", response_model=RunResponse)
def confirm_competitors(run_id: str, payload: ConfirmCompetitorsRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        run = confirm_and_continue_run(db, run_id, payload.competitor_ids, [item.model_dump() for item in payload.custom_competitors])
        background_tasks.add_task(execute_report_run, run.id)
        return run
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidRunStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{run_id}/regenerate", response_model=RunResponse)
def regenerate_run_report(run_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        run = get_run_or_raise(db, run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if run.status not in ("completed", "failed"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Can only regenerate report for completed or failed runs.")
    run.status = "running"
    run.current_stage = "report_generation"
    db.commit()
    db.refresh(run)
    background_tasks.add_task(regenerate_report, run_id)
    return run


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(run_id: str, db: Session = Depends(get_db)):
    try:
        run = get_run_or_raise(db, run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    db.delete(run)
    db.commit()
