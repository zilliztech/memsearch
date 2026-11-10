#!/usr/bin/env python3
"""Read one explicitly scoped OpenCode V2 conversation; never use the sidecar as dialogue."""

from __future__ import annotations

import argparse
import contextlib
import sqlite3
import sys

from opencode_turns import Scope, TranscriptError, build_turns, find_turn_index, get_db_path, open_source, session_row


def parse_session(session_id: str, scope: Scope, db_path: str, *, limit=20, turn_id=None, context=3) -> str:
    with contextlib.closing(open_source(db_path)) as conn:
        session_row(conn, session_id, scope)
        turns = build_turns(conn, session_id)
    if not turns:
        raise TranscriptError("Session has no V2 user turns. Verify the referenced session and host migration.")
    if turn_id:
        index = find_turn_index(turns, turn_id)
        selected = turns[max(0, index - context) : index + context + 1]
    else:
        selected = turns[-limit:]
    return "\n\n".join(f"=== Turn {turn.turn_id} ===\n{turn.render()}" for turn in selected)


def bounded_int(low: int, high: int):
    def parse(value: str) -> int:
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"must be between {low} and {high}")
        return number

    return parse


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_id")
    parser.add_argument("--project-dir", required=True, help="Exact requesting checkout/root")
    parser.add_argument("--project-id", required=True, help="Requesting host project ID")
    parser.add_argument("--workspace-id")
    parser.add_argument("--db", help="Database path from the journal anchor")
    parser.add_argument("--channel", default="latest")
    parser.add_argument("--turn")
    parser.add_argument("--limit", type=bounded_int(1, 50), default=20)
    parser.add_argument("--context", type=bounded_int(0, 10), default=3)
    args = parser.parse_args()
    try:
        text = parse_session(
            args.session_id,
            Scope(args.project_dir, args.project_id, args.workspace_id),
            get_db_path(args.db, args.channel),
            limit=args.limit,
            turn_id=args.turn,
            context=args.context,
        )
        sys.stdout.write(text + "\n")
        return 0
    except (TranscriptError, sqlite3.Error, OSError) as exc:
        sys.stderr.write(f"Transcript unavailable: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
