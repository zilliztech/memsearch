"""OpenAI embedding provider.

Requires: ``pip install memsearch`` (openai is included by default)
Environment variables:
    OPENAI_API_KEY   — required
    OPENAI_BASE_URL  — optional, override API base URL
"""

from __future__ import annotations

import os


class OpenAIEmbedding:
    """OpenAI text-embedding provider."""

    _DEFAULT_BATCH_SIZE = 2048

    def __init__(
        self, model: str = "text-embedding-3-small", *, batch_size: int = 0,
    ) -> None:
        import openai

        kwargs: dict = {}
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url

        self._client = openai.AsyncOpenAI(**kwargs)  # reads OPENAI_API_KEY
        self._model = model
        self._dimension = _detect_dimension(model, kwargs)
        self._batch_size = batch_size if batch_size > 0 else self._DEFAULT_BATCH_SIZE

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from .utils import batched_embed

        return await batched_embed(texts, self._embed_batch, self._batch_size)

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.embeddings.create(input=texts, model=self._model)
        return [item.embedding for item in resp.data]


_KNOWN_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


def _detect_dimension(model: str, client_kwargs: dict) -> int:
    """Return the embedding dimension for *model*.

    Uses a lookup table for well-known OpenAI models.  For unknown models
    (e.g. custom models via OPENAI_BASE_URL), a trial embed is performed.
    """
    if model in _KNOWN_DIMENSIONS:
        return _KNOWN_DIMENSIONS[model]
    import openai

    sync_client = openai.OpenAI(**client_kwargs)
    trial = sync_client.embeddings.create(input=["dim"], model=model)
    return len(trial.data[0].embedding)
