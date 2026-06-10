import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agents.nodes.material_collection import material_collection_node
from app.db.models import Evidence, KnowledgeItem, Run, Source
from app.db.session import SessionLocal, init_db
from app.main import app
from app.services.knowledge_service import upsert_from_evidence

client = TestClient(app)


def test_upsert_from_evidence_and_search_route():
    init_db()
    suffix = uuid4().hex[:8]
    source_url = f"https://example.com/slack-docs-knowledge-{suffix}"
    quote = f"Slack docs cover workflow automation, apps, APIs and integrations. {suffix}"
    db = SessionLocal()
    try:
        run = Run(
            user_requirement="沉淀 Slack 知识",
            status="completed",
            current_stage="completed",
        )
        db.add(run)
        db.flush()
        source = Source(
            run_id=run.id,
            title="Slack docs",
            url=source_url,
            snippet="Slack docs cover workflow automation and integrations.",
            source_type="official_docs",
            provider="test",
            metadata_json=json.dumps(
                {"source_type_label": "官方文档/帮助中心"}, ensure_ascii=False
            ),
        )
        db.add(source)
        db.flush()
        evidence = Evidence(
            run_id=run.id,
            source_id=source.id,
            related_product="Slack",
            related_dimension="核心功能",
            quote=quote,
            summary="Slack 支持工作流自动化、应用、API 和集成。",
            confidence=0.9,
        )
        db.add(evidence)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    db = SessionLocal()
    try:
        result = upsert_from_evidence(db, run_id)
        assert result.created_count == 1
        assert result.updated_count == 0

        second_result = upsert_from_evidence(db, run_id)
        assert second_result.created_count == 0
        assert second_result.updated_count == 1
    finally:
        db.close()

    response = client.get(
        "/api/knowledge/items",
        params={"q": "workflow automation", "product_name": "Slack"},
    )
    assert response.status_code == 200
    items = response.json()
    assert any(item["product_name"] == "Slack" for item in items)
    assert any(item["source_url"] == source_url for item in items)

    rebuild_response = client.post(f"/api/knowledge/rebuild-from-run/{run_id}")
    assert rebuild_response.status_code == 200
    assert rebuild_response.json()["run_id"] == run_id


def test_upsert_skips_custom_focus_evidence():
    init_db()
    suffix = uuid4().hex[:8]
    db = SessionLocal()
    try:
        run = Run(
            user_requirement="沉淀时跳过个性化关注点",
            status="completed",
            current_stage="completed",
        )
        db.add(run)
        db.flush()
        source = Source(
            run_id=run.id,
            title="Slack source",
            url=f"https://example.com/slack-focus-{suffix}",
            snippet="Slack source snippet.",
            source_type="official_docs",
            provider="test",
        )
        db.add(source)
        db.flush()
        db.add_all(
            [
                Evidence(
                    run_id=run.id,
                    source_id=source.id,
                    related_product="Slack",
                    related_dimension="核心功能",
                    quote=f"Slack supports integrations. {suffix}",
                    summary="Slack 支持集成。",
                    confidence=0.9,
                ),
                Evidence(
                    run_id=run.id,
                    source_id=source.id,
                    related_product="Slack",
                    related_dimension="个性化关注点：本地存储与隐私",
                    quote=f"Slack custom focus privacy note. {suffix}",
                    summary="个性化关注点证据不应沉淀。",
                    confidence=0.95,
                ),
            ]
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()

    db = SessionLocal()
    try:
        result = upsert_from_evidence(db, run_id)
        assert result.created_count == 1
        assert result.skipped_count == 1
        dimensions = [
            item.dimension
            for item in db.query(KnowledgeItem).filter(KnowledgeItem.run_id == run_id)
        ]
        assert dimensions == ["核心功能"]
    finally:
        db.close()


def test_clear_knowledge_items_route_deletes_only_knowledge_items():
    init_db()
    db = SessionLocal()
    try:
        run = Run(
            user_requirement="清空知识库",
            status="completed",
            current_stage="completed",
        )
        db.add(run)
        db.flush()
        db.add(
            KnowledgeItem(
                product_name="Slack",
                dimension="核心功能",
                claim="Slack supports integrations.",
                summary="Slack 支持集成。",
                confidence=0.9,
                source_type="official_docs",
                run_id=run.id,
            )
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()

    response = client.delete("/api/knowledge/items")
    assert response.status_code == 200
    assert response.json()["deleted_count"] >= 1

    db = SessionLocal()
    try:
        assert db.query(KnowledgeItem).count() == 0
        assert db.get(Run, run_id) is not None
    finally:
        db.close()


def test_material_collection_injects_knowledge_items_before_search():
    init_db()
    db = SessionLocal()
    try:
        previous_run = Run(
            user_requirement="历史 Slack 分析",
            status="completed",
            current_stage="completed",
        )
        current_run = Run(
            user_requirement="分析 Slack 竞品",
            status="running",
            current_stage="material_collection",
        )
        db.add_all([previous_run, current_run])
        db.flush()
        db.add(
            KnowledgeItem(
                product_name="Slack",
                dimension="核心功能",
                claim="Slack supports workflow automation, apps, APIs and integrations.",
                summary="Slack 支持工作流自动化、应用、API 和集成。",
                confidence=0.9,
                source_type="official_docs",
                source_title="Slack docs",
                source_url="https://example.com/slack-docs-material",
                run_id=previous_run.id,
                metadata_json="{}",
            )
        )
        db.commit()
        current_run_id = current_run.id
    finally:
        db.close()

    progress_events = []

    class EmptySearchProvider:
        name = "empty"

        def search(self, query: str, *, limit: int = 5, include_raw_content: bool = True):
            return []

    state = {
        "run_id": current_run_id,
        "requirement": {"query": "Slack 竞品 功能 对比", "domain": "团队协作"},
        "selected_competitors": [
            {
                "id": "comp_slack_knowledge",
                "name": "Slack",
                "website": "https://slack.com",
                "description": "团队协作工具",
                "category": "direct_competitor",
                "confidence": 1.0,
            }
        ],
        "sources": [],
        "evidence": [],
    }
    result = material_collection_node(
        state,
        EmptySearchProvider(),
        progress=lambda stage, message, metadata: progress_events.append(
            (stage, message, metadata)
        ),
    )

    assert any(event[0] == "knowledge_retrieval" for event in progress_events)
    assert any(source["provider"] == "knowledge_base" for source in result["sources"])
    assert any(
        item["source_url"] == "https://example.com/slack-docs-material"
        for item in result["evidence"]
    )
