"""Tests for the side-effect-free ``memsearch quality`` command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from memsearch.cli import cli


def test_quality_json_reports_a_stable_verdict() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["quality", "--json-output"],
        input="Implemented configuration validation and deterministic scoring for captured memory.\n",
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"score": 100, "action": "write", "reasons": []}


def test_quality_uses_recent_file_for_duplicate_detection(tmp_path: Path) -> None:
    runner = CliRunner()
    candidate = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"
    recent = tmp_path / "2026-09-13.md"
    recent.write_text(candidate, encoding="utf-8")

    result = runner.invoke(
        cli,
        ["quality", "--json-output", "--recent-file", str(recent)],
        input=candidate,
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"score": 60, "action": "write", "reasons": ["near-duplicate"]}


def test_quality_rejects_missing_candidate_on_stderr() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["quality", "--json-output"], input="  \n")

    assert result.exit_code != 0
    assert result.stdout == ""
    assert "Candidate section is required" in result.stderr
