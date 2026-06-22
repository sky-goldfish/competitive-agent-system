import threading
import time

from app.agents.nodes.material_collection import (
    _classify_source,
    _extract_evidence_jobs_concurrently,
    _extract_evidence_items,
    _fallback_evidence_item,
)


class FakeEvidenceLLM:
    name = "fake-evidence"

    def __init__(self, result):
        self.result = result

    def extract_evidence_from_source(self, source, query_item, competitor, requirement):
        return self.result


class CountingEvidenceLLM:
    name = "counting-evidence"

    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def extract_evidence_from_source(self, source, query_item, competitor, requirement):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1
        return {
            "source_relevance": 0.9,
            "evidence": [
                {
                    "related_product": competitor["name"],
                    "related_dimension": query_item["dimension"],
                    "quote": source["snippet"],
                    "summary": source["snippet"],
                    "supports_dimension": True,
                    "support_type": "direct",
                    "relevance_score": 0.9,
                    "confidence": 0.9,
                }
            ],
        }


def source():
    return {
        "title": "Acme features",
        "url": "https://acme.example.com/features",
        "snippet": "Acme provides code completion and code review.",
        "raw_content": "Acme provides code completion and code review for developers.",
        "source_type": "official_docs",
        "credibility_score": 0.92,
        "reference_id": 7,
    }


def query_item():
    return {
        "dimension": "核心功能",
        "target_slot": "core_features",
        "success_criteria": "找到核心功能证据",
    }


def competitor():
    return {"id": "comp_acme", "name": "Acme", "description": "AI coding tool"}


def test_llm_empty_evidence_is_respected_without_fallback_pollution():
    result = _extract_evidence_items(
        FakeEvidenceLLM(
            {
                "source_relevance": 0.1,
                "source_relevance_reason": "Unrelated source.",
                "evidence": [],
            }
        ),
        source(),
        query_item(),
        competitor(),
        {},
    )

    assert result == []


def test_llm_can_extract_multiple_evidence_items_from_one_source():
    result = _extract_evidence_items(
        FakeEvidenceLLM(
            {
                "source_relevance": 0.9,
                "source_relevance_reason": "Directly relevant.",
                "evidence": [
                    {
                        "related_product": "Acme",
                        "related_dimension": "核心功能",
                        "claim": "Acme supports code completion.",
                        "quote": "code completion",
                        "summary": "Acme 支持代码补全。",
                        "supports_dimension": True,
                        "support_type": "direct",
                        "relevance_score": 0.92,
                        "confidence": 0.88,
                    },
                    {
                        "related_product": "Acme",
                        "related_dimension": "核心功能",
                        "claim": "Acme supports code review.",
                        "quote": "code review",
                        "summary": "Acme 支持代码审查。",
                        "supports_dimension": True,
                        "support_type": "direct",
                        "relevance_score": 0.9,
                        "confidence": 0.86,
                    },
                ],
            }
        ),
        source(),
        query_item(),
        competitor(),
        {},
    )

    assert result is not None
    assert len(result) == 2
    assert [item["summary"] for item in result] == [
        "Acme 支持代码补全。",
        "Acme 支持代码审查。",
    ]
    assert all(item["source_url"] == "https://acme.example.com/features" for item in result)
    assert all(item["reference_id"] == 7 for item in result)
    assert all(item["support_type"] == "direct" for item in result)
    assert all(item["extraction_method"] == "llm_extraction" for item in result)


def test_evidence_extraction_jobs_run_concurrently():
    llm = CountingEvidenceLLM()
    jobs = [
        {
            "source": {**source(), "url": f"https://acme.example.com/{idx}"},
            "query_item": query_item(),
            "competitor": competitor(),
            "credibility_score": 0.9,
        }
        for idx in range(4)
    ]

    result = _extract_evidence_jobs_concurrently(llm, jobs, {})

    assert len(result) == 4
    assert llm.max_active > 1


def test_official_docs_domain_is_classified_as_official_docs():
    source_type, score, _reason = _classify_source(
        "https://docs.github.com/en/copilot/get-started/features",
        "GitHub Copilot features",
        "GitHub Copilot offers assistive and agentic features.",
        {"domain": "AI coding"},
        "核心功能",
        {
            "competitor_name": "GitHub Copilot",
            "competitor_website": "https://github.com/features/copilot",
        },
    )

    assert source_type == "official_docs"
    assert score == 0.92


def test_third_party_pricing_guide_is_not_official_pricing_page():
    source_type, _score, _reason = _classify_source(
        "https://www.ssdnodes.com/blog/claude-code-pricing-in-2026",
        "Claude Code Pricing in 2026: Every Plan Explained",
        "Third-party guide to Claude Code pricing.",
        {"domain": "AI coding"},
        "价格与商业模式",
        {
            "competitor_name": "Claude Code",
            "competitor_website": "https://claude.ai",
        },
    )

    assert source_type == "professional_review"


def test_official_product_forum_is_classified_as_community_discussion():
    source_type, score, _reason = _classify_source(
        "https://forum.cursor.com/t/complaint-regarding-cursor-ai-agent-performance/77460",
        "Complaint Regarding Cursor AI Agent Performance - Feedback - Cursor - Community Forum",
        "User feedback about Cursor AI Agent performance.",
        {"domain": "AI coding"},
        "用户评价与痛点",
        {
            "competitor_name": "Cursor",
            "competitor_website": "https://cursor.com",
        },
    )

    assert source_type == "community_discussion"
    assert score == 0.62


def test_fallback_evidence_is_marked_and_capped():
    item = _fallback_evidence_item(
        {
            "title": "Acme fallback",
            "url": "https://example.com/acme",
            "snippet": "Acme fallback snippet.",
            "raw_content": "Acme fallback raw content.",
            "source_type": "professional_review",
            "reference_id": 9,
        },
        query_item(),
        competitor(),
        0.95,
    )

    assert item["extraction_method"] == "fallback_search_snippet"
    assert item["support_type"] == "indirect"
    assert item["confidence"] <= 0.65
    assert item["relevance_score"] <= 0.65
