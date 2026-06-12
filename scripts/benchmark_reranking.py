from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryScore:
    hit_at_1: bool
    hit_at_3: bool
    best_rank: int | None


@dataclass(frozen=True)
class SourceDiversity:
    unique_sources: int
    max_repeats_for_one_source: int


def _source_parts(source: str) -> list[str]:
    return [part for part in str(source or "").replace("\\", "/").split("/") if part]


def source_matches(actual: str, expected: str) -> bool:
    actual_parts = _source_parts(actual)
    expected_parts = _source_parts(expected)

    return bool(
        actual_parts
        and expected_parts
        and actual_parts[-len(expected_parts) :] == expected_parts
    )


def score_query_results(
    results: Sequence[Mapping[str, object]], expected_sources: Sequence[str]
) -> QueryScore:
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
