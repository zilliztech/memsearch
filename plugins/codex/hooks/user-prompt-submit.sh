#!/usr/bin/env bash
# UserPromptSubmit hook: capability hint reminding Codex about the memory-recall skill.
# The actual search + expand is handled by the memory-recall skill.

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

echo '{"systemMessage": "[memsearch] Recall available if needed"}'
