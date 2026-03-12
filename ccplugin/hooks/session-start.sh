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
  # Before declaring key missing, check if the config file provides an API key
  # (supports both literal keys and "env:VAR_NAME" references).
  CONFIG_API_KEY=""
  if [ -n "$MEMSEARCH_CMD" ]; then
    CONFIG_API_KEY=$($MEMSEARCH_CMD config get embedding.api_key 2>/dev/null || true)
  fi
  if [ -z "$CONFIG_API_KEY" ]; then
    KEY_MISSING=true
  fi
fi

# Check PyPI for newer version (2s timeout, non-blocking on failure)
UPDATE_HINT=""
if [ -n "$VERSION" ]; then
  _PYPI_JSON=$(curl -s --max-time 2 https://pypi.org/pypi/memsearch/json 2>/dev/null || true)
  LATEST=$(_json_val "$_PYPI_JSON" "info.version" "")
  if [ -n "$LATEST" ] && [ "$LATEST" != "$VERSION" ]; then
    # Detect install method to suggest the right upgrade command
    if [ "$MEMSEARCH_CMD" = "uvx memsearch" ]; then
      UPGRADE_CMD="uvx --upgrade memsearch --version"
    else
      _MS_PATH=$(command -v memsearch 2>/dev/null || true)
      if [[ "$_MS_PATH" == *"uv/tools"* ]]; then
        UPGRADE_CMD="uv tool upgrade memsearch"
      else
        UPGRADE_CMD="pip install --upgrade memsearch"
      fi
    fi
    UPDATE_HINT=" | UPDATE: v${LATEST} available — run: ${UPGRADE_CMD}"
  fi
fi

# Build status line: version | provider/model | milvus | optional update/error
VERSION_TAG="${VERSION:+ v${VERSION}}"
COLLECTION_HINT=""
if [ -n "$COLLECTION_NAME" ]; then
  COLLECTION_HINT=" | collection: ${COLLECTION_NAME}"
fi
status="[memsearch${VERSION_TAG}] embedding: ${PROVIDER}/${MODEL:-unknown} | milvus: ${MILVUS_URI:-unknown}${COLLECTION_HINT}${UPDATE_HINT}"
if [ "$KEY_MISSING" = true ]; then
  status+=" | ERROR: ${REQUIRED_KEY} not set — memory search disabled"
fi

# Build collection description: "<project_basename> | <provider>/<model>"
PROJECT_BASENAME=$(basename "${CLAUDE_PROJECT_DIR:-.}")
COLLECTION_DESC="${PROJECT_BASENAME} | ${PROVIDER}/${MODEL:-default}"

# Write session heading to today's memory file
ensure_memory_dir
TODAY=$(date +%Y-%m-%d)
NOW=$(date +%H:%M)
MEMORY_FILE="$MEMORY_DIR/$TODAY.md"
if [ ! -f "$MEMORY_FILE" ] || ! grep -qF "## Session $NOW" "$MEMORY_FILE"; then
  echo -e "\n## Session $NOW\n" >> "$MEMORY_FILE"
fi

# If API key is missing, show status and exit early (watch/search would fail)
if [ "$KEY_MISSING" = true ]; then
  json_status=$(_json_encode_str "$status")
  echo "{\"systemMessage\": $json_status}"
  exit 0
fi

# Start memsearch watch (Server mode) or do one-time index (Lite mode).
# start_watch() skips watch for Lite — file lock prevents concurrent access.
start_watch

# Lite mode: one-time index since watch is not running
if [[ "$MILVUS_URI" != http* ]] && [[ "$MILVUS_URI" != tcp* ]]; then
  run_memsearch index "$MEMORY_DIR" &>/dev/null &
fi

# Always include status in systemMessage
json_status=$(_json_encode_str "$status")

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
  json_context=$(_json_encode_str "$context")
  echo "{\"systemMessage\": $json_status, \"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": $json_context}}"
else
  echo "{\"systemMessage\": $json_status}"
fi
