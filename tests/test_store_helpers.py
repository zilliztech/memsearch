from __future__ import annotations

from pathlib import Path

import pytest

from memsearch.store import MilvusStore, _escape_filter_value


@pytest.fixture
def store(tmp_path: Path):
    db = tmp_path / "store_helpers.db"
    s = MilvusStore(uri=str(db), dimension=4)
    yield s
    s.close()


@pytest.fixture
def seeded_store(store: MilvusStore) -> MilvusStore:
    store.upsert(
        [
            {
                "embedding": [1.0, 0.0, 0.0, 0.0],
                "content": "Alpha chunk",
                "source": 'docs/alpha"quote\\.md',
                "heading": "Alpha",
                "chunk_hash": "hash-alpha",
                "heading_level": 1,
                "start_line": 1,
                "end_line": 3,
            },
            {
                "embedding": [0.0, 1.0, 0.0, 0.0],
                "content": "Beta chunk",
                "source": "docs/beta.md",
                "heading": "Beta",
                "chunk_hash": "hash-beta",
                "heading_level": 1,
                "start_line": 4,
                "end_line": 6,
            },
        ]
    )
    return store


def test_escape_filter_value_escapes_backslashes_and_quotes() -> None:
    assert _escape_filter_value('say "hi" \\ path') == 'say \\"hi\\" \\\\ path'


def test_hashes_by_source_and_indexed_sources(seeded_store: MilvusStore) -> None:
    assert seeded_store.hashes_by_source('docs/alpha"quote\\.md') == {"hash-alpha"}
    assert seeded_store.indexed_sources() == {'docs/alpha"quote\\.md', "docs/beta.md"}


def test_query_count_and_delete_by_hashes(seeded_store: MilvusStore) -> None:
    rows = seeded_store.query(filter_expr='source == "docs/beta.md"')

    assert len(rows) == 1
    assert rows[0]["chunk_hash"] == "hash-beta"
    assert seeded_store.count() == 2

    seeded_store.delete_by_hashes(["hash-beta"])

    assert seeded_store.count() == 1
    assert seeded_store.hashes_by_source("docs/beta.md") == set()
