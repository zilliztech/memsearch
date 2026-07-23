"""End-of-index flush wiring for ``milvus.flush_on_index``."""

from pathlib import Path

import pytest

from memsearch.core import MemSearch


class _StubEmbedder:
    """Deterministic embedder so indexing runs without network access."""

    model_name = "stub-model"
    batch_size = 8
    dimension = 4

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    d = tmp_path / "docs"
    d.mkdir()
    (d / "notes.md").write_text("# Title\n\nSome content worth indexing.\n")
    return d


def _make(tmp_path: Path, paths: list[str], *, flush_on_index: bool) -> tuple[MemSearch, list]:
    m = MemSearch(paths, milvus_uri=str(tmp_path / "flush_test.db"), embedding_api_key="test-key")
    m._embedder = _StubEmbedder()
    # Rebuild the store at the stub's dimension so real upserts succeed.
    m._store.close()
    from memsearch.store import MilvusStore

    m._store = MilvusStore(uri=str(tmp_path / "flush_test_stub.db"), dimension=4)
    m._flush_on_index = flush_on_index
    flush_calls: list[bool] = []
    m._store.flush = lambda: flush_calls.append(True)  # type: ignore[method-assign]
    return m, flush_calls


@pytest.mark.asyncio
async def test_index_flushes_once_when_enabled(tmp_path: Path, sample_dir: Path):
    m, flush_calls = _make(tmp_path, [str(sample_dir)], flush_on_index=True)
    try:
        n = await m.index()
        assert n > 0
        assert flush_calls == [True]
    finally:
        m.close()


@pytest.mark.asyncio
async def test_index_does_not_flush_by_default(tmp_path: Path, sample_dir: Path):
    m, flush_calls = _make(tmp_path, [str(sample_dir)], flush_on_index=False)
    try:
        n = await m.index()
        assert n > 0
        assert flush_calls == []
    finally:
        m.close()


@pytest.mark.asyncio
async def test_no_flush_when_nothing_indexed(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    m, flush_calls = _make(tmp_path, [str(empty)], flush_on_index=True)
    try:
        assert await m.index() == 0
        assert flush_calls == []
    finally:
        m.close()
