from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _run_stop_hook(
    tmp_path: Path,
    *,
    index_status: int,
    create_zero_segment: bool,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    script = Path("plugins/claude-code/hooks/stop.sh")
    plugin_root = Path("plugins/claude-code").resolve()
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    memsearch_dir = tmp_path / ".memsearch"
    milvus_uri = home / ".memsearch" / "milvus.db"
    zero_segment = milvus_uri / "data" / "insert_log" / "zero.parquet"
    transcript = tmp_path / "session-123.jsonl"
    home.mkdir()
    fake_bin.mkdir()
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "system", "message": {"content": "start"}}),
                json.dumps({"type": "user", "uuid": "turn-1", "message": {"content": "Remember this"}}),
                json.dumps({"type": "assistant", "message": {"content": "I recorded the result."}}),
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
    milvus.uri) echo "$FAKE_MILVUS_URI" ;;
    plugins.claude-code.summarize.enabled) echo "true" ;;
    plugins.claude-code.summarize.model) echo "" ;;
    plugins.claude-code.summarize.provider) echo "" ;;
    prompts.summarize) echo "" ;;
    *) echo "" ;;
  esac
  exit 0
fi
if [ "$1" = "index" ]; then
  if [ "$FAKE_CREATE_ZERO_SEGMENT" = "1" ]; then
    mkdir -p "$(dirname "$FAKE_ZERO_SEGMENT")"
    : > "$FAKE_ZERO_SEGMENT"
  fi
  if [ "$FAKE_INDEX_STATUS" -ne 0 ]; then
    echo "simulated index failure" >&2
  fi
  exit "$FAKE_INDEX_STATUS"
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
echo "- User asked Claude Code to remember a result."
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
        "MEMSEARCH_NO_WATCH": "1",
        "FAKE_MILVUS_URI": "~/.memsearch/milvus.db",
        "FAKE_ZERO_SEGMENT": str(zero_segment),
        "FAKE_CREATE_ZERO_SEGMENT": "1" if create_zero_segment else "0",
        "FAKE_INDEX_STATUS": str(index_status),
    }
    result = subprocess.run(
        ["bash", str(script)],
        input=json.dumps({"transcript_path": str(transcript)}),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result, zero_segment


def test_claude_stop_hook_reports_index_exit_and_zero_byte_segment(tmp_path: Path) -> None:
    result, zero_segment = _run_stop_hook(tmp_path, index_status=23, create_zero_segment=True)

    payload = json.loads(result.stdout)
    message = payload["systemMessage"]

    assert "Index exited with status 23" in message
    assert "simulated index failure" in message
    assert f"Zero-byte Milvus segment detected: {zero_segment}" in message
    assert result.stderr == ""
    assert list((tmp_path / ".memsearch" / "memory").glob("*.md"))


def test_claude_stop_hook_checks_zero_byte_segments_after_successful_index(tmp_path: Path) -> None:
    result, zero_segment = _run_stop_hook(tmp_path, index_status=0, create_zero_segment=True)

    payload = json.loads(result.stdout)
    message = payload["systemMessage"]

    assert "Index exited with status" not in message
    assert f"Zero-byte Milvus segment detected: {zero_segment}" in message
