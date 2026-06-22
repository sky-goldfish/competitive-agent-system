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
    user_text = (state.get("user_requirement") or "").strip()
    focus_profile = _ground_focus_profile_in_user_text(focus_profile, user_text)

    if not focus_profile.get("clarification_needed"):
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


def _ground_focus_profile_in_user_text(
    profile: dict[str, Any], user_text: str
) -> dict[str, Any]:
    if not profile.get("explicit_focuses"):
        return profile
    grounded = [
        focus
        for focus in profile.get("explicit_focuses") or []
        if _focus_is_grounded_in_user_text(focus, user_text)
    ]
    if len(grounded) == len(profile.get("explicit_focuses") or []):
        return profile
    assumptions = list(profile.get("assumptions") or [])
    assumptions.append("已忽略未在用户原始输入中明确出现的默认分析维度。")
    return {
        **profile,
        "explicit_focuses": grounded,
        "assumptions": assumptions,
    }


def _focus_is_grounded_in_user_text(focus: dict[str, Any], user_text: str) -> bool:
    normalized_text = _normalize_text(user_text)
    if not normalized_text:
        return False
    candidates = _focus_grounding_terms(focus)
    return any(term and term in normalized_text for term in candidates)


def _focus_grounding_terms(focus: dict[str, Any]) -> set[str]:
    raw_values = [
        focus.get("key"),
        focus.get("label"),
        *(focus.get("query_terms") if isinstance(focus.get("query_terms"), list) else []),
    ]
    terms: set[str] = set()
    for value in raw_values:
        text = _normalize_text(str(value or ""))
        if not text:
            continue
        terms.add(text)
        terms.update(part for part in text.replace("_", " ").split() if len(part) >= 2)

    label = str(focus.get("label") or "")
    key = str(focus.get("key") or "").lower()
    alias_map = {
        "功能": {"功能", "能力", "特性", "feature", "features", "capability"},
        "性能": {"性能", "速度", "准确率", "延迟", "benchmark", "performance"},
        "体验": {"体验", "易用", "交互", "学习曲线", "ux", "experience"},
        "架构": {"架构", "技术架构", "模型架构", "推理", "插件", "architecture"},
        "定价": {"价格", "定价", "收费", "套餐", "预算", "pricing", "price", "cost"},
        "隐私": {"隐私", "安全", "加密", "合规", "privacy", "security"},
        "本地": {"本地", "离线", "local", "offline", "localfirst"},
        "协作": {"协作", "团队", "共享", "多人", "collaboration", "team"},
        "代码质量": {"代码质量", "准确性", "代码生成质量", "多语言", "debug", "调试"},
    }
    combined = f"{label} {key}"
    for marker, aliases in alias_map.items():
        if marker in combined or marker in key:
            terms.update(_normalize_text(alias) for alias in aliases)
    return {term for term in terms if term}


def _normalize_text(value: str) -> str:
    return (
        value.lower()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
        .replace("（", "")
        .replace("）", "")
        .replace("(", "")
        .replace(")", "")
    )


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
