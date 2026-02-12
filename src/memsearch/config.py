"""Configuration system for memsearch.

Priority chain (lowest to highest):
  dataclass defaults → ~/.memsearch/config.toml → .memsearch.toml → CLI flags
"""

from __future__ import annotations

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
_INT_FIELDS = {"max_chunk_size", "overlap_lines", "debounce_ms"}


@dataclass
class MilvusConfig:
    uri: str = "~/.memsearch/milvus.db"
    token: str = ""
    collection: str = "memsearch_chunks"


@dataclass
class EmbeddingConfig:
    provider: str = "openai"
    model: str = ""


@dataclass
class CompactConfig:
    llm_provider: str = "openai"
    llm_model: str = ""
    prompt_file: str = ""


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


def _default_dict() -> dict[str, Any]:
    """Return MemSearchConfig defaults as a nested dict."""
    return asdict(MemSearchConfig())


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
    result = _default_dict()
    result = deep_merge(result, load_config_file(GLOBAL_CONFIG_PATH))
    result = deep_merge(result, load_config_file(PROJECT_CONFIG_PATH))
    if cli_overrides:
        result = deep_merge(result, cli_overrides)
    return _dict_to_config(result)


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
