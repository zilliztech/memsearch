"""Tests for the compact CLI command."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from memsearch.cli import cli


class _FakeMemSearch:
    last_source: str | None = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def compact(self, **kwargs):
        _FakeMemSearch.last_source = kwargs.get("source")
        return ""

    def close(self):
        return None


def test_compact_resolves_relative_source_to_absolute_path(tmp_path: Path, monkeypatch):
    source_file = tmp_path / "memory" / "old-notes.md"
    source_file.parent.mkdir()
    source_file.write_text("# Old notes\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("memsearch.core.MemSearch", _FakeMemSearch)
    _FakeMemSearch.last_source = None

    runner = CliRunner()
    result = runner.invoke(cli, ["compact", "--source", "memory/old-notes.md"])

    assert result.exit_code == 0
    assert _FakeMemSearch.last_source == str(source_file.resolve())
    assert "No chunks to compact." in result.output
