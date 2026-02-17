#!/usr/bin/env bash
# Stop hook: parse transcript, summarize with claude -p, and save to memory.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Prevent infinite loop: if this Stop was triggered by a previous Stop hook, bail out
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  echo '{}'
  exit 0
fi

# Skip summarization when OPENAI_API_KEY is missing — the session would only
# contain the "please set your API key" exchange, which is not useful memory.
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo '{}'
  exit 0
fi

# Extract transcript path from hook input
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)

if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
  echo '{}'
  exit 0
fi

# Check if transcript is empty (< 3 lines = no real content)
LINE_COUNT=$(wc -l < "$TRANSCRIPT_PATH" 2>/dev/null || echo "0")
if [ "$LINE_COUNT" -lt 3 ]; then
  echo '{}'
  exit 0
fi

ensure_memory_dir

# Parse transcript into concise text
PARSED=$("$SCRIPT_DIR/parse-transcript.sh" "$TRANSCRIPT_PATH" 2>/dev/null || true)

if [ -z "$PARSED" ] || [ "$PARSED" = "(empty transcript)" ]; then
  echo '{}'
  exit 0
fi

# Determine today's date and current time
TODAY=$(date +%Y-%m-%d)
NOW=$(date +%H:%M)
MEMORY_FILE="$MEMORY_DIR/$TODAY.md"

# Extract session ID and last user turn UUID for progressive disclosure anchors
SESSION_ID=$(basename "$TRANSCRIPT_PATH" .jsonl)
LAST_USER_TURN_UUID=$(python3 -c "
import json, sys
uuid = ''
with open(sys.argv[1]) as f:
    for line in f:
        try:
            obj = json.loads(line)
            if obj.get('type') == 'user' and isinstance(obj.get('message', {}).get('content'), str):
                uuid = obj.get('uuid', '')
        except: pass
print(uuid)
" "$TRANSCRIPT_PATH" 2>/dev/null || true)

# Use claude -p to summarize the parsed transcript into concise bullet points.
# --model haiku: cheap and fast model for summarization
# --no-session-persistence: don't save this throwaway session to disk
# --no-chrome: skip browser integration
# --system-prompt: separate role instructions from data (transcript via stdin)
SUMMARY=""
if command -v claude &>/dev/null; then
  SUMMARY=$(printf '%s' "$PARSED" | claude -p \
    --model haiku \
    --no-session-persistence \
    --no-chrome \
    --system-prompt "You are a session memory writer. Your ONLY job is to output bullet-point summaries. Output NOTHING else — no greetings, no questions, no offers to help, no preamble, no closing remarks.

Rules:
- Output 3-8 bullet points, each starting with '- '
- Focus on: decisions made, problems solved, code changes, key findings
- Be specific and factual — mention file names, function names, and concrete details
- Do NOT include timestamps, headers, or any formatting beyond bullet points
- Do NOT add any text before or after the bullet points" \
    2>/dev/null || true)
fi

# If claude is not available or returned empty, fall back to raw parsed output
if [ -z "$SUMMARY" ]; then
  SUMMARY="$PARSED"
fi

# Append as a sub-heading under the session heading written by SessionStart
# Include HTML comment anchor for progressive disclosure (L3 transcript lookup)
{
  echo "### $NOW"
  if [ -n "$SESSION_ID" ]; then
    echo "<!-- session:${SESSION_ID} turn:${LAST_USER_TURN_UUID} transcript:${TRANSCRIPT_PATH} -->"
  fi
  echo "$SUMMARY"
  echo ""
} >> "$MEMORY_FILE"

# Index immediately — don't rely on watch (which may be killed by SessionEnd before debounce fires)
run_memsearch index "$MEMORY_DIR"

echo '{}'
