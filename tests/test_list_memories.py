"""Tests for listing indexed memories."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from click.testing import CliRunner

from memsearch.cli import cli
from memsearch.core import MemSearch
from memsearch.store import MilvusStore


def _vector(dim: int, index: int) -> list[float]:
    values = [0.0] * dim
    values[index] = 1.0
    return values


def _sample_chunks(source_a: str, source_b: str, *, dim: int = 4) -> list[dict]:
    return [
        {
            "embedding": _vector(dim, 0),
            "content": "Investigated Rust setup and fixed cargo PATH.",
            "source": source_b,
            "heading": "Rust setup",
            "chunk_hash": "h-rust",
            "heading_level": 2,
            "start_line": 8,
            "end_line": 12,
        },
        {
            "embedding": _vector(dim, 1),
            "content": "Documented Redis TTL decision for the cache layer.",
            "source": source_a,
            "heading": "Redis cache",
            "chunk_hash": "h-redis",
            "heading_level": 2,
            "start_line": 4,
            "end_line": 7,
        },
        {
            "embedding": _vector(dim, 2),
            "content": "Captured deployment notes for staging rollout.",
            "source": source_a,
            "heading": "Deployment",
            "chunk_hash": "h-deploy",
            "heading_level": 2,
            "start_line": 20,
            "end_line": 24,
        },
    ]


def test_store_list_memories_orders_and_filters(tmp_path: Path) -> None:
    db = tmp_path / "memories.db"
    source_a = str((tmp_path / "memory" / "2026-04-01.md").resolve())
    source_b = str((tmp_path / "memory" / "2026-04-02.md").resolve())

    store = MilvusStore(uri=str(db), dimension=4)
    store.upsert(_sample_chunks(source_a, source_b))

    all_memories = store.list_memories()
    assert [row["chunk_hash"] for row in all_memories] == ["h-redis", "h-deploy", "h-rust"]

    limited = store.list_memories(limit=2)
    assert [row["chunk_hash"] for row in limited] == ["h-redis", "h-deploy"]

    filtered = store.list_memories(source_prefix=tmp_path / "memory")
    assert [row["chunk_hash"] for row in filtered] == ["h-redis", "h-deploy", "h-rust"]

    other = store.list_memories(source_prefix=tmp_path / "other")
    assert other == []

    store.close()


def test_core_list_memories(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    source_a = str((tmp_path / "memory" / "2026-04-01.md").resolve())
    source_b = str((tmp_path / "memory" / "2026-04-02.md").resolve())

    mem = MemSearch(milvus_uri=str(db), embedding_api_key="test-key")
    mem._store.upsert(_sample_chunks(source_a, source_b, dim=1536))

    memories = asyncio.run(mem.list_memories(limit=2))
    assert [row["chunk_hash"] for row in memories] == ["h-redis", "h-deploy"]

    mem.close()


def test_cli_list_outputs_text_and_json(tmp_path: Path) -> None:
    db = tmp_path / "cli.db"
    source_a = str((tmp_path / "memory" / "2026-04-01.md").resolve())
    source_b = str((tmp_path / "memory" / "2026-04-02.md").resolve())

    store = MilvusStore(uri=str(db), dimension=4)
    store.upsert(_sample_chunks(source_a, source_b))
    store.close()

    runner = CliRunner()

    text_result = runner.invoke(cli, ["list", "--milvus-uri", str(db), "--limit", "2"])
    assert text_result.exit_code == 0
    assert "--- Memory 1 ---" in text_result.output
    assert "Heading: Redis cache" in text_result.output
    assert "Chunk: h-redis" in text_result.output
    assert "Chunk: h-deploy" in text_result.output

    json_result = runner.invoke(
        cli,
        [
            "list",
            "--milvus-uri",
            str(db),
            "--source-prefix",
            str(tmp_path / "memory"),
            "--json-output",
        ],
    )
    assert json_result.exit_code == 0
    payload = json.loads(json_result.output)
    assert [row["chunk_hash"] for row in payload] == ["h-redis", "h-deploy", "h-rust"]
