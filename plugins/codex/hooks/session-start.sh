#!/usr/bin/env bash
# SessionStart hook: clean up orphans, start watch singleton, inject recent memory context.
# Codex-specific: no SessionEnd counterpart.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Clean up orphaned processes from previous sessions (no SessionEnd in Codex)
cleanup_orphaned_processes

# Bootstrap: if memsearch not available, install uv and warm up uvx cache
if ! memsearch_available; then
  if ! command -v uvx &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null
    export PATH="$HOME/.local/bin:$PATH"
  fi
  # Warm up uvx cache with --upgrade to pull latest version
  uvx --upgrade --from 'memsearch[onnx]' memsearch --version &>/dev/null || true
  _detect_memsearch
fi

# First-time setup: if no config file exists, default to onnx provider.
if memsearch_available; then
  if [ ! -f "$HOME/.memsearch/config.toml" ] && [ ! -f "${PROJECT_DIR}/.memsearch.toml" ]; then
    _memsearch config set embedding.provider onnx 2>/dev/null || true
  fi
fi

# Read resolved config and version for status display
PROVIDER="onnx"; MODEL=""; MILVUS_URI=""; VERSION=""
if memsearch_available; then
  PROVIDER=$(_memsearch config get embedding.provider 2>/dev/null || echo "onnx")
  MODEL=$(_memsearch config get embedding.model 2>/dev/null || echo "")
  MILVUS_URI=$(_memsearch config get milvus.uri 2>/dev/null || echo "")
  # "memsearch, version 0.1.10" → "0.1.10"
  VERSION=$(_memsearch --version 2>/dev/null | sed 's/.*version //' || echo "")
fi

# Determine required API key for the configured provider
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
REQUIRED_KEY=$(_required_env_var "$PROVIDER")

KEY_MISSING=false
if [ -n "$REQUIRED_KEY" ] && [ -z "${!REQUIRED_KEY:-}" ]; then
  # Env var not set — check if API key is configured in memsearch config file
  CONFIG_API_KEY=""
  if memsearch_available; then
    CONFIG_API_KEY=$(_memsearch config get embedding.api_key 2>/dev/null || echo "")
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
    _MS_REAL=$(readlink -f "$(command -v memsearch 2>/dev/null)" 2>/dev/null || echo "")
    if [ "${MEMSEARCH_CMD[0]:-}" = "uvx" ] || [[ "$_MS_REAL" == *"uv/tools"* ]]; then
      UPGRADE_CMD="uv tool install -U 'memsearch[onnx]'"
    else
      UPGRADE_CMD="pip install --upgrade 'memsearch[onnx]'"
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

# Capture preexisting memory files before writing the new session heading.
EXISTING_MEMORY_FILES=$(find "$MEMORY_DIR" -maxdepth 1 -type f -name '*.md' 2>/dev/null | sort || true)
EXISTING_MEMORY_COUNT=$(printf '%s\n' "$EXISTING_MEMORY_FILES" | sed '/^$/d' | wc -l | tr -d ' ')

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
    INDEX_OUTPUT=$(_memsearch index "${_index_args[@]}" 2>&1) || true
    if echo "$INDEX_OUTPUT" | grep -q "dimension mismatch"; then
      _reset_args=(--yes)
      [ -n "$COLLECTION_NAME" ] && _reset_args+=(--collection "$COLLECTION_NAME")
      _memsearch reset "${_reset_args[@]}" 2>/dev/null || true
      _memsearch index "${_index_args[@]}" 2>/dev/null || true
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

# Count only preexisting memory entries for the hint.
# Do not treat the just-created session heading as past memory.
if [ "$EXISTING_MEMORY_COUNT" -gt 0 ]; then
  oldest_path=$(printf '%s\n' "$EXISTING_MEMORY_FILES" | sed -n '1p')
  newest_path=$(printf '%s\n' "$EXISTING_MEMORY_FILES" | tail -1)
  oldest=$(basename "$oldest_path" .md 2>/dev/null || true)
  newest=$(basename "$newest_path" .md 2>/dev/null || true)
  context="You have ${EXISTING_MEMORY_COUNT} past memory file(s) (${oldest} to ${newest}). Use \$memory-recall to search when the user's question could benefit from historical context."
fi

if [ -n "$context" ]; then
  json_context=$(_json_encode_str "$context")
  echo "{\"systemMessage\": $json_status, \"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": $json_context}}"
else
  echo "{\"systemMessage\": $json_status}"
fi
