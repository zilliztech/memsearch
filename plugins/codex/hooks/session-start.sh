#!/usr/bin/env bash
# SessionStart hook: clean up orphans, start watch singleton, inject recent memory context.
# Codex-specific: handles "source" field (startup/resume/clear), no SessionEnd counterpart.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Clean up orphaned processes from previous sessions (no SessionEnd in Codex)
cleanup_orphaned_processes

# Extract session source (startup/resume/clear) — Codex-specific field
SESSION_SOURCE=$(_json_val "$INPUT" "source" "startup")

# Bootstrap: if memsearch not available, install uv and warm up uvx cache
if [ -z "$MEMSEARCH_CMD" ]; then
  if ! command -v uvx &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null
    export PATH="$HOME/.local/bin:$PATH"
  fi
  # Warm up uvx cache with --upgrade to pull latest version
  uvx --upgrade --from 'memsearch[onnx]' memsearch --version &>/dev/null || true
  _detect_memsearch
fi

# First-time setup: if no config file exists, default to onnx provider.
if [ -n "$MEMSEARCH_CMD" ]; then
  if [ ! -f "$HOME/.memsearch/config.toml" ] && [ ! -f "${PROJECT_DIR}/.memsearch.toml" ]; then
    $MEMSEARCH_CMD config set embedding.provider onnx 2>/dev/null || true
  fi
fi

# Read resolved config and version for status display
PROVIDER="onnx"; MODEL=""; MILVUS_URI=""; VERSION=""
if [ -n "$MEMSEARCH_CMD" ]; then
  PROVIDER=$($MEMSEARCH_CMD config get embedding.provider 2>/dev/null || echo "onnx")
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
    *) echo "" ;;  # onnx, ollama, local — no API key needed
  esac
}
REQUIRED_KEY=$(_required_env_var "$PROVIDER")

KEY_MISSING=false
if [ -n "$REQUIRED_KEY" ] && [ -z "${!REQUIRED_KEY:-}" ]; then
  # Env var not set — check if API key is configured in memsearch config file
  CONFIG_API_KEY=""
  if [ -n "$MEMSEARCH_CMD" ]; then
    CONFIG_API_KEY=$($MEMSEARCH_CMD config get embedding.api_key 2>/dev/null || echo "")
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
    if [[ "$MEMSEARCH_CMD" == *"uvx"* ]]; then
      UPGRADE_CMD="uvx --upgrade --from 'memsearch[onnx]' memsearch --version"
    else
      _MS_PATH=$(command -v memsearch 2>/dev/null || true)
      _MS_REAL=$(readlink -f "$_MS_PATH" 2>/dev/null \
        || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$_MS_PATH" 2>/dev/null \
        || echo "$_MS_PATH")
      if [[ "$_MS_REAL" == *"uv/tools"* ]]; then
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
  status+=" | Tip: switch to free local embedding: memsearch config set embedding.provider onnx && memsearch index --force"
fi

# Build collection description: "<project_basename> | <provider>/<model>"
PROJECT_BASENAME=$(basename "$PROJECT_DIR")
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
start_watch

# Lite mode: one-time index since watch is not running.
# Runs in background subshell to avoid blocking the hook.
if [[ "$MILVUS_URI" != http* ]] && [[ "$MILVUS_URI" != tcp* ]]; then
  kill_orphaned_index
  (
    _index_args=("$MEMORY_DIR")
    [ -n "$COLLECTION_NAME" ] && _index_args+=(--collection "$COLLECTION_NAME")
    [ -n "$COLLECTION_DESC" ] && _index_args+=(--description "$COLLECTION_DESC")
    INDEX_OUTPUT=$($MEMSEARCH_CMD index "${_index_args[@]}" 2>&1) || true
    if echo "$INDEX_OUTPUT" | grep -q "dimension mismatch"; then
      _reset_args=(--yes)
      [ -n "$COLLECTION_NAME" ] && _reset_args+=(--collection "$COLLECTION_NAME")
      $MEMSEARCH_CMD reset "${_reset_args[@]}" 2>/dev/null || true
      $MEMSEARCH_CMD index "${_index_args[@]}" 2>/dev/null || true
    fi
  ) >/dev/null 2>&1 &
  echo $! > "$INDEX_PIDFILE"
fi

# Always include status in systemMessage
json_status=$(_json_encode_str "$status")

# If memory dir has no .md files, nothing to inject
if [ ! -d "$MEMORY_DIR" ] || ! ls "$MEMORY_DIR"/*.md &>/dev/null; then
  echo "{\"systemMessage\": $json_status}"
  exit 0
fi

context=""

# Count memory entries for the hint
memory_count=$(ls -1 "$MEMORY_DIR"/*.md 2>/dev/null | wc -l)
if [ "$memory_count" -gt 0 ]; then
  # Get date range of memory files
  oldest=$(ls -1 "$MEMORY_DIR"/*.md 2>/dev/null | sort | head -1 | xargs basename .md 2>/dev/null | sed 's/\.md//')
  newest=$(ls -1 "$MEMORY_DIR"/*.md 2>/dev/null | sort -r | head -1 | xargs basename .md 2>/dev/null | sed 's/\.md//')
  context="You have ${memory_count} past memory file(s) (${oldest} to ${newest}). Use \$memory-recall to search when the user's question could benefit from historical context."
fi

if [ -n "$context" ]; then
  json_context=$(_json_encode_str "$context")
  echo "{\"systemMessage\": $json_status, \"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": $json_context}}"
else
  echo "{\"systemMessage\": $json_status}"
fi
