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

# If memsearch is available, also do a semantic search for recent context
if [ -n "$MEMSEARCH_CMD" ]; then
  search_results=$($MEMSEARCH_CMD search "recent session summary" --top-k 3 --json-output 2>/dev/null || true)
  if [ -n "$search_results" ] && [ "$search_results" != "[]" ] && [ "$search_results" != "null" ]; then
    formatted=$(echo "$search_results" | jq -r '
      .[]? |
      "- [\(.source // "unknown"):\(.heading // "")]  \(.content // "" | .[0:200])"
    ' 2>/dev/null || true)
    if [ -n "$formatted" ]; then
      context+="\n## Semantic Search: Recent Sessions\n$formatted\n"
    fi
  fi
fi

# Add memory tools instructions for progressive disclosure
context+="\n## Memory Tools\n"
context+="When injected memories above need more context, use these commands via Bash:\n"
context+="- \`${MEMSEARCH_CMD_PREFIX} expand <chunk_hash>\` — show the full section around a memory chunk\n"
context+="- \`${MEMSEARCH_CMD_PREFIX} expand <chunk_hash> --json-output\` — JSON output with anchor metadata for L3 drill-down\n"
context+="- \`${MEMSEARCH_CMD_PREFIX} transcript <jsonl_path> --turn <uuid> --context 3\` — view original conversation turns from the JSONL transcript\n"
context+="chunk_hash is shown in Relevant Memories injected on each prompt. Anchors (session/turn/transcript path) are embedded in expand output.\n"

if [ -n "$context" ]; then
  json_context=$(printf '%s' "$context" | jq -Rs .)
  echo "{\"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": $json_context}}"
else
  echo '{}'
fi
