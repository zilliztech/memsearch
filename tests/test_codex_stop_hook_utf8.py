from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path("plugins/codex/hooks/stop.sh")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


@pytest.mark.parametrize("has_timeout", [True, False])
@pytest.mark.parametrize(
    ("configured_model", "expected_model", "expected_effort"),
    [("", "gpt-6-sol", "none"), ("gpt-6-sol", "gpt-6-sol", "none"), ("custom-model", "custom-model", "low")],
)
def test_codex_native_summary_model_and_effort(
    tmp_path: Path, has_timeout: bool, configured_model: str, expected_model: str, expected_effort: str
) -> None:
    """Capture a turn with the default or an explicitly configured native model."""
    memory_file = tmp_path / ".memsearch" / "memory" / "2026-11-27.md"
    work_file = tmp_path / "work.json"
    work_file.write_text(
        json.dumps(
            {
                "now": "10:00",
                "memory_file": str(memory_file),
                "session_id": "native-summary-test",
                "content": "The release marker is maple-8412; retention is 47 minutes.",
                "user_question": "Remember the release settings.",
                "last_msg": "Recorded the settings.",
            }
        ),
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "memsearch",
        '#!/bin/sh\ncase "$3" in\n  plugins.codex.summarize.model) printf "%s\\n" "$TEST_MODEL" ;;\nesac\nexit 0\n',
    )
    _write_executable(
        fake_bin / "codex",
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['TEST_ARGS']).write_text(json.dumps(sys.argv[1:]))\n"
        "print('- The release marker is maple-8412; retention is 47 minutes.')\n",
    )
    _write_executable(
        fake_bin / "python3",
        '#!/bin/sh\ncase "$1" in\n  */maintenance-runner.py) exit 0 ;;\nesac\nexec "$TEST_PYTHON" "$@"\n',
    )
    _write_executable(
        fake_bin / "timeout",
        '#!/bin/sh\nprintf "%s\\n" "$1" > "$TEST_TIMEOUT"\nshift\nexec "$@"\n',
    )
    environment = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "MEMSEARCH_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_DIR": str(tmp_path / ".memsearch"),
        "MEMSEARCH_NO_WATCH": "1",
        "PATH": f"{fake_bin}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "TEST_MODEL": configured_model,
        "TEST_ARGS": str(tmp_path / "args.json"),
        "TEST_TIMEOUT": str(tmp_path / "timeout.txt"),
        "TEST_PYTHON": sys.executable,
    }
    # Exercise the macOS branch even when GNU timeout is installed on the host.
    command = 'exec bash "$@"'
    if not has_timeout:
        command = (
            'command() { if [[ "$1" == -v && "$2" == timeout ]]; then return 1; fi; '
            'builtin command "$@"; }; export -f command; ' + command
        )
    result = subprocess.run(
        ["bash", "-c", command, "_", str(SCRIPT.resolve()), "--worker", str(work_file)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    args = json.loads((tmp_path / "args.json").read_text())
    assert args[args.index("-m") + 1] == expected_model
    assert f'model_reasoning_effort="{expected_effort}"' in args
    assert "features.hooks=false" in args
    assert "--ephemeral" in args
    timeout_file = tmp_path / "timeout.txt"
    assert timeout_file.exists() is has_timeout
    if has_timeout:
        assert timeout_file.read_text().strip() == "30"
    journal = memory_file.read_text()
    assert "<!-- session:native-summary-test " in journal
    assert "- The release marker is maple-8412; retention is 47 minutes." in journal
    assert "- User asked:" not in journal


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
    journal = ""
    while time.monotonic() < deadline:
        journal_files = list((memsearch_dir / "memory").glob("*.md"))
        if journal_files:
            assert len(journal_files) == 1
            journal = journal_files[0].read_text(encoding="utf-8")
            # The worker appends a blank line after the summary. The heading and anchor appear first.
            if journal.endswith("\n\n"):
                break
        time.sleep(0.05)

    assert journal.endswith("\n\n"), "capture worker did not finish writing the journal entry"
    assert "AGENTS.md instructions" not in journal
    assert "environment_context" not in journal
    assert "[User]: Remember the synthetic orchard marker." in journal
    assert "[Codex]: The synthetic orchard marker is recorded." in journal
