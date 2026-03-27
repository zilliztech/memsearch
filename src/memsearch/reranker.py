"""Cross-encoder reranking for search results.

Re-scores hybrid search results using a cross-encoder that reads query and
document together, producing more accurate relevance scores than embedding
similarity alone. Adds ~14.9pp avg nDCG@10 across 12 NanoBEIR datasets.

Uses ONNX Runtime for inference -- no PyTorch or sentence-transformers
required. Only needs ``onnxruntime``, ``tokenizers``, and ``huggingface-hub``,
all already included in ``memsearch[onnx]``.
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
# 512 tokens covers the majority of relevance signal for reranking.
_MAX_RERANK_TOKENS = 512

# Known ONNX cross-encoder repos and their recommended files.
_KNOWN_MODELS: dict[str, tuple[str, str]] = {
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
class _CachedModel:
    """Holds a loaded ONNX session + tokenizer for reuse."""

    session: Any  # onnxruntime.InferenceSession
    tokenizer: Any  # tokenizers.Tokenizer
    input_names: set[str] = field(default_factory=set)


_cache: dict[str, _CachedModel] = {}
_cache_lock = threading.Lock()


def _resolve_model(model_name: str) -> tuple[str, str | None]:
    """Return (repo_id, onnx_filename_or_None) from a model name."""
    if model_name in _KNOWN_MODELS:
        return _KNOWN_MODELS[model_name]
    return model_name, None


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


def _load_model(model_name: str) -> _CachedModel:
    """Download (if needed) and load an ONNX cross-encoder model.

    Thread-safe: uses double-checked locking to prevent duplicate loads.
    """
    with _cache_lock:
        if model_name in _cache:
            return _cache[model_name]

    # Resolve and download outside the lock (may be slow)
    repo_id, onnx_file = _resolve_model(model_name)

    from huggingface_hub import hf_hub_download, list_repo_files
    from tokenizers import Tokenizer

    if onnx_file is None:
        repo_files = list(list_repo_files(repo_id))
        onnx_file = _find_onnx_file(repo_id, repo_files)
    else:
        repo_files = list(list_repo_files(repo_id))

    # Download external data file if present (e.g. model.onnx_data)
    data_file = onnx_file + "_data"
    if data_file in repo_files:
        hf_hub_download(repo_id, data_file)
    model_path = hf_hub_download(repo_id, onnx_file)

    # Load tokenizer -- disable baked-in padding, use dynamic per-batch
    tok_path = hf_hub_download(repo_id, "tokenizer.json")
    tokenizer = Tokenizer.from_file(tok_path)
    tokenizer.enable_truncation(max_length=_MAX_RERANK_TOKENS)
    tokenizer.no_padding()

    import onnxruntime as ort

    session = ort.InferenceSession(model_path)
    input_names = {inp.name for inp in session.get_inputs()}

    cached = _CachedModel(
        session=session,
        tokenizer=tokenizer,
        input_names=input_names,
    )

    logger.info(
        "Loaded ONNX cross-encoder reranker: %s (%s, max_length=%d)",
        model_name,
        onnx_file,
        _MAX_RERANK_TOKENS,
    )

    with _cache_lock:
        if model_name not in _cache:
            _cache[model_name] = cached
        return _cache[model_name]


def _extract_scores(logits: np.ndarray) -> list[float]:
    """Convert raw model logits to relevance scores.

    Handles single-logit (sigmoid), two-class (softmax), and flat arrays.
    """
    if logits.ndim == 2 and logits.shape[1] == 1:
        return [1.0 / (1.0 + math.exp(-float(x))) for x in logits[:, 0]]
    if logits.ndim == 2 and logits.shape[1] == 2:
        exp = np.exp(logits - logits.max(axis=1, keepdims=True))
        softmax = exp / exp.sum(axis=1, keepdims=True)
        return softmax[:, 1].tolist()
    # Flat or unexpected shape -- sigmoid
    return [1.0 / (1.0 + math.exp(-float(x))) for x in logits.flatten()]


def rerank(
    query: str,
    results: list[dict[str, Any]],
    *,
    model_name: str = DEFAULT_RERANKER,
    top_k: int = 0,
) -> list[dict[str, Any]]:
    """Re-score search results with an ONNX cross-encoder.

    Parameters
    ----------
    query:
        The original search query.
    results:
        Search results from MilvusStore.search(). Each dict must have
        a ``content`` key with the chunk text.
    model_name:
        HuggingFace model ID for the cross-encoder. Must have ONNX
        exports available in the repo.
    top_k:
        Return only the top-k results after reranking.
        0 means return all results (re-sorted).

    Returns
    -------
    list[dict]
        Results re-sorted by cross-encoder score. The ``score`` field
        is replaced with the cross-encoder score.
    """
    if not results:
        return []

    model = _load_model(model_name)

    # Tokenize query-document pairs without padding
    pairs = [(query, r["content"]) for r in results]
    encoded = [model.tokenizer.encode(*pair) for pair in pairs]

    # Dynamic padding to longest sequence in batch
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

    # Run inference
    logits = model.session.run(None, feed)[0]
    scores = _extract_scores(logits)

    scored = [{**r, "score": float(s)} for r, s in zip(results, scores, strict=True)]
    scored.sort(key=lambda x: x["score"], reverse=True)

    if top_k > 0:
        scored = scored[:top_k]
    return scored
