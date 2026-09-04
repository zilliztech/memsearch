"""Unit tests for the Voyage AI reranker backend."""

from __future__ import annotations

import sys
import types

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


def test_voyage_provider_reranks_via_the_api(monkeypatch):
    record: dict = {}
    _install_fake_voyageai(monkeypatch, record=record, order=[2, 0, 1])

    out = reranker.rerank("why did it fail", _results(), model_name="rerank-3", provider="voyage")

    assert record["model"] == "rerank-3"
    assert record["query"] == "why did it fail"
    assert record["documents"] == ["chunk 0", "chunk 1", "chunk 2"]
    # API order is authoritative; the original result dicts are preserved.
    assert [r["content"] for r in out] == ["chunk 2", "chunk 0", "chunk 1"]
    assert [r["source"] for r in out] == ["/tmp/2.md", "/tmp/0.md", "/tmp/1.md"]
    assert out[0]["score"] > out[1]["score"] > out[2]["score"]


def test_voyage_provider_falls_back_to_default_model(monkeypatch):
    record: dict = {}
    _install_fake_voyageai(monkeypatch, record=record, order=[0, 1, 2])

    reranker.rerank("q", _results(), model_name="", provider="voyage")

    assert record["model"] == reranker.DEFAULT_VOYAGE_RERANKER


def test_voyage_provider_passes_top_k_through(monkeypatch):
    record: dict = {}
    _install_fake_voyageai(monkeypatch, record=record, order=[2, 0, 1])

    out = reranker.rerank("q", _results(), model_name="rerank-3", top_k=2, provider="voyage")

    assert record["top_k"] == 2
    assert [r["content"] for r in out] == ["chunk 2", "chunk 0"]


def test_voyage_provider_top_k_zero_requests_all(monkeypatch):
    record: dict = {}
    _install_fake_voyageai(monkeypatch, record=record, order=[1, 0, 2])

    out = reranker.rerank("q", _results(), model_name="rerank-3", top_k=0, provider="voyage")

    assert record["top_k"] is None
    assert len(out) == 3


def test_voyage_provider_skips_when_voyageai_is_not_installed(monkeypatch):
    # A None entry in sys.modules makes `import voyageai` raise ImportError.
    monkeypatch.setitem(sys.modules, "voyageai", None)
    monkeypatch.setattr(reranker, "_voyage_client", None)
    original = _results()

    out = reranker.rerank("q", original, model_name="rerank-3", provider="voyage")

    assert out == original


def test_unknown_provider_skips_reranking(monkeypatch):
    record: dict = {}
    _install_fake_voyageai(monkeypatch, record=record, order=[2, 1, 0])
    original = _results()

    out = reranker.rerank("q", original, model_name="rerank-3", provider="nope")

    assert out == original
    assert record == {}, "an unknown provider must not reach any backend"


def test_local_provider_does_not_reach_voyage(monkeypatch):
    record: dict = {}
    _install_fake_voyageai(monkeypatch, record=record, order=[2, 1, 0])
    monkeypatch.setattr(reranker, "_detect_backend", lambda: "none")
    original = _results()

    out = reranker.rerank("q", original, model_name=reranker.DEFAULT_RERANKER)

    assert record == {}, "the default local provider must not call the Voyage API"
    assert out == original


def test_empty_results_short_circuit(monkeypatch):
    record: dict = {}
    _install_fake_voyageai(monkeypatch, record=record, order=[])

    assert reranker.rerank("q", [], model_name="rerank-3", provider="voyage") == []
    assert record == {}
