#!/usr/bin/env python3
"""Shared helpers for OpenCode transcript turn handling.

The raw OpenCode SQLite database remains the source of truth for transcript
content. This module also manages a small sidecar SQLite database under
<project>/.memsearch/opencode-turns.db for derived capture checkpoints and
stable turn ordering during replay.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class OpenCodeMessage:
    """A single meaningful OpenCode message with rendered text."""

    id: str
    role: str
    parent_id: str | None
    time_created: int
    finish: str | None
    text: str


@dataclass(slots=True)
class OpenCodeTurn:
    """A user turn plus its assistant follow-up messages."""

    session_id: str
    turn_id: str
    turn_index: int
    start_time: int
    end_time: int
    first_message_id: str
    last_message_id: str
    message_count: int
    assistant_message_count: int
    complete: bool
    messages: list[OpenCodeMessage] = field(default_factory=list)

    def render(self, max_chars: int = 3000) -> str:
        """Render the turn into readable transcript text."""
        lines: list[str] = [
            f"=== Turn {self.turn_index} ({self.turn_id}) ===",
        ]
        for message in self.messages:
            label = "[Human]" if message.role == "user" else "[Assistant]"
            text = message.text.strip()
            if len(text) > max_chars:
                text = text[:max_chars] + "\n..."
            lines.append(f"{label}: {text}")
            lines.append("")
        return "\n".join(lines).strip()


@dataclass(slots=True)
class TurnState:
    """Persistent capture progress for a session."""

    session_id: str
    last_completed_time: int
    last_completed_message_id: str
    last_completed_turn_id: str


def get_db_path() -> str:
    """Find the OpenCode SQLite database."""
    default = os.path.expanduser("~/.local/share/opencode/opencode.db")
    if os.path.exists(default):
        return default

    xdg_data = os.environ.get("XDG_DATA_HOME", "")
    if xdg_data:
        alt = os.path.join(xdg_data, "opencode", "opencode.db")
        if os.path.exists(alt):
            return alt

    return default


def get_turn_db_path(project_dir: str) -> str:
    """Return the derived turn metadata database path for a project."""
    return os.path.join(project_dir, ".memsearch", "opencode-turns.db")


def open_turn_db(project_dir: str) -> sqlite3.Connection:
    """Open the sidecar turn database and ensure its schema exists."""
    turn_db_path = get_turn_db_path(project_dir)
    Path(turn_db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(turn_db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    ensure_turn_schema(conn)
    return conn


def ensure_turn_schema(conn: sqlite3.Connection) -> None:
    """Create the sidecar schema if it does not exist yet."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS turns (
            session_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            turn_index INTEGER NOT NULL,
            start_time INTEGER NOT NULL,
            start_message_id TEXT NOT NULL,
            end_time INTEGER NOT NULL,
            end_message_id TEXT NOT NULL,
            message_count INTEGER NOT NULL,
            assistant_message_count INTEGER NOT NULL,
            complete INTEGER NOT NULL DEFAULT 1,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            PRIMARY KEY (session_id, turn_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS turn_state (
            session_id TEXT PRIMARY KEY,
            last_completed_time INTEGER NOT NULL DEFAULT 0,
            last_completed_message_id TEXT NOT NULL DEFAULT '',
            last_completed_turn_id TEXT NOT NULL DEFAULT '',
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS turns_session_index_idx ON turns (session_id, turn_index)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS turns_session_time_idx ON turns (session_id, end_time, turn_id)"
    )
    conn.commit()


def load_turn_state(conn: sqlite3.Connection, session_id: str) -> TurnState:
    """Load the last completed turn checkpoint for a session."""
    row = conn.execute(
        """
        SELECT session_id, last_completed_time, last_completed_message_id, last_completed_turn_id
        FROM turn_state
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()

    if row is None:
        return TurnState(session_id=session_id, last_completed_time=0, last_completed_message_id="", last_completed_turn_id="")

    return TurnState(
        session_id=row["session_id"],
        last_completed_time=int(row["last_completed_time"]),
        last_completed_message_id=row["last_completed_message_id"] or "",
        last_completed_turn_id=row["last_completed_turn_id"] or "",
    )


def save_turn_state(conn: sqlite3.Connection, state: TurnState) -> None:
    """Persist the checkpoint for a session."""
    now = int(_now_ms())
    conn.execute(
        """
        INSERT INTO turn_state (
            session_id, last_completed_time, last_completed_message_id, last_completed_turn_id,
            time_created, time_updated
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            last_completed_time = excluded.last_completed_time,
            last_completed_message_id = excluded.last_completed_message_id,
            last_completed_turn_id = excluded.last_completed_turn_id,
            time_updated = excluded.time_updated
        """,
        (
            state.session_id,
            state.last_completed_time,
            state.last_completed_message_id,
            state.last_completed_turn_id,
            now,
            now,
        ),
    )
    conn.commit()


def save_turn(conn: sqlite3.Connection, turn: OpenCodeTurn) -> None:
    """Persist derived metadata for a completed turn."""
    now = int(_now_ms())
    conn.execute(
        """
        INSERT INTO turns (
            session_id, turn_id, turn_index, start_time, start_message_id, end_time,
            end_message_id, message_count, assistant_message_count, complete,
            time_created, time_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id, turn_id) DO UPDATE SET
            turn_index = excluded.turn_index,
            start_time = excluded.start_time,
            start_message_id = excluded.start_message_id,
            end_time = excluded.end_time,
            end_message_id = excluded.end_message_id,
            message_count = excluded.message_count,
            assistant_message_count = excluded.assistant_message_count,
            complete = excluded.complete,
            time_updated = excluded.time_updated
        """,
        (
            turn.session_id,
            turn.turn_id,
            turn.turn_index,
            turn.start_time,
            turn.first_message_id,
            turn.end_time,
            turn.last_message_id,
            turn.message_count,
            turn.assistant_message_count,
            1 if turn.complete else 0,
            now,
            now,
        ),
    )
    conn.commit()


def load_session_turn_rows(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    """Load cached turn rows for a session."""
    return conn.execute(
        """
        SELECT session_id, turn_id, turn_index, start_time, start_message_id,
               end_time, end_message_id, message_count, assistant_message_count, complete
        FROM turns
        WHERE session_id = ?
        ORDER BY turn_index ASC
        """,
        (session_id,),
    ).fetchall()


def load_messages(
    conn: sqlite3.Connection,
    session_id: str,
    after_time: int | None = None,
    after_message_id: str | None = None,
) -> list[sqlite3.Row]:
    """Load OpenCode messages for a session in chronological order."""
    query = [
        "SELECT id, data, time_created FROM message WHERE session_id = ?",
    ]
    params: list[object] = [session_id]

    if after_time is not None:
        if after_message_id:
            query.append(
                "AND (time_created > ? OR (time_created = ? AND id > ?))"
            )
            params.extend([after_time, after_time, after_message_id])
        else:
            query.append("AND time_created > ?")
            params.append(after_time)

    query.append("ORDER BY time_created ASC, id ASC")
    return conn.execute(" ".join(query), tuple(params)).fetchall()


def extract_message_text(conn: sqlite3.Connection, message_id: str) -> str:
    """Render a message's parts into readable text."""
    parts = conn.execute(
        """
        SELECT id, data, time_created
        FROM part
        WHERE message_id = ?
        ORDER BY time_created ASC, id ASC
        """,
        (message_id,),
    ).fetchall()

    text_parts: list[str] = []
    tool_parts: list[str] = []

    for part in parts:
        try:
            part_data = json.loads(part["data"])
        except Exception:
            continue

        part_type = part_data.get("type", "")
        if part_type == "text" and part_data.get("text"):
            if part_data.get("synthetic"):
                continue
            text = str(part_data["text"]).strip()
            if text:
                text_parts.append(text)
        elif part_type == "tool" and part_data.get("state"):
            state = part_data.get("state", {})
            status = state.get("status", "unknown")
            tool_name = part_data.get("tool", "unknown")

            if status == "completed":
                tool_input = state.get("input", {})
                tool_output = state.get("output", "")
                if isinstance(tool_output, str) and len(tool_output) > 300:
                    tool_output = tool_output[:300] + "..."

                input_summary = ""
                if isinstance(tool_input, dict):
                    if "command" in tool_input:
                        input_summary = f" `{tool_input['command']}`"
                    elif "path" in tool_input:
                        input_summary = f" {tool_input['path']}"
                    elif "query" in tool_input:
                        input_summary = f" '{tool_input['query']}'"

                tool_parts.append(
                    f"[Tool: {tool_name}{input_summary}] {tool_output}"
                )
            elif status == "error":
                error = state.get("error", "unknown error")
                tool_parts.append(f"[Tool: {tool_name}] Error: {error}")

    combined = "\n".join(text_parts).strip()
    if tool_parts:
        combined = "\n".join([combined, "\n".join(tool_parts)]).strip()
    return combined


def build_turns(
    conn: sqlite3.Connection,
    session_id: str,
    after_time: int | None = None,
    after_message_id: str | None = None,
) -> list[OpenCodeTurn]:
    """Group OpenCode messages into turns."""
    rows = load_messages(conn, session_id, after_time=after_time, after_message_id=after_message_id)

    turns: list[OpenCodeTurn] = []
    current: OpenCodeTurn | None = None
    current_message_ids: set[str] = set()

    for row in rows:
        try:
            msg_data = json.loads(row["data"])
        except Exception:
            continue

        role = msg_data.get("role", "unknown")
        parent_id = msg_data.get("parentID")
        time_created = int(row["time_created"])
        finish = msg_data.get("finish")
        message_text = extract_message_text(conn, row["id"]).strip()

        if role == "user":
            if not message_text:
                continue

            message = OpenCodeMessage(
                id=row["id"],
                role=role,
                parent_id=parent_id,
                time_created=time_created,
                finish=finish,
                text=message_text,
            )

            if current is not None:
                current.complete = _is_complete(current)
                turns.append(current)

            current = OpenCodeTurn(
                session_id=session_id,
                turn_id=message.id,
                turn_index=len(turns) + 1,
                start_time=message.time_created,
                end_time=message.time_created,
                first_message_id=message.id,
                last_message_id=message.id,
                message_count=1,
                assistant_message_count=0,
                complete=False,
                messages=[message],
            )
            current_message_ids = {message.id}
            continue

        if role == "assistant" and current is not None:
            if parent_id and parent_id not in current_message_ids:
                continue

            if not message_text:
                current_message_ids.add(row["id"])
                continue

            message = OpenCodeMessage(
                id=row["id"],
                role=role,
                parent_id=parent_id,
                time_created=time_created,
                finish=finish,
                text=message_text,
            )

            current.messages.append(message)
            current_message_ids.add(message.id)
            current.end_time = message.time_created
            current.last_message_id = message.id
            current.message_count += 1
            current.assistant_message_count += 1

    if current is not None:
        current.complete = _is_complete(current)
        turns.append(current)

    for index, turn in enumerate(turns, start=1):
        turn.turn_index = index

    return turns


def _is_complete(turn: OpenCodeTurn) -> bool:
    """Heuristically decide whether a grouped turn has finished."""
    assistant_finishes = [msg.finish for msg in turn.messages if msg.role == "assistant"]
    if not assistant_finishes:
        return False
    last_finish = assistant_finishes[-1]
    return last_finish != "tool-calls"


def find_turn_index(turns: list[OpenCodeTurn], target_turn_id: str) -> int:
    """Find a turn index by exact or prefix match."""
    if not target_turn_id:
        return -1

    for index, turn in enumerate(turns):
        if turn.turn_id == target_turn_id:
            return index
        if turn.turn_id.startswith(target_turn_id) or target_turn_id.startswith(turn.turn_id[:8]):
            return index
    return -1


def _now_ms() -> int:
    return int(time.time() * 1000)
