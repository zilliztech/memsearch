"""End-to-end tests for the DSH session transcript parser.

Builds synthetic DSH session artifacts (header + SessionEvent JSONL lines) and
runs ``scripts/parse-transcript.py`` as a subprocess, the same way the
``memory-recall`` skill invokes it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "parse-transcript.py"

SESSION_ID = "sess-00000000-0000-0000-0000-000000000001"


def _header() -> str:
    return json.dumps(
        {
            "type": "session",
            "version": 3,
            "id": SESSION_ID,
            "createdAt": 1700000000000,
            "cwd": "/proj",
            "delegationDepth": 0,
        }
    )


def _line(record: dict) -> str:
    return json.dumps(record)


def _turn_start(turn: int, seq: int) -> dict:
    return {"type": "turn/start", "seq": seq, "time": 1700000000000 + seq, "data": {"turn": turn}}


def _turn_end(turn: int, seq: int) -> dict:
    return {
        "type": "turn/end",
        "seq": seq,
        "time": 1700000000000 + seq,
        "data": {"turn": turn, "reason": {"kind": "completed"}},
    }


def _user(text: str, seq: int, *, source_kind: str = "user") -> dict:
    return {
        "type": "user/message",
        "seq": seq,
        "time": 1700000000000 + seq,
        "data": {
            "id": f"u{seq}",
            "role": "user",
            "content": [{"type": "text", "text": text}],
            "source": {"kind": source_kind},
        },
    }


def _assistant(text: str, turn: int, seq: int) -> dict:
    return {
        "type": "assistant/message",
        "seq": seq,
        "time": 1700000000000 + seq,
        "data": {
            "turn": turn,
            "step": 1,
            "message": {
                "id": f"a{seq}",
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
                "source": {"kind": "model", "provider": "deepseek", "model": "deepseek-chat"},
            },
        },
    }


def _tool_call(turn: int, name: str, seq: int) -> dict:
    return {
        "type": "tool/call",
        "seq": seq,
        "time": 1700000000000 + seq,
        "data": {"turn": turn, "step": 1, "callId": f"c{seq}", "name": name, "arguments": "{}"},
    }


def _packed_text_chunks(turn: int, seq0: int, texts: list[str]) -> dict:
    return {
        "type": "text-chunks",
        "seq0": seq0,
        "time0": 1700000000000 + seq0,
        "data": {"turn": turn, "step": 1, "index": 0, "dt": [1, 1], "texts": texts},
    }


def _write_session(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "session.jsonl"
    path.write_text(_header() + "\n" + "\n".join(_line(r) for r in records) + "\n", encoding="utf-8")
    return path


def _run(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--db", str(db_path), *args],
        capture_output=True,
        text=True,
    )


def test_renders_user_and_assistant_turn(tmp_path: Path) -> None:
    db = _write_session(
        tmp_path,
        [
            _turn_start(1, 1),
            _user("What is the deploy command?", 2),
            _assistant("Run `uv run python -m pytest`.", 1, 3),
            _turn_end(1, 4),
        ],
    )
    result = _run(db)
    assert result.returncode == 0, result.stderr
    assert SESSION_ID in result.stdout
    assert "[User]: What is the deploy command?" in result.stdout
    assert "[Assistant]: Run `uv run python -m pytest`." in result.stdout
    assert "=== Turn 1 ===" in result.stdout


def test_skips_plugin_injected_user_messages(tmp_path: Path) -> None:
    db = _write_session(
        tmp_path,
        [
            _turn_start(1, 1),
            _user("[memsearch] Retrieved memory context attached.", 2, source_kind="plugin"),
            _user("Real question?", 3),
            _assistant("Answer.", 1, 4),
            _turn_end(1, 5),
        ],
    )
    result = _run(db)
    assert result.returncode == 0, result.stderr
    assert "[memsearch] Retrieved memory context attached." not in result.stdout
    assert "[User]: Real question?" in result.stdout


def test_target_turn_with_context(tmp_path: Path) -> None:
    db = _write_session(
        tmp_path,
        [
            _turn_start(1, 1),
            _user("First.", 2),
            _assistant("One.", 1, 3),
            _turn_end(1, 4),
            _turn_start(2, 5),
            _user("Second.", 6),
            _assistant("Two.", 2, 7),
            _turn_end(2, 8),
            _turn_start(3, 9),
            _user("Third.", 10),
            _assistant("Three.", 3, 11),
            _turn_end(3, 12),
        ],
    )
    result = _run(db, "--turn", "2", "--context", "1")
    assert result.returncode == 0, result.stderr
    assert "=== Turn 1 ===" in result.stdout
    assert "=== Turn 2 ===" in result.stdout
    assert "=== Turn 3 ===" in result.stdout
    # The block for turn 2 carries its content.
    assert "[User]: Second." in result.stdout


def test_target_turn_context_zero(tmp_path: Path) -> None:
    db = _write_session(
        tmp_path,
        [
            _turn_start(1, 1),
            _user("First.", 2),
            _assistant("One.", 1, 3),
            _turn_end(1, 4),
            _turn_start(2, 5),
            _user("Second.", 6),
            _assistant("Two.", 2, 7),
            _turn_end(2, 8),
        ],
    )
    result = _run(db, "--turn", "1", "--context", "0")
    assert result.returncode == 0, result.stderr
    assert "=== Turn 1 ===" in result.stdout
    assert "=== Turn 2 ===" not in result.stdout


def test_ignores_packed_chunk_rows(tmp_path: Path) -> None:
    db = _write_session(
        tmp_path,
        [
            _turn_start(1, 1),
            _user("Stream it.", 2),
            _packed_text_chunks(1, 3, ["Hel", "lo ", "world"]),
            _assistant("Hello world", 1, 4),
            _turn_end(1, 5),
        ],
    )
    result = _run(db)
    assert result.returncode == 0, result.stderr
    assert "[Assistant]: Hello world" in result.stdout
    # The packed row must not render as a turn event or duplicate text.
    assert result.stdout.count("[Assistant]") == 1


def test_includes_tool_calls(tmp_path: Path) -> None:
    db = _write_session(
        tmp_path,
        [
            _turn_start(1, 1),
            _user("Run the tests.", 2),
            _tool_call(1, "bash", 3),
            _assistant("Done.", 1, 4),
            _turn_end(1, 5),
        ],
    )
    result = _run(db)
    assert result.returncode == 0, result.stderr
    assert "[Tool call]: bash" in result.stdout


def test_missing_db_is_visible_error(tmp_path: Path) -> None:
    result = _run(
        tmp_path / "missing",
    )
    assert result.returncode == 1
    assert "does not exist" in result.stderr


def test_session_id_mismatch(tmp_path: Path) -> None:
    db = _write_session(tmp_path, [_turn_start(1, 1), _user("Hi.", 2), _turn_end(1, 3)])
    result = _run(db, "--session", "different-id")
    assert result.returncode == 1
    assert "session id mismatch" in result.stderr


def test_limit_controls_turns_without_target(tmp_path: Path) -> None:
    records: list[dict] = []
    seq = 1
    for turn in range(1, 4):
        records.append(_turn_start(turn, seq))
        seq += 1
        records.append(_user(f"Q{turn}.", seq))
        seq += 1
        records.append(_assistant(f"A{turn}.", turn, seq))
        seq += 1
        records.append(_turn_end(turn, seq))
        seq += 1
    db = _write_session(tmp_path, records)
    result = _run(db, "--limit", "2")
    assert result.returncode == 0, result.stderr
    assert "=== Turn 3 ===" in result.stdout
    assert "=== Turn 1 ===" not in result.stdout
