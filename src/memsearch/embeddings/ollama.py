"""Ollama embedding provider (local models via Ollama server).

Requires: ``pip install 'memsearch[ollama]'``
Environment variables:
    OLLAMA_HOST — optional, default http://localhost:11434
"""

from __future__ import annotations


class OllamaEmbedding:
    """Ollama embedding provider."""

    def __init__(self, model: str = "nomic-embed-text") -> None:
        import ollama

        self._client = ollama.AsyncClient()  # reads OLLAMA_HOST
        self._model = model
        # Auto-detect dimension via a trial embed (each model has its own)
        _sync = ollama.Client()
        trial = _sync.embed(model=model, input=["dim"])
        self._dimension = len(trial["embeddings"][0])

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        result = await self._client.embed(model=self._model, input=texts)
        return result["embeddings"]
