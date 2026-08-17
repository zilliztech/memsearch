"""Parse pi JSONL sessions for progressive memory disclosure (L3).

pi sessions differ from the Claude Code format in two ways that matter here:

* Entries are uniformly ``{"type": "message", "message": {"role": ...}}``
  rather than top-level ``user`` / ``assistant`` types.
* Entries form a tree via ``id`` / ``parentId``, so a file can hold several
  branches. Reading it in line order would interleave abandoned branches with
  the live one, so the branch is always resolved by walking parents.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_CONTENT_CHARS = 2000


@dataclass
class Turn:
    """A single user or assistant message on the resolved branch."""

    id: str
    timestamp: str
    role: str  # "user" or "assistant"
    content: str
    tool_calls: list[str] = field(default_factory=list)


def load_entries(path: str | Path) -> list[dict[str, Any]]:
    """Read a session file, dropping the header and unparseable lines."""
    path = Path(path)
    if not path.exists():
        return []

    entries: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "session":  # header, not part of the tree
                continue
            entries.append(obj)
    return entries


def resolve_branch(
    entries: list[dict[str, Any]], target_id: str | None = None
) -> list[dict[str, Any]]:
    """Return one root-to-leaf path, in chronological order.

    Walks ``parentId`` upward from the target entry (or from the last entry in
    the file, which is the live leaf) so that abandoned branches are excluded.
    """
    if not entries:
        return []

    by_id = {entry["id"]: entry for entry in entries if "id" in entry}

    leaf_id = None
    if target_id:
        leaf_id = _match_id(by_id, target_id)
    if leaf_id is None:
        leaf_id = entries[-1].get("id")

    branch: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = leaf_id
    while current and current in by_id and current not in seen:
        seen.add(current)
        entry = by_id[current]
        branch.append(entry)
        current = entry.get("parentId")

    branch.reverse()
    return branch


def _match_id(by_id: dict[str, Any], wanted: str) -> str | None:
    """Resolve an entry id, allowing a unique prefix."""
    if wanted in by_id:
        return wanted
    matches = [key for key in by_id if key.startswith(wanted)]
    return matches[0] if len(matches) == 1 else None


def _extract(content: Any) -> tuple[str, list[str]]:
    """Split message content into rendered text and tool-call summaries."""
    if isinstance(content, str):
        return content.strip(), []
    if not isinstance(content, list):
        return "", []

    texts: list[str] = []
    calls: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            texts.append(block.get("text", ""))
        elif kind == "toolCall":
            calls.append(_summarize_tool_call(block))
        # "thinking" and "image" blocks are deliberately dropped

    return "\n".join(texts).strip(), calls


def _summarize_tool_call(block: dict[str, Any]) -> str:
    name = block.get("name", "tool")
    raw = block.get("arguments", "")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    if isinstance(raw, dict):
        parts = [f"{k}={str(v)[:60]}" for k, v in list(raw.items())[:3]]
        return f"{name}({', '.join(parts)})"
    return f"{name}({str(raw)[:60]})"


def parse_transcript(path: str | Path, target_id: str | None = None) -> list[Turn]:
    """Parse a session file into user/assistant turns on one branch."""
    branch = resolve_branch(load_entries(path), target_id)

    turns: list[Turn] = []
    for entry in branch:
        if entry.get("type") != "message":
            continue
        message = entry.get("message") or {}
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue  # toolResult messages are folded into their tool calls

        text, calls = _extract(message.get("content"))
        if not text and not calls:
            continue

        turns.append(
            Turn(
                id=entry.get("id", ""),
                timestamp=_extract_time(entry.get("timestamp", "")),
                role=role,
                content=text[:MAX_CONTENT_CHARS],
                tool_calls=calls,
            )
        )
    return turns


def find_turn_context(
    turns: list[Turn], turn_id: str, context: int = 3
) -> tuple[list[Turn], int]:
    """Return the turns surrounding a target, plus the target's new index."""
    target = -1
    for index, turn in enumerate(turns):
        if turn.id == turn_id or turn.id.startswith(turn_id):
            target = index
            break
    if target == -1:
        return turns[-(context * 2 + 1) :], -1

    start = max(0, target - context)
    end = min(len(turns), target + context + 1)
    return turns[start:end], target - start


def format_turns(turns: list[Turn], highlight_idx: int = -1) -> str:
    lines: list[str] = []
    for index, turn in enumerate(turns):
        marker = " <<< TARGET" if index == highlight_idx else ""
        label = "[User]" if turn.role == "user" else "[Assistant]"
        stamp = f" {turn.timestamp}" if turn.timestamp else ""
        lines.append(f"{label}{stamp}{marker}")
        if turn.content:
            lines.append(turn.content)
        for call in turn.tool_calls:
            lines.append(f"  -> {call}")
        lines.append("")
    return "\n".join(lines).strip()


def turns_to_dicts(turns: list[Turn]) -> list[dict[str, Any]]:
    return [
        {
            "id": turn.id,
            "timestamp": turn.timestamp,
            "role": turn.role,
            "content": turn.content,
            "tool_calls": turn.tool_calls,
        }
        for turn in turns
    ]


def _extract_time(timestamp: str) -> str:
    """Render an ISO timestamp as HH:MM."""
    if "T" not in timestamp:
        return ""
    return timestamp.split("T", 1)[1][:5]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Parse a pi JSONL session for memory drill-down."
    )
    parser.add_argument("jsonl_path", help="Path to the session JSONL file.")
    parser.add_argument("--turn", "-t", default=None, help="Target entry id (prefix ok).")
    parser.add_argument(
        "--context", "-c", default=3, type=int, help="Turns before/after the target."
    )
    parser.add_argument(
        "--limit", "-l", default=20, type=int, help="Max turns when no target is given."
    )
    parser.add_argument("--json-output", "-j", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    all_turns = parse_transcript(args.jsonl_path, args.turn)
    if not all_turns:
        raise SystemExit("No turns found — the session file may be missing or empty.")

    if args.turn:
        selected, highlight = find_turn_context(all_turns, args.turn, args.context)
    else:
        selected, highlight = all_turns[-args.limit :], -1

    if args.json_output:
        print(json.dumps(turns_to_dicts(selected), ensure_ascii=False, indent=2))
    else:
        print(format_turns(selected, highlight))
