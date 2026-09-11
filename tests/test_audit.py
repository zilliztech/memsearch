"""Tests for the background LLM call audit (memsearch.audit)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memsearch import audit


def _write(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def test_record_appends_entry(tmp_path: Path) -> None:
    assert audit.record(source="dsh-summarize", status="ok", duration_ms=123, memsearch_dir=tmp_path)
    assert audit.record(source="dsh-summarize", status="error", error="boom", memsearch_dir=tmp_path)
    entries = audit.read_entries(memsearch_dir=tmp_path)
    assert len(entries) == 2
    assert entries[0]["source"] == "dsh-summarize"
    assert entries[0]["status"] == "ok"
    assert entries[1]["status"] == "error"
    assert entries[1]["error"] == "boom"


def test_record_disabled_is_noop(tmp_path: Path) -> None:
    assert not audit.record(source="x", status="ok", enabled=False, memsearch_dir=tmp_path)
    assert audit.audit_path(tmp_path).is_file() is False


def test_record_never_raises_on_unwritable_dir(tmp_path: Path) -> None:
    # Make the parent a regular file so the mkdir inside record() must fail.
    # (chmod-based denial is unreliable on Windows, e.g. under elevated shells.)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    assert not audit.record(source="x", status="ok", memsearch_dir=blocker / ".memsearch")


def test_read_entries_skips_corrupted_lines(tmp_path: Path) -> None:
    p = audit.audit_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"ts": "2026-09-09T00:00:00+00:00", "source": "ok-src", "status": "ok"})
        + "\nnot json\n\n"
        + json.dumps({"ts": "2026-09-09T01:00:00+00:00", "source": "ok-src", "status": "error"})
        + "\n",
        encoding="utf-8",
    )
    entries = audit.read_entries(memsearch_dir=tmp_path)
    assert [e["status"] for e in entries] == ["ok", "error"]


def test_read_entries_filters_by_source_errors_and_days(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=10)
    _write(
        audit.audit_path(tmp_path),
        [
            {"ts": old.isoformat(), "source": "a", "status": "ok"},
            {"ts": now.isoformat(), "source": "a", "status": "error"},
            {"ts": now.isoformat(), "source": "b", "status": "ok"},
        ],
    )
    assert len(audit.read_entries(days=7, memsearch_dir=tmp_path)) == 2
    assert [e["source"] for e in audit.read_entries(source="b", memsearch_dir=tmp_path)] == ["b"]
    errs = audit.read_entries(only_errors=True, memsearch_dir=tmp_path)
    assert len(errs) == 1
    assert errs[0]["source"] == "a" and errs[0]["status"] == "error"


def test_report_aggregates_by_source(tmp_path: Path) -> None:
    _write(
        audit.audit_path(tmp_path),
        [
            {"ts": "2026-09-09T00:00:00+00:00", "source": "s", "status": "ok", "duration_ms": 100,
             "input_tokens": 10, "output_tokens": 5},
            {"ts": "2026-09-09T01:00:00+00:00", "source": "s", "status": "error", "duration_ms": 50},
            {"ts": "2026-09-09T02:00:00+00:00", "source": "t", "status": "ok"},
        ],
    )
    agg = audit.report(memsearch_dir=tmp_path)
    assert agg["s"]["calls"] == 2
    assert agg["s"]["failures"] == 1
    assert agg["s"]["input_tokens"] == 10
    assert agg["s"]["output_tokens"] == 5
    assert agg["s"]["total_duration_ms"] == 150
    assert agg["t"]["calls"] == 1


def test_prune_drops_old_entries_and_keeps_rest(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    _write(
        audit.audit_path(tmp_path),
        [
            {"ts": (now - timedelta(days=100)).isoformat(), "source": "old", "status": "ok"},
            {"ts": now.isoformat(), "source": "new", "status": "ok"},
        ],
    )
    removed = audit.prune(retention_days=90, memsearch_dir=tmp_path)
    assert removed == 1
    remaining = audit.read_entries(memsearch_dir=tmp_path)
    assert [e["source"] for e in remaining] == ["new"]


def test_prune_never_raises_on_missing_file(tmp_path: Path) -> None:
    assert audit.prune(retention_days=90, memsearch_dir=tmp_path) == 0


def test_audit_config_defaults() -> None:
    from memsearch.config import MemSearchConfig

    cfg = MemSearchConfig()
    assert cfg.llm_audit.enabled is True
    assert cfg.llm_audit.retention_days == 90
