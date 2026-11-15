"""Contract tests for remote reranking without network calls."""

import copy
import http.client
import io
import json
import threading
import urllib.error
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from memsearch.core import MemSearch
from memsearch.jev_reranker import JevReranker
from memsearch.reranker import rerank


def response(scores):
    return {
        "model": "jev-1.13.0",
        "answers": {f"d{i}": {"type": "noul", "noul": score} for i, score in enumerate(scores)},
        "usage": {"input_tokens": 123, "output_tokens": 12},
    }


@pytest.mark.parametrize("model", ["jev-latest", "jev-1.13.0"])
def test_batched_request_preserves_content_and_metadata(monkeypatch, model):
    candidates = [
        {"content": "long memory " * 2000, "source": "a.md", "score": 9},
        {"content": "second", "source": "b.md", "chunk_id": "b"},
        {"content": "third", "source": "c.md"},
    ]
    before = copy.deepcopy(candidates)
    calls = []

    def open_request(request, timeout):
        calls.append((request, timeout))
        return io.BytesIO(json.dumps(response([0.2, 0.8, 0.8])).encode())

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr("urllib.request.urlopen", open_request)
    ranked = rerank("question", candidates, model_name=f"jev:{model}", top_k=2)
    assert [r["source"] for r in ranked] == ["b.md", "c.md"]
    assert ranked[0]["chunk_id"] == "b"
    assert candidates == before
    assert len(calls) == 1
    request, timeout = calls[0]
    payload = json.loads(request.data)
    assert payload["model"] == model
    assert payload["state"] == {"query_excerpt": "question"}
    assert len(payload["questions"]) == 3
    assert payload["questions"]["d0"]["instructions"].endswith(candidates[0]["content"])
    assert set(payload["questions"]["d0"]["criteria"]) == {"true", "false"}
    assert request.get_header("Authorization") == "Bearer test-key"
    assert timeout == 60


def test_empty_candidates_need_no_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert JevReranker().rerank("query", []) == []


def test_missing_key_fails_explicitly(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
        JevReranker().rerank("query", [{"content": "text"}])


@pytest.mark.parametrize("score", [None, True, "0.5", float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_scores_fail(score):
    with pytest.raises(ValueError):
        JevReranker.scores(response([score]), 1)


def test_missing_and_extra_answers_fail():
    for result in [response([]), response([0.1, 0.2])]:
        with pytest.raises(ValueError, match="missing or unexpected"):
            JevReranker.scores(result, 1)


def test_wrong_type_fails():
    result = response([0.5])
    result["answers"]["d0"]["type"] = "choice"
    with pytest.raises(ValueError, match="answer type"):
        JevReranker.scores(result, 1)


@pytest.mark.parametrize("code", [401, 429, 503])
def test_http_errors_do_not_leak_body_or_fall_back(monkeypatch, code):
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://api.typesafe.ai", code, "private payload", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(RuntimeError, match=f"HTTP {code}") as exc:
        JevReranker(api_key="secret").rerank("query", [{"content": "private text"}])
    assert "private" not in str(exc.value)
    assert "secret" not in str(exc.value)


def test_local_model_still_uses_local_backend(monkeypatch):
    candidates = [{"content": "text"}]
    monkeypatch.setattr("memsearch.reranker._detect_backend", lambda: "onnx")
    seen = []

    def local(query, results, model, top_k):
        seen.append((query, model, top_k))
        return results

    monkeypatch.setattr("memsearch.reranker._rerank_onnx", local)
    assert rerank("query", candidates, model_name="local-model", top_k=1) == candidates
    assert seen == [("query", "local-model", 1)]


def test_disconnected_remote_request_fails_explicitly(monkeypatch):
    def disconnect(*args, **kwargs):
        raise http.client.RemoteDisconnected("Remote end closed connection")

    monkeypatch.setattr("urllib.request.urlopen", disconnect)
    with pytest.raises(RuntimeError, match="failed or timed out"):
        JevReranker(api_key="test-key").rerank("query", [{"content": "text"}])


def test_invalid_configuration():
    with pytest.raises(ValueError):
        JevReranker(model="")
    with pytest.raises(ValueError):
        JevReranker(timeout=0)
    with pytest.raises(ValueError):
        JevReranker().rerank("q", [], top_k=-1)


@pytest.mark.asyncio
async def test_search_fetches_extra_candidates_and_returns_jev_top_k(monkeypatch):
    candidates = [{"content": f"passage {i}", "chunk_id": str(i)} for i in range(6)]
    store = Mock()
    store.search.return_value = candidates
    mem = MemSearch.__new__(MemSearch)
    mem._embedder = SimpleNamespace(embed=AsyncMock(return_value=[[0.1, 0.2]]))
    mem._store = store
    mem._reranker_model = "jev:jev-1.13.0"
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    def remote_request(*args, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        return io.BytesIO(json.dumps(response([0.1, 0.2, 0.3, 0.9, 0.4, 0.8])).encode())

    monkeypatch.setattr("urllib.request.urlopen", remote_request)
    results = await mem.search("question", top_k=2)
    assert [r["chunk_id"] for r in results] == ["3", "5"]
    assert store.search.call_args.kwargs["top_k"] == 6


def test_default_alias_preserves_resolved_response_version(monkeypatch):
    seen = []

    def open_request(request, timeout):
        seen.append(json.loads(request.data)["model"])
        return io.BytesIO(json.dumps(response([0.8])).encode())

    monkeypatch.setattr("urllib.request.urlopen", open_request)
    result = JevReranker(api_key="test-key").evaluate("question", ["memory"])
    assert seen == ["jev-latest"]
    assert result["model"] == "jev-1.13.0"
