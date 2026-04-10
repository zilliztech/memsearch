"""Parse Claude Code JSONL transcripts for progressive memory disclosure."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _entry_content(entry: dict[str, Any]) -> Any:
    """Return transcript content from either nested or flat event formats."""
    msg = entry.get("message")
    if isinstance(msg, dict) and "content" in msg:
        return msg.get("content")
    return entry.get("content", "")


@dataclass
class Turn:
    """A single conversation turn extracted from a JSONL transcript."""

    uuid: str
    timestamp: str
    role: str  # "user" or "assistant"
    content: str  # rendered text content
    tool_calls: list[str] = field(default_factory=list)  # ["Bash(command=ls)", ...]


def parse_transcript(path: str | Path) -> list[Turn]:
    """Parse a JSONL transcript into a list of conversation turns.

    Turns are user messages (non-tool-result) and their corresponding
    assistant responses, grouped logically.  Progress, system, and
    file-history-snapshot entries are skipped.
    """
    path = Path(path)
    if not path.exists():
        return []

    entries: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                entries.append(obj)
            except json.JSONDecodeError:
                continue

    turns: list[Turn] = []
    current_turn: Turn | None = None

    for entry in entries:
        entry_type = entry.get("type", "")

        if entry_type == "user":
            content = _entry_content(entry)

            # Skip tool results — they are part of the previous assistant turn
            if (
                isinstance(content, list)
                and content
                and isinstance(content[0], dict)
                and content[0].get("type") == "tool_result"
            ):
                continue

            # Real user message
            if isinstance(content, str) and content.strip():
                # Strip XML tags injected by hooks
                clean = _strip_hook_tags(content)
                if not clean:
                    continue
                # Save previous turn and start new one
                if current_turn is not None:
                    turns.append(current_turn)
                current_turn = Turn(
                    uuid=entry.get("uuid", ""),
                    timestamp=entry.get("timestamp", ""),
                    role="user",
                    content=clean,
                )

        elif entry_type == "assistant" and current_turn is not None:
            content_blocks = _entry_content(entry)
            if not isinstance(content_blocks, list):
                continue

            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")

                if block_type == "text":
                    text = block.get("text", "").strip()
                    if text:
                        if current_turn.role == "user":
                            # First assistant block — create assistant section
                            current_turn.content += f"\n\n**Assistant**: {text}"
                        else:
                            current_turn.content += f"\n{text}"

                elif block_type == "tool_use":
                    name = block.get("name", "unknown")
                    tool_input = block.get("input", {})
                    summary = _summarize_tool_input(name, tool_input)
                    current_turn.tool_calls.append(summary)

                # Skip "thinking" blocks

    # Don't forget the last turn
    if current_turn is not None:
        turns.append(current_turn)

    return turns


def find_turn_context(
    turns: list[Turn],
    target_uuid: str,
    context: int = 3,
) -> tuple[list[Turn], int]:
    """Find a turn by UUID and return surrounding context turns."""
    idx = -1
    for i, turn in enumerate(turns):
        if turn.uuid == target_uuid or turn.uuid.startswith(target_uuid):
            idx = i
            break

    if idx == -1:
        return [], -1

    start = max(0, idx - context)
    end = min(len(turns), idx + context + 1)
    return turns[start:end], idx - start


def _strip_hook_tags(text: str) -> str:
    """Strip hook wrapper tags and their contents from transcript content."""
    import re

    text = re.sub(r"<command-[^>]+>.*?</command-[^>]+>", "", text, flags=re.DOTALL)
    return re.sub(r"<[^>]+>", "", text).strip()


def _extract_time(timestamp: str) -> str:
    """Extract HH:MM:SS from ISO timestamp."""
    if not timestamp:
        return ""
    try:
        return timestamp.split("T", 1)[1].split(".", 1)[0].rstrip("Z")
    except Exception:
        return timestamp


def _summarize_tool_input(name: str, tool_input: dict[str, Any]) -> str:
    """Summarize tool input for compact display."""
    if name == "Read" and "file_path" in tool_input:
        return f"Read({tool_input['file_path']})"
    if name == "Bash" and "command" in tool_input:
        return f"Bash({tool_input['command']})"
    if not tool_input:
        return name
    parts = ", ".join(f"{k}={v}" for k, v in tool_input.items())
    return f"{name}({parts})"


def format_turn_index(turns: list[Turn]) -> str:
    """Format a compact index of transcript turns."""
    lines = []
    for turn in turns:
        preview = turn.content.replace("\n", " ")[:80]
        tool_part = f" [{len(turn.tool_calls)} tools]" if turn.tool_calls else ""
        lines.append(f"{turn.uuid[:12]} {_extract_time(turn.timestamp)} {preview}{tool_part}")
    return "\n".join(lines)
