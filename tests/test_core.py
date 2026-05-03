"""Integration tests for the MemSearch core class.

Requires OPENAI_API_KEY to be set.
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)


@pytest.fixture
def mem(tmp_path: Path):
    from memsearch.core import MemSearch

    m = MemSearch(
        milvus_uri=str(tmp_path / "test.db"),
    )
    yield m
    m.close()


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    d = tmp_path / "docs"
    d.mkdir()
    (d / "notes.md").write_text(
        "# Python Tips\n\n"
        "Use list comprehensions for cleaner code.\n\n"
        "## Virtual Environments\n\n"
        "Always use virtual environments for project isolation.\n"
    )
    (d / "recipes.md").write_text(
        "# Cooking\n\n"
        "## Pasta\n\n"
        "Boil water, add salt, cook pasta for 10 minutes.\n\n"
        "## Salad\n\n"
        "Mix greens, tomatoes, and dressing.\n"
    )
    return d


@pytest.mark.asyncio
async def test_index_and_search(mem, sample_dir: Path):
    mem._paths = [str(sample_dir)]
    n = await mem.index()
    assert n > 0

    results = await mem.search("virtual environment python")
    assert len(results) > 0
    # The top result should be about Python / virtual environments
    top = results[0]
    assert "content" in top
    assert "score" in top


@pytest.mark.asyncio
async def test_index_single_file(mem, sample_dir: Path):
    n = await mem.index_file(sample_dir / "notes.md")
    assert n > 0

    results = await mem.search("list comprehension")
    assert len(results) > 0


# ---------------------------------------------------------------------------
# T7: multi-scope blended search tests
# ---------------------------------------------------------------------------

from memsearch.chunker import chunk_markdown, compute_chunk_id  # noqa: E402


async def _seed_scope(mem, store_name: str, file_path, content: str):
    """Write content to file_path and upsert its chunks into mem._stores[store_name]."""
    file_path.write_text(content)
    text = file_path.read_text()
    chunks = chunk_markdown(text, source=str(file_path), max_chunk_size=1500, overlap_lines=2)
    if not chunks:
        return
    embeddings = await mem._embedder.embed([c.content for c in chunks])
    model = mem._embedder.model_name
    rows = [
        {
            "chunk_hash": compute_chunk_id(c.source, c.start_line, c.end_line, c.content_hash, model),
            "content": c.content,
            "source": c.source,
            "heading": c.heading,
            "heading_level": c.heading_level,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "embedding": e,
        }
        for c, e in zip(chunks, embeddings, strict=True)
    ]
    mem._stores[store_name].upsert(rows)


@pytest.fixture
def two_scope_mem(tmp_path):
    from memsearch.core import MemSearch, Scope

    m = MemSearch(
        milvus_uri=str(tmp_path / "x.db"),
        collection="ms_proj",
        extra_scopes=[Scope(name="global", collection="ms_global", quota=2)],
        default_scope_quota=2,
    )
    yield m
    m.close()


@pytest.mark.asyncio
async def test_search_single_scope_no_scope_field(mem, sample_dir):
    """Single-scope MemSearch must NOT add a 'scope' field to results."""
    mem._paths = [str(sample_dir)]
    await mem.index()
    results = await mem.search("python", top_k=2)
    assert results
    assert "scope" not in results[0]


@pytest.mark.asyncio
async def test_search_multi_scope_tags_results(two_scope_mem, tmp_path):
    """Multi-scope: results carry 'scope' field; both scopes surface."""
    proj_dir = tmp_path / "proj"
    glob_dir = tmp_path / "glob"
    proj_dir.mkdir()
    glob_dir.mkdir()
    await _seed_scope(two_scope_mem, "project", proj_dir / "p.md", "# Project\n\nDeploy via uv.\n")
    await _seed_scope(two_scope_mem, "global", glob_dir / "g.md", "# Global\n\nUse 4-space indents.\n")

    results = await two_scope_mem.search("how do I deploy", top_k=4)
    scopes_seen = {r["scope"] for r in results}
    assert "project" in scopes_seen
    assert "scope" in results[0]


@pytest.mark.asyncio
async def test_search_only_scope_restriction(two_scope_mem, tmp_path):
    """only_scope=['project'] must exclude 'global'."""
    await _seed_scope(two_scope_mem, "project", tmp_path / "p.md", "# P\n\nFoo bar baz.\n")
    await _seed_scope(two_scope_mem, "global", tmp_path / "g.md", "# G\n\nFoo bar baz.\n")

    results = await two_scope_mem.search("foo", top_k=4, only_scope=["project"])
    assert results
    assert all(r["scope"] == "project" for r in results)


@pytest.mark.asyncio
async def test_search_only_scope_unknown_raises(two_scope_mem):
    with pytest.raises(ValueError, match="unknown scope"):
        await two_scope_mem.search("foo", top_k=4, only_scope=["nope"])


@pytest.mark.asyncio
async def test_index_routes_files_by_scope_paths(tmp_path):
    """Files under scope A's paths land in scope A's store; same for B."""
    from memsearch.core import MemSearch, Scope

    proj_dir = tmp_path / "proj"
    glob_dir = tmp_path / "glob"
    proj_dir.mkdir()
    glob_dir.mkdir()
    (proj_dir / "p.md").write_text("# Project\n\nProject-specific note.\n")
    (glob_dir / "g.md").write_text("# Global\n\nGlobal preference note.\n")

    m = MemSearch(
        milvus_uri=str(tmp_path / "x.db"),
        paths=[str(proj_dir)],
        collection="ms_proj",
        extra_scopes=[Scope(name="global", collection="ms_global", paths=[str(glob_dir)])],
    )
    try:
        await m.index()
        proj_results = m._stores["project"].search([0.0] * m._embedder.dimension, top_k=10)
        glob_results = m._stores["global"].search([0.0] * m._embedder.dimension, top_k=10)
        proj_sources = {r["source"] for r in proj_results}
        glob_sources = {r["source"] for r in glob_results}
        assert any("p.md" in s for s in proj_sources)
        assert not any("g.md" in s for s in proj_sources)
        assert any("g.md" in s for s in glob_sources)
        assert not any("p.md" in s for s in glob_sources)
    finally:
        m.close()


@pytest.mark.asyncio
async def test_index_skips_read_only_scope(tmp_path):
    """A scope with empty paths must not be touched by index()."""
    from memsearch.core import MemSearch, Scope

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    (proj_dir / "p.md").write_text("# P\n\nx.\n")
    m = MemSearch(
        milvus_uri=str(tmp_path / "x.db"),
        paths=[str(proj_dir)],
        collection="ms_proj",
        extra_scopes=[Scope(name="readonly", collection="ms_team", paths=[])],
    )
    try:
        n = await m.index()
        # Read-only scope's collection should be empty
        ro_results = m._stores["readonly"].search([0.0] * m._embedder.dimension, top_k=10)
        assert ro_results == []
        assert n > 0
    finally:
        m.close()
