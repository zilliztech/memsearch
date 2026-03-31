"""Google (Gemini) embedding provider.

Requires: ``pip install 'memsearch[google]'`` or ``uv add 'memsearch[google]'``
Environment variables:
    GOOGLE_API_KEY — required unless using Vertex AI credentials
    GOOGLE_GENAI_USE_VERTEXAI — optional, set to "true" to use Vertex AI auth
"""

from __future__ import annotations

import os

# Known dimensions for common Google embedding models.
# gemini-embedding-001 natively outputs 3072, but 768 is the recommended
# default for most use cases (Matryoshka truncation, saves storage).
_KNOWN_DIMENSIONS: dict[str, int] = {
    "gemini-embedding-001": 768,
    "gemini-embedding-2-preview": 768,
    "text-embedding-005": 768,
    "text-embedding-004": 768,
}


class GoogleEmbedding:
    """Google Generative AI embedding provider."""

    _DEFAULT_BATCH_SIZE = 100

    def __init__(
        self,
        model: str = "gemini-embedding-001",
        *,
        batch_size: int = 0,
    ) -> None:
        from google import genai

        use_vertex_ai = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() == "true"
        self._client = genai.Client(vertexai=use_vertex_ai)  # reads GOOGLE_API_KEY or Vertex AI env vars
        self._model = model
        self._dimension = _detect_dimension(self._client, model)
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
        from google.genai import types

        result = await self._client.aio.models.embed_content(
            model=self._model,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=self._dimension),
        )
        return [e.values for e in result.embeddings]


def _detect_dimension(client, model: str) -> int:
    """Return the embedding dimension for *model*.

    Uses a lookup table for well-known models.  For unknown models, a
    trial embed is performed to discover the native dimension.
    """
    if model in _KNOWN_DIMENSIONS:
        return _KNOWN_DIMENSIONS[model]
    # Unknown model: trial embed without output_dimensionality to get native dim
    result = client.models.embed_content(model=model, contents=["dim"])
    return len(result.embeddings[0].values)
