from __future__ import annotations

from click.testing import CliRunner

from memsearch import cli as cli_module
from memsearch.cli import cli
from memsearch.config import MemSearchConfig, load_config_file


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
    cfg.reranker.model = ""

    kwargs = cli_module._cfg_to_memsearch_kwargs(cfg)

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
        "reranker_model": "",
    }


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
        "watch": {"debounce_ms": 300},
    }
