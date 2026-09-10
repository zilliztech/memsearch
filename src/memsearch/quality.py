"""Pre-write memory quality filter (Proposal 002).

A pure scorer for candidate memory sections: given the text a summarizer
produced and the recent sections already written to the journal, compute a
0-100 quality score and a capture action (``write`` / ``degrade`` /
``reject``). No I/O, no shared state, no LLM - the caller owns the file
system and the journal, which keeps this module trivially testable and
shareable across plugin capture paths via ``memsearch quality``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "DEGRADE_THRESHOLD_DEFAULT",
    "MIN_CONTENT_LENGTH_DEFAULT",
    "REJECT_THRESHOLD_DEFAULT",
    "QualityFilterSettings",
    "QualityVerdict",
    "decide",
    "evaluate_section",
    "extract_sections",
    "score_section",
]

MIN_CONTENT_LENGTH_DEFAULT = 40
DEGRADE_THRESHOLD_DEFAULT = 60
REJECT_THRESHOLD_DEFAULT = 30

Action = Literal["write", "degrade", "reject"]

# Vocabulary of notes that talk about the memory system itself rather than
# the work. Matched case-insensitively on word boundaries.
_META_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\[\s*memsearch\s*\]",
        r"\bmemsearch recall\b",
        r"\brecall available\b",
        r"\bmemory recall (status|hint|message)\b",
        r"\bmemory summary unavailable\b",
        r"\bmaintenance task\b",
        r"\bmemory journal\b",
        r"\bquality filter\b",
        r"\bsession[- ]wrapup\b",
    )
)

# Self-referential agent verbosity boilerplate. These openings mark notes
# about the conversation's shape rather than its content.
_BOILERPLATE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^\s*the user asked\b",
        r"^\s*user (asked|said|сообщил|спросил)\b",
        r"^\s*i (replied|answered|responded)\b",
        r"^\s*я (ответил|предложил)\b",
        r"\bas an ai\b",
        r"\bas requested\b",
        r"\bhere('?s| is) (a |the )?summary\b",
    )
)

_WHITESPACE_RE = re.compile(r"\s+")

_SHINGLE_SIZE = 4
_MAX_SHINGLES = 512  # cap for bounded, predictable scoring time


@dataclass(frozen=True)
class QualityVerdict:
    """Result of scoring one candidate section."""

    score: int
    action: Action
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"score": self.score, "action": self.action, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class QualityFilterSettings:
    """Knobs mirroring the ``[quality_filter]`` config section."""

    enabled: bool = True
    min_content_length: int = MIN_CONTENT_LENGTH_DEFAULT
    degrade_threshold: int = DEGRADE_THRESHOLD_DEFAULT
    reject_threshold: int = REJECT_THRESHOLD_DEFAULT


def _normalize(text: str) -> str:
    # Drop lone surrogates that can arrive from platform pipes (e.g. Windows stdin).
    cleaned = text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def _tokens(text: str) -> list[str]:
    return _normalize(text).lower().split()


def _token_shingles(tokens: Sequence[str], size: int = _SHINGLE_SIZE) -> set[int]:
    """Hash word shingles to 64-bit ints for cheap Jaccard comparison."""
    if len(tokens) < size:
        if not tokens:
            return set()
        digest = hashlib.sha1(" ".join(tokens).encode("utf-8")).digest()
        return {int.from_bytes(digest[:8], "big")}
    shingles: set[int] = set()
    for i in range(min(len(tokens) - size + 1, _MAX_SHINGLES)):
        digest = hashlib.sha1(" ".join(tokens[i : i + size]).encode("utf-8")).digest()
        shingles.add(int.from_bytes(digest[:8], "big"))
    return shingles


def _repetition_ratio(tokens: Sequence[str]) -> float:
    """Fraction of the text covered by repeated tokens (content words only)."""
    content = [t for t in tokens if len(t) > 3]
    if not content:
        return 0.0
    counts: dict[str, int] = {}
    for tok in content:
        counts[tok] = counts.get(tok, 0) + 1
    repeated = sum(c for c in counts.values() if c > 1)
    return repeated / len(content)


def _max_jaccard(candidate: str, recent_sections: Iterable[str]) -> float:
    cand_shingles = _token_shingles(_tokens(candidate))
    if not cand_shingles:
        return 0.0
    best = 0.0
    for section in recent_sections:
        other = _token_shingles(_tokens(section))
        if not other:
            continue
        union = len(cand_shingles | other)
        similarity = len(cand_shingles & other) / union if union else 0.0
        if similarity > best:
            best = similarity
    return best


def score_section(
    text: str,
    recent_sections: Sequence[str] | None = None,
    settings: QualityFilterSettings | None = None,
) -> tuple[int, tuple[str, ...]]:
    """Score a candidate memory section from 0 to 100.

    Higher is better; penalties subtract from a 100 start. Returns the score
    and the list of triggered penalty reasons. Pure: same inputs, same output,
    no side effects.
    """
    cfg = settings or QualityFilterSettings()
    reasons: list[str] = []
    score = 100

    normalized = _normalize(text)

    if any(p.search(text) for p in _META_PATTERNS):
        score -= 25
        reasons.append("meta-memory vocabulary")

    if any(p.search(text) for p in _BOILERPLATE_PATTERNS):
        score -= 10
        reasons.append("agent-verbosity boilerplate")

    if len(normalized) < cfg.min_content_length:
        score -= 30
        reasons.append(f"content shorter than min_content_length ({cfg.min_content_length})")

    tokens = _tokens(text)
    if tokens and _repetition_ratio(tokens) > 0.6:
        score -= 20
        reasons.append("high token repetition ratio")

    if recent_sections and _max_jaccard(text, recent_sections) > 0.8:
        score -= 40
        reasons.append("near-duplicate of a recent section")

    return max(score, 0), tuple(reasons)


def decide(score: int, settings: QualityFilterSettings | None = None) -> Action:
    """Map a quality score to a capture action."""
    cfg = settings or QualityFilterSettings()
    if score >= cfg.degrade_threshold:
        return "write"
    if score >= cfg.reject_threshold:
        return "degrade"
    return "reject"


def evaluate_section(
    text: str,
    recent_sections: Sequence[str] | None = None,
    settings: QualityFilterSettings | None = None,
) -> QualityVerdict:
    """Score and decide in one call - the main entry point for capture paths."""
    cfg = settings or QualityFilterSettings()
    if not cfg.enabled:
        return QualityVerdict(score=100, action="write", reasons=("quality filter disabled",))
    score, reasons = score_section(text, recent_sections, cfg)
    return QualityVerdict(score=score, action=decide(score, cfg), reasons=reasons)


_SECTION_SPLIT_RE = re.compile(r"^#{2,6}\s+\S", re.MULTILINE)
_HTML_ANCHOR_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def extract_sections(journal_text: str) -> list[str]:
    """Split a daily journal file into recent sections for near-dup checks.

    Strips HTML anchor comments (session/turn metadata) so that two different
    turns from the same session are not marked near-duplicates by their shared
    anchor. Sections without any heading are kept as one block.
    """
    stripped = _HTML_ANCHOR_RE.sub("", journal_text)
    parts = [p for p in _SECTION_SPLIT_RE.split(stripped) if _normalize(p)]
    return [_normalize(p) for p in parts]
