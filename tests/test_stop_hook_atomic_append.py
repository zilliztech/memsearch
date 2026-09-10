from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path("plugins/codex/hooks/stop.sh")


def _bash_exe() -> str:
    # On Windows, bare `bash` is often the WSL stub (no /bin/bash). Prefer Git Bash.
    if os.name == "nt":
        git_bash = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if git_bash.exists():
            return str(git_bash)
    return shutil.which("bash") or "bash"


def _git_bin_dirs() -> list[str]:
    if os.name != "nt":
        return []
    root = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git"
    return [str(root / "bin"), str(root / "usr" / "bin")]


def _bash_path(path: Path | str) -> str:
    text = str(path)
    if os.name == "nt" and len(text) >= 2 and text[1] == ":":
        return "/" + text[0].lower() + text[2:].replace("\\", "/")
    return text


def _write_work(
    path: Path,
    *,
    memory_file: Path,
    now: str,
    session_id: str,
    user_question: str,
    last_msg: str,
) -> None:
    path.write_text(
        json.dumps(
            {
                "now": now,
                "memory_file": _bash_path(memory_file),
                "session_id": session_id,
                "transcript_path": f"/tmp/{session_id}.jsonl",
                "content": "content",
                "user_question": user_question,
                "last_msg": last_msg,
            }
        ),
        encoding="utf-8",
    )


def _env(tmp_path: Path) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    for name in ("codex", "memsearch"):
        fake = fake_bin / name
        if not fake.exists():
            fake.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            fake.chmod(0o755)
    # Git Bash on Windows often lacks a working `python3`; hooks call python3 for JSON.
    if os.name == "nt":
        shim = fake_bin / "python3"
        shim.write_text(f'#!/usr/bin/env bash\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    path_parts = [str(fake_bin), *_git_bin_dirs(), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    if os.name == "nt":
        path_parts.append(str(Path(sys.executable).parent))
    return {
        **os.environ,
        "HOME": _bash_path(home),
        "MEMSEARCH_PROJECT_DIR": _bash_path(tmp_path),
        "MEMSEARCH_SKIP_HOOK_STDIN": "1",
        "PATH": os.pathsep.join(path_parts),
    }


def _block_for_session(lines: list[str], session_id: str) -> list[str]:
    marker = f"session:{session_id}"
    for index, line in enumerate(lines):
        if marker in line:
            start = index
            while start > 0 and not lines[start].startswith("### "):
                start -= 1
            end = index + 1
            while end < len(lines) and not lines[end].startswith("### ") and not lines[end].startswith("<!-- session:"):
                end += 1
            return lines[start:end]
    raise AssertionError(f"session marker not found: {session_id}")


def test_codex_stop_worker_writes_entry_as_contiguous_block(tmp_path: Path) -> None:
    memory_dir = tmp_path / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)
    memory_file = memory_dir / "2026-09-10.md"
    env = _env(tmp_path)

    for now, session_id, question, msg in (
        ("10:00", "session-alpha", "alpha question?", "alpha summary line"),
        ("10:00", "session-beta", "beta question?", "beta summary line"),
    ):
        work_file = tmp_path / f"work-{session_id}.json"
        _write_work(
            work_file,
            memory_file=memory_file,
            now=now,
            session_id=session_id,
            user_question=question,
            last_msg=msg,
        )
        subprocess.run([_bash_exe(), str(SCRIPT), "--worker", str(work_file)], check=True, env=env)

    lines = [line for line in memory_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    for session_id, msg in (
        ("session-alpha", "alpha summary line"),
        ("session-beta", "beta summary line"),
    ):
        block = _block_for_session(lines, session_id)
        assert block[0].startswith("### ")
        assert f"session:{session_id}" in block[1]
        assert msg in "\n".join(block)
        assert block.index(block[1]) == 1


def test_codex_stop_worker_concurrent_appends_keep_entries_whole(tmp_path: Path) -> None:
    memory_dir = tmp_path / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)
    memory_file = memory_dir / "2026-09-10.md"
    env = _env(tmp_path)

    sessions = []
    for index in range(8):
        session_id = f"session-{index}"
        work_file = tmp_path / f"work-{session_id}.json"
        _write_work(
            work_file,
            memory_file=memory_file,
            now="11:22",
            session_id=session_id,
            user_question=f"q{index}",
            last_msg=f"unique-summary-{index}",
        )
        sessions.append(session_id)
        subprocess.Popen(
            [_bash_exe(), str(SCRIPT), "--worker", str(work_file)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # Workers append immediately before indexing; wait for all markers.
    deadline = 20.0
    waited = 0.0
    while waited < deadline:
        text = memory_file.read_text(encoding="utf-8") if memory_file.exists() else ""
        if all(f"session:{sid}" in text for sid in sessions):
            break
        waited += 0.1
        time.sleep(0.1)
    else:
        raise AssertionError("concurrent workers did not finish appending")

    lines = [line for line in memory_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    for index, session_id in enumerate(sessions):
        block = _block_for_session(lines, session_id)
        assert block[0].startswith("### ")
        assert f"session:{session_id}" in block[1]
        assert f"unique-summary-{index}" in "\n".join(block)
