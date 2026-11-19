"""Progressive-disclosure expansion of an indexed chunk.

``memsearch expand`` and the MCP ``memory_expand`` tool both need the same
thing: given a chunk's line range and heading level, return the full
markdown section it lives in.  The logic lives here so the CLI and the MCP
server share one implementation.
"""

from __future__ import annotations

from .chunker import _HEADING_RE


def extract_section(
    all_lines: list[str],
    start_line: int,
    heading_level: int,
) -> tuple[str, int, int]:
    """Extract the full section containing the chunk.

    Walks backward to find the section heading, then forward to the next
    heading of equal or higher level (or EOF).

    Parameters
    ----------
    all_lines:
        The source file split into lines.
    start_line:
        1-based line the chunk starts at.
    heading_level:
        Heading depth of the chunk (``0`` for content outside any heading).

    Returns
    -------
    tuple
        ``(content, first_line, last_line)`` with 1-based line numbers.
    """
    # Find section start — walk backward to the heading, starting at the
    # chunk's own first line (clamped in case the file shrank since indexing)
    section_start = start_line - 1  # 0-indexed
    if heading_level > 0:
        for i in range(min(start_line, len(all_lines)) - 1, -1, -1):
            m = _HEADING_RE.match(all_lines[i])
            if m and len(m.group(1)) <= heading_level:
                section_start = i
                break

    # Find section end — walk forward to the next heading of same or higher level
    section_end = len(all_lines)
    if heading_level > 0:
        for i in range(start_line, len(all_lines)):
            m = _HEADING_RE.match(all_lines[i])
            if m and len(m.group(1)) <= heading_level:
                section_end = i
                break

    content = "\n".join(all_lines[section_start:section_end])
    return content, section_start + 1, section_end
