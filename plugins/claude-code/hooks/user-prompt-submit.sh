#!/usr/bin/env bash
# UserPromptSubmit hook: capability hint reminding Claude about the memory-recall skill.
# The actual search + expand is handled by the memory-recall skill (pull-based, context: fork).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Skip short prompts (greetings, single words, etc.)
PROMPT=$(_json_val "$INPUT" "prompt" "")
if [ -z "$PROMPT" ] || [ "${#PROMPT}" -lt 10 ]; then
  echo '{}'
  exit 0
fi

# Need memsearch available
if ! memsearch_available; then
  echo '{}'
  exit 0
fi

# systemMessage is shown to the user in the terminal only; on UserPromptSubmit the
# model sees hookSpecificOutput.additionalContext (or plain stdout), so the hint has
# to travel in both to keep the visible one-liner and actually reach Claude.
echo '{"systemMessage": "[memsearch] Recall available if needed", "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "[memsearch] Recall available if needed"}}'
