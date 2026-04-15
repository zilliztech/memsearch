from __future__ import annotations

import pytest
from pymilvus.exceptions import MilvusException

from memsearch.store import MilvusStore


class _MissingCollectionClient:
    def query(self, **_kwargs):
        raise MilvusException(code=100, message="collection not found")


def test_query_returns_empty_when_collection_is_missing() -> None:
    store = MilvusStore.__new__(MilvusStore)
    store._client = _MissingCollectionClient()
    store._collection = "missing"

    assert store.query() == []


class _OtherFailureClient:
    def query(self, **_kwargs):
        raise MilvusException(code=500, message="boom")


def test_query_reraises_non_missing_collection_errors() -> None:
    store = MilvusStore.__new__(MilvusStore)
    store._client = _OtherFailureClient()
    store._collection = "broken"

    with pytest.raises(MilvusException, match="boom"):
        store.query()
