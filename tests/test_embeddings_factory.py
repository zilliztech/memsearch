"""Tests for embedding provider factory and protocol."""

from __future__ import annotations

import pytest

from memsearch.embeddings import DEFAULT_MODELS, get_provider
from memsearch.embeddings.utils import batched_embed


class TestProviderFactory:
    def test_get_provider_openai(self):
        """Factory should instantiate OpenAI provider."""
        # Skip if no API key
        import os
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")
        
        provider = get_provider("openai")
        assert provider.model_name == "text-embedding-3-small"
        assert provider.dimension == 1536

    def test_get_provider_local(self):
        """Factory should instantiate local provider."""
        try:
            provider = get_provider("local")
            assert provider.model_name == "all-MiniLM-L6-v2"
            assert provider.dimension == 384
        except ImportError:
            pytest.skip("local embedding dependencies not installed")

    def test_get_provider_unknown_raises(self):
        """Factory should raise ValueError for unknown provider."""
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            get_provider("unknown_provider")

    def test_get_provider_with_custom_model(self):
        """Factory should accept custom model parameter."""
        import os
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")
        
        provider = get_provider("openai", model="text-embedding-3-large")
        assert provider.model_name == "text-embedding-3-large"

    def test_get_provider_with_batch_size(self):
        """Factory should accept batch_size parameter."""
        import os
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")
        
        provider = get_provider("openai", batch_size=100)
        # batch_size is internal, but shouldn't raise
        assert provider is not None


class TestDefaultModels:
    def test_default_models_has_all_providers(self):
        """DEFAULT_MODELS should have entries for all providers."""
        expected = ["openai", "google", "voyage", "ollama", "local"]
        for provider in expected:
            assert provider in DEFAULT_MODELS
            assert isinstance(DEFAULT_MODELS[provider], str)
            assert len(DEFAULT_MODELS[provider]) > 0

    def test_default_models_openai(self):
        """OpenAI default model should be text-embedding-3-small."""
        assert DEFAULT_MODELS["openai"] == "text-embedding-3-small"

    def test_default_models_local(self):
        """Local default model should be all-MiniLM-L6-v2."""
        assert DEFAULT_MODELS["local"] == "all-MiniLM-L6-v2"