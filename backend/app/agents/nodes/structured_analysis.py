from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import re
from typing import Any
from uuid import uuid4

from app.agents.evidence_policy import (
    FIELD_DIMENSION_REQUIREMENTS,
    dimension_matches_any,
    evidence_matches_claim_policy,
    parse_field_evidence_ids,
    parse_item_evidence_bindings,
)
from app.agents.state import AgentState
from app.providers.llm.base import LLMProvider

try:
    from app.services import call_tracer
except ModuleNotFoundError:
    class _NoopCallTracer:
        @staticmethod
        def get_trace_context() -> dict[str, Any] | None:
            return None

        @staticmethod
        def set_worker_trace_context(trace_ctx: dict[str, Any] | None) -> None:
            return None

    call_tracer = _NoopCallTracer()

logger = logging.getLogger(__name__)


def structured_analysis_node(state: AgentState, llm: LLMProvider) -> AgentState:
    competitors = state.get("selected_competitors", [])
    evidence = state.get("evidence", [])
    focus_items = _active_focus_items(state.get("requirement", {}))
    existing_analyses = _dedupe_analyses_by_competitor(
        state.get("analyses", []), competitors
    )
    existing_by_competitor = {
        str(item.get("competitor_id")): item
        for item in existing_analyses
        if item.get("competitor_id")
    }
    retry_ids = state.get("qa_retry_analysis_ids")
    retry_queries = state.get("qa_retry_queries")
    qa_retry_guidance_map = state.get("qa_retry_guidance_map")
    qa_repair_tasks = state.get("qa_repair_tasks") or []
    qa_bad_evidence_ids = {str(item) for item in state.get("qa_bad_evidence_ids", [])}

    affected_ids = set(retry_ids or [])
    if not affected_ids and retry_queries:
        query_names = {
            rq.get("competitor_name")
            for rq in retry_queries
            if rq.get("competitor_name")
        }
        name_to_id: dict[str, str] = {}
        for c in competitors:
            name_to_id.setdefault(c["name"], c["id"])
        matched_ids = {name_to_id[n] for n in query_names if n in name_to_id}
        if not matched_ids and query_names:
            from difflib import get_close_matches

            for qn in query_names:
                matches = get_close_matches(qn, name_to_id.keys(), n=1, cutoff=0.6)
                if matches:
                    matched_ids.add(name_to_id[matches[0]])
        affected_ids = matched_ids

    if affected_ids and existing_analyses:
        keep = [
            a for a in existing_analyses if a.get("competitor_id") not in affected_ids
        ]
        retry_competitors = [c for c in competitors if c["id"] in affected_ids]
    elif existing_analyses and (retry_ids or retry_queries):
        logger.warning(
            "QA retry requested but no competitors matched; skipping re-analysis. "
            "retry_names=%s available_names=%s",
            {rq.get("competitor_name") for rq in (retry_queries or [])},
            [c["name"] for c in competitors],
        )
        return {**state, "analyses": existing_analyses}
    else:
        keep = []
        retry_competitors = competitors

    def analyze_one(competitor: dict, trace_ctx: dict | None) -> dict:
        call_tracer.set_worker_trace_context(trace_ctx)
        competitor_evidence = [
            item
            for item in evidence
            if item.get("competitor_id") == competitor["id"]
            or item.get("related_product") == competitor.get("name")
        ]
        if qa_bad_evidence_ids:
            competitor_evidence = [
                item
                for item in competitor_evidence
                if str(item.get("id") or "") not in qa_bad_evidence_ids
            ]
        comp = competitor
        feedback = (qa_retry_guidance_map or {}).get(competitor["name"])
        repair_tasks = _repair_tasks_for_competitor(qa_repair_tasks, competitor)
        removed_evidence_ids = qa_bad_evidence_ids | _must_remove_evidence_ids_from_tasks(
            repair_tasks
        )
        if focus_items or (feedback and (retry_ids or retry_queries)) or repair_tasks:
            comp = {**competitor}
            if focus_items:
                comp["_focus_schema"] = [
                    {
                        "key": f["key"],
                        "label": f["label"],
                        "evidence_expectation": f.get("evidence_expectation", ""),
                    }
                    for f in focus_items
                ]
            if feedback and (retry_ids or retry_queries):
                comp["_qa_feedback"] = feedback
            if repair_tasks:
                comp["_qa_repair_tasks"] = repair_tasks
        analysis = llm.analyze_competitor(comp, competitor_evidence)
        analysis = _clean_analysis_business_fields(analysis)
        analysis["custom_focus_analysis_json"] = _normalize_custom_focus_analysis(
            analysis.get("custom_focus_analysis_json"),
            focus_items,
            competitor_evidence,
        )
        analysis["id"] = f"ana_{uuid4().hex[:12]}"
        analysis["analysis_iteration"] = state.get("feedback_loop_count", 0)
        # Preserve LLM-returned evidence_ids_json when valid; only fall back to full
        # evidence set when the LLM didn't provide one.
        llm_evidence_ids = _parse_json_list(analysis.get("evidence_ids_json"))
        valid_ev_ids = {item.get("id") for item in competitor_evidence if item.get("id")}
        if llm_evidence_ids and all(str(eid) in valid_ev_ids for eid in llm_evidence_ids):
            # LLM returned valid evidence IDs — keep them as-is (already ev_xxx after
            # the ref_id→ev_id conversion in the provider layer).
            filtered_ids = [
                str(eid) for eid in llm_evidence_ids if str(eid) not in removed_evidence_ids
            ]
        else:
            filtered_ids = [
                item["id"]
                for item in competitor_evidence
                if item.get("id") and str(item.get("id")) not in removed_evidence_ids
            ]
        filtered_ids = _repair_evidence_bindings(
            filtered_ids,
            analysis,
            competitor_evidence,
            repair_tasks,
            removed_evidence_ids,
        )
        item_evidence_bindings = _repair_item_evidence_bindings(
            analysis,
            competitor_evidence,
            filtered_ids,
            repair_tasks,
            removed_evidence_ids,
        )
        item_field_evidence_ids = _field_evidence_ids_from_item_bindings(
            item_evidence_bindings
        )
        repaired_field_evidence_ids = _repair_field_evidence_bindings(
            analysis,
            competitor_evidence,
            filtered_ids,
            repair_tasks,
            removed_evidence_ids,
        )
        field_evidence_ids = _merge_field_evidence_bindings(
            item_field_evidence_ids,
            repaired_field_evidence_ids,
            analysis,
            competitor_evidence,
        )
        filtered_ids = _merge_field_and_analysis_evidence_ids(
            field_evidence_ids,
            filtered_ids,
        )
        analysis["item_evidence_bindings_json"] = json.dumps(
            item_evidence_bindings, ensure_ascii=False
        )
        analysis["field_evidence_ids_json"] = json.dumps(
            field_evidence_ids, ensure_ascii=False
        )
        analysis["evidence_ids_json"] = json.dumps(filtered_ids, ensure_ascii=False)
        return {
            **analysis,
            "competitor_id": competitor["id"],
            "competitor_name": competitor["name"],
        }

    new_analyses = []
    if not retry_competitors:
        return {**state, "analyses": _dedupe_analyses_by_competitor(keep, competitors)}
    trace_ctx = call_tracer.get_trace_context()
    with ThreadPoolExecutor(max_workers=min(4, len(retry_competitors))) as executor:
        futures = {executor.submit(analyze_one, c, trace_ctx): c for c in retry_competitors}
        try:
            for future in as_completed(futures, timeout=300):
                new_analyses.append(future.result())
        except TimeoutError:
            for f in futures:
                if f.done():
                    try:
                        new_analyses.append(f.result())
                    except Exception:
                        pass
            timed_out = [futures[f]["name"] for f in futures if not f.done()]
            logger.error(
                "Structured analysis timed out for competitors: %s",
                ", ".join(timed_out),
            )

    accepted_new_analyses = _accept_non_regressive_analyses(
        new_analyses,
        retry_competitors,
        existing_by_competitor,
        qa_repair_tasks,
    )
    analyses = _dedupe_analyses_by_competitor(keep + accepted_new_analyses, competitors)
    analyses.sort(
        key=lambda a: next(
            (i for i, c in enumerate(competitors) if c["id"] == a["competitor_id"]), 0
        )
    )
    return {**state, "analyses": analyses}


def _accept_non_regressive_analyses(
    candidates: list[dict[str, Any]],
    retry_competitors: list[dict[str, Any]],
    previous_by_competitor: dict[str, dict[str, Any]],
    repair_tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidate_by_competitor = {
        str(item.get("competitor_id")): item
        for item in _dedupe_analyses_by_competitor(candidates, retry_competitors)
        if item.get("competitor_id")
    }
    accepted: list[dict[str, Any]] = []
    for competitor in retry_competitors:
        cid = str(competitor.get("id") or "")
        candidate = candidate_by_competitor.get(cid)
        previous = previous_by_competitor.get(cid)
        if candidate is None:
            if previous is not None:
                accepted.append(previous)
            continue
        tasks = _repair_tasks_for_competitor(repair_tasks, competitor)
        if previous is not None and _is_regressive_analysis(candidate, previous, tasks):
            logger.warning(
                "Structured analysis regression detected for %s; keeping previous analysis",
                competitor.get("name") or cid,
            )
            accepted.append(previous)
        else:
            accepted.append(candidate)
    return accepted


def _is_regressive_analysis(
    candidate: dict[str, Any],
    previous: dict[str, Any],
    repair_tasks: list[dict[str, Any]],
) -> bool:
    if _analysis_quality_score(candidate) + 2 < _analysis_quality_score(previous):
        return True
    for task in repair_tasks:
        for field in task.get("fields") or []:
            if _is_placeholder(candidate.get(field)) and not _is_placeholder(
                previous.get(field)
            ):
                return True
    return False


def _analysis_quality_score(analysis: dict[str, Any]) -> int:
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
        score += 2 if not _is_placeholder(analysis.get(field)) else -2
    evidence_count = len(_parse_json_list(analysis.get("evidence_ids_json")))
    score += min(evidence_count, 8)
    return score


def _repair_evidence_bindings(
    selected_ids: list[str],
    analysis: dict[str, Any],
    competitor_evidence: list[dict[str, Any]],
    repair_tasks: list[dict[str, Any]],
    bad_evidence_ids: set[str],
) -> list[str]:
    evidence_by_id = {
        str(item.get("id")): item for item in competitor_evidence if item.get("id")
    }
    selected: list[str] = []
    for eid in selected_ids:
        sid = str(eid)
        if sid in evidence_by_id and sid not in bad_evidence_ids and sid not in selected:
            selected.append(sid)

    priority_ids: list[str] = []
    def add_priority(eid: str) -> None:
        if eid in evidence_by_id and eid not in bad_evidence_ids and eid not in priority_ids:
            priority_ids.append(eid)

    required_ids = _explicit_evidence_ids_from_tasks(repair_tasks)
    for eid in required_ids:
        add_priority(eid)

    fields_to_repair = {
        str(field)
        for task in repair_tasks
        for field in (task.get("fields") or [])
        if field
    }
    for field in fields_to_repair:
        if field not in FIELD_DIMENSION_REQUIREMENTS:
            continue
        if _is_placeholder(analysis.get(field)):
            continue
        needed_dimensions = FIELD_DIMENSION_REQUIREMENTS[field]
        has_matching_selected = any(
            _dimension_matches_any(
                evidence_by_id[eid].get("related_dimension", ""), needed_dimensions
            )
            for eid in selected
            if eid in evidence_by_id
        )
        if has_matching_selected:
            continue
        for item in _rank_evidence_for_dimensions(competitor_evidence, needed_dimensions):
            eid = str(item.get("id") or "")
            if eid:
                add_priority(eid)
                break

    if not selected:
        selected = [
            str(item.get("id"))
            for item in _rank_evidence_for_dimensions(competitor_evidence, set())
            if item.get("id") and str(item.get("id")) not in bad_evidence_ids
        ]
    merged: list[str] = []
    for eid in [*priority_ids, *selected]:
        if eid not in merged:
            merged.append(eid)
    return merged[:16]


def _repair_field_evidence_bindings(
    analysis: dict[str, Any],
    competitor_evidence: list[dict[str, Any]],
    selected_ids: list[str],
    repair_tasks: list[dict[str, Any]],
    bad_evidence_ids: set[str],
) -> dict[str, list[str]]:
    evidence_by_id = {
        str(item.get("id")): item for item in competitor_evidence if item.get("id")
    }
    existing = parse_field_evidence_ids(
        _parse_json_dict(analysis.get("field_evidence_ids_json"))
    )
    fields_to_repair = {
        str(field)
        for task in repair_tasks
        for field in (task.get("fields") or [])
        if field
    }
    result: dict[str, list[str]] = {}

    for field, dimensions in FIELD_DIMENSION_REQUIREMENTS.items():
        if _is_placeholder(analysis.get(field)):
            continue
        ids: list[str] = []
        for evidence_id in existing.get(field, []):
            if (
                evidence_id in evidence_by_id
                and evidence_id not in bad_evidence_ids
                and (not dimensions or _dimension_matches_any(
                    evidence_by_id[evidence_id].get("related_dimension", ""), dimensions
                ))
            ):
                ids.append(evidence_id)

        if not ids and dimensions:
            for evidence_id in selected_ids:
                if (
                    evidence_id in evidence_by_id
                    and evidence_id not in bad_evidence_ids
                    and _dimension_matches_any(
                        evidence_by_id[evidence_id].get("related_dimension", ""),
                        dimensions,
                    )
                ):
                    ids.append(evidence_id)
                    break

        if (not ids or field in fields_to_repair) and dimensions:
            for item in _rank_evidence_for_dimensions(competitor_evidence, dimensions):
                evidence_id = str(item.get("id") or "")
                if (
                    evidence_id
                    and evidence_id not in bad_evidence_ids
                    and evidence_id not in ids
                ):
                    ids.append(evidence_id)
                if len(ids) >= 4:
                    break

        if not ids and not dimensions:
            for evidence_id in selected_ids:
                if evidence_id in evidence_by_id and evidence_id not in bad_evidence_ids:
                    ids.append(evidence_id)
                if len(ids) >= 2:
                    break

        if ids:
            result[field] = ids[:4]

    return result


def _repair_item_evidence_bindings(
    analysis: dict[str, Any],
    competitor_evidence: list[dict[str, Any]],
    selected_ids: list[str],
    repair_tasks: list[dict[str, Any]],
    bad_evidence_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    evidence_by_id = {
        str(item.get("id")): item for item in competitor_evidence if item.get("id")
    }
    existing = parse_item_evidence_bindings(
        _parse_json_dict(analysis.get("item_evidence_bindings_json"))
    )
    selected_set = {str(eid) for eid in selected_ids if eid}
    preferred_ids = set(_explicit_evidence_ids_from_tasks(repair_tasks))
    result: dict[str, list[dict[str, Any]]] = {}

    for field in FIELD_DIMENSION_REQUIREMENTS:
        claims = _analysis_field_claims(analysis.get(field))
        if not claims:
            continue
        existing_rows = existing.get(field, [])
        existing_by_index = {
            int(row.get("item_index") or index): row
            for index, row in enumerate(existing_rows)
        }
        rows: list[dict[str, Any]] = []
        for index, claim in enumerate(claims):
            task_required_ids = _task_evidence_ids_for_item(
                repair_tasks,
                field,
                claim,
                evidence_by_id,
                bad_evidence_ids,
                key="required_evidence_ids",
                legacy_key="must_use_evidence_ids",
            )
            task_preferred_ids = _task_evidence_ids_for_item(
                repair_tasks,
                field,
                claim,
                evidence_by_id,
                bad_evidence_ids,
                key="preferred_evidence_ids",
                legacy_key="suggested_evidence_ids",
            )
            current_ids = []
            if index in existing_by_index:
                current_ids = existing_by_index[index].get("evidence_ids") or []
            ids = [
                evidence_id
                for evidence_id in current_ids
                if evidence_id in evidence_by_id
                and evidence_id not in bad_evidence_ids
                and evidence_matches_claim_policy(
                    evidence_by_id[evidence_id], field, claim, competitor_evidence
                )
            ]
            if task_required_ids:
                ids = task_required_ids + [eid for eid in ids if eid not in task_required_ids]
            if not ids:
                ids = _best_evidence_ids_for_item(
                    field,
                    claim,
                    competitor_evidence,
                    selected_set
                    | preferred_ids
                    | set(task_required_ids)
                    | set(task_preferred_ids),
                    bad_evidence_ids,
                )
            rows.append(
                {
                    "item_index": index,
                    "claim": claim,
                    "evidence_ids": ids[:3],
                    "match_reason": _item_match_reason(field, ids, evidence_by_id)
                    if ids
                    else "未找到可直接支撑该条目的证据",
                }
            )
        if rows:
            result[field] = rows
    return result


def _analysis_field_claims(value: Any) -> list[str]:
    if _is_placeholder(value):
        return []
    parsed = _parse_json_list(value)
    if parsed:
        return [
            _strip_evidence_id_text(str(item)).strip()
            for item in parsed
            if not _is_placeholder(item)
        ]
    text = _strip_evidence_id_text(str(value)).strip()
    return [text] if text and not _is_placeholder(text) else []


def _best_evidence_ids_for_item(
    field: str,
    claim: str,
    evidence: list[dict[str, Any]],
    preferred_ids: set[str],
    bad_evidence_ids: set[str],
) -> list[str]:
    claim_tokens = _claim_tokens(claim)
    candidates = []
    for item in evidence:
        evidence_id = str(item.get("id") or "")
        if not evidence_id or evidence_id in bad_evidence_ids:
            continue
        if not evidence_matches_claim_policy(item, field, claim, evidence):
            continue
        text = " ".join(
            str(item.get(key) or "") for key in ("claim", "summary", "quote")
        )
        overlap = len(claim_tokens & _claim_tokens(text))
        candidates.append(
            (
                (
                    1 if evidence_id in preferred_ids else 0,
                    overlap,
                    1 if item.get("support_type") == "direct" else 0,
                    _safe_float(item.get("relevance_score")),
                    _safe_float(item.get("confidence")),
                    _safe_float(item.get("source_credibility")),
                ),
                evidence_id,
            )
        )
    candidates.sort(reverse=True)
    return [evidence_id for _, evidence_id in candidates[:2]]


def _task_evidence_ids_for_item(
    tasks: list[dict[str, Any]],
    field: str,
    claim: str,
    evidence_by_id: dict[str, dict[str, Any]],
    bad_evidence_ids: set[str],
    *,
    key: str,
    legacy_key: str | None = None,
) -> list[str]:
    result: list[str] = []
    for task in tasks:
        if field not in (task.get("fields") or []):
            continue
        task_claim = str(task.get("claim") or "")
        if task_claim and not _task_claim_matches(claim, task_claim):
            continue
        ids = task.get(key) or (task.get(legacy_key) if legacy_key else None) or []
        if not isinstance(ids, list):
            continue
        for evidence_id in ids:
            eid = str(evidence_id)
            evidence = evidence_by_id.get(eid)
            if (
                evidence
                and eid not in bad_evidence_ids
                and evidence_matches_claim_policy(evidence, field, claim, list(evidence_by_id.values()))
                and eid not in result
            ):
                result.append(eid)
    return result[:3]


def _task_claim_matches(claim: str, task_claim: str) -> bool:
    claim_tokens = _claim_tokens(claim)
    task_tokens = _claim_tokens(task_claim)
    if not claim_tokens or not task_tokens:
        return True
    return len(claim_tokens & task_tokens) >= 2


def _claim_tokens(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", str(text or "").lower())
    tokens = set(re.findall(r"[a-z0-9]{3,}", normalized))
    for i in range(max(0, len(normalized) - 1)):
        tokens.add(normalized[i : i + 2])
    return tokens


def _item_match_reason(
    field: str, evidence_ids: list[str], evidence_by_id: dict[str, dict[str, Any]]
) -> str:
    dimensions = sorted(FIELD_DIMENSION_REQUIREMENTS.get(field, set()))
    sentiments = [
        str(evidence_by_id[eid].get("sentiment") or "neutral")
        for eid in evidence_ids
        if eid in evidence_by_id
    ]
    return "字段维度匹配：" + "/".join(dimensions) + (
        f"；证据情绪={','.join(sentiments)}" if sentiments else ""
    )


def _field_evidence_ids_from_item_bindings(
    item_bindings: dict[str, list[dict[str, Any]]]
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for field, rows in item_bindings.items():
        ids: list[str] = []
        for row in rows:
            for evidence_id in row.get("evidence_ids") or []:
                evidence_id = str(evidence_id)
                if evidence_id and evidence_id not in ids:
                    ids.append(evidence_id)
        if ids:
            result[field] = ids[:6]
    return result


def _merge_field_evidence_bindings(
    item_field_ids: dict[str, list[str]],
    repaired_field_ids: dict[str, list[str]],
    analysis: dict[str, Any],
    competitor_evidence: list[dict[str, Any]],
) -> dict[str, list[str]]:
    evidence_by_id = {
        str(item.get("id")): item for item in competitor_evidence if item.get("id")
    }
    result: dict[str, list[str]] = {}

    for field, dimensions in FIELD_DIMENSION_REQUIREMENTS.items():
        if _is_placeholder(analysis.get(field)):
            continue
        merged: list[str] = []
        for evidence_id in [*item_field_ids.get(field, []), *repaired_field_ids.get(field, [])]:
            if evidence_id in evidence_by_id and evidence_id not in merged:
                merged.append(evidence_id)

        if dimensions and not any(
            _dimension_matches_any(
                evidence_by_id[eid].get("related_dimension", ""), dimensions
            )
            for eid in merged
            if eid in evidence_by_id
        ):
            for evidence_id in repaired_field_ids.get(field, []):
                if evidence_id in evidence_by_id and evidence_id not in merged:
                    merged.append(evidence_id)
                if any(
                    _dimension_matches_any(
                        evidence_by_id[eid].get("related_dimension", ""), dimensions
                    )
                    for eid in merged
                    if eid in evidence_by_id
                ):
                    break

        if merged:
            result[field] = merged[:6]
    return result


def _merge_field_and_analysis_evidence_ids(
    field_evidence_ids: dict[str, list[str]], selected_ids: list[str]
) -> list[str]:
    merged: list[str] = []
    for evidence_id in selected_ids:
        if evidence_id not in merged:
            merged.append(evidence_id)
    for ids in field_evidence_ids.values():
        for evidence_id in ids:
            if evidence_id not in merged:
                merged.append(evidence_id)
    return merged[:16]


def _explicit_evidence_ids_from_tasks(tasks: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for key in (
            "required_evidence_ids",
            "preferred_evidence_ids",
            "must_use_evidence_ids",
            "suggested_evidence_ids",
        ):
            values = task.get(key) or []
            if isinstance(values, list):
                for value in values:
                    evidence_id = str(value or "")
                    if evidence_id.startswith("ev_") and evidence_id not in result:
                        result.append(evidence_id)
        text = " ".join(
            str(task.get(key) or "")
            for key in ("description", "fix_suggestion", "acceptance_criteria")
        )
        for match in re.findall(r"\bev_[A-Za-z0-9_]+\b", text):
            if match not in result:
                result.append(match)
    return result


def _must_remove_evidence_ids_from_tasks(tasks: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for key in ("forbidden_evidence_ids", "must_remove_evidence_ids"):
            values = task.get(key) or []
            if not isinstance(values, list):
                continue
            result.update(str(value) for value in values if value)
    return result


def _clean_analysis_business_fields(analysis: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(analysis)
    for field in (
        "positioning",
        "target_users",
        "core_features_json",
        "pricing_summary",
        "strengths_json",
        "weaknesses_json",
        "opportunities_json",
    ):
        if field in cleaned:
            cleaned[field] = _remove_evidence_ids_from_value(cleaned[field])
    return cleaned


def _remove_evidence_ids_from_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_remove_evidence_ids_from_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _remove_evidence_ids_from_value(item)
            for key, item in value.items()
        }
    if not isinstance(value, str):
        return value
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return _strip_evidence_id_text(value)
    if isinstance(parsed, (list, dict)):
        return json.dumps(_remove_evidence_ids_from_value(parsed), ensure_ascii=False)
    return _strip_evidence_id_text(value)


def _strip_evidence_id_text(text: str) -> str:
    cleaned = re.sub(
        r"（?\s*证据\s*ev_[A-Za-z0-9_]+(?:[、,，\s]+ev_[A-Za-z0-9_]+)*\s*）?",
        "",
        text,
    )
    cleaned = re.sub(r"\[?ev_[A-Za-z0-9_]+\]?", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"[（(]\s*[）)]", "", cleaned)
    return cleaned.strip(" ；;，,")


def _rank_evidence_for_dimensions(
    evidence: list[dict[str, Any]], dimensions: set[str]
) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in evidence
        if item.get("id")
        and (
            not dimensions
            or _dimension_matches_any(item.get("related_dimension", ""), dimensions)
        )
    ]
    return sorted(
        candidates,
        key=lambda item: (
            1 if item.get("support_type") == "direct" else 0,
            _safe_float(item.get("relevance_score")),
            _safe_float(item.get("confidence")),
            _safe_float(item.get("source_credibility")),
        ),
        reverse=True,
    )


def _dimension_matches_any(dimension: Any, preferred: set[str]) -> bool:
    if not preferred:
        return True
    return dimension_matches_any(dimension, preferred)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dedupe_analyses_by_competitor(
    analyses: list[dict[str, Any]], competitors: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    competitor_order = {
        str(competitor.get("id")): index
        for index, competitor in enumerate(competitors)
        if competitor.get("id")
    }
    latest: dict[str, dict[str, Any]] = {}
    original_order: dict[str, int] = {}
    latest_index: dict[str, int] = {}
    for index, analysis in enumerate(analyses or []):
        if not isinstance(analysis, dict):
            continue
        key = str(
            analysis.get("competitor_id")
            or analysis.get("competitor_name")
            or analysis.get("id")
            or index
        )
        original_order.setdefault(key, index)
        existing = latest.get(key)
        if existing is None or _analysis_sort_key(analysis, index) >= _analysis_sort_key(
            existing, latest_index[key]
        ):
            latest[key] = analysis
            latest_index[key] = index
    return sorted(
        latest.values(),
        key=lambda item: (
            competitor_order.get(str(item.get("competitor_id")), len(competitor_order)),
            original_order.get(
                str(
                    item.get("competitor_id")
                    or item.get("competitor_name")
                    or item.get("id")
                    or ""
                ),
                0,
            ),
        ),
    )


def _analysis_sort_key(analysis: dict[str, Any], index: int) -> tuple[int, str, int, str]:
    return (
        _safe_int(analysis.get("analysis_iteration")),
        str(analysis.get("created_at") or ""),
        index,
        str(analysis.get("id") or ""),
    )


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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
        return any(
            marker in lowered
            for marker in (
                "暂无",
                "未涉及",
                "无相关",
                "待补充",
                "占位",
                "mock",
                "n/a",
                "unknown",
            )
        )
    return value is None


def _active_focus_items(requirement: dict) -> list[dict]:
    """Return user-explicit focus items from the normalized focus profile."""
    profile = (
        requirement.get("focus_profile")
        if isinstance(requirement.get("focus_profile"), dict)
        else {}
    )
    if not isinstance(profile, dict):
        return []
    items = []
    for f in profile.get("explicit_focuses") or []:
        if isinstance(f, dict) and f.get("label"):
            items.append(f)
    return items[:6]


def _repair_tasks_for_competitor(
    tasks: list[dict[str, Any]], competitor: dict[str, Any]
) -> list[dict[str, Any]]:
    result = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("competitor_id") and task.get("competitor_id") == competitor.get("id"):
            result.append(task)
        elif task.get("competitor_name") == competitor.get("name"):
            result.append(task)
    return result


def _normalize_custom_focus_analysis(
    value: object, focus_items: list[dict], evidence: list[dict]
) -> str:
    if not focus_items:
        return "[]"
    focus_by_key = {
        str(item.get("key") or ""): item
        for item in focus_items
        if isinstance(item, dict) and item.get("key") and item.get("label")
    }
    focus_by_label = {
        str(item.get("label") or "").strip(): item
        for item in focus_items
        if isinstance(item, dict) and item.get("key") and item.get("label")
    }
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = []
    if not isinstance(parsed, list):
        parsed = []
    valid_evidence_ids = {item.get("id") for item in evidence if item.get("id")}
    normalized = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        raw_key = str(item.get("focus_key") or item.get("key") or "").strip()
        raw_label = str(item.get("label") or "").strip()
        focus_schema_item = focus_by_key.get(raw_key) or focus_by_label.get(raw_label)
        if not focus_schema_item:
            continue
        focus_key = str(focus_schema_item.get("key") or "").strip()
        label = str(focus_schema_item.get("label") or "").strip()
        evidence_ids = (
            [
                str(evidence_id)
                for evidence_id in item.get("evidence_ids", [])
                if evidence_id in valid_evidence_ids
            ]
            if isinstance(item.get("evidence_ids"), list)
            else []
        )
        normalized.append(
            {
                "focus_key": focus_key[:64],
                "label": label[:80],
                "verdict": str(item.get("verdict") or "证据中未涉及")[:800],
                "evidence_ids": evidence_ids[:6],
                "confidence": _bounded_confidence(item.get("confidence")),
            }
        )
    if normalized:
        return json.dumps(normalized[:6], ensure_ascii=False)
    empty_items = [
        {
            "focus_key": item["key"],
            "label": item["label"],
            "verdict": "证据中未涉及",
            "evidence_ids": [],
            "confidence": 0.0,
        }
        for item in focus_items
    ]
    return json.dumps(empty_items, ensure_ascii=False)


def _bounded_confidence(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score > 1:
        score = score / 100
    return min(1.0, max(0.0, score))


def _parse_json_list(value: Any) -> list[str]:
    """Parse a JSON string or list into a flat list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    return []


def _parse_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
