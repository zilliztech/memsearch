"""Tests for ordered OpenAI-compatible embedding responses."""

from __future__ import annotations

import json

import httpx
import openai
import pytest

from memsearch.embeddings.openai import OpenAIEmbedding


@pytest.mark.asyncio
async def test_out_of_order_embeddings_are_returned_in_input_order(monkeypatch):
    batches = []

    def respond(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        batches.append(texts)
        data = [{"object": "embedding", "index": i, "embedding": [float(ord(text[0]))]} for i, text in enumerate(texts)]
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-small",
                "data": list(reversed(data)),
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        client = openai.AsyncOpenAI(api_key="test", base_url="https://example.invalid/v1", http_client=http_client)
        monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: client)
        provider = OpenAIEmbedding(api_key="test", batch_size=2)
        result = await provider.embed(["alpha", "beta", "gamma", "delta", "epsilon"])

    assert batches == [["alpha", "beta"], ["gamma", "delta"], ["epsilon"]]
    assert result == [[97.0], [98.0], [103.0], [100.0], [101.0]]


@pytest.mark.asyncio
@pytest.mark.parametrize("indices", [[0, 0], [0, 2], [-1, 1], [0], [0, 1, 2]])
async def test_invalid_embedding_indices_are_rejected(monkeypatch, indices):
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-small",
                "data": [{"object": "embedding", "index": i, "embedding": [float(i)]} for i in indices],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        client = openai.AsyncOpenAI(api_key="test", base_url="https://example.invalid/v1", http_client=http_client)
        monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: client)
        provider = OpenAIEmbedding(api_key="test")
        with pytest.raises(ValueError, match="embedding indices"):
            await provider.embed(["alpha", "beta"])
