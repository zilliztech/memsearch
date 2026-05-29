from __future__ import annotations

import json
import subprocess
from pathlib import Path

SCRIPT = Path("plugins/codex/scripts/parse-rollout.sh")


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


def test_parse_rollout_omits_tool_output_content(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    _write_jsonl(
        rollout,
        [
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Check the journal"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": "tail -80 memory.md"}),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": (
                        "Chunk ID: test\n"
                        "Wall time: 0.1234 seconds\n"
                        "Process exited with code 0\n"
                        "Output:\n"
                        "stale fact: memsearch version 0.4.4\n"
                    ),
                },
            },
            {"type": "event_msg", "payload": {"type": "agent_message", "message": "Current version is 0.4.5."}},
        ],
    )

    output = _run_parse(rollout)

    assert "[User]: Check the journal" in output
    assert "[Codex calls tool]" not in output
    assert "[Tool output" not in output
    assert "exit_code=0" not in output
    assert "wall_time=0.1234 seconds" not in output
    assert "stale fact" not in output
    assert "0.4.4" not in output
    assert "Current version is 0.4.5." in output


def test_parse_rollout_omits_tool_output_metadata(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    _write_jsonl(
        rollout,
        [
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Show output"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": "Process exited with code 0\nOutput:\nimportant detail",
                },
            },
        ],
    )

    output = _run_parse(rollout)

    assert "[Tool output" not in output
    assert "exit_code=0" not in output
    assert "important detail" not in output


def test_parse_rollout_omits_tool_error_content(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-error.jsonl"
    error_text = "prefix " + ("x" * 1200) + " final error marker"
    _write_jsonl(
        rollout,
        [
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Debug failure"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": f"Process exited with code 2\nOutput:\n{error_text}",
                },
            },
        ],
    )

    output = _run_parse(rollout)

    assert "[Tool output" not in output
    assert "exit_code=2" not in output
    assert "final error marker" not in output
    assert "prefix " not in output
