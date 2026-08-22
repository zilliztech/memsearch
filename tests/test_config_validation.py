"""Tests for configuration validation."""

from __future__ import annotations

import pytest

from memsearch.config import MemSearchConfig


class TestConfigValidation:
    def test_default_config_creation(self):
        """Default config should be created successfully."""
        cfg = MemSearchConfig()
        assert cfg is not None

    def test_config_default_provider(self):
        """Default provider should be openai."""
        cfg = MemSearchConfig()
        assert cfg.embedding.provider == "openai"

    def test_config_default_model(self):
        """Default model should be text-embedding-3-small."""
        cfg = MemSearchConfig()
        # Model is determined by DEFAULT_MODELS
        from memsearch.embeddings import DEFAULT_MODELS
        assert DEFAULT_MODELS["openai"] == "text-embedding-3-small"

    def test_config_default_uri(self):
        """Default Milvus URI should be local path."""
        cfg = MemSearchConfig()
        assert "~/.memsearch" in cfg.milvus.uri

    def test_config_default_collection(self):
        """Default collection name should be set."""
        cfg = MemSearchConfig()
        assert cfg.milvus.collection == "memsearch_chunks"

    def test_config_chunking_defaults(self):
        """Default chunking parameters should be set."""
        cfg = MemSearchConfig()
        assert cfg.chunking.max_chunk_size == 1500
        assert cfg.chunking.overlap_lines == 2