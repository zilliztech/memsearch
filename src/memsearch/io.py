"""Text file helpers."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def read_utf8_text_replace(path: str | Path) -> str:
    """Read text as UTF-8, replacing invalid byte sequences.

    Markdown memory files are expected to be UTF-8, but hooks may append
    agent/tool output that contains malformed bytes. Keep indexing usable
    and preserve as much surrounding text as possible.
    """
    p = Path(path)
    data = p.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        logger.warning(
            "File %s contains invalid UTF-8 at byte %d; replacing invalid bytes",
            p,
            e.start,
        )
        return data.decode("utf-8", errors="replace")
