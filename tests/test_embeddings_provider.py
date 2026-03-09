"""Tests for embedding provider interface."""

from __future__ import annotations

import pytest

from memsearch.embeddings import EmbeddingProvider


class TestEmbeddingProviderProtocol:
    def test_provider_has_model_name_property(self):
        """Provider should have model_name property."""
        assert hasattr(EmbeddingProvider, 'model_name')

    def test_provider_has_dimension_property(self):
        """Provider should have dimension property."""
        assert hasattr(EmbeddingProvider, 'dimension')

    def test_provider_has_embed_method(self):
        """Provider should have embed method."""
        assert hasattr(EmbeddingProvider, 'embed')

    def test_provider_is_protocol(self):
        """EmbeddingProvider should be a Protocol."""
        from typing import Protocol
        assert issubclass(EmbeddingProvider, Protocol)


class TestProviderRegistry:
    def test_default_models_has_all_providers(self):
        """DEFAULT_MODELS should include all providers."""
        from memsearch.embeddings import DEFAULT_MODELS
        expected = ["openai", "google", "voyage", "ollama", "local"]
        for provider in expected:
            assert provider in DEFAULT_MODELS

    def test_provider_models_are_strings(self):
        """All provider models should be strings."""
        from memsearch.embeddings import DEFAULT_MODELS
        for model in DEFAULT_MODELS.values():
            assert isinstance(model, str)
            assert len(model) > 0

    def test_provider_install_hints(self):
        """Install hints should exist for providers."""
        from memsearch.embeddings import _INSTALL_HINTS
        expected = ["openai", "google", "voyage", "ollama", "local"]
        for provider in expected:
            assert provider in _INSTALL_HINTS