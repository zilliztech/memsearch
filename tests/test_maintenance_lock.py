"""Real-process lock regressions, also run without the core on Windows CI."""

from __future__ import annotations

import contextlib
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

import pytest

LOCK_MODULE = Path(__file__).resolve().parents[1] / "src/memsearch/_maintenance_lock.py"
file_lock = runpy.run_path(str(LOCK_MODULE))["file_lock"]


@contextlib.contextmanager
def holder(lock):
    code = """
import runpy,sys
from pathlib import Path
file_lock = runpy.run_path(sys.argv[1])['file_lock']
with file_lock(Path(sys.argv[2])) as acquired:
    print(acquired, flush=True)
    sys.stdin.readline()
"""
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", code, str(LOCK_MODULE), str(lock)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "True"
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def test_live_holder_skipped_and_hard_kill_recovers(tmp_path):
    lock = tmp_path / "task.lock"
    for _ in range(2):
        with holder(lock) as process:
            with file_lock(lock) as acquired:
                assert not acquired
            process.kill()
            process.wait(timeout=10)
        # No waiting for an age threshold or deleting files manually.
        with file_lock(lock) as acquired:
            assert acquired


def test_normal_exit_and_exception_release_lock(tmp_path):
    lock = tmp_path / "task.lock"
    with pytest.raises(RuntimeError, match="task failed"), file_lock(lock) as acquired:
        assert acquired
        raise RuntimeError("task failed")
    with file_lock(lock) as acquired:
        assert acquired
    assert not lock.exists()


def test_legacy_live_pid_is_preserved_even_when_old(tmp_path):
    lock = tmp_path / "task.lock"
    lock.write_text(str(os.getpid()))
    old = time.time() - 7 * 86400
    os.utime(lock, (old, old))
    with file_lock(lock) as acquired:
        assert not acquired
    assert lock.read_text() == str(os.getpid())


def test_legacy_dead_pid_recovers(tmp_path):
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    lock = tmp_path / "task.lock"
    lock.write_text(str(child.pid))
    with file_lock(lock) as acquired:
        assert acquired


@pytest.mark.parametrize("content", ["", "incomplete"])
def test_incomplete_legacy_write_has_bounded_grace(tmp_path, content):
    lock = tmp_path / "task.lock"
    lock.write_text(content)
    with file_lock(lock) as acquired:
        assert not acquired
    old = time.time() - 120
    os.utime(lock, (old, old))
    with file_lock(lock) as acquired:
        assert acquired


def test_concurrent_recovery_never_runs_two_tasks(tmp_path):
    lock = tmp_path / "task.lock"
    with holder(lock) as process:
        process.kill()
        process.wait(timeout=10)
    gate = tmp_path / "go"
    exclusive = tmp_path / "running"
    code = """
import os,runpy,sys,time
from pathlib import Path
file_lock = runpy.run_path(sys.argv[1])['file_lock']
gate, exclusive = Path(sys.argv[3]), Path(sys.argv[4])
while not gate.exists(): time.sleep(0.01)
with file_lock(Path(sys.argv[2])) as acquired:
    if acquired:
        fd = os.open(exclusive, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            time.sleep(0.4)
        finally:
            os.close(fd)
            exclusive.unlink()
    print(acquired)
"""
    children = []
    try:
        for _ in range(6):  # Keep handles for cleanup if a later spawn fails.
            child = subprocess.Popen(
                [sys.executable, "-c", code, str(LOCK_MODULE), str(lock), str(gate), str(exclusive)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            children.append(child)
        gate.touch()
        outcomes = []
        for child in children:
            out, err = child.communicate(timeout=15)
            assert child.returncode == 0, err
            outcomes.append(out.strip())
        assert "True" in outcomes
        assert "False" in outcomes
        with file_lock(lock) as acquired:
            assert acquired
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
