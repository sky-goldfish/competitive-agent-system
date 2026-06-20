import json

from app.agents.nodes.quality_check import (
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
