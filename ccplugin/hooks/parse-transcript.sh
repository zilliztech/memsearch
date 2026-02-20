#!/usr/bin/env bash
# parse-transcript.sh — convert a Claude Code JSONL transcript into concise
# plain text suitable for LLM summarization.
#
# Usage: bash parse-transcript.sh <transcript_path>
#
# Truncation:
#   - Process only the last MAX_LINES lines  (env MEMSEARCH_MAX_LINES, default 200)
#   - Text blocks > MAX_CHARS characters      (env MEMSEARCH_MAX_CHARS, default 500)
#     are tail-truncated with a leading "..."
#   - Tool calls:    tool name + truncated input summary
#   - Tool results:  one-line truncated preview
#   - file-history-snapshot entries are skipped entirely

set -euo pipefail

if ! command -v jq &>/dev/null; then
  echo "(transcript parsing skipped — jq not installed)"
  exit 0
fi

TRANSCRIPT_PATH="${1:-}"
MAX_LINES="${MEMSEARCH_MAX_LINES:-200}"
MAX_CHARS="${MEMSEARCH_MAX_CHARS:-500}"

if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
  echo "ERROR: transcript not found: $TRANSCRIPT_PATH" >&2
  exit 1
fi

TOTAL_LINES=$(wc -l <"$TRANSCRIPT_PATH")
if [ "$TOTAL_LINES" -eq 0 ]; then
  echo "(empty transcript)"
  exit 0
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Keep the last $2 characters of $1; prepend "..." when truncated.
truncate_tail() {
  local text="$1" max="$2"
  if [ "${#text}" -le "$max" ]; then
    printf '%s' "$text"
  else
    printf '...%s' "${text: -$max}"
  fi
}

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

if [ "$TOTAL_LINES" -gt "$MAX_LINES" ]; then
  echo "=== Transcript (last $MAX_LINES of $TOTAL_LINES lines) ==="
else
  echo "=== Transcript ($TOTAL_LINES lines) ==="
fi
echo ""

tail -n "$MAX_LINES" "$TRANSCRIPT_PATH" | while IFS= read -r line; do
  entry_type=$(printf '%s' "$line" | jq -r '.type // empty' 2>/dev/null) || continue
  [ "$entry_type" = "file-history-snapshot" ] && continue

  # Extract HH:MM:SS from ISO timestamp.
  ts=$(printf '%s' "$line" | jq -r '.timestamp // empty' 2>/dev/null)
  ts_short=""
  [ -n "$ts" ] && ts_short=$(printf '%s' "$ts" | sed -n 's/.*T\([0-9][0-9]:[0-9][0-9]:[0-9][0-9]\).*/\1/p' 2>/dev/null || echo "")

  if [ "$entry_type" = "user" ]; then
    content_type=$(printf '%s' "$line" | jq -r '.message.content | if type == "array" then .[0].type // "text" else "text" end' 2>/dev/null) || content_type="text"

    if [ "$content_type" = "tool_result" ]; then
      result_text=$(printf '%s' "$line" | jq -r '.message.content[0].content // "" | if type == "array" then .[0].text // "" else . end' 2>/dev/null)
      echo "[${ts_short}] TOOL RESULT: $(truncate_tail "$result_text" "$MAX_CHARS")"
    else
      user_text=$(printf '%s' "$line" | jq -r '.message.content // "" | if type == "array" then map(select(.type == "text") | .text) | join("\n") else . end' 2>/dev/null)
      echo ""
      echo "[${ts_short}] USER: $(truncate_tail "$user_text" "$MAX_CHARS")"
    fi

  elif [ "$entry_type" = "assistant" ]; then
    num_blocks=$(printf '%s' "$line" | jq -r '.message.content | length' 2>/dev/null) || num_blocks=0

    for ((i = 0; i < num_blocks; i++)); do
      block_type=$(printf '%s' "$line" | jq -r ".message.content[$i].type // empty" 2>/dev/null)

      if [ "$block_type" = "text" ]; then
        text=$(printf '%s' "$line" | jq -r ".message.content[$i].text // empty" 2>/dev/null)
        [ -z "$text" ] && continue
        echo "[${ts_short}] ASSISTANT: $(truncate_tail "$text" "$MAX_CHARS")"

      elif [ "$block_type" = "tool_use" ]; then
        tool_name=$(printf '%s' "$line" | jq -r ".message.content[$i].name // \"unknown\"" 2>/dev/null)
        tool_input=$(printf '%s' "$line" | jq -r ".message.content[$i].input | to_entries | map(\"\(.key)=\(.value | tostring | .[0:80])\") | join(\", \")" 2>/dev/null || echo "")
        echo "[${ts_short}] TOOL USE: ${tool_name}($(truncate_tail "$tool_input" 200))"
      fi
    done
  fi
done

echo ""
echo "=== End of transcript ==="
