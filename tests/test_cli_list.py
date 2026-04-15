from __future__ import annotations

import json

from click.testing import CliRunner

from memsearch.cli import cli


class _DummyStore:
    def __init__(self, uri, token, collection, dimension=None):
        self.rows = [
            {"source": "/tmp/memory/2026-04-15.md", "heading": "Rust setup", "chunk_hash": "a"},
            {"source": "/tmp/memory/2026-04-15.md", "heading": "Rust setup", "chunk_hash": "b"},
            {"source": "/tmp/memory/2026-04-16.md", "heading": "Python env", "chunk_hash": "c"},
        ]

    def query(self, *, filter_expr: str = ""):
        return self.rows

    def close(self):
        pass


def test_list_command_groups_chunks_by_source(monkeypatch) -> None:
    monkeypatch.setattr("memsearch.cli.resolve_config", lambda *_args, **_kwargs: type("Cfg", (), {"milvus": type("M", (), {"uri": "sqlite", "token": "", "collection": "test"})()})())
    monkeypatch.setattr("memsearch.store.MilvusStore", _DummyStore)

    runner = CliRunner()
    result = runner.invoke(cli, ["list"])

    assert result.exit_code == 0
    assert "/tmp/memory/2026-04-15.md (2 chunks)" in result.output
    assert "Rust setup" in result.output
    assert "/tmp/memory/2026-04-16.md (1 chunks)" in result.output


def test_list_command_supports_json_output(monkeypatch) -> None:
    monkeypatch.setattr("memsearch.cli.resolve_config", lambda *_args, **_kwargs: type("Cfg", (), {"milvus": type("M", (), {"uri": "sqlite", "token": "", "collection": "test"})()})())
    monkeypatch.setattr("memsearch.store.MilvusStore", _DummyStore)

    runner = CliRunner()
    result = runner.invoke(cli, ["list", "--json-output"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["source"] == "/tmp/memory/2026-04-15.md"
    assert payload[0]["chunk_count"] == 2
    assert payload[0]["headings"] == ["Rust setup"]
