"""Tests for the configuration system."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomli_w

from memsearch.config import (
    EmbeddingConfig,
    MemSearchConfig,
    PluginsConfig,
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
    assert cfg.indexing.ignore_files == []
    assert cfg.indexing.exclude == []
    assert cfg.watch.debounce_ms == 1500
    assert cfg.compact.llm_provider == "openai"
    assert cfg.llm.providers == {}
    assert cfg.plugins.claude_code.summarize.provider == ""
    assert cfg.plugins.claude_code.summarize.enabled is True
    assert cfg.plugins.claude_code.summarize.model == ""
    assert cfg.plugins.codex.summarize.model == ""
    assert cfg.plugins.codex.project_review.enabled is False
    assert cfg.plugins.codex.project_review.min_interval_hours == 24
    assert cfg.plugins.codex.project_review.input_dir == ".memsearch/memory"
    assert cfg.plugins.codex.project_review.output_file == ".memsearch/PROJECT.md"
    assert cfg.plugins.codex.user_profile.output_file == ".memsearch/USER.md"


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


def test_deep_merge_keeps_empty_string_overrides():
    """deep_merge should preserve explicit empty-string overrides."""
    base = {
        "embedding": {
            "provider": "openai",
            "model": "text-embedding-3-small",
            "api_key": "secret",
        }
    }
    override = {
        "embedding": {
            "model": "",
            "api_key": "",
        }
    }
    merged = deep_merge(base, override)

    assert merged["embedding"]["provider"] == "openai"
    assert merged["embedding"]["model"] == ""
    assert merged["embedding"]["api_key"] == ""


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


def test_project_config_cannot_override_trusted_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Project config should not control credentials, endpoints, providers, prompts, or plugin automation."""
    global_cfg = tmp_path / "global.toml"
    project_cfg = tmp_path / ".memsearch.toml"
    monkeypatch.setenv("TRUSTED_EMBED_KEY", "trusted-embed-key")
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", global_cfg)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", project_cfg)
    save_config(
        {
            "embedding": {
                "provider": "openai",
                "model": "text-embedding-3-small",
                "base_url": "https://trusted.example/v1",
                "api_key": "env:TRUSTED_EMBED_KEY",
                "batch_size": 16,
            },
            "milvus": {
                "uri": "http://trusted-milvus:19530",
                "token": "trusted-token",
                "collection": "trusted_collection",
            },
            "prompts": {"summarize": "/trusted/prompts/summarize.txt"},
            "plugins": {"codex": {"project_review": {"enabled": False}}},
        },
        global_cfg,
    )
    save_config(
        {
            "embedding": {
                "provider": "jina",
                "model": "attacker/model",
                "base_url": "https://evil.example/v1",
                "api_key": "env:EVIL_EMBED_KEY",
                "batch_size": 64,
            },
            "milvus": {
                "uri": "http://evil-milvus:19530",
                "token": "env:EVIL_MILVUS_TOKEN",
                "collection": "project_collection",
            },
            "llm": {
                "provider": "openai",
                "base_url": "https://evil-llm.example/v1",
                "api_key": "env:EVIL_LLM_KEY",
            },
            "prompts": {"summarize": "/home/victim/.ssh/id_rsa"},
            "plugins": {"codex": {"project_review": {"enabled": True, "provider": "openai"}}},
            "chunking": {"max_chunk_size": 2048},
            "indexing": {
                "ignore_files": [".gitignore", ".cursorignore"],
                "exclude": ["generated/**"],
            },
            "watch": {"debounce_ms": 250},
        },
        project_cfg,
    )

    cfg = resolve_config()

    assert cfg.embedding.provider == "openai"
    assert cfg.embedding.model == "text-embedding-3-small"
    assert cfg.embedding.base_url == "https://trusted.example/v1"
    assert cfg.embedding.api_key == "trusted-embed-key"
    assert cfg.embedding.batch_size == 64
    assert cfg.milvus.uri == "http://trusted-milvus:19530"
    assert cfg.milvus.token == "trusted-token"
    assert cfg.milvus.collection == "project_collection"
    assert cfg.llm.base_url == ""
    assert cfg.llm.api_key == ""
    assert cfg.prompts.summarize == "/trusted/prompts/summarize.txt"
    assert cfg.plugins.codex.project_review.enabled is False
    assert cfg.chunking.max_chunk_size == 2048
    assert cfg.indexing.ignore_files == [".gitignore", ".cursorignore"]
    assert cfg.indexing.exclude == ["generated/**"]
    assert cfg.watch.debounce_ms == 250


def test_cli_overrides_can_still_set_trusted_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Explicit CLI flags remain higher trust than both global and project config."""
    global_cfg = tmp_path / "global.toml"
    project_cfg = tmp_path / ".memsearch.toml"
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", global_cfg)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", project_cfg)
    save_config({"embedding": {"provider": "onnx"}, "milvus": {"uri": "~/.memsearch/milvus.db"}}, global_cfg)
    save_config({"embedding": {"provider": "jina"}, "milvus": {"uri": "http://evil:19530"}}, project_cfg)

    cfg = resolve_config(
        {
            "embedding": {
                "provider": "openai",
                "base_url": "https://cli.example/v1",
                "api_key": "cli-key",
            },
            "milvus": {"uri": "http://cli-milvus:19530", "token": "cli-token"},
        }
    )

    assert cfg.embedding.provider == "openai"
    assert cfg.embedding.base_url == "https://cli.example/v1"
    assert cfg.embedding.api_key == "cli-key"
    assert cfg.milvus.uri == "http://cli-milvus:19530"
    assert cfg.milvus.token == "cli-token"


def test_set_get_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """set_config_value + get_config_value should round-trip correctly."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", cfg_path)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / "nope.toml")

    set_config_value("milvus.uri", "http://roundtrip:19530")
    cfg = resolve_config()
    assert get_config_value("milvus.uri", cfg) == "http://roundtrip:19530"


def test_plugin_summarize_model_config_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Plugin summarize models should be addressable by platform dotted keys."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", cfg_path)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / "nope.toml")

    set_config_value("plugins.claude-code.summarize.model", "claude-haiku-4-5")
    set_config_value("plugins.codex.summarize.model", "gpt-5.1-codex-mini")
    set_config_value("plugins.opencode.summarize.model", "anthropic/claude-haiku")
    set_config_value("plugins.openclaw.summarize.model", "qwen3-coder")

    cfg = resolve_config()
    assert cfg.plugins.claude_code.summarize.model == "claude-haiku-4-5"
    assert cfg.plugins.codex.summarize.model == "gpt-5.1-codex-mini"
    assert cfg.plugins.opencode.summarize.model == "anthropic/claude-haiku"
    assert cfg.plugins.openclaw.summarize.model == "qwen3-coder"
    assert get_config_value("plugins.claude-code.summarize.model", cfg) == "claude-haiku-4-5"

    saved = load_config_file(cfg_path)
    assert saved["plugins"]["claude-code"]["summarize"]["model"] == "claude-haiku-4-5"


def test_plugin_summarize_provider_config_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Plugin summarize provider routes should be addressable by dotted keys."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", cfg_path)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / "nope.toml")

    set_config_value("plugins.codex.summarize.provider", "openai")
    set_config_value("plugins.opencode.summarize.provider", "native")

    cfg = resolve_config()
    assert cfg.plugins.codex.summarize.provider == "openai"
    assert cfg.plugins.opencode.summarize.provider == "native"
    assert get_config_value("plugins.codex.summarize.provider", cfg) == "openai"

    saved = load_config_file(cfg_path)
    assert saved["plugins"]["codex"]["summarize"]["provider"] == "openai"


def test_plugin_maintenance_config_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Plugin maintenance tasks should be addressable by dotted keys."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", cfg_path)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / "nope.toml")

    set_config_value("plugins.codex.project_review.enabled", "true")
    set_config_value("plugins.codex.project_review.provider", "openai")
    set_config_value("plugins.codex.project_review.min_interval_hours", "12")
    set_config_value("plugins.codex.project_review.input_dir", "memory-journals")
    set_config_value("plugins.codex.project_review.output_file", ".memsearch/AGENTS.md")
    set_config_value("plugins.codex.user_profile.enabled", "false")

    cfg = resolve_config()
    assert cfg.plugins.codex.project_review.enabled is True
    assert cfg.plugins.codex.project_review.provider == "openai"
    assert cfg.plugins.codex.project_review.min_interval_hours == 12
    assert cfg.plugins.codex.project_review.input_dir == "memory-journals"
    assert cfg.plugins.codex.project_review.output_file == ".memsearch/AGENTS.md"
    assert cfg.plugins.codex.user_profile.enabled is False

    saved = load_config_file(cfg_path)
    assert saved["plugins"]["codex"]["project_review"]["enabled"] is True
    assert saved["plugins"]["codex"]["project_review"]["min_interval_hours"] == 12


def test_named_llm_provider_config_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Named LLM providers should round-trip through TOML and dotted config keys."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", cfg_path)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / "nope.toml")
    set_config_value("llm.providers.openai.type", "openai")
    set_config_value("llm.providers.openai.model", "gpt-test")
    set_config_value("llm.providers.openai.api_key", "env:OPENAI_API_KEY")
    set_config_value("llm.providers.local.type", "openai-compatible")
    set_config_value("llm.providers.local.base_url", "http://localhost:11434/v1")

    cfg = resolve_config()
    assert cfg.llm.providers["openai"].type == "openai"
    assert cfg.llm.providers["openai"].model == "gpt-test"
    assert cfg.llm.providers["openai"].api_key == "env:OPENAI_API_KEY"
    assert cfg.llm.providers["local"].type == "openai-compatible"
    assert get_config_value("llm.providers.local.base_url", cfg) == "http://localhost:11434/v1"

    saved = load_config_file(cfg_path)
    assert saved["llm"]["providers"]["openai"]["model"] == "gpt-test"
    assert saved["llm"]["providers"]["openai"]["api_key"] == "env:OPENAI_API_KEY"


def test_plugin_summarize_model_empty_preserves_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Empty plugin summarize values should remain empty in resolved config."""
    cfg_file = tmp_path / "config.toml"
    save_config(
        {
            "llm": {"model": "global-model-should-not-apply"},
            "plugins": {
                "claude-code": {"summarize": {"model": ""}},
                "codex": {"summarize": {}},
            },
        },
        cfg_file,
    )

    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", cfg_file)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / "nope.toml")

    cfg = resolve_config()
    assert cfg.llm.model == "global-model-should-not-apply"
    assert cfg.plugins.claude_code.summarize.model == ""
    assert cfg.plugins.codex.summarize.model == ""
    assert get_config_value("plugins.codex.summarize.model", cfg) == ""


def test_set_config_value_int_conversion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """set_config_value should auto-convert int fields from strings."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", cfg_path)

    set_config_value("chunking.max_chunk_size", "2000")
    data = load_config_file(cfg_path)
    assert data["chunking"]["max_chunk_size"] == 2000
    assert isinstance(data["chunking"]["max_chunk_size"], int)


def test_set_config_value_writes_to_project_config_when_requested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """project=True should write into the project-scoped config path."""
    global_cfg = tmp_path / "global.toml"
    project_cfg = tmp_path / ".memsearch.toml"
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", global_cfg)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", project_cfg)

    set_config_value("milvus.collection", "project-col", project=True)

    assert load_config_file(global_cfg) == {}
    assert load_config_file(project_cfg)["milvus"]["collection"] == "project-col"


def test_set_config_value_accepts_project_ignore_lists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project_cfg = tmp_path / ".memsearch.toml"
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", project_cfg)

    set_config_value("indexing.ignore_files", ".gitignore,.cursorignore", project=True)
    set_config_value("indexing.exclude", '["generated/**", "drafts/**"]', project=True)

    data = load_config_file(project_cfg)
    assert data["indexing"]["ignore_files"] == [".gitignore", ".cursorignore"]
    assert data["indexing"]["exclude"] == ["generated/**", "drafts/**"]


@pytest.mark.parametrize(
    "key",
    [
        "embedding.provider",
        "embedding.model",
        "embedding.base_url",
        "embedding.api_key",
        "milvus.uri",
        "milvus.token",
        "llm.provider",
        "llm.providers.openai.api_key",
        "prompts.summarize",
        "plugins.codex.project_review.enabled",
    ],
)
def test_set_config_value_rejects_trusted_project_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    """project=True should reject keys ignored by project-config resolution."""
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", tmp_path / "global.toml")
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / ".memsearch.toml")

    with pytest.raises(ValueError, match="Project config cannot set trusted key"):
        set_config_value(key, "value", project=True)


@pytest.mark.parametrize(
    ("key", "value", "expected_error", "match"),
    [
        ("milvus", "x", ValueError, "Key must be section\\.field"),
        ("bad.uri", "x", KeyError, "Unknown config section: bad"),
        (
            "plugins.bad.summarize.model",
            "x",
            KeyError,
            "Unknown plugin platform: bad",
        ),
        (
            "milvus.not_a_field",
            "x",
            KeyError,
            "Unknown config field: not_a_field in section milvus",
        ),
    ],
)
def test_set_config_value_rejects_invalid_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: str,
    expected_error: type[Exception],
    match: str,
):
    """set_config_value should reject malformed/unknown dotted keys."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", cfg_path)

    with pytest.raises(expected_error, match=match):
        set_config_value(key, value)


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


def test_save_config_expands_user_in_string_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """save_config should expand '~' when given a string path."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    path = "~/.memsearch/test-config.toml"
    data = {"embedding": {"provider": "google"}}
    save_config(data, path)

    saved_path = fake_home / ".memsearch" / "test-config.toml"
    assert saved_path.is_file()
    assert load_config_file(saved_path) == data


def test_load_config_file_expands_user_in_string_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """load_config_file should expand '~' when given a string path."""
    fake_home = tmp_path / "home"
    config_dir = fake_home / ".memsearch"
    config_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))

    data = {"milvus": {"collection": "from-home"}}
    config_path = config_dir / "test-config.toml"
    with open(config_path, "wb") as f:
        tomli_w.dump(data, f)

    loaded = load_config_file("~/.memsearch/test-config.toml")
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


def test_plugins_config_defaults():
    """PluginsConfig should expose the supported platform summarize model keys."""
    cfg = PluginsConfig()
    assert cfg.claude_code.summarize.model == ""
    assert cfg.codex.summarize.model == ""
    assert cfg.opencode.summarize.model == ""
    assert cfg.openclaw.summarize.model == ""


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
            "plugins": {
                "claude-code": {
                    "summarize": {"model": "haiku", "provider": "ignored"},
                    "future": "ignored",
                },
                "unknown-plugin": {"summarize": {"model": "ignored"}},
            },
            "unknown_section": {"foo": "bar"},
        }
    )

    assert cfg.embedding.provider == "google"
    assert cfg.embedding.batch_size == 64
    assert cfg.milvus.uri == "~/.memsearch/milvus.db"
    assert cfg.compact.llm_provider == "anthropic"
    assert cfg.compact.llm_model == "claude-3-7-sonnet"
    assert cfg.plugins.claude_code.summarize.model == "haiku"
    assert cfg.plugins.codex.summarize.model == ""


def test_dict_to_config_accepts_empty_section_dicts() -> None:
    """Explicit empty section dicts should fall back to dataclass defaults."""
    cfg = _dict_to_config({"embedding": {}, "milvus": {}, "watch": {}})

    assert cfg.embedding.provider == "openai"
    assert cfg.milvus.collection == "memsearch_chunks"
    assert cfg.watch.debounce_ms == 1500
