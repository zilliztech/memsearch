"""Background LLM call audit — append-only JSONL log of LLM invocations.

Every background LLM call made by memsearch (turn summarization, maintenance
tasks, skills distillation) is recorded to ``<memory>/.llm-audit.jsonl`` so
users can answer "how many tokens did memory cost me?" and triage failures
(the "summary fallback" failure mode). Recording is best-effort: it never
raises and never blocks the audited feature itself.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

AUDIT_FILENAME = ".llm-audit.jsonl"


def resolve_audit_dir(memsearch_dir: str | Path | None = None) -> Path:
    """Resolve the memsearch directory the audit log lives in.

    Explicit *memsearch_dir* wins, then ``MEMSEARCH_DIR``, then
    ``<cwd>/.memsearch`` — the same precedence the maintenance runner uses.
    """
    if memsearch_dir is not None:
        return Path(memsearch_dir).expanduser()
    env = os.environ.get("MEMSEARCH_DIR")
    if env:
        return Path(env).expanduser()
    return Path.cwd() / ".memsearch"


def audit_path(memsearch_dir: str | Path | None = None) -> Path:
    """Return the audit JSONL path inside the memsearch directory."""
    return resolve_audit_dir(memsearch_dir) / AUDIT_FILENAME


def record(
    *,
    source: str,
    provider: str = "",
    mode: str = "",
    status: str,
    duration_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error: str | None = None,
    context: str | None = None,
    memsearch_dir: str | Path | None = None,
    enabled: bool = True,
) -> bool:
    """Append one audit entry. Best-effort: never raises.

    Parameters
    ----------
    source:
        What triggered the call, e.g. ``dsh-summarize``, ``project-review``,
        ``compact``.
    status:
        ``ok`` or ``error``.
    error:
        Real failure cause when *status* is ``error`` (shortened to 500 chars).
    context:
        Optional correlation string (e.g. ``session-<id>/<turn>``).
    enabled:
        Master switch from ``[llm_audit] enabled``; when False, no-op.

    Returns
    -------
    bool
        Whether an entry was actually written.
    """
    if not enabled:
        return False
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(source),
        "provider": str(provider or ""),
        "mode": str(mode or ""),
        "status": "error" if status == "error" else "ok",
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
        "input_tokens": int(input_tokens) if input_tokens is not None else None,
        "output_tokens": int(output_tokens) if output_tokens is not None else None,
        "error": (str(error)[:500]) if error else None,
        "context": str(context) if context else None,
    }
    try:
        path = audit_path(memsearch_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def read_entries(
    *,
    days: int | None = None,
    source: str | None = None,
    only_errors: bool = False,
    memsearch_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Read audit entries, newest last, skipping corrupted lines."""
    path = audit_path(memsearch_dir)
    if not path.is_file():
        return []
    cutoff = time.mktime((datetime.now(timezone.utc) - timedelta(days=days)).timetuple()) if days else None
    entries: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                if source and entry.get("source") != source:
                    continue
                if only_errors and entry.get("status") != "error":
                    continue
                if cutoff is not None:
                    try:
                        ts = datetime.fromisoformat(str(entry["ts"]))
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        if ts.timestamp() < cutoff:
                            continue
                    except (KeyError, ValueError):
                        continue  # unreadable timestamp: keep out of date-filtered views
                entries.append(entry)
    except OSError:
        return []
    return entries


def report(
    *,
    days: int | None = None,
    memsearch_dir: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Aggregate entries by *source*: calls/failures/tokens/durations."""
    agg: dict[str, dict[str, Any]] = {}
    for e in read_entries(days=days, memsearch_dir=memsearch_dir):
        src = str(e.get("source") or "unknown")
        row = agg.setdefault(
            src,
            {
                "calls": 0,
                "failures": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "known_token_calls": 0,
                "total_duration_ms": 0,
            },
        )
        row["calls"] += 1
        if e.get("status") == "error":
            row["failures"] += 1
        for field in ("input_tokens", "output_tokens"):
            v = e.get(field)
            if isinstance(v, int):
                row[field] += v
                row["known_token_calls"] += 1
        d = e.get("duration_ms")
        if isinstance(d, int):
            row["total_duration_ms"] += d
    return agg


def prune(
    *,
    retention_days: int = 90,
    memsearch_dir: str | Path | None = None,
) -> int:
    """Drop entries older than *retention_days*. Returns the removed count.

    Best-effort: never raises; a failed rewrite leaves the log untouched.
    """
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    path = audit_path(memsearch_dir)
    if not path.is_file():
        return 0
    kept: list[str] = []
    removed = 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    ts = datetime.fromisoformat(str(json.loads(stripped)["ts"]))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                    kept.append(stripped)  # corrupted lines stay until next rewrite
                    continue
                if ts < cutoff:
                    removed += 1
                else:
                    kept.append(stripped)
        if removed:
            tmp = path.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            tmp.replace(path)
    except Exception:
        return 0
    return removed
