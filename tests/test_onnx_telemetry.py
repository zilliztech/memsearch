"""onnxruntime telemetry must be switched off before any InferenceSession is built.

onnxruntime uploads usage events from its own worker thread; on macOS that thread can outlive
interpreter shutdown and abort an otherwise successful ``memsearch index`` with SIGABRT (#747).
The abort is a timing race that cannot be provoked on demand, so these tests assert the property
that removes it — the switch is thrown, and thrown *before* the session exists — using a stub
onnxruntime, so no wheel and no model download are needed.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

import memsearch.reranker as reranker_mod
from memsearch.embeddings.onnx import OnnxEmbedding
from memsearch.onnx_telemetry import disable_telemetry
from memsearch.reranker import _load_onnx_model


class _StubEncoding:
    def __init__(self) -> None:
        self.ids = [1, 2, 3]
        self.attention_mask = [1, 1, 0]
        self.type_ids = [0, 0, 0]


class _StubTokenizer:
    @staticmethod
    def from_file(_path: str) -> _StubTokenizer:
        return _StubTokenizer()

    def enable_padding(self, **_kwargs) -> None: ...

    def enable_truncation(self, **_kwargs) -> None: ...

    def no_padding(self) -> None: ...

    def encode_batch(self, texts):
        return [_StubEncoding() for _ in texts]

    def encode(self, *_pair):
        return _StubEncoding()


class _StubSession:
    """Mimics the parts of ort.InferenceSession both call sites touch."""

    def get_outputs(self):
        return [types.SimpleNamespace(name="dense_vecs")]

    def get_inputs(self):
        return [types.SimpleNamespace(name="input_ids"), types.SimpleNamespace(name="attention_mask")]

    def run(self, _output_names, feed):
        return [np.ones((len(feed["input_ids"]), 4), dtype=np.float32)]


def _fake_onnxruntime(calls: list[str], *, switch: str = "present") -> types.ModuleType:
    """A stand-in onnxruntime that records the order of the calls memsearch makes.

    ``switch`` selects how ``disable_telemetry_events`` behaves: ``"present"`` records the call,
    ``"missing"`` omits the attribute (older / trimmed builds), ``"raises"`` fails the call.
    """
    mod = types.ModuleType("onnxruntime")

    def inference_session(_model_path, *_args, **_kwargs):
        calls.append("InferenceSession")
        return _StubSession()

    mod.InferenceSession = inference_session

    if switch == "present":

        def disable_telemetry_events() -> None:
            calls.append("disable_telemetry_events")

        mod.disable_telemetry_events = disable_telemetry_events
    elif switch == "raises":

        def disable_telemetry_events() -> None:
            calls.append("disable_telemetry_events")
            raise RuntimeError("no telemetry provider in this build")

        mod.disable_telemetry_events = disable_telemetry_events

    return mod


def _fake_huggingface_hub() -> types.ModuleType:
    mod = types.ModuleType("huggingface_hub")
    mod.hf_hub_download = lambda repo, filename, **_kwargs: f"/stub/{repo}/{filename}"
    mod.list_repo_files = lambda _repo: ["tokenizer.json", "model_quantized.onnx", "onnx/model_quantized.onnx"]
    return mod


def _fake_tokenizers() -> types.ModuleType:
    mod = types.ModuleType("tokenizers")
    mod.Tokenizer = _StubTokenizer
    return mod


@pytest.fixture
def onnx_stubs(monkeypatch):
    """Install stub onnxruntime / huggingface_hub / tokenizers and return the call log."""
    calls: list[str] = []

    def install(*, switch: str = "present") -> list[str]:
        monkeypatch.setitem(sys.modules, "onnxruntime", _fake_onnxruntime(calls, switch=switch))
        monkeypatch.setitem(sys.modules, "huggingface_hub", _fake_huggingface_hub())
        monkeypatch.setitem(sys.modules, "tokenizers", _fake_tokenizers())
        return calls

    return install


@pytest.fixture(autouse=True)
def _clear_reranker_cache():
    reranker_mod._onnx_cache.clear()
    yield
    reranker_mod._onnx_cache.clear()


# ======================================================================
# Embedding provider
# ======================================================================


def test_embedding_disables_telemetry_before_creating_the_session(onnx_stubs) -> None:
    calls = onnx_stubs()

    OnnxEmbedding()

    assert calls == ["disable_telemetry_events", "InferenceSession"]


def test_embedding_works_when_the_build_has_no_telemetry_switch(onnx_stubs) -> None:
    calls = onnx_stubs(switch="missing")

    provider = OnnxEmbedding()

    assert calls == ["InferenceSession"]
    assert provider.dimension == 4


def test_embedding_survives_a_failing_telemetry_switch(onnx_stubs) -> None:
    calls = onnx_stubs(switch="raises")

    provider = OnnxEmbedding()

    assert calls == ["disable_telemetry_events", "InferenceSession"]
    assert provider.dimension == 4


# ======================================================================
# Reranker
# ======================================================================


def test_reranker_disables_telemetry_before_creating_the_session(onnx_stubs) -> None:
    calls = onnx_stubs()

    _load_onnx_model("cross-encoder/ms-marco-MiniLM-L6-v2")

    assert calls == ["disable_telemetry_events", "InferenceSession"]


def test_reranker_works_when_the_build_has_no_telemetry_switch(onnx_stubs) -> None:
    calls = onnx_stubs(switch="missing")

    cached = _load_onnx_model("cross-encoder/ms-marco-MiniLM-L6-v2")

    assert calls == ["InferenceSession"]
    assert cached.input_names == {"input_ids", "attention_mask"}


# ======================================================================
# Helper
# ======================================================================


def test_disable_telemetry_reports_whether_the_switch_was_thrown() -> None:
    calls: list[str] = []

    assert disable_telemetry(_fake_onnxruntime(calls)) is True
    assert disable_telemetry(_fake_onnxruntime(calls, switch="missing")) is False
    assert disable_telemetry(_fake_onnxruntime(calls, switch="raises")) is False
