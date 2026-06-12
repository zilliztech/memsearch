from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class QueryScore:
    hit_at_1: bool
    hit_at_3: bool
    best_rank: int | None


@dataclass(frozen=True)
class SourceDiversity:
    unique_sources: int
    max_repeats_for_one_source: int


@dataclass(frozen=True)
class QuerySpec:
    id: str
    query: str
    expected_sources: tuple[str, ...]
    notes: str = ""


def _source_parts(source: str) -> list[str]:
    return [part for part in str(source or "").replace("\\", "/").split("/") if part]


def source_matches(actual: str, expected: str) -> bool:
    actual_parts = _source_parts(actual)
    expected_parts = _source_parts(expected)

    return bool(actual_parts and expected_parts and actual_parts[-len(expected_parts) :] == expected_parts)


def score_query_results(results: Sequence[Mapping[str, object]], expected_sources: Sequence[str]) -> QueryScore:
    best_rank = None

    for index, result in enumerate(results, start=1):
        actual_source = _result_source(result)
        if any(source_matches(actual_source, expected_source) for expected_source in expected_sources):
            best_rank = index
            break

    return QueryScore(
        hit_at_1=best_rank == 1,
        hit_at_3=best_rank is not None and best_rank <= 3,
        best_rank=best_rank,
    )


def source_diversity_stats(results: Sequence[Mapping[str, object]]) -> SourceDiversity:
    sources = (_result_source(result) for result in results)
    source_counts = Counter(source for source in sources if source)

    return SourceDiversity(
        unique_sources=len(source_counts),
        max_repeats_for_one_source=max(source_counts.values(), default=0),
    )


def _result_source(result: Mapping[str, object]) -> str:
    return str(result.get("source") or result.get("path") or result.get("file") or "")


def load_query_manifest(path: Path) -> list[QuerySpec]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Query manifest must be a JSON list of objects.")
    if not data:
        raise ValueError("Query manifest must contain at least one query.")

    queries: list[QuerySpec] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Query manifest item {index} must be an object.")

        missing = {"id", "query", "expected_sources"} - set(item)
        if missing:
            raise ValueError(f"Query manifest item {index} missing fields: {', '.join(sorted(missing))}.")

        query_id = item["id"]
        if not isinstance(query_id, str) or not query_id:
            raise ValueError(f"Query manifest item {index} id must be a non-empty string.")
        if query_id in seen_ids:
            raise ValueError(f"Query manifest item {index} duplicates id: {query_id}.")
        seen_ids.add(query_id)

        query_text = item["query"]
        if not isinstance(query_text, str) or not query_text:
            raise ValueError(f"Query manifest item {index} query must be a non-empty string.")

        expected_sources = item["expected_sources"]
        if (
            not isinstance(expected_sources, list)
            or not expected_sources
            or not all(isinstance(source, str) for source in expected_sources)
        ):
            raise ValueError(f"Query manifest item {index} expected_sources must be a non-empty list of strings.")

        notes = item.get("notes", "")
        if not isinstance(notes, str):
            raise ValueError(f"Query manifest item {index} notes must be a string when present.")

        queries.append(
            QuerySpec(
                id=query_id,
                query=query_text,
                expected_sources=tuple(expected_sources),
                notes=notes,
            )
        )

    return queries


def build_search_command(query: str, *, collection: str, top_k: int, reranker_model: str | None = None) -> list[str]:
    command = [
        "memsearch",
        "search",
        query,
        "--top-k",
        str(top_k),
        "--json-output",
        "--collection",
        collection,
    ]
    command.extend(["--reranker-model", "" if reranker_model is None else reranker_model])
    return command


def run_live_query(
    query: str, *, collection: str, top_k: int, reranker_model: str | None = None
) -> list[dict[str, Any]]:
    completed = subprocess.run(
        build_search_command(query, collection=collection, top_k=top_k, reranker_model=reranker_model),
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(completed.stdout)
    if not isinstance(data, list):
        raise ValueError("memsearch search --json-output must return a JSON list.")
    return [_normalise_result(result) for result in data]


def load_fixture_results(fixture_dir: Path, mode: str, query_id: str) -> list[dict[str, Any]]:
    path = fixture_dir / mode / f"{query_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Fixture result snapshot must be a JSON list: {path}")
    return [_normalise_result(result) for result in data]


def _normalise_result(result: object) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("Search results must be JSON objects.")
    return dict(result)


def duplicate_source_count(results: Sequence[Mapping[str, object]]) -> int:
    stats = source_diversity_stats(results)
    non_empty_sources = sum(1 for result in results if _result_source(result))
    return max(0, non_empty_sources - stats.unique_sources)


def evaluate_results(
    query: QuerySpec, mode: str, results: Sequence[Mapping[str, object]], latency_seconds: float
) -> dict[str, Any]:
    score = score_query_results(results, query.expected_sources)
    diversity = source_diversity_stats(results)
    duplicate_count = duplicate_source_count(results)
    return {
        "query_id": query.id,
        "query": query.query,
        "notes": query.notes,
        "mode": mode,
        "hit_at_1": score.hit_at_1,
        "hit_at_3": score.hit_at_3,
        "hit_at_5": score.best_rank is not None and score.best_rank <= 5,
        "best_rank": score.best_rank,
        "duplicate_source_count": duplicate_count,
        "unique_sources": diversity.unique_sources,
        "max_repeats_for_one_source": diversity.max_repeats_for_one_source,
        "latency_seconds": latency_seconds,
        "top_sources": [_result_source(result) for result in results],
    }


def summarise_mode(query_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    count = len(query_reports)
    latencies = [float(report["latency_seconds"]) for report in query_reports]
    return {
        "queries": count,
        "hit_at_1": _rate(query_reports, "hit_at_1"),
        "hit_at_3": _rate(query_reports, "hit_at_3"),
        "hit_at_5": _rate(query_reports, "hit_at_5"),
        "duplicate_source_count": sum(int(report["duplicate_source_count"]) for report in query_reports),
        "median_latency_seconds": statistics.median(latencies) if latencies else None,
        "p95_latency_seconds": _p95(latencies),
    }


def _rate(query_reports: Sequence[Mapping[str, Any]], key: str) -> float | None:
    if not query_reports:
        return None
    return sum(1 for report in query_reports if report[key]) / len(query_reports)


def _p95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = max(0, min(len(sorted_values) - 1, math.ceil(0.95 * len(sorted_values)) - 1))
    return sorted_values[index]


def better_report(left: Mapping[str, Any], right: Mapping[str, Any]) -> Mapping[str, Any]:
    left_rank = _rank_value(left["best_rank"])
    right_rank = _rank_value(right["best_rank"])
    if left_rank != right_rank:
        return left if left_rank < right_rank else right

    left_dupes = int(left["duplicate_source_count"])
    right_dupes = int(right["duplicate_source_count"])
    if left_dupes != right_dupes:
        return left if left_dupes < right_dupes else right

    return left if float(left["latency_seconds"]) <= float(right["latency_seconds"]) else right


def build_report(
    queries: Sequence[QuerySpec],
    mode_results: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    top_k: int,
    collection: str,
    fixture_dir: Path | None = None,
    warmup: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    per_query: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    duplicate_warnings: list[dict[str, Any]] = []
    recommendation_basis: list[str] = []

    for query in queries:
        reports = [
            dict(report) for reports in mode_results.values() for report in reports if report["query_id"] == query.id
        ]
        winner = reports[0]
        for report in reports[1:]:
            winner = dict(better_report(winner, report))

        plain = next((report for report in reports if report["mode"] == "plain"), None)
        for report in reports:
            if int(report["duplicate_source_count"]) > 0:
                duplicate_warnings.append(
                    {
                        "query_id": query.id,
                        "mode": report["mode"],
                        "duplicate_source_count": report["duplicate_source_count"],
                        "max_repeats_for_one_source": report["max_repeats_for_one_source"],
                    }
                )
            if plain and report["mode"] != "plain":
                regressions.extend(
                    {"query_id": query.id, "mode": report["mode"], **regression}
                    for regression in _regressions_for_report(report, plain)
                )

        recommendation_basis.append(
            f"{query.id}: {winner['mode']} wins with best_rank={winner['best_rank']} "
            f"and duplicate_source_count={winner['duplicate_source_count']}."
        )
        per_query.append(
            {
                "query_id": query.id,
                "query": query.query,
                "winner": winner["mode"],
                "diffs": _query_diffs(reports),
                "results": reports,
            }
        )

    overall_scores = {mode: summarise_mode(reports) for mode, reports in mode_results.items()}
    recommendation = _recommendation(overall_scores, regressions, recommendation_basis)
    return {
        "top_k": top_k,
        "collection": collection,
        "fixture_dir": str(fixture_dir) if fixture_dir else None,
        "warmup": dict(warmup) if warmup else _no_warmup_metadata(),
        "modes": list(mode_results),
        "overall_scores": overall_scores,
        "per_query": per_query,
        "regressions": regressions,
        "duplicate_source_warnings": duplicate_warnings,
        "recommendation": recommendation,
        "recommendation_basis": recommendation_basis,
    }


def _rank_value(rank: object) -> int:
    return int(rank) if rank is not None else 1_000_000


def _no_warmup_metadata(*, model: str | None = None) -> dict[str, Any]:
    return {
        "mode": "onnx-rerank" if model else None,
        "ran": False,
        "model": model,
        "latency_seconds": None,
        "cache_state": "unknown",
    }


def _regressions_for_report(report: Mapping[str, Any], plain: Mapping[str, Any]) -> list[dict[str, Any]]:
    regressions: list[dict[str, Any]] = []
    if _rank_value(report["best_rank"]) > _rank_value(plain["best_rank"]):
        regressions.append(
            {
                "type": "rank",
                "reason": "best_rank worsened",
                "plain_best_rank": plain["best_rank"],
                "mode_best_rank": report["best_rank"],
                "plain_duplicate_source_count": plain["duplicate_source_count"],
                "mode_duplicate_source_count": report["duplicate_source_count"],
            }
        )
    if int(report["duplicate_source_count"]) > int(plain["duplicate_source_count"]):
        regressions.append(
            {
                "type": "duplicate_source",
                "reason": "duplicate_source_count increased",
                "plain_best_rank": plain["best_rank"],
                "mode_best_rank": report["best_rank"],
                "plain_duplicate_source_count": plain["duplicate_source_count"],
                "mode_duplicate_source_count": report["duplicate_source_count"],
            }
        )
    return regressions


def _query_diffs(reports: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    plain = next((report for report in reports if report["mode"] == "plain"), None)
    if plain is None:
        return []

    return [
        {
            "mode": report["mode"],
            "baseline": "plain",
            "best_rank_delta": _best_rank_delta(report["best_rank"], plain["best_rank"]),
            "duplicate_source_delta": int(report["duplicate_source_count"]) - int(plain["duplicate_source_count"]),
            "hit_at_1_delta": _bool_delta(report["hit_at_1"], plain["hit_at_1"]),
            "hit_at_3_delta": _bool_delta(report["hit_at_3"], plain["hit_at_3"]),
            "hit_at_5_delta": _bool_delta(report["hit_at_5"], plain["hit_at_5"]),
        }
        for report in reports
        if report["mode"] != "plain"
    ]


def _best_rank_delta(report_rank: object, plain_rank: object) -> int | None:
    if report_rank is None or plain_rank is None:
        return None
    return int(report_rank) - int(plain_rank)


def _bool_delta(report_value: object, plain_value: object) -> int:
    return int(bool(report_value)) - int(bool(plain_value))


def _recommendation(
    overall_scores: Mapping[str, Mapping[str, Any]], regressions: Sequence[Mapping[str, Any]], basis: Sequence[str]
) -> str:
    if "onnx-rerank" not in overall_scores:
        return (
            "Fixture/plain benchmark only. Use this report to validate scoring/reporting, not live retrieval quality."
        )
    if regressions:
        return "Do not promote ONNX reranking yet. Review regressions before enabling it broadly."

    plain = overall_scores.get("plain", {})
    rerank = overall_scores["onnx-rerank"]
    rerank_hit_at_3 = float(rerank.get("hit_at_3") or 0.0)
    plain_hit_at_3 = float(plain.get("hit_at_3") or 0.0)
    if rerank_hit_at_3 <= plain_hit_at_3:
        return "Keep plain retrieval as the baseline. ONNX reranking did not improve hit@3."
    latency_basis = _latency_basis(rerank, plain)
    return "ONNX reranking is a candidate for Task 3 live validation if latency is acceptable. " + latency_basis


def _latency_basis(rerank: Mapping[str, Any], plain: Mapping[str, Any]) -> str:
    return (
        f"p95 latency plain={_fmt_seconds(plain.get('p95_latency_seconds'))}, "
        f"onnx-rerank={_fmt_seconds(rerank.get('p95_latency_seconds'))}."
    )


def run_benchmark(
    queries: Sequence[QuerySpec],
    *,
    collection: str,
    top_k: int,
    reranker_model: str | None = None,
    fixture_dir: Path | None = None,
) -> dict[str, Any]:
    mode_names = ["plain", "onnx-rerank"] if reranker_model else ["plain"]
    mode_results: dict[str, list[dict[str, Any]]] = {mode: [] for mode in mode_names}

    if fixture_dir:
        for mode in mode_names:
            for query in queries:
                started = time.perf_counter()
                results = load_fixture_results(fixture_dir, mode, query.id)
                latency = time.perf_counter() - started
                mode_results[mode].append(evaluate_results(query, mode, results, latency))
        return build_report(
            queries,
            mode_results,
            top_k=top_k,
            collection=collection,
            fixture_dir=fixture_dir,
            warmup=_no_warmup_metadata(model=reranker_model),
        )

    for query in queries:
        started = time.perf_counter()
        results = run_live_query(query.query, collection=collection, top_k=top_k)
        mode_results["plain"].append(evaluate_results(query, "plain", results, time.perf_counter() - started))

    if reranker_model:
        warmup = _warm_up_reranker(
            queries[0].query if queries else "warmup", collection=collection, top_k=top_k, model=reranker_model
        )
        for query in queries:
            started = time.perf_counter()
            results = run_live_query(query.query, collection=collection, top_k=top_k, reranker_model=reranker_model)
            mode_results["onnx-rerank"].append(
                evaluate_results(query, "onnx-rerank", results, time.perf_counter() - started)
            )
    else:
        warmup = _no_warmup_metadata()

    return build_report(queries, mode_results, top_k=top_k, collection=collection, warmup=warmup)


def _warm_up_reranker(query: str, *, collection: str, top_k: int, model: str) -> dict[str, Any]:
    started = time.perf_counter()
    run_live_query(query, collection=collection, top_k=top_k, reranker_model=model)
    return {
        "mode": "onnx-rerank",
        "ran": True,
        "model": model,
        "latency_seconds": time.perf_counter() - started,
        "cache_state": "unknown",
    }


def write_outputs(report: Mapping[str, Any], json_out: Path, markdown_out: Path | None = None) -> tuple[Path, Path]:
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md_out = markdown_out or json_out.with_suffix(".md")
    md_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.write_text(render_markdown_report(report), encoding="utf-8")
    return json_out, md_out


def render_markdown_report(report: Mapping[str, Any]) -> str:
    lines = [
        "# MemSearch reranking benchmark",
        "",
        f"Collection: `{report['collection']}`",
        f"Top K: `{report['top_k']}`",
        "",
        "## Warm-up",
        "",
        _format_warmup(report["warmup"]),
        "",
        "## Overall scores",
        "",
        "| Mode | hit@1 | hit@3 | hit@5 | duplicate sources | median latency | p95 latency |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode, scores in report["overall_scores"].items():
        lines.append(
            f"| {mode} | {_fmt_rate(scores['hit_at_1'])} | {_fmt_rate(scores['hit_at_3'])} | "
            f"{_fmt_rate(scores['hit_at_5'])} | {scores['duplicate_source_count']} | "
            f"{_fmt_seconds(scores['median_latency_seconds'])} | {_fmt_seconds(scores['p95_latency_seconds'])} |"
        )

    lines.extend(["", "## Per-query winners", ""])
    for item in report["per_query"]:
        lines.append(f"- `{item['query_id']}`: `{item['winner']}`")
        lines.extend(
            (
                f"  - diff vs {diff['baseline']} for {diff['mode']}: "
                f"best_rank_delta={diff['best_rank_delta']}, "
                f"duplicate_source_delta={diff['duplicate_source_delta']}, "
                f"hit@1_delta={diff['hit_at_1_delta']}, "
                f"hit@3_delta={diff['hit_at_3_delta']}, "
                f"hit@5_delta={diff['hit_at_5_delta']}"
            )
            for diff in item["diffs"]
        )
        lines.extend(
            (
                f"  - {result['mode']}: best_rank={result['best_rank']}, "
                f"hit@5={result['hit_at_5']}, duplicates={result['duplicate_source_count']}, "
                f"latency={_fmt_seconds(result['latency_seconds'])}"
            )
            for result in item["results"]
        )

    lines.extend(["", "## Regressions", ""])
    if report["regressions"]:
        lines.extend((_format_regression(item)) for item in report["regressions"])
    else:
        lines.append("- None.")

    lines.extend(["", "## Duplicate-source warnings", ""])
    if report["duplicate_source_warnings"]:
        lines.extend(
            (
                f"- `{item['query_id']}` / `{item['mode']}`: "
                f"{item['duplicate_source_count']} duplicate source result(s), "
                f"max repeats {item['max_repeats_for_one_source']}."
            )
            for item in report["duplicate_source_warnings"]
        )
    else:
        lines.append("- None.")

    lines.extend(["", "## Recommendation", "", str(report["recommendation"]), ""])
    lines.extend(["Basis:", ""])
    lines.extend(f"- {item}" for item in report["recommendation_basis"])
    lines.append("")
    return "\n".join(lines)


def _fmt_rate(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.0%}"


def _format_warmup(warmup: Mapping[str, Any]) -> str:
    if not warmup["ran"]:
        return (
            f"- Live warm-up did not run. mode={warmup['mode']}, model={warmup['model']}, "
            f"cache_state={warmup['cache_state']}."
        )
    return (
        f"- Live warm-up ran for `{warmup['mode']}` with model `{warmup['model']}` in "
        f"{_fmt_seconds(warmup['latency_seconds'])}. cache_state={warmup['cache_state']}."
    )


def _format_regression(item: Mapping[str, Any]) -> str:
    if item["type"] == "duplicate_source":
        return (
            f"- `{item['query_id']}`: `{item['mode']}` duplicate sources increased from "
            f"{item['plain_duplicate_source_count']} to {item['mode_duplicate_source_count']}."
        )
    return (
        f"- `{item['query_id']}`: `{item['mode']}` rank regressed from "
        f"{item['plain_best_rank']} to {item['mode_best_rank']}."
    )


def _fmt_seconds(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.3f}s"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark MemSearch plain retrieval against ONNX reranking.")
    parser.add_argument("--queries", required=True, type=Path, help="JSON query manifest.")
    parser.add_argument("--collection", required=True, help="Milvus collection name for live MemSearch runs.")
    parser.add_argument("--top-k", required=True, type=int, help="Number of search results to request.")
    parser.add_argument("--reranker-model", default=None, help="ONNX reranker model to benchmark.")
    parser.add_argument("--out", required=True, type=Path, help="JSON report output path.")
    parser.add_argument("--markdown-out", default=None, type=Path, help="Markdown report output path.")
    parser.add_argument(
        "--fixture-dir",
        default=None,
        type=Path,
        help="Replay saved result snapshots from this directory instead of calling live MemSearch.",
    )
    return parser


def _write_error(message: str) -> None:
    sys.stderr.write(f"{message}\n")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        queries = load_query_manifest(args.queries)
        report = run_benchmark(
            queries,
            collection=args.collection,
            top_k=args.top_k,
            reranker_model=args.reranker_model,
            fixture_dir=args.fixture_dir,
        )
        write_outputs(report, args.out, args.markdown_out)
    except subprocess.CalledProcessError as exc:
        _write_error(f"Error: command failed with exit code {exc.returncode}: {' '.join(exc.cmd)}")
        if exc.stderr:
            _write_error(f"stderr: {exc.stderr.strip()}")
        if exc.stdout:
            _write_error(f"stdout: {exc.stdout.strip()}")
        return 1
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        _write_error(f"Error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
