"""Tests for CLI help and version commands."""

from __future__ import annotations

from click.testing import CliRunner

from memsearch.cli import cli


class TestCLIHelp:
    def test_cli_main_help(self):
        """Main CLI should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_cli_version(self):
        """CLI should respond to version flag."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "version" in result.output

    def test_config_help(self):
        """Config command should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_index_help(self):
        """Index command should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["index", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_search_help(self):
        """Search command should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_stats_help(self):
        """Stats command should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["stats", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_watch_help(self):
        """Watch command should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["watch", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_compact_help(self):
        """Compact command should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["compact", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_expand_help(self):
        """Expand command should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["expand", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_transcript_help(self):
        """Transcript command should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["transcript", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_reset_help(self):
        """Reset command should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["reset", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_config_init_help(self):
        """Config init command should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "init", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_config_set_help(self):
        """Config set command should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "set", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_config_get_help(self):
        """Config get command should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "get", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_config_list_help(self):
        """Config list command should have help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "list", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
