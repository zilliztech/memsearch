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
    jina) echo "JINA_API_KEY" ;;
    mistral) echo "MISTRAL_API_KEY" ;;
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

SUMMARIZE_ENABLED=$($MEMSEARCH_CMD config get plugins.claude-code.summarize.enabled 2>/dev/null || echo "true")
if [ "$SUMMARIZE_ENABLED" = "false" ]; then
  echo '{}'
  exit 0
fi

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
with open(sys.argv[1], encoding='utf-8', errors='replace') as f:
    for line in f:
        try:
            obj = json.loads(line)
            if obj.get('type') != 'user' or obj.get('isMeta'):
                continue
            content = obj.get('message', {}).get('content')
            if isinstance(content, str) and content.strip():
                uuid = obj.get('uuid', '')
                continue
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text' and block.get('text', '').strip():
                        uuid = obj.get('uuid', '')
                        break
        except: pass
print(uuid)
" "$TRANSCRIPT_PATH" 2>/dev/null || true)

# Load summarization prompt: user custom (via config) > plugin built-in template
AGENT_NAME="Claude Code"
PROMPT_FILE=""
if [ -n "$MEMSEARCH_CMD" ]; then
  PROMPT_FILE=$($MEMSEARCH_CMD config get prompts.summarize 2>/dev/null || true)
fi
if [ -n "$PROMPT_FILE" ] && [ -f "$PROMPT_FILE" ]; then
  SYSTEM_PROMPT=$(sed "s/{{AGENT_NAME}}/$AGENT_NAME/g" "$PROMPT_FILE")
elif [ -f "${CLAUDE_PLUGIN_ROOT}/prompts/summarize.txt" ]; then
  SYSTEM_PROMPT=$(sed "s/{{AGENT_NAME}}/$AGENT_NAME/g" "${CLAUDE_PLUGIN_ROOT}/prompts/summarize.txt")
else
  SYSTEM_PROMPT="You are a third-person note-taker. Summarize the transcript as 2-10 bullet points. Write in third person. Mandatory language rule: write every bullet in the same primary language as the [User] text. If User mixes languages, use the dominant user-facing language. Do NOT answer User's question. Output ONLY bullet points."
fi

# Summarize the last turn into structured bullet points.
# Default: use claude -p with the plugin default model. A plugin-specific
# summarize model override can replace the model without changing provider
# routing.
SUMMARY=""
SUMMARIZE_PROVIDER=""
if [ -n "$MEMSEARCH_CMD" ]; then
  SUMMARIZE_PROVIDER=$($MEMSEARCH_CMD config get plugins.claude-code.summarize.provider 2>/dev/null || true)
fi

if [ -n "$SUMMARIZE_PROVIDER" ] && [ "$SUMMARIZE_PROVIDER" != "native" ] && [ -n "$MEMSEARCH_CMD" ]; then
  SUMMARY=$(printf '%s' "$PARSED" | MEMSEARCH_NO_WATCH=1 $MEMSEARCH_CMD summarize \
    --plugin claude-code \
    --agent-name "$AGENT_NAME" \
    2>/dev/null || true)
elif command -v claude &>/dev/null; then
  SUMMARIZE_MODEL="haiku"
  if [ -n "$MEMSEARCH_CMD" ]; then
    CONFIG_MODEL=$($MEMSEARCH_CMD config get plugins.claude-code.summarize.model 2>/dev/null || true)
    if [ -n "$CONFIG_MODEL" ]; then
      SUMMARIZE_MODEL="$CONFIG_MODEL"
    fi
  fi
  # Keep the shared external-observer prompt, but pass it as the primary prompt.
  # This avoids the stdin + --system-prompt path while preserving summary rules.
  LLM_PROMPT="${SYSTEM_PROMPT}

Transcript:
${PARSED}"
  CLAUDE_SAFE_MODE_ARG=""
  if claude --help 2>/dev/null | grep -q -- '--safe-mode'; then
    CLAUDE_SAFE_MODE_ARG="--safe-mode"
  fi
  SUMMARY=$(MEMSEARCH_NO_WATCH=1 MEMSEARCH_DISABLE=1 CLAUDECODE= claude -p \
    ${CLAUDE_SAFE_MODE_ARG:+"$CLAUDE_SAFE_MODE_ARG"} \
    --strict-mcp-config \
    --tools "" \
    --model "$SUMMARIZE_MODEL" \
    --no-session-persistence \
    --no-chrome \
    "$LLM_PROMPT" \
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

# Kill any previous background index before re-indexing to avoid process accumulation
kill_orphaned_index

# Index immediately — don't rely on watch (which may be killed by SessionEnd before debounce fires)
INDEX_MILVUS_URI=""
if [ -n "$MEMSEARCH_CMD" ]; then
  INDEX_MILVUS_URI=$($MEMSEARCH_CMD config get milvus.uri 2>/dev/null || true)
fi

INDEX_OUTPUT=""
INDEX_STATUS=0
INDEX_OUTPUT=$(run_memsearch index "$MEMORY_DIR" 2>&1) || INDEX_STATUS=$?

# A successful command is not sufficient evidence that the local Lite store is
# healthy. Detect a truncated segment created by this or an overlapping index.
ZERO_BYTE_SEGMENT=$(find_zero_byte_segment "$INDEX_MILVUS_URI" || true)

if [ "$INDEX_STATUS" -ne 0 ] || [ -n "$ZERO_BYTE_SEGMENT" ]; then
  INDEX_MESSAGE="[memsearch] Stop-hook indexing failed. Markdown memory was saved, but search may be stale."
  if [ "$INDEX_STATUS" -ne 0 ]; then
    INDEX_MESSAGE+=" Index exited with status $INDEX_STATUS."
    INDEX_DETAIL=$(printf '%s\n' "$INDEX_OUTPUT" | sed '/^[[:space:]]*$/d' | tail -n 1 | cut -c1-500)
    if [ -n "$INDEX_DETAIL" ]; then
      INDEX_MESSAGE+=" $INDEX_DETAIL"
    fi
  fi
  if [ -n "$ZERO_BYTE_SEGMENT" ]; then
    INDEX_MESSAGE+=" Zero-byte Milvus segment detected: $ZERO_BYTE_SEGMENT."
  fi
  INDEX_MESSAGE+=" Repair or rebuild the derived index before relying on memory search."
  JSON_INDEX_MESSAGE=$(_json_encode_str "$INDEX_MESSAGE")
  echo "{\"systemMessage\": $JSON_INDEX_MESSAGE}"
  exit 0
fi

echo '{}'
