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
    trace.output_json = json.dumps(
        _summarize_output(stage, output), ensure_ascii=False, default=str
    )
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
    duration_ms: int | None = None,
    started_at: datetime | None = None,
) -> None:
    now = datetime.utcnow()
    if started_at is None:
        started_at = now
    if duration_ms is None:
        duration_ms = int((now - started_at).total_seconds() * 1000)

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
        started_at=started_at,
        ended_at=now,
        duration_ms=duration_ms,
    )
    db.add(trace)
    db.commit()


def _summarize_output(stage: str, output: dict[str, Any]) -> dict[str, Any]:
    if stage == "requirement_understanding":
        requirement = output.get("requirement", {})
        return {
            "input_type": requirement.get("input_type"),
            "target_product": requirement.get("target_product"),
            "product_description": requirement.get("product_description"),
            "domain": requirement.get("domain"),
            "possible_market_category": requirement.get("possible_market_category"),
            "summary": requirement.get("summary"),
            "target_users": requirement.get("target_users") or [],
            "core_capabilities": requirement.get("core_capabilities") or [],
            "use_cases": requirement.get("use_cases") or [],
            "analysis_dimensions": requirement.get("analysis_dimensions") or [],
            "dimension_count": len(requirement.get("analysis_dimensions", [])),
            "queries": requirement.get("queries")
            or ([requirement.get("query")] if requirement.get("query") else []),
            "confidence": requirement.get("confidence"),
            "warnings": requirement.get("warnings") or [],
        }
    if stage == "focus_profile":
        requirement = output.get("requirement", {})
        profile = (
            requirement.get("focus_profile", {})
            if isinstance(requirement, dict)
            else {}
        )
        return {
            "explicit_focuses": profile.get("explicit_focuses") or [],
            "inferred_focuses": profile.get("inferred_focuses") or [],
            "clarification_needed": profile.get("clarification_needed"),
            "clarifying_question": profile.get("clarifying_question"),
            "assumptions": profile.get("assumptions") or [],
        }
    if stage == "competitor_discovery":
        target = output.get("target_understanding", {})
        return {
            "target": target.get("name"),
            "target_category": target.get("category"),
            "target_confidence": target.get("confidence"),
            "competitor_count": len(output.get("competitors") or []),
            "target_search_result_count": len(
                output.get("target_search_results") or []
            ),
            "competitor_search_result_count": len(
                output.get("competitor_search_results", [])
            ),
            "competitors": [item.get("name") for item in output.get("competitors", [])],
        }
    if stage == "human_confirm_competitors":
        return {
            "status": output.get("status"),
            "candidate_count": len(output.get("competitors") or []),
        }
    if stage == "material_collection":
        return {
            "source_count": len(output.get("sources") or []),
            "evidence_count": len(output.get("evidence") or []),
        }
    if stage == "structured_analysis":
        return {"analysis_count": len(output.get("analyses") or [])}
    if stage == "report_generation":
        report = output.get("report", {})
        return {"title": report.get("title"), "summary": report.get("summary")}
    if stage == "quality_check":
        qa = output.get("qa_result", {})
        return {
            "overall_score": qa.get("overall_score"),
            "decision": qa.get("decision"),
            "issue_count": len(qa.get("issues", [])),
            "iteration": qa.get("iteration"),
            "check_phase": qa.get("check_phase"),
        }
    return {"stage": stage, "status": "completed"}
