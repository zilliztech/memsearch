"""File watcher — monitors directories for markdown changes using watchdog."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_MS = 1500


class _MarkdownHandler(FileSystemEventHandler):
    """Dispatch markdown file events to a callback with debounce."""

    def __init__(
        self,
        callback: Callable[[str, Path], None],
        extensions: tuple[str, ...] = (".md", ".markdown"),
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        path_filter: Callable[[Path], bool] | None = None,
    ) -> None:
        self._callback = callback
        self._extensions = extensions
        self._debounce_s = debounce_ms / 1000.0
        self._path_filter = path_filter
        self._timers: dict[str, threading.Timer] = {}
        self._pending: dict[str, str] = {}  # path -> latest event_type
        self._lock = threading.Lock()

    def _is_markdown(self, path: str) -> bool:
        return Path(path).suffix.lower() in self._extensions

    def _should_process(self, path: str) -> bool:
        return self._path_filter is None or self._path_filter(Path(path))

    def _schedule(self, event_type: str, path: str) -> None:
        with self._lock:
            self._pending[path] = event_type
            if path in self._timers:
                self._timers[path].cancel()
            timer = threading.Timer(self._debounce_s, self._fire, args=(path,))
            self._timers[path] = timer
            timer.start()

    def _fire(self, path: str) -> None:
        with self._lock:
            event_type = self._pending.pop(path, None)
            self._timers.pop(path, None)
        if event_type:
            logger.debug("Debounced %s: %s", event_type, path)
            self._callback(event_type, Path(path))

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_markdown(event.src_path) and self._should_process(event.src_path):
            self._schedule("created", event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_markdown(event.src_path) and self._should_process(event.src_path):
            self._schedule("modified", event.src_path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_markdown(event.src_path):
            self._schedule("deleted", event.src_path)

    def cancel_all(self) -> None:
        """Cancel all pending debounce timers."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
            self._pending.clear()


class FileWatcher:
    """Watch directories for markdown file changes.

    Parameters
    ----------
    paths:
        Directories to watch.
    callback:
        Called with ``(event_type, file_path)`` on change.
        ``event_type`` is one of ``"created"``, ``"modified"``, ``"deleted"``.
    debounce_ms:
        Debounce delay in milliseconds.  Multiple events for the same
        file within this window are collapsed into one callback.
        Defaults to 1500 ms (matching OpenClaw).
    path_filter:
        Optional predicate for created and modified markdown paths. Deleted
        files are always dispatched so any previously indexed chunks can be
        removed safely.
    """

    def __init__(
        self,
        paths: list[str | Path],
        callback: Callable[[str, Path], None],
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        path_filter: Callable[[Path], bool] | None = None,
    ) -> None:
        self._paths = [Path(p).expanduser().resolve() for p in paths]
        self._handler = _MarkdownHandler(callback, debounce_ms=debounce_ms, path_filter=path_filter)
        self._observer = Observer()

    def start(self) -> None:
        """Start watching in a background thread."""
        for p in self._paths:
            if p.is_dir():
                self._observer.schedule(self._handler, str(p), recursive=True)
                logger.info("Watching %s", p)
        self._observer.start()

    def stop(self) -> None:
        """Stop watching."""
        self._handler.cancel_all()
        self._observer.stop()
        self._observer.join()

    def __enter__(self) -> FileWatcher:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
