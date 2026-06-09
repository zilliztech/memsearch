from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from memsearch.core import MemSearch


class FakeEmbedder:
    @property
    def model_name(self) -> str:
        return "fake"

    @property
    def dimension(self) -> int:
        return 4

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]


class RecordingStore:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def hashes_by_source(self, source: str) -> set[str]:
        return set()

    def delete_by_hashes(self, hashes: list[str]) -> None:
        pass

    def upsert(self, records: list[dict[str, Any]]) -> int:
        self.records.extend(records)
        return len(records)


def make_memsearch() -> tuple[MemSearch, RecordingStore]:
    ms = MemSearch.__new__(MemSearch)
    ms._paths = []
    ms._max_chunk_size = 1500
    ms._overlap_lines = 2
    ms._embedder = FakeEmbedder()
    store = RecordingStore()
    ms._store = store
    ms._reranker_model = ""
    return ms, store


@pytest.mark.asyncio
async def test_index_file_replaces_invalid_utf8_bytes(tmp_path: Path) -> None:
    note = tmp_path / "bad.md"
    note.write_bytes(b"# Bad UTF-8\n\nThis line has an invalid byte: \xff.\n")
    ms, store = make_memsearch()

    indexed = await ms.index_file(note)

    assert indexed == 1
    assert store.records[0]["content"] == "# Bad UTF-8\n\nThis line has an invalid byte: \ufffd."
