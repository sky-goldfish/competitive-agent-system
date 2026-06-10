import pytest
from app.providers.llm.ark import _extract_citation_fingerprints, _stitch_citations


def test_fingerprint_stitching_exact():
    old_markdown = "Product A is very expensive [[1]]. It has many features [[2]]."
    new_markdown = "Product A is very expensive. It has many features."

    fingerprints = _extract_citation_fingerprints(old_markdown)
    stitched = _stitch_citations(new_markdown, fingerprints)

    assert "expensive [[1]]" in stitched
    assert "features [[2]]" in stitched


def test_fingerprint_stitching_slight_rewording():
    old_markdown = (
        "The pricing of Product A is relatively high [[1]], which might be a barrier."
    )
    # LLM removed 'relatively' and changed 'might be' to 'is'
    new_markdown = "The pricing of Product A is high, which is a barrier."

    fingerprints = _extract_citation_fingerprints(old_markdown)
    stitched = _stitch_citations(new_markdown, fingerprints)

    # Prefix "The pricing of Product A is relatively high" won't match exactly.
    # But word-based anchors should help it match.
    assert "[[1]]" in stitched


def test_fingerprint_stitching_avoid_duplicates():
    old_markdown = "Fact [[1]]."
    new_markdown = "Fact [[1]]."

    fingerprints = _extract_citation_fingerprints(old_markdown)
    stitched = _stitch_citations(new_markdown, fingerprints)

    # Should not add another [[1]]
    assert stitched.count("[[1]]") == 1


def test_fingerprint_stitching_multiple_at_same_place():
    old_markdown = "Dense info [[1]] [[2]]."
    new_markdown = "Dense info."

    fingerprints = _extract_citation_fingerprints(old_markdown)
    stitched = _stitch_citations(new_markdown, fingerprints)

    assert "[[1]]" in stitched
    assert "[[2]]" in stitched
