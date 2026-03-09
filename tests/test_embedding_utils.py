"""Tests for embedding utilities."""

from __future__ import annotations

import pytest

from memsearch.embeddings.utils import batched_embed


class TestBatchedEmbed:
    @pytest.mark.asyncio
    async def test_batched_embed_empty_list(self):
        """Empty list should return empty results."""
        async def mock_embed(texts):
            return [[0.0] * 4 for _ in texts]

        result = await batched_embed([], mock_embed, batch_size=4)
        assert result == []

    @pytest.mark.asyncio
    async def test_batched_embed_single_item(self):
        """Single item should work."""
        async def mock_embed(texts):
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

        result = await batched_embed(["test"], mock_embed, batch_size=4)
        assert len(result) == 1
        assert result[0] == [1.0, 0.0, 0.0, 0.0]

    @pytest.mark.asyncio
    async def test_batched_embed_under_batch_size(self):
        """Items under batch size should not split."""
        async def mock_embed(texts):
            return [[float(i), 0.0, 0.0, 0.0] for i in range(len(texts))]

        result = await batched_embed(["a", "b", "c"], mock_embed, batch_size=4)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_batched_embed_exact_batch_size(self):
        """Exactly batch size items."""
        async def mock_embed(texts):
            return [[1.0] * 4 for _ in texts]

        result = await batched_embed(["a", "b", "c", "d"], mock_embed, batch_size=4)
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_batched_embed_over_batch_size(self):
        """Items over batch size should split."""
        calls = []
        async def mock_embed(texts):
            calls.append(len(texts))
            return [[1.0] * 4 for _ in texts]

        result = await batched_embed(["a", "b", "c", "d", "e"], mock_embed, batch_size=4)
        assert len(result) == 5
        assert len(calls) == 2  # Split into 4 + 1

    def test_batched_embed_invalid_batch_size(self):
        """Invalid batch size should raise."""
        async def mock_embed(texts):
            return []

        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            import asyncio
            asyncio.run(batched_embed(["test"], mock_embed, batch_size=0))