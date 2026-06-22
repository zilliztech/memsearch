"""Tests for pinned model revisions (security: supply-chain).

A model id may carry a ``@<revision>`` suffix (commit SHA / tag / branch) so
users can pin the exact remote weights they download and execute, defending
against a compromised/MITM'd HuggingFace repo silently serving a malicious
ONNX file. See security issue #594 (CWE-367 finding).
"""

from __future__ import annotations

from memsearch.embeddings.onnx import _split_revision as onnx_split
from memsearch.reranker import _split_revision as reranker_split


def test_split_revision_none():
    assert onnx_split("gpahal/bge-m3-onnx-int8") == ("gpahal/bge-m3-onnx-int8", None)
    assert reranker_split("cross-encoder/ms-marco-MiniLM-L6-v2") == (
        "cross-encoder/ms-marco-MiniLM-L6-v2",
        None,
    )


def test_split_revision_sha():
    repo, rev = onnx_split("gpahal/bge-m3-onnx-int8@abc123def456")
    assert repo == "gpahal/bge-m3-onnx-int8"
    assert rev == "abc123def456"


def test_split_revision_tag_with_org():
    # Only the LAST '@' separates revision; org names never contain '@' but be safe.
    repo, rev = reranker_split("Alibaba-NLP/gte-reranker-modernbert-base@v1.0")
    assert repo == "Alibaba-NLP/gte-reranker-modernbert-base"
    assert rev == "v1.0"


def test_split_revision_empty_suffix_ignored():
    # A trailing '@' with no revision is treated as unpinned, not an empty pin.
    assert onnx_split("repo/model@") == ("repo/model", None)
