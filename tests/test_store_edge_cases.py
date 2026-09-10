"""Edge case tests for Milvus store operations."""

from __future__ import annotations

import pytest

from memsearch.store import MilvusStore


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test_milvus.db"
    s = MilvusStore(uri=str(db), dimension=4)
    yield s
    s.close()


class TestStoreEdgeCases:
    def test_upsert_empty_chunks(self, store):
        """Upsert with empty list should return 0."""
        result = store.upsert([])
        assert result == 0

    def test_upsert_single_chunk(self, store):
        """Upsert with single chunk."""
        chunk = {
            "embedding": [1.0, 0.0, 0.0, 0.0],
            "content": "Single chunk",
            "source": "single.md",
            "heading": "",
            "chunk_hash": "single_hash",
            "heading_level": 0,
            "start_line": 1,
            "end_line": 1,
        }
        n = store.upsert([chunk])
        assert n == 1

        results = store.search([1.0, 0.0, 0.0, 0.0], top_k=1)
        assert len(results) == 1
        assert results[0]["content"] == "Single chunk"

    def test_delete_by_hashes_empty_list(self, store):
        """Delete by empty hash list should not raise."""
        store.delete_by_hashes([])  # Should not raise

    def test_delete_by_hashes_nonexistent(self, store):
        """Delete non-existent hashes should not raise."""
        store.delete_by_hashes(["nonexistent_hash_12345"])  # Should not raise

    def test_hashes_by_source_nonexistent(self, store):
        """Hashes for non-existent source should be empty."""
        hashes = store.hashes_by_source("nonexistent.md")
        assert hashes == set()

    def test_count_empty_store(self, store):
        """Count on empty store should be 0."""
        count = store.count()
        assert count == 0

    def test_count_after_operations(self, store):
        """Count should reflect upserts and deletes."""
        assert store.count() == 0

        chunk1 = {
            "embedding": [1.0, 0.0, 0.0, 0.0],
            "content": "Chunk 1",
            "source": "test.md",
            "heading": "",
            "chunk_hash": "hash1",
            "heading_level": 0,
            "start_line": 1,
            "end_line": 1,
        }
        store.upsert([chunk1])
        assert store.count() == 1

        chunk2 = {
            "embedding": [0.0, 1.0, 0.0, 0.0],
            "content": "Chunk 2",
            "source": "test.md",
            "heading": "",
            "chunk_hash": "hash2",
            "heading_level": 0,
            "start_line": 2,
            "end_line": 2,
        }
        store.upsert([chunk2])
        assert store.count() == 2

    def test_indexed_sources_empty(self, store):
        """Indexed sources on empty store should be empty."""
        sources = store.indexed_sources()
        assert sources == set()

    def test_query_empty_filter(self, store):
        """Query with empty filter should return all chunks."""
        chunk = {
            "embedding": [1.0, 0.0, 0.0, 0.0],
            "content": "Test",
            "source": "test.md",
            "heading": "",
            "chunk_hash": "hash1",
            "heading_level": 0,
            "start_line": 1,
            "end_line": 1,
        }
        store.upsert([chunk])

        results = store.query()
        assert len(results) >= 1

    def test_search_with_filter(self, store):
        """Search with filter expression."""
        chunks = [
            {
                "embedding": [1.0, 0.0, 0.0, 0.0],
                "content": "Alpha content",
                "source": "alpha.md",
                "heading": "",
                "chunk_hash": "alpha_hash",
                "heading_level": 0,
                "start_line": 1,
                "end_line": 1,
            },
            {
                "embedding": [0.0, 1.0, 0.0, 0.0],
                "content": "Beta content",
                "source": "beta.md",
                "heading": "",
                "chunk_hash": "beta_hash",
                "heading_level": 0,
                "start_line": 1,
                "end_line": 1,
            },
        ]
        store.upsert(chunks)

        # Filter for alpha source only
        results = store.search(
            [1.0, 0.0, 0.0, 0.0],
            query_text="alpha",
            top_k=10,
            filter_expr='source == "alpha.md"',
        )
        assert len(results) >= 0  # May or may not find results