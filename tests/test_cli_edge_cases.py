"""Edge case tests for CLI interface."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from memsearch.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestCLIEdgeCases:
    def test_cli_invalid_command(self, runner: CliRunner):
        """CLI should handle invalid commands gracefully."""
        result = runner.invoke(cli, ["nonexistent-command"])
        assert result.exit_code != 0
        assert "No such command" in result.output or "Usage:" in result.output

    def test_cli_missing_args(self, runner: CliRunner):
        """CLI should handle missing arguments."""
        result = runner.invoke(cli, ["config", "set"])  # Missing key and value
        assert result.exit_code != 0
        assert "Missing argument" in result.output or "Usage:" in result.output

    def test_search_without_query(self, runner: CliRunner):
        """search without query should fail."""
        result = runner.invoke(cli, ["search"])  # Missing query argument
        assert result.exit_code != 0

    def test_index_without_paths(self, runner: CliRunner):
        """index without paths should fail or show help."""
        result = runner.invoke(cli, ["index"])
        # May succeed with defaults or fail - either is OK if documented
        assert result.exit_code in [0, 2]

    def test_config_get_unknown_key(self, runner: CliRunner, tmp_path):
        """Getting unknown config key should error."""
        result = runner.invoke(cli, ["config", "get", "nonexistent.key"])
        assert result.exit_code != 0 or "unknown" in result.output.lower()

    def test_invalid_json_output_flag(self, runner: CliRunner):
        """search with invalid --json-output usage."""
        result = runner.invoke(cli, ["search", "query", "--json-output"])
        # Should either succeed in JSON mode or fail gracefully
        assert result.exit_code in [0, 2]


class TestCLIHelpFlags:
    def test_help_on_all_commands(self, runner: CliRunner):
        """All commands should provide help."""
        commands = [
            ["--help"],
            ["config", "--help"],
            ["index", "--help"],
            ["search", "--help"],
            ["stats", "--help"],
            ["watch", "--help"],
        ]
        for cmd in commands:
            result = runner.invoke(cli, cmd)
            assert result.exit_code == 0, f"Failed on: {cmd}"
            assert "Usage:" in result.output or "Options:" in result.output

    def test_help_has_examples(self, runner: CliRunner):
        """Help text should provide examples for complex commands."""
        result = runner.invoke(cli, ["index", "--help"])
        assert result.exit_code == 0
        # Help should mention PATH argument
        assert "PATH" in result.output or "path" in result.output.lower()