import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.db.models import Analysis, Competitor, Evidence, QAResult, Report, Run, Source
from app.db.session import SessionLocal, init_db
from app.main import app
from app.schemas.qa import QAResultResponse
from app.services.chat_service import _get_run_context
from app.services.run_service import _rebuild_state_from_db


client = TestClient(app)


def test_report_citation_bundle_uses_latest_analysis_per_competitor():
    init_db()
    db = SessionLocal()
    try:
        run = Run(
            user_requirement="测试",
            status="completed",
            current_stage="completed",
            title="测试",
            requirement_summary="测试",
        )
        db.add(run)
        db.flush()
        competitor = Competitor(
            run_id=run.id,
            name="Acme",
            website="https://acme.example.com",
            description="Acme",
            category="direct_competitor",
            confidence=0.9,
            selected=True,
            discovery_source="test",
        )
        db.add(competitor)
        db.flush()
        source = Source(
            run_id=run.id,
            competitor_id=competitor.id,
            title="Acme source",
            url="https://acme.example.com/source",
            snippet="Acme source",
            source_type="official_site",
            provider="test",
            reference_id=1,
        )
        db.add(source)
        db.flush()
        evidence = Evidence(
            run_id=run.id,
            source_id=source.id,
            related_product="Acme",
            related_dimension="价格与商业模式",
            quote="Acme new pricing",
            summary="Acme new pricing summary",
            confidence=0.9,
            reference_id=1,
        )
        db.add(evidence)
        db.flush()

        old_time = datetime.utcnow() - timedelta(minutes=5)
        new_time = datetime.utcnow()
        old_analysis_id = f"ana_old_{run.id}"
        new_analysis_id = f"ana_new_{run.id}"
        db.add(
            Analysis(
                id=old_analysis_id,
                run_id=run.id,
                competitor_id=competitor.id,
                positioning="old positioning",
                target_users='["old users"]',
                core_features_json='["old features"]',
                pricing_summary="old pricing",
                strengths_json='["old strength"]',
                weaknesses_json='["old weakness"]',
                opportunities_json='["old opportunity"]',
                custom_focus_analysis_json="[]",
                evidence_ids_json=json.dumps([evidence.id], ensure_ascii=False),
                analysis_iteration=1,
                created_at=old_time,
            )
        )
        db.add(
            Analysis(
                id=new_analysis_id,
                run_id=run.id,
                competitor_id=competitor.id,
                positioning="new positioning",
                target_users='["new users"]',
                core_features_json='["new features"]',
                pricing_summary="new pricing",
                strengths_json='["new strength"]',
                weaknesses_json='["new weakness"]',
                opportunities_json='["new opportunity"]',
                custom_focus_analysis_json="[]",
                evidence_ids_json=json.dumps([evidence.id], ensure_ascii=False),
                analysis_iteration=1,
                created_at=new_time,
            )
        )
        db.add(
            Report(
                run_id=run.id,
                iteration=0,
                title="Report",
                markdown_content=(
                    "# Report\n\nAcme pricing [[1]]\n\n"
                    "## 参考来源\n\n"
                    "1. [[1]](https://acme.example.com/source)\n"
                ),
                summary="Report",
                competitor_names_json=json.dumps(["Acme"], ensure_ascii=False),
            )
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()

    bundle_response = client.get(f"/api/runs/{run_id}/report/citation-bundle")
    assert bundle_response.status_code == 200
    bundle = bundle_response.json()
    assert len(bundle) == 1
    assert bundle[0]["analysis_iteration"] == 1
    pricing_claim = next(
        claim for claim in bundle[0]["claims"] if claim["claim_type"] == "pricing"
    )
    assert pricing_claim["text"] == "new pricing"

    citations_response = client.get(f"/api/runs/{run_id}/report/citations")
    assert citations_response.status_code == 200
    citation_analyses = citations_response.json()[0]["analyses"]
    assert [item["id"] for item in citation_analyses] == [new_analysis_id]

    db = SessionLocal()
    try:
        ctx = _get_run_context(db, run_id)
        assert [analysis.id for analysis in ctx["analyses"]] == [new_analysis_id]
    finally:
        db.close()


def test_latest_analysis_prefers_quality_over_later_placeholder_in_same_iteration():
    init_db()
    db = SessionLocal()
    try:
        run = Run(
            user_requirement="测试",
            status="completed",
            current_stage="completed",
            title="测试",
            requirement_summary="测试",
        )
        db.add(run)
        db.flush()
        competitor = Competitor(
            run_id=run.id,
            name="Acme",
            website="https://acme.example.com",
            description="Acme",
            category="direct_competitor",
            confidence=0.9,
            selected=True,
            discovery_source="test",
        )
        db.add(competitor)
        db.flush()

        old_time = datetime.utcnow() - timedelta(minutes=5)
        new_time = datetime.utcnow()
        good_analysis_id = f"ana_good_{run.id}"
        placeholder_analysis_id = f"ana_placeholder_{run.id}"
        common = {
            "run_id": run.id,
            "competitor_id": competitor.id,
            "positioning": "Acme is a workflow automation product.",
            "target_users": '["Operations teams"]',
            "core_features_json": '["Automation", "Integrations"]',
            "pricing_summary": "Tiered subscription pricing.",
            "strengths_json": '["Broad integrations"]',
            "opportunities_json": '["Expand self-serve adoption"]',
            "custom_focus_analysis_json": "[]",
            "evidence_ids_json": "[]",
            "analysis_iteration": 2,
        }
        db.add(
            Analysis(
                id=good_analysis_id,
                weaknesses_json='["Complex setup"]',
                created_at=old_time,
                **common,
            )
        )
        db.add(
            Analysis(
                id=placeholder_analysis_id,
                weaknesses_json='["证据中未涉及明显劣势"]',
                created_at=new_time,
                **common,
            )
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()

    response = client.get(f"/api/runs/{run_id}/analyses")
    assert response.status_code == 200
    analyses = response.json()
    assert [item["id"] for item in analyses] == [good_analysis_id]


def test_rebuild_state_counts_full_checks_separately_from_issue_verifications():
    init_db()
    db = SessionLocal()
    try:
        run = Run(
            user_requirement="测试",
            status="running",
            current_stage="structured_analysis",
            title="测试",
            requirement_summary="测试",
        )
        db.add(run)
        db.flush()
        competitor = Competitor(
            run_id=run.id,
            name="Acme",
            website="https://acme.example.com",
            description="Acme",
            category="direct_competitor",
            confidence=0.9,
            selected=True,
            discovery_source="test",
        )
        db.add(competitor)
        db.flush()
        source = Source(
            run_id=run.id,
            competitor_id=competitor.id,
            title="Acme source",
            url="https://acme.example.com/source",
            snippet="Acme source",
            source_type="official_site",
            provider="test",
            reference_id=1,
        )
        db.add(source)
        db.flush()
        evidence = Evidence(
            run_id=run.id,
            source_id=source.id,
            related_product="Acme",
            related_dimension="核心功能",
            quote="Acme feature",
            summary="Acme feature summary",
            confidence=0.9,
            reference_id=1,
        )
        db.add(evidence)
        db.flush()
        db.add(
            Analysis(
                run_id=run.id,
                competitor_id=competitor.id,
                positioning="positioning",
                target_users='["users"]',
                core_features_json='["features"]',
                pricing_summary="pricing",
                strengths_json='["strength"]',
                weaknesses_json='["weakness"]',
                opportunities_json='["opportunity"]',
                custom_focus_analysis_json="[]",
                evidence_ids_json=json.dumps([evidence.id], ensure_ascii=False),
                analysis_iteration=2,
            )
        )
        scores = json.dumps(
            {
                "evidence_grounding": 0.8,
                "citation_accuracy": 0.8,
                "schema_completeness": 0.8,
                "coverage_gaps": 0.8,
                "cross_competitor_consistency": 0.8,
                "factual_plausibility": 0.8,
            },
            ensure_ascii=False,
        )
        for iteration, phase in [
            (1, "full_check"),
            (2, "issue_verification"),
            (3, "issue_verification"),
            (4, "full_check"),
        ]:
            db.add(
                QAResult(
                    run_id=run.id,
                    iteration=iteration,
                    overall_score=0.8,
                    decision="retry_analysis",
                    check_phase=phase,
                    dimension_scores_json=scores,
                    issues_json="[]",
                    issue_checklist_json="[]",
                    retry_queries_json="[]",
                )
            )
        db.commit()

        state = _rebuild_state_from_db(db, run)

        assert state is not None
        assert state["feedback_loop_count"] == 2
        assert state["qa_issue_verification_count"] == 0
        assert state["qa_result"]["iteration"] == 4
        assert state["qa_result"]["check_phase"] == "full_check"
    finally:
        db.close()


def test_qa_response_preserves_forced_pass_flags():
    qa = QAResult(
        id="qa_forced",
        run_id="run_forced",
        iteration=9,
        overall_score=0.56,
        decision="pass",
        check_phase="issue_verification",
        forced_pass=True,
        quality_warning=False,
        dimension_scores_json=json.dumps({"schema_completeness": 0.56}),
        issues_json="[]",
        issue_checklist_json="[]",
        retry_queries_json="[]",
        created_at=datetime.utcnow(),
    )

    response = QAResultResponse.from_db(qa)

    assert response.forced_pass is True
    assert response.quality_warning is True
