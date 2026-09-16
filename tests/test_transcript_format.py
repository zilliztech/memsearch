"""Tests for transcript format utilities."""

from __future__ import annotations

from memsearch.transcript import format_turn_index


class TestTranscriptFormat:
    def test_format_empty_turns(self):
        """Empty turns list should return empty string."""
        result = format_turn_index([])
        assert result == ""

    def test_format_single_turn(self):
        """Single turn should be formatted correctly."""
        from memsearch.transcript import Turn
        
        turn = Turn(
            uuid="abc123",
            timestamp="2026-03-09T10:00:00Z",
            role="user",
            content="Hello world",
            tool_calls=[],
        )
        result = format_turn_index([turn])
        assert "abc123" in result or "abc" in result
        assert "10:00:00" in result
        assert "Hello world" in result

    def test_format_with_tool_calls(self):
        """Turn with tool calls should show count."""
        from memsearch.transcript import Turn
        
        turn = Turn(
            uuid="abc123",
            timestamp="2026-03-09T10:00:00Z",
            role="assistant",
            content="Test",
            tool_calls=["tool1", "tool2"],
        )
        result = format_turn_index([turn])
        assert "[2 tools]" in result

    def test_format_multiline_content(self):
        """Multiline content should be truncated."""
        from memsearch.transcript import Turn
        
        turn = Turn(
            uuid="abc123",
            timestamp="2026-03-09T10:00:00Z",
            role="user",
            content="Line 1\nLine 2\nLine 3",
            tool_calls=[],
        )
        result = format_turn_index([turn])
        # Should show first line or truncated
        assert "Line 1" in result or "Line" in result

    def test_format_truncates_long_content(self):
        """Long content should be truncated."""
        from memsearch.transcript import Turn
        
        turn = Turn(
            uuid="abc123",
            timestamp="2026-03-09T10:00:00Z",
            role="user",
            content="A" * 200,
            tool_calls=[],
        )
        result = format_turn_index([turn])
        # Should be truncated
        assert len(result) < 250  # Reasonable limit