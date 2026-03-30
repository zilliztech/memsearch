from __future__ import annotations

import json
import sys
from pathlib import Path

# transcript.py was moved from memsearch core to the Claude Code plugin directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins" / "claude-code"))

from transcript import (
    _extract_time,
    _strip_hook_tags,
    _summarize_tool_input,
    find_turn_context,
    format_turn_index,
    parse_transcript,
)


def test_parse_transcript_skips_invalid_and_tool_result(tmp_path: Path) -> None:
    transcript = tmp_path / "sample.jsonl"
    transcript.write_text(
        "\n".join(
            [
                "{not valid json",
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "u1",
                        "timestamp": "2026-03-07T05:00:00Z",
                        "message": {"content": [{"type": "tool_result", "content": "ok"}]},
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "u2",
                        "timestamp": "2026-03-07T05:00:01Z",
                        "message": {"content": "<system-reminder>ignore</system-reminder>Hello"},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {"type": "text", "text": "World"},
                                {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}},
                            ]
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    turns = parse_transcript(transcript)

    assert len(turns) == 1
    assert turns[0].uuid == "u2"
    assert "Hello" in turns[0].content
    assert "Assistant" in turns[0].content
    assert turns[0].tool_calls == ["Bash(ls -la)"]


def test_find_turn_context_supports_uuid_prefix() -> None:
    turns = [
        type("T", (), {"uuid": "aaaabbbb-1"})(),
        type("T", (), {"uuid": "ccccdddd-2"})(),
        type("T", (), {"uuid": "eeeeffff-3"})(),
    ]

    context, idx = find_turn_context(turns, "ccccdddd", context=1)

    assert len(context) == 3
    assert idx == 1


def test_helpers_format_and_summarize() -> None:
    assert _strip_hook_tags("<command-x>rm</command-x>keep") == "keep"
    assert _extract_time("2026-03-07T05:10:11.123Z") == "05:10:11"
    assert _summarize_tool_input("Read", {"file_path": "a.md"}) == "Read(a.md)"
    assert _summarize_tool_input("Unknown", {"k": "v"}) == "Unknown(k=v)"


def test_format_turn_index_includes_tool_count() -> None:
    turns = [
        type(
            "T",
            (),
            {
                "uuid": "12345678-abcd",
                "timestamp": "2026-03-07T05:10:11Z",
                "content": "line1\nline2",
                "tool_calls": ["Read(a.md)", "Edit(a.md)"],
            },
        )(),
    ]

    output = format_turn_index(turns)

    assert "12345678-abcd"[:12] in output
    assert "05:10:11" in output
    assert "line1 line2" in output
    assert "[2 tools]" in output
