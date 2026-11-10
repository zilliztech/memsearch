from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path("plugins/codex/hooks/stop.sh")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_codex_stop_worker_fallback_summary_preserves_utf8(tmp_path: Path) -> None:
    memory_dir = tmp_path / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)
    memory_file = memory_dir / "2026-06-01.md"
    work_file = tmp_path / "work.json"
    long_cyrillic_message = "Привет мир, проверяем безопасную обрезку UTF-8. " * 120

    work_file.write_text(
        json.dumps(
            {
                "now": "15:10",
                "memory_file": str(memory_file),
                "session_id": "test-session",
                "transcript_path": str(tmp_path / "rollout.jsonl"),
                "content": "fallback content",
                "user_question": "как поправить?",
                "last_msg": long_cyrillic_message,
            }
        ),
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_codex = fake_bin / "codex"
    fake_codex.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    fake_memsearch = fake_bin / "memsearch"
    fake_memsearch.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_memsearch.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "MEMSEARCH_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_SKIP_HOOK_STDIN": "1",
        # Force the native summarizer path to return no summary so fallback
        # formatting is exercised even on machines with codex installed.
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
    }
    subprocess.run(["bash", str(SCRIPT), "--worker", str(work_file)], check=True, env=env)

    content = memory_file.read_text(encoding="utf-8")
    assert "- User asked: как поправить?" in content
    assert "- Codex: Привет мир" in content
    assert "..." in content


def test_codex_stop_hook_filters_host_envelope_from_journal(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    rollout = tmp_path / "rollout.jsonl"
    host_envelope = (
        "# AGENTS.md instructions\n\n"
        "<INSTRUCTIONS>\nSynthetic project rules.\n</INSTRUCTIONS>\n"
        "<environment_context>\n"
        "  <current_date>2026-09-18</current_date>\n"
        "  <timezone>UTC</timezone>\n"
        "  <filesystem><workspace_roots><root>/fixture</root></workspace_roots></filesystem>\n"
        "</environment_context>"
    )
    rows = [
        {"type": "event_msg", "payload": {"type": "task_started"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "synthetic host policy"}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": host_envelope}],
            },
        },
        {"type": "world_state", "payload": {"cwd": "/fixture"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Remember the synthetic orchard marker."}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "The synthetic orchard marker is recorded."}],
            },
        },
    ]
    rollout.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "codex", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(fake_bin / "memsearch", "#!/usr/bin/env bash\nexit 0\n")

    memsearch_dir = tmp_path / ".memsearch"
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "CODEX_HOME": str(tmp_path / "codex-home"),
        "MEMSEARCH_PROJECT_DIR": str(project_dir),
        "MEMSEARCH_DIR": str(memsearch_dir),
        "MEMSEARCH_NO_WATCH": "1",
        "PATH": f"{fake_bin}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        input=json.dumps(
            {
                "cwd": str(project_dir),
                "transcript_path": str(rollout),
                "session_id": "synthetic-host-envelope",
            }
        ),
        env=env,
    )
    assert result.stdout == "{}\n"

    deadline = time.monotonic() + 10
    journal_files: list[Path] = []
    while time.monotonic() < deadline:
        journal_files = list((memsearch_dir / "memory").glob("*.md"))
        if journal_files and journal_files[0].stat().st_size:
            break
        time.sleep(0.05)

    assert len(journal_files) == 1
    journal = journal_files[0].read_text(encoding="utf-8")
    assert "AGENTS.md instructions" not in journal
    assert "environment_context" not in journal
    assert "[User]: Remember the synthetic orchard marker." in journal
    assert "[Codex]: The synthetic orchard marker is recorded." in journal
