"""Tests for ONNX input-feed construction (token_type_ids compatibility).

Uses a stub session so no onnxruntime model download is needed.
"""

from __future__ import annotations

import numpy as np

from memsearch.embeddings.onnx import OnnxEmbedding


class _StubEncoding:
    def __init__(self) -> None:
        self.ids = [1, 2, 3]
        self.attention_mask = [1, 1, 0]


class _StubTokenizer:
    def encode_batch(self, texts):
        return [_StubEncoding() for _ in texts]


class _StubSession:
    """Mimics ort.InferenceSession run(); records the feed it was given."""

    def __init__(self) -> None:
        self.last_feed: dict | None = None

    def run(self, _output_names, feed):
        self.last_feed = feed
        batch = len(feed["input_ids"])
        return [np.ones((batch, 4), dtype=np.float32)]


def _make(needs_token_type_ids: bool) -> tuple[OnnxEmbedding, _StubSession]:
    e = object.__new__(OnnxEmbedding)
    session = _StubSession()
    e._tokenizer = _StubTokenizer()
    e._session = session
    e._output_names = ["dense_vecs"]
    e._has_dense_vecs = True
    e._needs_token_type_ids = needs_token_type_ids
    return e, session


def test_token_type_ids_fed_as_zeros_when_model_requires() -> None:
    e, session = _make(needs_token_type_ids=True)
    e._encode(["hello", "world"])
    assert session.last_feed is not None
    assert set(session.last_feed) == {"input_ids", "attention_mask", "token_type_ids"}
    tti = session.last_feed["token_type_ids"]
    assert tti.shape == session.last_feed["input_ids"].shape
    assert not tti.any()


def test_token_type_ids_omitted_when_model_does_not_declare_it() -> None:
    e, session = _make(needs_token_type_ids=False)
    e._encode(["hello"])
    assert session.last_feed is not None
    assert set(session.last_feed) == {"input_ids", "attention_mask"}
