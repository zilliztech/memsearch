from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import scripts.benchmark_reranking as benchmark
from scripts.benchmark_reranking import (
    build_parser,
    build_search_command,
    load_query_manifest,
    main,
    render_markdown_report,
    run_benchmark,
    score_query_results,
    source_diversity_stats,
    source_matches,
    write_outputs,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reranking"


def test_source_matches_uses_path_component_suffix_matching() -> None:
    assert source_matches("/memory/report.md", "port.md") is False
    assert source_matches("/memory/right.md", "right.md") is True
    assert source_matches("/repo/memory/right.md", "memory/right.md") is True


def test_expected_source_scoring_finds_best_rank_and_hit_cutoffs() -> None:
    results = [
        {"source": "/memory/old.md"},
        {"source": "/memory/right.md"},
    ]

    score = score_query_results(results, expected_sources=["/memory/right.md"])

    assert score.hit_at_1 is False
    assert score.hit_at_3 is True
    assert score.best_rank == 2


def test_source_diversity_counts_unique_sources_and_repeats() -> None:
    results = [
        {"source": "/linear/export-a.md"},
        {"source": "/linear/export-a.md"},
        {"source": "/memory/2026-06-06.md"},
    ]

    stats = source_diversity_stats(results)

    assert stats.unique_sources == 2
    assert stats.max_repeats_for_one_source == 2


def test_load_query_manifest_accepts_required_json_shape() -> None:
    queries = load_query_manifest(FIXTURE_DIR / "benchmark.json")

    assert [query.id for query in queries] == ["rerank-runner", "duplicate-source"]
    assert queries[0].query == "reranking benchmark runner"
    assert queries[0].expected_sources == ("memory/reranking-plan.md",)
    assert queries[0].notes == "Find the approved reranking benchmark implementation plan."


def test_parser_accepts_approved_cli_shape_without_candidate_k() -> None:
    args = build_parser().parse_args(
        [
            "--queries",
            "benchmark.json",
            "--collection",
            "ms_memsearch_ae2d4f9b",
            "--top-k",
            "5",
            "--reranker-model",
            "Alibaba-NLP/gte-reranker-modernbert-base",
            "--out",
            "outputs/reranking-benchmark.json",
        ]
    )

    assert args.queries == Path("benchmark.json")
    assert args.collection == "ms_memsearch_ae2d4f9b"
    assert args.top_k == 5
    assert args.reranker_model == "Alibaba-NLP/gte-reranker-modernbert-base"
    assert args.out == Path("outputs/reranking-benchmark.json")
    assert not hasattr(args, "candidate_k")


def test_parser_rejects_candidate_k() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "--queries",
                "benchmark.json",
                "--collection",
                "ms_memsearch_ae2d4f9b",
                "--top-k",
                "5",
                "--candidate-k",
                "15",
                "--out",
                "outputs/reranking-benchmark.json",
            ]
        )


def test_build_search_command_uses_memsearch_search_json_collection_and_no_candidate_k() -> None:
    command = build_search_command(
        "reranking benchmark runner",
        collection="ms_memsearch_ae2d4f9b",
        top_k=5,
        reranker_model="Alibaba-NLP/gte-reranker-modernbert-base",
    )

    assert command == [
        "memsearch",
        "search",
        "reranking benchmark runner",
        "--top-k",
        "5",
        "--json-output",
        "--collection",
        "ms_memsearch_ae2d4f9b",
        "--reranker-model",
        "Alibaba-NLP/gte-reranker-modernbert-base",
    ]
    assert "--candidate-k" not in command


def test_build_search_command_disables_global_reranker_for_plain_mode() -> None:
    command = build_search_command(
        "reranking benchmark runner",
        collection="ms_memsearch_ae2d4f9b",
        top_k=5,
        reranker_model=None,
    )

    assert command[-2:] == ["--reranker-model", ""]


def test_summarise_mode_uses_nearest_rank_p95_for_two_values() -> None:
    summary = benchmark.summarise_mode(
        [
            {"hit_at_1": True, "hit_at_3": True, "hit_at_5": True, "duplicate_source_count": 0, "latency_seconds": 1.0},
            {
                "hit_at_1": True,
                "hit_at_3": True,
                "hit_at_5": True,
                "duplicate_source_count": 0,
                "latency_seconds": 10.0,
            },
        ]
    )

    assert summary["p95_latency_seconds"] == 10.0


def test_load_query_manifest_rejects_coerced_fields(tmp_path: Path) -> None:
    manifest = tmp_path / "benchmark.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "id": 123,
                    "query": "reranking benchmark runner",
                    "expected_sources": ["memory/reranking-plan.md"],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="id must be a non-empty string"):
        load_query_manifest(manifest)


def test_load_query_manifest_allows_missing_notes(tmp_path: Path) -> None:
    manifest = tmp_path / "benchmark.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "id": "rerank-runner",
                    "query": "reranking benchmark runner",
                    "expected_sources": ["memory/reranking-plan.md"],
                }
            ]
        ),
        encoding="utf-8",
    )

    queries = load_query_manifest(manifest)

    assert queries[0].notes == ""


def test_fixture_mode_scores_and_reports_without_live_memsearch() -> None:
    queries = load_query_manifest(FIXTURE_DIR / "benchmark.json")

    report = run_benchmark(
        queries,
        collection="ms_memsearch_ae2d4f9b",
        top_k=5,
        reranker_model="Alibaba-NLP/gte-reranker-modernbert-base",
        fixture_dir=FIXTURE_DIR,
    )

    assert report["modes"] == ["plain", "onnx-rerank"]
    assert report["warmup"] == {
        "mode": "onnx-rerank",
        "ran": False,
        "model": "Alibaba-NLP/gte-reranker-modernbert-base",
        "latency_seconds": None,
        "cache_state": "unknown",
    }
    assert report["overall_scores"]["plain"]["hit_at_1"] == 0.0
    assert report["overall_scores"]["plain"]["hit_at_3"] == 1.0
    assert report["overall_scores"]["plain"]["hit_at_5"] == 1.0
    assert report["overall_scores"]["onnx-rerank"]["hit_at_1"] == 1.0
    assert report["overall_scores"]["onnx-rerank"]["duplicate_source_count"] == 1
    assert report["overall_scores"]["onnx-rerank"]["median_latency_seconds"] is not None
    assert report["overall_scores"]["onnx-rerank"]["p95_latency_seconds"] is not None
    assert report["per_query"][0]["winner"] == "onnx-rerank"
    assert report["per_query"][0]["diffs"] == [
        {
            "mode": "onnx-rerank",
            "baseline": "plain",
            "best_rank_delta": -1,
            "duplicate_source_delta": 0,
            "hit_at_1_delta": 1,
            "hit_at_3_delta": 0,
            "hit_at_5_delta": 0,
        }
    ]
    assert report["per_query"][1]["diffs"] == [
        {
            "mode": "onnx-rerank",
            "baseline": "plain",
            "best_rank_delta": -1,
            "duplicate_source_delta": 1,
            "hit_at_1_delta": 1,
            "hit_at_3_delta": 0,
            "hit_at_5_delta": 0,
        }
    ]
    assert report["regressions"] == [
        {
            "query_id": "duplicate-source",
            "mode": "onnx-rerank",
            "type": "duplicate_source",
            "reason": "duplicate_source_count increased",
            "plain_best_rank": 2,
            "mode_best_rank": 1,
            "plain_duplicate_source_count": 0,
            "mode_duplicate_source_count": 1,
        }
    ]
    assert report["duplicate_source_warnings"] == [
        {
            "query_id": "duplicate-source",
            "mode": "onnx-rerank",
            "duplicate_source_count": 1,
            "max_repeats_for_one_source": 2,
        }
    ]

    markdown = render_markdown_report(report)
    for heading in [
        "## Overall scores",
        "## Per-query winners",
        "## Regressions",
        "## Duplicate-source warnings",
        "## Recommendation",
    ]:
        assert heading in markdown
    assert "Fixture/plain benchmark only" not in markdown
    assert "Live warm-up did not run" in markdown
    assert "diff vs plain for onnx-rerank: best_rank_delta=-1" in markdown
    assert "`onnx-rerank` duplicate sources increased from 0 to 1" in markdown
    assert "regressed from rank 2 to 1" not in markdown


def test_live_mode_records_reranker_warmup_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_run_live_query(
        query: str, *, collection: str, top_k: int, reranker_model: str | None = None
    ) -> list[dict[str, str]]:
        assert collection == "ms_memsearch_ae2d4f9b"
        assert top_k == 5
        calls.append((query, reranker_model))
        return [{"source": "memory/reranking-plan.md"}]

    monkeypatch.setattr(benchmark, "run_live_query", fake_run_live_query)
    queries = load_query_manifest(FIXTURE_DIR / "benchmark.json")[:1]

    report = benchmark.run_benchmark(
        queries,
        collection="ms_memsearch_ae2d4f9b",
        top_k=5,
        reranker_model="Alibaba-NLP/gte-reranker-modernbert-base",
    )

    assert calls == [
        ("reranking benchmark runner", None),
        ("reranking benchmark runner", "Alibaba-NLP/gte-reranker-modernbert-base"),
        ("reranking benchmark runner", "Alibaba-NLP/gte-reranker-modernbert-base"),
    ]
    assert report["warmup"]["mode"] == "onnx-rerank"
    assert report["warmup"]["ran"] is True
    assert report["warmup"]["model"] == "Alibaba-NLP/gte-reranker-modernbert-base"
    assert report["warmup"]["latency_seconds"] >= 0
    assert report["warmup"]["cache_state"] == "unknown"


def test_write_outputs_creates_json_and_default_markdown(tmp_path: Path) -> None:
    queries = load_query_manifest(FIXTURE_DIR / "benchmark.json")
    report = run_benchmark(
        queries,
        collection="ms_memsearch_ae2d4f9b",
        top_k=5,
        reranker_model="Alibaba-NLP/gte-reranker-modernbert-base",
        fixture_dir=FIXTURE_DIR,
    )
    json_out = tmp_path / "outputs" / "reranking-benchmark.json"

    written_json, written_markdown = write_outputs(report, json_out)

    assert written_json == json_out
    assert written_markdown == tmp_path / "outputs" / "reranking-benchmark.md"
    assert json.loads(written_json.read_text(encoding="utf-8"))["collection"] == "ms_memsearch_ae2d4f9b"
    assert "## Overall scores" in written_markdown.read_text(encoding="utf-8")


def test_main_writes_explicit_markdown_output(tmp_path: Path) -> None:
    json_out = tmp_path / "reranking-benchmark.json"
    markdown_out = tmp_path / "custom-report.md"

    exit_code = main(
        [
            "--queries",
            str(FIXTURE_DIR / "benchmark.json"),
            "--collection",
            "ms_memsearch_ae2d4f9b",
            "--top-k",
            "5",
            "--reranker-model",
            "Alibaba-NLP/gte-reranker-modernbert-base",
            "--fixture-dir",
            str(FIXTURE_DIR),
            "--out",
            str(json_out),
            "--markdown-out",
            str(markdown_out),
        ]
    )

    assert exit_code == 0
    assert json_out.exists()
    assert markdown_out.exists()


def test_main_reports_common_errors_without_traceback(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "--queries",
            str(tmp_path / "missing.json"),
            "--collection",
            "ms_memsearch_ae2d4f9b",
            "--top-k",
            "5",
            "--out",
            str(tmp_path / "reranking-benchmark.json"),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err.startswith("Error: ")
    assert "Traceback" not in captured.err


def test_main_reports_subprocess_context_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run_benchmark(*args: object, **kwargs: object) -> dict[str, object]:
        raise subprocess.CalledProcessError(
            2,
            ["memsearch", "search"],
            output="partial output",
            stderr="reranker failed",
        )

    monkeypatch.setattr(benchmark, "run_benchmark", fake_run_benchmark)

    exit_code = main(
        [
            "--queries",
            str(FIXTURE_DIR / "benchmark.json"),
            "--collection",
            "ms_memsearch_ae2d4f9b",
            "--top-k",
            "5",
            "--out",
            str(tmp_path / "reranking-benchmark.json"),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "exit code 2" in captured.err
    assert "stderr: reranker failed" in captured.err
    assert "stdout: partial output" in captured.err
    assert "Traceback" not in captured.err
