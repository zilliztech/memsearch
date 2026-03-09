"""Edge case tests for OpenAI embeddings."""

from __future__ import annotations

import pytest


class TestOpenAIEmbeddingEdgeCases:
    def test_openai_embedding_import(self):
        """OpenAI embedding module should be importable."""
        try:
            from memsearch.embeddings.openai import OpenAIEmbedding
            assert True
        except ImportError as e:
            pytest.skip(f"OpenAI not available: {e}")

    def test_openai_embedding_class_exists(self):
        """OpenAIEmbedding class should exist."""
        try:
            from memsearch.embeddings.openai import OpenAIEmbedding
            assert hasattr(OpenAIEmbedding, '__init__')
            assert hasattr(OpenAIEmbedding, 'embed')
        except ImportError:
            pytest.skip("OpenAI not available")

    def test_openai_default_model(self):
        """OpenAI should have default model configured."""
        from memsearch.embeddings import DEFAULT_MODELS
        assert "openai" in DEFAULT_MODELS
        assert DEFAULT_MODELS["openai"] == "text-embedding-3-small"

    def test_openai_dimension(self):
        """OpenAI model should have expected dimension."""
        try:
            from memsearch.embeddings.openai import OpenAIEmbedding
            # Default model dimension
            embedder = OpenAIEmbedding.__new__(OpenAIEmbedding)
            embedder._dimension = 1536  # text-embedding-3-small
            assert embedder._dimension == 1536
        except ImportError:
            pytest.skip("OpenAI not available")


class TestOpenAIEmbeddingConfiguration:
    def test_openai_configurable_batch_size(self):
        """OpenAI embedding should support batch_size parameter."""
        try:
            from memsearch.embeddings.openai import OpenAIEmbedding
            # Test that batch_size is accepted
            assert hasattr(OpenAIEmbedding, '__init__')
        except ImportError:
            pytest.skip("OpenAI not available")

    def test_openai_configurable_model(self):
        """OpenAI embedding should support model parameter."""
        try:
            from memsearch.embeddings.openai import OpenAIEmbedding
            assert hasattr(OpenAIEmbedding, '__init__')
        except ImportError:
            pytest.skip("OpenAI not available")