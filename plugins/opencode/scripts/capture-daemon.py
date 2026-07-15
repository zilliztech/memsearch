#!/usr/bin/env python3
"""Background daemon that watches OpenCode SQLite for completed turns and captures them.

Usage:
  capture-daemon.py <project_dir> <collection_name> [--memsearch-cmd CMD]
                    [--memsearch-dir DIR]

The daemon polls the OpenCode SQLite database for completed turns, extracts
the latest completed turn, summarizes it as bullet points, and writes to
<memsearch_dir>/memory/YYYY-MM-DD.md.

It also persists derived turn metadata in <memsearch_dir>/opencode-turns.db
and triggers memsearch indexing after writing. <memsearch_dir> defaults to
<project_dir>/.memsearch but honors MEMSEARCH_DIR (shared/global scope) when
the plugin passes --memsearch-dir. OpenCode session and config lookups still
key off the real <project_dir>.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shlex
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
_TAIL_TURN_QUIET_PERIOD_MS = int(os.environ.get("MEMSEARCH_OPENCODE_TAIL_QUIET_MS", "300000"))


class TailTurnObservation:
    """Track when the tail turn of a session last changed content."""

    __slots__ = ("fingerprint", "stable_since_ms", "turn_id")

    def __init__(self, turn_id: str, fingerprint: str, stable_since_ms: int) -> None:
        """Initialize with the turn ID, content fingerprint, and observation timestamp."""
        self.turn_id = turn_id
        self.fingerprint = fingerprint
        self.stable_since_ms = stable_since_ms


def split_memsearch_cmd(memsearch_cmd: str) -> list[str]:
    """Split the configured memsearch command preserving quoted arguments."""
    return shlex.split(memsearch_cmd)


def _strip_jsonc(text: str) -> str:
    """Remove JSONC comments and trailing commas while preserving string contents."""
    out: list[str] = []
    i = 0
    in_string = False
    string_quote = ""
    escaped = False
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_quote:
                in_string = False
            i += 1
            continue
        if char in {'"', "'"}:
            in_string = True
            string_quote = char
            out.append(char)
            i += 1
            continue
        if char == "/" and nxt == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if char == "/" and nxt == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(char)
        i += 1

    without_comments = "".join(out)
    out = []
    i = 0
    in_string = False
    string_quote = ""
    escaped = False
    while i < len(without_comments):
        char = without_comments[i]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_quote:
                in_string = False
            i += 1
            continue
        if char in {'"', "'"}:
            in_string = True
            string_quote = char
            out.append(char)
            i += 1
            continue
        if char == ",":
            j = i + 1
            while j < len(without_comments) and without_comments[j].isspace():
                j += 1
            if j < len(without_comments) and without_comments[j] in "]}":
                i += 1
                continue
        out.append(char)
        i += 1
    return "".join(out)


def _read_jsonc_config(path: Path) -> dict:
    """Parse a JSONC file, returning an empty dict on any error."""
    try:
        data = json.loads(_strip_jsonc(path.read_text(encoding="utf-8")))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _deep_merge_config(base: dict, override: dict) -> dict:
    """Recursively merge override into base, deep-merging nested dicts."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_config(result[key], value)
        else:
            result[key] = value
    return result


def _rewrite_relative_file_refs(value, config_dir: Path):
    """Resolve relative {file:...} references in config values to absolute paths."""
    if isinstance(value, dict):
        return {key: _rewrite_relative_file_refs(item, config_dir) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_relative_file_refs(item, config_dir) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        """Resolve one {file:...} match to an absolute path."""
        file_ref = match.group(1)
        if file_ref.startswith("~/") or os.path.isabs(file_ref):
            return match.group(0)
        return "{file:" + str((config_dir / file_ref).resolve()) + "}"

    return re.sub(r"\{file:([^}]+)\}", replace, value)


def _load_opencode_config_file(path: Path) -> dict:
    """Load a single OpenCode config file and resolve relative file references."""
    cfg = _read_jsonc_config(path)
    if not cfg:
        return {}
    return _rewrite_relative_file_refs(cfg, path.parent)


def _opencode_global_config_dir() -> Path:
    """Return the OpenCode global config directory, respecting XDG_CONFIG_HOME."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config).expanduser() / "opencode"
    return Path.home() / ".config" / "opencode"


def _env_flag_enabled(name: str) -> bool:
    """Return True if the named environment variable is set to a truthy value."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _opencode_project_config_files(project_dir: Path) -> list[Path]:
    """Walk ancestors of project_dir to collect opencode config files (nearest last)."""
    found: list[Path] = []
    current = project_dir.resolve()
    while True:
        for filename in ("opencode.jsonc", "opencode.json"):
            candidate = current / filename
            if candidate.is_file():
                found.append(candidate)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return list(reversed(found))


def _opencode_directory_config_files(project_dir: Path) -> list[Path]:
    """Collect config files from .opencode dirs, home, and OPENCODE_CONFIG_DIR."""
    dirs: list[Path] = []
    if not _env_flag_enabled("OPENCODE_DISABLE_PROJECT_CONFIG"):
        current = project_dir.resolve()
        while True:
            local = current / ".opencode"
            if local.is_dir() and local not in dirs:
                dirs.append(local)
            parent = current.parent
            if parent == current:
                break
            current = parent

    home_local = Path.home() / ".opencode"
    if home_local.is_dir() and home_local not in dirs:
        dirs.append(home_local)

    env_dir = os.environ.get("OPENCODE_CONFIG_DIR", "").strip()
    if env_dir:
        config_dir = Path(env_dir).expanduser()
        if config_dir not in dirs:
            dirs.append(config_dir)

    files: list[Path] = []
    for directory in dirs:
        for filename in ("opencode.json", "opencode.jsonc"):
            candidate = directory / filename
            if candidate.is_file():
                files.append(candidate)
    return files


def _iter_opencode_config_files(project_dir: str | os.PathLike[str] | None = None) -> list[Path]:
    """Return all OpenCode config files in load order (global → env → project → local)."""
    project = Path(project_dir or os.getcwd()).expanduser().resolve()
    files: list[Path] = []

    global_dir = _opencode_global_config_dir()
    for filename in ("config.json", "opencode.json", "opencode.jsonc"):
        candidate = global_dir / filename
        if candidate.is_file():
            files.append(candidate)

    env_config = os.environ.get("OPENCODE_CONFIG", "").strip()
    if env_config:
        candidate = Path(env_config).expanduser()
        if candidate.is_file():
            files.append(candidate)

    if not _env_flag_enabled("OPENCODE_DISABLE_PROJECT_CONFIG"):
        files.extend(_opencode_project_config_files(project))

    files.extend(_opencode_directory_config_files(project))
    return files


def load_opencode_config(project_dir: str | os.PathLike[str] | None = None) -> dict:
    """Load local OpenCode config sources in OpenCode-compatible precedence order."""
    merged: dict = {}
    for path in _iter_opencode_config_files(project_dir):
        merged = _deep_merge_config(merged, _load_opencode_config_file(path))

    content = os.environ.get("OPENCODE_CONFIG_CONTENT")
    if content:
        content_dir = Path(project_dir or os.getcwd()).expanduser().resolve()
        cfg = _rewrite_relative_file_refs(_read_jsonc_config_from_text(content), content_dir)
        merged = _deep_merge_config(merged, cfg)
    return merged


def _read_jsonc_config_from_text(text: str) -> dict:
    """Parse a JSONC string, returning an empty dict on any error."""
    try:
        data = json.loads(_strip_jsonc(text))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _sanitize_opencode_config(cfg: dict) -> dict:
    """Strip plugin keys from a config dict to prevent recursion during summarization."""
    sanitized = dict(cfg)
    for key in ("plugin", "plugins", "plugin_origins"):
        sanitized.pop(key, None)
    return sanitized


def get_small_model(project_dir: str | os.PathLike[str] | None = None) -> str:
    """Read small_model from OpenCode config, falling back to model."""
    cfg = load_opencode_config(project_dir)
    return str(cfg.get("small_model", cfg.get("model", "")) or "")


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


def get_plugin_summarize_provider(memsearch_cmd: str | None = None) -> str:
    """Read the memsearch OpenCode summarize provider route."""
    if not memsearch_cmd:
        return ""
    try:
        result = subprocess.run(
            [*split_memsearch_cmd(memsearch_cmd), "config", "get", "plugins.opencode.summarize.provider"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def get_plugin_summarize_enabled(memsearch_cmd: str | None = None) -> bool:
    """Read whether the memsearch OpenCode summarizer is enabled."""
    if not memsearch_cmd:
        return True
    try:
        result = subprocess.run(
            [*split_memsearch_cmd(memsearch_cmd), "config", "get", "plugins.opencode.summarize.enabled"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip().lower() != "false"
    except Exception:
        return True


def ensure_isolated_config(project_dir: str | os.PathLike[str] | None = None) -> str:
    """Create isolated config dir without plugins/ to prevent recursion."""
    root = Path.home() / ".codex" / "tmp" / "opencode-memsearch-summarize"
    isolated = root / "opencode"
    isolated.mkdir(parents=True, exist_ok=True)
    for filename in ("config.json", "opencode.json", "opencode.jsonc"):
        stale = isolated / filename
        if stale.is_symlink() or stale.is_file():
            stale.unlink(missing_ok=True)
    cfg = _sanitize_opencode_config(load_opencode_config(project_dir))
    if cfg:
        (isolated / "opencode.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(root)


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
        "2-10 bullet points. Write in third person. Do NOT answer User's question. "
        "Mandatory language rule: write every bullet in the same primary language as the [User] text. "
        "If User mixes languages, use the dominant user-facing language. "
        "Output ONLY bullet points."
    )


def summarize_with_llm(
    turn_text: str,
    small_model: str,
    memsearch_cmd: str | None = None,
    project_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Summarize using configured provider routing."""
    if not get_plugin_summarize_enabled(memsearch_cmd):
        return None

    system_prompt = _load_summarize_prompt("OpenCode", memsearch_cmd)
    full_prompt = f"{system_prompt}\n\nTranscript:\n{turn_text}"

    summarize_provider = get_plugin_summarize_provider(memsearch_cmd)
    if summarize_provider and summarize_provider != "native" and memsearch_cmd:
        try:
            result = subprocess.run(
                [*split_memsearch_cmd(memsearch_cmd), "summarize", "--plugin", "opencode", "--agent-name", "OpenCode"],
                input=turn_text,
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "MEMSEARCH_NO_WATCH": "1"},
            )
            output = result.stdout.strip()
            lines = output.split("\n")
            bullets = [line for line in lines if line.strip().startswith("- ")]
            if bullets:
                return "\n".join(bullets)
            if output:
                return output
        except Exception:
            pass
        return None

    # Native path: summarize using opencode run in isolated env (no plugins -> no recursion).
    isolated_dir = ensure_isolated_config(project_dir)

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
                "OPENCODE_CONFIG": "",
                "OPENCODE_CONFIG_DIR": "",
                "OPENCODE_CONFIG_CONTENT": "",
                "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
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


def wake_maintenance(project_dir: str, memsearch_dir: Path) -> None:
    """Start maintenance in a hook-disabled child environment."""
    runner = Path(__file__).resolve().parent / "maintenance-runner.py"
    subprocess.Popen(
        [
            "python3",
            str(runner),
            "--platform",
            "opencode",
            "--project-dir",
            project_dir,
            "--memsearch-dir",
            memsearch_dir.as_posix(),
        ],
        env={**os.environ, "MEMSEARCH_NO_WATCH": "1", "MEMSEARCH_DISABLE": "1"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def process_is_alive(pid: int) -> bool:
    """Return whether a process exists without sending it a signal."""
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


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


def _load_legacy_last_msg_time(project_dir: Path) -> int:
    """Read the pre-sidecar capture checkpoint for upgrade compatibility."""
    # Always reads from project_dir/.memsearch regardless of MEMSEARCH_DIR so
    # existing checkpoints are found after users migrate to a shared storage dir.
    path = project_dir / ".memsearch" / ".last_msg_time"
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0
    return max(value, 0)


def _make_capture_anchor_key(session_id: str, turn_id: str) -> tuple[str, str]:
    return (session_id, turn_id)


def load_capture_anchor_cache(memory_dir: Path) -> set[tuple[str, str]]:
    if not memory_dir.is_dir():
        return set()

    anchor_cache: set[tuple[str, str]] = set()
    for path in memory_dir.iterdir():
        if not path.name.endswith(".md"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for session_id, turn_id in _ANCHOR_RE.findall(text):
            anchor_cache.add(_make_capture_anchor_key(session_id, turn_id))

    return anchor_cache


def write_capture(
    memory_dir: Path,
    turn_text: str,
    session_id: str,
    turn_id: str,
    db_path: str = "",
    anchor_cache: set[tuple[str, str]] | None = None,
) -> Path:
    """Write a captured turn to the daily memory file."""
    memory_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M")
    memory_file = memory_dir / f"{today}.md"

    if not memory_file.exists():
        memory_file.write_text(f"# {today}\n\n## Session {now}\n\n", encoding="utf-8")

    anchor = f"<!-- session:{session_id} turn:{turn_id} db:{db_path} -->\n" if session_id else ""
    entry = f"### {now}\n{anchor}{turn_text}\n\n"

    with memory_file.open("a", encoding="utf-8") as f:
        f.write(entry)

    if session_id and anchor_cache is not None:
        anchor_cache.add(_make_capture_anchor_key(session_id, turn_id))

    return memory_file


def capture_exists(memory_dir: Path, session_id: str, turn_id: str) -> bool:
    """Check whether a turn anchor was already written to memory markdown."""
    if not memory_dir.is_dir():
        return False

    anchor = f"<!-- session:{session_id} turn:{turn_id} "
    for path in memory_dir.iterdir():
        if not path.name.endswith(".md"):
            continue
        try:
            with path.open(encoding="utf-8") as handle:
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
    memory_dir: Path,
    session_id: str,
    small_model: str,
    memsearch_cmd: str,
    db_path: str,
    tail_turn_cache: dict[str, TailTurnObservation] | None = None,
    project_dir: str | os.PathLike[str] = "",
) -> bool:
    """Capture all newly completed turns for a single session."""
    state = load_turn_state(turn_db, session_id)
    captured_any = False
    next_turn_index = get_next_turn_index(turn_db, session_id)
    if tail_turn_cache is None:
        tail_turn_cache = {}

    after_time = state.last_completed_time if state.last_completed_time > 0 else None
    if after_time is None:
        legacy_after_time = _load_legacy_last_msg_time(Path(project_dir).resolve())
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
            if not get_plugin_summarize_enabled(memsearch_cmd):
                continue
            summary = summarize_with_llm(turn_text, small_model, memsearch_cmd, project_dir)
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
    parser.add_argument(
        "--memsearch-dir",
        default=None,
        help="MemSearch storage dir (defaults to <project_dir>/.memsearch)",
    )
    parser.add_argument("--poll-interval", type=int, default=10, help="Poll interval in seconds")
    parser.add_argument("--parent-pid", type=int, default=0, help="Exit when this parent process is gone")
    args = parser.parse_args()

    _db_path = get_db_path()
    if not _db_path.exists():
        sys.stderr.write(f"OpenCode database not found at {_db_path}\n")
        sys.exit(1)
    db_path = _db_path.as_posix()

    # Storage keys off memsearch_dir (honoring MEMSEARCH_DIR global scope);
    # OpenCode session/config lookups still key off the real project_dir.
    memsearch_dir = (
        Path(os.path.abspath(args.memsearch_dir)) if args.memsearch_dir else Path(args.project_dir) / ".memsearch"
    )
    memory_dir = memsearch_dir / "memory"
    # PID file is per-project so each project has its own daemon even when sharing memsearch_dir.
    pid_file = Path(args.project_dir) / ".memsearch" / ".capture.pid"

    memsearch_dir.mkdir(parents=True, exist_ok=True)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    def cleanup(signum=None, frame=None) -> None:
        with contextlib.suppress(OSError):
            pid_file.unlink()
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    small_model = get_small_model(args.project_dir)
    turn_db = open_turn_db(memsearch_dir)
    tail_turn_cache: dict[str, TailTurnObservation] = {}

    while True:
        if args.parent_pid and not process_is_alive(args.parent_pid):
            cleanup()

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
                        args.project_dir,
                    )
                    or any_new
                )

            if any_new:
                subprocess.Popen(
                    [
                        *split_memsearch_cmd(args.memsearch_cmd),
                        "index",
                        memory_dir.as_posix(),
                        "--collection",
                        args.collection_name,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                wake_maintenance(args.project_dir, memsearch_dir)
        except Exception:
            pass
        finally:
            if conn is not None:
                conn.close()

        if args.parent_pid and not process_is_alive(args.parent_pid):
            cleanup()
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
