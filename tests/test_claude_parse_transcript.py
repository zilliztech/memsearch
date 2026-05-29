from __future__ import annotations

import json
import subprocess
from pathlib import Path

SCRIPT = Path("plugins/claude-code/hooks/parse-transcript.sh")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _run_parse(path: Path) -> str:
    result = subprocess.run(
        ["bash", str(SCRIPT), str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_claude_parse_transcript_omits_successful_tool_output_content(tmp_path: Path) -> None:
    transcript = tmp_path / "claude.jsonl"
    _write_jsonl(
        transcript,
        [
            {"type": "user", "uuid": "u1", "message": {"content": "Check the current version"}},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "tail memory.md"}},
                        {"type": "text", "text": "Checking"},
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "content": "stale fact from old journal: memsearch 0.4.4",
                        }
                    ]
                },
            },
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Current version is 0.4.5."}]},
            },
        ],
    )

    output = _run_parse(transcript)

    assert "[User]: Check the current version" in output
    assert "[Claude Code calls tool]" not in output
    assert "[Tool output]" not in output
    assert "stale fact" not in output
    assert "0.4.4" not in output
    assert "Current version is 0.4.5." in output


def test_claude_parse_transcript_omits_tool_error_content(tmp_path: Path) -> None:
    transcript = tmp_path / "claude-error.jsonl"
    error_text = "prefix " + ("x" * 1200) + " final traceback marker"
    _write_jsonl(
        transcript,
        [
            {"type": "user", "uuid": "u1", "message": {"content": "Debug the failure"}},
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "is_error": True,
                            "content": error_text,
                        }
                    ]
                },
            },
        ],
    )

    output = _run_parse(transcript)

    assert "[Tool error]" not in output
    assert "final traceback marker" not in output
    assert "prefix " not in output
