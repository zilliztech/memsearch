"""Tests for chunker heading handling."""

from __future__ import annotations

from memsearch.chunker import chunk_markdown


class TestChunkerHeadings:
    def test_single_heading(self):
        """Single heading should create one chunk."""
        text = "# Heading 1\n\nContent here."
        chunks = chunk_markdown(text)
        assert len(chunks) == 1
        assert chunks[0].heading == "Heading 1"
        assert chunks[0].heading_level == 1

    def test_multiple_headings(self):
        """Multiple headings should create multiple chunks."""
        text = "# H1\n\nContent 1\n\n## H2\n\nContent 2"
        chunks = chunk_markdown(text)
        assert len(chunks) == 2
        headings = [c.heading for c in chunks]
        assert "H1" in headings
        assert "H2" in headings

    def test_heading_levels(self):
        """Different heading levels should be tracked."""
        text = "# Level 1\n\nA\n\n## Level 2\n\nB\n\n### Level 3\n\nC"
        chunks = chunk_markdown(text)
        levels = [c.heading_level for c in chunks]
        assert 1 in levels
        assert 2 in levels
        assert 3 in levels

    def test_preamble_no_heading(self):
        """Content before first heading should have empty heading."""
        text = "Preamble content\n\n# First Heading\n\nMore content"
        chunks = chunk_markdown(text)
        # First chunk should be preamble
        assert any(c.heading == "" for c in chunks)

    def test_empty_heading_content(self):
        """Headings without content should be handled."""
        text = "# Heading\n\n# Next Heading"
        chunks = chunk_markdown(text)
        # Should handle gracefully
        assert len(chunks) >= 1