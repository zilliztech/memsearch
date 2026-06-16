"""Cross-format transcript parsing for L3 drill-down.

The daily journals are lossy summaries — they drop the exact commands an agent
ran. To write an accurate skill you need the originals, which live in each
agent's raw session transcript. The formats differ per agent, so this module
parses them into a common shape that **includes tool calls (the exact commands)
and their output**, and exposes it as the ``memsearch transcript`` CLI command.

Both paths use that one command: the ``/memory-to-skill`` skill calls it
on-demand, and the background distillation tool calls it too — so the
format-specific parsing lives in one place instead of being re-derived by each
agent from raw JSONL.

Auto-detected formats: Claude Code JSONL, Codex rollout JSONL, OpenClaw JSONL.
Unknown formats raise :class:`UnknownTranscriptFormat` so the caller can fall
back to reading the file directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Truncation strategy: commands are the point, so they are kept in full; tool
# output is secondary (kept short), and the whole rendering is capped. One budget,
# applied the same way on every path.
MAX_OUTPUT_CHARS = 200  # per tool-call output (keep just the key first lines)
MAX_RENDER_CHARS = 12_000  # total rendered transcript, head-truncated past this


class UnknownTranscriptFormat(Exception):
    """Raised when the transcript format cannot be recognized."""


@dataclass
class ToolCall:
    name: str
    command: str  # the full, untruncated invocation (e.g. the shell command)
    output: str = ""  # tool result, truncated to MAX_OUTPUT_CHARS


@dataclass
class Turn:
    role: str  # "user" | "assistant"
    uuid: str = ""
    text: str = ""
    tools: list[ToolCall] = field(default_factory=list)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def detect_format(entries: list[dict[str, Any]]) -> str:
    for obj in entries[:80]:
        t = obj.get("type")
        if t in ("event_msg", "response_item"):
            return "codex"
        if t == "message" and isinstance(obj.get("message"), dict) and "role" in obj["message"]:
            return "openclaw"
        if t in ("user", "assistant") and "message" in obj:
            return "claude"
    raise UnknownTranscriptFormat("could not recognize transcript format")


def _clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


def _as_text(content: Any) -> str:
    """Render a content value (string or list of blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(p for p in parts if p)
    return ""


# -- per-format parsers ----------------------------------------------------------


def _parse_claude(entries: list[dict[str, Any]]) -> list[Turn]:
    turns: list[Turn] = []
    pending: dict[str, ToolCall] = {}  # tool_use_id -> ToolCall (awaiting result)
    for entry in entries:
        etype = entry.get("type")
        msg = entry.get("message", {}) if isinstance(entry.get("message"), dict) else {}
        content = msg.get("content", "")
        if etype == "user":
            # A user entry is either a real prompt or tool_result(s) for the prior turn.
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        tc = pending.pop(b.get("tool_use_id", ""), None)
                        if tc is not None:
                            tc.output = _clip(_as_text(b.get("content", "")))
                continue
            text = _as_text(content).strip()
            if text:
                turns.append(Turn(role="user", uuid=entry.get("uuid", ""), text=text))
        elif etype == "assistant":
            blocks = content if isinstance(content, list) else []
            turn = Turn(role="assistant", uuid=entry.get("uuid", ""))
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    turn.text += (("\n" if turn.text else "") + b.get("text", "")).rstrip()
                elif b.get("type") == "tool_use":
                    tc = ToolCall(name=b.get("name", "tool"), command=_render_tool_input(b.get("input", {})))
                    turn.tools.append(tc)
                    if b.get("id"):
                        pending[b["id"]] = tc
            if turn.text or turn.tools:
                turns.append(turn)
    return turns


def _render_tool_input(tool_input: Any) -> str:
    """Full (untruncated) rendering of a tool input — prefer the shell command."""
    if isinstance(tool_input, dict):
        for key in ("command", "cmd", "query", "pattern", "file_path", "path"):
            val = tool_input.get(key)
            if val:
                return " ".join(val) if isinstance(val, list) else str(val)
        return json.dumps(tool_input, ensure_ascii=False)
    if isinstance(tool_input, list):
        return " ".join(str(x) for x in tool_input)
    return str(tool_input)


def _parse_codex(entries: list[dict[str, Any]]) -> list[Turn]:
    turns: list[Turn] = []
    pending: dict[str, ToolCall] = {}  # call_id -> ToolCall
    cur: Turn | None = None
    for obj in entries:
        ltype = obj.get("type")
        payload = obj.get("payload", {}) if isinstance(obj.get("payload"), dict) else {}
        if ltype == "event_msg":
            mtype = payload.get("type")
            if mtype == "user_message":
                text = str(payload.get("message", "")).strip()
                if text:
                    turns.append(Turn(role="user", text=text))
                    cur = None
            elif mtype == "agent_message":
                text = str(payload.get("message", "")).strip()
                if text:
                    if cur is None:
                        cur = Turn(role="assistant")
                        turns.append(cur)
                    cur.text += (("\n" if cur.text else "") + text).rstrip()
        elif ltype == "response_item":
            itype = payload.get("type")
            if itype == "function_call":
                args = payload.get("arguments", "")
                try:
                    parsed = json.loads(args) if isinstance(args, str) else args
                except json.JSONDecodeError:
                    parsed = args
                tc = ToolCall(name=payload.get("name", "tool"), command=_render_tool_input(parsed))
                if cur is None:
                    cur = Turn(role="assistant")
                    turns.append(cur)
                cur.tools.append(tc)
                if payload.get("call_id"):
                    pending[payload["call_id"]] = tc
            elif itype == "function_call_output":
                tc = pending.pop(payload.get("call_id", ""), None)
                if tc is not None:
                    out = payload.get("output", "")
                    tc.output = _clip(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False))
    return turns


def _parse_openclaw(entries: list[dict[str, Any]]) -> list[Turn]:
    turns: list[Turn] = []
    for obj in entries:
        if obj.get("type") != "message":
            continue
        msg = obj.get("message", {})
        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content", "")
        turn = Turn(role=role, uuid=obj.get("id", ""), text=_as_text(content).strip())
        if isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "toolCall":
                    name = b.get("name", b.get("toolName", "tool"))
                    turn.tools.append(
                        ToolCall(name=name, command=_render_tool_input(b.get("input", b.get("parameters", {}))))
                    )
                elif b.get("type") == "toolResult" and turn.tools:
                    res = b.get("text", b.get("content", ""))
                    turn.tools[-1].output = _clip(_as_text(res) if not isinstance(res, str) else res)
        if turn.text or turn.tools:
            turns.append(turn)
    return turns


_PARSERS = {"claude": _parse_claude, "codex": _parse_codex, "openclaw": _parse_openclaw}


def parse_transcript(path: str | Path) -> list[Turn]:
    """Parse a transcript file into turns with tool calls. Raises
    :class:`UnknownTranscriptFormat` if the format is not recognized."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"transcript not found: {p}")
    entries = _load_jsonl(p)
    if not entries:
        return []
    return _PARSERS[detect_format(entries)](entries)


def select_turns(turns: list[Turn], turn_id: str | None, context: int) -> list[Turn]:
    if not turn_id:
        return turns
    for i, t in enumerate(turns):
        if t.uuid and (t.uuid.startswith(turn_id) or turn_id.startswith(t.uuid[:8])):
            return turns[max(0, i - context) : i + context + 1]
    return turns  # turn not found (e.g. format has no per-turn ids) → return all


def format_turns(turns: list[Turn]) -> str:
    lines: list[str] = []
    for t in turns:
        who = "User" if t.role == "user" else "Assistant"
        lines.append(f"### {who}")
        if t.text:
            lines.append(t.text)
        for tc in t.tools:
            lines.append(f"- $ [{tc.name}] {tc.command}")
            if tc.output:
                lines.append(f"  → {tc.output}")
        lines.append("")
    rendered = "\n".join(lines).strip() + "\n"
    if len(rendered) > MAX_RENDER_CHARS:
        rendered = rendered[:MAX_RENDER_CHARS] + "\n…[transcript truncated]\n"
    return rendered
