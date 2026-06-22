from app.agents.nodes.focus_profile import focus_profile_node


class DirtyFocusLLM:
    def extract_focus_profile(self, user_requirement, requirement):
        return {
            "explicit_focuses": [
                {
                    "key": "function_comparison",
                    "label": "功能对比",
                    "priority": "medium",
                    "evidence_expectation": "功能差异",
                    "query_terms": ["AI coding agent features comparison"],
                },
                {
                    "key": "pricing_strategy",
                    "label": "定价策略",
                    "priority": "medium",
                    "evidence_expectation": "价格与套餐",
                    "query_terms": ["AI coding agent pricing comparison"],
                },
            ],
            "inferred_focuses": [],
            "clarification_needed": False,
            "clarifying_question": None,
            "assumptions": [],
        }


def test_focus_profile_drops_default_dimensions_not_grounded_in_user_text():
    result = focus_profile_node(
        {
            "user_requirement": "编程智能体",
            "requirement": {
                "domain": "AI编程助手",
                "analysis_dimensions": ["功能对比", "定价策略"],
            },
        },
        DirtyFocusLLM(),
    )

    profile = result["requirement"]["focus_profile"]
    assert profile["explicit_focuses"] == []
    assert profile["inferred_focuses"] == []


def test_focus_profile_keeps_focus_grounded_in_user_text():
    result = focus_profile_node(
        {
            "user_requirement": "编程智能体，重点关注功能和价格",
            "requirement": {
                "domain": "AI编程助手",
                "analysis_dimensions": ["功能对比", "定价策略"],
            },
        },
        DirtyFocusLLM(),
    )

    profile = result["requirement"]["focus_profile"]
    assert [item["label"] for item in profile["explicit_focuses"]] == [
        "功能对比",
        "定价策略",
    ]
