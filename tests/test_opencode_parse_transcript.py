from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path


def _make_opencode_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE part (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _insert_message(
    conn: sqlite3.Connection,
    message_id: str,
    session_id: str,
    time_created: int,
    role: str,
    text: str,
    parent_id: str | None = None,
    finish: str = "stop",
) -> None:
    payload: dict[str, object] = {
        "role": role,
        "time": {"created": time_created},
        "finish": finish,
    }
    if parent_id:
        payload["parentID"] = parent_id
    conn.execute(
        """
        INSERT INTO message (id, session_id, time_created, time_updated, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        (message_id, session_id, time_created, time_created, json.dumps(payload)),
    )
    conn.execute(
        """
        INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            f"{message_id}-p1",
            message_id,
            session_id,
            time_created,
            time_created,
            json.dumps({"type": "text", "text": text}),
        ),
    )


def _load_parse_transcript_module():
    script_dir = Path("plugins/opencode/scripts").resolve()
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    script = script_dir / "parse-transcript.py"
    spec = importlib.util.spec_from_file_location("opencode_parse_transcript", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_transcript_help_describes_project_dir_as_non_source_of_truth() -> None:
    script = Path("plugins/opencode/scripts/parse-transcript.py").resolve()

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    normalized_stdout = " ".join(result.stdout.split())

    assert result.returncode == 0
    assert "unused for transcript reads" in normalized_stdout
    assert "sidecar cache" not in normalized_stdout


def test_parse_transcript_reads_from_opencode_sqlite_without_sidecar(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "opencode.db"
    conn = _make_opencode_db(db_path)
    session_id = "ses_sqlite_only"

    _insert_message(conn, "u1", session_id, 100, "user", text="Question")
    _insert_message(conn, "a1", session_id, 110, "assistant", text="Answer", parent_id="u1")
    conn.commit()
    conn.close()

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    module = _load_parse_transcript_module()
    monkeypatch.setattr(module, "get_db_path", lambda: str(db_path))

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        module.parse_session(session_id, limit=1)

    output = stdout.getvalue()

    assert "[Human]: Question" in output
    assert "[Assistant]: Answer" in output
