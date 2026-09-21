from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path("plugins/zcode/hooks/stop.sh")


def test_zcode_stop_worker_fallback_preserves_utf8(tmp_path: Path) -> None:
    """The stop hook's fallback summary path must not corrupt multi-byte UTF-8."""
    memory_dir = tmp_path / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)
    memory_file = memory_dir / "2026-06-01.md"
    work_file = tmp_path / "work.json"

    work_file.write_text(
        json.dumps(
            {
                "now": "15:10",
                "memory_file": str(memory_file),
                "session_id": "test-session",
                "db_path": str(tmp_path / "db.sqlite"),
                "content": "fallback content",
            }
        ),
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    # No claude, no memsearch → the hook falls back to raw content.
    for name in ("claude", "memsearch"):
        fake = fake_bin / name
        fake.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        fake.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        "MEMSEARCH_SKIP_HOOK_STDIN": "1",
        "MEMSEARCH_IN_STOP_WORKER": "1",
    }

    result = subprocess.run(
        ["bash", str(SCRIPT), "--worker", str(work_file)],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, f"worker failed: {result.stderr}"
    assert memory_file.exists()
    content = memory_file.read_text(encoding="utf-8")
    assert "### 15:10" in content
    assert "<!-- session:test-session db:" in content
    assert "fallback content" in content


def test_zcode_stop_worker_skips_when_content_empty(tmp_path: Path) -> None:
    """When content is empty, the worker should exit without writing."""
    memory_dir = tmp_path / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)
    work_file = tmp_path / "work.json"

    work_file.write_text(
        json.dumps(
            {
                "now": "15:10",
                "memory_file": str(memory_dir / "2026-06-01.md"),
                "session_id": "test-session",
                "db_path": str(tmp_path / "db.sqlite"),
                "content": "",
            }
        ),
        encoding="utf-8",
    )

    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "MEMSEARCH_SKIP_HOOK_STDIN": "1",
        "MEMSEARCH_IN_STOP_WORKER": "1",
    }

    result = subprocess.run(
        ["bash", str(SCRIPT), "--worker", str(work_file)],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert not (memory_dir / "2026-06-01.md").exists()


def test_zcode_stop_hook_no_session_id_exits_cleanly(tmp_path: Path) -> None:
    """When CLAUDE_SESSION_ID is unset, the Stop hook should exit cleanly with {}."""
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        # Explicitly unset session id
        "CLAUDE_SESSION_ID": "",
        "ZCODE_SESSION_ID": "",
    }

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input="{}",
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "{}"
