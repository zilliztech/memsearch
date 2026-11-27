#!/usr/bin/env bash
# Materialize the shared maintenance runner in each self-contained plugin.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for platform in claude-code codex openclaw opencode dsh antigravity; do
    cp "$REPO_ROOT/plugins/_shared/scripts/maintenance-runner.py" "$REPO_ROOT/plugins/$platform/scripts/maintenance-runner.py"
done
