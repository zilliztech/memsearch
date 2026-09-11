from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

CAPABILITY_MARKER = "[memsearch] Recall available if needed"
RETRIEVED_MARKER = "[memsearch] Retrieved memory context attached."
# Claude Code shows systemMessage to the user only; the model reads
# hookSpecificOutput.additionalContext, so the Claude hook carries the hint in both.
# Codex has no such split and keeps the plain systemMessage.
EXPECTED_CAPABILITY_JSON = {
    "claude-code": {
        "systemMessage": CAPABILITY_MARKER,
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": CAPABILITY_MARKER},
    },
    "codex": {"systemMessage": CAPABILITY_MARKER},
}
EXPECTED_CAPABILITY_OUTPUT = {
    platform: json.dumps(payload, separators=(", ", ": ")).encode() + b"\n"
    for platform, payload in EXPECTED_CAPABILITY_JSON.items()
}
HOOKS = {
    "claude-code": Path("plugins/claude-code/hooks/user-prompt-submit.sh"),
    "codex": Path("plugins/codex/hooks/user-prompt-submit.sh"),
}


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _run_hook(
    tmp_path: Path,
    platform: str,
    prompt: str,
    *,
    with_memsearch: bool,
) -> tuple[subprocess.CompletedProcess[bytes], Path]:
    case_dir = tmp_path / platform
    home = case_dir / "home"
    fake_bin = case_dir / "bin"
    project = case_dir / "project"
    call_log = case_dir / "memsearch-calls.txt"
    home.mkdir(parents=True)
    fake_bin.mkdir()
    project.mkdir()

    if with_memsearch:
        _write_executable(
            fake_bin / "memsearch",
            '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$MEMSEARCH_TEST_CALL_LOG"\nexit 0\n',
        )

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "CLAUDE_PROJECT_DIR": str(project),
        "MEMSEARCH_PROJECT_DIR": str(project),
        "MEMSEARCH_TEST_CALL_LOG": str(call_log),
    }
    result = subprocess.run(
        ["bash", str(HOOKS[platform].resolve())],
        cwd=project,
        input=json.dumps({"prompt": prompt}).encode(),
        capture_output=True,
        env=env,
        check=False,
    )
    return result, call_log


@pytest.mark.parametrize("platform", HOOKS)
def test_user_prompt_submit_long_prompt_emits_capability_without_search(tmp_path: Path, platform: str) -> None:
    result, call_log = _run_hook(
        tmp_path,
        platform,
        "Explain the current project status without using memory.",
        with_memsearch=True,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout == EXPECTED_CAPABILITY_OUTPUT[platform]
    assert result.stdout[-1:] == b"\n"
    assert json.loads(result.stdout) == EXPECTED_CAPABILITY_JSON[platform]
    assert not call_log.exists(), "The capability hook must not invoke memsearch search or any other CLI command"


@pytest.mark.parametrize("platform", HOOKS)
def test_user_prompt_submit_short_prompt_is_noop(tmp_path: Path, platform: str) -> None:
    result, call_log = _run_hook(tmp_path, platform, "2+2?", with_memsearch=True)

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout == b"{}\n"
    assert result.stdout[-1:] == b"\n"
    assert not call_log.exists()


@pytest.mark.parametrize("platform", HOOKS)
def test_user_prompt_submit_without_cli_is_noop(tmp_path: Path, platform: str) -> None:
    result, call_log = _run_hook(
        tmp_path,
        platform,
        "This prompt is long enough to reach the CLI availability gate.",
        with_memsearch=False,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout == b"{}\n"
    assert result.stdout[-1:] == b"\n"
    assert not call_log.exists()


def test_capability_marker_is_synchronized_across_direct_consumers() -> None:
    consumers = [
        Path("CLAUDE.md"),
        Path("plugins/claude-code/hooks/user-prompt-submit.sh"),
        Path("plugins/claude-code/skills/memory-recall/SKILL.md"),
        Path("plugins/claude-code/README.md"),
        Path("docs/platforms/claude-code/how-it-works.md"),
        Path("docs/platforms/claude-code/troubleshooting.md"),
        Path("plugins/codex/hooks/user-prompt-submit.sh"),
        Path("plugins/codex/skills/memory-recall/SKILL.md"),
        Path("plugins/codex/README.md"),
        Path("docs/platforms/codex/how-it-works.md"),
    ]

    for consumer in consumers:
        assert CAPABILITY_MARKER in consumer.read_text(encoding="utf-8"), consumer


def test_retrieved_marker_is_synchronized_across_dsh_direct_consumers() -> None:
    consumers = [
        Path("plugins/dsh/index.js"),
        Path("plugins/dsh/README.md"),
        Path("docs/platforms/dsh/how-it-works.md"),
        Path("plugins/dsh/tests/test_parse_transcript.py"),
    ]

    for consumer in consumers:
        assert RETRIEVED_MARKER in consumer.read_text(encoding="utf-8"), consumer
