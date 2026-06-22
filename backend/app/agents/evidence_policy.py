from __future__ import annotations

from typing import Any


SCHEMA_FIELDS = {
    "positioning": "产品定位",
    "target_users": "目标用户",
    "core_features_json": "核心功能",
    "pricing_summary": "定价信息",
    "strengths_json": "优势",
    "weaknesses_json": "劣势或痛点",
    "opportunities_json": "机会点",
}

ALL_EVIDENCE_DIMENSIONS = {
    "产品定位",
    "核心功能",
    "价格与商业模式",
    "用户评价与痛点",
    "竞争关系",
    "市场信号",
    "风险与机会",
}

FIELD_DIMENSION_REQUIREMENTS = {
    "positioning": {"产品定位"},
    "target_users": {"产品定位", "用户评价与痛点"},
    "core_features_json": {"核心功能"},
    "pricing_summary": {"价格与商业模式"},
    "strengths_json": {
        "产品定位",
        "核心功能",
        "价格与商业模式",
        "用户评价与痛点",
        "竞争关系",
        "市场信号",
    },
    "weaknesses_json": {
        "产品定位",
        "核心功能",
        "用户评价与痛点",
        "价格与商业模式",
        "风险与机会",
        "竞争关系",
    },
    "opportunities_json": ALL_EVIDENCE_DIMENSIONS,
}

VALID_SENTIMENTS = {"positive", "negative", "neutral", "mixed"}
VALID_EVIDENCE_ROLES = {
    "positioning",
    "feature",
    "pricing",
    "user_praise",
    "user_complaint",
    "market_signal",
    "limitation",
    "competition",
    "risk",
    "opportunity",
    "background",
}

FIELD_POLICIES = {
    "positioning": {
        "allowed_dimensions": {"产品定位", "竞争关系"},
        "allowed_sentiments": {"positive", "neutral", "mixed"},
        "blocked_sentiments": set(),
        "required": True,
    },
    "target_users": {
        "allowed_dimensions": {"产品定位", "用户评价与痛点"},
        "allowed_sentiments": {"positive", "neutral", "mixed"},
        "blocked_sentiments": set(),
        "required": True,
    },
    "core_features_json": {
        "allowed_dimensions": {"核心功能"},
        "allowed_sentiments": {"positive", "neutral", "mixed"},
        "blocked_sentiments": set(),
        "required": True,
    },
    "pricing_summary": {
        "allowed_dimensions": {"价格与商业模式"},
        "allowed_sentiments": {"neutral", "mixed"},
        "blocked_sentiments": set(),
        "required": True,
    },
    "strengths_json": {
        "allowed_dimensions": FIELD_DIMENSION_REQUIREMENTS["strengths_json"],
        "allowed_sentiments": {"positive", "neutral", "mixed"},
        "blocked_sentiments": {"negative"},
        "required": True,
    },
    "weaknesses_json": {
        "allowed_dimensions": FIELD_DIMENSION_REQUIREMENTS["weaknesses_json"],
        "allowed_sentiments": {"negative", "mixed", "neutral"},
        "blocked_sentiments": {"positive"},
        "required": True,
    },
    "opportunities_json": {
        "allowed_dimensions": FIELD_DIMENSION_REQUIREMENTS["opportunities_json"],
        "allowed_sentiments": {"positive", "negative", "neutral", "mixed"},
        "blocked_sentiments": set(),
        "required": False,
    },
}

CLAIM_FIELD_MAP = {
    "positioning": "positioning",
    "target_users": "target_users",
    "core_features": "core_features_json",
    "pricing": "pricing_summary",
    "strengths": "strengths_json",
    "weaknesses": "weaknesses_json",
    "opportunities": "opportunities_json",
}

CLAIM_DIMENSION_MAP = {
    claim_type: FIELD_DIMENSION_REQUIREMENTS[field]
    for claim_type, field in CLAIM_FIELD_MAP.items()
}

DIMENSION_ALIASES: dict[str, set[str]] = {
    "产品定位": {"产品定位", "定位", "市场定位", "产品定位与目标用户"},
    "核心功能": {"核心功能", "功能", "产品功能", "功能特性", "核心能力"},
    "价格与商业模式": {
        "价格与商业模式",
        "定价策略",
        "价格",
        "定价",
        "商业模式",
        "收费模式",
    },
    "用户评价与痛点": {"用户评价与痛点", "用户评价", "痛点", "用户反馈", "口碑"},
    "市场信号": {"市场信号", "市场趋势", "市场动态"},
    "风险与机会": {"风险与机会", "风险", "机会", "风险与机遇"},
}


def dimension_matches_any(dimension: Any, preferred: set[str]) -> bool:
    if not dimension or not preferred:
        return False
    dim_stripped = str(dimension).strip()
    for pref in preferred:
        if dim_stripped == pref:
            return True
        aliases = DIMENSION_ALIASES.get(pref, set())
        if dim_stripped in aliases:
            return True
        for alias in aliases:
            if alias in dim_stripped or dim_stripped in alias:
                return True
    return False


def parse_field_evidence_ids(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, list[str]] = {}
    for field in SCHEMA_FIELDS:
        ids = raw.get(field)
        if not isinstance(ids, list):
            continue
        cleaned: list[str] = []
        for value in ids:
            evidence_id = str(value).strip()
            if evidence_id and evidence_id not in cleaned:
                cleaned.append(evidence_id)
        if cleaned:
            result[field] = cleaned
    return result


def parse_item_evidence_bindings(raw: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for field in SCHEMA_FIELDS:
        rows = raw.get(field)
        if not isinstance(rows, list):
            continue
        cleaned_rows: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            raw_ids = row.get("evidence_ids")
            if not isinstance(raw_ids, list):
                raw_ids = []
            evidence_ids: list[str] = []
            for value in raw_ids:
                evidence_id = str(value).strip()
                if evidence_id and evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
            try:
                item_index = int(row.get("item_index") or index)
            except (TypeError, ValueError):
                item_index = index
            cleaned_rows.append(
                {
                    "item_index": item_index,
                    "claim": str(row.get("claim") or "").strip(),
                    "evidence_ids": evidence_ids,
                    "match_reason": str(row.get("match_reason") or "").strip(),
                }
            )
        if cleaned_rows:
            result[field] = cleaned_rows
    return result


def normalize_sentiment(value: Any, *, default: str = "neutral") -> str:
    sentiment = str(value or default).strip().lower()
    if sentiment in {"正面", "积极", "positive"}:
        return "positive"
    if sentiment in {"负面", "消极", "negative"}:
        return "negative"
    if sentiment in {"混合", "mixed"}:
        return "mixed"
    if sentiment in {"中性", "neutral"}:
        return "neutral"
    return default


def normalize_evidence_role(value: Any, *, default: str = "background") -> str:
    role = str(value or default).strip().lower()
    aliases = {
        "功能": "feature",
        "价格": "pricing",
        "定价": "pricing",
        "用户好评": "user_praise",
        "用户抱怨": "user_complaint",
        "用户痛点": "user_complaint",
        "限制": "limitation",
        "竞争": "competition",
        "风险": "risk",
        "机会": "opportunity",
        "定位": "positioning",
    }
    role = aliases.get(role, role)
    return role if role in VALID_EVIDENCE_ROLES else default


def evidence_matches_field_policy(
    evidence: dict[str, Any],
    field: str,
    *,
    allow_neutral_for_weakness: bool = True,
) -> bool:
    policy = FIELD_POLICIES.get(field)
    if not policy:
        return True
    dimensions = policy.get("allowed_dimensions") or set()
    if dimensions and not dimension_matches_any(evidence.get("related_dimension"), dimensions):
        return False
    sentiment = normalize_sentiment(evidence.get("sentiment"))
    role = normalize_evidence_role(evidence.get("evidence_role"))
    if field == "weaknesses_json" and sentiment == "positive" and role == "user_praise":
        return False
    blocked = set(policy.get("blocked_sentiments") or set())
    if sentiment in blocked:
        return False
    allowed = set(policy.get("allowed_sentiments") or set())
    if field == "weaknesses_json" and allow_neutral_for_weakness:
        allowed = allowed | {"neutral"}
    return not allowed or sentiment in allowed


def claim_required_dimensions(
    field: str,
    claim: str | list[str],
    available_evidence: list[dict[str, Any]] | None = None,
) -> set[str]:
    if field == "opportunities_json":
        return set()

    if isinstance(claim, list):
        text = " ".join(str(item or "") for item in claim).lower()
    else:
        text = str(claim or "").lower()
    if not text:
        return set()

    available_evidence = available_evidence or []
    has_user_feedback_evidence = any(
        dimension_matches_any(item.get("related_dimension"), {"用户评价与痛点"})
        for item in available_evidence
    )
    has_positioning_evidence = any(
        dimension_matches_any(item.get("related_dimension"), {"产品定位"})
        for item in available_evidence
    )

    positioning_markers = (
        "positioning",
        "position",
        "brand",
        "category",
        "vs code",
        "developer-first",
        "developer first",
        "model-first",
        "定位",
        "品牌",
        "品类",
        "开发者优先",
        "模型优先",
        "独立",
        "差异化",
    )
    pricing_markers = (
        "price",
        "pricing",
        "cost",
        "free",
        "pro",
        "business",
        "enterprise",
        "plan",
        "tier",
        "seat",
        "token",
        "usage",
        "refund",
        "refundable",
        "non-refundable",
        "价格",
        "定价",
        "收费",
        "成本",
        "免费",
        "套餐",
        "订阅",
        "席位",
        "用量",
        "贵",
        "退款",
        "退费",
        "不支持退款",
    )
    pricing_weakness_markers = (
        "refund",
        "refundable",
        "non-refundable",
        "paid",
        "subscription",
        "billing",
        "charge",
        "cost",
        "price",
        "pricing",
        "退款",
        "退费",
        "不支持退款",
        "付费",
        "订阅",
        "收费",
        "费用",
        "成本",
        "价格",
        "定价",
        "套餐",
        "账单",
        "额度",
        "免费版",
    )
    user_feedback_markers = (
        "user",
        "users",
        "review",
        "report",
        "complain",
        "pain",
        "setup",
        "用户",
        "评价",
        "痛点",
        "抱怨",
        "反馈",
        "上手",
        "配置",
        "复杂",
    )
    feature_markers = (
        "feature",
        "llm",
        "model",
        "agent",
        "chat",
        "cli",
        "code review",
        "completion",
        "integration",
        "provider",
        "功能",
        "模型",
        "代码补全",
        "代码审查",
        "集成",
        "提供商",
        "自定义",
        "多模型",
        "插件",
    )
    limitation_markers = (
        "limit",
        "limited",
        "limitation",
        "restriction",
        "unsupported",
        "not support",
        "can't",
        "cannot",
        "缺乏",
        "限制",
        "受限",
        "不支持",
        "无法",
        "不能",
        "不足",
        "边界",
        "功能限制",
        "高级功能",
    )

    if field == "weaknesses_json":
        if has_positioning_evidence and any(marker in text for marker in positioning_markers):
            return {"产品定位"}
        if has_user_feedback_evidence and any(marker in text for marker in user_feedback_markers):
            return {"用户评价与痛点"}
        if any(marker in text for marker in pricing_weakness_markers):
            return {"价格与商业模式"}
        if any(marker in text for marker in limitation_markers):
            return {"核心功能"}
        if any(marker in text for marker in pricing_markers):
            return {"价格与商业模式"}
    if field == "pricing_summary":
        return {"价格与商业模式"}
    if field == "core_features_json":
        return {"核心功能"}
    if any(marker in text for marker in pricing_markers):
        return {"价格与商业模式"}
    if any(marker in text for marker in feature_markers):
        return {"核心功能"}
    if has_user_feedback_evidence and any(marker in text for marker in user_feedback_markers):
        return {"用户评价与痛点"}
    if has_positioning_evidence and any(marker in text for marker in positioning_markers):
        return {"产品定位"}
    return set()


def evidence_matches_claim_policy(
    evidence: dict[str, Any],
    field: str,
    claim: str | list[str],
    available_evidence: list[dict[str, Any]] | None = None,
) -> bool:
    if not evidence_matches_field_policy(evidence, field):
        return False
    required = claim_required_dimensions(field, claim, available_evidence)
    return not required or dimension_matches_any(evidence.get("related_dimension"), required)
