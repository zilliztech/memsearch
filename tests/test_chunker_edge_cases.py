"""Edge case tests for markdown chunking."""

from __future__ import annotations

from memsearch.chunker import Chunk, chunk_markdown, compute_chunk_id


class TestChunkerEdgeCases:
    def test_empty_markdown(self):
        """Empty markdown should produce no chunks."""
        chunks = chunk_markdown("")
        assert chunks == []

    def test_whitespace_only(self):
        """Whitespace-only markdown should produce no chunks."""
        chunks = chunk_markdown("   \n\n   ")
        assert chunks == []

    def test_single_line_no_heading(self):
        """Single line without heading should produce one chunk."""
        chunks = chunk_markdown("Just a single line.")
        assert len(chunks) == 1
        assert chunks[0].content == "Just a single line."
        assert chunks[0].heading == ""
        assert chunks[0].heading_level == 0

    def test_only_headings_no_content(self):
        """Headings without content should be handled."""
        md = "# Heading 1\n# Heading 2"
        chunks = chunk_markdown(md)
        # Should have chunks for headings themselves
        assert len(chunks) >= 1

    def test_very_large_max_chunk_size(self):
        """Very large max_chunk_size should not split."""
        text = "# Title\n\n" + "x" * 10000
        chunks = chunk_markdown(text, max_chunk_size=100000)
        assert len(chunks) == 1

    def test_very_small_max_chunk_size(self):
        """Very small max_chunk_size should split aggressively."""
        text = "# Title\n\nParagraph one.\n\nParagraph two.\n\nParagraph three."
        chunks = chunk_markdown(text, max_chunk_size=50)
        assert len(chunks) >= 2  # Should have split

    def test_unicode_content(self):
        """Unicode content should be handled correctly."""
        text = "# 标题\n\n内容包含中文和 emoji 🎉"
        chunks = chunk_markdown(text)
        assert len(chunks) == 1
        assert "🎉" in chunks[0].content

    def test_special_markdown_characters(self):
        """Special markdown characters should be preserved."""
        text = "# Title\n\n```code block```\n\n| table | col |\n|-------|-----|"
        chunks = chunk_markdown(text)
        assert len(chunks) >= 1
        assert "```" in chunks[0].content


class TestComputeChunkIdEdgeCases:
    def test_empty_strings(self):
        """compute_chunk_id should handle empty strings."""
        result = compute_chunk_id("", 1, 2, "abc", "model")
        assert len(result) == 16  # Should still produce hash
        assert isinstance(result, str)

    def test_unicode_in_id_components(self):
        """compute_chunk_id should handle unicode in components."""
        result = compute_chunk_id("文件.md", 1, 10, "哈希", "模型")
        assert len(result) == 16
        assert isinstance(result, str)

    def test_id_determinism(self):
        """compute_chunk_id should be deterministic."""
        id1 = compute_chunk_id("test.md", 1, 10, "abc123", "model-v1")
        id2 = compute_chunk_id("test.md", 1, 10, "abc123", "model-v1")
        assert id1 == id2

    def test_id_uniqueness(self):
        """compute_chunk_id should produce different IDs for different inputs."""
        id1 = compute_chunk_id("a.md", 1, 10, "abc", "model")
        id2 = compute_chunk_id("b.md", 1, 10, "abc", "model")
        id3 = compute_chunk_id("a.md", 2, 10, "abc", "model")
        assert id1 != id2
        assert id1 != id3
        assert id2 != id3