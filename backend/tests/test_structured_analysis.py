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


def test_repair_tasks_force_explicit_and_field_dimension_evidence_ids():
    evidence = [
        {
            "id": "ev_old",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "reference_id": 1,
            "confidence": 0.9,
            "relevance_score": 0.9,
            "support_type": "direct",
        },
        {
            "id": "ev_pain",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 2,
            "confidence": 0.92,
            "relevance_score": 0.95,
            "support_type": "direct",
        },
        {
            "id": "ev_feature",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 3,
            "confidence": 0.91,
            "relevance_score": 0.93,
            "support_type": "direct",
        },
    ]

    result = structured_analysis_node(
        {
            "selected_competitors": [competitor()],
            "evidence": evidence,
            "feedback_loop_count": 2,
            "qa_retry_analysis_ids": ["comp_1"],
            "qa_repair_tasks": [
                {
                    "issue_id": "qai_weakness",
                    "competitor_id": "comp_1",
                    "competitor_name": "Acme",
                    "fields": ["weaknesses_json", "core_features_json"],
                    "acceptance_criteria": (
                        "劣势必须引用 ev_pain；核心功能必须使用核心功能证据。"
                    ),
                }
            ],
        },
        FakeAnalysisLLM(
            complete_analysis(
                id="ana_repaired",
                weaknesses_json=json.dumps(["用户反馈配置复杂"]),
                core_features_json=json.dumps(["自动化工作流"]),
                evidence_ids_json=json.dumps(["ev_old"]),
            )
        ),
    )

    ids = set(json.loads(result["analyses"][0]["evidence_ids_json"]))
    assert {"ev_old", "ev_pain", "ev_feature"} <= ids
    field_ids = json.loads(result["analyses"][0]["field_evidence_ids_json"])
    assert "ev_pain" in field_ids["weaknesses_json"]
    assert "ev_feature" in field_ids["core_features_json"]


def test_repair_task_evidence_ids_are_not_truncated_by_stale_long_list():
    evidence = [
        {
            "id": f"ev_old_{idx}",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "reference_id": idx,
            "confidence": 0.7,
        }
        for idx in range(20)
    ]
    evidence.append(
        {
            "id": "ev_required",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 99,
            "confidence": 0.95,
            "relevance_score": 0.95,
            "support_type": "direct",
        }
    )

    result = structured_analysis_node(
        {
            "selected_competitors": [competitor()],
            "evidence": evidence,
            "feedback_loop_count": 2,
            "qa_retry_analysis_ids": ["comp_1"],
            "qa_repair_tasks": [
                {
                    "issue_id": "qai_weakness",
                    "competitor_id": "comp_1",
                    "competitor_name": "Acme",
                    "fields": ["weaknesses_json"],
                    "acceptance_criteria": "劣势必须引用 ev_required。",
                }
            ],
        },
        FakeAnalysisLLM(
            complete_analysis(
                id="ana_repaired",
                weaknesses_json=json.dumps(["用户反馈配置复杂"]),
                evidence_ids_json=json.dumps([f"ev_old_{idx}" for idx in range(20)]),
            )
        ),
    )

    ids = json.loads(result["analyses"][0]["evidence_ids_json"])
    assert ids[0] == "ev_required"
    assert "ev_required" in ids
    assert len(ids) == 16


def test_citation_bundle_prefers_field_evidence_binding_for_claim():
    analysis = complete_analysis(
        field_evidence_ids_json=json.dumps(
            {"weaknesses_json": ["ev_pain"]}, ensure_ascii=False
        ),
        evidence_ids_json=json.dumps(["ev_feature"], ensure_ascii=False),
    )
    evidence = [
        {
            "id": "ev_feature",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 1,
            "confidence": 0.9,
        },
        {
            "id": "ev_pain",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 2,
            "confidence": 0.9,
        },
    ]

    bundle = _build_citation_bundle([analysis], evidence, [])
    weakness_claim = next(
        claim for claim in bundle[0]["claims"] if claim["claim_type"] == "weaknesses"
    )

    assert weakness_claim["evidence"][0]["source_reference_id"] == 2


def test_repair_tasks_remove_bad_evidence_ids_from_bindings_and_fields():
    evidence = [
        {
            "id": "ev_positive",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 1,
            "confidence": 0.9,
        },
        {
            "id": "ev_negative",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 2,
            "confidence": 0.9,
            "relevance_score": 0.9,
            "support_type": "direct",
        },
    ]

    result = structured_analysis_node(
        {
            "selected_competitors": [competitor()],
            "evidence": evidence,
            "feedback_loop_count": 2,
            "qa_retry_analysis_ids": ["comp_1"],
            "qa_repair_tasks": [
                {
                    "issue_id": "qai_bad_ev",
                    "competitor_id": "comp_1",
                    "competitor_name": "Acme",
                    "fields": ["weaknesses_json"],
                    "must_remove_evidence_ids": ["ev_positive"],
                    "acceptance_criteria": "移除不能支撑劣势的正面评价证据。",
                }
            ],
        },
        FakeAnalysisLLM(
            complete_analysis(
                id="ana_repaired",
                weaknesses_json=json.dumps(
                    ["定价引发用户不满（证据ev_negative）"], ensure_ascii=False
                ),
                field_evidence_ids_json=json.dumps(
                    {"weaknesses_json": ["ev_positive", "ev_negative"]},
                    ensure_ascii=False,
                ),
                evidence_ids_json=json.dumps(["ev_positive", "ev_negative"]),
            )
        ),
    )

    analysis = result["analyses"][0]
    ids = json.loads(analysis["evidence_ids_json"])
    field_ids = json.loads(analysis["field_evidence_ids_json"])
    weaknesses = json.loads(analysis["weaknesses_json"])

    assert "ev_positive" not in ids
    assert "ev_positive" not in field_ids["weaknesses_json"]
    assert "ev_negative" in field_ids["weaknesses_json"]
    assert all("ev_" not in item for item in weaknesses)


def test_repair_tasks_required_evidence_ids_override_stale_bindings():
    evidence = [
        {
            "id": "ev_pricing",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "价格与商业模式",
            "reference_id": 1,
            "confidence": 0.9,
        },
        {
            "id": "ev_positioning",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "reference_id": 2,
            "confidence": 0.95,
            "relevance_score": 0.95,
            "support_type": "direct",
        },
    ]

    result = structured_analysis_node(
        {
            "selected_competitors": [competitor()],
            "evidence": evidence,
            "feedback_loop_count": 2,
            "qa_retry_analysis_ids": ["comp_1"],
            "qa_repair_tasks": [
                {
                    "issue_id": "qai_positioning_weakness",
                    "competitor_id": "comp_1",
                    "competitor_name": "Acme",
                    "fields": ["weaknesses_json"],
                    "required_evidence_ids": ["ev_positioning"],
                    "forbidden_evidence_ids": ["ev_pricing"],
                    "claim": "产品定位缺乏差异化",
                    "acceptance_criteria": "劣势必须引用定位证据。",
                }
            ],
        },
        FakeAnalysisLLM(
            complete_analysis(
                id="ana_repaired",
                weaknesses_json=json.dumps(["产品定位缺乏差异化"], ensure_ascii=False),
                field_evidence_ids_json=json.dumps(
                    {"weaknesses_json": ["ev_pricing"]}, ensure_ascii=False
                ),
                evidence_ids_json=json.dumps(["ev_pricing"]),
            )
        ),
    )

    analysis = result["analyses"][0]
    field_ids = json.loads(analysis["field_evidence_ids_json"])
    item_bindings = json.loads(analysis["item_evidence_bindings_json"])

    assert field_ids["weaknesses_json"] == ["ev_positioning"]
    assert item_bindings["weaknesses_json"][0]["evidence_ids"] == ["ev_positioning"]


def test_field_evidence_merges_repaired_ids_when_item_binding_has_wrong_dimension():
    evidence = [
        {
            "id": "ev_competition",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "竞争关系",
            "reference_id": 1,
            "confidence": 0.8,
            "support_type": "direct",
        },
        {
            "id": "ev_positioning",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "reference_id": 2,
            "confidence": 0.95,
            "relevance_score": 0.95,
            "support_type": "direct",
        },
    ]

    result = structured_analysis_node(
        {
            "selected_competitors": [competitor()],
            "evidence": evidence,
            "feedback_loop_count": 2,
            "qa_retry_analysis_ids": ["comp_1"],
        },
        FakeAnalysisLLM(
            complete_analysis(
                id="ana_repaired",
                positioning="Acme is positioned as an AI coding agent.",
                evidence_ids_json=json.dumps(["ev_competition"]),
                field_evidence_ids_json=json.dumps(
                    {"positioning": ["ev_competition"]}, ensure_ascii=False
                ),
                item_evidence_bindings_json=json.dumps(
                    {
                        "positioning": [
                            {
                                "item_index": 0,
                                "claim": "Acme is positioned as an AI coding agent.",
                                "evidence_ids": ["ev_competition"],
                                "match_reason": "LLM chose a competition signal.",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            )
        ),
    )

    field_ids = json.loads(result["analyses"][0]["field_evidence_ids_json"])
    assert "ev_positioning" in field_ids["positioning"]


def test_item_evidence_repair_uses_item_index_not_row_position():
    evidence = [
        {
            "id": "ev_first",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 1,
            "confidence": 0.9,
            "relevance_score": 0.9,
            "support_type": "direct",
            "sentiment": "negative",
            "claim": "Users report complex setup.",
        },
        {
            "id": "ev_second",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 2,
            "confidence": 0.95,
            "relevance_score": 0.95,
            "support_type": "direct",
            "sentiment": "negative",
            "claim": "Users report unstable integrations.",
        },
    ]

    result = structured_analysis_node(
        {
            "selected_competitors": [competitor()],
            "evidence": evidence,
            "feedback_loop_count": 2,
            "qa_retry_analysis_ids": ["comp_1"],
        },
        FakeAnalysisLLM(
            complete_analysis(
                id="ana_repaired",
                weaknesses_json=json.dumps(
                    [
                        "Users report complex setup",
                        "Users report unstable integrations",
                    ],
                    ensure_ascii=False,
                ),
                evidence_ids_json=json.dumps(["ev_first", "ev_second"]),
                item_evidence_bindings_json=json.dumps(
                    {
                        "weaknesses_json": [
                            {
                                "item_index": 1,
                                "claim": "Users report unstable integrations",
                                "evidence_ids": ["ev_second"],
                                "match_reason": "Existing row for item 1.",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            )
        ),
    )

    rows = json.loads(result["analyses"][0]["item_evidence_bindings_json"])[
        "weaknesses_json"
    ]
    row_by_index = {row["item_index"]: row for row in rows}
    assert "ev_second" in row_by_index[1]["evidence_ids"]


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
