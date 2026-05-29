#!/usr/bin/env bash
# Parse a Claude Code JSONL transcript — extract and format the LAST TURN only.
#
# A "turn" = the last real user message (content is a string, not a tool_result)
# plus all subsequent assistant text responses until EOF.
#
# Skips: progress, file-history-snapshot, system, thinking blocks.
# Tool calls and tool results are skipped so the summarizer works from a clean
# User/Assistant transcript instead of structured execution metadata.
#
# Usage: bash parse-transcript.sh <transcript_path>

set -euo pipefail

TRANSCRIPT_PATH="${1:-}"

if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
  echo "ERROR: transcript not found: $TRANSCRIPT_PATH" >&2
  exit 1
fi

# Check if transcript has any content
LINE_COUNT=$(wc -l < "$TRANSCRIPT_PATH" 2>/dev/null || echo "0")
if [ "$LINE_COUNT" -eq 0 ]; then
  echo "(empty transcript)"
  exit 0
fi

python3 -c '
import json, sys

def find_last_turn_start(lines):
    """Find the index of the last real user message (string or array-format content)."""
    for i in range(len(lines) - 1, -1, -1):
        try:
            obj = json.loads(lines[i])
            if obj.get("type") == "user" and not obj.get("isMeta"):
                content = obj.get("message", {}).get("content")
                if isinstance(content, str) and content.strip():
                    return i
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip():
                            return i
        except Exception:
            pass
    return None

def format_turn(lines):
    """Format a turn into structured text for LLM summarization."""
    output = ["=== Transcript of a conversation between User and Claude Code ==="]
    for raw_line in lines:
        try:
            obj = json.loads(raw_line)
        except Exception:
            continue

        msg_type = obj.get("type", "")

        # Skip non-content types
        if msg_type not in ("user", "assistant"):
            continue

        if msg_type == "user":
            content = obj.get("message", {}).get("content")
            if isinstance(content, str) and content.strip():
                output.append(f"[User]: {content.strip()}")
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text:
                            output.append(f"[User]: {text}")
                    # Skip tool_result blocks; they are structured execution metadata.

        elif msg_type == "assistant":
            content = obj.get("message", {}).get("content", [])
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")

                if block_type == "text":
                    text = block.get("text", "").strip()
                    if text:
                        output.append(f"[Claude Code]: {text}")

                # Skip tool_use and thinking blocks; these are structured execution metadata.

    return "\n".join(output)

# --- Main ---
transcript_path = sys.argv[1]
with open(transcript_path) as f:
    lines = f.readlines()

if not lines:
    print("(empty transcript)")
    sys.exit(0)

start_idx = find_last_turn_start(lines)
if start_idx is None:
    print("(no user message found)")
    sys.exit(0)

last_turn = lines[start_idx:]
formatted = format_turn(last_turn)

if not formatted.strip():
    print("(empty turn)")
    sys.exit(0)

print(formatted)
' "$TRANSCRIPT_PATH"
