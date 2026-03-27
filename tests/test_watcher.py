from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

from memsearch.watcher import _MarkdownHandler


class FakeTimer:
    instances: ClassVar[list[FakeTimer]] = []

    def __init__(self, interval: float, fn, args=(), kwargs=None):
        self.interval = interval
        self.fn = fn
        self.args = args
        self.kwargs = kwargs or {}
        self.started = False
        self.cancelled = False
        FakeTimer.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        self.fn(*self.args, **self.kwargs)


def test_markdown_handler_debounces_same_file(monkeypatch) -> None:
    events: list[tuple[str, Path]] = []
    FakeTimer.instances.clear()
    monkeypatch.setattr("memsearch.watcher.threading.Timer", FakeTimer)

    handler = _MarkdownHandler(lambda event_type, path: events.append((event_type, path)), debounce_ms=250)
    file_path = "/tmp/notes.md"

    handler.on_created(SimpleNamespace(is_directory=False, src_path=file_path))
    handler.on_modified(SimpleNamespace(is_directory=False, src_path=file_path))

    assert len(FakeTimer.instances) == 2
    assert FakeTimer.instances[0].cancelled is True
    assert FakeTimer.instances[1].started is True

    FakeTimer.instances[1].fire()

    assert events == [("modified", Path(file_path))]


def test_markdown_handler_tracks_different_files_independently(monkeypatch) -> None:
    events: list[tuple[str, Path]] = []
    FakeTimer.instances.clear()
    monkeypatch.setattr("memsearch.watcher.threading.Timer", FakeTimer)

    handler = _MarkdownHandler(lambda event_type, path: events.append((event_type, path)), debounce_ms=250)
    first = "/tmp/a.md"
    second = "/tmp/b.markdown"

    handler.on_modified(SimpleNamespace(is_directory=False, src_path=first))
    handler.on_deleted(SimpleNamespace(is_directory=False, src_path=second))

    assert len(FakeTimer.instances) == 2
    FakeTimer.instances[0].fire()
    FakeTimer.instances[1].fire()

    assert events == [
        ("modified", Path(first)),
        ("deleted", Path(second)),
    ]


def test_markdown_handler_ignores_directories_and_non_markdown(monkeypatch) -> None:
    events: list[tuple[str, Path]] = []
    FakeTimer.instances.clear()
    monkeypatch.setattr("memsearch.watcher.threading.Timer", FakeTimer)

    handler = _MarkdownHandler(lambda event_type, path: events.append((event_type, path)))

    handler.on_modified(SimpleNamespace(is_directory=True, src_path="/tmp/folder"))
    handler.on_modified(SimpleNamespace(is_directory=False, src_path="/tmp/readme.txt"))
    handler.on_modified(SimpleNamespace(is_directory=False, src_path="/tmp/README.MD"))

    assert len(FakeTimer.instances) == 1
    FakeTimer.instances[0].fire()

    assert events == [("modified", Path("/tmp/README.MD"))]


def test_markdown_handler_cancel_all_clears_pending_timers(monkeypatch) -> None:
    FakeTimer.instances.clear()
    monkeypatch.setattr("memsearch.watcher.threading.Timer", FakeTimer)

    handler = _MarkdownHandler(lambda _event_type, _path: None)
    handler.on_created(SimpleNamespace(is_directory=False, src_path="/tmp/a.md"))
    handler.on_created(SimpleNamespace(is_directory=False, src_path="/tmp/b.md"))

    handler.cancel_all()

    assert all(timer.cancelled for timer in FakeTimer.instances)
    assert handler._pending == {}
    assert handler._timers == {}
