from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from contextlib import suppress
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "plugins" / "opencode" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

CAPTURE_DAEMON_PATH = SCRIPT_DIR / "capture-daemon.py"
CAPTURE_DAEMON_SPEC = importlib.util.spec_from_file_location(
    "capture_daemon",
    CAPTURE_DAEMON_PATH,
)
assert CAPTURE_DAEMON_SPEC is not None
assert CAPTURE_DAEMON_SPEC.loader is not None
capture_daemon = importlib.util.module_from_spec(CAPTURE_DAEMON_SPEC)
CAPTURE_DAEMON_SPEC.loader.exec_module(capture_daemon)

from opencode_turns import (  # noqa: E402
    OpenCodeTurn,
    TurnState,
    build_turns,
    get_turn_db_path,
    load_session_turn_rows,
    load_turn_state,
    open_turn_db,
    save_turn,
    save_turn_state,
)


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
    parent_id: str | None = None,
    finish: str = "stop",
    text: str = "",
    tool_output: str | None = None,
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

    part_id = f"{message_id}-p1"
    if text:
        conn.execute(
            """
            INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                part_id,
                message_id,
                session_id,
                time_created,
                time_created,
                json.dumps({"type": "text", "text": text}),
            ),
        )

    if tool_output is not None:
        conn.execute(
            """
            INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"{message_id}-tool",
                message_id,
                session_id,
                time_created,
                time_created,
                json.dumps(
                    {
                        "type": "tool",
                        "tool": "Bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "ls"},
                            "output": tool_output,
                        },
                    }
                ),
            ),
        )


def test_build_turns_groups_multi_message_assistant_turns(tmp_path: Path) -> None:
    db_path = tmp_path / "opencode.db"
    conn = _make_opencode_db(db_path)
    session_id = "ses_test"

    _insert_message(conn, "u1", session_id, 100, "user", text="Plan the change")
    _insert_message(conn, "a1", session_id, 110, "assistant", parent_id="u1", finish="tool-calls", text="Checking")
    _insert_message(
        conn,
        "a2",
        session_id,
        120,
        "assistant",
        parent_id="u1",
        finish="stop",
        text="Done",
        tool_output="output.txt",
    )
    _insert_message(conn, "u2", session_id, 130, "user", text="Thanks")
    _insert_message(conn, "a3", session_id, 140, "assistant", parent_id="u2", finish="stop", text="You're welcome")
    conn.commit()

    turns = build_turns(conn, session_id)

    assert len(turns) == 2
    assert turns[0].turn_id == "u1"
    assert turns[0].assistant_message_count == 2
    assert turns[0].complete is True
    assert "Plan the change" in turns[0].render()
    assert "[Tool: Bash" in turns[0].render()
    assert turns[1].turn_id == "u2"
    assert turns[1].complete is True

    conn.close()


def test_build_turns_keeps_assistant_descendants_in_same_turn(tmp_path: Path) -> None:
    db_path = tmp_path / "opencode.db"
    conn = _make_opencode_db(db_path)
    session_id = "ses_descendants"

    _insert_message(conn, "u1", session_id, 100, "user", text="Investigate the failure")
    _insert_message(
        conn,
        "a1",
        session_id,
        110,
        "assistant",
        parent_id="u1",
        finish="tool-calls",
        text="Running checks",
    )
    _insert_message(
        conn,
        "a2",
        session_id,
        120,
        "assistant",
        parent_id="a1",
        finish="stop",
        text="Found the root cause",
    )
    _insert_message(conn, "u2", session_id, 130, "user", text="Apply the fix")
    conn.commit()

    turns = build_turns(conn, session_id)

    assert len(turns) == 2
    assert turns[0].turn_id == "u1"
    assert turns[0].assistant_message_count == 2
    assert turns[0].complete is True
    assert [message.id for message in turns[0].messages] == ["u1", "a1", "a2"]

    conn.close()


def test_build_turns_keeps_descendants_through_textless_assistant_nodes(tmp_path: Path) -> None:
    db_path = tmp_path / "opencode.db"
    conn = _make_opencode_db(db_path)
    session_id = "ses_textless_descendants"

    _insert_message(conn, "u1", session_id, 100, "user", text="Investigate the failure")
    _insert_message(conn, "a1", session_id, 110, "assistant", parent_id="u1", finish="tool-calls")
    _insert_message(
        conn,
        "a2",
        session_id,
        120,
        "assistant",
        parent_id="a1",
        finish="stop",
        text="Found the root cause",
    )
    _insert_message(conn, "u2", session_id, 130, "user", text="Apply the fix")
    conn.commit()

    turns = build_turns(conn, session_id)

    assert len(turns) == 2
    assert turns[0].turn_id == "u1"
    assert turns[0].assistant_message_count == 1
    assert turns[0].complete is True
    assert [message.id for message in turns[0].messages] == ["u1", "a2"]
    assert "Found the root cause" in turns[0].render()

    conn.close()


def test_turn_sidecar_persists_state_and_turns(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    turn_db = open_turn_db(str(project_dir))
    turn = OpenCodeTurn(
        session_id="ses_1",
        turn_id="u1",
        turn_index=1,
        start_time=100,
        end_time=150,
        first_message_id="u1",
        last_message_id="a1",
        message_count=2,
        assistant_message_count=1,
        complete=True,
        messages=[],
    )

    save_turn(turn_db, turn)
    save_turn_state(
        turn_db,
        TurnState(
            session_id="ses_1",
            last_completed_time=150,
            last_completed_message_id="a1",
            last_completed_turn_id="u1",
        ),
    )

    rows = load_session_turn_rows(turn_db, "ses_1")
    state = load_turn_state(turn_db, "ses_1")

    assert get_turn_db_path(str(project_dir)).endswith(".memsearch/opencode-turns.db")
    assert len(rows) == 1
    assert rows[0]["turn_id"] == "u1"
    assert state.last_completed_turn_id == "u1"
    assert state.last_completed_message_id == "a1"

    turn_db.close()


def test_capture_session_turns_keeps_monotonic_turn_index_across_batches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "opencode.db"
    conn = _make_opencode_db(db_path)
    session_id = "ses_capture"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    memory_dir = project_dir / ".memsearch" / "memory"

    monkeypatch.setattr(capture_daemon, "summarize_with_llm", lambda *args, **kwargs: None)
    current_time_ms = {"value": 0}
    monkeypatch.setattr(capture_daemon.time, "time", lambda: current_time_ms["value"] / 1000)

    _insert_message(conn, "u1", session_id, 100, "user", text="Question one")
    _insert_message(conn, "a1", session_id, 110, "assistant", parent_id="u1", finish="stop", text="Answer one")
    conn.commit()

    turn_db = open_turn_db(str(project_dir))
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
    )

    assert load_session_turn_rows(turn_db, session_id) == []

    _insert_message(conn, "u2", session_id, 200, "user", text="Question two")
    _insert_message(conn, "a2", session_id, 210, "assistant", parent_id="u2", finish="stop", text="Answer two")
    conn.commit()

    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
    )

    rows = load_session_turn_rows(turn_db, session_id)
    assert [(row["turn_id"], row["turn_index"]) for row in rows] == [("u1", 1)]

    _insert_message(conn, "u3", session_id, 300, "user", text="Question three")
    conn.commit()

    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
    )

    rows = load_session_turn_rows(turn_db, session_id)

    assert [(row["turn_id"], row["turn_index"]) for row in rows] == [("u1", 1), ("u2", 2)]

    turn_db.close()
    conn.close()


def test_capture_session_turns_is_idempotent_after_partial_state_save_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "opencode.db"
    conn = _make_opencode_db(db_path)
    session_id = "ses_crash"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    memory_dir = project_dir / ".memsearch" / "memory"

    _insert_message(conn, "u1", session_id, 100, "user", text="Question")
    _insert_message(conn, "a1", session_id, 110, "assistant", parent_id="u1", finish="stop", text="Answer")
    _insert_message(conn, "u2", session_id, 200, "user", text="Follow-up")
    conn.commit()

    monkeypatch.setattr(capture_daemon, "summarize_with_llm", lambda *args, **kwargs: None)

    original_save_turn_state = capture_daemon.save_turn_state
    failed_once = {"value": False}

    def flaky_save_turn_state(*args, **kwargs):
        if not failed_once["value"]:
            failed_once["value"] = True
            raise RuntimeError("simulated crash before cursor persisted")
        return original_save_turn_state(*args, **kwargs)

    turn_db = open_turn_db(str(project_dir))
    monkeypatch.setattr(capture_daemon, "save_turn_state", flaky_save_turn_state)

    with suppress(RuntimeError):
        capture_daemon.capture_session_turns(
            conn,
            turn_db,
            str(memory_dir),
            session_id,
            "",
            "memsearch",
            str(db_path),
        )

    monkeypatch.setattr(capture_daemon, "save_turn_state", original_save_turn_state)
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
    )

    files = sorted(memory_dir.glob("*.md"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert content.count(f"<!-- session:{session_id} turn:u1 db:{db_path} -->") == 1

    state = load_turn_state(turn_db, session_id)
    assert state.last_completed_turn_id == "u1"

    turn_db.close()
    conn.close()


def test_capture_session_turns_waits_for_tail_turn_stability_before_capture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "opencode.db"
    conn = _make_opencode_db(db_path)
    session_id = "ses_tail_wait"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    memory_dir = project_dir / ".memsearch" / "memory"
    tail_cache: dict[str, object] = {}

    monkeypatch.setattr(capture_daemon, "summarize_with_llm", lambda *args, **kwargs: None)
    current_time_ms = {"value": 0}
    monkeypatch.setattr(capture_daemon.time, "time", lambda: current_time_ms["value"] / 1000)

    _insert_message(conn, "u1", session_id, 100, "user", text="Question")
    _insert_message(conn, "a1", session_id, 110, "assistant", parent_id="u1", finish="stop", text="Answer")
    conn.commit()

    turn_db = open_turn_db(str(project_dir))
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
        tail_cache,
    )
    assert load_session_turn_rows(turn_db, session_id) == []

    current_time_ms["value"] = 299_999
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
        tail_cache,
    )
    assert load_session_turn_rows(turn_db, session_id) == []

    current_time_ms["value"] = 300_000
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
        tail_cache,
    )

    rows = load_session_turn_rows(turn_db, session_id)
    assert [(row["turn_id"], row["turn_index"]) for row in rows] == [("u1", 1)]

    turn_db.close()
    conn.close()


def test_capture_session_turns_resets_tail_stability_when_content_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "opencode.db"
    conn = _make_opencode_db(db_path)
    session_id = "ses_tail_reset"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    memory_dir = project_dir / ".memsearch" / "memory"
    tail_cache: dict[str, object] = {}

    monkeypatch.setattr(capture_daemon, "summarize_with_llm", lambda *args, **kwargs: None)
    current_time_ms = {"value": 0}
    monkeypatch.setattr(capture_daemon.time, "time", lambda: current_time_ms["value"] / 1000)

    _insert_message(conn, "u1", session_id, 100, "user", text="Question")
    _insert_message(conn, "a1", session_id, 110, "assistant", parent_id="u1", finish="stop", text="Draft answer")
    conn.commit()

    turn_db = open_turn_db(str(project_dir))
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
        tail_cache,
    )
    assert load_session_turn_rows(turn_db, session_id) == []

    _insert_message(conn, "a2", session_id, 120, "assistant", parent_id="a1", finish="stop", text="Final answer")
    conn.commit()

    current_time_ms["value"] = 250_000
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
        tail_cache,
    )
    assert load_session_turn_rows(turn_db, session_id) == []

    current_time_ms["value"] = 549_999
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
        tail_cache,
    )
    assert load_session_turn_rows(turn_db, session_id) == []

    current_time_ms["value"] = 550_000
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
        tail_cache,
    )

    rows = load_session_turn_rows(turn_db, session_id)
    assert [(row["turn_id"], row["turn_index"]) for row in rows] == [("u1", 1)]

    turn_db.close()
    conn.close()


def test_capture_session_turns_closes_prior_turn_as_soon_as_next_user_arrives(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "opencode.db"
    conn = _make_opencode_db(db_path)
    session_id = "ses_next_user"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    memory_dir = project_dir / ".memsearch" / "memory"
    tail_cache: dict[str, object] = {}

    monkeypatch.setattr(capture_daemon, "summarize_with_llm", lambda *args, **kwargs: None)
    current_time_ms = {"value": 0}
    monkeypatch.setattr(capture_daemon.time, "time", lambda: current_time_ms["value"] / 1000)

    _insert_message(conn, "u1", session_id, 100, "user", text="Question one")
    _insert_message(conn, "a1", session_id, 110, "assistant", parent_id="u1", finish="stop", text="Answer one")
    conn.commit()

    turn_db = open_turn_db(str(project_dir))
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
        tail_cache,
    )
    assert load_session_turn_rows(turn_db, session_id) == []

    _insert_message(conn, "u2", session_id, 200, "user", text="Question two")
    conn.commit()

    current_time_ms["value"] = 1_000
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
        tail_cache,
    )

    rows = load_session_turn_rows(turn_db, session_id)
    assert [(row["turn_id"], row["turn_index"]) for row in rows] == [("u1", 1)]

    turn_db.close()
    conn.close()
def test_capture_session_turns_uses_legacy_last_msg_time_before_sidecar_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "opencode.db"
    conn = _make_opencode_db(db_path)
    session_id = "ses_upgrade"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    memory_dir = project_dir / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)
    legacy_state_file = project_dir / ".memsearch" / ".last_msg_time"
    legacy_state_file.write_text("150", encoding="utf-8")

    today = capture_daemon.datetime.now().strftime("%Y-%m-%d")
    legacy_memory = memory_dir / f"{today}.md"
    legacy_memory.write_text(
        f"# {today}\n\n"
        "## Session 00:00\n\n"
        "### 00:00\n"
        f"<!-- session:{session_id} db:{db_path} -->\n"
        "- legacy summary for turn u1\n\n",
        encoding="utf-8",
    )

    _insert_message(conn, "u1", session_id, 100, "user", text="Question one")
    _insert_message(conn, "a1", session_id, 110, "assistant", parent_id="u1", finish="stop", text="Answer one")
    _insert_message(conn, "u2", session_id, 200, "user", text="Question two")
    _insert_message(conn, "a2", session_id, 210, "assistant", parent_id="u2", finish="stop", text="Answer two")
    _insert_message(conn, "u3", session_id, 300, "user", text="Question three")
    conn.commit()

    monkeypatch.setattr(capture_daemon, "summarize_with_llm", lambda *args, **kwargs: None)

    turn_db = open_turn_db(str(project_dir))
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
    )

    rows = load_session_turn_rows(turn_db, session_id)
    assert [row["turn_id"] for row in rows] == ["u2"]

    content = legacy_memory.read_text(encoding="utf-8")
    assert f"<!-- session:{session_id} db:{db_path} -->" in content
    assert f"<!-- session:{session_id} turn:u1 db:{db_path} -->" not in content
    assert f"<!-- session:{session_id} turn:u2 db:{db_path} -->" in content
    assert "Question two" in content

    state = load_turn_state(turn_db, session_id)
    assert state.last_completed_turn_id == "u2"
    assert state.last_completed_time == 210

    turn_db.close()
    conn.close()


def test_capture_session_turns_does_not_advance_sidecar_when_markdown_write_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "opencode.db"
    conn = _make_opencode_db(db_path)
    session_id = "ses_write_fail"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    memory_dir = project_dir / ".memsearch" / "memory"

    _insert_message(conn, "u1", session_id, 100, "user", text="Question")
    _insert_message(conn, "a1", session_id, 110, "assistant", parent_id="u1", finish="stop", text="Answer")
    conn.commit()

    monkeypatch.setattr(capture_daemon, "summarize_with_llm", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        capture_daemon,
        "write_capture",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    turn_db = open_turn_db(str(project_dir))

    with suppress(OSError):
        capture_daemon.capture_session_turns(
            conn,
            turn_db,
            str(memory_dir),
            session_id,
            "",
            "memsearch",
            str(db_path),
        )

    state = load_turn_state(turn_db, session_id)
    rows = load_session_turn_rows(turn_db, session_id)

    assert state.last_completed_turn_id == ""
    assert state.last_completed_message_id == ""
    assert state.last_completed_time == 0
    assert rows == []

    turn_db.close()
    conn.close()


def test_capture_session_turns_skips_summarizer_when_anchor_already_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    summarize_calls = {"count": 0}

    def tracking_summarize(*args, **kwargs):
        summarize_calls["count"] += 1
        return "- summarized"

    monkeypatch.setattr(capture_daemon, "summarize_with_llm", tracking_summarize)

    db_path = tmp_path / "opencode.db"
    conn = _make_opencode_db(db_path)
    session_id = "ses_rebuild"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    memory_dir = project_dir / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)

    _insert_message(conn, "u1", session_id, 100, "user", text="Question")
    _insert_message(conn, "a1", session_id, 110, "assistant", parent_id="u1", finish="stop", text="Answer")
    _insert_message(conn, "u2", session_id, 200, "user", text="Follow-up")
    conn.commit()

    turn_db = open_turn_db(str(project_dir))
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
    )

    assert summarize_calls["count"] == 1
    content = next(memory_dir.glob("*.md")).read_text(encoding="utf-8")
    assert f"<!-- session:{session_id} turn:u1 db:{db_path} -->" in content

    turn_db.close()

    turn_db = open_turn_db(str(project_dir))
    capture_daemon.capture_session_turns(
        conn,
        turn_db,
        str(memory_dir),
        session_id,
        "",
        "memsearch",
        str(db_path),
    )

    assert summarize_calls["count"] == 1

    content = next(memory_dir.glob("*.md")).read_text(encoding="utf-8")
    assert content.count(f"<!-- session:{session_id} turn:u1 db:{db_path} -->") == 1

    turn_db.close()
    conn.close()
