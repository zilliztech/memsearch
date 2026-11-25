"""Unit tests for the Voyage AI reranker backend."""

from __future__ import annotations

import logging
import sys
import threading
import types

import pytest

from memsearch import reranker


def _install_fake_voyageai(monkeypatch, *, record: dict, order: list[int]):
    """Install a fake ``voyageai`` module whose rerank() returns *order*."""
    voyageai_module = types.ModuleType("voyageai")

    class FakeClient:
        def rerank(self, query, documents, *, model, top_k=None):
            record["query"] = query
            record["documents"] = documents
            record["model"] = model
            record["top_k"] = top_k
            record["thread"] = threading.current_thread()
            selected = order if top_k is None else order[:top_k]
            return types.SimpleNamespace(
                results=[
                    types.SimpleNamespace(index=idx, relevance_score=1.0 - position / 10)
                    for position, idx in enumerate(selected)
                ]
            )

    voyageai_module.Client = FakeClient
    monkeypatch.setitem(sys.modules, "voyageai", voyageai_module)
    monkeypatch.setattr(reranker, "_voyage_client", None)


def _results(n: int = 3) -> list[dict]:
    return [{"content": f"chunk {i}", "source": f"/tmp/{i}.md"} for i in range(n)]


def test_voyage_prefix_reranks_via_the_api(monkeypatch):
    record: dict = {}
    _install_fake_voyageai(monkeypatch, record=record, order=[2, 0, 1])

    out = reranker.rerank("why did it fail", _results(), model_name="voyage:rerank-3")

    assert record["model"] == "rerank-3"
    assert record["query"] == "why did it fail"
    assert record["documents"] == ["chunk 0", "chunk 1", "chunk 2"]
    # API order is authoritative; the original result dicts are preserved.
    assert [r["content"] for r in out] == ["chunk 2", "chunk 0", "chunk 1"]
    assert [r["source"] for r in out] == ["/tmp/2.md", "/tmp/0.md", "/tmp/1.md"]
    assert out[0]["score"] > out[1]["score"] > out[2]["score"]


def test_voyage_passes_top_k_through(monkeypatch):
    record: dict = {}
    _install_fake_voyageai(monkeypatch, record=record, order=[2, 0, 1])

    out = reranker.rerank("q", _results(), model_name="voyage:rerank-3", top_k=2)

    assert record["top_k"] == 2
    assert [r["content"] for r in out] == ["chunk 2", "chunk 0"]


def test_voyage_top_k_zero_requests_all(monkeypatch):
    record: dict = {}
    _install_fake_voyageai(monkeypatch, record=record, order=[1, 0, 2])

    out = reranker.rerank("q", _results(), model_name="voyage:rerank-3", top_k=0)

    assert record["top_k"] is None
    assert len(out) == 3


def test_voyage_skips_when_voyageai_is_not_installed(monkeypatch):
    # A None entry in sys.modules makes `import voyageai` raise ImportError.
    monkeypatch.setitem(sys.modules, "voyageai", None)
    monkeypatch.setattr(reranker, "_voyage_client", None)
    original = _results()

    out = reranker.rerank("q", original, model_name="voyage:rerank-3")

    assert out == original


def test_local_model_does_not_reach_voyage(monkeypatch):
    record: dict = {}
    _install_fake_voyageai(monkeypatch, record=record, order=[2, 1, 0])
    monkeypatch.setattr(reranker, "_detect_backend", lambda: "none")
    original = _results()

    out = reranker.rerank("q", original, model_name=reranker.DEFAULT_RERANKER)

    assert record == {}, "a local model id must not call the Voyage API"
    assert out == original


def test_empty_results_short_circuit(monkeypatch):
    record: dict = {}
    _install_fake_voyageai(monkeypatch, record=record, order=[])

    assert reranker.rerank("q", [], model_name="voyage:rerank-3") == []
    assert record == {}


# ======================================================================
# Degradation paths must still honour top_k
#
# MemSearch.search() over-fetches top_k * 3 candidates whenever reranking is
# enabled, expecting rerank() to narrow them back down. A path that skips
# reranking and hands the candidate list straight back would therefore return
# up to three times the requested result count.
# ======================================================================


def _install_failing_voyageai(monkeypatch, exc_name: str = "AuthenticationError"):
    """Install a fake ``voyageai`` whose rerank() raises a Voyage error.

    Mirrors the real SDK: the client constructs happily without a key and the
    failure surfaces at rerank() time as ``voyageai.error.AuthenticationError``,
    a subclass of ``voyageai.error.VoyageError``.
    """
    voyageai_module = types.ModuleType("voyageai")
    error_module = types.ModuleType("voyageai.error")

    class VoyageError(Exception):
        pass

    class AuthenticationError(VoyageError):
        pass

    error_module.VoyageError = VoyageError
    error_module.AuthenticationError = AuthenticationError

    raised = RuntimeError("boom") if exc_name == "RuntimeError" else AuthenticationError("no api key")

    class FailingClient:
        def rerank(self, query, documents, *, model, top_k=None):
            raise raised

    voyageai_module.Client = FailingClient
    voyageai_module.error = error_module
    monkeypatch.setitem(sys.modules, "voyageai", voyageai_module)
    monkeypatch.setitem(sys.modules, "voyageai.error", error_module)
    monkeypatch.setattr(reranker, "_voyage_client", None)


def test_missing_voyageai_still_honours_top_k(monkeypatch):
    monkeypatch.setitem(sys.modules, "voyageai", None)
    monkeypatch.setattr(reranker, "_voyage_client", None)

    out = reranker.rerank("q", _results(9), model_name="voyage:rerank-3", top_k=3)

    assert [r["content"] for r in out] == ["chunk 0", "chunk 1", "chunk 2"]


def test_missing_local_backend_still_honours_top_k(monkeypatch):
    monkeypatch.setattr(reranker, "_detect_backend", lambda: "none")

    out = reranker.rerank("q", _results(9), model_name=reranker.DEFAULT_RERANKER, top_k=3)

    assert [r["content"] for r in out] == ["chunk 0", "chunk 1", "chunk 2"]


def test_degraded_top_k_zero_still_returns_every_candidate(monkeypatch):
    monkeypatch.setattr(reranker, "_detect_backend", lambda: "none")
    original = _results(9)

    assert reranker.rerank("q", original, model_name=reranker.DEFAULT_RERANKER, top_k=0) == original


# ======================================================================
# A Voyage API error degrades like a missing package, rather than crashing
# ======================================================================


def test_voyage_api_error_degrades_to_unranked_results(monkeypatch, caplog):
    _install_failing_voyageai(monkeypatch)
    original = _results()

    with caplog.at_level(logging.WARNING, logger="memsearch.reranker"):
        out = reranker.rerank("q", original, model_name="voyage:rerank-3")

    assert out == original
    assert "AuthenticationError" in caplog.text


def test_voyage_api_error_still_honours_top_k(monkeypatch):
    _install_failing_voyageai(monkeypatch)

    out = reranker.rerank("q", _results(9), model_name="voyage:rerank-3", top_k=3)

    assert [r["content"] for r in out] == ["chunk 0", "chunk 1", "chunk 2"]


def test_non_voyage_exception_still_propagates(monkeypatch):
    _install_failing_voyageai(monkeypatch, exc_name="RuntimeError")

    with pytest.raises(RuntimeError, match="boom"):
        reranker.rerank("q", _results(), model_name="voyage:rerank-3")


# ======================================================================
# The search() over-fetch interplay the unit tests above stand in for
# ======================================================================


class _FakeEmbedder:
    dimension = 4

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]


class _FakeStore:
    """Returns exactly as many chunks as it was asked for."""

    def __init__(self) -> None:
        self.requested_top_k: int | None = None

    def _require_collection(self) -> None:
        pass

    def search(self, embedding, *, query_text, top_k, filter_expr):
        self.requested_top_k = top_k
        return _results(top_k)


@pytest.mark.asyncio
async def test_search_does_not_over_deliver_when_reranking_degrades(monkeypatch):
    from memsearch.core import MemSearch

    # A None entry in sys.modules makes `import voyageai` raise ImportError.
    monkeypatch.setitem(sys.modules, "voyageai", None)
    monkeypatch.setattr(reranker, "_voyage_client", None)

    ms = MemSearch.__new__(MemSearch)
    ms._embedder = _FakeEmbedder()
    ms._store = _FakeStore()
    ms._reranker_model = "voyage:rerank-3"

    out = await ms.search("q", top_k=10)

    assert ms._store.requested_top_k == 30, "search() over-fetches candidates for the reranker"
    assert len(out) == 10, "the caller asked for 10 results and must not get the raw candidate list"


@pytest.mark.asyncio
async def test_search_runs_voyage_off_the_event_loop(monkeypatch):
    from memsearch.core import MemSearch

    record: dict = {}
    _install_fake_voyageai(monkeypatch, record=record, order=[2, 0, 1])
    ms = MemSearch.__new__(MemSearch)
    ms._embedder = _FakeEmbedder()
    ms._store = _FakeStore()
    ms._reranker_model = "voyage:rerank-3"

    await ms.search("q", top_k=1)

    assert record["thread"] is not threading.main_thread(), "a blocking HTTP call must not stall the event loop"
