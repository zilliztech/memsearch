"""Edge case tests for embeddings module."""

from __future__ import annotations

import pytest

from memsearch.embeddings import DEFAULT_MODELS, get_provider


class TestEmbeddingsEdgeCases:
    def test_default_models_not_empty(self):
        """DEFAULT_MODELS should contain all providers."""
        assert len(DEFAULT_MODELS) >= 5
        assert "openai" in DEFAULT_MODELS
        assert "google" in DEFAULT_MODELS
        assert "voyage" in DEFAULT_MODELS
        assert "ollama" in DEFAULT_MODELS
        assert "local" in DEFAULT_MODELS

    def test_get_provider_invalid_name(self):
        """Invalid provider name should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            get_provider("invalid_provider")

    def test_get_provider_case_sensitive(self):
        """Provider names should be case-sensitive."""
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            get_provider("OpenAI")  # Should fail, expects "openai"

    def test_default_models_values_not_empty(self):
        """All default model values should be non-empty strings."""
        for provider, model in DEFAULT_MODELS.items():
            assert isinstance(model, str)
            assert len(model) > 0
            assert " " not in model  # Model names shouldn't have spaces

    def test_get_provider_with_negative_batch_size(self):
        """Negative batch size should be handled."""
        # This tests the parameter passing, actual validation is provider-specific
        try:
            provider = get_provider("openai", batch_size=-1)
            # If we got here, the provider was created (validation may be lazy)
            assert provider is not None
        except ValueError:
            # Also acceptable if validation is strict
            pass

    def test_default_models_consistency(self):
        """DEFAULT_MODELS keys should match common provider names."""
        common_providers = ["openai", "google", "voyage", "ollama", "local"]
        for provider in common_providers:
            assert provider in DEFAULT_MODELS