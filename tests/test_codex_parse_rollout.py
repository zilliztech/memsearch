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


# --- codex-cli >= 0.153: message text lives only in response_item (#742) -----


def test_parse_rollout_reads_response_item_messages(tmp_path: Path) -> None:
    """The 0.153 rollout writes no user_message/agent_message events at all.

    Reading only those events left the transcript empty but for its header, so
    the summarizer reported the user's question as missing and the daily entry
    carried the final assistant line at best.
    """
    rollout = tmp_path / "rollout.jsonl"
    _write_jsonl(
        rollout,
        [
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "What is 3+3?"}],
                },
            },
            {
                "type": "response_item",
                "payload": {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "adding"}]},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "6"}],
                },
            },
            {"type": "event_msg", "payload": {"type": "token_count"}},
            {"type": "event_msg", "payload": {"type": "task_complete"}},
        ],
    )

    output = _run_parse(rollout)

    assert "[User]: What is 3+3?" in output
    assert "[Codex]: 6" in output
    assert "adding" not in output


def test_parse_rollout_drops_injected_instructions(tmp_path: Path) -> None:
    """The harness injects its own instructions as a user-role message.

    They are not part of the conversation, and a summary built from them
    describes the system prompt instead of the turn.
    """
    rollout = tmp_path / "rollout.jsonl"
    _write_jsonl(
        rollout,
        [
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "developer preamble"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "# AGENTS.md instructions for /repo\n<INSTRUCTIONS>obey</INSTRUCTIONS>",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "<environment_context>cwd=/repo</environment_context>"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Summarize the journal"}],
                },
            },
        ],
    )

    output = _run_parse(rollout)

    assert "[User]: Summarize the journal" in output
    assert "AGENTS.md instructions" not in output
    assert "obey" not in output
    assert "environment_context" not in output
    assert "developer preamble" not in output


def test_parse_rollout_does_not_duplicate_dual_written_messages(tmp_path: Path) -> None:
    """Older codex versions write a message twice, as event and as item."""
    rollout = tmp_path / "rollout.jsonl"
    _write_jsonl(
        rollout,
        [
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "What is 3+3?"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "What is 3+3?"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "6"}],
                },
            },
            {"type": "event_msg", "payload": {"type": "agent_message", "message": "6"}},
        ],
    )

    output = _run_parse(rollout)

    assert output.count("[User]: What is 3+3?") == 1
    assert output.count("[Codex]: 6") == 1


def test_parse_rollout_falls_back_to_a_response_item_user_message(tmp_path: Path) -> None:
    """No task_started: the fallback has to know the new shape too.

    It looked for a user_message event, which 0.153 never writes, so a rollout
    without a turn boundary reported no user message and was dropped whole.
    """
    rollout = tmp_path / "rollout.jsonl"
    _write_jsonl(
        rollout,
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Where is the config?"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "In ~/.memsearch."}],
                },
            },
        ],
    )

    output = _run_parse(rollout)

    assert "no user message found" not in output
    assert "[User]: Where is the config?" in output
    assert "[Codex]: In ~/.memsearch." in output
