"""Unit tests for core helpers that don't require Milvus or an embedder."""

from __future__ import annotations


def test_scope_dataclass_defaults():
    from memsearch.core import Scope

    s = Scope(name="x", collection="c")
    assert s.name == "x"
    assert s.collection == "c"
    assert s.paths == []
    assert s.quota is None
    assert s.uri is None
    assert s.token is None


def _hit(chunk_hash: str, score: float, content: str = "x", source: str = "/x.md") -> dict:
    return {"chunk_hash": chunk_hash, "score": score, "content": content, "source": source}


def test_blend_dedups_keeps_higher_score():
    from memsearch.core import _blend_scope_results

    result = _blend_scope_results(
        per_scope=[
            ("project", [_hit("a", 0.5), _hit("b", 0.3)]),
            ("global", [_hit("a", 0.9)]),  # same chunk_hash, higher score
        ],
        scope_quotas={"project": None, "global": None},
        default_scope_name="project",
        scope_order=["project", "global"],
        top_k=10,
    )
    chunk_a = next(r for r in result if r["chunk_hash"] == "a")
    assert chunk_a["score"] == 0.9
    assert chunk_a["scope"] == "global"


def test_blend_all_quotas_caps_per_scope():
    from memsearch.core import _blend_scope_results

    result = _blend_scope_results(
        per_scope=[
            ("project", [_hit(f"p{i}", 1.0 - i * 0.01) for i in range(10)]),
            ("global", [_hit(f"g{i}", 0.5 - i * 0.01) for i in range(10)]),
        ],
        scope_quotas={"project": 3, "global": 2},
        default_scope_name="project",
        scope_order=["project", "global"],
        top_k=10,
    )
    by_scope = {}
    for r in result:
        by_scope.setdefault(r["scope"], 0)
        by_scope[r["scope"]] += 1
    assert by_scope == {"project": 3, "global": 2}


def test_blend_no_quotas_returns_global_top_k():
    from memsearch.core import _blend_scope_results

    result = _blend_scope_results(
        per_scope=[
            ("project", [_hit(f"p{i}", 0.5) for i in range(5)]),
            ("global", [_hit(f"g{i}", 0.9) for i in range(5)]),
        ],
        scope_quotas={"project": None, "global": None},
        default_scope_name="project",
        scope_order=["project", "global"],
        top_k=4,
    )
    assert len(result) == 4
    # global has higher scores; all 4 should be from global
    assert all(r["scope"] == "global" for r in result)


def test_blend_mixed_quotas():
    """Quota'd scopes filled first (cap), unquota'd share remainder by score."""
    from memsearch.core import _blend_scope_results

    result = _blend_scope_results(
        per_scope=[
            ("project", [_hit(f"p{i}", 0.95) for i in range(10)]),  # high score, no quota
            ("global", [_hit(f"g{i}", 0.50) for i in range(10)]),  # quota=2
        ],
        scope_quotas={"project": None, "global": 2},
        default_scope_name="project",
        scope_order=["project", "global"],
        top_k=5,
    )
    by_scope = {r["scope"] for r in result}
    counts = {s: sum(1 for r in result if r["scope"] == s) for s in by_scope}
    assert counts == {"project": 3, "global": 2}


def test_blend_quota_underfill_does_not_redistribute():
    from memsearch.core import _blend_scope_results

    result = _blend_scope_results(
        per_scope=[
            ("project", [_hit(f"p{i}", 0.9) for i in range(10)]),
            ("global", [_hit("g0", 0.5)]),  # only 1 hit, quota 5 → 4 empty slots
        ],
        scope_quotas={"project": 3, "global": 5},
        default_scope_name="project",
        scope_order=["project", "global"],
        top_k=10,
    )
    counts = {s: sum(1 for r in result if r["scope"] == s) for s in {"project", "global"}}
    assert counts == {"project": 3, "global": 1}  # NOT 3 + 5; project still capped


def test_blend_tiebreak_default_scope_wins():
    from memsearch.core import _blend_scope_results

    result = _blend_scope_results(
        per_scope=[
            ("project", [_hit("p", 0.5)]),
            ("global", [_hit("g", 0.5)]),  # equal score
        ],
        scope_quotas={"project": None, "global": None},
        default_scope_name="project",
        scope_order=["project", "global"],
        top_k=2,
    )
    assert result[0]["scope"] == "project"
    assert result[1]["scope"] == "global"
