import json
import logging
import random
import re
import time
from datetime import datetime
from typing import Any

from app.agents.state import ensure_dict
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Analysis,
    ChatMessage,
    Competitor,
    Evidence,
    QAResult,
    Report,
    Run,
    Source,
)
from app.db.session import SessionLocal
from app.agents.nodes.report_generation import _build_citation_bundle
from app.services.analysis_service import latest_analyses_by_competitor
from app.providers.llm.factory import get_llm_provider
from app.providers.search.factory import get_search_provider

logger = logging.getLogger(__name__)


class ChatError(ValueError):
    pass


def _get_run_context(db: Session, run_id: str) -> dict[str, Any]:
    run = db.get(Run, run_id)
    if run is None:
        raise ChatError(f"Run not found: {run_id}")

    # Align backend chat gating with the UI rule: if a report was already
    # created after a stale running trace, the current round is complete.
    from app.services.run_service import reconcile_stale_run_state

    reconcile_stale_run_state(db, run)
    db.refresh(run)

    latest_report = (
        db.query(Report)
        .filter(Report.run_id == run_id)
        .order_by(Report.iteration.desc())
        .first()
    )
    if latest_report is None:
        raise ChatError("报告尚未生成，暂不能进行对话修改。")

    analyses = latest_analyses_by_competitor(db, run_id)
    evidence_items = db.query(Evidence).filter(Evidence.run_id == run_id).all()
    sources = db.query(Source).filter(Source.run_id == run_id).all()
    competitors = (
        db.query(Competitor)
        .filter(Competitor.run_id == run_id, Competitor.selected.is_(True))
        .all()
    )
    chat_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.run_id == run_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )

    import json as _json

    requirement = _json.loads(run.requirement_json) if run.requirement_json else {}

    latest_qa = (
        db.query(QAResult)
        .filter(QAResult.run_id == run_id)
        .order_by(QAResult.iteration.desc())
        .first()
    )
    qa_feedback = latest_qa.retry_instructions if latest_qa else None

    return {
        "run": run,
        "report": latest_report,
        "analyses": analyses,
        "evidence": evidence_items,
        "sources": sources,
        "competitors": competitors,
        "chat_messages": chat_messages,
        "requirement": requirement,
        "qa_feedback": qa_feedback,
    }


def process_chat_message(run_id: str, user_message: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        ctx = _get_run_context(db, run_id)
        llm = get_llm_provider()
        report = ctx["report"]

        user_msg = ChatMessage(
            run_id=run_id,
            role="user",
            content=user_message,
            report_version=report.iteration,
            metadata_json=json.dumps(
                _queued_metadata() if ctx["run"].status == "running" else {},
                ensure_ascii=False,
            ),
        )
        db.add(user_msg)
        _commit_with_retry(db)
        db.refresh(user_msg)

        if ctx["run"].status == "running":
            assistant_msg = ChatMessage(
                run_id=run_id,
                role="assistant",
                content="已收到反馈。当前质检 Agent 仍在检查分析结果，我会在质检结束后基于最新版本处理你的修改。",
                intent="queued_revision",
                action_type="queued_revision",
                report_version=report.iteration,
                metadata_json=json.dumps(
                    {
                        "queued": True,
                        "processed": False,
                        "reason": "waiting_for_quality_check",
                    },
                    ensure_ascii=False,
                ),
            )
            db.add(assistant_msg)
            _commit_with_retry(db)
            db.refresh(assistant_msg)
            return {
                "message": assistant_msg,
                "report_version": report.iteration,
                "intent": "queued_revision",
                "action_type": "queued_revision",
            }

        chat_history = [
            {"role": msg.role, "content": msg.content} for msg in ctx["chat_messages"]
        ] + [{"role": "user", "content": user_message}]

        result = _handle_revision_workflow(db, ctx, llm, user_message, chat_history)
        intent = result.get("intent", "report_edit")
        intent_result = result.get("intent_result", {})
        logger.info(
            "Chat intent: %s for run %s, reason: %s",
            intent,
            run_id,
            intent_result.get("reason"),
        )

        assistant_msg = ChatMessage(
            run_id=run_id,
            role="assistant",
            content=result["reply"],
            intent=intent,
            action_type=result.get("action_type", intent),
            report_version=result.get("report_version"),
            metadata_json=json.dumps(
                {
                    "intent_reason": intent_result.get("reason"),
                    "new_queries": result.get("new_queries", []),
                    "workflow_steps": result.get("workflow_steps", []),
                    "action_details": result.get("action_details", {}),
                    "intent_result": intent_result,
                    "search_plan": result.get("search_plan", {}),
                    "revision_plan": result.get("revision_plan", {}),
                    "revision_summary": result.get("revision_summary"),
                },
                ensure_ascii=False,
            ),
        )
        db.add(assistant_msg)
        _commit_with_retry(db)
        db.refresh(assistant_msg)

        return {
            "message": assistant_msg,
            "report_version": result.get("report_version"),
            "intent": intent,
            "action_type": result.get("action_type", intent),
        }
    finally:
        db.close()


def enqueue_chat_message(run_id: str, user_message: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        ctx = _get_run_context(db, run_id)
        run: Run = ctx["run"]
        report: Report = ctx["report"]
        waiting_for_auto_flow = run.status == "running"

        user_msg = ChatMessage(
            run_id=run_id,
            role="user",
            content=user_message,
            report_version=report.iteration,
            metadata_json=json.dumps(
                _queued_metadata(processing=False), ensure_ascii=False
            ),
        )
        db.add(user_msg)
        _commit_with_retry(db)
        db.refresh(user_msg)

        assistant_msg = ChatMessage(
            run_id=run_id,
            role="assistant",
            content=(
                "已收到反馈。当前质检 Agent 仍在检查分析结果，我会在质检结束后基于最新版本处理你的修改。"
                if waiting_for_auto_flow
                else "已收到反馈，Agent 正在基于当前报告规划修订流程。"
            ),
            intent="queued_revision"
            if waiting_for_auto_flow
            else "revision_processing",
            action_type="queued_revision"
            if waiting_for_auto_flow
            else "revision_processing",
            report_version=report.iteration,
            metadata_json=json.dumps(
                {
                    "queued": True,
                    "processing": not waiting_for_auto_flow,
                    "processed": False,
                    "reason": "waiting_for_quality_check"
                    if waiting_for_auto_flow
                    else "processing_revision",
                    "queued_message_id": user_msg.id,
                },
                ensure_ascii=False,
            ),
        )
        db.add(assistant_msg)
        _commit_with_retry(db)
        db.refresh(assistant_msg)
        return {
            "message": assistant_msg,
            "report_version": report.iteration,
            "intent": assistant_msg.intent,
            "action_type": assistant_msg.action_type,
        }
    finally:
        db.close()


def _commit_with_retry(db: Session, *, attempts: int = 5) -> None:
    for index in range(attempts):
        try:
            db.commit()
            return
        except OperationalError as exc:
            if "database is locked" not in str(exc).lower() or index == attempts - 1:
                db.rollback()
                raise ChatError("Agent 当前正在写入数据，请稍后重试。") from exc
            db.rollback()
            delay = (2**index) * 0.1 + random.uniform(0.0, 0.1)
            time.sleep(delay)
        except IntegrityError as exc:
            db.rollback()
            if "unique" in str(exc).lower() or "constraint" in str(exc).lower():
                raise ChatError("报告版本冲突，请重试。") from exc
            raise


def _queued_metadata(
    *, processed: bool = False, processing: bool = False
) -> dict[str, Any]:
    return {
        "queued": True,
        "processing": processing,
        "processed": processed,
        "reason": "waiting_for_quality_check",
    }


def _human_report_version(iteration: int | None) -> str:
    return f"第 {(iteration or 0) + 1} 版"


def _parse_metadata(metadata_json: str | None) -> dict[str, Any]:
    if not metadata_json:
        return {}
    try:
        parsed = json.loads(metadata_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def process_queued_revisions(run_id: str) -> None:
    db = SessionLocal()
    try:
        ctx = _get_run_context(db, run_id)
        run: Run = ctx["run"]
        if run.status not in {"completed", "failed"}:
            return
        if run.active_revision_id:
            logger.info(
                "Skipping queued revisions for run %s: revision %s is active",
                run_id,
                run.active_revision_id,
            )
            return

        queued_messages = []
        for msg in ctx["chat_messages"]:
            metadata = _parse_metadata(msg.metadata_json)
            if (
                msg.role == "user"
                and metadata.get("queued")
                and not metadata.get("processed")
                and not metadata.get("processing")
            ):
                queued_messages.append(msg)
        if not queued_messages:
            return

        for msg in queued_messages:
            msg.metadata_json = json.dumps(
                _queued_metadata(processing=True), ensure_ascii=False
            )
        _commit_with_retry(db)

        combined_feedback = "\n".join(
            f"{index + 1}. {msg.content}" for index, msg in enumerate(queued_messages)
        )
        llm = get_llm_provider()
        chat_history = [
            {"role": msg.role, "content": msg.content}
            for msg in ctx["chat_messages"]
            if msg.id not in {queued.id for queued in queued_messages}
        ] + [{"role": "user", "content": combined_feedback}]
        result = _handle_revision_workflow(
            db, ctx, llm, combined_feedback, chat_history
        )
        intent = result.get("intent", "report_edit")
        intent_result = result.get("intent_result", {})

        assistant_msg = ChatMessage(
            run_id=run_id,
            role="assistant",
            content=result["reply"],
            intent=intent,
            action_type="queued_revision_processed",
            report_version=result.get("report_version"),
            metadata_json=json.dumps(
                {
                    "queued_batch_processed": True,
                    "queued_message_ids": [msg.id for msg in queued_messages],
                    "intent_reason": intent_result.get("reason"),
                    "new_queries": result.get("new_queries", []),
                    "workflow_steps": result.get("workflow_steps", []),
                    "action_details": result.get("action_details", {}),
                    "intent_result": intent_result,
                    "search_plan": result.get("search_plan", {}),
                    "revision_plan": result.get("revision_plan", {}),
                    "revision_summary": result.get("revision_summary"),
                },
                ensure_ascii=False,
            ),
        )
        db.add(assistant_msg)
        for msg in queued_messages:
            msg.metadata_json = json.dumps(
                _queued_metadata(processed=True), ensure_ascii=False
            )
        _commit_with_retry(db)
    except Exception:
        logger.exception("Failed to process queued revisions for run %s", run_id)
        db.rollback()
        for msg in (
            db.query(ChatMessage)
            .filter(ChatMessage.run_id == run_id, ChatMessage.role == "user")
            .all()
        ):
            metadata = _parse_metadata(msg.metadata_json)
            if (
                metadata.get("queued")
                and metadata.get("processing")
                and not metadata.get("processed")
            ):
                msg.metadata_json = json.dumps(
                    _queued_metadata(processed=False), ensure_ascii=False
                )
        try:
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def _handle_report_edit(
    db: Session,
    ctx: dict[str, Any],
    llm,
    user_message: str,
) -> dict[str, Any]:
    report = ctx["report"]
    analyses = ctx["analyses"]
    evidence = ctx["evidence"]

    context_parts = []
    for analysis in analyses:
        comp_name = (
            analysis.competitor.name if analysis.competitor else analysis.competitor_id
        )
        context_parts.append(
            f"竞品 {comp_name}: 定位={(analysis.positioning or '')[:100]}, "
            f"价格={(analysis.pricing_summary or '')[:100]}"
        )
    context = "\n".join(context_parts[:10])

    new_markdown = llm.edit_report_markdown(
        report.markdown_content,
        user_message,
        context,
    )
    new_markdown = _protect_inline_citations(report.markdown_content, new_markdown)

    max_iteration = (
        db.query(func.max(Report.iteration))
        .filter(Report.run_id == report.run_id)
        .scalar()
    )
    if max_iteration is None:
        max_iteration = -1
    selected_names = [
        c.name
        for c in db.query(Competitor.name)
        .filter(Competitor.run_id == report.run_id, Competitor.selected.is_(True))
        .all()
    ]
    new_report = Report(
        run_id=report.run_id,
        iteration=max_iteration + 1,
        title=report.title,
        markdown_content=new_markdown,
        summary=report.summary,
        competitor_names_json=json.dumps(selected_names, ensure_ascii=False),
    )
    db.add(new_report)
    try:
        _commit_with_retry(db)
    except IntegrityError:
        db.rollback()
        max_iteration = (
            db.query(func.max(Report.iteration))
            .filter(Report.run_id == report.run_id)
            .scalar()
            or -1
        )
        new_report = Report(
            run_id=report.run_id,
            iteration=max_iteration + 1,
            title=report.title,
            markdown_content=new_markdown,
            summary=report.summary,
            competitor_names_json=json.dumps(selected_names, ensure_ascii=False),
        )
        db.add(new_report)
        _commit_with_retry(db)
    db.refresh(new_report)

    return {
        "reply": f"已根据你的反馈修改报告（{_human_report_version(new_report.iteration)}）。你可以查看更新后的报告，或继续提出修改意见。",
        "report_version": new_report.iteration,
        "action_type": "report_edit",
        "action_details": {
            "modified_by_user": user_message,
            "original_report_version": report.iteration,
            "new_report_version": new_report.iteration,
        },
        "workflow_steps": [
            {
                "title": "判断修改类型",
                "detail": "识别为报告细节修改，不需要重新搜索资料。",
            },
            {
                "title": "编辑报告内容",
                "detail": "基于当前报告和结构化分析上下文执行局部改写。",
            },
            {
                "title": "保存新版本",
                "detail": f"生成{_human_report_version(new_report.iteration)}。",
            },
        ],
    }


def _handle_revision_workflow(
    db: Session,
    ctx: dict[str, Any],
    llm,
    user_message: str,
    chat_history: list[dict[str, str]],
) -> dict[str, Any]:
    report: Report = ctx["report"]
    competitors: list[Competitor] = ctx["competitors"]
    current_report = {
        "title": report.title,
        "summary": report.summary,
        "markdown_content": report.markdown_content,
        "iteration": report.iteration,
    }
    competitor_list = [_competitor_to_dict(item) for item in competitors]
    selected_comp_ids = {c.id for c in competitors if c.selected}
    source_list = _source_list(db, report.run_id, selected_comp_ids)
    analysis_list = _analysis_list(db, report.run_id)
    evidence_list = _evidence_list(db, report.run_id, competitors)

    intent_result = llm.classify_revision_intent(
        user_message,
        current_report,
        chat_history,
    )
    need_search = (
        bool(intent_result.get("need_search"))
        or intent_result.get("intent") == "research_required"
        or bool(intent_result.get("new_competitors"))
        or bool(intent_result.get("removed_competitors"))
        or _looks_like_research_feedback(user_message)
    )
    workflow_steps = [
        {
            "title": "判断修改类型",
            "detail": "需要补充调研" if need_search else "报告细节修改，不需要新增资料",
        }
    ]

    search_plan: dict[str, Any] = {}
    new_sources: list[Source] = []
    added_competitors: list[Competitor] = []
    activated_competitors: list[Competitor] = []
    removed_competitors: list[Competitor] = []

    # --- 竞品名单更新 (必须在搜索前执行) ---
    competitor_result = _ensure_revision_competitors(
        db,
        report.run_id,
        competitors,
        [],
        intent_result,
    )
    added_competitors = competitor_result.get("added", [])
    activated_competitors = competitor_result.get("activated", [])
    removed_competitors = competitor_result.get("removed", [])

    if added_competitors or activated_competitors or removed_competitors:
        # Fresh fetch: re-query from DB to ensure all IDs are populated
        # and state is consistent (especially for newly added competitors)
        competitors = (
            db.query(Competitor)
            .filter(Competitor.run_id == report.run_id, Competitor.selected.is_(True))
            .all()
        )
        competitor_list = [_competitor_to_dict(item) for item in competitors]
        add_names = [item.name for item in (added_competitors + activated_competitors)]
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
        search_plan = llm.generate_revision_search_plan(
            user_message,
            current_report,
            competitor_list,
            source_list,
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
        new_sources = _execute_revision_search_plan(
            db,
            report.run_id,
            plan_items or [],
            {item.name: item for item in competitors},
        )
        workflow_steps.append(
            {
                "title": "收集新资料",
                "detail": f"新增 {len(new_sources)} 条公开来源。",
            }
        )

    # --- 新增/激活竞品的结构化分析（必须在搜索之后，确保证据可用） ---
    to_analyze = added_competitors + activated_competitors
    if to_analyze:
        run = ctx.get("run")
        requirement = ensure_dict(
            json.loads(run.requirement_json) if run and run.requirement_json else {}
        )
        _latest_qa_feedback = _get_latest_qa_feedback(db, report.run_id)
        _analyze_revision_competitors(
            db,
            report.run_id,
            to_analyze,
            llm,
            focus_items=_active_focus_items(requirement),
            qa_feedback=_latest_qa_feedback,
        )
        workflow_steps.append(
            {
                "title": "分析新增竞品",
                "detail": f"已生成 {len(to_analyze)} 个竞品的结构化分析。",
            }
        )

    selected_comp_ids = {c.id for c in competitors if c.selected}
    source_list = _source_list(db, report.run_id, selected_comp_ids)
    evidence_list = _evidence_list(db, report.run_id, competitors)

    _ensure_analyses_for_all_selected(db, report.run_id, competitors)

    analysis_list = _analysis_list(db, report.run_id, evidence_list=evidence_list)
    new_source_list = [_source_to_dict(item) for item in new_sources]

    revision_plan = llm.generate_revision_plan(
        user_message,
        current_report,
        analysis_list,
        evidence_list,
        new_source_list,
        intent_result,
    )
    workflow_steps.append(
        {
            "title": "生成修订计划",
            "detail": _revision_plan_summary(revision_plan),
        }
    )

    citation_bundle = _build_citation_bundle(analysis_list, evidence_list)
    bundle_competitor_names = {
        c.get("competitor_name") for c in citation_bundle if c.get("competitor_name")
    }
    selected_competitor_names = {c.name for c in competitors if c.selected}
    missing_from_bundle = selected_competitor_names - bundle_competitor_names
    if missing_from_bundle:
        logger.warning(
            "citation_bundle missing competitors: %s (selected: %s, bundle: %s)",
            missing_from_bundle,
            selected_competitor_names,
            bundle_competitor_names,
        )
    removed_citation_ids: set[str] = set()
    if removed_competitors:
        removed_comp_ids = {c.id for c in removed_competitors}
        for src in db.query(Source).filter(Source.run_id == report.run_id).all():
            if src.competitor_id in removed_comp_ids:
                ref_id = _extract_ref_id(src.metadata_json)
                if ref_id:
                    removed_citation_ids.add(str(ref_id))
    new_report = llm.revise_report_with_plan(
        current_report,
        revision_plan,
        citation_bundle,
        source_list,
        removed_competitor_names=[c.name for c in removed_competitors],
        excluded_citation_ids=removed_citation_ids,
    )
    markdown_content = _protect_inline_citations(
        report.markdown_content,
        new_report.get("markdown_content", ""),
        excluded_ids=removed_citation_ids,
    )
    new_report["markdown_content"] = markdown_content

    max_iteration = (
        db.query(func.max(Report.iteration))
        .filter(Report.run_id == report.run_id)
        .scalar()
    )
    if max_iteration is None:
        max_iteration = -1
    selected_names = [c.name for c in competitors if c.selected]
    new_report_record = Report(
        run_id=report.run_id,
        iteration=max_iteration + 1,
        title=new_report.get("title", report.title),
        markdown_content=markdown_content,
        summary=new_report.get("summary", report.summary),
        competitor_names_json=json.dumps(selected_names, ensure_ascii=False),
    )
    db.add(new_report_record)
    _commit_with_retry(db)
    db.refresh(new_report_record)

    revision_summary = llm.generate_revision_summary(
        user_message,
        revision_plan,
        {
            "title": new_report_record.title,
            "summary": new_report_record.summary,
            "markdown_content": new_report_record.markdown_content,
        },
    )
    workflow_steps.append(
        {
            "title": "生成新版本报告",
            "detail": f"已保存为{_human_report_version(new_report_record.iteration)}。",
        }
    )

    return {
        "reply": revision_summary,
        "report_version": new_report_record.iteration,
        "intent": "report_redo" if need_search else "report_edit",
        "intent_result": intent_result,
        "action_type": "report_redo" if need_search else "report_edit",
        "workflow_steps": workflow_steps,
        "search_plan": search_plan,
        "revision_plan": revision_plan,
        "revision_summary": revision_summary,
        "new_queries": _flatten_search_queries(search_plan),
        "action_details": {
            "need_search": need_search,
            "new_sources_count": len(new_sources),
            "added_competitors": [item.name for item in added_competitors],
            "original_report_version": report.iteration,
            "new_report_version": new_report_record.iteration,
        },
    }


def _handle_report_redo(
    db: Session,
    ctx: dict[str, Any],
    llm,
    user_message: str,
    intent_result: dict[str, Any],
) -> dict[str, Any]:
    report = ctx["report"]
    competitors = ctx["competitors"]
    search = get_search_provider()

    existing_competitor_names = [c.name for c in competitors]
    query_result = llm.generate_chat_queries(
        user_message,
        report.summary or report.title,
        existing_competitor_names,
    )
    retry_queries = query_result.get("retry_queries", [])
    retry_instructions = query_result.get("retry_instructions", user_message)

    if not retry_queries:
        retry_queries = _fallback_chat_queries(existing_competitor_names, user_message)

    new_sources = []
    new_evidence = []
    seen_urls = {
        s.url for s in db.query(Source.url).filter(Source.run_id == report.run_id).all()
    }
    next_reference_id = _next_reference_id(db, report.run_id)

    for rq in retry_queries:
        comp_name = rq.get("competitor_name", "")
        query = rq.get("query", "")
        if not query:
            continue
        try:
            results = search.search(query, limit=3)
        except Exception:
            continue
        for result in results:
            if result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            competitor = _fuzzy_find_competitor(
                comp_name, {c.name: c for c in competitors}
            )
            source = Source(
                run_id=report.run_id,
                title=result.title,
                url=result.url,
                snippet=result.snippet,
                source_type="unknown",
                provider=search.name,
                competitor_id=competitor.id if competitor else None,
                reference_id=next_reference_id,
                metadata_json=json.dumps(
                    {"reference_id": next_reference_id}, ensure_ascii=False
                ),
            )
            next_reference_id += 1
            db.add(source)
            try:
                db.flush()
            except Exception:
                db.rollback()
                continue
            new_sources.append(source)

            evidence = Evidence(
                run_id=report.run_id,
                source_id=source.id,
                related_product=competitor.name if competitor else comp_name,
                related_dimension=_map_to_standard_dimension(
                    rq.get("slot", "core_features")
                ),
                quote=(result.snippet or "")[:800],
                summary=result.snippet or "",
                confidence=0.65,
                reference_id=source.reference_id,
            )
            db.add(evidence)
            try:
                db.flush()
            except Exception:
                db.rollback()
                continue
            new_evidence.append(evidence)

    _commit_with_retry(db)

    evidence_items = db.query(Evidence).filter(Evidence.run_id == report.run_id).all()

    affected_comp_names = {rq.get("competitor_name") for rq in retry_queries}
    affected_competitor_ids = {
        c.id for c in competitors if c.name in affected_comp_names
    }

    # We no longer delete old analyses to preserve history.
    # New analyses will be created with a higher iteration number.

    for competitor in competitors:
        if competitor.id not in affected_competitor_ids:
            continue
        comp_evidence = [
            {
                "id": e.id,
                "competitor_id": e.source.competitor_id if e.source else None,
                "related_product": e.related_product,
                "related_dimension": e.related_dimension,
                "quote": e.quote,
                "summary": e.summary,
                "confidence": e.confidence,
                "source_url": e.source.url if e.source else None,
                "source_title": e.source.title if e.source else None,
                "reference_id": (
                    e.reference_id
                    if e.reference_id is not None
                    else _extract_ref_id(e.source.metadata_json if e.source else None)
                ),
                "source_type": e.source.source_type if e.source else "unknown",
            }
            for e in evidence_items
            if e.related_product == competitor.name
        ]
        comp = {
            "id": competitor.id,
            "name": competitor.name,
            "website": competitor.website,
            "description": competitor.description,
            "category": competitor.category,
            "region": competitor.region,
            "confidence": competitor.confidence,
            "_qa_feedback": retry_instructions,
        }
        analysis = llm.analyze_competitor(comp, comp_evidence)
        db.add(
            Analysis(
                run_id=report.run_id,
                competitor_id=competitor.id,
                positioning=_str(analysis.get("positioning"), ""),
                target_users=_str(analysis.get("target_users"), "[]"),
                core_features_json=_str(analysis.get("core_features_json"), "[]"),
                pricing_summary=_str(analysis.get("pricing_summary"), ""),
                strengths_json=_str(analysis.get("strengths_json"), "[]"),
                weaknesses_json=_str(analysis.get("weaknesses_json"), "[]"),
                opportunities_json=_str(analysis.get("opportunities_json"), "[]"),
                custom_focus_analysis_json=_str(
                    analysis.get("custom_focus_analysis_json"), "[]"
                ),
                evidence_ids_json=json.dumps(
                    [e["id"] for e in comp_evidence if e.get("id")],
                    ensure_ascii=False,
                ),
                analysis_iteration=report.iteration + 1,
            )
        )
    _commit_with_retry(db)

    selected_comp_ids = {c.id for c in competitors if c.selected}
    source_list = _source_list(db, report.run_id, selected_comp_ids)
    evidence_list = _evidence_list(db, report.run_id, competitors)

    _ensure_analyses_for_all_selected(db, report.run_id, competitors)

    analysis_list = _analysis_list(db, report.run_id, evidence_list=evidence_list)
    citation_bundle = _build_citation_bundle(analysis_list, evidence_list)

    new_report = llm.generate_report(
        {
            "title": report.title,
            "user_requirement": ctx["run"].user_requirement,
            "requirement_summary": ctx["run"].requirement_summary,
            "qa_analysis_guidance": retry_instructions,
            "citation_bundle": citation_bundle,
        },
        analysis_list,
        source_list,
    )

    max_iteration = (
        db.query(func.max(Report.iteration))
        .filter(Report.run_id == report.run_id)
        .scalar()
    )
    if max_iteration is None:
        max_iteration = -1
    markdown_content = _protect_inline_citations(
        report.markdown_content, new_report.get("markdown_content", "")
    )
    selected_names = [c.name for c in competitors if c.selected]
    new_report_record = Report(
        run_id=report.run_id,
        iteration=max_iteration + 1,
        title=new_report.get("title", report.title),
        markdown_content=markdown_content,
        summary=new_report.get("summary", report.summary),
        competitor_names_json=json.dumps(selected_names, ensure_ascii=False),
    )
    db.add(new_report_record)
    _commit_with_retry(db)
    db.refresh(new_report_record)

    return {
        "reply": (
            f"已根据你的反馈重新调研并生成报告（{_human_report_version(new_report_record.iteration)}）。\n"
            f"新增了 {len(new_sources)} 个信息来源，重新分析了 {len(affected_competitor_ids)} 个竞品。\n"
            f"你可以查看更新后的报告，或继续提出意见。"
        ),
        "report_version": new_report_record.iteration,
        "action_type": "report_redo",
        "new_queries": [
            {"competitor_name": rq["competitor_name"], "query": rq["query"]}
            for rq in retry_queries
        ],
        "action_details": {
            "action": "report_redo",
            "new_sources_count": len(new_sources),
            "reanalyzed_competitors": list(affected_competitor_ids),
            "reanalyzed_competitor_names": [
                c.name for c in competitors if c.id in affected_competitor_ids
            ],
            "search_queries": [
                {"competitor_name": rq["competitor_name"], "query": rq["query"]}
                for rq in retry_queries
            ],
            "original_report_version": report.iteration,
            "new_report_version": new_report_record.iteration,
        },
        "workflow_steps": [
            {"title": "判断修改类型", "detail": "识别为需要重新调研/重新分析的反馈。"},
            {
                "title": "生成搜索查询",
                "detail": f"生成 {len(retry_queries)} 条补充检索 query。",
            },
            {"title": "搜索新资料", "detail": f"新增 {len(new_sources)} 个公开来源。"},
            {
                "title": "重新分析竞品",
                "detail": f"重新分析 {len(affected_competitor_ids)} 个受影响竞品。",
            },
            {
                "title": "生成新报告",
                "detail": f"生成{_human_report_version(new_report_record.iteration)}。",
            },
        ],
    }


def _fallback_chat_queries(
    competitors: list[str], user_message: str
) -> list[dict[str, str]]:
    queries = []
    for comp in competitors[:4]:
        queries.append(
            {
                "competitor_name": comp,
                "slot": "core_features",
                "query": f"{comp} {user_message[:40]}",
            }
        )
    return queries


def _competitor_to_dict(competitor: Competitor) -> dict[str, Any]:
    return {
        "id": competitor.id,
        "name": competitor.name,
        "website": competitor.website,
        "description": competitor.description,
        "category": competitor.category,
        "region": competitor.region,
        "confidence": competitor.confidence,
    }


def _source_to_dict(source: Source) -> dict[str, Any]:
    ref_id = (
        source.reference_id
        if source.reference_id and source.reference_id > 0
        else _extract_ref_id(source.metadata_json)
    )
    return {
        "id": source.id,
        "competitor_id": source.competitor_id,
        "title": source.title,
        "url": source.url,
        "snippet": source.snippet,
        "source_type": source.source_type,
        "provider": source.provider,
        "raw_content": source.raw_content,
        "reference_id": ref_id,
        "metadata_json": source.metadata_json,
    }


def _ensure_revision_competitors(
    db: Session,
    run_id: str,
    existing: list[Competitor],
    plan_items: list[dict[str, Any]],
    intent_result: dict[str, Any],
) -> dict[str, list[Competitor]]:
    existing_by_name: dict[str, Competitor] = {}
    for item in existing:
        key = _normalize_comp_name(item.name)
        if key not in existing_by_name:
            existing_by_name[key] = item

    requested_names: list[str] = []
    for value in intent_result.get("new_competitors") or []:
        name = str(value).strip()
        if name:
            requested_names.append(name)
    for value in intent_result.get("affected_competitors") or []:
        name = str(value).strip()
        if not name:
            continue
        matched = _fuzzy_find_competitor(name, {c.name: c for c in existing})
        if not matched:
            logger.warning(
                "affected_competitor '%s' not found in existing competitors; skipping (not creating new)",
                name,
            )
            continue
        requested_names.append(name)
    for item in plan_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("competitor_name") or "").strip()
        if name:
            requested_names.append(name)

    added: list[Competitor] = []
    activated: list[Competitor] = []
    existing_affected: list[Competitor] = []
    removed: list[Competitor] = []

    for name in requested_names:
        key = _normalize_comp_name(name)
        if not key or key in {"目标产品", "竞品名或目标对象"}:
            continue
        matched = existing_by_name.get(key)
        if not matched:
            matched = _fuzzy_find_competitor(name, {c.name: c for c in existing})
        if matched:
            if not matched.selected:
                matched.selected = True
                matched.discovery_source = "user_revision"
                activated.append(matched)
            else:
                existing_affected.append(matched)
            continue
        competitor = Competitor(
            run_id=run_id,
            name=name[:120],
            website=None,
            description="用户二轮反馈中新增的竞品，已进入补充调研。",
            category="revision_added",
            region=None,
            confidence=0.9,
            selected=True,
            discovery_source="user_revision",
            relationship_type="direct",
            relationship_reason="用户要求补充到竞品分析报告中。",
        )
        db.add(competitor)
        db.flush()
        added.append(competitor)
        existing_by_name[key] = competitor

    for value in intent_result.get("removed_competitors") or []:
        name = str(value).strip()
        if not name:
            continue
        key = _normalize_comp_name(name)
        matched = existing_by_name.get(key)
        if not matched:
            matched = _fuzzy_find_competitor(name, {c.name: c for c in existing})
        if matched and matched.selected:
            matched.selected = False
            removed.append(matched)

    total_selected_after = sum(1 for c in existing if c.selected) + len(added)
    if total_selected_after <= 0 and removed:
        for comp in removed:
            comp.selected = True
        logger.warning(
            "Refused to remove all competitors; at least one must remain. "
            "Attempted to remove: %s",
            [c.name for c in removed],
        )
        removed.clear()

    if added or activated or removed:
        db.commit()
    affected = added + activated + existing_affected
    seen_ids = set()
    unique_affected: list[Competitor] = []
    for item in affected:
        if item.id not in seen_ids:
            seen_ids.add(item.id)
            unique_affected.append(item)
    return {
        "added": added,
        "activated": activated,
        "existing": existing_affected,
        "affected": unique_affected,
        "removed": removed,
    }


def _normalize_comp_name(name: str) -> str:
    return re.sub(r"[\s\-_]+", "", name).lower().strip()


def _looks_like_new_competitor_request(
    intent_result: dict[str, Any], name: str
) -> bool:
    goal = str(intent_result.get("user_goal") or "")
    return name in goal and any(
        keyword in goal for keyword in ["新增", "增加", "加上", "补充", "加入"]
    )


def _source_list(
    db: Session,
    run_id: str,
    selected_competitor_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    query = db.query(Source).filter(Source.run_id == run_id)
    if selected_competitor_ids is not None:
        query = query.filter(
            (Source.competitor_id.in_(selected_competitor_ids))
            | (Source.competitor_id.is_(None))
        )
    return [_source_to_dict(item) for item in query.all()]


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _evidence_list(
    db: Session, run_id: str, competitors: list[Competitor]
) -> list[dict[str, Any]]:
    by_name = {item.name: item.id for item in competitors}
    selected_ids = {item.id for item in competitors if item.selected}
    items = db.query(Evidence).filter(Evidence.run_id == run_id).all()
    result: list[dict[str, Any]] = []
    for item in items:
        comp_id = (
            item.source.competitor_id
            if item.source and item.source.competitor_id
            else by_name.get(item.related_product)
        )
        if comp_id and comp_id not in selected_ids:
            continue
        ref_id = (
            item.reference_id
            if item.reference_id is not None
            else _extract_ref_id(item.source.metadata_json if item.source else None)
        )
        result.append(
            {
                "id": item.id,
                "competitor_id": comp_id,
                "related_product": item.related_product,
                "related_dimension": item.related_dimension,
                "quote": item.quote,
                "summary": item.summary,
                "confidence": item.confidence,
                "source_url": item.source.url if item.source else None,
                "source_title": item.source.title if item.source else None,
                "reference_id": ref_id,
                "source_type": item.source.source_type if item.source else "unknown",
            }
        )
    return result


def _analysis_list(
    db: Session,
    run_id: str,
    evidence_list: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    evidence_by_competitor: dict[str, list[str]] = {}
    if evidence_list:
        for item in evidence_list:
            competitor_id = item.get("competitor_id")
            evidence_id = item.get("id")
            if competitor_id and evidence_id:
                evidence_by_competitor.setdefault(str(competitor_id), []).append(
                    str(evidence_id)
                )

    analyses = latest_analyses_by_competitor(db, run_id)
    competitor_by_id: dict[str, Competitor] = {}
    if not analyses:
        return []
    for item in analyses:
        if item.competitor:
            competitor_by_id[item.competitor_id] = item.competitor
    if not competitor_by_id:
        competitor_by_id = {
            c.id: c
            for c in db.query(Competitor).filter(Competitor.run_id == run_id).all()
        }
    result = []
    for item in analyses:
        evidence_ids = _json_list(item.evidence_ids_json)
        merged_ids = list(
            dict.fromkeys(
                evidence_ids + evidence_by_competitor.get(item.competitor_id, [])
            )
        )
        competitor_name = ""
        if item.competitor:
            competitor_name = item.competitor.name
        elif item.competitor_id in competitor_by_id:
            competitor_name = competitor_by_id[item.competitor_id].name
            logger.warning(
                "Analysis %s competitor relation missing, fallback lookup: %s",
                item.id,
                competitor_name,
            )
        result.append(
            {
                "id": item.id,
                "competitor_id": item.competitor_id,
                "competitor_name": competitor_name,
                "positioning": item.positioning,
                "target_users": item.target_users,
                "core_features_json": item.core_features_json,
                "pricing_summary": item.pricing_summary,
                "strengths_json": item.strengths_json,
                "weaknesses_json": item.weaknesses_json,
                "opportunities_json": item.opportunities_json,
                "custom_focus_analysis_json": item.custom_focus_analysis_json,
                "evidence_ids_json": json.dumps(merged_ids, ensure_ascii=False),
            }
        )
    return result


def _analyze_revision_competitors(
    db: Session,
    run_id: str,
    competitors: list[Competitor],
    llm,
    focus_items: list[dict] | None = None,
    qa_feedback: str | None = None,
) -> None:
    if not competitors:
        return

    max_analysis_iter = (
        db.query(func.max(Analysis.analysis_iteration))
        .filter(Analysis.run_id == run_id)
        .scalar()
    )
    next_analysis_iteration = (
        max_analysis_iter if max_analysis_iter is not None else 0
    ) + 1

    evidence_items = db.query(Evidence).filter(Evidence.run_id == run_id).all()
    for competitor in competitors:
        comp_name_norm = _normalize_comp_name(competitor.name)
        comp_evidence = [
            {
                "id": item.id,
                "competitor_id": competitor.id,
                "related_product": item.related_product,
                "related_dimension": item.related_dimension,
                "quote": item.quote,
                "summary": item.summary,
                "confidence": item.confidence,
                "source_url": item.source.url if item.source else None,
                "source_title": item.source.title if item.source else None,
                "reference_id": (
                    item.reference_id
                    if item.reference_id is not None
                    else _extract_ref_id(
                        item.source.metadata_json if item.source else None
                    )
                ),
                "source_type": item.source.source_type if item.source else "unknown",
            }
            for item in evidence_items
            if item.related_product == competitor.name
            or (item.source and item.source.competitor_id == competitor.id)
            or _normalize_comp_name(item.related_product) == comp_name_norm
        ]
        comp_dict = _competitor_to_dict(competitor)
        if qa_feedback:
            comp_dict["_qa_feedback"] = qa_feedback
        if focus_items:
            comp_dict["_focus_schema"] = [
                {
                    "key": f["key"],
                    "label": f["label"],
                    "evidence_expectation": f.get("evidence_expectation", ""),
                }
                for f in focus_items
            ]
        analysis = llm.analyze_competitor(comp_dict, comp_evidence)
        db.add(
            Analysis(
                run_id=run_id,
                competitor_id=competitor.id,
                positioning=_str(analysis.get("positioning"), ""),
                target_users=_str(analysis.get("target_users"), "[]"),
                core_features_json=_str(analysis.get("core_features_json"), "[]"),
                pricing_summary=_str(analysis.get("pricing_summary"), ""),
                strengths_json=_str(analysis.get("strengths_json"), "[]"),
                weaknesses_json=_str(analysis.get("weaknesses_json"), "[]"),
                opportunities_json=_str(analysis.get("opportunities_json"), "[]"),
                custom_focus_analysis_json=_str(
                    analysis.get("custom_focus_analysis_json"), "[]"
                ),
                evidence_ids_json=json.dumps(
                    [item["id"] for item in comp_evidence if item.get("id")],
                    ensure_ascii=False,
                ),
                analysis_iteration=next_analysis_iteration,
            )
        )
    _commit_with_retry(db)


def _fuzzy_find_competitor(
    competitor_name: str,
    competitors_by_name: dict[str, Competitor] | None,
) -> Competitor | None:
    if not competitors_by_name or not competitor_name:
        return None
    if competitor_name in competitors_by_name:
        return competitors_by_name[competitor_name]
    normalized = _normalize_comp_name(competitor_name)
    for name, comp in competitors_by_name.items():
        if _normalize_comp_name(name) == normalized:
            return comp
    from difflib import get_close_matches

    matches = get_close_matches(
        competitor_name, competitors_by_name.keys(), n=1, cutoff=0.6
    )
    if matches:
        return competitors_by_name[matches[0]]
    return None


def _str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


_STANDARD_DIMENSION_MAP = {
    "positioning": "产品定位",
    "core_features": "核心功能",
    "pricing": "价格与商业模式",
    "user_feedback": "用户评价与痛点",
    "relationship_evidence": "竞争关系",
    "market_signal": "市场信号",
    "risk_opportunity": "风险与机会",
}


def _map_to_standard_dimension(slot: str) -> str:
    return _STANDARD_DIMENSION_MAP.get(slot, slot)


def _active_focus_items(requirement: dict) -> list[dict]:
    profile = (
        requirement.get("focus_profile")
        if isinstance(requirement.get("focus_profile"), dict)
        else {}
    )
    if not isinstance(profile, dict):
        return []
    items = []
    for f in (profile.get("explicit_focuses") or []) + (
        profile.get("inferred_focuses") or []
    ):
        if isinstance(f, dict) and f.get("label"):
            items.append(f)
    return items[:6]


def _execute_revision_search_plan(
    db: Session,
    run_id: str,
    plan_items: list[dict[str, Any]],
    competitors_by_name: dict[str, Competitor] | None = None,
) -> list[Source]:
    search = get_search_provider()
    seen_urls = {
        item.url for item in db.query(Source).filter(Source.run_id == run_id).all()
    }
    next_reference_id = _next_reference_id(db, run_id)
    new_sources: list[Source] = []
    for item in plan_items:
        if not isinstance(item, dict):
            continue
        competitor_name = str(item.get("competitor_name") or "").strip()
        competitor = _fuzzy_find_competitor(competitor_name, competitors_by_name)
        purpose = str(item.get("purpose") or "补充调研").strip()
        queries = item.get("queries") or []
        if isinstance(queries, str):
            queries = [queries]
        for query in [str(q).strip() for q in queries if str(q).strip()][:3]:
            try:
                results = search.search(query, limit=3)
            except Exception:
                logger.exception("Revision search failed: %s", query)
                continue
            for result in results:
                if result.url in seen_urls:
                    continue
                if _is_low_quality_search_result(result):
                    continue
                seen_urls.add(result.url)
                source = Source(
                    run_id=run_id,
                    competitor_id=competitor.id if competitor else None,
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet,
                    source_type="revision_search",
                    provider=search.name,
                    raw_content=getattr(result, "raw_content", None),
                    reference_id=next_reference_id,
                    metadata_json=json.dumps(
                        {
                            "reference_id": next_reference_id,
                            "query": query,
                            "purpose": purpose,
                            "source_type_label": "补充调研",
                        },
                        ensure_ascii=False,
                    ),
                )
                next_reference_id += 1
                db.add(source)
                try:
                    db.flush()
                except Exception:
                    db.rollback()
                    logger.exception("Failed to flush source: %s", result.url)
                    continue
                db.add(
                    Evidence(
                        run_id=run_id,
                        source_id=source.id,
                        related_product=competitor.name
                        if competitor
                        else competitor_name,
                        related_dimension=_map_to_standard_dimension(
                            item.get("expected_evidence", purpose)
                        ),
                        quote=(result.snippet or "")[:800],
                        summary=result.snippet or "",
                        confidence=0.68,
                        reference_id=source.reference_id,
                    )
                )
                new_sources.append(source)
    db.commit()
    return new_sources


def _get_latest_qa_feedback(db: Session, run_id: str) -> str | None:
    qa = (
        db.query(QAResult)
        .filter(QAResult.run_id == run_id)
        .order_by(QAResult.iteration.desc())
        .first()
    )
    if not qa:
        return None
    retry_instructions = getattr(qa, "retry_instructions", None) or ""
    if retry_instructions:
        return retry_instructions[:500]
    try:
        issues = json.loads(qa.issues_json or "[]")
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(issues, list) or not issues:
        return None
    return "; ".join(
        str(i.get("description", ""))[:120] for i in issues[:5] if isinstance(i, dict)
    )[:500]


_LOW_QUALITY_DOMAINS = {
    "pinterest.com",
    "www.pinterest.com",
    "tiktok.com",
    "www.tiktok.com",
    "facebook.com",
    "www.facebook.com",
    "instagram.com",
    "www.instagram.com",
    "twitter.com",
    "x.com",
    "amazon.com",
    "www.amazon.com",
    "ebay.com",
    "www.ebay.com",
    "aliexpress.com",
    "www.aliexpress.com",
    "jd.com",
    "www.jd.com",
    "taobao.com",
    "www.taobao.com",
    "tmall.com",
    "www.tmall.com",
}


def _is_low_quality_search_result(result) -> bool:
    from urllib.parse import urlparse

    url = getattr(result, "url", "") or ""
    snippet = getattr(result, "snippet", "") or ""
    domain = urlparse(url).netloc.lower()
    if any(dq in domain for dq in _LOW_QUALITY_DOMAINS):
        return True
    if not snippet and not getattr(result, "raw_content", ""):
        return True
    return False


def _flatten_search_queries(search_plan: dict[str, Any]) -> list[dict[str, str]]:
    queries = []
    for item in (
        search_plan.get("search_plan", []) if isinstance(search_plan, dict) else []
    ):
        if not isinstance(item, dict):
            continue
        for query in item.get("queries", []) or []:
            queries.append(
                {
                    "competitor_name": str(item.get("competitor_name") or ""),
                    "query": str(query),
                }
            )
    return queries


def _revision_plan_summary(plan: dict[str, Any]) -> str:
    sections = plan.get("sections_to_change") if isinstance(plan, dict) else []
    if isinstance(sections, list) and sections:
        names = [
            str(item.get("section") or "相关章节")
            for item in sections
            if isinstance(item, dict)
        ]
        return "计划修改：" + "、".join(names[:4])
    return str(plan.get("final_edit_instruction") or "已生成修订计划")[:120]


def _extract_ref_id(metadata_json: str | None) -> int | None:
    if not metadata_json:
        return None
    try:
        metadata = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return None
    value = metadata.get("reference_id")
    return int(value) if isinstance(value, (int, float)) else None


def _protect_inline_citations(
    previous_markdown: str,
    next_markdown: str,
    excluded_ids: set[str] | None = None,
) -> str:
    """Avoid citation regression when a chat edit/regeneration drops inline refs."""
    from app.providers.llm.ark import _extract_citation_fingerprints, _stitch_citations

    if not next_markdown.strip():
        return previous_markdown
    previous_ids = set(re.findall(r"\[\[(\d+)\]\]", previous_markdown))
    next_ids = set(re.findall(r"\[\[(\d+)\]\]", next_markdown))
    if previous_ids.issubset(next_ids) or not previous_ids:
        return next_markdown

    missing = previous_ids - next_ids
    if excluded_ids:
        excluded_str = {str(x) for x in excluded_ids}
        missing = missing - excluded_str
    if not missing:
        return next_markdown

    fingerprints = _extract_citation_fingerprints(previous_markdown)
    missing_fingerprints = [f for f in fingerprints if str(f["id"]) in missing]
    if missing_fingerprints:
        stitched = _stitch_citations(next_markdown, missing_fingerprints)
        stitched_ids = set(re.findall(r"\[\[(\d+)\]\]", stitched))
        still_missing = missing - stitched_ids
        if not still_missing:
            return stitched
        remaining_markers = [
            f"[[{ref_id}]]" for ref_id in sorted(int(x) for x in still_missing)
        ]
        marker = "\n\n> 引用保留：" + " ".join(remaining_markers[:12])
        return stitched.rstrip() + marker

    markers = [f"[[{ref_id}]]" for ref_id in sorted(int(x) for x in missing)]
    marker = "\n\n> 引用保留：" + " ".join(markers[:12])
    return next_markdown.rstrip() + marker


def _looks_like_research_feedback(message: str) -> bool:
    return bool(
        re.search(
            r"重新|再搜|再查|搜索|调研|调查|不正确|不太对|方向|竞品找|产品定位|资料|证据|信息不足",
            message,
        )
    )


def _next_reference_id(db: Session, run_id: str) -> int:
    max_from_source = (
        db.query(func.max(Source.reference_id)).filter(Source.run_id == run_id).scalar()
    ) or 0
    max_from_evidence = (
        db.query(func.max(Evidence.reference_id))
        .filter(Evidence.run_id == run_id)
        .scalar()
    ) or 0
    max_id = max(max_from_source, max_from_evidence)
    for source in (
        db.query(Source)
        .filter(Source.run_id == run_id, Source.reference_id.is_(None))
        .all()
    ):
        ref_id = _extract_ref_id(source.metadata_json)
        if ref_id:
            max_id = max(max_id, ref_id)
            source.reference_id = ref_id
    for obj in db.new:
        if isinstance(obj, Source) and obj.run_id == run_id:
            ref_id = obj.reference_id or _extract_ref_id(obj.metadata_json)
            if ref_id:
                max_id = max(max_id, ref_id)
        elif isinstance(obj, Evidence) and obj.run_id == run_id:
            ref_id = obj.reference_id
            if ref_id:
                max_id = max(max_id, ref_id)
    return max_id + 1


def list_chat_messages(db: Session, run_id: str) -> list[ChatMessage]:
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.run_id == run_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )


def _ensure_analyses_for_all_selected(
    db: Session, run_id: str, competitors: list[Any]
) -> None:
    selected = [c for c in competitors if getattr(c, "selected", False)]
    if not selected:
        return
    selected_ids = {c.id for c in selected}
    existing_ids = {
        row[0]
        for row in db.query(Analysis.competitor_id)
        .filter(Analysis.run_id == run_id)
        .all()
    }
    missing = [c for c in selected if c.id not in existing_ids]
    if not missing:
        return
    max_iteration = (
        db.query(func.max(Analysis.analysis_iteration))
        .filter(Analysis.run_id == run_id)
        .scalar()
    )
    if max_iteration is None:
        max_iteration = 0
    logger.warning(
        "Creating stub analyses for %d competitors missing from analyses table: %s",
        len(missing),
        [c.name for c in missing],
    )
    for competitor in missing:
        db.add(
            Analysis(
                run_id=run_id,
                competitor_id=competitor.id,
                positioning=getattr(competitor, "description", "") or "待补充",
                target_users="[]",
                core_features_json="[]",
                pricing_summary="证据中未涉及",
                strengths_json="[]",
                weaknesses_json="[]",
                opportunities_json="[]",
                custom_focus_analysis_json="[]",
                evidence_ids_json="[]",
                analysis_iteration=-1,
            )
        )
    db.commit()
