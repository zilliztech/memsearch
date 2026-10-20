#!/usr/bin/env python3
"""Finite V2 capture/maintenance batch. Native inference is requested over stdio."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import signal
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from opencode_turns import Scope, build_turns, get_db_path, open_source, session_ids, session_row

UNAVAILABLE = (
    "- Memory summary unavailable: summarizer failed or returned no usable output; "
    "transcript content was omitted. Use the transcript anchor for details."
)
MAX_SUMMARY = 16000


@contextlib.contextmanager
def cli_lock():
    """Serialize plugin index/search/expand across checkouts sharing HOME.

    Always acquire after the project capture lock. Inference and optional
    maintenance never hold this lock, even when they use the memsearch CLI.
    """
    state = Path.home() / ".memsearch"
    state.mkdir(parents=True, exist_ok=True)
    with (state / ".opencode-cli.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


class Cancelled(BaseException):
    """Host shutdown is retryable, unlike a completed summarizer failure."""


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def native_request(prompt: str, model: str = "", task: str = "summarize") -> str:
    emit({"type": "generate", "prompt": prompt, "model": model, "task": task})
    line = sys.stdin.readline()
    if not line:
        raise Cancelled()
    response = json.loads(line)
    if response.get("cancelled"):
        raise Cancelled()
    if response.get("error"):
        raise RuntimeError("Native generation unavailable")
    return str(response.get("text", ""))


def maintenance_module():
    path = Path(__file__).with_name("maintenance-runner.py")
    spec = importlib.util.spec_from_file_location("opencode_maintenance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summarize(turn, cfg, command, root: str, native=native_request) -> str:
    """Retain shared routing and output validation; never return raw dialogue."""
    try:
        settings = cfg.plugins.opencode.summarize
        text = turn.render()
        provider = (settings.provider or "native").strip()
        if provider and provider != "native":
            result = subprocess.run(
                [*command, "summarize", "--plugin", "opencode", "--agent-name", "OpenCode"],
                input=text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=30,
                cwd=root,
                env={**os.environ, "MEMSEARCH_NO_WATCH": "1"},
                check=False,
            )
            output = result.stdout.strip() if result.returncode == 0 else ""
            bullets = [line for line in output.splitlines() if line.strip().startswith("- ")]
            if bullets:
                output = "\n".join(bullets)
        else:
            from memsearch.cli import _load_plugin_summarize_prompt

            custom = Path(cfg.prompts.summarize).expanduser() if cfg.prompts.summarize else None
            builtin = Path(__file__).resolve().parent.parent / "prompts/summarize.txt"
            if custom and custom.is_file():
                prompt = custom.read_text(encoding="utf-8")
            elif builtin.is_file():
                prompt = builtin.read_text(encoding="utf-8")
            else:
                prompt = _load_plugin_summarize_prompt(cfg, "OpenCode")
            prompt = prompt.replace("{{AGENT_NAME}}", "OpenCode")
            output = native(f"{prompt}\n\nTranscript:\n{text}", settings.model.strip(), "summarize")
            output = "\n".join(line for line in output.splitlines() if line.strip().startswith("- "))
        output = output.strip()
        return output if output and len(output) <= MAX_SUMMARY else UNAVAILABLE
    except Exception:
        return UNAVAILABLE


class CaptureStore:
    """Derived progress only. Host rows and existing journals are never reset."""

    def __init__(self, root: str):
        self.root = Path(root)
        self.memory = self.root / ".memsearch/memory"
        state = self.root / ".memsearch"
        state.mkdir(parents=True, exist_ok=True)
        self.lock = (state / ".capture-v2.lock").open("a")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.db = sqlite3.connect(state / "opencode-turns.db", timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS v2_sources (source TEXT PRIMARY KEY, index_dirty INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS v2_sessions (
                source TEXT NOT NULL, session_id TEXT NOT NULL, cursor_seq INTEGER NOT NULL DEFAULT -1,
                PRIMARY KEY(source, session_id));
            CREATE TABLE IF NOT EXISTS v2_pending (
                source TEXT NOT NULL, session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                end_seq INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                journal TEXT, offset INTEGER, prefix_hash TEXT, entry BLOB,
                PRIMARY KEY(source, session_id, turn_id));
        """)

    def close(self):
        self.db.close()
        self.lock.close()

    def cursor(self, source, session_id):
        row = self.db.execute(
            "SELECT cursor_seq FROM v2_sessions WHERE source=? AND session_id=?", (source, session_id)
        ).fetchone()
        return row[0] if row else -1

    def advance(self, source, session_id, seq):
        self.db.execute(
            """INSERT INTO v2_sessions VALUES(?,?,?)
            ON CONFLICT(source,session_id) DO UPDATE SET cursor_seq=excluded.cursor_seq""",
            (source, session_id, seq),
        )
        self.db.commit()

    def anchored(self, session_id, turn_id):
        needle = f"<!-- session:{session_id} turn:{turn_id} "
        return any(needle in p.read_text(encoding="utf-8") for p in self.memory.glob("????-??-??.md"))

    def pending(self, source, turn):
        return self.db.execute(
            "SELECT * FROM v2_pending WHERE source=? AND session_id=? AND turn_id=?",
            (source, turn.session_id, turn.turn_id),
        ).fetchone()

    def prepare(self, source, turn):
        fingerprint = hashlib.sha256(json.dumps(turn.messages, sort_keys=True).encode()).hexdigest()
        self.db.execute(
            "INSERT OR IGNORE INTO v2_pending(source,session_id,turn_id,end_seq,fingerprint) VALUES(?,?,?,?,?)",
            (source, turn.session_id, turn.turn_id, turn.end_seq, fingerprint),
        )
        self.db.commit()
        row = self.pending(source, turn)
        if row["fingerprint"] != fingerprint or row["end_seq"] != turn.end_seq:
            raise RuntimeError("Pending turn changed in OpenCode; capture stopped without modifying its journal.")
        return row

    def stage_entry(self, source, turn, summary, db_path):
        self.memory.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        journal = self.memory / f"{now:%Y-%m-%d}.md"
        previous = journal.read_bytes() if journal.exists() else b""
        header = f"# {now:%Y-%m-%d}\n\n## Session {now:%H:%M}\n\n" if not previous else ""
        anchor = f"<!-- session:{turn.session_id} turn:{turn.turn_id} db:{db_path} -->"
        entry = (header + f"### {now:%H:%M}\n{anchor}\n{summary}\n\n").encode()
        self.db.execute(
            """UPDATE v2_pending SET journal=?,offset=?,prefix_hash=?,entry=?
            WHERE source=? AND session_id=? AND turn_id=?""",
            (
                str(journal),
                len(previous),
                hashlib.sha256(previous).hexdigest(),
                entry,
                source,
                turn.session_id,
                turn.turn_id,
            ),
        )
        self.db.commit()

    def append_prepared(self, row):
        """Recover only our own exact append, including a partial write."""
        journal = Path(row["journal"])
        data = journal.read_bytes() if journal.exists() else b""
        offset, entry = row["offset"], bytes(row["entry"])
        if len(data) < offset or hashlib.sha256(data[:offset]).hexdigest() != row["prefix_hash"]:
            raise RuntimeError("Journal changed before the pending append; automatic repair stopped.")
        tail = data[offset:]
        if tail.startswith(entry):
            return
        if not entry.startswith(tail):
            raise RuntimeError("Journal changed during the pending append; automatic repair stopped.")
        with journal.open("ab") as handle:
            handle.write(entry[len(tail) :])
            handle.flush()
            os.fsync(handle.fileno())
        # Ensure the new journal's directory entry survives an abrupt process exit.
        fd = os.open(journal.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def commit(self, source, turn):
        with self.db:
            self.db.execute(
                """INSERT INTO v2_sessions VALUES(?,?,?) ON CONFLICT(source,session_id)
                DO UPDATE SET cursor_seq=excluded.cursor_seq""",
                (source, turn.session_id, turn.end_seq),
            )
            self.db.execute(
                "DELETE FROM v2_pending WHERE source=? AND session_id=? AND turn_id=?",
                (source, turn.session_id, turn.turn_id),
            )
            self.db.execute("UPDATE v2_sources SET index_dirty=1 WHERE source=?", (source,))


def source_key(db_path, scope):
    return json.dumps([db_path, str(Path(scope.root).resolve()), scope.workspace_id])


def capture_batch(conn, store, scope, db_path, summarizer, *, enabled=True, initialize=False):
    source = source_key(db_path, scope)
    fresh = store.db.execute("SELECT 1 FROM v2_sources WHERE source=?", (source,)).fetchone() is None
    if fresh and initialize:
        # Commit the baseline and source marker together. An interrupted startup
        # cannot turn a partially baselined history into a bulk replay.
        with store.db:
            for session_id in session_ids(conn, scope):
                session_row(conn, session_id, scope)
                cursor = -1
                for turn in build_turns(conn, session_id):
                    if turn.status == "pending":
                        break
                    cursor = turn.end_seq
                store.db.execute("INSERT OR REPLACE INTO v2_sessions VALUES(?,?,?)", (source, session_id, cursor))
            store.db.execute("INSERT INTO v2_sources(source) VALUES(?)", (source,))
        return source, 0
    if initialize:
        # Startup re-indexes existing Markdown too, including user edits.
        with store.db:
            store.db.execute("UPDATE v2_sources SET index_dirty=1 WHERE source=?", (source,))
        return source, 0
    store.db.execute("INSERT OR IGNORE INTO v2_sources(source) VALUES(?)", (source,))
    store.db.commit()
    captured = 0
    for session_id in session_ids(conn, scope):
        row = session_row(conn, session_id, scope)
        cursor = store.cursor(source, session_id)
        # Forked projections copy settled history at its original sequence numbers.
        if row["fork_session_id"] and row["fork_boundary"]:
            boundary = json.loads(row["fork_boundary"])
            original = conn.execute(
                "SELECT seq FROM session_message WHERE session_id=? AND id=?",
                (row["fork_session_id"], boundary.get("messageID")),
            ).fetchone()
            if original is not None:
                if boundary.get("type") == "before":
                    copied = conn.execute(
                        "SELECT max(seq) FROM session_message WHERE session_id=? AND seq<?",
                        (row["fork_session_id"], original[0]),
                    ).fetchone()[0]
                    cutoff = copied if copied is not None else -1
                else:
                    cutoff = original[0]
            else:
                # v2.0.32 copies fork projections with IDs <fork-event-message>_<seq>.
                # This remains inspectable even after the parent is deleted.
                copied = [
                    r["seq"]
                    for r in conn.execute("SELECT id,seq FROM session_message WHERE session_id=?", (session_id,))
                    if r["id"].endswith(f"_{r['seq']}")
                ]
                cutoff = max(copied, default=-1)
            cursor = max(cursor, cutoff)
        turns = build_turns(conn, session_id, cursor)
        for turn in turns:
            if turn.status == "pending":
                break
            if turn.status == "discarded":
                store.advance(source, session_id, turn.end_seq)
                continue
            pending = store.pending(source, turn)
            if pending is None and store.anchored(session_id, turn.turn_id):
                store.commit(source, turn)
                continue
            if not enabled:
                break
            pending = store.prepare(source, turn)
            if pending["entry"] is None:
                summary = summarizer(turn)
                store.stage_entry(source, turn, summary, db_path)
                pending = store.pending(source, turn)
            # Inference can outlive a session move or a projection update.
            session_row(conn, session_id, scope)
            latest = next((t for t in build_turns(conn, session_id, cursor) if t.turn_id == turn.turn_id), None)
            if latest is None or latest.status != "complete":
                raise RuntimeError("Turn changed while summarizing; capture remains pending.")
            store.prepare(source, latest)
            store.append_prepared(pending)
            store.commit(source, turn)
            captured += 1
    return source, captured


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-id")
    parser.add_argument("--db", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--command", required=True, help="JSON argv for the memsearch executable")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--default-onnx", action="store_true")
    parser.add_argument("--maintenance", action="store_true")
    parser.add_argument("--query", help="JSON search/expand argv, serialized with capture/index")
    parser.add_argument("--session-id", help="Requesting session for a serialized recall query")
    args = parser.parse_args()

    def cancel(*_):
        raise Cancelled()

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    try:
        os.chdir(args.project_dir)
        command = json.loads(args.command)
        scope = Scope(args.project_dir, args.project_id, args.workspace_id)
        db_path = get_db_path(args.db)
        if args.query:
            query = json.loads(args.query)
            if not args.session_id or not query or query[0] not in {"search", "expand"}:
                raise ValueError("A recall query requires its requesting session and search/expand argv.")
            # Recheck scope after waiting for capture, before any CLI access.
            with contextlib.closing(CaptureStore(args.project_dir)):
                with contextlib.closing(open_source(db_path)) as conn:
                    session_row(conn, args.session_id, scope)
                with cli_lock():
                    return subprocess.run([*command, *query], timeout=110, check=False).returncode
        runner = maintenance_module()
        runner.ensure_memsearch_importable(Path(__file__).resolve())
        from memsearch.config import resolve_config

        cfg = resolve_config()
        if args.maintenance:
            # Optional inference never holds the capture lock or the recall
            # barrier. Shared per-task locks/due-state serialize maintenance.
            runner.run_maintenance(
                "opencode",
                Path(scope.root),
                str(Path(scope.root) / ".memsearch"),
                cfg,
                native_runner=lambda ctx, prompt: native_request(prompt, ctx.task_config.model, ctx.task),
            )
            emit({"type": "done", "captured": 0})
            return 0
        if not Path(db_path).exists() and args.initialize:
            emit({"type": "done", "captured": 0})
            return 0
        with contextlib.closing(CaptureStore(args.project_dir)) as store:
            with contextlib.closing(open_source(db_path)) as conn:
                source, count = capture_batch(
                    conn,
                    store,
                    scope,
                    db_path,
                    lambda turn: summarize(turn, cfg, command, scope.root),
                    enabled=cfg.plugins.opencode.summarize.enabled,
                    initialize=args.initialize,
                )
            if args.initialize:
                # Baseline before enabling prompt hooks; recovery/index/maintenance
                # run in the next finite batch and cannot undo this boundary.
                emit({"type": "done", "captured": 0})
                return 0
            dirty = store.db.execute("SELECT index_dirty FROM v2_sources WHERE source=?", (source,)).fetchone()[0]
            if dirty and store.memory.exists():
                with cli_lock():
                    result = subprocess.run(
                        [
                            *command,
                            "index",
                            str(store.memory),
                            "--default-collection",
                            args.collection,
                            *(["--provider", "onnx"] if args.default_onnx else []),
                        ],
                        capture_output=True,
                        timeout=120,
                        check=False,
                    )
                if result.returncode != 0:
                    raise RuntimeError("Memory indexing failed; the journal is saved and indexing will retry.")
                with store.db:
                    store.db.execute("UPDATE v2_sources SET index_dirty=0 WHERE source=?", (source,))
        emit({"type": "done", "captured": count})
        return 0
    except Cancelled:
        return 75
    except Exception as exc:
        # Do not serialize provider errors, credentials, prompts, or subprocess output.
        emit(
            {
                "type": "error",
                "message": f"Capture pending ({type(exc).__name__}); verify database/scope, CLI and index configuration.",
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
