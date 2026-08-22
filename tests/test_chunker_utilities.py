"""Additional unit tests for chunker module utilities."""

from __future__ import annotations

from memsearch.chunker import Chunk, chunk_markdown, compute_chunk_id


class TestChunkerUtilities:
    def test_chunk_dataclass_structure(self):
        """Chunk dataclass should have correct structure."""
        chunk = Chunk(
            content="Test content",
            source="test.md",
            heading="Test Heading",
            heading_level=1,
            start_line=1,
            end_line=5,
        )
        assert chunk.content == "Test content"
        assert chunk.source == "test.md"
        assert chunk.heading == "Test Heading"
        assert chunk.heading_level == 1
        assert chunk.start_line == 1
        assert chunk.end_line == 5
        assert len(chunk.content_hash) == 16  # SHA-256 truncated to 16 chars

    def test_chunk_content_hash_consistency(self):
        """Same content should produce same hash."""
        chunk1 = Chunk(
            content="Same content",
            source="test.md",
            heading="",
            heading_level=0,
            start_line=1,
            end_line=1,
        )
        chunk2 = Chunk(
            content="Same content",
            source="other.md",
            heading="",
            heading_level=0,
            start_line=1,
            end_line=1,
        )
        # Hash is based on content, not source
        assert chunk1.content_hash == chunk2.content_hash

    def test_chunk_different_content_different_hash(self):
        """Different content should produce different hashes."""
        chunk1 = Chunk(
            content="Content A",
            source="test.md",
            heading="",
            heading_level=0,
            start_line=1,
            end_line=1,
        )
        chunk2 = Chunk(
            content="Content B",
            source="test.md",
            heading="",
            heading_level=0,
            start_line=1,
            end_line=1,
        )
        assert chunk1.content_hash != chunk2.content_hash

    def test_compute_chunk_id_format(self):
        """compute_chunk_id should return 16-character hex string."""
        result = compute_chunk_id("test.md", 1, 10, "abc123", "model-v1")
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_chunk_markdown_returns_chunks(self):
        """chunk_markdown should return list of Chunk objects."""
        text = "# Heading\n\nParagraph content."
        chunks = chunk_markdown(text)
        assert isinstance(chunks, list)
        assert len(chunks) > 0
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_chunk_markdown_empty_returns_empty(self):
        """Empty markdown should return empty list."""
        chunks = chunk_markdown("")
        assert chunks == []

    def test_chunk_markdown_whitespace_only(self):
        """Whitespace only markdown should return empty list."""
        chunks = chunk_markdown("   \n   \n   ")
        assert chunks == []