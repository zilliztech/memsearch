#!/usr/bin/env bash
# Stop hook: extract last turn context, summarize with codex exec LLM, save to memory.
# Uses the normal CODEX_HOME auth context with hooks disabled to prevent recursion.
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

_latest_user_prompt_from_history() {
  local session_id="$1"
  local history_file="${CODEX_HOME:-$HOME/.codex}/history.jsonl"
  if [ -z "$session_id" ] || [ ! -f "$history_file" ]; then
    return 0
  fi

  python3 -c "
import json, sys
session_id = sys.argv[1]
history_file = sys.argv[2]
latest = ''
with open(history_file) as f:
    for line in f:
        try:
            obj = json.loads(line)
            if obj.get('session_id') == session_id:
                text = (obj.get('text') or '').strip()
                if text:
                    latest = text
        except Exception:
            pass
print(latest)
" "$session_id" "$history_file" 2>/dev/null || true
}

_load_worker_field() {
  local work_input="$1"
  local key="$2"
  _json_val "$work_input" "$key" ""
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

  local NOW MEMORY_FILE SESSION_ID TRANSCRIPT_PATH CONTENT USER_QUESTION LAST_MSG
  NOW=$(_load_worker_field "$work_input" "now")
  MEMORY_FILE=$(_load_worker_field "$work_input" "memory_file")
  SESSION_ID=$(_load_worker_field "$work_input" "session_id")
  TRANSCRIPT_PATH=$(_load_worker_field "$work_input" "transcript_path")
  CONTENT=$(_load_worker_field "$work_input" "content")
  USER_QUESTION=$(_load_worker_field "$work_input" "user_question")
  LAST_MSG=$(_load_worker_field "$work_input" "last_msg")

  if [ -z "$MEMORY_FILE" ] || [ -z "$CONTENT" ]; then
    exit 0
  fi

  ensure_memory_dir

  # Load summarization prompt: user custom (via config) > plugin built-in template
  local AGENT_NAME="Codex"
  local PROMPT_FILE=""
  if [ -n "$MEMSEARCH_CMD" ]; then
    PROMPT_FILE=$($MEMSEARCH_CMD config get prompts.summarize 2>/dev/null || true)
  fi
  local SYSTEM_PROMPT=""
  if [ -n "$PROMPT_FILE" ] && [ -f "$PROMPT_FILE" ]; then
    SYSTEM_PROMPT=$(sed "s/{{AGENT_NAME}}/$AGENT_NAME/g" "$PROMPT_FILE")
  elif [ -f "$SCRIPT_DIR/../prompts/summarize.txt" ]; then
    SYSTEM_PROMPT=$(sed "s/{{AGENT_NAME}}/$AGENT_NAME/g" "$SCRIPT_DIR/../prompts/summarize.txt")
  else
    SYSTEM_PROMPT="You are a third-person note-taker. Summarize the transcript as 2-6 bullet points. Write in third person. Output ONLY bullet points."
  fi

  local SUMMARY=""
  if command -v codex &>/dev/null; then
    local LLM_PROMPT
    LLM_PROMPT="${SYSTEM_PROMPT}

Here is the transcript:

${CONTENT}"

    if command -v timeout &>/dev/null; then
      SUMMARY=$(MEMSEARCH_NO_WATCH=1 MEMSEARCH_IN_STOP_WORKER=1 timeout 30 codex exec \
        --ephemeral \
        --skip-git-repo-check \
        -s read-only \
        -c features.codex_hooks=false \
        -c model_reasoning_effort='"low"' \
        -m gpt-5.1-codex-mini \
        "$LLM_PROMPT" 2>/dev/null || true)
    else
      SUMMARY=$(MEMSEARCH_NO_WATCH=1 MEMSEARCH_IN_STOP_WORKER=1 codex exec \
        --ephemeral \
        --skip-git-repo-check \
        -s read-only \
        -c features.codex_hooks=false \
        -c model_reasoning_effort='"low"' \
        -m gpt-5.1-codex-mini \
        "$LLM_PROMPT" 2>/dev/null || true)
    fi
  fi

  if [ -z "$SUMMARY" ]; then
    if [ -n "$LAST_MSG" ] && [ -n "$USER_QUESTION" ]; then
      local TRUNCATED_MSG
      TRUNCATED_MSG=$(printf '%s' "$LAST_MSG" | head -c 800)
      if [ ${#LAST_MSG} -gt 800 ]; then
        TRUNCATED_MSG="${TRUNCATED_MSG}..."
      fi
      SUMMARY="- User asked: ${USER_QUESTION}
- Codex: ${TRUNCATED_MSG}"
    elif [ -n "$LAST_MSG" ]; then
      local TRUNCATED_MSG
      TRUNCATED_MSG=$(printf '%s' "$LAST_MSG" | head -c 800)
      if [ ${#LAST_MSG} -gt 800 ]; then
        TRUNCATED_MSG="${TRUNCATED_MSG}..."
      fi
      SUMMARY="- Codex: ${TRUNCATED_MSG}"
    else
      SUMMARY="$CONTENT"
    fi
  fi

  {
    echo "### $NOW"
    if [ -n "$SESSION_ID" ]; then
      echo "<!-- session:${SESSION_ID} rollout:${TRANSCRIPT_PATH} -->"
    fi
    echo "$SUMMARY"
    echo ""
  } >> "$MEMORY_FILE"

  local _uri
  _uri="${MILVUS_URI:-$(_memsearch config get milvus.uri 2>/dev/null || echo "")}"
  if [[ "$_uri" == http* ]] || [[ "$_uri" == tcp* ]]; then
    kill_orphaned_index
    run_memsearch index "$MEMORY_DIR" >/dev/null
  fi
}

if [ "${1:-}" = "--worker" ]; then
  run_worker "${2:-}"
  exit 0
fi

source "$SCRIPT_DIR/common.sh"

# Defense-in-depth against recursion: the worker's `codex exec` passes
# `features.codex_hooks=false`, but if a future build ignores that flag the
# nested Stop hook would spawn another worker. MEMSEARCH_IN_STOP_WORKER is
# exported across the exec boundary so the nested invocation no-ops here.
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

# Extract transcript path from hook input
TRANSCRIPT_PATH=$(_json_val "$INPUT" "transcript_path" "")

ensure_memory_dir

# Determine today's date and current time
TODAY=$(date +%Y-%m-%d)
NOW=$(date +%H:%M)
MEMORY_FILE="$MEMORY_DIR/$TODAY.md"

# Extract session ID for progressive disclosure anchors
SESSION_ID=$(_json_val "$INPUT" "session_id" "")
if [ -z "$SESSION_ID" ] && [ -n "$TRANSCRIPT_PATH" ]; then
  SESSION_ID=$(basename "$TRANSCRIPT_PATH" .jsonl | sed 's/^rollout-//')
fi

# Extract user question and last assistant message before going async
LAST_MSG=$(_json_val "$INPUT" "last_assistant_message" "")
# Cap before it flows into sys.argv of the work-file Python payload.
# Unbounded transcripts risk ARG_MAX overflow on execve; the worker only
# ever uses the first 800 chars of LAST_MSG as a fallback summary anyway.
if [ ${#LAST_MSG} -gt 4000 ]; then
  LAST_MSG="${LAST_MSG:0:4000}...(truncated)"
fi
USER_QUESTION=""
PARSED=""

if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
  LINE_COUNT=$(wc -l < "$TRANSCRIPT_PATH" 2>/dev/null || echo "0")
  if [ "$LINE_COUNT" -lt 3 ]; then
    echo '{}'
    exit 0
  fi

  USER_QUESTION=$(python3 -c "
import json, sys
last_q = ''
with open(sys.argv[1]) as f:
    for line in f:
        try:
            obj = json.loads(line)
            if obj.get('type') == 'event_msg':
                p = obj.get('payload', {})
                if p.get('type') == 'user_message':
                    msg = p.get('message', '').strip()
                    if msg:
                        last_q = msg
        except:
            pass
# Truncate to first line, max 200 chars
first_line = last_q.split('\n')[0][:200] if last_q else ''
print(first_line)
" "$TRANSCRIPT_PATH" 2>/dev/null || true)

  # Parse the last turn before returning. Codex may clean up transient rollout
  # files as soon as the hook completes, so the detached worker should work
  # from cached content instead of reopening the transcript path later.
  PARSED=$("$SCRIPT_DIR/../scripts/parse-rollout.sh" "$TRANSCRIPT_PATH" 2>/dev/null || true)
fi

if [ -z "$USER_QUESTION" ]; then
  USER_QUESTION=$(_latest_user_prompt_from_history "$SESSION_ID")
fi

CONTENT=""
if [ -n "$PARSED" ] && [ "$PARSED" != "(empty rollout)" ] && [ "$PARSED" != "(no user message found)" ] && [ "$PARSED" != "(empty turn)" ]; then
  CONTENT="$PARSED"
elif [ -n "$LAST_MSG" ] && [ -n "$USER_QUESTION" ]; then
  CONTENT="[Human]: ${USER_QUESTION}
[Codex]: ${LAST_MSG}"
elif [ -n "$LAST_MSG" ]; then
  CONTENT="[Codex]: ${LAST_MSG}"
else
  echo '{}'
  exit 0
fi

if [ ${#CONTENT} -gt 4000 ]; then
  CONTENT="${CONTENT:0:4000}...(truncated)"
fi

WORK_FILE="$(mktemp "${TMPDIR:-/tmp}/memsearch-stop.XXXXXX.json")"
python3 - "$WORK_FILE" "$NOW" "$MEMORY_FILE" "$SESSION_ID" "$TRANSCRIPT_PATH" "$CONTENT" "$USER_QUESTION" "$LAST_MSG" <<'PY'
from pathlib import Path
import json
import sys

payload = {
    "now": sys.argv[2],
    "memory_file": sys.argv[3],
    "session_id": sys.argv[4],
    "transcript_path": sys.argv[5],
    "content": sys.argv[6],
    "user_question": sys.argv[7],
    "last_msg": sys.argv[8],
}
Path(sys.argv[1]).write_text(json.dumps(payload))
PY

echo '{}'

if command -v setsid &>/dev/null; then
  MEMSEARCH_PROJECT_DIR="$PROJECT_DIR" MEMSEARCH_SKIP_HOOK_STDIN=1 setsid bash "$0" --worker "$WORK_FILE" </dev/null &>/dev/null &
else
  MEMSEARCH_PROJECT_DIR="$PROJECT_DIR" MEMSEARCH_SKIP_HOOK_STDIN=1 nohup bash "$0" --worker "$WORK_FILE" </dev/null &>/dev/null &
fi
