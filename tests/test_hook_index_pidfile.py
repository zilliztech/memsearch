from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

PLUGINS = ["claude-code", "codex"]
DEFAULT_HARNESS = {"claude-code": "claude-code", "codex": "codex"}


def _common_sh(plugin: str) -> Path:
    return Path(f"plugins/{plugin}/hooks/common.sh")


def _pgrep_shim(bin_dir: Path) -> Path:
    """A pgrep that hides milvus_lite from the sweep.

    Step 3 of kill_orphaned_index matches `milvus_lite/lib/milvus` with no path
    scoping, so under the real pgrep it would kill the milvus_lite processes that
    other tests in this suite are using. The `memsearch index <dir>` pattern is
    scoped to a tmp_path, so that one passes through to the real pgrep.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    real = shutil.which("pgrep") or "/usr/bin/pgrep"
    shim = bin_dir / "pgrep"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'for arg in "$@"; do\n'
        '  case "$arg" in\n'
        "    *milvus_lite/lib/milvus*) exit 1 ;;\n"
        "  esac\n"
        "done\n"
        f'exec {real} "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim


def _run_bash(plugin: str, body: str, *, env_extra: dict[str, str], memsearch_dir: Path) -> str:
    """Source a plugin's common.sh and run `body` against it."""
    script = textwrap.dedent(f"""
        SCRIPT_DIR="$(cd "$(dirname "{_common_sh(plugin)}")" && pwd)"
        source "{_common_sh(plugin)}" </dev/null
        {body}
    """)
    shim_dir = memsearch_dir.parent / "shim-bin"
    _pgrep_shim(shim_dir)
    env = {
        **os.environ,
        "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
        "MEMSEARCH_DIR": str(memsearch_dir),
        "CLAUDE_PROJECT_DIR": str(memsearch_dir.parent),
        **env_extra,
    }
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=True)
    return result.stdout


def _spawn_sleeper(memory_dir: Path, bin_dir: Path, *, with_child: bool = False) -> subprocess.Popen[bytes]:
    """A process whose command line matches the `memsearch index <dir>` sweep pattern.

    `exec -a` replaces the wrapper with the sleep itself, so the PID handles SIGTERM
    promptly; a bash wrapper would defer the signal until its foreground child exited.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "memsearch"
    if with_child:
        # Stays alive as a parent so the descendant-protection case has a subtree.
        body = 'exec -a "memsearch index $2 child" sleep 30 &\necho $! > "$2.child"\nwait\n'
    else:
        body = 'exec -a "memsearch index $2" sleep 30\n'
    fake.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    fake.chmod(0o755)
    return subprocess.Popen([str(fake), "index", str(memory_dir)])


def _alive(proc: subprocess.Popen[bytes]) -> bool:
    """poll() reaps the child; os.kill(pid, 0) would report a zombie as alive."""
    return proc.poll() is None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@pytest.mark.parametrize("plugin", PLUGINS)
def test_pidfile_is_tagged_with_the_harness(tmp_path: Path, plugin: str) -> None:
    memsearch_dir = tmp_path / ".memsearch"
    out = _run_bash(plugin, 'echo "$INDEX_PIDFILE"', env_extra={}, memsearch_dir=memsearch_dir)
    assert out.strip().endswith(f".index.{DEFAULT_HARNESS[plugin]}.pid")


@pytest.mark.parametrize("plugin", PLUGINS)
def test_memsearch_harness_env_overrides_the_default_tag(tmp_path: Path, plugin: str) -> None:
    memsearch_dir = tmp_path / ".memsearch"
    out = _run_bash(
        plugin, 'echo "$INDEX_PIDFILE"', env_extra={"MEMSEARCH_HARNESS": "grok"}, memsearch_dir=memsearch_dir
    )
    assert out.strip().endswith(".index.grok.pid")


@pytest.mark.parametrize("plugin", PLUGINS)
def test_cleanup_spares_an_index_owned_by_another_harness(tmp_path: Path, plugin: str) -> None:
    memsearch_dir = tmp_path / ".memsearch"
    memory_dir = memsearch_dir / "memory"
    memory_dir.mkdir(parents=True)

    other = _spawn_sleeper(memory_dir, tmp_path / "bin-other")
    mine = _spawn_sleeper(memory_dir, tmp_path / "bin-mine")
    time.sleep(0.3)
    (memsearch_dir / ".index.other-harness.pid").write_text(str(other.pid), encoding="utf-8")
    (memsearch_dir / f".index.{DEFAULT_HARNESS[plugin]}.pid").write_text(str(mine.pid), encoding="utf-8")

    try:
        _run_bash(plugin, "kill_orphaned_index", env_extra={}, memsearch_dir=memsearch_dir)
        time.sleep(0.4)

        assert _alive(other), "another harness's in-flight index must survive"
        assert not _alive(mine), "this harness's own stale index must be reaped"
        assert (memsearch_dir / ".index.other-harness.pid").exists()
        assert not (memsearch_dir / f".index.{DEFAULT_HARNESS[plugin]}.pid").exists()
    finally:
        for proc in (other, mine):
            proc.kill()
            proc.wait()


@pytest.mark.parametrize("plugin", PLUGINS)
def test_cleanup_spares_descendants_of_another_harness(tmp_path: Path, plugin: str) -> None:
    """milvus_lite is a child of `memsearch index` and outlives it, so the subtree is protected."""
    memsearch_dir = tmp_path / ".memsearch"
    memory_dir = memsearch_dir / "memory"
    memory_dir.mkdir(parents=True)

    other = _spawn_sleeper(memory_dir, tmp_path / "bin-other", with_child=True)
    time.sleep(0.5)
    child_pid = int(Path(f"{memory_dir}.child").read_text(encoding="utf-8").strip())
    (memsearch_dir / ".index.other-harness.pid").write_text(str(other.pid), encoding="utf-8")

    try:
        _run_bash(plugin, "kill_orphaned_index", env_extra={}, memsearch_dir=memsearch_dir)
        time.sleep(0.4)

        assert _alive(other), "another harness's index must survive"
        assert _pid_alive(child_pid), "its child must survive too"
    finally:
        for pid in (child_pid, other.pid):
            with contextlib.suppress(OSError):
                os.kill(pid, 9)
        other.wait()


@pytest.mark.parametrize("plugin", PLUGINS)
def test_cleanup_reaps_the_untagged_legacy_pidfile(tmp_path: Path, plugin: str) -> None:
    memsearch_dir = tmp_path / ".memsearch"
    memory_dir = memsearch_dir / "memory"
    memory_dir.mkdir(parents=True)

    legacy = _spawn_sleeper(memory_dir, tmp_path / "bin-legacy")
    time.sleep(0.3)
    (memsearch_dir / ".index.pid").write_text(str(legacy.pid), encoding="utf-8")

    try:
        _run_bash(plugin, "kill_orphaned_index", env_extra={}, memsearch_dir=memsearch_dir)
        time.sleep(0.4)

        assert not _alive(legacy)
        assert not (memsearch_dir / ".index.pid").exists()
    finally:
        legacy.kill()
        legacy.wait()
