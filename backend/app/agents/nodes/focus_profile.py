from typing import Any

from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider


def focus_profile_node(state: AgentState, llm: LLMProvider) -> AgentState:
    requirement = state["requirement"]
    existing_profile = requirement.get("focus_profile") if isinstance(requirement, dict) else None
    if isinstance(existing_profile, dict) and not existing_profile.get("clarification_needed"):
        # Resuming after clarification — profile already validated, pass through
        return {**state}

    focus_profile = normalize_focus_profile(
        llm.extract_focus_profile(state["user_requirement"], requirement)
    )
    enriched_requirement = {**requirement, "focus_profile": focus_profile}
    return {
        **state,
        "requirement": enriched_requirement,
    }


def focus_profile_route(state: AgentState) -> str:
    requirement = state.get("requirement", {})
    profile = requirement.get("focus_profile", {}) if isinstance(requirement, dict) else {}
    return "clarify" if profile.get("clarification_needed") else "continue"


def normalize_focus_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    profile = raw if isinstance(raw, dict) else {}
    explicit = _focus_list(profile.get("explicit_focuses"))
    inferred = _focus_list(profile.get("inferred_focuses"))
    question = str(profile.get("clarifying_question") or "").strip()
    needs_clarification = bool(profile.get("clarification_needed")) and bool(question)
    return {
        "explicit_focuses": explicit,
        "inferred_focuses": inferred,
        "clarification_needed": needs_clarification,
        "clarifying_question": question if needs_clarification else None,
        "assumptions": _string_list(profile.get("assumptions")),
    }


def _focus_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("key") or "").strip()
        if not label:
            continue
        normalized.append(
            {
                "key": str(item.get("key") or _key_from_label(label)).strip()[:64],
                "label": label[:80],
                "priority": str(item.get("priority") or "medium").strip()[:16],
                "evidence_expectation": str(item.get("evidence_expectation") or "").strip()[:240],
                "query_terms": _string_list(item.get("query_terms"))[:6],
            }
        )
    return normalized[:6]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _key_from_label(label: str) -> str:
    return "_".join(label.lower().split())[:64] or "focus"
