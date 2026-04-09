from __future__ import annotations

from typing import ClassVar

from click.testing import CliRunner

from memsearch.cli import cli


class DummyMemSearch:
    last_query = None
    last_source_prefix = None
    list_sources_result: ClassVar[list[str]] = ["/tmp/notes.md"]

    async def search(self, query: str, **kwargs):
        DummyMemSearch.last_query = query
        DummyMemSearch.last_source_prefix = kwargs.get("source_prefix")
        return [
            {
                "content": "Version 111123 release checklist",
                "source": "/tmp/notes.md",
                "heading": "Release",
                "score": 0.99,
                "chunk_hash": "h_numeric",
            }
        ]

    def list_sources(self):
        return list(self.list_sources_result)

    def close(self) -> None:
        pass


def test_search_cli_accepts_numeric_only_query(monkeypatch):
    monkeypatch.setattr("memsearch.core.MemSearch", lambda **kwargs: DummyMemSearch())

    runner = CliRunner()
    result = runner.invoke(cli, ["search", "111123"])

    assert result.exit_code == 0
    assert DummyMemSearch.last_query == "111123"
    assert "Version 111123 release checklist" in result.output


def test_search_cli_normalizes_existing_source_prefix(monkeypatch, tmp_path):
    note = tmp_path / "memory" / "old-notes.md"
    note.parent.mkdir()
    note.write_text("# note\n")

    monkeypatch.setattr("memsearch.core.MemSearch", lambda **kwargs: DummyMemSearch())

    runner = CliRunner()
    result = runner.invoke(cli, ["search", "111123", "--source-prefix", str(note.parent)])

    assert result.exit_code == 0
    assert DummyMemSearch.last_source_prefix == str(note.parent.resolve())


def test_search_cli_leaves_non_path_source_prefix_unchanged(monkeypatch):
    monkeypatch.setattr("memsearch.core.MemSearch", lambda **kwargs: DummyMemSearch())

    runner = CliRunner()
    result = runner.invoke(cli, ["search", "111123", "--source-prefix", "session:abc123"])

    assert result.exit_code == 0
    assert DummyMemSearch.last_source_prefix == "session:abc123"


def test_list_cli_renders_sources(monkeypatch):
    DummyMemSearch.list_sources_result = ["/tmp/a.md", "/tmp/b.md"]
    monkeypatch.setattr("memsearch.core.MemSearch", lambda **kwargs: DummyMemSearch())

    runner = CliRunner()
    result = runner.invoke(cli, ["list"])

    assert result.exit_code == 0
    assert "/tmp/a.md" in result.output
    assert "/tmp/b.md" in result.output


def test_list_cli_reports_empty_index(monkeypatch):
    DummyMemSearch.list_sources_result = []
    monkeypatch.setattr("memsearch.core.MemSearch", lambda **kwargs: DummyMemSearch())

    runner = CliRunner()
    result = runner.invoke(cli, ["list"])

    assert result.exit_code == 0
    assert "No memories indexed." in result.output
