import json
import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.agents.graph import (
    build_competitor_discovery_graph,
    build_report_generation_graph,
)
from app.agents.nodes.focus_profile import normalize_focus_profile
from app.agents.nodes.report_generation import report_generation_node
from app.agents.state import AgentState, ensure_dict
from app.agents.trace import record_progress_trace, run_traced_stage
from app.db.models import (
    AgentTrace,
    Analysis,
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


VALID_RUN_STATUSES = frozenset(
    {
        "created",
        "running",
        "waiting_for_clarification",
        "waiting_for_human",
        "completed",
        "failed",
        "revising",
    }
)

VALID_CURRENT_STAGES = frozenset(
    {
        "created",
        "failed",
        "completed",
        "requirement_understanding",
        "focus_profile",
        "competitor_discovery",
        "requirement_clarification",
        "human_confirm_competitors",
        "material_collection",
        "structured_analysis",
        "report_generation",
        "quality_check",
        "retry_collection",
        "retry_analysis",
        "retry_collection_and_analysis",
    }
)

REPORT_GRAPH_STAGES = [
    "material_collection",
    "structured_analysis",
    "report_generation",
    "quality_check",
]


def _next_report_iteration(db: Session, run_id: str) -> int:
    max_iteration = (
        db.query(func.max(Report.iteration)).filter(Report.run_id == run_id).scalar()
    )
    return (max_iteration if max_iteration is not None else -1) + 1


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


def _validate_status(status: str) -> str:
    if status not in VALID_RUN_STATUSES:
        logger.warning("Unknown run status '%s'; defaulting to 'failed'", status)
        return "failed"
    return status


def _validate_stage(stage: str) -> str:
    if stage not in VALID_CURRENT_STAGES:
        logger.warning("Unknown current_stage '%s'; defaulting to 'created'", stage)
        return "created"
    return stage


def _set_run_status(run: Run, status: str, stage: str | None = None) -> None:
    run.status = _validate_status(status)
    if stage is not None:
        run.current_stage = _validate_stage(stage)


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
    if run.status not in ("running", "revising"):
        return

    now = datetime.utcnow()
    stale_threshold_seconds = 30 * 60
    stale = (
        run.updated_at is not None
        and (now - run.updated_at).total_seconds() > stale_threshold_seconds
    ) or (
        run.updated_at is None
        and run.created_at is not None
        and (now - run.created_at).total_seconds() > stale_threshold_seconds
    )
    if not stale:
        return

    if run.status == "revising" and run.active_revision_id:
        from app.db.models import Revision

        revision = db.get(Revision, run.active_revision_id)
        if revision and revision.status == "running":
            revision.status = "failed"
            revision.error_message = f"revision stale (last run update: {run.updated_at.isoformat() if run.updated_at else 'unknown'})"
            revision.completed_at = now

    _set_run_status(run, "failed", "failed")
    run.error_message = f"run stale (last update: {run.updated_at.isoformat() if run.updated_at else 'unknown'})"
    run.completed_at = now
    db.commit()


def start_run(db: Session, user_requirement: str) -> Run:
    run = Run(
        user_requirement=user_requirement,
    )
    _set_run_status(run, "running", "requirement_understanding")
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
        state: AgentState = {"run_id": run.id, "user_requirement": run.user_requirement}
        if run.requirement_json:
            state["requirement"] = ensure_dict(json.loads(run.requirement_json))

        graph = build_competitor_discovery_graph(
            llm,
            search,
            trace=lambda stage, current_state, action: run_traced_stage(
                db,
                run.id,
                stage,
                _trace_input(stage, current_state),
                action,
            ),
            progress=lambda stage, message, metadata: _progress_callback(
                db, run.id, stage, message, metadata
            ),
        )
        try:
            state = graph.invoke(state, {"recursion_limit": 50})
        except Exception as invoke_exc:
            logger.error(
                "Discovery graph invocation failed for run %s: %s", run_id, invoke_exc
            )
            raise

        req_dict = ensure_dict(state.get("requirement"))
        run.requirement_summary = req_dict.get("summary", "分析需求已收录")
        run.title = req_dict.get("domain", "竞品分析报告")
        run.requirement_json = json.dumps(req_dict, ensure_ascii=False)
        focus_profile_raw = ensure_dict(req_dict.get("focus_profile"))
        if focus_profile_raw.get("clarification_needed"):
            focus_profile = focus_profile_raw
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
            _set_run_status(
                run, "waiting_for_clarification", "requirement_clarification"
            )
            db.commit()
            return
        if state.get("target_understanding"):
            run.target_understanding_json = json.dumps(
                state["target_understanding"], ensure_ascii=False
            )
        for item in state["competitors"]:
            if "selected" not in item:
                item["selected"] = True
            competitor_data = {
                k: v
                for k, v in item.items()
                if k
                in {
                    "name",
                    "website",
                    "description",
                    "category",
                    "region",
                    "confidence",
                    "selected",
                    "discovery_source",
                    "relationship_type",
                    "relationship_reason",
                    "overlap_dimensions_json",
                }
            }
            db.add(Competitor(run_id=run.id, **competitor_data))
        _set_run_status(run, "waiting_for_human", "human_confirm_competitors")
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(Run, run_id)
        if run is not None:
            _set_run_status(run, "failed")
            run.error_message = str(exc)
            db.commit()
    finally:
        db.close()


def answer_requirement_clarification(db: Session, run_id: str, answer: str) -> Run:
    run = get_run_or_raise(db, run_id)
    if run.status != "waiting_for_clarification":
        raise InvalidRunStateError("Run is not waiting for requirement clarification.")
    answer = answer.strip()
    if len(answer) < 1:
        raise InvalidRunStateError("Clarification answer cannot be empty.")

    requirement = ensure_dict(json.loads(run.requirement_json or "{}"))
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
    _set_run_status(run, "running", "competitor_discovery")
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
    db.flush()
    custom_ids = {c.id for c in custom_items}
    if not selected and not custom_items:
        raise InvalidRunStateError("No valid competitors selected.")

    all_competitors = db.query(Competitor).filter(Competitor.run_id == run_id).all()
    for competitor in all_competitors:
        competitor.selected = (
            competitor.id in competitor_ids or competitor.id in custom_ids
        )

    _set_run_status(run, "running", "material_collection")
    db.commit()
    db.refresh(run)
    return run


def _resume_from_report_generation(
    db: Session,
    run: Run,
    run_id: str,
    state: AgentState,
    llm,
    on_stage_complete: Callable[[str, AgentState], None],
) -> bool:
    from app.agents.nodes.quality_check import quality_check_node, qa_route

    _set_run_status(run, "running", "report_generation")
    db.commit()
    try:
        state = report_generation_node(state, llm)
    except Exception as exc:
        logger.error("Resumed report_generation failed for run %s: %s", run_id, exc)
        raise
    on_stage_complete("report_generation", state)

    _set_run_status(run, "running", "quality_check")
    db.commit()
    try:
        state = quality_check_node(state, llm)
    except Exception as exc:
        logger.error("Resumed quality_check failed for run %s: %s", run_id, exc)
        raise
    on_stage_complete("quality_check", state)

    route = qa_route(state)
    if route == "end":
        return True

    logger.info(
        "Resumed QA decided '%s' for run %s; restarting full graph",
        route,
        run_id,
    )
    _RETRY_ROUTE_STAGE = {
        "retry_collection": "material_collection",
        "retry_analysis": "structured_analysis",
        "retry_collection_and_analysis": "material_collection",
    }
    resolved_stage = _RETRY_ROUTE_STAGE.get(route, route)
    _set_run_status(run, "running", resolved_stage)
    db.commit()
    return False


def _rebuild_state_from_db(db: Session, run: Run) -> AgentState | None:
    if run.current_stage not in REPORT_GRAPH_STAGES:
        return None

    stage_index = REPORT_GRAPH_STAGES.index(run.current_stage)
    if stage_index == 0:
        return None

    requirement = ensure_dict(
        json.loads(run.requirement_json)
        if run.requirement_json
        else {
            "domain": run.title,
            "summary": run.requirement_summary,
            "query": f"{run.title} 竞品 对比 功能 定价 用户评价",
        }
    )
    target_understanding = (
        ensure_dict(json.loads(run.target_understanding_json))
        if run.target_understanding_json
        else None
    )
    selected = (
        db.query(Competitor)
        .filter(Competitor.run_id == run.id, Competitor.selected.is_(True))
        .all()
    )

    selected_comp_ids = {item.id for item in selected}

    from app.services.chat_service import (
        _analysis_list,
        _evidence_list,
        _source_list,
    )

    source_list = _source_list(db, run.id, selected_comp_ids)
    evidence_list = _evidence_list(db, run.id, selected)
    analysis_list = _analysis_list(db, run.id, evidence_list=evidence_list)

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
                "relationship_type": item.relationship_type,
                "relationship_reason": item.relationship_reason,
                "overlap_dimensions": (
                    json.loads(item.overlap_dimensions_json)
                    if item.overlap_dimensions_json
                    else None
                ),
            }
            for item in selected
        ],
        "sources": source_list,
        "evidence": evidence_list,
        "analyses": analysis_list,
    }
    if target_understanding:
        state["target_understanding"] = target_understanding

    latest_qa = (
        db.query(QAResult)
        .filter(QAResult.run_id == run.id)
        .order_by(QAResult.iteration.desc())
        .first()
    )
    if latest_qa:
        state["qa_result"] = {
            "overall_score": latest_qa.overall_score,
            "dimension_scores": json.loads(latest_qa.dimension_scores_json)
            if latest_qa.dimension_scores_json
            else {},
            "decision": latest_qa.decision,
            "issues": json.loads(latest_qa.issues_json)
            if latest_qa.issues_json
            else [],
            "issue_checklist": json.loads(latest_qa.issue_checklist_json)
            if latest_qa.issue_checklist_json
            else [],
            "iteration": latest_qa.iteration,
        }
        state["feedback_loop_count"] = latest_qa.iteration
        state["qa_issue_checklist"] = (
            json.loads(latest_qa.issue_checklist_json)
            if latest_qa.issue_checklist_json
            else []
        )

    if stage_index >= 3:
        latest_report = (
            db.query(Report)
            .filter(Report.run_id == run.id)
            .order_by(Report.iteration.desc())
            .first()
        )
        if latest_report:
            state["report"] = {
                "title": latest_report.title,
                "markdown_content": latest_report.markdown_content,
                "summary": latest_report.summary,
            }

    logger.info(
        "Rebuilt AgentState from DB for run %s at stage '%s' "
        "(sources=%d, evidence=%d, analyses=%d)",
        run.id,
        run.current_stage,
        len(source_list),
        len(evidence_list),
        len(analysis_list),
    )
    return state


def execute_report_run(run_id: str) -> None:
    db = SessionLocal()
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
            existing_evidence_quotes: dict[str, str] = {}
            for e in (
                db.query(Evidence.id, Evidence.quote)
                .filter(Evidence.run_id == run_id, Evidence.quote != "")
                .all()
            ):
                existing_evidence_quotes[e.quote] = e.id
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
                    key: value
                    for key, value in item.items()
                    if key not in ("reference_id", "credibility_score")
                }
                source_data["metadata_json"] = metadata
                source_data["reference_id"] = item.get("reference_id")
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
                item_quote = item.get("quote", "")
                if item_quote and item_quote in existing_evidence_quotes:
                    existing_ev_id = existing_evidence_quotes[item_quote]
                    persisted_evidence.append({**item, "id": existing_ev_id})
                    continue
                source = _source_for_evidence(
                    item, source_by_key, source_by_competitor_url, source_by_url
                )
                if source is None and item.get("source_url"):
                    source = (
                        db.query(Source)
                        .filter(
                            Source.run_id == run_id, Source.url == item["source_url"]
                        )
                        .first()
                    )
                    if source:
                        source_by_url.setdefault(item["source_url"], source)
                        key = _source_key_for_evidence(item)
                        source_by_key.setdefault(key, source)
                if source is None and item.get("source_id"):
                    source = db.get(Source, item["source_id"])
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
                        "id",
                        "competitor_id",
                        "source_url",
                        "source_title",
                        "source_type",
                    }
                }
                if (
                    "reference_id" not in evidence_data
                    and source.reference_id is not None
                ):
                    evidence_data["reference_id"] = source.reference_id
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
            _set_run_status(run, "running", "structured_analysis")
            db.commit()
        elif stage == "structured_analysis":
            new_competitor_ids = {
                item.get("competitor_id")
                for item in state["analyses"]
                if item.get("competitor_id")
            }
            for item in state["analyses"]:
                existing = db.get(Analysis, item.get("id"))
                if existing is not None:
                    for key, value in item.items():
                        if key not in ("id",) and hasattr(existing, key):
                            setattr(existing, key, value)
                else:
                    cid = item.get("competitor_id")
                    if not cid:
                        logger.warning(
                            "Skipping Analysis with missing competitor_id in run=%s",
                            run_id,
                        )
                        continue
                    db.add(
                        Analysis(
                            id=item.get("id"),
                            run_id=run_id,
                            competitor_id=cid,
                            positioning=item.get("positioning", ""),
                            target_users=item.get("target_users", "[]"),
                            core_features_json=item.get("core_features_json", "[]"),
                            pricing_summary=item.get("pricing_summary", ""),
                            strengths_json=item.get("strengths_json", "[]"),
                            weaknesses_json=item.get("weaknesses_json", "[]"),
                            opportunities_json=item.get("opportunities_json", "[]"),
                            custom_focus_analysis_json=item.get(
                                "custom_focus_analysis_json", "[]"
                            ),
                            evidence_ids_json=item.get("evidence_ids_json", "[]"),
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
            _set_run_status(run, "running", "report_generation")
            db.commit()
        elif stage == "report_generation":
            feedback_count = state.get("feedback_loop_count", 0)
            report_data = state["report"]
            if feedback_count > 0:
                latest_report = (
                    db.query(Report)
                    .filter(Report.run_id == run_id)
                    .order_by(Report.iteration.desc())
                    .first()
                )
                if latest_report:
                    latest_report.title = report_data.get("title", latest_report.title)
                    latest_report.markdown_content = report_data.get(
                        "markdown_content", latest_report.markdown_content
                    )
                    latest_report.summary = report_data.get(
                        "summary", latest_report.summary
                    )
                    latest_report.updated_at = datetime.utcnow()
                    db.add(latest_report)
                else:
                    next_iteration = _next_report_iteration(db, run_id)
                    selected_names = [
                        c.name
                        for c in db.query(Competitor.name)
                        .filter(
                            Competitor.run_id == run_id,
                            Competitor.selected.is_(True),
                        )
                        .all()
                    ]
                    db.add(
                        Report(
                            run_id=run_id,
                            iteration=next_iteration,
                            competitor_names_json=json.dumps(
                                selected_names, ensure_ascii=False
                            ),
                            **report_data,
                        )
                    )
            else:
                next_iteration = _next_report_iteration(db, run_id)
                selected_names = [
                    c.name
                    for c in db.query(Competitor.name)
                    .filter(
                        Competitor.run_id == run_id,
                        Competitor.selected.is_(True),
                    )
                    .all()
                ]
                db.add(
                    Report(
                        run_id=run_id,
                        iteration=next_iteration,
                        competitor_names_json=json.dumps(
                            selected_names, ensure_ascii=False
                        ),
                        **report_data,
                    )
                )
            db.commit()
        elif stage == "quality_check":
            qa_result = state.get("qa_result", {})
            qa_iteration = (
                db.query(func.max(QAResult.iteration))
                .filter(QAResult.run_id == run_id)
                .scalar()
            )
            qa_iteration = (qa_iteration if qa_iteration is not None else 0) + 1
            db.add(
                QAResult(
                    run_id=run_id,
                    iteration=qa_iteration,
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

        state = _rebuild_state_from_db(db, run)
        skip_graph = False
        if state is not None:
            stage_index = REPORT_GRAPH_STAGES.index(run.current_stage)
            logger.info(
                "Resuming run %s from checkpoint at stage '%s' (index %d)",
                run_id,
                run.current_stage,
                stage_index,
            )
            if stage_index >= 3:
                skip_graph = _resume_from_report_generation(
                    db,
                    run,
                    run_id,
                    state,
                    llm,
                    on_stage_complete,
                )
                if skip_graph:
                    state = None

        if not skip_graph and state is None:
            requirement = ensure_dict(
                json.loads(run.requirement_json)
                if run.requirement_json
                else {
                    "domain": run.title,
                    "summary": run.requirement_summary,
                    "query": f"{run.title} 竞品 对比 功能 定价 用户评价",
                }
            )
            target_understanding = (
                ensure_dict(json.loads(run.target_understanding_json))
                if run.target_understanding_json
                else None
            )
            state = {
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
                        "relationship_type": item.relationship_type,
                        "relationship_reason": item.relationship_reason,
                        "overlap_dimensions": (
                            json.loads(item.overlap_dimensions_json)
                            if item.overlap_dimensions_json
                            else None
                        ),
                    }
                    for item in selected
                ],
                "sources": [],
                "evidence": [],
                "analyses": [],
            }
            if target_understanding:
                state["target_understanding"] = target_understanding

        if state is not None:
            graph = build_report_generation_graph(
                llm,
                search,
                trace=lambda stage, current_state, action: run_traced_stage(
                    db,
                    run.id,
                    stage,
                    _trace_input(stage, current_state),
                    action,
                ),
                progress=lambda stage, message, metadata: record_progress_trace(
                    db, run.id, stage, message, metadata
                ),
                on_stage_complete=on_stage_complete,
            )
            try:
                state = graph.invoke(state, {"recursion_limit": 50})
            except Exception as invoke_exc:
                logger.error(
                    "Report graph invocation failed for run %s: %s", run_id, invoke_exc
                )
                raise

        _set_run_status(run, "completed", "completed")
        run.completed_at = datetime.utcnow()
        db.commit()
        should_process_queued_revisions = True
    except QueuedRevisionPending:
        run = db.get(Run, run_id)
        if run is not None:
            _set_run_status(run, "completed", "completed")
            run.completed_at = datetime.utcnow()
            db.commit()
            should_process_queued_revisions = True
    except Exception as exc:
        db.rollback()
        run = db.get(Run, run_id)
        if run is not None:
            _set_run_status(run, "failed")
            run.error_message = str(exc)[:2000]
            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.exception(
                    "Failed to mark run %s as failed after rollback", run_id
                )
        should_process_queued_revisions = True
    finally:
        db.close()
    if should_process_queued_revisions:
        from app.services.chat_service import process_queued_revisions

        process_queued_revisions(run_id)


def regenerate_report(run_id: str) -> None:
    db = SessionLocal()
    try:
        run = get_run_or_raise(db, run_id)

        llm = get_llm_provider()

        sources = db.query(Source).filter(Source.run_id == run_id).all()
        competitors = db.query(Competitor).filter(Competitor.run_id == run_id).all()
        selected_comp_ids = {c.id for c in competitors if c.selected}

        from app.services.chat_service import (
            _analysis_list,
            _evidence_list,
            _source_list,
        )

        source_list = _source_list(db, run_id, selected_comp_ids)
        evidence_list = _evidence_list(
            db, run_id, [c for c in competitors if c.selected]
        )
        analysis_list = _analysis_list(db, run_id, evidence_list=evidence_list)
        requirement = ensure_dict(
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
            "selected_competitors": [
                {
                    "id": c.id,
                    "name": c.name,
                    "website": c.website,
                    "description": c.description,
                    "category": c.category,
                    "region": c.region,
                    "confidence": c.confidence,
                    "selected": c.selected,
                    "relationship_type": c.relationship_type,
                    "overlap_dimensions": json.loads(c.overlap_dimensions_json)
                    if c.overlap_dimensions_json
                    else None,
                }
                for c in competitors
                if c.selected
            ],
            "target_understanding": ensure_dict(
                json.loads(run.target_understanding_json)
            )
            if run.target_understanding_json
            else {},
        }

        _set_run_status(run, "running", "report_generation")
        db.commit()

        state = report_generation_node(state, llm)

        report_data = state.get("report", {})
        if report_data:
            latest_report = (
                db.query(Report)
                .filter(Report.run_id == run_id)
                .order_by(Report.iteration.desc())
                .first()
            )
            if latest_report:
                latest_report.title = report_data.get("title", latest_report.title)
                latest_report.markdown_content = report_data.get(
                    "markdown_content", latest_report.markdown_content
                )
                latest_report.summary = report_data.get(
                    "summary", latest_report.summary
                )
                latest_report.updated_at = datetime.utcnow()
                db.add(latest_report)
            else:
                selected_names = [c.name for c in competitors if c.selected]
                iteration = _next_report_iteration(db, run_id)
                db.add(
                    Report(
                        run_id=run_id,
                        iteration=iteration,
                        title=report_data.get("title", "竞品分析报告"),
                        markdown_content=report_data.get("markdown_content", ""),
                        summary=report_data.get("summary", ""),
                        competitor_names_json=json.dumps(
                            selected_names, ensure_ascii=False
                        ),
                    )
                )
            db.commit()

        from app.agents.nodes.quality_check import quality_check_node, qa_route

        _set_run_status(run, "running", "quality_check")
        db.commit()
        state = quality_check_node(state, llm)

        qa_result = state.get("qa_result", {})

        route = qa_route(state)
        if route != "end":
            logger.info(
                "Regenerate report QA decided '%s' for run %s; forcing pass",
                route,
                run_id,
            )

        _set_run_status(run, "completed", "completed")
        run.completed_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(Run, run_id)
        if run is not None:
            _set_run_status(run, "failed")
            run.error_message = str(exc)
            db.commit()
    finally:
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


def _trace_input(stage: str, state: AgentState) -> dict:
    if stage == "requirement_understanding":
        return {"user_requirement": state.get("user_requirement")}
    req_dict = ensure_dict(state.get("requirement"))
    if stage == "focus_profile":
        return {"domain": req_dict.get("domain")}
    if stage == "competitor_discovery":
        return {"query": req_dict.get("query")}
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
