"""Tests for the MCP server."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from memsearch.config import MemSearchConfig
from memsearch.mcp_server import MCPServer, serve


class FakeStore:
    """Minimal stand-in for MilvusStore."""

    def __init__(self, chunks: list[dict]) -> None:
        self.chunks = chunks

    def count(self) -> int:
        return len(self.chunks)

    def indexed_sources(self) -> set[str]:
        return {c["source"] for c in self.chunks}

    def query(self, *, filter_expr: str = "") -> list[dict]:
        return list(self.chunks)

    def close(self) -> None:
        pass


class FakeMemSearch:
    """Minimal stand-in for MemSearch."""

    def __init__(self, results: list[dict]) -> None:
        self.results = results
        self.calls: list[tuple[str, int, str | None]] = []

    async def search(self, query: str, *, top_k: int = 10, source_prefix: str | None = None):
        self.calls.append((query, top_k, source_prefix))
        return self.results[:top_k]

    def close(self) -> None:
        pass


@pytest.fixture
def server(monkeypatch) -> MCPServer:
    # Hermetic: never pick up a real dsh-knowledge store on the test machine.
    monkeypatch.setattr("memsearch.mcp_server._auto_knowledge_db", lambda: "")
    return MCPServer(config=MemSearchConfig(), collection="test_collection")


def _request(server: MCPServer, method: str, params: dict | None = None, mid: int = 1) -> dict:
    reply = server.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
    assert reply is not None
    return reply


def test_initialize_advertises_tools(server: MCPServer) -> None:
    reply = _request(server, "initialize", {"protocolVersion": "2024-11-05"})
    result = reply["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["serverInfo"]["name"] == "memsearch"


def test_initialized_notification_has_no_reply(server: MCPServer) -> None:
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list_exposes_the_core_tools(server: MCPServer) -> None:
    reply = _request(server, "tools/list")
    names = [t["name"] for t in reply["result"]["tools"]]
    assert names == [
        "memory_search",
        "memory_index",
        "memory_stats",
        "memory_expand",
        "embed",
        "rerank",
    ]
    for tool in reply["result"]["tools"]:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"


def test_knowledge_tool_absent_without_store(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("memsearch.mcp_server.DEFAULT_KNOWLEDGE_DB", tmp_path / "missing.sqlite")
    srv = MCPServer(config=MemSearchConfig(), collection="test_collection")
    names = [t["name"] for t in _request(srv, "tools/list")["result"]["tools"]]
    assert "knowledge_search" not in names


def test_knowledge_tool_auto_detected_with_default_store(monkeypatch, tmp_path) -> None:
    store = tmp_path / "knowledge-chunks.sqlite"
    store.write_bytes(b"")
    monkeypatch.setattr("memsearch.mcp_server.DEFAULT_KNOWLEDGE_DB", store)
    srv = MCPServer(config=MemSearchConfig(), collection="test_collection")
    names = [t["name"] for t in _request(srv, "tools/list")["result"]["tools"]]
    assert "knowledge_search" in names


def test_knowledge_search_is_only_advertised_with_a_store(tmp_path: Path) -> None:
    db = tmp_path / "knowledge.sqlite"
    db.write_bytes(b"")
    server = MCPServer(config=MemSearchConfig(), knowledge_db=str(db))
    names = [t["name"] for t in server.tool_definitions()]
    assert "knowledge_search" in names


def test_tools_call_search_returns_formatted_hits(server: MCPServer) -> None:
    fake = FakeMemSearch(
        [
            {
                "content": "校机的向量服务跑在 8080",
                "source": "/tmp/notes.md",
                "heading": "端口",
                "score": 0.9981,
                "chunk_hash": "abc123",
                "start_line": 3,
                "end_line": 9,
            }
        ]
    )
    server._ms = fake
    reply = _request(server, "tools/call", {"name": "memory_search", "arguments": {"query": "端口"}})
    content = reply["result"]["content"][0]["text"]
    assert "abc123" in content
    assert "0.9981" in content
    assert fake.calls == [("端口", 5, None)]


def test_tools_call_reports_invalid_arguments_as_tool_error(server: MCPServer) -> None:
    reply = _request(server, "tools/call", {"name": "memory_search", "arguments": {}})
    assert reply["result"]["isError"] is True
    assert "query is required" in reply["result"]["content"][0]["text"]


def test_unknown_tool_returns_jsonrpc_error(server: MCPServer) -> None:
    reply = _request(server, "tools/call", {"name": "nope", "arguments": {}})
    assert reply["error"]["code"] == -32601


def test_unknown_method_returns_jsonrpc_error(server: MCPServer) -> None:
    reply = _request(server, "does/not/exist")
    assert reply["error"]["code"] == -32601


def test_stats_reports_the_collection(server: MCPServer) -> None:
    server._store = FakeStore([{"source": "a.md"}, {"source": "b.md"}])
    reply = _request(server, "tools/call", {"name": "memory_stats", "arguments": {}})
    text = reply["result"]["content"][0]["text"]
    assert "test_collection" in text
    assert "Total indexed chunks: 2" in text


def test_expand_returns_the_full_section(server: MCPServer, tmp_path: Path) -> None:
    doc = tmp_path / "notes.md"
    doc.write_text("# 标题\n\n正文第一行。\n\n## 小节\n\n小节内容。\n", encoding="utf-8")
    server._store = FakeStore(
        [
            {
                "chunk_hash": "h1",
                "source": str(doc),
                "heading": "标题",
                "heading_level": 1,
                "start_line": 1,
                "end_line": 3,
            }
        ]
    )
    reply = _request(server, "tools/call", {"name": "memory_expand", "arguments": {"chunk_id": "h1"}})
    text = reply["result"]["content"][0]["text"]
    assert "## 小节" in text
    assert "小节内容。" in text


def test_stdio_loop_answers_every_request() -> None:
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        + "\n"
    )
    stdout = io.StringIO()
    serve(config=MemSearchConfig(), stdin=stdin, stdout=stdout)
    lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert [line["id"] for line in lines] == [1, 2]
    assert lines[0]["result"]["serverInfo"]["name"] == "memsearch"
    assert lines[1]["result"]["tools"]


def test_stdio_loop_survives_a_broken_line() -> None:
    stdin = io.StringIO("not json\n" + json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}) + "\n")
    stdout = io.StringIO()
    serve(config=MemSearchConfig(), stdin=stdin, stdout=stdout)
    lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["id"] == 7


def test_chinese_payload_survives_the_stdio_loop() -> None:
    query = "校机的向量服务端口"
    server = MCPServer(config=MemSearchConfig(), collection="test_collection")
    fake = FakeMemSearch(
        [{"content": "端口 8080", "source": "a.md", "heading": "端口", "score": 1.0, "chunk_hash": "h"}]
    )
    server._ms = fake
    stdin = io.StringIO(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "memory_search", "arguments": {"query": query}},
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    stdout = io.StringIO()
    serve(config=MemSearchConfig(), stdin=stdin, stdout=stdout, server=server)
    reply = json.loads(stdout.getvalue().splitlines()[0])
    assert reply["result"]["isError"] is False
    assert "端口" in reply["result"]["content"][0]["text"]
    assert fake.calls[0][0] == query
