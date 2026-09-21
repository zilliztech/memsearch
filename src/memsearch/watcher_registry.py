"""Filesystem-backed ownership for long-running watch commands."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

WATCHER_REGISTRY_VERSION = 1
DEFAULT_HEARTBEAT_INTERVAL = 30.0


class WatcherRegistry:
    """Hold exclusive ownership of one canonical set of watched paths."""

    def __init__(
        self,
        paths: Iterable[str | Path],
        *,
        state_dir: str | Path | None = None,
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
    ) -> None:
        resolved_paths = tuple(sorted(str(Path(path).expanduser().resolve()) for path in paths))
        if not resolved_paths:
            raise ValueError("at least one watch path is required")

        digest = hashlib.sha256("\0".join(resolved_paths).encode()).hexdigest()[:20]
        self.paths = resolved_paths
        self.watcher_id = uuid.uuid4().hex
        self.started_at = _now()
        self.heartbeat_interval = heartbeat_interval
        self.registry_dir = _state_root(state_dir) / "watchers" / digest
        self.lock_path = self.registry_dir / "watcher.lock"
        self.owner_path = self.registry_dir / "owner.json"
        self._lock_file: BinaryIO | None = None
        self._metadata_lock = threading.Lock()
        self._stop_heartbeat = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def acquire(self) -> bool:
        """Acquire ownership without waiting, returning false when already owned."""
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        lock_file = self.lock_path.open("a+b")
        try:
            _lock(lock_file)
        except OSError:
            lock_file.close()
            return False

        self._lock_file = lock_file
        try:
            self._write_owner()
        except Exception:
            _unlock(lock_file)
            lock_file.close()
            self._lock_file = None
            raise
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat,
            name="memsearch-watch-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()
        return True

    def release(self) -> None:
        """Release ownership and remove only this watcher's metadata."""
        lock_file = self._lock_file
        if lock_file is None:
            return

        self._stop_heartbeat.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=max(self.heartbeat_interval, 1.0) + 1.0)

        owner = self.read_owner()
        if owner.get("watcher_id") == self.watcher_id:
            with contextlib.suppress(OSError):
                self.owner_path.unlink()
        _unlock(lock_file)
        lock_file.close()
        self._lock_file = None

    def is_owned(self) -> bool:
        """Return whether this instance still owns the registry entry."""
        return self._lock_file is not None and self.read_owner().get("watcher_id") == self.watcher_id

    def read_owner(self) -> dict[str, object]:
        """Read current owner metadata, returning an empty mapping if unavailable."""
        with self._metadata_lock, contextlib.suppress(OSError, UnicodeError, json.JSONDecodeError):
            owner = json.loads(self.owner_path.read_text(encoding="utf-8"))
            if isinstance(owner, dict):
                return owner
        return {}

    def cleanup(self) -> None:
        """Remove stale owner metadata while this instance holds the lock."""
        if self._lock_file is not None:
            owner = self.read_owner()
            if owner and owner.get("watcher_id") != self.watcher_id:
                with contextlib.suppress(OSError):
                    self.owner_path.unlink()

    def __enter__(self) -> WatcherRegistry:
        if not self.acquire():
            raise RuntimeError("watcher registry is already owned")
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.release()

    def _heartbeat(self) -> None:
        while not self._stop_heartbeat.wait(self.heartbeat_interval):
            if not self.is_owned():
                return
            with contextlib.suppress(OSError):
                self._write_owner()

    def _write_owner(self) -> None:
        owner = {
            "version": WATCHER_REGISTRY_VERSION,
            "watcher_id": self.watcher_id,
            "pid": os.getpid(),
            "memory_dir": self.paths[0] if len(self.paths) == 1 else None,
            "paths": list(self.paths),
            "started_at": self.started_at,
            "heartbeat": _now(),
        }
        with self._metadata_lock:
            tmp_path = self.owner_path.with_name(f"owner.{self.watcher_id}.tmp")
            try:
                tmp_path.write_text(json.dumps(owner, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                tmp_path.replace(self.owner_path)
            finally:
                with contextlib.suppress(OSError):
                    tmp_path.unlink()


def _state_root(state_dir: str | Path | None) -> Path:
    if state_dir is not None:
        return Path(state_dir).expanduser().resolve()
    if configured := os.environ.get("MEMSEARCH_STATE_DIR"):
        return Path(configured).expanduser().resolve()
    if configured := os.environ.get("XDG_STATE_HOME"):
        return Path(configured).expanduser().resolve() / "memsearch"
    if os.name == "nt" and (local_app_data := os.environ.get("LOCALAPPDATA")):
        return Path(local_app_data).expanduser().resolve() / "memsearch"
    return Path.home().resolve() / ".local" / "state" / "memsearch"


def _lock(lock_file: BinaryIO) -> None:
    lock_file.seek(0)
    if os.name == "nt":
        import msvcrt

        if lock_file.read(1) == b"":
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(lock_file: BinaryIO) -> None:
    lock_file.seek(0)
    if os.name == "nt":
        import msvcrt

        with contextlib.suppress(OSError):
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    with contextlib.suppress(OSError):
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
