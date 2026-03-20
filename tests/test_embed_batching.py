"""Tests for embedding batch-size handling.

Uses a fake embedding provider to verify that large chunk lists are
split into batches that respect the provider's batch_size limit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memsearch.chunker import Chunk
from memsearch.core import MemSearch
from memsearch.embeddings.utils import _estimate_tokens, _split_into_batches, batched_embed
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


# -- Token-aware batching tests --


@pytest.mark.asyncio
async def test_batched_embed_splits_on_token_limit():
    """Even if item count is under batch_size, split when tokens exceed limit."""
    rec = _Recorder()
    # Each text is 400 chars = ~100 tokens. 3 texts = ~300 tokens.
    # With max_tokens=200, should split into 2 batches despite batch_size=10.
    texts = ["x" * 400] * 3
    result = await batched_embed(texts, rec, batch_size=10, max_tokens=200)
    assert len(result) == 3
    assert rec.call_sizes == [2, 1]


@pytest.mark.asyncio
async def test_batched_embed_respects_both_limits():
    """Token limit and item limit are both enforced."""
    rec = _Recorder()
    # 6 short texts, batch_size=3, max_tokens very high -> splits by items only
    texts = list("abcdef")
    result = await batched_embed(texts, rec, batch_size=3, max_tokens=999999)
    assert len(result) == 6
    assert rec.call_sizes == [3, 3]


def test_estimate_tokens():
    assert _estimate_tokens("") == 1  # minimum 1
    assert _estimate_tokens("abcd") == 1  # 4 chars = 1 token
    assert _estimate_tokens("a" * 400) == 100


def test_split_into_batches_by_tokens():
    # 3 texts of 400 chars each (~100 tokens each), max_tokens=150
    texts = ["x" * 400] * 3
    batches = _split_into_batches(texts, batch_size=100, max_tokens=150)
    assert len(batches) == 3  # each text alone is ~100 tokens, 2 would be ~200 > 150
    assert all(len(b) == 1 for b in batches)


def test_split_into_batches_by_items():
    texts = list("abcdef")
    batches = _split_into_batches(texts, batch_size=2, max_tokens=999999)
    assert len(batches) == 3
    assert [len(b) for b in batches] == [2, 2, 2]


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


# -- Error isolation tests --


@pytest.mark.asyncio
async def test_index_continues_after_file_failure(tmp_path: Path):
    """A file that fails to index should not prevent other files from indexing."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "aaa_good.md").write_text("# Good\n\nThis file is fine.\n")
    (docs / "bbb_bad.md").write_text("# Bad\n\nThis file will fail.\n")
    (docs / "ccc_good.md").write_text("# Also Good\n\nThis file is fine too.\n")

    fake = FakeEmbedder(batch_size=100, dim=4)
    ms = MemSearch.__new__(MemSearch)
    ms._paths = [str(docs)]
    ms._max_chunk_size = 1500
    ms._overlap_lines = 2
    ms._embedder = fake
    ms._store = MilvusStore(uri=str(tmp_path / "test.db"), dimension=fake.dimension)

    # Patch _index_file to fail on the bad file
    original_index_file = ms._index_file

    async def _patched_index_file(f, *, force=False):
        if "bbb_bad" in str(f.path):
            raise RuntimeError("Simulated embedding API failure")
        return await original_index_file(f, force=force)

    ms._index_file = _patched_index_file

    n = await ms.index()
    ms.close()

    # Both good files should have been indexed despite the middle file failing
    assert n > 0
    assert len(fake.call_sizes) >= 2
