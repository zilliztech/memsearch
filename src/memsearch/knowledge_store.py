"""Read-only hybrid search over a DeepSeek Harness knowledge store.

The DeepSeek Harness knowledge plugin keeps its chunks in a SQLite
database (``~/.dsh/storages/knowledge-chunks.sqlite`` by default):

``chunk``
    ``chunk_id``, ``doc_id``, ``base_id``, ``idx``, ``text``, ``search_text``,
    ``heading``, ``context``, ``embedding`` (float32 blob, L2-normalised),
    ``embedding_model``, ``embedding_text_hash``, ``fts_rowid``, …
``chunk_fts``
    FTS5 table over ``search_text`` (``content='chunk'``), queried with
    ``bm25(chunk_fts)``.

This module reads that store and answers queries with the same recipe the
knowledge plugin uses: a dense vector scan fused with a BM25 ranking
(reciprocal rank fusion) and, when a reranker is available, a final
cross-encoder pass.

The database is opened read-only, so a running knowledge plugin is never
disturbed.  Nothing here is imported by the core library — it is only
reachable through the MCP server's optional ``knowledge_search`` tool.
"""

from __future__ import annotations

import array
import contextlib
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

#: RRF constant — the same value the knowledge plugin uses.
RRF_K = 60

EmbedFn = Callable[[list[str]], list[list[float]]]
RerankFn = Callable[[str, list[str]], list[float] | None]


class KnowledgeStore:
    """Hybrid search over a DSH knowledge store."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        if not self.path.exists():
            raise FileNotFoundError(f"knowledge store not found: {self.path}")
        self._conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=15)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        with contextlib.suppress(Exception):  # pragma: no cover - best effort
            self._conn.close()

    # ------------------------------------------------------------------

    def count(self, base_id: str | None = None) -> int:
        if base_id:
            row = self._conn.execute("SELECT COUNT(*) FROM chunk WHERE base_id = ?", (base_id,)).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM chunk").fetchone()
        return int(row[0]) if row else 0

    def _rows(self, base_id: str | None) -> list[sqlite3.Row]:
        if base_id:
            sql = (
                "SELECT chunk_id, doc_id, base_id, idx, text, heading, context, "
                "embedding, embedding_model FROM chunk WHERE base_id = ?"
            )
            return list(self._conn.execute(sql, (base_id,)))
        sql = "SELECT chunk_id, doc_id, base_id, idx, text, heading, context, embedding, embedding_model FROM chunk"
        return list(self._conn.execute(sql))

    def _bm25(self, query: str, limit: int = 50) -> dict[str, float]:
        """Return ``{chunk_id: bm25_score}`` for the query.

        The knowledge store indexes ``search_text`` with an FTS5
        **trigram** tokenizer, so a multi-word query has to be matched term
        by term: a single quoted phrase over the whole query only matches
        when the words appear in exactly that order and contiguously, which
        a natural-language question almost never does.  Each whitespace
        separated term is therefore quoted and OR-ed together.

        FTS5 returns a *negative* score, where more negative means a better
        match; the ranking below keeps that order.
        """
        cleaned = " ".join(query.split())
        if len(cleaned) < 2:
            return {}
        terms = [t for t in cleaned.split(" ") if len(t) >= 1]
        if not terms:
            return {}
        expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
        try:
            rows = self._conn.execute(
                "SELECT f.rowid AS rowid, bm25(chunk_fts) AS score "
                "FROM chunk_fts f WHERE chunk_fts MATCH ? ORDER BY score LIMIT ?",
                (expression, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        if not rows:
            return {}
        ids: dict[str, str] = {}
        for row in self._conn.execute("SELECT chunk_id, fts_rowid FROM chunk"):
            ids[str(row["fts_rowid"])] = row["chunk_id"]
        out: dict[str, float] = {}
        for row in rows:
            chunk_id = ids.get(str(row["rowid"]))
            if chunk_id:
                out[chunk_id] = float(row["score"])
        return out

    def _dense(self, vectors: list[list[float]], rows: list[sqlite3.Row]) -> dict[str, float]:
        """Cosine similarity of the query vector against every stored vector.

        The stored blobs are L2-normalised float32, so the dot product is
        the cosine similarity.  numpy is used when available — the pure
        Python fallback is an order of magnitude slower on a few thousand
        chunks of 2560 dimensions.
        """
        if not vectors or not rows:
            return {}
        query = vectors[0]
        qn = sum(x * x for x in query) ** 0.5 or 1.0

        blobs: list[tuple[str, bytes]] = []
        for row in rows:
            blob = row["embedding"]
            if blob is None:
                continue
            blobs.append((row["chunk_id"], blob))
        if not blobs:
            return {}

        try:
            import numpy as np

            matrix = np.frombuffer(b"".join(b for _id, b in blobs), dtype=np.float32)
            matrix = matrix.reshape(len(blobs), -1)
            q = np.asarray(query, dtype=np.float32)
            if matrix.shape[1] != q.shape[0]:
                return {}
            scores = matrix @ q / qn
            return {chunk_id: float(score) for (chunk_id, _b), score in zip(blobs, scores, strict=False)}
        except ImportError:
            pass

        out: dict[str, float] = {}
        for chunk_id, blob in blobs:
            stored = array.array("f")
            stored.frombytes(blob)
            if len(stored) != len(query):
                continue
            dot = sum(a * b for a, b in zip(query, stored, strict=False))
            out[chunk_id] = dot / qn
        return out

    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        base_id: str | None = None,
        embed_fn: EmbedFn | None = None,
        rerank_fn: RerankFn | None = None,
        candidates: int = 50,
        rerank_candidates: int = 15,
    ) -> list[dict[str, Any]]:
        """Return the best matching chunks.

        Parameters
        ----------
        query:
            The user query.
        limit:
            Maximum number of hits to return.
        base_id:
            Restrict the search to one knowledge base.
        embed_fn:
            Callable embedding a list of texts — used for the dense half of
            the hybrid search.  Without it only BM25 runs.
        rerank_fn:
            Callable ``(query, documents) -> scores`` used for the final
            cross-encoder pass.  Without it the fused ranking is returned.
        candidates:
            How many hits of each retriever take part in the fusion.
        rerank_candidates:
            How many fused hits are sent to the cross-encoder.  A remote
            reranker costs one request per batch, so only the head of the
            list is worth paying for.
        """
        rows = self._rows(base_id)
        if not rows:
            return []
        by_id = {row["chunk_id"]: row for row in rows}

        dense: dict[str, float] = {}
        if embed_fn is not None:
            try:
                vectors = embed_fn([query])
            except Exception:
                vectors = []
            if vectors:
                dense = self._dense(vectors, rows)

        bm25 = self._bm25(query, limit=candidates)

        # Reciprocal rank fusion over the two rankings.  Only the head of
        # each ranking takes part — fusing every dense hit would drown the
        # (much more selective) BM25 ranking.
        fused: dict[str, float] = {}
        for ranking in (dense, bm25):
            top = sorted(ranking.items(), key=lambda kv: -kv[1])[:candidates]
            for rank, (chunk_id, _score) in enumerate(top):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)

        if not fused:
            return []

        ordered = sorted(fused.items(), key=lambda kv: -kv[1])[: max(candidates, limit)]
        hits = []
        for chunk_id, score in ordered:
            row = by_id[chunk_id]
            hits.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": row["doc_id"],
                    "base_id": row["base_id"],
                    "heading": row["heading"],
                    "text": row["text"],
                    "context": row["context"],
                    "score": score,
                    "dense_score": dense.get(chunk_id),
                    "bm25_score": bm25.get(chunk_id),
                }
            )

        if rerank_fn is not None and hits:
            head = hits[: max(limit, min(rerank_candidates, len(hits)))]
            try:
                scores = rerank_fn(query, [h["text"] for h in head])
            except Exception:
                scores = None
            if scores:
                for hit, score in zip(head, scores, strict=False):
                    hit["rerank_score"] = float(score)
                head.sort(key=lambda h: -h["rerank_score"])
                return head[:limit]

        return hits[:limit]
