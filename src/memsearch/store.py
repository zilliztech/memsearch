"""Milvus vector storage layer using MilvusClient API."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class MilvusStore:
    """Thin wrapper around ``pymilvus.MilvusClient`` for chunk storage."""

    DEFAULT_COLLECTION = "memsearch_chunks"

    def __init__(
        self,
        uri: str = "~/.memsearch/milvus.db",
        *,
        token: str | None = None,
        collection: str = DEFAULT_COLLECTION,
        dimension: int = 1536,
    ) -> None:
        from pymilvus import MilvusClient

        resolved = str(Path(uri).expanduser()) if not uri.startswith(("http", "tcp")) else uri
        if not uri.startswith(("http", "tcp")):
            Path(resolved).parent.mkdir(parents=True, exist_ok=True)
        connect_kwargs: dict[str, Any] = {"uri": resolved}
        if token:
            connect_kwargs["token"] = token
        self._client = MilvusClient(**connect_kwargs)
        self._collection = collection
        self._dimension = dimension
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if self._client.has_collection(self._collection):
            return
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field(
            field_name="chunk_hash", datatype=21, max_length=64, is_primary=True,
        )  # VARCHAR primary key
        schema.add_field(
            field_name="embedding",
            datatype=101,  # FLOAT_VECTOR
            dim=self._dimension,
        )
        schema.add_field(field_name="content", datatype=21, max_length=65535)  # VARCHAR
        schema.add_field(field_name="source", datatype=21, max_length=1024)  # VARCHAR
        schema.add_field(field_name="heading", datatype=21, max_length=1024)  # VARCHAR
        schema.add_field(field_name="heading_level", datatype=5)  # INT64
        schema.add_field(field_name="start_line", datatype=5)  # INT64
        schema.add_field(field_name="end_line", datatype=5)  # INT64

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="FLAT",
            metric_type="COSINE",
        )
        self._client.create_collection(
            collection_name=self._collection,
            schema=schema,
            index_params=index_params,
        )

    def existing_hashes(self, hashes: list[str]) -> set[str]:
        """Return the subset of *hashes* that already exist in the collection."""
        if not hashes:
            return set()
        hash_list = ", ".join(f'"{h}"' for h in hashes)
        results = self._client.query(
            collection_name=self._collection,
            filter=f"chunk_hash in [{hash_list}]",
            output_fields=["chunk_hash"],
        )
        return {r["chunk_hash"] for r in results}

    def upsert(self, chunks: list[dict[str, Any]]) -> int:
        """Insert or update chunks (keyed by ``chunk_hash`` primary key)."""
        if not chunks:
            return 0
        result = self._client.upsert(
            collection_name=self._collection,
            data=chunks,
        )
        return result.get("upsert_count", len(chunks)) if isinstance(result, dict) else len(chunks)

    def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 10,
        filter_expr: str = "",
    ) -> list[dict[str, Any]]:
        """Semantic search returning top-k results."""
        kwargs: dict[str, Any] = {
            "collection_name": self._collection,
            "data": [query_embedding],
            "limit": top_k,
            "output_fields": self._QUERY_FIELDS,
        }
        if filter_expr:
            kwargs["filter"] = filter_expr
        results = self._client.search(**kwargs)
        if not results or not results[0]:
            return []
        return [
            {**hit["entity"], "score": hit["distance"]}
            for hit in results[0]
        ]

    _QUERY_FIELDS = [
        "content", "source", "heading", "chunk_hash",
        "heading_level", "start_line", "end_line",
    ]

    def query(self, *, filter_expr: str = "") -> list[dict[str, Any]]:
        """Retrieve chunks by scalar filter (no vector needed)."""
        kwargs: dict[str, Any] = {
            "collection_name": self._collection,
            "output_fields": self._QUERY_FIELDS,
            "filter": filter_expr if filter_expr else 'chunk_hash != ""',
        }
        return self._client.query(**kwargs)

    def hashes_by_source(self, source: str) -> set[str]:
        """Return all chunk_hash values for a given source file."""
        results = self._client.query(
            collection_name=self._collection,
            filter=f'source == "{source}"',
            output_fields=["chunk_hash"],
        )
        return {r["chunk_hash"] for r in results}

    def indexed_sources(self) -> set[str]:
        """Return all distinct source values in the collection."""
        results = self._client.query(
            collection_name=self._collection,
            filter='chunk_hash != ""',
            output_fields=["source"],
        )
        return {r["source"] for r in results}

    def delete_by_source(self, source: str) -> None:
        """Delete all chunks from a given source file."""
        self._client.delete(
            collection_name=self._collection,
            filter=f'source == "{source}"',
        )

    def delete_by_hashes(self, hashes: list[str]) -> None:
        """Delete chunks by their content hashes (primary keys)."""
        if not hashes:
            return
        self._client.delete(
            collection_name=self._collection,
            ids=hashes,
        )

    def count(self) -> int:
        """Return total number of stored chunks."""
        stats = self._client.get_collection_stats(self._collection)
        return stats.get("row_count", 0)

    def drop(self) -> None:
        """Drop the entire collection."""
        if self._client.has_collection(self._collection):
            self._client.drop_collection(self._collection)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MilvusStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
