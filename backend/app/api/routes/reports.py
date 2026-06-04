import json
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Analysis, Evidence, Report, Run, Source
from app.db.session import get_db
from app.schemas.report import CitationAnalysisRef, CitationBundleClaim, CitationBundleCompetitor, CitationBundleEvidenceRef, CitationMapItem, ReportResponse

router = APIRouter(prefix="/runs/{run_id}/report", tags=["reports"])


@router.get("", response_model=ReportResponse)
def get_report(run_id: str, iteration: int | None = None, db: Session = Depends(get_db)):
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    query = db.query(Report).filter(Report.run_id == run_id)
    if iteration is not None:
        report = query.filter(Report.iteration == iteration).first()
    else:
        report = query.order_by(Report.iteration.desc()).first()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    return report


@router.get("/versions", response_model=list[ReportResponse])
def get_report_versions(run_id: str, db: Session = Depends(get_db)):
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return db.query(Report).filter(Report.run_id == run_id).order_by(Report.iteration.asc()).all()


@router.get("/citations", response_model=list[CitationMapItem])
def get_report_citations(run_id: str, db: Session = Depends(get_db)):
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    report = db.query(Report).filter(Report.run_id == run_id).first()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")

    reference_urls = _extract_reference_urls(report.markdown_content)
    sources = db.query(Source).filter(Source.run_id == run_id).order_by(Source.retrieved_at.asc(), Source.id.asc()).all()
    sources_by_url: dict[str, list[Source]] = {}
    for source in sources:
        sources_by_url.setdefault(source.url, []).append(source)
    evidence_items = db.query(Evidence).filter(Evidence.run_id == run_id).all()
    evidence_by_source_id: dict[str, list[Evidence]] = {}
    for item in evidence_items:
        evidence_by_source_id.setdefault(item.source_id, []).append(item)

    analyses = db.query(Analysis).filter(Analysis.run_id == run_id).all()
    analysis_refs_by_evidence_id = _analysis_refs_by_evidence_id(analyses)

    citation_items = []
    for reference_id, url in reference_urls:
        matching_sources = sources_by_url.get(url, [])
        source = matching_sources.pop(0) if matching_sources else None
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
                existing.claim_types[:] = sorted(set(existing.claim_types + ref.claim_types))
        citation_items.append(
            CitationMapItem(
                reference_id=reference_id,
                source=source,
                evidence=evidence_for_source,
                analyses=list(analysis_refs.values()),
            )
        )
    return citation_items


def _extract_reference_urls(markdown_content: str) -> list[tuple[int, str]]:
    reference_section_match = re.search(
        r"\n*##\s*(?:(?:\d+|[一二三四五六七八九十]+)[\.、]\s*)?(?:参考来源|参考文献|References)\s*\n(?P<section>[\s\S]*)$",
        markdown_content.strip(),
    )
    if not reference_section_match:
        return []
    section = reference_section_match.group("section")
    matches = re.findall(r"^\s*\d+\.\s+\[\[(\d+)\]\]\((https?://[^)\s]+)\)", section, flags=re.MULTILINE)
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
def get_report_citation_bundle(run_id: str, db: Session = Depends(get_db)):
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    sources = db.query(Source).filter(Source.run_id == run_id).all()
    source_ref_by_id = {s.id: _extract_ref_id(s.metadata_json) for s in sources}
    source_by_id = {s.id: s for s in sources}

    evidence_items = db.query(Evidence).filter(Evidence.run_id == run_id).all()
    evidence_by_competitor: dict[str, list[Evidence]] = {}
    for item in evidence_items:
        evidence_by_competitor.setdefault(item.related_product, []).append(item)

    analyses = db.query(Analysis).filter(Analysis.run_id == run_id).order_by(Analysis.created_at.asc()).all()

    result: list[CitationBundleCompetitor] = []
    for analysis in analyses:
        competitor_name = analysis.competitor.name if analysis.competitor else analysis.competitor_id
        competitor_evidence = evidence_by_competitor.get(competitor_name, [])

        claims: list[CitationBundleClaim] = []
        for claim_type, label in CLAIM_DEFINITIONS:
            field = ANALYSIS_FIELD_MAP[claim_type]
            text = _analysis_field_text(analysis, field)

            preferred_dims = CLAIM_DIMENSION_MAP.get(claim_type, set())
            if preferred_dims:
                matched = [e for e in competitor_evidence if e.related_dimension in preferred_dims]
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

            claims.append(CitationBundleClaim(claim_type=claim_type, label=label, text=text, evidence=ev_refs))

        result.append(CitationBundleCompetitor(competitor_id=analysis.competitor_id, competitor_name=competitor_name, analysis_iteration=analysis.analysis_iteration, claims=claims))

    return result


def _analysis_refs_by_evidence_id(analyses: list[Analysis]) -> dict[str, list[CitationAnalysisRef]]:
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
    return claims


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
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
