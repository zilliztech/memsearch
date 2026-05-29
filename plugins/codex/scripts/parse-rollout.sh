#!/usr/bin/env bash
# Parse a Codex CLI rollout JSONL — extract and format the LAST TURN only.
#
# A "turn" starts at the last task_started event and scans all subsequent
# messages until EOF. Tool records are recognized but skipped during formatting.
#
# Key rollout JSONL line types:
#   event_msg + user_message   → user's text input
#   event_msg + agent_message  → agent's text output
#   response_item + function_call        → tool invocation (skipped)
#   response_item + function_call_output → tool result (skipped)
#   response_item + message (role=user)  → user content blocks
#   response_item + message (role=assistant) → assistant content blocks
#   event_msg + task_started   → turn boundary
#   event_msg + task_complete  → turn end
#
# Tool calls and tool results are skipped so the summarizer works from a clean
# User/Assistant transcript instead of structured execution metadata.
#
# Usage: bash parse-rollout.sh <rollout_path>

set -euo pipefail

ROLLOUT_PATH="${1:-}"

if [ -z "$ROLLOUT_PATH" ] || [ ! -f "$ROLLOUT_PATH" ]; then
  echo "ERROR: rollout not found: $ROLLOUT_PATH" >&2
  exit 1
fi

# Check if rollout has any content
LINE_COUNT=$(wc -l < "$ROLLOUT_PATH" 2>/dev/null || echo "0")
if [ "$LINE_COUNT" -eq 0 ]; then
  echo "(empty rollout)"
  exit 0
fi

python3 -c '
import json, sys

def find_last_turn_start(lines):
    """Find the index of the last task_started event."""
    for i in range(len(lines) - 1, -1, -1):
        try:
            obj = json.loads(lines[i])
            if obj.get("type") == "event_msg":
                payload = obj.get("payload", {})
                if payload.get("type") == "task_started":
                    return i
        except Exception:
            pass
    return None

def find_last_user_message(lines):
    """Fallback: find the last user_message event."""
    for i in range(len(lines) - 1, -1, -1):
        try:
            obj = json.loads(lines[i])
            if obj.get("type") == "event_msg":
                payload = obj.get("payload", {})
                if payload.get("type") == "user_message":
                    return i
        except Exception:
            pass
    return None

def format_turn(lines):
    """Format a turn into structured text for LLM summarization."""
    output = ["=== Transcript of a conversation between User and Codex CLI ==="]

    for raw_line in lines:
        try:
            obj = json.loads(raw_line)
        except Exception:
            continue

        line_type = obj.get("type", "")
        payload = obj.get("payload", {})

        if line_type == "event_msg":
            msg_type = payload.get("type", "")

            if msg_type == "user_message":
                message = payload.get("message", "")
                if message.strip():
                    output.append(f"[User]: {message.strip()}")

            elif msg_type == "agent_message":
                message = payload.get("message", "")
                if message.strip():
                    output.append(f"[Codex]: {message.strip()}")

            # Skip: task_started, task_complete, token_count, agent_reasoning

        elif line_type == "response_item":
            item_type = payload.get("type", "")

            # Skip tool calls/results and response_item "message" duplicates.
            # Skip: reasoning, session_meta, turn_context, web_search_call

    return "\n".join(output)

# --- Main ---
rollout_path = sys.argv[1]
with open(rollout_path) as f:
    lines = f.readlines()

if not lines:
    print("(empty rollout)")
    sys.exit(0)

# Find the start of the last turn
start_idx = find_last_turn_start(lines)

# Fallback: find last user_message if no task_started found
if start_idx is None:
    start_idx = find_last_user_message(lines)

if start_idx is None:
    print("(no user message found)")
    sys.exit(0)

last_turn = lines[start_idx:]
formatted = format_turn(last_turn)

if not formatted.strip():
    print("(empty turn)")
    sys.exit(0)

print(formatted)
' "$ROLLOUT_PATH"
