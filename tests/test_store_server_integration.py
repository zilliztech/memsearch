"""Controlled Milvus Server coverage for growing-row search visibility.

Run this test explicitly against an isolated server. It is skipped unless
``MEMSEARCH_TEST_MILVUS_URI`` is set. The test creates and removes only
collections under ``MEMSEARCH_TEST_COLLECTION_PREFIX``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator

import pytest

from memsearch.store import MilvusStore

SERVER_URI = os.environ.get("MEMSEARCH_TEST_MILVUS_URI", "")
COLLECTION_PREFIX = os.environ.get("MEMSEARCH_TEST_COLLECTION_PREFIX", f"memsearch_it_{uuid.uuid4().hex[:12]}")

pytestmark = pytest.mark.skipif(not SERVER_URI, reason="MEMSEARCH_TEST_MILVUS_URI is not set")


def _row(chunk_hash: str, content: str, vector: list[float]) -> dict[str, object]:
    return {
        "embedding": vector,
        "content": content,
        "source": f"{chunk_hash}.md",
        "heading": "Integration",
        "chunk_hash": chunk_hash,
        "heading_level": 1,
        "start_line": 1,
        "end_line": 1,
    }


def _strong_count(store: MilvusStore) -> int:
    result = store._client.query(
        collection_name=store._collection,
        filter="",
        output_fields=["count(*)"],
        consistency_level="Strong",
    )
    return int(result[0]["count(*)"]) if result else 0


@pytest.fixture
def server_stores() -> Iterator[Callable[[str], MilvusStore]]:
    stores: list[MilvusStore] = []

    def create(suffix: str) -> MilvusStore:
        store = MilvusStore(
            uri=SERVER_URI,
            collection=f"{COLLECTION_PREFIX}_{suffix}",
            dimension=4,
            _create_if_missing=True,
        )
        stores.append(store)
        return store

    yield create

    if stores:
        client = stores[-1]._client
        try:
            for store in reversed(stores):
                if client.has_collection(store._collection):
                    client.drop_collection(store._collection)
        finally:
            stores[-1].close()


def test_server_empty_growing_sealed_and_mixed_visibility(server_stores):
    empty = server_stores("empty")
    assert empty.count() == 0
    assert _strong_count(empty) == 0
    assert empty.search([1.0, 0.0, 0.0, 0.0], query_text="empty") == []

    growing = server_stores("growing")
    assert growing.upsert([_row("growing", "growing row visibility", [1.0, 0.0, 0.0, 0.0])]) == 1
    assert growing.count() == 0, "The controlled server must keep the row in a growing segment"
    assert _strong_count(growing) == 1
    assert [result["chunk_hash"] for result in growing.search([1.0, 0.0, 0.0, 0.0], query_text="growing")] == [
        "growing"
    ]

    sealed = server_stores("sealed")
    assert sealed.upsert([_row("sealed", "sealed row visibility", [1.0, 0.0, 0.0, 0.0])]) == 1
    sealed._client.flush(sealed._collection)
    assert sealed.count() == 1
    assert _strong_count(sealed) == 1
    assert [result["chunk_hash"] for result in sealed.search([1.0, 0.0, 0.0, 0.0], query_text="sealed")] == ["sealed"]

    mixed = server_stores("mixed")
    assert mixed.upsert([_row("mixed_sealed", "mixed sealed row", [1.0, 0.0, 0.0, 0.0])]) == 1
    mixed._client.flush(mixed._collection)
    assert mixed.upsert([_row("mixed_growing", "mixed growing row", [0.9, 0.1, 0.0, 0.0])]) == 1
    assert mixed.count() == 1
    assert _strong_count(mixed) == 2
    assert {result["chunk_hash"] for result in mixed.search([1.0, 0.0, 0.0, 0.0], query_text="mixed")} == {
        "mixed_sealed",
        "mixed_growing",
    }
