#!/usr/bin/env bash
# Stop hook — record the transcript path for deferred summarization.
#
# Fires after every assistant turn. Instead of running an expensive LLM call
# each time, we write a lightweight state file that flush_pending() (called
# once by SessionEnd) will pick up and summarize.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

# Guard against recursion: flush_pending() calls claude -p, which may
# re-trigger Stop hooks — bail out if that's the case.
if [ "$(_json_val "$INPUT" "stop_hook_active" "false")" = "true" ]; then
  echo '{}'
  exit 0
fi

# Nothing useful to record when the embedding key is missing.
if ! _check_embedding_key; then
  echo '{}'
  exit 0
fi

TRANSCRIPT_PATH=$(_json_val "$INPUT" "transcript_path" "")
if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
  echo '{}'
  exit 0
fi

# Write state: transcript path + date. Overwrites on every turn so only
# the final (most complete) transcript snapshot is summarized.
SESSION_ID=$(basename "$TRANSCRIPT_PATH" .jsonl)
mkdir -p "$PENDING_DIR"
printf '%s\n%s\n' "$TRANSCRIPT_PATH" "$(date +%Y-%m-%d)" >"$PENDING_DIR/$SESSION_ID"

echo '{}'
