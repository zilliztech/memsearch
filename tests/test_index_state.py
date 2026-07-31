from __future__ import annotations

import json
import time
from pathlib import Path

from click.testing import CliRunner

from memsearch import cli as cli_module
from memsearch import core as core_module
from memsearch import index_state as index_state_module
from memsearch.cli import cli
from memsearch.config import MemSearchConfig
from memsearch.index_report import IndexFailure, IndexReport
from memsearch.index_state import (
    load_index_state,
    record_index_error,
    record_index_report,
    record_index_started,
    resolve_index_state_path,
)


def test_resolve_index_state_path_uses_explicit_memsearch_dir(tmp_path: Path) -> None:
    state_path = resolve_index_state_path([tmp_path / "docs"], memsearch_dir=tmp_path / ".memsearch")

    assert state_path == (tmp_path / ".memsearch" / ".index-state.json").resolve()


def test_resolve_index_state_path_infers_memsearch_root(tmp_path: Path) -> None:
    memory_dir = tmp_path / ".memsearch" / "memory"

    state_path = resolve_index_state_path([memory_dir / "2026-07-20.md"])

    assert state_path == tmp_path / ".memsearch" / ".index-state.json"


def test_resolve_index_state_path_skips_arbitrary_paths(tmp_path: Path) -> None:
    state_path = resolve_index_state_path([tmp_path / "docs"])

    assert state_path is None


def test_index_state_success_clears_previous_error(tmp_path: Path) -> None:
    state_path = tmp_path / ".memsearch" / ".index-state.json"
    paths = [tmp_path / ".memsearch" / "memory"]

    record_index_started(state_path, operation="index", paths=paths, collection="c", milvus_uri="lite.db")
    record_index_error(
        state_path,
        RuntimeError("provider timeout"),
        operation="index",
        paths=paths,
        collection="c",
        milvus_uri="lite.db",
    )
    record_index_report(
        state_path,
        IndexReport(indexed_chunks=3, total_files=1, indexed_files=1),
        operation="index",
        paths=paths,
        collection="c",
        milvus_uri="lite.db",
    )

    state = load_index_state(state_path)
    assert state["status"] == "ok"
    assert state["indexed_chunks"] == 3
    assert state["last_success_at"]
    assert "last_error" not in state
    assert state["failed_files"] == []


def test_index_state_degraded_preserves_previous_success(tmp_path: Path) -> None:
    state_path = tmp_path / ".memsearch" / ".index-state.json"
    paths = [tmp_path / ".memsearch" / "memory"]

    record_index_report(
        state_path,
        IndexReport(indexed_chunks=3, total_files=1, indexed_files=1),
        operation="index",
        paths=paths,
        collection="c",
        milvus_uri="lite.db",
    )
    success_at = load_index_state(state_path)["last_success_at"]
    record_index_report(
        state_path,
        IndexReport(
            indexed_chunks=2,
            total_files=2,
            indexed_files=1,
            failed_files=(IndexFailure(path="bad.md", error="RuntimeError: broken"),),
        ),
        operation="index",
        paths=paths,
        collection="c",
        milvus_uri="lite.db",
    )

    state = load_index_state(state_path)
    assert state["status"] == "degraded"
    assert state["last_success_at"] == success_at
    assert state["last_failed_at"]
    assert state["failed_files"] == [{"path": "bad.md", "error": "RuntimeError: broken"}]


def test_index_state_write_failures_are_best_effort(monkeypatch, tmp_path: Path) -> None:
    def fail_save(_state_path, _state):
        raise OSError("read-only state directory")

    monkeypatch.setattr(index_state_module, "_save_index_state", fail_save)

    record_index_started(
        tmp_path / ".memsearch" / ".index-state.json",
        operation="index",
        paths=[tmp_path / ".memsearch" / "memory"],
        collection="c",
        milvus_uri="lite.db",
    )


def test_cli_index_records_ok_state(monkeypatch, tmp_path: Path) -> None:
    memory_dir = tmp_path / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)

    class FakeMemSearch:
        def __init__(self, paths, **kwargs):
            assert paths == [str(memory_dir)]
            assert kwargs["collection"] == "memsearch_chunks"

        async def index_with_report(self, *, force=False):
            assert force is False
            return IndexReport(indexed_chunks=7, total_files=2, indexed_files=2)

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli_module, "resolve_config", lambda _overrides=None: MemSearchConfig())
    monkeypatch.setattr(core_module, "MemSearch", FakeMemSearch)

    result = CliRunner().invoke(cli, ["index", str(memory_dir)])

    assert result.exit_code == 0
    assert "Indexed 7 chunks." in result.output
    state = json.loads((tmp_path / ".memsearch" / ".index-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "ok"
    assert state["indexed_chunks"] == 7
    assert state["total_files"] == 2


def test_cli_index_combines_configured_and_one_off_ignore_rules(monkeypatch, tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    cfg = MemSearchConfig()
    cfg.indexing.ignore_files = [".gitignore"]
    cfg.indexing.exclude = ["generated/**"]
    captured: dict = {}

    class FakeMemSearch:
        def __init__(self, paths, **kwargs):
            captured["paths"] = paths
            captured["kwargs"] = kwargs

        async def index_with_report(self, *, force=False):
            return IndexReport(indexed_chunks=0, total_files=0, indexed_files=0)

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli_module, "resolve_config", lambda _overrides=None: cfg)
    monkeypatch.setattr(core_module, "MemSearch", FakeMemSearch)

    result = CliRunner().invoke(
        cli,
        [
            "index",
            str(memory_dir),
            "--ignore-file",
            ".cursorignore",
            "--ignore-file",
            ".gitignore",
            "--exclude",
            "drafts/**",
        ],
    )

    assert result.exit_code == 0
    assert captured["paths"] == [str(memory_dir)]
    assert captured["kwargs"]["ignore_files"] == [".gitignore", ".cursorignore"]
    assert captured["kwargs"]["exclude"] == ["generated/**", "drafts/**"]


def test_cli_index_records_degraded_state(monkeypatch, tmp_path: Path) -> None:
    memory_dir = tmp_path / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)

    class FakeMemSearch:
        def __init__(self, *_args, **_kwargs):
            pass

        async def index_with_report(self, *, force=False):
            return IndexReport(
                indexed_chunks=2,
                total_files=2,
                indexed_files=1,
                failed_files=(IndexFailure(path=str(memory_dir / "bad.md"), error="RuntimeError: failed"),),
            )

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli_module, "resolve_config", lambda _overrides=None: MemSearchConfig())
    monkeypatch.setattr(core_module, "MemSearch", FakeMemSearch)

    result = CliRunner().invoke(cli, ["index", str(memory_dir)])

    assert result.exit_code == 0
    state = json.loads((tmp_path / ".memsearch" / ".index-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "degraded"
    assert state["last_failed_at"]
    assert state["failed_files"][0]["path"] == str(memory_dir / "bad.md")


def test_cli_index_records_error_state(monkeypatch, tmp_path: Path) -> None:
    memory_dir = tmp_path / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)

    class FakeMemSearch:
        def __init__(self, *_args, **_kwargs):
            pass

        async def index_with_report(self, *, force=False):
            raise RuntimeError("store unavailable")

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli_module, "resolve_config", lambda _overrides=None: MemSearchConfig())
    monkeypatch.setattr(core_module, "MemSearch", FakeMemSearch)

    result = CliRunner().invoke(cli, ["index", str(memory_dir)])

    assert result.exit_code != 0
    state = json.loads((tmp_path / ".memsearch" / ".index-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "error"
    assert "RuntimeError: store unavailable" in state["last_error"]


def test_cli_watch_records_event_error_state(monkeypatch, tmp_path: Path) -> None:
    memory_dir = tmp_path / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)
    changed_file = memory_dir / "2026-07-20.md"

    class FakeWatcher:
        def stop(self) -> None:
            pass

    class FakeMemSearch:
        def __init__(self, *_args, **_kwargs):
            pass

        async def index_with_report(self, *, force=False):
            return IndexReport(indexed_chunks=1, total_files=1, indexed_files=1)

        def watch(self, *, on_event=None, on_error=None, debounce_ms=None):
            assert debounce_ms == 1500
            on_error("modified", RuntimeError("event failed"), changed_file)
            return FakeWatcher()

        def close(self) -> None:
            pass

    def stop_loop(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_module, "resolve_config", lambda _overrides=None: MemSearchConfig())
    monkeypatch.setattr(core_module, "MemSearch", FakeMemSearch)
    monkeypatch.setattr(time, "sleep", stop_loop)

    result = CliRunner().invoke(cli, ["watch", str(memory_dir)])

    assert result.exit_code == 0
    state = json.loads((tmp_path / ".memsearch" / ".index-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "degraded"
    assert state["operation"] == "watch:modified"
    assert state["failed_files"] == [
        {"path": str(changed_file), "error": "RuntimeError: event failed"},
    ]
