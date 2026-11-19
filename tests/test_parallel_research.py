"""The runnable research path uses MCP over HTTP, then the public memory API."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("mcp", reason="Install memsearch[research] to test the research example")

spec = importlib.util.spec_from_file_location(
    "parallel_research", Path(__file__).parents[1] / "examples" / "parallel_research.py"
)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


@pytest.fixture
def mcp_server(monkeypatch):
    requests = []
    state = {"fetch_errors": [], "tools": ["web_search", "web_fetch"], "tool_error": False}

    async def respond(request):
        requests.append(request)
        message = json.loads(request.content)
        method = message["method"]
        if "id" not in message:
            return httpx.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fixture", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": [{"name": name, "inputSchema": {"type": "object"}} for name in state["tools"]]}
        elif method == "tools/call":
            name = message["params"]["name"]
            data = {
                "results": [
                    {
                        "url": "https://example.org/" + name,
                        "title": "Hybrid search",
                        "excerpts": ["Dense vectors and BM25 retrieve complementary results."],
                    }
                ],
                "session_id": "fixture-session",
            }
            if name == "web_fetch":
                data["errors"] = state["fetch_errors"]
            result = {
                "content": [{"type": "text", "text": json.dumps(data)}],
                "structuredContent": data,
                "isError": state["tool_error"],
            }
        else:
            raise AssertionError(method)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    original_client = httpx.AsyncClient

    def client(**kwargs):
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(example.httpx, "AsyncClient", client)
    return requests, state


async def test_research_http_to_markdown_to_memory(mcp_server, monkeypatch, tmp_path, capsys):
    requests, _ = mcp_server
    seen = {}

    class Memory:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            seen["closed"] = True

        async def index_with_report(self):
            pages = list(seen["paths"][0].glob("*.md"))
            assert len(pages) == 2
            seen["notes"] = [p.read_text() for p in pages]
            assert all("Source: https://example.org/" in note for note in seen["notes"])
            return SimpleNamespace(failed_files=[])

        async def search(self, query, *, top_k):
            assert query == "Milvus hybrid search" and top_k == 3
            return [{"source": "research.md", "content": seen["notes"][0]}]

    monkeypatch.setattr(example, "MemSearch", Memory)
    await example.research("Milvus hybrid search", tmp_path, ["https://example.org/web_fetch"])
    assert seen["embedding_provider"] == "onnx"
    assert seen["milvus_uri"] == str(tmp_path / "research.db")
    assert seen["collection"] == "parallel_research"
    assert seen["closed"]
    assert "BM25" in capsys.readouterr().out
    for request in requests:
        assert str(request.url) == example.MCP_URL
        assert request.headers["User-Agent"] == example.USER_AGENT
        assert "authorization" not in request.headers
    request_count = len(requests)
    await example.research("Milvus hybrid search", tmp_path, [], recall_only=True)
    assert len(requests) == request_count
    calls = [json.loads(r.content) for r in requests if json.loads(r.content)["method"] == "tools/call"]
    assert [c["params"]["name"] for c in calls] == ["web_search", "web_fetch"]
    assert calls[1]["params"]["arguments"] == {
        "urls": ["https://example.org/web_fetch"],
        "session_id": "fixture-session",
    }


async def test_fetch_failure_does_not_write_notes(mcp_server, tmp_path):
    _, state = mcp_server
    state["fetch_errors"] = [{"url": "https://example.org/missing", "error_type": "not_found"}]
    with pytest.raises(Exception, match="unhandled errors") as error:
        await example.research("hybrid search", tmp_path, ["https://example.org/missing"])
    assert "Page fetching failed" in str(error.value.exceptions)
    assert not (tmp_path / "pages").exists()


async def test_missing_tool_and_remote_tool_error(mcp_server):
    _, state = mcp_server
    state["tools"] = ["web_search"]
    with pytest.raises(Exception) as error:
        await example.collect_pages("hybrid search", ["https://example.org/"])
    assert "missing tools" in str(error.value.exceptions)
    state["tool_error"] = True
    with pytest.raises(Exception) as error:
        await example.collect_pages("hybrid search", [])
    assert "web_search failed" in str(error.value.exceptions)


def test_source_snapshot_uses_safe_stable_filename(tmp_path):
    page = {"url": "https://example.org/../../outside", "title": "A\nTitle", "excerpts": ["first"]}
    example.save_pages([page], tmp_path)
    page["excerpts"] = ["updated"]
    example.save_pages([page], tmp_path)
    notes = list(tmp_path.glob("*.md"))
    assert len(notes) == 1
    assert notes[0].read_text() == "# A Title\n\nSource: https://example.org/../../outside\n\nupdated\n"


async def test_recall_only_does_not_contact_mcp(monkeypatch, tmp_path):
    async def unexpected(*args):
        raise AssertionError("local recall must not contact MCP")

    monkeypatch.setattr(example, "collect_pages", unexpected)
    with pytest.raises(RuntimeError, match="No saved research"):
        await example.research("hybrid search", tmp_path, [], recall_only=True)
