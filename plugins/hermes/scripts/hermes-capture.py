#!/usr/bin/env python3
"""Capture recent Hermes session turns into the SAME daily
.memsearch/memory/YYYY-MM-DD.md format that Claude Code / OpenCode / Codex
plugins write, so the agents share one semantic memory. Modeled on OpenCode's
plugin (background poll of its SQLite store) — Hermes's state.db is the
analogue, so this is the hookless Hermes capture.

Reads ~/.hermes/state.db for the last [minutes] of user+assistant turns and
appends them to the project daily file. A per-project state checkpoint
prevents duplicate appends.

Usage: hermes-capture.py <project_dir> [minutes=60]
"""
import argparse, json, os, sqlite3, subprocess, sys, time
from collections import OrderedDict
from datetime import datetime

HERMES_DB = os.path.expanduser('~/.hermes/state.db')


def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(path, session_id, msg_id):
    d = load_state(path)
    d.setdefault('session', {})[session_id] = msg_id
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(d, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('project_dir')
    ap.add_argument('minutes', nargs='?', default=60, type=int)
    args = ap.parse_args()

    proj = args.project_dir
    memdir = os.path.join(proj, '.memsearch')
    memory_dir = os.path.join(memdir, 'memory')
    os.makedirs(memory_dir, exist_ok=True)
    today = datetime.now().strftime('%Y-%m-%d')
    state_file = os.path.join(memdir, 'hermes-capture-state.json')
    memory_file = os.path.join(memory_dir, f'{today}.md')

    if not os.path.exists(HERMES_DB):
        print('capture: no hermes state.db at', HERMES_DB)
        return 1

    cutoff = time.time() - args.minutes * 60
    con = sqlite3.connect(f'file:{HERMES_DB}?mode=ro', uri=True)
    rows = con.execute(
        'SELECT session_id, id, role, content, timestamp FROM messages '
        'WHERE active=1 AND compacted=0 '
        "AND role IN ('user','assistant') "
        "AND content != '' AND content IS NOT NULL "
        'AND timestamp >= ? ORDER BY timestamp ASC', (cutoff,)).fetchall()

    groups = OrderedDict()
    for sid, mid, role, content, ts in rows:
        groups.setdefault(sid, []).append((sid, mid, role, content, ts))
    if not groups:
        print('capture: nothing new in last %d min' % args.minutes)
        return 0

    state = load_state(state_file)
    written = 0
    for sid, msgs in groups.items():
        last = state.get('session', {}).get(sid, -1)
        new = [m for m in msgs if m[1] > last]
        if not new:
            continue
        hhmm = datetime.fromtimestamp(new[0][4]).strftime('%H:%M')
        session_title = ''  # could pull from sessions.title if needed
        lines = [
            f'\n## Session {hhmm}',
            f'<!-- hermes session_id:{sid} capture:{new[-1][1]} '
            f'transcript:hermes-state-db -->',
            '=== Transcript of a conversation between User and Hermes ===',
        ]
        for _, mid, role, content, ts in new[:60]:
            text = content.strip()
            if not text:
                continue
            if len(text) > 1200:
                text = text[:1200] + ' …'
            label = 'User' if role == 'user' else 'Assistant'
            lines.append(f'[{label}]: {text}')
        with open(memory_file, 'a') as f:
            f.write('\n'.join(lines))
        save_state(state_file, sid, new[-1][1])
        written += 1

    if not written:
        print('capture: no new turns (all up to date)')
        return 0

    rc = subprocess.run(
        ['bash', os.path.join(memdir, 'scripts', 'derive-collection.sh'), proj],
        capture_output=True, text=True)
    coll = rc.stdout.strip() if rc.returncode == 0 else None
    if coll:
        subprocess.run(['memsearch', 'index', memory_dir, '--collection', coll],
                       capture_output=True)
    print('capture: appended %d session(s) to %s' % (written, memory_file))
    return 0


if __name__ == '__main__':
    sys.exit(main())