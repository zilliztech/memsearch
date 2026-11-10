"""Exercise progressive recall against a real local index and transcript."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from memsearch import core as core_module
from memsearch.cli import cli


class FixtureEmbedding:
    dimension = 4
    model_name = "recall-workflow-fixture"
    batch_size = 8

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Keep retrieval deterministic without a network service or model download.
        return [[0.0, 1.0, 0.0, 0.0] if "rate limiting" in text else [1.0, 0.0, 0.0, 0.0] for text in texts]


@pytest.fixture
def indexed_memory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", tmp_path / "no-global.toml")
    monkeypatch.setattr(core_module, "get_provider", lambda *_args, **_kwargs: FixtureEmbedding())
    transcript = tmp_path / "conversation.jsonl"
    transcript.write_text(
        "\n".join(
            json.dumps(
                {
                    "type": "user",
                    "uuid": turn,
                    "timestamp": f"2026-10-20T10:0{i}:00Z",
                    "message": {"content": text},
                }
            )
            for i, (turn, text) in enumerate(
                [
                    ("login-turn", "Login redirects use rollback label REDIRECT-41."),
                    ("rate-turn", "API rate limiting uses rollback label LIMIT-73."),
                    ("cache-turn", "Cache eviction uses rollback label CACHE-92."),
                ],
                start=1,
            )
        )
        + "\n",
        encoding="utf-8",
    )
    source = tmp_path / "memory.md"
    source.write_text(
        "## Session 10:00\n\n"
        "### 10:01\n"
        f"<!-- session:fixture turn:login-turn transcript:{transcript} -->\n"
        "- Fixed login redirects.\n\n"
        "### 10:02\n"
        f"<!-- session:fixture turn:rate-turn transcript:{transcript} -->\n"
        "- Added API rate limiting; the exact rollback label is in the original conversation.\n\n"
        "### 10:03\n"
        f"<!-- session:fixture turn:cache-turn transcript:{transcript} -->\n"
        "- Configured cache eviction.\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    options = ["--milvus-uri", str(tmp_path / "index.db"), "--collection", "recall_workflow"]
    result = runner.invoke(cli, ["index", str(source), *options])
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli, ["search", "API rate limiting", "--top-k", "1", "--json-output", *options])
    assert result.exit_code == 0, result.output
    hit = json.loads(result.stdout)[0]
    assert hit["start_line"] == 7
    return runner, options, source, transcript, hit


def test_search_expand_transcript_stays_on_the_matching_turn(indexed_memory):
    runner, options, source, transcript, hit = indexed_memory
    result = runner.invoke(cli, ["expand", hit["chunk_hash"], "--json-output", *options])
    assert result.exit_code == 0, result.output
    expanded = json.loads(result.stdout)
    assert expanded["source"] == str(source)
    assert (expanded["start_line"], expanded["end_line"]) == (7, 10)
    assert expanded["anchor"] == {"session": "fixture", "turn": "rate-turn", "transcript": str(transcript)}
    assert "login-turn" not in expanded["content"]
    assert "cache-turn" not in expanded["content"]
    assert "LIMIT-73" not in expanded["content"]

    result = runner.invoke(
        cli,
        [
            "transcript",
            expanded["anchor"]["transcript"],
            "--turn",
            expanded["anchor"]["turn"],
            "--context",
            "0",
            "--json-output",
        ],
    )
    assert result.exit_code == 0, result.output
    turns = json.loads(result.stdout)
    assert [turn["uuid"] for turn in turns] == ["rate-turn"]
    assert "LIMIT-73" in turns[0]["text"]
    assert "REDIRECT-41" not in result.stdout
    assert "CACHE-92" not in result.stdout


def test_expand_warns_when_indexed_source_becomes_empty(indexed_memory):
    runner, options, source, _, hit = indexed_memory
    source.write_text("", encoding="utf-8")
    result = runner.invoke(cli, ["expand", hit["chunk_hash"], "--json-output", *options])
    assert result.exit_code == 0, result.output
    assert "past the end" in result.stderr
    assert "Re-run 'memsearch index <path>'" in result.stderr
    expanded = json.loads(result.stdout)
    assert expanded["content"] == ""
    assert "anchor" not in expanded
