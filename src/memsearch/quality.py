"""Deterministic, fail-open scoring for captured memory sections.

The scorer deliberately performs no I/O and makes no model calls.  Capture
integrations supply any recent sections needed for duplicate detection, then
choose whether to write, mark degraded, or skip the candidate.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# These phrases identify notes about the memory mechanism rather than durable
# project/user knowledge.  Matching is intentionally narrow: a false positive
# must not discard a useful captured turn.
_META_MEMORY_PHRASES = (
    "[memsearch]",
    "memory summary unavailable",
    "memory recall",
    "memory plugin",
    "memsearch plugin",
    "retrieved memory context attached",
)
_BOILERPLATE_PHRASES = (
    "the user asked",
    "i replied",
    "the assistant replied",
    "пользователь попросил",
    "пользователь спросил",
    "ассистент ответил",
)


@dataclass(frozen=True)
class QualityAssessment:
    """One deterministic quality verdict for a candidate section."""

    score: int
    action: str
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable verdict."""
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def normalize_text(text: object) -> str:
    """Normalize arbitrary captured text without failing on lone surrogates."""
    value = str(text or "")
    # Python can hold malformed UTF-16 surrogate code points, while captures may
    # later cross UTF-8 process boundaries.  Replace them deterministically here.
    value = value.encode("utf-8", errors="replace").decode("utf-8")
    value = _COMMENT_RE.sub(" ", value)
    return " ".join(value.casefold().split())


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _shingles(tokens: list[str]) -> set[tuple[str, ...]]:
    if len(tokens) < 3:
        return {(token,) for token in tokens}
    return {tuple(tokens[index : index + 3]) for index in range(len(tokens) - 2)}


def _jaccard(left: set[tuple[str, ...]], right: set[tuple[str, ...]]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def score_section(
    text: object,
    recent_sections: Iterable[object] = (),
    *,
    enabled: bool = True,
    min_content_length: int = 40,
    degrade_threshold: int = 60,
    reject_threshold: int = 30,
) -> QualityAssessment:
    """Score one candidate section using deterministic, conservative penalties.

    ``recent_sections`` is deliberately supplied by the caller, which keeps
    this function pure and lets each platform choose its own journal window.
    Disabled scoring returns a normal write verdict, preserving existing capture
    behaviour exactly.
    """
    if not enabled:
        return QualityAssessment(score=100, action="write")
    numeric_values = (min_content_length, degrade_threshold, reject_threshold)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in numeric_values):
        raise ValueError("quality thresholds must be integers")
    if min_content_length < 0 or not 0 <= reject_threshold <= degrade_threshold <= 100:
        raise ValueError("quality thresholds must satisfy 0 <= reject <= degrade <= 100")

    normalized = normalize_text(text)
    tokens = _tokens(normalized)
    score = 100
    reasons: list[str] = []

    if any(phrase in normalized for phrase in _META_MEMORY_PHRASES):
        score -= 25
        reasons.append("meta-memory")
    if any(phrase in normalized for phrase in _BOILERPLATE_PHRASES):
        score -= 10
        reasons.append("boilerplate")
    if len(normalized) < min_content_length:
        score -= 30
        reasons.append("too-short")
    if tokens and 1 - (len(set(tokens)) / len(tokens)) > 0.6:
        score -= 20
        reasons.append("repetitive")

    candidate_shingles = _shingles(tokens)
    for recent in recent_sections:
        recent_shingles = _shingles(_tokens(normalize_text(recent)))
        if _jaccard(candidate_shingles, recent_shingles) > 0.8:
            score -= 40
            reasons.append("near-duplicate")
            break

    score = max(0, min(100, score))
    if score >= degrade_threshold:
        action = "write"
    elif score >= reject_threshold:
        action = "degrade"
    else:
        action = "reject"
    return QualityAssessment(score=score, action=action, reasons=tuple(reasons))
