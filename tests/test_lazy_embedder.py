"""The embedding provider is only built when vectors are actually needed.

An index run over unchanged files must not load the model (issue #828).
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import memsearch.core as core
from memsearch.core import MemSearch
from memsearch.embeddings import _PROVIDERS, DEFAULT_MODELS
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


@pytest.mark.parametrize("model", [None, "custom/model"])
def test_unknown_provider_still_fails_at_construction(tmp_path: Path, model: str | None):
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        MemSearch([], embedding_provider="nope", embedding_model=model, milvus_uri=str(tmp_path / "x.db"))


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


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["index_file", "compact"])
@pytest.mark.parametrize("error_type", [ValueError, ImportError, RuntimeError])
async def test_single_file_callers_preserve_provider_error(
    tmp_path: Path, docs: Path, provider, monkeypatch: pytest.MonkeyPatch, operation: str, error_type: type[Exception]
):
    note = docs / "a.md"
    with _ms(tmp_path, docs) as first:
        await first.index()
        before = first.store.hashes_by_source(str(note.resolve()))

    error = error_type("Provider unavailable")

    def broken_get_provider(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(core, "get_provider", broken_get_provider)
    monkeypatch.setattr(core, "compact_chunks", AsyncMock(return_value="Compacted notes."))
    note.write_text("# A\n\nChanged caching notes.\n")
    with _ms(tmp_path, docs) as second:
        with pytest.raises(error_type, match=r"^Provider unavailable$") as caught:
            if operation == "compact":
                await second.compact()
            else:
                await second.index_file(note)
        assert caught.value is error
        assert second.store.hashes_by_source(str(note.resolve())) == before


@pytest.mark.parametrize("failure", ["load", "dimension"])
def test_watch_deletion_validates_provider_before_removing_chunks(
    tmp_path: Path, docs: Path, provider, monkeypatch: pytest.MonkeyPatch, failure: str
):
    note = docs / "a.md"
    with _ms(tmp_path, docs) as first:
        asyncio.run(first.index())
        before = first.store.hashes_by_source(str(note.resolve()))

    if failure == "load":

        def broken_get_provider(*_args, **_kwargs):
            raise RuntimeError("Provider unavailable")

        monkeypatch.setattr(core, "get_provider", broken_get_provider)
        error_type, message = RuntimeError, "Provider unavailable"
    else:
        provider[1]["onnx"] = 8
        error_type, message = DimensionMismatchError, "Embedding dimension mismatch"

    class FakeWatcher:
        def __init__(self, paths, on_change, **kwargs):
            self.on_change = on_change

        def start(self):
            self.on_change("deleted", note)

    monkeypatch.setattr("memsearch.watcher.FileWatcher", FakeWatcher)
    note.unlink()
    errors = []
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(core.asyncio, "new_event_loop", lambda: loop)
    try:
        with _ms(tmp_path, docs) as second:
            second.watch(on_error=lambda event, error, path: errors.append((event, error, path)))
            assert len(errors) == 1
            event, error, path = errors[0]
            assert (event, path) == ("deleted", note)
            assert isinstance(error, error_type)
            assert message in str(error)
            assert second.store.hashes_by_source(str(note.resolve())) == before
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_index_file_dimension_mismatch_preserves_error_and_chunks(tmp_path: Path, docs: Path, provider):
    note = docs / "a.md"
    with _ms(tmp_path, docs) as first:
        await first.index()
        before = first.store.hashes_by_source(str(note.resolve()))

    provider[1]["other-model"] = 8
    with _ms(tmp_path, docs, model="other-model") as second:
        with pytest.raises(DimensionMismatchError, match=r"Embedding dimension mismatch.*has dim=4.*outputs dim=8"):
            await second.index_file(note)
        assert second.store.hashes_by_source(str(note.resolve())) == before


def test_default_models_cover_registered_providers():
    assert DEFAULT_MODELS.keys() == _PROVIDERS.keys()


@pytest.mark.parametrize("name", sorted(_PROVIDERS))
def test_default_model_matches_provider_signature(name: str):
    module_name, class_name = _PROVIDERS[name]
    provider_class = getattr(importlib.import_module(module_name), class_name)
    assert inspect.signature(provider_class).parameters["model"].default == DEFAULT_MODELS[name]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "change"),
    [
        ("index", "section"),
        ("index_file", "section"),
        ("index", "empty"),
        ("index_file", "empty"),
        ("index", "deleted"),
    ],
)
@pytest.mark.parametrize("failure", ["load", "dimension"])
async def test_deletion_only_validates_provider_before_removing_chunks(
    tmp_path: Path, docs: Path, provider, monkeypatch: pytest.MonkeyPatch, operation: str, change: str, failure: str
):
    note = docs / "a.md"
    original = note.read_text()
    note.write_text(original + "\n## B\n\nAnother section.\n")
    with _ms(tmp_path, docs) as first:
        await first.index()
        before = first.store.hashes_by_source(str(note.resolve()))
        assert len(before) == 2

    if failure == "load":

        def broken_get_provider(*_args, **_kwargs):
            raise RuntimeError("Provider unavailable")

        monkeypatch.setattr(core, "get_provider", broken_get_provider)
        error_type, message = RuntimeError, "Provider unavailable"
    else:
        provider[1]["onnx"] = 8
        error_type, message = DimensionMismatchError, "Embedding dimension mismatch"

    if change == "deleted":
        note.unlink()
    else:
        note.write_text(original if change == "section" else "")
    with _ms(tmp_path, docs) as second:
        with pytest.raises(error_type, match=message):
            if operation == "index_file":
                await second.index_file(note)
            else:
                await second.index()
        assert second.store.hashes_by_source(str(note.resolve())) == before
