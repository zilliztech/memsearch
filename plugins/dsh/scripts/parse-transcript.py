#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["zstandard>=0.23"]
# ///
"""Parse a DSH session artifact into readable [User]/[Assistant] turns.

Level-3 progressive disclosure for the memsearch ``memory-recall`` skill:
after ``memsearch search``/``expand`` surfaces an anchor comment of the form

    <!-- session:<id> turn:<N> db:<path> -->

this script renders the original DSH conversation around that turn.

The artifact is the JSONL log DSH persists per session
(``~/.dsh/sessions/--<project>--/<session>/session.jsonl.zstd``), whose first
line is a ``session`` header followed by ``SessionEvent`` lines and (for
streaming deltas) packed ``*-chunks`` rows. Only the assembled event lines are
rendered; packed delta rows are ignored because the ``assistant/message``
event already carries the full text.

Usage:
    parse-transcript.py --db <log-or-dir> [--session <id>] [--turn <N>] \\
        [--context <K>] [--limit <N>]
"""

# ruff: noqa: T201  # CLI tool: stdout/stderr are the output mechanism
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TEXT_BLOCK_TYPES = {"text"}


def _read_bytes(path: Path) -> bytes:
    """Read a session artifact, decompressing zstd when the suffix says so."""
    raw = path.read_bytes()
    if path.name.endswith(".zstd"):
        return _zstd_decompress(raw)
    return raw


def _zstd_decompress(raw: bytes) -> bytes:
    """Read every independent frame in a DSH append-only session log."""
    try:
        import zstandard  # type: ignore[import-not-found]
    except ImportError:
        zstandard = None
    if zstandard is not None:
        parts = []
        while raw:
            decoder = zstandard.ZstdDecompressor().decompressobj()
            parts.append(decoder.decompress(raw))
            if not decoder.eof:
                raise RuntimeError("incomplete zstd frame in session log")
            raw = decoder.unused_data
        return b"".join(parts)
    zstd_bin = shutil.which("zstd")
    if not zstd_bin:
        raise RuntimeError(
            "cannot decompress session log: install the Python `zstandard` package or the `zstd` CLI binary, "
            "or run this script with `uv run --script` to use its declared dependencies"
        )
    result = subprocess.run(
        [zstd_bin, "-d", "-c"],
        input=raw,
        capture_output=True,
        check=False,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
    )
    if result.returncode != 0:
        raise RuntimeError(f"zstd -d failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def _resolve_artifact(db_arg: str) -> tuple[Path, str]:
    """Locate the session JSONL artifact from an anchor ``db:`` value."""
    candidate = Path(db_arg).expanduser()
    if candidate.is_file():
        return candidate, candidate.name
    if candidate.is_dir():
        for suffix in (".jsonl.zstd", ".jsonl"):
            match = candidate / f"session{suffix}"
            if match.is_file():
                return match, match.name
        raise RuntimeError(f"no session.jsonl artifact found under {candidate}")
    raise RuntimeError(f"session artifact does not exist: {candidate}")


def _text_of(message: dict) -> str:
    """Concatenate text blocks of a message's content list."""
    content = message.get("content") or []
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") in TEXT_BLOCK_TYPES and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts).strip()


def _load_events(path: Path) -> tuple[str, list[dict]]:
    """Parse the artifact into (session_id, event dicts). Ignores packed rows."""
    lines = _read_bytes(path).decode("utf-8", errors="replace").splitlines()
    session_id = ""
    events: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            # The durable tail may be truncated mid-line after an interrupted
            # flush; skip partial lines rather than failing the whole render.
            continue
        if not isinstance(record, dict):
            continue
        record_type = record.get("type")
        if record_type == "session":
            session_id = str(record.get("id") or "")
            continue
        if record_type and "-chunks" in record_type:
            continue  # packed streaming deltas; assistant/message carries the text
        if "data" in record:
            events.append(record)
    return session_id, events


def _build_turns(session_id: str, events: list[dict]) -> list[dict]:
    """Group events into turns, returning one dict per turn."""
    turns: list[dict] = []
    current: dict | None = None
    for event in events:
        event_type = event.get("type")
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        if event_type == "turn/start":
            current = {"turn": data.get("turn"), "items": []}
            turns.append(current)
            continue
        if current is None:
            continue
        if event_type == "user/message":
            source = data.get("source") or {}
            if source.get("kind") != "user":
                continue  # skip plugin injections (e.g. time-context, memsearch)
            current["items"].append(("[User]", _text_of(data)))
        elif event_type == "assistant/message":
            message = data.get("message") or {}
            text = _text_of(message)
            if text:
                current["items"].append(("[Assistant]", text))
        elif event_type == "tool/call":
            name = data.get("name") or ""
            if name:
                current["items"].append(("[Tool call]", name))
    return turns


def _render_turn(turn: dict) -> str:
    """Render one turn into transcript text (mirrors the capture renderer)."""
    lines = [f"=== Turn {turn['turn']} ==="]
    for label, text in turn["items"]:
        lines.append("")
        lines.append(f"{label}: {text}")
    return "\n".join(lines).strip()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Render a DSH session artifact as readable turns.")
    parser.add_argument("--db", required=True, help="Session log file or directory (from an anchor db: field).")
    parser.add_argument("--session", default="", help="Expected session id (validated when given).")
    parser.add_argument("--turn", default=None, type=int, help="Target turn; show it plus surrounding context.")
    parser.add_argument("--context", default=3, type=int, help="Turns before/after the target (default: 3).")
    parser.add_argument("--limit", default=20, type=int, help="Max turns when no --turn is given (default: 20).")
    args = parser.parse_args()

    try:
        path, _ = _resolve_artifact(args.db)
        session_id, events = _load_events(path)
    except Exception as error:  # surface the reader failure
        print(f"Error: {error}", file=sys.stderr)
        return 1

    if args.session and session_id and args.session != session_id:
        print(
            f"Error: session id mismatch (expected {args.session}, artifact has {session_id})",
            file=sys.stderr,
        )
        return 1

    turns = _build_turns(session_id, events)
    if not turns:
        print("(no turns found)", file=sys.stderr)
        return 1

    if args.turn is not None:
        index = next((i for i, t in enumerate(turns) if t["turn"] == args.turn), None)
        if index is None:
            print(f"Error: turn {args.turn} not found (turns: {[t['turn'] for t in turns]})", file=sys.stderr)
            return 1
        lo = max(0, index - args.context)
        hi = min(len(turns), index + args.context + 1)
        selected = turns[lo:hi]
    else:
        selected = turns[-max(1, args.limit) :]

    header = f"Session {session_id or '(unknown)'}"
    blocks = [_render_turn(turn) for turn in selected]
    print(f"# {header}\n")
    print("\n\n".join(blocks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
