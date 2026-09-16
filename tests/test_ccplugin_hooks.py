from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path


def _link_command(target_dir: Path, name: str) -> None:
    source = shutil.which(name)
    if source is None:
        raise AssertionError(f"required command not found in PATH: {name}")
    (target_dir / name).symlink_to(source)


def test_common_hook_reads_stdin_without_timeout_binary(tmp_path: Path) -> None:
    """Simulate macOS: no GNU `timeout`, but hook stdin should still be read."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    for command in [
        "bash",
        "basename",
        "cat",
        "cut",
        "dirname",
        "pwd",
        "realpath",
        "sed",
        "sha256sum",
        "tr",
    ]:
        _link_command(bin_dir, command)

    memsearch_stub = bin_dir / "memsearch"
    memsearch_stub.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    memsearch_stub.chmod(memsearch_stub.stat().st_mode | stat.S_IEXEC)

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    payload = {"transcript_path": "/tmp/session.jsonl", "stop_hook_active": False}
    script = "source ccplugin/hooks/common.sh; printf '%s' \"$INPUT\""
    result = subprocess.run(
        ["bash", "-lc", script],
        cwd=Path(__file__).resolve().parents[1],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "PATH": str(bin_dir),
            "CLAUDE_PROJECT_DIR": str(project_dir),
        },
    )

    assert json.loads(result.stdout) == payload
