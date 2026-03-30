#!/usr/bin/env bash
# Parse OpenClaw JSONL transcript and extract the last conversation turn.
#
# OpenClaw transcript format (one JSON object per line):
#   {"type":"message","id":"...","message":{"role":"user","content":[{"type":"text","text":"..."}]}}
#   {"type":"message","id":"...","message":{"role":"assistant","content":[{"type":"text","text":"..."},{"type":"toolCall",...}]}}
#
# Usage: parse-transcript.sh <transcript.jsonl>
# Output: formatted last turn with [Human] / [Assistant] / [Tool Call] labels

set -euo pipefail

TRANSCRIPT_FILE="${1:-}"

if [ -z "$TRANSCRIPT_FILE" ] || [ ! -f "$TRANSCRIPT_FILE" ]; then
  echo "(no transcript file)"
  exit 0
fi

# Use Python3 for reliable JSON parsing
python3 - "$TRANSCRIPT_FILE" << 'PYEOF'
import json
import sys

MAX_RESULT_CHARS = 1000

def extract_text(content):
    """Extract text from content (string or array of content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "toolCall":
                    name = block.get("name", block.get("toolName", "unknown"))
                    inp = block.get("input", block.get("parameters", {}))
                    # Compact tool call representation
                    if isinstance(inp, dict):
                        preview = json.dumps(inp, ensure_ascii=False)[:200]
                    else:
                        preview = str(inp)[:200]
                    parts.append(f"[Tool Call: {name}({preview})]")
                elif block.get("type") == "toolResult":
                    result_text = block.get("text", block.get("content", ""))
                    if isinstance(result_text, list):
                        result_text = " ".join(
                            r.get("text", "") for r in result_text if isinstance(r, dict)
                        )
                    result_text = str(result_text)
                    if len(result_text) > MAX_RESULT_CHARS:
                        result_text = result_text[:MAX_RESULT_CHARS] + "..."
                    parts.append(f"[Tool Result]: {result_text}")
        return "\n".join(parts)
    return str(content)


def main():
    transcript_file = sys.argv[1]

    messages = []
    with open(transcript_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get("type", "")
            if msg_type != "message":
                continue

            msg = obj.get("message", {})
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role in ("user", "assistant"):
                messages.append({"role": role, "content": content, "id": obj.get("id", "")})

    if not messages:
        print("(empty transcript)")
        return

    # Find the last real user message (text content, not tool_result)
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg["role"] == "user":
            content = msg["content"]
            if isinstance(content, str):
                last_user_idx = i
                break
            if isinstance(content, list) and any(
                b.get("type") == "text" for b in content if isinstance(b, dict)
            ):
                last_user_idx = i
                break

    if last_user_idx == -1:
        print("(no user message found)")
        return

    # Format the last turn
    print("=== Transcript of a conversation between a human and an AI assistant ===")
    for msg in messages[last_user_idx:]:
        role = msg["role"]
        text = extract_text(msg["content"])
        if not text.strip():
            continue

        if role == "user":
            print(f"[Human]: {text}")
        elif role == "assistant":
            print(f"[Assistant]: {text}")


if __name__ == "__main__":
    main()
PYEOF
