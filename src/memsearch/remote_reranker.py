"""Remote reranking against a rerank HTTP service.

Model names prefixed with ``remote:`` select this backend, e.g.
``remote:Qwen3-Reranker-8B``. The endpoint comes from
``MEMSEARCH_REMOTE_RERANKER_URL`` (or the constructor) and defaults to the
loopback port used by an SSH tunnel to a self-hosted reranker deployment.
Hosted rerank APIs serving the same payload shape are reached by pointing
``MEMSEARCH_REMOTE_RERANKER_URL`` at them and setting
``MEMSEARCH_REMOTE_RERANKER_API_KEY`` for bearer authentication.

The service scores every candidate against the query and returns
``results[]`` of ``{"index", "relevance_score"}`` — the shape served by vLLM's
``/v1/rerank`` and compatible relays. Candidates the service leaves out (a
``top_n`` response shorter than the request) are dropped, so the caller sees
exactly what the reranker ranked highest. Errors are surfaced to the caller;
an unsuccessful request never silently becomes an unreranked result.
"""

from __future__ import annotations

import http.client
import json
import math
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

DEFAULT_MODEL = "Qwen3-Reranker-8B"
DEFAULT_URL = "http://127.0.0.1:8081/v1/rerank"
URL_ENV_VAR = "MEMSEARCH_REMOTE_RERANKER_URL"
API_KEY_ENV_VAR = "MEMSEARCH_REMOTE_RERANKER_API_KEY"


class RemoteReranker:
    """Score all candidates in one request, preserving their original fields.

    ``timeout`` bounds one HTTP request. Set a larger value when the service
    runs the cross-encoder on CPU: a nine-candidate batch measured 10.6 s on a
    CPU deployment reached through a loopback tunnel.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        url: str | None = None,
        timeout: float = 60.0,
        api_key: str | None = None,
    ) -> None:
        if not model or timeout <= 0:
            raise ValueError("A model and positive timeout are required")
        self.model = model
        self.url = url or os.environ.get(URL_ENV_VAR) or DEFAULT_URL
        # SSRF hardening: the URL is operator-configured, but only real
        # HTTP(S) endpoints are acceptable fetch targets — never file://,
        # ftp:// or other arbitrary schemes.
        if urlsplit(self.url).scheme not in ("http", "https"):
            raise ValueError("Remote reranker URL must use http or https")
        self.timeout = timeout
        # Optional bearer token. Empty for the default self-hosted service;
        # set for hosted rerank APIs that authenticate the endpoint with a
        # bearer token.
        self.api_key = api_key or os.environ.get(API_KEY_ENV_VAR) or ""

    def build_request(self, query: str, documents: list[str]) -> dict[str, Any]:
        """Build the rerank payload, preserving every candidate's text."""
        if not isinstance(query, str) or any(not isinstance(doc, str) for doc in documents):
            raise TypeError("Query and documents must be strings")
        return {"model": self.model, "query": query, "documents": list(documents)}

    @staticmethod
    def scores(response: dict[str, Any], count: int) -> dict[int, float]:
        """Validate the returned indices and relevance scores.

        Maps each candidate index to its score. Indices must be in range,
        unique, and paired with a finite numeric score.
        """
        entries = response.get("results")
        if not isinstance(entries, list):
            raise ValueError("Reranker response has no results list")
        scored: dict[int, float] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Reranker returned an unexpected result entry")
            index = entry.get("index")
            score = entry.get("relevance_score")
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count:
                raise ValueError("Reranker returned an out-of-range index")
            if index in scored:
                raise ValueError("Reranker returned a duplicate index")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                raise ValueError("Reranker returned a non-finite or non-numeric score")
            scored[index] = float(score)
        return scored

    def evaluate(self, query: str, documents: list[str]) -> dict[str, Any]:
        """Return the service response for scoring, having posted every candidate."""
        if not documents:
            return {"model": self.model, "results": []}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.url,
            data=json.dumps(self.build_request(query, documents)).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Remote reranking failed (HTTP {exc.code})") from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError):
            raise RuntimeError("Remote reranking request failed or timed out") from None
        if not isinstance(result, dict):
            raise ValueError("Remote reranker returned an invalid response")
        return result

    def rerank(self, query: str, results: list[dict[str, Any]], *, top_k: int = 0) -> list[dict[str, Any]]:
        """Return copies of candidates sorted by score, retaining tie order.

        ``top_k`` of 0 keeps every candidate the service ranked.
        """
        if top_k < 0:
            raise ValueError("top_k must be non-negative")
        if not results:
            return []
        response = self.evaluate(query, [r["content"] for r in results])
        scored = self.scores(response, len(results))
        ranked = [
            {**results[index], "score": score}
            for index, score in sorted(scored.items(), key=lambda pair: (-pair[1], pair[0]))
        ]
        return ranked[:top_k] if top_k else ranked
