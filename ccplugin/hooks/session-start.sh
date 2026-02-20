#!/usr/bin/env bash
# SessionStart hook — bootstrap memsearch, inject recent memory context.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

# --- Auto-install via uvx if memsearch is not on PATH ----------------------

if [ -z "$MEMSEARCH_CMD" ]; then
  if ! command -v uvx &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null
    export PATH="$HOME/.local/bin:$PATH"
  fi
  uvx --upgrade memsearch --version &>/dev/null || true
  _detect_memsearch
fi

# --- Resolve config for status line ----------------------------------------

PROVIDER="openai"
MODEL=""
MILVUS_URI=""
VERSION=""
if [ -n "$MEMSEARCH_CMD" ]; then
  PROVIDER=$($MEMSEARCH_CMD config get embedding.provider 2>/dev/null || echo "openai")
  MODEL=$($MEMSEARCH_CMD config get embedding.model 2>/dev/null || echo "")
  MILVUS_URI=$($MEMSEARCH_CMD config get milvus.uri 2>/dev/null || echo "")
  VERSION=$($MEMSEARCH_CMD --version 2>/dev/null | sed 's/.*version //' || echo "")
fi

# --- Check required API key ------------------------------------------------

_required_env_var() {
  case "$1" in
    openai) echo "OPENAI_API_KEY" ;;
    google) echo "GOOGLE_API_KEY" ;;
    voyage) echo "VOYAGE_API_KEY" ;;
    *) echo "" ;;
  esac
}
REQUIRED_KEY=$(_required_env_var "$PROVIDER")

KEY_MISSING=false
if [ -n "$REQUIRED_KEY" ] && [ -z "${!REQUIRED_KEY:-}" ]; then
  KEY_MISSING=true
fi

# --- Check for newer version on PyPI (non-blocking, 2 s timeout) ----------

UPDATE_HINT=""
if [ -n "$VERSION" ]; then
  _PYPI_JSON=$(curl -s --max-time 2 https://pypi.org/pypi/memsearch/json 2>/dev/null || true)
  LATEST=$(_json_val "$_PYPI_JSON" "info.version" "")
  if [ -n "$LATEST" ] && [ "$LATEST" != "$VERSION" ]; then
    UPDATE_HINT=" | UPDATE: v${LATEST} available"
  fi
fi

# --- Build status line -----------------------------------------------------

VERSION_TAG="${VERSION:+ v${VERSION}}"
status="[memsearch${VERSION_TAG}] embedding: ${PROVIDER}/${MODEL:-unknown} | milvus: ${MILVUS_URI:-unknown}${UPDATE_HINT}"
[ "$KEY_MISSING" = true ] && status+=" | ERROR: ${REQUIRED_KEY} not set — memory search disabled"

# --- Flush pending summaries from previous (possibly crashed) sessions -----

ensure_memory_dir
flush_pending

# --- Write session heading -------------------------------------------------

TODAY=$(date +%Y-%m-%d)
NOW=$(date +%H:%M)
MEMORY_FILE="$MEMORY_DIR/$TODAY.md"
echo -e "\n## Session $NOW\n" >>"$MEMORY_FILE"

# Early exit when the API key is missing — watch and search would fail.
if [ "$KEY_MISSING" = true ]; then
  json_status=$(_json_encode_str "$status")
  echo "{\"systemMessage\": $json_status}"
  exit 0
fi

# --- Start the file watcher ------------------------------------------------

start_watch

# --- Inject cold-start context (last 2 daily logs) -------------------------

json_status=$(_json_encode_str "$status")

if [ ! -d "$MEMORY_DIR" ] || ! ls "$MEMORY_DIR"/*.md &>/dev/null; then
  echo "{\"systemMessage\": $json_status}"
  exit 0
fi

context=""
recent_files=$(ls -1 "$MEMORY_DIR"/*.md 2>/dev/null | sort -r | head -2)
if [ -n "$recent_files" ]; then
  context="# Recent Memory\n\n"
  for f in $recent_files; do
    content=$(tail -30 "$f" 2>/dev/null || true)
    if [ -n "$content" ]; then
      context+="## $(basename "$f")\n$content\n\n"
    fi
  done
fi

# Full memory search is handled by the memory-recall skill (pull-based).
# This cold-start snippet gives Claude enough awareness to decide when
# to invoke that skill for deeper recall.
if [ -n "$context" ]; then
  json_context=$(_json_encode_str "$context")
  echo "{\"systemMessage\": $json_status, \"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": $json_context}}"
else
  echo "{\"systemMessage\": $json_status}"
fi
