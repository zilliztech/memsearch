#!/usr/bin/env bash
# Shared setup for memsearch Codex CLI hooks.
# Sourced by all hook scripts — not executed directly.

set -euo pipefail

# Read stdin JSON into $INPUT
# Use timeout to prevent indefinite blocking when stdin pipe may not close properly
INPUT="$(timeout 2 cat 2>/dev/null || echo '{}')"

# Ensure common user bin paths are in PATH (hooks may run in a minimal env)
for p in "$HOME/.local/bin" "$HOME/.cargo/bin" "$HOME/bin" "/usr/local/bin"; do
  [[ -d "$p" ]] && [[ ":$PATH:" != *":$p:"* ]] && export PATH="$p:$PATH"
done

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

# --- Project directory (from stdin JSON cwd field, fallback to pwd) ---

PROJECT_DIR=$(_json_val "$INPUT" "cwd" "$(pwd)")

# Memory directory and memsearch state directory are project-scoped
MEMSEARCH_DIR="${MEMSEARCH_DIR:-${PROJECT_DIR}/.memsearch}"
MEMORY_DIR="$MEMSEARCH_DIR/memory"

# Find memsearch binary: prefer PATH, fallback to uvx
_detect_memsearch() {
  MEMSEARCH_CMD=""
  if command -v memsearch &>/dev/null; then
    MEMSEARCH_CMD="memsearch"
  elif command -v uvx &>/dev/null; then
    MEMSEARCH_CMD="uvx --from memsearch[onnx] memsearch"
  fi
}
_detect_memsearch

# Short command prefix for injected instructions (falls back to "memsearch" even if unavailable)
MEMSEARCH_CMD_PREFIX="${MEMSEARCH_CMD:-memsearch}"

# Derive per-project collection name from project directory
COLLECTION_NAME=$("$(dirname "${BASH_SOURCE[0]}")/../scripts/derive-collection.sh" "$PROJECT_DIR" 2>/dev/null || true)

# Helper: ensure memory directory exists
ensure_memory_dir() {
  mkdir -p "$MEMORY_DIR"
}

# Collection description (set by session-start.sh, empty by default)
COLLECTION_DESC=""

# Helper: run memsearch with arguments, silently fail if not available
run_memsearch() {
  if [ -n "$MEMSEARCH_CMD" ] && [ -n "$COLLECTION_NAME" ]; then
    $MEMSEARCH_CMD "$@" --collection "$COLLECTION_NAME" ${COLLECTION_DESC:+--description "$COLLECTION_DESC"} 2>/dev/null || true
  elif [ -n "$MEMSEARCH_CMD" ]; then
    $MEMSEARCH_CMD "$@" ${COLLECTION_DESC:+--description "$COLLECTION_DESC"} 2>/dev/null || true
  fi
}

# --- Index process cleanup ---

INDEX_PIDFILE="$MEMSEARCH_DIR/.index.pid"

# Kill any previously spawned background index processes for this project.
# Also sweeps orphaned milvus_lite processes.
kill_orphaned_index() {
  # Skip in child codex exec processes to avoid killing the parent's work
  if [ "${MEMSEARCH_NO_WATCH:-}" = "1" ]; then
    return 0
  fi

  # 1. Kill PID recorded from previous background index launch
  if [ -f "$INDEX_PIDFILE" ]; then
    local pid
    pid=$(cat "$INDEX_PIDFILE" 2>/dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$INDEX_PIDFILE"
  fi

  # 2. Sweep any orphaned memsearch index processes for this MEMORY_DIR
  local orphans
  orphans=$(pgrep -f "memsearch index $MEMORY_DIR" 2>/dev/null || true)
  if [ -n "$orphans" ]; then
    echo "$orphans" | while read -r opid; do
      kill "$opid" 2>/dev/null || true
    done
  fi

  # 3. Kill orphaned milvus_lite processes (they don't exit when memsearch index exits)
  orphans=$(pgrep -f "milvus_lite/lib/milvus" 2>/dev/null || true)
  if [ -n "$orphans" ]; then
    echo "$orphans" | while read -r opid; do
      kill "$opid" 2>/dev/null || true
    done
  fi
}

# --- Watch singleton management ---

WATCH_PIDFILE="$MEMSEARCH_DIR/.watch.pid"

# Kill a process and its entire process group to avoid orphans
_kill_tree() {
  local pid="$1"
  kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
}

# Stop the watch process: pidfile first, then sweep for orphans
stop_watch() {
  if [ "${MEMSEARCH_NO_WATCH:-}" = "1" ]; then
    return 0
  fi
  if [ -f "$WATCH_PIDFILE" ]; then
    local pid
    pid=$(cat "$WATCH_PIDFILE" 2>/dev/null)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      _kill_tree "$pid"
    fi
    rm -f "$WATCH_PIDFILE"
  fi

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
  if [ "${MEMSEARCH_NO_WATCH:-}" = "1" ]; then
    return 0
  fi
  if [ -z "$MEMSEARCH_CMD" ]; then
    return 0
  fi
  ensure_memory_dir

  # Always restart: ensures latest config (milvus_uri, etc.) is used
  stop_watch

  # Detect Milvus backend from URI
  local _uri="${MILVUS_URI:-$($MEMSEARCH_CMD config get milvus.uri 2>/dev/null || echo "")}"

  # Lite (local .db): skip watch entirely — file lock prevents concurrent access.
  # Session-start does a one-time index() instead.
  if [[ "$_uri" != http* ]] && [[ "$_uri" != tcp* ]]; then
    return 0
  fi

  # Server (http/tcp): setsid — watch runs persistently for real-time indexing.
  local launch_prefix="nohup"
  command -v setsid &>/dev/null && launch_prefix="setsid"

  if [ -n "$COLLECTION_NAME" ]; then
    $launch_prefix $MEMSEARCH_CMD watch "$MEMORY_DIR" --collection "$COLLECTION_NAME" ${COLLECTION_DESC:+--description "$COLLECTION_DESC"} </dev/null &>/dev/null &
  else
    $launch_prefix $MEMSEARCH_CMD watch "$MEMORY_DIR" ${COLLECTION_DESC:+--description "$COLLECTION_DESC"} </dev/null &>/dev/null &
  fi
  echo $! > "$WATCH_PIDFILE"
}

# --- Orphan cleanup (called at session start since Codex has no SessionEnd hook) ---

cleanup_orphaned_processes() {
  # Clean up stale PID files from previous sessions that didn't get a clean shutdown.
  # Since Codex has no SessionEnd hook, we rely on this at next session start.
  if [ -f "$WATCH_PIDFILE" ]; then
    local pid
    pid=$(cat "$WATCH_PIDFILE" 2>/dev/null || true)
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$WATCH_PIDFILE"
    fi
  fi
  if [ -f "$INDEX_PIDFILE" ]; then
    local pid
    pid=$(cat "$INDEX_PIDFILE" 2>/dev/null || true)
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$INDEX_PIDFILE"
    fi
  fi
}
