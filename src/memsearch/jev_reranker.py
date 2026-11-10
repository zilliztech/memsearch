"""Optional remote reranking with TypeSafe's Jev decision model."""

from __future__ import annotations

import http.client
import json
import math
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_MODEL = "jev-latest"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"

# Adapted from https://docs.typesafe.ai/cookbooks/rerank_typesafe.
# Candidates live in separate questions, evaluated independently against the query.
INSTRUCTIONS = (
    "The query asks about information recorded in project memory. Could the candidate passage "
    "be a source for the answer — does it state the specific fact, decision, procedure, or "
    "event the query asks about?"
)
CRITERIA = {
    "true": (
        "The candidate passage states or establishes the specific information needed to "
        "answer the query, or a necessary supporting fact for a query requiring multiple passages."
    ),
    "false": (
        "The candidate passage is merely on a similar topic or project; it does not supply "
        "the specific information the query requires."
    ),
}


class JevReranker:
    """Score all candidates in one request without truncating their content.

    Credentials default to ``TYPESAFE_API_KEY``. Calling this class sends the
    query and candidate content to TypeSafe. Errors are surfaced to the caller;
    an unsuccessful request never silently becomes an unreranked result.
    """

    def __init__(self, model: str = DEFAULT_MODEL, *, api_key: str | None = None, timeout: float = 60.0) -> None:
        if not model or timeout <= 0:
            raise ValueError("A model and positive timeout are required")
        self.model = model
        self._api_key = api_key
        self.timeout = timeout

    def build_request(self, query: str, documents: list[str]) -> dict[str, Any]:
        """Build the batched Noul request, preserving every candidate's text."""
        if not isinstance(query, str) or any(not isinstance(doc, str) for doc in documents):
            raise TypeError("Query and documents must be strings")
        return {
            "model": self.model,
            "state": {"query_excerpt": query},
            "questions": {
                f"d{i}": {
                    "type": "noul",
                    "instructions": INSTRUCTIONS + "\nCandidate passage:\n" + doc,
                    "criteria": dict(CRITERIA),
                }
                for i, doc in enumerate(documents)
            },
        }

    @staticmethod
    def scores(response: dict[str, Any], count: int) -> list[float]:
        """Validate exact answer coverage and finite probabilities."""
        answers = response.get("answers")
        if not isinstance(answers, dict) or set(answers) != {f"d{i}" for i in range(count)}:
            raise ValueError("Jev returned missing or unexpected answers")
        scores = []
        for i in range(count):
            answer = answers[f"d{i}"]
            if not isinstance(answer, dict) or answer.get("type") != "noul":
                raise ValueError("Jev returned an unexpected answer type")
            score = answer.get("noul")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                raise ValueError("Jev returned a non-finite or non-numeric score")
            if not 0 <= score <= 1:
                raise ValueError("Jev score must be between zero and one")
            scores.append(float(score))
        return scores

    def evaluate(self, query: str, documents: list[str]) -> dict[str, Any]:
        """Return validated scores and provider usage metadata."""
        if not documents:
            return {"model": self.model, "answers": {}, "usage": {"input_tokens": 0, "output_tokens": 0}}
        api_key = self._api_key or os.environ.get("TYPESAFE_API_KEY")
        if not api_key:
            raise ValueError("Set TYPESAFE_API_KEY to enable Jev reranking")
        payload = self.build_request(query, documents)
        request = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Jev reranking failed (HTTP {exc.code})") from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError):
            raise RuntimeError("Jev reranking request failed or timed out") from None
        if not isinstance(result, dict):
            raise ValueError("Jev returned an invalid response")
        self.scores(result, len(documents))
        return result

    def rerank(self, query: str, results: list[dict[str, Any]], *, top_k: int = 0) -> list[dict[str, Any]]:
        """Return copies of candidates sorted by score, retaining tie order."""
        if top_k < 0:
            raise ValueError("top_k must be non-negative")
        if not results:
            return []
        response = self.evaluate(query, [r["content"] for r in results])
        scores = self.scores(response, len(results))
        ranked = [{**result, "score": score} for result, score in zip(results, scores, strict=True)]
        ranked.sort(key=lambda result: -result["score"])
        return ranked[:top_k] if top_k else ranked
