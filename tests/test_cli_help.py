"""Tests for CLI help and version commands."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from memsearch.cli import cli


@pytest.mark.parametrize(
    ("args", "expected_text"),
    [
        pytest.param(["--help"], "Usage:", id="main-help"),
        pytest.param(["config", "--help"], "Usage:", id="config-help"),
        pytest.param(["config", "init", "--help"], "Usage:", id="config-init-help"),
        pytest.param(["config", "set", "--help"], "Usage:", id="config-set-help"),
        pytest.param(["config", "get", "--help"], "Usage:", id="config-get-help"),
        pytest.param(["config", "list", "--help"], "Usage:", id="config-list-help"),
        pytest.param(["index", "--help"], "Usage:", id="index-help"),
        pytest.param(["search", "--help"], "Usage:", id="search-help"),
        pytest.param(["expand", "--help"], "Usage:", id="expand-help"),
        pytest.param(["stats", "--help"], "Usage:", id="stats-help"),
        pytest.param(["reset", "--help"], "Usage:", id="reset-help"),
        pytest.param(["watch", "--help"], "Usage:", id="watch-help"),
        pytest.param(["compact", "--help"], "Usage:", id="compact-help"),
        pytest.param(["--version"], "version", id="version"),
    ],
)
def test_cli_help_and_version_commands(args: list[str], expected_text: str) -> None:
    """CLI entrypoints should expose stable help/version output."""
    runner = CliRunner()
    result = runner.invoke(cli, args)

    assert result.exit_code == 0
    assert expected_text in result.output
