#!/usr/bin/env python3
"""Memsearch MCP server for Hermes — semantic memory for the Hermes agent.

Hermes-native: capture + transcript read Hermes's OWN store
(~/.hermes/state.db); search reads the SHARED per-project Milvus collection
that the Claude Code / OpenCode / Codex plugins also write — so the Hermes
agent recalls anything captured by any agent.

Memory lives in a dedicated folder (default ~/hermes, override with the
HERMES_MEMORY_HOME env var) so Hermes conversations don't pollute project
repos: <home>/.memsearch/memory/YYYY-MM-DD.md + the ms_<home>_<hash> collection.

Tools:
  memory_search       semantic search over the project's indexed memories
  memory_get          expand a chunk to its full section
  memory_transcript   read the original turns of a Hermes session (state.db)
  memory_capture      capture recent Hermes sessions into the daily memory file

Setup:
  uv tool install "memsearch[onnx]"
  python3 -m venv .venv && .venv/bin/pip install fastmcp
  hermes mcp add memsearch --command "<venv>/bin/python <this script>"
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("memsearch")

HERMES_DB = os.path.expanduser("~/.hermes/state.db")
MEMORY_HOME = os.path.expanduser(os.environ.get("HERMES_MEMORY_HOME", "~/hermes"))


def derive_collection() -> str:
    p = os.path.abspath(MEMORY_HOME)
    base = os.path.basename(p).lower()
    base = re.sub(r"[^a-z0-9]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_")[:40]
    h = hashlib.sha256(p.encode()).hexdigest()[:8]
    return f"ms_{base}_{h}"


def run_memsearch(*args: str) -> str:
    r = subprocess.run(["memsearch", *args], capture_output=True, text=True)
    return r.stdout.strip() if r.stdout.strip() else r.stderr.strip()


@mcp.tool()
def memory_search(query: str, top_k: int = 5) -> str:
    """Semantic search over the shared memory (hybrid BM25 + dense + RRF).

    Memories come from ALL agents that captured in the same place (Claude
    Code, OpenCode, Codex, Zed, and Hermes itself).

    Args:
        query: the memory question (e.g. "what did we decide about X")
        top_k: number of chunks to return (default 5)
    """
    coll = derive_collection()
    return run_memsearch(
        "search", query, "--top-k", str(top_k), "--json-output", "--collection", coll
    )


@mcp.tool()
def memory_get(chunk_hash: str) -> str:
    """Expand a memory chunk to its full markdown section with context.

    Args:
        chunk_hash: the chunk hash from a memory_search result
    """
    return run_memsearch("expand", chunk_hash, "--collection", derive_collection())


@mcp.tool()
def memory_transcript(session_id: str, turn_id: int | None = None, context: int = 3) -> str:
    """Read the original conversation of a Hermes session from ~/.hermes/state.db.

    Use when an expanded chunk carries a 'hermes session_id:<sid>' anchor and
    the exact reasoning matters.

    Args:
        session_id: the Hermes session id (from the memory anchor)
        turn_id: optional message id to center a window around
        context: turns before/after the anchor (default 3)
    """
    if not os.path.exists(HERMES_DB):
        return f"no Hermes session store at {HERMES_DB}"
    con = sqlite3.connect(f"file:{HERMES_DB}?mode=ro", uri=True)
    if turn_id:
        rows = con.execute(
            "SELECT id, role, content, timestamp FROM messages "
            "WHERE session_id=? AND content != '' AND id BETWEEN ? AND ? ORDER BY id",
            (session_id, turn_id - context, turn_id + context)).fetchall()
    else:
        rows = con.execute(
            "SELECT id, role, content, timestamp FROM messages "
            "WHERE session_id=? AND content != '' ORDER BY id DESC LIMIT 30",
            (session_id,)).fetchall()
        rows = list(reversed(rows))
    if not rows:
        return f"no turns found for session {session_id}"
    out = []
    for mid, role, content, ts in rows:
        text = content.strip().replace("\n", " ")
        if len(text) > 1200:
            text = text[:1200] + " …"
        out.append(f"[{datetime.fromtimestamp(ts).strftime('%H:%M')}] "
                   f"({role}, msg {mid}) {text}")
    return "\n".join(out)


@mcp.tool()
def memory_capture(minutes: int = 60) -> str:
    """Capture recent Hermes sessions into the shared daily memory file + re-index.

    Self-contained: reads ~/.hermes/state.db, appends [User]:/[Assistant]:
    turns to <MEMORY_HOME>/.memsearch/memory/YYYY-MM-DD.md (the shared format),
    and re-indexes. Idempotent — a checkpoint (.memsearch/hermes-capture-state.json,
    shared with any cron capture) prevents duplicates.

    Args:
        minutes: how far back to scan state.db (default 60)
    """
    p = os.path.abspath(MEMORY_HOME)
    memdir = os.path.join(p, ".memsearch")
    memory_dir = os.path.join(memdir, "memory")
    os.makedirs(memory_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    state_file = os.path.join(memdir, "hermes-capture-state.json")
    memory_file = os.path.join(memory_dir, f"{today}.md")
    if not os.path.exists(HERMES_DB):
        return f"no Hermes session store at {HERMES_DB}"
    state = {}
    if os.path.exists(state_file):
        try:
            state = json.load(open(state_file))
        except Exception:
            state = {}
    cutoff = datetime.now().timestamp() - minutes * 60
    con = sqlite3.connect(f"file:{HERMES_DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT session_id, id, role, content, timestamp FROM messages "
        "WHERE active=1 AND compacted=0 "
        "AND role IN ('user','assistant') "
        "AND content != '' AND content IS NOT NULL "
        "AND timestamp >= ? ORDER BY timestamp ASC", (cutoff,)).fetchall()
    sessions: dict = {}
    for sid, mid, role, content, ts in rows:
        sessions.setdefault(sid, []).append((sid, mid, role, content, ts))
    written = 0
    for sid, msgs in sessions.items():
        last = state.get("session", {}).get(sid, -1)
        new = [m for m in msgs if m[1] > last]
        if not new:
            continue
        hhmm = datetime.fromtimestamp(new[0][4]).strftime("%H:%M")
        lines = [f"\n## Session {hhmm}",
                 f"<!-- hermes session_id:{sid} capture:{new[-1][1]} "
                 f"transcript:hermes-state-db -->",
                 "=== Transcript of a conversation between User and Hermes ==="]
        for _, mid, role, content, ts in new[:60]:
            text = content.strip()
            if not text:
                continue
            if len(text) > 1200:
                text = text[:1200] + " …"
            label = "User" if role == "user" else "Assistant"
            lines.append(f"[{label}]: {text}")
        with open(memory_file, "a") as f:
            f.write("\n".join(lines))
        state.setdefault("session", {})[sid] = new[-1][1]
        written += 1
    if written:
        with open(state_file, "w") as f:
            json.dump(state, f)
        run_memsearch("index", memory_dir, "--collection", derive_collection())
    if not rows:
        return "capture: nothing new in the last %d min" % minutes
    return f"capture: appended {written} session(s) to {memory_file}"


if __name__ == "__main__":
    mcp.run()
