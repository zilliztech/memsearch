"""Configuration system for memsearch.

Priority chain (lowest to highest):
  dataclass defaults → ~/.memsearch/config.toml → .memsearch.toml → CLI flags
"""

from __future__ import annotations

import os
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import tomli_w

GLOBAL_CONFIG_PATH = Path("~/.memsearch/config.toml").expanduser()
PROJECT_CONFIG_PATH = Path(".memsearch.toml")

# Fields that should be parsed as int when set via CLI strings
_INT_FIELDS = {"max_chunk_size", "overlap_lines", "debounce_ms", "batch_size"}


@dataclass
class MilvusConfig:
    uri: str = "~/.memsearch/milvus.db"
    token: str = ""
    collection: str = "memsearch_chunks"


@dataclass
class EmbeddingConfig:
    provider: str = "openai"
    model: str = ""
    batch_size: int = 0  # 0 = use provider default
    base_url: str = ""  # OpenAI-compatible endpoint URL
    api_key: str = ""  # API key (supports "env:VAR_NAME" syntax)


@dataclass
class CompactConfig:
    llm_provider: str = "openai"
    llm_model: str = ""
    prompt_file: str = ""
    base_url: str = ""  # OpenAI-compatible endpoint URL
    api_key: str = ""  # API key (supports "env:VAR_NAME" syntax)


@dataclass
class ChunkingConfig:
    max_chunk_size: int = 1500
    overlap_lines: int = 2


@dataclass
class WatchConfig:
    debounce_ms: int = 1500


@dataclass
class MemSearchConfig:
    milvus: MilvusConfig = field(default_factory=MilvusConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    compact: CompactConfig = field(default_factory=CompactConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    watch: WatchConfig = field(default_factory=WatchConfig)


# -- Section name → dataclass mapping for typed reconstruction --
_SECTION_CLASSES: dict[str, type] = {
    "milvus": MilvusConfig,
    "embedding": EmbeddingConfig,
    "compact": CompactConfig,
    "chunking": ChunkingConfig,
    "watch": WatchConfig,
}


_ENV_PREFIX = "env:"

_EMBEDDING_API_KEY_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "voyage": "VOYAGE_API_KEY",
}
_COMPACT_API_KEY_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}
_OPENAI_BASE_URL_ENV_VAR = "OPENAI_BASE_URL"
_DEFAULT_COMPACT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-5-20250929",
    "gemini": "gemini-2.0-flash",
}


def resolve_env_ref(value: str) -> str:
    """Resolve an ``env:VAR_NAME`` reference to its environment variable value.

    If *value* starts with ``env:``, the remainder is used as an environment
    variable name.  Returns the variable's value, or raises ``KeyError`` if
    the variable is not set.  Non-prefixed strings are returned unchanged.
    """
    if not isinstance(value, str) or not value.startswith(_ENV_PREFIX):
        return value
    var_name = value[len(_ENV_PREFIX) :]
    env_val = os.environ.get(var_name)
    if env_val is None:
        raise KeyError(f"Environment variable {var_name!r} referenced in config (via {value!r}) is not set")
    return env_val


def _resolve_env_refs_in_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Walk a nested config dict and resolve all ``env:`` references."""
    resolved = {}
    for key, val in d.items():
        if isinstance(val, dict):
            resolved[key] = _resolve_env_refs_in_dict(val)
        elif isinstance(val, str) and val.startswith(_ENV_PREFIX):
            resolved[key] = resolve_env_ref(val)
        else:
            resolved[key] = val
    return resolved


def _default_dict() -> dict[str, Any]:
    """Return MemSearchConfig defaults as a nested dict."""
    return asdict(MemSearchConfig())


def _merged_config_dict(cli_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return config sources merged without resolving ``env:`` references."""
    result = _default_dict()
    result = deep_merge(result, load_config_file(GLOBAL_CONFIG_PATH))
    result = deep_merge(result, load_config_file(PROJECT_CONFIG_PATH))
    if cli_overrides:
        result = deep_merge(result, cli_overrides)
    return result


def load_config_file(path: Path | str) -> dict[str, Any]:
    """Read a TOML config file, returning a nested dict (or {} if missing)."""
    p = Path(path).expanduser()
    if not p.is_file():
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*.

    ``None`` values in *override* are treated as "not set" and skipped.
    Empty strings are valid overrides and are NOT skipped.
    """
    merged = dict(base)
    for key, val in override.items():
        if val is None:
            continue
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def _dict_to_config(d: dict[str, Any]) -> MemSearchConfig:
    """Convert a nested dict to a MemSearchConfig, ignoring unknown keys."""
    kwargs: dict[str, Any] = {}
    for section_name, cls in _SECTION_CLASSES.items():
        section_data = d.get(section_name, {})
        if not isinstance(section_data, dict):
            continue
        valid = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in section_data.items() if k in valid}
        kwargs[section_name] = cls(**filtered)
    return MemSearchConfig(**kwargs)


def resolve_config(cli_overrides: dict[str, Any] | None = None) -> MemSearchConfig:
    """Layer all config sources and return the final MemSearchConfig.

    Priority (lowest → highest):
      defaults → global TOML → project TOML → cli_overrides
    """
    result = _merged_config_dict(cli_overrides)
    result = _resolve_env_refs_in_dict(result)
    cfg = _dict_to_config(result)

    # Fill in the provider's default model when model is empty
    if not cfg.embedding.model:
        from .embeddings import DEFAULT_MODELS

        cfg.embedding.model = DEFAULT_MODELS.get(cfg.embedding.provider, "")

    return cfg


def _source_value(config_dict: dict[str, Any], section: str, field_name: str) -> Any:
    section_dict = config_dict.get(section, {})
    if not isinstance(section_dict, dict):
        return None
    return section_dict.get(field_name)


def _has_source_value(config_dict: dict[str, Any], section: str, field_name: str) -> bool:
    section_dict = config_dict.get(section, {})
    return isinstance(section_dict, dict) and field_name in section_dict


def _value_origin(section: str, field_name: str, cli_overrides: dict[str, Any] | None = None) -> tuple[str, Any]:
    """Return the highest-priority origin and raw value for a config field."""
    sources = (
        ("cli", cli_overrides or {}),
        ("project", load_config_file(PROJECT_CONFIG_PATH)),
        ("global", load_config_file(GLOBAL_CONFIG_PATH)),
    )
    for source_name, data in sources:
        if not _has_source_value(data, section, field_name):
            continue
        value = _source_value(data, section, field_name)
        if value is not None:
            return source_name, value

    default_value = _source_value(_default_dict(), section, field_name)
    if default_value not in (None, ""):
        return "default", default_value

    return "missing", None


def _setting_status(
    section: str,
    field_name: str,
    *,
    fallback_env_var: str | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe whether a config setting is effectively available."""
    source, raw_value = _value_origin(section, field_name, cli_overrides)
    status: dict[str, Any] = {"source": source, "configured": False}

    if isinstance(raw_value, str) and raw_value.startswith(_ENV_PREFIX):
        env_var = raw_value[len(_ENV_PREFIX) :]
        status["env_var"] = env_var
        status["configured"] = bool(os.environ.get(env_var))
        return status

    if raw_value not in (None, ""):
        status["configured"] = True
        return status

    if source != "missing":
        return status

    if fallback_env_var:
        status["env_var"] = fallback_env_var
        status["configured"] = bool(os.environ.get(fallback_env_var))
        status["source"] = "environment" if status["configured"] else "missing"

    return status


def get_config_status(cli_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return hook-friendly status for resolved backend configuration.

    The status deliberately avoids returning secret values. Instead it reports
    which source currently wins (project/global/default/environment), whether
    required settings are configured, and non-secret resolved values that the
    shell hooks need for status display.
    """
    merged = _merged_config_dict(cli_overrides)

    embedding_provider = str(merged["embedding"]["provider"])
    embedding_model = str(merged["embedding"]["model"])
    if not embedding_model:
        from .embeddings import DEFAULT_MODELS

        embedding_model = DEFAULT_MODELS.get(embedding_provider, "")

    compact_provider = str(merged["compact"]["llm_provider"])
    compact_model = str(merged["compact"]["llm_model"]) or _DEFAULT_COMPACT_MODELS.get(compact_provider, "")

    embedding_api_key = _setting_status(
        "embedding",
        "api_key",
        fallback_env_var=_EMBEDDING_API_KEY_ENV_VARS.get(embedding_provider),
        cli_overrides=cli_overrides,
    )
    embedding_base_url = _setting_status(
        "embedding",
        "base_url",
        fallback_env_var=_OPENAI_BASE_URL_ENV_VAR if embedding_provider == "openai" else None,
        cli_overrides=cli_overrides,
    )
    compact_api_key = _setting_status(
        "compact",
        "api_key",
        fallback_env_var=_COMPACT_API_KEY_ENV_VARS.get(compact_provider),
        cli_overrides=cli_overrides,
    )
    compact_base_url = _setting_status(
        "compact",
        "base_url",
        fallback_env_var=_OPENAI_BASE_URL_ENV_VAR if compact_provider == "openai" else None,
        cli_overrides=cli_overrides,
    )

    embedding_requires_api_key = embedding_provider in _EMBEDDING_API_KEY_ENV_VARS
    compact_requires_api_key = compact_provider in _COMPACT_API_KEY_ENV_VARS
    milvus_uri = _source_value(merged, "milvus", "uri")
    milvus_collection = _source_value(merged, "milvus", "collection")

    return {
        "embedding": {
            "provider": embedding_provider,
            "model": embedding_model,
            "ready": embedding_api_key["configured"] if embedding_requires_api_key else True,
            "requires_api_key": embedding_requires_api_key,
            "api_key": embedding_api_key,
            "base_url": embedding_base_url,
        },
        "compact": {
            "provider": compact_provider,
            "model": compact_model,
            "ready": compact_api_key["configured"] if compact_requires_api_key else True,
            "requires_api_key": compact_requires_api_key,
            "api_key": compact_api_key,
            "base_url": compact_base_url,
        },
        "milvus": {
            "uri": str(os.environ.get(milvus_uri[len(_ENV_PREFIX) :], milvus_uri))
            if isinstance(milvus_uri, str) and milvus_uri.startswith(_ENV_PREFIX)
            else str(milvus_uri),
            "collection": str(os.environ.get(milvus_collection[len(_ENV_PREFIX) :], milvus_collection))
            if isinstance(milvus_collection, str) and milvus_collection.startswith(_ENV_PREFIX)
            else str(milvus_collection),
        },
    }


def save_config(cfg_dict: dict[str, Any], path: Path | str) -> None:
    """Write a config dict to a TOML file."""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        tomli_w.dump(cfg_dict, f)


def config_to_dict(cfg: MemSearchConfig) -> dict[str, Any]:
    """Convert a MemSearchConfig to a nested dict (for saving)."""
    return asdict(cfg)


def get_config_value(key: str, cfg: MemSearchConfig | None = None) -> Any:
    """Get a config value by dotted key (e.g. ``milvus.uri``).

    If *cfg* is None, resolves the full config from all sources first.
    """
    if cfg is None:
        cfg = resolve_config()
    d = asdict(cfg)
    parts = key.split(".")
    current: Any = d
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Unknown config key: {key}")
        current = current[part]
    return current


def set_config_value(key: str, value: Any, *, project: bool = False) -> None:
    """Set a single config value by dotted key and persist to TOML.

    Parameters
    ----------
    key:
        Dotted key like ``milvus.uri``.
    value:
        The value to set.
    project:
        If True, write to ``.memsearch.toml``; otherwise to the
        global ``~/.memsearch/config.toml``.
    """
    path = PROJECT_CONFIG_PATH if project else GLOBAL_CONFIG_PATH
    existing = load_config_file(path)

    parts = key.split(".")
    if len(parts) != 2:
        raise ValueError(f"Key must be section.field (got {key!r})")
    section, field_name = parts

    # Validate key
    if section not in _SECTION_CLASSES:
        raise KeyError(f"Unknown config section: {section}")
    cls = _SECTION_CLASSES[section]
    valid = {f.name for f in fields(cls)}
    if field_name not in valid:
        raise KeyError(f"Unknown config field: {field_name} in section {section}")

    # Auto-convert int fields
    if field_name in _INT_FIELDS and isinstance(value, str):
        value = int(value)

    existing.setdefault(section, {})[field_name] = value
    save_config(existing, path)
