from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("plugins/codex/scripts/parse-rollout.sh")
FIXTURES = Path("tests/fixtures")


def _write_jsonl(path: Path, rows: list[object]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _run_parse(path: Path) -> str:
    result = subprocess.run(
        ["bash", str(SCRIPT), str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _task_started() -> dict:
    return {"type": "event_msg", "payload": {"type": "task_started"}}


def _legacy_user(text: str, event_id: str | None = None) -> dict:
    payload = {"type": "user_message", "message": text}
    if event_id is not None:
        payload["id"] = event_id
    return {"type": "event_msg", "payload": payload}


def _response_message(role: str, text: str, event_id: str | None = None, phase: str | None = None) -> dict:
    payload = {
        "type": "message",
        "role": role,
        "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
    }
    if event_id is not None:
        payload["id"] = event_id
    if phase is not None:
        payload["phase"] = phase
    return {"type": "response_item", "payload": payload}


def _developer_message(text: str = "host policy") -> dict:
    return {
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "developer",
            "content": [{"type": "input_text", "text": text}],
        },
    }


def test_parse_rollout_old_schema_fixture() -> None:
    output = _run_parse(FIXTURES / "codex_rollout_old.jsonl")

    assert output.count("[User]: Repeat the marker twice.") == 1
    assert output.count("[Codex]: marker marker") == 1


def test_parse_rollout_new_schema_fixture() -> None:
    output = _run_parse(FIXTURES / "codex_rollout_0_153.jsonl")

    assert "[User]: First block.\nSecond block." in output
    assert "[Codex]: Answer block one.\nAnswer block two." in output
    assert "environment_context" not in output
    assert "private reasoning" not in output
    assert "sensitive" not in output


def test_parse_rollout_host_envelope_fixture() -> None:
    output = _run_parse(FIXTURES / "codex_rollout_host_envelopes.jsonl")

    assert "AGENTS.md instructions" not in output
    assert "environment_context" not in output
    assert "synthetic metadata sentinel" not in output
    assert "[User]: Remember the synthetic orchard marker." in output
    assert "[Codex]: The synthetic orchard marker is recorded." in output


def test_parse_rollout_mixed_schema_preserves_repeated_logical_messages() -> None:
    output = _run_parse(FIXTURES / "codex_rollout_mixed.jsonl")

    assert "Ignore the previous turn" not in output
    assert output.count("[User]: same text") == 2
    assert output.count("[Codex]: working") == 1
    assert output.count("[Codex]: done") == 1


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


def test_parse_rollout_ignores_unknown_and_malformed_items(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-malformed.jsonl"
    rollout.write_text(
        "not-json\n"
        + "\n".join(
            json.dumps(row)
            for row in [
                {"type": "event_msg", "payload": {"type": "task_started"}},
                {"type": "response_item", "payload": None},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": {}}},
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [None, "raw", {"type": "future_text", "text": "unknown payload"}],
                    },
                },
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "valid text"}],
                    },
                },
                {"type": "future_item", "payload": {"text": "metadata payload"}},
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    output = _run_parse(rollout)

    assert "[User]: valid text" in output
    assert "unknown payload" not in output
    assert "metadata payload" not in output


def test_parse_rollout_returns_empty_turn_when_no_natural_language(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-empty.jsonl"
    _write_jsonl(
        rollout,
        [
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "response_item", "payload": {"type": "reasoning", "content": []}},
            {"type": "response_item", "payload": {"type": "function_call_output", "output": "hidden"}},
        ],
    )

    assert _run_parse(rollout) == "(empty turn)\n"


def test_parse_rollout_preserves_instruction_lookalikes_and_later_wrappers(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-instruction-lookalikes.jsonl"
    _write_jsonl(
        rollout,
        [
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "# AGENTS.md instructions are useful documentation."}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Please explain <INSTRUCTIONS> literally."}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "<environment_context>example</environment_context>"}],
                },
            },
        ],
    )

    output = _run_parse(rollout)

    assert "# AGENTS.md instructions are useful documentation." in output
    assert "Please explain <INSTRUCTIONS> literally." in output
    assert "<environment_context>example</environment_context>" in output


def test_parse_rollout_preserves_same_schema_repeats(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-repeats.jsonl"
    _write_jsonl(
        rollout,
        [
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "repeat"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "repeat"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "again"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "again"}],
                },
            },
        ],
    )

    output = _run_parse(rollout)

    assert output.count("[User]: repeat") == 2
    assert output.count("[Codex]: again") == 2


def test_parse_rollout_preserves_adjacent_messages_with_different_event_ids(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-distinct-ids.jsonl"
    _write_jsonl(
        rollout,
        [
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {
                "type": "event_msg",
                "payload": {"type": "user_message", "item_id": "legacy-1", "message": "repeat"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "id": "response-2",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "repeat"}],
                },
            },
        ],
    )

    assert _run_parse(rollout).count("[User]: repeat") == 2


@pytest.mark.parametrize(
    ("legacy_id", "response_id"),
    [
        (None, None),
        ("legacy-id", None),
        (None, "response-id"),
        ("legacy-id", "response-id"),
    ],
)
def test_parse_rollout_uncertain_cross_schema_identity_fails_open(
    tmp_path: Path, legacy_id: str | None, response_id: str | None
) -> None:
    rollout = tmp_path / "rollout-uncertain-identity.jsonl"
    _write_jsonl(
        rollout,
        [
            _task_started(),
            _legacy_user("repeat", legacy_id),
            _response_message("user", "repeat", response_id),
        ],
    )

    assert _run_parse(rollout).count("[User]: repeat") == 2


def test_parse_rollout_same_id_and_content_deduplicates_cross_schema_event(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-same-event.jsonl"
    _write_jsonl(
        rollout,
        [
            _task_started(),
            _legacy_user("repeat", "shared-id"),
            _response_message("user", "repeat", "shared-id"),
        ],
    )

    assert _run_parse(rollout).count("[User]: repeat") == 1


def test_parse_rollout_same_id_with_different_content_fails_open(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-id-content-conflict.jsonl"
    _write_jsonl(
        rollout,
        [
            _task_started(),
            _legacy_user("first text", "shared-id"),
            _response_message("user", "second text", "shared-id"),
        ],
    )

    output = _run_parse(rollout)
    assert "[User]: first text" in output
    assert "[User]: second text" in output


def test_parse_rollout_same_id_with_different_phase_fails_open(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-id-phase-conflict.jsonl"
    _write_jsonl(
        rollout,
        [
            _task_started(),
            {
                "type": "event_msg",
                "payload": {"type": "agent_message", "id": "shared-id", "phase": "commentary", "message": "same"},
            },
            _response_message("assistant", "same", "shared-id", "final_answer"),
        ],
    )

    assert _run_parse(rollout).count("[Codex]: same") == 2


def test_parse_rollout_non_message_record_breaks_deduplication(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-dedup-barrier.jsonl"
    _write_jsonl(
        rollout,
        [
            _task_started(),
            _legacy_user("repeat", "shared-id"),
            {"type": "response_item", "payload": {"type": "function_call_output", "output": "hidden"}},
            _response_message("user", "repeat", "shared-id"),
        ],
    )

    output = _run_parse(rollout)
    assert output.count("[User]: repeat") == 2
    assert "hidden" not in output


def test_parse_rollout_same_schema_same_id_repeats_are_preserved(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-same-schema-same-id.jsonl"
    _write_jsonl(
        rollout,
        [_task_started(), _legacy_user("repeat", "shared-id"), _legacy_user("repeat", "shared-id")],
    )

    assert _run_parse(rollout).count("[User]: repeat") == 2


def test_parse_rollout_repeated_identity_across_turns_obeys_last_turn_boundary(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-cross-turn-repeat.jsonl"
    _write_jsonl(
        rollout,
        [
            _task_started(),
            _legacy_user("repeat", "shared-id"),
            _task_started(),
            _response_message("user", "repeat", "shared-id"),
        ],
    )

    assert _run_parse(rollout).count("[User]: repeat") == 1


@pytest.mark.parametrize("root", [[], "text", 1, None])
def test_parse_rollout_ignores_valid_non_object_json_lines(tmp_path: Path, root: object) -> None:
    rollout = tmp_path / "rollout-non-object.jsonl"
    _write_jsonl(rollout, [_task_started(), root, _response_message("user", "safe dialogue")])

    assert "[User]: safe dialogue" in _run_parse(rollout)


REAL_ENVIRONMENT_ENVELOPE = """<environment_context>
  <cwd>/fixture</cwd>
  <shell>bash</shell>
  <current_date>2026-09-18</current_date>
  <timezone>UTC</timezone>
</environment_context>"""

WORKSPACE_ENVIRONMENT_ENVELOPE = """<environment_context>
  <current_date>2026-09-18</current_date>
  <timezone>UTC</timezone>
  <filesystem><workspace_roots><root>/fixture</root></workspace_roots></filesystem>
</environment_context>"""


def _agents_envelope(header: str, *, composite: bool) -> str:
    text = f"{header}\n\n<INSTRUCTIONS>\nSynthetic project rules.\n</INSTRUCTIONS>"
    if composite:
        text += f"\n{WORKSPACE_ENVIRONMENT_ENVELOPE}"
    return text


@pytest.mark.parametrize(
    "text",
    [
        REAL_ENVIRONMENT_ENVELOPE,
        "<user_instructions>\nliteral example\n</user_instructions>",
        "# AGENTS.md instructions for /fixture\n\n<INSTRUCTIONS>literal example</INSTRUCTIONS>",
    ],
)
def test_parse_rollout_preserves_first_user_literal_host_envelope(tmp_path: Path, text: str) -> None:
    rollout = tmp_path / "rollout-literal-host-envelope.jsonl"
    _write_jsonl(rollout, [_task_started(), _developer_message(), _response_message("user", text)])

    assert f"[User]: {text}" in _run_parse(rollout)


@pytest.mark.parametrize(
    "text",
    [
        REAL_ENVIRONMENT_ENVELOPE,
        "<user_instructions>\nhost configuration\n</user_instructions>",
        "# AGENTS.md instructions for /fixture\n\n<INSTRUCTIONS>host configuration</INSTRUCTIONS>",
    ],
)
def test_parse_rollout_filters_observed_leading_host_sequence(tmp_path: Path, text: str) -> None:
    rollout = tmp_path / "rollout-host-sequence.jsonl"
    _write_jsonl(
        rollout,
        [
            _task_started(),
            _developer_message(),
            _response_message("user", text),
            _response_message("user", "real prompt"),
        ],
    )

    output = _run_parse(rollout)
    assert text not in output
    assert "[User]: real prompt" in output


@pytest.mark.parametrize(
    "header",
    [
        "# AGENTS.md instructions",
        "# AGENTS.md instructions for /fixture",
        "# AGENTS.md instructions for /fixture with spaces",
    ],
)
@pytest.mark.parametrize("composite", [False, True])
def test_parse_rollout_filters_agents_header_and_terminator_matrix(
    tmp_path: Path, header: str, composite: bool
) -> None:
    rollout = tmp_path / "rollout-agents-matrix.jsonl"
    envelope = _agents_envelope(header, composite=composite)
    _write_jsonl(
        rollout,
        [
            _task_started(),
            {"type": "response_item", "payload": {"type": "session_meta", "synthetic": True}},
            _developer_message(),
            _response_message("user", envelope),
            {"type": "world_state", "payload": {"cwd": "/fixture"}},
            {"type": "response_item", "payload": {"type": "turn_context", "synthetic": True}},
            {"type": "response_item", "payload": {"type": "reasoning", "text": "metadata sentinel"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "synthetic_tool"}},
            {"type": "response_item", "payload": {"type": "function_call_output", "output": "tool sentinel"}},
            {"type": "token_usage_record", "payload": {"total_tokens": 1}},
            {"type": "compacted", "payload": {"replacement_history": []}},
            _response_message("user", "real prompt"),
        ],
    )

    output = _run_parse(rollout)
    assert envelope not in output
    assert "metadata sentinel" not in output
    assert "tool sentinel" not in output
    assert "[User]: real prompt" in output


def test_parse_rollout_filters_workspace_environment_without_cwd_or_shell(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-workspace-environment.jsonl"
    _write_jsonl(
        rollout,
        [
            _task_started(),
            _developer_message(),
            _response_message("user", WORKSPACE_ENVIRONMENT_ENVELOPE),
            {"type": "world_state", "payload": {"cwd": "/fixture"}},
            _response_message("user", "real prompt"),
        ],
    )

    output = _run_parse(rollout)
    assert WORKSPACE_ENVIRONMENT_ENVELOPE not in output
    assert "[User]: real prompt" in output


@pytest.mark.parametrize(
    "envelope",
    [
        """<environment_context>
  <current_date>2026-09-19</current_date>
  <timezone>UTC</timezone>
  <filesystem><workspace_roots /></filesystem>
</environment_context>""",
        """<environment_context>
  <current_date>2026-09-19</current_date>
  <timezone>UTC</timezone>
  <filesystem><workspace_roots><root>   </root></workspace_roots></filesystem>
</environment_context>""",
        """<environment_context>
  <current_date></current_date>
  <timezone>UTC</timezone>
  <filesystem><workspace_roots><root>/fixture</root></workspace_roots></filesystem>
</environment_context>""",
        """<environment_context>
  <cwd>/fixture</cwd>
  <shell>bash</shell>
  <current_date>2026-09-19</current_date>
  <timezone>   </timezone>
</environment_context>""",
        """<environment_context>
  <cwd></cwd>
  <shell>bash</shell>
  <current_date>2026-09-19</current_date>
  <timezone>UTC</timezone>
</environment_context>""",
    ],
)
def test_parse_rollout_incomplete_environment_context_fails_open(tmp_path: Path, envelope: str) -> None:
    rollout = tmp_path / "rollout-incomplete-environment.jsonl"
    _write_jsonl(
        rollout,
        [
            _task_started(),
            _developer_message(),
            _response_message("user", envelope),
            _response_message("user", "real prompt"),
        ],
    )

    output = _run_parse(rollout)
    assert envelope in output
    assert "[User]: real prompt" in output


def test_parse_rollout_filters_consecutive_host_envelopes_before_real_user(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-consecutive-envelopes.jsonl"
    agents_envelope = _agents_envelope("# AGENTS.md instructions", composite=True)
    _write_jsonl(
        rollout,
        [
            _task_started(),
            _developer_message(),
            _response_message("user", agents_envelope),
            {"type": "world_state", "payload": {"cwd": "/fixture"}},
            _response_message("user", WORKSPACE_ENVIRONMENT_ENVELOPE),
            _response_message("user", "real prompt"),
        ],
    )

    output = _run_parse(rollout)
    assert agents_envelope not in output
    assert WORKSPACE_ENVIRONMENT_ENVELOPE not in output
    assert "[User]: real prompt" in output


def test_parse_rollout_preserves_consecutive_envelopes_without_real_user(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-consecutive-envelopes-only.jsonl"
    first = _agents_envelope("# AGENTS.md instructions for /fixture", composite=False)
    second = WORKSPACE_ENVIRONMENT_ENVELOPE
    _write_jsonl(
        rollout,
        [_task_started(), _developer_message(), _response_message("user", first), _response_message("user", second)],
    )

    output = _run_parse(rollout)
    assert first in output
    assert second in output


@pytest.mark.parametrize(
    "envelope",
    [
        _agents_envelope("# AGENTS.md instructions", composite=True),
        WORKSPACE_ENVIRONMENT_ENVELOPE,
    ],
)
def test_parse_rollout_preserves_new_host_shapes_without_leading_developer(tmp_path: Path, envelope: str) -> None:
    rollout = tmp_path / "rollout-no-leading-developer.jsonl"
    _write_jsonl(rollout, [_task_started(), _response_message("user", envelope), _response_message("user", "next")])

    output = _run_parse(rollout)
    assert envelope in output
    assert "[User]: next" in output


def test_parse_rollout_preserves_host_shape_after_conversation_starts(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-later-literal-envelope.jsonl"
    envelope = _agents_envelope("# AGENTS.md instructions", composite=True)
    _write_jsonl(
        rollout,
        [
            _task_started(),
            _developer_message(),
            _response_message("user", "Discuss a literal fixture."),
            _response_message("user", envelope),
            _response_message("user", "What does it mean?"),
        ],
    )

    output = _run_parse(rollout)
    assert "[User]: Discuss a literal fixture." in output
    assert envelope in output
    assert "[User]: What does it mean?" in output


def test_parse_rollout_preserves_host_shape_after_assistant_starts_conversation(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-assistant-before-wrapper.jsonl"
    _write_jsonl(
        rollout,
        [
            _task_started(),
            _developer_message(),
            _response_message("assistant", "Conversation already started."),
            _response_message("user", WORKSPACE_ENVIRONMENT_ENVELOPE),
            _response_message("user", "real prompt"),
        ],
    )

    output = _run_parse(rollout)
    assert "[Codex]: Conversation already started." in output
    assert WORKSPACE_ENVIRONMENT_ENVELOPE in output
    assert "[User]: real prompt" in output


def test_parse_rollout_assistant_is_later_user_scan_barrier(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-assistant-between-wrapper-and-user.jsonl"
    _write_jsonl(
        rollout,
        [
            _task_started(),
            _developer_message(),
            _response_message("user", WORKSPACE_ENVIRONMENT_ENVELOPE),
            _response_message("assistant", "Reply to the literal wrapper."),
            _response_message("user", "real prompt"),
        ],
    )

    output = _run_parse(rollout)
    assert WORKSPACE_ENVIRONMENT_ENVELOPE in output
    assert "[Codex]: Reply to the literal wrapper." in output
    assert "[User]: real prompt" in output


@pytest.mark.parametrize(
    "text",
    [
        "# AGENTS.md instructions\n<INSTRUCTIONS>missing separator</INSTRUCTIONS>",
        "# AGENTS.md instructions\n\n<INSTRUCTIONS>missing close",
        "# AGENTS.md instructions\n\n<INSTRUCTIONS>closed</INSTRUCTIONS>\ntrailing text",
        "# AGENTS.md instructions for \n\n<INSTRUCTIONS>empty qualifier</INSTRUCTIONS>",
        "# AGENTS.md instructions for \t \n\n<INSTRUCTIONS>whitespace qualifier</INSTRUCTIONS>",
        (
            "# AGENTS.md instructions for /fixture\n"
            "literal discussion line\n\n"
            "<INSTRUCTIONS>multiline header</INSTRUCTIONS>"
        ),
        "# AGENTS.md instructions \n\n<INSTRUCTIONS>bare header with trailing space</INSTRUCTIONS>",
        "# AGENTS.md instructions for /fixture \n\n<INSTRUCTIONS>path header with trailing space</INSTRUCTIONS>",
        "<environment_context>\n  <current_date>2026-09-18</current_date>\n</environment_context>",
        "<environment_context>\n  <current_date>2026-09-18</current_date>\n  <timezone>UTC</timezone>\n  <filesystem />\n</environment_context>",
    ],
)
def test_parse_rollout_malformed_host_candidates_fail_open(tmp_path: Path, text: str) -> None:
    rollout = tmp_path / "rollout-malformed-host-candidate.jsonl"
    _write_jsonl(
        rollout,
        [_task_started(), _developer_message(), _response_message("user", text), _response_message("user", "next")],
    )

    output = _run_parse(rollout)
    assert text in output
    assert "[User]: next" in output


@pytest.mark.parametrize(
    ("text", "sentinel"),
    [
        (
            "# AGENTS.md instructions for /fixture\r\n\n<INSTRUCTIONS>mixed line ending</INSTRUCTIONS>",
            "mixed line ending",
        ),
        (
            "# AGENTS.md instructions for /fixture\r\n\r\n<INSTRUCTIONS>CRLF wrapper</INSTRUCTIONS>",
            "CRLF wrapper",
        ),
    ],
)
def test_parse_rollout_non_lf_agents_wrapper_fails_open(tmp_path: Path, text: str, sentinel: str) -> None:
    rollout = tmp_path / "rollout-crlf-agents-wrapper.jsonl"
    _write_jsonl(
        rollout,
        [_task_started(), _developer_message(), _response_message("user", text), _response_message("user", "next")],
    )

    output = _run_parse(rollout)
    assert sentinel in output
    assert "[User]: next" in output


def test_parse_rollout_host_envelope_does_not_cross_turn_boundary(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-host-cross-turn.jsonl"
    envelope = _agents_envelope("# AGENTS.md instructions", composite=True)
    _write_jsonl(
        rollout,
        [
            _task_started(),
            _developer_message(),
            _response_message("user", envelope),
            _response_message("user", "old turn prompt"),
            _task_started(),
            _response_message("user", "new turn prompt"),
        ],
    )

    output = _run_parse(rollout)
    assert envelope not in output
    assert "old turn prompt" not in output
    assert "[User]: new turn prompt" in output


def test_parse_rollout_preserves_wrapper_without_leading_developer_context(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-user-wrapper-sequence.jsonl"
    _write_jsonl(
        rollout,
        [_task_started(), _response_message("user", REAL_ENVIRONMENT_ENVELOPE), _response_message("user", "next")],
    )

    output = _run_parse(rollout)
    assert REAL_ENVIRONMENT_ENVELOPE in output
    assert "[User]: next" in output


@pytest.mark.parametrize(
    ("item_type", "payload"),
    [
        ("function_call", {"arguments": "natural-language-sentinel"}),
        ("function_call_output", {"output": "natural-language-sentinel"}),
        ("custom_tool_call", {"input": "natural-language-sentinel"}),
        ("custom_tool_call_output", {"output": "natural-language-sentinel"}),
        ("local_shell_call", {"command": "natural-language-sentinel"}),
        ("reasoning", {"summary": [{"type": "summary_text", "text": "natural-language-sentinel"}]}),
        ("web_search_call", {"query": "natural-language-sentinel"}),
        ("session_meta", {"instructions": "natural-language-sentinel"}),
        ("turn_context", {"context": "natural-language-sentinel"}),
    ],
)
def test_parse_rollout_non_message_items_never_become_dialogue(tmp_path: Path, item_type: str, payload: dict) -> None:
    rollout = tmp_path / f"rollout-{item_type}.jsonl"
    _write_jsonl(
        rollout,
        [
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "response_item", "payload": {"type": item_type, **payload}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "safe dialogue"}],
                },
            },
        ],
    )

    output = _run_parse(rollout)

    assert "[User]: safe dialogue" in output
    assert "natural-language-sentinel" not in output
