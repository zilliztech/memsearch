"""Google (Gemini) embedding provider.

Requires: ``pip install 'memsearch[google]'``
Environment variables:
    GOOGLE_API_KEY — required
"""

from __future__ import annotations


class GoogleEmbedding:
    """Google Generative AI embedding provider."""

    def __init__(self, model: str = "gemini-embedding-001") -> None:
        from google import genai

        self._client = genai.Client()  # reads GOOGLE_API_KEY
        self._model = model
        self._dimension = 768

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from google.genai import types

        result = await self._client.aio.models.embed_content(
            model=self._model,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=self._dimension),
        )
        return [e.values for e in result.embeddings]
