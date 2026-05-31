import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AgentTrace, Run


def run_traced_stage(
    db: Session,
    run_id: str,
    stage: str,
    input_data: dict[str, Any],
    action: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    started_at = datetime.utcnow()
    run = db.get(Run, run_id)
    if run is not None:
        run.current_stage = stage
        run.updated_at = started_at
    trace = AgentTrace(
        run_id=run_id,
        stage=stage,
        status="running",
        input_json=json.dumps(input_data, ensure_ascii=False, default=str),
        started_at=started_at,
    )
    db.add(trace)
    db.commit()
    db.refresh(trace)

    try:
        output = action()
    except Exception as exc:
        ended_at = datetime.utcnow()
        trace.status = "failed"
        trace.error_message = str(exc)
        trace.ended_at = ended_at
        trace.duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        db.commit()
        raise

    ended_at = datetime.utcnow()
    trace.status = "completed"
    trace.output_json = json.dumps(_summarize_output(stage, output), ensure_ascii=False, default=str)
    trace.ended_at = ended_at
    trace.duration_ms = int((ended_at - started_at).total_seconds() * 1000)
    db.commit()
    return output


def record_progress_trace(
    db: Session,
    run_id: str,
    stage: str,
    message: str,
    metadata: dict[str, Any] | None = None,
    status: str = "completed",
) -> None:
    now = datetime.utcnow()
    payload = {"message": message, **(metadata or {})}
    
    output_payload = metadata or {}
    if metadata and metadata.get("queries"):
        output_payload["queries"] = metadata["queries"]
    
    trace = AgentTrace(
        run_id=run_id,
        stage=stage,
        status=status,
        input_json=json.dumps(payload, ensure_ascii=False, default=str),
        output_json=json.dumps(output_payload, ensure_ascii=False, default=str),
        started_at=now,
        ended_at=now,
        duration_ms=0,
    )
    db.add(trace)
    db.commit()



def _summarize_output(stage: str, output: dict[str, Any]) -> dict[str, Any]:
    if stage == "requirement_understanding":
        requirement = output.get("requirement", {})
        return {
            "domain": requirement.get("domain"),
            "summary": requirement.get("summary"),
            "dimension_count": len(requirement.get("analysis_dimensions", [])),
        }
    if stage == "competitor_discovery":
        target = output.get("target_understanding", {})
        return {
            "target": target.get("name"),
            "target_category": target.get("category"),
            "target_confidence": target.get("confidence"),
            "competitor_count": len(output.get("competitors", [])),
            "target_search_result_count": len(output.get("target_search_results", [])),
            "competitor_search_result_count": len(output.get("competitor_search_results", [])),
            "competitors": [item.get("name") for item in output.get("competitors", [])],
        }
    if stage == "human_confirm_competitors":
        return {"status": output.get("status"), "candidate_count": len(output.get("competitors", []))}
    if stage == "material_collection":
        return {"source_count": len(output.get("sources", [])), "evidence_count": len(output.get("evidence", []))}
    if stage == "structured_analysis":
        return {"analysis_count": len(output.get("analyses", []))}
    if stage == "report_generation":
        report = output.get("report", {})
        return {"title": report.get("title"), "summary": report.get("summary")}
    return {"stage": stage, "status": "completed"}
