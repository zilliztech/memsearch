"""Read OpenCode V2 projections without modifying the host database."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class TranscriptError(ValueError):
    """An actionable failure to read the referenced conversation."""


def get_db_path(explicit: str | None = None, channel: str = "latest") -> str:
    if explicit:
        return str(Path(explicit).expanduser().resolve()) if explicit != ":memory:" else explicit
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "opencode"
    filename = os.environ.get("OPENCODE_DB")
    if filename is None:
        shared = channel in {"latest", "dev", "beta", "next", "prod"}
        shared = shared or os.environ.get("OPENCODE_DISABLE_CHANNEL_DB", "").lower() in {"1", "true"}
        filename = "opencode.db" if shared else f"opencode-{re.sub(r'[^a-zA-Z0-9._-]', '-', channel)}.db"
    if filename == ":memory:":
        return filename
    return str((data / filename).expanduser().resolve())


def open_source(path: str) -> sqlite3.Connection:
    if path == ":memory:":
        raise TranscriptError("In-memory OpenCode databases cannot be read by the transcript helper.")
    file = Path(path).expanduser().resolve()
    if not file.is_file():
        raise TranscriptError(f"OpenCode database not found: {file}. Check the anchor and host data directory.")
    conn = sqlite3.connect(file.as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"session_v2", "session_message"} <= tables:
        conn.close()
        raise TranscriptError(
            "OpenCode V2 session_v2/session_message schema unavailable. V1 users must pin plugin 0.3.17. "
            "For an upgraded host, verify its migration: https://opencode.ai/v2/docs/migrate-v1 . "
            "MemSearch does not migrate databases or rewrite journal anchors."
        )
    required = {
        "session_v2": {
            "id",
            "project_id",
            "directory",
            "workspace_id",
            "parent_id",
            "fork_session_id",
            "fork_boundary",
        },
        "session_message": {"id", "session_id", "type", "seq", "data"},
    }
    for table, columns in required.items():
        if not columns <= {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
            conn.close()
            raise TranscriptError("Unsupported OpenCode V2 projection schema; verify host version and migration.")
    return conn


def project_root(directory: str) -> str:
    """Resolve a checkout, keeping unrelated non-Git directories distinct."""
    path = Path(directory).resolve(strict=True)
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return str(Path(result.stdout.strip()).resolve(strict=True))
    except (OSError, subprocess.SubprocessError):
        pass
    return str(path)


@dataclass(frozen=True)
class Scope:
    root: str
    project_id: str
    workspace_id: str | None = None

    def owns(self, row: sqlite3.Row) -> bool:
        # Host project IDs can change independently of physical ownership.
        if row["workspace_id"] != self.workspace_id:
            return False
        try:
            return project_root(row["directory"]) == str(Path(self.root).resolve(strict=True))
        except (OSError, ValueError):
            return False


def session_row(conn: sqlite3.Connection, session_id: str, scope: Scope) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM session_v2 WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise TranscriptError(
            f"Session {session_id} is unavailable in this V2 database. Check the referenced database/session; "
            "if it predates the upgrade, verify the user-owned OpenCode migration."
        )
    if not scope.owns(row):
        raise TranscriptError("Referenced session is outside the requesting project's checkout/workspace.")
    return row


def session_ids(conn: sqlite3.Connection, scope: Scope) -> list[str]:
    rows = conn.execute(
        "SELECT * FROM session_v2 WHERE workspace_id IS ? AND parent_id IS NULL ORDER BY id",
        (scope.workspace_id,),
    )
    return [row["id"] for row in rows if scope.owns(row)]


@dataclass
class OpenCodeTurn:
    session_id: str
    turn_id: str
    start_seq: int
    end_seq: int
    messages: list[dict] = field(default_factory=list)
    outcome: str | None = None
    followed_by_user: bool = False

    @property
    def status(self) -> str:
        assistants = [m for m in self.messages if m["type"] == "assistant"]
        settled = all(
            m.get("time", {}).get("completed") is not None
            and not m.get("retry")
            and all(
                p.get("state", {}).get("status") in {"completed", "error"}
                for p in m.get("content", [])
                if p.get("type") == "tool"
            )
            for m in assistants
        )
        if self.outcome in {"failed", "interrupted"}:
            return "discarded"
        final = assistants[-1] if assistants else {}
        # A failed final assistant can retain a nominal finish reason. Earlier
        # failed attempts may be followed by a successfully recovered response.
        failed = final.get("error") is not None or final.get("finish") == "error"
        # Officially migrated V2 projections have completed timestamps but no
        # streamed timestamp or idle row. In the pinned V2 runner, visible text
        # starts the step before streamed is persisted, then completion follows.
        # Require that settled projected shape, never just another user message.
        imported = (
            bool(assistants)
            and all(
                m.get("time", {}).get("created") is not None and "streamed" not in m.get("time", {}) for m in assistants
            )
            and any(p.get("type") == "text" and p.get("text", "").strip() for p in final.get("content", []))
        )
        if (
            assistants
            and settled
            and not failed
            and final.get("finish") in {"stop", "length", "content-filter"}
            and (self.outcome == "succeeded" or imported)
        ):
            return "complete"
        if settled and failed and self.outcome == "succeeded":
            return "discarded"
        # A user steer can supersede an earlier intent without a final answer.
        # Only a persisted terminal boundary permits advancing past that intent.
        if self.followed_by_user and self.outcome == "succeeded" and settled:
            return "discarded"
        return "pending"

    def render(self, max_chars: int = 24000) -> str:
        lines = []
        for message in self.messages:
            if message["type"] == "user":
                text = str(message.get("text", ""))
                label = "User"
            elif message["type"] == "assistant":
                text = "\n".join(str(p.get("text", "")) for p in message.get("content", []) if p.get("type") == "text")
                label = "Assistant"
            else:
                continue
            if text.strip():
                if len(text) > 6000:
                    text = "...(truncated to tail)\n" + text[-6000:]
                lines.append(f"[{label}]: {text.strip()}")
        rendered = "\n\n".join(lines)
        if len(rendered) > max_chars:
            # Retain the initial request as well as final conclusions.
            rendered = rendered[:4000] + "\n...(truncated)\n" + rendered[-(max_chars - 4025) :]
        return rendered


def build_turns(conn: sqlite3.Connection, session_id: str, after_seq: int = -1) -> list[OpenCodeTurn]:
    # A moved session's earlier payload belongs to another location. Establish
    # the boundary from metadata before selecting any message content.
    switched = conn.execute(
        "SELECT max(seq) FROM session_message WHERE session_id = ? AND type = 'location-switched'",
        (session_id,),
    ).fetchone()[0]
    after_seq = max(after_seq, switched if switched is not None else -1)
    rows = conn.execute(
        "SELECT id, type, seq, data FROM session_message WHERE session_id = ? AND seq > ? ORDER BY seq",
        (session_id, after_seq),
    )
    turns: list[OpenCodeTurn] = []
    current = None
    busy: list[OpenCodeTurn] = []
    for row in rows:
        try:
            data = json.loads(row["data"])
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except (ValueError, TypeError) as exc:
            raise TranscriptError(f"Invalid V2 message data for {row['id']}; capture remains pending.") from exc
        message = {**data, "id": row["id"], "type": row["type"]}
        if row["type"] == "user":
            if current:
                current.followed_by_user = True
                if current.outcome is None and current.status == "complete":
                    # A later V2 run's idle outcome must not overwrite the
                    # terminal state of already-settled imported history.
                    busy.remove(current)
            current = OpenCodeTurn(session_id, row["id"], row["seq"], row["seq"], [message])
            turns.append(current)
            busy.append(current)
        elif row["type"] == "assistant" and current:
            current.messages.append(message)
            current.end_seq = row["seq"]
        elif row["type"] == "idle":
            for turn in busy:
                turn.outcome = data.get("outcome")
            if current:
                current.end_seq = row["seq"]
            busy = []
            current = None
        elif row["type"] == "location-switched":
            # Do not attribute the previous location's conversation to its new owner.
            turns = []
            busy = []
            current = None
    return turns


def find_turn_index(turns: list[OpenCodeTurn], target: str) -> int:
    exact = [i for i, turn in enumerate(turns) if turn.turn_id == target]
    matches = exact or [i for i, turn in enumerate(turns) if turn.turn_id.startswith(target)]
    if len(matches) > 1:
        raise TranscriptError("Ambiguous turn prefix; use the complete turn ID from the journal anchor.")
    if not matches:
        raise TranscriptError(f"Turn not found: {target}. Verify this anchor in the selected V2 database.")
    return matches[0]


if __name__ == "__main__":
    import argparse
    import contextlib
    import sys

    parser = argparse.ArgumentParser(description="Validate exact V2 session ownership without reading dialogue.")
    parser.add_argument("session_id")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-id")
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    try:
        with contextlib.closing(open_source(args.db)) as conn:
            session_row(conn, args.session_id, Scope(args.project_dir, args.project_id, args.workspace_id))
    except (TranscriptError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"Session ownership unavailable: {exc}\n")
        raise SystemExit(1) from exc
