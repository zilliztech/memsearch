from __future__ import annotations

from click.testing import CliRunner

from memsearch.cli import cli


class DummyMemSearch:
    last_query = None

    async def search(self, query: str, **kwargs):
        DummyMemSearch.last_query = query
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
