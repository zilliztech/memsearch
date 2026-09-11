from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

SCRIPT = Path("plugins/zcode/scripts/parse-session.py")


def _create_db(db_path: Path) -> str:
    """Create a minimal ZCode conversation DB with one session and two turns."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE message (
            id text primary key,
            session_id text not null,
            time_created integer not null,
            time_updated integer not null,
            data text not null,
            sequence integer
        );
        CREATE TABLE part (
            id text primary key,
            message_id text not null references message(id) on delete cascade,
            session_id text not null,
            time_created integer not null,
            time_updated integer not null,
            data text not null,
            sequence integer
        );
        """
    )

    session_id = "sess_test_001"

    messages = [
        # Turn 1: user asks, assistant responds
        {
            "id": "msg_1",
            "seq": 0,
            "data": {
                "role": "user",
                "semantics": {"kind": "user_prompt"},
                "anchor": {"turnId": "turn_1"},
            },
        },
        {
            "id": "msg_2",
            "seq": 1,
            "data": {
                "role": "assistant",
                "semantics": {"kind": "assistant_response"},
                "anchor": {"turnId": "turn_1"},
            },
        },
        # Turn 2: user asks again, assistant responds with tool call + text
        {
            "id": "msg_3",
            "seq": 2,
            "data": {
                "role": "user",
                "semantics": {"kind": "user_prompt"},
                "anchor": {"turnId": "turn_2"},
            },
        },
        {
            "id": "msg_4",
            "seq": 3,
            "data": {
                "role": "assistant",
                "semantics": {"kind": "assistant_response"},
                "anchor": {"turnId": "turn_2"},
            },
        },
    ]

    for msg in messages:
        conn.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg["id"], session_id, msg["seq"], msg["seq"], json.dumps(msg["data"]), msg["seq"]),
        )

    parts = [
        # Turn 1 user prompt
        {"id": "p1", "msg_id": "msg_1", "seq": 0, "data": {"type": "text", "text": "How do I cache Redis?"}},
        # Turn 1 assistant response
        {"id": "p2", "msg_id": "msg_2", "seq": 0, "data": {"type": "text", "text": "Use SETEX for TTL caching."}},
        # Turn 2 user prompt
        {"id": "p3", "msg_id": "msg_3", "seq": 0, "data": {"type": "text", "text": "Show me the config file"}},
        # Turn 2 assistant: tool call + text
        {"id": "p4", "msg_id": "msg_4", "seq": 0, "data": {"type": "step-start"}},
        {
            "id": "p5",
            "msg_id": "msg_4",
            "seq": 1,
            "data": {"type": "tool", "toolName": "Read"},
        },
        {
            "id": "p6",
            "msg_id": "msg_4",
            "seq": 2,
            "data": {"type": "text", "text": "Here is the config file content."},
        },
    ]

    for part in parts:
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                part["id"],
                part["msg_id"],
                session_id,
                part["seq"],
                part["seq"],
                json.dumps(part["data"]),
                part["seq"],
            ),
        )

    conn.commit()
    conn.close()
    return session_id


def _run_parse(db_path: str, session_id: str, turn: str | None = None) -> str:
    args = ["python3", str(SCRIPT), "--session", session_id, "--db", db_path]
    if turn is not None:
        args += ["--turn", turn]
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout


def test_parse_session_returns_last_turn(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    session_id = _create_db(db_path)

    output = _run_parse(str(db_path), session_id)

    # Should contain the second turn's user prompt, not the first
    assert "[User]: Show me the config file" in output
    assert "How do I cache Redis?" not in output
    # Should include the assistant text and tool call
    assert "[Assistant]: Here is the config file content." in output
    assert "[Tool call]: Read" in output


def test_parse_session_specific_turn(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    session_id = _create_db(db_path)

    output = _run_parse(str(db_path), session_id, turn="1")

    assert "[User]: How do I cache Redis?" in output
    assert "[Assistant]: Use SETEX for TTL caching." in output
    # Should NOT contain turn 2 content
    assert "Show me the config file" not in output


def test_parse_session_nonexistent_session(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    _create_db(db_path)

    result = subprocess.run(
        ["python3", str(SCRIPT), "--session", "sess_nonexistent", "--db", str(db_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "no messages found" in result.stderr


def test_parse_session_omits_reasoning_blocks(tmp_path: Path) -> None:
    """Reasoning blocks should not appear in the rendered transcript."""
    db_path = tmp_path / "db.sqlite"
    session_id = _create_db(db_path)

    # Add a reasoning part to the last assistant message
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data, sequence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "p_reasoning",
            "msg_4",
            session_id,
            10,
            10,
            json.dumps({"type": "reasoning", "text": "I should read the config file first."}),
            0,
        ),
    )
    conn.commit()
    conn.close()

    output = _run_parse(str(db_path), session_id)
    assert "I should read the config file first." not in output
    assert "[Assistant]: Here is the config file content." in output
