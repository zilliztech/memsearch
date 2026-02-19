"""Tests for embedding batch-size handling in _embed_and_store().

Uses a fake embedding provider to verify that large chunk lists are
split into batches that respect the provider's max_batch_size limit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memsearch.chunker import Chunk
from memsearch.core import MemSearch
from memsearch.store import MilvusStore


class FakeEmbedder:
    """Fake embedding provider that records batch sizes."""

    def __init__(self, *, max_batch: int = 4, dim: int = 4) -> None:
        self._max_batch = max_batch
        self._dim = dim
        self.call_sizes: list[int] = []

    @property
    def model_name(self) -> str:
        return "fake"

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def max_batch_size(self) -> int:
        return self._max_batch

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if len(texts) > self._max_batch:
            raise ValueError(
                f"Received {len(texts)} texts, max is {self._max_batch}"
            )
        self.call_sizes.append(len(texts))
        return [[0.0] * self._dim for _ in texts]


@pytest.fixture
def mem_with_fake(tmp_path: Path):
    """MemSearch instance wired to a FakeEmbedder with max_batch_size=4."""
    fake = FakeEmbedder(max_batch=4, dim=4)
    ms = MemSearch.__new__(MemSearch)
    ms._paths = []
    ms._max_chunk_size = 1500
    ms._overlap_lines = 2
    ms._embedder = fake
    ms._store = MilvusStore(uri=str(tmp_path / "test.db"), dimension=fake.dimension)
    yield ms, fake
    ms.close()


def _make_chunks(n: int) -> list[Chunk]:
    return [
        Chunk(
            content=f"chunk {i}",
            source="test.md",
            heading="",
            heading_level=0,
            start_line=i,
            end_line=i,
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_batching_splits_large_requests(mem_with_fake):
    ms, fake = mem_with_fake
    chunks = _make_chunks(10)  # 10 chunks, batch size 4
    n = await ms._embed_and_store(chunks)
    assert n == 10
    # Should have been split into 3 batches: 4 + 4 + 2
    assert fake.call_sizes == [4, 4, 2]


@pytest.mark.asyncio
async def test_batching_single_batch_under_limit(mem_with_fake):
    ms, fake = mem_with_fake
    chunks = _make_chunks(3)  # 3 chunks, batch size 4
    n = await ms._embed_and_store(chunks)
    assert n == 3
    assert fake.call_sizes == [3]


@pytest.mark.asyncio
async def test_batching_exact_batch_size(mem_with_fake):
    ms, fake = mem_with_fake
    chunks = _make_chunks(4)  # exactly batch size
    n = await ms._embed_and_store(chunks)
    assert n == 4
    assert fake.call_sizes == [4]


@pytest.mark.asyncio
async def test_batching_empty_chunks(mem_with_fake):
    ms, fake = mem_with_fake
    n = await ms._embed_and_store([])
    assert n == 0
    assert fake.call_sizes == []
