#!/usr/bin/env bash
# Install memsearch OpenClaw plugin.
#
# Usage:
#   # From the plugin directory (development mode):
#   cd plugins/openclaw && bash install.sh
#
#   # Or from repo root:
#   bash plugins/openclaw/install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== memsearch OpenClaw plugin installer ==="

# 1. Ensure memsearch is available
if command -v memsearch &>/dev/null; then
  echo "[OK] memsearch found: $(memsearch --version 2>/dev/null || echo 'unknown')"
elif command -v uvx &>/dev/null; then
  echo "[INFO] memsearch not in PATH, will use uvx fallback"
  echo "[INFO] Installing memsearch[onnx] via uvx..."
  uvx --from 'memsearch[onnx]' memsearch --version
else
  echo "[WARN] Neither memsearch nor uvx found."
  echo "       Install uv first: curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "       Then: uvx --from 'memsearch[onnx]' memsearch --version"
fi

# 2. Ensure OpenClaw is available
if ! command -v openclaw &>/dev/null; then
  # Try nvm
  if [ -f "$HOME/.nvm/nvm.sh" ]; then
    source "$HOME/.nvm/nvm.sh"
  fi
fi

if command -v openclaw &>/dev/null; then
  echo "[OK] openclaw found: $(openclaw --version 2>/dev/null || echo 'unknown')"
else
  echo "[ERROR] openclaw not found. Install it first:"
  echo "        npm install -g openclaw"
  exit 1
fi

# 3. Install the plugin
echo ""
echo "Installing memsearch plugin into OpenClaw..."
openclaw plugins install "$SCRIPT_DIR"

echo ""
echo "=== Installation complete ==="
echo ""
echo "The plugin will be loaded on next OpenClaw session."
echo "To verify: openclaw plugins list | grep memsearch"
echo ""
echo "Configuration (optional):"
echo "  openclaw plugins config memsearch  # open config UI"
echo ""
echo "CLI commands:"
echo "  openclaw memsearch status   # show status"
echo "  openclaw memsearch search   # search memories"
echo "  openclaw memsearch index    # index memory files"
