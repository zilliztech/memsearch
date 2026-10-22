"""`compact` must be able to write its summary into a store directory that is not named ``memory``.

Before the fix ``compact`` joined ``/ "memory"`` onto the base directory unconditionally,
so a central store laid out as ``<store-root>/<project>`` could never receive the summary:
it landed in a fresh ``<project>/memory/`` subdirectory instead, outside the store that was
being compacted, and was then indexed from there.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from memsearch.core import MemSearch


class FakeStore:
    """Returns one chunk, so `compact` reaches the write path."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def query(self, filter_expr: str = "", **_: Any) -> list[dict[str, Any]]:
        self.queries.append(filter_expr)
        return [{"content": "a stored chunk"}]


def make_memsearch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, paths: list[str] | None = None
) -> tuple[MemSearch, list[Path]]:
    """A MemSearch with no Milvus and no LLM, plus the list of files it indexed.

    The cwd is moved into *tmp_path*, so a regression that falls back to
    ``Path.cwd()`` writes there instead of into the working tree.
    """
    monkeypatch.chdir(tmp_path)
    ms = MemSearch.__new__(MemSearch)
    ms._paths = paths or []
    ms._store = FakeStore()

    async def fake_compact_chunks(*_args: Any, **_kwargs: Any) -> str:
        return "- a summary line"

    monkeypatch.setattr("memsearch.core.compact_chunks", fake_compact_chunks)

    indexed: list[Path] = []

    async def fake_index_file(path: str | Path) -> int:
        indexed.append(Path(path))
        return 1

    monkeypatch.setattr(ms, "index_file", fake_index_file)
    return ms, indexed


async def test_memory_dir_writes_into_the_named_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = tmp_path / "store-root" / "my-project"
    store.mkdir(parents=True)
    ms, _ = make_memsearch(monkeypatch, tmp_path)

    await ms.compact(memory_dir=store)

    assert (store / f"{date.today()}.md").is_file()
    assert not (store / "memory").exists()


async def test_memory_dir_overrides_output_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = tmp_path / "store-root" / "my-project"
    store.mkdir(parents=True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    ms, _ = make_memsearch(monkeypatch, tmp_path)

    await ms.compact(output_dir=other, memory_dir=store)

    assert (store / f"{date.today()}.md").is_file()
    assert list(other.iterdir()) == []


async def test_memory_dir_is_created_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = tmp_path / "store-root" / "not-yet" / "my-project"
    ms, _ = make_memsearch(monkeypatch, tmp_path)

    await ms.compact(memory_dir=store)

    assert (store / f"{date.today()}.md").is_file()


async def test_memory_dir_indexes_the_file_it_wrote(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = tmp_path / "store-root" / "my-project"
    store.mkdir(parents=True)
    ms, indexed = make_memsearch(monkeypatch, tmp_path)

    await ms.compact(memory_dir=store)

    assert indexed == [store / f"{date.today()}.md"]


async def test_memory_dir_accepts_a_string_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = tmp_path / "store-root" / "my-project"
    store.mkdir(parents=True)
    ms, _ = make_memsearch(monkeypatch, tmp_path)

    await ms.compact(memory_dir=str(store))

    assert (store / f"{date.today()}.md").is_file()
    assert not (store / "memory").exists()


async def test_without_memory_dir_the_memory_subdirectory_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression guard: the default layout must not move."""
    base = tmp_path / ".memsearch"
    base.mkdir()
    ms, indexed = make_memsearch(monkeypatch, tmp_path)

    await ms.compact(output_dir=base)

    expected = base / "memory" / f"{date.today()}.md"
    assert expected.is_file()
    assert indexed == [expected]


async def test_without_any_directory_the_first_path_is_still_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression guard: the `paths[0]` fallback must not move."""
    first = tmp_path / "notes"
    first.mkdir()
    ms, _ = make_memsearch(monkeypatch, tmp_path, paths=[str(first)])

    await ms.compact()

    assert (first / "memory" / f"{date.today()}.md").is_file()


async def test_empty_memory_dir_falls_back_to_the_default_layout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty value means "not given", not "the current directory"."""
    base = tmp_path / ".memsearch"
    base.mkdir()
    ms, _ = make_memsearch(monkeypatch, tmp_path)

    await ms.compact(output_dir=base, memory_dir="")

    assert (base / "memory" / f"{date.today()}.md").is_file()
    assert not (Path.cwd() / f"{date.today()}.md").exists()
