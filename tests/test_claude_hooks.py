from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _write_claude_transcript(path: Path, *, turn_uuid: str) -> None:
    path.write_text(
        "\n".join(
            [
                json.dumps({"type": "system", "message": {"content": "start"}}),
                json.dumps({"type": "user", "uuid": turn_uuid, "message": {"content": "Summarize this session"}}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": "I explained the hook behavior."}]},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_claude_hook_memsearch_disable_exits_before_writing_memory(tmp_path: Path) -> None:
    script = Path("plugins/claude-code/hooks/session-start.sh")
    env = {
        **os.environ,
        "MEMSEARCH_DISABLE": "1",
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_DIR": str(tmp_path / ".memsearch"),
    }

    result = subprocess.run(
        ["bash", str(script)],
        input="{}",
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    assert result.stdout.strip() == "{}"
    assert not (tmp_path / ".memsearch").exists()


def test_claude_session_start_does_not_create_journal(tmp_path: Path) -> None:
    script = Path("plugins/claude-code/hooks/session-start.sh")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    memsearch_dir = tmp_path / ".memsearch"
    home.mkdir()
    fake_bin.mkdir()
    (home / ".memsearch").mkdir()
    (home / ".memsearch" / "config.toml").write_text("", encoding="utf-8")

    _write_executable(
        fake_bin / "memsearch",
        """#!/usr/bin/env bash
if [ "$1" = "config" ] && [ "$2" = "list" ]; then
  echo '{"embedding":{"provider":"onnx","model":"","api_key":""},"milvus":{"uri":"http://localhost:19530"}}'
  exit 0
fi
if [ "$1" = "--version" ]; then
  echo "memsearch, version 0.4.16"
  exit 0
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "curl",
        """#!/usr/bin/env bash
echo '{"info":{"version":"0.4.16"}}'
""",
    )

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_DIR": str(memsearch_dir),
        "MEMSEARCH_NO_WATCH": "1",
    }

    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    payload = json.loads(result.stdout)
    memory_dir = memsearch_dir / "memory"
    assert "systemMessage" in payload
    assert memory_dir.is_dir()
    assert list(memory_dir.glob("*.md")) == []


def test_claude_session_start_recent_memory_skips_empty_sessions(tmp_path: Path) -> None:
    script = Path("plugins/claude-code/hooks/session-start.sh")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    memory = tmp_path / ".memsearch" / "memory"
    home.mkdir()
    fake_bin.mkdir()
    (home / ".memsearch").mkdir()
    (home / ".memsearch" / "config.toml").write_text("", encoding="utf-8")
    memory.mkdir(parents=True)
    (memory / "2026-01-01.md").write_text(
        """# 2026-01-01

## Session 09:00

## Session 09:01

### 09:01
- User discussed a useful migration note.

## Session 09:02
""",
        encoding="utf-8",
    )
    (memory / "zzz-scratch.md").write_text(
        """# Scratch

## Session 10:00

### 10:00
- Scratch content should not displace daily journals.
""",
        encoding="utf-8",
    )

    fake_memsearch = fake_bin / "memsearch"
    fake_memsearch.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "config" ] && [ "$2" = "list" ]; then
  echo '{"embedding":{"provider":"onnx","model":"","api_key":""},"milvus":{"uri":"~/.memsearch/milvus.db"}}'
  exit 0
fi
if [ "$1" = "config" ] && [ "$2" = "get" ]; then
  case "$3" in
    embedding.provider) echo "onnx" ;;
    embedding.model) echo "" ;;
    milvus.uri) echo "~/.memsearch/milvus.db" ;;
    *) echo "" ;;
  esac
  exit 0
fi
if [ "$1" = "config" ] && [ "$2" = "set" ]; then
  exit 0
fi
if [ "$1" = "index" ]; then
  exit 0
fi
if [ "$1" = "--version" ]; then
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_memsearch.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_DIR": str(tmp_path / ".memsearch"),
    }

    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    payload = json.loads(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]

    assert "User discussed a useful migration note." in context
    assert "Session 09:01" in context
    assert "Scratch content should not displace daily journals." not in context
    assert "Session 09:00" not in context
    assert "Session 09:02" not in context


def test_claude_session_start_uv_tool_upgrade_hint_preserves_extras(tmp_path: Path) -> None:
    script = Path("plugins/claude-code/hooks/session-start.sh")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    uv_tool_bin = home / ".local" / "share" / "uv" / "tools" / "memsearch" / "bin"
    memsearch_dir = tmp_path / ".memsearch"
    home.mkdir()
    fake_bin.mkdir()
    uv_tool_bin.mkdir(parents=True)
    (home / ".memsearch").mkdir()
    (home / ".memsearch" / "config.toml").write_text("", encoding="utf-8")

    fake_memsearch = uv_tool_bin / "memsearch"
    fake_memsearch.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "config" ] && [ "$2" = "list" ]; then
  echo '{"embedding":{"provider":"voyage","model":"voyage-3-lite","api_key":""},"milvus":{"uri":"http://localhost:19530"}}'
  exit 0
fi
if [ "$1" = "config" ] && [ "$2" = "get" ]; then
  case "$3" in
    embedding.provider) echo "voyage" ;;
    embedding.model) echo "voyage-3-lite" ;;
    milvus.uri) echo "http://localhost:19530" ;;
    *) echo "" ;;
  esac
  exit 0
fi
if [ "$1" = "--version" ]; then
  echo "memsearch, version 0.4.12"
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_memsearch.chmod(0o755)
    (fake_bin / "memsearch").symlink_to(fake_memsearch)

    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env bash
echo '{"info":{"version":"0.4.13"}}'
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_DIR": str(memsearch_dir),
        "MEMSEARCH_NO_WATCH": "1",
        "VOYAGE_API_KEY": "test-key",
    }

    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    status = json.loads(result.stdout)["systemMessage"]
    assert "UPDATE: v0.4.13 available" in status
    assert "uv tool upgrade memsearch" in status
    assert "uv tool install -U 'memsearch[onnx]'" not in status


def test_claude_session_start_reads_resolved_config_once(tmp_path: Path) -> None:
    script = Path("plugins/claude-code/hooks/session-start.sh")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    memsearch_dir = tmp_path / ".memsearch"
    call_log = tmp_path / "memsearch-calls.txt"
    home.mkdir()
    fake_bin.mkdir()
    memsearch_dir.mkdir()
    (home / ".memsearch").mkdir()
    (home / ".memsearch" / "config.toml").write_text("", encoding="utf-8")

    fake_memsearch = fake_bin / "memsearch"
    fake_memsearch.write_text(
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MEMSEARCH_CALL_LOG"
if [ "$1" = "config" ] && [ "$2" = "list" ]; then
  echo '{"embedding":{"provider":"voyage","model":"voyage-3-lite","api_key":"configured-key"},"milvus":{"uri":"http://localhost:19530"}}'
  exit 0
fi
if [ "$1" = "--version" ]; then
  echo "memsearch, version 0.4.15"
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_memsearch.chmod(0o755)

    fake_curl = fake_bin / "curl"
    fake_curl.write_text("""#!/usr/bin/env bash\necho '{"info":{"version":"0.4.15"}}'\n""", encoding="utf-8")
    fake_curl.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_DIR": str(memsearch_dir),
        "MEMSEARCH_NO_WATCH": "1",
        "MEMSEARCH_CALL_LOG": str(call_log),
        "VOYAGE_API_KEY": "",
    }

    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    status = json.loads(result.stdout)["systemMessage"]
    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert "embedding: voyage/voyage-3-lite" in status
    assert "ERROR: VOYAGE_API_KEY not set" not in status
    assert calls.count("config list --resolved --json-output") == 1
    assert not any(call.startswith("config get ") for call in calls)
    assert not any(call.startswith("skills status ") for call in calls)


def test_claude_session_start_falls_back_for_older_cli(tmp_path: Path) -> None:
    script = Path("plugins/claude-code/hooks/session-start.sh")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    memsearch_dir = tmp_path / ".memsearch"
    call_log = tmp_path / "memsearch-calls.txt"
    home.mkdir()
    fake_bin.mkdir()
    memsearch_dir.mkdir()
    (home / ".memsearch").mkdir()
    (home / ".memsearch" / "config.toml").write_text("", encoding="utf-8")

    fake_memsearch = fake_bin / "memsearch"
    fake_memsearch.write_text(
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MEMSEARCH_CALL_LOG"
if [ "$1" = "config" ] && [ "$2" = "list" ]; then
  exit 2
fi
if [ "$1" = "config" ] && [ "$2" = "get" ]; then
  case "$3" in
    embedding.provider) echo "voyage" ;;
    embedding.model) echo "voyage-3-lite" ;;
    embedding.api_key) echo "configured-key" ;;
    milvus.uri) echo "http://localhost:19530" ;;
  esac
  exit 0
fi
if [ "$1" = "--version" ]; then
  echo "memsearch, version 0.4.14"
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_memsearch.chmod(0o755)

    fake_curl = fake_bin / "curl"
    fake_curl.write_text("""#!/usr/bin/env bash\necho '{"info":{"version":"0.4.14"}}'\n""", encoding="utf-8")
    fake_curl.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_DIR": str(memsearch_dir),
        "MEMSEARCH_NO_WATCH": "1",
        "MEMSEARCH_CALL_LOG": str(call_log),
        "VOYAGE_API_KEY": "",
    }

    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    status = json.loads(result.stdout)["systemMessage"]
    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert "embedding: voyage/voyage-3-lite" in status
    assert "ERROR: VOYAGE_API_KEY not set" not in status
    assert calls.count("config list --resolved --json-output") == 1
    assert "config get embedding.provider" in calls
    assert "config get embedding.model" in calls
    assert "config get milvus.uri" in calls
    assert "config get embedding.api_key" in calls


def test_session_start_upgrade_hints_do_not_clobber_extras() -> None:
    for script in (
        Path("plugins/claude-code/hooks/session-start.sh"),
        Path("plugins/codex/hooks/session-start.sh"),
    ):
        source = script.read_text(encoding="utf-8")

        assert "uv tool install -U 'memsearch[onnx]'" not in source
        assert "pip install --upgrade 'memsearch[onnx]'" not in source
        assert "uv tool upgrade memsearch" in source
        assert "pip install --upgrade memsearch" in source


def test_session_start_recent_memory_selects_daily_journals() -> None:
    for script in (
        Path("plugins/claude-code/hooks/session-start.sh"),
        Path("plugins/codex/hooks/session-start.sh"),
    ):
        source = script.read_text(encoding="utf-8")

        assert "DAILY_JOURNAL_PATTERN" in source
        assert "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md" in source


def test_session_start_warns_when_index_state_is_unhealthy(tmp_path: Path) -> None:
    for name, script in (
        ("claude", Path("plugins/claude-code/hooks/session-start.sh")),
        ("codex", Path("plugins/codex/hooks/session-start.sh")),
    ):
        project = tmp_path / name
        home = project / "home"
        fake_bin = project / "bin"
        memsearch_dir = project / ".memsearch"
        home.mkdir(parents=True)
        fake_bin.mkdir()
        memsearch_dir.mkdir()
        (memsearch_dir / ".index-state.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "error",
                    "last_error": "RuntimeError: store unavailable",
                }
            ),
            encoding="utf-8",
        )

        fake_memsearch = fake_bin / "memsearch"
        fake_memsearch.write_text(
            """#!/usr/bin/env bash
if [ "$1" = "config" ] && [ "$2" = "list" ]; then
  echo '{"embedding":{"provider":"onnx","model":"","api_key":""},"milvus":{"uri":"http://localhost:19530"}}'
  exit 0
fi
if [ "$1" = "config" ] && [ "$2" = "get" ]; then
  case "$3" in
    embedding.provider) echo "onnx" ;;
    embedding.model) echo "" ;;
    milvus.uri) echo "http://localhost:19530" ;;
    *) echo "" ;;
  esac
  exit 0
fi
if [ "$1" = "--version" ]; then
  echo "memsearch, version 0.4.14"
  exit 0
fi
exit 0
""",
            encoding="utf-8",
        )
        fake_memsearch.chmod(0o755)

        fake_curl = fake_bin / "curl"
        fake_curl.write_text("""#!/usr/bin/env bash\necho '{"info":{"version":"0.4.14"}}'\n""", encoding="utf-8")
        fake_curl.chmod(0o755)

        env = {
            **os.environ,
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "CLAUDE_PROJECT_DIR": str(project),
            "MEMSEARCH_PROJECT_DIR": str(project),
            "MEMSEARCH_DIR": str(memsearch_dir),
            "MEMSEARCH_NO_WATCH": "1",
        }

        result = subprocess.run(
            ["bash", str(script)],
            input=json.dumps({"cwd": str(project)}),
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )

        status = json.loads(result.stdout)["systemMessage"]
        assert "WARNING: memory index may be stale" in status
        assert "memory-config skill" in status


def test_session_start_shows_skill_candidate_hint(tmp_path: Path) -> None:
    hint = "SKILLS: 2 candidate skill version(s) pending install - run the memory-to-skill skill to review and install."
    for name, script in (
        ("claude", Path("plugins/claude-code/hooks/session-start.sh")),
        ("codex", Path("plugins/codex/hooks/session-start.sh")),
    ):
        project = tmp_path / name
        home = project / "home"
        fake_bin = project / "bin"
        memsearch_dir = project / ".memsearch"
        home.mkdir(parents=True)
        fake_bin.mkdir()
        memsearch_dir.mkdir()
        (memsearch_dir / "skill-candidates").mkdir()

        fake_memsearch = fake_bin / "memsearch"
        fake_memsearch.write_text(
            f"""#!/usr/bin/env bash
if [ "$1" = "config" ] && [ "$2" = "list" ]; then
  echo '{{"embedding":{{"provider":"onnx","model":"","api_key":""}},"milvus":{{"uri":"http://localhost:19530"}}}}'
  exit 0
fi
if [ "$1" = "config" ] && [ "$2" = "get" ]; then
  case "$3" in
    embedding.provider) echo "onnx" ;;
    embedding.model) echo "" ;;
    milvus.uri) echo "http://localhost:19530" ;;
    *) echo "" ;;
  esac
  exit 0
fi
if [ "$1" = "skills" ] && [ "$2" = "status" ] && [ "$3" = "--hint" ]; then
  echo "{hint}"
  exit 0
fi
if [ "$1" = "--version" ]; then
  echo "memsearch, version 0.4.14"
  exit 0
fi
exit 0
""",
            encoding="utf-8",
        )
        fake_memsearch.chmod(0o755)

        fake_curl = fake_bin / "curl"
        fake_curl.write_text("""#!/usr/bin/env bash\necho '{"info":{"version":"0.4.14"}}'\n""", encoding="utf-8")
        fake_curl.chmod(0o755)

        env = {
            **os.environ,
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "CLAUDE_PROJECT_DIR": str(project),
            "MEMSEARCH_PROJECT_DIR": str(project),
            "MEMSEARCH_DIR": str(memsearch_dir),
            "MEMSEARCH_NO_WATCH": "1",
        }

        result = subprocess.run(
            ["bash", str(script)],
            input=json.dumps({"cwd": str(project)}),
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )

        status = json.loads(result.stdout)["systemMessage"]
        assert hint in status


def test_claude_stop_hook_writes_summary_without_safe_mode_flag(tmp_path: Path) -> None:
    script = Path("plugins/claude-code/hooks/stop.sh")
    plugin_root = Path("plugins/claude-code").resolve()
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    memsearch_dir = tmp_path / ".memsearch"
    transcript = tmp_path / "session-123.jsonl"
    claude_args = tmp_path / "claude-args.txt"
    home.mkdir()
    fake_bin.mkdir()
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "system", "message": {"content": "start"}}),
                json.dumps({"type": "user", "uuid": "turn-1", "message": {"content": "Summarize this session"}}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": "I explained the macOS hook issue."}]},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    fake_memsearch = fake_bin / "memsearch"
    fake_memsearch.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "config" ] && [ "$2" = "get" ]; then
  case "$3" in
    embedding.provider) echo "onnx" ;;
    plugins.claude-code.summarize.enabled) echo "true" ;;
    plugins.claude-code.summarize.model) echo "" ;;
    plugins.claude-code.summarize.provider) echo "" ;;
    prompts.summarize) echo "" ;;
    *) echo "" ;;
  esac
  exit 0
fi
if [ "$1" = "index" ]; then
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_memsearch.chmod(0o755)

    fake_claude = fake_bin / "claude"
    fake_claude.write_text(
        """#!/usr/bin/env bash
if [ "${1:-}" = "--help" ]; then
  echo "Usage: claude"
  exit 0
fi
printf '%s\n' "$@" > "$CLAUDE_ARGS_FILE"
echo "- User discussed a macOS stop hook regression."
""",
        encoding="utf-8",
    )
    fake_claude.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_DIR": str(memsearch_dir),
        "CLAUDE_ARGS_FILE": str(claude_args),
    }
    result = subprocess.run(
        ["bash", str(script)],
        input=json.dumps({"transcript_path": str(transcript)}),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    memory_files = list((memsearch_dir / "memory").glob("*.md"))
    assert result.stdout.strip() == "{}"
    assert len(memory_files) == 1
    memory_text = memory_files[0].read_text(encoding="utf-8")
    assert "macOS stop hook regression" in memory_text

    captured_args = claude_args.read_text(encoding="utf-8").splitlines()
    assert captured_args[:4] == ["-p", "--strict-mcp-config", "--tools", ""]
    assert "--safe-mode" not in captured_args
    assert captured_args[captured_args.index("--model") + 1] == "haiku"


def test_claude_stop_hook_sends_large_native_prompt_on_stdin(tmp_path: Path) -> None:
    script = Path("plugins/claude-code/hooks/stop.sh")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    memsearch_dir = tmp_path / ".memsearch"
    transcript = tmp_path / "large.jsonl"
    received = tmp_path / "received.txt"
    home.mkdir()
    fake_bin.mkdir()
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "system", "message": {"content": "start"}}),
                json.dumps({"type": "user", "uuid": "turn-large", "message": {"content": "x" * 200000}}),
                json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_executable(
        fake_bin / "memsearch",
        """#!/usr/bin/env bash
if [ "$1" = "config" ] && [ "$2" = "get" ]; then
  case "$3" in
    embedding.provider) echo onnx ;;
    plugins.claude-code.summarize.enabled) echo true ;;
    plugins.claude-code.summarize.provider) echo "" ;;
    plugins.claude-code.summarize.model) echo "" ;;
    prompts.summarize) echo "" ;;
  esac
fi
if [ "$1" = index ]; then exit 0; fi
""",
    )
    _write_executable(
        fake_bin / "claude",
        """#!/usr/bin/env bash
if [ "${1:-}" = --help ]; then exit 0; fi
cat > "$CLAUDE_INPUT_FILE"
echo '- Large turn summarized.'
""",
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CLAUDE_PLUGIN_ROOT": str(Path("plugins/claude-code").resolve()),
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_DIR": str(memsearch_dir),
        "CLAUDE_INPUT_FILE": str(received),
    }
    result = subprocess.run(
        ["bash", str(script)],
        input=json.dumps({"transcript_path": str(transcript)}),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert result.stdout.strip() == "{}"
    assert len(received.read_text(encoding="utf-8")) > 200000
    memory_text = next((memsearch_dir / "memory").glob("*.md")).read_text(encoding="utf-8")
    assert "Large turn summarized." in memory_text
    assert "x" * 1000 not in memory_text


@pytest.mark.parametrize("route", ["native", "provider"])
@pytest.mark.parametrize("mode", ["missing", "nonzero", "empty", "timeout"])
def test_claude_stop_hook_failure_never_persists_transcript(tmp_path: Path, route: str, mode: str) -> None:
    script = Path("plugins/claude-code/hooks/stop.sh")
    home, fake_bin, memsearch_dir = tmp_path / "home", tmp_path / "bin", tmp_path / ".memsearch"
    transcript = tmp_path / "session.jsonl"
    home.mkdir()
    fake_bin.mkdir()
    marker = "SECRET-TRANSCRIPT-MARKER"
    _write_claude_transcript(transcript, turn_uuid="turn-failure")
    transcript.write_text(
        transcript.read_text(encoding="utf-8").replace("Summarize this session", marker), encoding="utf-8"
    )
    provider = "openai" if route == "provider" else ""
    provider_mode = mode if route == "provider" else "success"
    _write_executable(
        fake_bin / "memsearch",
        f"""#!/usr/bin/env bash
if [ "$1" = config ] && [ "$2" = get ]; then
  case "$3" in
    embedding.provider) echo onnx ;;
    plugins.claude-code.summarize.enabled) echo true ;;
    plugins.claude-code.summarize.provider) echo "{provider}" ;;
    *) echo "" ;;
  esac
fi
if [ "$1" = index ]; then exit 0; fi
if [ "$1" = summarize ]; then
  case "{provider_mode}" in
    missing) exit 127 ;;
    nonzero) exit 23 ;;
    empty) exit 0 ;;
    timeout) echo should-not-run ;;
  esac
fi
""",
    )
    if route == "native" and mode != "missing":
        body = '#!/usr/bin/env bash\nif [ "${1:-}" = --help ]; then exit 0; fi\n'
        body += {"nonzero": "exit 23\n", "empty": "exit 0\n", "timeout": "echo should-not-run\n"}[mode]
        _write_executable(fake_bin / "claude", body)
    if mode == "timeout":
        _write_executable(
            fake_bin / "timeout",
            '#!/usr/bin/env bash\nif [ "$1" = 110 ]; then exit 124; fi\nshift\nexec "$@"\n',
        )
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CLAUDE_PLUGIN_ROOT": str(Path("plugins/claude-code").resolve()),
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_DIR": str(memsearch_dir),
    }
    subprocess.run(
        ["bash", str(script)],
        input=json.dumps({"transcript_path": str(transcript)}),
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=125,
    )
    memory_text = next((memsearch_dir / "memory").glob("*.md")).read_text(encoding="utf-8")
    assert marker not in memory_text
    assert "transcript content was omitted" in memory_text
    assert "session:session turn:turn-failure" in memory_text


def test_claude_stop_hook_groups_session_headings(tmp_path: Path) -> None:
    script = Path("plugins/claude-code/hooks/stop.sh")
    plugin_root = Path("plugins/claude-code").resolve()
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    memsearch_dir = tmp_path / ".memsearch"
    transcript_a = tmp_path / "session-a.jsonl"
    transcript_b = tmp_path / "session-b.jsonl"
    home.mkdir()
    fake_bin.mkdir()
    _write_claude_transcript(transcript_a, turn_uuid="turn-a")
    _write_claude_transcript(transcript_b, turn_uuid="turn-b")

    _write_executable(
        fake_bin / "memsearch",
        """#!/usr/bin/env bash
if [ "$1" = "config" ] && [ "$2" = "get" ]; then
  case "$3" in
    embedding.provider) echo "onnx" ;;
    plugins.claude-code.summarize.enabled) echo "true" ;;
    plugins.claude-code.summarize.model) echo "" ;;
    plugins.claude-code.summarize.provider) echo "" ;;
    prompts.summarize) echo "" ;;
    *) echo "" ;;
  esac
  exit 0
fi
if [ "$1" = "index" ]; then
  exit 0
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "claude",
        """#!/usr/bin/env bash
if [ "${1:-}" = "--help" ]; then
  echo "Usage: claude"
  exit 0
fi
echo "- Captured a session summary."
""",
    )
    _write_executable(
        fake_bin / "date",
        """#!/usr/bin/env bash
case "${1:-}" in
  +%Y-%m-%d) echo "2026-07-23" ;;
  +%H:%M) echo "12:34" ;;
  *) /bin/date "$@" ;;
esac
""",
    )

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_DIR": str(memsearch_dir),
    }

    def run_stop(transcript: Path) -> None:
        result = subprocess.run(
            ["bash", str(script)],
            input=json.dumps({"transcript_path": str(transcript)}),
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        assert result.stdout.strip() == "{}"

    memory_file = memsearch_dir / "memory" / "2026-07-23.md"

    run_stop(transcript_a)
    memory_text = memory_file.read_text(encoding="utf-8")
    assert memory_text.count("## Session 12:34") == 1
    assert memory_text.count("### 12:34") == 1
    assert memory_text.count("session:session-a ") == 1

    run_stop(transcript_a)
    memory_text = memory_file.read_text(encoding="utf-8")
    assert memory_text.count("## Session 12:34") == 1
    assert memory_text.count("### 12:34") == 2
    assert memory_text.count("session:session-a ") == 2

    run_stop(transcript_b)
    memory_text = memory_file.read_text(encoding="utf-8")
    sections = memory_text.split("## Session 12:34")
    assert len(sections) == 3
    assert sections[1].count("session:session-a ") == 2
    assert "session:session-b " not in sections[1]
    assert sections[2].count("session:session-b ") == 1


def test_claude_stop_hook_avoids_empty_array_expansion_under_nounset() -> None:
    script = Path("plugins/claude-code/hooks/stop.sh")
    source = script.read_text(encoding="utf-8")

    assert '"${CLAUDE_SAFE_MODE_ARGS[@]}"' not in source
    assert "CLAUDE_SAFE_MODE_ARG" in source


def _install_layout(root: Path, version: str) -> Path:
    """Create a uv/pipx-style install tree and return its bin directory."""
    bin_dir = root / "bin"
    site = root / "lib" / "python3.14" / "site-packages"
    bin_dir.mkdir(parents=True)
    site.mkdir(parents=True)
    (site / f"memsearch-{version}.dist-info").mkdir()
    return bin_dir


def _session_start_env(tmp_path: Path, home: Path, fake_bin: Path, call_log: Path) -> dict[str, str]:
    return {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_DIR": str(tmp_path / ".memsearch"),
        "MEMSEARCH_NO_WATCH": "1",
        "MEMSEARCH_CALL_LOG": str(call_log),
    }


def test_claude_session_start_reads_version_from_dist_info(tmp_path: Path) -> None:
    """The status version comes from dist-info, without a second CLI start."""
    script = Path("plugins/claude-code/hooks/session-start.sh")
    home = tmp_path / "home"
    (home / ".memsearch").mkdir(parents=True)
    (home / ".memsearch" / "config.toml").write_text("", encoding="utf-8")
    (tmp_path / ".memsearch").mkdir()
    call_log = tmp_path / "memsearch-calls.txt"

    fake_bin = _install_layout(tmp_path / "opt", "9.9.9")
    _write_executable(
        fake_bin / "memsearch",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MEMSEARCH_CALL_LOG"
if [ "$1" = "config" ] && [ "$2" = "list" ]; then
  echo '{"embedding":{"provider":"onnx","model":"tiny"},"milvus":{"uri":"/tmp/x.db"}}'
  exit 0
fi
if [ "$1" = "--version" ]; then
  echo "memsearch, version 0.0.0-should-not-be-used"
  exit 0
fi
exit 0
""",
    )
    _write_executable(fake_bin / "curl", """#!/usr/bin/env bash\necho '{"info":{"version":"9.9.9"}}'\n""")

    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=_session_start_env(tmp_path, home, fake_bin, call_log),
        check=True,
    )

    status = json.loads(result.stdout)["systemMessage"]
    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert "[memsearch v9.9.9]" in status
    assert "--version" not in calls


def test_claude_session_start_falls_back_to_cli_version_without_dist_info(tmp_path: Path) -> None:
    """Layouts with no discoverable dist-info still report a version."""
    script = Path("plugins/claude-code/hooks/session-start.sh")
    home = tmp_path / "home"
    (home / ".memsearch").mkdir(parents=True)
    (home / ".memsearch" / "config.toml").write_text("", encoding="utf-8")
    (tmp_path / ".memsearch").mkdir()
    call_log = tmp_path / "memsearch-calls.txt"

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "memsearch",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MEMSEARCH_CALL_LOG"
if [ "$1" = "config" ] && [ "$2" = "list" ]; then
  echo '{"embedding":{"provider":"onnx","model":"tiny"},"milvus":{"uri":"/tmp/x.db"}}'
  exit 0
fi
if [ "$1" = "--version" ]; then
  echo "memsearch, version 1.2.3"
  exit 0
fi
exit 0
""",
    )
    _write_executable(fake_bin / "curl", """#!/usr/bin/env bash\necho '{"info":{"version":"1.2.3"}}'\n""")

    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=_session_start_env(tmp_path, home, fake_bin, call_log),
        check=True,
    )

    status = json.loads(result.stdout)["systemMessage"]
    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert "[memsearch v1.2.3]" in status
    assert "--version" in calls


def _write_bsd_readlink_shim(shim_dir: Path) -> None:
    """Shadow readlink with a macOS-like implementation that rejects -f."""
    real_readlink = shutil.which("readlink")
    assert real_readlink is not None
    _write_executable(
        shim_dir / "readlink",
        f"""#!/usr/bin/env bash
for arg in "$@"; do
  if [ "$arg" = "-f" ]; then
    echo "readlink: illegal option -- f" >&2
    exit 1
  fi
done
exec "{real_readlink}" "$@"
""",
    )


@pytest.mark.parametrize(
    "common_sh",
    ["plugins/claude-code/hooks/common.sh", "plugins/codex/hooks/common.sh"],
    ids=["claude-code", "codex"],
)
def test_dist_info_version_resolves_symlinked_bin_without_gnu_readlink(tmp_path: Path, common_sh: str) -> None:
    """A symlinked entry point (uv tool / pipx layout) must resolve to its
    install tree even where readlink lacks -f (BSD readlink on macOS)."""
    home = tmp_path / "home"
    home.mkdir()
    install_bin = _install_layout(tmp_path / "opt", "9.9.9")
    _write_executable(install_bin / "memsearch", "#!/usr/bin/env bash\nexit 0\n")

    # ~/.local/bin/memsearch -> ../opt/bin/memsearch, a relative target like
    # the ones uv writes.
    link_bin = tmp_path / "links"
    link_bin.mkdir()
    (link_bin / "memsearch").symlink_to(Path("..") / "opt" / "bin" / "memsearch")

    shim_bin = tmp_path / "shims"
    shim_bin.mkdir()
    _write_bsd_readlink_shim(shim_bin)

    result = subprocess.run(
        ["bash", "-c", 'source "$1" < /dev/null && _installed_version_from_dist_info', "bash", common_sh],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{shim_bin}:{link_bin}:{os.environ['PATH']}",
            "MEMSEARCH_DISABLE": "",
        },
        check=True,
    )

    assert result.stdout == "9.9.9"


def test_claude_session_start_resolves_symlinked_bin_without_gnu_readlink(tmp_path: Path) -> None:
    """The full SessionStart path works through a symlinked uv tool install
    without GNU readlink: version comes from dist-info (no --version call) and
    the update hint recognizes the uv/tools layout behind the symlink."""
    script = Path("plugins/claude-code/hooks/session-start.sh")
    home = tmp_path / "home"
    (home / ".memsearch").mkdir(parents=True)
    (home / ".memsearch" / "config.toml").write_text("", encoding="utf-8")
    (tmp_path / ".memsearch").mkdir()
    call_log = tmp_path / "memsearch-calls.txt"

    install_bin = _install_layout(tmp_path / "share" / "uv" / "tools" / "memsearch", "9.9.9")
    _write_executable(
        install_bin / "memsearch",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MEMSEARCH_CALL_LOG"
if [ "$1" = "config" ] && [ "$2" = "list" ]; then
  echo '{"embedding":{"provider":"onnx","model":"tiny"},"milvus":{"uri":"/tmp/x.db"}}'
  exit 0
fi
if [ "$1" = "--version" ]; then
  echo "memsearch, version 0.0.0-should-not-be-used"
  exit 0
fi
exit 0
""",
    )

    link_bin = tmp_path / "local-bin"
    link_bin.mkdir()
    (link_bin / "memsearch").symlink_to(Path("..") / "share" / "uv" / "tools" / "memsearch" / "bin" / "memsearch")

    fake_bin = tmp_path / "shims"
    fake_bin.mkdir()
    _write_bsd_readlink_shim(fake_bin)
    _write_executable(fake_bin / "curl", """#!/usr/bin/env bash\necho '{"info":{"version":"9.9.10"}}'\n""")

    env = _session_start_env(tmp_path, home, fake_bin, call_log)
    env["PATH"] = f"{link_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    status = json.loads(result.stdout)["systemMessage"]
    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert "[memsearch v9.9.9]" in status
    assert "--version" not in calls
    assert "uv tool upgrade memsearch" in status


def test_claude_session_start_caches_pypi_lookup(tmp_path: Path) -> None:
    """PyPI is queried on the first start and served from cache on the next."""
    script = Path("plugins/claude-code/hooks/session-start.sh")
    home = tmp_path / "home"
    (home / ".memsearch").mkdir(parents=True)
    (home / ".memsearch" / "config.toml").write_text("", encoding="utf-8")
    (tmp_path / ".memsearch").mkdir()
    call_log = tmp_path / "memsearch-calls.txt"
    curl_log = tmp_path / "curl-calls.txt"

    fake_bin = _install_layout(tmp_path / "opt", "1.0.0")
    _write_executable(
        fake_bin / "memsearch",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MEMSEARCH_CALL_LOG"
if [ "$1" = "config" ] && [ "$2" = "list" ]; then
  echo '{"embedding":{"provider":"onnx","model":"tiny"},"milvus":{"uri":"/tmp/x.db"}}'
  exit 0
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "curl",
        """#!/usr/bin/env bash\nprintf 'called\\n' >> "$CURL_CALL_LOG"\necho '{"info":{"version":"2.0.0"}}'\n""",
    )

    env = _session_start_env(tmp_path, home, fake_bin, call_log)
    env["CURL_CALL_LOG"] = str(curl_log)

    first = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, check=True)
    second = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, check=True)

    assert curl_log.read_text(encoding="utf-8").count("called") == 1
    assert (home / ".memsearch" / ".pypi-latest").read_text(encoding="utf-8") == "2.0.0"
    # The update hint survives the cache round trip.
    for run in (first, second):
        assert "UPDATE: v2.0.0 available" in json.loads(run.stdout)["systemMessage"]


def test_claude_session_start_caches_failed_pypi_lookup(tmp_path: Path) -> None:
    """A failed lookup is cached too, so an offline machine stops retrying."""
    script = Path("plugins/claude-code/hooks/session-start.sh")
    home = tmp_path / "home"
    (home / ".memsearch").mkdir(parents=True)
    (home / ".memsearch" / "config.toml").write_text("", encoding="utf-8")
    (tmp_path / ".memsearch").mkdir()
    call_log = tmp_path / "memsearch-calls.txt"
    curl_log = tmp_path / "curl-calls.txt"

    fake_bin = _install_layout(tmp_path / "opt", "1.0.0")
    _write_executable(
        fake_bin / "memsearch",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MEMSEARCH_CALL_LOG"
if [ "$1" = "config" ] && [ "$2" = "list" ]; then
  echo '{"embedding":{"provider":"onnx","model":"tiny"},"milvus":{"uri":"/tmp/x.db"}}'
  exit 0
fi
exit 0
""",
    )
    # Stand in for an unreachable index: no output, non-zero exit.
    _write_executable(
        fake_bin / "curl",
        """#!/usr/bin/env bash\nprintf 'called\\n' >> "$CURL_CALL_LOG"\nexit 6\n""",
    )

    env = _session_start_env(tmp_path, home, fake_bin, call_log)
    env["CURL_CALL_LOG"] = str(curl_log)

    first = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, check=True)
    second = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, check=True)

    cache = home / ".memsearch" / ".pypi-latest"
    assert curl_log.read_text(encoding="utf-8").count("called") == 1
    assert cache.exists() and cache.read_text(encoding="utf-8") == ""
    # No latest version known, so no hint is claimed either way.
    for run in (first, second):
        assert "UPDATE:" not in json.loads(run.stdout)["systemMessage"]


COMMON_SH_PLUGINS = ["plugins/claude-code/hooks/common.sh", "plugins/codex/hooks/common.sh"]


def _spawn_fake_watcher(tmp_path: Path, target: Path) -> subprocess.Popen[bytes]:
    """Start a stub standing in for `memsearch watch <target>`.

    Its argv contains "memsearch" so the reaper's PID-reuse guard recognises it,
    and start_new_session mirrors the setsid/nohup launch in start_watch, which
    makes it a process-group leader so _kill_tree's group kill has a group.
    """
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "memsearch"
    _write_executable(stub, "#!/usr/bin/env bash\nsleep 300\n")
    return subprocess.Popen([str(stub), "watch", str(target)], start_new_session=True)


def _run_registry_snippet(
    common_sh: str, snippet: str, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'source "$1" < /dev/null\n{snippet}', "bash", common_sh, *args],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )


def _registry_env(tmp_path: Path, project: Path, state_dir: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_PROJECT_DIR": str(project),
        "MEMSEARCH_STATE_DIR": str(state_dir),
        "MEMSEARCH_DISABLE": "",
    }


@pytest.mark.parametrize("common_sh", COMMON_SH_PLUGINS, ids=["claude-code", "codex"])
def test_watch_registry_lives_outside_the_watched_tree(tmp_path: Path, common_sh: str) -> None:
    """The handle used to reap a watcher must outlive the directory it watches.

    A pidfile stored under the project tree is destroyed with that tree (e.g.
    `git worktree remove`), which is exactly when reaping is needed.
    """
    project = tmp_path / "project"
    project.mkdir()
    state_dir = tmp_path / "state"

    result = _run_registry_snippet(
        common_sh,
        'printf "%s\\n%s\\n" "$WATCH_REGISTRY_DIR" "$MEMSEARCH_DIR"',
        _registry_env(tmp_path, project, state_dir),
    )
    registry_dir, memsearch_dir = result.stdout.splitlines()

    assert Path(registry_dir) == state_dir / "watchers"
    assert not Path(registry_dir).is_relative_to(project)
    assert not Path(registry_dir).is_relative_to(memsearch_dir)


@pytest.mark.parametrize("common_sh", COMMON_SH_PLUGINS, ids=["claude-code", "codex"])
def test_reap_stale_watchers_kills_watcher_whose_target_is_gone(tmp_path: Path, common_sh: str) -> None:
    """Positive control: the removed-worktree case the in-tree pidfile cannot reach."""
    project = tmp_path / "project"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    state_dir = tmp_path / "state"

    watcher = _spawn_fake_watcher(tmp_path, memory)
    try:
        _run_registry_snippet(
            common_sh,
            '_watch_registry_record "$2" "$3"',
            _registry_env(tmp_path, project, state_dir),
            str(watcher.pid),
            str(memory),
        )
        entry = state_dir / "watchers" / f"{watcher.pid}.pid"
        assert entry.exists(), "recording a watcher must create its registry entry"

        shutil.rmtree(project)  # the worktree goes away, taking the in-tree pidfile with it

        _run_registry_snippet(common_sh, "reap_stale_watchers", _registry_env(tmp_path, project, state_dir))
        assert watcher.wait(timeout=10) is not None
        assert not entry.exists()
    finally:
        if watcher.poll() is None:
            watcher.kill()
            watcher.wait(timeout=10)


@pytest.mark.parametrize("common_sh", COMMON_SH_PLUGINS, ids=["claude-code", "codex"])
def test_reap_stale_watchers_leaves_live_watchers_alone(tmp_path: Path, common_sh: str) -> None:
    """Negative control: a watcher whose target still exists must survive the sweep.

    Without this, a reaper that killed everything unconditionally would pass the
    positive control above.
    """
    project = tmp_path / "project"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    state_dir = tmp_path / "state"

    watcher = _spawn_fake_watcher(tmp_path, memory)
    try:
        _run_registry_snippet(
            common_sh,
            '_watch_registry_record "$2" "$3"',
            _registry_env(tmp_path, project, state_dir),
            str(watcher.pid),
            str(memory),
        )
        entry = state_dir / "watchers" / f"{watcher.pid}.pid"
        assert entry.exists()

        _run_registry_snippet(common_sh, "reap_stale_watchers", _registry_env(tmp_path, project, state_dir))

        with pytest.raises(subprocess.TimeoutExpired):
            watcher.wait(timeout=1)
        assert entry.exists(), "a live watcher must keep its registry entry"
    finally:
        watcher.kill()
        watcher.wait(timeout=10)
