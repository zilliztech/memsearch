#!/usr/bin/env bash
# SessionStart hook: clean up orphans, start watch singleton, inject recent memory context.
# ZCode has no SessionEnd hook, so orphan cleanup happens here.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

cleanup_orphaned_processes

if ! memsearch_available; then
  if ! command -v uvx &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null
    export PATH="$HOME/.local/bin:$PATH"
  fi
  uvx --upgrade --from 'memsearch[onnx]' memsearch --version &>/dev/null || true
  _detect_memsearch
fi

if memsearch_available; then
  if [ ! -f "$HOME/.memsearch/config.toml" ] && [ ! -f "${PROJECT_DIR}/.memsearch.toml" ]; then
    _memsearch config set embedding.provider onnx 2>/dev/null || true
  fi
fi

PROVIDER="onnx"; MODEL=""; MILVUS_URI=""; VERSION=""
if memsearch_available; then
  PROVIDER=$(_memsearch config get embedding.provider 2>/dev/null || echo "onnx")
  MODEL=$(_memsearch config get embedding.model 2>/dev/null || echo "")
  MILVUS_URI=$(_memsearch config get milvus.uri 2>/dev/null || echo "")
  VERSION=$(_memsearch --version 2>/dev/null | sed 's/.*version //' || echo "")
fi

_required_env_var() {
  case "$1" in
    openai) echo "OPENAI_API_KEY" ;;
    google) echo "GOOGLE_API_KEY" ;;
    voyage) echo "VOYAGE_API_KEY" ;;
    jina) echo "JINA_API_KEY" ;;
    mistral) echo "MISTRAL_API_KEY" ;;
    *) echo "" ;;
  esac
}
REQUIRED_KEY=$(_required_env_var "$PROVIDER")

KEY_MISSING=false
if [ -n "$REQUIRED_KEY" ] && [ -z "${!REQUIRED_KEY:-}" ]; then
  CONFIG_API_KEY=""
  if memsearch_available; then
    CONFIG_API_KEY=$(_memsearch config get embedding.api_key 2>/dev/null || echo "")
  fi
  if [ -z "$CONFIG_API_KEY" ]; then
    KEY_MISSING=true
  fi
fi

ensure_memory_dir
TODAY=$(date +%Y-%m-%d)
NOW=$(date +%H:%M)
MEMORY_FILE="$MEMORY_DIR/$TODAY.md"

# Create session heading if not exists (same pattern as codex)
if [ ! -f "$MEMORY_FILE" ] || ! grep -qF "## Session $NOW" "$MEMORY_FILE"; then
  echo -e "\n## Session $NOW\n" >> "$MEMORY_FILE"
fi

start_watch

# Lite mode: one-time index since watch not running.
# Runs in background subshell to avoid blocking hook (ONNX model loading takes ~10s).
# Kill any previous background index first to prevent process accumulation.
# If embedding dimension changed (e.g. user switched provider), auto-reset and re-index.
if [[ "$MILVUS_URI" != http* ]] && [[ "$MILVUS_URI" != tcp* ]]; then
  kill_orphaned_index
  ensure_memory_dir

  if memsearch_available; then
    (
      INDEX_OUTPUT=$(_memsearch index "$MEMORY_DIR" 2>&1) || true
      # Check for dimension mismatch and auto-recover
      if echo "$INDEX_OUTPUT" | grep -q "dimension mismatch"; then
        _memsearch reset --yes 2>/dev/null || true
        _memsearch index "$MEMORY_DIR" 2>/dev/null || true
      fi
    ) >/dev/null 2>&1 &
    echo $! > "$INDEX_PIDFILE"
  fi
fi
# Build status message with warnings/hints
_status_parts=()
if [ "$KEY_MISSING" = "false" ] && memsearch_available; then
  _warn=$(index_state_warning 2>/dev/null || true)
  [ -n "$_warn" ] && _status_parts+=("$_warn")
  _hint=$(skill_candidate_hint 2>/dev/null || true)
  [ -n "$_hint" ] && _status_parts+=("$_hint")
fi

# Cold-start injection: memory file count and date range
if [ -d "$MEMORY_DIR" ]; then
  _file_count=$(find "$MEMORY_DIR" -maxdepth 1 -name "*.md" -type f 2>/dev/null | wc -l)
  if [ "$_file_count" -gt 0 ]; then
    _dates=$(ls -1t "$MEMORY_DIR"/*.md 2>/dev/null | head -3 | xargs -I{} basename {} .md | tr '\n' ',' | sed 's/,$//')
    _status_parts+=("memsearch: $_file_count memory files ($_dates). Use /memory-recall to search.")
  fi
fi

# Update check: query PyPI for newer version
if [ "$KEY_MISSING" = "false" ] && memsearch_available; then
  _current=$(_installed_version_from_dist_info)
  _latest=$(_pypi_latest_version)
  if [ -n "$_current" ] && [ -n "$_latest" ] && [ "$_current" != "$_latest" ]; then
    _status_parts+=("memsearch update available: $_current → $_latest")
  fi
fi

# Output as JSON systemMessage (matching claude-code pattern)
if [ ${#_status_parts[@]} -gt 0 ]; then
  _json_status=$(_json_encode_str "$(IFS=$'\n'; echo "${_status_parts[*]}")")
  echo "{\"systemMessage\": $_json_status}"
else
  echo '{}'
fi
