from sqlalchemy.orm import Session, joinedload

from app.db.models import Analysis, Competitor


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
    candidate_key = (
        candidate.analysis_iteration or 0,
        candidate.created_at,
        candidate.id,
    )
    existing_key = (
        existing.analysis_iteration or 0,
        existing.created_at,
        existing.id,
    )
    return candidate_key > existing_key
