from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from click.testing import CliRunner

from memsearch import cli as cli_module
from memsearch import core as core_module
from memsearch.cli import cli
from memsearch.config import MemSearchConfig
from memsearch.store import MilvusStore


class FakeEmbeddingProvider:
    dimension = 4
    model_name = "fake-model"
    batch_size = 8

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


@pytest.fixture(autouse=True)
def fake_embedding_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_module, "get_provider", lambda *_args, **_kwargs: FakeEmbeddingProvider())


def _config(uri: Path, collection: str = "missing") -> MemSearchConfig:
    cfg = MemSearchConfig()
    cfg.embedding.provider = "fake"
    cfg.milvus.uri = str(uri)
    cfg.milvus.collection = collection
    return cfg


def _collections(uri: Path) -> list[str]:
    from pymilvus import MilvusClient

    client = MilvusClient(uri=str(uri))
    try:
        return client.list_collections()
    finally:
        client.close()


def _storage_digest(uri: Path) -> str:
    digest = hashlib.sha256()
    paths = [uri] if uri.is_file() else sorted(path for path in uri.rglob("*") if path.is_file())
    for path in paths:
        digest.update(str(path.relative_to(uri.parent)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.mark.asyncio
async def test_python_search_missing_lite_path_does_not_create_storage(tmp_path: Path) -> None:
    uri = tmp_path / "nested" / "missing.db"
    ms = core_module.MemSearch(milvus_uri=str(uri), collection="missing")
    try:
        with pytest.raises(RuntimeError, match="does not exist"):
            await ms.search("query")
    finally:
        ms.close()

    assert not uri.parent.exists()


@pytest.mark.asyncio
async def test_python_search_missing_collection_preserves_existing_database(tmp_path: Path) -> None:
    uri = tmp_path / "existing.db"
    seed = MilvusStore(uri=str(uri), collection="present", dimension=4, _create_if_missing=True)
    seed.close()
    before = _collections(uri)
    before_digest = _storage_digest(uri)

    ms = core_module.MemSearch(milvus_uri=str(uri), collection="missing")
    try:
        with pytest.raises(RuntimeError, match="does not exist"):
            await ms.search("query")
    finally:
        ms.close()

    assert _storage_digest(uri) == before_digest
    assert _collections(uri) == before == ["present"]


def test_dimension_none_missing_lite_path_does_not_create_storage(tmp_path: Path) -> None:
    uri = tmp_path / "nested" / "missing.db"
    store = MilvusStore(uri=str(uri), collection="missing", dimension=None)
    try:
        with pytest.raises(RuntimeError, match="does not exist"):
            store.count()
    finally:
        store.close()

    assert not uri.parent.exists()


def test_default_known_dimension_search_missing_lite_path_does_not_create_storage(tmp_path: Path) -> None:
    uri = tmp_path / "nested" / "missing.db"
    store = MilvusStore(uri=str(uri), collection="missing", dimension=4)
    try:
        with pytest.raises(RuntimeError, match="does not exist"):
            store.search([1.0, 0.0, 0.0, 0.0], query_text="missing")
    finally:
        store.close()

    assert not uri.parent.exists()


def test_default_known_dimension_search_missing_collection_preserves_existing_database(tmp_path: Path) -> None:
    uri = tmp_path / "existing.db"
    seed = MilvusStore(uri=str(uri), collection="present", dimension=4, _create_if_missing=True)
    seed.close()
    before = _collections(uri)
    before_digest = _storage_digest(uri)

    store = MilvusStore(uri=str(uri), collection="missing", dimension=4)
    try:
        with pytest.raises(RuntimeError, match="does not exist"):
            store.search([1.0, 0.0, 0.0, 0.0], query_text="missing")
    finally:
        store.close()

    assert _storage_digest(uri) == before_digest
    assert _collections(uri) == before == ["present"]


@pytest.mark.asyncio
async def test_python_index_and_index_file_lazily_create_collection(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    note = docs / "note.md"
    note.write_text("# Note\n\nIndex me.\n", encoding="utf-8")

    index_uri = tmp_path / "index" / "mem.db"
    ms = core_module.MemSearch(paths=[docs], milvus_uri=str(index_uri), collection="from_index")
    try:
        assert not index_uri.parent.exists()
        assert await ms.index() == 1
    finally:
        ms.close()
    assert _collections(index_uri) == ["from_index"]

    file_uri = tmp_path / "index-file" / "mem.db"
    ms = core_module.MemSearch(milvus_uri=str(file_uri), collection="from_index_file")
    try:
        assert not file_uri.parent.exists()
        assert await ms.index_file(note) == 1
    finally:
        ms.close()
    assert _collections(file_uri) == ["from_index_file"]


def test_direct_store_upsert_lazily_creates_collection(tmp_path: Path) -> None:
    uri = tmp_path / "nested" / "direct.db"
    store = MilvusStore(uri=str(uri), collection="direct", dimension=4)
    try:
        assert not uri.parent.exists()
        assert (
            store.upsert(
                [
                    {
                        "embedding": [1.0, 0.0, 0.0, 0.0],
                        "content": "Direct write",
                        "source": "direct.md",
                        "heading": "",
                        "chunk_hash": "direct-hash",
                        "heading_level": 0,
                        "start_line": 1,
                        "end_line": 1,
                    }
                ]
            )
            == 1
        )
    finally:
        store.close()

    assert _collections(uri) == ["direct"]


def test_missing_read_calls_no_milvus_create_or_load_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = dict.fromkeys(("client", "schema", "index", "create", "load"), 0)

    class Builder:
        def add_field(self, **_kwargs) -> None:
            pass

        def add_function(self, _function) -> None:
            pass

        def add_index(self, **_kwargs) -> None:
            pass

    class Client:
        def __init__(self, **_kwargs) -> None:
            calls["client"] += 1

        def has_collection(self, _collection: str) -> bool:
            return False

        def create_schema(self, **_kwargs) -> Builder:
            calls["schema"] += 1
            return Builder()

        def prepare_index_params(self) -> Builder:
            calls["index"] += 1
            return Builder()

        def create_collection(self, **_kwargs) -> None:
            calls["create"] += 1

        def load_collection(self, *_args, **_kwargs) -> None:
            calls["load"] += 1

        def close(self) -> None:
            pass

    monkeypatch.setattr("pymilvus.MilvusClient", Client)
    uri = tmp_path / "nested" / "missing.db"

    store = MilvusStore(uri=str(uri), collection="missing", dimension=4)
    try:
        with pytest.raises(RuntimeError, match="does not exist"):
            store.search([1.0, 0.0, 0.0, 0.0], query_text="missing")
    finally:
        store.close()

    assert calls == {"client": 0, "schema": 0, "index": 0, "create": 0, "load": 0}
    assert not uri.parent.exists()


def test_describe_collection_failure_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = RuntimeError("describe failed")

    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        def has_collection(self, _collection: str) -> bool:
            return True

        def describe_collection(self, _collection: str):
            raise failure

        def load_collection(self, *_args, **_kwargs) -> None:
            pass

    monkeypatch.setattr("pymilvus.MilvusClient", Client)

    with pytest.raises(RuntimeError, match="describe failed") as exc_info:
        MilvusStore(uri="http://milvus.invalid", collection="present", dimension=4)

    assert exc_info.value is failure


def test_has_collection_failure_is_not_reclassified(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = RuntimeError("authorization failed")

    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        def has_collection(self, _collection: str) -> bool:
            raise failure

    monkeypatch.setattr("pymilvus.MilvusClient", Client)

    with pytest.raises(RuntimeError, match="authorization failed") as exc_info:
        MilvusStore(uri="http://milvus.invalid", collection="unknown", dimension=4)

    assert exc_info.value is failure


@pytest.mark.parametrize(
    ("args", "json_search"),
    [
        (["search", "query", "--json-output"], True),
        (["stats"], False),
        (["expand", "unknown"], False),
        (["compact"], False),
    ],
)
def test_cli_missing_reads_are_actionable_and_non_mutating(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    args: list[str],
    json_search: bool,
) -> None:
    uri = tmp_path / "nested" / "missing.db"
    output_dir = tmp_path / "compact-output"
    cfg = _config(uri)
    monkeypatch.setattr(cli_module, "resolve_config", lambda *_args, **_kwargs: cfg)
    if args[0] == "compact":
        args = [*args, "--output-dir", str(output_dir)]

    result = CliRunner().invoke(cli, args)

    assert result.exit_code == 1
    assert "does not exist" in result.stderr
    assert "memsearch index" in result.stderr
    if json_search:
        assert "[]" not in result.output
    assert not uri.parent.exists()
    assert not output_dir.exists()


@pytest.mark.parametrize("command", ["index", "watch"])
def test_cli_write_commands_lazily_create_collection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "note.md").write_text("# Note\n\nCLI write.\n", encoding="utf-8")
    uri = tmp_path / command / "mem.db"
    cfg = _config(uri, collection=f"from_{command}")
    monkeypatch.setattr(cli_module, "resolve_config", lambda *_args, **_kwargs: cfg)
    if command == "watch":

        def stop_after_initial_index(self, **_kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(core_module.MemSearch, "watch", stop_after_initial_index)

    result = CliRunner().invoke(cli, [command, str(docs)])

    assert result.exit_code == 0
    assert _collections(uri) == [f"from_{command}"]
