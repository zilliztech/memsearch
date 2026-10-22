"""`memsearch compact --memory-dir` must reach `MemSearch.compact`."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from click.testing import CliRunner

from memsearch.cli import cli


class DummyMemSearch:
    last_kwargs: ClassVar[dict[str, Any]] = {}

    async def compact(self, **kwargs: Any) -> str:
        DummyMemSearch.last_kwargs = kwargs
        return ""

    def close(self) -> None:
        pass


def test_compact_help_lists_memory_dir() -> None:
    result = CliRunner().invoke(cli, ["compact", "--help"])

    assert result.exit_code == 0
    assert "--memory-dir" in result.output


def test_compact_forwards_memory_dir(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / "store-root" / "my-project"
    store.mkdir(parents=True)
    monkeypatch.setattr("memsearch.core.MemSearch", lambda **kwargs: DummyMemSearch())

    result = CliRunner().invoke(cli, ["compact", "--memory-dir", str(store)])

    assert result.exit_code == 0
    assert DummyMemSearch.last_kwargs["memory_dir"] == str(store)


def test_compact_without_memory_dir_forwards_none(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("memsearch.core.MemSearch", lambda **kwargs: DummyMemSearch())

    result = CliRunner().invoke(cli, ["compact", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert DummyMemSearch.last_kwargs["memory_dir"] is None


def test_compact_rejects_a_memory_dir_that_is_a_file(monkeypatch, tmp_path: Path) -> None:
    """A file must be refused by click, before any LLM call is paid for."""
    not_a_dir = tmp_path / "notes.md"
    not_a_dir.write_text("# note\n")
    DummyMemSearch.last_kwargs = {}
    monkeypatch.setattr("memsearch.core.MemSearch", lambda **kwargs: DummyMemSearch())

    result = CliRunner().invoke(cli, ["compact", "--memory-dir", str(not_a_dir)])

    assert result.exit_code == 2
    assert DummyMemSearch.last_kwargs == {}
