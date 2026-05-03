"""Unit tests for core helpers that don't require Milvus or an embedder."""

from __future__ import annotations


def test_scope_dataclass_defaults():
    from memsearch.core import Scope

    s = Scope(name="x", collection="c")
    assert s.name == "x"
    assert s.collection == "c"
    assert s.paths == []
    assert s.quota is None
    assert s.uri is None
    assert s.token is None
