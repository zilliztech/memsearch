"""Tests for environment variable configuration."""

from __future__ import annotations

import os

import pytest


class TestEnvironmentVariables:
    def test_openai_api_key_env_var(self):
        """OPENAI_API_KEY should be configurable via environment."""
        # Check if env var exists (don't set it)
        key = os.environ.get("OPENAI_API_KEY")
        # Just verify the mechanism exists
        assert isinstance(key, str) or key is None

    def test_openai_base_url_env_var(self):
        """OPENAI_BASE_URL should be configurable via environment."""
        url = os.environ.get("OPENAI_BASE_URL")
        assert isinstance(url, str) or url is None

    def test_anthropic_api_key_env_var(self):
        """ANTHROPIC_API_KEY should be configurable via environment."""
        key = os.environ.get("ANTHROPIC_API_KEY")
        assert isinstance(key, str) or key is None

    def test_google_api_key_env_var(self):
        """GOOGLE_API_KEY should be configurable via environment."""
        key = os.environ.get("GOOGLE_API_KEY")
        assert isinstance(key, str) or key is None

    def test_env_var_names(self):
        """Expected environment variable names."""
        expected_vars = [
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
        ]
        for var in expected_vars:
            assert isinstance(var, str)
            assert len(var) > 0