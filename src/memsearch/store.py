"""Milvus vector storage layer using MilvusClient API."""

from __future__ import annotations

import importlib.metadata
import logging
import operator
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


class CollectionNotFoundError(RuntimeError):
    """Raised when a read targets a collection that has not been created."""

    def __init__(self, collection: str, uri: str) -> None:
        super().__init__(
            f"Collection '{collection}' does not exist at '{uri}'. "
            "Run 'memsearch index <path> ...' to create it, or verify --collection and --milvus-uri."
        )


def _escape_filter_value(value: str) -> str:
    """Escape backslashes and double quotes for Milvus filter expressions."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _milvus_lite_major() -> int | None:
    """Major version of the installed milvus-lite, or None if it cannot be read."""
    try:
        return int(importlib.metadata.version("milvus-lite").split(".")[0])
    except (importlib.metadata.PackageNotFoundError, ValueError):
        return None


def _non_negative_integer(value: Any) -> int:
    """Return an integer-protocol value without accepting bools or truncation."""
    if isinstance(value, bool):
        raise ValueError("boolean values are not row counts")
    try:
        result = operator.index(value)
    except TypeError as exc:
        raise ValueError("row counts must be integers") from exc
    if result < 0:
        raise ValueError("row counts must be non-negative")
    return result


def _local_open_error_message(exc: Exception, resolved: str, major: int | None) -> str:
    """Describe a failed local Milvus Lite open without asserting an unproven cause.

    Milvus Lite 3.x stores a database as a directory, so a plain file under a 3.x
    runtime is a layout mismatch worth reporting, but the path being a file does not
    prove Milvus Lite 2.x wrote it: a mistyped URI reaches the same branch. Every
    failure is reported with the underlying error and no remediation that discards
    data. pymilvus reports a database held by another process as a bare
    ConnectionConfigException carrying no cause, so the reason is not recoverable
    here and must not be guessed at.
    """
    if major is not None and major >= 3 and Path(resolved).is_file():
        return (
            f"Could not open the local Milvus database at {resolved}: {exc}. Milvus Lite {major}.x "
            f"stores a database as a directory, but this path is a file. If it is a database from "
            f"Milvus Lite 2.x, move it aside and rebuild the index with 'memsearch index'. "
            f"Otherwise check the configured URI, or use Milvus Server via Docker or Zilliz Cloud."
        )
    return (
        f"Could not open the local Milvus database at {resolved}: {exc}. This can happen if another "
        "process already has the database open, if file permissions are wrong, or if the file is "
        "damaged. Close other processes using this database and verify that the path is writable. "
        "If the problem continues, preserve the database and inspect the application logs before "
        "attempting recovery."
    )


class MilvusStore:
    """Thin wrapper around ``pymilvus.MilvusClient`` for chunk storage.

    Collections use both dense vector and BM25 sparse vector fields,
    with hybrid search (semantic + keyword, RRF reranking) by default.
    """

    DEFAULT_COLLECTION = "memsearch_chunks"

    def __init__(
        self,
        uri: str = "~/.memsearch/milvus.db",
        *,
        token: str | None = None,
        collection: str = DEFAULT_COLLECTION,
        dimension: int | None = 1536,
        description: str = "",
        _create_if_missing: bool = False,
    ) -> None:
        is_local = not uri.startswith(("http", "tcp", "unix:"))
        resolved = str(Path(uri).expanduser()) if is_local else uri
        self._connect_kwargs: dict[str, Any] = {"uri": resolved}
        if token:
            self._connect_kwargs["token"] = token
        self._client: Any | None = None
        self._is_lite = is_local
        self._resolved_uri = resolved
        self._collection = collection
        self._dimension = dimension
        self._description = description
        self._collection_exists = False

        may_create = _create_if_missing and dimension is not None
        if may_create or not is_local or Path(resolved).exists():
            self._connect(create_local_storage=may_create)
            self._ensure_collection(create_if_missing=may_create)

    def _connect(self, *, create_local_storage: bool) -> None:
        """Connect to Milvus, creating a local parent only for an authorized write."""
        if self._client is not None:
            return
        if self._is_lite and create_local_storage:
            Path(self._resolved_uri).parent.mkdir(parents=True, exist_ok=True)

        from pymilvus import MilvusClient

        try:
            self._client = MilvusClient(**self._connect_kwargs)
        except Exception as exc:
            if self._is_lite:
                raise RuntimeError(_local_open_error_message(exc, self._resolved_uri, _milvus_lite_major())) from exc
            raise

    def _ensure_collection(self, *, create_if_missing: bool = True) -> None:
        client = self._connected_client()
        if client.has_collection(self._collection):
            self._collection_exists = True
            self._check_dimension()
            self._load_collection()
            return

        self._collection_exists = False
        if not create_if_missing:
            return
        if self._dimension is None:
            raise ValueError("Cannot create a collection without an embedding dimension")

        from pymilvus import DataType, Function, FunctionType

        # Description is optional backend metadata. Indexing and search never
        # depend on it because some Milvus Lite versions do not return it.
        schema = client.create_schema(
            enable_dynamic_field=True,
            description=self._description,
        )
        schema.add_field(field_name="chunk_hash", datatype=DataType.VARCHAR, max_length=64, is_primary=True)
        schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=self._dimension)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=65535, enable_analyzer=True)
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field(field_name="source", datatype=DataType.VARCHAR, max_length=1024)
        schema.add_field(field_name="heading", datatype=DataType.VARCHAR, max_length=1024)
        schema.add_field(field_name="heading_level", datatype=DataType.INT64)
        schema.add_field(field_name="start_line", datatype=DataType.INT64)
        schema.add_field(field_name="end_line", datatype=DataType.INT64)
        schema.add_function(
            Function(
                name="bm25_fn",
                function_type=FunctionType.BM25,
                input_field_names=["content"],
                output_field_names=["sparse_vector"],
            )
        )

        index_params = client.prepare_index_params()
        index_params.add_index(field_name="embedding", index_type="FLAT", metric_type="COSINE")
        index_params.add_index(field_name="sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")

        client.create_collection(
            collection_name=self._collection,
            schema=schema,
            index_params=index_params,
        )
        self._collection_exists = True
        self._load_collection()

    def _ensure_collection_for_write(self) -> None:
        """Create the collection lazily at the first authorized write boundary."""
        if self._collection_exists:
            return
        if self._dimension is None:
            raise CollectionNotFoundError(self._collection, self._resolved_uri)
        self._connect(create_local_storage=True)
        self._ensure_collection(create_if_missing=True)

    def _require_collection(self) -> None:
        """Fail a read before any backend operation when the collection is absent."""
        if not self._collection_exists:
            raise CollectionNotFoundError(self._collection, self._resolved_uri)

    def _connected_client(self) -> Any:
        if self._client is None:
            raise CollectionNotFoundError(self._collection, self._resolved_uri)
        return self._client

    def _load_collection(self) -> None:
        """Load the collection before query/search operations."""
        client = self._connected_client()
        try:
            client.load_collection(collection_name=self._collection)
        except TypeError:
            client.load_collection(self._collection)

    def _check_dimension(self) -> None:
        """Verify that the existing collection's embedding dimension matches."""
        if self._dimension is None:
            return  # no dimension specified — skip check (read-only mode)
        info = self._connected_client().describe_collection(self._collection)
        for field in info.get("fields", []):
            if field.get("name") == "embedding":
                existing_dim = field.get("params", {}).get("dim")
                if existing_dim is not None and int(existing_dim) != self._dimension:
                    raise ValueError(
                        f"Embedding dimension mismatch: collection '{self._collection}' "
                        f"has dim={existing_dim} but the current embedding provider "
                        f"outputs dim={self._dimension}. "
                        f"Run 'memsearch reset --yes' to drop the collection and re-index, "
                        f"or use a different --milvus-uri / --collection."
                    )
                break

    def upsert(self, chunks: list[dict[str, Any]]) -> int:
        """Insert or update chunks (keyed by ``chunk_hash`` primary key).

        ``sparse_vector`` is auto-generated by the BM25 Function from
        ``content`` — do NOT include it in chunk dicts.
        """
        if not chunks:
            return 0
        self._ensure_collection_for_write()
        result = self._connected_client().upsert(
            collection_name=self._collection,
            data=chunks,
        )
        return result.get("upsert_count", len(chunks)) if isinstance(result, dict) else len(chunks)

    def search(
        self,
        query_embedding: list[float],
        *,
        query_text: str = "",
        top_k: int = 10,
        filter_expr: str = "",
    ) -> list[dict[str, Any]]:
        """Hybrid search: dense vector + BM25 full-text with RRF reranking."""
        from pymilvus import AnnSearchRequest, RRFRanker

        self._require_collection()
        client = self._connected_client()

        # BM25 crashes on empty collections (avgdl=0 → NaN). See #306. Remote
        # Milvus metadata omits growing rows, so confirm zero metadata counts
        # with a strong query before treating the collection as empty.
        if self._collection_is_empty():
            return []

        req_kwargs: dict[str, Any] = {}
        if filter_expr:
            req_kwargs["expr"] = filter_expr

        dense_req = AnnSearchRequest(
            data=[query_embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {}},
            limit=top_k,
            **req_kwargs,
        )

        bm25_req = AnnSearchRequest(
            data=[query_text] if query_text else [""],
            anns_field="sparse_vector",
            param={"metric_type": "BM25"},
            limit=top_k,
            **req_kwargs,
        )

        reqs = [dense_req, bm25_req]
        rrf_k = 60
        results = client.hybrid_search(
            collection_name=self._collection,
            reqs=reqs,
            ranker=RRFRanker(k=rrf_k),
            limit=top_k,
            output_fields=self._QUERY_FIELDS,
        )

        if not results or not results[0]:
            return []
        # Normalize RRF scores to [0, 1].
        # Theoretical max = num_retrievers / (k + 1), when a result ranks #1 in every retriever.
        max_rrf = len(reqs) / (rrf_k + 1)
        return [{**hit["entity"], "score": hit["distance"] / max_rrf} for hit in results[0]]

    def _collection_is_empty(self) -> bool:
        """Return whether no sealed or growing rows exist in the collection."""
        self._require_collection()
        client = self._connected_client()
        stats = client.get_collection_stats(self._collection)
        try:
            metadata_count = _non_negative_integer(stats["row_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Milvus returned an invalid metadata count for collection '{self._collection}': {stats!r}"
            ) from exc
        if metadata_count > 0:
            return False

        results = client.query(
            collection_name=self._collection,
            filter="",
            output_fields=["count(*)"],
            consistency_level="Strong",
        )
        if not isinstance(results, list) or len(results) != 1:
            raise RuntimeError(
                f"Milvus returned an invalid count response for collection '{self._collection}': {results!r}; "
                "expected exactly one aggregate row"
            )

        try:
            row_count = _non_negative_integer(results[0]["count(*)"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Milvus returned an invalid count response for collection '{self._collection}': {results!r}"
            ) from exc
        return row_count == 0

    _QUERY_FIELDS: ClassVar[list[str]] = [
        "content",
        "source",
        "heading",
        "chunk_hash",
        "heading_level",
        "start_line",
        "end_line",
    ]

    def query(self, *, filter_expr: str = "") -> list[dict[str, Any]]:
        """Retrieve chunks by scalar filter (no vector needed)."""
        self._require_collection()
        kwargs: dict[str, Any] = {
            "collection_name": self._collection,
            "output_fields": self._QUERY_FIELDS,
            "filter": filter_expr if filter_expr else 'chunk_hash != ""',
        }
        return self._connected_client().query(**kwargs)

    def hashes_by_source(self, source: str) -> set[str]:
        """Return all chunk_hash values for a given source file."""
        self._require_collection()
        escaped = _escape_filter_value(source)
        results = self._connected_client().query(
            collection_name=self._collection,
            filter=f'source == "{escaped}"',
            output_fields=["chunk_hash"],
        )
        return {r["chunk_hash"] for r in results}

    def indexed_sources(self) -> set[str]:
        """Return all distinct source values in the collection."""
        self._require_collection()
        results = self._connected_client().query(
            collection_name=self._collection,
            filter='chunk_hash != ""',
            output_fields=["source"],
        )
        return {r["source"] for r in results}

    def delete_by_source(self, source: str) -> None:
        """Delete all chunks from a given source file."""
        self._require_collection()
        escaped = _escape_filter_value(source)
        self._connected_client().delete(
            collection_name=self._collection,
            filter=f'source == "{escaped}"',
        )

    def delete_by_hashes(self, hashes: list[str]) -> None:
        """Delete chunks by their content hashes (primary keys)."""
        if not hashes:
            return
        self._require_collection()
        self._connected_client().delete(
            collection_name=self._collection,
            ids=hashes,
        )

    def count(self) -> int:
        """Return the metadata row count, which may lag on Milvus Server."""
        self._require_collection()
        stats = self._connected_client().get_collection_stats(self._collection)
        return stats.get("row_count", 0)

    def drop(self) -> None:
        """Drop the entire collection."""
        if self._client is not None and self._client.has_collection(self._collection):
            self._client.drop_collection(self._collection)
            self._collection_exists = False

    def close(self) -> None:
        if self._client is None:
            return
        self._client.close()
        # Milvus Lite: release the server process to free the db file lock.
        # Without this, the milvus_lite subprocess outlives the parent and
        # blocks subsequent CLI invocations from opening the same .db file.
        if self._is_lite:
            try:
                from milvus_lite.server_manager import server_manager_instance

                server_manager_instance.release_server(self._resolved_uri)
            except Exception:
                pass

    def __enter__(self) -> MilvusStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
