from __future__ import annotations

import os
import signal
import subprocess
from contextlib import suppress
from pathlib import Path

COMMON = Path("plugins/codex/hooks/common.sh")
STOP = Path("plugins/codex/hooks/stop.sh")


def _write_fake_memsearch(fake_bin: Path) -> None:
    fake_memsearch = fake_bin / "memsearch"
    fake_memsearch.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "config" ] && [ "${2:-}" = "get" ]; then
  case "${3:-}" in
    milvus.uri) echo "http://localhost:19530" ;;
    *) echo "" ;;
  esac
  exit 0
fi
if [ "${1:-}" = "index" ]; then
  echo "$$ $*" >> "$MEMSEARCH_FAKE_INDEX_LOG"
  sleep 5
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_memsearch.chmod(0o755)


def _run_common_function(tmp_path: Path, function_body: str, log_file: Path) -> subprocess.CompletedProcess[str]:
    project = tmp_path / "project"
    project.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_memsearch(fake_bin)

    script = f"""
set -euo pipefail
SCRIPT_DIR="{Path("plugins/codex/hooks").resolve()}"
source "{COMMON.resolve()}"
{function_body}
"""
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "MEMSEARCH_PROJECT_DIR": str(project),
        "MEMSEARCH_SKIP_HOOK_STDIN": "1",
        "MEMSEARCH_FAKE_INDEX_LOG": str(log_file),
        "MILVUS_URI": "http://localhost:19530",
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
    }
    return subprocess.run(["bash", "-c", script], check=True, capture_output=True, text=True, env=env)


def test_stop_hook_uses_suffix_safe_mktemp_template() -> None:
    source = STOP.read_text(encoding="utf-8")

    assert "memsearch-stop.XXXXXX.json" not in source
    assert 'mktemp "${TMPDIR:-/tmp}/memsearch-stop.XXXXXX"' in source


def test_background_index_is_singleton_when_watch_is_missing(tmp_path: Path) -> None:
    log_file = tmp_path / "index.log"
    result = _run_common_function(
        tmp_path,
        """
start_background_index
start_background_index
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [ -s "$MEMSEARCH_FAKE_INDEX_LOG" ] && break
  sleep 0.1
done
cat "$INDEX_PIDFILE"
""",
        log_file,
    )

    pid = int(result.stdout.strip())
    try:
        lines = log_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
    finally:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)


def test_background_index_skips_when_watch_pid_is_alive(tmp_path: Path) -> None:
    log_file = tmp_path / "index.log"
    _run_common_function(
        tmp_path,
        """
ensure_memory_dir
echo "$$" > "$WATCH_PIDFILE"
start_background_index
sleep 0.2
""",
        log_file,
    )

    assert not log_file.exists()
