"""Tests for CLI help and version commands."""

from __future__ import annotations

from click.testing import CliRunner

from memsearch.cli import _normalize_compact_source, cli


class TestCLIHelp:
    def test_compact_source_normalization(self):
        """Relative compact source paths should normalize to absolute paths."""
        rel = "./memory/old-notes.md"
        normalized, is_prefix = _normalize_compact_source(rel)
        assert normalized is not None
        assert normalized.startswith("/")
        assert normalized.endswith("memory/old-notes.md")
        assert is_prefix is False

    def test_compact_source_normalization_none(self):
        """None source should remain None."""
        normalized, is_prefix = _normalize_compact_source(None)
        assert normalized is None
        assert is_prefix is False

    def test_compact_source_directory_prefix(self, tmp_path):
        """Directory source should normalize to prefix mode."""
        source_dir = tmp_path / "memory"
        source_dir.mkdir()
        normalized, is_prefix = _normalize_compact_source(str(source_dir))
        assert normalized is not None
        assert normalized.endswith("/memory/")
        assert is_prefix is True

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
        assert "memsearch" in result.output

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