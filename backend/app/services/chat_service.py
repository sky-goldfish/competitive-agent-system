import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

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
from app.providers.llm.factory import get_llm_provider
from app.providers.search.factory import get_search_provider

logger = logging.getLogger(__name__)


class ChatError(ValueError):
    pass


def _get_run_context(db: Session, run_id: str) -> dict[str, Any]:
    run = db.get(Run, run_id)
    if run is None:
        raise ChatError(f"Run not found: {run_id}")
    if run.status != "completed":
        raise ChatError(
            f"Run is not completed (status={run.status})，无法进行对话修改。"
        )

    latest_report = (
        db.query(Report)
        .filter(Report.run_id == run_id)
        .order_by(Report.iteration.desc())
        .first()
    )
    if latest_report is None:
        raise ChatError("Report not found.")

    analyses = db.query(Analysis).filter(Analysis.run_id == run_id).all()
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

    return {
        "run": run,
        "report": latest_report,
        "analyses": analyses,
        "evidence": evidence_items,
        "sources": sources,
        "competitors": competitors,
        "chat_messages": chat_messages,
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
        )
        db.add(user_msg)
        db.commit()

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
        db.commit()
        db.refresh(assistant_msg)

        return {
            "message": assistant_msg,
            "report_version": result.get("report_version"),
            "intent": intent,
            "action_type": result.get("action_type", intent),
        }
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
            f"竞品 {comp_name}: 定位={analysis.positioning[:100]}, "
            f"价格={analysis.pricing_summary[:100]}"
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
        or 0
    )
    new_report = Report(
        run_id=report.run_id,
        iteration=max_iteration + 1,
        title=report.title,
        markdown_content=new_markdown,
        summary=report.summary,
    )
    db.add(new_report)
    db.commit()
    db.refresh(new_report)

    return {
        "reply": f"已根据你的反馈修改报告（版本 {new_report.iteration}）。你可以查看更新后的报告，或继续提出修改意见。",
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
            {"title": "保存新版本", "detail": f"生成报告版本 {new_report.iteration}。"},
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
    source_list = _source_list(db, report.run_id)
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
    )
    workflow_steps = [
        {
            "title": "判断修改类型",
            "detail": "需要补充调研" if need_search else "报告细节修改，不需要新增资料",
        }
    ]

    search_plan: dict[str, Any] = {}
    new_sources: list[Source] = []
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
        new_sources = _execute_revision_search_plan(db, report.run_id, plan_items or [])
        workflow_steps.append(
            {
                "title": "收集新资料",
                "detail": f"新增 {len(new_sources)} 条公开来源。",
            }
        )

    source_list = _source_list(db, report.run_id)
    evidence_list = _evidence_list(db, report.run_id, competitors)
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
    new_report = llm.revise_report_with_plan(
        current_report,
        revision_plan,
        citation_bundle,
        source_list,
    )
    markdown_content = _protect_inline_citations(
        report.markdown_content, new_report.get("markdown_content", "")
    )
    markdown_content = _append_new_source_citations(markdown_content, new_sources)
    new_report["markdown_content"] = markdown_content

    max_iteration = (
        db.query(func.max(Report.iteration))
        .filter(Report.run_id == report.run_id)
        .scalar()
        or 0
    )
    new_report_record = Report(
        run_id=report.run_id,
        iteration=max_iteration + 1,
        title=new_report.get("title", report.title),
        markdown_content=markdown_content,
        summary=new_report.get("summary", report.summary),
    )
    db.add(new_report_record)
    db.commit()
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
            "detail": f"已保存为版本 {new_report_record.iteration}。",
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
            source = Source(
                run_id=report.run_id,
                title=result.title,
                url=result.url,
                snippet=result.snippet,
                source_type="unknown",
                provider=search.name,
                metadata_json=json.dumps(
                    {"reference_id": next_reference_id}, ensure_ascii=False
                ),
            )
            next_reference_id += 1
            db.add(source)
            db.flush()
            new_sources.append(source)

            competitor = next((c for c in competitors if c.name == comp_name), None)
            evidence = Evidence(
                run_id=report.run_id,
                source_id=source.id,
                related_product=comp_name,
                related_dimension=rq.get("slot", "core_features"),
                quote=(result.snippet or "")[:800],
                summary=result.snippet or "",
                confidence=0.65,
            )
            db.add(evidence)
            db.flush()
            new_evidence.append(evidence)

    db.commit()

    analyses = ctx["analyses"]
    evidence_items = db.query(Evidence).filter(Evidence.run_id == report.run_id).all()

    affected_comp_names = {rq.get("competitor_name") for rq in retry_queries}
    affected_competitor_ids = {
        c.id for c in competitors if c.name in affected_comp_names
    }

    if affected_competitor_ids and analyses:
        db.query(Analysis).filter(
            Analysis.run_id == report.run_id,
            Analysis.competitor_id.in_(affected_competitor_ids),
        ).delete(synchronize_session=False)
        db.commit()

    analyses = db.query(Analysis).filter(Analysis.run_id == report.run_id).all()

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
                "reference_id": _extract_ref_id(
                    e.source.metadata_json if e.source else None
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
                positioning=analysis.get("positioning", ""),
                target_users=analysis.get("target_users", "[]"),
                core_features_json=analysis.get("core_features_json", "[]"),
                pricing_summary=analysis.get("pricing_summary", ""),
                strengths_json=analysis.get("strengths_json", "[]"),
                weaknesses_json=analysis.get("weaknesses_json", "[]"),
                opportunities_json=analysis.get("opportunities_json", "[]"),
                custom_focus_analysis_json=analysis.get(
                    "custom_focus_analysis_json", "[]"
                ),
                evidence_ids_json=json.dumps(
                    [e["id"] for e in comp_evidence if e.get("id")],
                    ensure_ascii=False,
                ),
                analysis_iteration=report.iteration + 1,
            )
        )
    db.commit()

    analyses = db.query(Analysis).filter(Analysis.run_id == report.run_id).all()
    sources = db.query(Source).filter(Source.run_id == report.run_id).all()

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
            "custom_focus_analysis_json": a.custom_focus_analysis_json,
            "evidence_ids_json": a.evidence_ids_json,
        }
        for a in analyses
    ]
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
            "reference_id": _extract_ref_id(s.metadata_json),
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
            "quote": e.quote,
            "summary": e.summary,
            "confidence": e.confidence,
            "source_url": e.source.url if e.source else None,
            "source_title": e.source.title if e.source else None,
            "reference_id": _extract_ref_id(
                e.source.metadata_json if e.source else None
            ),
            "source_type": e.source.source_type if e.source else "unknown",
        }
        for e in db.query(Evidence).filter(Evidence.run_id == report.run_id).all()
    ]
    citation_bundle = _build_citation_bundle(analysis_list, evidence_list)

    new_report = llm.generate_report(
        {
            "title": report.title,
            "user_requirement": ctx["run"].user_requirement,
            "requirement_summary": ctx["run"].requirement_summary,
            "qa_report_guidance": retry_instructions,
            "citation_bundle": citation_bundle,
        },
        analysis_list,
        source_list,
    )

    max_iteration = (
        db.query(func.max(Report.iteration))
        .filter(Report.run_id == report.run_id)
        .scalar()
        or 0
    )
    markdown_content = _protect_inline_citations(
        report.markdown_content, new_report.get("markdown_content", "")
    )
    markdown_content = _append_new_source_citations(markdown_content, new_sources)
    new_report_record = Report(
        run_id=report.run_id,
        iteration=max_iteration + 1,
        title=new_report.get("title", report.title),
        markdown_content=markdown_content,
        summary=new_report.get("summary", report.summary),
    )
    db.add(new_report_record)
    db.commit()
    db.refresh(new_report_record)

    return {
        "reply": (
            f"已根据你的反馈重新调研并生成报告（版本 {new_report_record.iteration}）。\n"
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
                "detail": f"生成报告版本 {new_report_record.iteration}。",
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
    return {
        "id": source.id,
        "competitor_id": source.competitor_id,
        "title": source.title,
        "url": source.url,
        "snippet": source.snippet,
        "source_type": source.source_type,
        "provider": source.provider,
        "raw_content": source.raw_content,
        "reference_id": _extract_ref_id(source.metadata_json),
        "metadata_json": source.metadata_json,
    }


def _source_list(db: Session, run_id: str) -> list[dict[str, Any]]:
    return [
        _source_to_dict(item)
        for item in db.query(Source).filter(Source.run_id == run_id).all()
    ]


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
    items = db.query(Evidence).filter(Evidence.run_id == run_id).all()
    return [
        {
            "id": item.id,
            "competitor_id": item.source.competitor_id
            if item.source and item.source.competitor_id
            else by_name.get(item.related_product),
            "related_product": item.related_product,
            "related_dimension": item.related_dimension,
            "quote": item.quote,
            "summary": item.summary,
            "confidence": item.confidence,
            "source_url": item.source.url if item.source else None,
            "source_title": item.source.title if item.source else None,
            "reference_id": _extract_ref_id(
                item.source.metadata_json if item.source else None
            ),
            "source_type": item.source.source_type if item.source else "unknown",
        }
        for item in items
    ]


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

    analyses = db.query(Analysis).filter(Analysis.run_id == run_id).all()
    result = []
    for item in analyses:
        evidence_ids = _json_list(item.evidence_ids_json)
        merged_ids = list(
            dict.fromkeys(
                evidence_ids + evidence_by_competitor.get(item.competitor_id, [])
            )
        )
        result.append(
            {
                "id": item.id,
                "competitor_id": item.competitor_id,
                "competitor_name": item.competitor.name if item.competitor else "",
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


def _execute_revision_search_plan(
    db: Session,
    run_id: str,
    plan_items: list[dict[str, Any]],
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
                seen_urls.add(result.url)
                source = Source(
                    run_id=run_id,
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet,
                    source_type="revision_search",
                    provider=search.name,
                    raw_content=getattr(result, "raw_content", None),
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
                db.flush()
                db.add(
                    Evidence(
                        run_id=run_id,
                        source_id=source.id,
                        related_product=competitor_name,
                        related_dimension=purpose,
                        quote=(result.snippet or "")[:800],
                        summary=result.snippet or "",
                        confidence=0.68,
                    )
                )
                new_sources.append(source)
    db.commit()
    return new_sources


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


def _protect_inline_citations(previous_markdown: str, next_markdown: str) -> str:
    """Avoid citation regression when a chat edit/regeneration drops inline refs."""
    if not next_markdown.strip():
        return previous_markdown
    previous_refs = re.findall(
        r"\[\[(\d+)\]\]\((https?://[^)\s]+)\)", previous_markdown
    )
    next_refs = re.findall(r"\[\[(\d+)\]\]\((https?://[^)\s]+)\)", next_markdown)
    if len(next_refs) >= len(previous_refs) or not previous_refs:
        return next_markdown

    missing = []
    existing_ids = {ref_id for ref_id, _ in next_refs}
    for ref_id, url in previous_refs:
        if ref_id not in existing_ids:
            missing.append(f"[[{ref_id}]]({url})")
            existing_ids.add(ref_id)
    if not missing:
        return next_markdown

    marker = "\n\n> 引用保留：" + " ".join(missing[:12])
    return next_markdown.rstrip() + marker


def _append_new_source_citations(markdown: str, new_sources: list[Source]) -> str:
    refs = []
    existing = set(re.findall(r"\[\[(\d+)\]\]", markdown))
    for source in new_sources:
        ref_id = _extract_ref_id(source.metadata_json)
        if not ref_id or str(ref_id) in existing or not source.url:
            continue
        refs.append(f"[[{ref_id}]]({source.url})")
        existing.add(str(ref_id))
    if not refs:
        return markdown
    block = (
        "\n\n### 补充调研依据\n\n本轮补充调研新增了以下来源支撑："
        + " ".join(refs[:10])
        + "\n"
    )
    pattern = r"\n##\s*(?:(?:\d+|[一二三四五六七八九十]+)[\.、]\s*)?(?:参考来源|参考文献|References)\s*\n"
    match = re.search(pattern, markdown)
    if match:
        return markdown[: match.start()] + block + markdown[match.start() :]
    return markdown.rstrip() + block


def _looks_like_research_feedback(message: str) -> bool:
    return bool(
        re.search(
            r"重新|再搜|再查|搜索|调研|调查|不正确|不太对|方向|竞品找|产品定位|资料|证据|信息不足",
            message,
        )
    )


def _next_reference_id(db: Session, run_id: str) -> int:
    sources = db.query(Source).filter(Source.run_id == run_id).all()
    max_id = 0
    for source in sources:
        ref_id = _extract_ref_id(source.metadata_json)
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
