"""Watcher routes file events to the correct scope's store via path-prefix match."""

from __future__ import annotations

import os

import pytest

_needs_openai = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)


@_needs_openai
def test_resolve_scope_for_path_matches_longest_prefix(tmp_path):
    """The path-to-scope router picks the longest matching prefix."""
    from memsearch.core import MemSearch, Scope

    proj = tmp_path / "proj"
    glob = tmp_path / "glob"
    proj.mkdir()
    glob.mkdir()
    nested = proj / "nested"
    nested.mkdir()

    m = MemSearch(
        milvus_uri=str(tmp_path / "x.db"),
        paths=[str(proj)],
        collection="ms_proj",
        extra_scopes=[Scope(name="global", collection="ms_global", paths=[str(glob)])],
    )
    try:
        # File under proj/ resolves to "project"
        assert m._resolve_scope_for_path(proj / "p.md") == "project"
        # File under proj/nested/ also resolves to "project" (prefix match still works)
        assert m._resolve_scope_for_path(nested / "deep.md") == "project"
        # File under glob/ resolves to "global"
        assert m._resolve_scope_for_path(glob / "g.md") == "global"
        # File outside any scope's paths → returns None
        outside = tmp_path / "outside.md"
        assert m._resolve_scope_for_path(outside) is None
    finally:
        m.close()


def test_resolve_scope_longest_prefix_wins(tmp_path):
    """If two scopes' paths nest (e.g., one inside another), longest prefix wins."""
    # NOTE: validate_scope_paths normally rejects overlap; we test the resolver
    # directly here, bypassing the validator, because nested paths CAN occur
    # programmatically (e.g., a path passed to FileWatcher that happens to be
    # under two registered roots).
    from memsearch.core import MemSearch, Scope

    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)

    m = MemSearch.__new__(MemSearch)  # bypass __init__ to skip validate_scope_paths
    m._default_scope_name = "outer"
    m._paths = [str(parent)]
    m._extra_scopes = [Scope(name="inner", collection="x", paths=[str(child)])]

    file_in_child = child / "deep.md"
    # Longest-prefix match: file is under both parent and child;
    # child is the longer prefix so "inner" wins.
    assert m._resolve_scope_for_path(file_in_child) == "inner"
    file_in_parent_only = parent / "shallow.md"
    assert m._resolve_scope_for_path(file_in_parent_only) == "outer"


@_needs_openai
@pytest.mark.asyncio
async def test_watch_routes_modify_event_to_correct_scope(tmp_path):
    """A modify event for a file under a scope's paths upserts into that scope's store."""
    from memsearch.core import MemSearch, Scope

    proj = tmp_path / "proj"
    glob = tmp_path / "glob"
    proj.mkdir()
    glob.mkdir()
    (proj / "p.md").write_text("# P\n\nProject content.\n")
    (glob / "g.md").write_text("# G\n\nGlobal content.\n")

    m = MemSearch(
        milvus_uri=str(tmp_path / "x.db"),
        paths=[str(proj)],
        collection="ms_proj",
        extra_scopes=[Scope(name="global", collection="ms_global", paths=[str(glob)])],
    )
    try:
        # Simulate what _on_change does: route + index_file_for_scope
        n_proj = await m.index_file_for_scope(proj / "p.md", scope_name="project")
        n_glob = await m.index_file_for_scope(glob / "g.md", scope_name="global")
        assert n_proj > 0
        assert n_glob > 0
        # Verify routing: project store has p.md, NOT g.md; global store has g.md, NOT p.md
        proj_results = m._stores["project"].search([0.0] * m._embedder.dimension, top_k=10)
        glob_results = m._stores["global"].search([0.0] * m._embedder.dimension, top_k=10)
        assert any("p.md" in r["source"] for r in proj_results)
        assert not any("g.md" in r["source"] for r in proj_results)
        assert any("g.md" in r["source"] for r in glob_results)
        assert not any("p.md" in r["source"] for r in glob_results)
    finally:
        m.close()
