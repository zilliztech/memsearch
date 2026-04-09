from __future__ import annotations

from click.testing import CliRunner

from memsearch.cli import cli


class DummyMemSearch:
    last_query = None
    last_source_prefix = None

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
