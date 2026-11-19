"""Shared onnxruntime telemetry opt-out, used by the ONNX embedding provider and reranker.

onnxruntime ships a platform telemetry provider that batches usage events and uploads them
over HTTP from its own worker thread.  On macOS that thread can outlive interpreter shutdown:
the response to a late upload is dispatched against state that is already being torn down, the
dispatch throws, and the process aborts with ``SIGABRT`` *after* the run succeeded — so a
``memsearch index`` that wrote every row still exits 134 for whoever checks the exit code.

An event that is never logged is never uploaded, so switching the events off removes that path
entirely.  It also keeps a local ONNX run off the network, which is the reason
``embeddings/onnx.py`` already resolves model files with ``local_files_only`` first.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def disable_telemetry(ort: Any) -> bool:
    """Switch off onnxruntime telemetry events.  Returns whether the switch was thrown.

    Call this before the first ``InferenceSession`` is created: onnxruntime emits a process-info
    event while it builds its environment, and only events suppressed before that point are
    guaranteed never to reach the uploader.

    ``disable_telemetry_events`` is a no-op on builds whose telemetry provider is a stub, and is
    absent from some third-party builds.  Both are treated as "nothing to do" — a telemetry
    preference must never be the reason embedding or reranking fails.
    """
    disable = getattr(ort, "disable_telemetry_events", None)
    if disable is None:
        return False
    try:
        disable()
    except Exception:
        logger.debug("Could not disable onnxruntime telemetry", exc_info=True)
        return False
    return True
