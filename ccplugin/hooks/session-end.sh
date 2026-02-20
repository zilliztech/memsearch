#!/usr/bin/env bash
# SessionEnd hook — summarize the session and tear down the watcher.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

# Flush before stopping the watcher — it may be killed before its debounce fires.
flush_pending
stop_watch

exit 0
