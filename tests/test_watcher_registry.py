from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from click.testing import CliRunner

from memsearch import cli as cli_module
from memsearch.cli import cli
from memsearch.watcher_registry import WatcherRegistry


def test_registry_uses_stable_path_key_and_external_state_dir(tmp_path: Path) -> None:
    memory_dir = tmp_path / "project" / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)
    state_dir = tmp_path / "state"

    first = WatcherRegistry([memory_dir], state_dir=state_dir)
    second = WatcherRegistry([memory_dir / ".." / "memory"], state_dir=state_dir)

    assert first.registry_dir == second.registry_dir
    assert first.registry_dir.is_relative_to(state_dir)
    assert not first.registry_dir.is_relative_to(memory_dir)


def test_registry_uses_xdg_state_home_by_default(monkeypatch, tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    xdg_state_home = tmp_path / "xdg-state"
    monkeypatch.delenv("MEMSEARCH_STATE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state_home))

    registry = WatcherRegistry([memory_dir])

    assert registry.registry_dir.parent == (xdg_state_home / "memsearch" / "watchers").resolve()


def test_registry_allows_exactly_one_owner_and_releases_cleanly(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    state_dir = tmp_path / "state"
    first = WatcherRegistry([memory_dir], state_dir=state_dir, heartbeat_interval=0.01)
    second = WatcherRegistry([memory_dir], state_dir=state_dir)

    assert first.acquire()
    assert not second.acquire()
    owner = first.read_owner()
    assert owner["watcher_id"] == first.watcher_id
    assert owner["pid"] == os.getpid()
    assert owner["memory_dir"] == str(memory_dir.resolve())

    initial_heartbeat = owner["heartbeat"]
    deadline = time.monotonic() + 1
    while first.read_owner().get("heartbeat") == initial_heartbeat and time.monotonic() < deadline:
        time.sleep(0.01)
    assert first.read_owner()["heartbeat"] != initial_heartbeat

    first.release()
    assert not first.owner_path.exists()
    assert second.acquire()
    second.release()


def test_registry_lock_is_process_scoped(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    state_dir = tmp_path / "state"
    owner = WatcherRegistry([memory_dir], state_dir=state_dir)
    assert owner.acquire()

    code = (
        "from memsearch.watcher_registry import WatcherRegistry; "
        "import sys; "
        "registry=WatcherRegistry([sys.argv[1]], state_dir=sys.argv[2]); "
        "print(json.dumps(registry.acquire()))"
    )
    env = {**os.environ, "PYTHONPATH": str(Path("src").resolve())}
    blocked = subprocess.run(
        [sys.executable, "-c", "import json; " + code, str(memory_dir), str(state_dir)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert json.loads(blocked.stdout) is False

    owner.release()
    acquired = subprocess.run(
        [sys.executable, "-c", "import json; " + code, str(memory_dir), str(state_dir)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert json.loads(acquired.stdout) is True

    recovered = WatcherRegistry([memory_dir], state_dir=state_dir)
    assert recovered.acquire()
    assert recovered.read_owner()["watcher_id"] == recovered.watcher_id
    recovered.release()


def test_concurrent_processes_choose_exactly_one_owner(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    state_dir = tmp_path / "state"
    gate = tmp_path / "gate"
    code = """
import json
import sys
import time
from pathlib import Path
from memsearch.watcher_registry import WatcherRegistry

while not Path(sys.argv[3]).exists():
    time.sleep(0.01)
registry = WatcherRegistry([sys.argv[1]], state_dir=sys.argv[2])
acquired = registry.acquire()
print(json.dumps(acquired), flush=True)
if acquired:
    time.sleep(1)
    registry.release()
"""
    env = {**os.environ, "PYTHONPATH": str(Path("src").resolve())}
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(memory_dir), str(state_dir), str(gate)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for _ in range(4)
    ]
    gate.touch()
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        results.append(json.loads(stdout))

    assert results.count(True) == 1


def test_release_does_not_remove_replaced_owner_metadata(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    registry = WatcherRegistry([memory_dir], state_dir=tmp_path / "state")
    assert registry.acquire()
    replacement = {**registry.read_owner(), "watcher_id": "replacement"}
    registry.owner_path.write_text(json.dumps(replacement), encoding="utf-8")

    registry.release()

    assert json.loads(registry.owner_path.read_text(encoding="utf-8"))["watcher_id"] == "replacement"


def test_watch_cli_exits_before_initializing_when_path_is_owned(monkeypatch, tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    state_dir = tmp_path / "state"
    monkeypatch.setenv("MEMSEARCH_STATE_DIR", str(state_dir))
    owner = WatcherRegistry([memory_dir], state_dir=state_dir)
    assert owner.acquire()
    try:
        result = CliRunner().invoke(cli, ["watch", str(memory_dir)])
    finally:
        owner.release()

    assert result.exit_code == 0
    assert result.output == "A watcher is already running for these paths.\n"
    assert not (tmp_path / ".memsearch" / ".index-state.json").exists()


def test_watch_cli_releases_ownership_when_config_fails(monkeypatch, tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    state_dir = tmp_path / "state"
    monkeypatch.setenv("MEMSEARCH_STATE_DIR", str(state_dir))

    def fail_config(_overrides) -> None:
        raise ValueError("bad")

    monkeypatch.setattr(cli_module, "_safe_resolve_config", fail_config)

    result = CliRunner().invoke(cli, ["watch", str(memory_dir)])

    assert result.exit_code != 0
    recovered = WatcherRegistry([memory_dir], state_dir=state_dir)
    assert recovered.acquire()
    recovered.release()
