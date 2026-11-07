"""Indexed responses must keep embeddings aligned with their inputs."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from memsearch.embeddings.jina import JinaEmbedding
from memsearch.embeddings.mistral import MistralEmbedding


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["jina", "mistral"])
@pytest.mark.parametrize(
    "indices", [[1, 0], [0, 0], [0, 2], [-1, 1], [0, True], [0], [0, 1, 2], [None, None], [None, 1]]
)
async def test_indexed_provider_response_order_and_validation(provider_name, indices):
    data = [
        {"index": index, "embedding": [float(index if index is not None else i)]} for i, index in enumerate(indices)
    ]

    def respond(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["input"] == ["first", "second"]
        return httpx.Response(200, json={"data": data})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        if provider_name == "jina":
            provider = JinaEmbedding.__new__(JinaEmbedding)
            provider._client = client
            provider._model = "test"
            provider._task = ""
            provider._dimensions = 1
            provider._batch_size = 2
            provider._api_key = "test"
        else:

            async def create_async(*, model, inputs):
                assert inputs == ["first", "second"]
                return SimpleNamespace(data=[SimpleNamespace(**item) for item in data])

            provider = MistralEmbedding.__new__(MistralEmbedding)
            provider._client = SimpleNamespace(embeddings=SimpleNamespace(create_async=create_async))
            provider._model = "test"
            provider._batch_size = 2

        if indices == [1, 0] or (provider_name == "mistral" and indices == [None, None]):
            assert await provider.embed(["first", "second"]) == [[0.0], [1.0]]
        else:
            with pytest.raises(ValueError, match="embedding indices"):
                await provider.embed(["first", "second"])


@pytest.mark.asyncio
@pytest.mark.parametrize("indexed", [True, False])
async def test_mistral_sdk_handles_indexed_and_unindexed_responses(indexed):
    mistral = pytest.importorskip("mistralai.client")

    def respond(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["input"] == ["first", "second"]
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "list",
                "model": "mistral-embed",
                "data": (
                    [{"index": 1, "embedding": [1.0]}, {"index": 0, "embedding": [0.0]}]
                    if indexed
                    else [{"embedding": [0.0]}, {"embedding": [1.0]}]
                ),
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = MistralEmbedding.__new__(MistralEmbedding)
        provider._client = mistral.Mistral(api_key="test", server_url="https://example.invalid", async_client=client)
        provider._model = "mistral-embed"
        provider._batch_size = 2
        assert await provider.embed(["first", "second"]) == [[0.0], [1.0]]
