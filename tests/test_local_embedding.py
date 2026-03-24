"""Tests for local embedding provider."""

from unittest.mock import patch


def test_mps_device_detected_on_apple_silicon():
    """When torch.backends.mps.is_available() is True, device should be 'mps'."""
    with (
        patch("torch.backends.mps.is_available", return_value=True),
        patch("torch.cuda.is_available", return_value=False),
    ):
        from memsearch.embeddings.local import _detect_device

        assert _detect_device() == "mps"


def test_cuda_preferred_over_mps():
    """CUDA should take priority when both are available."""
    with (
        patch("torch.backends.mps.is_available", return_value=True),
        patch("torch.cuda.is_available", return_value=True),
    ):
        from memsearch.embeddings.local import _detect_device

        assert _detect_device() == "cuda"


def test_cpu_fallback():
    """Falls back to CPU when no GPU is available."""
    with (
        patch("torch.backends.mps.is_available", return_value=False),
        patch("torch.cuda.is_available", return_value=False),
    ):
        from memsearch.embeddings.local import _detect_device

        assert _detect_device() == "cpu"


def test_default_model_is_gte_modernbert():
    """Default local model should be gte-modernbert-base."""
    from memsearch.embeddings import DEFAULT_MODELS

    assert DEFAULT_MODELS["local"] == "Alibaba-NLP/gte-modernbert-base"


def test_default_google_model_is_gemini_embedding_2():
    """Default Google model should be gemini-embedding-2-preview."""
    from memsearch.embeddings import DEFAULT_MODELS

    assert DEFAULT_MODELS["google"] == "gemini-embedding-2-preview"


def test_default_voyage_model_is_v4():
    """Default Voyage model should be voyage-4-lite."""
    from memsearch.embeddings import DEFAULT_MODELS

    assert DEFAULT_MODELS["voyage"] == "voyage-4-lite"


def test_all_provider_defaults_present():
    """Every registered provider should have a default model."""
    from memsearch.embeddings import _PROVIDERS, DEFAULT_MODELS

    for provider in _PROVIDERS:
        assert provider in DEFAULT_MODELS, f"Missing default for {provider}"
        assert DEFAULT_MODELS[provider], f"Empty default for {provider}"
