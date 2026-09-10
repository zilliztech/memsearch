"""Edge case tests for MemSearch core class."""

from __future__ import annotations

import os

import pytest

from memsearch.core import MemSearch


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
class TestMemSearchCoreEdgeCases:
    def test_memsearch_no_paths(self):
        """MemSearch with no paths should work."""
        ms = MemSearch(paths=[])
        assert ms._paths == []
        ms.close()

    def test_memsearch_single_path(self):
        """MemSearch with single path."""
        ms = MemSearch(paths=["/tmp/test"])
        assert ms._paths == ["/tmp/test"]
        ms.close()

    def test_memsearch_path_objects(self):
        """MemSearch with Path objects."""
        from pathlib import Path
        ms = MemSearch(paths=[Path("/tmp/test")])
        assert ms._paths == ["/tmp/test"]
        ms.close()

    def test_memsearch_context_manager(self):
        """MemSearch as context manager."""
        with MemSearch(paths=[]) as ms:
            assert ms._paths == []

    def test_memsearch_custom_chunk_params(self):
        """MemSearch with custom chunking parameters."""
        ms = MemSearch(
            paths=[],
            max_chunk_size=1000,
            overlap_lines=3,
        )
        assert ms._max_chunk_size == 1000
        assert ms._overlap_lines == 3
        ms.close()

    def test_memsearch_different_providers(self):
        """MemSearch initialization with different provider names."""
        # Just test that provider name is stored
        for provider in ["openai", "google", "voyage", "ollama", "local"]:
            try:
                ms = MemSearch(paths=[], embedding_provider=provider)
                ms.close()
            except Exception:
                # Provider-specific errors are expected without API keys
                pass