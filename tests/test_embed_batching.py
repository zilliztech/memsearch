"""Tests for embedding batch-size handling.

Uses a fake embedding provider to verify that large chunk lists are
split into batches that respect the provider's batch_size limit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memsearch.chunker import Chunk
from memsearch.core import MemSearch
from memsearch.embeddings.utils import batched_embed
from memsearch.store import MilvusStore


# -- batched_embed utility tests --


class _Recorder:
    """Records call sizes for embed assertions."""

    def __init__(self, dim: int = 4) -> None:
        self.call_sizes: list[int] = []
        self._dim = dim

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        self.call_sizes.append(len(texts))
        return [[0.0] * self._dim for _ in texts]


@pytest.mark.asyncio
async def test_batched_embed_splits():
    rec = _Recorder()
    result = await batched_embed(list("abcdefghij"), rec, batch_size=4)
    assert len(result) == 10
    assert rec.call_sizes == [4, 4, 2]


@pytest.mark.asyncio
async def test_batched_embed_single_batch():
    rec = _Recorder()
    result = await batched_embed(list("abc"), rec, batch_size=4)
    assert len(result) == 3
    # Under the limit — should be a single call, not split
    assert rec.call_sizes == [3]


@pytest.mark.asyncio
async def test_batched_embed_exact():
    rec = _Recorder()
    result = await batched_embed(list("abcd"), rec, batch_size=4)
    assert len(result) == 4
    assert rec.call_sizes == [4]


@pytest.mark.asyncio
async def test_batched_embed_empty():
    rec = _Recorder()
    result = await batched_embed([], rec, batch_size=4)
    assert result == []
    assert rec.call_sizes == []


@pytest.mark.asyncio
async def test_batched_embed_invalid_batch_size():
    rec = _Recorder()
    with pytest.raises(ValueError, match="batch_size must be >= 1"):
        await batched_embed(["a"], rec, batch_size=0)


# -- Integration test: MemSearch._embed_and_store with fake embedder --


class FakeEmbedder:
    """Fake embedding provider with configurable batch_size."""

    def __init__(self, *, batch_size: int = 4, dim: int = 4) -> None:
        self._batch_size = batch_size
        self._dim = dim
        self.call_sizes: list[int] = []

    @property
    def model_name(self) -> str:
        return "fake"

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from memsearch.embeddings.utils import batched_embed

        return await batched_embed(texts, self._embed_batch, self._batch_size)

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.call_sizes.append(len(texts))
        return [[0.0] * self._dim for _ in texts]


@pytest.fixture
def mem_with_fake(tmp_path: Path):
    """MemSearch instance wired to a FakeEmbedder with batch_size=4."""
    fake = FakeEmbedder(batch_size=4, dim=4)
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
async def test_embed_and_store_batching(mem_with_fake):
    ms, fake = mem_with_fake
    chunks = _make_chunks(10)  # 10 chunks, batch size 4
    n = await ms._embed_and_store(chunks)
    assert n == 10
    # Should have been split into 3 batches: 4 + 4 + 2
    assert fake.call_sizes == [4, 4, 2]


@pytest.mark.asyncio
async def test_embed_and_store_under_limit(mem_with_fake):
    ms, fake = mem_with_fake
    chunks = _make_chunks(3)
    n = await ms._embed_and_store(chunks)
    assert n == 3
    assert fake.call_sizes == [3]


@pytest.mark.asyncio
async def test_embed_and_store_empty(mem_with_fake):
    ms, fake = mem_with_fake
    n = await ms._embed_and_store([])
    assert n == 0
    assert fake.call_sizes == []
