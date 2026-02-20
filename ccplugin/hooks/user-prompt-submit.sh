#!/usr/bin/env bash
# UserPromptSubmit hook — emit a hint so Claude knows the memory-recall skill
# is available. The actual search is handled by the skill itself (context: fork).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

# Ignore trivially short prompts (greetings, single words, etc.).
PROMPT=$(_json_val "$INPUT" "prompt" "")
if [ -z "$PROMPT" ] || [ "${#PROMPT}" -lt 10 ]; then
  echo '{}'
  exit 0
fi

[ -z "$MEMSEARCH_CMD" ] && {
  echo '{}'
  exit 0
}

echo '{"systemMessage": "[memsearch] Memory available"}'
