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
  # Warm up uvx cache (first run downloads packages, ~2s; subsequent <0.3s)
  uvx memsearch --version &>/dev/null || true
  _detect_memsearch
fi

# Guard: OpenAI API key is required for the default embedding provider.
# If missing, write session heading but skip watch/search and warn the user.
if [ -z "${OPENAI_API_KEY:-}" ]; then
  ensure_memory_dir
  TODAY=$(date +%Y-%m-%d)
  NOW=$(date +%H:%M)
  MEMORY_FILE="$MEMORY_DIR/$TODAY.md"
  echo -e "\n## Session $NOW\n" >> "$MEMORY_FILE"

  warn="[memsearch] OPENAI_API_KEY not set — memory search disabled. "
  warn+="Get a key: https://platform.openai.com/api-keys  "
  warn+="Then: export OPENAI_API_KEY=sk-..."
  json_warn=$(printf '%s' "$warn" | jq -Rs .)
  echo "{\"systemMessage\": $json_warn}"
  exit 0
fi

# Start memsearch watch as a singleton background process.
# This is the ONLY place indexing is managed — all other hooks just write .md files.
start_watch

# Write session heading to today's memory file
ensure_memory_dir
TODAY=$(date +%Y-%m-%d)
NOW=$(date +%H:%M)
MEMORY_FILE="$MEMORY_DIR/$TODAY.md"
echo -e "\n## Session $NOW\n" >> "$MEMORY_FILE"

# If memory dir has no .md files (other than the one we just created), nothing to inject
if [ ! -d "$MEMORY_DIR" ] || ! ls "$MEMORY_DIR"/*.md &>/dev/null; then
  echo '{}'
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
  echo "{\"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": $json_context}}"
else
  echo '{}'
fi
