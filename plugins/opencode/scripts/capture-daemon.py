#!/usr/bin/env python3
"""Background daemon that watches OpenCode SQLite for completed turns and captures them.

Usage:
  capture-daemon.py <project_dir> <collection_name> [--memsearch-cmd CMD]

The daemon polls the OpenCode SQLite database for completed turns, extracts
the latest completed turn, summarizes it as bullet points, and writes to
<project_dir>/.memsearch/memory/YYYY-MM-DD.md.

It also persists derived turn metadata in <project_dir>/.memsearch/opencode-turns.db
and triggers memsearch indexing after writing.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from opencode_turns import (
    build_turns,
    get_db_path,
    load_turn_state,
    open_turn_db,
    save_turn,
    save_turn_state,
)

_ANCHOR_RE = re.compile(r"<!-- session:([^ ]+) turn:([^ ]+) db:")
_TAIL_TURN_QUIET_PERIOD_MS = 300_000


class TailTurnObservation:
    __slots__ = ("fingerprint", "stable_since_ms", "turn_id")

    def __init__(self, turn_id: str, fingerprint: str, stable_since_ms: int) -> None:
        self.turn_id = turn_id
        self.fingerprint = fingerprint
        self.stable_since_ms = stable_since_ms


def split_memsearch_cmd(memsearch_cmd: str) -> list[str]:
    """Split the configured memsearch command preserving quoted arguments."""
    return shlex.split(memsearch_cmd)


def get_small_model() -> str:
    """Read small_model from opencode.json config (fallback to model, then empty)."""
    config_paths = [
        os.path.expanduser("~/.config/opencode/opencode.json"),
        "opencode.json",
    ]
    for p in config_paths:
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    cfg = json.load(f)
                return cfg.get("small_model", cfg.get("model", ""))
            except Exception:
                pass
    return ""


def get_plugin_summarize_model(memsearch_cmd: str | None = None) -> str:
    """Read the memsearch OpenCode summarize model override."""
    if not memsearch_cmd:
        return ""
    try:
        result = subprocess.run(
            [*split_memsearch_cmd(memsearch_cmd), "config", "get", "plugins.opencode.summarize.model"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def ensure_isolated_config() -> str:
    """Create isolated config dir without plugins/ to prevent recursion."""
    isolated = os.path.expanduser("~/.codex/tmp/opencode-memsearch-summarize/opencode")
    os.makedirs(isolated, exist_ok=True)
    # Copy opencode.json (provider config) but NOT plugins/
    src = os.path.expanduser("~/.config/opencode/opencode.json")
    dst = os.path.join(isolated, "opencode.json")
    if os.path.islink(dst) or (os.path.lexists(dst) and not os.path.isfile(dst)):
        with contextlib.suppress(OSError):
            os.remove(dst)
    if os.path.exists(src) and not os.path.exists(dst):
        shutil.copy2(src, dst)
    return os.path.dirname(isolated)


def _load_summarize_prompt(agent_name: str, memsearch_cmd: str | None = None) -> str:
    """Load summarization prompt: user custom > plugin built-in > inline fallback."""
    # Try user-custom prompt via config
    if memsearch_cmd:
        try:
            result = subprocess.run(
                [*split_memsearch_cmd(memsearch_cmd), "config", "get", "prompts.summarize"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            custom_path = result.stdout.strip()
            if custom_path and os.path.isfile(custom_path):
                template = Path(custom_path).read_text(encoding="utf-8")
                return template.replace("{{AGENT_NAME}}", agent_name)
        except Exception:
            pass

    # Plugin built-in template
    builtin = Path(__file__).resolve().parent.parent / "prompts" / "summarize.txt"
    if builtin.is_file():
        template = builtin.read_text(encoding="utf-8")
        return template.replace("{{AGENT_NAME}}", agent_name)

    # Inline fallback
    return (
        "You are a third-person note-taker. Summarize the transcript as "
        "2-6 bullet points. Write in third person. Output ONLY bullet points."
    )


def summarize_with_llm(turn_text: str, small_model: str, memsearch_cmd: str | None = None) -> str | None:
    """Summarize using opencode run in isolated env (no plugins -> no recursion)."""
    system_prompt = _load_summarize_prompt("OpenCode", memsearch_cmd)
    full_prompt = f"{system_prompt}\n\nTranscript:\n{turn_text}"
    isolated_dir = ensure_isolated_config()

    summarize_model = get_plugin_summarize_model(memsearch_cmd) or small_model
    cmd = ["opencode", "run"]
    if summarize_model:
        cmd += ["-m", summarize_model]
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
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip()
        lines = output.split("\n")
        bullets = [line for line in lines if line.strip().startswith("- ")]
        if bullets:
            return "\n".join(bullets)
    except Exception:
        pass

    return None


def get_session_ids(conn: sqlite3.Connection, project_dir: str) -> list[str]:
    """Find OpenCode sessions that belong to the given project directory."""
    sessions = conn.execute(
        """
        SELECT s.id
        FROM session s
        WHERE s.directory = ?
        ORDER BY s.time_updated DESC
        LIMIT 5
        """,
        (project_dir,),
    ).fetchall()

    if not sessions:
        sessions = conn.execute(
            """
            SELECT s.id
            FROM session s
            WHERE s.directory LIKE ?
            ORDER BY s.time_updated DESC
            LIMIT 5
            """,
            (f"%{os.path.basename(project_dir)}%",),
        ).fetchall()

    return [row[0] for row in sessions]


def _load_legacy_last_msg_time(project_dir: str) -> int:
    """Read the pre-sidecar capture checkpoint for upgrade compatibility."""
    path = Path(project_dir) / ".memsearch" / ".last_msg_time"
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0
    return max(value, 0)


def _make_capture_anchor_key(session_id: str, turn_id: str) -> tuple[str, str]:
    return (session_id, turn_id)


def load_capture_anchor_cache(memory_dir: str) -> set[tuple[str, str]]:
    if not os.path.isdir(memory_dir):
        return set()

    anchor_cache: set[tuple[str, str]] = set()
    for name in os.listdir(memory_dir):
        if not name.endswith(".md"):
            continue

        path = os.path.join(memory_dir, name)
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            continue

        for session_id, turn_id in _ANCHOR_RE.findall(text):
            anchor_cache.add(_make_capture_anchor_key(session_id, turn_id))

    return anchor_cache


def write_capture(
    memory_dir: str,
    turn_text: str,
    session_id: str,
    turn_id: str,
    db_path: str = "",
    anchor_cache: set[tuple[str, str]] | None = None,
) -> str:
    """Write a captured turn to the daily memory file."""
    os.makedirs(memory_dir, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M")
    memory_file = os.path.join(memory_dir, f"{today}.md")

    if not os.path.exists(memory_file):
        with open(memory_file, "w", encoding="utf-8") as f:
            f.write(f"# {today}\n\n## Session {now}\n\n")

    anchor = f"<!-- session:{session_id} turn:{turn_id} db:{db_path} -->\n" if session_id else ""
    entry = f"### {now}\n{anchor}{turn_text}\n\n"

    with open(memory_file, "a", encoding="utf-8") as f:
        f.write(entry)

    if session_id and anchor_cache is not None:
        anchor_cache.add(_make_capture_anchor_key(session_id, turn_id))

    return memory_file


def capture_exists(memory_dir: str, session_id: str, turn_id: str) -> bool:
    """Check whether a turn anchor was already written to memory markdown."""
    if not os.path.isdir(memory_dir):
        return False

    anchor = f"<!-- session:{session_id} turn:{turn_id} "
    for name in os.listdir(memory_dir):
        if not name.endswith(".md"):
            continue

        path = os.path.join(memory_dir, name)
        try:
            with open(path, encoding="utf-8") as handle:
                if anchor in handle.read():
                    return True
        except OSError:
            continue

    return False


def load_saved_turn_index(conn: sqlite3.Connection, session_id: str, turn_id: str) -> int | None:
    """Return an existing saved turn index when replaying a partially persisted turn."""
    row = conn.execute(
        """
        SELECT turn_index
        FROM turns
        WHERE session_id = ? AND turn_id = ?
        """,
        (session_id, turn_id),
    ).fetchone()
    if row is None:
        return None
    return int(row["turn_index"])


def get_next_turn_index(conn: sqlite3.Connection, session_id: str) -> int:
    """Return the next monotonically increasing turn index for a session."""
    row = conn.execute(
        """
        SELECT COALESCE(MAX(turn_index), 0) AS max_turn_index
        FROM turns
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    return int(row["max_turn_index"]) + 1


def _now_ms() -> int:
    return int(time.time() * 1000)


def _compute_turn_fingerprint(turn) -> str:
    payload = {
        "turn_id": turn.turn_id,
        "last_message_id": turn.last_message_id,
        "message_count": turn.message_count,
        "assistant_message_count": turn.assistant_message_count,
        "complete": turn.complete,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "parent_id": message.parent_id,
                "time_created": message.time_created,
                "finish": message.finish,
                "text": message.text,
            }
            for message in turn.messages
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()


def _tail_turn_is_stable_for_capture(
    turn,
    tail_turn_cache: dict[str, TailTurnObservation],
) -> bool:
    if not turn.complete:
        tail_turn_cache.pop(turn.session_id, None)
        return False

    fingerprint = _compute_turn_fingerprint(turn)
    now_ms = _now_ms()
    observed = tail_turn_cache.get(turn.session_id)
    if observed is None or observed.turn_id != turn.turn_id or observed.fingerprint != fingerprint:
        tail_turn_cache[turn.session_id] = TailTurnObservation(
            turn_id=turn.turn_id,
            fingerprint=fingerprint,
            stable_since_ms=now_ms,
        )
        return False

    return now_ms - observed.stable_since_ms >= _TAIL_TURN_QUIET_PERIOD_MS


def _turn_ready_for_capture(
    turn,
    is_tail_turn: bool,
    tail_turn_cache: dict[str, TailTurnObservation],
) -> bool:
    # A non-tail turn has already been closed by a later user message.
    if not is_tail_turn:
        tail_turn_cache.pop(turn.session_id, None)
        return True

    # The final turn must stay textually stable for a quiet window before capture.
    return _tail_turn_is_stable_for_capture(turn, tail_turn_cache)


def capture_session_turns(
    conn: sqlite3.Connection,
    turn_db: sqlite3.Connection,
    memory_dir: str,
    session_id: str,
    small_model: str,
    memsearch_cmd: str,
    db_path: str,
    tail_turn_cache: dict[str, TailTurnObservation] | None = None,
) -> bool:
    """Capture all newly completed turns for a single session."""
    state = load_turn_state(turn_db, session_id)
    captured_any = False
    next_turn_index = get_next_turn_index(turn_db, session_id)
    if tail_turn_cache is None:
        tail_turn_cache = {}

    after_time = state.last_completed_time if state.last_completed_time > 0 else None
    if after_time is None:
        legacy_after_time = _load_legacy_last_msg_time(str(Path(memory_dir).resolve().parent.parent))
        if legacy_after_time > 0:
            after_time = legacy_after_time
    after_message_id = state.last_completed_message_id or None
    turns = build_turns(
        conn,
        session_id,
        after_time=after_time,
        after_message_id=after_message_id,
    )

    for index, turn in enumerate(turns):
        is_tail_turn = index == len(turns) - 1
        if not _turn_ready_for_capture(turn, is_tail_turn, tail_turn_cache):
            break

        saved_turn_index = load_saved_turn_index(turn_db, session_id, turn.turn_id)
        if saved_turn_index is not None:
            turn.turn_index = saved_turn_index
        else:
            turn.turn_index = next_turn_index
            next_turn_index += 1

        turn_text = turn.render()
        if len(turn_text.strip()) <= 10:
            continue

        # Check anchor first so that sidecar rebuilds repair state without
        # calling the summarizer again for already-captured turns.
        if not capture_exists(memory_dir, session_id, turn.turn_id):
            summary = summarize_with_llm(turn_text, small_model, memsearch_cmd)
            write_capture(
                memory_dir,
                summary if summary else turn_text,
                session_id,
                turn.turn_id,
                db_path,
            )
        save_turn(turn_db, turn)
        state.last_completed_time = turn.end_time
        state.last_completed_message_id = turn.last_message_id
        state.last_completed_turn_id = turn.turn_id
        save_turn_state(turn_db, state)
        tail_turn_cache.pop(session_id, None)
        captured_any = True

    return captured_any


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture daemon for OpenCode sessions")
    parser.add_argument("project_dir", help="Project directory")
    parser.add_argument("collection_name", help="Milvus collection name")
    parser.add_argument("--memsearch-cmd", default="memsearch", help="memsearch command")
    parser.add_argument("--poll-interval", type=int, default=10, help="Poll interval in seconds")
    args = parser.parse_args()

    db_path = get_db_path()
    if not os.path.exists(db_path):
        sys.stderr.write(f"OpenCode database not found at {db_path}\n")
        sys.exit(1)

    memory_dir = os.path.join(args.project_dir, ".memsearch", "memory")
    pid_file = os.path.join(args.project_dir, ".memsearch", ".capture.pid")

    os.makedirs(os.path.dirname(pid_file), exist_ok=True)
    with open(pid_file, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    def cleanup(signum=None, frame=None) -> None:
        with contextlib.suppress(OSError):
            os.remove(pid_file)
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    small_model = get_small_model()
    turn_db = open_turn_db(args.project_dir)
    tail_turn_cache: dict[str, TailTurnObservation] = {}

    while True:
        any_new = False
        conn = None
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            for session_id in get_session_ids(conn, args.project_dir):
                any_new = (
                    capture_session_turns(
                        conn,
                        turn_db,
                        memory_dir,
                        session_id,
                        small_model,
                        args.memsearch_cmd,
                        db_path,
                        tail_turn_cache,
                    )
                    or any_new
                )

            if any_new:
                os.system(
                    f"{args.memsearch_cmd} index '{memory_dir}' "
                    f"--collection {args.collection_name} &"
                )
        except Exception:
            pass
        finally:
            if conn is not None:
                conn.close()

        time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
