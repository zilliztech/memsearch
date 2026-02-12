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
