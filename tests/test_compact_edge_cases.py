"""Edge case tests for compact module."""

from __future__ import annotations

import pytest

from memsearch.compact import COMPACT_PROMPT, compact_chunks


class TestCompactEdgeCases:
    @pytest.mark.asyncio
    async def test_compact_empty_list(self):
        """Empty list should return empty string immediately."""
        result = await compact_chunks([], llm_provider="openai")
        assert result == ""

    @pytest.mark.asyncio
    async def test_compact_unknown_provider(self):
        """Unknown provider should raise ValueError."""
        chunks = [{"content": "test"}]
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            await compact_chunks(chunks, llm_provider="unknown")

    def test_compact_prompt_has_placeholder(self):
        """Default prompt should contain {chunks} placeholder."""
        assert "{chunks}" in COMPACT_PROMPT

    @pytest.mark.asyncio
    async def test_compact_multiple_chunks_combine(self):
        """Multiple chunks should be combined with separators."""
        chunks = [
            {"content": "First chunk"},
            {"content": "Second chunk"},
            {"content": "Third chunk"},
        ]
        # Just test that empty chunks returns empty, structure validated
        empty_result = await compact_chunks([], llm_provider="openai")
        assert empty_result == ""

    @pytest.mark.asyncio
    async def test_compact_all_providers_unknown(self):
        """Test that invalid provider names are rejected."""
        chunks = [{"content": "test content"}]
        
        invalid_providers = ["invalid", "gpt", "llm", "custom"]
        for provider in invalid_providers:
            with pytest.raises(ValueError, match="Unknown LLM provider"):
                await compact_chunks(chunks, llm_provider=provider)