#!/usr/bin/env bash
# Stop hook: parse transcript, summarize with claude -p, and save to memory.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Prevent infinite loop: if this Stop was triggered by a previous Stop hook, bail out
STOP_HOOK_ACTIVE=$(_json_val "$INPUT" "stop_hook_active" "false")
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  echo '{}'
  exit 0
fi

# Skip summarization when the required API key is missing — embedding/search
# would fail, and the session likely only contains the "key not set" warning.
_required_env_var() {
  case "$1" in
    openai) echo "OPENAI_API_KEY" ;;
    google) echo "GOOGLE_API_KEY" ;;
    voyage) echo "VOYAGE_API_KEY" ;;
    *) echo "" ;;  # onnx, ollama, local — no API key needed
  esac
}
_PROVIDER=$($MEMSEARCH_CMD config get embedding.provider 2>/dev/null || echo "onnx")
_REQ_KEY=$(_required_env_var "$_PROVIDER")
if [ -n "$_REQ_KEY" ] && [ -z "${!_REQ_KEY:-}" ]; then
  # Env var not set — check if API key is configured in memsearch config file
  _CONFIG_API_KEY=""
  if [ -n "$MEMSEARCH_CMD" ]; then
    _CONFIG_API_KEY=$($MEMSEARCH_CMD config get embedding.api_key 2>/dev/null || echo "")
  fi
  if [ -z "$_CONFIG_API_KEY" ]; then
    echo '{}'
    exit 0
  fi
fi

# Extract transcript path from hook input
TRANSCRIPT_PATH=$(_json_val "$INPUT" "transcript_path" "")

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

# Parse transcript — extract the last turn only (one user question + all responses)
PARSED=$("$SCRIPT_DIR/parse-transcript.sh" "$TRANSCRIPT_PATH" 2>/dev/null || true)

if [ -z "$PARSED" ] || [ "$PARSED" = "(empty transcript)" ] || [ "$PARSED" = "(no user message found)" ] || [ "$PARSED" = "(empty turn)" ]; then
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

# Use claude -p to summarize the last turn into structured bullet points.
# --model haiku: cheap and fast model for summarization
# --no-session-persistence: don't save this throwaway session to disk
# --no-chrome: skip browser integration
# --system-prompt: separate role instructions from data (transcript via stdin)
SUMMARY=""
if command -v claude &>/dev/null; then
  SUMMARY=$(printf '%s' "$PARSED" | MEMSEARCH_NO_WATCH=1 CLAUDECODE= claude -p \
    --model haiku \
    --no-session-persistence \
    --no-chrome \
    --system-prompt "You are a third-person note-taker. You will receive a transcript of ONE conversation turn between a human (labeled [Human]) and Claude Code (labeled [Claude Code]). Tool calls are labeled [Tool Call] and their results [Tool RESULT] or [Tool ERROR].

Your job is to record what happened as factual third-person notes. You are an EXTERNAL OBSERVER — you are NOT Claude Code, NOT an assistant. Do NOT answer the human's question, do NOT give suggestions, do NOT offer help. ONLY record what occurred.

Output 2-6 bullet points, each starting with '- '. NOTHING else.

Rules:
- Write in third person: 'User asked...', 'Claude read file X', 'Claude ran command Y'
- First bullet: what the user asked or wanted (one sentence)
- Remaining bullets: what Claude did — tools called, files read/edited, commands run, key findings
- Be specific: mention file names, function names, tool names, and concrete outcomes
- Do NOT answer the human's question yourself — just note what was discussed
- Do NOT add any text before or after the bullet points
- Write in the same language as the human's message (the [Human] line) in the transcript

The transcript uses these labels:
- [Human]: what the user said
- [Claude Code]: what Claude Code said
- [Claude Code calls tool]: a tool Claude Code invoked
- [Tool output]: the result returned by a tool
- [Tool error]: an error returned by a tool" \
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
