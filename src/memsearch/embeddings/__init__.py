"""Embedding providers — protocol, factory, and concrete implementations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Minimal interface every embedding backend must satisfy."""

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


# Provider registry: name -> (module_path, class_name)
_PROVIDERS: dict[str, tuple[str, str]] = {
    "openai": ("memsearch.embeddings.openai", "OpenAIEmbedding"),
    "google": ("memsearch.embeddings.google", "GoogleEmbedding"),
    "voyage": ("memsearch.embeddings.voyage", "VoyageEmbedding"),
    "ollama": ("memsearch.embeddings.ollama", "OllamaEmbedding"),
    "local": ("memsearch.embeddings.local", "LocalEmbedding"),
}

_INSTALL_HINTS: dict[str, str] = {
    "openai": 'pip install memsearch  (or: uv add memsearch)',
    "google": 'pip install "memsearch[google]"  (or: uv add "memsearch[google]")',
    "voyage": 'pip install "memsearch[voyage]"  (or: uv add "memsearch[voyage]")',
    "ollama": 'pip install "memsearch[ollama]"  (or: uv add "memsearch[ollama]")',
    "local": 'pip install "memsearch[local]"  (or: uv add "memsearch[local]")',
}


def get_provider(
    name: str = "openai",
    *,
    model: str | None = None,
) -> EmbeddingProvider:
    """Instantiate an embedding provider by name.

    Parameters
    ----------
    name:
        One of "openai", "google", "voyage", "ollama", "local".
    model:
        Override the default model for the provider.
    """
    if name not in _PROVIDERS:
        raise ValueError(
            f"Unknown embedding provider {name!r}. "
            f"Available: {', '.join(sorted(_PROVIDERS))}"
        )

    module_path, class_name = _PROVIDERS[name]
    try:
        import importlib

        mod = importlib.import_module(module_path)
    except ImportError as exc:
        hint = _INSTALL_HINTS.get(name, "")
        raise ImportError(
            f"Embedding provider {name!r} requires extra dependencies. "
            f"Install with: {hint}"
        ) from exc

    cls = getattr(mod, class_name)
    kwargs: dict = {}
    if model is not None:
        kwargs["model"] = model
    return cls(**kwargs)


__all__ = ["EmbeddingProvider", "get_provider"]
