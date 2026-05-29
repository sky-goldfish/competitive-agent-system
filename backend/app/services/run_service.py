import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.agents.graph import build_competitor_discovery_graph, build_report_generation_graph
from app.agents.nodes.report_generation import report_generation_node
from app.agents.state import AgentState
from app.agents.trace import record_progress_trace, run_traced_stage
from app.db.models import Analysis, Competitor, Evidence, Report, Run, Source
from app.db.session import SessionLocal
from app.providers.llm.factory import get_llm_provider
from app.providers.search.factory import get_search_provider


class RunNotFoundError(ValueError):
    pass


class InvalidRunStateError(ValueError):
    pass


def get_run_or_raise(db: Session, run_id: str) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise RunNotFoundError(f"Run not found: {run_id}")
    return run


def start_run(db: Session, user_requirement: str) -> Run:
    run = Run(user_requirement=user_requirement, status="running", current_stage="requirement_understanding")
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
            progress=lambda stage, message, metadata: record_progress_trace(db, run.id, stage, message, metadata),
        )
        state = graph.invoke(state)

        run.requirement_summary = state["requirement"]["summary"]
        run.title = state["requirement"]["domain"]
        run.requirement_json = json.dumps(state["requirement"], ensure_ascii=False)
        if state.get("target_understanding"):
            run.target_understanding_json = json.dumps(state["target_understanding"], ensure_ascii=False)
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
        db.close()


def confirm_and_continue_run(db: Session, run_id: str, competitor_ids: list[str], custom_competitors: list[dict] | None = None) -> Run:
    run = get_run_or_raise(db, run_id)
    if run.status != "waiting_for_human":
        raise InvalidRunStateError("Run is not waiting for human confirmation.")

    selected = db.query(Competitor).filter(Competitor.run_id == run_id, Competitor.id.in_(competitor_ids)).all()
    custom_items = []
    for item in custom_competitors or []:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        competitor = Competitor(
            run_id=run_id,
            name=name[:80],
            website=item.get("website"),
            description=f"用户手动补充的候选竞品：{name}",
            category=item.get("category") or "direct_competitor",
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
        competitor.selected = competitor.id in competitor_ids or competitor in custom_items

    run.status = "running"
    run.current_stage = "material_collection"
    db.commit()
    db.refresh(run)
    return run


def execute_report_run(run_id: str) -> None:
    db = SessionLocal()
    # Track persisted source URLs → Source objects for evidence foreign key resolution
    source_by_url: dict[str, Source] = {}

    def on_stage_complete(stage: str, state: AgentState) -> None:
        nonlocal source_by_url
        run = db.get(Run, run_id)
        if stage == "material_collection":
            for item in state["sources"]:
                metadata = _merge_reference_id(item.get("metadata_json"), item.get("reference_id"))
                source_data = {k: v for k, v in item.items() if k != "reference_id"}
                source_data["metadata_json"] = metadata
                source = Source(run_id=run_id, **source_data)
                db.add(source)
                db.flush()
                source_by_url[item["url"]] = source
            for item in state["evidence"]:
                source = source_by_url[item["source_url"]]
                evidence = Evidence(run_id=run_id, source_id=source.id, **{key: value for key, value in item.items() if key not in ("competitor_id", "source_url")})
                db.add(evidence)
                db.flush()
            run.current_stage = "structured_analysis"
            db.commit()
        elif stage == "structured_analysis":
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
                        evidence_ids_json=item["evidence_ids_json"],
                    )
                )
            run.current_stage = "report_generation"
            db.commit()

    try:
        run = get_run_or_raise(db, run_id)
        selected = db.query(Competitor).filter(Competitor.run_id == run_id, Competitor.selected.is_(True)).all()
        if not selected:
            raise InvalidRunStateError("No valid competitors selected.")

        llm = get_llm_provider()
        search = get_search_provider()
        requirement = json.loads(run.requirement_json) if run.requirement_json else {
            "domain": run.title,
            "summary": run.requirement_summary,
            "query": f"{run.title} 竞品 对比 功能 定价 用户评价",
        }
        target_understanding = json.loads(run.target_understanding_json) if run.target_understanding_json else None
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
            trace=lambda stage, current_state, action: run_traced_stage(
                db,
                run.id,
                stage,
                _trace_input(stage, current_state),
                action,
            ),
            progress=lambda stage, message, metadata: record_progress_trace(db, run.id, stage, message, metadata),
            on_stage_complete=on_stage_complete,
        )
        state = graph.invoke(state)

        # Resolve evidence source_url → source_id for report_generation_node's citation_bundle
        for item in state.get("evidence", []):
            if "source_url" in item and item["source_url"] in source_by_url:
                item["source_id"] = source_by_url[item["source_url"]].id

        existing_report = db.query(Report).filter(Report.run_id == run_id).first()
        if existing_report is None:
            db.add(Report(run_id=run_id, **state["report"]))
        else:
            existing_report.title = state["report"]["title"]
            existing_report.summary = state["report"]["summary"]
            existing_report.markdown_content = state["report"]["markdown_content"]

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
        db.close()


def _merge_reference_id(metadata_json: str | None, reference_id: int | None) -> str | None:
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
    return int(value) if isinstance(value, (int, float)) else None


def _trace_input(stage: str, state: AgentState) -> dict:
    if stage == "requirement_understanding":
        return {"user_requirement": state.get("user_requirement")}
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
    return {}


def regenerate_report(run_id: str) -> None:
    db = SessionLocal()
    try:
        run = get_run_or_raise(db, run_id)

        llm = get_llm_provider()

        sources = db.query(Source).filter(Source.run_id == run_id).all()
        evidence_items = db.query(Evidence).filter(Evidence.run_id == run_id).all()
        analyses = db.query(Analysis).filter(Analysis.run_id == run_id).all()

        source_list = [
            {
                "id": s.id,
                "competitor_id": s.competitor_id,
                "title": s.title,
                "url": s.url,
                "snippet": s.snippet,
                "source_type": s.source_type,
                "provider": s.provider,
                "raw_content": s.raw_content,
                "reference_id": _extract_reference_id(s.metadata_json),
                "metadata_json": s.metadata_json,
            }
            for s in sources
        ]
        evidence_list = [
            {
                "id": e.id,
                "competitor_id": e.source.competitor_id if e.source else None,
                "related_product": e.related_product,
                "related_dimension": e.related_dimension,
                "summary": e.summary,
                "quote": e.quote,
                "confidence": e.confidence,
                "source_url": e.source.url if e.source else None,
            }
            for e in evidence_items
        ]
        analysis_list = [
            {
                "id": a.id,
                "competitor_id": a.competitor_id,
                "competitor_name": a.competitor.name if a.competitor else "",
                "positioning": a.positioning,
                "target_users": a.target_users,
                "core_features_json": a.core_features_json,
                "pricing_summary": a.pricing_summary,
                "strengths_json": a.strengths_json,
                "weaknesses_json": a.weaknesses_json,
                "opportunities_json": a.opportunities_json,
                "evidence_ids_json": a.evidence_ids_json,
            }
            for a in analyses
        ]

        state: AgentState = {
            "run_id": run_id,
            "user_requirement": run.user_requirement,
            "sources": source_list,
            "evidence": evidence_list,
            "analyses": analysis_list,
        }

        run.status = "running"
        run.current_stage = "report_generation"
        db.commit()

        state = report_generation_node(state, llm)

        existing_report = db.query(Report).filter(Report.run_id == run_id).first()
        if existing_report is None:
            db.add(Report(run_id=run_id, **state["report"]))
        else:
            existing_report.title = state["report"]["title"]
            existing_report.summary = state["report"]["summary"]
            existing_report.markdown_content = state["report"]["markdown_content"]

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
        db.close()
