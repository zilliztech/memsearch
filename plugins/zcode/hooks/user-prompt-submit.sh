#!/usr/bin/env bash
# UserPromptSubmit hook: lightweight hint reminding ZCode about the memory-recall skill.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

PROMPT=$(_json_val "$INPUT" "prompt" "")
if [ -z "$PROMPT" ] || [ "${#PROMPT}" -lt 10 ]; then
  echo '{}'
  exit 0
fi

if ! memsearch_available; then
  echo '{}'
  exit 0
fi

echo '{"systemMessage": "[memsearch] Memory available"}'
