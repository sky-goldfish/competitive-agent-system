import json

import pytest
from fastapi.testclient import TestClient

import app.services.run_service as run_service
from app.db.session import init_db
from app.main import app
from app.providers.llm.mock import MockLLMProvider
from app.providers.search.mock import MockSearchProvider


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
    raise AssertionError(f"Run {run_id} did not reach {expected}")


def test_run_lifecycle():
    init_db()
    create_response = client.post("/api/runs", json={"user_requirement": "我想分析 AI 会议纪要工具的竞品"})
    assert create_response.status_code == 201
    run = create_response.json()
    assert run["status"] == "running"
    run = _wait_for_status(run["id"], "waiting_for_human")

    competitors_response = client.get(f"/api/runs/{run['id']}/competitors")
    assert competitors_response.status_code == 200
    competitors = competitors_response.json()
    assert len(competitors) >= 2

    selected_ids = [item["id"] for item in competitors[:2]]
    confirm_response = client.post(
        f"/api/runs/{run['id']}/competitors/confirm",
        json={
            "competitor_ids": selected_ids,
            "custom_competitors": [{"name": "自定义竞品", "website": "https://example.com", "category": "adjacent_product"}],
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
    evidence_response = client.get(f"/api/runs/{run['id']}/evidence")
    assert evidence_response.status_code == 200
    evidence_items = evidence_response.json()
    assert len(evidence_items) > 0

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
    assert {"requirement_understanding", "competitor_discovery", "human_confirm_competitors", "material_collection", "structured_analysis", "report_generation"}.issubset(stages)
    assert {"material_query_planning", "source_search", "source_classification", "evidence_extraction", "coverage_checking"}.issubset(stages)


def test_material_source_classification_supports_domain_weights():
    from app.agents.nodes.material_collection import _classify_source

    commodity_requirement = {"domain": "智能保温杯与办公水杯"}
    assert _classify_source("https://item.jd.com/100.html", "Ember Mug 京东商品页", "价格 参数", commodity_requirement, "价格与商业模式")[:2] == ("ecommerce_product_page", 0.86)
    assert _classify_source("https://www.xiaohongshu.com/explore/1", "Ember Mug 使用体验", "用户评价", commodity_requirement, "用户评价与痛点")[:2] == ("social_review_post", 0.66)
    assert _classify_source("https://www.zhihu.com/question/1", "智能杯值得买吗", "讨论", commodity_requirement, "用户评价与痛点")[:2] == ("community_discussion", 0.62)

    saas_requirement = {"domain": "企业协作办公平台"}
    assert _classify_source("https://slack.com/pricing", "Slack Pricing", "plans", saas_requirement, "价格与商业模式")[:2] == ("official_pricing_page", 0.93)
    assert _classify_source("https://www.g2.com/products/slack/reviews", "Slack Reviews", "pros cons", saas_requirement, "用户评价与痛点")[:2] == ("review_site", 0.72)


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

    numbered_summary = _source_report_summary({"title": "Example", "url": "https://example.com"}, reference_id=3)
    assert numbered_summary["reference_id"] == 3

    content = "## 摘要\n\n结论引用[2](https://b.example)，越界引用[19](https://missing.example)。\n\n## 参考来源\n\n1. [旧来源](https://old.example)"
    updated = _ensure_reference_section(
        content,
        [
            {"title": "A Source", "url": "https://a.example", "source_type": "official_site"},
            {"title": "B Source", "url": "https://b.example", "source_type": "review_site"},
        ],
    )
    assert "旧来源" not in updated
    assert "结论引用[[2]](https://b.example)，越界引用。" in updated
    assert "missing.example" not in updated
    assert "1. [[1]](https://a.example) [A Source](https://a.example)" in updated
    assert "2. [[2]](https://b.example) [B Source](https://b.example)" in updated



def test_feishu_competitor_discovery_uses_collaboration_context():
    init_db()
    create_response = client.post("/api/runs", json={"user_requirement": "我想分析飞书的竞品"})
    assert create_response.status_code == 201
    run = create_response.json()
    assert run["status"] == "running"
    run = _wait_for_status(run["id"], "waiting_for_human")
    assert run["title"] == "企业协作办公平台"

    competitors_response = client.get(f"/api/runs/{run['id']}/competitors")
    assert competitors_response.status_code == 200
    competitors = competitors_response.json()
    competitor_names = {item["name"] for item in competitors}

    assert competitor_names & {"钉钉", "企业微信", "Slack", "Microsoft Teams", "Google Workspace", "Notion"}
    assert not competitor_names & {"GIE", "Outscraper", "通用", "視点", "Products", "The", "EPD", "Industrial"}
    assert all("匹配维度" in item["description"] for item in competitors)
    assert all("推荐来源" in item["description"] for item in competitors)

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
    discovery_trace = next(item for item in timeline if item["stage"] == "competitor_discovery")
    assert "飞书" in discovery_trace["output_json"]
    assert "target_search_result_count" in discovery_trace["output_json"]
