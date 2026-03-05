"""Integration tests for OpenAI embedding provider.

These tests require OPENAI_API_KEY to be set.
They are skipped if the key is not available.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)


@pytest.fixture
def provider():
    from memsearch.embeddings.openai import OpenAIEmbedding

    return OpenAIEmbedding()


@pytest.mark.asyncio
async def test_embed_single(provider):
    results = await provider.embed(["Hello world"])
    assert len(results) == 1
    assert len(results[0]) == provider.dimension
    assert all(isinstance(v, float) for v in results[0])


@pytest.mark.asyncio
async def test_embed_batch(provider):
    texts = ["First text", "Second text", "Third text"]
    results = await provider.embed(texts)
    assert len(results) == 3
    for emb in results:
        assert len(emb) == provider.dimension


@pytest.mark.asyncio
async def test_embed_deterministic(provider):
    text = "Deterministic embedding test"
    r1 = await provider.embed([text])
    r2 = await provider.embed([text])
    # OpenAI embeddings should be deterministic
    assert r1[0][:5] == r2[0][:5]


def test_model_name(provider):
    assert provider.model_name == "text-embedding-3-small"


def test_dimension(provider):
    assert provider.dimension == 1536
