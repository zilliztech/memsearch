"""Voyage AI embedding provider.

Requires: ``pip install 'memsearch[voyage]'`` or ``uv add 'memsearch[voyage]'``
Environment variables:
    VOYAGE_API_KEY — required
"""

from __future__ import annotations


class VoyageEmbedding:
    """Voyage AI embedding provider."""

    _DEFAULT_BATCH_SIZE = 128

    def __init__(
        self,
        model: str = "voyage-3-lite",
        *,
        batch_size: int = 0,
        api_key: str | None = None,
    ) -> None:
        import voyageai

        kwargs = {"api_key": api_key} if api_key else {}
        self._client = voyageai.AsyncClient(**kwargs)  # reads VOYAGE_API_KEY if api_key is not provided
        self._model = model
        self._dimension = _detect_dimension(model)
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
        result = await self._client.embed(texts, model=self._model)
        return result.embeddings


_KNOWN_DIMENSIONS: dict[str, int] = {
    "voyage-3-lite": 512,
    "voyage-3": 1024,
    "voyage-code-3": 1024,
}


def _detect_dimension(model: str) -> int:
    """Return the embedding dimension for *model*.

    Uses a lookup table for well-known Voyage models.  For unknown models,
    a trial embed is performed.
    """
    if model in _KNOWN_DIMENSIONS:
        return _KNOWN_DIMENSIONS[model]
    import voyageai

    sync_client = voyageai.Client()
    trial = sync_client.embed(["dim"], model=model)
    return len(trial.embeddings[0])
