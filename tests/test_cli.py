"""Tests for the CLI interface."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from memsearch.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Mock config paths to use temp directory."""
    monkeypatch.setattr("memsearch.cli.GLOBAL_CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr("memsearch.cli.PROJECT_CONFIG_PATH", tmp_path / "project.toml")
    return tmp_path


class TestConfigCommands:
    def test_config_init_creates_file(self, runner: CliRunner, mock_config_path: Path):
        """config init should create a config file."""
        result = runner.invoke(cli, ["config", "init"])
        assert result.exit_code == 0
        assert (mock_config_path / "config.toml").exists()

    def test_config_init_project_flag(self, runner: CliRunner, mock_config_path: Path):
        """config init --project should create project config."""
        result = runner.invoke(cli, ["config", "init", "--project"])
        assert result.exit_code == 0
        assert (mock_config_path / "project.toml").exists()

    def test_config_set_value(self, runner: CliRunner, mock_config_path: Path):
        """config set should update a config value."""
        # Initialize first
        runner.invoke(cli, ["config", "init"])
        
        result = runner.invoke(cli, ["config", "set", "milvus.uri", "http://test:19530"])
        assert result.exit_code == 0

    def test_config_list_shows_config(self, runner: CliRunner, mock_config_path: Path):
        """config list should show current configuration."""
        runner.invoke(cli, ["config", "init"])
        result = runner.invoke(cli, ["config", "list"])
        assert result.exit_code == 0
        assert "milvus" in result.output.lower() or "embedding" in result.output.lower()


class TestStatsCommand:
    @patch("memsearch.cli.MemSearch")
    def test_stats_shows_chunk_count(self, mock_memsearch_class: MagicMock, runner: CliRunner):
        """stats should display indexed chunk count."""
        mock_instance = MagicMock()
        mock_instance.stats.return_value = {"chunks": 42, "sources": 5}
        mock_memsearch_class.return_value = mock_instance
        
        result = runner.invoke(cli, ["stats"])
        assert result.exit_code == 0
        assert "42" in result.output or "chunk" in result.output.lower()


class TestCLIHelpers:
    def test_cli_version(self, runner: CliRunner):
        """CLI should respond to --version."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "memsearch" in result.output.lower()

    def test_cli_help(self, runner: CliRunner):
        """CLI should show help."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output