import logging
from typing import Any

from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)


def focus_profile_node(state: AgentState, llm: LLMProvider) -> AgentState:
    requirement = state.get("requirement", {})
    existing_profile = (
        requirement.get("focus_profile") if isinstance(requirement, dict) else None
    )
    if isinstance(existing_profile, dict) and not existing_profile.get(
        "clarification_needed"
    ):
        return {**state}

    raw_result = llm.extract_focus_profile(state["user_requirement"], requirement)
    focus_profile = normalize_focus_profile(raw_result)

    if not focus_profile.get("clarification_needed"):
        user_text = (state.get("user_requirement") or "").strip()
        if _is_vague_requirement(user_text) and not focus_profile.get(
            "explicit_focuses"
        ):
            logger.info(
                "Safety-net: forcing clarification for vague input (len=%d): %.80s",
                len(user_text),
                user_text,
            )
            focus_profile["clarification_needed"] = True
            focus_profile["clarifying_question"] = (
                focus_profile.get("clarifying_question")
                or "请补充这份报告最需要关注的判断维度。"
            )

    logger.debug(
        "focus_profile raw keys=%s normalized clarification_needed=%s question=%s",
        list(raw_result.keys()) if isinstance(raw_result, dict) else None,
        focus_profile.get("clarification_needed"),
        focus_profile.get("clarifying_question"),
    )

    enriched_requirement = {**requirement, "focus_profile": focus_profile}
    return {
        **state,
        "requirement": enriched_requirement,
    }


def focus_profile_route(state: AgentState) -> str:
    requirement = state.get("requirement", {})
    profile = (
        requirement.get("focus_profile", {}) if isinstance(requirement, dict) else {}
    )
    return "clarify" if profile.get("clarification_needed") else "continue"


def normalize_focus_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    profile = raw if isinstance(raw, dict) else {}
    explicit = _focus_list(profile.get("explicit_focuses"))
    inferred = _focus_list(profile.get("inferred_focuses"))
    question = str(
        profile.get("clarifying_question")
        or profile.get("clarification_question")
        or ""
    ).strip()
    needs_clarification = bool(profile.get("clarification_needed"))
    if needs_clarification and not question:
        question = "请补充这份报告最需要关注的判断维度。"
    if not needs_clarification:
        question = None
    return {
        "explicit_focuses": explicit,
        "inferred_focuses": inferred,
        "clarification_needed": needs_clarification,
        "clarifying_question": question,
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
                "evidence_expectation": str(
                    item.get("evidence_expectation") or ""
                ).strip()[:240],
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


_VAGUE_KEYWORDS = {
    "竞品",
    "对比",
    "分析",
    "比较",
    "看看",
    "了解",
    "调研",
    "competitive",
    "compare",
    "analysis",
    "benchmark",
}


def _is_vague_requirement(text: str) -> bool:
    if len(text) > 60:
        return False
    lower = text.lower()
    has_keyword = any(kw in lower for kw in _VAGUE_KEYWORDS)
    if not has_keyword:
        return False
    word_count = len(lower.split())
    cjk_char_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    effective_token_count = word_count + max(0, cjk_char_count - 1) // 2
    return effective_token_count <= 8
