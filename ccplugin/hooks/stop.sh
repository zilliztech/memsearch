#!/usr/bin/env bash
# Stop hook: record the transcript path for deferred summarization.
#
# This hook fires after every assistant turn, but summarization is expensive
# (Haiku API call). Instead of summarizing on every turn, we just save the
# transcript path to a lightweight state file. The actual summarization
# happens once in flush_pending() — called by SessionEnd (or SessionStart
# as a safety net for crashed sessions).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Prevent infinite loop: if this Stop was triggered by a claude -p call
# inside flush_pending, bail out.
STOP_HOOK_ACTIVE=$(_json_val "$INPUT" "stop_hook_active" "false")
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  echo '{}'
  exit 0
fi

# Skip when the required API key is missing — the session likely only
# contains the "key not set" warning, and flush would skip anyway.
if ! _check_embedding_key; then
  echo '{}'
  exit 0
fi

# Extract and validate transcript path from hook input
TRANSCRIPT_PATH=$(_json_val "$INPUT" "transcript_path" "")
if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
  echo '{}'
  exit 0
fi

# Save transcript path to a pending state file.
# Filename = session ID (derived from transcript). Content = path + date.
# Each Stop invocation overwrites the same file (last-writer-wins),
# so only the final transcript state is summarized.
SESSION_ID=$(basename "$TRANSCRIPT_PATH" .jsonl)
TODAY=$(date +%Y-%m-%d)

mkdir -p "$PENDING_DIR"
printf '%s\n%s\n' "$TRANSCRIPT_PATH" "$TODAY" > "$PENDING_DIR/$SESSION_ID"

echo '{}'
