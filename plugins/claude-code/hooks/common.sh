#!/usr/bin/env bash
# Shared setup for memsearch command hooks.
# Sourced by all hook scripts — not executed directly.

set -euo pipefail

# Internal maintenance/summarization subprocesses may invoke Claude Code again.
# When they do, the child process must not run memsearch hooks, or it can write
# empty nested session headings and keep maintenance inputs changing forever.
if [ "${MEMSEARCH_DISABLE:-}" = "1" ]; then
  echo '{}'
  exit 0
fi

# Read stdin JSON into $INPUT
# Use timeout to prevent indefinite blocking in WSL 2 where stdin pipe may not close properly.
# macOS lacks `timeout` — use perl alarm(2) as a portable fallback with a 2-second deadline.
if command -v timeout &>/dev/null; then
  INPUT="$(timeout 2 cat 2>/dev/null || echo '{}')"
else
  INPUT="$(perl -e 'alarm 2; local $/; $_ = <STDIN>; print if defined' 2>/dev/null || echo '{}')"
fi

# Ensure common user bin paths are in PATH (hooks may run in a minimal env)
for p in "$HOME/.local/bin" "$HOME/.cargo/bin" "$HOME/bin" "/usr/local/bin"; do
  [[ -d "$p" ]] && [[ ":$PATH:" != *":$p:"* ]] && export PATH="$p:$PATH"
done

# Memory directory and memsearch state directory are project-scoped.
# Prefer git root to avoid .memsearch scattered in subdirectories when
# CLAUDE_PROJECT_DIR is unset (child claude -p) or points to a subdir.
_GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
if [ -n "$_GIT_ROOT" ]; then
  _PROJECT_DIR="$_GIT_ROOT"
else
  _PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
fi
# When MEMSEARCH_DIR is explicitly set, use global scope (shared dir + collection).
# Otherwise, default to per-project isolation.
_MEMSEARCH_DIR_EXPLICIT="${MEMSEARCH_DIR:+true}"
MEMSEARCH_DIR="${MEMSEARCH_DIR:-$_PROJECT_DIR/.memsearch}"
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

# Derive collection name: from MEMSEARCH_DIR when explicitly set (global scope),
# otherwise from project directory (per-project isolation).
if [ "$_MEMSEARCH_DIR_EXPLICIT" = "true" ]; then
  COLLECTION_NAME=$("$(dirname "${BASH_SOURCE[0]}")/../scripts/derive-collection.sh" "$MEMSEARCH_DIR" 2>/dev/null || true)
else
  COLLECTION_NAME=$("$(dirname "${BASH_SOURCE[0]}")/../scripts/derive-collection.sh" "$_PROJECT_DIR" 2>/dev/null || true)
fi

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
    result=$(printf '%s' "$json" | python3 -c "
import json, sys
try:
    obj = json.load(sys.stdin)
    val = obj
    for k in sys.argv[1].split('.'):
        val = val[k]
    if val is None:
        print('')
    elif isinstance(val, bool):
        print(str(val).lower())
    else:
        print(val)
except Exception:
    print('')
" "$key" 2>/dev/null) || true
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

# _resolve_symlinks <path>
# Follow a symlink chain to its target without `readlink -f`, which BSD
# readlink (macOS) does not support. Relative link targets resolve against
# the link's directory; a hop cap guards against cycles. The directory part
# is canonicalized with `pwd -P` so `..` segments and directory symlinks
# collapse the way GNU `readlink -f` would collapse them.
_resolve_symlinks() {
  local target="$1" link dir hops=0
  while [ -L "$target" ] && [ "$hops" -lt 40 ]; do
    link=$(readlink "$target" 2>/dev/null) || break
    case "$link" in
      /*) target="$link" ;;
      *) target="$(dirname "$target")/$link" ;;
    esac
    hops=$((hops + 1))
  done
  dir=$(cd "$(dirname "$target")" 2>/dev/null && pwd -P) || { printf '%s' "$target"; return 0; }
  printf '%s/%s' "$dir" "${target##*/}"
}

# Resolve the installed memsearch version from its dist-info directory name.
# Callers already spend one CLI start reading config; asking the CLI for
# `--version` spawns a second Python interpreter (~0.3s warm, several seconds
# cold) purely to render a status string. Prints nothing when no dist-info is
# discoverable (uvx, editable installs) so callers can fall back to the CLI.
_installed_version_from_dist_info() {
  local bin real candidate
  bin=$(command -v memsearch 2>/dev/null) || return 0
  [ -n "$bin" ] || return 0
  real=$(_resolve_symlinks "$bin")
  for candidate in "${real%/bin/memsearch}"/lib/python*/site-packages/memsearch-*.dist-info; do
    [ -d "$candidate" ] || continue
    candidate=${candidate##*/memsearch-}
    candidate=${candidate%.dist-info}
    # Require a version-shaped string so a sibling distribution whose name
    # starts with "memsearch-" cannot be mistaken for the package itself.
    case "$candidate" in
      [0-9]*) printf '%s' "$candidate"; return 0 ;;
    esac
  done
}

# Parse the supported suffixes into their public-version order. Local labels
# are handled separately because a public index must not advertise the same
# public version as an upgrade over an installed local build.
_version_suffix_key() {
  local suffix="${1#.}" number
  case "$suffix" in
    "") _VERSION_SUFFIX_RANK=4; _VERSION_SUFFIX_NUMBER=0; return 0 ;;
    dev*) _VERSION_SUFFIX_RANK=0; number=${suffix#dev} ;;
    a*) _VERSION_SUFFIX_RANK=1; number=${suffix#a} ;;
    b*) _VERSION_SUFFIX_RANK=2; number=${suffix#b} ;;
    rc*) _VERSION_SUFFIX_RANK=3; number=${suffix#rc} ;;
    post*) _VERSION_SUFFIX_RANK=5; number=${suffix#post} ;;
    *) return 1 ;;
  esac
  case "$number" in ""|*[!0-9]*) return 1 ;; esac
  [ "${#number}" -le 9 ] || return 1
  _VERSION_SUFFIX_NUMBER=$((10#$number))
}

# True when the first version is strictly newer than the second. Release fields
# compare numerically; dev, a, b, rc, final, and post suffixes follow that order.
# Local labels are ignored after validating their shape. Unknown versions stay
# silent because guessing their order could emit a downgrade hint.
_version_gt() {
  local a="$1" b="$2" a_local="" b_local="" a_release b_release a_suffix b_suffix
  local ax bx a_rank b_rank a_number b_number local_part

  case "$a" in *+*) a_local=${a#*+}; a=${a%%+*} ;; esac
  case "$b" in *+*) b_local=${b#*+}; b=${b%%+*} ;; esac
  for local_part in "$a_local" "$b_local"; do
    case "$local_part" in *[!A-Za-z0-9._-]*) return 1 ;; esac
  done
  [ "$1" = "$a" ] || [ -n "$a_local" ] || return 1
  [ "$2" = "$b" ] || [ -n "$b_local" ] || return 1

  a_release=${a%%[!0-9.]*}
  b_release=${b%%[!0-9.]*}
  case "$a_release" in *.) [ "$a" != "$a_release" ] || return 1; a_release=${a_release%.} ;; esac
  case "$b_release" in *.) [ "$b" != "$b_release" ] || return 1; b_release=${b_release%.} ;; esac
  case "$a_release" in ""|.*|*.|*..*|*[!0-9.]*) return 1 ;; esac
  case "$b_release" in ""|.*|*.|*..*|*[!0-9.]*) return 1 ;; esac
  a_suffix=${a#$a_release}
  b_suffix=${b#$b_release}

  _version_suffix_key "$a_suffix" || return 1
  a_rank=$_VERSION_SUFFIX_RANK
  a_number=$_VERSION_SUFFIX_NUMBER
  _version_suffix_key "$b_suffix" || return 1
  b_rank=$_VERSION_SUFFIX_RANK
  b_number=$_VERSION_SUFFIX_NUMBER

  while [ -n "$a_release" ] || [ -n "$b_release" ]; do
    ax=${a_release%%.*}
    bx=${b_release%%.*}
    [ "${#ax}" -le 9 ] && [ "${#bx}" -le 9 ] || return 1
    # 10# forces base ten so a zero-padded field is not read as octal.
    ax=$((10#${ax:-0}))
    bx=$((10#${bx:-0}))
    [ "$ax" -gt "$bx" ] && return 0
    [ "$ax" -lt "$bx" ] && return 1
    case "$a_release" in *.*) a_release=${a_release#*.} ;; *) a_release="" ;; esac
    case "$b_release" in *.*) b_release=${b_release#*.} ;; *) b_release="" ;; esac
  done

  [ "$a_rank" -gt "$b_rank" ] && return 0
  [ "$a_rank" -lt "$b_rank" ] && return 1
  [ "$a_number" -gt "$b_number" ]
}

# Latest memsearch version on PyPI, cached for 24h and refreshed off the
# blocking path. Keeps the update hint current without making any session start
# wait on a network round trip: a cache older than a day is still printed, and
# the refresh runs in a detached child, so the hint is at most one session
# stale. Prints nothing until the first lookup has answered.
_pypi_latest_version() {
  local cache="$HOME/.memsearch/.pypi-latest" last
  # A cache file younger than a day is authoritative even when it is empty: an
  # empty file records a lookup that failed, so an offline machine stops
  # re-paying the curl timeout on every session start.
  if [ -n "$(find "$cache" -mtime -1 2>/dev/null)" ]; then
    cat "$cache" 2>/dev/null || true
    return 0
  fi
  last=$(cat "$cache" 2>/dev/null || true)
  mkdir -p "$(dirname "$cache")" 2>/dev/null || true
  # Only an answer marks the cache fresh: the child's mv is the sole writer of
  # both the contents and the mtime. That keeps the sentence above true -- an
  # empty fresh file records a lookup that ran and failed, never one that was
  # merely started -- and a refresh that dies leaves the previous answer for the
  # next start to retry. Concurrent starts may each spawn a lookup; off the
  # blocking path that costs the session start nothing.
  # Both fds must be redirected. The hook runner keeps a pipe on the hook's
  # stderr, so `child >/dev/null &` still holds the session start open until the
  # child exits (measured in #676). Same form as the Lite-mode index subshell.
  (
    local json latest tmp="$cache.$$"
    json=$(curl -s --max-time 2 https://pypi.org/pypi/memsearch/json 2>/dev/null || true)
    latest=$(_json_val "$json" "info.version" "")
    if printf '%s' "$latest" > "$tmp" 2>/dev/null; then
      mv -f "$tmp" "$cache" 2>/dev/null || true
    fi
    rm -f "$tmp" 2>/dev/null || true
  ) </dev/null >/dev/null 2>&1 &
  printf '%s' "$last"
}

# Return a concise user-facing warning when the persisted index state says
# search may be stale. Detailed diagnosis stays in the memory-config skill.
index_state_warning() {
  local state_path="$MEMSEARCH_DIR/.index-state.json"
  [ -f "$state_path" ] || return 0
  python3 - "$state_path" <<'PY' 2>/dev/null || true
import json
import sys
from datetime import datetime, timezone

try:
    state = json.loads(open(sys.argv[1], encoding="utf-8").read())
except Exception:
    raise SystemExit(0)

status = state.get("status")
if status in {"error", "degraded"}:
    print("WARNING: memory index may be stale; run the memory-config skill to diagnose")
    raise SystemExit(0)

if status == "running":
    raw_started = state.get("last_started_at")
    try:
        started = datetime.fromisoformat(str(raw_started).replace("Z", "+00:00"))
    except Exception:
        raise SystemExit(0)
    if datetime.now(timezone.utc).timestamp() - started.timestamp() > 3600:
        print("WARNING: memory index has been running for over 1h; run the memory-config skill to diagnose")
PY
}

skill_candidate_hint() {
  [ -n "$MEMSEARCH_CMD" ] || return 0
  [ -d "$MEMSEARCH_DIR/skill-candidates" ] || return 0
  MEMSEARCH_DIR="$MEMSEARCH_DIR" $MEMSEARCH_CMD skills status --hint 2>/dev/null || true
}

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

run_maintenance() {
  if command -v python3 >/dev/null 2>&1; then
    MEMSEARCH_NO_WATCH=1 python3 "$SCRIPT_DIR/../scripts/maintenance-runner.py" \
      --platform claude-code \
      --project-dir "$_PROJECT_DIR" \
      --memsearch-dir "$MEMSEARCH_DIR" \
      >/dev/null 2>&1 || true
  fi
}

# --- Index process cleanup ---

INDEX_PIDFILE="$MEMSEARCH_DIR/.index.pid"

# Kill any previously spawned background index processes for this project.
# Also sweeps orphaned milvus_lite processes, which outlive `memsearch index`
# in Lite mode because milvus_lite does not exit when its parent process ends.
#
# Without this cleanup, rapid session open/close cycles (e.g. when Claude Code
# freezes on startup and the user force-quits) accumulate dozens of orphaned
# python/milvus processes that can consume tens of GB of virtual memory and
# cause subsequent sessions to freeze due to resource exhaustion.
kill_orphaned_index() {
  # Skip in child claude -p processes to avoid killing the current parent's work
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
  # Kill the process group (negative PID) to catch child processes
  kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
}

# Stop the watch process: pidfile first, then sweep for orphans
stop_watch() {
  # Skip watch management in child claude -p processes (e.g. stop.sh summarization)
  if [ "${MEMSEARCH_NO_WATCH:-}" = "1" ]; then
    return 0
  fi
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
  # Skip watch management in child claude -p processes (e.g. stop.sh summarization)
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
