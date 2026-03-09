"""Tests for compact module prompt functionality."""

from __future__ import annotations

from memsearch.compact import COMPACT_PROMPT


class TestCompactPrompt:
    def test_compact_prompt_is_string(self):
        """COMPACT_PROMPT should be a string."""
        assert isinstance(COMPACT_PROMPT, str)

    def test_compact_prompt_contains_chunks_placeholder(self):
        """COMPACT_PROMPT should contain {chunks} placeholder."""
        assert "{chunks}" in COMPACT_PROMPT

    def test_compact_prompt_not_empty(self):
        """COMPACT_PROMPT should not be empty."""
        assert len(COMPACT_PROMPT) > 0

    def test_compact_prompt_contains_instructions(self):
        """COMPACT_PROMPT should contain summarization instructions."""
        assert "summary" in COMPACT_PROMPT.lower() or "compress" in COMPACT_PROMPT.lower()

    def test_compact_prompt_markdown_format(self):
        """COMPACT_PROMPT should mention markdown output."""
        assert "markdown" in COMPACT_PROMPT.lower()

    def test_compact_prompt_reasonable_length(self):
        """COMPACT_PROMPT should be a reasonable length."""
        assert 100 < len(COMPACT_PROMPT) < 2000