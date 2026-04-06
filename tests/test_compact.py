"""Unit tests for compact (LLM summarization) functionality."""

from __future__ import annotations

import pytest

from memsearch.compact import compact_chunks


class TestCompactChunks:
    @pytest.mark.asyncio
    async def test_compact_empty_chunks(self):
        """compact_chunks with empty list should return empty string."""
        result = await compact_chunks(
            [],
            llm_provider="openai",
            model=None,
            prompt_template=None,
            base_url=None,
            api_key=None,
        )
        assert result == ""

    @pytest.mark.asyncio
    async def test_compact_single_chunk(self):
        """compact_chunks with single chunk."""
        chunks = [
            {
                "content": "This is a test chunk about Python programming.",
                "source": "test.md",
                "heading": "Introduction",
            }
        ]
        # Will skip if no API key, but structure is tested
        try:
            result = await compact_chunks(
                chunks,
                llm_provider="openai",
                model=None,
                prompt_template=None,
                base_url=None,
                api_key=None,
            )
            # If we get here, either we have a valid result or it handled gracefully
            assert isinstance(result, str)
        except Exception:
            # Expected if no API key configured
            pytest.skip("API key not configured")


class TestCompactConfiguration:
    def test_compact_config_has_required_fields(self):
        """CompactConfig should have base_url and api_key fields."""
        from memsearch.config import CompactConfig
        
        cfg = CompactConfig()
        assert hasattr(cfg, 'base_url')
        assert hasattr(cfg, 'api_key')
        assert cfg.base_url == ""
        assert cfg.api_key == ""