"""Cross-encoder reranking for search results.

Re-scores hybrid search results using a cross-encoder that reads query and
document together, producing more accurate relevance scores than embedding
similarity alone. Adds +7.8pp avg nDCG@10 across 13 NanoBEIR datasets.

Requires: ``pip install 'memsearch[local]'`` (sentence-transformers)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_cached_model: Any = None
_cached_model_name: str = ""

DEFAULT_RERANKER = "Alibaba-NLP/gte-reranker-modernbert-base"

# Cap cross-encoder sequence length to avoid OOM on long documents.
# Most cross-encoders support 512-8192 tokens but attention memory scales
# quadratically. 512 tokens is safe on any hardware and covers the majority
# of relevance signal (cross-encoders attend most to early tokens anyway).
_MAX_RERANK_TOKENS = 512


def rerank(
    query: str,
    results: list[dict[str, Any]],
    *,
    model_name: str = DEFAULT_RERANKER,
    top_k: int = 0,
) -> list[dict[str, Any]]:
    """Re-score search results with a cross-encoder.

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
        Results re-sorted by cross-encoder score. The ``score`` field
        is replaced with the cross-encoder score.
    """
    if not results:
        return []

    global _cached_model, _cached_model_name
    if _cached_model is None or _cached_model_name != model_name:
        from sentence_transformers import CrossEncoder

        _cached_model = CrossEncoder(
            model_name,
            max_length=_MAX_RERANK_TOKENS,
            trust_remote_code=True,
        )
        _cached_model_name = model_name
        logger.info("Loaded cross-encoder reranker: %s (max_length=%d)", model_name, _MAX_RERANK_TOKENS)

    pairs = [(query, r["content"]) for r in results]
    scores = _cached_model.predict(pairs)

    scored = [{**r, "score": float(scores[i])} for i, r in enumerate(results)]
    scored.sort(key=lambda x: x["score"], reverse=True)

    if top_k > 0:
        scored = scored[:top_k]
    return scored
