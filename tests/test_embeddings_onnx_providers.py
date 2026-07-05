"""Tests for ONNX execution-provider selection.

_select_providers is a pure function, so these run without onnxruntime
or any model download.
"""

from __future__ import annotations

from memsearch.embeddings.onnx import _CPU_PROVIDER, _select_providers

_MACOS_PIP_WHEEL = ["CoreMLExecutionProvider", "AzureExecutionProvider", "CPUExecutionProvider"]
_CUDA_BUILD = ["CUDAExecutionProvider", "CPUExecutionProvider"]
_CPU_ONLY = ["CPUExecutionProvider"]


def test_auto_stays_cpu_on_macos_wheel() -> None:
    # CoreML is opt-in only: on the default int8 bge-m3 export it measured
    # ~60x slower than CPU (220 partitions, 1490/2384 nodes placed).
    assert _select_providers(_MACOS_PIP_WHEEL) == [_CPU_PROVIDER]


def test_auto_prefers_cuda_when_available() -> None:
    assert _select_providers(_CUDA_BUILD) == ["CUDAExecutionProvider", "CPUExecutionProvider"]


def test_coreml_available_via_explicit_request() -> None:
    selected = _select_providers(_MACOS_PIP_WHEEL, ["CoreMLExecutionProvider"])
    assert selected == ["CoreMLExecutionProvider", "CPUExecutionProvider"]


def test_auto_never_picks_remote_providers() -> None:
    # AzureExecutionProvider is available on the stock macOS wheel but must
    # never be selected implicitly.
    assert "AzureExecutionProvider" not in _select_providers(_MACOS_PIP_WHEEL)


def test_cpu_only_runtime_stays_cpu() -> None:
    assert _select_providers(_CPU_ONLY) == [_CPU_PROVIDER]


def test_requested_order_is_kept_and_filtered() -> None:
    selected = _select_providers(_MACOS_PIP_WHEEL, ["CoreMLExecutionProvider", "CUDAExecutionProvider"])
    assert selected == ["CoreMLExecutionProvider", "CPUExecutionProvider"]


def test_requested_unavailable_falls_back_to_cpu() -> None:
    assert _select_providers(_CPU_ONLY, ["CUDAExecutionProvider"]) == [_CPU_PROVIDER]


def test_cpu_always_appended_to_explicit_request() -> None:
    # An accelerator-only request must not produce an accelerator-only list;
    # session creation would hard-fail on models the provider cannot place.
    selected = _select_providers(_CUDA_BUILD, ["CUDAExecutionProvider"])
    assert selected[-1] == _CPU_PROVIDER
