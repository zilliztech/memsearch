"""Tests for the Milvus store."""

import subprocess
import sys
import time
from pathlib import Path

import pytest

from memsearch.store import MilvusStore, _local_open_error_message


@pytest.fixture
def store(tmp_path: Path):
    db = tmp_path / "test_milvus.db"
    s = MilvusStore(uri=str(db), dimension=4)
    yield s
    s.close()


def test_upsert_and_search(store: MilvusStore):
    chunks = [
        {
            "embedding": [1.0, 0.0, 0.0, 0.0],
            "content": "Hello world",
            "source": "test.md",
            "heading": "Intro",
            "chunk_hash": "h1",
            "heading_level": 1,
            "start_line": 1,
            "end_line": 5,
        },
        {
            "embedding": [0.0, 1.0, 0.0, 0.0],
            "content": "Goodbye world",
            "source": "test.md",
            "heading": "Outro",
            "chunk_hash": "h2",
            "heading_level": 1,
            "start_line": 6,
            "end_line": 10,
        },
    ]
    n = store.upsert(chunks)
    assert n == 2

    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=1)
    assert len(results) >= 1
    assert results[0]["content"] == "Hello world"


def test_delete_by_source(store: MilvusStore):
    chunks = [
        {
            "embedding": [1.0, 0.0, 0.0, 0.0],
            "content": "A",
            "source": "a.md",
            "heading": "",
            "chunk_hash": "ha",
            "heading_level": 0,
            "start_line": 1,
            "end_line": 1,
        },
        {
            "embedding": [0.0, 1.0, 0.0, 0.0],
            "content": "B",
            "source": "b.md",
            "heading": "",
            "chunk_hash": "hb",
            "heading_level": 0,
            "start_line": 1,
            "end_line": 1,
        },
    ]
    store.upsert(chunks)
    store.delete_by_source("a.md")
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=10)
    sources = {r["source"] for r in results}
    assert "a.md" not in sources


def test_upsert_is_idempotent(store: MilvusStore):
    chunk = {
        "embedding": [1.0, 0.0, 0.0, 0.0],
        "content": "Same content",
        "source": "test.md",
        "heading": "",
        "chunk_hash": "same_hash",
        "heading_level": 0,
        "start_line": 1,
        "end_line": 1,
        "doc_type": "markdown",
    }
    store.upsert([chunk])
    store.upsert([chunk])
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=10)
    hashes = [r["chunk_hash"] for r in results]
    assert hashes.count("same_hash") == 1


def test_hybrid_search(store: MilvusStore):
    chunks = [
        {
            "embedding": [1.0, 0.0, 0.0, 0.0],
            "content": "Redis caching with TTL and LRU eviction policy",
            "source": "test.md",
            "heading": "Caching",
            "chunk_hash": "h_redis",
            "heading_level": 1,
            "start_line": 1,
            "end_line": 5,
        },
        {
            "embedding": [0.0, 1.0, 0.0, 0.0],
            "content": "PostgreSQL database migration and schema changes",
            "source": "test.md",
            "heading": "Database",
            "chunk_hash": "h_pg",
            "heading_level": 1,
            "start_line": 6,
            "end_line": 10,
        },
    ]
    store.upsert(chunks)

    # Hybrid search: BM25 should boost the Redis result for keyword "Redis"
    results = store.search(
        [0.5, 0.5, 0.0, 0.0],  # ambiguous dense vector
        query_text="Redis caching",
        top_k=2,
    )
    assert len(results) >= 1
    assert results[0]["content"].startswith("Redis")


def test_dimension_mismatch(tmp_path: Path):
    db = str(tmp_path / "dim_test.db")
    # Create collection with dim=4
    s1 = MilvusStore(uri=db, dimension=4)
    s1.close()
    # Re-open with dim=8 — should raise ValueError
    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        MilvusStore(uri=db, dimension=8)


def test_reopened_collection_is_loaded_for_query(tmp_path: Path):
    db = str(tmp_path / "reopen_test.db")
    chunk = {
        "embedding": [1.0, 0.0, 0.0, 0.0],
        "content": "Reopened collection",
        "source": "test.md",
        "heading": "",
        "chunk_hash": "reopen_hash",
        "heading_level": 0,
        "start_line": 1,
        "end_line": 1,
    }

    s1 = MilvusStore(uri=db, dimension=4)
    s1.upsert([chunk])
    s1.close()

    s2 = MilvusStore(uri=db, dimension=4)
    try:
        results = s2.query()
    finally:
        s2.close()

    assert [r["chunk_hash"] for r in results] == ["reopen_hash"]


def test_drop(store: MilvusStore):
    chunk = {
        "embedding": [1.0, 0.0, 0.0, 0.0],
        "content": "Will be dropped",
        "source": "test.md",
        "heading": "",
        "chunk_hash": "hd",
        "heading_level": 0,
        "start_line": 1,
        "end_line": 1,
        "doc_type": "markdown",
    }
    store.upsert([chunk])
    store.drop()
    # After drop, collection is gone — re-ensure should work
    store._ensure_collection()
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=10)
    assert len(results) == 0


def test_collection_description(tmp_path: Path):
    """Collection should store the description when provided."""
    db = str(tmp_path / "desc_test.db")
    desc = "myproject | openai/text-embedding-3-small"
    s = MilvusStore(uri=db, dimension=4, description=desc)
    info = s._client.describe_collection(s._collection)
    assert info.get("description") == desc
    s.close()


def test_collection_description_empty_by_default(tmp_path: Path):
    """Collection should have empty description when not provided."""
    db = str(tmp_path / "desc_default_test.db")
    s = MilvusStore(uri=db, dimension=4)
    info = s._client.describe_collection(s._collection)
    assert info.get("description") == ""
    s.close()


def test_open_error_reports_file_where_directory_expected(tmp_path: Path):
    """Under a 3.x runtime a plain file is a real layout mismatch worth reporting."""
    db = tmp_path / "old.db"
    db.write_text("")
    message = _local_open_error_message(RuntimeError("open failed"), str(db), 3)
    assert "but this path is a file" in message
    assert "open failed" in message


def test_open_error_does_not_assert_the_file_is_a_2x_database(tmp_path: Path):
    """The path being a file does not prove Milvus Lite 2.x wrote it. A mistyped
    URI pointing at any unrelated file reaches this branch, so the legacy database
    must be offered as one possibility, never stated as fact."""
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("not a database")
    message = _local_open_error_message(RuntimeError("open failed"), str(unrelated), 3)
    assert "If it is a database from Milvus Lite 2.x" in message
    assert "was created by Milvus Lite 2.x" not in message
    assert "check the configured URI" in message


def test_open_error_keeps_2x_layout_generic(tmp_path: Path):
    """On a 2.x runtime a plain file is the normal layout, not a mismatch."""
    db = tmp_path / "current.db"
    db.write_text("")
    message = _local_open_error_message(RuntimeError("open failed"), str(db), 2)
    assert "but this path is a file" not in message
    assert "move it aside" not in message
    assert "open failed" in message


def test_open_error_keeps_3x_layout_generic(tmp_path: Path):
    """A directory is the expected 3.x layout, so nothing is diagnosable."""
    db = tmp_path / "current.db"
    db.mkdir()
    message = _local_open_error_message(RuntimeError("open failed"), str(db), 3)
    assert "but this path is a file" not in message
    assert "move it aside" not in message


def test_open_error_generic_when_version_unknown(tmp_path: Path):
    """An unreadable milvus-lite version proves nothing about the layout."""
    db = tmp_path / "old.db"
    db.write_text("")
    message = _local_open_error_message(RuntimeError("open failed"), str(db), None)
    assert "but this path is a file" not in message
    assert "move it aside" not in message


def test_open_error_is_actionable_without_visible_logs(tmp_path: Path):
    """Library and plugin callers may redirect or suppress dependency logs."""
    db = tmp_path / "current.db"
    message = _local_open_error_message(RuntimeError("open failed"), str(db), 3)
    assert "Close other processes" in message
    assert "verify that the path is writable" in message
    assert "preserve the database" in message
    assert "log output above" not in message


_HOLD_DATABASE = """
import pathlib
import sys
import time

from pymilvus import MilvusClient

MilvusClient(uri=sys.argv[1])
pathlib.Path(sys.argv[2]).write_text("ready")
time.sleep(30)
"""

_HOLD_TIMEOUT_S = 60


def _wait_until_held(holder: subprocess.Popen, ready: Path) -> None:
    """Block until the child has the database open, or fail with its stderr.

    A readiness read with no bound can hang the whole suite if the child stalls,
    so this polls a marker file against a deadline and surfaces the child's own
    output when it dies early or never gets there.
    """
    deadline = time.monotonic() + _HOLD_TIMEOUT_S
    while not ready.exists():
        if holder.poll() is not None:
            _, err = holder.communicate()
            raise AssertionError(f"holder exited with {holder.returncode} before opening the database: {err.strip()}")
        if time.monotonic() > deadline:
            holder.kill()
            _, err = holder.communicate()
            raise AssertionError(f"holder did not open the database within {_HOLD_TIMEOUT_S}s: {err.strip()}")
        time.sleep(0.05)


def test_concurrent_open_is_not_reported_as_incompatibility(tmp_path: Path):
    """A database held by another process must not be diagnosed as an
    incompatible old database, which would advise discarding a working index."""
    db = str(tmp_path / "busy.db")
    ready = tmp_path / "holder.ready"
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLD_DATABASE, db, str(ready)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_until_held(holder, ready)
        with pytest.raises(RuntimeError) as excinfo:
            MilvusStore(uri=db, dimension=4)
        message = str(excinfo.value)
        assert "another process already has the database open" in message
        assert "but this path is a file" not in message
        assert "move it aside" not in message
    finally:
        holder.kill()
        holder.wait(timeout=30)
