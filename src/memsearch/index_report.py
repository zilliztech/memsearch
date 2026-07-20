"""Structured index results shared by core and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexFailure:
    """A per-file indexing failure captured during a best-effort scan."""

    path: str
    error: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "error": self.error}


@dataclass(frozen=True)
class IndexReport:
    """Structured result for a completed indexing pass."""

    indexed_chunks: int
    total_files: int
    indexed_files: int
    failed_files: tuple[IndexFailure, ...] = ()

    @property
    def status(self) -> str:
        return "degraded" if self.failed_files else "ok"


def format_error(error: BaseException, limit: int = 2000) -> str:
    """Return a compact, JSON-safe error string for diagnostics."""
    message = f"{type(error).__name__}: {error}"
    suffix = "... [truncated]"
    if len(message) > limit:
        return message[: limit - len(suffix)] + suffix
    return message
