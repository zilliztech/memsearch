#!/usr/bin/env bash
# common.sh — shared utilities for all memsearch hooks.
# Sourced (not executed) by every hook script.

set -euo pipefail

# shellcheck disable=SC2034  # INPUT is read by scripts that source this file.
INPUT="$(cat)"

# Hooks may run in a minimal environment; ensure common bin paths are available.
for p in "$HOME/.local/bin" "$HOME/.cargo/bin" "$HOME/bin" "/usr/local/bin"; do
  [[ -d "$p" ]] && [[ ":$PATH:" != *":$p:"* ]] && export PATH="$p:$PATH"
done

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMSEARCH_DIR="${CLAUDE_PROJECT_DIR:-.}/.memsearch"
MEMORY_DIR="$MEMSEARCH_DIR/memory"
PENDING_DIR="$MEMSEARCH_DIR/.pending"
WATCH_PIDFILE="$MEMSEARCH_DIR/.watch.pid"

# ---------------------------------------------------------------------------
# memsearch binary detection
# ---------------------------------------------------------------------------

_detect_memsearch() {
  MEMSEARCH_CMD=""
  if command -v memsearch &>/dev/null; then
    MEMSEARCH_CMD="memsearch"
  elif command -v uvx &>/dev/null; then
    MEMSEARCH_CMD="uvx memsearch"
  fi
}
_detect_memsearch

# Used in injected instructions even when the binary is absent.
# shellcheck disable=SC2034
MEMSEARCH_CMD_PREFIX="${MEMSEARCH_CMD:-memsearch}"

# ---------------------------------------------------------------------------
# JSON helpers  (prefer jq, fall back to python3)
# ---------------------------------------------------------------------------

# _json_val <json> <dotted.key> [default]
# Extract a scalar value. Returns default (or "") on missing key / parse error.
_json_val() {
  local json="$1" key="$2" default="${3:-}"
  local result=""

  if command -v jq &>/dev/null; then
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

  printf '%s' "${result:-$default}"
  return 0
}

# _json_encode_str <string>
# Return a JSON-encoded string (with surrounding quotes).
_json_encode_str() {
  local str="$1"
  if command -v jq &>/dev/null; then
    printf '%s' "$str" | jq -Rs . 2>/dev/null && return 0
  fi
  printf '%s' "$str" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))" 2>/dev/null && return 0
  printf '"%s"' "$str"
  return 0
}

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

ensure_memory_dir() { mkdir -p "$MEMORY_DIR"; }

# Run memsearch silently; no-op when the binary is unavailable.
run_memsearch() {
  [ -n "$MEMSEARCH_CMD" ] && $MEMSEARCH_CMD "$@" 2>/dev/null || true
}

# Return 0 if the configured embedding provider's API key is set (or not required).
_check_embedding_key() {
  local provider
  provider=$($MEMSEARCH_CMD config get embedding.provider 2>/dev/null || echo "openai")
  local req_key=""
  case "$provider" in
    openai) req_key="OPENAI_API_KEY" ;;
    google) req_key="GOOGLE_API_KEY" ;;
    voyage) req_key="VOYAGE_API_KEY" ;;
    *) return 0 ;;
  esac
  [ -z "$req_key" ] || [ -n "${!req_key:-}" ]
}

# ---------------------------------------------------------------------------
# Watch process management  (singleton per project)
# ---------------------------------------------------------------------------

_kill_tree() {
  local pid="$1"
  kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
}

stop_watch() {
  if [ -f "$WATCH_PIDFILE" ]; then
    local pid
    pid=$(cat "$WATCH_PIDFILE" 2>/dev/null)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && _kill_tree "$pid"
    rm -f "$WATCH_PIDFILE"
  fi
  # Sweep for orphaned watchers targeting the same directory.
  local orphans
  orphans=$(pgrep -f "memsearch watch $MEMORY_DIR" 2>/dev/null || true)
  if [ -n "$orphans" ]; then
    echo "$orphans" | while read -r opid; do kill "$opid" 2>/dev/null || true; done
  fi
}

# Always restart to pick up any config changes (uri, provider, etc.).
start_watch() {
  [ -z "$MEMSEARCH_CMD" ] && return 0
  ensure_memory_dir
  stop_watch
  # shellcheck disable=SC2086  # Intentional word splitting: MEMSEARCH_CMD may be "uvx memsearch".
  nohup $MEMSEARCH_CMD watch "$MEMORY_DIR" &>/dev/null &
  echo $! >"$WATCH_PIDFILE"
}

# ---------------------------------------------------------------------------
# Deferred summarization  (Stop-hook dedup)
#
# The Stop hook fires after every assistant turn, but we only need one summary
# per session. Stop records the transcript path in a lightweight state file
# (overwriting on each turn). The expensive work — parsing + LLM call —
# runs exactly once via flush_pending(), triggered by SessionEnd (or by
# SessionStart as a safety net for crashed sessions).
# ---------------------------------------------------------------------------

# Summarize one pending session and append the result to its daily .md.
_summarize_pending() {
  local pending="$1"
  [ -f "$pending" ] || return 0

  # State file format: line 1 = transcript path, line 2 = target date.
  local transcript_path target_date
  transcript_path=$(sed -n '1p' "$pending")
  target_date=$(sed -n '2p' "$pending")

  if [ -z "$transcript_path" ] || [ ! -f "$transcript_path" ] || [ -z "$target_date" ]; then
    rm -f "$pending"
    return 0
  fi

  local line_count
  line_count=$(wc -l <"$transcript_path" 2>/dev/null || echo "0")
  if [ "$line_count" -lt 3 ]; then
    rm -f "$pending"
    return 0
  fi

  local parsed
  parsed=$("$HOOKS_DIR/parse-transcript.sh" "$transcript_path" 2>/dev/null || true)
  if [ -z "$parsed" ] || [ "$parsed" = "(empty transcript)" ]; then
    rm -f "$pending"
    return 0
  fi

  # Extract metadata for the progressive-disclosure anchor.
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

  # Model is configurable via env var (default: haiku).
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

  # Fall back to raw parsed text when claude is unavailable.
  [ -z "$summary" ] && summary="$parsed"

  local now memory_file
  now=$(date +%H:%M)
  memory_file="$MEMORY_DIR/${target_date}.md"

  ensure_memory_dir
  {
    echo "### $now"
    echo "<!-- session:${session_id} turn:${last_turn_uuid} transcript:${transcript_path} -->"
    echo "$summary"
    echo ""
  } >>"$memory_file"

  rm -f "$pending"
}

# Process all pending state files, then re-index.
flush_pending() {
  [ -d "$PENDING_DIR" ] || return 0

  if ! _check_embedding_key; then
    rm -rf "$PENDING_DIR"
    return 0
  fi

  local flushed=false
  for pending in "$PENDING_DIR"/*; do
    [ -f "$pending" ] || continue
    _summarize_pending "$pending"
    flushed=true
  done

  [ "$flushed" = true ] && run_memsearch index "$MEMORY_DIR"
  rmdir "$PENDING_DIR" 2>/dev/null || true
}
