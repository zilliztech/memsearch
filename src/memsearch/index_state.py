"""Index health state used by CLI and plugin diagnostics."""

from __future__ import annotations

import contextlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .index_report import IndexFailure, IndexReport, format_error

INDEX_STATE_FILENAME = ".index-state.json"
INDEX_STATE_SCHEMA_VERSION = 1


def resolve_index_state_path(
    paths: list[str | Path] | tuple[str | Path, ...],
    *,
    memsearch_dir: str | Path | None = None,
    cwd: str | Path | None = None,
) -> Path | None:
    """Resolve the state file for an index command.

    Plugin calls usually index ``<root>/.memsearch/memory``.  The hook-local
    ``MEMSEARCH_DIR`` shell variable is not always exported to the child CLI, so
    this helper can infer the state root from any path containing ``.memsearch``.
    For arbitrary user paths outside a MemSearch tree, no state file is written.
    """
    explicit_dir = memsearch_dir or os.environ.get("MEMSEARCH_DIR")
    if explicit_dir:
        return Path(explicit_dir).expanduser().resolve() / INDEX_STATE_FILENAME

    base = Path(cwd).expanduser().resolve() if cwd is not None else Path.cwd()
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = base / path
        resolved = path.resolve(strict=False)
        parts = resolved.parts
        for idx, part in enumerate(parts):
            if part == ".memsearch":
                return Path(*parts[: idx + 1]) / INDEX_STATE_FILENAME

    return None


def load_index_state(state_path: Path | None) -> dict[str, Any]:
    """Load an index state file, returning an empty dict if unavailable."""
    if state_path is None or not state_path.is_file():
        return {}
    with contextlib.suppress(json.JSONDecodeError, OSError):
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    return {}


def record_index_started(
    state_path: Path | None,
    *,
    operation: str,
    paths: list[str | Path] | tuple[str | Path, ...],
    collection: str,
    milvus_uri: str,
) -> None:
    """Persist that an indexing operation has started."""
    if state_path is None:
        return

    previous = load_index_state(state_path)
    now = _now()
    state = _base_state(
        status="running",
        operation=operation,
        paths=paths,
        collection=collection,
        milvus_uri=milvus_uri,
        previous=previous,
        now=now,
    )
    state["last_started_at"] = now
    _try_save_index_state(state_path, state)


def record_index_report(
    state_path: Path | None,
    report: IndexReport,
    *,
    operation: str,
    paths: list[str | Path] | tuple[str | Path, ...],
    collection: str,
    milvus_uri: str,
) -> None:
    """Persist a completed indexing report."""
    if state_path is None:
        return

    previous = load_index_state(state_path)
    now = _now()
    state = _base_state(
        status=report.status,
        operation=operation,
        paths=paths,
        collection=collection,
        milvus_uri=milvus_uri,
        previous=previous,
        now=now,
    )
    state.update(
        {
            "last_started_at": previous.get("last_started_at", now),
            "last_completed_at": now,
            "indexed_chunks": report.indexed_chunks,
            "total_files": report.total_files,
            "indexed_files": report.indexed_files,
            "failed_files": [failure.to_dict() for failure in report.failed_files],
        }
    )

    if report.status == "ok":
        state["last_success_at"] = now
    else:
        state["last_failed_at"] = now
        state["last_error"] = f"{len(report.failed_files)} file(s) failed during indexing."

    _try_save_index_state(state_path, state)


def record_index_error(
    state_path: Path | None,
    error: BaseException,
    *,
    operation: str,
    paths: list[str | Path] | tuple[str | Path, ...],
    collection: str,
    milvus_uri: str,
    status: str = "error",
    failed_files: list[IndexFailure] | tuple[IndexFailure, ...] = (),
) -> None:
    """Persist a failed indexing operation."""
    if state_path is None:
        return

    previous = load_index_state(state_path)
    now = _now()
    state = _base_state(
        status=status,
        operation=operation,
        paths=paths,
        collection=collection,
        milvus_uri=milvus_uri,
        previous=previous,
        now=now,
    )
    state.update(
        {
            "last_started_at": previous.get("last_started_at", now),
            "last_completed_at": now,
            "last_failed_at": now,
            "last_error": format_error(error),
            "failed_files": [failure.to_dict() for failure in failed_files],
        }
    )
    _try_save_index_state(state_path, state)


def _base_state(
    *,
    status: str,
    operation: str,
    paths: list[str | Path] | tuple[str | Path, ...],
    collection: str,
    milvus_uri: str,
    previous: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "schema_version": INDEX_STATE_SCHEMA_VERSION,
        "status": status,
        "operation": operation,
        "updated_at": now,
        "paths": [str(path) for path in paths],
        "collection": collection,
        "milvus_uri": milvus_uri,
    }
    if previous.get("last_success_at"):
        state["last_success_at"] = previous["last_success_at"]
    return state


def _save_index_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_name(f"{state_path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(state_path)
    finally:
        with contextlib.suppress(OSError):
            tmp_path.unlink()


def _try_save_index_state(state_path: Path, state: dict[str, Any]) -> None:
    with contextlib.suppress(OSError):
        _save_index_state(state_path, state)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
