"""Tests for the pre-write memory quality filter (Proposal 002)."""

from __future__ import annotations

import json

from click.testing import CliRunner

from memsearch.cli import cli
from memsearch.quality import (
    QualityFilterSettings,
    decide,
    evaluate_section,
    extract_sections,
    score_section,
)

GOOD_NOTE = (
    "Implemented a pre-write scoring gate in memsearch: a new quality.py "
    "module evaluates candidate memory sections before append, applying "
    "penalties for meta talk, boilerplate, short content, repetition, and "
    "near-duplicates."
)

META_NOTE = "[memsearch] Recall available if needed."

SHORT_NOTE = "Fixed a bug."

DUPLICATE_TEXT = " ".join(["word"] * 60)


# -- score_section: individual penalties --


def test_clean_section_scores_100() -> None:
    score, reasons = score_section(GOOD_NOTE)
    assert score == 100
    assert reasons == ()


def test_meta_memory_vocabulary_penalized() -> None:
    # Long enough to avoid the short-content penalty, no other penalty.
    text = "Discussed plugin behaviour: [memsearch] Recall available if needed, and hooks."
    score, reasons = score_section(text)
    assert score == 100 - 25
    assert "meta-memory vocabulary" in reasons


def test_agent_boilerplate_penalized() -> None:
    text = "The user asked about deployment options. " + GOOD_NOTE
    score, reasons = score_section(text)
    assert score == 100 - 10
    assert "agent-verbosity boilerplate" in reasons


def test_short_content_penalized() -> None:
    score, reasons = score_section(SHORT_NOTE)
    assert "content shorter than min_content_length (40)" in reasons
    assert score == 100 - 30


def test_short_content_respects_setting() -> None:
    cfg = QualityFilterSettings(min_content_length=5)
    score, reasons = score_section(SHORT_NOTE, settings=cfg)
    assert reasons == ()
    assert score == 100


def test_high_repetition_penalized() -> None:
    text = " ".join(["important"] * 80)
    score, reasons = score_section(text)
    assert score == 100 - 20
    assert "high token repetition ratio" in reasons


def test_normal_prose_has_low_repetition() -> None:
    _, reasons = score_section(GOOD_NOTE)
    assert "high token repetition ratio" not in reasons


def test_near_duplicate_penalized() -> None:
    recent = [GOOD_NOTE]
    score, reasons = score_section(GOOD_NOTE, recent_sections=recent)
    assert score == 100 - 40
    assert "near-duplicate of a recent section" in reasons


def test_distinct_section_not_flagged_as_duplicate() -> None:
    recent = [GOOD_NOTE]
    other = (
        "Ubuntu parity run completed: 413 passed, 7 skipped on the Linux "
        "native clone; PR description updated with the verification matrix."
    )
    _, reasons = score_section(other, recent_sections=recent)
    assert "near-duplicate of a recent section" not in reasons


def test_penalties_stack() -> None:
    text = "[memsearch] Recall available. short"
    score, reasons = score_section(text)
    assert score == 100 - 25 - 30
    assert len(reasons) == 2


def test_score_never_negative() -> None:
    # All five penalties at once via a raised min_content_length.
    text = "The user asked [memsearch] blah blah blah blah blah blah"
    cfg = QualityFilterSettings(min_content_length=10_000)
    score, reasons = score_section(text, recent_sections=[text], settings=cfg)
    assert len(reasons) == 5
    assert score == 0


# -- decide / evaluate_section --


def test_decide_boundaries() -> None:
    assert decide(60) == "write"
    assert decide(100) == "write"
    assert decide(59) == "degrade"
    assert decide(30) == "degrade"
    assert decide(29) == "reject"
    assert decide(0) == "reject"


def test_disabled_filter_writes_everything() -> None:
    verdict = evaluate_section(SHORT_NOTE, settings=QualityFilterSettings(enabled=False))
    assert verdict.action == "write"
    assert verdict.score == 100


def test_evaluate_section_rejects_garbage() -> None:
    text = "The user asked [memsearch] blah blah blah blah blah blah"
    cfg = QualityFilterSettings(min_content_length=10_000)
    verdict = evaluate_section(text, recent_sections=[text], settings=cfg)
    assert verdict.action == "reject"


# -- purity (property-style invariants) --


def test_score_is_deterministic() -> None:
    for _ in range(5):
        assert score_section(META_NOTE + " " + DUPLICATE_TEXT) == score_section(
            META_NOTE + " " + DUPLICATE_TEXT
        )


def test_score_does_not_mutate_inputs() -> None:
    recent = [GOOD_NOTE]
    snapshot = list(recent)
    score_section(GOOD_NOTE, recent_sections=recent)
    assert recent == snapshot


# -- extract_sections --


def test_extract_sections_splits_on_headings_and_strips_anchors() -> None:
    journal = (
        "### 01:10\n<!-- session:s1 turn:2 db:x -->\nFirst turn note.\n\n"
        "### 01:23\n<!-- session:s2 turn:7 db:y -->\nSecond turn note.\n"
    )
    sections = extract_sections(journal)
    assert len(sections) == 2
    assert "session:s1" not in sections[0]
    assert "First turn note." in sections[0]


def test_anchors_do_not_create_false_duplicates() -> None:
    # A new turn summary that only shares anchor metadata (and differs in
    # content) must not be flagged as a near-duplicate; identical content must.
    candidate = (
        "Configured the DSH web profile to link the memsearch plugin and "
        "documented restart instructions for future sessions."
    )
    journal = (
        "### 01:10\n<!-- session:s1 turn:2 db:x -->\n" + GOOD_NOTE + "\n\n"
        "### 01:20\n<!-- session:s1 turn:3 db:x -->\n" + GOOD_NOTE + "\n"
    )
    recent = extract_sections(journal)
    _, reasons = score_section(candidate, recent_sections=recent)
    assert "near-duplicate of a recent section" not in reasons
    _, reasons = score_section(GOOD_NOTE, recent_sections=recent)
    assert "near-duplicate of a recent section" in reasons


# -- regression: real conversational turn summaries are not rejected --


REAL_TURN_SUMMARIES = [
    GOOD_NOTE,
    "Opened PR zilliztech/memsearch#729 documenting three proposals: idle "
    "consolidation, pre-write quality filter, and heat/cold archive.",
    "Ubuntu parity run for feat/llm-audit finished: 413 passed, 7 skipped; "
    "the PR was marked ready for review afterwards.",
    "Reviewed the DSH plugin summarize path and confirmed the profile override "
    "reaches the headless summarizer without changing the Web model.",
    "Discussed merge timing for PR #721 with the user; expectations set to "
    "several hours up to a few days depending on maintainer availability.",
]


def test_regression_reject_rate_on_real_turns() -> None:
    written: list[str] = []
    rejected = 0
    for note in REAL_TURN_SUMMARIES:
        verdict = evaluate_section(note, recent_sections=written)
        if verdict.action == "reject":
            rejected += 1
        else:
            written.append(note)
    assert rejected == 0
    assert len(written) == len(REAL_TURN_SUMMARIES)


# -- CLI --


def test_quality_cli_from_stdin_json() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["quality", "-j"], input=GOOD_NOTE)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["action"] == "write"
    assert payload["score"] == 100


def test_quality_cli_rejects_meta_noise() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["quality", "-j"], input=META_NOTE)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["action"] in {"degrade", "reject"}
    assert "meta-memory vocabulary" in payload["reasons"]


def test_quality_cli_recent_file(tmp_path) -> None:
    journal = tmp_path / "2026-09-08.md"
    journal.write_text(f"### 01:10\n<!-- anchor -->\n{GOOD_NOTE}\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli, ["quality", "-j", "--recent-file", str(journal)], input=GOOD_NOTE
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "near-duplicate of a recent section" in payload["reasons"]


def test_quality_cli_plain_output() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["quality"], input=SHORT_NOTE)
    assert result.exit_code == 0, result.output
    assert "action:" in result.output
