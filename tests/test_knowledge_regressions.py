"""Ranking and compatibility regressions using temporary SQLite stores."""

from __future__ import annotations

import array
import sqlite3
import sys

import pytest

from memsearch.knowledge_store import KnowledgeStore


@pytest.fixture
def knowledge(tmp_path):
    path = tmp_path / "knowledge.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE chunk (
            chunk_id TEXT PRIMARY KEY, doc_id TEXT, base_id TEXT, idx INTEGER,
            text TEXT, search_text TEXT, heading TEXT, context TEXT,
            embedding BLOB, embedding_model TEXT, fts_rowid INTEGER
        );
        CREATE VIRTUAL TABLE chunk_fts USING fts5(
            search_text, content='chunk', content_rowid='fts_rowid', tokenize='trigram'
        );
    """)
    for index, (cid, base, text, model, vector) in enumerate(
        [
            ("strong", "base", "needle needle needle", "openai:model-a", [1.0, 0.0, 0.0]),
            ("weak", "base", "filler " * 300 + "needle", "openai:model-b", [1.0, 0.0]),
            ("outside", "other", "needle needle", "openai:model-b", [1.0, 0.0, 0.0]),
        ],
        1,
    ):
        conn.execute(
            "INSERT INTO chunk VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (cid, cid, base, index, text, text, "", "", array.array("f", vector).tobytes(), model, index),
        )
    conn.execute("INSERT INTO chunk_fts(chunk_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()
    store = KnowledgeStore(path)
    yield store
    store.close()


def test_bm25_stronger_match_ranks_first(knowledge):
    hits = knowledge.search("needle", base_id="base", limit=2)
    assert [hit["chunk_id"] for hit in hits] == ["strong", "weak"]


def test_bm25_restricts_base_before_applying_limit(knowledge):
    hits = knowledge.search("needle", base_id="other", limit=1, candidates=1)
    assert [hit["chunk_id"] for hit in hits] == ["outside"]
    assert hits[0]["base_id"] == "other"


@pytest.mark.parametrize("use_numpy", [False, True])
def test_mixed_dimensions_preserve_compatible_hits(knowledge, monkeypatch, use_numpy):
    if use_numpy:
        pytest.importorskip("numpy")
    else:
        monkeypatch.setitem(sys.modules, "numpy", None)
    hits = knowledge.search("needle", base_id="base", limit=2, embed_fn=lambda texts: [[1.0, 0.0, 0.0]])
    by_id = {hit["chunk_id"]: hit for hit in hits}
    assert by_id["strong"]["dense_score"] == pytest.approx(1.0)
    assert by_id["weak"]["dense_score"] is None


def test_equal_total_blob_length_does_not_splice_vector_boundaries(knowledge):
    rows = [
        {"chunk_id": "two", "embedding": array.array("f", [1.0, 0.0]).tobytes()},
        {"chunk_id": "four", "embedding": array.array("f", [0.0, 0.0, 0.0, 1.0]).tobytes()},
    ]
    # Six floats can be reshaped to 2x3, but neither stored row is a 3D vector.
    assert knowledge._dense([[1.0, 0.0, 0.0]], rows) == {}


def test_same_dimension_different_models_are_not_compared(knowledge):
    hits = knowledge.search(
        "needle", limit=3, embed_fn=lambda texts: [[1.0, 0.0, 0.0]], embedding_model="openai:model-a"
    )
    by_id = {hit["chunk_id"]: hit for hit in hits}
    assert by_id["strong"]["dense_score"] == pytest.approx(1.0)
    assert by_id["outside"]["dense_score"] is None
    assert by_id["weak"]["dense_score"] is None


def test_omitted_rerank_candidate_cannot_beat_a_negative_score(knowledge):
    def rerank(query, documents):
        return [-0.5 if document.startswith("needle") else None for document in documents]

    hits = knowledge.search("needle", base_id="base", limit=2, rerank_fn=rerank)
    assert [hit["chunk_id"] for hit in hits] == ["strong"]
    assert hits[0]["rerank_score"] == -0.5


@pytest.mark.parametrize("scores", [[], [None, None]])
def test_empty_scoring_response_is_a_failure_not_no_match(knowledge, scores):
    with pytest.raises(RuntimeError, match="no scores"):
        knowledge.search("needle", base_id="base", rerank_fn=lambda query, docs: scores)


def test_unavailable_reranker_preserves_fused_ranking(knowledge):
    expected = knowledge.search("needle", base_id="base", limit=2)
    hits = knowledge.search("needle", base_id="base", limit=2, rerank_fn=lambda query, docs: None)
    assert hits == expected


@pytest.mark.parametrize(
    "scores",
    [
        [0.5],
        [0.5, 0.4, 0.3],
        (0.5, 0.4),
        [True, 0.5],
        ["0.5", 0.4],
        [float("nan"), 0.5],
        [float("inf"), 0.5],
    ],
)
def test_malformed_rerank_scores_are_not_silently_ignored(knowledge, scores):
    with pytest.raises(RuntimeError, match="score"):
        knowledge.search("needle", base_id="base", rerank_fn=lambda query, docs: scores)


def test_rerank_callback_failure_is_not_silently_ignored(knowledge):
    def fail(query, documents):
        raise RuntimeError("reranker failed")

    with pytest.raises(RuntimeError, match="reranker failed"):
        knowledge.search("needle", base_id="base", rerank_fn=fail)
