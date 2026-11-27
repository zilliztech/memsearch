from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from click.testing import CliRunner

from memsearch.cli import cli
from memsearch.transcript import _parse_antigravity, format_turns, last_exchange, parse_transcript, select_turns

FIXTURE = Path(__file__).parent / "fixtures/antigravity/transcript.jsonl"


def test_actual_cli_fixture_user_assistant_and_tool_evidence():
    turns = parse_transcript(FIXTURE)
    assert [t.role for t in turns] == ["user", "assistant", "assistant"]
    assert [t.uuid for t in turns] == ["0", "1", "3"]
    assert turns[0].text.startswith("Read /tmp/memsearch-antigravity-phase1-tools/facts.txt")
    assert "ADDITIONAL_METADATA" not in turns[0].text
    assert "USER_SETTINGS_CHANGE" not in turns[0].text
    tool = turns[1].tools[0]
    assert tool.name == "read_file"
    assert json.loads(tool.command) == {"Path": "/tmp/memsearch-antigravity-phase1-tools/facts.txt"}
    assert "The sample device is quartz-47. Its port is 4182." in tool.output
    assert "Created At" not in tool.output
    assert "quartz-47" in turns[-1].text


def test_summary_excludes_tools_thinking_and_host_injection():
    entries = [json.loads(line) for line in FIXTURE.read_text().splitlines() if line]
    entries.insert(1, {"step_index": 20, "type": "USER_INPUT", "source": "SYSTEM", "content": "private injected rule"})
    entries.insert(
        2, {"step_index": 21, "type": "THINKING", "source": "MODEL", "content": "private internal reasoning"}
    )
    entries[3]["thinking"] = "private planner reasoning"
    exchange = last_exchange(_parse_antigravity(entries))
    assert exchange["turn"] == "0"
    assert "[User]: Read" in exchange["text"] and "[Assistant]: From" in exchange["text"]
    assert "private" not in exchange["text"]
    assert "Showing lines" not in exchange["text"]
    assert '"Path"' not in exchange["text"]


def test_full_companion_restores_truncated_content_and_stable_anchors(tmp_path):
    compact = tmp_path / "transcript.jsonl"
    full = tmp_path / "transcript_full.jsonl"
    entries = [
        {"type": "USER_INPUT", "step_index": 10, "source": "USER_EXPLICIT", "content": "test question"},
        {"type": "PLANNER_RESPONSE", "step_index": 11, "source": "MODEL", "content": "short [truncated]"},
        {"type": "USER_INPUT", "step_index": 12, "source": "USER_EXPLICIT", "content": "next question"},
    ]
    compact.write_text("\n".join(json.dumps(e) for e in entries))
    full.write_text(json.dumps({**entries[1], "content": "complete answer"}) + "\n")
    turns = parse_transcript(compact)
    assert [t.uuid for t in turns] == ["10", "11", "12"]
    assert turns[1].text == "complete answer"
    assert select_turns(turns, "10", 1) == turns[:2]


def test_l3_cli_decodes_anchor_path_and_returns_actual_tool_io(tmp_path):
    destination = tmp_path / "space dir"
    destination.mkdir()
    for name in ("transcript.jsonl", "transcript_full.jsonl"):
        (destination / name).write_bytes(FIXTURE.with_name(name).read_bytes())
    path = quote(str(destination / "transcript.jsonl"), safe="/")
    result = CliRunner().invoke(cli, ["transcript", path, "--turn", "0", "--context", "3", "-j"])
    assert result.exit_code == 0, result.output
    turns = json.loads(result.output)
    assert turns[1]["tools"][0]["name"] == "read_file"
    assert "4182" in turns[1]["tools"][0]["output"]


def test_tool_result_without_pending_tool_does_not_become_assistant_text():
    turns = _parse_antigravity(
        [
            {"type": "GENERIC", "step_index": 1, "source": "MODEL", "content": "host bookkeeping"},
            {"type": "PLANNER_RESPONSE", "step_index": 2, "source": "SYSTEM", "content": "host policy"},
        ]
    )
    assert turns == []


def test_render_preserves_full_arguments_and_bounds_outputs():
    command = "echo " + "a" * 1200
    turns = _parse_antigravity(
        [
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 1,
                "source": "MODEL",
                "tool_calls": [{"name": "run_command", "args": {"CommandLine": command, "Cwd": "/synthetic"}}],
            },
            {"type": "GENERIC", "step_index": 2, "source": "MODEL", "content": "x" * 1000},
        ]
    )
    assert command in turns[0].tools[0].command
    assert len(turns[0].tools[0].output) < 250
    assert "[run_command]" in format_turns(turns)
