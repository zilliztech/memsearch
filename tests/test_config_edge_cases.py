"""Edge case tests for configuration module."""

from __future__ import annotations

import pytest

from memsearch.config import (
    EmbeddingConfig,
    MemSearchConfig,
    deep_merge,
    get_config_value,
    load_config_file,
    set_config_value,
)


class TestConfigEdgeCases:
    def test_memsearch_config_empty_paths(self):
        """MemSearchConfig should handle empty paths list."""
        cfg = MemSearchConfig(paths=[])
        assert cfg.paths == []

    def test_deep_merge_empty_dicts(self):
        """deep_merge with empty dicts."""
        result = deep_merge({}, {})
        assert result == {}

    def test_deep_merge_one_empty(self):
        """deep_merge with one empty dict."""
        result = deep_merge({"a": 1}, {})
        assert result == {"a": 1}

    def test_deep_merge_nested_empty(self):
        """deep_merge with nested empty dicts."""
        base = {"a": {"x": 1}}
        override = {"a": {}}
        result = deep_merge(base, override)
        assert result == {"a": {"x": 1}}

    def test_config_with_special_characters_in_description(self):
        """Config should handle special characters in description."""
        cfg = MemSearchConfig(description="Test | Special: chars\\nnewline")
        assert "|" in cfg.description or cfg.description == "Test | Special: chars\\nnewline"

    def test_embedding_config_minimal(self):
        """EmbeddingConfig with minimal settings."""
        cfg = EmbeddingConfig()
        assert cfg.provider == "openai"  # Default
        assert cfg.model == ""  # Empty default
        assert cfg.batch_size == 0  # Default

    def test_invalid_config_key_raises(self):
        """Getting invalid config key should raise KeyError."""
        cfg = MemSearchConfig()
        with pytest.raises(KeyError):
            get_config_value("invalid.key.path", cfg)

    def test_load_config_file_nonexistent(self, tmp_path):
        """Loading non-existent file should return empty dict."""
        result = load_config_file(tmp_path / "nonexistent.toml")
        assert result == {}