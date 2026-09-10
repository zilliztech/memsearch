"""Unit tests for store module utilities."""

from __future__ import annotations

from memsearch.store import _escape_filter_value


class TestStoreUtilities:
    def test_escape_filter_value_no_special_chars(self):
        """String without special chars should remain unchanged."""
        result = _escape_filter_value("simple_string")
        assert result == "simple_string"

    def test_escape_filter_value_with_backslash(self):
        """Backslash should be escaped."""
        result = _escape_filter_value("path\\to\\file")
        assert result == "path\\\\to\\\\file"

    def test_escape_filter_value_with_quotes(self):
        """Double quotes should be escaped."""
        result = _escape_filter_value('say "hello"')
        assert result == 'say \\"hello\\"'

    def test_escape_filter_value_with_both(self):
        """Both backslash and quotes should be escaped."""
        result = _escape_filter_value('path\\to\\file "name"')
        assert "\\\\" in result
        assert '\\"' in result

    def test_escape_filter_value_empty_string(self):
        """Empty string should remain empty."""
        result = _escape_filter_value("")
        assert result == ""

    def test_escape_filter_value_unicode(self):
        """Unicode characters should be preserved."""
        result = _escape_filter_value("文件路径")
        assert result == "文件路径"