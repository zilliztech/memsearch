from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from memsearch import cli as cli_module
from memsearch.cli import cli


class DummyMemSearch:
    last_source = None
    last_prompt_template = None

    async def compact(self, **kwargs):
        DummyMemSearch.last_source = kwargs["source"]
        DummyMemSearch.last_prompt_template = kwargs["prompt_template"]
        return ""

    def close(self) -> None:
        pass


def test_normalize_compact_source_resolves_existing_relative_path(tmp_path: Path):
    note = tmp_path / "memory" / "old-notes.md"
    note.parent.mkdir()
    note.write_text("# note\n")

    cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        normalized = cli_module._normalize_compact_source("./memory/old-notes.md")
    finally:
        os.chdir(cwd)

    assert normalized == str(note.resolve())


def test_normalize_compact_source_expands_user_home(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    note = home / "memory" / "old-notes.md"
    note.parent.mkdir(parents=True)
    note.write_text("# note\n")

    monkeypatch.setenv("HOME", str(home))

    normalized = cli_module._normalize_compact_source("~/memory/old-notes.md")

    assert normalized == str(note.resolve())


def test_normalize_compact_source_leaves_non_path_filters_unchanged() -> None:
    source = "session:abc123"

    assert cli_module._normalize_compact_source(source) == source


def test_compact_shows_matched_source_when_no_chunks(monkeypatch, tmp_path: Path):
    note = tmp_path / "memory" / "old-notes.md"
    note.parent.mkdir()
    note.write_text("# note\n")

    monkeypatch.setattr("memsearch.core.MemSearch", lambda **kwargs: DummyMemSearch())

    runner = CliRunner()
    result = runner.invoke(cli, ["compact", "--source", str(note)])

    assert result.exit_code == 0
    assert DummyMemSearch.last_source == str(note.resolve())
    assert f"No chunks matched source: {note.resolve()}" in result.output


def test_compact_reads_prompt_file_and_passes_template(monkeypatch, tmp_path: Path):
    note = tmp_path / "memory" / "old-notes.md"
    note.parent.mkdir()
    note.write_text("# note\n")
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Summarize carefully:\n{chunks}\n", encoding="utf-8")

    monkeypatch.setattr("memsearch.core.MemSearch", lambda **kwargs: DummyMemSearch())

    runner = CliRunner()
    result = runner.invoke(cli, ["compact", "--source", str(note), "--prompt-file", str(prompt_file)])

    assert result.exit_code == 0
    assert DummyMemSearch.last_prompt_template == "Summarize carefully:\n{chunks}\n"
