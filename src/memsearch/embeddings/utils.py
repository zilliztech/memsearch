"""Shared utilities for embedding providers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

# OpenAI embedding API limit is 300,000 tokens per request.
# Use a conservative default (reserving headroom for tokenization variance).
_DEFAULT_MAX_TOKENS_PER_BATCH = 250_000

# Rough estimate: 1 token per 4 characters for cl100k_base.
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    """Estimate token count from character length (conservative)."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _split_into_batches(
    texts: list[str],
    batch_size: int,
    max_tokens: int,
) -> list[list[str]]:
    """Split texts into batches respecting both item count and token budget."""
    batches: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0

    for text in texts:
        text_tokens = _estimate_tokens(text)
        would_exceed_tokens = current and (current_tokens + text_tokens > max_tokens)
        would_exceed_items = len(current) >= batch_size

        if would_exceed_tokens or would_exceed_items:
            batches.append(current)
            current = []
            current_tokens = 0

        current.append(text)
        current_tokens += text_tokens

    if current:
        batches.append(current)

    return batches


async def batched_embed(
    texts: list[str],
    embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]],
    batch_size: int,
    max_tokens: int = _DEFAULT_MAX_TOKENS_PER_BATCH,
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
    max_tokens:
        Maximum estimated tokens per batch.  Prevents exceeding
        provider API limits when many texts are small enough to
        fit under *batch_size* but collectively exceed the token cap.
    """
    if not texts:
        return []
    if batch_size <= 0:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")

    total_tokens = sum(_estimate_tokens(t) for t in texts)
    if len(texts) <= batch_size and total_tokens <= max_tokens:
        return await embed_fn(texts)

    results: list[list[float]] = []
    for batch in _split_into_batches(texts, batch_size, max_tokens):
        results.extend(await embed_fn(batch))
    return results
