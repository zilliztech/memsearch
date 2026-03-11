from pathlib import Path

import pytest

from memsearch.core import MemSearch


class _DummyEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        assert len(texts) == 1
        return [[0.1, 0.2, 0.3]]


class _DummyStore:
    def __init__(self) -> None:
        self.last_filter_expr = None

    def search(self, query_embedding, *, query_text: str, top_k: int, filter_expr: str = ""):
        self.last_filter_expr = filter_expr
        return [{"content": "ok", "source": "x.md", "score": 0.9}]


@pytest.mark.asyncio
async def test_search_applies_source_prefix_filter(tmp_path: Path):
    mem = object.__new__(MemSearch)
    mem._embedder = _DummyEmbedder()
    store = _DummyStore()
    mem._store = store

    base = (tmp_path / "memory" / "product")
    base.mkdir(parents=True)

    await mem.search("price", source_prefix=base)

    expected_prefix = str(base.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    assert store.last_filter_expr == f'source like "{expected_prefix}%"'


@pytest.mark.asyncio
async def test_search_without_source_prefix_keeps_filter_empty():
    mem = object.__new__(MemSearch)
    mem._embedder = _DummyEmbedder()
    store = _DummyStore()
    mem._store = store

    await mem.search("anything")

    assert store.last_filter_expr == ""
