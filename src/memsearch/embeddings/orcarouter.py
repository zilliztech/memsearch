"""OrcaRouter embedding provider.

Requires: ``pip install memsearch`` (openai is included by default)
Environment variables:
    ORCAROUTER_API_KEY  — required
    ORCAROUTER_BASE_URL — optional, override API base URL

OrcaRouter (https://www.orcarouter.ai) is an OpenAI-compatible model routing
gateway. Model IDs are namespaced (e.g. ``openai/text-embedding-3-small``);
bare IDs such as ``text-embedding-3-small`` are not routable and return 503.
The default base URL is ``https://api.orcarouter.ai/v1``.
"""

from __future__ import annotations

import os

_DEFAULT_BASE_URL = "https://api.orcarouter.ai/v1"

# Known output dimensions for OrcaRouter-routable embedding models.
_KNOWN_DIMENSIONS: dict[str, int] = {
    "openai/text-embedding-3-small": 1536,
    "openai/text-embedding-3-large": 3072,
}


class OrcaRouterEmbedding:
    """OrcaRouter embedding provider (OpenAI-compatible endpoint)."""

    # OpenAI-compatible gateways cap total tokens per embedding request.
    # A lower batch size avoids hitting that limit with large chunks.
    _DEFAULT_BATCH_SIZE = 256

    def __init__(
        self,
        model: str = "openai/text-embedding-3-small",
        *,
        batch_size: int = 0,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        import openai

        self._api_key = api_key or os.environ.get("ORCAROUTER_API_KEY")
        if not self._api_key:
            raise RuntimeError("ORCAROUTER_API_KEY is required for the OrcaRouter embedding provider")

        # Explicit params take priority over environment variables.
        effective_base_url = base_url or os.environ.get("ORCAROUTER_BASE_URL") or _DEFAULT_BASE_URL
        client_kwargs: dict = {
            "api_key": self._api_key,
            "base_url": effective_base_url,
        }
        self._client = openai.AsyncOpenAI(**client_kwargs)
        self._model = model
        self._dimension = _detect_dimension(model, client_kwargs)
        self._batch_size = batch_size if batch_size > 0 else self._DEFAULT_BATCH_SIZE

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def batch_size(self) -> int:
        return self._batch_size

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from .utils import batched_embed

        return await batched_embed(texts, self._embed_batch, self._batch_size)

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.embeddings.create(input=texts, model=self._model, encoding_format="float")
        return [item.embedding for item in resp.data]


def _detect_dimension(model: str, client_kwargs: dict) -> int:
    """Return the embedding dimension for *model*.

    Uses a lookup table for well-known models.  For unknown models
    (e.g. custom models via ORCAROUTER_BASE_URL), a trial embed is performed.
    """
    if model in _KNOWN_DIMENSIONS:
        return _KNOWN_DIMENSIONS[model]
    import openai

    sync_client = openai.OpenAI(**client_kwargs)
    trial = sync_client.embeddings.create(input=["dim"], model=model, encoding_format="float")
    return len(trial.data[0].embedding)
