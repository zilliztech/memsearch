from __future__ import annotations

from scripts.benchmark_reranking import (
    score_query_results,
    source_diversity_stats,
    source_matches,
)


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
