import json

from app.agents.nodes.material_collection import _focus_items
from app.agents.nodes.report_generation import _extract_focus_dimensions
from app.agents.nodes.report_generation import _build_citation_bundle
from app.agents.nodes.structured_analysis import (
    _active_focus_items,
    _normalize_custom_focus_analysis,
    structured_analysis_node,
)


class FakeAnalysisLLM:
    name = "fake-analysis"

    def __init__(self, analysis):
        self.analysis = analysis
        self.calls = 0

    def analyze_competitor(self, competitor, evidence):
        self.calls += 1
        return dict(self.analysis)


def competitor():
    return {
        "id": "comp_1",
        "name": "Acme",
        "website": "https://acme.example.com",
        "description": "Acme",
    }


def complete_analysis(**overrides):
    analysis = {
        "id": "ana_previous",
        "competitor_id": "comp_1",
        "competitor_name": "Acme",
        "positioning": "Acme is a workflow automation product.",
        "target_users": json.dumps(["Operations teams"]),
        "core_features_json": json.dumps(["Automation", "Integrations"]),
        "pricing_summary": "Tiered subscription pricing.",
        "strengths_json": json.dumps(["Broad integrations"]),
        "weaknesses_json": json.dumps(["Complex setup"]),
        "opportunities_json": json.dumps(["Expand self-serve adoption"]),
        "custom_focus_analysis_json": "[]",
        "evidence_ids_json": json.dumps(["ev_1", "ev_2", "ev_3"]),
        "analysis_iteration": 1,
    }
    analysis.update(overrides)
    return analysis


def evidence_items():
    return [
        {
            "id": f"ev_{idx}",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": idx,
            "confidence": 0.9,
        }
        for idx in range(1, 4)
    ]


def requirement_with_focuses():
    return {
        "focus_profile": {
            "explicit_focuses": [
                {
                    "key": "privacy",
                    "label": "隐私安全",
                    "priority": "high",
                    "evidence_expectation": "隐私政策和安全文档",
                    "query_terms": ["privacy", "security"],
                }
            ],
            "inferred_focuses": [
                {
                    "key": "code_generation_quality",
                    "label": "代码生成质量与准确性",
                    "priority": "medium",
                    "evidence_expectation": "代码生成准确率",
                    "query_terms": ["code generation accuracy"],
                }
            ],
        }
    }


def test_structured_analysis_dedupes_existing_versions_before_returning_state():
    result = structured_analysis_node(
        {
            "selected_competitors": [competitor()],
            "evidence": evidence_items(),
            "analyses": [
                complete_analysis(
                    id="ana_old",
                    weaknesses_json=json.dumps(["Old weakness"]),
                    analysis_iteration=1,
                ),
                complete_analysis(
                    id="ana_new",
                    weaknesses_json=json.dumps(["New weakness"]),
                    analysis_iteration=2,
                ),
            ],
            "qa_retry_analysis_ids": ["missing_competitor"],
        },
        FakeAnalysisLLM(complete_analysis(id="ana_unused")),
    )

    assert len(result["analyses"]) == 1
    assert result["analyses"][0]["id"] == "ana_new"


def test_structured_analysis_keeps_previous_when_retry_regresses_to_placeholder():
    result = structured_analysis_node(
        {
            "selected_competitors": [competitor()],
            "evidence": evidence_items(),
            "feedback_loop_count": 2,
            "analyses": [complete_analysis()],
            "qa_retry_analysis_ids": ["comp_1"],
            "qa_repair_tasks": [
                {
                    "issue_id": "qai_weakness",
                    "competitor_id": "comp_1",
                    "competitor_name": "Acme",
                    "fields": ["weaknesses_json"],
                    "acceptance_criteria": "Add concrete weaknesses.",
                }
            ],
        },
        FakeAnalysisLLM(
            complete_analysis(
                id="ana_regressed",
                weaknesses_json=json.dumps(["证据中未涉及明显劣势"]),
                evidence_ids_json=json.dumps(["ev_1"]),
            )
        ),
    )

    assert len(result["analyses"]) == 1
    assert result["analyses"][0]["id"] == "ana_previous"
    assert json.loads(result["analyses"][0]["weaknesses_json"]) == ["Complex setup"]


def test_focus_helpers_only_expose_user_explicit_focuses():
    requirement = requirement_with_focuses()

    assert [item["label"] for item in _active_focus_items(requirement)] == ["隐私安全"]
    assert [item["label"] for item in _focus_items(requirement)] == ["隐私安全"]
    assert [item["label"] for item in _extract_focus_dimensions(requirement)] == [
        "隐私安全"
    ]


def test_inferred_focuses_do_not_create_visible_custom_dimensions():
    requirement = requirement_with_focuses()
    requirement["focus_profile"]["explicit_focuses"] = []

    assert _active_focus_items(requirement) == []
    assert _focus_items(requirement) == []
    assert _extract_focus_dimensions(requirement) == []


def test_structured_analysis_drops_llm_custom_focus_without_explicit_schema():
    llm_value = json.dumps(
        [
            {
                "focus_key": "code_quality",
                "label": "代码质量",
                "verdict": "LLM invented this focus.",
                "evidence_ids": ["ev_1"],
                "confidence": 0.9,
            }
        ]
    )

    assert _normalize_custom_focus_analysis(llm_value, [], evidence_items()) == "[]"


def test_structured_analysis_filters_custom_focus_to_explicit_schema():
    llm_value = json.dumps(
        [
            {
                "focus_key": "privacy",
                "label": "隐私安全",
                "verdict": "Supported focus.",
                "evidence_ids": ["ev_1", "missing_ev"],
                "confidence": 0.9,
            },
            {
                "focus_key": "code_quality",
                "label": "代码质量",
                "verdict": "Schema-external focus.",
                "evidence_ids": ["ev_2"],
                "confidence": 0.9,
            },
        ]
    )

    normalized = json.loads(
        _normalize_custom_focus_analysis(
            llm_value,
            requirement_with_focuses()["focus_profile"]["explicit_focuses"],
            evidence_items(),
        )
    )

    assert len(normalized) == 1
    assert normalized[0]["focus_key"] == "privacy"
    assert normalized[0]["label"] == "隐私安全"
    assert normalized[0]["evidence_ids"] == ["ev_1"]


def test_report_bundle_filters_historical_custom_focus_by_explicit_schema():
    analysis = complete_analysis(
        custom_focus_analysis_json=json.dumps(
            [
                {
                    "focus_key": "code_quality",
                    "label": "代码质量",
                    "verdict": "Historical dirty focus.",
                    "evidence_ids": ["ev_1"],
                    "confidence": 0.9,
                }
            ]
        )
    )

    bundle_without_focus = _build_citation_bundle([analysis], evidence_items(), [])
    assert all(
        not claim["claim_type"].startswith("focus:")
        for claim in bundle_without_focus[0]["claims"]
    )

    bundle_with_unrelated_focus = _build_citation_bundle(
        [analysis],
        evidence_items(),
        [{"key": "privacy", "label": "隐私安全", "priority": "high"}],
    )
    assert all(
        not claim["claim_type"].startswith("focus:")
        for claim in bundle_with_unrelated_focus[0]["claims"]
    )
