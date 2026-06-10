import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.db.models import Evidence, KnowledgeItem, Run, Source, new_id
from app.db.session import SessionLocal

PROMOTABLE_DIMENSIONS = {
    "产品定位",
    "核心功能",
    "价格与商业模式",
    "用户评价与痛点",
}


@dataclass
class KnowledgeUpsertResult:
    run_id: str
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0


def upsert_from_evidence(db: Session, run_id: str) -> KnowledgeUpsertResult:
    if db.get(Run, run_id) is None:
        raise ValueError(f"Run not found: {run_id}")

    result = KnowledgeUpsertResult(run_id=run_id)
    evidence_items = (
        db.query(Evidence)
        .filter(Evidence.run_id == run_id)
        .options(joinedload(Evidence.source))
        .all()
    )
    for evidence in evidence_items:
        if not _is_promotable_evidence(evidence):
            result.skipped_count += 1
            continue
        source = evidence.source
        existing = _find_existing_item(db, evidence, source)
        metadata = _metadata_for_evidence(evidence, source)
        if existing is None:
            db.add(
                KnowledgeItem(
                    product_name=evidence.related_product,
                    dimension=evidence.related_dimension,
                    claim=_claim_from_evidence(evidence),
                    summary=evidence.summary or "",
                    confidence=evidence.confidence,
                    source_type=source.source_type if source else "unknown",
                    source_title=source.title if source else None,
                    source_url=source.url if source else None,
                    run_id=run_id,
                    evidence_id=evidence.id,
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                )
            )
            result.created_count += 1
            continue

        existing.product_name = evidence.related_product
        existing.dimension = evidence.related_dimension
        existing.claim = _claim_from_evidence(evidence)
        existing.summary = evidence.summary or ""
        existing.confidence = evidence.confidence
        existing.source_type = source.source_type if source else "unknown"
        existing.source_title = source.title if source else None
        existing.source_url = source.url if source else None
        existing.run_id = run_id
        existing.evidence_id = evidence.id
        existing.metadata_json = json.dumps(metadata, ensure_ascii=False)
        existing.updated_at = datetime.utcnow()
        result.updated_count += 1

    db.commit()
    return result


def search_knowledge(
    db: Session,
    *,
    query: str | None = None,
    product_names: list[str] | None = None,
    dimensions: list[str] | None = None,
    exclude_run_id: str | None = None,
    limit: int = 20,
) -> list[KnowledgeItem]:
    query_obj = db.query(KnowledgeItem)
    if product_names:
        product_filters = [
            KnowledgeItem.product_name.ilike(f"%{_escape_like(name)}%")
            for name in product_names
            if name.strip()
        ]
        if product_filters:
            query_obj = query_obj.filter(or_(*product_filters))
    if dimensions:
        query_obj = query_obj.filter(KnowledgeItem.dimension.in_(dimensions))
    if exclude_run_id:
        query_obj = query_obj.filter(
            or_(KnowledgeItem.run_id.is_(None), KnowledgeItem.run_id != exclude_run_id)
        )
    if query:
        terms = [term for term in _tokenize_query(query) if term]
        if terms:
            term_filters = []
            for term in terms[:8]:
                pattern = f"%{_escape_like(term)}%"
                term_filters.append(KnowledgeItem.claim.ilike(pattern))
                term_filters.append(KnowledgeItem.summary.ilike(pattern))
                term_filters.append(KnowledgeItem.product_name.ilike(pattern))
                term_filters.append(KnowledgeItem.dimension.ilike(pattern))
            query_obj = query_obj.filter(or_(*term_filters))
    return (
        query_obj.order_by(
            KnowledgeItem.confidence.desc(), KnowledgeItem.updated_at.desc()
        )
        .limit(max(1, min(limit, 100)))
        .all()
    )


def retrieve_for_material_collection(
    run_id: str,
    competitors: list[dict[str, Any]],
    requirement: dict[str, Any],
    *,
    dimensions: list[str],
    limit_per_competitor: int = 8,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    db = SessionLocal()
    try:
        sources: list[dict[str, Any]] = []
        evidence_items: list[dict[str, Any]] = []
        seen_source_keys: set[tuple[str, str]] = set()
        next_ref_id = 1
        query_text = _requirement_query(requirement)
        for competitor in competitors:
            competitor_id = str(competitor.get("id") or "")
            product_name = str(competitor.get("name") or "").strip()
            if not competitor_id or not product_name:
                continue
            matches = search_knowledge(
                db,
                query=query_text,
                product_names=[product_name],
                dimensions=dimensions,
                exclude_run_id=run_id,
                limit=limit_per_competitor,
            )
            for item in matches:
                source_url = item.source_url or f"knowledge://{item.id}"
                source_key = (competitor_id, source_url)
                if source_key not in seen_source_keys:
                    seen_source_keys.add(source_key)
                    ref_id = next_ref_id
                    next_ref_id += 1
                    sources.append(
                        {
                            "competitor_id": competitor_id,
                            "title": item.source_title
                            or f"{item.product_name} 历史知识",
                            "url": source_url,
                            "snippet": item.summary or item.claim[:240],
                            "source_type": item.source_type or "knowledge_base",
                            "provider": "knowledge_base",
                            "raw_content": item.claim,
                            "reference_id": ref_id,
                            "metadata_json": json.dumps(
                                {
                                    "reference_id": ref_id,
                                    "source_type_label": "历史知识库",
                                    "credibility_score": item.confidence,
                                    "rank_score": item.confidence,
                                    "classification_reason": "来自历史任务沉淀的结构化证据",
                                    "knowledge_item_id": item.id,
                                    "original_run_id": item.run_id,
                                    "original_evidence_id": item.evidence_id,
                                },
                                ensure_ascii=False,
                            ),
                        }
                    )
                else:
                    ref_id = next(
                        source["reference_id"]
                        for source in sources
                        if source.get("competitor_id") == competitor_id
                        and source.get("url") == source_url
                    )
                evidence_items.append(
                    {
                        "id": new_id("ev"),
                        "competitor_id": competitor_id,
                        "related_product": product_name,
                        "related_dimension": item.dimension,
                        "quote": item.claim[:800],
                        "summary": item.summary or item.claim[:240],
                        "confidence": item.confidence,
                        "source_url": source_url,
                        "source_title": item.source_title
                        or f"{item.product_name} 历史知识",
                        "reference_id": ref_id,
                        "source_type": item.source_type or "knowledge_base",
                    }
                )
        return sources, evidence_items
    finally:
        db.close()


def _find_existing_item(
    db: Session, evidence: Evidence, source: Source | None
) -> KnowledgeItem | None:
    existing = (
        db.query(KnowledgeItem)
        .filter(KnowledgeItem.evidence_id == evidence.id)
        .first()
    )
    if existing is not None:
        return existing
    claim = _claim_from_evidence(evidence)
    query = db.query(KnowledgeItem).filter(
        KnowledgeItem.product_name == evidence.related_product,
        KnowledgeItem.dimension == evidence.related_dimension,
        KnowledgeItem.claim == claim,
    )
    if source and source.url:
        query = query.filter(KnowledgeItem.source_url == source.url)
    return query.first()


def _is_promotable_evidence(evidence: Evidence) -> bool:
    if not evidence.related_product or not evidence.related_dimension:
        return False
    if evidence.related_dimension not in PROMOTABLE_DIMENSIONS:
        return False
    if not evidence.quote and not evidence.summary:
        return False
    return float(evidence.confidence or 0) >= 0.72


def _claim_from_evidence(evidence: Evidence) -> str:
    return (evidence.quote or evidence.summary or "").strip()[:1200]


def _metadata_for_evidence(evidence: Evidence, source: Source | None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"promoted_from": "evidence"}
    if evidence.reference_id is not None:
        metadata["reference_id"] = evidence.reference_id
    if source and source.metadata_json:
        try:
            source_metadata = json.loads(source.metadata_json)
        except json.JSONDecodeError:
            source_metadata = {}
        if isinstance(source_metadata, dict):
            metadata["source_metadata"] = source_metadata
    return metadata


def _requirement_query(requirement: dict[str, Any]) -> str:
    values = [
        requirement.get("query"),
        requirement.get("summary"),
        requirement.get("domain"),
        requirement.get("target_product"),
        requirement.get("name"),
    ]
    focus_profile = requirement.get("focus_profile")
    if isinstance(focus_profile, list):
        for item in focus_profile:
            if isinstance(item, dict):
                values.extend([item.get("label"), item.get("key")])
    return " ".join(str(value) for value in values if value)


def _tokenize_query(query: str) -> list[str]:
    return [
        token.strip(" ,，。:：;；/\\|()[]{}")
        for token in query.split()
        if token.strip(" ,，。:：;；/\\|()[]{}")
    ]


def _escape_like(value: str) -> str:
    return value.replace("%", "\\%").replace("_", "\\_")
