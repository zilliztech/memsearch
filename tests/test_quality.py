"""Tests for deterministic pre-write memory quality scoring."""

from __future__ import annotations

from memsearch.quality import normalize_text, score_section


def test_good_section_writes_normally() -> None:
    verdict = score_section("Implemented a deterministic scorer and added focused regression tests for it.")

    assert verdict.score == 100
    assert verdict.action == "write"
    assert verdict.reasons == ()


def test_penalties_are_reported_without_hiding_valid_text() -> None:
    text = "[memsearch] The user asked the assistant to explain the plugin behaviour in detail."

    verdict = score_section(text)

    assert verdict.score == 65
    assert verdict.action == "write"
    assert verdict.reasons == ("meta-memory", "boilerplate")


def test_short_repetitive_meta_section_is_rejected() -> None:
    verdict = score_section("[memsearch] x x x x x x x x x x")

    assert verdict.score == 25
    assert verdict.action == "reject"
    assert verdict.reasons == ("meta-memory", "too-short", "repetitive")


def test_threshold_boundaries_are_stable() -> None:
    # A short section scores exactly 70: at degrade it writes, at reject it
    # degrades, and one point below reject it is rejected.
    text = "short note"

    assert score_section(text, degrade_threshold=70, reject_threshold=30).action == "write"
    assert score_section(text, degrade_threshold=71, reject_threshold=70).action == "degrade"
    assert score_section(text, degrade_threshold=71, reject_threshold=71).action == "reject"


def test_near_duplicate_requires_jaccard_strictly_above_point_eight() -> None:
    candidate = "alpha beta gamma delta epsilon zeta eta"
    exactly_point_eight = "alpha beta gamma delta epsilon zeta"

    assert score_section(candidate, [exactly_point_eight], min_content_length=0).score == 100
    duplicate = score_section(candidate, [candidate], min_content_length=0)
    assert duplicate.score == 60
    assert duplicate.reasons == ("near-duplicate",)


def test_disabled_filter_preserves_existing_write_behaviour() -> None:
    verdict = score_section("[memsearch] x", enabled=False)

    assert verdict.score == 100
    assert verdict.action == "write"
    assert verdict.reasons == ()


def test_normalization_removes_anchor_and_replaces_lone_surrogates() -> None:
    normalized = normalize_text("<!-- session:abc turn:1 -->\n\u041f\u0440\u0438\u0432\u0435\u0442 \udc98")

    assert "session" not in normalized
    assert "\u043f\u0440\u0438\u0432\u0435\u0442" in normalized
    assert "\udc98" not in normalized


def test_invalid_threshold_order_is_rejected() -> None:
    try:
        score_section("valid text", reject_threshold=70, degrade_threshold=60)
    except ValueError as error:
        assert "thresholds" in str(error)
    else:
        raise AssertionError("invalid thresholds must raise ValueError")
