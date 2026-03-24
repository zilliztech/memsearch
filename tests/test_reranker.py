"""Tests for cross-encoder reranker."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def test_reranker_sorts_by_cross_encoder_score():
    """Reranker should re-sort results by cross-encoder score."""
    from memsearch.reranker import rerank

    results = [
        {"content": "Unrelated document about cooking", "score": 0.95, "source": "a.md"},
        {"content": "Python is a programming language", "score": 0.90, "source": "b.md"},
        {"content": "The Python standard library includes os and sys", "score": 0.85, "source": "c.md"},
    ]

    query = "What modules are in the Python standard library?"
    reranked = rerank(query, results, model_name="cross-encoder/ms-marco-MiniLM-L-6-v2", top_k=2)

    assert len(reranked) == 2
    assert reranked[0]["source"] == "c.md"
    assert "score" in reranked[0]


def test_reranker_returns_empty_for_empty_results():
    """Reranker should handle empty input gracefully."""
    from memsearch.reranker import rerank

    assert rerank("query", [], model_name="cross-encoder/ms-marco-MiniLM-L-6-v2") == []


def test_reranker_preserves_metadata():
    """Reranker should keep all metadata fields from original results."""
    from memsearch.reranker import rerank

    results = [
        {
            "content": "Test content about Python libraries",
            "score": 0.9,
            "source": "test.md",
            "heading": "Section 1",
            "chunk_hash": "abc123",
            "start_line": 1,
            "end_line": 10,
        },
    ]

    reranked = rerank("test query", results, model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
    assert reranked[0]["source"] == "test.md"
    assert reranked[0]["heading"] == "Section 1"
    assert reranked[0]["chunk_hash"] == "abc123"
    assert reranked[0]["start_line"] == 1
    assert reranked[0]["end_line"] == 10


def test_reranker_top_k_zero_returns_all():
    """top_k=0 should return all results, re-sorted."""
    from memsearch.reranker import rerank

    results = [
        {"content": "Doc A about cats", "score": 0.9, "source": "a.md"},
        {"content": "Doc B about dogs and cats", "score": 0.8, "source": "b.md"},
        {"content": "Doc C about fish", "score": 0.7, "source": "c.md"},
    ]

    reranked = rerank("cats", results, model_name="cross-encoder/ms-marco-MiniLM-L-6-v2", top_k=0)
    assert len(reranked) == 3


def test_reranker_replaces_score():
    """Cross-encoder score should replace the original hybrid search score."""
    from memsearch.reranker import rerank

    results = [{"content": "test doc", "score": 0.999, "source": "a.md"}]
    reranked = rerank("test", results, model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
    # Cross-encoder score will be different from the original 0.999
    assert reranked[0]["score"] != 0.999


def test_reranker_caches_model():
    """Calling rerank twice with same model should reuse the cached instance."""
    import memsearch.reranker as mod

    # Reset cache
    mod._cached_model = None
    mod._cached_model_name = ""

    results = [{"content": "test", "score": 0.5, "source": "a.md"}]

    rerank = mod.rerank
    rerank("q1", results, model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
    first_model = mod._cached_model

    rerank("q2", results, model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
    assert mod._cached_model is first_model


def test_reranker_config_empty_disables():
    """Empty reranker model in config means reranking is disabled."""
    from memsearch.config import RerankerConfig

    cfg = RerankerConfig(model="")
    assert cfg.model == ""


def test_reranker_config_default_enabled():
    """Default reranker config should have the GTE model enabled."""
    from memsearch.config import RerankerConfig

    cfg = RerankerConfig()
    assert cfg.model == "Alibaba-NLP/gte-reranker-modernbert-base"


def test_reranker_config_in_memsearch_config():
    """RerankerConfig should be part of MemSearchConfig."""
    from memsearch.config import MemSearchConfig

    cfg = MemSearchConfig()
    assert hasattr(cfg, "reranker")
    assert cfg.reranker.model == "Alibaba-NLP/gte-reranker-modernbert-base"


def test_reranker_wired_in_core_search():
    """MemSearch.search() should apply reranking when reranker_model is set."""
    import memsearch.reranker as reranker_mod
    from memsearch.core import MemSearch

    mock_embedder = MagicMock()
    mock_embedder.dimension = 768
    mock_embedder.embed = AsyncMock(return_value=[[0.1] * 768])

    mock_store = MagicMock()
    mock_store.search = MagicMock(
        return_value=[
            {"content": "doc A", "score": 0.9, "source": "a.md"},
            {"content": "doc B", "score": 0.8, "source": "b.md"},
        ]
    )

    mock_ce = MagicMock()
    mock_ce.predict = MagicMock(return_value=[0.3, 0.9])  # doc B ranked higher

    # Reset reranker cache and inject mock
    reranker_mod._cached_model = mock_ce
    reranker_mod._cached_model_name = "test-model"

    with (
        patch("memsearch.core.get_provider", return_value=mock_embedder),
        patch("memsearch.core.MilvusStore", return_value=mock_store),
    ):
        ms = MemSearch(reranker_model="test-model")
        results = asyncio.run(ms.search("test query", top_k=2))

    # Results should be re-sorted: doc B (0.9) before doc A (0.3)
    assert results[0]["source"] == "b.md"
    assert results[1]["source"] == "a.md"

    # Cleanup
    reranker_mod._cached_model = None
    reranker_mod._cached_model_name = ""


def test_core_search_skips_reranker_when_empty():
    """MemSearch.search() should skip reranking when reranker_model is empty."""
    from memsearch.core import MemSearch

    mock_embedder = MagicMock()
    mock_embedder.dimension = 768
    mock_embedder.embed = AsyncMock(return_value=[[0.1] * 768])

    mock_store = MagicMock()
    mock_store.search = MagicMock(
        return_value=[{"content": "doc A", "score": 0.9, "source": "a.md"}]
    )

    with (
        patch("memsearch.core.get_provider", return_value=mock_embedder),
        patch("memsearch.core.MilvusStore", return_value=mock_store),
    ):
        ms = MemSearch(reranker_model="")
        results = asyncio.run(ms.search("test query", top_k=1))

    # Original results returned unchanged (no reranking)
    assert results[0]["score"] == 0.9


def test_core_search_fetches_more_candidates_for_reranker():
    """When reranker is enabled, search should fetch 3x candidates."""
    from memsearch.core import MemSearch

    mock_embedder = MagicMock()
    mock_embedder.dimension = 768
    mock_embedder.embed = AsyncMock(return_value=[[0.1] * 768])

    mock_store = MagicMock()
    mock_store.search = MagicMock(return_value=[])

    with (
        patch("memsearch.core.get_provider", return_value=mock_embedder),
        patch("memsearch.core.MilvusStore", return_value=mock_store),
    ):
        ms = MemSearch(reranker_model="some-model")
        asyncio.run(ms.search("test", top_k=5))

    # Should have called store.search with top_k=15 (3x5)
    call_kwargs = mock_store.search.call_args
    assert call_kwargs.kwargs.get("top_k") == 15 or call_kwargs[1].get("top_k") == 15
