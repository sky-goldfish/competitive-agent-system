import json
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents.graph import (
    build_competitor_discovery_graph,
    build_report_generation_graph,
)
from app.agents.nodes.focus_profile import normalize_focus_profile
from app.agents.nodes.report_generation import report_generation_node
from app.agents.state import AgentState
from app.agents.trace import record_progress_trace, run_traced_stage
from app.db.models import (
    AgentTrace,
    Analysis,
    CallTrace,
    ChatMessage,
    Competitor,
    Evidence,
    Message,
    QAResult,
    Report,
    Run,
    Source,
)
from app.db.session import SessionLocal
from app.providers.llm.factory import get_llm_provider
from app.providers.search.factory import get_search_provider
from app.services import call_tracer


def _progress_callback(
    db: Session, run_id: str, stage: str, message: str, metadata: dict
) -> None:
    start_time_iso = metadata.pop("_start_time", None)
    started_at = None
    duration_ms = None
    if start_time_iso:
        try:
            started_at = datetime.fromisoformat(start_time_iso)
            duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
        except (ValueError, TypeError):
            pass
    record_progress_trace(
        db,
        run_id,
        stage,
        message,
        metadata,
        started_at=started_at,
        duration_ms=duration_ms,
    )
    run = db.get(Run, run_id)
    if run is not None and run.status == "running":
        run.updated_at = datetime.utcnow()
        db.commit()


class RunNotFoundError(ValueError):
    pass


class InvalidRunStateError(ValueError):
    pass


class QueuedRevisionPending(Exception):
    pass


def get_run_or_raise(db: Session, run_id: str) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise RunNotFoundError(f"Run not found: {run_id}")
    reconcile_stale_run_state(db, run)
    return run


def _chat_metadata(metadata_json: str | None) -> dict:
    if not metadata_json:
        return {}
    try:
        value = json.loads(metadata_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _has_unprocessed_queued_revisions(db: Session, run_id: str) -> bool:
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.run_id == run_id, ChatMessage.role == "user")
        .all()
    )
    for message in messages:
        metadata = _chat_metadata(message.metadata_json)
        if metadata.get("queued") and not metadata.get("processed"):
            return True
    return False


def reconcile_stale_run_state(db: Session, run: Run) -> None:
    if run.status != "running":
        return

    now = datetime.utcnow()
    stale_threshold_seconds = 30 * 60
    stale = (
        run.updated_at is not None
        and (now - run.updated_at).total_seconds() > stale_threshold_seconds
    )
    if not stale:
        return

    run.status = "failed"
    run.current_stage = "failed"
    run.error_message = f"run stale (last update: {run.updated_at.isoformat() if run.updated_at else 'unknown'})"
    run.completed_at = now
    db.commit()


def start_run(db: Session, user_requirement: str) -> Run:
    run = Run(
        user_requirement=user_requirement,
        status="running",
        current_stage="requirement_understanding",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def execute_discovery_run(run_id: str) -> None:
    db = SessionLocal()
    try:
        run = get_run_or_raise(db, run_id)
        llm = get_llm_provider()
        search = get_search_provider()
        call_tracer.set_trace_context(run_id, run.current_stage)
        state: AgentState = {"run_id": run.id, "user_requirement": run.user_requirement}
        if run.requirement_json:
            state["requirement"] = json.loads(run.requirement_json)

        graph = build_competitor_discovery_graph(
            llm,
            search,
            trace=lambda stage, current_state, action: (
                call_tracer.update_stage(stage),
                run_traced_stage(
                    db,
                    run.id,
                    stage,
                    _trace_input(stage, current_state),
                    action,
                ),
            )[1],
            progress=lambda stage, message, metadata: _progress_callback(
                db, run.id, stage, message, metadata
            ),
        )
        state = graph.invoke(state)

        run.requirement_summary = state["requirement"]["summary"]
        run.title = state["requirement"]["domain"]
        run.requirement_json = json.dumps(state["requirement"], ensure_ascii=False)
        if state["requirement"].get("focus_profile", {}).get("clarification_needed"):
            focus_profile = state["requirement"].get("focus_profile", {})
            question = str(focus_profile.get("clarifying_question") or "").strip()
            if question:
                db.add(
                    Message(
                        run_id=run.id,
                        role="assistant",
                        content=question,
                        metadata_json=json.dumps(
                            {"kind": "focus_clarification"}, ensure_ascii=False
                        ),
                    )
                )
            run.status = "waiting_for_clarification"
            run.current_stage = "requirement_clarification"
            db.commit()
            return
        if state.get("target_understanding"):
            run.target_understanding_json = json.dumps(
                state["target_understanding"], ensure_ascii=False
            )
        for item in state["competitors"]:
            db.add(Competitor(run_id=run.id, **item))
        run.status = "waiting_for_human"
        run.current_stage = "human_confirm_competitors"
        db.commit()
    except Exception as exc:
        run = db.get(Run, run_id)
        if run is not None:
            run.status = "failed"
            run.error_message = str(exc)
            db.commit()
    finally:
        call_tracer.clear_trace_context()
        db.close()


def answer_requirement_clarification(db: Session, run_id: str, answer: str) -> Run:
    run = get_run_or_raise(db, run_id)
    if run.status != "waiting_for_clarification":
        raise InvalidRunStateError("Run is not waiting for requirement clarification.")
    answer = answer.strip()
    if len(answer) < 1:
        raise InvalidRunStateError("Clarification answer cannot be empty.")

    requirement = json.loads(run.requirement_json or "{}")
    llm = get_llm_provider()
    combined_requirement = f"{run.user_requirement}\n\n用户补充侧重点：{answer}"
    focus_profile = normalize_focus_profile(
        llm.extract_focus_profile(combined_requirement, requirement)
    )
    focus_profile["clarification_needed"] = False
    focus_profile["clarifying_question"] = None
    requirement["focus_profile"] = focus_profile

    db.add(
        Message(
            run_id=run.id,
            role="user",
            content=answer,
            metadata_json=json.dumps(
                {"kind": "focus_clarification_answer"}, ensure_ascii=False
            ),
        )
    )
    run.requirement_json = json.dumps(requirement, ensure_ascii=False)
    run.status = "running"
    run.current_stage = "competitor_discovery"
    db.commit()
    db.refresh(run)
    return run


def confirm_and_continue_run(
    db: Session,
    run_id: str,
    competitor_ids: list[str],
    custom_competitors: list[dict] | None = None,
) -> Run:
    run = get_run_or_raise(db, run_id)
    if run.status != "waiting_for_human":
        raise InvalidRunStateError("Run is not waiting for human confirmation.")

    competitor_ids = list(dict.fromkeys(competitor_ids))
    selected = (
        db.query(Competitor)
        .filter(Competitor.run_id == run_id, Competitor.id.in_(competitor_ids))
        .all()
    )
    selected_ids = {competitor.id for competitor in selected}
    invalid_ids = [
        competitor_id
        for competitor_id in competitor_ids
        if competitor_id not in selected_ids
    ]
    if invalid_ids:
        raise InvalidRunStateError("Selected competitors do not belong to this run.")

    custom_items = []
    seen_custom_names: set[str] = set()
    for item in custom_competitors or []:
        name = str(item.get("name", "")).strip()
        normalized_name = name.casefold()
        if not name or normalized_name in seen_custom_names:
            continue
        seen_custom_names.add(normalized_name)
        competitor = Competitor(
            run_id=run_id,
            name=name[:80],
            website=item.get("website"),
            description=f"用户手动补充的候选竞品：{name}",
            category=item.get("category") or "direct_competitor",
            region=item.get("region"),
            confidence=1.0,
            selected=True,
            discovery_source="human_input",
        )
        db.add(competitor)
        custom_items.append(competitor)
    if not selected and not custom_items:
        raise InvalidRunStateError("No valid competitors selected.")

    all_competitors = db.query(Competitor).filter(Competitor.run_id == run_id).all()
    for competitor in all_competitors:
        competitor.selected = (
            competitor.id in competitor_ids or competitor in custom_items
        )

    run.status = "running"
    run.current_stage = "material_collection"
    db.commit()
    db.refresh(run)
    return run


def execute_report_run(run_id: str) -> None:
    db = SessionLocal()
    call_tracer.set_trace_context(run_id, "")
    should_process_queued_revisions = False
    source_by_key: dict[str, Source] = {}
    source_by_competitor_url: dict[str, Source] = {}
    source_by_url: dict[str, Source] = {}

    def on_stage_complete(stage: str, state: AgentState) -> None:
        run = db.get(Run, run_id)
        if run is None:
            raise InvalidRunStateError(f"Run not found: {run_id}")

        if stage == "material_collection":
            existing_source_urls = {
                s.url
                for s in db.query(Source.url).filter(Source.run_id == run_id).all()
            }
            existing_evidence_ids = {
                e.id
                for e in db.query(Evidence.id).filter(Evidence.run_id == run_id).all()
            }
            for item in state["sources"]:
                if item.get("url") in existing_source_urls:
                    source = (
                        db.query(Source)
                        .filter(Source.run_id == run_id, Source.url == item["url"])
                        .first()
                    )
                    if source:
                        source_by_key[_source_key_for_source(item)] = source
                        if item.get("competitor_id"):
                            source_by_competitor_url[
                                _competitor_url_key(
                                    item.get("competitor_id"), item.get("url")
                                )
                            ] = source
                        source_by_url.setdefault(item["url"], source)
                        continue
                metadata = _merge_reference_id(
                    item.get("metadata_json"), item.get("reference_id")
                )
                source_data = {
                    key: value for key, value in item.items() if key != "reference_id"
                }
                source_data["metadata_json"] = metadata
                source = Source(run_id=run_id, **source_data)
                db.add(source)
                db.flush()
                source_by_key[_source_key_for_source(source_data)] = source
                if item.get("competitor_id") and item.get("url"):
                    source_by_competitor_url[
                        _competitor_url_key(item.get("competitor_id"), item.get("url"))
                    ] = source
                source_by_url.setdefault(item["url"], source)

            persisted_evidence = []
            for item in state["evidence"]:
                if item.get("id") and item["id"] in existing_evidence_ids:
                    persisted_evidence.append(item)
                    continue
                source = _source_for_evidence(
                    item, source_by_key, source_by_competitor_url, source_by_url
                )
                source_url = item.get("source_url")
                if source is None:
                    raise InvalidRunStateError(
                        f"Evidence source not found for URL: {source_url}"
                    )
                evidence_data = {
                    key: value
                    for key, value in item.items()
                    if key
                    not in {
                        "competitor_id",
                        "source_url",
                        "source_title",
                        "source_type",
                        "reference_id",
                    }
                }
                evidence = Evidence(run_id=run_id, source_id=source.id, **evidence_data)
                db.add(evidence)
                db.flush()
                persisted_evidence.append(
                    {
                        **item,
                        "id": evidence.id,
                        "source_id": source.id,
                        "source_url": source_url,
                    }
                )
            state["evidence"] = persisted_evidence
            run.current_stage = "structured_analysis"
            db.commit()
        elif stage == "structured_analysis":
            new_competitor_ids = {item["competitor_id"] for item in state["analyses"]}
            # We no longer delete old analyses to preserve history for revision.
            # Analyses are versioned via analysis_iteration.
            for item in state["analyses"]:
                db.add(
                    Analysis(
                        id=item["id"],
                        run_id=run_id,
                        competitor_id=item["competitor_id"],
                        positioning=item["positioning"],
                        target_users=item["target_users"],
                        core_features_json=item["core_features_json"],
                        pricing_summary=item["pricing_summary"],
                        strengths_json=item["strengths_json"],
                        weaknesses_json=item["weaknesses_json"],
                        opportunities_json=item["opportunities_json"],
                        custom_focus_analysis_json=item.get(
                            "custom_focus_analysis_json", "[]"
                        ),
                        evidence_ids_json=item["evidence_ids_json"],
                        analysis_iteration=item.get("analysis_iteration", 0),
                    )
                )
                # 更新竞品的关系信息
                competitor = db.get(Competitor, item["competitor_id"])
                if competitor:
                    competitor.relationship_type = item.get(
                        "relationship_type", "direct"
                    )
                    competitor.relationship_reason = item.get("relationship_reason")
                    overlap_dims = item.get("overlap_dimensions")
                    if overlap_dims:
                        competitor.overlap_dimensions_json = json.dumps(
                            overlap_dims, ensure_ascii=False
                        )
                    db.add(competitor)
            run.current_stage = "report_generation"
            db.commit()
        elif stage == "report_generation":
            existing_count = db.query(Report).filter(Report.run_id == run_id).count()
            selected_names = [
                c.name
                for c in db.query(Competitor.name)
                .filter(Competitor.run_id == run_id, Competitor.selected.is_(True))
                .all()
            ]
            db.add(
                Report(
                    run_id=run_id,
                    iteration=existing_count,
                    competitor_names_json=json.dumps(
                        selected_names, ensure_ascii=False
                    ),
                    **state["report"],
                )
            )
            db.commit()
        elif stage == "quality_check":
            qa_result = state.get("qa_result", {})
            db.add(
                QAResult(
                    run_id=run_id,
                    iteration=qa_result.get("iteration", 1),
                    overall_score=qa_result.get("overall_score", 0),
                    decision=qa_result.get("decision", "pass"),
                    check_phase=qa_result.get("check_phase", "full_check"),
                    dimension_scores_json=json.dumps(
                        qa_result.get("dimension_scores", {}), ensure_ascii=False
                    ),
                    issues_json=json.dumps(
                        qa_result.get("issues", []), ensure_ascii=False
                    ),
                    issue_checklist_json=json.dumps(
                        qa_result.get("issue_checklist", []), ensure_ascii=False
                    ),
                    retry_instructions=qa_result.get("retry_instructions"),
                    retry_queries_json=json.dumps(
                        state.get("qa_retry_queries", []), ensure_ascii=False
                    ),
                )
            )
            run.feedback_loop_count = state.get("feedback_loop_count", 0)
            db.commit()
            if _has_unprocessed_queued_revisions(db, run_id):
                raise QueuedRevisionPending()

    try:
        run = get_run_or_raise(db, run_id)
        selected = (
            db.query(Competitor)
            .filter(Competitor.run_id == run_id, Competitor.selected.is_(True))
            .all()
        )
        if not selected:
            raise InvalidRunStateError("No valid competitors selected.")

        llm = get_llm_provider()
        search = get_search_provider()
        requirement = (
            json.loads(run.requirement_json)
            if run.requirement_json
            else {
                "domain": run.title,
                "summary": run.requirement_summary,
                "query": f"{run.title} 竞品 对比 功能 定价 用户评价",
            }
        )
        target_understanding = (
            json.loads(run.target_understanding_json)
            if run.target_understanding_json
            else None
        )
        state: AgentState = {
            "run_id": run.id,
            "user_requirement": run.user_requirement,
            "requirement": requirement,
            "selected_competitors": [
                {
                    "id": item.id,
                    "name": item.name,
                    "website": item.website,
                    "description": item.description,
                    "category": item.category,
                    "region": item.region,
                    "confidence": item.confidence,
                }
                for item in selected
            ],
        }
        if target_understanding:
            state["target_understanding"] = target_understanding

        graph = build_report_generation_graph(
            llm,
            search,
            trace=lambda stage, current_state, action: (
                call_tracer.update_stage(stage),
                run_traced_stage(
                    db,
                    run.id,
                    stage,
                    _trace_input(stage, current_state),
                    action,
                ),
            )[1],
            progress=lambda stage, message, metadata: record_progress_trace(
                db, run.id, stage, message, metadata
            ),
            on_stage_complete=on_stage_complete,
        )
        state = graph.invoke(state)

        run.status = "completed"
        run.current_stage = "completed"
        run.completed_at = datetime.utcnow()
        db.commit()
        should_process_queued_revisions = True
    except QueuedRevisionPending:
        run = db.get(Run, run_id)
        if run is not None:
            run.status = "completed"
            run.current_stage = "completed"
            run.completed_at = datetime.utcnow()
            db.commit()
            should_process_queued_revisions = True
    except Exception as exc:
        run = db.get(Run, run_id)
        if run is not None:
            run.status = "failed"
            run.error_message = str(exc)
            db.commit()
            should_process_queued_revisions = True
    finally:
        call_tracer.clear_trace_context()
        db.close()
    if should_process_queued_revisions:
        from app.services.chat_service import process_queued_revisions

        process_queued_revisions(run_id)


def regenerate_report(run_id: str) -> None:
    db = SessionLocal()
    call_tracer.set_trace_context(run_id, "report_generation")
    try:
        run = get_run_or_raise(db, run_id)

        llm = get_llm_provider()

        sources = db.query(Source).filter(Source.run_id == run_id).all()
        evidence_items = db.query(Evidence).filter(Evidence.run_id == run_id).all()
        analyses = db.query(Analysis).filter(Analysis.run_id == run_id).all()

        source_list = [
            {
                "id": source.id,
                "competitor_id": source.competitor_id,
                "title": source.title,
                "url": source.url,
                "snippet": source.snippet,
                "source_type": source.source_type,
                "provider": source.provider,
                "raw_content": source.raw_content,
                "reference_id": _extract_reference_id(source.metadata_json),
                "metadata_json": source.metadata_json,
            }
            for source in sources
        ]
        evidence_list = [
            {
                "id": evidence.id,
                "competitor_id": evidence.source.competitor_id
                if evidence.source
                else None,
                "related_product": evidence.related_product,
                "related_dimension": evidence.related_dimension,
                "summary": evidence.summary,
                "quote": evidence.quote,
                "confidence": evidence.confidence,
                "source_id": evidence.source_id,
                "source_url": evidence.source.url if evidence.source else None,
            }
            for evidence in evidence_items
        ]
        analysis_list = [
            {
                "id": analysis.id,
                "competitor_id": analysis.competitor_id,
                "competitor_name": analysis.competitor.name
                if analysis.competitor
                else "",
                "positioning": analysis.positioning,
                "target_users": analysis.target_users,
                "core_features_json": analysis.core_features_json,
                "pricing_summary": analysis.pricing_summary,
                "strengths_json": analysis.strengths_json,
                "weaknesses_json": analysis.weaknesses_json,
                "opportunities_json": analysis.opportunities_json,
                "custom_focus_analysis_json": analysis.custom_focus_analysis_json,
                "evidence_ids_json": analysis.evidence_ids_json,
            }
            for analysis in analyses
        ]
        requirement = (
            json.loads(run.requirement_json)
            if run.requirement_json
            else {
                "domain": run.title,
                "summary": run.requirement_summary,
            }
        )

        state: AgentState = {
            "run_id": run_id,
            "user_requirement": run.user_requirement,
            "requirement": requirement,
            "sources": source_list,
            "evidence": evidence_list,
            "analyses": analysis_list,
        }

        run.status = "running"
        run.current_stage = "report_generation"
        db.commit()

        state = report_generation_node(state, llm)

        max_iteration = (
            db.query(func.max(Report.iteration))
            .filter(Report.run_id == run_id)
            .scalar()
            or 0
        )
        db.add(Report(run_id=run_id, iteration=max_iteration + 1, **state["report"]))

        run.status = "completed"
        run.current_stage = "completed"
        run.completed_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        run = db.get(Run, run_id)
        if run is not None:
            run.status = "failed"
            run.error_message = str(exc)
            db.commit()
    finally:
        call_tracer.clear_trace_context()
        db.close()


def _merge_reference_id(metadata_json: str | None, reference_id: object) -> str | None:
    if reference_id is None:
        return metadata_json
    try:
        metadata = json.loads(metadata_json) if metadata_json else {}
    except (json.JSONDecodeError, TypeError):
        metadata = {}
    metadata["reference_id"] = reference_id
    return json.dumps(metadata, ensure_ascii=False)


def _extract_reference_id(metadata_json: str | None) -> int | None:
    if not metadata_json:
        return None
    try:
        metadata = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return None
    value = metadata.get("reference_id")
    return int(value) if isinstance(value, int | float) else None


def _trace_input(stage: str, state: AgentState) -> dict:
    if stage == "requirement_understanding":
        return {"user_requirement": state.get("user_requirement")}
    if stage == "focus_profile":
        return {"domain": state.get("requirement", {}).get("domain")}
    if stage == "competitor_discovery":
        return {"query": state.get("requirement", {}).get("query")}
    if stage == "human_confirm_competitors":
        return {"candidate_count": len(state.get("competitors", []))}
    if stage == "material_collection":
        return {"competitor_count": len(state.get("selected_competitors", []))}
    if stage == "structured_analysis":
        return {"evidence_count": len(state.get("evidence", []))}
    if stage == "report_generation":
        return {"analysis_count": len(state.get("analyses", []))}
    if stage == "quality_check":
        prev = state.get("qa_result", {})
        return {
            "report_title": state.get("report", {}).get("title"),
            "analysis_count": len(state.get("analyses", [])),
            "feedback_loop_count": state.get("feedback_loop_count", 0),
            "previous_decision": prev.get("decision")
            if isinstance(prev, dict)
            else None,
        }
    return {}


def _source_for_evidence(
    evidence: dict,
    source_by_key: dict[str, Source],
    source_by_competitor_url: dict[str, Source],
    source_by_url: dict[str, Source],
) -> Source | None:
    source_url = evidence.get("source_url")
    return (
        source_by_key.get(_source_key_for_evidence(evidence))
        or source_by_competitor_url.get(
            _competitor_url_key(evidence.get("competitor_id"), source_url)
        )
        or source_by_url.get(source_url)
    )


def _source_key_for_source(source: dict) -> str:
    dimension = _source_dimension(source)
    return "::".join(
        str(part or "")
        for part in [source.get("competitor_id"), dimension, source.get("url")]
    )


def _source_key_for_evidence(evidence: dict) -> str:
    return "::".join(
        str(part or "")
        for part in [
            evidence.get("competitor_id"),
            evidence.get("related_dimension"),
            evidence.get("source_url"),
        ]
    )


def _competitor_url_key(competitor_id: object, url: object) -> str:
    return "::".join(str(part or "") for part in [competitor_id, url])


def _source_dimension(source: dict) -> str | None:
    metadata_json = source.get("metadata_json")
    if not metadata_json:
        return None
    try:
        metadata = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return None
    dimension = metadata.get("dimension") if isinstance(metadata, dict) else None
    return str(dimension) if dimension else None
