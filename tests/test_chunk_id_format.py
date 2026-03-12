"""Tests for chunk ID format and generation."""

from __future__ import annotations

from memsearch.chunker import compute_chunk_id


class TestChunkIdFormat:
    def test_chunk_id_is_hex(self):
        """Chunk ID should be hexadecimal string."""
        result = compute_chunk_id("test.md", 1, 5, "hash123", "model")
        assert all(c in "0123456789abcdef" for c in result)

    def test_chunk_id_length(self):
        """Chunk ID should be exactly 16 characters."""
        result = compute_chunk_id("test.md", 1, 5, "hash", "model")
        assert len(result) == 16

    def test_chunk_id_deterministic(self):
        """Same input should produce same ID."""
        id1 = compute_chunk_id("file.md", 1, 10, "abc", "gpt-4")
        id2 = compute_chunk_id("file.md", 1, 10, "abc", "gpt-4")
        assert id1 == id2

    def test_chunk_id_unique_per_source(self):
        """Different sources should produce different IDs."""
        id1 = compute_chunk_id("a.md", 1, 5, "hash", "model")
        id2 = compute_chunk_id("b.md", 1, 5, "hash", "model")
        assert id1 != id2

    def test_chunk_id_unique_per_lines(self):
        """Different line ranges should produce different IDs."""
        id1 = compute_chunk_id("file.md", 1, 5, "hash", "model")
        id2 = compute_chunk_id("file.md", 6, 10, "hash", "model")
        assert id1 != id2

    def test_chunk_id_unique_per_hash(self):
        """Different content hashes should produce different IDs."""
        id1 = compute_chunk_id("file.md", 1, 5, "hash1", "model")
        id2 = compute_chunk_id("file.md", 1, 5, "hash2", "model")
        assert id1 != id2

    def test_chunk_id_unique_per_model(self):
        """Different models should produce different IDs."""
        id1 = compute_chunk_id("file.md", 1, 5, "hash", "model-a")
        id2 = compute_chunk_id("file.md", 1, 5, "hash", "model-b")
        assert id1 != id2
