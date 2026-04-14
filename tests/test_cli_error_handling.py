from __future__ import annotations

from click.testing import CliRunner
from pymilvus.exceptions import MilvusException

from memsearch import cli as cli_module
from memsearch import store as store_module
from memsearch.cli import cli
from memsearch.config import ConfigEnvVarError, MemSearchConfig


def test_stats_shows_friendly_config_error(monkeypatch) -> None:
    def fake_resolve_config(_overrides=None):
        raise ConfigEnvVarError("Environment variable 'MISSING_KEY' referenced in config is not set")

    monkeypatch.setattr(cli_module, "resolve_config", fake_resolve_config)

    runner = CliRunner()
    result = runner.invoke(cli, ["stats"])

    assert result.exit_code == 1
    assert "Configuration error:" in result.stderr
    assert "MISSING_KEY" in result.stderr


def test_stats_shows_friendly_milvus_error(monkeypatch) -> None:
    class BrokenStore:
        def __init__(self, **_kwargs):
            raise MilvusException(code=2, message="server unavailable")

    monkeypatch.setattr(cli_module, "resolve_config", lambda _overrides=None: MemSearchConfig())
    monkeypatch.setattr(store_module, "MilvusStore", BrokenStore)

    runner = CliRunner()
    result = runner.invoke(cli, ["stats"])

    assert result.exit_code == 1
    assert "Milvus error (code 2):" in result.stderr
    assert "server unavailable" in result.stderr


def test_unrelated_key_error_is_not_swallowed(monkeypatch) -> None:
    """A bare KeyError from config resolution (e.g. a programming bug) must
    surface as a traceback, not be misreported as a user config error."""

    def fake_resolve_config(_overrides=None):
        raise KeyError("internal_lookup_bug")

    monkeypatch.setattr(cli_module, "resolve_config", fake_resolve_config)

    runner = CliRunner()
    result = runner.invoke(cli, ["stats"])

    assert result.exit_code != 0
    assert "Configuration error:" not in (result.stderr or "")
    assert isinstance(result.exception, KeyError)
    assert not isinstance(result.exception, ConfigEnvVarError)


def test_missing_env_var_in_real_resolve(monkeypatch) -> None:
    """End-to-end: a real env:VAR config with an unset var produces a
    friendly error, exercising ConfigEnvVarError through resolve_config."""
    monkeypatch.delenv("DEFINITELY_NOT_SET_MEMSEARCH_API_KEY", raising=False)

    def fake_load(_path):
        return {"embedding": {"api_key": "env:DEFINITELY_NOT_SET_MEMSEARCH_API_KEY"}}

    monkeypatch.setattr(cli_module, "resolve_config", cli_module.resolve_config)
    # Patch the loader inside the real resolve_config pipeline.
    from memsearch import config as config_module

    monkeypatch.setattr(config_module, "load_config_file", fake_load)

    runner = CliRunner()
    result = runner.invoke(cli, ["stats"])

    assert result.exit_code == 1
    assert "Configuration error:" in result.stderr
    assert "DEFINITELY_NOT_SET_MEMSEARCH_API_KEY" in result.stderr
