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

# Default model for each provider (mirrors the __init__ defaults in each class).
# Kept here so callers can resolve the effective model without importing heavy deps.
DEFAULT_MODELS: dict[str, str] = {
    "openai": "text-embedding-3-small",
    "google": "gemini-embedding-001",
    "voyage": "voyage-3-lite",
    "ollama": "nomic-embed-text",
    "local": "all-MiniLM-L6-v2",
}

_INSTALL_HINTS: dict[str, str] = {
    "openai": "pip install memsearch  (or: uv add memsearch)",
    "google": 'pip install "memsearch[google]"  (or: uv add "memsearch[google]")',
    "voyage": 'pip install "memsearch[voyage]"  (or: uv add "memsearch[voyage]")',
    "ollama": 'pip install "memsearch[ollama]"  (or: uv add "memsearch[ollama]")',
    "local": 'pip install "memsearch[local]"  (or: uv add "memsearch[local]")',
}

_API_KEY_PROVIDERS = {"openai", "google", "voyage"}


def get_provider(
    name: str = "openai",
    *,
    model: str | None = None,
    batch_size: int = 0,
    base_url: str | None = None,
    api_key: str | None = None,
) -> EmbeddingProvider:
    """Instantiate an embedding provider by name.

    Parameters
    ----------
    name:
        One of "openai", "google", "voyage", "ollama", "local".
    model:
        Override the default model for the provider.
    batch_size:
        Maximum number of texts per embedding API call.
        ``0`` means use the provider's built-in default.
    base_url:
        Override the API base URL (currently only used by the openai provider).
    api_key:
        Override the API key for providers that support explicit credentials.
    """
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown embedding provider {name!r}. Available: {', '.join(sorted(_PROVIDERS))}")

    module_path, class_name = _PROVIDERS[name]
    try:
        import importlib

        mod = importlib.import_module(module_path)
    except ImportError as exc:
        hint = _INSTALL_HINTS.get(name, "")
        raise ImportError(f"Embedding provider {name!r} requires extra dependencies. Install with: {hint}") from exc

    cls = getattr(mod, class_name)
    kwargs: dict = {}
    if model is not None:
        kwargs["model"] = model
    if batch_size > 0:
        kwargs["batch_size"] = batch_size
    if name == "openai" and base_url:
        kwargs["base_url"] = base_url
    if api_key and name in _API_KEY_PROVIDERS:
        kwargs["api_key"] = api_key
    return cls(**kwargs)


__all__ = ["DEFAULT_MODELS", "EmbeddingProvider", "get_provider"]
