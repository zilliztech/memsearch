#!/usr/bin/env python3
"""Read original conversation turns from the Hermes session store
(~/.hermes/state.db) — the Layer-3 "transcript" analogue of the OpenCode
plugin's parse-transcript.py. Hermes stores every message (role, content,
timestamp) per session_id.

Usage:
  parse-transcript.py <session_id> [--turn <message_id>] [--context <n>] [--limit <n>]
"""
import argparse, os, sqlite3

HERMES_DB = os.path.expanduser('~/.hermes/state.db')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('session_id')
    ap.add_argument('--turn', type=int, help='message id to center on')
    ap.add_argument('--context', type=int, default=3)
    ap.add_argument('--limit', type=int, default=50)
    args = ap.parse_args()

    con = sqlite3.connect(f'file:{HERMES_DB}?mode=ro', uri=True)
    if args.turn:
        # center a window around the given message id
        rows = con.execute(
            "SELECT id, role, content, timestamp FROM messages "
            "WHERE session_id=? AND content != '' "
            "AND id BETWEEN ? AND ? ORDER BY id", (
                args.session_id,
                args.turn - args.context,
                args.turn + args.context,
            )).fetchall()
    else:
        rows = con.execute(
            "SELECT id, role, content, timestamp FROM messages "
            "WHERE session_id=? AND content != '' ORDER BY id DESC LIMIT ?",
            (args.session_id, args.limit)).fetchall()
        rows = list(reversed(rows))

    from datetime import datetime
    for mid, role, content, ts in rows:
        text = content.strip().replace('\n', ' ')
        if len(text) > 1200:
            text = text[:1200] + ' …'
        print(f"[{datetime.fromtimestamp(ts).strftime('%H:%M')}] "
              f"({role}, msg {mid}) {text}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())