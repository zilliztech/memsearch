"""Tests for embedding provider factory compatibility."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from click.testing import CliRunner

import memsearch.core as core
from memsearch.cli import cli
from memsearch.config import save_config
from memsearch.embeddings import get_provider


def _install_fake_provider(monkeypatch, module_path: str, class_name: str):
    module = ModuleType(module_path)

    class FakeProvider:
        def __init__(self, model: str = "default-model", *, batch_size: int = 0) -> None:
            self.model = model
            self.batch_size = batch_size

        @property
        def model_name(self) -> str:
            return self.model

        @property
        def dimension(self) -> int:
            return 8

    setattr(module, class_name, FakeProvider)
    monkeypatch.setitem(sys.modules, module_path, module)
    return FakeProvider


def test_get_provider_ignores_api_key_for_local_and_ollama(monkeypatch):
    """Providers without an api_key parameter should still be constructible."""
    _install_fake_provider(monkeypatch, "memsearch.embeddings.local", "LocalEmbedding")
    _install_fake_provider(monkeypatch, "memsearch.embeddings.ollama", "OllamaEmbedding")

    local = get_provider("local", api_key="stale-key")
    ollama = get_provider("ollama", api_key="stale-key")

    assert local.model_name == "default-model"
    assert ollama.model_name == "default-model"


def test_index_cli_accepts_stale_api_key_when_switching_to_local_provider(
    tmp_path: Path, monkeypatch
):
    """CLI indexing should not crash if a previous OpenAI key remains configured."""
    _install_fake_provider(monkeypatch, "memsearch.embeddings.local", "LocalEmbedding")

    project_cfg = tmp_path / "project.toml"
    note = tmp_path / "note.md"
    note.write_text("# Note\n\nLocal providers should ignore stale API keys.\n", encoding="utf-8")
    save_config({"embedding": {"provider": "local", "api_key": "sk-stale"}}, project_cfg)

    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", tmp_path / "global.toml")
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", project_cfg)

    class DummyStore:
        def __init__(self, *, uri: str, token: str | None, collection: str, dimension: int, description: str) -> None:
            self.uri = uri

        def close(self) -> None:
            return None

    async def fake_index(self, *, force: bool = False) -> int:
        return 0

    monkeypatch.setattr(core, "MilvusStore", DummyStore)
    monkeypatch.setattr(core.MemSearch, "index", fake_index)

    result = CliRunner().invoke(cli, ["index", str(note)])

    assert result.exit_code == 0
    assert "Indexed 0 chunks" in result.output
