"""Edge case tests for transcript parser."""

from __future__ import annotations

from memsearch.chunker import compute_chunk_id
from memsearch.transcript import (
    _extract_time,
    _strip_hook_tags,
    _summarize_tool_input,
)


class TestTranscriptEdgeCases:
    def test_extract_time_various_formats(self):
        """Time extraction from different timestamp formats."""
        # Standard format
        assert _extract_time("2026-03-09T15:30:45Z") == "15:30:45"
        # With milliseconds
        assert _extract_time("2026-03-09T15:30:45.123Z") == "15:30:45"
        # No timezone
        assert _extract_time("2026-03-09T15:30:45") == "15:30:45"
        # Just time portion
        assert _extract_time("15:30:45") == "15:30:45"

    def test_strip_hook_tags_various(self):
        """Strip various hook tag formats."""
        assert _strip_hook_tags("<command>rm -rf</command>keep this") == "keep this"
        assert _strip_hook_tags("<file>/path/to/file</file>") == ""
        assert _strip_hook_tags("no tags here") == "no tags here"
        assert _strip_hook_tags("") == ""

    def test_summarize_tool_input_empty(self):
        """Summarize with empty input."""
        result = _summarize_tool_input("Read", {})
        assert result == "Read()"

    def test_summarize_tool_input_long(self):
        """Summarize with long input values."""
        long_path = "/path/to/very/long/directory/structure" * 5
        result = _summarize_tool_input("Read", {"file_path": long_path})
        assert "Read" in result
        assert long_path in result

    def test_summarize_tool_input_special_chars(self):
        """Summarize with special characters."""
        result = _summarize_tool_input("Edit", {"file": "file with spaces & symbols.md"})
        assert "Edit" in result
        assert "spaces & symbols" in result


class TestComputeChunkIdEdgeCases:
    def test_chunk_id_empty_content_hash(self):
        """Compute chunk ID with empty content hash."""
        result = compute_chunk_id("test.md", 1, 10, "", "model")
        # Should still produce valid hash
        assert len(result) == 16
        assert result.isalnum()

    def test_chunk_id_unicode_paths(self):
        """Compute chunk ID with unicode in path."""
        result = compute_chunk_id("文档.md", 1, 10, "hash123", "模型")
        assert len(result) == 16
        assert result.isalnum()

    def test_chunk_id_large_line_numbers(self):
        """Compute chunk ID with large line numbers."""
        result = compute_chunk_id("test.md", 999999, 1000000, "hash", "model")
        assert len(result) == 16

    def test_chunk_id_negative_line_numbers(self):
        """Compute chunk ID with negative line numbers."""
        result = compute_chunk_id("test.md", -1, -1, "hash", "model")
        assert len(result) == 16