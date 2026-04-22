#!/bin/bash
# Sync shared prompt templates to all plugin directories.
# Run this after editing plugins/_shared/prompts/*.txt.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SHARED_DIR="$REPO_ROOT/plugins/_shared/prompts"

PLUGINS=(claude-code codex openclaw opencode)

for plugin in "${PLUGINS[@]}"; do
    dest="$REPO_ROOT/plugins/$plugin/prompts"
    mkdir -p "$dest"
    cp "$SHARED_DIR"/*.txt "$dest/"
    echo "  synced → plugins/$plugin/prompts/"
done

echo "Done. All plugin prompts are in sync."
