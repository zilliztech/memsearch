from __future__ import annotations

import sys
import types

import pytest

from memsearch.embeddings import DEFAULT_MODELS, get_provider


class DummyProvider:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_default_models_include_supported_providers() -> None:
    assert DEFAULT_MODELS["openai"] == "text-embedding-3-small"
    assert DEFAULT_MODELS["google"] == "gemini-embedding-001"
    assert DEFAULT_MODELS["onnx"] == "gpahal/bge-m3-onnx-int8"


def test_get_provider_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        get_provider("unknown")


def test_get_provider_instantiates_openai_with_optional_kwargs(monkeypatch) -> None:
    fake_module = types.SimpleNamespace(OpenAIEmbedding=DummyProvider)
    monkeypatch.setitem(sys.modules, "memsearch.embeddings.openai", fake_module)

    provider = get_provider(
        "openai",
        model="text-embedding-test",
        batch_size=64,
        base_url="https://example.invalid/v1",
        api_key="secret",
    )

    assert isinstance(provider, DummyProvider)
    assert provider.kwargs == {
        "model": "text-embedding-test",
        "batch_size": 64,
        "base_url": "https://example.invalid/v1",
        "api_key": "secret",
    }


def test_get_provider_ignores_openai_specific_kwargs_for_other_providers(monkeypatch) -> None:
    fake_module = types.SimpleNamespace(GoogleEmbedding=DummyProvider)
    monkeypatch.setitem(sys.modules, "memsearch.embeddings.google", fake_module)

    provider = get_provider(
        "google",
        model="gemini-test",
        batch_size=16,
        base_url="https://should-not-pass",
        api_key="should-not-pass",
    )

    assert isinstance(provider, DummyProvider)
    assert provider.kwargs == {
        "model": "gemini-test",
        "batch_size": 16,
    }


def test_get_provider_surfaces_install_hint_for_missing_extra(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "memsearch.embeddings.google", raising=False)

    import importlib

    real_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name == "memsearch.embeddings.google":
            raise ImportError("missing google extra")
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    with pytest.raises(ImportError, match=r"memsearch\[google\]"):
        get_provider("google")
