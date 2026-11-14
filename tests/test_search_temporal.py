"""Temporal window tests for MemSearch.search (since/until).

Failure-mode inventory (each test binds to one entry):
- T1 endpoint boundaries: since == until returns that day (inclusive both ends).
- T2 undated chunks never leak into a windowed result.
- T3 no-window metamorphic: without a window, fetch_k is unchanged and
  results pass through untouched (baseline behaviour).
- T4 invalid date format raises ValueError instead of silently disabling.
- T5 since > until raises ValueError.
- T6 filter x rerank composition: the reranker only sees in-window candidates.
- T7 window results may be shorter than top_k; never padded from outside.
- T8 year-boundary window (12-31 -> 01-01) keeps both endpoints.
- T9 Windows-style backslash sources resolve like POSIX.
- T10 CLI passthrough: --since/--until must reach core.search.

Excluded, with reasons:
- Real Milvus retrieval quality / embedder behaviour: test_core.py owns the
  real pipeline; everything here runs on fake store/embedder/reranker, no
  API key, no model downloads.
- Timezone semantics: source dates come from file names; there is no
  timezone concept to inject.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from typing import ClassVar

import pytest


def _chunk(source: str, content: str = "content") -> dict:
    return {"source": source, "content": content, "heading": "h", "chunk_hash": f"h-{source}"}


class FakeStore:
    """Records the fetch_k it was asked for; replays chunks in order."""

    def __init__(self, chunks: list[dict]) -> None:
        self.chunks = chunks
        self.calls: list[int] = []

    def _require_collection(self) -> None:
        return None

    def search(self, embedding, *, query_text="", top_k=10, filter_expr=""):
        self.calls.append(top_k)
        self.last_expr = filter_expr
        return [dict(chunk, score=0.5) for chunk in self.chunks[:top_k]]


class FakeEmbedder:
    async def embed(self, texts):
        return [[0.1] * 8 for _ in texts]


def _make_memsearch(store: FakeStore, reranker_model: str | None = None, monkeypatch=None):
    from memsearch.core import MemSearch

    mem = MemSearch.__new__(MemSearch)
    mem._store = store
    mem._embedder = FakeEmbedder()
    mem._reranker_model = reranker_model
    if reranker_model is not None and monkeypatch is not None:
        # search() imports rerank from .reranker inside the call; patch there.
        seen: dict = {}
        monkeypatch.setattr(
            "memsearch.reranker.rerank",
            lambda query, results, *, model_name, top_k: (
                seen.update(candidates=[r["source"] for r in results])
                or sorted(results, key=lambda r: r["score"], reverse=True)[:top_k]
            ),
        )
        mem._reranker_seen = seen
    return mem


def _journal_chunks() -> list[dict]:
    return [
        _chunk("2026-06-01.md", "first"),
        _chunk("2026-06-02.md", "second"),
        _chunk("2026-06-05.md", "fifth"),
        _chunk("PROJECT.md", "undated project notes"),
        _chunk("2026-01-01.md", "january"),
    ]


@pytest.mark.asyncio
async def test_window_inclusive_endpoints_single_day(tmp_path) -> None:
    """T1: since == until returns exactly that day's chunks."""
    mem = _make_memsearch(FakeStore(_journal_chunks()))
    results = await mem.search("anything", since="2026-06-02", until="2026-06-02")
    assert [r["content"] for r in results] == ["second"]


@pytest.mark.asyncio
async def test_window_excludes_undated_sources(tmp_path) -> None:
    """T2: chunks from undated files never appear inside a window."""
    mem = _make_memsearch(FakeStore(_journal_chunks()))
    results = await mem.search("anything", since="2026-01-01", until="2026-12-31")
    sources = [r["source"] for r in results]
    assert sources and all("PROJECT" not in s for s in sources)


@pytest.mark.asyncio
async def test_no_window_matches_baseline_fetch(tmp_path) -> None:
    """T3: without a window, fetch_k is unchanged (no overfetch) and results pass through."""
    chunks = _journal_chunks()
    store = FakeStore(chunks)
    mem = _make_memsearch(store)
    results = await mem.search("anything", top_k=10)
    assert store.calls == [10]
    assert len(results) == len(chunks)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["not-a-date", "2026-13-99", "2026/06/01", ""])
async def test_bad_date_format_raises(tmp_path, bad: str) -> None:
    """T4: unusable dates raise instead of silently disabling the window."""
    mem = _make_memsearch(FakeStore(_journal_chunks()))
    with pytest.raises(ValueError, match="invalid"):
        await mem.search("anything", since=bad)


@pytest.mark.asyncio
async def test_since_after_until_raises(tmp_path) -> None:
    """T5: an inverted window is rejected with both values named."""
    mem = _make_memsearch(FakeStore(_journal_chunks()))
    with pytest.raises(ValueError, match="after until"):
        await mem.search("anything", since="2026-06-05", until="2026-06-01")


@pytest.mark.asyncio
async def test_filter_runs_before_rerank(tmp_path, monkeypatch) -> None:
    """T6 (组合缝隙): the reranker must never see candidates outside the window."""
    store = FakeStore(_journal_chunks())
    mem = _make_memsearch(store, reranker_model="local-onnx", monkeypatch=monkeypatch)
    results = await mem.search("anything", top_k=2, since="2026-06-01", until="2026-06-30")
    assert all("2026-06" in r["source"] for r in results)
    assert all("PROJECT" not in s for s in mem._reranker_seen["candidates"])
    assert all("2026-01" not in s for s in mem._reranker_seen["candidates"])


@pytest.mark.asyncio
async def test_window_result_may_be_shorter_than_top_k(tmp_path) -> None:
    """T7: a narrow window over a big fetch may return fewer than top_k — never padded."""
    store = FakeStore(_journal_chunks())
    mem = _make_memsearch(store)
    results = await mem.search("anything", top_k=50, since="2026-06-01", until="2026-06-02")
    assert 0 < len(results) < 50
    assert store.calls == [400]  # window widens the fetch to top_k * 8
    assert all(r["source"] in {"2026-06-01.md", "2026-06-02.md"} for r in results)


@pytest.mark.asyncio
async def test_window_over_year_boundary(tmp_path) -> None:
    """T8: a 12-31 → 01-01 window keeps both endpoints."""
    mem = _make_memsearch(FakeStore(_journal_chunks()))
    results = await mem.search("anything", since="2025-12-31", until="2026-01-01")
    assert [r["content"] for r in results] == ["january"]


@pytest.mark.asyncio
async def test_windows_backslash_sources_resolve_like_posix(tmp_path) -> None:
    """T9: backslash-separated sources carry their date the same way."""
    store = FakeStore([_chunk("C:\\mem\\memory\\2026-06-02.md", "win"), _chunk("C:\\mem\\memory\\notes.md", "undated")])
    mem = _make_memsearch(store)
    results = await mem.search("anything", since="2026-06-02", until="2026-06-02")
    assert [r["content"] for r in results] == ["win"]


@pytest.mark.asyncio
async def test_one_sided_windows(tmp_path) -> None:
    """Single-bound windows work: since-only and until-only."""
    store = FakeStore(_journal_chunks())
    mem = _make_memsearch(store)
    since_only = await mem.search("anything", since="2026-06-02")
    assert {r["content"] for r in since_only} == {"second", "fifth"}
    until_only = await _make_memsearch(FakeStore(_journal_chunks())).search("anything", until="2026-01-31")
    assert [r["content"] for r in until_only] == ["january"]


def test_chunk_date_helpers() -> None:
    from memsearch.core import _chunk_date

    assert _chunk_date("2026-06-01.md") == date(2026, 6, 1)
    assert _chunk_date("C:\\mem\\2026-06-01.md") == date(2026, 6, 1)
    assert _chunk_date("/x/2026-01-01/notes/memory.md") is None  # parent dir dates don't count
    assert _chunk_date("PROJECT.md") is None
    assert _chunk_date("2026-02-30.md") is None  # a name, not a real date
    assert _chunk_date("memory.md") is None


def test_month_patterns_span_and_cap() -> None:
    from memsearch.core import _month_patterns

    assert _month_patterns(date(2026, 11, 1), date(2026, 11, 14)) == ["%2026-11-%"]
    assert _month_patterns(date(2025, 12, 31), date(2026, 1, 1)) == ["%2025-12-%", "%2026-01-%"]
    assert _month_patterns(None, date(2026, 1, 1)) == []  # one-sided: no prefilter
    assert _month_patterns(date(2010, 1, 1), date(2026, 1, 1)) == []  # absurd range: prefilter off


def test_window_prefilter_enters_the_engine_query(tmp_path) -> None:
    """组合缝隙: the month pattern must ride inside filter_expr to the engine."""
    store = FakeStore(_journal_chunks())
    mem = _make_memsearch(store)
    import asyncio

    asyncio.run(mem.search("q", since="2026-06-01", until="2026-06-02"))
    expr = getattr(store, "last_expr", "")
    assert expr == 'source like "%2026-06-%"'


def test_window_prefilter_composes_with_source_prefix(tmp_path) -> None:
    store = FakeStore(_journal_chunks())
    mem = _make_memsearch(store)
    import asyncio

    asyncio.run(mem.search("q", source_prefix="/proj", since="2026-06-01", until="2026-06-02"))
    expr = getattr(store, "last_expr", "")
    assert expr.startswith('(source like "')
    assert ") and (" in expr  # prefix filter AND month prefilter composed
    assert "%2026-06-%" in expr


def test_resolve_date_window_accepts_datetime_and_date() -> None:
    from memsearch.core import _resolve_date_window

    assert _resolve_date_window(None, None) is None
    assert _resolve_date_window(datetime(2026, 6, 2, 9, 30), None) == (date(2026, 6, 2), None)
    assert _resolve_date_window(date(2026, 6, 2), date(2026, 6, 5)) == (date(2026, 6, 2), date(2026, 6, 5))
    with pytest.raises(ValueError, match="invalid since"):
        _resolve_date_window("junk", None)


# ---------------------------------------------------------------------------
# T10: CLI passthrough (缺席类 — the flag must actually reach core.search)
# ---------------------------------------------------------------------------


class _RecordingMemSearch(SimpleNamespace):
    instances: ClassVar[list[_RecordingMemSearch]] = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        _RecordingMemSearch.instances.append(self)
        self.search_args: dict = {}
        self.closed = False

    async def search(self, query, **kwargs):
        self.search_args = {"query": query, **kwargs}
        # Delegate window validation to the real core validator so the CLI's
        # ValueError path is exercised against actual rules, not a stub.
        from memsearch.core import _resolve_date_window

        _resolve_date_window(kwargs.get("since"), kwargs.get("until"))
        return [{"source": "2026-06-01.md", "content": "x", "heading": "", "score": 1.0}]

    def close(self):
        self.closed = True


def _run_cli(monkeypatch, args: list[str]) -> object:
    from click.testing import CliRunner

    from memsearch import cli

    _RecordingMemSearch.instances = []
    monkeypatch.setattr("memsearch.core.MemSearch", _RecordingMemSearch)
    monkeypatch.setattr(cli, "_safe_resolve_config", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_cfg_to_memsearch_kwargs", lambda cfg: {})
    monkeypatch.setattr(cli, "_build_cli_overrides", lambda **k: {})
    return CliRunner().invoke(cli.cli, args)


def test_cli_passes_window_to_core(tmp_path, monkeypatch) -> None:
    result = _run_cli(monkeypatch, ["search", "q", "--since", "2026-06-01", "--until", "2026-06-07", "-k", "3"])
    assert result.exit_code == 0, result.output
    ms = _RecordingMemSearch.instances[0]
    assert ms.search_args["since"] == "2026-06-01"
    assert ms.search_args["until"] == "2026-06-07"
    assert ms.search_args["top_k"] == 3
    assert ms.closed


def test_cli_bad_since_is_a_usage_error_not_a_traceback(tmp_path, monkeypatch) -> None:
    """T4 at the CLI edge: clean message + exit code 2, no raw traceback."""
    result = _run_cli(monkeypatch, ["search", "q", "--since", "not-a-date"])
    assert result.exit_code == 2
    assert "invalid since date" in result.stderr or "invalid since date" in result.output
    assert "Traceback" not in (result.output + getattr(result, "stderr", ""))


def test_cli_no_window_leaves_call_shape_unchanged(tmp_path, monkeypatch) -> None:
    """Without a window the search call carries no window kwargs at all —
    consumers that stub search with the old fixed signature keep working."""
    result = _run_cli(monkeypatch, ["search", "q"])
    assert result.exit_code == 0, result.output
    ms = _RecordingMemSearch.instances[0]
    assert "since" not in ms.search_args
    assert "until" not in ms.search_args
