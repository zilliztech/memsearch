"""Cross-encoder reranking for search results.

Re-scores hybrid search results using a cross-encoder that reads query and
document together, producing more accurate relevance scores than embedding
similarity alone.

Two backends are supported, auto-detected at runtime:
  1. ONNX Runtime (preferred) — lightweight, CPU-only, included in ``memsearch[onnx]``
  2. sentence-transformers CrossEncoder — PyTorch-based, included in ``memsearch[local]``

If neither is installed, reranking is silently skipped.
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_RERANKER = "Alibaba-NLP/gte-reranker-modernbert-base"

# Cap cross-encoder sequence length to avoid OOM on long documents.
_MAX_RERANK_TOKENS = 512


# ======================================================================
# Backend detection
# ======================================================================

def _detect_backend() -> str:
    """Return 'onnx', 'torch', or 'none'."""
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
        return "onnx"
    except ImportError:
        pass
    try:
        from sentence_transformers import CrossEncoder  # noqa: F401
        return "torch"
    except ImportError:
        pass
    return "none"


# ======================================================================
# ONNX backend
# ======================================================================

# Known ONNX cross-encoder repos and their recommended files.
_KNOWN_ONNX_MODELS: dict[str, tuple[str, str]] = {
    "Alibaba-NLP/gte-reranker-modernbert-base": (
        "Alibaba-NLP/gte-reranker-modernbert-base",
        "onnx/model_quantized.onnx",
    ),
    "cross-encoder/ms-marco-MiniLM-L6-v2": (
        "cross-encoder/ms-marco-MiniLM-L6-v2",
        "onnx/model.onnx",
    ),
}


@dataclass(slots=True)
class _OnnxCachedModel:
    """Holds a loaded ONNX session + tokenizer for reuse."""

    session: Any  # onnxruntime.InferenceSession
    tokenizer: Any  # tokenizers.Tokenizer
    input_names: set[str] = field(default_factory=set)


_onnx_cache: dict[str, _OnnxCachedModel] = {}
_onnx_cache_lock = threading.Lock()


def _find_onnx_file(repo_id: str, repo_files: list[str]) -> str:
    """Pick the best ONNX file from a repo's file listing."""
    onnx_files = [f for f in repo_files if f.endswith(".onnx")]
    if not onnx_files:
        raise ValueError(
            f"No .onnx files found in {repo_id}. "
            f"Export one with: optimum-cli export onnx --model {repo_id} output/"
        )
    for preferred in [
        "onnx/model_quantized.onnx",
        "onnx/model_int8.onnx",
        "onnx/model.onnx",
        "model_quantized.onnx",
        "model.onnx",
    ]:
        if preferred in onnx_files:
            return preferred
    return onnx_files[0]


def _load_onnx_model(model_name: str) -> _OnnxCachedModel:
    """Download (if needed) and load an ONNX cross-encoder model."""
    with _onnx_cache_lock:
        if model_name in _onnx_cache:
            return _onnx_cache[model_name]

    from huggingface_hub import hf_hub_download, list_repo_files
    from tokenizers import Tokenizer

    repo_id = model_name
    onnx_file = None
    if model_name in _KNOWN_ONNX_MODELS:
        repo_id, onnx_file = _KNOWN_ONNX_MODELS[model_name]

    repo_files = list(list_repo_files(repo_id))
    if onnx_file is None:
        onnx_file = _find_onnx_file(repo_id, repo_files)

    # Download external data file if present (e.g. model.onnx_data)
    data_file = onnx_file + "_data"
    if data_file in repo_files:
        hf_hub_download(repo_id, data_file)
    model_path = hf_hub_download(repo_id, onnx_file)

    tok_path = hf_hub_download(repo_id, "tokenizer.json")
    tokenizer = Tokenizer.from_file(tok_path)
    tokenizer.enable_truncation(max_length=_MAX_RERANK_TOKENS)
    tokenizer.no_padding()

    import onnxruntime as ort

    session = ort.InferenceSession(model_path)
    input_names = {inp.name for inp in session.get_inputs()}

    cached = _OnnxCachedModel(session=session, tokenizer=tokenizer, input_names=input_names)
    logger.info("Loaded ONNX cross-encoder reranker: %s (%s)", model_name, onnx_file)

    with _onnx_cache_lock:
        if model_name not in _onnx_cache:
            _onnx_cache[model_name] = cached
        return _onnx_cache[model_name]


def _extract_scores(logits: np.ndarray) -> list[float]:
    """Convert raw model logits to relevance scores."""
    if logits.ndim == 2 and logits.shape[1] == 1:
        return [1.0 / (1.0 + math.exp(-float(x))) for x in logits[:, 0]]
    if logits.ndim == 2 and logits.shape[1] == 2:
        exp = np.exp(logits - logits.max(axis=1, keepdims=True))
        softmax = exp / exp.sum(axis=1, keepdims=True)
        return softmax[:, 1].tolist()
    return [1.0 / (1.0 + math.exp(-float(x))) for x in logits.flatten()]


def _rerank_onnx(
    query: str, results: list[dict[str, Any]], model_name: str, top_k: int
) -> list[dict[str, Any]]:
    """Rerank using ONNX Runtime backend."""
    model = _load_onnx_model(model_name)

    pairs = [(query, r["content"]) for r in results]
    encoded = [model.tokenizer.encode(*pair) for pair in pairs]

    max_len = max(len(e.ids) for e in encoded)
    batch_size = len(encoded)

    input_ids = np.zeros((batch_size, max_len), dtype=np.int64)
    attention_mask = np.zeros((batch_size, max_len), dtype=np.int64)
    token_type_ids = np.zeros((batch_size, max_len), dtype=np.int64)

    for i, enc in enumerate(encoded):
        length = len(enc.ids)
        input_ids[i, :length] = enc.ids
        attention_mask[i, :length] = enc.attention_mask
        token_type_ids[i, :length] = enc.type_ids

    feed: dict[str, np.ndarray] = {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
    }
    if "token_type_ids" in model.input_names:
        feed["token_type_ids"] = token_type_ids

    logits = model.session.run(None, feed)[0]
    scores = _extract_scores(logits)

    scored = [{**r, "score": float(s)} for r, s in zip(results, scores, strict=True)]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k] if top_k > 0 else scored


# ======================================================================
# PyTorch (sentence-transformers) backend
# ======================================================================

_torch_cache: dict[str, Any] = {}  # model_name -> CrossEncoder instance
_torch_cache_lock = threading.Lock()


def _load_torch_model(model_name: str) -> Any:
    """Load a sentence-transformers CrossEncoder model."""
    with _torch_cache_lock:
        if model_name in _torch_cache:
            return _torch_cache[model_name]

    from sentence_transformers import CrossEncoder

    model = CrossEncoder(model_name, max_length=_MAX_RERANK_TOKENS)
    logger.info("Loaded PyTorch cross-encoder reranker: %s", model_name)

    with _torch_cache_lock:
        if model_name not in _torch_cache:
            _torch_cache[model_name] = model
        return _torch_cache[model_name]


def _rerank_torch(
    query: str, results: list[dict[str, Any]], model_name: str, top_k: int
) -> list[dict[str, Any]]:
    """Rerank using sentence-transformers CrossEncoder backend."""
    model = _load_torch_model(model_name)

    pairs = [(query, r["content"]) for r in results]
    raw_scores = model.predict(pairs)

    scores = [float(s) for s in raw_scores]
    scored = [{**r, "score": s} for r, s in zip(results, scores, strict=True)]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k] if top_k > 0 else scored


# ======================================================================
# Public API
# ======================================================================

def rerank(
    query: str,
    results: list[dict[str, Any]],
    *,
    model_name: str = DEFAULT_RERANKER,
    top_k: int = 0,
) -> list[dict[str, Any]]:
    """Re-score search results with a cross-encoder.

    Automatically selects the best available backend:
      1. ONNX Runtime (``memsearch[onnx]``) — preferred, lightweight
      2. sentence-transformers (``memsearch[local]``) — PyTorch fallback

    Parameters
    ----------
    query:
        The original search query.
    results:
        Search results from MilvusStore.search(). Each dict must have
        a ``content`` key with the chunk text.
    model_name:
        HuggingFace model ID for the cross-encoder.
    top_k:
        Return only the top-k results after reranking.
        0 means return all results (re-sorted).

    Returns
    -------
    list[dict]
        Results re-sorted by cross-encoder score.
    """
    if not results:
        return []

    backend = _detect_backend()
    if backend == "onnx":
        return _rerank_onnx(query, results, model_name, top_k)
    if backend == "torch":
        return _rerank_torch(query, results, model_name, top_k)

    logger.warning(
        "Reranker model %r configured but neither onnxruntime nor "
        "sentence-transformers is installed; skipping reranking",
        model_name,
    )
    return results
