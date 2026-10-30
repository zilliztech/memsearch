"""The embedding provider is only built when vectors are actually needed.

An index run over unchanged files must not load the model (issue #828).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import memsearch.core as core
from memsearch.core import MemSearch
from memsearch.embeddings import DEFAULT_MODELS
from memsearch.store import DimensionMismatchError


class _FakeEmbedder:
    def __init__(self, model: str, dim: int) -> None:
        self._model = model
        self._dim = dim

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def batch_size(self) -> int:
        return 32

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (self._dim - 1) for _ in texts]


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> tuple[list[dict], dict[str, int]]:
    calls: list[dict] = []
    dims = {"onnx": 4}

    def fake_get_provider(name: str = "openai", *, model: str | None = None, **kwargs) -> _FakeEmbedder:
        calls.append({"name": name, "model": model})
        return _FakeEmbedder(model if model is not None else DEFAULT_MODELS[name], dims.get(model or name, 4))

    monkeypatch.setattr(core, "get_provider", fake_get_provider)
    return calls, dims


def _ms(tmp_path: Path, docs: Path, model: str | None = None) -> MemSearch:
    return MemSearch(
        [docs],
        embedding_provider="onnx",
        embedding_model=model,
        milvus_uri=str(tmp_path / "lazy.db"),
    )


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    d = tmp_path / "docs"
    d.mkdir()
    (d / "a.md").write_text("# A\n\nRedis caching notes.\n")
    return d


@pytest.mark.asyncio
async def test_unchanged_index_does_not_build_provider(
    tmp_path: Path, docs: Path, provider: tuple[list[dict], dict[str, int]]
):
    provider_calls = provider[0]
    first = _ms(tmp_path, docs)
    assert provider_calls == []  # construction alone never loads the model
    assert await first.index() > 0
    assert len(provider_calls) == 1
    first._store.close()

    second = _ms(tmp_path, docs)
    assert await second.index() == 0
    assert len(provider_calls) == 1  # nothing new to embed -> no provider


@pytest.mark.asyncio
async def test_changed_file_still_embeds(tmp_path: Path, docs: Path, provider: tuple[list[dict], dict[str, int]]):
    provider_calls = provider[0]
    first = _ms(tmp_path, docs)
    await first.index()
    first._store.close()

    (docs / "a.md").write_text("# A\n\nRedis caching notes.\n\n## B\n\nNew section.\n")
    second = _ms(tmp_path, docs)
    assert await second.index() > 0
    assert len(provider_calls) == 2


@pytest.mark.asyncio
async def test_dimension_mismatch_aborts_and_keeps_chunks(
    tmp_path: Path, docs: Path, provider: tuple[list[dict], dict[str, int]]
):
    dims = provider[1]
    first = _ms(tmp_path, docs)
    await first.index()
    source = str((docs / "a.md").resolve())
    before = first._store.hashes_by_source(source)
    first._store.close()

    dims["other-model"] = 8
    second = _ms(tmp_path, docs, model="other-model")
    with pytest.raises(DimensionMismatchError, match="Embedding dimension mismatch"):
        await second.index()
    assert second._store.hashes_by_source(source) == before


def test_model_name_resolves_without_provider(tmp_path: Path, docs: Path, provider: tuple[list[dict], dict[str, int]]):
    provider_calls = provider[0]
    assert _ms(tmp_path, docs)._model_name == DEFAULT_MODELS["onnx"]
    assert _ms(tmp_path, docs, model="custom/model")._model_name == "custom/model"
    assert provider_calls == []


def test_unknown_provider_still_fails_at_construction(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        MemSearch([], embedding_provider="nope", milvus_uri=str(tmp_path / "x.db"))


@pytest.mark.asyncio
async def test_provider_load_failure_aborts_the_run(
    tmp_path: Path, docs: Path, provider: tuple[list[dict], dict[str, int]], monkeypatch: pytest.MonkeyPatch
):
    first = _ms(tmp_path, docs)
    await first.index()
    first._store.close()

    def broken_get_provider(*_args, **_kwargs):
        raise RuntimeError("OPENAI_API_KEY is not set")

    (docs / "b.md").write_text("# B\n\nNeeds embedding.\n")
    monkeypatch.setattr(core, "get_provider", broken_get_provider)
    second = _ms(tmp_path, docs)
    # Collection exists, so the load happens per file; it must still abort the run.
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await second.index()
