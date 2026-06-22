import json
import logging
import re
import traceback
import difflib
from datetime import datetime
from typing import Any

from openai import OpenAI
from app.core.config import get_settings
from app.providers.llm.mock import MockLLMProvider
from app.services import call_tracer

logger = logging.getLogger(__name__)


def _extract_citation_fingerprints(markdown: str) -> list[dict[str, Any]]:
    """Extract context fingerprints for each citation in the markdown."""
    fingerprints = []
    # Match [[n]] or [n]
    matches = list(re.finditer(r"\[{2}(\d+)\]{2}|\[(\d+)\]", markdown))

    for match in matches:
        ref_id = int(match.group(1) or match.group(2))
        start = match.start()
        end = match.end()

        prefix = markdown[max(0, start - 40) : start].strip()
        suffix = markdown[end : min(len(markdown), end + 40)].strip()

        prefix = re.sub(r"\[{2}\d+\]{2}|\[\d+\]", "", prefix)
        suffix = re.sub(r"\[{2}\d+\]{2}|\[\d+\]", "", suffix)

        # Take the last/first few words as they are more likely to be preserved
        prefix_words = prefix.split()
        suffix_words = suffix.split()

        prefix_short = " ".join(prefix_words[-4:]) if prefix_words else ""
        suffix_short = " ".join(suffix_words[:4]) if suffix_words else ""

        fingerprints.append(
            {
                "id": ref_id,
                "prefix": prefix,
                "suffix": suffix,
                "prefix_short": prefix_short,
                "suffix_short": suffix_short,
                "full_match": match.group(0),
            }
        )
    return fingerprints


def _stitch_citations(new_markdown: str, fingerprints: list[dict[str, Any]]) -> str:
    """Try to re-insert missing citations using robust context matching."""
    if not fingerprints:
        return new_markdown

    result_markdown = new_markdown
    existing_ids = {
        int(a or b)
        for a, b in re.findall(r"\[{2}(\d+)\]{2}|\[(\d+)\]", result_markdown)
    }

    missing_fingerprints = [f for f in fingerprints if f["id"] not in existing_ids]
    if not missing_fingerprints:
        return result_markdown

    for f in missing_fingerprints:
        best_pos = -1

        if len(f["prefix"]) >= 10 and len(f["suffix"]) >= 10:
            pattern = re.escape(f["prefix"]) + r".{0,150}?" + re.escape(f["suffix"])
            match = re.search(pattern, result_markdown, re.DOTALL)
            if match:
                best_pos = match.start() + len(f["prefix"])

        if best_pos == -1:
            prefix_words = [w for w in re.findall(r"\w+", f["prefix"]) if len(w) > 1]
            suffix_words = [w for w in re.findall(r"\w+", f["suffix"]) if len(w) > 1]

            if prefix_words and suffix_words:
                last_p = prefix_words[-1]
                first_s = suffix_words[0]
                pattern = re.escape(last_p) + r".{0,50}?" + re.escape(first_s)
                match = re.search(pattern, result_markdown, re.DOTALL | re.IGNORECASE)
                if match:
                    best_pos = match.start() + len(last_p)

        if best_pos == -1 and f["prefix_short"] and f["suffix_short"]:
            pattern = (
                re.escape(f["prefix_short"])
                + r".{0,200}?"
                + re.escape(f["suffix_short"])
            )
            match = re.search(pattern, result_markdown, re.DOTALL)
            if match:
                best_pos = match.start() + len(f["prefix_short"])

        if best_pos == -1:
            prefix_words = [w for w in re.findall(r"\w+", f["prefix"]) if len(w) > 1]
            if len(prefix_words) >= 2:
                anchor = " ".join(prefix_words[-2:])
                pos = result_markdown.rfind(anchor)
                if pos != -1:
                    best_pos = pos + len(anchor)

        if best_pos == -1:
            suffix_words = [w for w in re.findall(r"\w+", f["suffix"]) if len(w) > 1]
            if len(suffix_words) >= 2:
                anchor = " ".join(suffix_words[:2])
                pos = result_markdown.find(anchor)
                if pos != -1:
                    best_pos = pos

        if best_pos != -1:
            citation = f" [[{f['id']}]]"
            context_area = result_markdown[
                max(0, best_pos - 15) : min(len(result_markdown), best_pos + 15)
            ]
            if f"[{f['id']}]" in context_area or f"[[{f['id']}]]" in context_area:
                continue

            before = result_markdown[:best_pos].rstrip()
            after = result_markdown[best_pos:].lstrip()
            in_table_cell = before.endswith("|") or after.startswith("|")
            if in_table_cell:
                if after.startswith("|"):
                    result_markdown = before + citation + " " + after
                else:
                    result_markdown = before + citation + after
            else:
                result_markdown = before + citation + " " + after

    return result_markdown


def _normalize_table_name(name: str) -> str:
    cleaned = re.sub(r"\*+", "", name).strip()
    cleaned = re.sub(r"（重点关注）|\(重点关注\)", "", cleaned).strip()
    cleaned = cleaned.lower()
    cleaned = re.sub(r"[\s\-_]+", "", cleaned)
    return cleaned


def _parse_table_grid(markdown: str) -> list[list[str]]:
    """Parse a markdown table into a 2D grid of cell contents, preserving empty cells."""
    rows: list[list[str]] = []
    for line in markdown.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if stripped.endswith("|"):
            inner = stripped[1:-1]
        else:
            inner = stripped[1:]
        cells = [c.strip() for c in inner.split("|")]
        if not cells:
            continue
        if all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        rows.append(cells)
    return rows


def _build_semantic_citation_map(
    markdown: str,
) -> dict[tuple[str, str], list[int]]:
    """Build a mapping from (normalized_dimension, normalized_competitor) -> citation IDs."""
    grid = _parse_table_grid(markdown)
    if len(grid) < 2:
        return {}
    header = grid[0]
    competitor_names = [_normalize_table_name(c) for c in header[1:]]
    citation_map: dict[tuple[str, str], list[int]] = {}
    for row in grid[1:]:
        if not row:
            continue
        dimension_name = _normalize_table_name(row[0])
        for col_idx, cell in enumerate(row[1:]):
            if col_idx >= len(competitor_names):
                break
            ids = [
                int(a or b) for a, b in re.findall(r"\[{2}(\d+)\]{2}|\[(\d+)\]", cell)
            ]
            if ids:
                citation_map[(dimension_name, competitor_names[col_idx])] = ids
    return citation_map


def _fuzzy_match_cell(old_cell: str, new_cell: str) -> bool:
    """Check if two cells are talking about the same thing despite rephrasing."""
    old_clean = re.sub(r"\[{2}\d+\]{2}|\[\d+\]", "", old_cell).strip()
    new_clean = re.sub(r"\[{2}\d+\]{2}|\[\d+\]", "", new_cell).strip()
    if not old_clean or not new_clean:
        return False
    old_keywords = set(re.findall(r"[\w]{2,}", old_clean.lower()))
    new_keywords = set(re.findall(r"[\w]{2,}", new_clean.lower()))
    if not old_keywords or not new_keywords:
        return False
    overlap = old_keywords & new_keywords
    return len(overlap) / min(len(old_keywords), len(new_keywords)) >= 0.4


def _fuzzy_match_dimension(norm_dim: str, known_dims: list[str]) -> str | None:
    if not norm_dim or not known_dims:
        return None
    if norm_dim in known_dims:
        return norm_dim
    best_match: str | None = None
    best_ratio: float = 0.0
    for d in known_dims:
        shorter = min(len(norm_dim), len(d))
        if shorter == 0:
            continue
        seq = difflib.SequenceMatcher(None, norm_dim, d)
        ratio = seq.ratio()
        if ratio > best_ratio and ratio >= 0.55:
            best_ratio = ratio
            best_match = d
    return best_match


def _fuzzy_match_competitor(norm_comp: str, known_comps: list[str]) -> str | None:
    if not norm_comp or not known_comps:
        return None
    if norm_comp in known_comps:
        return norm_comp
    scores: list[tuple[float, str]] = []
    for c in known_comps:
        seq = difflib.SequenceMatcher(None, norm_comp, c)
        scores.append((seq.ratio(), c))
    scores.sort(key=lambda x: x[0], reverse=True)
    if not scores:
        return None
    best_ratio, best_comp = scores[0]
    if best_ratio < 0.85:
        return None
    if len(scores) > 1 and scores[1][0] >= best_ratio - 0.15:
        return None
    return best_comp


def _table_aware_stitch(
    old_markdown: str,
    new_markdown: str,
    fingerprints: list[dict[str, Any]],
    excluded_citation_ids: set[int] | None = None,
) -> str:
    """Table-aware citation recovery using semantic coordinate alignment."""
    if not fingerprints:
        return new_markdown

    new_ids = {
        int(a or b) for a, b in re.findall(r"\[{2}(\d+)\]{2}|\[(\d+)\]", new_markdown)
    }
    missing_ids = {f["id"] for f in fingerprints if f["id"] not in new_ids}
    if excluded_citation_ids:
        missing_ids -= excluded_citation_ids
    if not missing_ids:
        return new_markdown

    old_citation_map = _build_semantic_citation_map(old_markdown)
    if not old_citation_map:
        return _stitch_citations(new_markdown, fingerprints)

    new_grid = _parse_table_grid(new_markdown)
    if len(new_grid) < 2:
        return _stitch_citations(new_markdown, fingerprints)

    new_header = new_grid[0]
    new_competitor_names = [_normalize_table_name(c) for c in new_header[1:]]

    known_dims = list({k[0] for k in old_citation_map})
    known_comps = list({k[1] for k in old_citation_map})

    dim_alias_map: dict[str, str] = {}
    comp_alias_map: dict[str, str] = {}

    for nd in set(new_competitor_names) - set(known_comps):
        matched = _fuzzy_match_competitor(nd, known_comps)
        if matched:
            comp_alias_map[nd] = matched

    for row in new_grid[1:]:
        if not row:
            continue
        nd = _normalize_table_name(row[0])
        if nd and nd not in known_dims and nd not in dim_alias_map:
            matched = _fuzzy_match_dimension(nd, known_dims)
            if matched:
                dim_alias_map[nd] = matched

    row_dimension_names: list[str] = []
    for row in new_grid[1:]:
        if row:
            row_dimension_names.append(_normalize_table_name(row[0]))
        else:
            row_dimension_names.append("")

    new_lines = new_markdown.split("\n")
    data_row_counter = 0
    result_lines: list[str] = []

    for line in new_lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            result_lines.append(line)
            continue

        if stripped.endswith("|"):
            inner = stripped[1:-1]
        else:
            inner = stripped[1:]
        cells = [c.strip() for c in inner.split("|")]

        if not cells:
            result_lines.append(line)
            continue

        if all(set(c) <= {"-", ":", " "} for c in cells):
            result_lines.append(line)
            continue

        is_header = data_row_counter == 0
        if is_header:
            result_lines.append(line)
            data_row_counter += 1
            continue

        if data_row_counter - 1 < len(row_dimension_names):
            norm_dim = row_dimension_names[data_row_counter - 1]
        else:
            norm_dim = ""

        resolved_dim = dim_alias_map.get(norm_dim, norm_dim)

        restored_line = line
        for col_idx in range(1, len(cells)):
            if col_idx - 1 >= len(new_competitor_names):
                break
            norm_comp = new_competitor_names[col_idx - 1]
            resolved_comp = comp_alias_map.get(norm_comp, norm_comp)

            cell = cells[col_idx]
            cell_citation_ids: list[int] = []

            lookup_key = (resolved_dim, resolved_comp)
            if lookup_key in old_citation_map:
                cell_citation_ids = old_citation_map[lookup_key]

            if resolved_dim != norm_dim:
                alt_key = (norm_dim, resolved_comp)
                if alt_key in old_citation_map:
                    for cid in old_citation_map[alt_key]:
                        if cid not in cell_citation_ids:
                            cell_citation_ids.append(cid)

            if resolved_comp != norm_comp:
                alt_key = (resolved_dim, norm_comp)
                if alt_key in old_citation_map:
                    for cid in old_citation_map[alt_key]:
                        if cid not in cell_citation_ids:
                            cell_citation_ids.append(cid)

            to_restore = [
                cid
                for cid in cell_citation_ids
                if cid in missing_ids and f"[[{cid}]]" not in cell
            ]

            if to_restore:
                citation_str = "".join(f" [[{cid}]]" for cid in to_restore)
                cells[col_idx] = cell + citation_str
                restored_line = "| " + " | ".join(cells) + " |"
                for cid in to_restore:
                    missing_ids.discard(cid)

        result_lines.append(restored_line)
        data_row_counter += 1

    result = "\n".join(result_lines)

    remaining = [f for f in fingerprints if f["id"] in missing_ids]
    if remaining:
        full_fingerprints = _extract_citation_fingerprints(old_markdown)
        remaining_full = [f for f in full_fingerprints if f["id"] in missing_ids]
        if remaining_full:
            result = _stitch_citations(result, remaining_full)

    return result


def _safe_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.72
    if confidence > 1:
        confidence = confidence / 100
    return min(max(confidence, 0.0), 1.0)


def _cap_search_results(
    results: list[dict[str, Any]], *, max_items: int = 10, max_chars: int = 6000
) -> list[dict[str, Any]]:
    trimmed = []
    total = 0
    for item in results[:max_items]:
        slim = {
            k: v[:300] if isinstance(v, str) and len(v) > 300 else v
            for k, v in item.items()
            if k != "raw_content"
        }
        dumped = json.dumps(slim, ensure_ascii=False)
        if total + len(dumped) > max_chars and trimmed:
            break
        trimmed.append(slim)
        total += len(dumped)
    return trimmed


def _parse_source_metadata(source: dict[str, Any]) -> dict[str, Any]:
    metadata = source.get("metadata")
    if not isinstance(metadata, dict):
        metadata_json = source.get("metadata_json")
        if isinstance(metadata_json, str) and metadata_json:
            try:
                parsed = json.loads(metadata_json)
            except json.JSONDecodeError:
                parsed = {}
            metadata = parsed if isinstance(parsed, dict) else {}
        else:
            metadata = {}
    return metadata


def _source_report_summary(
    source: dict[str, Any], reference_id: int | None = None
) -> dict[str, Any]:
    metadata = _parse_source_metadata(source)
    summary = {
        "title": str(source.get("title", ""))[:80],
        "url": source.get("url", ""),
        "source_type": source.get("source_type", ""),
        "source_type_label": metadata.get("source_type_label"),
        "credibility_score": metadata.get(
            "credibility_score", source.get("credibility_score", 0)
        ),
        "rank_score": metadata.get("rank_score", source.get("rank_score", 0)),
        "dimension": metadata.get("dimension"),
        "query": metadata.get("query"),
        "classification_reason": metadata.get("classification_reason"),
    }
    if reference_id is not None:
        summary["reference_id"] = reference_id
    return summary


def _format_reference_section(
    sources: list[dict[str, Any]], cited_ids: set[int] | None = None
) -> str:
    if not sources:
        return ""
    sorted_sources = sorted(
        [s for s in sources if isinstance(s.get("reference_id"), int)],
        key=lambda s: s.get("reference_id", 0),
    )
    lines = ["## 参考来源", ""]
    for source in sorted_sources:
        reference_id = source.get("reference_id")
        if not isinstance(reference_id, int):
            continue
        summary = _source_report_summary(source, reference_id)
        title = (
            str(summary.get("title") or f"来源 {reference_id}")
            .replace("\n", " ")
            .strip()
        )
        url = str(summary.get("url") or "").strip()
        source_label = (
            summary.get("source_type_label") or summary.get("source_type") or "来源"
        )
        credibility = summary.get("credibility_score")
        weight_text = (
            f"，权重 {float(credibility):.2f}"
            if isinstance(credibility, int | float)
            else ""
        )
        if url:
            lines.append(
                f"{reference_id}. [[{reference_id}]]({url}) [{title}]({url}) - {source_label}{weight_text}"
            )
        else:
            lines.append(
                f"{reference_id}. [{reference_id}] {title} - {source_label}{weight_text}"
            )
    return "\n".join(lines)


def _split_compound_citations(text: str) -> str:
    def _expand(match: re.Match[str]) -> str:
        inner = match.group(1)
        nums = re.split(r"[,，、\s]+", inner)
        parts = [f"[[{n.strip()}]]" for n in nums if n.strip().isdigit()]
        return " ".join(parts) if parts else match.group(0)

    text = re.sub(
        r"\[\[([0-9]{1,2}[,，、\s]+[0-9]{1,2}(?:[,，、\s]+[0-9]{1,2})*)\]\]",
        _expand,
        text,
    )
    text = re.sub(
        r"\[([0-9]{1,2}[,，、\s]+[0-9]{1,2}(?:[,，、\s]+[0-9]{1,2})*)\](?!\()",
        _expand,
        text,
    )
    return text


def _normalize_inline_citations(
    markdown_content: str, max_reference_id: int | None = None
) -> str:
    normalized = _split_compound_citations(markdown_content)
    normalized = re.sub(
        r"(?<!\[)\[(\d{1,2})\]\((https?://[^)\s]+)\)", r"[[\1]](\2)", normalized
    )
    normalized = re.sub(r"(?<!\[)\[(\d{1,2})\](?!\()(?!\])", r"[[\1]]", normalized)
    if max_reference_id is None:
        return normalized

    def strip_unknown_reference_url(match: re.Match[str]) -> str:
        reference_id = int(match.group(1))
        if 1 <= reference_id <= max_reference_id:
            return match.group(0)
        return ""

    normalized = re.sub(
        r"\[\[(\d{1,2})\]\]\((https?://[^)\s]+)\)",
        strip_unknown_reference_url,
        normalized,
    )

    def strip_unknown_reference(match: re.Match[str]) -> str:
        reference_id = int(match.group(1))
        if 1 <= reference_id <= max_reference_id:
            return match.group(0)
        return ""

    return re.sub(r"\[\[(\d{1,2})\]\]", strip_unknown_reference, normalized)


def _ensure_reference_section(
    markdown_content: str, sources: list[dict[str, Any]]
) -> str:
    existing_ids = {
        s.get("reference_id") for s in sources if isinstance(s.get("reference_id"), int)
    }
    next_id = max(existing_ids, default=0) + 1
    working_sources: list[dict[str, Any]] = []
    for s in sources:
        ws = {**s}
        if ws.get("reference_id") is None:
            ws["reference_id"] = next_id
            next_id += 1
        working_sources.append(ws)

    stripped = markdown_content.strip()
    body_only = re.sub(
        r"\n*##\s*(?:(?:\d+|[一二三四五六七八九十]+)[\.、]\s*)?(?:参考来源|参考文献|References)\s*\n[\s\S]*$",
        "",
        stripped,
    ).strip()
    cited_ids = {
        int(a or b) for a, b in re.findall(r"\[{2}(\d+)\]{2}|\[(\d+)\]", body_only)
    }
    reference_section = _format_reference_section(working_sources, cited_ids)
    max_reference_id = max(
        (
            s.get("reference_id", 0)
            for s in working_sources
            if isinstance(s.get("reference_id"), int)
        ),
        default=0,
    )
    if not reference_section:
        return _normalize_inline_citations(stripped)
    normalized = _normalize_inline_citations(
        stripped, max_reference_id=max_reference_id
    )
    pattern = r"\n*##\s*(?:(?:\d+|[一二三四五六七八九十]+)[\.、]\s*)?(?:参考来源|参考文献|References)\s*\n[\s\S]*$"
    result = normalized
    if re.search(pattern, normalized):
        result = re.sub(pattern, f"\n\n{reference_section}", normalized).strip()
    else:
        result = f"{normalized}\n\n{reference_section}".strip()

    valid_ids = {
        s.get("reference_id")
        for s in working_sources
        if isinstance(s.get("reference_id"), int)
    }
    body_ids = {
        int(a or b) for a, b in re.findall(r"\[{2}(\d+)\]{2}|\[(\d+)\]", result)
    }
    orphan_ids = body_ids - valid_ids
    if orphan_ids:
        logger.warning(
            "Citation consistency: body references %s have no matching source (valid: %s)",
            orphan_ids,
            sorted(valid_ids),
        )

    return result


def _validate_citation_whitelist(
    markdown_content: str, citation_bundle: list[dict[str, Any]]
) -> str:
    if not citation_bundle:
        return markdown_content
    all_allowed: set[int] = set()
    for competitor in citation_bundle:
        for claim in competitor.get("claims", []):
            for rid in claim.get("allowed_reference_ids", []):
                if isinstance(rid, int):
                    all_allowed.add(rid)
            for ev in claim.get("evidence", []):
                rid = ev.get("source_reference_id")
                if isinstance(rid, int):
                    all_allowed.add(rid)
    if not all_allowed:
        return markdown_content

    def remove_disallowed(match: re.Match[str]) -> str:
        rid = int(match.group(1) or match.group(2))
        if rid in all_allowed:
            return match.group(0)
        logger.warning(
            "Removing disallowed citation [[%d]] not in any claim's evidence", rid
        )
        return ""

    return re.sub(
        r"\[\[(\d{1,2})\]\](?:\([^)]*\))?|\[(\d{1,2})\](?!\()",
        remove_disallowed,
        markdown_content,
    )


def _strip_code_fences(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1 :]
        else:
            content = content[3:]
            if content.startswith("json") or content.startswith("JSON"):
                content = content[4:]
        content = content.strip()
    if content.endswith("```"):
        content = content[:-3].strip()
    return content


def _extract_token_count(response: Any) -> int | None:
    try:
        usage = getattr(response, "usage", None)
        if usage is not None:
            total = getattr(usage, "total_tokens", None)
            if total is not None:
                return total
    except Exception:
        pass
    return None


class ArkLLMProvider:
    name = "ark"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.ark_api_key:
            raise ValueError("ARK_API_KEY is required when LLM_PROVIDER=ark.")
        self.model = settings.ark_endpoint_id or settings.ark_model
        if not self.model:
            raise ValueError(
                "ARK_ENDPOINT_ID or ARK_MODEL is required when LLM_PROVIDER=ark."
            )
        self.client = OpenAI(
            api_key=settings.ark_api_key,
            base_url=settings.ark_base_url,
            timeout=60.0,
            max_retries=2,
        )
        self.temperature: float | None = 0.2
        self.fallback = MockLLMProvider()

    def understand_requirement(self, user_requirement: str) -> dict[str, Any]:
        fallback = self.fallback.understand_requirement(user_requirement)
        prompt = f"""
你是竞品分析系统的需求理解 Agent。请把用户输入解析成严格 JSON，不要输出 Markdown。

用户输入：{user_requirement}

=== 内部两步思考逻辑（无需输出） ===
1. 意图解析：分析用户文本，隐式提取出核心客群 (Target User)、核心能力 (Core Features)、行业领域 (Domain)。
2. 关键词组装：摒弃自然语言陈述（如"我想做..."、"如何实现..."），将核心标签翻译成精准搜索词组。

=== 混合检索 Query 生成规则 ===
1. 数量限制：根据用户需求的复杂度，灵活生成 1~3 个并行的搜索 Query。
2. 长度限制：每个 Query 必须极其严苛地控制在 40 个字符（Characters）以内。
3. 语言与市场分发策略（核心）：
   - 严禁在单个 Query 中进行中英文混杂。
   - 采用混合检索：至少包含 1 个针对全球市场的纯英文 Query（寻找海外前沿技术模型）；以及 1 个针对国内市场的纯中文 Query（寻找本土落地竞品）。
   - 英文 Query 优先使用英文专业术语，善用双引号精确匹配，可适当加入 2026 获取最新资讯。
   - 中文 Query 专注本土市场，寻找国内同类产品和竞品。

JSON schema:
{{
  "input_type": "existing_product | product_idea | mixed | unclear",
  "target_product": "已有产品名称或 null",
  "product_description": "产品想法描述或 null",
  "domain": "产品或赛道名称",
  "summary": "一句话说明分析目标",
  "target_users": ["目标用户1", "目标用户2"],
  "core_capabilities": ["核心能力1"],
  "use_cases": ["场景1"],
  "possible_market_category": "可能赛道",
  "analysis_dimensions": ["维度1", "维度2", "维度3"],
  "needs_clarification": false,
  "clarification_questions": [],
  "confidence": 0.0,
  "warnings": [],
  "queries": ["混合检索Query1（英文）", "混合检索Query2（中文）", "混合检索Query3（可选）"],
  "query": "用于搜索竞品的中文查询词（兼容旧版）"
}}
"""
        return self._json_chat(prompt, fallback)

    def extract_focus_profile(
        self, user_requirement: str, requirement: dict[str, Any]
    ) -> dict[str, Any]:
        fallback = self.fallback.extract_focus_profile(user_requirement, requirement)
        prompt = f"""
你是竞品分析系统的个性化关注点识别 Agent。请根据用户原始输入和已结构化需求，判断报告是否需要围绕特定侧重点展开。

用户原始输入：{user_requirement}
结构化需求：{json.dumps(requirement, ensure_ascii=False)}

判断规则：
- 如果用户明确表达了关注点，例如功能对比、产品能力、本地存储、隐私安全、AI 能力、价格、团队协作、迁移成本、开放 API、特定人群等，放入 explicit_focuses。
- explicit_focuses 必须只来自“用户原始输入”的直接表达；不要把结构化需求中自动补齐的 analysis_dimensions、core_capabilities、use_cases、summary 推断成用户显式关注点。
- 如果用户没有明确表达关注点，inferred_focuses 必须返回空数组；不要把领域常见维度推断成用户关注点。
- 判断是否反问，不要依据文本长度，而要依据“缺少偏好是否会改变竞品选择、资料检索方向、报告排序和最终建议”。
- 如果用户只给出一个宽泛品类或赛道，并要求做竞品分析，但没有说明决策场景或关注维度，必须设置 clarification_needed=true。典型例子：
  - “我想分析笔记软件的竞品” -> 必须反问，因为本地存储/隐私、AI 能力、团队协作、价格、迁移成本会导向不同竞品和证据。
  - “分析 AI 会议纪要工具竞品” -> 必须反问，因为转写质量、CRM 集成、数据安全、团队协作、价格会导向不同报告重点。
  - “帮我看看 CRM 工具竞品” -> 必须反问，因为销售团队规模、集成生态、价格、行业方案会改变分析口径。
- 如果用户已经给出足够清晰的目标和侧重点，例如“重点关注笔记软件是否本地存储和隐私安全”，不要反问，直接放入 explicit_focuses。
- 如果用户没有明确侧重点，但需求已经包含具体决策目标，例如“给 20 人销售团队选便宜的会议纪要工具”，可以不反问；只有用户原文能直接支持的侧重点才能放入 explicit_focuses，否则保持空数组并在 assumptions 说明默认均衡分析口径。
- 反问只能问 1 个问题，且要给出 4-6 个可选方向，方便用户快速回答。
- 如果 clarification_needed=true，clarifying_question 不能为空；如果 clarification_needed=false，clarifying_question 必须为 null。

输出严格 JSON，不要输出 Markdown。
JSON schema:
{{
  "explicit_focuses": [
    {{
      "key": "snake_case_key",
      "label": "用户可读的关注点名称",
      "priority": "high|medium|low",
      "evidence_expectation": "需要什么类型证据来回答这个关注点",
      "query_terms": ["用于检索的中文或英文关键词"]
    }}
  ],
  "inferred_focuses": [
    {{
      "key": "snake_case_key",
      "label": "推断关注点名称",
      "priority": "high|medium|low",
      "evidence_expectation": "证据要求",
      "query_terms": ["关键词"]
    }}
  ],
  "clarification_needed": <boolean>,
  "clarifying_question": <string | null>,
  "assumptions": ["继续分析时采用的假设"]
}}

示例1（需要反问）：
{{
  "explicit_focuses": [],
  "inferred_focuses": [],
  "clarification_needed": true,
  "clarifying_question": "你最关注笔记软件的哪些方面？可选：本地存储与隐私、AI 能力、团队协作、价格、迁移成本、开放 API",
  "assumptions": ["用户可能关注 AI 能力"]
}}

示例2（不需反问）：
{{
  "explicit_focuses": [{{"key": "local_storage_privacy", "label": "本地存储与隐私安全", "priority": "high", "evidence_expectation": "本地存储方案和数据加密政策", "query_terms": ["local-first notes", "本地存储 笔记"]}}],
  "inferred_focuses": [],
  "clarification_needed": false,
  "clarifying_question": null,
  "assumptions": []
}}
"""
        return self._json_chat(prompt, fallback)

    def understand_target(
        self, requirement: dict[str, Any], target_search_results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        fallback = self.fallback.understand_target(requirement, target_search_results)
        truncated_results = _cap_search_results(
            target_search_results, max_items=10, max_chars=6000
        )
        prompt = f"""
你是竞品分析系统中的目标理解 Agent。请基于需求理解和目标搜索结果，先形成目标对象画像，不要直接推荐竞品。

需求理解：{json.dumps(requirement, ensure_ascii=False)}
目标搜索结果：{json.dumps(truncated_results, ensure_ascii=False)}

要求：
- category 必须是具体赛道，例如"即时通讯与社交平台""移动支付与生活服务""企业协作办公平台"，不要输出"某某所在产品赛道"这类占位。
- core_capabilities 必须来自目标产品真实能力或搜索结果，不要输出"核心流程自动化、信息整理、报告生成"这类通用占位。
- 如果搜索结果混入广告平台、开发者文档、企业版或同品牌其他产品，要区分它们与目标产品本体，不要让噪声主导画像。
- 对 QQ、微信、小红书、B站、抖音、淘宝等 C 端产品，优先识别消费级社交、内容、交易、支付、社区等真实用户场景。
- 如果用户输入的是已有产品名，必须先明确这个产品到底解决什么问题、属于什么具体赛道，再生成竞品检索口径。例如 Lovable 应识别为 AI app builder / AI product prototyping / PRD-to-prototype 相关工具，而不是泛泛的“AI 工具”。
- competitor_search_category 必须是用于找竞品的具体赛道短语，不要照抄产品名。
- competitor_search_terms 必须包含 4-8 个可直接搜索的中英文短语，围绕产品定位、核心能力和使用场景找同类产品。
- non_competitor_boundaries 用来说明哪些相邻品类不要误判为竞品。

输出严格 JSON，不要输出 Markdown。
JSON schema:
{{
  "name": "目标产品或产品想法名称",
  "category": "所属赛道",
  "positioning": "产品定位",
  "target_users": ["目标用户"],
  "core_capabilities": ["核心能力"],
  "primary_use_cases": ["使用场景"],
  "competitor_search_category": "用于搜索竞品的具体赛道/品类",
  "competitor_search_terms": ["英文检索词", "中文检索词"],
  "non_competitor_boundaries": ["不应纳入竞品的相邻品类"],
  "source_ids": ["支撑来源 URL"],
  "evidence_ids": [],
  "confidence": 0.0,
  "warnings": []
}}
"""
        result = self._json_chat(prompt, fallback)
        if result is fallback:
            return fallback
        return result

    def extract_competitors(
        self,
        requirement: dict[str, Any],
        target_understanding: dict[str, Any],
        search_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        fallback = self.fallback.extract_competitors(
            requirement, target_understanding, search_results
        )
        truncated_search = _cap_search_results(
            search_results, max_items=12, max_chars=8000
        )
        prompt = f"""
你是竞品发现 Agent。请从真实搜索结果中提取与目标对象同赛道的具体产品/品牌/服务名称。

需求理解：{json.dumps(requirement, ensure_ascii=False)}
目标对象理解：{json.dumps(target_understanding, ensure_ascii=False)}
竞品发现搜索结果：{json.dumps(truncated_search, ensure_ascii=False)}

严格要求：
1. name 字段必须是一个具体的产品名、品牌名、App名或服务名。例如："Litter-Robot"、"CATLINK"、"小佩"、"Stripe"、"PayPal"。
2. name 绝对不能是：
   - 行业/市场描述（如"宠物智能用品行业"、"全球智能猫砂盒市场"）
   - 数字/金额（如"亿元"、"年的"、"2024年"）
   - 句子片段或中文短语（如"此外"、"其中"、"但是"）
   - 泛概念词（如"竞品"、"替代方案"、"主要玩家"）
3. 优先从搜索结果中出现的品牌名、产品名、公司名提取。
4. 如果搜索结果中提到了具体品牌（如"CATLINK智能猫砂盆"），提取品牌名"CATLINK"。
5. 排除目标产品自身。
6. 不要固定输出数量。只输出你认为与目标对象“具体定位”匹配、且证据置信度 >= 0.85 的候选竞品；如果高置信候选很多，最多输出 12 个。
7. confidence 必须综合判断：目标定位一致性、目标用户/使用场景重合、搜索结果证据强度、是否为具体产品而非泛品类。低于 0.85 不要输出。
8. 优先覆盖直接竞品；间接竞品/替代方案只有在能解释清楚竞争关系且 confidence >= 0.85 时才输出。
9. 每个竞品必须增加 region 字段：
   - "global" 表示国外/海外产品
   - "china" 表示国内/中国本土产品

输出严格 JSON，不要输出 Markdown 代码块。
JSON schema:
{{
  "competitors": [
    {{
      "name": "具体的产品名或品牌名（2-30个字符）",
      "website": "官网或最相关 URL",
      "description": "用中文解释它是什么产品，以及为什么和目标对象竞争",
      "category": "direct_competitor | indirect_competitor | substitute_solution | adjacent_product",
      "region": "global | china",
      "reason": "推荐理由",
      "matched_dimensions": ["产品定位", "目标用户", "核心功能", "使用场景"],
      "source_ids": ["支撑来源 URL"],
      "evidence_ids": [],
      "selected_by_default": true,
      "confidence": 0.0
    }}
  ]
}}
"""
        result = self._json_chat(prompt, {"competitors": []})
        competitors = result.get("competitors")
        if not isinstance(competitors, list) or not competitors:
            return fallback
        cleaned = []
        global_count = 0
        china_count = 0
        for item in competitors:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            region = str(item.get("region", "global")).lower()
            if region not in {"global", "china"}:
                region = "global"
            confidence = _safe_confidence(item.get("confidence"))
            cleaned.append(
                {
                    "name": str(item.get("name", ""))[:80],
                    "website": item.get("website"),
                    "description": str(
                        item.get("description")
                        or "由真实搜索结果和大模型提取的候选竞品。"
                    )[:500],
                    "category": item.get("category")
                    if item.get("category")
                    in {
                        "direct_competitor",
                        "indirect_competitor",
                        "substitute_solution",
                        "adjacent_product",
                    }
                    else "direct_competitor",
                    "region": region,
                    "reason": str(
                        item.get("reason")
                        or item.get("description")
                        or "基于目标对象理解和搜索结果推荐。"
                    )[:500],
                    "matched_dimensions": item.get("matched_dimensions")
                    if isinstance(item.get("matched_dimensions"), list)
                    else [],
                    "source_ids": item.get("source_ids")
                    if isinstance(item.get("source_ids"), list)
                    else [],
                    "evidence_ids": item.get("evidence_ids")
                    if isinstance(item.get("evidence_ids"), list)
                    else [],
                    "selected_by_default": bool(item.get("selected_by_default", True)),
                    "confidence": confidence,
                    "discovery_source": f"{self.name}+search",
                }
            )
            if region == "global":
                global_count += 1
            else:
                china_count += 1
            if len(cleaned) >= 12:
                break
        return cleaned if cleaned else fallback

    def analyze_competitor(
        self, competitor: dict[str, Any], evidence: list[dict[str, Any]]
    ) -> dict[str, Any]:
        fallback = self.fallback.analyze_competitor(competitor, evidence)
        evidence_summary = "\n".join(
            f"- evidence_id={e.get('id', '')}；source_ref=[{e.get('reference_id', '?')}]；"
            f"维度={e.get('related_dimension', '未知')}；"
            f"来源类型={e.get('source_type', '未知')}；置信度={e.get('confidence', 0)}；"
            f"来源={e.get('source_url', '')}；摘要={e.get('summary', '')[:300]}"
            for e in evidence[:12]
        )
        focus_schema = (
            competitor.get("_focus_schema")
            if isinstance(competitor.get("_focus_schema"), list)
            else []
        )
        focus_schema_section = ""
        if focus_schema:
            focus_schema_section = f"""

动态关注点 Schema：
{json.dumps(focus_schema, ensure_ascii=False)}

请为动态关注点 Schema 中的每一项生成一条 custom_focus_analysis_json。它们是结构化分析的动态字段，必须基于证据，不要新增 Schema 外的关注点。
"""
        qa_feedback_section = ""
        qa_feedback = competitor.get("_qa_feedback")
        if qa_feedback:
            qa_feedback_section = f"""

【质检反馈——请务必改进以下问题】
{qa_feedback}

请特别注意：上次分析存在上述问题，请务必在本次分析中改进。
"""
        repair_tasks_section = ""
        repair_tasks = competitor.get("_qa_repair_tasks")
        if isinstance(repair_tasks, list) and repair_tasks:
            repair_tasks_section = f"""

【结构化修复任务——必须逐条满足】
{json.dumps(repair_tasks, ensure_ascii=False)}

要求：
- 对 tasks 中 fields 指定的字段进行针对性修复，不要只泛泛改写。
- must_remove_reference_ids 中列出的 source_ref 不得作为字段依据；forbidden_evidence_ids/must_remove_evidence_ids 中列出的 evidence_id 必须从 item_evidence_bindings_json、field_evidence_ids_json 和 evidence_ids_json 中移除。
- required_evidence_ids 是必须优先使用的证据；preferred_evidence_ids 是建议优先使用的证据，但如果与结论语义不匹配，应改写结论或选择更匹配证据。
- evidence_ids_json、field_evidence_ids_json 和 item_evidence_bindings_json 必须使用 evidence_id（ev_xxx），不要使用 source_ref。
- 如果 acceptance_criteria 要求补齐价格、劣势、用户痛点等内容，必须从上方证据中提取具体事实。
- 不要在业务字段中输出“证据中未涉及”“暂无”“unknown”等占位文本，除非该字段完全没有可用证据且没有对应修复任务。
- 不要在 positioning、target_users、core_features_json、pricing_summary、strengths_json、weaknesses_json、opportunities_json 正文字段里输出 ev_xxx 或 source_ref。
"""
        prompt = f"""
你是竞品分析师 Agent。请仔细阅读以下证据材料，基于证据中的真实信息对竞品进行分析。
不要编造证据中没有的信息。如果某个字段在证据中没有找到相关内容，请如实写"证据中未涉及"。
结构化字段正文只写事实结论，不要内嵌 source_ref 或 evidence_id 引用，例如不要写“证据[36]”“[ev_xxx]”。证据绑定统一通过 item_evidence_bindings_json、field_evidence_ids_json、evidence_ids_json 和 custom_focus_analysis_json.evidence_ids 表达。

竞品名称：{competitor.get("name", "")}
竞品描述：{competitor.get("description", "")[:300]}

已采集证据（请基于这些内容分析）：
{evidence_summary}
{focus_schema_section}
{qa_feedback_section}
{repair_tasks_section}
输出严格 JSON，不要输出 Markdown。
JSON schema:
{{
  "positioning": "基于证据总结该产品的定位，不要写引用号",
  "target_users": ["从证据中提取的目标用户"],
  "core_features_json": ["从证据中提取的核心功能"],
  "pricing_summary": "从证据中提取的定价信息，无则写'证据中未涉及'",
  "strengths_json": ["从证据中提取的优势"],
  "weaknesses_json": ["从证据中提取的劣势或用户痛点"],
  "opportunities_json": ["基于证据分析的机会点"],
  "custom_focus_analysis_json": [
    {{
      "focus_key": "必须来自动态关注点 Schema 的 key",
      "label": "必须来自动态关注点 Schema 的 label",
      "verdict": "围绕该关注点的结构化结论；如果证据不足，写'证据中未涉及'",
      "evidence_ids": ["支撑该结论的 evidence_id，必须来自已采集证据"],
      "confidence": 0.0
    }}
  ],
  "field_evidence_ids_json": {{
    "positioning": ["支撑定位字段的 evidence_id"],
    "target_users": ["支撑目标用户字段的 evidence_id"],
    "core_features_json": ["支撑核心功能字段的 evidence_id"],
    "pricing_summary": ["支撑定价字段的 evidence_id"],
    "strengths_json": ["支撑优势字段的 evidence_id"],
    "weaknesses_json": ["支撑劣势或用户痛点字段的 evidence_id"],
    "opportunities_json": ["支撑机会点字段的 evidence_id"]
  }},
  "item_evidence_bindings_json": {{
    "strengths_json": [
      {{
        "item_index": 0,
        "claim": "对应 strengths_json 第 0 条结论",
        "evidence_ids": ["直接支撑该条结论的 evidence_id"],
        "match_reason": "说明该证据为什么支撑该条结论"
      }}
    ],
    "weaknesses_json": [
      {{
        "item_index": 0,
        "claim": "对应 weaknesses_json 第 0 条结论",
        "evidence_ids": ["直接支撑该条结论的 evidence_id，优先选择负面/限制/痛点证据"],
        "match_reason": "说明该证据为什么支撑该条劣势或痛点"
      }}
    ]
  }},
  "evidence_ids_json": ["支撑本竞品分析的 evidence_id，必须来自已采集证据"],
  "relationship_type": "direct/indirect/substitute 之一。direct=直接竞品，indirect=间接竞品，substitute=替代方案",
  "relationship_reason": "简要说明为什么是该竞争类型，它竞争的是什么需求或场景，基于证据",
  "overlap_dimensions": [
    {{
      "dimension": "产品定位|目标用户|核心功能|使用场景|商业模式 之一",
      "detail": "具体说明在该维度上如何与目标产品重叠"
    }}
  ]
}}
注意：overlap_dimensions 必须包含 2-4 个维度的具体重叠点，每个维度必须有具体说明。
注意：如果你输出 source_ref 数字（如 36），系统会尽力转换为对应 evidence_id；但优先直接输出 evidence_id。业务字段正文仍然禁止写引用号。
"""
        result = self._json_chat(prompt, fallback)
        if result is fallback:
            return fallback
        # Convert LLM-facing reference_id back to internal ev_xxx UUIDs for storage.
        ref_to_ev: dict[str, str] = {}
        for e in evidence:
            ref_id = e.get("reference_id")
            ev_id = e.get("id")
            if ref_id is not None and ev_id:
                ref_to_ev[str(ref_id)] = ev_id
        eids = result.get("evidence_ids_json")
        if isinstance(eids, list):
            result["evidence_ids_json"] = [
                _coerce_llm_evidence_id(v, ref_to_ev) for v in eids
            ]
        field_eids = result.get("field_evidence_ids_json")
        if isinstance(field_eids, dict):
            result["field_evidence_ids_json"] = {
                str(field): [
                    _coerce_llm_evidence_id(v, ref_to_ev) for v in values
                ]
                for field, values in field_eids.items()
                if isinstance(values, list)
            }
        item_eids = result.get("item_evidence_bindings_json")
        if isinstance(item_eids, dict):
            converted_bindings: dict[str, list[dict[str, Any]]] = {}
            for field, rows in item_eids.items():
                if not isinstance(rows, list):
                    continue
                converted_rows = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    values = row.get("evidence_ids")
                    converted_rows.append(
                        {
                            **row,
                            "evidence_ids": [
                                _coerce_llm_evidence_id(v, ref_to_ev) for v in values
                            ]
                            if isinstance(values, list)
                            else [],
                        }
                    )
                converted_bindings[str(field)] = converted_rows
            result["item_evidence_bindings_json"] = converted_bindings
        cfa = result.get("custom_focus_analysis_json")
        if isinstance(cfa, list):
            for item in cfa:
                if isinstance(item, dict):
                    item_eids = item.get("evidence_ids")
                    if isinstance(item_eids, list):
                        item["evidence_ids"] = [
                            _coerce_llm_evidence_id(v, ref_to_ev) for v in item_eids
                        ]
        for key in [
            "target_users",
            "core_features_json",
            "strengths_json",
            "weaknesses_json",
            "opportunities_json",
            "evidence_ids_json",
            "custom_focus_analysis_json",
        ]:
            if isinstance(result.get(key), list):
                result[key] = json.dumps(result[key], ensure_ascii=False)
        return result

    def extract_evidence_from_source(
        self,
        source: dict[str, Any],
        query_item: dict[str, Any],
        competitor: dict[str, Any],
        requirement: dict[str, Any],
    ) -> dict[str, Any]:
        fallback = self.fallback.extract_evidence_from_source(
            source, query_item, competitor, requirement
        )
        content = str(source.get("raw_content") or source.get("snippet") or "")[:6000]
        prompt = f"""
你是竞品分析系统的证据抽取 Agent。请判断单个来源是否能支撑当前竞品与目标维度，并从中抽取 0 到 4 条结构化 evidence。

用户需求/领域：{json.dumps(requirement, ensure_ascii=False)}
竞品：{json.dumps({"id": competitor.get("id"), "name": competitor.get("name"), "description": competitor.get("description")}, ensure_ascii=False)}
检索目标：{json.dumps(query_item, ensure_ascii=False)}

来源：
- title: {source.get("title", "")}
- url: {source.get("url", "")}
- source_type: {source.get("source_type", "")}
- source_credibility: {source.get("credibility_score", 0)}
- snippet: {source.get("snippet", "")}
- content: {content}

抽取规则：
- 只抽取能直接支撑“竞品 + 目标维度”的事实，不要因为 query 命中就强行生成 evidence。
- 如果来源与该竞品不是同一个产品，或内容不支持目标维度，evidence 返回空数组。
- 一个来源可以生成多条 evidence，但每条必须有明确 claim/quote/summary。
- related_dimension 必须优先使用：产品定位、核心功能、价格与商业模式、用户评价与痛点、竞争关系；除非检索目标是个性化关注点。
- quote 应为来源中的短证据片段，不要包含导航、cookie、页脚等噪声。
- confidence 反映这条证据对该维度的支撑强度，不只是来源可信度。
- support_type 用 direct/indirect/background 表示支撑强度：direct=直接证明目标维度；indirect=间接支撑；background=背景信息。优先抽取 direct，background 只有高度相关时才保留。
- sentiment 用 positive/negative/neutral/mixed 表示证据方向：正面评价或优势用 positive；抱怨、限制、缺陷、成本压力用 negative；价格/功能/定位事实通常用 neutral；同时包含正反两面用 mixed。
- evidence_role 用 positioning/feature/pricing/user_praise/user_complaint/market_signal/limitation/competition/risk/opportunity/background 之一。

输出严格 JSON，不要输出 Markdown。
JSON schema:
{{
  "source_relevance": 0.0,
  "source_relevance_reason": "说明该来源与竞品和目标维度的相关性",
  "evidence": [
    {{
      "related_product": "{competitor.get("name", "")}",
      "related_dimension": "{query_item.get("dimension", "")}",
      "claim": "该证据支持的事实主张",
      "quote": "来源中的关键原文片段",
      "summary": "中文简要说明这条证据能证明什么",
      "supports_dimension": true,
      "sentiment": "positive | negative | neutral | mixed",
      "evidence_role": "feature",
      "support_type": "direct",
      "relevance_score": 0.0,
      "confidence": 0.0
    }}
  ]
}}
"""
        result = self._json_chat(prompt, fallback)
        evidence = result.get("evidence") if isinstance(result, dict) else None
        if not isinstance(evidence, list):
            return fallback
        return result

    def generate_report(
        self,
        run: dict[str, Any],
        analyses: list[dict[str, Any]],
        sources: list[dict[str, Any]],
    ) -> dict[str, str]:
        fallback = self.fallback.generate_report(run, analyses, sources)
        citation_bundle_raw = run.get("citation_bundle", [])
        citation_bundle = json.dumps(citation_bundle_raw, ensure_ascii=False)
        qa_guidance = run.get("qa_analysis_guidance")
        qa_guidance_section = ""
        if qa_guidance:
            qa_guidance_section = f"""

【上次质检反馈——请务必在本次分析中改进以下问题】
{qa_guidance}

请特别注意：上次分析存在上述问题，请在本次报告生成时针对性改进。
"""
        prompt = f"""
你是报告撰写 Agent。请基于以下 citation_bundle 生成一份专业的中文 Markdown 竞品分析报告。

用户需求：{run.get("user_requirement", "")}
citation_bundle：{citation_bundle}{qa_guidance_section}

报告要求：
1. 标题应该准确反映分析对象和领域，不要用"通用产品"这种泛泛标题
2. 开头必须有一段 2-3 句话的「市场综述」摘要，概括整体竞争格局和核心发现
3. 报告的核心必须是一个 Markdown 对比表格，结构如下：
   - 第一行为表头：`| 分析维度 | 竞品A | 竞品B | ... |`
   - 每个分析维度占一行，第一列为维度名称（加粗），后续列为各竞品在该维度的核心结论
   - 维度顺序：先排列基础维度（产品定位、核心功能、定价策略、优势、劣势或痛点、机会点），再排列用户特别关注的自定义维度（来自 citation_bundle 中 claim_type 以 focus: 开头的条目）
   - 用户自定义维度的维度名应使用其 label 字段，并在后面标注"（重点关注）"
4. 每个单元格的关键结论必须引用该 claim 下 evidence 中提供的 source_reference_id，格式为 `[[1]]`；禁止写成 `[1]` 或 `[1](URL)`
5. 【重要】不同 claim 有各自不同的 evidence 和 source_reference_id。你必须为每个 claim 使用该 claim 自己的 evidence 中的 source_reference_id，严禁把同一个 source_reference_id 用于所有 claim。严禁使用任何 claim 的 evidence 列表中没有出现的 source_reference_id——如果你不确定，宁可不写引用也不要编造引用号
6. 如果某些信息不确定或缺失，如实填入"证据中未涉及"，不要编造
7. 单元格内容控制在 20-60 字，力求简练但信息完整；不要在单元格内写长段落；单元格内禁止使用换行符，如需分行请用「；」或「——」连接
8. 在表格之后，可以为特别重要的维度或需要深入解释的结论补充简短的「深度解读」段落，每个段落不超过 3-4 句话
9. 不要自行生成 `## 参考来源` 部分，系统会自动补充

输出严格 JSON，不要输出 Markdown 代码块。
JSON schema:
{{
  "title": "报告标题（应包含具体产品或领域名称）",
  "summary": "报告摘要（2-3句话概括核心发现）",
  "markdown_content": "完整 Markdown 报告（含摘要段落 + 对比表格 + 深度解读）"
}}
"""
        result = self._json_chat(prompt, fallback)
        if result is fallback:
            return fallback
        md = result.get("markdown_content", "")
        md = _normalize_inline_citations(md)
        md = _validate_citation_whitelist(md, citation_bundle_raw)
        md = _ensure_reference_section(md, sources)
        result["markdown_content"] = md
        return result

    def qa_check_report(
        self,
        analyses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        fallback = self.fallback.qa_check_report(analyses, evidence)
        capped_analyses = analyses[:15]
        capped_evidence = evidence
        analyses_summary = "\n".join(
            _format_analysis_for_qa(a)
            for a in capped_analyses
        )
        evidence_summary = "\n".join(
            f"- evidence_id={e.get('id', '')}；source_ref=[{e.get('reference_id', '?')}]；"
            f"竞品={e.get('related_product', '')}；维度={e.get('related_dimension', '')}；"
            f"来源类型={e.get('source_type', '')}；置信度={e.get('confidence', 0)}；摘要={e.get('summary', '')}"
            for e in capped_evidence
        )
        prompt = f"""
你是竞品分析系统的质检 Agent。请对以下结构化分析数据和证据进行多维度质量检查。

## 结构化分析（每个竞品的完整分析数据）
{analyses_summary}

## 证据摘要（含 evidence_id 与 source_ref）
{evidence_summary}

## 质检维度

请从以下 6 个维度评估，每个维度打分 0.0-1.0：

1. **evidence_grounding（证据支撑度）**：分析结论（定位、目标用户、功能、定价、优劣势、机会点等）是否被对应的 evidence_ids 所引用的证据支撑？是否存在幻觉内容？
2. **citation_accuracy（引用准确性）**：每个竞品分析中 field_evidence_ids_json 与 evidence_ids_json 列出的 evidence_id 是否真实存在，并且指向与该竞品相关、维度匹配的证据？是否存在张冠李戴？
3. **schema_completeness（Schema 完整度）**：每个竞品的 7 个分析字段（product positioning、target users、core features、pricing、strengths、weaknesses、opportunities）是否都有实质内容而非占位文本？
4. **coverage_gaps（覆盖缺口）**：已采集的证据库中，每个竞品的 4 个核心维度（产品定位、核心功能、价格与商业模式、用户评价与痛点）是否有足够可用证据。注意：coverage_gaps 只评价“证据库是否采够”，不要求结构化分析引用该维度的全部证据。
5. **cross_competitor_consistency（跨竞品一致性）**：各竞品分析深度和信息量是否一致？是否有的竞品分析非常详尽、有的非常简略？
6. **factual_plausibility（事实合理性）**：分析内容是否有明显不合理的陈述？例如与已知事实矛盾、逻辑不通等。

## 评分锚点

请按以下锚点校准分数，避免“发现严重问题但仍给高分”：

- 0.90-1.00：证据充分、字段完整、引用准确，仅有非常轻微可忽略问题。
- 0.70-0.89：总体可用，存在少量 minor 问题，但不影响主要结论。
- 0.50-0.69：存在 major 问题，例如关键字段空泛、部分竞品证据不足、引用需要明显修正。
- 0.20-0.49：存在 critical 问题，例如某竞品几乎没有证据、核心结论缺少支撑、引用大面积无效。
- 0.00-0.19：结构化分析基本不可用，缺少主要内容或明显幻觉。

硬性上限规则：
- 若某维度存在 critical issue，该维度分数不得高于 0.35。
- 若 citation_accuracy 或 schema_completeness 存在 major issue，该维度分数不得高于 0.60。
- 若其他维度存在 major issue，该维度分数不得高于 0.65。
- 若某维度仅存在 minor issue，该维度分数不得高于 0.80。
- coverage_gaps 中单个竞品某核心维度的已采集公开证据少于 3 条时，至少应生成 major issue；为 0 条时应生成 critical issue。
- 如果证据库中某维度已采集到 ≥3 条相关证据，但结构化分析只选择引用其中 1-2 条代表性证据，不要生成 coverage_gaps issue。LLM 被允许选择部分最相关证据，不需要使用全部证据。
- 若分析结论没有被其字段级绑定证据支撑，归为 evidence_grounding；若 field_evidence_ids_json 或 evidence_ids_json 指向不存在、错竞品或错维度证据，归为 citation_accuracy。不要把“未引用全部可用证据”当作问题。

引用语义说明：
- evidence_id 是结构化分析 field_evidence_ids_json 与 evidence_ids_json 应引用的唯一证据 ID。
- field_evidence_ids_json 是字段级证据绑定；evidence_ids_json 是兼容用的代表性证据汇总。二者都不要求包含该竞品/维度的全部证据。
- 当前证据库的标准维度只有：产品定位、核心功能、价格与商业模式、用户评价与痛点、竞争关系。不要发明“目标用户维度”“市场维度”并把它们作为 citation_accuracy 的硬性要求。
- target_users 可以由产品定位、用户评价与痛点证据支撑；opportunities_json 不要求固定维度证据，只有当机会点结论与所引用证据明显矛盾时才生成 evidence_grounding issue。
- strengths_json 可以由产品定位、核心功能或用户评价与痛点证据支撑；不要因为它没有“优势专用维度”而判定 citation_accuracy 错误。
- 结构化字段正文不要求内嵌 evidence_id 或 source_ref；不要因为字段正文没有“证据[36]”或“ev_xxx”而生成 issue。字段正文里的 source_ref 只当普通文本线索，不能作为 citation_accuracy 的判定依据。
- source_ref 是报告展示用来源编号，同一个 source_ref 可以对应多条 evidence，因为同一个来源可能支撑多个维度；不要仅因为 source_ref 重复就生成 issue。
- source_ref 为 [?] 或 [None]、field_evidence_ids_json/evidence_ids_json 中的 evidence_id 不存在、evidence_id 指向其他竞品/错误维度，才属于 citation_accuracy 问题。

输出严格 JSON，不要输出 Markdown 代码块，不要输出 schema 外字段。
JSON schema:
{{
  "dimension_scores": {{
    "evidence_grounding": 0.0,
    "citation_accuracy": 0.0,
    "schema_completeness": 0.0,
    "coverage_gaps": 0.0,
    "cross_competitor_consistency": 0.0,
    "factual_plausibility": 0.0
  }},
  "retry_instructions": "具体的改进指导（有 issues 时填写，面向人类阅读）",
  "retry_queries": [
    {{
      "competitor_name": "竞品名称",
      "slot": "core_features | pricing | positioning | user_feedback | market_signal | risk_opportunity | relationship_evidence",
      "query": "用于搜索引擎的具体检索关键词，15-40字，精准有效"
    }}
  ],
  "issues": [
    {{
      "dimension": "维度名",
      "severity": "critical | major | minor",
      "competitor_name": "单个竞品名，或 system。严禁填入多个竞品名（如\"A、B\"或\"全部竞品\"）",
      "description": "问题描述",
      "fix_suggestion": "修复建议"
    }}
  ]
}}

【issues 生成规则】
- 每条 issue 必须对应且只对应一个竞品。如果一个问题同时影响多个竞品（如\"A 和 B 都缺少用户评价\"），必须拆成多条独立的 issue，每条只关联一个竞品
- 对于 cross_competitor_consistency 类问题，每条 issue 只需列出受影响的一方（如\"A 的分析深度高于 B\"，应拆为一条针对 A 的 issue 和一条针对 B 的 issue）
- system 级别 issue 仅用于全局性问题（如所有竞品证据数量均不足），不要滥用

【retry_queries 生成规则】
- 当 issue 需要补采公开资料时填写，尤其是 coverage_gaps 或 evidence_grounding 问题
- 每个需要补采的 issue 对应生成 1-2 条 query
- query 必须是有效的搜索关键词，不要包含自然语言指令（如"补充搜索"）
- 根据竞品名称的语言选择中英文 query：英文竞品用英文，中文竞品用中文
- 每条 query 控制在 15-40 个字符，精准命中信息缺口
- 示例：{{"competitor_name": "Otter.ai", "slot": "core_features", "query": "Otter.ai feature list integrations API documentation"}}
"""
        result = self._json_chat(prompt, fallback)
        if result is fallback:
            return fallback
        issues = result.get("issues")
        if not isinstance(issues, list):
            result["issues"] = []
        return result

    def qa_verify_issues(
        self,
        analyses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        open_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        fallback = self.fallback.qa_verify_issues(
            analyses, evidence, open_issues
        )
        issues_json = json.dumps(open_issues, ensure_ascii=False)
        capped_analyses = analyses[:15]
        capped_evidence = evidence
        analyses_summary = "\n".join(
            _format_analysis_for_qa(a)
            for a in capped_analyses
        )
        evidence_summary = "\n".join(
            f"- evidence_id={e.get('id', '')}；source_ref=[{e.get('reference_id', '?')}]；"
            f"竞品={e.get('related_product', '')}；维度={e.get('related_dimension', '')}；"
            f"来源类型={e.get('source_type', '')}；置信度={e.get('confidence', 0)}；摘要={e.get('summary', '')}"
            for e in capped_evidence
        )
        prompt = f"""
你是竞品分析系统的质检复核 Agent。请只检查以下历史未解决问题是否已经被本轮结构化分析和证据解决。

## 历史未解决 issues
{issues_json}

## 结构化分析（每个竞品的完整分析数据）
{analyses_summary}

## 证据摘要
{evidence_summary}

引用语义说明：
- evidence_id 是结构化分析 field_evidence_ids_json/evidence_ids_json 引用的唯一证据 ID。
- 当前证据库的标准维度只有：产品定位、核心功能、价格与商业模式、用户评价与痛点、竞争关系。不要发明“目标用户维度”“市场维度”并把它们作为未解决依据。
- target_users 可以由产品定位、用户评价与痛点证据支撑；opportunities_json 不要求固定维度证据，只有当机会点结论与所引用证据明显矛盾时才保持 open。
- strengths_json 可以由产品定位、核心功能或用户评价与痛点证据支撑；不要因为它没有“优势专用维度”而判定未解决。
- 结构化字段正文不要求内嵌 evidence_id 或 source_ref；不要因为字段正文没有“证据[36]”或“ev_xxx”而判定未解决。字段正文里的 source_ref 只当普通文本线索，不能作为 citation_accuracy 的判定依据。
- source_ref 是报告展示用来源编号，同一 source_ref 可对应多条 evidence；不要仅因 source_ref 重复判定未解决。
- source_ref 为 [?] 或 [None]、field_evidence_ids_json/evidence_ids_json 中的 evidence_id 不存在、或 evidence_id 指向其他竞品/错误维度，才是引用问题。

输出严格 JSON，不要输出 Markdown 代码块，不要输出 schema 外字段。
JSON schema:
{{
  "resolutions": [
    {{
      "issue_id": "必须来自历史 issue 的 id",
      "status": "resolved | open",
      "resolution_reason": "说明为什么已解决或仍未解决",
      "retry_queries": [
        {{
          "competitor_name": "竞品名称",
          "slot": "core_features | pricing | positioning | user_feedback | market_signal | risk_opportunity | relationship_evidence",
          "query": "如果仍需补采，给出具体搜索关键词；否则为空数组"
        }}
      ]
    }}
  ],
  "retry_instructions": "如果仍有 open issue，给出下一步修复指引；否则为空"
}}

规则：
- 每个历史 issue 必须返回一条 resolution。
- 只有在新分析/新证据已经直接覆盖原问题时，status 才能是 resolved。
- 检查标准：对应的分析字段是否已有实质内容、采集证据库数量是否充足、field_evidence_ids_json/evidence_ids_json 是否准确匹配。
- 对 coverage_gaps：只检查证据库是否已有足够可用证据；不要要求结构化分析引用全部证据。若证据库已满足覆盖要求，即使分析只选择部分代表性证据，也可以判定 coverage_gaps resolved。
- 如果采集证据库仍不足、字段仍空泛、引用仍无法核验，status 必须是 open。
"""
        result = self._json_chat(prompt, fallback)
        if result is fallback:
            return fallback
        resolutions = result.get("resolutions")
        if not isinstance(resolutions, list):
            result["resolutions"] = []
        return result

    def _chat(self, prompt: str) -> str | None:
        result = None
        status = "completed"
        error = None
        output_data: dict = {}
        started_at = datetime.utcnow()
        try:
            request: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt},
                ],
            }
            if self.temperature is not None:
                request["temperature"] = self.temperature
            response = self.client.chat.completions.create(**request)
            if not response.choices:
                logger.warning("LLM returned empty choices")
                status = "failed"
                error = "Empty choices returned"
                output_data = {"error": "empty_choices"}
                return None
            content = response.choices[0].message.content
            if not content:
                status = "failed"
                error = "Empty content returned"
                output_data = {"error": "empty_content"}
                return None
            result = content.strip() or None
            output_data = {"content": result}
            return result
        except Exception as exc:
            logger.exception("LLM chat call failed")
            status = "failed"
            error = traceback.format_exc()
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in (400, 401, 403, 404):
                raise
            return None
        finally:
            call_tracer.record_llm_call(
                provider=self.name,
                model=self.model,
                input_data={"messages": request["messages"], "temperature": request.get("temperature")},
                output_data=output_data,
                token_count=_extract_token_count(locals().get("response")),
                duration_ms=int((datetime.utcnow() - started_at).total_seconds() * 1000),
                started_at=started_at,
                status=status,
                error=error,
            )

    def _json_chat(self, prompt: str, fallback: dict[str, Any]) -> dict[str, Any]:
        content = ""
        result = fallback
        status = "completed"
        error = None
        output_data: dict = {}
        started_at = datetime.utcnow()
        try:
            request: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是严谨的竞品分析多 Agent 系统。必须只输出纯 JSON，不要包含 ```json 代码块标记，不要输出任何解释文字。",
                    },
                    {"role": "user", "content": prompt},
                ],
            }
            if self.temperature is not None:
                request["temperature"] = self.temperature
            response = self.client.chat.completions.create(**request)
            if not response.choices:
                logger.warning("LLM returned empty choices, using fallback")
                status = "failed"
                error = "Empty choices returned"
                output_data = {"error": "empty_choices", "fallback_used": True}
                return fallback
            content = (response.choices[0].message.content or "").strip()
            content = _strip_code_fences(content)
            if not content:
                logger.warning("LLM returned empty content, using fallback")
                status = "failed"
                error = "Empty content returned"
                output_data = {"error": "empty_content", "fallback_used": True}
                return fallback
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                json_match = re.search(r"\{[\s\S]*\}", content)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                else:
                    raise
            if not isinstance(parsed, dict):
                logger.warning("LLM returned non-dict JSON, using fallback")
                status = "failed"
                error = "Non-dict JSON returned"
                output_data = {"error": "non_dict_json", "raw_content": content}
                return fallback
            output_data = {"parsed": parsed}
            result = parsed
            return parsed
        except json.JSONDecodeError:
            logger.warning(
                "LLM returned invalid JSON: %s", content[:200] if content else "empty"
            )
            status = "failed"
            error = f"JSON decode error: {content[:200] if content else 'empty'}"
            output_data = {"error": "json_decode_error", "raw_content": content if content else "empty"}
            return fallback
        except Exception:
            logger.exception("LLM API call failed, using fallback")
            status = "failed"
            error = traceback.format_exc()
            return fallback
        finally:
            call_tracer.record_llm_call(
                provider=self.name,
                model=self.model,
                input_data={"messages": request["messages"], "temperature": request.get("temperature")},
                output_data=output_data,
                token_count=_extract_token_count(locals().get("response")),
                duration_ms=int((datetime.utcnow() - started_at).total_seconds() * 1000),
                started_at=started_at,
                status=status,
                error=error,
            )

    def classify_chat_intent(
        self,
        user_message: str,
        report_summary: str,
        chat_history: list[dict[str, str]],
    ) -> dict[str, Any]:
        history_text = "\n".join(
            f"{msg['role']}: {msg['content'][:200]}" for msg in chat_history[-6:]
        )
        prompt = f"""判断用户的消息意图，决定是"小幅修改报告"还是"需要重新调研后重做报告"。

当前报告摘要：{report_summary[:500]}

对话历史：
{history_text or "（无历史）"}

用户最新消息：{user_message}

判断规则：
- report_edit: 用户要求修改报告细节、措辞、格式、增加/删除某些内容，不涉及新数据采集
- report_redo: 用户认为报告方向不对、信息不准确、需要新的调研数据、或者对核心结论不满意

输出严格 JSON：
{{
  "intent": "report_edit | report_redo",
  "reason": "判断理由"
}}"""
        result = self._json_chat(prompt, {"intent": "report_edit", "reason": "默认"})
        return result

    def edit_report_markdown(
        self,
        report_markdown: str,
        user_message: str,
        context: str,
    ) -> str:
        prompt = f"""根据用户反馈修改以下竞品分析报告。

报告内容：
{report_markdown[:8000]}

上下文信息（竞品分析数据摘要）：
{context[:2000]}

用户修改要求：{user_message}

请直接输出修改后的完整 Markdown 报告。保持报告结构化格式，确保修改后的报告逻辑连贯、数据准确。
只修改用户要求的部分，其余内容保持不变。
【重要】必须保留原报告正文里的 `[[数字]](URL)` 引用标记；除非删除对应结论，否则不得移除引用。"""
        result = self._chat(prompt)
        return result if result else report_markdown

    def generate_chat_queries(
        self,
        user_message: str,
        report_summary: str,
        existing_competitors: list[str],
    ) -> dict[str, Any]:
        competitors_text = (
            "、".join(existing_competitors[:6]) if existing_competitors else "（无）"
        )
        prompt = f"""用户对当前竞品分析报告不满意，需要重新调研。请生成新的搜索查询。

报告摘要：{report_summary[:500]}

已有竞品：{competitors_text}

用户反馈：{user_message}

请为每个竞品生成 1-2 个针对性的搜索 query，重点关注用户反馈中提到的方向。输出严格 JSON：
{{
  "retry_queries": [
    {{"competitor_name": "竞品名", "slot": "core_features|pricing|user_feedback|positioning|market_signal", "query": "搜索query"}}
  ],
  "retry_instructions": "给分析阶段的指导说明",
  "additional_guidance": "额外的搜索方向建议"
}}"""
        result = self._json_chat(
            prompt,
            {
                "retry_queries": [],
                "retry_instructions": user_message,
                "additional_guidance": "",
            },
        )
        return result

    def classify_revision_intent(
        self,
        user_message: str,
        current_report: dict[str, Any],
        chat_history: list[dict[str, str]],
    ) -> dict[str, Any]:
        history_text = "\n".join(
            f"{msg['role']}: {msg['content'][:200]}" for msg in chat_history[-6:]
        )
        prompt = f"""你是竞品分析报告的二轮修订调度 Agent。请判断用户反馈应该如何处理。

当前报告标题：{current_report.get("title", "")}
当前报告摘要：{current_report.get("summary", "")}
对话历史：
{history_text or "（无）"}

用户最新反馈：{user_message}

判断标准：
- report_edit：只涉及措辞、格式、语气、删除/合并段落、在已有证据内补写，不需要新资料。
- research_required：涉及事实准确性、竞品是否选错、产品定位/目标用户/价格/功能是否不对、证据不足、需要补充公开资料或重新核实；用户要求新增/补充某个竞品时也属于 research_required。
- 不确定时选择 research_required，因为竞品分析强调可信度和溯源。
- 如果用户明确要求删除某个竞品或说某个竞品不需要，请将其列入 removed_competitors。

输出严格 JSON：
{{
  "intent": "report_edit | research_required",
  "need_search": true,
  "confidence": 0.0,
  "reason": "判断理由",
  "affected_sections": ["章节或维度"],
  "affected_competitors": ["已有或新增竞品名"],
  "new_competitors": ["用户要求新增但当前报告未覆盖的竞品名"],
  "removed_competitors": ["用户要求删除或移除的竞品名"],
  "user_goal": "用户真正想解决的问题"
}}"""
        return self._json_chat(
            prompt,
            {
                "intent": "research_required",
                "need_search": True,
                "confidence": 0.3,
                "reason": "LLM 未返回有效结果，默认按需搜索处理以避免降级",
                "affected_sections": [],
                "affected_competitors": [],
                "new_competitors": [],
                "removed_competitors": [],
                "user_goal": user_message,
            },
        )

    def generate_revision_search_plan(
        self,
        user_message: str,
        current_report: dict[str, Any],
        competitors: list[dict[str, Any]],
        existing_sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        competitors_text = "\n".join(
            f"- {c.get('name', '')}: {c.get('description', '')}"
            for c in competitors[:8]
        )
        source_text = "\n".join(
            f"- [{s.get('reference_id', '?')}] {s.get('title', '')}: {s.get('snippet', '')[:120]}"
            for s in existing_sources[:20]
        )
        prompt = f"""用户反馈需要补充调研。请生成有针对性的搜索计划。

用户反馈：{user_message}
当前报告摘要：{current_report.get("summary", "")}
已有竞品：
{competitors_text or "（无）"}
已有来源摘要：
{source_text or "（无）"}

要求：
1. 查询要能验证用户指出的问题，不要泛泛搜索。
2. 优先覆盖官网/文档/定价页/第三方评测/用户评价。
3. 每个 query 保持可直接搜索。
4. 如果用户要求新增某个竞品，即使它不在“已有竞品”列表里，也必须为它生成 search_plan 条目，competitor_name 填新增竞品名。

输出严格 JSON：
{{
  "search_plan": [
    {{
      "competitor_name": "竞品名或目标对象",
      "purpose": "为什么搜",
      "queries": ["query1", "query2"],
      "expected_evidence": "期望拿到的证据"
    }}
  ],
  "plan_summary": "一句话说明搜索计划"
}}"""
        return self._json_chat(prompt, {"search_plan": [], "plan_summary": "补充调研"})

    def generate_revision_plan(
        self,
        user_message: str,
        current_report: dict[str, Any],
        analyses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        new_sources: list[dict[str, Any]],
        intent_result: dict[str, Any],
    ) -> dict[str, Any]:
        new_source_text = "\n".join(
            f"- [{s.get('reference_id', '?')}] {s.get('title', '')}: {s.get('snippet', '')[:180]}"
            for s in new_sources[:20]
        )
        analysis_text = "\n".join(
            f"- {a.get('competitor_name', '')}: 定位={a.get('positioning', '')[:120]}；价格={a.get('pricing_summary', '')[:80]}"
            for a in analyses[:10]
        )
        prompt = f"""你是竞品分析报告修订规划 Agent。请基于用户反馈、当前报告、已有分析和新资料，先制定修订计划，不要直接写报告。

用户反馈：{user_message}
意图判断：{json.dumps(intent_result, ensure_ascii=False)}
当前报告：
{current_report.get("markdown_content", "")[:5000]}

已有结构化分析摘要：
{analysis_text or "（无）"}

本轮新增资料：
{new_source_text or "（无新增资料）"}

请分析：
1. 报告结构要不要改。
2. 哪些章节要改，为什么改。
3. 具体怎么改。
4. 哪些新增/修改结论必须带正文引用。
5. 如果意图判断中指定了 removed_competitors，必须为这些竞品生成 delete 类型的章节变更。

输出严格 JSON：
{{
  "revision_type": "minor | section_rewrite | structural_change",
  "structure_change_needed": true,
  "structure_change_reason": "原因",
  "sections_to_change": [
    {{"section": "章节名", "change_type": "rewrite|add|delete|reorder|keep", "reason": "原因", "new_direction": "具体修改方向"}}
  ],
  "citation_requirements": [
    {{"claim": "需要引用支撑的结论", "must_cite_sources": [1, 2]}}
  ],
  "final_edit_instruction": "给报告撰写 Agent 的详细修改指令"
}}"""
        return self._json_chat(
            prompt,
            {
                "revision_type": "minor",
                "structure_change_needed": False,
                "structure_change_reason": "默认局部修改",
                "sections_to_change": [],
                "citation_requirements": [],
                "final_edit_instruction": user_message,
            },
        )

    def revise_report_with_plan(
        self,
        current_report: dict[str, Any],
        revision_plan: dict[str, Any],
        citation_bundle: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        removed_competitor_names: list[str] | None = None,
        excluded_citation_ids: set[int] | None = None,
    ) -> dict[str, str]:
        removed_clause = ""
        if removed_competitor_names:
            removed_names_text = "、".join(removed_competitor_names)
            removed_clause = f"""
12. 【硬性约束——删除竞品】以下竞品已被用户移除，你必须从表格中删除它们的整列及所有内容，正文中也不得再提及它们：{removed_names_text}。这些竞品列中的 [[N]] 引用也必须一并删除，不要保留任何指向已删除竞品的引用标记。"""
        fallback = {
            "title": current_report.get("title", "竞品分析报告"),
            "summary": current_report.get("summary", "已根据反馈更新报告。"),
            "markdown_content": current_report.get("markdown_content", ""),
        }

        # Extract fingerprints from current report
        old_markdown = current_report.get("markdown_content", "")
        fingerprints = _extract_citation_fingerprints(old_markdown)

        citation_bundle_raw = citation_bundle
        citation_bundle_json = json.dumps(citation_bundle, ensure_ascii=False)
        if len(citation_bundle_json) > 8000:
            _CORE_CLAIM_TYPES = {"positioning", "core_features", "pricing"}
            per_competitor: dict[str, list[dict]] = {}
            for item in citation_bundle:
                name = item.get("competitor_name", "unknown")
                per_competitor.setdefault(name, []).append(item)
            budget = 7500
            trimmed_chunks: list[str] = []
            used = 0
            for name, items in per_competitor.items():
                core_items = [
                    i
                    for i in items
                    if any(
                        c.get("claim_type", "") in _CORE_CLAIM_TYPES
                        for c in i.get("claims", [])
                    )
                ]
                other_items = [i for i in items if i not in core_items]
                chunk_items: list[dict] = []
                for item in core_items + other_items:
                    item_json = json.dumps(item, ensure_ascii=False)
                    candidate = ("," + item_json) if chunk_items else item_json
                    if used + len(candidate) + 2 > budget:
                        break
                    chunk_items.append(item)
                    used += len(candidate)
                if chunk_items:
                    trimmed_chunks.append(json.dumps(chunk_items, ensure_ascii=False))
            citation_bundle_json = "[" + ",".join(trimmed_chunks) + "]"
            if len(citation_bundle_json) > 8000:
                safe_items: list[str] = []
                total = 1
                for item in citation_bundle:
                    item_json = json.dumps(item, ensure_ascii=False)
                    if total + len(item_json) + 2 > 7990:
                        break
                    safe_items.append(item_json)
                    total += len(item_json) + 1
                citation_bundle_json = "[" + ",".join(safe_items) + "]"

        removed_names_text = ""
        if removed_competitor_names:
            removed_names_text = json.dumps(
                removed_competitor_names, ensure_ascii=False
            )

        prompt = f"""你是报告撰写 Agent。请严格根据修订计划改写当前 Markdown 报告。

当前报告：
{old_markdown[:9000]}

修订计划：
{json.dumps(revision_plan, ensure_ascii=False)}

 citation_bundle：
{citation_bundle_json}

报告修订要求：
1. 【最重要】必须维持或更新当前报告的「动态对比表格」结构（列为竞品，行为维度），严禁退回传统的 ## 竞品二级标题章节模式。
2. 开头必须保留或更新 2-3 句话的「市场综述」摘要，概括整体竞争格局和核心发现。
3. 如果修订计划要求新增竞品（sections_to_change.change_type==add），请在表格中增加对应的列。
4. 如果修订计划要求删除竞品（sections_to_change.change_type==delete），请从表格中移除对应的列及其所有内容。
5. 如果修订计划涉及新的分析维度，请在表格中增加对应的行；维度名使用其 label 字段，用户特别关注的维度标注"（重点关注）"。
6. 每个单元格的关键结论必须引用该条目下 evidence 中提供的 source_reference_id，格式为 `[[1]]`；严禁写成 `[1]` 或 `[1](URL)`。严禁使用 citation_bundle 中该 claim 的 evidence 列表里没有出现的引用号——如果不确定，宁可不写引用也不要编造引用号
7. 【引用保留——硬性要求】对于未被修订计划涉及的旧结论和旧单元格，必须原封不动地保留其 `[[n]]` 引用标记。即使你微调了措辞，也绝对不得丢弃原有的引用编号。引用是报告可信度的唯一来源，丢失引用等同于数据造假。
8. 如果某些信息不确定或缺失，如实填入"证据中未涉及"，不要编造。
9. 单元格内容控制在 20-60 字，单元格内禁止使用换行符，如需分行请用「；」或「——」连接。
10. 在表格之后，保留或更新原有的「深度解读」段落，每段不超过 3-4 句话。
11. 不要自行生成 `## 参考来源` 部分，系统会自动补充。
{removed_clause}

输出严格 JSON：
{{"title": "报告标题（应包含具体产品或领域名称）", "summary": "修订摘要（2-3句话概括改动点和核心发现）", "markdown_content": "修订后的完整 Markdown 报告（含摘要段落 + 对比表格 + 深度解读）"}}"""
        result = self._json_chat(prompt, fallback)

        new_markdown = result.get("markdown_content", "")
        new_markdown = _table_aware_stitch(
            old_markdown,
            new_markdown,
            fingerprints,
            excluded_citation_ids=excluded_citation_ids,
        )

        md = _normalize_inline_citations(new_markdown)
        md = _validate_citation_whitelist(md, citation_bundle_raw)
        md = _ensure_reference_section(md, sources)
        result["markdown_content"] = md
        return result

    def generate_revision_summary(
        self,
        user_message: str,
        revision_plan: dict[str, Any],
        new_report: dict[str, Any],
    ) -> str:
        prompt = f"""请为用户生成一段简短的报告修订总结，说明这次改了什么。不要超过 80 字。

用户反馈：{user_message}
修订计划：{json.dumps(revision_plan, ensure_ascii=False)}
新报告摘要：{new_report.get("summary", "")}

只输出总结文本，不要 Markdown。"""
        return self._chat(prompt) or "已根据你的反馈更新报告，并生成新的报告版本。"


def _format_analysis_for_qa(a: dict[str, Any]) -> str:
    """Format a single structured analysis entry for QA prompt context.

    Exposes all 7 core fields plus selected evidence_ids so the QA LLM can
    judge completeness, grounding, and citation accuracy.
    """
    evidence_ids = _json_list(a.get("evidence_ids_json"))
    field_evidence_ids = a.get("field_evidence_ids_json")
    if isinstance(field_evidence_ids, str):
        try:
            parsed_field_evidence_ids = json.loads(field_evidence_ids)
        except json.JSONDecodeError:
            parsed_field_evidence_ids = {}
    elif isinstance(field_evidence_ids, dict):
        parsed_field_evidence_ids = field_evidence_ids
    else:
        parsed_field_evidence_ids = {}
    lines = [
        f"竞品={a.get('competitor_name', '')}",
        f"  定位: {a.get('positioning', '')}",
        f"  目标用户: {_join_json_list_for_qa(a.get('target_users'))}",
        f"  核心功能: {_join_json_list_for_qa(a.get('core_features_json'))}",
        f"  定价: {a.get('pricing_summary', '')}",
        f"  优势: {_join_json_list_for_qa(a.get('strengths_json'))}",
        f"  劣势: {_join_json_list_for_qa(a.get('weaknesses_json'))}",
        f"  机会点: {_join_json_list_for_qa(a.get('opportunities_json'))}",
        f"  field_evidence_ids_json: {json.dumps(parsed_field_evidence_ids, ensure_ascii=False)}",
        f"  evidence_ids_json: {json.dumps(evidence_ids[:16], ensure_ascii=False)}",
        f"  关联证据数: {len(evidence_ids)}",
    ]
    return "\n".join(lines)


def _coerce_llm_evidence_id(value: Any, ref_to_ev: dict[str, str]) -> str:
    text = str(value).strip()
    if text in ref_to_ev:
        return ref_to_ev[text]
    bracketed = re.fullmatch(r"\[+(\d+)\]+", text)
    if bracketed:
        return ref_to_ev.get(bracketed.group(1), text)
    source_ref = re.search(r"(?:source_ref|ref|证据)\s*\[?(\d+)\]?", text, re.I)
    if source_ref:
        return ref_to_ev.get(source_ref.group(1), text)
    return text


def _join_json_list_for_qa(value: Any) -> str:
    """Join a JSON list stored as string into a semicolon-separated summary."""
    items = _json_list(value)
    return "；".join(items[:6]) or "(无)"


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
