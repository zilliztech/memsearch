#!/usr/bin/env python3
"""Parse a ZCode session from the local SQLite DB into summarizer-ready text.

Renders the LAST completed turn (one real user prompt + all subsequent
assistant text/tool-call parts until the next user prompt or end) in the
same ``[User]``/``[Assistant]``/``[Tool call]`` shape the other memsearch
platform plugins feed to their summarizer.

The ZCode conversation store lives in ``~/.zcode/cli/db/db.sqlite``:
  - ``message``: one row per message, with ``data`` JSON carrying ``role``,
    ``semantics.kind`` (``user_prompt`` / ``assistant_response`` / ...), and
    ``anchor.turnId``.
  - ``part``: content blocks (``text``, ``reasoning``, ``tool``, ...) ordered
    by ``sequence`` within a message.

Usage:
    parse-session.py --session <sess_id> [--db <path>] [--turn <N>]
    parse-session.py --session <sess_id>            # last turn only
"""

# ruff: noqa: T201  # CLI tool: stdout is the output mechanism
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = str(Path.home() / ".zcode" / "cli" / "db" / "db.sqlite")

USER_KINDS = {"user_prompt"}
ASSISTANT_KINDS = {"assistant_response"}
TEXT_PART_TYPES = {"text"}
MAX_CHARS = 24000


def _connect(db_path: str) -> sqlite3.Connection:
    if not Path(db_path).is_file():
        raise RuntimeError(f"ZCode DB not found: {db_path}")
    uri = f"file:{db_path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _load_messages(conn: sqlite3.Connection, session_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, sequence, data FROM message WHERE session_id = ? ORDER BY sequence, time_created, id",
        (session_id,),
    ).fetchall()
    messages: list[dict] = []
    for mid, seq, raw in rows:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        messages.append(
            {
                "id": mid,
                "sequence": seq,
                "role": data.get("role", ""),
                "kind": (data.get("semantics") or {}).get("kind", ""),
                "turn_id": (data.get("anchor") or {}).get("turnId", ""),
            }
        )
    return messages


def _load_parts(conn: sqlite3.Connection, message_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT data FROM part WHERE message_id = ? ORDER BY sequence, time_created, id",
        (message_id,),
    ).fetchall()
    parts: list[dict] = []
    for (raw,) in rows:
        parsed = _safe_json_load(raw)
        if parsed is not None:
            parts.append(parsed)
    return parts


def _safe_json_load(raw: str) -> dict | None:
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None


def _text_of(parts: list[dict]) -> str:
    return "\n".join(
        part["text"] for part in parts if part.get("type") in TEXT_PART_TYPES and isinstance(part.get("text"), str)
    ).strip()


def _tool_calls_of(parts: list[dict]) -> list[str]:
    names: list[str] = []
    for part in parts:
        if part.get("type") == "tool":
            name = part.get("toolName") or part.get("name") or ""
            if name:
                names.append(name)
    return names


def _group_turns(messages: list[dict]) -> list[list[dict]]:
    """Group messages into turns. A turn starts at a real user prompt and
    runs until the next real user prompt (or end)."""
    turns: list[list[dict]] = []
    current: list[dict] = []
    for msg in messages:
        is_user = msg["role"] == "user" and msg["kind"] in USER_KINDS
        if is_user and current:
            turns.append(current)
            current = []
        current.append(msg)
    if current:
        turns.append(current)
    return turns


def render_turn(conn: sqlite3.Connection, messages: list[dict], turn_index: int) -> str | None:
    lines = [f"=== Turn {turn_index + 1} ==="]
    has_user = False
    for msg in messages:
        parts = _load_parts(conn, msg["id"])
        if msg["role"] == "user" and msg["kind"] in USER_KINDS:
            text = _text_of(parts)
            if not text:
                continue
            lines += ["", f"[User]: {text}"]
            has_user = True
        elif msg["role"] == "assistant" and msg["kind"] in ASSISTANT_KINDS:
            text = _text_of(parts)
            if text:
                lines += ["", f"[Assistant]: {text}"]
            for name in _tool_calls_of(parts):
                lines += ["", f"[Tool call]: {name}"]
        elif msg["role"] == "assistant":
            for name in _tool_calls_of(parts):
                lines += ["", f"[Tool call]: {name}"]
    if not has_user:
        return None
    render = "\n".join(lines).strip()
    if len(render) <= 10:
        return None
    return render[:MAX_CHARS]


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the last ZCode session turn as transcript text.")
    parser.add_argument("--session", required=True, help="ZCode session id (sess_...).")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to db.sqlite (default: ~/.zcode/cli/db/db.sqlite).")
    parser.add_argument("--turn", default=None, type=int, help="1-based turn index; omit for the last turn.")
    args = parser.parse_args()

    try:
        conn = _connect(args.db)
        messages = _load_messages(conn, args.session)
        conn.close()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    if not messages:
        print("(no messages found)", file=sys.stderr)
        return 1

    turns = _group_turns(messages)
    if not turns:
        print("(no turns found)", file=sys.stderr)
        return 1

    if args.turn is not None:
        idx = args.turn - 1
        if idx < 0 or idx >= len(turns):
            print(f"Error: turn {args.turn} out of range (1..{len(turns)})", file=sys.stderr)
            return 1
        target = turns[idx]
    else:
        target = turns[-1]
        idx = len(turns) - 1

    try:
        conn = _connect(args.db)
        rendered = render_turn(conn, target, idx)
        conn.close()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    if not rendered:
        print("(empty turn)", file=sys.stderr)
        return 1

    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
