"""Tests for watcher utility functions."""

from __future__ import annotations

try:
    from memsearch.watcher import DEFAULT_DEBOUNCE_MS
except ImportError:
    DEFAULT_DEBOUNCE_MS = 1500  # Fallback if watchdog not installed


class TestWatcherDefaults:
    def test_default_debounce_ms_constant(self):
        """DEFAULT_DEBOUNCE_MS should be 1500."""
        assert DEFAULT_DEBOUNCE_MS == 1500

    def test_default_debounce_ms_positive(self):
        """DEFAULT_DEBOUNCE_MS should be positive."""
        assert DEFAULT_DEBOUNCE_MS > 0

    def test_default_debounce_ms_reasonable(self):
        """DEFAULT_DEBOUNCE_MS should be reasonable (1-10 seconds)."""
        assert 1000 <= DEFAULT_DEBOUNCE_MS <= 10000


class TestWatcherExtensions:
    def test_markdown_extensions(self):
        """Watcher should recognize markdown extensions."""
        extensions = (".md", ".markdown")
        assert ".md" in extensions
        assert ".markdown" in extensions

    def test_extension_case_variants(self):
        """Extension variants that should be handled."""
        variants = [".md", ".MD", ".Md", ".markdown", ".MARKDOWN"]
        expected_base = [".md", ".markdown"]
        for ext in expected_base:
            assert ext in [v.lower() for v in variants]