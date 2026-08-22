#!/usr/bin/env python3
"""Memsearch MCP server for Kimi Code CLI — semantic memory for the Kimi agent.

Kimi-native: capture + transcript read Kimi's OWN store
(~/.kimi-code/session_index.jsonl + sessions/*/agents/main/wire.jsonl);
search reads the SHARED per-project Milvus collection that the Claude Code /
OpenCode / Codex / Zed / Hermes captures also write — so the Kimi agent
recalls anything any agent captured in the same project.

Memory lives in each project's .memsearch/memory/YYYY-MM-DD.md (the shared
format) + the project's ms_<project>_<hash> collection.

Tools:
  memory_search       semantic search over the current project's memories
  memory_get          expand a chunk to its full section
  memory_transcript   read the original turns of a Kimi session (wire.jsonl)
  memory_capture      capture recent Kimi sessions into the shared daily files

Setup:
  uv tool install "memsearch[onnx]"
  python3 -m venv .venv && .venv/bin/pip install fastmcp
  # ~/.kimi-code/mcp.json  (or .kimi-code/mcp.json in the project)
  {"mcpServers": {"memsearch": {
      "command": "<this dir>/.venv/bin/python",
      "args": ["<this file>"]}}}
  New Kimi sessions then expose mcp__memsearch__memory_* tools.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime

from fastmcp import FastMCP

mcp = FastMCP("memsearch")

KIMI_HOME = os.path.expanduser("~/.kimi-code")
INDEX_FILE = os.path.join(KIMI_HOME, "session_index.jsonl")
CAPTURE = os.path.expanduser("~/.memsearch/scripts/kimi-capture.py")


def run_memsearch(*args: str, cwd: str | None = None) -> str:
    r = subprocess.run(["memsearch", *args], capture_output=True, text=True,
                       cwd=cwd, timeout=300)
    return r.stdout.strip() if r.stdout.strip() else r.stderr.strip()


def _text_of(msg: dict) -> str:
    """Join the text parts of a Kimi message content list."""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for p in content:
        if isinstance(p, dict) and p.get("type") == "text" and p.get("text"):
            parts.append(p["text"])
    return "\n".join(parts)


@mcp.tool()
def memory_search(query: str, top_k: int = 5) -> str:
    """Semantic search over the current project's shared memories.

    Memories come from ALL agents that captured in the same project (Claude
    Code, OpenCode, Codex, Zed, Hermes, and Kimi itself). Uses the CWD-based
    collection (the memsearch index . rule) — run from the project root.

    Args:
        query: the memory question (e.g. "what did we decide about X")
        top_k: number of chunks to return (default 5)
    """
    return run_memsearch(
        "search", query, "--top-k", str(top_k), "--json-output", cwd=os.getcwd()
    )


@mcp.tool()
def memory_get(chunk_hash: str) -> str:
    """Expand a memory chunk to its full markdown section with context.

    Args:
        chunk_hash: the chunk hash from a memory_search result
    """
    return run_memsearch("expand", chunk_hash, cwd=os.getcwd())


@mcp.tool()
def memory_transcript(session_id: str, limit: int = 30) -> str:
    """Read the original user/assistant turns of a Kimi session.

    Use when an expanded chunk carries a 'kimi session_id:<sid>' anchor and
    the exact reasoning matters.

    Args:
        session_id: the Kimi session id (from the memory anchor)
        limit: max turns to return (default 30, newest first)
    """
    if not os.path.exists(INDEX_FILE):
        return f"no Kimi session store at {INDEX_FILE}"
    sdir = None
    with open(INDEX_FILE) as f:
        for line in f:
            try:
                idx = json.loads(line)
            except Exception:
                continue
            if idx.get("sessionId") == session_id:
                sdir = idx.get("sessionDir")
                break
    if not sdir:
        return f"no Kimi session found for {session_id}"
    wire = os.path.join(sdir, "agents", "main", "wire.jsonl")
    if not os.path.exists(wire):
        return f"no transcript for {session_id}"
    turns = []
    with open(wire, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("type") != "context.append_message":
                continue
            msg = ev.get("message") or {}
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            text = _text_of(msg).strip().replace("\n", " ")
            if len(text) > 1200:
                text = text[:1200] + " …"
            if text:
                turns.append(f"({role}) {text}")
    if not turns:
        return f"no turns found for session {session_id}"
    return "\n".join(turns[-limit:])


@mcp.tool()
def memory_capture() -> str:
    """Capture recent Kimi sessions into the shared daily memory files + re-index.

    Self-contained: reads ~/.kimi-code/session_index.jsonl, appends
    [User]:/[Assistant]: turns to each project's .memsearch/memory/YYYY-MM-DD.md
    (the shared format), and re-indexes. Idempotent — a per-session line-offset
    checkpoint prevents duplicates.
    """
    if not os.path.exists(CAPTURE):
        return f"kimi-capture missing at {CAPTURE}"
    r = subprocess.run(["python3", CAPTURE], capture_output=True, text=True,
                       timeout=300)
    return (r.stdout or r.stderr).strip()


if __name__ == "__main__":
    mcp.run()
