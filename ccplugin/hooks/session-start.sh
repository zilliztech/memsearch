#!/usr/bin/env bash
# SessionStart hook: start watch singleton + inject recent memory context.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Bootstrap: if memsearch not available, install uv and warm up uvx cache
if [ -z "$MEMSEARCH_CMD" ]; then
  if ! command -v uvx &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null
    export PATH="$HOME/.local/bin:$PATH"
  fi
  # Warm up uvx cache with --upgrade to pull latest version
  # First run downloads packages (~2s); subsequent runs use cache (<0.3s)
  uvx --upgrade memsearch --version &>/dev/null || true
  _detect_memsearch
fi

# Read resolved config and version for status display
PROVIDER="openai"; MODEL=""; MILVUS_URI=""; VERSION=""
if [ -n "$MEMSEARCH_CMD" ]; then
  PROVIDER=$($MEMSEARCH_CMD config get embedding.provider 2>/dev/null || echo "openai")
  MODEL=$($MEMSEARCH_CMD config get embedding.model 2>/dev/null || echo "")
  MILVUS_URI=$($MEMSEARCH_CMD config get milvus.uri 2>/dev/null || echo "")
  # "memsearch, version 0.1.10" → "0.1.10"
  VERSION=$($MEMSEARCH_CMD --version 2>/dev/null | sed 's/.*version //' || echo "")
fi

# Determine required API key for the configured provider
_required_env_var() {
  case "$1" in
    openai) echo "OPENAI_API_KEY" ;;
    google) echo "GOOGLE_API_KEY" ;;
    voyage) echo "VOYAGE_API_KEY" ;;
    *) echo "" ;;  # ollama, local — no API key needed
  esac
}
REQUIRED_KEY=$(_required_env_var "$PROVIDER")

KEY_MISSING=false
if [ -n "$REQUIRED_KEY" ] && [ -z "${!REQUIRED_KEY:-}" ]; then
  KEY_MISSING=true
fi

# Check PyPI for newer version (2s timeout, non-blocking on failure)
UPDATE_HINT=""
if [ -n "$VERSION" ]; then
  LATEST=$(curl -s --max-time 2 https://pypi.org/pypi/memsearch/json 2>/dev/null \
    | jq -r '.info.version // empty' 2>/dev/null || true)
  if [ -n "$LATEST" ] && [ "$LATEST" != "$VERSION" ]; then
    UPDATE_HINT=" | UPDATE: v${LATEST} available"
  fi
fi

# Build status line: version | provider/model | milvus | optional update/error
VERSION_TAG="${VERSION:+ v${VERSION}}"
status="[memsearch${VERSION_TAG}] embedding: ${PROVIDER}/${MODEL:-unknown} | milvus: ${MILVUS_URI:-unknown}${UPDATE_HINT}"
if [ "$KEY_MISSING" = true ]; then
  status+=" | ERROR: ${REQUIRED_KEY} not set — memory search disabled"
fi

# Write session heading to today's memory file
ensure_memory_dir
TODAY=$(date +%Y-%m-%d)
NOW=$(date +%H:%M)
MEMORY_FILE="$MEMORY_DIR/$TODAY.md"
echo -e "\n## Session $NOW\n" >> "$MEMORY_FILE"

# If API key is missing, show status and exit early (watch/search would fail)
if [ "$KEY_MISSING" = true ]; then
  json_status=$(printf '%s' "$status" | jq -Rs .)
  echo "{\"systemMessage\": $json_status}"
  exit 0
fi

# Start memsearch watch as a singleton background process.
# This is the ONLY place indexing is managed — all other hooks just write .md files.
start_watch

# Always include status in systemMessage
json_status=$(printf '%s' "$status" | jq -Rs .)

# If memory dir has no .md files (other than the one we just created), nothing to inject
if [ ! -d "$MEMORY_DIR" ] || ! ls "$MEMORY_DIR"/*.md &>/dev/null; then
  echo "{\"systemMessage\": $json_status}"
  exit 0
fi

context=""

# Find the 2 most recent daily log files (sorted by filename descending)
recent_files=$(ls -1 "$MEMORY_DIR"/*.md 2>/dev/null | sort -r | head -2)

if [ -n "$recent_files" ]; then
  context="# Recent Memory\n\n"
  for f in $recent_files; do
    basename_f=$(basename "$f")
    # Read last ~30 lines from each file
    content=$(tail -30 "$f" 2>/dev/null || true)
    if [ -n "$content" ]; then
      context+="## $basename_f\n$content\n\n"
    fi
  done
fi

# Note: Detailed memory search is handled by the memory-recall skill (pull-based).
# The cold-start context above gives Claude enough awareness of recent sessions
# to decide when to invoke the skill for deeper recall.

if [ -n "$context" ]; then
  json_context=$(printf '%s' "$context" | jq -Rs .)
  echo "{\"systemMessage\": $json_status, \"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": $json_context}}"
else
  echo "{\"systemMessage\": $json_status}"
fi
