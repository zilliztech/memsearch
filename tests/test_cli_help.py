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


@pytest.mark.parametrize("args", [["index", "--help"], ["watch", "--help"]])
def test_chunk_size_flag_appears_in_help(args: list[str]) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, args)

    assert result.exit_code == 0
    assert "--max-chunk-size" in result.output


def test_search_help_mentions_extra_scope():
    result = CliRunner().invoke(cli, ["search", "--help"])
    assert result.exit_code == 0
    assert "--extra-scope" in result.output
    assert "--only-scope" in result.output


def test_search_text_output_includes_scope_when_present(monkeypatch):
    """When results carry a 'scope' field, the text output shows it."""
    from click.testing import CliRunner

    from memsearch import cli as cli_mod

    fake_results = [
        {"chunk_hash": "h1", "score": 0.9, "source": "/x.md", "heading": "H", "content": "hi", "scope": "global"},
    ]

    class FakeMS:
        def __init__(self, *a, **kw):
            pass

        async def search(self, *a, **kw):
            return fake_results

        def close(self):
            pass

    monkeypatch.setattr("memsearch.core.MemSearch", FakeMS)
    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["search", "foo"])
    assert "scope: global" in result.output
