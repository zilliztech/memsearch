#!/usr/bin/env bash
# UserPromptSubmit hook: lightweight hint reminding Claude about the memory-recall skill.
# The actual search + expand is handled by the memory-recall skill (pull-based, context: fork).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Skip short prompts (greetings, single words, etc.)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty' 2>/dev/null)
if [ -z "$PROMPT" ] || [ "${#PROMPT}" -lt 10 ]; then
  echo '{}'
  exit 0
fi

# Need memsearch available
if [ -z "$MEMSEARCH_CMD" ]; then
  echo '{}'
  exit 0
fi

echo '{"systemMessage": "[memsearch] Memory available"}'
