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
class RerankerConfig:
    model: str = ""  # empty = disabled; set to model ID to enable


@dataclass
class LLMConfig:
    """LLM settings for memsearch-managed summarization jobs.

    All fields default to empty.  When empty, the ``compact`` CLI falls back to
    ``[compact].llm_provider`` (deprecated) or ``"openai"``.
    """

    provider: str = ""  # empty = compact defaults to openai; "openai"/"anthropic"/"gemini" for explicit
    model: str = ""
    base_url: str = ""  # OpenAI-compatible endpoint URL
    api_key: str = ""  # API key (supports "env:VAR_NAME" syntax)
    providers: dict[str, LLMProviderConfig] = field(default_factory=dict)


@dataclass
class LLMProviderConfig:
    """Named LLM provider settings for plugin summarization routing."""

    type: str = ""
    model: str = ""
    base_url: str = ""
    api_key: str = ""  # supports "env:VAR_NAME" syntax


@dataclass
class PromptsConfig:
    """Paths to custom prompt template files.

    Empty string means "use built-in default".
    """

    compact: str = ""  # custom prompt file for memsearch compact
    summarize: str = ""  # custom prompt file for plugin session summarization


@dataclass
class PluginSummarizeConfig:
    """Plugin summarization settings."""

    provider: str = ""  # empty/native = keep plugin-native summarization path
    model: str = ""  # empty = keep plugin default/native model selection


@dataclass
class PluginPlatformConfig:
    """Settings for one platform plugin."""

    summarize: PluginSummarizeConfig = field(default_factory=PluginSummarizeConfig)


@dataclass
class PluginsConfig:
    """Platform plugin settings.

    Python field names use underscores where TOML keys use hyphens.
    """

    claude_code: PluginPlatformConfig = field(default_factory=PluginPlatformConfig)
    codex: PluginPlatformConfig = field(default_factory=PluginPlatformConfig)
    opencode: PluginPlatformConfig = field(default_factory=PluginPlatformConfig)
    openclaw: PluginPlatformConfig = field(default_factory=PluginPlatformConfig)


@dataclass
class MemSearchConfig:
    milvus: MilvusConfig = field(default_factory=MilvusConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    compact: CompactConfig = field(default_factory=CompactConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    watch: WatchConfig = field(default_factory=WatchConfig)
    reranker: RerankerConfig = field(default_factory=RerankerConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    prompts: PromptsConfig = field(default_factory=PromptsConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)


# -- Section name → dataclass mapping for typed reconstruction --
_SECTION_CLASSES: dict[str, type] = {
    "milvus": MilvusConfig,
    "embedding": EmbeddingConfig,
    "compact": CompactConfig,
    "chunking": ChunkingConfig,
    "watch": WatchConfig,
    "reranker": RerankerConfig,
    "llm": LLMConfig,
    "prompts": PromptsConfig,
    "plugins": PluginsConfig,
}

_PLUGIN_KEY_TO_FIELD = {
    "claude-code": "claude_code",
    "claude_code": "claude_code",
    "codex": "codex",
    "opencode": "opencode",
    "openclaw": "openclaw",
}
_PLUGIN_FIELD_TO_KEY = {
    "claude_code": "claude-code",
    "codex": "codex",
    "opencode": "opencode",
    "openclaw": "openclaw",
}


_ENV_PREFIX = "env:"


class ConfigEnvVarError(KeyError):
    """Raised when an ``env:VAR_NAME`` reference points at an unset variable.

    Subclasses ``KeyError`` so any existing `except KeyError` still catches it,
    but allows the CLI layer to distinguish env-ref failures from unrelated
    dict-lookup bugs that should not be reported as configuration errors.
    """


def resolve_env_ref(value: str) -> str:
    """Resolve an ``env:VAR_NAME`` reference to its environment variable value.

    If *value* starts with ``env:``, the remainder is used as an environment
    variable name.  Returns the variable's value, or raises
    :class:`ConfigEnvVarError` if the variable is not set.  Non-prefixed
    strings are returned unchanged.
    """
    if not isinstance(value, str) or not value.startswith(_ENV_PREFIX):
        return value
    var_name = value[len(_ENV_PREFIX) :]
    env_val = os.environ.get(var_name)
    if env_val is None:
        raise ConfigEnvVarError(f"Environment variable {var_name!r} referenced in config (via {value!r}) is not set")
    return env_val


def _resolve_env_refs_in_dict(d: dict[str, Any], path: tuple[str, ...] = ()) -> dict[str, Any]:
    """Walk a nested config dict and resolve all ``env:`` references."""
    resolved = {}
    for key, val in d.items():
        child_path = (*path, key)
        if isinstance(val, dict):
            resolved[key] = _resolve_env_refs_in_dict(val, child_path)
        elif isinstance(val, str) and val.startswith(_ENV_PREFIX):
            if len(child_path) == 4 and child_path[0] == "llm" and child_path[1] == "providers":
                # Named LLM providers are selected lazily by plugin summarization.
                # Keep env refs raw here so unused providers do not break unrelated
                # config commands. The selected provider resolves env refs when used.
                resolved[key] = val
            else:
                resolved[key] = resolve_env_ref(val)
        else:
            resolved[key] = val
    return resolved


def _default_dict() -> dict[str, Any]:
    """Return MemSearchConfig defaults as a nested dict."""
    return config_to_dict(MemSearchConfig())


def _plugins_to_dict(cfg: PluginsConfig) -> dict[str, Any]:
    """Convert plugin config to TOML-facing keys."""
    data = asdict(cfg)
    return {_PLUGIN_FIELD_TO_KEY[key]: value for key, value in data.items()}


def _dict_to_plugins_config(section_data: dict[str, Any]) -> PluginsConfig:
    """Convert a TOML plugins table to PluginsConfig."""
    kwargs: dict[str, Any] = {}
    valid_platform_fields = {f.name for f in fields(PluginPlatformConfig)}
    valid_summarize_fields = {f.name for f in fields(PluginSummarizeConfig)}

    for raw_platform, raw_platform_data in section_data.items():
        platform = _PLUGIN_KEY_TO_FIELD.get(raw_platform)
        if not platform or not isinstance(raw_platform_data, dict):
            continue

        platform_kwargs: dict[str, Any] = {}
        summarize_data = raw_platform_data.get("summarize", {})
        if isinstance(summarize_data, dict):
            summarize_filtered = {k: v for k, v in summarize_data.items() if k in valid_summarize_fields}
            platform_kwargs["summarize"] = PluginSummarizeConfig(**summarize_filtered)

        filtered = {k: v for k, v in raw_platform_data.items() if k in valid_platform_fields and k != "summarize"}
        platform_kwargs.update(filtered)
        kwargs[platform] = PluginPlatformConfig(**platform_kwargs)

    return PluginsConfig(**kwargs)


def _dict_to_llm_config(section_data: dict[str, Any]) -> LLMConfig:
    """Convert a TOML llm table to LLMConfig, preserving named providers."""
    valid = {f.name for f in fields(LLMConfig) if f.name != "providers"}
    kwargs = {k: v for k, v in section_data.items() if k in valid}
    provider_items = section_data.get("providers", {})
    providers: dict[str, LLMProviderConfig] = {}
    if isinstance(provider_items, dict):
        valid_provider_fields = {f.name for f in fields(LLMProviderConfig)}
        for name, raw_provider in provider_items.items():
            if not isinstance(name, str) or not isinstance(raw_provider, dict):
                continue
            filtered = {k: v for k, v in raw_provider.items() if k in valid_provider_fields}
            providers[name] = LLMProviderConfig(**filtered)
    kwargs["providers"] = providers
    return LLMConfig(**kwargs)


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
        if section_name == "plugins":
            kwargs[section_name] = _dict_to_plugins_config(section_data)
            continue
        if section_name == "llm":
            kwargs[section_name] = _dict_to_llm_config(section_data)
            continue
        valid = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in section_data.items() if k in valid}
        kwargs[section_name] = cls(**filtered)
    return MemSearchConfig(**kwargs)


def _has_legacy_compact(global_cfg: dict[str, Any], project_cfg: dict[str, Any]) -> bool:
    """Check if the user's actual config files contain a [compact] section."""
    return "compact" in global_cfg or "compact" in project_cfg


def resolve_config(cli_overrides: dict[str, Any] | None = None) -> MemSearchConfig:
    """Layer all config sources and return the final MemSearchConfig.

    Priority (lowest → highest):
      defaults → global TOML → project TOML → cli_overrides
    """
    result = _default_dict()
    global_cfg = load_config_file(GLOBAL_CONFIG_PATH)
    project_cfg = load_config_file(PROJECT_CONFIG_PATH)
    result = deep_merge(result, global_cfg)
    result = deep_merge(result, project_cfg)
    if cli_overrides:
        result = deep_merge(result, cli_overrides)
    result = _resolve_env_refs_in_dict(result)
    cfg = _dict_to_config(result)

    # Warn about deprecated [compact] section in user config files
    if _has_legacy_compact(global_cfg, project_cfg):
        import warnings

        warnings.warn(
            "[compact] config section is deprecated. "
            "Move LLM settings to [llm] and prompt settings to [prompts]. "
            "See https://memsearch.dev/configuration for details.",
            DeprecationWarning,
            stacklevel=2,
        )

    # Fill in the provider's default model when model is empty
    if not cfg.embedding.model:
        from .embeddings import DEFAULT_MODELS

        cfg.embedding.model = DEFAULT_MODELS.get(cfg.embedding.provider, "")

    return cfg


def save_config(cfg_dict: dict[str, Any], path: Path | str) -> None:
    """Write a config dict to a TOML file."""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        tomli_w.dump(cfg_dict, f)


def config_to_dict(cfg: MemSearchConfig) -> dict[str, Any]:
    """Convert a MemSearchConfig to a nested dict (for saving)."""
    data = asdict(cfg)
    data["plugins"] = _plugins_to_dict(cfg.plugins)
    return data


def _validate_dotted_key(parts: list[str]) -> str:
    """Validate a dotted config key and return its final field name."""
    if len(parts) < 2:
        raise ValueError(f"Key must be section.field (got {'.'.join(parts)!r})")

    section = parts[0]
    if section not in _SECTION_CLASSES:
        raise KeyError(f"Unknown config section: {section}")

    if section == "plugins":
        if len(parts) != 4:
            raise ValueError(
                f"Plugin config keys must be plugins.<platform>.summarize.<field> (got {'.'.join(parts)!r})"
            )
        platform, subsection, field_name = parts[1:]
        if platform not in _PLUGIN_KEY_TO_FIELD:
            raise KeyError(f"Unknown plugin platform: {platform}")
        if subsection != "summarize":
            raise KeyError(f"Unknown plugin config section: {subsection} in platform {platform}")
        valid = {f.name for f in fields(PluginSummarizeConfig)}
        if field_name not in valid:
            raise KeyError(f"Unknown plugin summarize field: {field_name} in platform {platform}")
        return field_name

    if section == "llm" and len(parts) == 4 and parts[1] == "providers":
        _, _, provider_name, field_name = parts
        if not provider_name:
            raise KeyError("LLM provider name must not be empty")
        valid = {f.name for f in fields(LLMProviderConfig)}
        if field_name not in valid:
            raise KeyError(f"Unknown LLM provider field: {field_name}")
        return field_name

    if len(parts) != 2:
        raise ValueError(f"Key must be section.field (got {'.'.join(parts)!r})")

    field_name = parts[1]
    cls = _SECTION_CLASSES[section]
    valid = {f.name for f in fields(cls)}
    if field_name not in valid:
        raise KeyError(f"Unknown config field: {field_name} in section {section}")
    return field_name


def get_config_value(key: str, cfg: MemSearchConfig | None = None) -> Any:
    """Get a config value by dotted key (e.g. ``milvus.uri``).

    If *cfg* is None, resolves the full config from all sources first.
    """
    if cfg is None:
        cfg = resolve_config()
    d = config_to_dict(cfg)
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
    field_name = _validate_dotted_key(parts)

    # Auto-convert int fields
    if field_name in _INT_FIELDS and isinstance(value, str):
        value = int(value)

    current: dict[str, Any] = existing
    for part in parts[:-1]:
        next_value = current.setdefault(part, {})
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value
    save_config(existing, path)
