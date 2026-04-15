from __future__ import annotations

from pathlib import Path

from memsearch.core import MemSearch


class _DummyStore:
    def delete_by_source(self, source: str) -> None:
        raise RuntimeError(f"boom: {source}")


class _DummyWatcher:
    def __init__(self, paths, callback, **kwargs) -> None:
        self.paths = paths
        self.callback = callback
        self.kwargs = kwargs
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        pass


def test_watch_callback_swallow_delete_errors(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_file_watcher(paths, callback, **kwargs):
        watcher = _DummyWatcher(paths, callback, **kwargs)
        captured["watcher"] = watcher
        return watcher

    logged: list[tuple[str, str, Path]] = []

    def _fake_exception(message: str, event_type: str, file_path: Path) -> None:
        logged.append((message, event_type, file_path))

    monkeypatch.setattr("memsearch.watcher.FileWatcher", _fake_file_watcher)
    monkeypatch.setattr("memsearch.core.logger.exception", _fake_exception)

    mem = MemSearch.__new__(MemSearch)
    mem._paths = ["/tmp"]
    mem._store = _DummyStore()

    watcher = mem.watch()
    assert watcher.started is True

    file_path = Path("/tmp/test.md")
    watcher.callback("deleted", file_path)

    assert logged == [
        ("Failed to process %s event for %s", "deleted", file_path),
    ]
