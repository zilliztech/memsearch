"""Google (Gemini) embedding provider.

Requires: ``pip install 'memsearch[google]'`` or ``uv add 'memsearch[google]'``
Environment variables:
    GOOGLE_API_KEY — required
"""

from __future__ import annotations


# Known dimensions for common Google embedding models.
# gemini-embedding-001 natively outputs 3072, but 768 is the recommended
# default for most use cases (Matryoshka truncation, saves storage).
_KNOWN_DIMENSIONS: dict[str, int] = {
    "gemini-embedding-001": 768,
    "text-embedding-004": 768,
}


class GoogleEmbedding:
    """Google Generative AI embedding provider."""

    def __init__(self, model: str = "gemini-embedding-001") -> None:
        from google import genai

        self._client = genai.Client()  # reads GOOGLE_API_KEY
        self._model = model
        self._dimension = _detect_dimension(self._client, model)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from google.genai import types

        # Google API limits batch size to 100 texts per request.
        batch_size = 100
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            result = await self._client.aio.models.embed_content(
                model=self._model,
                contents=batch,
                config=types.EmbedContentConfig(output_dimensionality=self._dimension),
            )
            all_embeddings.extend(e.values for e in result.embeddings)
        return all_embeddings


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
