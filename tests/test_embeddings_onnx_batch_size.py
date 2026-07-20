"""ONNX provider batch-size default and override resolution.

Pure-function tests only: constructing OnnxEmbedding loads a real model,
so the resolution logic is tested through ``_resolve_batch_size``.
"""

import pytest

onnx_module = pytest.importorskip("memsearch.embeddings.onnx")


def test_default_batch_size_is_64():
    assert onnx_module.OnnxEmbedding._DEFAULT_BATCH_SIZE == 64


def test_zero_batch_size_resolves_to_provider_default():
    assert onnx_module.OnnxEmbedding._resolve_batch_size(0) == 64


def test_explicit_batch_size_overrides_default():
    assert onnx_module.OnnxEmbedding._resolve_batch_size(128) == 128
    assert onnx_module.OnnxEmbedding._resolve_batch_size(16) == 16
