"""Nonblocking maintenance locks, including recovery of legacy PID files."""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

import psutil
from filelock import FileLock, Timeout

_FORMAT = "memsearch-maintenance-v1"
_LEGACY_WRITE_GRACE_SECONDS = 60


def _legacy_holder_active(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError):
        return True
    try:
        marker = json.loads(text)
    except ValueError:
        marker = None
    if isinstance(marker, dict) and marker.get("format") == _FORMAT:
        # Only writers holding the kernel guard create this marker. We own
        # that guard now, so the previous writer has already exited.
        return False
    try:
        pid = int(text)
    except ValueError:
        # An older writer may be between O_EXCL and writing its PID. A crash
        # in that window must not leave an empty file blocking maintenance.
        try:
            return time.time() - path.stat().st_mtime < _LEGACY_WRITE_GRACE_SECONDS
        except FileNotFoundError:
            return False
    if pid <= 0:
        return False
    try:
        return psutil.Process(pid).is_running()
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return True


@contextlib.contextmanager
def file_lock(path: Path):
    # The kernel guard serializes both execution and stale-marker recovery.
    # A hard-killed process releases it automatically on Windows and POSIX.
    guard = FileLock(str(path) + ".guard", timeout=0)
    try:
        guard.acquire()
    except Timeout:
        yield False
        return
    try:
        if path.exists():
            if _legacy_holder_active(path):
                yield False
                return
            path.unlink(missing_ok=True)
        # Keep the sentinel while running so older installed runners also
        # skip this task. O_EXCL handles a legacy runner starting concurrently.
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            yield False
            return
        try:
            os.write(fd, json.dumps({"format": _FORMAT, "pid": os.getpid()}).encode())
            yield True
        finally:
            os.close(fd)
            with contextlib.suppress(OSError):
                path.unlink()
    finally:
        guard.release()
