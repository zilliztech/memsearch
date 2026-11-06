"""MCP boundary and resource regressions; no network services are required."""

from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import sys
from types import ModuleType, SimpleNamespace

import pytest

from memsearch.config import MemSearchConfig
from memsearch.index_report import IndexFailure, IndexReport
from memsearch.mcp_server import MCPServer, serve


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr("memsearch.mcp_server._auto_knowledge_db", lambda: "")
    srv = MCPServer(config=MemSearchConfig(), collection="test")
    yield srv
    srv.close()


def call(server, name, arguments):
    return server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    )["result"]


@pytest.mark.parametrize("method", ["ping", "tools/list", "initialize"])
def test_notifications_do_not_generate_responses(server, method):
    source = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "method": method})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"})
        + "\n"
    )
    sink = io.StringIO()
    serve(config=server._cfg, stdin=source, stdout=sink, server=server)
    assert [json.loads(line)["id"] for line in sink.getvalue().splitlines()] == [7]


def test_explicit_null_id_is_distinct_from_notification(server):
    reply = server.handle({"jsonrpc": "2.0", "id": None, "method": "ping"})
    assert reply is not None and reply["id"] is None


@pytest.mark.parametrize("value", ["false", 0, 1, None, [], {}])
def test_invalid_force_is_rejected_before_creating_backend(server, monkeypatch, tmp_path, value):
    note = tmp_path / "note.md"
    note.write_text("# Note\ntext\n", encoding="utf-8")
    created = []
    monkeypatch.setattr("memsearch.core.MemSearch", lambda **kwargs: created.append(kwargs))
    reply = call(server, "memory_index", {"paths": [str(note)], "force": value})
    assert reply["isError"] is True
    assert "force" in reply["content"][0]["text"]
    assert created == []


@pytest.mark.parametrize("value", [-1, 0, True, "2", 1.5])
@pytest.mark.parametrize("tool", ["memory_search", "knowledge_search"])
def test_invalid_limit_is_rejected_before_using_backend(server, monkeypatch, tool, value):
    monkeypatch.setattr(server, "_memsearch", lambda: pytest.fail("invalid limit reached backend"))
    server._knowledge_db = "not-opened.sqlite"
    reply = call(server, tool, {"query": "needle", "limit": value})
    assert reply["isError"] is True
    assert "limit" in reply["content"][0]["text"]


@pytest.mark.parametrize("value", [-1, True, "1", 1.5])
def test_invalid_expand_context_is_rejected(server, tmp_path, value):
    note = tmp_path / "note.md"
    note.write_text("first\nsecond\nthird\n", encoding="utf-8")
    server._store = SimpleNamespace(
        query=lambda **kwargs: [{"source": str(note), "start_line": 2, "end_line": 2, "heading_level": 0}]
    )
    reply = call(server, "memory_expand", {"chunk_id": "h", "lines": value})
    assert reply["isError"] is True
    assert "lines" in reply["content"][0]["text"]


def test_zero_expand_context_returns_exact_chunk(server, tmp_path):
    note = tmp_path / "note.md"
    note.write_text("first\nsecond\nthird\n", encoding="utf-8")
    server._store = SimpleNamespace(
        query=lambda **kwargs: [{"source": str(note), "start_line": 2, "end_line": 2, "heading_level": 0}]
    )
    reply = call(server, "memory_expand", {"chunk_id": "h", "lines": 0})
    assert reply["isError"] is False
    assert "lines 2-2" in reply["content"][0]["text"]
    assert reply["content"][0]["text"].endswith("\n\nsecond")


def test_expand_escapes_quotes_and_backslashes(server):
    queries = []
    server._store = SimpleNamespace(query=lambda **kwargs: queries.append(kwargs["filter_expr"]) or [])
    chunk_id = 'prefix" OR value == "' + chr(92) + "tail"
    call(server, "memory_expand", {"chunk_id": chunk_id})
    assert queries == [f"chunk_hash == {json.dumps(chunk_id)}"]


def test_repeated_async_tools_share_live_loop(server):
    loops = []

    class Provider:
        model_name = "fake"
        dimension = 2

        async def embed(self, texts):
            loop = asyncio.get_running_loop()
            if loops:
                assert loop is loops[0], "cached client moved to another loop"
            loops.append(loop)
            return [[1.0, 0.0] for _ in texts]

    provider = Provider()

    class Memory:
        _embedder = provider

        async def search(self, query, **kwargs):
            await provider.embed([query])
            return []

        def close(self):
            pass

    server._ms = Memory()
    assert call(server, "memory_search", {"query": "first"})["isError"] is False
    assert call(server, "embed", {"texts": ["second"]})["isError"] is False
    assert call(server, "memory_search", {"query": "third"})["isError"] is False
    assert len(loops) == 3
    server.close()
    assert loops[0].is_closed()


def test_embed_does_not_open_a_memory_collection(server, monkeypatch):
    class Provider:
        model_name = "fake"
        dimension = 2

        async def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr("memsearch.embeddings.get_provider", lambda *args, **kwargs: Provider())
    monkeypatch.setattr(server, "_memsearch", lambda: pytest.fail("embed must not open a collection"))
    reply = call(server, "embed", {"texts": ["text"]})
    assert reply["isError"] is False
    assert json.loads(reply["content"][0]["text"])["dimension"] == 2


@pytest.mark.parametrize("indexed,failures", [(0, 1), (1, 1)])
def test_indexing_failures_reach_the_client(server, monkeypatch, tmp_path, indexed, failures):
    note = tmp_path / "note.md"
    note.write_text("# Note\ntext\n", encoding="utf-8")
    report = IndexReport(indexed, indexed + failures, indexed, (IndexFailure(str(note), "provider unavailable"),))

    class Memory:
        def __init__(self, **kwargs):
            pass

        async def index(self, **kwargs):
            return report.indexed_chunks

        async def index_with_report(self, **kwargs):
            return report

        def close(self):
            pass

    monkeypatch.setattr("memsearch.core.MemSearch", Memory)
    reply = call(server, "memory_index", {"paths": [str(note)]})
    assert reply["isError"] is True
    assert "provider unavailable" in reply["content"][0]["text"]
    assert str(note) in reply["content"][0]["text"]


def test_index_invalidates_cached_missing_collection(server, monkeypatch, tmp_path):
    note = tmp_path / "note.md"
    note.write_text("# Note\ntext\n", encoding="utf-8")
    state = {"exists": False}
    closed = []

    class Store:
        def __init__(self, **kwargs):
            self.exists = state["exists"]

        def count(self):
            if not self.exists:
                raise RuntimeError("collection does not exist")
            return 1

        def indexed_sources(self):
            return {str(note)}

        def close(self):
            closed.append("store")

    class Memory:
        def __init__(self, **kwargs):
            pass

        async def index(self, **kwargs):
            state["exists"] = True
            return 1

        async def index_with_report(self, **kwargs):
            state["exists"] = True
            return IndexReport(1, 1, 1)

        def close(self):
            closed.append("writer")

    monkeypatch.setattr("memsearch.store.MilvusStore", Store)
    monkeypatch.setattr("memsearch.core.MemSearch", Memory)
    assert call(server, "memory_stats", {})["isError"] is True
    assert call(server, "memory_index", {"paths": [str(note)]})["isError"] is False
    reply = call(server, "memory_stats", {})
    assert reply["isError"] is False
    assert "Total indexed chunks: 1" in reply["content"][0]["text"]
    assert "store" in closed


def test_index_invalidates_cached_memsearch(server, monkeypatch, tmp_path):
    note = tmp_path / "note.md"
    note.write_text("# Note\ntext\n", encoding="utf-8")
    state = {"exists": False}
    closed = []

    class Memory:
        def __init__(self, **kwargs):
            self.exists = state["exists"]

        async def search(self, query, **kwargs):
            if not self.exists:
                raise RuntimeError("collection does not exist")
            return []

        async def index_with_report(self, **kwargs):
            state["exists"] = True
            return IndexReport(1, 1, 1)

        def close(self):
            closed.append(self)

    monkeypatch.setattr("memsearch.core.MemSearch", Memory)
    assert call(server, "memory_search", {"query": "q"})["isError"] is True
    original = server._ms
    assert call(server, "memory_index", {"paths": [str(note)]})["isError"] is False
    assert call(server, "memory_search", {"query": "q"})["isError"] is False
    assert original in closed
    assert server._ms is not original


@pytest.mark.parametrize("force", [False, True])
def test_boolean_force_is_preserved(server, monkeypatch, tmp_path, force):
    note = tmp_path / "note.md"
    note.write_text("# Note\ntext\n", encoding="utf-8")
    seen = []

    class Memory:
        def __init__(self, **kwargs):
            pass

        async def index_with_report(self, *, force):
            seen.append(force)
            return IndexReport(1, 1, 1)

        def close(self):
            pass

    monkeypatch.setattr("memsearch.core.MemSearch", Memory)
    assert call(server, "memory_index", {"paths": [str(note)], "force": force})["isError"] is False
    assert seen == [force]


def test_rerank_scores_stay_with_their_documents(server, monkeypatch):
    fake = ModuleType("memsearch.remote_reranker")

    class Reranker:
        def __init__(self, **kwargs):
            pass

        def rerank(self, query, candidates):
            return [{"content": candidates[1]["content"], "score": 0.9}]

    fake.RemoteReranker = Reranker
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    server._cfg.reranker.model = "remote:fake"
    reply = call(server, "rerank", {"query": "q", "documents": ["wrong", "right"]})
    text = reply["content"][0]["text"]
    assert "0.900000  right" in text
    assert "wrong" not in text


def test_partial_rerank_does_not_invent_zero_scores(server, monkeypatch):
    fake = ModuleType("memsearch.remote_reranker")

    class Reranker:
        def __init__(self, **kwargs):
            pass

        def evaluate(self, query, documents):
            return {"results": []}

        def scores(self, response, count):
            return {1: -0.5}

    fake.RemoteReranker = Reranker
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    server._cfg.reranker.model = "remote:fake"
    assert server._rerank_documents("q", ["omitted", "scored"]) == [None, -0.5]


def test_remote_adapter_and_mcp_share_partial_score_semantics(server, monkeypatch):
    remote = pytest.importorskip("memsearch.remote_reranker", reason="remote adapter is supplied by PR #833")
    import email.message
    import urllib.response

    def respond(handler, request):
        body = json.dumps({"results": [{"index": 1, "relevance_score": -0.5}]}).encode()
        response = urllib.response.addinfourl(io.BytesIO(body), email.message.Message(), request.full_url, 200)
        response.msg = "OK"
        return response

    monkeypatch.setattr("urllib.request.HTTPSHandler.https_open", respond)
    monkeypatch.setattr("urllib.request.getproxies", dict)
    monkeypatch.setenv("MEMSEARCH_REMOTE_RERANKER_URL", "https://review.invalid/v1/rerank")
    monkeypatch.delenv("MEMSEARCH_REMOTE_RERANKER_API_KEY", raising=False)
    server._cfg.reranker.model = "remote:review"
    assert server._rerank_documents("q", ["omitted", "scored"]) == [None, -0.5]
    ranked = remote.RemoteReranker().rerank("q", [{"content": "omitted"}, {"content": "scored"}])
    assert [result["content"] for result in ranked] == ["scored"]


# ---------------------------------------------------------------------------
# Review follow-ups: honest failures, dispatch boundaries, knowledge races.
# ---------------------------------------------------------------------------


def _knowledge_store(tmp_path):
    path = tmp_path / "knowledge.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE chunk (
            chunk_id TEXT PRIMARY KEY, doc_id TEXT, base_id TEXT, idx INTEGER,
            text TEXT, search_text TEXT, heading TEXT, context TEXT,
            embedding BLOB, embedding_model TEXT, fts_rowid INTEGER
        );
        CREATE VIRTUAL TABLE chunk_fts USING fts5(
            search_text, content='chunk', content_rowid='fts_rowid', tokenize='trigram'
        );
        """
    )
    conn.execute(
        "INSERT INTO chunk VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("doc", "doc", "base", 1, "服务端口 8080", "服务端口 8080", "", "", None, None, 1),
    )
    conn.execute("INSERT INTO chunk_fts(chunk_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()
    return path


def test_unknown_tool_is_an_error_but_tool_keyerror_is_not(server, monkeypatch):
    unknown = server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "no_such_tool", "arguments": {}}}
    )
    assert unknown["error"]["code"] == -32601

    def explode(_args):
        raise KeyError("internal")

    monkeypatch.setattr(server, "tool_memory_stats", explode)
    broken = call(server, "memory_stats", {})
    assert broken["isError"] is True
    assert "KeyError" in broken["content"][0]["text"]
    assert "error" not in broken


def test_configured_remote_reranker_failure_is_reported(monkeypatch, tmp_path):
    # A configured-but-failing backend must surface as a tool error; only the
    # absent adapter (before #833 ships) may degrade to unreranked results.
    monkeypatch.setattr("memsearch.mcp_server._auto_knowledge_db", lambda: "")
    srv = MCPServer(config=MemSearchConfig(), collection="test", knowledge_db=str(_knowledge_store(tmp_path)))
    try:
        fake = ModuleType("memsearch.remote_reranker")

        class Reranker:
            def __init__(self, **kwargs):
                pass

            def evaluate(self, query, documents):
                raise RuntimeError("Remote reranking failed (HTTP 401)")

        fake.RemoteReranker = Reranker
        monkeypatch.setitem(sys.modules, fake.__name__, fake)
        srv._cfg.reranker.model = "remote:fake"
        reply = srv.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "knowledge_search", "arguments": {"query": "8080"}},
            }
        )
        assert reply["result"]["isError"] is True
        assert "HTTP 401" in reply["result"]["content"][0]["text"]
    finally:
        srv.close()


def test_remote_adapter_absent_returns_fused_ranking(monkeypatch, tmp_path):
    monkeypatch.setattr("memsearch.mcp_server._auto_knowledge_db", lambda: "")
    srv = MCPServer(config=MemSearchConfig(), collection="test", knowledge_db=str(_knowledge_store(tmp_path)))
    try:
        monkeypatch.setitem(sys.modules, "memsearch.remote_reranker", None)
        srv._cfg.reranker.model = "remote:fake"
        reply = srv.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "knowledge_search", "arguments": {"query": "8080"}},
            }
        )
        assert reply["result"]["isError"] is False
        assert "服务端口 8080" in reply["result"]["content"][0]["text"]
    finally:
        srv.close()
