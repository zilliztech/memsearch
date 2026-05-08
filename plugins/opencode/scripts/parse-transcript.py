#!/usr/bin/env python3
"""Parse OpenCode SQLite transcript for a given session.

Usage:
  parse-transcript.py <session_id> [--limit N] [--turn TURN_ID] [--context N] [--project-dir PATH]

Options:
  --limit N        Max number of turns to return when no turn is targeted (default: 20)
  --turn TURN_ID   Return the target turn plus surrounding context turns
  --context N      Number of turns before/after the target turn (default: 3)
  --project-dir    OpenCode project directory (unused for transcript reads; kept for tool compatibility)

The script reads from the OpenCode SQLite database at:
  ~/.local/share/opencode/opencode.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

from opencode_turns import build_turns, find_turn_index, get_db_path


def _emit(text: str = "", *, err: bool = False) -> None:
    """Write a line of output without relying on print()."""
    stream = sys.stderr if err else sys.stdout
    stream.write(text)
    if not text.endswith("\n"):
        stream.write("\n")


def parse_session(
    session_id: str,
    limit: int = 20,
    turn_id: str | None = None,
    context: int = 3,
) -> None:
    """Parse messages for a session, grouped into turns."""
    db_path = get_db_path()
    if not os.path.exists(db_path):
        _emit(f"Error: OpenCode database not found at {db_path}", err=True)
        sys.exit(1)

    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row

    try:
        turns = build_turns(conn, session_id)
        if not turns:
            _emit(f"No messages found for session {session_id}")
            return

        if turn_id:
            target_idx = find_turn_index(turns, turn_id)
            if target_idx < 0:
                _emit(f"Turn not found: {turn_id}", err=True)
                sys.exit(1)

            start = max(0, target_idx - context)
            end = min(len(turns), target_idx + context + 1)
            selected = turns[start:end]
        elif limit and limit > 0:
            selected = turns[-limit:]
        else:
            selected = turns

        if not selected:
            _emit(f"No meaningful content found for session {session_id}")
            return

        for turn in selected:
            _emit(turn.render())
            _emit()

    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse OpenCode session transcript")
    parser.add_argument("session_id", help="Session ID to parse")
    parser.add_argument("--limit", type=int, default=20, help="Max turns to return")
    parser.add_argument("--turn", default=None, help="Target turn ID (prefix match)")
    parser.add_argument("--context", type=int, default=3, help="Turns before/after target")
    parser.add_argument(
        "--project-dir",
        default=os.getcwd(),
        help="OpenCode project directory (unused for transcript reads; kept for tool compatibility)",
    )
    args = parser.parse_args()

    # The capture daemon may maintain a turn sidecar for replay-safe progress,
    # but transcript reads always rebuild from the raw OpenCode SQLite database.
    parse_session(
        args.session_id,
        limit=args.limit,
        turn_id=args.turn,
        context=args.context,
    )


if __name__ == "__main__":
    main()
