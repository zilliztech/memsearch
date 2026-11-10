#!/usr/bin/env bash
# Python 3 is required even when jq is available (for transcript parsing).
# Verify candidates: Windows Store aliases can be on PATH without running Python,
# and the unversioned `python` command may still be Python 2.

_detect_python() {
  local candidate path
  MEMSEARCH_PYTHON_CMD=()
  for candidate in python3 python; do
    path=$(command -v "$candidate" 2>/dev/null) || continue
    if "$path" -c 'import sys; sys.exit(sys.version_info[0] != 3)' </dev/null >/dev/null 2>&1; then
      MEMSEARCH_PYTHON_CMD=("$path")
      return 0
    fi
  done
  path=$(command -v py 2>/dev/null) || return 1
  if "$path" -3 -c 'import sys; sys.exit(sys.version_info[0] != 3)' </dev/null >/dev/null 2>&1; then
    MEMSEARCH_PYTHON_CMD=("$path" -3)
    return 0
  fi
  return 1
}
_detect_python || true

python_available() {
  [ "${#MEMSEARCH_PYTHON_CMD[@]}" -gt 0 ]
}

run_python() {
  python_available || return 127
  "${MEMSEARCH_PYTHON_CMD[@]}" "$@"
}
