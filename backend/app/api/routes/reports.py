import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.schemas.analysis import parse_focus_analysis_json
from app.db.models import Analysis, Evidence, Report, Run, Source
from app.db.session import get_db
from app.schemas.report import (
    CitationAnalysisRef,
    CitationBundleClaim,
    CitationBundleCompetitor,
    CitationBundleEvidenceRef,
    CitationMapItem,
    ReportResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs/{run_id}/report", tags=["reports"])


@router.get("", response_model=ReportResponse)
def get_report(
    run_id: str, iteration: int | None = None, db: Session = Depends(get_db)
):
    if db.get(Run, run_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        )
    report = _get_report_version(db, run_id, iteration)
    if report is None:
        existing_iterations = [
            row[0]
            for row in db.query(Report.iteration).filter(Report.run_id == run_id).all()
        ]
        logger.warning(
            "Report not found for run=%s iteration=%s, existing iterations=%s",
            run_id,
            iteration,
            existing_iterations,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report not found."
        )
    return report


@router.get("/versions", response_model=list[ReportResponse])
def get_report_versions(run_id: str, db: Session = Depends(get_db)):
    if db.get(Run, run_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        )
    versions = (
        db.query(Report)
        .filter(Report.run_id == run_id, Report.is_qa_intermediate.is_(False))
        .order_by(Report.iteration.desc())
        .limit(20)
        .all()
    )
    versions.reverse()
    return versions


@router.get("/citations", response_model=list[CitationMapItem])
def get_report_citations(
    run_id: str, iteration: int | None = None, db: Session = Depends(get_db)
):
    if db.get(Run, run_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        )
    report = _get_report_version(db, run_id, iteration)
    if report is None:
        logger.warning(
            "Citations requested for run=%s iteration=%s but report not found",
            run_id,
            iteration,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report not found."
        )

    try:
        reference_urls = _extract_reference_urls(report.markdown_content)
    except Exception:
        logger.exception(
            "Failed to extract reference URLs for run=%s iteration=%s",
            run_id,
            iteration,
        )
        reference_urls = []

    if not reference_urls:
        logger.info(
            "No reference URLs found in report run=%s iteration=%s (content length=%d)",
            run_id,
            iteration,
            len(report.markdown_content or ""),
        )
    sources = (
        db.query(Source)
        .filter(Source.run_id == run_id)
        .order_by(Source.retrieved_at.asc(), Source.id.asc())
        .all()
    )
    sources_by_url: dict[str, list[Source]] = {}
    for source in sources:
        sources_by_url.setdefault(source.url, []).append(source)
    evidence_items = db.query(Evidence).filter(Evidence.run_id == run_id).all()
    evidence_by_source_id: dict[str, list[Evidence]] = {}
    for item in evidence_items:
        evidence_by_source_id.setdefault(item.source_id, []).append(item)

    analyses = (
        db.query(Analysis)
        .filter(Analysis.run_id == run_id)
        .options(joinedload(Analysis.competitor))
        .all()
    )
    analysis_refs_by_evidence_id = _analysis_refs_by_evidence_id(analyses)

    citation_items = []
    url_source_index: dict[str, int] = {}
    for reference_id, url in reference_urls:
        matching_sources = sources_by_url.get(url, [])
        idx = url_source_index.get(url, 0)
        source = matching_sources[idx] if idx < len(matching_sources) else None
        url_source_index[url] = idx + 1
        if source is None:
            continue
        evidence_for_source = evidence_by_source_id.get(source.id, [])
        analysis_refs: dict[str, CitationAnalysisRef] = {}
        for evidence in evidence_for_source:
            for ref in analysis_refs_by_evidence_id.get(evidence.id, []):
                existing = analysis_refs.get(ref.id)
                if existing is None:
                    analysis_refs[ref.id] = ref
                    continue
                existing.claim_types[:] = sorted(
                    set(existing.claim_types + ref.claim_types)
                )
        citation_items.append(
            CitationMapItem(
                reference_id=reference_id,
                source=source,
                evidence=evidence_for_source,
                analyses=list(analysis_refs.values()),
            )
        )
    return citation_items


def _get_report_version(
    db: Session, run_id: str, iteration: int | None
) -> Report | None:
    query = db.query(Report).filter(Report.run_id == run_id)
    if iteration is not None:
        return query.filter(Report.iteration == iteration).first()
    return (
        query.filter(Report.is_qa_intermediate.is_(False))
        .order_by(Report.iteration.desc())
        .first()
    )


def _extract_reference_urls(markdown_content: str) -> list[tuple[int, str]]:
    reference_section_match = re.search(
        r"\n*##\s*(?:(?:\d+|[一二三四五六七八九十]+)[\.、]\s*)?(?:参考来源|参考文献|References)\s*\n(?P<section>[\s\S]*)$",
        markdown_content.strip(),
    )
    if not reference_section_match:
        return []
    section = reference_section_match.group("section")
    matches = re.findall(
        r"^\s*\d+\.\s+\[\[(\d+)\]\]\((https?://[^)\s]+)\)", section, flags=re.MULTILINE
    )
    return [(int(reference_id), url) for reference_id, url in matches]


CLAIM_DEFINITIONS: list[tuple[str, str]] = [
    ("positioning", "产品定位"),
    ("target_users", "目标用户"),
    ("core_features", "核心功能"),
    ("pricing", "定价策略"),
    ("strengths", "优势"),
    ("weaknesses", "劣势或痛点"),
    ("opportunities", "机会点"),
]

CLAIM_DIMENSION_MAP: dict[str, set[str]] = {
    "positioning": {"产品定位"},
    "target_users": {"产品定位", "用户评价与痛点"},
    "core_features": {"核心功能"},
    "pricing": {"价格与商业模式"},
    "strengths": {"产品定位", "核心功能"},
    "weaknesses": {"用户评价与痛点"},
    "opportunities": set(),
}

ANALYSIS_FIELD_MAP: dict[str, str] = {
    "positioning": "positioning",
    "target_users": "target_users",
    "core_features": "core_features_json",
    "pricing": "pricing_summary",
    "strengths": "strengths_json",
    "weaknesses": "weaknesses_json",
    "opportunities": "opportunities_json",
}


@router.get("/citation-bundle", response_model=list[CitationBundleCompetitor])
def get_report_citation_bundle(
    run_id: str, iteration: int | None = None, db: Session = Depends(get_db)
):
    if db.get(Run, run_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        )

    competitor_names_filter: set[str] | None = None
    if iteration is not None:
        report = _get_report_version(db, run_id, iteration)
        if report is not None and report.competitor_names_json:
            try:
                competitor_names_filter = set(json.loads(report.competitor_names_json))
            except (json.JSONDecodeError, TypeError):
                pass

    sources = db.query(Source).filter(Source.run_id == run_id).all()
    source_ref_by_id = {s.id: _extract_ref_id(s.metadata_json) for s in sources}
    source_by_id = {s.id: s for s in sources}

    evidence_items = db.query(Evidence).filter(Evidence.run_id == run_id).all()
    evidence_by_competitor: dict[str, list[Evidence]] = {}
    for item in evidence_items:
        evidence_by_competitor.setdefault(item.related_product, []).append(item)

    analyses = (
        db.query(Analysis)
        .filter(Analysis.run_id == run_id)
        .options(joinedload(Analysis.competitor))
        .order_by(Analysis.created_at.asc())
        .all()
    )
    if competitor_names_filter is not None:
        analyses = [
            a
            for a in analyses
            if (a.competitor.name if a.competitor else a.competitor_id)
            in competitor_names_filter
        ]

    result: list[CitationBundleCompetitor] = []
    for analysis in analyses:
        competitor_name = (
            analysis.competitor.name if analysis.competitor else analysis.competitor_id
        )
        competitor_evidence = evidence_by_competitor.get(competitor_name, [])

        claims: list[CitationBundleClaim] = []
        for claim_type, label in CLAIM_DEFINITIONS:
            field = ANALYSIS_FIELD_MAP[claim_type]
            text = _analysis_field_text(analysis, field)

            preferred_dims = CLAIM_DIMENSION_MAP.get(claim_type, set())
            if preferred_dims:
                matched = [
                    e
                    for e in competitor_evidence
                    if e.related_dimension in preferred_dims
                ]
            else:
                matched = []
            if not matched:
                matched = competitor_evidence

            ev_refs: list[CitationBundleEvidenceRef] = []
            for e in matched[:4]:
                source = source_by_id.get(e.source_id)
                source_url = source.url if source else ""
                ev_refs.append(
                    CitationBundleEvidenceRef(
                        source_reference_id=source_ref_by_id.get(e.source_id),
                        source_title=source.title if source else None,
                        source_url=source_url or None,
                        related_dimension=e.related_dimension,
                        summary=e.summary,
                        quote=e.quote,
                        confidence=e.confidence,
                    )
                )

            claims.append(
                CitationBundleClaim(
                    claim_type=claim_type, label=label, text=text, evidence=ev_refs
                )
            )

        claims.extend(
            _custom_focus_claims(
                analysis,
                evidence_items,
                source_by_id,
                source_ref_by_id,
                competitor_evidence,
            )
        )
        result.append(
            CitationBundleCompetitor(
                competitor_id=analysis.competitor_id,
                competitor_name=competitor_name,
                analysis_iteration=analysis.analysis_iteration,
                claims=claims,
            )
        )

    return result


def _analysis_refs_by_evidence_id(
    analyses: list[Analysis],
) -> dict[str, list[CitationAnalysisRef]]:
    refs: dict[str, list[CitationAnalysisRef]] = {}
    for analysis in analyses:
        evidence_ids = _json_list(analysis.evidence_ids_json)
        claim_types = _claim_types_for_analysis(analysis)
        competitor_name = analysis.competitor.name if analysis.competitor else ""
        for evidence_id in evidence_ids:
            refs.setdefault(evidence_id, []).append(
                CitationAnalysisRef(
                    id=analysis.id,
                    competitor_id=analysis.competitor_id,
                    competitor_name=competitor_name,
                    claim_types=claim_types,
                )
            )
    return refs


def _claim_types_for_analysis(analysis: Analysis) -> list[str]:
    claims = []
    if analysis.positioning:
        claims.append("产品定位")
    if _json_list(analysis.target_users):
        claims.append("目标用户")
    if _json_list(analysis.core_features_json):
        claims.append("核心功能")
    if analysis.pricing_summary:
        claims.append("定价策略")
    if _json_list(analysis.strengths_json):
        claims.append("优势")
    if _json_list(analysis.weaknesses_json):
        claims.append("劣势或痛点")
    if _json_list(analysis.opportunities_json):
        claims.append("机会点")
    for item in parse_focus_analysis_json(analysis.custom_focus_analysis_json):
        label = str(item.get("label") or "").strip()
        if label:
            claims.append(label)
    return claims


def _custom_focus_claims(
    analysis: Analysis,
    evidence_items: list[Evidence],
    source_by_id: dict[str, Source],
    source_ref_by_id: dict[str, int | None],
    fallback_evidence: list[Evidence],
) -> list[CitationBundleClaim]:
    evidence_by_id = {item.id: item for item in evidence_items}
    claims: list[CitationBundleClaim] = []
    for item in parse_focus_analysis_json(analysis.custom_focus_analysis_json):
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        evidence_ids = _json_list(item.get("evidence_ids"))
        matched = [
            evidence_by_id[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in evidence_by_id
        ]
        if not matched:
            matched = [
                evidence
                for evidence in fallback_evidence
                if label in evidence.related_dimension
            ]
        ev_refs = []
        for evidence in matched[:4]:
            source = source_by_id.get(evidence.source_id)
            ev_refs.append(
                CitationBundleEvidenceRef(
                    source_reference_id=source_ref_by_id.get(evidence.source_id),
                    source_title=source.title if source else None,
                    source_url=source.url if source else None,
                    related_dimension=evidence.related_dimension,
                    summary=evidence.summary,
                    quote=evidence.quote,
                    confidence=evidence.confidence,
                )
            )
        claims.append(
            CitationBundleClaim(
                claim_type=f"focus:{item.get('focus_key') or len(claims) + 1}",
                label=label,
                text=str(item.get("verdict") or "证据中未涉及"),
                evidence=ev_refs,
            )
        )
    return claims


def _json_list(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _analysis_field_text(analysis: Analysis, field: str) -> str:
    value = getattr(analysis, field, "")
    if not value:
        return ""
    if field.endswith("_json"):
        items = _json_list(value)
        return "；".join(items) if items else ""
    return str(value)


def _extract_ref_id(metadata_json: str | None) -> int | None:
    if not metadata_json:
        return None
    try:
        metadata = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return None
    value = metadata.get("reference_id")
    return int(value) if isinstance(value, (int, float)) else None
