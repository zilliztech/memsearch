"""Synthetic projection fixtures for the pinned OpenCode 2.0.32 contract."""

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/opencode/scripts"
sys.path.insert(0, str(SCRIPTS))
import opencode_turns as reader  # noqa: E402


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


capture = load("opencode_capture_v2", "capture.py")
parser = load("opencode_parse_v2", "parse-transcript.py")


class Fixture:
    def __init__(self, root, path=None):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = path or root / "host.db"
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE session_v2 (
                id TEXT PRIMARY KEY, project_id TEXT, directory TEXT, workspace_id TEXT,
                parent_id TEXT, fork_session_id TEXT, fork_boundary TEXT, time_idle INTEGER, idle_outcome TEXT);
            CREATE TABLE session_message (
                id TEXT, session_id TEXT, type TEXT, seq INTEGER, data TEXT,
                time_created INTEGER, time_updated INTEGER,
                PRIMARY KEY(session_id,id), UNIQUE(session_id,seq));
        """)
        self.scope = reader.Scope(str(root.resolve()), "project")
        self.session("session")

    def session(
        self, name, *, directory=None, project="project", workspace=None, parent=None, fork=None, boundary=None
    ):
        self.conn.execute(
            "INSERT INTO session_v2 VALUES(?,?,?,?,?,?,?,NULL,NULL)",
            (
                name,
                project,
                str(directory or self.root),
                workspace,
                parent,
                fork,
                json.dumps(boundary) if boundary else None,
            ),
        )
        self.conn.commit()

    def row(self, seq, kind, data, *, session="session", id=None):
        id = id or f"msg{seq}"
        self.conn.execute(
            "INSERT INTO session_message VALUES(?,?,?,?,?,?,?)",
            (id, session, kind, seq, json.dumps(data), 100000 - seq, 100000 - seq),
        )
        self.conn.commit()
        return id

    def user(self, seq=2, *, session="session", id=None, text="synthetic user marker"):
        return self.row(seq, "user", {"text": text}, session=session, id=id)

    def assistant(
        self,
        seq=9,
        *,
        session="session",
        completed=True,
        tools=None,
        finish="stop",
        text="synthetic answer",
        retry=None,
    ):
        content = [{"type": "text", "text": text}] if text else []
        content += [
            {"type": "tool", "state": {"status": status, "output": "RAW_TOOL_SECRET"}} for status in tools or []
        ]
        data = {"content": content, "finish": finish, "time": {"streamed": 3}, "retry": retry}
        if completed:
            data["time"]["completed"] = 4
        return self.row(seq, "assistant", data, session=session)

    def idle(self, seq=15, *, session="session", outcome="succeeded"):
        self.row(seq, "idle", {"outcome": outcome}, session=session)

    def turn(self, base=0, *, session="session", text="synthetic user marker"):
        user = self.user(base + 2, session=session, text=text)
        self.assistant(base + 9, session=session)
        self.idle(base + 15, session=session)
        return user

    def batch(self, store, summary=lambda _: "- Safe summary.", **options):
        return capture.capture_batch(self.conn, store, self.scope, str(self.path), summary, **options)

    def journals(self):
        return "".join(p.read_text() for p in (self.root / ".memsearch/memory").glob("*.md"))
