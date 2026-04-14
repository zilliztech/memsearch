from __future__ import annotations

from click.testing import CliRunner
from pymilvus.exceptions import MilvusException

from memsearch import cli as cli_module
from memsearch.cli import cli
from memsearch.config import MemSearchConfig
from memsearch import store as store_module


def test_stats_shows_friendly_config_error(monkeypatch) -> None:
    def fake_resolve_config(_overrides=None):
        raise KeyError("Environment variable 'MISSING_KEY' referenced in config is not set")

    monkeypatch.setattr(cli_module, "resolve_config", fake_resolve_config)

    runner = CliRunner()
    result = runner.invoke(cli, ["stats"])

    assert result.exit_code == 1
    assert "Configuration error:" in result.output
    assert "MISSING_KEY" in result.output


def test_stats_shows_friendly_milvus_error(monkeypatch) -> None:
    class BrokenStore:
        def __init__(self, **_kwargs):
            raise MilvusException(code=2, message="server unavailable")

    monkeypatch.setattr(cli_module, "resolve_config", lambda _overrides=None: MemSearchConfig())
    monkeypatch.setattr(store_module, "MilvusStore", BrokenStore)

    runner = CliRunner()
    result = runner.invoke(cli, ["stats"])

    assert result.exit_code == 1
    assert "Milvus error:" in result.output
    assert "server unavailable" in result.output
