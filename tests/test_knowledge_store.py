"""Tests for the read-only knowledge store reader."""

from __future__ import annotations

import array
import sqlite3
from pathlib import Path

import pytest

from memsearch.knowledge_store import KnowledgeStore

SCHEMA = """
CREATE TABLE chunk (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT,
    base_id TEXT,
    idx INTEGER,
    text TEXT,
    search_text TEXT,
    heading TEXT,
    context TEXT,
    embedding BLOB,
    embedding_model TEXT,
    fts_rowid INTEGER
);
CREATE VIRTUAL TABLE chunk_fts USING fts5(
    search_text, content='chunk', content_rowid='fts_rowid', tokenize='trigram'
);
"""


def _vector(values: list[float]) -> bytes:
    arr = array.array("f", values)
    return arr.tobytes()


@pytest.fixture
def store(tmp_path: Path):
    db = tmp_path / "knowledge-chunks.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    rows = [
        (
            "c1",
            "doc-a",
            "base1",
            0,
            "校机的向量服务跑在 8080 端口。",
            "校机的向量服务跑在 8080 端口",
            "端口",
            "",
            _vector([1.0, 0.0, 0.0]),
            "openai:Qwen3-Embedding-4B",
        ),
        (
            "c2",
            "doc-b",
            "base1",
            0,
            "重排服务跑在 8081 端口。",
            "重排服务跑在 8081 端口",
            "端口",
            "",
            _vector([0.0, 1.0, 0.0]),
            "openai:Qwen3-Embedding-4B",
        ),
    ]
    for i, row in enumerate(rows, start=1):
        conn.execute(
            "INSERT INTO chunk (chunk_id, doc_id, base_id, idx, text, search_text, heading, "
            "context, embedding, embedding_model, fts_rowid) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (*row, i),
        )
    # external-content FTS tables are not populated by the base insert
    conn.execute("INSERT INTO chunk_fts(chunk_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()

    s = KnowledgeStore(db)
    yield s
    s.close()


def test_count_and_rows(store: KnowledgeStore) -> None:
    assert store.count() == 2
    assert store.count(base_id="base1") == 2
    assert store.count(base_id="other") == 0


def test_bm25_finds_the_matching_chunk(store: KnowledgeStore) -> None:
    scores = store._bm25("8081 端口")
    assert scores
    assert any(chunk_id == "c2" for chunk_id in scores)


def test_bm25_matches_terms_individually_not_as_one_phrase(store: KnowledgeStore) -> None:
    # a trigram index cannot match a whole question as a single phrase
    assert store._bm25("8081 端口") != {}
    # ... but it does match the individual terms
    assert "c1" in store._bm25("8080")
    assert "c2" in store._bm25("8081")


def test_dense_scan_ranks_by_cosine(store: KnowledgeStore) -> None:
    rows = store._rows(None)
    dense = store._dense([[1.0, 0.0, 0.0]], rows)
    assert dense["c1"] == pytest.approx(1.0, abs=1e-5)
    assert dense["c2"] == pytest.approx(0.0, abs=1e-5)


def test_search_fuses_dense_and_bm25(store: KnowledgeStore) -> None:
    hits = store.search(
        "端口",
        limit=2,
        embed_fn=lambda texts: [[0.0, 1.0, 0.0]],
    )
    assert len(hits) == 2
    assert hits[0]["chunk_id"] == "c2"  # dense favours c2, bm25 favours c2 as well
    assert hits[0]["score"] > hits[1]["score"]


def test_search_without_embedding_falls_back_to_bm25(store: KnowledgeStore) -> None:
    hits = store.search("8080", limit=2)
    assert hits
    assert hits[0]["chunk_id"] == "c1"


def test_rerank_scores_decide_the_order(store: KnowledgeStore) -> None:
    def rerank(query: str, documents: list[str]) -> list[float]:
        return [1.0 if "8080" in doc else 0.1 for doc in documents]

    hits = store.search(
        "端口",
        limit=2,
        embed_fn=lambda texts: [[0.0, 1.0, 0.0]],
        rerank_fn=rerank,
    )
    assert hits[0]["chunk_id"] == "c1"
    assert hits[0]["rerank_score"] == pytest.approx(1.0)


def test_missing_database_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        KnowledgeStore(tmp_path / "nope.sqlite")


def test_store_is_opened_read_only(store: KnowledgeStore, tmp_path: Path) -> None:
    with pytest.raises(sqlite3.OperationalError):
        store._conn.execute("DELETE FROM chunk")
