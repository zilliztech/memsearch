#!/bin/bash
# Prepare the V2 source for development. Host configuration remains user-owned.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v node >/dev/null || { echo "Node 22 is required; activate the existing nvm environment." >&2; exit 1; }
command -v npm >/dev/null
command -v python3 >/dev/null
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) process.exit(1)' || {
  echo "Node 22+ is required. Use nvm without replacing your shared installation." >&2; exit 1;
}
if ! command -v memsearch >/dev/null && ! command -v uvx >/dev/null; then
  echo "Install the core first: uv tool install 'memsearch[onnx]'" >&2
  exit 1
fi
npm install --prefix "$SCRIPT_DIR" --ignore-scripts --no-package-lock
python3 - "$SCRIPT_DIR" <<'PY'
import json
import sys
print("MemSearch V2 development source prepared for OpenCode >=2.0.32 <3.")
print("Add this source once to the V2 plugins array, retaining your other plugins:")
print(json.dumps({"plugins": [sys.argv[1]]}, indent=2))
print("Do not also enable an npm MemSearch entry or old local memsearch.ts link.")
print("Restart OpenCode and verify the loaded path. Skills register at runtime.")
print("Published V1 users pin @zilliz/memsearch-opencode@0.3.17.")
print("No host config, authentication, global Skills or daemon state was changed.")
PY
