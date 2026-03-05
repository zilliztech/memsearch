"""Markdown chunking — split markdown files into semantic chunks by headings."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    """A single chunk extracted from a markdown document."""

    content: str
    source: str  # file path
    heading: str  # nearest heading (empty string for preamble)
    heading_level: int  # 0 for preamble
    start_line: int
    end_line: int
    content_hash: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.content_hash:
            h = hashlib.sha256(self.content.encode()).hexdigest()[:16]
            object.__setattr__(self, "content_hash", h)


def compute_chunk_id(
    source: str,
    start_line: int,
    end_line: int,
    content_hash: str,
    model: str,
) -> str:
    """Compute a composite chunk ID matching OpenClaw's format.

    ``hash(source:path:startLine:endLine:contentHash:model)``
    """
    raw = f"markdown:{source}:{start_line}:{end_line}:{content_hash}:{model}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def chunk_markdown(
    text: str,
    source: str = "",
    *,
    max_chunk_size: int = 1500,
    overlap_lines: int = 2,
) -> list[Chunk]:
    """Split markdown *text* into chunks, breaking on headings.

    Chunks that exceed *max_chunk_size* characters are split further at
    paragraph boundaries.  A small *overlap_lines* context is carried
    forward to preserve continuity.
    """
    lines = text.split("\n")
    # Find all heading positions
    heading_positions: list[tuple[int, int, str]] = []  # (line_idx, level, title)
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            heading_positions.append((i, len(m.group(1)), m.group(2).strip()))

    # Build sections between headings
    sections: list[tuple[int, int, str, int]] = []  # (start, end, heading, level)
    if not heading_positions or heading_positions[0][0] > 0:
        end = heading_positions[0][0] if heading_positions else len(lines)
        sections.append((0, end, "", 0))

    for idx, (line_idx, level, title) in enumerate(heading_positions):
        next_start = heading_positions[idx + 1][0] if idx + 1 < len(heading_positions) else len(lines)
        sections.append((line_idx, next_start, title, level))

    chunks: list[Chunk] = []
    for start, end, heading, level in sections:
        section_text = "\n".join(lines[start:end]).strip()
        if not section_text:
            continue

        if len(section_text) <= max_chunk_size:
            chunks.append(
                Chunk(
                    content=section_text,
                    source=source,
                    heading=heading,
                    heading_level=level,
                    start_line=start + 1,
                    end_line=end,
                )
            )
        else:
            # Split large sections at paragraph boundaries
            chunks.extend(
                _split_large_section(
                    lines[start:end],
                    source=source,
                    heading=heading,
                    heading_level=level,
                    base_line=start,
                    max_size=max_chunk_size,
                    overlap=overlap_lines,
                )
            )

    return chunks


def _split_large_section(
    lines: list[str],
    *,
    source: str,
    heading: str,
    heading_level: int,
    base_line: int,
    max_size: int,
    overlap: int,
) -> list[Chunk]:
    """Split a large section into smaller chunks at paragraph boundaries."""
    chunks: list[Chunk] = []
    current_lines: list[str] = []
    current_start = 0

    for i, line in enumerate(lines):
        current_lines.append(line)
        text = "\n".join(current_lines)

        # Check if we hit the size limit at a paragraph boundary
        is_paragraph_break = line.strip() == "" and i + 1 < len(lines)
        is_last_line = i == len(lines) - 1

        if (len(text) >= max_size and is_paragraph_break) or is_last_line:
            content = text.strip()
            if content:
                chunks.append(
                    Chunk(
                        content=content,
                        source=source,
                        heading=heading,
                        heading_level=heading_level,
                        start_line=base_line + current_start + 1,
                        end_line=base_line + i + 1,
                    )
                )
            # Carry overlap lines forward
            overlap_start = max(0, len(current_lines) - overlap)
            current_lines = current_lines[overlap_start:] if not is_last_line else []
            current_start = i + 1 - len(current_lines)

    return chunks
