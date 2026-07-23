from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


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


def test_claude_stop_hook_avoids_empty_array_expansion_under_nounset() -> None:
    script = Path("plugins/claude-code/hooks/stop.sh")
    source = script.read_text(encoding="utf-8")

    assert '"${CLAUDE_SAFE_MODE_ARGS[@]}"' not in source
    assert "CLAUDE_SAFE_MODE_ARG" in source
