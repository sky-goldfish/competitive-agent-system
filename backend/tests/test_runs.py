import json

import pytest
from fastapi.testclient import TestClient

import app.services.run_service as run_service
from app.db.models import Report, Run, Source
from app.db.session import SessionLocal, init_db
from app.main import app
from app.providers.llm.mock import MockLLMProvider
from app.providers.search.mock import MockSearchProvider
from app.services.run_service import _report_record_fields


client = TestClient(app)


@pytest.fixture(autouse=True)
def use_stable_mock_providers(monkeypatch):
    monkeypatch.setattr(run_service, "get_llm_provider", MockLLMProvider)
    monkeypatch.setattr(run_service, "get_search_provider", MockSearchProvider)


def _wait_for_status(run_id: str, expected: str, *, attempts: int = 20):
    for _ in range(attempts):
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        if run["status"] == expected:
            return run
        if run["status"] == "failed":
            raise AssertionError(run.get("error_message") or "run failed")
    raise AssertionError(
        f"Run {run_id} did not reach {expected}. Current status: {run['status']}"
    )


def test_report_record_fields_drops_runtime_metadata():
    fields = _report_record_fields(
        {
            "title": "Report",
            "markdown_content": "# Report",
            "summary": "Summary",
            "field_evidence_ids": {"weaknesses_json": ["ev_1"]},
            "citation_bundle": [],
        }
    )

    assert fields == {
        "title": "Report",
        "markdown_content": "# Report",
        "summary": "Summary",
    }


def test_run_lifecycle():
    init_db()
    create_response = client.post(
        "/api/runs",
        json={"user_requirement": "我想分析 AI 会议纪要工具的竞品，侧重功能对比"},
    )
    assert create_response.status_code == 201
    run = create_response.json()
    assert run["status"] == "running"
    run = _wait_for_status(run["id"], "waiting_for_human")

    competitors_response = client.get(f"/api/runs/{run['id']}/competitors")
    assert competitors_response.status_code == 200
    competitors = competitors_response.json()
    assert len(competitors) >= 2
    assert any(item["region"] in {"global", "china"} for item in competitors)

    selected_ids = [item["id"] for item in competitors[:2]]
    confirm_response = client.post(
        f"/api/runs/{run['id']}/competitors/confirm",
        json={
            "competitor_ids": selected_ids,
            "custom_competitors": [
                {
                    "name": "自定义竞品",
                    "website": "https://example.com",
                    "category": "adjacent_product",
                }
            ],
        },
    )
    assert confirm_response.status_code == 200
    confirmed_run = confirm_response.json()
    assert confirmed_run["status"] == "running"
    completed_run = _wait_for_status(run["id"], "completed")
    assert completed_run["status"] == "completed"

    report_response = client.get(f"/api/runs/{run['id']}/report")
    assert report_response.status_code == 200
    assert "#" in report_response.json()["markdown_content"]
    citations_response = client.get(f"/api/runs/{run['id']}/report/citations")
    assert citations_response.status_code == 200
    citations = citations_response.json()
    assert len(citations) > 0
    assert citations[0]["source"]["id"]
    assert citations[0]["evidence"]

    sources_response = client.get(f"/api/runs/{run['id']}/sources")
    assert sources_response.status_code == 200
    sources = sources_response.json()
    assert len(sources) > 0
    assert all(source["source_type_label"] for source in sources)
    assert all(source["credibility_score"] is not None for source in sources)
    assert any(source["classification_reason"] for source in sources)
    assert len({(source["competitor_id"], source["url"]) for source in sources}) == len(
        sources
    )
    evidence_response = client.get(f"/api/runs/{run['id']}/evidence")
    assert evidence_response.status_code == 200
    evidence_items = evidence_response.json()
    assert len(evidence_items) > 0
    source_ids = {source["id"] for source in sources}
    assert {item["source_id"] for item in evidence_items}.issubset(source_ids)

    analyses_response = client.get(f"/api/runs/{run['id']}/analyses")
    assert analyses_response.status_code == 200
    evidence_ids = {item["id"] for item in evidence_items}
    for analysis in analyses_response.json():
        linked_evidence_ids = set(json.loads(analysis["evidence_ids_json"]))
        assert linked_evidence_ids
        assert linked_evidence_ids.issubset(evidence_ids)

    confirmed_competitors = client.get(f"/api/runs/{run['id']}/competitors").json()
    assert "自定义竞品" in {item["name"] for item in confirmed_competitors}

    timeline_response = client.get(f"/api/runs/{run['id']}/timeline")
    assert timeline_response.status_code == 200
    stages = {item["stage"] for item in timeline_response.json()}
    assert {
        "requirement_understanding",
        "competitor_discovery",
        "human_confirm_competitors",
        "material_collection",
        "structured_analysis",
        "report_generation",
    }.issubset(stages)
    assert {
        "quart_planning",
        "material_query_planning",
        "source_search",
        "source_classification",
        "evidence_extraction",
        "coverage_checking",
    }.issubset(stages)


def test_report_citations_follow_selected_report_iteration():
    init_db()
    db = SessionLocal()
    try:
        run = Run(
            user_requirement="验证报告版本引用",
            status="completed",
            current_stage="completed",
        )
        db.add(run)
        db.flush()

        first_source = Source(
            run_id=run.id,
            title="First version source",
            url="https://example.com/report-version-0",
            snippet="First version source snippet",
            source_type="official_site",
            provider="test",
            metadata_json='{"reference_id": 1}',
        )
        latest_source = Source(
            run_id=run.id,
            title="Latest version source",
            url="https://example.com/report-version-1",
            snippet="Latest version source snippet",
            source_type="official_site",
            provider="test",
            metadata_json='{"reference_id": 1}',
        )
        db.add_all([first_source, latest_source])
        db.flush()

        db.add_all(
            [
                Report(
                    run_id=run.id,
                    iteration=0,
                    title="First report",
                    summary="First report summary",
                    markdown_content=(
                        "# First report\n\n"
                        "First conclusion [[1]](https://example.com/report-version-0).\n\n"
                        "## 参考来源\n\n"
                        "1. [[1]](https://example.com/report-version-0) [First version source](https://example.com/report-version-0)"
                    ),
                ),
                Report(
                    run_id=run.id,
                    iteration=1,
                    title="Latest report",
                    summary="Latest report summary",
                    markdown_content=(
                        "# Latest report\n\n"
                        "Latest conclusion [[1]](https://example.com/report-version-1).\n\n"
                        "## 参考来源\n\n"
                        "1. [[1]](https://example.com/report-version-1) [Latest version source](https://example.com/report-version-1)"
                    ),
                ),
            ]
        )
        db.commit()
        run_id = run.id
        first_source_id = first_source.id
        latest_source_id = latest_source.id
    finally:
        db.close()

    latest_report = client.get(f"/api/runs/{run_id}/report")
    latest_citations = client.get(f"/api/runs/{run_id}/report/citations")
    first_report = client.get(f"/api/runs/{run_id}/report?iteration=0")
    first_citations = client.get(f"/api/runs/{run_id}/report/citations?iteration=0")
    missing_citations = client.get(f"/api/runs/{run_id}/report/citations?iteration=99")

    assert latest_report.status_code == 200
    assert latest_report.json()["iteration"] == 1
    assert latest_citations.status_code == 200
    assert [item["source"]["id"] for item in latest_citations.json()] == [
        latest_source_id
    ]

    assert first_report.status_code == 200
    assert first_report.json()["iteration"] == 0
    assert first_citations.status_code == 200
    assert [item["source"]["id"] for item in first_citations.json()] == [
        first_source_id
    ]

    assert missing_citations.status_code == 404


def test_confirm_rejects_competitor_ids_from_other_runs():
    init_db()
    first_response = client.post(
        "/api/runs", json={"user_requirement": "我想分析飞书的竞品，侧重功能"}
    )
    second_response = client.post(
        "/api/runs",
        json={"user_requirement": "我想分析 AI 会议纪要工具的竞品，侧重功能"},
    )
    assert first_response.status_code == 201
    assert second_response.status_code == 201
    first_run = _wait_for_status(first_response.json()["id"], "waiting_for_human")
    second_run = _wait_for_status(second_response.json()["id"], "waiting_for_human")

    second_competitors = client.get(f"/api/runs/{second_run['id']}/competitors").json()
    assert second_competitors
    confirm_response = client.post(
        f"/api/runs/{first_run['id']}/competitors/confirm",
        json={
            "competitor_ids": [second_competitors[0]["id"]],
            "custom_competitors": [],
        },
    )

    assert confirm_response.status_code == 400
    assert "do not belong to this run" in confirm_response.text


def test_material_source_classification_supports_domain_weights():
    from app.agents.nodes.material_collection import _classify_source

    commodity_requirement = {"domain": "智能保温杯与办公水杯"}
    assert _classify_source(
        "https://item.jd.com/100.html",
        "Ember Mug 京东商品页",
        "价格 参数",
        commodity_requirement,
        "价格与商业模式",
    )[:2] == ("ecommerce_product_page", 0.86)
    assert _classify_source(
        "https://www.xiaohongshu.com/explore/1",
        "Ember Mug 使用体验",
        "用户评价",
        commodity_requirement,
        "用户评价与痛点",
    )[:2] == ("social_review_post", 0.66)
    assert _classify_source(
        "https://www.zhihu.com/question/1",
        "智能杯值得买吗",
        "讨论",
        commodity_requirement,
        "用户评价与痛点",
    )[:2] == ("community_discussion", 0.62)

    saas_requirement = {"domain": "企业协作办公平台"}
    assert _classify_source(
        "https://slack.com/pricing",
        "Slack Pricing",
        "plans",
        saas_requirement,
        "价格与商业模式",
    )[:2] == ("official_pricing_page", 0.93)
    assert _classify_source(
        "https://www.g2.com/products/slack/reviews",
        "Slack Reviews",
        "pros cons",
        saas_requirement,
        "用户评价与痛点",
    )[:2] == ("review_site", 0.72)


def test_retrieval_quart_planner_uses_software_and_commodity_rules():
    from app.agents.nodes.material_collection import (
        _detect_product_type,
        _plan_retrieval_quarts,
    )

    software_requirement = {"domain": "企业协作办公平台", "summary": "分析飞书竞品"}
    commodity_requirement = {
        "domain": "智能保温杯",
        "summary": "分析办公室智能保温杯竞品",
    }
    competitors = [
        {
            "id": "comp_global",
            "name": "Slack",
            "category": "direct_competitor",
            "region": "global",
        },
        {
            "id": "comp_china",
            "name": "钉钉",
            "category": "direct_competitor",
            "region": "china",
        },
    ]

    assert _detect_product_type(software_requirement) == "software"
    assert _detect_product_type(commodity_requirement) == "commodity"

    software_quarts = _plan_retrieval_quarts(competitors, software_requirement)
    assert {quart["product_type"] for quart in software_quarts} == {"software"}
    assert any(
        quart["target_slot"] == "relationship_evidence" for quart in software_quarts
    )
    assert any(quart["relation_claim"] for quart in software_quarts)
    assert any("vs Slack" in quart["query"] for quart in software_quarts)
    assert any(
        quart["query"] == "Slack pricing plans enterprise" for quart in software_quarts
    )
    assert any(
        quart["query"] == "钉钉 价格 收费 套餐 企业版" for quart in software_quarts
    )
    assert all(quart["success_criteria"] for quart in software_quarts)

    commodity_quarts = _plan_retrieval_quarts(
        [{"id": "cup", "name": "Ember Mug", "category": "direct_competitor"}],
        commodity_requirement,
    )
    assert {quart["product_type"] for quart in commodity_quarts} == {"commodity"}
    assert any(
        quart["target_slot"] == "relationship_evidence" for quart in commodity_quarts
    )
    assert any(
        quart["query"] == "Ember Mug 京东 天猫 淘宝 价格" for quart in commodity_quarts
    )
    assert any(
        quart["query"] == "Ember Mug 用户评价 小红书 知乎 B站 京东 差评"
        for quart in commodity_quarts
    )


def test_retrieval_quart_planner_uses_competitor_relationship_type():
    from app.agents.nodes.material_collection import _plan_retrieval_quarts

    requirement = {
        "name": "Notion AI",
        "domain": "团队知识管理与 AI 写作",
        "core_capabilities": ["知识管理", "AI 写作", "团队协作"],
        "primary_use_cases": ["团队知识沉淀", "文档协作"],
    }
    competitors = [
        {
            "id": "clickup",
            "name": "ClickUp AI",
            "category": "indirect_competitor",
            "region": "global",
        },
        {
            "id": "manual",
            "name": "搜索引擎 + 表格 + PPT",
            "category": "substitute_solution",
            "region": "china",
        },
    ]

    quarts = _plan_retrieval_quarts(competitors, requirement)
    clickup_relation = next(
        quart
        for quart in quarts
        if quart["competitor_id"] == "clickup"
        and quart["target_slot"] == "relationship_evidence"
    )
    manual_relation = next(
        quart
        for quart in quarts
        if quart["competitor_id"] == "manual"
        and quart["target_slot"] == "relationship_evidence"
    )

    assert clickup_relation["competitor_type"] == "indirect_competitor"
    assert "use cases team workflow" in clickup_relation["query"]
    assert "间接竞争" in clickup_relation["relation_claim"]
    assert manual_relation["competitor_type"] == "substitute_solution"
    assert "人工流程 表格 PPT" in manual_relation["query"]
    assert "替代路径" in manual_relation["relation_claim"]


def test_retrieval_quart_planner_skips_covered_pricing_slot():
    from app.agents.nodes.material_collection import _plan_retrieval_quarts

    competitor = {
        "id": "slack",
        "name": "Slack",
        "category": "direct_competitor",
        "region": "global",
    }
    sources = [{"id": "src_pricing", "source_type": "official_pricing_page"}]
    evidence = [
        {
            "competitor_id": "slack",
            "source_id": "src_pricing",
            "related_product": "Slack",
            "related_dimension": "价格与商业模式",
            "confidence": 0.9,
        }
    ]

    quarts = _plan_retrieval_quarts(
        [competitor], {"domain": "企业协作办公平台"}, evidence, sources
    )

    assert "pricing" not in {quart["target_slot"] for quart in quarts}
    assert "relationship_evidence" in {quart["target_slot"] for quart in quarts}
    assert len(quarts) == 5


def test_ark_report_source_summary_reads_metadata_json():
    from app.providers.llm.ark import _ensure_reference_section, _source_report_summary

    summary = _source_report_summary(
        {
            "title": "Slack Pricing Plans and Enterprise Features",
            "url": "https://slack.com/pricing",
            "source_type": "official_pricing_page",
            "metadata_json": (
                '{"credibility_score": 0.93, "rank_score": 1.0, '
                '"source_type_label": "官方价格页", "dimension": "价格与商业模式", '
                '"query": "Slack pricing plans enterprise official", '
                '"classification_reason": "按领域、域名、标题关键词和维度匹配。"}'
            ),
        }
    )

    assert summary["credibility_score"] == 0.93
    assert "reference_id" not in summary
    assert summary["rank_score"] == 1.0
    assert summary["source_type_label"] == "官方价格页"
    assert summary["dimension"] == "价格与商业模式"
    assert summary["query"] == "Slack pricing plans enterprise official"
    assert summary["classification_reason"] == "按领域、域名、标题关键词和维度匹配。"

    numbered_summary = _source_report_summary(
        {"title": "Example", "url": "https://example.com"}, reference_id=3
    )
    assert numbered_summary["reference_id"] == 3

    content = "## 摘要\n\n结论引用[2](https://b.example)，越界引用[19](https://missing.example)。\n\n## 参考来源\n\n1. [旧来源](https://old.example)"
    updated = _ensure_reference_section(
        content,
        [
            {
                "title": "A Source",
                "url": "https://a.example",
                "source_type": "official_site",
            },
            {
                "title": "B Source",
                "url": "https://b.example",
                "source_type": "review_site",
            },
        ],
    )
    assert "旧来源" not in updated
    assert "结论引用[[2]](https://b.example)，越界引用。" in updated
    assert "missing.example" not in updated
    assert "1. [[1]](https://a.example) [A Source](https://a.example)" in updated
    assert "2. [[2]](https://b.example) [B Source](https://b.example)" in updated


def test_feishu_competitor_discovery_uses_collaboration_context():
    init_db()
    create_response = client.post(
        "/api/runs", json={"user_requirement": "我想分析飞书的竞品，侧重功能对比"}
    )
    assert create_response.status_code == 201
    run = create_response.json()
    assert run["status"] == "running"
    run = _wait_for_status(run["id"], "waiting_for_human")
    assert run["title"] == "企业协作办公平台"

    competitors_response = client.get(f"/api/runs/{run['id']}/competitors")
    assert competitors_response.status_code == 200
    competitors = competitors_response.json()
    competitor_names = {item["name"] for item in competitors}
    competitor_regions = {item["region"] for item in competitors}

    assert competitor_names & {
        "钉钉",
        "企业微信",
        "Slack",
        "Microsoft Teams",
        "Google Workspace",
        "Notion",
    }
    assert {"global", "china"}.issubset(competitor_regions)
    assert not competitor_names & {
        "GIE",
        "Outscraper",
        "通用",
        "視点",
        "Products",
        "The",
        "EPD",
        "Industrial",
    }
    assert all("匹配维度" in item["description"] for item in competitors)
    assert all("来源" in item["description"] for item in competitors)

    timeline_response = client.get(f"/api/runs/{run['id']}/timeline")
    assert timeline_response.status_code == 200
    timeline = timeline_response.json()
    stages = {item["stage"] for item in timeline}
    assert {
        "target_query_planning",
        "target_search",
        "target_understanding",
        "competitor_query_planning",
        "competitor_search",
        "candidate_extraction",
    }.issubset(stages)
    discovery_trace = next(
        item for item in timeline if item["stage"] == "competitor_discovery"
    )
    assert "飞书" in discovery_trace["output_json"]
    assert "target_search_result_count" in discovery_trace["output_json"]


def test_ai_coding_competitor_discovery_uses_developer_tool_context():
    llm = MockLLMProvider()
    search = MockSearchProvider()
    requirement = llm.understand_requirement("我想做 AI 编程")
    focus_profile = llm.extract_focus_profile("我想做 AI 编程", requirement)
    target = llm.understand_target(requirement, [])
    results = [item.__dict__ for item in search.search(requirement["query"], limit=8)]
    competitors = llm.extract_competitors(requirement, target, results)
    names = {item["name"] for item in competitors}

    assert requirement["domain"] == "AI 编程"
    assert focus_profile["clarification_needed"] is True
    assert "代码生成质量" in focus_profile["clarifying_question"]
    assert names & {
        "Cursor",
        "GitHub Copilot",
        "Windsurf",
        "Codeium",
        "通义灵码",
        "豆包 MarsCode",
    }
    assert not names & {"我想做", "编程", "同类产品榜单", "与竞品对比", "alternatives"}


def test_product_idea_competitor_discovery_uses_drinkware_context():
    llm = MockLLMProvider()
    search = MockSearchProvider()
    requirement = llm.understand_requirement("我要做一个水壶产品")
    focus_profile = llm.extract_focus_profile("我要做一个水壶产品", requirement)
    target = llm.understand_target(requirement, [])
    results = [item.__dict__ for item in search.search(requirement["query"], limit=8)]
    competitors = llm.extract_competitors(requirement, target, results)
    names = {item["name"] for item in competitors}

    assert requirement["domain"] == "水壶/饮具"
    assert focus_profile["clarification_needed"] is True
    assert names & {
        "Stanley Quencher",
        "Hydro Flask",
        "YETI Rambler",
        "Fellow Carter",
        "膳魔师保温杯",
        "哈尔斯水杯",
        "富光水杯",
    }
    assert not names & {
        "我要做",
        "水壶",
        "水壶产品",
        "同类产品榜单",
        "与竞品对比",
        "用户需求",
    }
