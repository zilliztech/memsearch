"""Unit tests for file watcher components."""

from __future__ import annotations

from pathlib import Path

from memsearch.watcher import _MarkdownHandler


class TestMarkdownHandler:
    def test_is_markdown_recognizes_extensions(self):
        """Handler should recognize .md and .markdown files."""
        handler = _MarkdownHandler(callback=lambda e, p: None)
        
        assert handler._is_markdown("/path/to/file.md") is True
        assert handler._is_markdown("/path/to/file.markdown") is True
        assert handler._is_markdown("/path/to/file.MD") is True
        assert handler._is_markdown("/path/to/file.txt") is False
        assert handler._is_markdown("/path/to/file.py") is False
        assert handler._is_markdown("/path/to/file") is False

    def test_custom_extensions(self):
        """Handler should accept custom extensions."""
        handler = _MarkdownHandler(
            callback=lambda e, p: None,
            extensions=(".md", ".mkd")
        )
        
        assert handler._is_markdown("/path/to/file.md") is True
        assert handler._is_markdown("/path/to/file.mkd") is True
        assert handler._is_markdown("/path/to/file.markdown") is False

    def test_handler_creation(self):
        """Handler should initialize with callback."""
        called_with = []
        def callback(event_type, path):
            called_with.append((event_type, path))
        
        handler = _MarkdownHandler(callback=callback)
        assert handler._callback == callback
        assert handler._extensions == (".md", ".markdown")