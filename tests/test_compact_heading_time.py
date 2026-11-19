"""`compact` must time-stamp its heading so same-day compactions can be told apart (#768).

Before the fix every compaction wrote the fixed heading ``## Memory Compact``, so two
compactions on the same day left two identical headings in the daily file.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from memsearch.core import MemSearch


class FakeStore:
    def query(self, filter_expr: str = "", **_: Any) -> list[dict[str, Any]]:
        return [{"content": "a stored chunk"}]


def make_memsearch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clock: list[datetime]) -> MemSearch:
    """A MemSearch with no Milvus and no LLM; ``datetime.now()`` pops from *clock*."""
    monkeypatch.chdir(tmp_path)
    ms = MemSearch.__new__(MemSearch)
    ms._paths = [str(tmp_path)]
    ms._store = FakeStore()

    async def fake_compact_chunks(*_args: Any, **_kwargs: Any) -> str:
        return "- a summary line"

    async def fake_index_file(_path: str | Path) -> int:
        return 1

    class FakeDatetime:
        @staticmethod
        def now() -> datetime:
            return clock.pop(0)

    monkeypatch.setattr("memsearch.core.compact_chunks", fake_compact_chunks)
    monkeypatch.setattr("memsearch.core.datetime", FakeDatetime)
    monkeypatch.setattr(ms, "index_file", fake_index_file)
    return ms


async def test_same_day_compactions_get_distinct_time_headings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 13, 14, 30), datetime(2026, 10, 13, 16, 5)]
    ms = make_memsearch(monkeypatch, tmp_path, clock)

    await ms.compact()
    await ms.compact()

    text = (tmp_path / "memory" / "2026-10-13.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## Memory Compact.*$", text, flags=re.MULTILINE)
    assert headings == ["## Memory Compact 14:30", "## Memory Compact 16:05"]
    assert text.startswith("# 2026-10-13\n")


async def test_heading_keeps_the_memory_compact_prefix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Readers that match the old ``## Memory Compact`` prefix keep working."""
    ms = make_memsearch(monkeypatch, tmp_path, [datetime(2026, 1, 2, 3, 4)])

    await ms.compact()

    text = (tmp_path / "memory" / "2026-01-02.md").read_text(encoding="utf-8")
    assert "\n\n## Memory Compact 03:04\n\n- a summary line\n" in text
