from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import CallTrace as CallTraceModel, Run
from app.db.session import get_db
from app.schemas.run import RunResponse

router = APIRouter(prefix="/runs/{run_id}/observability", tags=["observability"])

STAGE_LABELS: dict[str, str] = {
    "requirement_understanding": "需求理解",
    "focus_profile": "识别关注点",
    "competitor_discovery": "竞品发现",
    "human_confirm_competitors": "人工确认",
    "material_collection": "资料采集",
    "structured_analysis": "结构化分析",
    "report_generation": "报告生成",
    "quality_check": "质量检查",
}


@router.get("")
def get_observability(run_id: str, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        )

    calls = (
        db.query(CallTraceModel)
        .filter(CallTraceModel.run_id == run_id)
        .order_by(CallTraceModel.started_at.asc())
        .all()
    )

    stages_by_name: dict[str, list[dict]] = {}
    for call in calls:
        stage = call.stage or "unknown"
        stages_by_name.setdefault(stage, []).append(call)

    stage_order = list(STAGE_LABELS.keys())
    sorted_stages = sorted(
        stages_by_name.items(),
        key=lambda item: stage_order.index(item[0])
        if item[0] in stage_order
        else len(stage_order),
    )

    stages = []
    total_llm_calls = 0
    total_search_calls = 0
    total_tokens = 0
    total_duration_ms = 0

    for stage_name, stage_calls in sorted_stages:
        stage_duration = sum(c.duration_ms or 0 for c in stage_calls)
        stage_tokens = sum(c.token_count or 0 for c in stage_calls)

        statuses = {c.status for c in stage_calls}
        if "failed" in statuses and "completed" not in statuses:
            stage_status = "failed"
        elif "running" in statuses:
            stage_status = "running"
        else:
            stage_status = "completed"

        total_llm_calls += sum(1 for c in stage_calls if c.call_type == "llm")
        total_search_calls += sum(1 for c in stage_calls if c.call_type == "search")
        total_tokens += stage_tokens
        total_duration_ms += stage_duration

        stages.append(
            {
                "stage": stage_name,
                "label": STAGE_LABELS.get(stage_name, stage_name),
                "status": stage_status,
                "duration_ms": stage_duration,
                "total_tokens": stage_tokens,
                "calls": stage_calls,
            }
        )

    stats = {
        "total_llm_calls": total_llm_calls,
        "total_search_calls": total_search_calls,
        "total_tokens": total_tokens,
        "total_duration_ms": total_duration_ms,
    }

    return {
        "run": {c.key: (v.isoformat() if isinstance(v, datetime) else v) for c, v in ((c, getattr(run, c.key)) for c in run.__table__.columns)},
        "stages": stages,
        "stats": stats,
    }
