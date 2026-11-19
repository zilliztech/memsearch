"""Shared utilities for embedding providers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable


def order_indexed_embeddings(
    entries: list[tuple[int | None, list[float]]], expected_count: int, *, allow_unindexed: bool = False
) -> list[list[float]]:
    """Validate response indices and return embeddings in input order."""
    indices = [index for index, _ in entries]
    if allow_unindexed and len(indices) == expected_count and all(index is None for index in indices):
        return [embedding for _, embedding in entries]
    if (
        len(indices) != expected_count
        or any(not isinstance(index, int) or isinstance(index, bool) for index in indices)
        or set(indices) != set(range(expected_count))
    ):
        raise ValueError("Invalid embedding indices in response")
    return [embedding for _, embedding in sorted(entries, key=lambda entry: entry[0])]


async def batched_embed(
    texts: list[str],
    embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]],
    batch_size: int,
) -> list[list[float]]:
    """Split *texts* into batches and call *embed_fn* on each.

    Parameters
    ----------
    texts:
        The texts to embed.
    embed_fn:
        An async callable that embeds a single batch of texts.
    batch_size:
        Maximum number of texts per batch.  Must be >= 1.
    """
    if not texts:
        return []
    if batch_size <= 0:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    if len(texts) <= batch_size:
        return await embed_fn(texts)
    results: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        results.extend(await embed_fn(texts[i : i + batch_size]))
    return results
