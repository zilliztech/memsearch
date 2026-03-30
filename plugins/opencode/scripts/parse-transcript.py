#!/usr/bin/env python3
"""Parse OpenCode SQLite transcript for a given session.

Usage:
  parse-transcript.py <session_id> [--limit N] [--last-turn]

Options:
  --limit N       Max number of messages to return (default: 20)
  --last-turn     Only return the last user+assistant turn (for capture)

The script reads from the OpenCode SQLite database at:
  ~/.local/share/opencode/opencode.db
"""

import sqlite3
import json
import sys
import os
import argparse


def get_db_path():
    """Find the OpenCode SQLite database."""
    # Default path
    default = os.path.expanduser("~/.local/share/opencode/opencode.db")
    if os.path.exists(default):
        return default

    # Check XDG_DATA_HOME
    xdg_data = os.environ.get("XDG_DATA_HOME", "")
    if xdg_data:
        alt = os.path.join(xdg_data, "opencode", "opencode.db")
        if os.path.exists(alt):
            return alt

    return default


def parse_session(session_id, limit=20, last_turn=False):
    """Parse messages and parts for a session, formatted as [Human]/[Assistant]."""
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"Error: OpenCode database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row

    try:
        # Get messages for the session, ordered by creation time
        messages = conn.execute(
            """
            SELECT id, data, time_created
            FROM message
            WHERE session_id = ?
            ORDER BY time_created ASC
            """,
            (session_id,),
        ).fetchall()

        if not messages:
            print(f"No messages found for session {session_id}")
            return

        # Build structured turns
        turns = []
        for msg in messages:
            msg_data = json.loads(msg["data"])
            role = msg_data.get("role", "unknown")
            msg_id = msg["id"]

            # Get parts for this message
            parts = conn.execute(
                """
                SELECT id, data, time_created
                FROM part
                WHERE message_id = ?
                ORDER BY time_created ASC
                """,
                (msg_id,),
            ).fetchall()

            text_parts = []
            tool_parts = []

            for part in parts:
                part_data = json.loads(part["data"])
                part_type = part_data.get("type", "")

                if part_type == "text" and part_data.get("text"):
                    text = part_data["text"].strip()
                    # Skip synthetic parts (e.g. "The following tool was executed by the user")
                    if part_data.get("synthetic"):
                        continue
                    if text:
                        text_parts.append(text)

                elif part_type == "tool" and part_data.get("state"):
                    state = part_data["state"]
                    tool_name = part_data.get("tool", "unknown")
                    status = state.get("status", "unknown")

                    if status == "completed":
                        tool_input = state.get("input", {})
                        tool_output = state.get("output", "")
                        # Truncate long output
                        if isinstance(tool_output, str) and len(tool_output) > 300:
                            tool_output = tool_output[:300] + "..."

                        input_summary = ""
                        if isinstance(tool_input, dict):
                            # Summarize common tool inputs
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

            # Combine text and tool parts
            combined = "\n".join(text_parts)
            if tool_parts:
                combined += "\n" + "\n".join(tool_parts)

            if combined.strip():
                turns.append({"role": role, "text": combined.strip()})

        if not turns:
            print(f"No meaningful content found for session {session_id}")
            return

        # If --last-turn, extract only the last user+assistant exchange
        if last_turn:
            turns = extract_last_turn(turns)

        # Apply limit
        if limit and not last_turn:
            turns = turns[-limit:]

        # Format output
        for turn in turns:
            role_label = "[Human]" if turn["role"] == "user" else "[Assistant]"
            text = turn["text"]
            # Truncate very long turns
            if len(text) > 3000:
                text = text[:3000] + "\n..."
            print(f"{role_label}: {text}\n")

    finally:
        conn.close()


def extract_last_turn(turns):
    """Extract the last user+assistant pair from turns."""
    if not turns:
        return []

    # Find the last user message (threshold 5 chars to support CJK)
    last_user_idx = -1
    for i in range(len(turns) - 1, -1, -1):
        if turns[i]["role"] == "user" and len(turns[i]["text"]) > 5:
            last_user_idx = i
            break

    if last_user_idx == -1:
        return []

    return turns[last_user_idx:]


def main():
    parser = argparse.ArgumentParser(description="Parse OpenCode session transcript")
    parser.add_argument("session_id", help="Session ID to parse")
    parser.add_argument("--limit", type=int, default=20, help="Max messages to return")
    parser.add_argument(
        "--last-turn",
        action="store_true",
        help="Only return the last user+assistant turn",
    )
    args = parser.parse_args()

    parse_session(args.session_id, limit=args.limit, last_turn=args.last_turn)


if __name__ == "__main__":
    main()
