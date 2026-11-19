import contextlib
import sqlite3
import subprocess
import sys

import pytest

from tests.opencode_v2_fixtures import SCRIPTS, Fixture, parser, reader


def test_readonly_explicit_escaped_db_and_turn_context(tmp_path):
    f = Fixture(tmp_path / "project", tmp_path / "space # ? 数据.db")
    f.turn()
    f.turn(30)
    before = f.path.read_bytes()
    assert "Turn msg32" in parser.parse_session("session", f.scope, str(f.path), turn_id="msg32", context=0)
    assert "Turn msg2 " not in parser.parse_session("session", f.scope, str(f.path), turn_id="msg32", context=0)
    with (
        contextlib.closing(reader.open_source(str(f.path))) as conn,
        pytest.raises(sqlite3.OperationalError, match="readonly"),
    ):
        conn.execute("DELETE FROM session_message")
    assert f.path.read_bytes() == before
    assert not (f.root / ".memsearch").exists()
    f.conn.close()


def test_missing_legacy_and_unmigrated_diagnostics(tmp_path):
    with pytest.raises(reader.TranscriptError, match="not found"):
        reader.open_source(str(tmp_path / "absent.db"))
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE message(id TEXT)")
    with pytest.raises(reader.TranscriptError, match=r"0\.3\.17.*migration"):
        reader.open_source(str(path))
    f = Fixture(tmp_path / "project")
    with pytest.raises(reader.TranscriptError, match="user-owned OpenCode migration"):
        parser.parse_session("absent", f.scope, str(f.path))
    with pytest.raises(reader.TranscriptError, match="no V2 user turns"):
        parser.parse_session("session", f.scope, str(f.path))
    f.conn.close()


def test_exact_or_unambiguous_prefix_only(tmp_path):
    f = Fixture(tmp_path / "project")
    f.turn()
    f.turn(20)
    assert "Turn msg22" in parser.parse_session("session", f.scope, str(f.path), turn_id="msg22", context=0)
    assert "Turn msg2" in parser.parse_session("session", f.scope, str(f.path), turn_id="msg2", context=0)
    with pytest.raises(reader.TranscriptError, match="Ambiguous"):
        parser.parse_session("session", f.scope, str(f.path), turn_id="msg")
    with pytest.raises(reader.TranscriptError, match="Turn not found"):
        parser.parse_session("session", f.scope, str(f.path), turn_id="absent")
    f.conn.close()


def test_referenced_session_must_belong_to_requesting_checkout(tmp_path):
    f = Fixture(tmp_path / "project")
    other = tmp_path / "other/project"
    other.mkdir(parents=True)
    f.session("foreign", directory=other)
    f.turn(session="foreign")
    with pytest.raises(reader.TranscriptError, match="outside"):
        parser.parse_session("foreign", f.scope, str(f.path))
    f.conn.close()


def test_cli_enforces_bounds_and_scope_arguments(tmp_path):
    f = Fixture(tmp_path / "project")
    f.turn()
    argv = [
        sys.executable,
        str(SCRIPTS / "parse-transcript.py"),
        "session",
        "--project-dir",
        str(f.root),
        "--project-id",
        "project",
        "--db",
        str(f.path),
    ]
    result = subprocess.run([*argv, "--turn", "msg2", "--context", "0"], capture_output=True, text=True)
    assert result.returncode == 0 and "synthetic answer" in result.stdout
    result = subprocess.run([*argv, "--limit", "1000"], capture_output=True, text=True)
    assert result.returncode == 2 and "between 1 and 50" in result.stderr
    result = subprocess.run(argv[:3], capture_output=True, text=True)
    assert result.returncode == 2 and "--project-dir" in result.stderr
    f.conn.close()


def test_db_channel_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("OPENCODE_DB", raising=False)
    monkeypatch.delenv("OPENCODE_DISABLE_CHANNEL_DB", raising=False)
    assert reader.get_db_path(channel="latest") == str(tmp_path / "opencode/opencode.db")
    assert reader.get_db_path(channel="branch/foo") == str(tmp_path / "opencode/opencode-branch-foo.db")
    monkeypatch.setenv("OPENCODE_DB", "relative.db")
    assert reader.get_db_path() == str(tmp_path / "opencode/relative.db")
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "absolute.db"))
    assert reader.get_db_path() == str(tmp_path / "absolute.db")
    assert reader.get_db_path(str(tmp_path / "anchor.db")) == str(tmp_path / "anchor.db")
    with pytest.raises(reader.TranscriptError, match="In-memory"):
        reader.open_source(":memory:")
