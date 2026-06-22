import json

from app.agents.evidence_policy import evidence_matches_claim_policy
from app.agents.nodes.quality_check import (
    _build_repair_tasks,
    _reference_ids_requiring_removal,
    quality_check_node,
)


class FakeQALLM:
    name = "fake-qa"

    def __init__(self, *, qa_result=None, verify_result=None):
        self.qa_check_calls = 0
        self.qa_verify_calls = 0
        self.qa_result = qa_result or {
            "dimension_scores": {
                "evidence_grounding": 0.9,
                "citation_accuracy": 0.9,
                "schema_completeness": 0.9,
                "coverage_gaps": 0.9,
                "cross_competitor_consistency": 0.9,
                "factual_plausibility": 0.9,
            },
            "issues": [],
            "retry_queries": [],
            "retry_instructions": None,
        }
        self.verify_result = verify_result or {
            "resolutions": [],
            "retry_instructions": None,
        }

    def qa_check_report(self, analyses, evidence):
        self.qa_check_calls += 1
        return self.qa_result

    def qa_verify_issues(self, analyses, evidence, open_issues):
        self.qa_verify_calls += 1
        return self.verify_result


def complete_analysis(**overrides):
    analysis = {
        "competitor_id": "comp_1",
        "competitor_name": "Acme",
        "positioning": "Acme is a workflow automation product.",
        "target_users": json.dumps(["Operations teams"]),
        "core_features_json": json.dumps(["Automation", "Integrations"]),
        "pricing_summary": "Tiered subscription pricing.",
        "strengths_json": json.dumps(["Broad integrations"]),
        "weaknesses_json": json.dumps(["Complex setup"]),
        "opportunities_json": json.dumps(["Expand self-serve adoption"]),
        "evidence_ids_json": json.dumps(["ev_1", "ev_2", "ev_3"]),
    }
    analysis.update(overrides)
    return analysis


def evidence_items():
    return [
        {
            "id": f"ev_{idx}",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "confidence": 0.9,
        }
        for idx in range(1, 4)
    ]


def referenced_evidence_items():
    return [
        {
            "id": f"ev_{idx}",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "reference_id": idx,
            "confidence": 0.9,
        }
        for idx in range(1, 4)
    ]


def test_field_content_requires_matching_dimension_evidence_binding():
    evidence = [
        {
            "id": "ev_positioning",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "reference_id": 1,
            "confidence": 0.9,
        },
        {
            "id": "ev_feature",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 2,
            "confidence": 0.9,
        },
        {
            "id": "ev_pricing",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "价格与商业模式",
            "reference_id": 3,
            "confidence": 0.9,
        },
        {
            "id": "ev_pain",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 4,
            "confidence": 0.92,
            "relevance_score": 0.95,
            "support_type": "direct",
        },
    ]
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    weaknesses_json=json.dumps(["Users report complex setup."]),
                    evidence_ids_json=json.dumps(
                        ["ev_positioning", "ev_feature", "ev_pricing"]
                    ),
                )
            ],
            "evidence": evidence,
        },
        FakeQALLM(),
    )

    assert result["qa_result"]["decision"] == "retry_analysis"
    assert any(
        issue["dimension"] == "evidence_grounding"
        and "劣势或痛点字段" in issue["description"]
        for issue in result["qa_result"]["issues"]
    )


def test_core_feature_limitation_can_support_weakness():
    limitation = {
        "id": "ev_limit",
        "competitor_id": "comp_1",
        "related_product": "Acme",
        "related_dimension": "核心功能",
        "sentiment": "negative",
        "evidence_role": "limitation",
        "support_type": "direct",
        "claim": "Advanced features require a dedicated model and do not support custom API keys.",
    }
    praise = {
        "id": "ev_praise",
        "competitor_id": "comp_1",
        "related_product": "Acme",
        "related_dimension": "用户评价与痛点",
        "sentiment": "positive",
        "evidence_role": "user_praise",
        "support_type": "direct",
        "claim": "Users say Acme improves productivity.",
    }

    assert evidence_matches_claim_policy(
        limitation,
        "weaknesses_json",
        "Advanced features have usage limitations.",
        [limitation, praise],
    )
    assert not evidence_matches_claim_policy(
        praise,
        "weaknesses_json",
        "Advanced features have usage limitations.",
        [limitation, praise],
    )


def test_refund_claim_prefers_pricing_evidence_for_weakness():
    pricing_limit = {
        "id": "ev_refund",
        "competitor_id": "comp_1",
        "related_product": "Acme",
        "related_dimension": "价格与商业模式",
        "sentiment": "negative",
        "evidence_role": "limitation",
        "claim": "Paid subscriptions are non-refundable.",
    }
    feature = {
        "id": "ev_feature",
        "competitor_id": "comp_1",
        "related_product": "Acme",
        "related_dimension": "核心功能",
        "sentiment": "neutral",
        "evidence_role": "feature",
        "claim": "Acme provides AI code generation.",
    }

    assert evidence_matches_claim_policy(
        pricing_limit,
        "weaknesses_json",
        "付费订阅不支持退款",
        [pricing_limit, feature],
    )
    assert not evidence_matches_claim_policy(
        feature,
        "weaknesses_json",
        "付费订阅不支持退款",
        [pricing_limit, feature],
    )


def test_opportunities_do_not_require_direct_dimension_binding():
    evidence = [
        {
            "id": "ev_positioning",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "reference_id": 1,
            "confidence": 0.9,
        },
        {
            "id": "ev_feature",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 2,
            "confidence": 0.9,
        },
        {
            "id": "ev_pricing",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "价格与商业模式",
            "reference_id": 3,
            "confidence": 0.9,
        },
        {
            "id": "ev_pain",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 4,
            "confidence": 0.9,
        },
    ]
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    opportunities_json=json.dumps(
                        ["Use multi-model and integration signals to expand enterprise roadmap."]
                    ),
                    evidence_ids_json=json.dumps(
                        ["ev_positioning", "ev_feature", "ev_pricing", "ev_pain"]
                    ),
                    item_evidence_bindings_json=json.dumps(
                        {
                            "opportunities_json": [
                                {
                                    "item_index": 0,
                                    "claim": "Use multi-model and integration signals to expand enterprise roadmap.",
                                    "evidence_ids": ["ev_feature"],
                                    "match_reason": "Feature evidence can inform strategic opportunities.",
                                }
                            ]
                        }
                    ),
                )
            ],
            "evidence": evidence,
        },
        FakeQALLM(),
    )

    assert result["qa_result"]["decision"] == "pass"
    assert not any(
        issue["dimension"] == "evidence_grounding"
        and "机会点" in issue["description"]
        for issue in result["qa_result"]["issues"]
    )


def test_unresolved_blocker_before_retry_budget_continues_retry():
    result = quality_check_node(
        {
            "analyses": [complete_analysis()],
            "evidence": evidence_items(),
            "feedback_loop_count": 1,
            "qa_issue_checklist": [
                {
                    "id": "qai_unresolved",
                    "dimension": "evidence_grounding",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "Weakness text lacks matching evidence.",
                    "fix_suggestion": "Add the matching evidence id.",
                    "status": "unresolved",
                    "first_seen_iteration": 1,
                    "last_seen_iteration": 1,
                }
            ],
        },
        FakeQALLM(),
    )

    assert result["qa_result"]["decision"] == "retry_analysis"
    assert result["qa_result"]["quality_warning"] is True
    assert any(
        task["issue_id"] == "qai_unresolved"
        for task in result["qa_repair_tasks"]
    )


def test_repair_tasks_extract_preferred_and_forbidden_evidence_ids():
    tasks = _build_repair_tasks(
        [
            {
                "id": "qai_binding",
                "dimension": "evidence_grounding",
                "severity": "major",
                "competitor_name": "Acme",
                "description": "劣势字段引用 ev_bad，证据不匹配。",
                "fix_suggestion": "将 weaknesses_json 替换为真正支撑定位问题的证据：ev_good_1、ev_good_2。",
                "status": "open",
            }
        ],
        [complete_analysis()],
    )

    assert tasks[0]["preferred_evidence_ids"] == ["ev_good_1", "ev_good_2"]
    assert tasks[0]["required_evidence_ids"] == []
    assert tasks[0]["forbidden_evidence_ids"] == ["ev_bad"]
    assert tasks[0]["must_remove_evidence_ids"] == ["ev_bad"]


def test_repair_tasks_extract_forbidden_ids_from_remove_instruction():
    tasks = _build_repair_tasks(
        [
            {
                "id": "qai_remove_bad",
                "dimension": "citation_accuracy",
                "severity": "minor",
                "competitor_name": "Acme",
                "description": "weaknesses字段引用了ev_bad，该证据属于核心功能维度，与弱点无关。",
                "fix_suggestion": "从weaknesses_json中移除ev_bad，或替换为真正的弱点证据。",
                "status": "open",
            }
        ],
        [complete_analysis()],
    )

    assert tasks[0]["forbidden_evidence_ids"] == ["ev_bad"]
    assert tasks[0]["must_remove_evidence_ids"] == ["ev_bad"]


def test_full_check_can_resolve_stale_unresolved_placeholder_issue():
    evidence = [
        {
            "id": "ev_positioning",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "reference_id": 1,
            "confidence": 0.9,
        },
        {
            "id": "ev_feature",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 2,
            "confidence": 0.9,
        },
        {
            "id": "ev_pricing",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "价格与商业模式",
            "reference_id": 3,
            "confidence": 0.9,
        },
        {
            "id": "ev_pain",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 4,
            "confidence": 0.9,
        },
    ]

    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    weaknesses_json=json.dumps(["Users report complex setup."]),
                    evidence_ids_json=json.dumps(
                        ["ev_positioning", "ev_feature", "ev_pricing", "ev_pain"]
                    ),
                )
            ],
            "evidence": evidence,
            "feedback_loop_count": 2,
            "qa_issue_checklist": [
                {
                    "id": "qai_stale",
                    "dimension": "schema_completeness",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "劣势字段仅写'无'，未提供任何实质性分析内容。",
                    "fix_suggestion": "补充具体劣势。",
                    "status": "unresolved",
                    "first_seen_iteration": 1,
                    "last_seen_iteration": 2,
                }
            ],
        },
        FakeQALLM(),
    )

    assert result["qa_result"]["decision"] == "pass"
    assert result["qa_issue_checklist"][0]["status"] == "resolved"
    assert "最新结构化分析已补齐" in result["qa_issue_checklist"][0]["resolution_reason"]


def test_stale_evidence_grounding_issue_requires_matching_field_evidence():
    evidence = [
        {
            "id": "ev_positioning",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
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
        {
            "id": "ev_feature",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 3,
            "confidence": 0.9,
        },
        {
            "id": "ev_pricing",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "价格与商业模式",
            "reference_id": 4,
            "confidence": 0.9,
        },
    ]

    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    weaknesses_json=json.dumps(["Users report complex setup."]),
                    evidence_ids_json=json.dumps(
                        ["ev_positioning", "ev_feature", "ev_pricing"]
                    ),
                )
            ],
            "evidence": evidence,
            "feedback_loop_count": 2,
            "qa_issue_checklist": [
                {
                    "id": "qai_stale_grounding",
                    "dimension": "evidence_grounding",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "劣势字段写'无'，但用户评价证据显示存在痛点。",
                    "fix_suggestion": "补充具体劣势并引用用户评价证据。",
                    "status": "unresolved",
                    "first_seen_iteration": 1,
                    "last_seen_iteration": 2,
                }
            ],
        },
        FakeQALLM(
            qa_result={
                "dimension_scores": {
                    "evidence_grounding": 0.95,
                    "citation_accuracy": 0.95,
                    "schema_completeness": 0.95,
                    "coverage_gaps": 0.95,
                    "cross_competitor_consistency": 0.95,
                    "factual_plausibility": 0.95,
                },
                "issues": [],
                "retry_queries": [],
                "retry_instructions": None,
            }
        ),
    )

    assert result["qa_result"]["decision"] == "retry_analysis"
    assert result["qa_issue_checklist"][0]["status"] == "unresolved"
    assert any(
        issue["id"] == "det_field_ev_comp_1_weaknesses_json"
        for issue in result["qa_issue_checklist"]
    )


def test_issue_verification_rejects_resolved_grounding_without_valid_binding():
    evidence = [
        {
            "id": "ev_positioning",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "reference_id": 1,
            "confidence": 0.9,
        },
        {
            "id": "ev_feature",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 2,
            "confidence": 0.9,
        },
        {
            "id": "ev_pricing",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "价格与商业模式",
            "reference_id": 3,
            "confidence": 0.9,
        },
        {
            "id": "ev_pain",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 4,
            "confidence": 0.9,
            "sentiment": "negative",
            "evidence_role": "user_complaint",
        },
    ]
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    weaknesses_json=json.dumps(["Users report complex setup."]),
                    evidence_ids_json=json.dumps(
                        ["ev_positioning", "ev_feature", "ev_pricing"]
                    ),
                    field_evidence_ids_json=json.dumps(
                        {"weaknesses_json": ["ev_pricing"]},
                        ensure_ascii=False,
                    ),
                )
            ],
            "evidence": evidence,
            "feedback_loop_count": 1,
            "qa_issue_verification_count": 0,
            "qa_issue_checklist": [
                {
                    "id": "qai_grounding",
                    "dimension": "evidence_grounding",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "劣势字段缺少用户痛点证据绑定。",
                    "fix_suggestion": "补充具体劣势并引用用户评价证据。",
                    "status": "open",
                    "first_seen_iteration": 1,
                    "last_seen_iteration": 1,
                    "fields": ["weaknesses_json"],
                }
            ],
        },
        FakeQALLM(
            verify_result={
                "resolutions": [
                    {
                        "issue_id": "qai_grounding",
                        "status": "resolved",
                        "resolution_reason": "已解决。",
                    }
                ],
                "retry_instructions": None,
            }
        ),
    )

    assert result["qa_result"]["decision"] == "retry_analysis"
    assert result["qa_issue_checklist"][0]["status"] == "open"
    assert "仍缺少有效证据绑定" in result["qa_issue_checklist"][0]["resolution_reason"]


def test_issue_verification_accepts_resolved_citation_when_bad_evidence_removed():
    evidence = [
        {
            "id": "ev_positioning",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "reference_id": 1,
            "confidence": 0.9,
        },
        {
            "id": "ev_feature",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 2,
            "confidence": 0.9,
        },
        {
            "id": "ev_price",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "价格与商业模式",
            "reference_id": 3,
            "confidence": 0.9,
            "sentiment": "negative",
            "evidence_role": "limitation",
        },
        {
            "id": "ev_bad",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 4,
            "confidence": 0.9,
            "sentiment": "neutral",
            "evidence_role": "feature",
        },
    ]
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    weaknesses_json=json.dumps(["Paid subscriptions are non-refundable."]),
                    evidence_ids_json=json.dumps(["ev_positioning", "ev_feature", "ev_price"]),
                    field_evidence_ids_json=json.dumps(
                        {
                            "positioning": ["ev_positioning"],
                            "core_features_json": ["ev_feature"],
                            "pricing_summary": ["ev_price"],
                            "weaknesses_json": ["ev_price"],
                        },
                        ensure_ascii=False,
                    ),
                    item_evidence_bindings_json=json.dumps(
                        {
                            "weaknesses_json": [
                                {
                                    "item_index": 0,
                                    "claim": "Paid subscriptions are non-refundable.",
                                    "evidence_ids": ["ev_price"],
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                )
            ],
            "evidence": evidence,
            "feedback_loop_count": 1,
            "qa_issue_verification_count": 0,
            "qa_issue_checklist": [
                {
                    "id": "qai_citation_bad_binding",
                    "dimension": "citation_accuracy",
                    "severity": "minor",
                    "competitor_name": "Acme",
                    "description": "weaknesses字段引用了ev_bad，该证据属于核心功能维度，与弱点无关。",
                    "fix_suggestion": "从weaknesses_json中移除ev_bad。",
                    "status": "open",
                    "first_seen_iteration": 1,
                    "last_seen_iteration": 1,
                    "fields": ["weaknesses_json"],
                }
            ],
        },
        FakeQALLM(
            verify_result={
                "resolutions": [
                    {
                        "issue_id": "qai_citation_bad_binding",
                        "status": "resolved",
                        "resolution_reason": "已移除错误证据。",
                    }
                ],
                "retry_instructions": None,
            }
        ),
    )

    assert result["qa_result"]["decision"] == "pass"
    assert result["qa_issue_checklist"][0]["status"] == "resolved"


def test_stale_item_binding_issue_resolves_when_item_no_longer_exists():
    evidence = [
        {
            "id": "ev_positioning",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "reference_id": 1,
            "confidence": 0.9,
        },
        {
            "id": "ev_feature",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 2,
            "confidence": 0.9,
        },
        {
            "id": "ev_pricing",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "价格与商业模式",
            "reference_id": 3,
            "confidence": 0.9,
        },
        {
            "id": "ev_pain",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 4,
            "confidence": 0.9,
            "sentiment": "negative",
            "support_type": "direct",
        },
    ]
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    weaknesses_json=json.dumps(["Users report complex setup."]),
                    evidence_ids_json=json.dumps(
                        ["ev_positioning", "ev_feature", "ev_pricing", "ev_pain"]
                    ),
                    field_evidence_ids_json=json.dumps(
                        {
                            "positioning": ["ev_positioning"],
                            "core_features_json": ["ev_feature"],
                            "pricing_summary": ["ev_pricing"],
                            "weaknesses_json": ["ev_pain"],
                        },
                        ensure_ascii=False,
                    ),
                    item_evidence_bindings_json=json.dumps(
                        {
                            "weaknesses_json": [
                                {
                                    "item_index": 0,
                                    "claim": "Users report complex setup.",
                                    "evidence_ids": ["ev_pain"],
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                )
            ],
            "evidence": evidence,
            "feedback_loop_count": 2,
            "qa_issue_checklist": [
                {
                    "id": "det_item_ev_comp_1_weaknesses_json_1",
                    "dimension": "evidence_grounding",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "Acme 的劣势或痛点第 2 条缺少条目级有效证据绑定。",
                    "fix_suggestion": "绑定 ev_pain。",
                    "status": "unresolved",
                    "first_seen_iteration": 1,
                    "last_seen_iteration": 2,
                    "fields": ["weaknesses_json", "item_evidence_bindings_json"],
                    "claim": "Old second weakness",
                }
            ],
        },
        FakeQALLM(),
    )

    assert result["qa_result"]["decision"] == "pass"
    assert result["qa_issue_checklist"][0]["status"] == "resolved"
    assert "已不存在" in result["qa_issue_checklist"][0]["resolution_reason"]


def test_stale_no_weakness_claim_resolves_when_real_weaknesses_exist():
    evidence = [
        {
            "id": "ev_positioning",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "reference_id": 1,
            "confidence": 0.9,
        },
        {
            "id": "ev_feature",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 2,
            "confidence": 0.9,
        },
        {
            "id": "ev_pricing",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "价格与商业模式",
            "reference_id": 3,
            "confidence": 0.9,
        },
        {
            "id": "ev_pain",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 4,
            "confidence": 0.9,
            "sentiment": "negative",
            "evidence_role": "user_complaint",
            "support_type": "direct",
        },
    ]
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    weaknesses_json=json.dumps(["Users report complex setup."]),
                    evidence_ids_json=json.dumps(
                        ["ev_positioning", "ev_feature", "ev_pricing", "ev_pain"]
                    ),
                    field_evidence_ids_json=json.dumps(
                        {
                            "positioning": ["ev_positioning"],
                            "core_features_json": ["ev_feature"],
                            "pricing_summary": ["ev_pricing"],
                            "weaknesses_json": ["ev_pain"],
                        },
                        ensure_ascii=False,
                    ),
                    item_evidence_bindings_json=json.dumps(
                        {
                            "weaknesses_json": [
                                {
                                    "item_index": 0,
                                    "claim": "Users report complex setup.",
                                    "evidence_ids": ["ev_pain"],
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                )
            ],
            "evidence": evidence,
            "feedback_loop_count": 2,
            "qa_issue_checklist": [
                {
                    "id": "qai_old_no_weakness",
                    "dimension": "factual_plausibility",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "weaknesses字段声称'未发现明显的劣势或用户痛点'，但证据显示存在痛点。",
                    "fix_suggestion": "删除或修改该结论，如实反映已知劣势。",
                    "status": "unresolved",
                    "first_seen_iteration": 1,
                    "last_seen_iteration": 2,
                    "fields": ["weaknesses_json"],
                    "claim": "未发现明显的劣势或用户痛点",
                }
            ],
        },
        FakeQALLM(),
    )

    assert result["qa_result"]["decision"] == "pass"
    assert result["qa_issue_checklist"][0]["status"] == "resolved"
    assert "旧结论已不存在" in result["qa_issue_checklist"][0]["resolution_reason"]


def test_repeated_consistency_issue_resolves_when_fields_now_deep_enough():
    description = "Acme结构化分析与其他竞品相比明显简略（如核心功能仅列3项，目标用户仅写'开发者'），信息深度不足。"
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    target_users=json.dumps(["个人开发者", "团队开发者", "企业开发者"]),
                    core_features_json=json.dumps(
                        ["代码生成", "智能补全", "调试能力", "Agent模式", "多模型选择"]
                    ),
                )
            ],
            "evidence": referenced_evidence_items(),
            "feedback_loop_count": 1,
            "qa_issue_checklist": [
                {
                    "id": "qai_consistency_depth",
                    "dimension": "cross_competitor_consistency",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": description,
                    "fix_suggestion": "补充更多核心功能细节，扩展目标用户描述。",
                    "status": "unresolved",
                    "first_seen_iteration": 1,
                    "last_seen_iteration": 1,
                    "fields": ["target_users", "core_features_json"],
                    "issue_type": "consistency_gap",
                }
            ],
        },
        FakeQALLM(
            qa_result={
                "dimension_scores": {
                    "evidence_grounding": 0.98,
                    "citation_accuracy": 0.98,
                    "schema_completeness": 0.98,
                    "coverage_gaps": 0.98,
                    "cross_competitor_consistency": 0.98,
                    "factual_plausibility": 0.98,
                },
                "issues": [
                    {
                        "dimension": "cross_competitor_consistency",
                        "severity": "major",
                        "competitor_name": "Acme",
                        "description": description,
                        "fix_suggestion": "补充更多核心功能细节，扩展目标用户描述。",
                        "fields": ["target_users", "core_features_json"],
                        "issue_type": "consistency_gap",
                    }
                ],
                "retry_queries": [],
                "retry_instructions": None,
            }
        ),
    )

    assert result["qa_result"]["decision"] == "pass"
    assert result["qa_issue_checklist"][0]["status"] == "resolved"
    assert "信息深度不足" in result["qa_issue_checklist"][0]["resolution_reason"]


def test_issue_verification_accepts_resolved_consistency_when_depth_sufficient():
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    target_users=json.dumps(["个人开发者", "团队开发者", "企业开发者"]),
                    core_features_json=json.dumps(
                        ["代码生成", "智能补全", "调试能力", "Agent模式", "多模型选择"]
                    ),
                )
            ],
            "evidence": referenced_evidence_items(),
            "feedback_loop_count": 1,
            "qa_issue_verification_count": 0,
            "qa_issue_checklist": [
                {
                    "id": "qai_consistency_depth",
                    "dimension": "cross_competitor_consistency",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "Acme结构化分析明显简略，核心功能仅列3项，目标用户仅写'开发者'。",
                    "fix_suggestion": "补充更多核心功能细节，扩展目标用户描述。",
                    "status": "open",
                    "first_seen_iteration": 1,
                    "last_seen_iteration": 1,
                    "fields": ["target_users", "core_features_json"],
                    "issue_type": "consistency_gap",
                }
            ],
        },
        FakeQALLM(
            verify_result={
                "resolutions": [
                    {
                        "issue_id": "qai_consistency_depth",
                        "status": "resolved",
                        "resolution_reason": "已经补足目标用户和核心功能深度。",
                    }
                ],
                "retry_instructions": None,
            }
        ),
    )

    assert result["qa_result"]["decision"] == "pass"
    assert result["qa_issue_checklist"][0]["status"] == "resolved"


def test_bad_binding_issue_resolves_when_bad_removed_and_preferred_added():
    evidence = [
        {
            "id": "ev_positioning",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "reference_id": 1,
            "confidence": 0.9,
        },
        {
            "id": "ev_feature",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 2,
            "confidence": 0.9,
        },
        {
            "id": "ev_pricing",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "价格与商业模式",
            "reference_id": 3,
            "confidence": 0.9,
        },
        {
            "id": "ev_bad",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 4,
            "confidence": 0.9,
            "sentiment": "positive",
            "evidence_role": "user_praise",
        },
        {
            "id": "ev_limit",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 5,
            "confidence": 0.9,
            "sentiment": "negative",
            "evidence_role": "limitation",
            "support_type": "direct",
        },
    ]
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    weaknesses_json=json.dumps(["Advanced features have usage limitations."]),
                    evidence_ids_json=json.dumps(
                        ["ev_positioning", "ev_feature", "ev_pricing", "ev_limit"]
                    ),
                    field_evidence_ids_json=json.dumps(
                        {
                            "positioning": ["ev_positioning"],
                            "core_features_json": ["ev_feature"],
                            "pricing_summary": ["ev_pricing"],
                            "weaknesses_json": ["ev_limit"],
                        },
                        ensure_ascii=False,
                    ),
                    item_evidence_bindings_json=json.dumps(
                        {
                            "weaknesses_json": [
                                {
                                    "item_index": 0,
                                    "claim": "Advanced features have usage limitations.",
                                    "evidence_ids": ["ev_limit"],
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                )
            ],
            "evidence": evidence,
            "feedback_loop_count": 2,
            "qa_issue_checklist": [
                {
                    "id": "qai_bad_binding",
                    "dimension": "citation_accuracy",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "weaknesses_json引用的ev_bad是正面用户评价，不能支撑劣势描述。",
                    "fix_suggestion": "将引用替换为ev_limit。",
                    "status": "unresolved",
                    "first_seen_iteration": 1,
                    "last_seen_iteration": 2,
                    "fields": ["weaknesses_json"],
                    "bad_evidence_ids": ["ev_bad"],
                    "preferred_evidence_ids": ["ev_limit"],
                }
            ],
        },
        FakeQALLM(),
    )

    assert result["qa_result"]["decision"] == "pass"
    assert result["qa_issue_checklist"][0]["status"] == "resolved"
    assert "错误证据已移除" in result["qa_issue_checklist"][0]["resolution_reason"]


def test_field_evidence_dangling_id_is_citation_issue():
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    evidence_ids_json=json.dumps(["ev_1"]),
                    field_evidence_ids_json=json.dumps(
                        {"weaknesses_json": ["ev_missing"]}, ensure_ascii=False
                    ),
                )
            ],
            "evidence": [
                {
                    "id": "ev_1",
                    "competitor_id": "comp_1",
                    "related_product": "Acme",
                    "related_dimension": "用户评价与痛点",
                    "reference_id": 1,
                    "confidence": 0.9,
                },
                {
                    "id": "ev_2",
                    "competitor_id": "comp_1",
                    "related_product": "Acme",
                    "related_dimension": "核心功能",
                    "reference_id": 2,
                    "confidence": 0.9,
                },
                {
                    "id": "ev_3",
                    "competitor_id": "comp_1",
                    "related_product": "Acme",
                    "related_dimension": "价格与商业模式",
                    "reference_id": 3,
                    "confidence": 0.9,
                },
            ],
            "feedback_loop_count": 0,
        },
        FakeQALLM(),
    )

    assert result["qa_result"]["decision"] == "retry_analysis"
    assert any(
        issue["dimension"] == "citation_accuracy"
        and "不存在的证据 ID" in issue["description"]
        for issue in result["qa_result"]["issues"]
    )


def test_pricing_summary_contradicting_specific_price_evidence_is_factual_issue():
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    pricing_summary="证据未提供具体定价金额。",
                    evidence_ids_json=json.dumps(["ev_price", "ev_positioning", "ev_feature"]),
                    field_evidence_ids_json=json.dumps(
                        {
                            "positioning": ["ev_positioning"],
                            "core_features_json": ["ev_feature"],
                            "pricing_summary": ["ev_price"],
                        },
                        ensure_ascii=False,
                    ),
                )
            ],
            "evidence": [
                {
                    "id": "ev_positioning",
                    "competitor_id": "comp_1",
                    "related_product": "Acme",
                    "related_dimension": "产品定位",
                    "reference_id": 1,
                    "confidence": 0.9,
                },
                {
                    "id": "ev_feature",
                    "competitor_id": "comp_1",
                    "related_product": "Acme",
                    "related_dimension": "核心功能",
                    "reference_id": 2,
                    "confidence": 0.9,
                },
                {
                    "id": "ev_price",
                    "competitor_id": "comp_1",
                    "related_product": "Acme",
                    "related_dimension": "价格与商业模式",
                    "reference_id": 3,
                    "confidence": 0.9,
                    "claim": "Acme Pro costs $20/month and includes a Free plan.",
                    "summary": "Acme has Free and Pro plans at $20/month.",
                },
            ],
            "feedback_loop_count": 0,
        },
        FakeQALLM(),
    )

    assert result["qa_result"]["decision"] == "retry_analysis"
    assert any(
        issue["id"] == "det_pricing_fact_comp_1"
        for issue in result["qa_result"]["issues"]
    )


def test_pass_with_minor_issue_still_records_issue_in_checklist():
    evidence = [
        {
            "id": "ev_positioning",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "reference_id": 1,
            "confidence": 0.9,
        },
        {
            "id": "ev_feature",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "reference_id": 2,
            "confidence": 0.9,
        },
        {
            "id": "ev_pricing",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "价格与商业模式",
            "reference_id": 3,
            "confidence": 0.9,
        },
        {
            "id": "ev_pain",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "用户评价与痛点",
            "reference_id": 4,
            "confidence": 0.9,
        },
    ]
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(
                    evidence_ids_json=json.dumps(
                        ["ev_positioning", "ev_feature", "ev_pricing", "ev_pain"]
                    )
                )
            ],
            "evidence": evidence,
        },
        FakeQALLM(
            qa_result={
                "dimension_scores": {
                    "evidence_grounding": 0.95,
                    "citation_accuracy": 0.95,
                    "schema_completeness": 0.95,
                    "coverage_gaps": 0.95,
                    "cross_competitor_consistency": 0.95,
                    "factual_plausibility": 0.95,
                },
                "issues": [
                    {
                        "dimension": "evidence_grounding",
                        "severity": "minor",
                        "competitor_name": "Acme",
                        "description": "Target users could use more direct evidence.",
                        "fix_suggestion": "Add one direct evidence id.",
                    }
                ],
                "retry_queries": [],
                "retry_instructions": None,
            }
        ),
    )

    assert result["qa_result"]["decision"] == "pass"
    assert any(
        issue["description"] == "Target users could use more direct evidence."
        for issue in result["qa_issue_checklist"]
    )


def test_generic_source_ref_format_issue_does_not_mark_refs_for_removal():
    issue = {
        "dimension": "citation_accuracy",
        "description": "所有竞品分析中引用方式均为source_ref（如[3]）而非evidence_id（如ev_...），导致引用不精确。",
        "fix_suggestion": "将每个引用替换为具体的evidence_id。",
    }

    assert _reference_ids_requiring_removal(issue) == set()


def test_specific_bad_source_ref_issue_still_marks_ref_for_removal():
    issue = {
        "dimension": "evidence_grounding",
        "description": "定位维度引用了source_ref [3]，该来源主要讨论定价模式变更，不支持定位描述。",
        "fix_suggestion": "改用source_ref [5]或调整结论。",
    }

    assert _reference_ids_requiring_removal(issue) == {3, 5}


def test_issue_verification_does_not_consume_full_check_budget():
    state = {
        "analyses": [complete_analysis()],
        "evidence": evidence_items(),
        "feedback_loop_count": 1,
        "qa_issue_verification_count": 0,
        "qa_result": {
            "overall_score": 0.72,
            "dimension_scores": {
                "evidence_grounding": 0.72,
                "citation_accuracy": 0.8,
                "schema_completeness": 0.8,
                "coverage_gaps": 0.8,
                "cross_competitor_consistency": 0.8,
                "factual_plausibility": 0.8,
            },
        },
        "qa_issue_checklist": [
            {
                "id": "qai_open",
                "dimension": "schema_completeness",
                "severity": "major",
                "competitor_name": "Acme",
                "description": "Pricing is still vague.",
                "fix_suggestion": "Add pricing details.",
                "status": "open",
                "first_seen_iteration": 1,
                "last_seen_iteration": 1,
            }
        ],
    }
    llm = FakeQALLM(
        verify_result={
            "resolutions": [
                {
                    "issue_id": "qai_open",
                    "status": "open",
                    "resolution_reason": "Still missing.",
                    "retry_queries": [],
                }
            ],
            "retry_instructions": "Add pricing details.",
        }
    )

    result = quality_check_node(state, llm)

    assert result["feedback_loop_count"] == 1
    assert result["qa_issue_verification_count"] == 1
    assert result["qa_result"]["check_phase"] == "issue_verification"
    assert result["qa_result"]["decision"] == "retry_analysis"


def test_major_analysis_issue_blocks_pass_even_when_scores_are_high():
    llm = FakeQALLM(
        qa_result={
            "dimension_scores": {
                "evidence_grounding": 0.9,
                "citation_accuracy": 0.9,
                "schema_completeness": 0.9,
                "coverage_gaps": 0.9,
                "cross_competitor_consistency": 0.9,
                "factual_plausibility": 0.9,
            },
            "issues": [
                {
                    "dimension": "schema_completeness",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "Pricing is too vague.",
                    "fix_suggestion": "Add specific pricing details.",
                }
            ],
            "retry_queries": [],
            "retry_instructions": "Add specific pricing details.",
        }
    )

    result = quality_check_node(
        {"analyses": [complete_analysis()], "evidence": evidence_items()},
        llm,
    )

    assert result["qa_result"]["decision"] == "retry_analysis"
    assert result["qa_result"]["dimension_scores"]["schema_completeness"] == 0.6


def test_deterministic_invalid_citation_creates_retry_analysis_issue():
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(evidence_ids_json=json.dumps(["ev_1", "missing"]))
            ],
            "evidence": evidence_items(),
        },
        FakeQALLM(),
    )

    assert result["qa_result"]["decision"] == "retry_analysis"
    assert any(
        issue["dimension"] == "citation_accuracy"
        for issue in result["qa_result"]["issues"]
    )
    assert result["qa_result"]["dimension_scores"]["citation_accuracy"] == 0.6


def test_third_full_check_can_still_enter_final_issue_verification_group():
    result = quality_check_node(
        {
            "analyses": [complete_analysis()],
            "evidence": evidence_items(),
            "feedback_loop_count": 2,
        },
        FakeQALLM(
            qa_result={
                "dimension_scores": {
                    "evidence_grounding": 0.9,
                    "citation_accuracy": 0.9,
                    "schema_completeness": 0.9,
                    "coverage_gaps": 0.9,
                    "cross_competitor_consistency": 0.9,
                    "factual_plausibility": 0.9,
                },
                "issues": [
                    {
                        "dimension": "schema_completeness",
                        "severity": "major",
                        "competitor_name": "Acme",
                        "description": "Pricing is too vague.",
                        "fix_suggestion": "Add specific pricing details.",
                    }
                ],
                "retry_queries": [],
                "retry_instructions": "Add specific pricing details.",
            }
        ),
    )

    assert result["feedback_loop_count"] == 3
    assert result["qa_issue_verification_count"] == 0
    assert result["qa_result"]["check_phase"] == "full_check"
    assert result["qa_result"]["decision"] == "retry_analysis"


def test_score_stall_does_not_force_pass_before_retry_budget_is_exhausted():
    result = quality_check_node(
        {
            "analyses": [complete_analysis()],
            "evidence": evidence_items(),
            "feedback_loop_count": 1,
            "qa_result": {
                "overall_score": 0.8,
                "dimension_scores": {
                    "evidence_grounding": 0.8,
                    "citation_accuracy": 0.8,
                    "schema_completeness": 0.8,
                    "coverage_gaps": 0.8,
                    "cross_competitor_consistency": 0.8,
                    "factual_plausibility": 0.8,
                },
            },
        },
        FakeQALLM(
            qa_result={
                "dimension_scores": {
                    "evidence_grounding": 0.8,
                    "citation_accuracy": 0.8,
                    "schema_completeness": 0.8,
                    "coverage_gaps": 0.8,
                    "cross_competitor_consistency": 0.8,
                    "factual_plausibility": 0.8,
                },
                "issues": [
                    {
                        "dimension": "schema_completeness",
                        "severity": "major",
                        "competitor_name": "Acme",
                        "description": "Pricing is still vague.",
                        "fix_suggestion": "Add pricing details.",
                    }
                ],
                "retry_queries": [],
                "retry_instructions": "Add pricing details.",
            }
        ),
    )

    assert result["feedback_loop_count"] == 2
    assert result["qa_result"]["decision"] == "retry_analysis"
    assert result["qa_result"]["forced_pass"] is False


def test_verification_limit_falls_through_to_full_check_without_hidden_verify_call():
    llm = FakeQALLM()

    result = quality_check_node(
        {
            "analyses": [complete_analysis()],
            "evidence": evidence_items(),
            "feedback_loop_count": 1,
            "qa_issue_verification_count": 2,
            "qa_issue_checklist": [
                {
                    "id": "qai_open",
                    "dimension": "schema_completeness",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "Pricing is still vague.",
                    "fix_suggestion": "Add pricing details.",
                    "status": "open",
                    "first_seen_iteration": 1,
                    "last_seen_iteration": 1,
                }
            ],
        },
        llm,
    )

    assert llm.qa_verify_calls == 0
    assert llm.qa_check_calls == 1
    assert result["feedback_loop_count"] == 2
    assert result["qa_issue_verification_count"] == 0
    assert result["qa_result"]["check_phase"] == "full_check"


def test_resolved_verification_before_final_full_check_runs_next_full_check():
    llm = FakeQALLM(
        verify_result={
            "resolutions": [
                {
                    "issue_id": "qai_open",
                    "status": "resolved",
                    "resolution_reason": "Resolved.",
                    "retry_queries": [],
                }
            ],
            "retry_instructions": None,
        }
    )

    result = quality_check_node(
        {
            "analyses": [complete_analysis()],
            "evidence": evidence_items(),
            "feedback_loop_count": 2,
            "qa_issue_verification_count": 0,
            "qa_issue_checklist": [
                {
                    "id": "qai_open",
                    "dimension": "schema_completeness",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "Pricing is still vague.",
                    "fix_suggestion": "Add pricing details.",
                    "status": "open",
                    "first_seen_iteration": 2,
                    "last_seen_iteration": 2,
                }
            ],
        },
        llm,
    )

    assert llm.qa_verify_calls == 1
    assert llm.qa_check_calls == 1
    assert result["feedback_loop_count"] == 3
    assert result["qa_issue_verification_count"] == 0
    assert result["qa_result"]["check_phase"] == "full_check"


def test_resolved_verification_after_final_full_check_does_not_run_fourth_full_check():
    low_scores = {
        "evidence_grounding": 0.8,
        "citation_accuracy": 0.8,
        "schema_completeness": 0.8,
        "coverage_gaps": 0.8,
        "cross_competitor_consistency": 0.8,
        "factual_plausibility": 0.8,
    }
    llm = FakeQALLM(
        verify_result={
            "resolutions": [
                {
                    "issue_id": "qai_open",
                    "status": "resolved",
                    "resolution_reason": "Resolved.",
                    "retry_queries": [],
                }
            ],
            "retry_instructions": None,
        }
    )

    result = quality_check_node(
        {
            "analyses": [complete_analysis()],
            "evidence": evidence_items(),
            "feedback_loop_count": 3,
            "qa_issue_verification_count": 0,
            "qa_result": {
                "overall_score": 0.8,
                "dimension_scores": low_scores,
            },
            "qa_issue_checklist": [
                {
                    "id": "qai_open",
                    "dimension": "schema_completeness",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "Pricing is still vague.",
                    "fix_suggestion": "Add pricing details.",
                    "status": "open",
                    "first_seen_iteration": 3,
                    "last_seen_iteration": 3,
                }
            ],
        },
        llm,
    )

    assert llm.qa_verify_calls == 1
    assert llm.qa_check_calls == 0
    assert result["feedback_loop_count"] == 3
    assert result["qa_issue_verification_count"] == 1
    assert result["qa_result"]["check_phase"] == "issue_verification"
    assert result["qa_result"]["decision"] == "pass"
    assert result["qa_result"]["forced_pass"] is True


def test_final_issue_verification_group_finishes_with_quality_warning():
    low_scores = {
        "evidence_grounding": 0.4,
        "citation_accuracy": 0.4,
        "schema_completeness": 0.4,
        "coverage_gaps": 0.4,
        "cross_competitor_consistency": 0.4,
        "factual_plausibility": 0.4,
    }
    result = quality_check_node(
        {
            "analyses": [complete_analysis()],
            "evidence": evidence_items(),
            "feedback_loop_count": 3,
            "qa_issue_verification_count": 1,
            "qa_result": {
                "overall_score": 0.4,
                "dimension_scores": low_scores,
            },
            "qa_issue_checklist": [
                {
                    "id": "qai_open",
                    "dimension": "schema_completeness",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "Pricing is still vague.",
                    "fix_suggestion": "Add pricing details.",
                    "status": "open",
                    "first_seen_iteration": 3,
                    "last_seen_iteration": 3,
                }
            ],
        },
        FakeQALLM(
            verify_result={
                "resolutions": [
                    {
                        "issue_id": "qai_open",
                        "status": "open",
                        "resolution_reason": "Still missing.",
                        "retry_queries": [],
                    }
                ],
                "retry_instructions": "Add pricing details.",
            }
        ),
    )

    assert result["feedback_loop_count"] == 3
    assert result["qa_issue_verification_count"] == 2
    assert result["qa_result"]["check_phase"] == "issue_verification"
    assert result["qa_result"]["decision"] == "pass_with_quality_warning"
    assert result["qa_result"]["forced_pass"] is True
    assert result["qa_result"]["quality_warning"] is True


def test_forced_pass_with_mid_score_and_open_major_issue_warns():
    scores = {
        "evidence_grounding": 0.6,
        "citation_accuracy": 0.6,
        "schema_completeness": 0.6,
        "coverage_gaps": 0.7,
        "cross_competitor_consistency": 0.7,
        "factual_plausibility": 0.7,
    }
    result = quality_check_node(
        {
            "analyses": [complete_analysis()],
            "evidence": evidence_items(),
            "feedback_loop_count": 3,
            "qa_issue_verification_count": 2,
            "qa_result": {
                "overall_score": 0.64,
                "dimension_scores": scores,
            },
            "qa_issue_checklist": [
                {
                    "id": "qai_open",
                    "dimension": "schema_completeness",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "Pricing is still vague.",
                    "fix_suggestion": "Add pricing details.",
                    "status": "open",
                    "first_seen_iteration": 3,
                    "last_seen_iteration": 3,
                }
            ],
        },
        FakeQALLM(),
    )

    assert result["qa_result"]["decision"] == "pass_with_quality_warning"
    assert result["qa_result"]["forced_pass"] is True
    assert result["qa_result"]["quality_warning"] is True


def test_weak_resolution_reason_does_not_close_schema_issue():
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(weaknesses_json=json.dumps(["证据中未涉及"]))
            ],
            "evidence": evidence_items(),
            "feedback_loop_count": 1,
            "qa_issue_verification_count": 0,
            "qa_result": {
                "overall_score": 0.6,
                "dimension_scores": {
                    "evidence_grounding": 0.6,
                    "citation_accuracy": 0.6,
                    "schema_completeness": 0.6,
                    "coverage_gaps": 0.7,
                    "cross_competitor_consistency": 0.7,
                    "factual_plausibility": 0.7,
                },
            },
            "qa_issue_checklist": [
                {
                    "id": "qai_schema",
                    "dimension": "schema_completeness",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "Acme 的结构化分析字段不完整：劣势或痛点",
                    "fix_suggestion": "重新分析 Acme，补齐劣势或痛点",
                    "status": "open",
                    "first_seen_iteration": 1,
                    "last_seen_iteration": 1,
                }
            ],
        },
        FakeQALLM(
            verify_result={
                "resolutions": [
                    {
                        "issue_id": "qai_schema",
                        "status": "resolved",
                        "resolution_reason": "Acme 当前证据数为 3。",
                        "retry_queries": [],
                    }
                ],
                "retry_instructions": None,
            }
        ),
    )

    assert result["qa_result"]["check_phase"] == "issue_verification"
    assert result["qa_result"]["decision"] == "retry_analysis"
    assert result["qa_result"]["issues"][0]["status"] == "open"
    assert result["qa_issue_checklist"][0]["status"] == "open"
    assert "系统复核未通过" in result["qa_result"]["issues"][0]["resolution_reason"]


def test_null_reference_id_is_citation_issue_but_repeated_source_ref_is_allowed():
    evidence = [
        {
            "id": "ev_1",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "产品定位",
            "confidence": 0.9,
            "reference_id": 7,
        },
        {
            "id": "ev_2",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "核心功能",
            "confidence": 0.9,
            "reference_id": 7,
        },
        {
            "id": "ev_3",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "价格与商业模式",
            "confidence": 0.9,
            "reference_id": None,
        },
    ]

    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(evidence_ids_json=json.dumps(["ev_1", "ev_2", "ev_3"]))
            ],
            "evidence": evidence,
        },
        FakeQALLM(),
    )

    citation_issues = [
        issue
        for issue in result["qa_result"]["issues"]
        if issue["dimension"] == "citation_accuracy"
    ]
    assert len(citation_issues) == 1
    assert "缺少来源编号" in citation_issues[0]["description"]


def test_terminal_unresolved_issue_is_reported_without_more_verification():
    llm = FakeQALLM(
        verify_result={
            "resolutions": [
                {
                    "issue_id": "qai_unresolved",
                    "status": "open",
                    "resolution_reason": "Still lacks direct references.",
                    "retry_queries": [],
                }
            ],
            "retry_instructions": "Add evidence references.",
        }
    )
    result = quality_check_node(
        {
            "analyses": [complete_analysis(pricing_summary="Pricing is now specific.")],
            "evidence": evidence_items(),
            "feedback_loop_count": 3,
            "qa_issue_verification_count": 1,
            "qa_result": {
                "overall_score": 0.82,
                "dimension_scores": {
                    "evidence_grounding": 0.8,
                    "citation_accuracy": 0.9,
                    "schema_completeness": 0.8,
                    "coverage_gaps": 1.0,
                    "cross_competitor_consistency": 0.85,
                    "factual_plausibility": 0.8,
                },
            },
            "qa_issue_checklist": [
                {
                    "id": "qai_unresolved",
                    "dimension": "evidence_grounding",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "Pricing field lacks evidence references.",
                    "fix_suggestion": "Add evidence references.",
                    "status": "unresolved",
                    "first_seen_iteration": 2,
                    "last_seen_iteration": 3,
                }
            ],
        },
        llm,
    )

    assert llm.qa_verify_calls == 0
    assert llm.qa_check_calls == 0
    assert result["qa_result"]["check_phase"] == "full_check"
    assert result["qa_result"]["decision"] == "pass_with_quality_warning"
    assert result["qa_result"]["forced_pass"] is True
    assert [issue["id"] for issue in result["qa_result"]["issues"]] == [
        "qai_unresolved"
    ]
    assert result["qa_result"]["issues"][0]["status"] == "unresolved"
    assert result["qa_issue_checklist"][0]["status"] == "unresolved"


def test_coverage_issue_closes_when_evidence_pool_is_sufficient_even_if_analysis_uses_subset():
    evidence = [
        {
            "id": f"ev_price_{idx}",
            "competitor_id": "comp_1",
            "related_product": "Acme",
            "related_dimension": "价格与商业模式",
            "confidence": 0.9,
            "reference_id": idx,
        }
        for idx in range(1, 4)
    ]
    result = quality_check_node(
        {
            "analyses": [
                complete_analysis(evidence_ids_json=json.dumps(["ev_price_1"]))
            ],
            "evidence": evidence,
            "feedback_loop_count": 1,
            "qa_issue_verification_count": 0,
            "qa_result": {
                "overall_score": 0.7,
                "dimension_scores": {
                    "evidence_grounding": 0.7,
                    "citation_accuracy": 0.8,
                    "schema_completeness": 0.8,
                    "coverage_gaps": 0.6,
                    "cross_competitor_consistency": 0.8,
                    "factual_plausibility": 0.8,
                },
            },
            "qa_issue_checklist": [
                {
                    "id": "qai_pricing_coverage",
                    "dimension": "coverage_gaps",
                    "severity": "major",
                    "competitor_name": "Acme",
                    "description": "Acme 的价格与商业模式维度仅引用 1 条证据，低于至少 3 条。",
                    "fix_suggestion": "补充更多定价证据。",
                    "status": "open",
                    "first_seen_iteration": 1,
                    "last_seen_iteration": 1,
                }
            ],
        },
        FakeQALLM(
            verify_result={
                "resolutions": [
                    {
                        "issue_id": "qai_pricing_coverage",
                        "status": "open",
                        "resolution_reason": "分析仍只引用一条价格证据。",
                        "retry_queries": [],
                    }
                ],
                "retry_instructions": "继续补充价格证据。",
            }
        ),
    )

    checklist = result["qa_issue_checklist"]
    assert checklist[0]["status"] == "resolved"
    assert "允许选择部分代表性证据" in checklist[0]["resolution_reason"]
