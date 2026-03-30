#!/usr/bin/env bash
# Stop hook: extract last turn context, summarize with codex exec LLM, save to memory.
# Uses isolated CODEX_HOME (no hooks.json) to prevent hook recursion.
# Async: outputs {} immediately, runs summarization in background.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Prevent infinite loop: if this Stop was triggered by a previous Stop hook, bail out
STOP_HOOK_ACTIVE=$(_json_val "$INPUT" "stop_hook_active" "false")
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  echo '{}'
  exit 0
fi

# Skip summarization when the required API key is missing
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

# Determine today's date and current time
TODAY=$(date +%Y-%m-%d)
NOW=$(date +%H:%M)
MEMORY_FILE="$MEMORY_DIR/$TODAY.md"

# Extract session ID for progressive disclosure anchors
SESSION_ID=$(_json_val "$INPUT" "session_id" "")
if [ -z "$SESSION_ID" ]; then
  SESSION_ID=$(basename "$TRANSCRIPT_PATH" .jsonl | sed 's/^rollout-//')
fi

# Extract user question and last assistant message before going async
LAST_MSG=$(_json_val "$INPUT" "last_assistant_message" "")

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

# Return immediately — summarization runs in background
echo '{}'

# --- Background: summarize with codex exec LLM, fallback to local, write to memory ---
(
  # Build content for LLM summarization from parsed rollout
  CONTENT=""
  PARSED=$("$SCRIPT_DIR/../scripts/parse-rollout.sh" "$TRANSCRIPT_PATH" 2>/dev/null || true)

  if [ -n "$PARSED" ] && [ "$PARSED" != "(empty rollout)" ] && [ "$PARSED" != "(no user message found)" ] && [ "$PARSED" != "(empty turn)" ]; then
    CONTENT="$PARSED"
  elif [ -n "$LAST_MSG" ] && [ -n "$USER_QUESTION" ]; then
    CONTENT="[Human]: ${USER_QUESTION}
[Codex]: ${LAST_MSG}"
  elif [ -n "$LAST_MSG" ]; then
    CONTENT="[Codex]: ${LAST_MSG}"
  else
    # No content to summarize
    exit 0
  fi

  # Truncate content to ~4000 chars for the LLM prompt
  if [ ${#CONTENT} -gt 4000 ]; then
    CONTENT="${CONTENT:0:4000}...(truncated)"
  fi

  # Try LLM summarization via codex exec with isolated CODEX_HOME
  SUMMARY=""
  if command -v codex &>/dev/null; then
    # Create isolated CODEX_HOME — no hooks.json means no hooks trigger (no recursion)
    CODEX_ISOLATED="/tmp/codex-no-hooks"
    mkdir -p "$CODEX_ISOLATED"
    [ -f "$HOME/.codex/auth.json" ] && ln -sf "$HOME/.codex/auth.json" "$CODEX_ISOLATED/auth.json"

    LLM_PROMPT="You are a third-person note-taker. You will receive a transcript of ONE conversation turn between a human and Codex CLI. Tool calls are labeled [Codex calls tool] and their results [Tool output].

Your job is to record what happened as factual third-person notes. You are an EXTERNAL OBSERVER — you are NOT Codex, NOT an assistant. Do NOT answer the human's question, do NOT give suggestions, do NOT offer help. ONLY record what occurred.

Output 2-6 bullet points, each starting with '- '. NOTHING else.

Rules:
- Write in third person: 'User asked...', 'Codex read file X', 'Codex ran command Y'
- First bullet: what the user asked or wanted (one sentence)
- Remaining bullets: what Codex did — tools called, files read/edited, commands run, key findings
- Be specific: mention file names, function names, tool names, and concrete outcomes
- Do NOT answer the human's question yourself — just note what was discussed
- Do NOT add any text before or after the bullet points
- Write in the same language as the human's message (the [Human] line) in the transcript

Here is the transcript:

${CONTENT}"

    SUMMARY=$(CODEX_HOME="$CODEX_ISOLATED" MEMSEARCH_NO_WATCH=1 timeout 30 codex exec \
      --ephemeral \
      --skip-git-repo-check \
      -s read-only \
      -m gpt-5.1-codex-mini \
      "$LLM_PROMPT" 2>/dev/null || true)
  fi

  # Fallback: local summarization if codex exec failed or returned empty
  if [ -z "$SUMMARY" ]; then
    if [ -n "$LAST_MSG" ] && [ -n "$USER_QUESTION" ]; then
      TRUNCATED_MSG=$(printf '%s' "$LAST_MSG" | head -c 800)
      if [ ${#LAST_MSG} -gt 800 ]; then
        TRUNCATED_MSG="${TRUNCATED_MSG}..."
      fi
      SUMMARY="- User asked: ${USER_QUESTION}
- Codex: ${TRUNCATED_MSG}"
    elif [ -n "$LAST_MSG" ]; then
      TRUNCATED_MSG=$(printf '%s' "$LAST_MSG" | head -c 800)
      if [ ${#LAST_MSG} -gt 800 ]; then
        TRUNCATED_MSG="${TRUNCATED_MSG}..."
      fi
      SUMMARY="- Codex: ${TRUNCATED_MSG}"
    else
      SUMMARY="$CONTENT"
    fi
  fi

  # Append as a sub-heading under the session heading written by SessionStart
  # Include HTML comment anchor for progressive disclosure (L3 rollout lookup)
  {
    echo "### $NOW"
    if [ -n "$SESSION_ID" ]; then
      echo "<!-- session:${SESSION_ID} rollout:${TRANSCRIPT_PATH} -->"
    fi
    echo "$SUMMARY"
    echo ""
  } >> "$MEMORY_FILE"

  # Only index in stop hook for Server mode — Milvus Lite has file lock issues
  _uri="${MILVUS_URI:-$($MEMSEARCH_CMD config get milvus.uri 2>/dev/null || echo "")}"
  if [[ "$_uri" == http* ]] || [[ "$_uri" == tcp* ]]; then
    kill_orphaned_index
    run_memsearch index "$MEMORY_DIR" >/dev/null
  fi
) >/dev/null 2>&1 &
