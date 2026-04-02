"""Tests for the configuration system."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomli_w

from memsearch.config import (
    EmbeddingConfig,
    MemSearchConfig,
    _dict_to_config,
    deep_merge,
    get_config_value,
    load_config_file,
    resolve_config,
    resolve_env_ref,
    save_config,
    set_config_value,
)


def test_default_config():
    """MemSearchConfig() should produce sensible defaults."""
    cfg = MemSearchConfig()
    assert cfg.milvus.uri == "~/.memsearch/milvus.db"
    assert cfg.milvus.collection == "memsearch_chunks"
    assert cfg.embedding.provider == "openai"
    assert cfg.chunking.max_chunk_size == 1500
    assert cfg.chunking.overlap_lines == 2
    assert cfg.watch.debounce_ms == 1500
    assert cfg.compact.llm_provider == "openai"


def test_load_toml_file(tmp_path: Path):
    """load_config_file should parse a TOML file into a nested dict."""
    cfg_file = tmp_path / "config.toml"
    data = {
        "milvus": {"uri": "http://localhost:19530", "collection": "test_col"},
        "embedding": {"provider": "google"},
    }
    with open(cfg_file, "wb") as f:
        tomli_w.dump(data, f)

    result = load_config_file(cfg_file)
    assert result["milvus"]["uri"] == "http://localhost:19530"
    assert result["milvus"]["collection"] == "test_col"
    assert result["embedding"]["provider"] == "google"


def test_load_missing_file(tmp_path: Path):
    """load_config_file should return {} for a missing file."""
    result = load_config_file(tmp_path / "nonexistent.toml")
    assert result == {}


def test_deep_merge_basic():
    """deep_merge should recursively merge nested dicts."""
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    override = {"a": {"y": 99}, "c": 4}
    merged = deep_merge(base, override)
    assert merged == {"a": {"x": 1, "y": 99}, "b": 3, "c": 4}


def test_deep_merge_none_skipped():
    """deep_merge should skip None values in override."""
    base = {"a": {"x": 1}}
    override = {"a": {"x": None}}
    merged = deep_merge(base, override)
    assert merged["a"]["x"] == 1


def test_resolve_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """resolve_config should layer: defaults < toml < cli."""
    # Write a "global" config
    global_cfg = tmp_path / "global.toml"
    save_config({"milvus": {"uri": "http://toml:19530"}}, global_cfg)

    # Patch the paths
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", global_cfg)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / "nope.toml")

    # CLI override
    cli = {"milvus": {"collection": "cli_col"}}

    cfg = resolve_config(cli)
    # TOML wins over default
    assert cfg.milvus.uri == "http://toml:19530"
    # CLI wins over everything
    assert cfg.milvus.collection == "cli_col"
    # Untouched fields remain default
    assert cfg.embedding.provider == "openai"
    assert cfg.chunking.max_chunk_size == 1500


def test_set_get_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """set_config_value + get_config_value should round-trip correctly."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", cfg_path)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / "nope.toml")

    set_config_value("milvus.uri", "http://roundtrip:19530")
    cfg = resolve_config()
    assert get_config_value("milvus.uri", cfg) == "http://roundtrip:19530"


def test_set_config_value_int_conversion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """set_config_value should auto-convert int fields from strings."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", cfg_path)

    set_config_value("chunking.max_chunk_size", "2000")
    data = load_config_file(cfg_path)
    assert data["chunking"]["max_chunk_size"] == 2000
    assert isinstance(data["chunking"]["max_chunk_size"], int)


def test_get_config_value_invalid_key():
    """get_config_value should raise KeyError for unknown keys."""
    cfg = MemSearchConfig()
    with pytest.raises(KeyError):
        get_config_value("nonexistent.key", cfg)


def test_save_and_load_roundtrip(tmp_path: Path):
    """save_config + load_config_file should round-trip a dict."""
    data = {"milvus": {"uri": "http://test:19530"}, "embedding": {"provider": "local"}}
    path = tmp_path / "test.toml"
    save_config(data, path)
    loaded = load_config_file(path)
    assert loaded == data


# -- env: resolver tests --


def test_resolve_env_ref_plain():
    """Non-prefixed strings should pass through unchanged."""
    assert resolve_env_ref("https://api.openai.com") == "https://api.openai.com"
    assert resolve_env_ref("") == ""
    assert resolve_env_ref("sk-test123") == "sk-test123"


def test_resolve_env_ref_env_prefix(monkeypatch: pytest.MonkeyPatch):
    """env:VAR_NAME should resolve to the environment variable value."""
    monkeypatch.setenv("MY_TEST_KEY", "resolved-value-123")
    assert resolve_env_ref("env:MY_TEST_KEY") == "resolved-value-123"


def test_resolve_env_ref_missing_var():
    """env:VAR_NAME should raise KeyError if the variable is not set."""
    import os

    # Ensure the var doesn't exist
    os.environ.pop("NONEXISTENT_MEMSEARCH_VAR", None)
    with pytest.raises(KeyError, match="NONEXISTENT_MEMSEARCH_VAR"):
        resolve_env_ref("env:NONEXISTENT_MEMSEARCH_VAR")


def test_resolve_env_refs_in_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """resolve_config should resolve env: references in TOML values."""
    monkeypatch.setenv("TEST_API_KEY", "sk-from-env")
    monkeypatch.setenv("TEST_MILVUS_TOKEN", "token-from-env")

    cfg_file = tmp_path / "config.toml"
    save_config(
        {
            "embedding": {
                "api_key": "env:TEST_API_KEY",
                "base_url": "https://my-endpoint.com",
            },
            "milvus": {"token": "env:TEST_MILVUS_TOKEN"},
        },
        cfg_file,
    )

    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", cfg_file)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / "nope.toml")

    cfg = resolve_config()
    assert cfg.embedding.api_key == "sk-from-env"
    assert cfg.embedding.base_url == "https://my-endpoint.com"
    assert cfg.milvus.token == "token-from-env"


def test_embedding_config_new_fields():
    """EmbeddingConfig should have base_url and api_key fields with empty defaults."""
    cfg = EmbeddingConfig()
    assert cfg.base_url == ""
    assert cfg.api_key == ""


def test_compact_config_new_fields():
    """CompactConfig should have base_url and api_key fields with empty defaults."""
    from memsearch.config import CompactConfig

    cfg = CompactConfig()
    assert cfg.base_url == ""
    assert cfg.api_key == ""


def test_compact_config_env_ref_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """resolve_config should resolve env: references in compact.api_key and compact.base_url."""
    monkeypatch.setenv("TEST_LLM_KEY", "sk-llm-from-env")

    cfg_file = tmp_path / "config.toml"
    save_config(
        {
            "compact": {
                "api_key": "env:TEST_LLM_KEY",
                "base_url": "https://my-llm-endpoint.com",
            },
        },
        cfg_file,
    )

    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", cfg_file)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / "nope.toml")

    cfg = resolve_config()
    assert cfg.compact.api_key == "sk-llm-from-env"
    assert cfg.compact.base_url == "https://my-llm-endpoint.com"


def test_compact_config_set_get_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """set_config_value + get_config_value should work for compact.base_url and compact.api_key."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", cfg_path)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / "nope.toml")

    set_config_value("compact.base_url", "https://custom-llm.example.com")
    set_config_value("compact.api_key", "sk-custom-123")
    cfg = resolve_config()
    assert get_config_value("compact.base_url", cfg) == "https://custom-llm.example.com"
    assert get_config_value("compact.api_key", cfg) == "sk-custom-123"


def test_dict_to_config_ignores_unknown_fields_and_non_dict_sections() -> None:
    """_dict_to_config should ignore garbage sections/fields instead of crashing."""
    cfg = _dict_to_config(
        {
            "embedding": {
                "provider": "google",
                "batch_size": 64,
                "unknown_field": "ignored",
            },
            "milvus": "not-a-dict",
            "compact": {
                "llm_provider": "anthropic",
                "llm_model": "claude-3-7-sonnet",
                "extra": True,
            },
            "unknown_section": {"foo": "bar"},
        }
    )

    assert cfg.embedding.provider == "google"
    assert cfg.embedding.batch_size == 64
    assert cfg.milvus.uri == "~/.memsearch/milvus.db"
    assert cfg.compact.llm_provider == "anthropic"
    assert cfg.compact.llm_model == "claude-3-7-sonnet"


def test_dict_to_config_accepts_empty_section_dicts() -> None:
    """Explicit empty section dicts should fall back to dataclass defaults."""
    cfg = _dict_to_config({"embedding": {}, "milvus": {}, "watch": {}})

    assert cfg.embedding.provider == "openai"
    assert cfg.milvus.collection == "memsearch_chunks"
    assert cfg.watch.debounce_ms == 1500
