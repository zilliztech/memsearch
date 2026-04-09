#!/usr/bin/env bash
# SessionEnd hook: stop the memsearch watch singleton.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MEMSEARCH_SKIP_INPUT=1
source "$SCRIPT_DIR/common.sh"

stop_watch
kill_orphaned_index

exit 0
