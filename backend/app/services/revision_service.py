import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    Analysis,
    ChatMessage,
    Competitor,
    Report,
    Revision,
    RevisionTrace,
    Run,
    Source,
)
from app.db.session import SessionLocal
from app.services import call_tracer
from app.services.chat_service import (
    ChatError,
    _active_focus_items,
    _analysis_list,
    _analyze_revision_competitors,
    _commit_with_retry,
    _competitor_to_dict,
    _ensure_analyses_for_all_selected,
    _ensure_revision_competitors,
    _evidence_list,
    _execute_revision_search_plan,
    _extract_ref_id,
    _get_run_context,
    _human_report_version,
    _protect_inline_citations,
    _revision_plan_summary,
    _source_list,
    _source_to_dict,
)
from app.services.run_service import _set_run_status

logger = logging.getLogger(__name__)
from app.providers.llm.factory import get_llm_provider
from app.agents.nodes.report_generation import _build_citation_bundle


def create_revision(
    db: Session, run_id: str, user_message: str
) -> tuple[Revision, ChatMessage]:
    run = db.get(Run, run_id)
    if run is None:
        raise ChatError(f"Run not found: {run_id}")
    report = (
        db.query(Report)
        .filter(Report.run_id == run_id)
        .order_by(Report.iteration.desc())
        .first()
    )
    if report is None:
        raise ChatError("报告尚未生成，暂不能进行对话修改。")

    user_msg = ChatMessage(
        run_id=run_id,
        role="user",
        content=user_message,
        report_version=report.iteration,
    )
    db.add(user_msg)
    db.flush()
    revision = Revision(
        run_id=run_id,
        base_report_iteration=report.iteration,
        user_message=user_message,
        status="queued",
        chat_user_message_id=user_msg.id,
    )
    db.add(revision)
    db.flush()
    assistant_msg = ChatMessage(
        run_id=run_id,
        role="assistant",
        content="已收到反馈，已创建独立修订任务，Agent 将开始处理。",
        intent="revision_processing",
        action_type="revision_processing",
        report_version=report.iteration,
        metadata_json=json.dumps(
            {
                "revision_id": revision.id,
                "revision_status": "queued",
                "processing": True,
                "processed": False,
            },
            ensure_ascii=False,
        ),
    )
    db.add(assistant_msg)
    db.flush()
    revision.chat_assistant_message_id = assistant_msg.id
    _commit_with_retry(db)
    db.refresh(revision)
    db.refresh(assistant_msg)
    return revision, assistant_msg


def execute_revision_run(revision_id: str) -> None:
    db = SessionLocal()
    try:
        revision = db.get(Revision, revision_id)
        if revision is None or revision.status not in {"queued", "failed"}:
            db.close()
            return
        call_tracer.set_trace_context(revision.run_id, "revision_workflow")
        revision.status = "running"
        revision.started_at = datetime.utcnow()

        # Sync Run status to 'revising'
        run = db.get(Run, revision.run_id)
        if run:
            _set_run_status(run, "revising")
            run.active_revision_id = revision.id

        _commit_with_retry(db)

        ctx = _get_run_context(db, revision.run_id)
        llm = get_llm_provider()
        chat_history = [
            {"role": msg.role, "content": msg.content}
            for msg in ctx["chat_messages"]
            if msg.id != revision.chat_assistant_message_id
        ]

        current_report = {
            "title": ctx["report"].title,
            "summary": ctx["report"].summary,
            "markdown_content": ctx["report"].markdown_content,
            "iteration": ctx["report"].iteration,
        }
        competitor_list = [_competitor_to_dict(item) for item in ctx["competitors"]]
        selected_comp_ids_early = {c.id for c in ctx["competitors"] if c.selected}
        source_list = _source_list(db, revision.run_id, selected_comp_ids_early)

        intent_result = _run_revision_stage(
            db,
            revision.id,
            "revision_intent",
            {"message": revision.user_message},
            lambda: llm.classify_revision_intent(
                revision.user_message, current_report, chat_history
            ),
        )

        need_search = (
            bool(intent_result.get("need_search"))
            or intent_result.get("intent") == "research_required"
        )
        revision.intent = intent_result.get("intent", "report_edit")

        search_plan: dict[str, Any] = {}
        new_sources: list[Any] = []
        added_competitors: list[Any] = []
        activated_competitors: list[Any] = []
        removed_competitors: list[Any] = []
        affected_competitors: list[Any] = []
        plan_items: list[Any] = []

        workflow_steps: list[dict[str, Any]] = [
            {
                "title": "判断修改类型",
                "detail": "需要补充调研"
                if need_search
                else "报告细节修改，不需要新增资料",
            }
        ]

        # --- 竞品名单更新 (必须在搜索前执行) ---
        competitor_result = _run_revision_stage(
            db,
            revision.id,
            "revision_competitor_update",
            {
                "new_competitors": intent_result.get("new_competitors", []),
                "removed_competitors": intent_result.get("removed_competitors", []),
            },
            lambda: _ensure_revision_competitors(
                db,
                revision.run_id,
                ctx["competitors"],
                [],
                intent_result,
            ),
        )
        added_competitors = competitor_result.get("added", [])
        activated_competitors = competitor_result.get("activated", [])
        removed_competitors = competitor_result.get("removed", [])
        affected_competitors = competitor_result.get("affected", [])
        ctx["removed_competitor_names"] = [c.name for c in removed_competitors]
        ctx["competitors_original"] = list(ctx["competitors"])

        if added_competitors or activated_competitors or removed_competitors:
            # Fresh fetch: re-query from DB to ensure all IDs are populated
            # and state is consistent (especially for newly added competitors)
            ctx["competitors"] = (
                db.query(Competitor)
                .filter(
                    Competitor.run_id == revision.run_id, Competitor.selected.is_(True)
                )
                .all()
            )
            competitor_list = [_competitor_to_dict(item) for item in ctx["competitors"]]
            add_names = [
                item.name for item in (added_competitors + activated_competitors)
            ]
            remove_names = [item.name for item in removed_competitors]
            detail_parts: list[str] = []
            if add_names:
                detail_parts.append("已纳入：" + "、".join(add_names[:6]))
            if remove_names:
                detail_parts.append("已移除：" + "、".join(remove_names[:6]))
            workflow_steps.append(
                {"title": "处理竞品名单", "detail": "；".join(detail_parts)}
            )

        # --- 搜索与资料采集 ---
        if need_search:
            search_plan = _run_revision_stage(
                db,
                revision.id,
                "revision_search_plan",
                {
                    "message": revision.user_message,
                    "competitors": [c["name"] for c in competitor_list[:8]],
                },
                lambda: llm.generate_revision_search_plan(
                    revision.user_message,
                    current_report,
                    competitor_list,
                    source_list,
                ),
            )
            plan_items = (
                search_plan.get("search_plan") if isinstance(search_plan, dict) else []
            )
            workflow_steps.append(
                {
                    "title": "生成搜索 Query",
                    "detail": f"生成 {sum(len(item.get('queries', [])) for item in plan_items if isinstance(item, dict))} 条补充检索 query。",
                }
            )

            new_sources = _run_revision_stage(
                db,
                revision.id,
                "revision_material_collection",
                {"plan_items": str(plan_items)[:500]},
                lambda: _execute_revision_search_plan(
                    db,
                    revision.run_id,
                    plan_items or [],
                    {item.name: item for item in ctx["competitors"]},
                ),
            )
            workflow_steps.append(
                {
                    "title": "收集新资料",
                    "detail": f"新增 {len(new_sources)} 条公开来源。",
                }
            )

        # --- 新增/激活竞品的结构化分析 ---
        to_analyze = added_competitors + activated_competitors
        if to_analyze:
            _run_revision_stage(
                db,
                revision.id,
                "revision_competitor_analysis",
                {"competitors": [item.name for item in to_analyze]},
                lambda: _analyze_revision_competitors(
                    db,
                    revision.run_id,
                    to_analyze,
                    llm,
                    focus_items=_active_focus_items(ctx.get("requirement", {})),
                    qa_feedback=ctx.get("qa_feedback"),
                ),
            )
            workflow_steps.append(
                {
                    "title": "分析竞品",
                    "detail": f"已生成 {len(to_analyze)} 个竞品的结构化分析。",
                }
            )

        evidence_list = _evidence_list(db, revision.run_id, ctx["competitors"])

        _ensure_analyses_for_all_selected(db, revision.run_id, ctx["competitors"])

        analysis_list = _analysis_list(db, revision.run_id, evidence_list=evidence_list)
        new_source_list = [_source_to_dict(item) for item in new_sources]

        selected_comp_ids = {c.id for c in ctx["competitors"] if c.selected}
        source_list = _source_list(db, revision.run_id, selected_comp_ids)

        revision_plan = _run_revision_stage(
            db,
            revision.id,
            "revision_plan",
            {"message": revision.user_message, "intent": intent_result.get("intent")},
            lambda: llm.generate_revision_plan(
                revision.user_message,
                current_report,
                analysis_list,
                evidence_list,
                new_source_list,
                intent_result,
            ),
        )
        workflow_steps.append(
            {
                "title": "生成修订计划",
                "detail": _revision_plan_summary(revision_plan),
            }
        )

        citation_bundle = _build_citation_bundle(analysis_list, evidence_list)
        bundle_competitor_names = {
            c.get("competitor_name")
            for c in citation_bundle
            if c.get("competitor_name")
        }
        selected_competitor_names = {c.name for c in ctx["competitors"] if c.selected}
        missing_from_bundle = selected_competitor_names - bundle_competitor_names
        if missing_from_bundle:
            logger.warning(
                "citation_bundle missing competitors: %s (selected: %s, bundle: %s)",
                missing_from_bundle,
                selected_competitor_names,
                bundle_competitor_names,
            )
        new_report = _run_revision_stage(
            db,
            revision.id,
            "revision_report_generation",
            {"revision_plan": str(revision_plan)[:500]},
            lambda: llm.revise_report_with_plan(
                current_report,
                revision_plan,
                citation_bundle,
                source_list,
                removed_competitor_names=ctx.get("removed_competitor_names"),
                excluded_citation_ids=ctx.get("excluded_citation_ids"),
            ),
        )

        removed_citation_ids: set[str] = set()
        removed_names = ctx.get("removed_competitor_names") or []
        if removed_names:
            removed_comp_ids = {
                c.id
                for c in ctx.get("competitors_original", [])
                if c.name in removed_names
            }
            for src in db.query(Source).filter(Source.run_id == revision.run_id).all():
                if src.competitor_id in removed_comp_ids:
                    ref_id = src.reference_id or _extract_ref_id(src.metadata_json)
                    if ref_id:
                        removed_citation_ids.add(str(ref_id))
        ctx["excluded_citation_ids"] = {
            int(x) for x in removed_citation_ids if x.isdigit()
        }

        markdown_content = _protect_inline_citations(
            ctx["report"].markdown_content,
            new_report.get("markdown_content", ""),
            excluded_ids=removed_citation_ids,
        )

        new_report["markdown_content"] = markdown_content

        max_iteration = (
            db.query(func.max(Report.iteration))
            .filter(Report.run_id == revision.run_id)
            .scalar()
        )
        if max_iteration is None:
            max_iteration = -1
        # Save competitor names snapshot
        selected_names = [c.name for c in ctx["competitors"] if c.selected]

        new_report_record = Report(
            run_id=revision.run_id,
            iteration=max_iteration + 1,
            title=new_report.get("title", ctx["report"].title),
            markdown_content=markdown_content,
            summary=new_report.get("summary", ctx["report"].summary),
            competitor_names_json=json.dumps(selected_names, ensure_ascii=False),
        )
        db.add(new_report_record)
        db.commit()
        db.refresh(new_report_record)

        revision_summary = _run_revision_stage(
            db,
            revision.id,
            "revision_summary",
            {"report_version": new_report_record.iteration},
            lambda: llm.generate_revision_summary(
                revision.user_message,
                revision_plan,
                {
                    "title": new_report_record.title or "",
                    "summary": new_report_record.summary or "",
                    "markdown_content": new_report_record.markdown_content or "",
                },
            ),
        )
        workflow_steps.append(
            {
                "title": "生成新版本报告",
                "detail": f"已保存为{_human_report_version(new_report_record.iteration)}。",
            }
        )

        result = {
            "reply": revision_summary,
            "report_version": new_report_record.iteration,
            "intent": intent_result.get("intent", "report_edit"),
            "intent_result": intent_result,
            "action_type": "report_redo" if need_search else "report_edit",
            "workflow_steps": workflow_steps,
            "search_plan": search_plan,
            "revision_plan": revision_plan,
            "revision_summary": revision_summary,
            "new_queries": [],
            "action_details": {
                "need_search": need_search,
                "new_sources_count": len(new_sources),
                "added_competitors": [item.name for item in added_competitors],
                "original_report_version": ctx["report"].iteration,
                "new_report_version": new_report_record.iteration,
            },
        }

        revision.intent = result.get("intent") or "report_edit"
        revision.status = "completed"
        revision.target_report_iteration = result.get("report_version")
        revision.summary = result.get("revision_summary") or result.get("reply")
        revision.completed_at = datetime.utcnow()

        # Restore Run status to 'completed'
        run = db.get(Run, revision.run_id)
        if run:
            _set_run_status(run, "completed")
            run.active_revision_id = None

        _update_processing_message(db, revision, result)
        db.add(
            ChatMessage(
                run_id=revision.run_id,
                role="assistant",
                content=result.get("reply") or "修订已完成。",
                intent=result.get("intent"),
                action_type="revision_completed",
                report_version=result.get("report_version"),
                metadata_json=json.dumps(
                    {
                        "revision_id": revision.id,
                        "revision_status": "completed",
                        "new_queries": result.get("new_queries", []),
                        "workflow_steps": result.get("workflow_steps", []),
                        "action_details": result.get("action_details", {}),
                        "intent_result": result.get("intent_result", {}),
                        "search_plan": result.get("search_plan", {}),
                        "revision_plan": result.get("revision_plan", {}),
                        "revision_summary": result.get("revision_summary"),
                    },
                    ensure_ascii=False,
                ),
            )
        )
        _commit_with_retry(db)
    except Exception as exc:
        db.rollback()
        revision = db.get(Revision, revision_id)
        if revision is not None:
            revision.status = "failed"
            revision.error_message = str(exc)
            revision.completed_at = datetime.utcnow()

            # Restore Run status to 'completed' even on failure
            run = db.get(Run, revision.run_id)
            if run:
                _set_run_status(run, "completed")
                run.active_revision_id = None

            _close_running_revision_traces(db, revision_id, str(exc))
            _update_processing_message(db, revision, {"error": str(exc)})
            db.add(
                ChatMessage(
                    run_id=revision.run_id,
                    role="assistant",
                    content=f"修订失败：{exc}",
                    intent="revision_failed",
                    action_type="revision_failed",
                    report_version=revision.base_report_iteration,
                    metadata_json=json.dumps(
                        {
                            "revision_id": revision.id,
                            "revision_status": "failed",
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            _commit_with_retry(db)
    finally:
        call_tracer.clear_trace_context()
        db.close()


def list_revisions(db: Session, run_id: str) -> list[Revision]:
    return (
        db.query(Revision)
        .filter(Revision.run_id == run_id)
        .order_by(Revision.created_at.asc())
        .all()
    )


def list_revision_traces(db: Session, revision_id: str) -> list[RevisionTrace]:
    return (
        db.query(RevisionTrace)
        .filter(RevisionTrace.revision_id == revision_id)
        .order_by(RevisionTrace.started_at.asc())
        .all()
    )


def _run_revision_stage(
    db: Session,
    revision_id: str,
    stage: str,
    input_data: dict[str, Any],
    action: Callable[[], Any],
) -> Any:
    started_at = datetime.utcnow()
    trace = RevisionTrace(
        revision_id=revision_id,
        stage=stage,
        status="running",
        input_json=json.dumps(input_data, ensure_ascii=False, default=str),
        started_at=started_at,
    )
    db.add(trace)
    _commit_with_retry(db)
    try:
        result = action()
    except Exception as exc:
        ended_at = datetime.utcnow()
        trace.status = "failed"
        trace.error_message = str(exc)
        trace.ended_at = ended_at
        trace.duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        _commit_with_retry(db)
        raise
    ended_at = datetime.utcnow()
    trace.status = "completed"
    trace.output_json = json.dumps(
        _summarize_revision_stage(stage, result),
        ensure_ascii=False,
        default=str,
    )
    trace.ended_at = ended_at
    trace.duration_ms = int((ended_at - started_at).total_seconds() * 1000)
    _commit_with_retry(db)
    return result


def _summarize_revision_stage(stage: str, result: Any) -> dict[str, Any]:
    if stage == "revision_intent":
        if isinstance(result, dict):
            return {
                "summary": result.get("reason", "已判断修改类型"),
                "intent": result.get("intent"),
                "need_search": result.get("need_search"),
                "new_competitors": result.get("new_competitors", []),
            }
        return {"summary": str(result)[:200]}

    if stage == "revision_search_plan":
        if isinstance(result, dict):
            plan = result.get("search_plan", [])
            count = sum(
                len(item.get("queries", [])) for item in plan if isinstance(item, dict)
            )
            return {
                "summary": result.get("plan_summary", f"生成 {count} 条搜索 query"),
                "query_count": count,
            }
        return {"summary": str(result)[:200]}

    if stage == "revision_competitor_update":
        if isinstance(result, dict):
            added = result.get("added", [])
            activated = result.get("activated", [])
            existing = result.get("existing", [])
            affected = result.get("affected", [])
            names = [item.name for item in affected if hasattr(item, "name")]
            if names:
                return {
                    "summary": f"已纳入竞品：{'、'.join(names[:6])}",
                    "added_count": len(added),
                    "activated_count": len(activated),
                    "existing_count": len(existing),
                    "competitors": names,
                }
            return {"summary": "无新增竞品", "competitors": []}
        if isinstance(result, list):
            return {
                "summary": f"新增 {len(result)} 个竞品",
                "competitors": [item.name for item in result if hasattr(item, "name")],
            }
        return {"summary": str(result)[:200]}

    if stage == "revision_material_collection":
        if isinstance(result, list):
            return {
                "summary": f"新增 {len(result)} 条公开来源",
                "source_count": len(result),
            }
        return {"summary": str(result)[:200]}

    if stage == "revision_competitor_analysis":
        return {"summary": "已完成新增竞品结构化分析"}

    if stage == "revision_plan":
        if isinstance(result, dict):
            return {
                "summary": _revision_plan_summary(result),
                "revision_type": result.get("revision_type"),
                "structure_change": result.get("structure_change_needed"),
            }
        return {"summary": str(result)[:200]}

    if stage == "revision_report_validation":
        if isinstance(result, tuple) and len(result) == 2:
            _, added_sections = result
            names = added_sections if isinstance(added_sections, list) else []
            if names:
                return {
                    "summary": f"校验报告正文：已补充 {'、'.join(names[:4])} 章节",
                    "added_sections": names,
                }
            return {"summary": "校验报告正文：所有竞品章节已就绪", "added_sections": []}
        return {"summary": str(result)[:200]}

    if stage == "revision_report_generation":
        if isinstance(result, dict):
            return {
                "summary": result.get("summary", "已生成新版本报告"),
                "title": result.get("title"),
            }
        return {"summary": str(result)[:200]}

    if stage == "revision_summary":
        return {
            "summary": str(result)[:200]
            if not isinstance(result, dict)
            else result.get("summary", str(result))[:200]
        }

    return {"summary": str(result)[:200] if result is not None else "completed"}


def _close_running_revision_traces(
    db: Session, revision_id: str, error_message: str
) -> None:
    now = datetime.utcnow()
    running_traces = (
        db.query(RevisionTrace)
        .filter(
            RevisionTrace.revision_id == revision_id, RevisionTrace.status == "running"
        )
        .all()
    )
    for trace in running_traces:
        trace.status = "failed"
        trace.error_message = error_message
        trace.ended_at = now
        trace.duration_ms = int((now - trace.started_at).total_seconds() * 1000)


def _update_processing_message(
    db: Session, revision: Revision, result: dict[str, Any]
) -> None:
    if not revision.chat_assistant_message_id:
        return
    msg = db.get(ChatMessage, revision.chat_assistant_message_id)
    if msg is None:
        return
    msg.content = (
        f"修订已完成，已生成{_human_report_version(revision.target_report_iteration)}。"
        if revision.status == "completed"
        else f"修订失败：{result.get('error', revision.error_message or '未知错误')}"
    )
    msg.intent = (
        "revision_completed" if revision.status == "completed" else "revision_failed"
    )
    msg.action_type = msg.intent
    msg.report_version = (
        revision.target_report_iteration or revision.base_report_iteration
    )
    msg.metadata_json = json.dumps(
        {
            "revision_id": revision.id,
            "revision_status": revision.status,
            "processing": False,
            "processed": revision.status == "completed",
            "error": revision.error_message,
        },
        ensure_ascii=False,
    )
