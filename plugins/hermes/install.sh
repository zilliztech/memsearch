#!/usr/bin/env bash
# memsearch Hermes plugin installer.
#
# Hermes recall comes from an MCP server (memory tools) — the same model as
# the Zed extension. Capture is a launchd/cron poller of ~/.hermes/state.db.
#
#   1. Copies the capture scripts into <project>/.memsearch/scripts/.
#   2. Sets up the MCP server venv + prints the `hermes mcp add` command.
#   3. Prints how to register the capture daemon (launchd) or cron.
#
# Usage: install.sh [project_dir]
#   If no project_dir given, uses pwd (must be a project root).
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${1:-$(pwd)}"

echo "== memsearch Hermes plugin install =="

# 1. Scripts -> <project>/.memsearch/scripts/
mkdir -p "$PROJECT_DIR/.memsearch/scripts" "$PROJECT_DIR/.memsearch/memory"
for script in hermes-capture.py parse-transcript.py derive-collection.sh; do
  cp "$PLUGIN_DIR/scripts/$script" "$PROJECT_DIR/.memsearch/scripts/"
  chmod +x "$PROJECT_DIR/.memsearch/scripts/$script"
  echo "  script installed: .memsearch/scripts/$script"
done

# 2. MCP server venv (fastmcp) — the recall path
MCP_SERVER="$PLUGIN_DIR/server/memsearch_mcp_server.py"
if [ ! -d "$PLUGIN_DIR/.venv" ]; then
  python3 -m venv "$PLUGIN_DIR/.venv"
  "$PLUGIN_DIR/.venv/bin/pip" install -q fastmcp
  echo "  MCP venv created: $PLUGIN_DIR/.venv"
fi

# 3. Capture daemon / cron — print the option to register.
COLLECTION=$(bash "$PROJECT_DIR/.memsearch/scripts/derive-collection.sh" "$PROJECT_DIR" 2>/dev/null || echo "<collection>")
cat <<EOF

== Register the MCP server (recall) ==
Run in a Hermes session or via `hermes mcp add`:

  hermes mcp add memsearch --command "$PLUGIN_DIR/.venv/bin/python $MCP_SERVER"

The agent then gets memory_search / memory_get / memory_transcript /
memory_capture as first-class tools.

== Capture ==
Continuous (recommended) — launchd daemon polling ~/.hermes/state.db every 2m:
  launchctl bootstrap gui/\$(id -u) $PLUGIN_DIR/hermes-capture-daemon.plist
Or hourly cron:
  Run: /usr/local/bin/python3 $PROJECT_DIR/.memsearch/scripts/hermes-capture.py $PROJECT_DIR 60
  (collection: $COLLECTION)

== Done ==
Ask Hermes "recall what we decided about X" — the agent calls memory_search.
EOF
