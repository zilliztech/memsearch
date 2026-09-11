#!/usr/bin/env bash
# Stop hook: extract last turn from the ZCode session DB, summarize with the
# native LLM, and save to memory.
#
# ZCode injects CLAUDE_SESSION_ID (the session id) and ZCODE_PROJECT_DIR.
# The conversation is read from the ZCode SQLite DB (~/.zcode/cli/db/db.sqlite)
# via parse-session.py, not from a JSONL transcript file.
#
# Async: outputs {} immediately, then hands work to a detached worker.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

_truncate_chars() {
  local limit="$1"
  python3 -c "
import sys
limit = int(sys.argv[1])
text = sys.stdin.read()
sys.stdout.write(text[:limit])
" "$limit" 2>/dev/null || true
}

_valid_utf8() {
  iconv -f UTF-8 -t UTF-8 -c 2>/dev/null || cat
}

run_worker() {
  local work_file="${1:-}"
  if [ -z "$work_file" ] || [ ! -f "$work_file" ]; then
    exit 0
  fi

  export MEMSEARCH_SKIP_HOOK_STDIN=1
  source "$SCRIPT_DIR/common.sh"

  local work_input
  work_input=$(cat "$work_file" 2>/dev/null || echo "")
  rm -f "$work_file"
  if [ -z "$work_input" ]; then
    exit 0
  fi

  local NOW MEMORY_FILE SESSION_ID DB_PATH CONTENT
  NOW=$(_json_val "$work_input" "now" "")
  MEMORY_FILE=$(_json_val "$work_input" "memory_file" "")
  SESSION_ID=$(_json_val "$work_input" "session_id" "")
  DB_PATH=$(_json_val "$work_input" "db_path" "")
  CONTENT=$(_json_val "$work_input" "content" "")

  if [ -z "$MEMORY_FILE" ] || [ -z "$CONTENT" ]; then
    exit 0
  fi

  ensure_memory_dir

  local SUMMARIZE_ENABLED="true"
  if memsearch_available; then
    SUMMARIZE_ENABLED=$(_memsearch config get plugins.zcode.summarize.enabled 2>/dev/null || echo "true")
  fi
  if [ "$SUMMARIZE_ENABLED" = "false" ]; then
    return 0
  fi

  local AGENT_NAME="ZCode"
  local PROMPT_FILE=""
  if [ -n "${MEMSEARCH_CMD:-}" ]; then
    PROMPT_FILE=$("${MEMSEARCH_CMD[@]}" config get prompts.summarize 2>/dev/null || true)
  fi
  local SYSTEM_PROMPT=""
  if [ -n "$PROMPT_FILE" ] && [ -f "$PROMPT_FILE" ]; then
    SYSTEM_PROMPT=$(sed "s/{{AGENT_NAME}}/$AGENT_NAME/g" "$PROMPT_FILE")
  elif [ -f "$SCRIPT_DIR/../prompts/summarize.txt" ]; then
    SYSTEM_PROMPT=$(sed "s/{{AGENT_NAME}}/$AGENT_NAME/g" "$SCRIPT_DIR/../prompts/summarize.txt")
  else
    SYSTEM_PROMPT="You are a third-person note-taker. Summarize the transcript as 2-10 bullet points. Write in third person. Mandatory language rule: write every bullet in the same primary language as the [User] text. If User mixes languages, use the dominant user-facing language. Do NOT answer User's question. Output ONLY bullet points."
  fi

  local SUMMARY=""
  local SUMMARIZE_PROVIDER=""
  if memsearch_available; then
    SUMMARIZE_PROVIDER=$(_memsearch config get plugins.zcode.summarize.provider 2>/dev/null || true)
  fi

  if [ -n "$SUMMARIZE_PROVIDER" ] && [ "$SUMMARIZE_PROVIDER" != "native" ] && memsearch_available; then
    SUMMARY=$(printf '%s' "$CONTENT" | MEMSEARCH_NO_WATCH=1 MEMSEARCH_IN_STOP_WORKER=1 _memsearch summarize \
      --plugin zcode \
      --agent-name "$AGENT_NAME" \
      2>/dev/null || true)
  elif command -v claude &>/dev/null; then
    local LLM_PROMPT
    LLM_PROMPT="${SYSTEM_PROMPT}

Here is the transcript:

${CONTENT}"
    local SUMMARIZE_MODEL="haiku"
    if memsearch_available; then
      local CONFIG_MODEL
      CONFIG_MODEL=$(_memsearch config get plugins.zcode.summarize.model 2>/dev/null || true)
      if [ -n "$CONFIG_MODEL" ]; then
        SUMMARIZE_MODEL="$CONFIG_MODEL"
      fi
    fi

    CLAUDE_SAFE_MODE_ARG=""
    if claude --help 2>/dev/null | grep -q -- '--safe-mode'; then
      CLAUDE_SAFE_MODE_ARG="--safe-mode"
    fi

    if command -v timeout &>/dev/null; then
      SUMMARY=$(printf '%s' "$LLM_PROMPT" | MEMSEARCH_NO_WATCH=1 MEMSEARCH_IN_STOP_WORKER=1 CLAUDECODE= timeout 110 claude -p \
        ${CLAUDE_SAFE_MODE_ARG:+"$CLAUDE_SAFE_MODE_ARG"} \
        --strict-mcp-config \
        --tools "" \
        --model "$SUMMARIZE_MODEL" \
        --no-session-persistence \
        --no-chrome \
        2>/dev/null || true)
    else
      SUMMARY=$(printf '%s' "$LLM_PROMPT" | MEMSEARCH_NO_WATCH=1 MEMSEARCH_IN_STOP_WORKER=1 CLAUDECODE= claude -p \
        ${CLAUDE_SAFE_MODE_ARG:+"$CLAUDE_SAFE_MODE_ARG"} \
        --strict-mcp-config \
        --tools "" \
        --model "$SUMMARIZE_MODEL" \
        --no-session-persistence \
        --no-chrome \
        2>/dev/null || true)
    fi
  fi

  if [ -z "$SUMMARY" ]; then
    SUMMARY="$CONTENT"
  fi

  {
    echo "### $NOW"
    if [ -n "$SESSION_ID" ]; then
      echo "<!-- session:${SESSION_ID} db:${DB_PATH} -->"
    fi
    printf '%s\n' "$SUMMARY" | _valid_utf8
    echo ""
  } >> "$MEMORY_FILE"

  local _uri
  _uri="${MILVUS_URI:-$(_memsearch config get milvus.uri 2>/dev/null || echo "")}"
  if [[ "$_uri" == http* ]] || [[ "$_uri" == tcp* ]]; then
    kill_orphaned_index
    run_memsearch index "$MEMORY_DIR" >/dev/null
  fi

  run_maintenance
}

if [ "${1:-}" = "--worker" ]; then
  run_worker "${2:-}"
  exit 0
fi

source "$SCRIPT_DIR/common.sh"

# Defense-in-depth against recursion
if [ -n "${MEMSEARCH_IN_STOP_WORKER:-}" ]; then
  echo '{}'
  exit 0
fi

# Prevent infinite loop: if this Stop was triggered by a previous Stop hook, bail out
STOP_HOOK_ACTIVE=$(_json_val "$INPUT" "stop_hook_active" "false")
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  echo '{}'
  exit 0
fi

# Skip summarization when the required API key is missing
_PROVIDER=$(_memsearch config get embedding.provider 2>/dev/null || echo "onnx")
_REQ_KEY=$(_required_env_var "$_PROVIDER")
if [ -n "$_REQ_KEY" ] && [ -z "${!_REQ_KEY:-}" ]; then
  _CONFIG_API_KEY=""
  if memsearch_available; then
    _CONFIG_API_KEY=$(_memsearch config get embedding.api_key 2>/dev/null || echo "")
  fi
  if [ -z "$_CONFIG_API_KEY" ]; then
    echo '{}'
    exit 0
  fi
fi

# Need a session id to query the DB
if [ -z "$ZCODE_SESSION_ID" ]; then
  echo '{}'
  exit 0
fi

ensure_memory_dir

TODAY=$(date +%Y-%m-%d)
NOW=$(date +%H:%M)
MEMORY_FILE="$MEMORY_DIR/$TODAY.md"

# Parse the last turn from the ZCode session DB before going async.
# No session-level dedup: the Stop hook fires per-turn and parse-session.py
# always extracts the latest turn, so each fire captures a different exchange
# (same approach as the codex plugin).
CONTENT=""
if [ -f "$ZCODE_DB_PATH" ]; then
  CONTENT=$(python3 "$SCRIPT_DIR/../scripts/parse-session.py" \
    --session "$ZCODE_SESSION_ID" \
    --db "$ZCODE_DB_PATH" \
    2>/dev/null || true)
fi

if [ -z "$CONTENT" ] || [ "$CONTENT" = "(empty turn)" ] || [ "$CONTENT" = "(no messages found)" ] || [ "$CONTENT" = "(no turns found)" ]; then
  echo '{}'
  exit 0
fi

MAX_CONTENT_CHARS="${MEMSEARCH_SUMMARY_MAX_CHARS:-8000}"
if [ ${#CONTENT} -gt "$MAX_CONTENT_CHARS" ]; then
  CONTENT="$(printf '%s' "$CONTENT" | _truncate_chars "$MAX_CONTENT_CHARS")...(truncated)"
fi

WORK_FILE="$(mktemp "${TMPDIR:-/tmp}/memsearch-zcode-stop.XXXXXX.json")"
python3 - "$WORK_FILE" "$NOW" "$MEMORY_FILE" "$ZCODE_SESSION_ID" "$ZCODE_DB_PATH" "$CONTENT" <<'PY'
from pathlib import Path
import json
import sys

payload = {
    "now": sys.argv[2],
    "memory_file": sys.argv[3],
    "session_id": sys.argv[4],
    "db_path": sys.argv[5],
    "content": sys.argv[6],
}
Path(sys.argv[1]).write_text(json.dumps(payload))
PY

echo '{}'

if command -v setsid &>/dev/null; then
  MEMSEARCH_PROJECT_DIR="$PROJECT_DIR" MEMSEARCH_SKIP_HOOK_STDIN=1 setsid bash "$0" --worker "$WORK_FILE" </dev/null &>/dev/null &
else
  MEMSEARCH_PROJECT_DIR="$PROJECT_DIR" MEMSEARCH_SKIP_HOOK_STDIN=1 nohup bash "$0" --worker "$WORK_FILE" </dev/null &>/dev/null &
fi
