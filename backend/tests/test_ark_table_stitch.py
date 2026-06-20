import pytest
from app.providers.llm.ark import (
    _normalize_table_name,
    _parse_table_grid,
    _build_semantic_citation_map,
    _fuzzy_match_dimension,
    _fuzzy_match_competitor,
    _table_aware_stitch,
    _extract_citation_fingerprints,
    _format_analysis_for_qa,
    _coerce_llm_evidence_id,
)


class TestNormalizeTableName:
    def test_strips_bold(self):
        assert _normalize_table_name("**定价策略**") == "定价策略"

    def test_strips_focus_label_cn(self):
        assert _normalize_table_name("隐私安全（重点关注）") == "隐私安全"

    def test_strips_focus_label_en(self):
        assert _normalize_table_name("Privacy (重点关注)") == "privacy"

    def test_normalizes_spaces_and_dashes(self):
        assert _normalize_table_name("  Core - Features ") == "corefeatures"

    def test_combined(self):
        assert _normalize_table_name("**定价策略（重点关注）**") == "定价策略"


def test_format_analysis_for_qa_exposes_evidence_ids_not_inline_citation_requirement():
    formatted = _format_analysis_for_qa(
        {
            "competitor_name": "Acme",
            "positioning": "AI development assistant without inline citations.",
            "target_users": '["Developers"]',
            "core_features_json": '["Completion"]',
            "pricing_summary": "Tiered pricing.",
            "strengths_json": '["Fast"]',
            "weaknesses_json": '["Limited integrations"]',
            "opportunities_json": '["Enterprise adoption"]',
            "evidence_ids_json": '["ev_1", "ev_2"]',
        }
    )

    assert 'evidence_ids_json: ["ev_1", "ev_2"]' in formatted
    assert "关联证据数: 2" in formatted


def test_coerce_llm_evidence_id_accepts_legacy_source_ref_shapes():
    ref_to_ev = {"36": "ev_36", "7": "ev_7"}

    assert _coerce_llm_evidence_id("ev_native", ref_to_ev) == "ev_native"
    assert _coerce_llm_evidence_id(36, ref_to_ev) == "ev_36"
    assert _coerce_llm_evidence_id("[36]", ref_to_ev) == "ev_36"
    assert _coerce_llm_evidence_id("source_ref [7]", ref_to_ev) == "ev_7"
    assert _coerce_llm_evidence_id("证据[7]", ref_to_ev) == "ev_7"


class TestParseTableGrid:
    def test_basic_table(self):
        md = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        grid = _parse_table_grid(md)
        assert grid == [["A", "B"], ["1", "2"]]

    def test_preserves_empty_cells(self):
        md = "| A | B | C |\n| --- | --- | --- |\n| 1 |  | 3 |"
        grid = _parse_table_grid(md)
        assert grid == [["A", "B", "C"], ["1", "", "3"]]

    def test_skips_separator(self):
        md = "| X | Y |\n| :--- | :--- |\n| a | b |"
        grid = _parse_table_grid(md)
        assert grid == [["X", "Y"], ["a", "b"]]


class TestSemanticCitationMap:
    def test_basic_mapping(self):
        md = "| 维度 | CompA | CompB |\n| --- | --- | --- |\n| **定价** | $10 [[1]] | $20 [[2]] |"
        cmap = _build_semantic_citation_map(md)
        assert cmap[("定价", "compa")] == [1]
        assert cmap[("定价", "compb")] == [2]

    def test_multiple_citations_per_cell(self):
        md = "| 维度 | X |\n| --- | --- |\n| 功能 | A [[1]] B [[2]] |"
        cmap = _build_semantic_citation_map(md)
        assert cmap[("功能", "x")] == [1, 2]


class TestFuzzyMatching:
    def test_dimension_exact(self):
        assert _fuzzy_match_dimension("定价", ["定价", "功能"]) == "定价"

    def test_dimension_fuzzy(self):
        result = _fuzzy_match_dimension("定价策略", ["定价", "功能"])
        assert result == "定价"

    def test_competitor_exact(self):
        assert _fuzzy_match_competitor("compa", ["compa", "compb"]) == "compa"

    def test_no_match(self):
        assert _fuzzy_match_dimension("zzz", ["定价", "功能"]) is None


class TestTableAwareStitch:
    def _make_fingerprints(self, ids: list[int]) -> list[dict]:
        return [{"id": i} for i in ids]

    def test_column_insertion_citations_preserved(self):
        old = (
            "| 维度 | CompA | CompB |\n"
            "| --- | --- | --- |\n"
            "| **定价** | $10 [[1]] | $20 [[2]] |"
        )
        new = (
            "| 维度 | CompA | CompC | CompB |\n"
            "| --- | --- | --- | --- |\n"
            "| **定价** | $10 | $15 | $20 |"
        )
        fps = self._make_fingerprints([1, 2])
        result = _table_aware_stitch(old, new, fps)
        assert "[[1]]" in result
        assert "[[2]]" in result
        data_lines = [l for l in result.split("\n") if "$10" in l]
        assert len(data_lines) == 1
        assert "$10 [[1]]" in data_lines[0]
        assert "$20 [[2]]" in data_lines[0]

    def test_row_deletion_citations_preserved(self):
        old = (
            "| 维度 | A | B |\n"
            "| --- | --- | --- |\n"
            "| **定价** | $10 [[1]] | $20 [[2]] |\n"
            "| **功能** | X [[3]] | Y [[4]] |"
        )
        new = "| 维度 | A | B |\n| --- | --- | --- |\n| **定价** | $10 | $20 |"
        fps = _extract_citation_fingerprints(old)
        result = _table_aware_stitch(old, new, fps)
        assert "[[1]]" in result
        assert "[[2]]" in result

    def test_dimension_rename_fuzzy_match(self):
        old = "| 维度 | A |\n| --- | --- |\n| **定价** | $10 [[1]] |"
        new = "| 维度 | A |\n| --- | --- |\n| **定价策略** | $10 |"
        fps = self._make_fingerprints([1])
        result = _table_aware_stitch(old, new, fps)
        assert "[[1]]" in result

    def test_no_citations_to_restore(self):
        old = "| 维度 | A |\n| --- | --- |\n| **定价** | $10 [[1]] |"
        new = "| 维度 | A |\n| --- | --- |\n| **定价** | $10 [[1]] |"
        fps = self._make_fingerprints([1])
        result = _table_aware_stitch(old, new, fps)
        assert result.count("[[1]]") == 1

    def test_empty_table_fallback(self):
        old = "Some text [[1]]"
        new = "Some text"
        fps = _extract_citation_fingerprints(old)
        result = _table_aware_stitch(old, new, fps)
        assert "[[1]]" in result

    def test_multiple_citations_per_cell(self):
        old = "| 维度 | A |\n| --- | --- |\n| **功能** | X [[1]] Y [[2]] |"
        new = "| 维度 | A | B |\n| --- | --- | --- |\n| **功能** | X Y | Z |"
        fps = self._make_fingerprints([1, 2])
        result = _table_aware_stitch(old, new, fps)
        assert "[[1]]" in result
        assert "[[2]]" in result

    def test_column_reorder(self):
        old = (
            "| 维度 | CompA | CompB |\n"
            "| --- | --- | --- |\n"
            "| **定价** | $10 [[1]] | $20 [[2]] |"
        )
        new = "| 维度 | CompB | CompA |\n| --- | --- | --- |\n| **定价** | $20 | $10 |"
        fps = self._make_fingerprints([1, 2])
        result = _table_aware_stitch(old, new, fps)
        lines = [
            l for l in result.split("\n") if l.strip().startswith("|") and "$" in l
        ]
        data_line = lines[0]
        assert "CompA" in new.split("\n")[0]
        a_idx = new.split("\n")[0].index("CompA")
        b_idx = new.split("\n")[0].index("CompB")
        assert a_idx > b_idx
        assert "[[1]]" in data_line
        assert "[[2]]" in data_line

    def test_competitor_name_variation(self):
        old = "| 维度 | Notion |\n| --- | --- |\n| **定价** | Free [[1]] |"
        new = "| 维度 | NotionAI |\n| --- | --- |\n| **定价** | Free |"
        fps = self._make_fingerprints([1])
        result = _table_aware_stitch(old, new, fps)
        assert "[[1]]" in result
