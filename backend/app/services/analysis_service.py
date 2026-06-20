import json
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.db.models import Analysis, Competitor

_PLACEHOLDER_MARKERS = (
    "暂无",
    "未涉及",
    "无相关",
    "待补充",
    "占位",
    "mock",
    "n/a",
    "unknown",
)


def latest_analyses_by_competitor(
    db: Session,
    run_id: str,
    *,
    selected_only: bool = True,
    competitor_names_filter: set[str] | None = None,
) -> list[Analysis]:
    query = (
        db.query(Analysis)
        .outerjoin(Competitor, Analysis.competitor_id == Competitor.id)
        .filter(Analysis.run_id == run_id)
        .options(joinedload(Analysis.competitor))
    )
    if selected_only:
        query = query.filter((Competitor.selected.is_(True)) | (Competitor.id.is_(None)))

    latest: dict[str, Analysis] = {}
    for item in query.all():
        competitor_name = item.competitor.name if item.competitor else item.competitor_id
        if competitor_names_filter is not None and competitor_name not in competitor_names_filter:
            continue
        key = item.competitor_id or item.id
        existing = latest.get(key)
        if existing is None or _is_newer_analysis(item, existing):
            latest[key] = item

    return sorted(
        latest.values(),
        key=lambda item: (
            item.competitor.name if item.competitor else item.competitor_id,
            item.created_at,
            item.id,
        ),
    )


def _is_newer_analysis(candidate: Analysis, existing: Analysis) -> bool:
    candidate_iteration = candidate.analysis_iteration or 0
    existing_iteration = existing.analysis_iteration or 0
    if candidate_iteration != existing_iteration:
        return candidate_iteration > existing_iteration

    candidate_quality = _analysis_quality_score(candidate)
    existing_quality = _analysis_quality_score(existing)
    if abs(candidate_quality - existing_quality) > 2:
        return candidate_quality > existing_quality

    return (candidate.created_at, candidate.id) > (existing.created_at, existing.id)


def _analysis_quality_score(analysis: Analysis) -> int:
    fields = (
        "positioning",
        "target_users",
        "core_features_json",
        "pricing_summary",
        "strengths_json",
        "weaknesses_json",
        "opportunities_json",
    )
    score = 0
    for field in fields:
        score += 2 if not _is_placeholder(getattr(analysis, field, None)) else -2
    score += min(len(_parse_json_list(analysis.evidence_ids_json)), 8)
    return score


def _is_placeholder(value: Any) -> bool:
    if isinstance(value, list):
        return len([item for item in value if not _is_placeholder(item)]) == 0
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return True
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return True
            if isinstance(parsed, list):
                return _is_placeholder(parsed)
            return True
        lowered = text.lower()
        return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)
    return value is None


def _parse_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    return []
