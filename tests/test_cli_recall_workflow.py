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


def test_existing_memory_reindexes_under_a_new_default_collection(monkeypatch, tmp_path):
    """A collection-name correction rebuilds the index from untouched Markdown."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", tmp_path / "no-global.toml")
    monkeypatch.setattr(core_module, "get_provider", lambda *_args, **_kwargs: FixtureEmbedding())
    memory = tmp_path / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    source = memory / "2026-11-19.md"
    original = "# Existing session\n\n- Keep cedar-852 for 47 minutes.\n"
    source.write_text(original, encoding="utf-8")
    original_mtime = source.stat().st_mtime_ns
    runner = CliRunner()
    uri = ["--milvus-uri", str(tmp_path / "index.db")]
    # Default names for the same C:\repo project before and after normalization.
    old_collection = "ms_repo_52bba149"
    new_collection = "ms_repo_8ecf695f"

    def invoke(*args):
        result = runner.invoke(cli, [*args, *uri])
        assert result.exit_code == 0, result.output
        return result

    invoke("index", str(memory), "--default-collection", old_collection)
    # The startup index command does not need --force or a data migration.
    invoke("index", str(memory), "--default-collection", new_collection)
    for collection in (new_collection, old_collection):
        result = invoke("search", "cedar-852", "--json-output", "--default-collection", collection)
        hits = json.loads(result.stdout)
        assert len(hits) == 1
        assert hits[0]["source"] == str(source)
        assert "47 minutes" in hits[0]["content"]
        result = invoke("expand", hits[0]["chunk_hash"], "--json-output", "--default-collection", collection)
        assert "cedar-852" in json.loads(result.stdout)["content"]

    # An explicit existing collection continues to override the new default.
    (tmp_path / ".memsearch.toml").write_text(f'[milvus]\ncollection = "{old_collection}"\n', encoding="utf-8")
    result = runner.invoke(cli, ["config", "get", "milvus.collection", "--default-collection", new_collection])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == old_collection
    assert source.read_text(encoding="utf-8") == original
    assert source.stat().st_mtime_ns == original_mtime
