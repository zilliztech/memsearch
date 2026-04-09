"""Tests for the Milvus store."""

from pathlib import Path

import pytest

from memsearch.store import MilvusStore, _bm25_query_text


@pytest.fixture
def store(tmp_path: Path):
    db = tmp_path / "test_milvus.db"
    s = MilvusStore(uri=str(db), dimension=4)
    yield s
    s.close()


def test_upsert_and_search(store: MilvusStore):
    chunks = [
        {
            "embedding": [1.0, 0.0, 0.0, 0.0],
            "content": "Hello world",
            "source": "test.md",
            "heading": "Intro",
            "chunk_hash": "h1",
            "heading_level": 1,
            "start_line": 1,
            "end_line": 5,
        },
        {
            "embedding": [0.0, 1.0, 0.0, 0.0],
            "content": "Goodbye world",
            "source": "test.md",
            "heading": "Outro",
            "chunk_hash": "h2",
            "heading_level": 1,
            "start_line": 6,
            "end_line": 10,
        },
    ]
    n = store.upsert(chunks)
    assert n == 2

    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=1)
    assert len(results) >= 1
    assert results[0]["content"] == "Hello world"


def test_delete_by_source(store: MilvusStore):
    chunks = [
        {
            "embedding": [1.0, 0.0, 0.0, 0.0],
            "content": "A",
            "source": "a.md",
            "heading": "",
            "chunk_hash": "ha",
            "heading_level": 0,
            "start_line": 1,
            "end_line": 1,
        },
        {
            "embedding": [0.0, 1.0, 0.0, 0.0],
            "content": "B",
            "source": "b.md",
            "heading": "",
            "chunk_hash": "hb",
            "heading_level": 0,
            "start_line": 1,
            "end_line": 1,
        },
    ]
    store.upsert(chunks)
    store.delete_by_source("a.md")
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=10)
    sources = {r["source"] for r in results}
    assert "a.md" not in sources


def test_upsert_is_idempotent(store: MilvusStore):
    chunk = {
        "embedding": [1.0, 0.0, 0.0, 0.0],
        "content": "Same content",
        "source": "test.md",
        "heading": "",
        "chunk_hash": "same_hash",
        "heading_level": 0,
        "start_line": 1,
        "end_line": 1,
        "doc_type": "markdown",
    }
    store.upsert([chunk])
    store.upsert([chunk])
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=10)
    hashes = [r["chunk_hash"] for r in results]
    assert hashes.count("same_hash") == 1


def test_bm25_query_text_skips_numeric_only_queries():
    assert _bm25_query_text("111123") == ""
    assert _bm25_query_text("   42-7 ") == ""
    assert _bm25_query_text("Redis 111123") == "Redis 111123"


def test_search_numeric_only_query_does_not_raise(store: MilvusStore):
    chunk = {
        "embedding": [1.0, 0.0, 0.0, 0.0],
        "content": "Version 111123 release checklist",
        "source": "test.md",
        "heading": "Release",
        "chunk_hash": "h_numeric",
        "heading_level": 1,
        "start_line": 1,
        "end_line": 3,
    }
    store.upsert([chunk])

    results = store.search([1.0, 0.0, 0.0, 0.0], query_text="111123", top_k=5)

    assert isinstance(results, list)


def test_hybrid_search(store: MilvusStore):
    chunks = [
        {
            "embedding": [1.0, 0.0, 0.0, 0.0],
            "content": "Redis caching with TTL and LRU eviction policy",
            "source": "test.md",
            "heading": "Caching",
            "chunk_hash": "h_redis",
            "heading_level": 1,
            "start_line": 1,
            "end_line": 5,
        },
        {
            "embedding": [0.0, 1.0, 0.0, 0.0],
            "content": "PostgreSQL database migration and schema changes",
            "source": "test.md",
            "heading": "Database",
            "chunk_hash": "h_pg",
            "heading_level": 1,
            "start_line": 6,
            "end_line": 10,
        },
    ]
    store.upsert(chunks)

    # Hybrid search: BM25 should boost the Redis result for keyword "Redis"
    results = store.search(
        [0.5, 0.5, 0.0, 0.0],  # ambiguous dense vector
        query_text="Redis caching",
        top_k=2,
    )
    assert len(results) >= 1
    assert results[0]["content"].startswith("Redis")


def test_dimension_mismatch(tmp_path: Path):
    db = str(tmp_path / "dim_test.db")
    # Create collection with dim=4
    s1 = MilvusStore(uri=db, dimension=4)
    s1.close()
    # Re-open with dim=8 — should raise ValueError
    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        MilvusStore(uri=db, dimension=8)


def test_drop(store: MilvusStore):
    chunk = {
        "embedding": [1.0, 0.0, 0.0, 0.0],
        "content": "Will be dropped",
        "source": "test.md",
        "heading": "",
        "chunk_hash": "hd",
        "heading_level": 0,
        "start_line": 1,
        "end_line": 1,
        "doc_type": "markdown",
    }
    store.upsert([chunk])
    store.drop()
    # After drop, collection is gone — re-ensure should work
    store._ensure_collection()
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=10)
    assert len(results) == 0


def test_collection_description(tmp_path: Path):
    """Collection should store the description when provided."""
    db = str(tmp_path / "desc_test.db")
    desc = "myproject | openai/text-embedding-3-small"
    s = MilvusStore(uri=db, dimension=4, description=desc)
    info = s._client.describe_collection(s._collection)
    assert info.get("description") == desc
    s.close()


def test_collection_description_empty_by_default(tmp_path: Path):
    """Collection should have empty description when not provided."""
    db = str(tmp_path / "desc_default_test.db")
    s = MilvusStore(uri=db, dimension=4)
    info = s._client.describe_collection(s._collection)
    assert info.get("description") == ""
    s.close()
