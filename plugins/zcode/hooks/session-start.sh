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

start_watch

if [[ "$MILVUS_URI" != http* ]] && [[ "$MILVUS_URI" != tcp* ]]; then
  ensure_memory_dir
  if memsearch_available; then
    _memsearch index "$MEMORY_DIR" >/dev/null 2>&1 || true
  fi
fi

ADDITIONAL_CONTEXT=""
if [ "$KEY_MISSING" = "false" ] && memsearch_available; then
  index_state_warning
  skill_candidate_hint
fi

echo '{}'
