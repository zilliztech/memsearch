#!/usr/bin/env bash
# SessionEnd hook: flush pending summaries and stop the memsearch watch singleton.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Flush staged stop-hook summaries into daily .md files and re-index.
# Must happen before stop_watch — the watcher may be killed before debounce fires.
flush_pending

stop_watch

exit 0
