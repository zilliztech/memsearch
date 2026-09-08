from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from memsearch import cli as cli_module
from memsearch.cli import cli
from memsearch.config import MemSearchConfig, load_config_file, save_config


def test_build_cli_overrides_maps_only_non_none_values() -> None:
    overrides = cli_module._build_cli_overrides(
        provider="google",
        model="gemini-embedding-001",
        batch_size=64,
        base_url=None,
        api_key="env:EMBED_KEY",
        collection="custom_chunks",
        milvus_uri="http://localhost:19530",
        milvus_token=None,
        llm_provider="gemini",
        llm_model="gemini-3-flash-preview",
        prompt_file="prompts/compact.txt",
        llm_base_url="https://llm.example.com",
        llm_api_key="env:LLM_KEY",
        max_chunk_size=2048,
        overlap_lines=3,
        debounce_ms=250,
        reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
    )

    assert overrides == {
        "embedding": {
            "provider": "google",
            "model": "gemini-embedding-001",
            "batch_size": 64,
            "api_key": "env:EMBED_KEY",
        },
        "milvus": {
            "collection": "custom_chunks",
            "uri": "http://localhost:19530",
        },
        "compact": {
            "llm_provider": "gemini",
            "llm_model": "gemini-3-flash-preview",
            "prompt_file": "prompts/compact.txt",
            "base_url": "https://llm.example.com",
            "api_key": "env:LLM_KEY",
        },
        "chunking": {
            "max_chunk_size": 2048,
            "overlap_lines": 3,
        },
        "watch": {
            "debounce_ms": 250,
        },
        "reranker": {
            "model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        },
    }


def test_cfg_to_memsearch_kwargs_translates_resolved_config() -> None:
    cfg = MemSearchConfig()
    cfg.embedding.provider = "local"
    cfg.embedding.model = "all-MiniLM-L6-v2"
    cfg.embedding.batch_size = 32
    cfg.embedding.base_url = "http://embeddings.local"
    cfg.embedding.api_key = "env:LOCAL_KEY"
    cfg.milvus.uri = "http://milvus.local:19530"
    cfg.milvus.token = "milvus-token"
    cfg.milvus.collection = "team_notes"
    cfg.chunking.max_chunk_size = 1800
    cfg.chunking.overlap_lines = 4
    cfg.indexing.ignore_files = [".gitignore"]
    cfg.indexing.exclude = ["generated/**"]
    cfg.reranker.model = ""

    kwargs = cli_module._cfg_to_memsearch_kwargs(
        cfg,
        extra_ignore_files=(".cursorignore", ".gitignore"),
        extra_exclude=("drafts/**",),
    )

    assert kwargs == {
        "embedding_provider": "local",
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_batch_size": 32,
        "embedding_base_url": "http://embeddings.local",
        "embedding_api_key": "env:LOCAL_KEY",
        "milvus_uri": "http://milvus.local:19530",
        "milvus_token": "milvus-token",
        "collection": "team_notes",
        "max_chunk_size": 1800,
        "overlap_lines": 4,
        "ignore_files": [".gitignore", ".cursorignore"],
        "exclude": ["generated/**", "drafts/**"],
        "reranker_model": "",
    }


def test_search_default_collection_respects_config_and_explicit_cli(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The integration fallback must stay below config and explicit CLI input."""
    from memsearch import config as config_module
    from memsearch import core as core_module

    global_cfg = tmp_path / "global.toml"
    project_cfg = tmp_path / ".memsearch.toml"
    save_config({"milvus": {"collection": "global_collection"}}, global_cfg)
    save_config({"milvus": {"collection": "project_collection"}}, project_cfg)
    monkeypatch.setattr(config_module, "GLOBAL_CONFIG_PATH", global_cfg)
    monkeypatch.setattr(config_module, "PROJECT_CONFIG_PATH", project_cfg)

    created_collections: list[str] = []

    class FakeMemSearch:
        def __init__(self, **kwargs) -> None:
            created_collections.append(kwargs["collection"])

        async def search(self, _query, *, top_k, source_prefix):
            return []

        def close(self) -> None:
            pass

    monkeypatch.setattr(core_module, "MemSearch", FakeMemSearch)
    runner = CliRunner()

    configured = runner.invoke(cli, ["search", "query", "--default-collection", "derived_collection"])
    explicit = runner.invoke(
        cli,
        [
            "search",
            "query",
            "--default-collection",
            "derived_collection",
            "--collection",
            "explicit_collection",
        ],
    )

    assert configured.exit_code == 0, configured.output
    assert explicit.exit_code == 0, explicit.output
    assert created_collections == ["project_collection", "explicit_collection"]


def test_config_init_project_writes_only_allowlisted_keys(monkeypatch) -> None:
    cfg = MemSearchConfig()
    cfg.milvus.collection = "notes"
    cfg.embedding.batch_size = 16
    cfg.chunking.max_chunk_size = 2048
    cfg.chunking.overlap_lines = 4
    cfg.watch.debounce_ms = 300
    cfg.plugins.codex.project_review.enabled = True
    cfg.prompts.project_review = "/tmp/project-review.txt"

    monkeypatch.setattr(cli_module, "resolve_config", lambda: cfg)

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["config", "init", "--project"], input="\n\n\n\n\n")

        assert result.exit_code == 0
        data = load_config_file(".memsearch.toml")

    assert data == {
        "milvus": {"collection": "notes"},
        "embedding": {"batch_size": 16},
        "chunking": {"max_chunk_size": 2048, "overlap_lines": 4},
        "indexing": {"ignore_files": [".gitignore"], "exclude": []},
        "watch": {"debounce_ms": 300},
    }


def test_config_init_preserves_explicitly_disabled_ignore_files(monkeypatch) -> None:
    cfg = MemSearchConfig()
    monkeypatch.setattr(cli_module, "resolve_config", lambda: cfg)

    runner = CliRunner()
    with runner.isolated_filesystem():
        save_config({"indexing": {"ignore_files": [], "exclude": []}}, ".memsearch.toml")
        result = runner.invoke(cli, ["config", "init", "--project"], input="\n\n\n\n\n")

        assert result.exit_code == 0
        data = load_config_file(".memsearch.toml")

    assert data["indexing"] == {"ignore_files": [], "exclude": []}


def test_config_get_prints_lowercase_booleans(monkeypatch) -> None:
    monkeypatch.setattr(cli_module, "get_config_value", lambda _key: False)

    runner = CliRunner()
    result = runner.invoke(cli, ["config", "get", "plugins.claude-code.summarize.enabled"])

    assert result.exit_code == 0
    assert result.output.strip() == "false"


def test_config_get_default_collection_respects_explicit_config(tmp_path: Path, monkeypatch) -> None:
    from memsearch import config as config_module

    global_cfg = tmp_path / "global.toml"
    project_cfg = tmp_path / ".memsearch.toml"
    save_config({"milvus": {"collection": "global_collection"}}, global_cfg)
    save_config({"milvus": {"collection": "project_collection"}}, project_cfg)
    monkeypatch.setattr(config_module, "GLOBAL_CONFIG_PATH", global_cfg)
    monkeypatch.setattr(config_module, "PROJECT_CONFIG_PATH", project_cfg)

    result = CliRunner().invoke(
        cli,
        ["config", "get", "milvus.collection", "--default-collection", "derived_collection"],
    )

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "project_collection"


def test_config_list_json_output_preserves_config_types(monkeypatch) -> None:
    cfg = MemSearchConfig()
    cfg.embedding.provider = "onnx"
    cfg.embedding.batch_size = 32
    cfg.indexing.ignore_files = [".gitignore"]
    cfg.plugins.claude_code.summarize.enabled = False
    monkeypatch.setattr(cli_module, "resolve_config", lambda: cfg)

    result = CliRunner().invoke(cli, ["config", "list", "--resolved", "--json-output"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["embedding"]["provider"] == "onnx"
    assert data["embedding"]["batch_size"] == 32
    assert data["indexing"]["ignore_files"] == [".gitignore"]
    assert data["plugins"]["claude-code"]["summarize"]["enabled"] is False


def test_config_list_default_collection_uses_resolved_priority(tmp_path: Path, monkeypatch) -> None:
    from memsearch import config as config_module

    global_cfg = tmp_path / "global.toml"
    project_cfg = tmp_path / ".memsearch.toml"
    save_config({}, global_cfg)
    save_config({}, project_cfg)
    monkeypatch.setattr(config_module, "GLOBAL_CONFIG_PATH", global_cfg)
    monkeypatch.setattr(config_module, "PROJECT_CONFIG_PATH", project_cfg)

    result = CliRunner().invoke(
        cli,
        ["config", "list", "--resolved", "--json-output", "--default-collection", "derived_collection"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["milvus"]["collection"] == "derived_collection"
