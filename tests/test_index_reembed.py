"""Incremental indexing must not re-embed unchanged text (#786).

Chunk IDs include line numbers, so inserting text above a chunk shifts every
ID below it. The indexer must reuse stored embeddings for those shifted
chunks instead of re-embedding identical content.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from memsearch.chunker import compute_chunk_id
from memsearch.core import MemSearch, _reusable_embeddings

ENTRIES_BEFORE = "\n".join(
    f"## [2026-09-{d:02d}] session\n\nWorked on item {d}. Some body text here.\n" for d in range(20, 0, -1)
)
FILE_BEFORE = f"# Log\n\n{ENTRIES_BEFORE}"
INSERTED = "## [2026-09-21] session\n\nNew entry.\n"
FILE_AFTER = f"# Log\n\n{INSERTED}{ENTRIES_BEFORE}"


class CountingEmbedder:
    """Distinct vector per embed call, so reused vectors are recognizable."""

    model_name = "fake"
    dimension = 4
    batch_size = 32

    def __init__(self) -> None:
        self.embedded_texts: list[str] = []
        self._next_base = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        base = self._next_base
        self._next_base += 100
        self.embedded_texts.extend(texts)
        return [[float(base + i), 1.0, 0.0, 0.0] for i in range(len(texts))]


class InMemoryStore:
    def __init__(self) -> None:
        self._records_by_source: dict[str, list[dict[str, Any]]] = {}
        self.deleted_hashes: list[list[str]] = []

    def _ensure_collection_for_write(self) -> None:
        pass

    def hashes_by_source(self, source: str) -> set[str]:
        return {record["chunk_hash"] for record in self._records_by_source.get(source, [])}

    def rows_by_hashes(self, hashes: list[str]) -> list[dict[str, Any]]:
        wanted = set(hashes)
        return [
            record
            for records in self._records_by_source.values()
            for record in records
            if record["chunk_hash"] in wanted
        ]

    def delete_by_hashes(self, hashes: list[str]) -> None:
        self.deleted_hashes.append(list(hashes))
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

    def rows_for(self, source: str) -> list[dict[str, Any]]:
        return self._records_by_source.get(source, [])

    def delete_by_source(self, source: str) -> None:
        self._records_by_source.pop(source, None)


def make_memsearch(paths: list[Path]) -> tuple[MemSearch, CountingEmbedder, InMemoryStore]:
    ms = MemSearch.__new__(MemSearch)
    ms._paths = [str(path) for path in paths]
    ms._max_chunk_size = 1500
    ms._overlap_lines = 2
    ms._ignore_files = []
    ms._exclude = []
    embedder = CountingEmbedder()
    ms._embedder = embedder
    ms._store = InMemoryStore()
    ms._reranker_model = ""
    return ms, embedder, ms._store


def write_and_index(ms: MemSearch, path: Path, text: str) -> int:
    path.write_text(text, encoding="utf-8")
    return asyncio.run(ms.index())


def test_insertion_at_top_reuses_embeddings_for_unchanged_chunks(tmp_path: Path) -> None:
    log = tmp_path / "log.md"
    ms, embedder, store = make_memsearch([log])

    write_and_index(ms, log, FILE_BEFORE)
    assert len(embedder.embedded_texts) == 20
    before_rows = {r["content"]: r["embedding"] for r in store.rows_for(str(log))}

    embedder.embedded_texts.clear()
    stored = write_and_index(ms, log, FILE_AFTER)

    # Only the genuinely new section is embedded; the 20 shifted chunks reuse
    # their stored vectors.
    assert embedder.embedded_texts == ["## [2026-09-21] session\n\nNew entry."]
    assert stored == 21
    after_rows = {r["content"]: r["embedding"] for r in store.rows_for(str(log))}
    assert len(after_rows) == 21
    for content, embedding in before_rows.items():
        assert after_rows[content] == embedding, f"embedding was not reused for: {content!r}"


def test_insertion_updates_line_metadata_of_reused_chunks(tmp_path: Path) -> None:
    log = tmp_path / "log.md"
    ms, _embedder, store = make_memsearch([log])

    write_and_index(ms, log, FILE_BEFORE)
    old_lines = {r["content"]: (r["start_line"], r["end_line"]) for r in store.rows_for(str(log))}

    write_and_index(ms, log, FILE_AFTER)

    offset = len(INSERTED.split("\n")) - 1
    for content, (start, end) in old_lines.items():
        row = next(r for r in store.rows_for(str(log)) if r["content"] == content)
        assert (row["start_line"], row["end_line"]) == (start + offset, end + offset)


def test_unchanged_file_embeds_nothing_on_reindex(tmp_path: Path) -> None:
    log = tmp_path / "log.md"
    ms, embedder, store = make_memsearch([log])

    write_and_index(ms, log, FILE_BEFORE)
    embedder.embedded_texts.clear()
    assert asyncio.run(ms.index()) == 0
    assert embedder.embedded_texts == []
    assert store.deleted_hashes == []


def test_stale_chunks_are_deleted_after_reuse(tmp_path: Path) -> None:
    log = tmp_path / "log.md"
    ms, _embedder, store = make_memsearch([log])

    write_and_index(ms, log, FILE_BEFORE)
    old_hashes = store.hashes_by_source(str(log))

    write_and_index(ms, log, FILE_AFTER)

    # Old IDs are gone; every row now carries the shifted line numbers.
    new_hashes = store.hashes_by_source(str(log))
    assert len(new_hashes) == 21
    assert len(old_hashes & new_hashes) == 0


def test_model_change_still_forces_full_reembed(tmp_path: Path) -> None:
    log = tmp_path / "log.md"
    ms, embedder, store = make_memsearch([log])

    write_and_index(ms, log, FILE_BEFORE)
    before_rows = {r["content"]: r["embedding"] for r in store.rows_for(str(log))}

    embedder.model_name = "fake-v2"
    embedder.embedded_texts.clear()
    write_and_index(ms, log, FILE_AFTER)

    # Stored vectors were embedded by the old model — none may be reused.
    assert len(embedder.embedded_texts) == 21
    after_rows = {r["content"]: r["embedding"] for r in store.rows_for(str(log))}
    for content in before_rows:
        assert after_rows[content] != before_rows[content], f"stale-model embedding reused for: {content!r}"


def test_force_reembeds_everything(tmp_path: Path) -> None:
    log = tmp_path / "log.md"
    ms, embedder, _store = make_memsearch([log])

    write_and_index(ms, log, FILE_BEFORE)
    embedder.embedded_texts.clear()
    write_and_index(ms, log, FILE_AFTER)
    assert embedder.embedded_texts == ["## [2026-09-21] session\n\nNew entry."]

    embedder.embedded_texts.clear()
    asyncio.run(ms.index(force=True))
    assert len(embedder.embedded_texts) == 21


def test_other_sources_are_not_touched_by_a_top_insertion(tmp_path: Path) -> None:
    log = tmp_path / "log.md"
    other = tmp_path / "other.md"
    ms, embedder, store = make_memsearch([log, other])

    write_and_index(ms, log, FILE_BEFORE)
    write_and_index(ms, other, "# Other\n\nuntouched notes\n")

    embedder.embedded_texts.clear()
    write_and_index(ms, log, FILE_AFTER)

    assert {r["content"]: r["embedding"] for r in store.rows_for(str(other))} == {
        "# Other\n\nuntouched notes": [100.0, 1.0, 0.0, 0.0]
    }
    assert embedder.embedded_texts == ["## [2026-09-21] session\n\nNew entry."]


def test_identical_sections_share_one_reused_embedding(tmp_path: Path) -> None:
    # Repeated identical sections (same heading + body) share one content
    # hash; both shifted copies must adopt the same stored vector.
    section = "## Session\n\nalpha body\n"
    prefix = "# Log\n\n"
    file_before = prefix + section + section
    inserted = "## Zero\n\nfresh entry.\n"
    file_after = prefix + inserted + file_before[len(prefix) :]
    log = tmp_path / "log.md"
    ms, embedder, store = make_memsearch([log])

    write_and_index(ms, log, file_before)
    original_vectors = [r["embedding"] for r in store.rows_for(str(log))]
    assert len(original_vectors) == 2  # two rows, one per shifted copy
    assert len({r["content"] for r in store.rows_for(str(log))}) == 1  # identical content

    embedder.embedded_texts.clear()
    write_and_index(ms, log, file_after)

    assert embedder.embedded_texts == ["## Zero\n\nfresh entry."]
    session_rows = [r for r in store.rows_for(str(log)) if r["heading"] == "Session"]
    assert len(session_rows) == 2
    assert len({row["content"] for row in session_rows}) == 1
    assert len({tuple(row["embedding"]) for row in session_rows}) == 1
    assert session_rows[0]["embedding"] in original_vectors


def test_reusable_embeddings_skips_rows_not_from_current_model() -> None:
    model = "fake"
    content = "## A\n\nalpha\n"
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

    def row(source: str, stored_model: str, *, with_embedding: bool = True) -> dict[str, Any]:
        record: dict[str, Any] = {
            "chunk_hash": compute_chunk_id(source, 1, 3, content_hash, stored_model),
            "content": content,
            "source": source,
            "heading": "A",
            "heading_level": 2,
            "start_line": 1,
            "end_line": 3,
        }
        if with_embedding:
            record["embedding"] = [1.0, 0.0, 0.0, 0.0]
        return record

    current_model = row("a.md", model)
    other_model = row("a.md", "other-model")
    no_embedding = row("a.md", model, with_embedding=False)

    reusable = _reusable_embeddings([current_model, other_model, no_embedding], model)

    assert reusable == {content_hash: current_model["embedding"]}


def test_reusable_embeddings_keeps_first_row_per_content() -> None:
    model = "fake"
    content = "## A\n\nalpha\n"
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    first: dict[str, Any] = {
        "chunk_hash": compute_chunk_id("a.md", 1, 3, content_hash, model),
        "content": content,
        "source": "a.md",
        "heading": "A",
        "heading_level": 2,
        "start_line": 1,
        "end_line": 3,
        "embedding": [1.0, 0.0, 0.0, 0.0],
    }
    second = {**first, "chunk_hash": compute_chunk_id("a.md", 5, 7, content_hash, model)}

    reusable = _reusable_embeddings([first, second], model)

    assert reusable == {content_hash: first["embedding"]}
