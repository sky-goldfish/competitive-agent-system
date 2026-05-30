import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.agents.graph import build_competitor_discovery_graph, build_report_generation_graph
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

    competitor_ids = list(dict.fromkeys(competitor_ids))
    selected = db.query(Competitor).filter(Competitor.run_id == run_id, Competitor.id.in_(competitor_ids)).all()
    selected_ids = {competitor.id for competitor in selected}
    invalid_ids = [competitor_id for competitor_id in competitor_ids if competitor_id not in selected_ids]
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
        competitor.selected = competitor.id in competitor_ids or competitor in custom_items

    run.status = "running"
    run.current_stage = "material_collection"
    db.commit()
    db.refresh(run)
    return run


def execute_report_run(run_id: str) -> None:
    db = SessionLocal()
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

        source_by_key: dict[str, Source] = {}
        source_by_competitor_url: dict[str, Source] = {}
        source_by_url: dict[str, Source] = {}
        for item in state["sources"]:
            source = Source(run_id=run.id, **item)
            db.add(source)
            db.flush()
            source_by_key[_source_key_for_source(item)] = source
            if item.get("competitor_id") and item.get("url"):
                source_by_competitor_url[_competitor_url_key(item.get("competitor_id"), item.get("url"))] = source
            source_by_url.setdefault(item["url"], source)

        persisted_evidence = []
        for item in state["evidence"]:
            source_url = item.get("source_url")
            source = (
                source_by_key.get(_source_key_for_evidence(item))
                or source_by_competitor_url.get(_competitor_url_key(item.get("competitor_id"), source_url))
                or source_by_url.get(source_url)
            )
            if source is None:
                raise InvalidRunStateError(f"Evidence source not found for URL: {source_url}")
            evidence_data = {key: value for key, value in item.items() if key not in {"competitor_id", "source_url"}}
            evidence = Evidence(run_id=run.id, source_id=source.id, **evidence_data)
            db.add(evidence)
            db.flush()
            persisted_evidence.append({**item, "id": evidence.id, "source_id": source.id, "source_url": source_url})
        state["evidence"] = persisted_evidence
        run.current_stage = "report_generation"
        db.commit()

        for item in state["analyses"]:
            db.add(
                Analysis(
                    id=item["id"],
                    run_id=run.id,
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

        existing_report = db.query(Report).filter(Report.run_id == run.id).first()
        if existing_report is None:
            db.add(Report(run_id=run.id, **state["report"]))
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


def _source_key_for_source(source: dict) -> str:
    dimension = _source_dimension(source)
    return "::".join(str(part or "") for part in [source.get("competitor_id"), dimension, source.get("url")])


def _source_key_for_evidence(evidence: dict) -> str:
    return "::".join(str(part or "") for part in [evidence.get("competitor_id"), evidence.get("related_dimension"), evidence.get("source_url")])


def _competitor_url_key(competitor_id: object, url: object) -> str:
    return "::".join(str(part or "") for part in [competitor_id, url])


def _source_dimension(source: dict) -> str | None:
    metadata_json = source.get("metadata_json")
    if not metadata_json:
        return None
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    dimension = metadata.get("dimension") if isinstance(metadata, dict) else None
    return str(dimension) if dimension else None
