from __future__ import annotations

import asyncio
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

    @property
    def batch_size(self) -> int:
        return 32

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]


class InMemoryStore:
    def __init__(self) -> None:
        self._records_by_source: dict[str, list[dict[str, Any]]] = {}
        self.deleted_sources: list[str] = []

    def hashes_by_source(self, source: str) -> set[str]:
        return {record["chunk_hash"] for record in self._records_by_source.get(source, [])}

    def delete_by_hashes(self, hashes: list[str]) -> None:
        stale = set(hashes)
        for source, records in list(self._records_by_source.items()):
            remaining = [record for record in records if record["chunk_hash"] not in stale]
            if remaining:
                self._records_by_source[source] = remaining
            else:
                self._records_by_source.pop(source, None)

    def upsert(self, records: list[dict[str, Any]]) -> int:
        for record in records:
            source = record["source"]
            existing = [
                old for old in self._records_by_source.get(source, []) if old["chunk_hash"] != record["chunk_hash"]
            ]
            existing.append(record)
            self._records_by_source[source] = existing
        return len(records)

    def indexed_sources(self) -> set[str]:
        return set(self._records_by_source)

    def delete_by_source(self, source: str) -> None:
        self.deleted_sources.append(source)
        self._records_by_source.pop(source, None)


def make_memsearch(
    paths: list[str | Path],
    *,
    ignore_files: list[str] | None = None,
    exclude: list[str] | None = None,
) -> tuple[MemSearch, InMemoryStore]:
    ms = MemSearch.__new__(MemSearch)
    ms._paths = [str(path) for path in paths]
    ms._max_chunk_size = 1500
    ms._overlap_lines = 2
    ms._ignore_files = list(ignore_files or [])
    ms._exclude = list(exclude or [])
    ms._embedder = FakeEmbedder()
    store = InMemoryStore()
    ms._store = store
    ms._reranker_model = ""
    return ms, store


def write_note(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_file_index_does_not_prune_other_indexed_sources(tmp_path: Path) -> None:
    a = write_note(tmp_path / "a.md", "# A\n\nalpha\n")
    b = write_note(tmp_path / "b.md", "# B\n\nbravo\n")

    ms, store = make_memsearch([a, b])
    await ms.index()

    ms._paths = [str(a)]
    await ms.index()

    assert str(a) in store.indexed_sources()
    assert str(b) in store.indexed_sources()
    assert store.deleted_sources == []


@pytest.mark.asyncio
async def test_directory_index_prunes_deleted_sources_inside_that_directory(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    keep = write_note(docs / "keep.md", "# Keep\n\nalpha\n")
    stale = write_note(docs / "stale.md", "# Stale\n\nbravo\n")

    ms, store = make_memsearch([docs])
    await ms.index()

    stale.unlink()
    await ms.index()

    assert str(keep) in store.indexed_sources()
    assert str(stale) not in store.indexed_sources()
    assert store.deleted_sources == [str(stale)]


@pytest.mark.asyncio
async def test_directory_index_does_not_prune_sources_outside_that_directory(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    other = tmp_path / "other"
    doc = write_note(docs / "a.md", "# A\n\nalpha\n")
    other_doc = write_note(other / "b.md", "# B\n\nbravo\n")

    ms, store = make_memsearch([docs, other_doc])
    await ms.index()

    ms._paths = [str(docs)]
    await ms.index()

    assert str(doc) in store.indexed_sources()
    assert str(other_doc) in store.indexed_sources()
    assert store.deleted_sources == []


@pytest.mark.asyncio
async def test_directory_cleanup_uses_path_boundaries_not_string_prefixes(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs2 = tmp_path / "docs2"
    doc = write_note(docs / "a.md", "# A\n\nalpha\n")
    similar_prefix_doc = write_note(docs2 / "b.md", "# B\n\nbravo\n")

    ms, store = make_memsearch([docs, docs2])
    await ms.index()

    ms._paths = [str(docs)]
    await ms.index()

    assert str(doc) in store.indexed_sources()
    assert str(similar_prefix_doc) in store.indexed_sources()
    assert store.deleted_sources == []


@pytest.mark.asyncio
async def test_enabling_ignore_rules_removes_previously_indexed_sources(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    keep = write_note(docs / "keep.md", "# Keep\n\nalpha\n")
    ignored = write_note(docs / "ignored.md", "# Ignored\n\nbravo\n")

    ms, store = make_memsearch([docs])
    await ms.index()

    write_note(docs / ".gitignore", "ignored.md\n")
    ms._ignore_files = [".gitignore"]
    await ms.index()

    assert str(keep) in store.indexed_sources()
    assert str(ignored) not in store.indexed_sources()
    assert store.deleted_sources == [str(ignored)]


@pytest.mark.asyncio
async def test_initial_index_and_live_watch_share_ignore_policy(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    write_note(docs / ".gitignore", "ignored*.md\n")
    existing_included = write_note(docs / "included.md", "# Included\n\nalpha\n")
    existing_ignored = write_note(docs / "ignored-old.md", "# Ignored\n\nbravo\n")

    ms, store = make_memsearch([docs], ignore_files=[".gitignore"])
    await ms.index()

    assert str(existing_included) in store.indexed_sources()
    assert str(existing_ignored) not in store.indexed_sources()

    watcher = ms.watch(debounce_ms=50)
    try:
        live_included = write_note(docs / "live.md", "# Live\n\ncharlie\n")
        live_ignored = write_note(docs / "ignored-live.md", "# Ignored Live\n\ndelta\n")
        await asyncio.sleep(0.5)
    finally:
        watcher.stop()

    assert str(live_included) in store.indexed_sources()
    assert str(live_ignored) not in store.indexed_sources()


@pytest.mark.asyncio
async def test_index_with_report_captures_file_failures(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    good = write_note(docs / "good.md", "# Good\n\nalpha\n")
    bad = write_note(docs / "bad.md", "# Bad\n\nbravo\n")

    ms, store = make_memsearch([docs])
    original_index_file = ms._index_file

    async def fail_bad_file(f, *, force=False):
        if f.path == bad:
            raise RuntimeError("embedding provider failed")
        return await original_index_file(f, force=force)

    ms._index_file = fail_bad_file

    report = await ms.index_with_report()

    assert report.status == "degraded"
    assert report.total_files == 2
    assert report.indexed_files == 1
    assert len(report.failed_files) == 1
    assert report.failed_files[0].path == str(bad)
    assert "RuntimeError: embedding provider failed" in report.failed_files[0].error
    assert str(good) in store.indexed_sources()
