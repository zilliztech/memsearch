#!/usr/bin/env python3
"""Background daemon that watches OpenCode SQLite for completed turns and captures them.

Usage:
  capture-daemon.py <project_dir> <collection_name> [--memsearch-cmd CMD]

The daemon polls the OpenCode SQLite database for new completed messages,
extracts the last turn, summarizes it as bullet points, and writes to
<project_dir>/.memsearch/memory/YYYY-MM-DD.md.

It also triggers memsearch indexing after writing.
"""

import sqlite3
import json
import sys
import os
import time
import shutil
import subprocess
import argparse
import signal
from datetime import datetime
from pathlib import Path


def get_small_model():
    """Read small_model from opencode.json config (fallback to model, then empty)."""
    config_paths = [
        os.path.expanduser("~/.config/opencode/opencode.json"),
        "opencode.json",
    ]
    for p in config_paths:
        if os.path.exists(p):
            try:
                with open(p) as f:
                    cfg = json.load(f)
                return cfg.get("small_model", cfg.get("model", ""))
            except Exception:
                pass
    return ""


def ensure_isolated_config():
    """Create isolated config dir without plugins/ to prevent recursion."""
    isolated = "/tmp/opencode-memsearch-summarize/opencode"
    os.makedirs(isolated, exist_ok=True)
    # Copy opencode.json (provider config) but NOT plugins/
    src = os.path.expanduser("~/.config/opencode/opencode.json")
    dst = os.path.join(isolated, "opencode.json")
    if os.path.exists(src) and not os.path.exists(dst):
        shutil.copy2(src, dst)
    return os.path.dirname(isolated)  # /tmp/opencode-memsearch-summarize


def summarize_with_llm(turn_text, small_model):
    """Summarize using opencode run in isolated env (no plugins -> no recursion)."""
    # Keep the instruction short and put it AFTER the transcript to avoid
    # the LLM treating the instruction itself as the conversation content.
    # Clear delimiters (===) separate the transcript from the task.
    full_prompt = (
        f"===TRANSCRIPT START===\n"
        f"{turn_text}\n"
        f"===TRANSCRIPT END===\n\n"
        f"Summarize the transcript above as 2-6 third-person bullet points (each starting with '- '). "
        f"Write 'User asked/did...' and 'OpenCode replied/did...'. "
        f"Be specific (file names, tools, outcomes). "
        f"Same language as the human. "
        f"Output ONLY bullet points, nothing else."
    )
    isolated_dir = ensure_isolated_config()

    cmd = ["opencode", "run"]
    if small_model:
        cmd += ["-m", small_model]
    cmd.append(full_prompt)

    try:
        result = subprocess.run(
            cmd,
            env={
                **os.environ,
                "XDG_CONFIG_HOME": isolated_dir,
                "XDG_DATA_HOME": os.path.join(isolated_dir, "data"),
                "MEMSEARCH_NO_WATCH": "1",
            },
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        # Extract bullet points (skip any opencode run header lines)
        lines = output.split("\n")
        bullets = [l for l in lines if l.strip().startswith("- ")]
        if bullets:
            return "\n".join(bullets)
    except Exception:
        pass

    return None  # fallback to raw text


def get_db_path():
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


def get_new_completed_turns(conn, project_dir, last_msg_time):
    """Get new user+assistant pairs from sessions in the project directory.

    Returns a list of (session_id, turn_text, max_msg_time) tuples for
    turns whose messages are newer than last_msg_time.
    """
    # Find all sessions for this project directory
    sessions = conn.execute(
        """
        SELECT s.id FROM session s
        WHERE s.directory = ?
        ORDER BY s.time_updated DESC
        LIMIT 5
        """,
        (project_dir,),
    ).fetchall()

    if not sessions:
        # Fallback: match by basename
        sessions = conn.execute(
            """
            SELECT s.id FROM session s
            WHERE s.directory LIKE ?
            ORDER BY s.time_updated DESC
            LIMIT 5
            """,
            (f"%{os.path.basename(project_dir)}%",),
        ).fetchall()

    results = []
    for (session_id,) in sessions:
        # Get messages newer than last_msg_time, in pairs (user + assistant)
        messages = conn.execute(
            """
            SELECT m.id, m.data, m.time_created
            FROM message m
            WHERE m.session_id = ? AND m.time_created > ?
            ORDER BY m.time_created ASC
            """,
            (session_id, last_msg_time),
        ).fetchall()

        # Group into user+assistant pairs
        i = 0
        while i < len(messages):
            msg_data = json.loads(messages[i][1])
            role = msg_data.get("role", "")
            msg_time = messages[i][2]

            if role == "user":
                user_text = _extract_msg_text(conn, messages[i][0], messages[i][1])
                assistant_text = ""
                # Look for following assistant message
                if i + 1 < len(messages):
                    next_data = json.loads(messages[i + 1][1])
                    if next_data.get("role") == "assistant":
                        assistant_text = _extract_msg_text(conn, messages[i + 1][0], messages[i + 1][1])
                        msg_time = messages[i + 1][2]
                        i += 1

                if user_text and len(user_text) > 5:
                    turn = f"[Human]: {user_text[:2000]}"
                    if assistant_text:
                        turn += f"\n\n[Assistant]: {assistant_text[:2000]}"
                    results.append((session_id, turn, msg_time))
            i += 1

    return results


def _extract_msg_text(conn, msg_id, msg_json):
    """Extract readable text from a message's parts."""
    parts = conn.execute(
        "SELECT data FROM part WHERE message_id = ? ORDER BY time_created ASC",
        (msg_id,),
    ).fetchall()

    text_parts = []
    for (part_json,) in parts:
        part_data = json.loads(part_json)
        if part_data.get("type") == "text" and part_data.get("text"):
            if not part_data.get("synthetic"):
                text_parts.append(part_data["text"].strip())
        elif part_data.get("type") == "tool" and part_data.get("state", {}).get("status") == "completed":
            tool_name = part_data.get("tool", "unknown")
            tool_input = part_data.get("state", {}).get("input", {})
            hint = ""
            if isinstance(tool_input, dict):
                if "command" in tool_input:
                    hint = f" `{tool_input['command'][:80]}`"
                elif "path" in tool_input:
                    hint = f" {tool_input['path']}"
            text_parts.append(f"[Tool: {tool_name}{hint}]")

    return "\n".join(text_parts)


def write_capture(memory_dir, turn_text, session_id):
    """Write a captured turn to the daily memory file."""
    os.makedirs(memory_dir, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M")
    memory_file = os.path.join(memory_dir, f"{today}.md")

    if not os.path.exists(memory_file):
        with open(memory_file, "w") as f:
            f.write(f"# {today}\n\n## Session {now}\n\n")

    anchor = f"<!-- session:{session_id} source:opencode-sqlite -->\n" if session_id else ""
    entry = f"### {now}\n{anchor}{turn_text}\n\n"

    with open(memory_file, "a") as f:
        f.write(entry)

    return memory_file


def main():
    parser = argparse.ArgumentParser(description="Capture daemon for OpenCode sessions")
    parser.add_argument("project_dir", help="Project directory")
    parser.add_argument("collection_name", help="Milvus collection name")
    parser.add_argument("--memsearch-cmd", default="memsearch", help="memsearch command")
    parser.add_argument("--poll-interval", type=int, default=10, help="Poll interval in seconds")
    args = parser.parse_args()

    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"OpenCode database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    memory_dir = os.path.join(args.project_dir, ".memsearch", "memory")
    pid_file = os.path.join(args.project_dir, ".memsearch", ".capture.pid")

    # Write PID file
    os.makedirs(os.path.dirname(pid_file), exist_ok=True)
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    # Clean up on exit
    def cleanup(signum=None, frame=None):
        try:
            os.remove(pid_file)
        except OSError:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    small_model = get_small_model()
    # Track by message time — persisted to disk so daemon restarts don't re-capture
    state_file = os.path.join(args.project_dir, ".memsearch", ".last_msg_time")
    last_msg_time = 0
    if os.path.exists(state_file):
        try:
            last_msg_time = int(open(state_file).read().strip())
        except (ValueError, OSError):
            pass

    while True:
        try:
            conn = sqlite3.connect(db_path, timeout=5)

            new_turns = get_new_completed_turns(conn, args.project_dir, last_msg_time)
            for session_id, turn_text, msg_time in new_turns:
                if turn_text and len(turn_text) > 10:
                    # Summarize with LLM, fallback to raw text
                    summary = summarize_with_llm(turn_text, small_model)
                    write_capture(memory_dir, summary if summary else turn_text, session_id)
                    if msg_time > last_msg_time:
                        last_msg_time = msg_time
                        try:
                            with open(state_file, "w") as sf:
                                sf.write(str(last_msg_time))
                        except OSError:
                            pass

            if new_turns:
                # Index in background after batch capture
                os.system(
                    f"{args.memsearch_cmd} index '{memory_dir}' "
                    f"--collection {args.collection_name} &"
                )

            conn.close()
        except Exception:
            pass

        time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
