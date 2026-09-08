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

if memsearch_available && ! require_default_collection_support; then
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
_PROVIDER=$(_memsearch config get embedding.provider 2>/dev/null || echo "onnx")
_REQ_KEY=$(_required_env_var "$_PROVIDER")
if [ -n "$_REQ_KEY" ] && [ -z "${!_REQ_KEY:-}" ]; then
  # Env var not set — check if API key is configured in memsearch config file
  _CONFIG_API_KEY=""
  if memsearch_available; then
    _CONFIG_API_KEY=$(_memsearch config get embedding.api_key 2>/dev/null || echo "")
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

SUMMARIZE_ENABLED=$(_memsearch config get plugins.claude-code.summarize.enabled 2>/dev/null || echo "true")
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
if memsearch_available; then
  PROMPT_FILE=$(_memsearch config get prompts.summarize 2>/dev/null || true)
  [ -n "$PROMPT_FILE" ] && PROMPT_FILE=$(project_path "$PROMPT_FILE")
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
SUMMARY_STATUS=0
SUMMARY_FAILURE=""
SUMMARIZE_PROVIDER=""
if memsearch_available; then
  SUMMARIZE_PROVIDER=$(_memsearch config get plugins.claude-code.summarize.provider 2>/dev/null || true)
fi

_run_summarizer() {
  (
    cd "$_PROJECT_DIR"
    if command -v timeout &>/dev/null; then
      timeout 110 "$@"
    else
      perl -e 'alarm shift; exec @ARGV' 110 "$@"
    fi
  )
}

if [ -n "$SUMMARIZE_PROVIDER" ] && [ "$SUMMARIZE_PROVIDER" != "native" ] && memsearch_available; then
  set +e
  SUMMARY=$(printf '%s' "$PARSED" | MEMSEARCH_NO_WATCH=1 _run_summarizer "${MEMSEARCH_CMD[@]}" summarize \
    --plugin claude-code \
    --agent-name "$AGENT_NAME" \
    2>/dev/null)
  SUMMARY_STATUS=$?
  set -e
elif command -v claude &>/dev/null; then
  SUMMARIZE_MODEL="haiku"
  if memsearch_available; then
    CONFIG_MODEL=$(_memsearch config get plugins.claude-code.summarize.model 2>/dev/null || true)
    if [ -n "$CONFIG_MODEL" ]; then
      SUMMARIZE_MODEL="$CONFIG_MODEL"
    fi
  fi
  # Keep the shared external-observer prompt as the primary prompt, but deliver
  # it over stdin so transcript size never contributes to argv limits.
  LLM_PROMPT="${SYSTEM_PROMPT}

Transcript:
${PARSED}"
  CLAUDE_SAFE_MODE_ARG=""
  if claude --help 2>/dev/null | grep -q -- '--safe-mode'; then
    CLAUDE_SAFE_MODE_ARG="--safe-mode"
  fi
  set +e
  SUMMARY=$(printf '%s' "$LLM_PROMPT" | MEMSEARCH_NO_WATCH=1 MEMSEARCH_DISABLE=1 CLAUDECODE= _run_summarizer claude -p \
    ${CLAUDE_SAFE_MODE_ARG:+"$CLAUDE_SAFE_MODE_ARG"} \
    --strict-mcp-config \
    --tools "" \
    --model "$SUMMARIZE_MODEL" \
    --no-session-persistence \
    --no-chrome \
    2>/dev/null)
  SUMMARY_STATUS=$?
  set -e
else
  SUMMARY_FAILURE="summarizer unavailable"
fi

if [ -z "$SUMMARY_FAILURE" ] && [ "$SUMMARY_STATUS" -ne 0 ]; then
  if [ "$SUMMARY_STATUS" -eq 124 ] || [ "$SUMMARY_STATUS" -eq 142 ]; then
    SUMMARY_FAILURE="summarizer timed out"
  else
    SUMMARY_FAILURE="summarizer exited with status $SUMMARY_STATUS"
  fi
elif [ -z "$SUMMARY_FAILURE" ] && [ -z "$SUMMARY" ]; then
  SUMMARY_FAILURE="summarizer returned empty output"
fi
if [ -n "$SUMMARY_FAILURE" ]; then
  SUMMARY="- Memory summary unavailable: ${SUMMARY_FAILURE}; transcript content was omitted. Use the transcript anchor for progressive disclosure."
fi

# Append under a session heading, writing the heading lazily on the first
# content-bearing Stop of this session (SessionStart no longer writes it
# eagerly, so sessions without summaries leave no stub journals). The
# progressive-disclosure anchor comment doubles as the heading-written marker.
{
  if [ -z "$SESSION_ID" ] || ! grep -qF "session:${SESSION_ID}" "$MEMORY_FILE" 2>/dev/null; then
    echo -e "\n## Session $NOW\n"
  fi
  echo "### $NOW"
  if [ -n "$SESSION_ID" ]; then
    echo "<!-- session:${SESSION_ID} turn:${LAST_USER_TURN_UUID} transcript:${TRANSCRIPT_PATH} -->"
  fi
  echo "$SUMMARY"
  echo ""
} >> "$MEMORY_FILE"

# Server mode indexes immediately instead of relying on the watch debounce.
# Lite mode keeps the SessionStart one-shot index: restarting it after every
# turn can permanently starve a slow index before it completes.
_uri="${MILVUS_URI:-$(_memsearch config get milvus.uri 2>/dev/null || echo "")}"
if [[ "$_uri" == http* ]] || [[ "$_uri" == tcp* ]]; then
  kill_orphaned_index
  run_memsearch index "$MEMORY_DIR"
fi

echo '{}'
