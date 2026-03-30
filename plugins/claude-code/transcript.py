"""Parse Claude Code JSONL transcripts for progressive memory disclosure."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
            msg = entry.get("message", {})
            content = msg.get("content", "")

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
            msg = entry.get("message", {})
            content_blocks = msg.get("content", [])
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
    """Find a turn by UUID and return surrounding context turns.

    Returns (context_turns, target_index_in_result).
    """
    target_idx = -1
    for i, turn in enumerate(turns):
        if turn.uuid.startswith(target_uuid) or target_uuid.startswith(turn.uuid[:8]):
            target_idx = i
            break

    if target_idx == -1:
        return [], -1

    start = max(0, target_idx - context)
    end = min(len(turns), target_idx + context + 1)
    return turns[start:end], target_idx - start


def format_turns(turns: list[Turn], highlight_idx: int = -1) -> str:
    """Format turns into readable text output."""
    lines: list[str] = []
    for i, turn in enumerate(turns):
        marker = ">>> " if i == highlight_idx else ""
        ts = _extract_time(turn.timestamp)
        lines.append(f"{marker}[{ts}] {turn.uuid[:8]}")
        lines.append(turn.content)
        if turn.tool_calls:
            lines.append(f"  Tools: {', '.join(turn.tool_calls)}")
        lines.append("")
    return "\n".join(lines)


def format_turn_index(turns: list[Turn]) -> str:
    """Format a compact index of all turns (for --no-turn overview)."""
    lines: list[str] = []
    for turn in turns:
        ts = _extract_time(turn.timestamp)
        preview = turn.content[:80].replace("\n", " ")
        n_tools = len(turn.tool_calls)
        tool_info = f" [{n_tools} tools]" if n_tools else ""
        lines.append(f"  {turn.uuid[:12]}  {ts}  {preview}{tool_info}")
    return "\n".join(lines)


def turns_to_dicts(turns: list[Turn]) -> list[dict[str, Any]]:
    """Convert turns to JSON-serializable dicts."""
    return [
        {
            "uuid": t.uuid,
            "timestamp": t.timestamp,
            "content": t.content,
            "tool_calls": t.tool_calls,
        }
        for t in turns
    ]


# -- Helpers --


def _strip_hook_tags(text: str) -> str:
    """Remove hook-injected XML tags from user messages."""
    import re

    # Remove <system-reminder>...</system-reminder>, <local-command-*>...</local-command-*>, etc.
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL)
    text = re.sub(r"<local-command-\w+>.*?</local-command-\w+>", "", text, flags=re.DOTALL)
    text = re.sub(r"<command-\w+>.*?</command-\w+>", "", text, flags=re.DOTALL)
    return text.strip()


def _extract_time(ts: str) -> str:
    """Extract HH:MM:SS from ISO timestamp."""
    if "T" in ts:
        time_part = ts.split("T")[1]
        return time_part[:8]  # HH:MM:SS
    return ts[:8] if len(ts) >= 8 else ts


def _summarize_tool_input(name: str, tool_input: dict) -> str:
    """Create a short summary of a tool call."""
    if name == "Bash":
        cmd = str(tool_input.get("command", ""))[:80]
        return f"Bash({cmd})"
    elif name == "Read":
        return f"Read({tool_input.get('file_path', '')})"
    elif name == "Edit":
        return f"Edit({tool_input.get('file_path', '')})"
    elif name == "Write":
        return f"Write({tool_input.get('file_path', '')})"
    elif name in ("Grep", "Glob"):
        pattern = tool_input.get("pattern", "")[:60]
        return f"{name}({pattern})"
    elif name == "Task":
        desc = tool_input.get("description", "")[:60]
        return f"Task({desc})"
    elif name == "WebSearch":
        query = tool_input.get("query", "")[:60]
        return f"WebSearch({query})"
    else:
        # Generic: show first key=value pair
        if tool_input:
            first_key = next(iter(tool_input))
            first_val = str(tool_input[first_key])[:60]
            return f"{name}({first_key}={first_val})"
        return name


# -- CLI entry point --


if __name__ == "__main__":
    import sys

    import argparse

    parser = argparse.ArgumentParser(
        description="View conversation turns from a Claude Code JSONL transcript."
    )
    parser.add_argument("jsonl_path", help="Path to the JSONL transcript file.")
    parser.add_argument("--turn", "-t", default=None, help="Target turn UUID (prefix match).")
    parser.add_argument("--context", "-c", default=3, type=int, help="Number of turns before/after target.")
    parser.add_argument("--json-output", "-j", action="store_true", help="Output as JSON.")
    args = parser.parse_args()

    turns = parse_transcript(args.jsonl_path)
    if not turns:
        print("No conversation turns found.")
        sys.exit(0)

    if args.turn:
        context_turns, highlight = find_turn_context(turns, args.turn, context=args.context)
        if not context_turns:
            print(f"Turn not found: {args.turn}", file=sys.stderr)
            sys.exit(1)
        if args.json_output:
            print(json.dumps(turns_to_dicts(context_turns), indent=2, ensure_ascii=False))
        else:
            print(f"Showing {len(context_turns)} turns around {args.turn[:12]}:\n")
            print(format_turns(context_turns, highlight_idx=highlight))
    else:
        if args.json_output:
            print(json.dumps(turns_to_dicts(turns), indent=2, ensure_ascii=False))
        else:
            print(f"All turns ({len(turns)}):\n")
            print(format_turn_index(turns))
