"""Tests for config environment variable resolution."""

from __future__ import annotations

import os

import pytest

from memsearch.config import resolve_env_ref


class TestEnvResolution:
    def test_resolve_plain_string(self):
        """Plain string should be returned as-is."""
        assert resolve_env_ref("plain_string") == "plain_string"

    def test_resolve_empty_string(self):
        """Empty string should be returned as-is."""
        assert resolve_env_ref("") == ""

    def test_resolve_known_env_var(self, monkeypatch):
        """Known env var reference should be resolved."""
        monkeypatch.setenv("TEST_VAR", "test_value")
        assert resolve_env_ref("env:TEST_VAR") == "test_value"

    def test_resolve_unknown_env_var(self):
        """Unknown env var should be returned as-is."""
        result = resolve_env_ref("env:UNKNOWN_VAR_XYZ")
        assert result == "env:UNKNOWN_VAR_XYZ"

    def test_resolve_partial_env_ref(self):
        """Partial env reference should be returned as-is."""
        assert resolve_env_ref("env:") == "env:"
        assert resolve_env_ref("env") == "env"

    def test_resolve_none(self):
        """None should be handled gracefully."""
        assert resolve_env_ref(None) is None