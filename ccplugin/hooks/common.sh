#!/usr/bin/env bash
# Shared setup for memsearch command hooks.
# Sourced by all hook scripts — not executed directly.

set -euo pipefail

# Read stdin JSON into $INPUT
INPUT="$(cat)"

# Ensure common user bin paths are in PATH (hooks may run in a minimal env)
for p in "$HOME/.local/bin" "$HOME/.cargo/bin" "$HOME/bin" "/usr/local/bin"; do
  [[ -d "$p" ]] && [[ ":$PATH:" != *":$p:"* ]] && export PATH="$p:$PATH"
done

# Hooks directory (where this file lives)
HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Memory directory and memsearch state directory are project-scoped
MEMSEARCH_DIR="${CLAUDE_PROJECT_DIR:-.}/.memsearch"
MEMORY_DIR="$MEMSEARCH_DIR/memory"
PENDING_DIR="$MEMSEARCH_DIR/.pending"

# Find memsearch binary: prefer PATH, fallback to uvx
_detect_memsearch() {
  MEMSEARCH_CMD=""
  if command -v memsearch &>/dev/null; then
    MEMSEARCH_CMD="memsearch"
  elif command -v uvx &>/dev/null; then
    MEMSEARCH_CMD="uvx memsearch"
  fi
}
_detect_memsearch

# Short command prefix for injected instructions (falls back to "memsearch" even if unavailable)
MEMSEARCH_CMD_PREFIX="${MEMSEARCH_CMD:-memsearch}"

# --- JSON helpers (jq preferred, python3 fallback) ---

# _json_val <json_string> <dotted_key> [default]
# Extract a value from JSON. Key supports dotted notation (e.g. "info.version").
# Returns the default (or empty string) if the key is missing or extraction fails.
_json_val() {
  local json="$1" key="$2" default="${3:-}"
  local result=""

  if command -v jq &>/dev/null; then
    # Build jq filter from dotted key: "info.version" → ".info.version"
    result=$(printf '%s' "$json" | jq -r ".${key} // empty" 2>/dev/null) || true
  else
    result=$(python3 -c "
import json, sys
try:
    obj = json.loads(sys.argv[1])
    val = obj
    for k in sys.argv[2].split('.'):
        val = val[k]
    if val is None:
        print('')
    elif isinstance(val, bool):
        print(str(val).lower())
    else:
        print(val)
except Exception:
    print('')
" "$json" "$key" 2>/dev/null) || true
  fi

  if [ -z "$result" ]; then
    printf '%s' "$default"
  else
    printf '%s' "$result"
  fi
  return 0
}

# _json_encode_str <string>
# Encode a string as a JSON string (with surrounding quotes).
_json_encode_str() {
  local str="$1"
  if command -v jq &>/dev/null; then
    printf '%s' "$str" | jq -Rs . 2>/dev/null && return 0
  fi
  printf '%s' "$str" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))" 2>/dev/null && return 0
  # Last resort: simple quoting (no special char escaping)
  printf '"%s"' "$str"
  return 0
}

# Helper: ensure memory directory exists
ensure_memory_dir() {
  mkdir -p "$MEMORY_DIR"
}

# Helper: run memsearch with arguments, silently fail if not available
run_memsearch() {
  if [ -n "$MEMSEARCH_CMD" ]; then
    $MEMSEARCH_CMD "$@" 2>/dev/null || true
  fi
}

# Helper: check if the embedding provider's API key is set.
# Returns 0 (true) if key is present or not required, 1 (false) if missing.
_check_embedding_key() {
  local provider
  provider=$($MEMSEARCH_CMD config get embedding.provider 2>/dev/null || echo "openai")
  local req_key=""
  case "$provider" in
    openai) req_key="OPENAI_API_KEY" ;;
    google) req_key="GOOGLE_API_KEY" ;;
    voyage) req_key="VOYAGE_API_KEY" ;;
    *) return 0 ;;  # ollama, local — no API key needed
  esac
  [ -z "$req_key" ] || [ -n "${!req_key:-}" ]
}

# --- Watch singleton management ---

WATCH_PIDFILE="$MEMSEARCH_DIR/.watch.pid"

# Kill a process and its entire process group to avoid orphans
_kill_tree() {
  local pid="$1"
  # Kill the process group (negative PID) to catch child processes
  kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
}

# Stop the watch process: pidfile first, then sweep for orphans
stop_watch() {
  # 1. Kill the process recorded in pidfile
  if [ -f "$WATCH_PIDFILE" ]; then
    local pid
    pid=$(cat "$WATCH_PIDFILE" 2>/dev/null)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      _kill_tree "$pid"
    fi
    rm -f "$WATCH_PIDFILE"
  fi

  # 2. Sweep for orphaned watch processes targeting this MEMORY_DIR
  local orphans
  orphans=$(pgrep -f "memsearch watch $MEMORY_DIR" 2>/dev/null || true)
  if [ -n "$orphans" ]; then
    echo "$orphans" | while read -r opid; do
      kill "$opid" 2>/dev/null || true
    done
  fi
}

# Start memsearch watch — always stop-then-start to pick up config changes
start_watch() {
  if [ -z "$MEMSEARCH_CMD" ]; then
    return 0
  fi
  ensure_memory_dir

  # Always restart: ensures latest config (milvus_uri, etc.) is used
  stop_watch

  nohup $MEMSEARCH_CMD watch "$MEMORY_DIR" &>/dev/null &
  echo $! > "$WATCH_PIDFILE"
}

# --- Pending session management (stop-hook dedup) ---
#
# The Stop hook fires after every assistant turn, but we only want one summary
# per session. Stop only records the transcript path in a lightweight state file
# (overwriting each time — last writer wins). The expensive work (parsing +
# Haiku summarization) happens exactly once in flush_pending(), called by
# SessionEnd (and by SessionStart as a safety net for crashed sessions).

# Summarize a single pending session and append to its daily .md file.
# Args: $1 = pending state file path
_summarize_pending() {
  local pending="$1"
  [ -f "$pending" ] || return 0

  # Read state: line 1 = transcript path, line 2 = target date
  local transcript_path target_date
  transcript_path=$(sed -n '1p' "$pending")
  target_date=$(sed -n '2p' "$pending")

  # Validate
  if [ -z "$transcript_path" ] || [ ! -f "$transcript_path" ] || [ -z "$target_date" ]; then
    rm -f "$pending"
    return 0
  fi

  # Skip empty transcripts (< 3 lines = no real content)
  local line_count
  line_count=$(wc -l < "$transcript_path" 2>/dev/null || echo "0")
  if [ "$line_count" -lt 3 ]; then
    rm -f "$pending"
    return 0
  fi

  # Parse transcript into concise text
  local parsed
  parsed=$("$HOOKS_DIR/parse-transcript.sh" "$transcript_path" 2>/dev/null || true)
  if [ -z "$parsed" ] || [ "$parsed" = "(empty transcript)" ]; then
    rm -f "$pending"
    return 0
  fi

  # Extract session ID and last user turn UUID for progressive disclosure anchors
  local session_id last_turn_uuid
  session_id=$(basename "$pending")
  last_turn_uuid=$(python3 -c "
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
" "$transcript_path" 2>/dev/null || true)

  # Summarize with claude -p (model configurable via MEMSEARCH_SUMMARY_MODEL)
  local summary_model="${MEMSEARCH_SUMMARY_MODEL:-haiku}"
  local summary=""
  if command -v claude &>/dev/null; then
    summary=$(printf '%s' "$parsed" | claude -p \
      --model "$summary_model" \
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

  # Fallback to raw parsed output if claude unavailable or returned empty
  if [ -z "$summary" ]; then
    summary="$parsed"
  fi

  # Append to daily .md
  local now memory_file
  now=$(date +%H:%M)
  memory_file="$MEMORY_DIR/${target_date}.md"

  ensure_memory_dir
  {
    echo "### $now"
    echo "<!-- session:${session_id} turn:${last_turn_uuid} transcript:${transcript_path} -->"
    echo "$summary"
    echo ""
  } >> "$memory_file"

  rm -f "$pending"
}

# Flush all pending sessions: summarize each and re-index.
flush_pending() {
  [ -d "$PENDING_DIR" ] || return 0

  # Check embedding API key — skip if missing (indexing would fail anyway)
  if ! _check_embedding_key; then
    # Clean up pending files since we can't process them
    rm -rf "$PENDING_DIR"
    return 0
  fi

  local flushed=false
  for pending in "$PENDING_DIR"/*; do
    [ -f "$pending" ] || continue
    _summarize_pending "$pending"
    flushed=true
  done

  # Re-index after flushing so memories become searchable immediately
  if [ "$flushed" = true ]; then
    run_memsearch index "$MEMORY_DIR"
  fi

  # Clean up empty pending dir
  rmdir "$PENDING_DIR" 2>/dev/null || true
}
