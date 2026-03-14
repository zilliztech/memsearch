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
  echo '{}'
  exit 0
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

# Summarize the last turn using a local Ollama model via direct HTTP call.
# This avoids spawning a `claude -p` subprocess, which would inherit Claude Code's
# hook configuration and trigger registered hooks (e.g. notification relays) on the
# transcript content — causing duplicate deliveries to external systems.
#
# Requires Ollama running at MEMSEARCH_OLLAMA_URL (default: http://localhost:11434).
# Model is read from memsearch config (embedding.model used as fallback) or overridden
# via MEMSEARCH_OLLAMA_SUMMARIZE_MODEL. Falls back to any available Ollama model.
OLLAMA_URL="${MEMSEARCH_OLLAMA_URL:-http://localhost:11434}"
OLLAMA_MODEL="${MEMSEARCH_OLLAMA_SUMMARIZE_MODEL:-}"

# Auto-detect model from config if not set
if [ -z "$OLLAMA_MODEL" ] && command -v "$MEMSEARCH_CMD" &>/dev/null; then
  _cfg_model=$($MEMSEARCH_CMD config get embedding.model 2>/dev/null || true)
  # Only use if it looks like a chat model (not an embed-only model)
  case "$_cfg_model" in
    *embed*|*nomic-embed*) OLLAMA_MODEL="" ;;
    *) OLLAMA_MODEL="$_cfg_model" ;;
  esac
fi

# Final fallback: pick first available Ollama model that isn't embed-only
if [ -z "$OLLAMA_MODEL" ]; then
  OLLAMA_MODEL=$(curl -s "${OLLAMA_URL}/api/tags" 2>/dev/null \
    | python3 -c "
import sys, json
try:
    models = json.load(sys.stdin).get('models', [])
    for m in models:
        name = m.get('name', '')
        if 'embed' not in name:
            print(name)
            break
except: pass
" 2>/dev/null || true)
fi

SYSTEM_PROMPT="You are a third-person note-taker. You will receive a transcript of ONE conversation turn between a human (labeled [Human]) and Claude Code (labeled [Claude Code]). Tool calls are labeled [Claude Code calls tool] and their results [Tool output] or [Tool error].

Your job is to record what happened as factual third-person notes. You are an EXTERNAL OBSERVER — you are NOT Claude Code, NOT an assistant. Do NOT answer the human's question, do NOT give suggestions, do NOT offer help. ONLY record what occurred.

Output 2-6 bullet points, each starting with '- '. NOTHING else.

Rules:
- Write in third person: 'User asked...', 'Claude read file X', 'Claude ran command Y'
- First bullet: what the user asked or wanted (one sentence)
- Remaining bullets: what Claude did — tools called, files read/edited, commands run, key findings
- Be specific: mention file names, function names, tool names, and concrete outcomes
- Do NOT answer the human's question yourself — just note what was discussed
- Do NOT add any text before or after the bullet points
- Write in the same language as the human's message (the [Human] line) in the transcript"

SUMMARY=""
if [ -n "$OLLAMA_MODEL" ]; then
  SUMMARY=$(python3 -c "
import sys, json, urllib.request, urllib.error

url = sys.argv[1]
model = sys.argv[2]
system_prompt = sys.argv[3]
transcript = sys.stdin.read()

payload = json.dumps({
    'model': model,
    'messages': [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': transcript}
    ],
    'stream': False
}).encode()

try:
    req = urllib.request.Request(
        url + '/api/chat',
        data=payload,
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
        print(result['message']['content'].strip())
except Exception as e:
    sys.exit(1)
" "$OLLAMA_URL" "$OLLAMA_MODEL" "$SYSTEM_PROMPT" <<< "$PARSED" 2>/dev/null || true)
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
