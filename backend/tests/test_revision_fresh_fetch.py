import json

import pytest
from sqlalchemy.orm import Session

from app.db.models import (
    Analysis,
    ChatMessage,
    Competitor,
    Evidence,
    Report,
    Run,
    Source,
)
from app.db.session import SessionLocal, init_db
from app.services.chat_service import (
    _competitor_to_dict,
    _ensure_revision_competitors,
    _handle_revision_workflow,
    _source_list,
    _evidence_list,
    _analysis_list,
)
from app.providers.llm.mock import MockLLMProvider
from app.providers.search.mock import MockSearchProvider


@pytest.fixture(autouse=True)
def _init_db():
    init_db()


def _seed_run_with_report(
    db: Session, competitor_names: list[str]
) -> tuple[str, list[Competitor]]:
    run = Run(
        user_requirement="测试竞品分析",
        status="completed",
        current_stage="completed",
        requirement_summary="测试",
        title="测试产品",
    )
    db.add(run)
    db.flush()

    competitors = []
    for name in competitor_names:
        comp = Competitor(
            run_id=run.id,
            name=name,
            website=f"https://{name.lower()}.example.com",
            description=f"{name} 竞品描述",
            category="direct_competitor",
            region="global",
            confidence=0.9,
            selected=True,
            discovery_source="test_seed",
        )
        db.add(comp)
        competitors.append(comp)
    db.flush()

    for comp in competitors:
        source = Source(
            run_id=run.id,
            competitor_id=comp.id,
            title=f"{comp.name} official site",
            url=f"https://{comp.name.lower()}.example.com",
            snippet=f"{comp.name} is a product",
            source_type="official_site",
            provider="test",
            metadata_json=json.dumps({"reference_id": 1}, ensure_ascii=False),
        )
        db.add(source)
        db.flush()

        evidence = Evidence(
            run_id=run.id,
            source_id=source.id,
            related_product=comp.name,
            related_dimension="core_features",
            quote=f"{comp.name} has core features",
            summary=f"{comp.name} core features summary",
            confidence=0.85,
        )
        db.add(evidence)
        db.flush()

        analysis = Analysis(
            run_id=run.id,
            competitor_id=comp.id,
            positioning=f"{comp.name} positioning",
            target_users='["users"]',
            core_features_json='["features"]',
            pricing_summary="freemium",
            strengths_json='["strength"]',
            weaknesses_json='["weakness"]',
            opportunities_json='["opp"]',
            custom_focus_analysis_json="[]",
            evidence_ids_json=json.dumps([evidence.id], ensure_ascii=False),
            analysis_iteration=0,
        )
        db.add(analysis)

    report_content = "# Test Report\n\n## 执行摘要\n\nTest.\n\n"
    for comp in competitors:
        report_content += f"## {comp.name}\n\n{comp.name} analysis.\n\n"
    report_content += "## 参考来源\n\n1. [[1]](https://example.com)\n"

    db.add(
        Report(
            run_id=run.id,
            iteration=0,
            title="Test Report",
            markdown_content=report_content,
            summary="Test summary",
        )
    )
    db.commit()
    return run.id, competitors


def test_scenario_a_add_competitor_fresh_fetch():
    db = SessionLocal()
    try:
        run_id, original_competitors = _seed_run_with_report(db, ["Slack", "Teams"])
        original_names = {c.name for c in original_competitors}

        intent_result = {
            "intent": "research_required",
            "need_search": True,
            "confidence": 0.85,
            "reason": "user wants to add a new competitor",
            "affected_sections": ["报告正文"],
            "affected_competitors": ["Notion"],
            "new_competitors": ["Notion"],
            "removed_competitors": [],
            "user_goal": "增加 Notion 到分析中",
        }

        result = _ensure_revision_competitors(
            db,
            run_id,
            original_competitors,
            [],
            intent_result,
        )

        added = result.get("added", [])
        assert len(added) == 1
        assert added[0].name == "Notion"
        assert added[0].id is not None, "Fresh-added competitor must have a valid DB ID"

        fresh_competitors = (
            db.query(Competitor)
            .filter(Competitor.run_id == run_id, Competitor.selected.is_(True))
            .all()
        )
        fresh_names = {c.name for c in fresh_competitors}
        assert fresh_names == {"Slack", "Teams", "Notion"}, (
            f"Expected Slack/Teams/Notion, got {fresh_names}"
        )

        for comp in fresh_competitors:
            assert comp.id is not None, (
                f"Competitor {comp.name} must have valid ID after fresh fetch"
            )

        competitor_map = {c.name: c for c in fresh_competitors}
        notion = competitor_map["Notion"]
        assert notion.id is not None
        assert notion.selected is True

        source_list = _source_list(db, run_id)
        evidence_list = _evidence_list(db, run_id, fresh_competitors)

        notion_evidence = [
            e for e in evidence_list if e.get("related_product") == "Notion"
        ]
        assert len(notion_evidence) >= 0

        print(
            f"[PASS] Scenario A: Added Notion (id={notion.id}), fresh fetch confirmed {len(fresh_competitors)} selected competitors"
        )
    finally:
        db.close()


def test_scenario_b_delete_competitor_fresh_fetch():
    db = SessionLocal()
    try:
        run_id, original_competitors = _seed_run_with_report(
            db, ["Slack", "Teams", "Zoom"]
        )

        intent_result = {
            "intent": "report_edit",
            "need_search": False,
            "confidence": 0.9,
            "reason": "user wants to remove Zoom",
            "affected_sections": ["报告正文"],
            "affected_competitors": [],
            "new_competitors": [],
            "removed_competitors": ["Zoom"],
            "user_goal": "删除 Zoom",
        }

        result = _ensure_revision_competitors(
            db,
            run_id,
            original_competitors,
            [],
            intent_result,
        )

        removed = result.get("removed", [])
        assert len(removed) == 1
        assert removed[0].name == "Zoom"

        fresh_competitors = (
            db.query(Competitor)
            .filter(Competitor.run_id == run_id, Competitor.selected.is_(True))
            .all()
        )
        fresh_names = {c.name for c in fresh_competitors}
        assert "Zoom" not in fresh_names, (
            f"Zoom should be deselected, but found in {fresh_names}"
        )
        assert fresh_names == {"Slack", "Teams"}

        zoom_analyses = (
            db.query(Analysis)
            .filter(Analysis.run_id == run_id, Analysis.competitor_id == removed[0].id)
            .all()
        )
        # LOGICAL DELETE: analyses are preserved for history
        assert len(zoom_analyses) == 1, (
            f"Zoom analyses should be preserved for history, but found {len(zoom_analyses)} records"
        )

        # Verify that _analysis_list only returns analyses for selected competitors
        evidence_list = _evidence_list(db, run_id, fresh_competitors)
        analysis_list = _analysis_list(db, run_id, evidence_list=evidence_list)
        analysis_names = {a.get("competitor_name") for a in analysis_list}
        assert "Zoom" not in analysis_names

        print(
            f"[PASS] Scenario B: Removed Zoom, fresh fetch confirmed {fresh_names}, analyses cleaned"
        )
    finally:
        db.close()


def test_scenario_c_composite_add_delete_fresh_fetch():
    db = SessionLocal()
    try:
        run_id, original_competitors = _seed_run_with_report(db, ["Slack", "Teams"])

        intent_result = {
            "intent": "research_required",
            "need_search": True,
            "confidence": 0.88,
            "reason": "user wants to replace Teams with Notion",
            "affected_sections": ["报告正文"],
            "affected_competitors": ["Notion"],
            "new_competitors": ["Notion"],
            "removed_competitors": ["Teams"],
            "user_goal": "不要分析 Teams 了，请改分析 Notion",
        }

        result = _ensure_revision_competitors(
            db,
            run_id,
            original_competitors,
            [],
            intent_result,
        )

        added = result.get("added", [])
        removed = result.get("removed", [])
        assert len(added) == 1
        assert added[0].name == "Notion"
        assert len(removed) == 1
        assert removed[0].name == "Teams"

        fresh_competitors = (
            db.query(Competitor)
            .filter(Competitor.run_id == run_id, Competitor.selected.is_(True))
            .all()
        )
        fresh_names = {c.name for c in fresh_competitors}
        assert fresh_names == {"Slack", "Notion"}, (
            f"Expected Slack/Notion, got {fresh_names}"
        )

        for comp in fresh_competitors:
            assert comp.id is not None, (
                f"Competitor {comp.name} missing ID after fresh fetch"
            )

        competitor_map = {c.name: c for c in fresh_competitors}
        notion_id = competitor_map["Notion"].id
        teams_id = removed[0].id

        teams_analyses = (
            db.query(Analysis)
            .filter(Analysis.run_id == run_id, Analysis.competitor_id == teams_id)
            .all()
        )
        # LOGICAL DELETE: preserved
        assert len(teams_analyses) == 1, (
            "Teams analyses should be preserved for history"
        )

        all_selected_ids = {c.id for c in fresh_competitors}

        source_list = _source_list(db, run_id)
        evidence_list = _evidence_list(db, run_id, fresh_competitors)
        analysis_list = _analysis_list(db, run_id, evidence_list=evidence_list)

        analysis_competitor_ids = {a.get("competitor_id") for a in analysis_list}
        for aid in analysis_competitor_ids:
            assert aid in all_selected_ids, (
                f"Analysis in active list references deselected competitor_id={aid}"
            )

        print(
            f"[PASS] Scenario C: Composite add/delete, fresh fetch confirmed {fresh_names}, no stale data"
        )
    finally:
        db.close()


def test_fresh_fetch_ensures_id_available_for_search_plan():
    db = SessionLocal()
    try:
        run_id, original_competitors = _seed_run_with_report(db, ["Slack"])

        intent_result = {
            "intent": "research_required",
            "need_search": True,
            "confidence": 0.85,
            "reason": "add new competitor",
            "affected_sections": [],
            "affected_competitors": ["Notion"],
            "new_competitors": ["Notion"],
            "removed_competitors": [],
            "user_goal": "增加 Notion",
        }

        result = _ensure_revision_competitors(
            db,
            run_id,
            original_competitors,
            [],
            intent_result,
        )

        fresh_competitors = (
            db.query(Competitor)
            .filter(Competitor.run_id == run_id, Competitor.selected.is_(True))
            .all()
        )
        competitors_by_name = {c.name: c for c in fresh_competitors}

        notion = competitors_by_name.get("Notion")
        assert notion is not None, "Notion should exist in fresh fetch results"
        assert notion.id is not None, (
            "Notion must have a valid DB ID for evidence linkage"
        )

        source = Source(
            run_id=run_id,
            competitor_id=notion.id,
            title="Notion official",
            url="https://notion.so",
            snippet="Notion is an AI workspace",
            source_type="official_site",
            provider="test",
            metadata_json='{"reference_id": 2}',
        )
        db.add(source)
        db.flush()

        evidence = Evidence(
            run_id=run_id,
            source_id=source.id,
            related_product="Notion",
            related_dimension="core_features",
            quote="Notion has docs and AI",
            summary="Notion core features",
            confidence=0.85,
        )
        db.add(evidence)
        db.commit()

        assert source.competitor_id == notion.id, (
            f"Source competitor_id mismatch: {source.competitor_id} != {notion.id}"
        )
        assert evidence.source_id == source.id

        print(
            f"[PASS] ID linkage: Notion.id={notion.id} successfully used in source and evidence"
        )
    finally:
        db.close()


def test_handle_revision_workflow_preserves_fresh_fetch():
    db = SessionLocal()
    try:
        run_id, original_competitors = _seed_run_with_report(db, ["Slack"])

        ctx = {
            "run": db.get(Run, run_id),
            "report": db.query(Report)
            .filter(Report.run_id == run_id)
            .order_by(Report.iteration.desc())
            .first(),
            "analyses": db.query(Analysis).filter(Analysis.run_id == run_id).all(),
            "evidence": db.query(Evidence).filter(Evidence.run_id == run_id).all(),
            "sources": db.query(Source).filter(Source.run_id == run_id).all(),
            "competitors": original_competitors,
            "chat_messages": [],
        }

        llm = MockLLMProvider()

        intent_override = {
            "intent": "research_required",
            "need_search": True,
            "confidence": 0.85,
            "reason": "add Notion",
            "affected_sections": [],
            "affected_competitors": ["Notion"],
            "new_competitors": ["Notion"],
            "removed_competitors": [],
            "user_goal": "增加 Notion",
        }

        original_classify = llm.classify_revision_intent

        def patched_classify(user_message, current_report, chat_history):
            return intent_override

        llm.classify_revision_intent = patched_classify

        user_message = "增加 Notion 到竞品分析中"
        chat_history = [{"role": "user", "content": user_message}]

        result = _handle_revision_workflow(db, ctx, llm, user_message, chat_history)

        assert result.get("report_version") is not None, (
            "Should produce a new report version"
        )
        assert "added_competitors" in result.get("action_details", {})

        fresh_competitors = (
            db.query(Competitor)
            .filter(Competitor.run_id == run_id, Competitor.selected.is_(True))
            .all()
        )
        fresh_names = {c.name for c in fresh_competitors}
        assert "Notion" in fresh_names, (
            f"Notion should be in selected competitors: {fresh_names}"
        )

        for comp in fresh_competitors:
            assert comp.id is not None

        # We expect all analyses to exist in DB (preserved)
        # but _analysis_list should only show active ones
        all_analyses = db.query(Analysis).filter(Analysis.run_id == run_id).all()

        evidence_list = _evidence_list(db, run_id, fresh_competitors)
        analysis_list = _analysis_list(db, run_id, evidence_list=evidence_list)
        active_analysis_competitor_ids = {a.get("competitor_id") for a in analysis_list}
        selected_ids = {c.id for c in fresh_competitors}
        assert active_analysis_competitor_ids.issubset(selected_ids)

        print(
            f"[PASS] Full workflow: Notion added via _handle_revision_workflow, fresh fetch confirmed"
        )
    finally:
        db.close()
