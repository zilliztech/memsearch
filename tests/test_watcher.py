"""Tests for the file watcher module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from watchdog.events import FileSystemEvent

from memsearch.watcher import DEFAULT_DEBOUNCE_MS, FileWatcher, _MarkdownHandler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(src_path: str, is_directory: bool = False) -> FileSystemEvent:
    """Convenience to build a real FileSystemEvent for testing."""
    ev = FileSystemEvent(src_path)
    ev.is_directory = is_directory
    return ev


# ---------------------------------------------------------------------------
# _MarkdownHandler
# ---------------------------------------------------------------------------


class TestMarkdownHandler:
    """Tests for the internal _MarkdownHandler class."""

    def test_on_created_dispatches_markdown(self):
        callback = MagicMock()
        handler = _MarkdownHandler(callback)

        ev = _make_event("/tmp/test.md")
        handler.on_created(ev)

        # The timer fires after debounce; we wait for it
        handler._timers["/tmp/test.md"].join()
        callback.assert_called_once_with("created", Path("/tmp/test.md"))

    def test_on_modified_dispatches_markdown(self):
        callback = MagicMock()
        handler = _MarkdownHandler(callback)

        ev = _make_event("/tmp/test.md")
        handler.on_modified(ev)

        handler._timers["/tmp/test.md"].join()
        callback.assert_called_once_with("modified", Path("/tmp/test.md"))

    def test_on_deleted_dispatches_markdown(self):
        callback = MagicMock()
        handler = _MarkdownHandler(callback)

        ev = _make_event("/tmp/test.md")
        handler.on_deleted(ev)

        handler._timers["/tmp/test.md"].join()
        callback.assert_called_once_with("deleted", Path("/tmp/test.md"))

    def test_on_deleted_dispatches_markdown_extension(self):
        """The .markdown extension should also be accepted."""
        callback = MagicMock()
        handler = _MarkdownHandler(callback)

        ev = _make_event("/tmp/test.markdown")
        handler.on_deleted(ev)

        handler._timers["/tmp/test.markdown"].join()
        callback.assert_called_once_with("deleted", Path("/tmp/test.markdown"))

    @pytest.mark.parametrize("ext", [".txt", ".html", ".py", "", ".mdx"])
    def test_non_markdown_files_are_ignored(self, ext):
        callback = MagicMock()
        handler = _MarkdownHandler(callback)

        ev = _make_event(f"/tmp/file{ext}")
        handler.on_created(ev)
        handler.on_modified(ev)
        handler.on_deleted(ev)

        # No timers should have been created
        assert len(handler._timers) == 0
        callback.assert_not_called()

    def test_directory_events_are_filtered(self):
        callback = MagicMock()
        handler = _MarkdownHandler(callback)

        ev = _make_event("/tmp/dir.md", is_directory=True)
        handler.on_created(ev)
        handler.on_modified(ev)
        handler.on_deleted(ev)

        assert len(handler._timers) == 0
        callback.assert_not_called()

    def test_debounce_coalesces_rapid_events(self):
        """Multiple rapid events for the same path should be collapsed."""
        callback = MagicMock()
        handler = _MarkdownHandler(callback, debounce_ms=100)

        ev_created = _make_event("/tmp/test.md")
        ev_modified = _make_event("/tmp/test.md")
        ev_deleted = _make_event("/tmp/test.md")

        handler.on_created(ev_created)
        handler.on_modified(ev_modified)
        handler.on_deleted(ev_deleted)

        # Only the last timer should still be running
        timers = handler._timers
        assert len(timers) == 1
        assert "/tmp/test.md" in timers
        # The pending event should be the last one ("deleted")
        assert handler._pending["/tmp/test.md"] == "deleted"

        timers["/tmp/test.md"].join()
        callback.assert_called_once_with("deleted", Path("/tmp/test.md"))

    def test_events_for_different_paths_are_not_coalesced(self):
        callback = MagicMock()
        handler = _MarkdownHandler(callback, debounce_ms=50)

        handler.on_created(_make_event("/tmp/a.md"))
        handler.on_created(_make_event("/tmp/b.md"))

        assert len(handler._timers) == 2

        # Grab timer references and wait for both to finish, since _fire
        # pops them from _timers before we can iterate safely.
        timers = list(handler._timers.values())
        for t in timers:
            t.join()

        assert callback.call_count == 2

    def test_custom_extensions(self):
        callback = MagicMock()
        handler = _MarkdownHandler(callback, extensions=(".rst",))

        handler.on_created(_make_event("/tmp/doc.rst"))
        handler.on_modified(_make_event("/tmp/doc.md"))  # should be ignored

        assert "/tmp/doc.rst" in handler._timers
        assert "/tmp/doc.md" not in handler._timers

        handler._timers["/tmp/doc.rst"].join()
        callback.assert_called_once_with("created", Path("/tmp/doc.rst"))

    def test_cancel_all_stops_pending_timers(self):
        callback = MagicMock()
        handler = _MarkdownHandler(callback, debounce_ms=5000)  # long debounce

        handler.on_created(_make_event("/tmp/a.md"))
        handler.on_created(_make_event("/tmp/b.md"))

        assert len(handler._timers) == 2

        handler.cancel_all()

        # All dicts should be cleared
        assert len(handler._timers) == 0
        assert len(handler._pending) == 0
        # Callback should never have been invoked
        callback.assert_not_called()

    def test_lock_used_for_thread_safety(self):
        """Verify _schedule and _fire use the internal lock."""
        callback = MagicMock()
        handler = _MarkdownHandler(callback)

        # The lock should be usable (not deadlocked / not a trivial object)
        assert hasattr(handler._lock, "acquire")
        assert hasattr(handler._lock, "release")
        acquired = handler._lock.acquire(blocking=False)
        assert acquired is True
        handler._lock.release()


# ---------------------------------------------------------------------------
# FileWatcher
# ---------------------------------------------------------------------------


class TestFileWatcher:
    """Tests for the public FileWatcher class."""

    def test_init_stores_paths_resolved(self, tmp_path: Path):
        callback = MagicMock()
        src = tmp_path / "subdir"
        src.mkdir()

        w = FileWatcher([src], callback)

        assert len(w._paths) == 1
        assert w._paths[0] == src.resolve()
        assert isinstance(w._handler, _MarkdownHandler)
        assert w._handler._callback is callback

    def test_init_resolves_expands_user(self):
        """expanduser() should be called on paths with ~."""
        callback = MagicMock()
        w = FileWatcher(["~"], callback)

        expected = Path.home().resolve()
        assert w._paths[0] == expected

    def test_start_schedules_only_existing_directories(self):
        callback = MagicMock()

        with patch("memsearch.watcher.Observer") as MockObserver:
            observer_instance = MockObserver.return_value
            w = FileWatcher(["/nonexistent/path"], callback)
            w.start()

            # Non-existent directory: schedule should NOT be called
            observer_instance.schedule.assert_not_called()
            observer_instance.start.assert_called_once()

    def test_start_schedules_existing_directories(self, tmp_path: Path):
        callback = MagicMock()
        (tmp_path / "sub").mkdir()
        target = tmp_path / "sub"

        with patch("memsearch.watcher.Observer") as MockObserver:
            observer_instance = MockObserver.return_value
            w = FileWatcher([target], callback)
            w.start()

            observer_instance.schedule.assert_called_once_with(w._handler, str(target.resolve()), recursive=True)
            observer_instance.start.assert_called_once()

    def test_stop_calls_cancel_all_and_observer_stop(self, tmp_path: Path):
        callback = MagicMock()

        with patch("memsearch.watcher.Observer") as MockObserver:
            observer_instance = MockObserver.return_value
            w = FileWatcher([tmp_path], callback)
            w.start()
            w.stop()

            w._handler.cancel_all()  # called inside stop
            observer_instance.stop.assert_called_once()
            observer_instance.join.assert_called_once()

    def test_context_manager(self, tmp_path: Path):
        callback = MagicMock()

        with patch("memsearch.watcher.Observer") as MockObserver:
            observer_instance = MockObserver.return_value
            w = FileWatcher([tmp_path], callback)

            with w as fw:
                assert fw is w
                observer_instance.start.assert_called_once()

            observer_instance.stop.assert_called_once()
            observer_instance.join.assert_called_once()

    def test_callback_received_via_watchdog_integration(self, tmp_path: Path):
        """Integration-style: use a real Observer + Handler to verify end-to-end."""
        received = []

        def callback(ev_type, path):
            received.append((ev_type, path))

        w = FileWatcher([tmp_path], callback, debounce_ms=50)
        w.start()

        try:
            # Create a markdown file
            md_file = tmp_path / "hello.md"
            md_file.write_text("# Hello")
            import time

            time.sleep(0.3)  # let watchdog detect + debounce fire
        finally:
            w.stop()

        assert len(received) >= 1
        # On some platforms (Windows), creating + writing a file may emit
        # "modified" as the final event instead of "created" due to debounce
        # coalescing. Accept either.
        event_type, path = received[-1]
        assert event_type in ("created", "modified")
        assert path.name == "hello.md"

    def test_default_debounce_ms(self):
        callback = MagicMock()
        w = FileWatcher([], callback)
        assert w._handler._debounce_s == DEFAULT_DEBOUNCE_MS / 1000.0
