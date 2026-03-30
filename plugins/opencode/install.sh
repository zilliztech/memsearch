#!/bin/bash
# Install the memsearch OpenCode plugin.
#
# This script:
# 1. Detects if memsearch is installed
# 2. Symlinks the plugin to OpenCode's plugins directory
# 3. Symlinks the memory-recall skill to ~/.agents/skills/
# 4. Prints setup instructions

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENCODE_PLUGINS_DIR="${HOME}/.config/opencode/plugins"
AGENTS_SKILLS_DIR="${HOME}/.agents/skills"

echo "=== memsearch OpenCode Plugin Installer ==="
echo ""

# 1. Check memsearch
if command -v memsearch &>/dev/null; then
  echo "[OK] memsearch found: $(which memsearch)"
elif command -v uvx &>/dev/null; then
  echo "[OK] uvx found — will use: uvx --from 'memsearch[onnx]' memsearch"
  echo "     Tip: install memsearch for faster startup: uv tool install 'memsearch[onnx]'"
else
  echo "[WARN] Neither memsearch nor uvx found."
  echo "       Install with: uv tool install 'memsearch[onnx]'"
  echo "       Or: pip install 'memsearch[onnx]'"
fi
echo ""

# 2. Symlink plugin to OpenCode plugins directory
mkdir -p "${OPENCODE_PLUGINS_DIR}"
PLUGIN_LINK="${OPENCODE_PLUGINS_DIR}/memsearch.ts"
if [ -L "${PLUGIN_LINK}" ] || [ -f "${PLUGIN_LINK}" ]; then
  echo "[SKIP] Plugin already exists at ${PLUGIN_LINK}"
  echo "       Remove it first if you want to reinstall: rm ${PLUGIN_LINK}"
else
  ln -sf "${SCRIPT_DIR}/index.ts" "${PLUGIN_LINK}"
  echo "[OK] Plugin symlinked: ${PLUGIN_LINK} -> ${SCRIPT_DIR}/index.ts"
fi
echo ""

# 3. Symlink skill to ~/.agents/skills/ (OpenCode-compatible)
mkdir -p "${AGENTS_SKILLS_DIR}"
SKILL_LINK="${AGENTS_SKILLS_DIR}/memory-recall"
if [ -L "${SKILL_LINK}" ] || [ -d "${SKILL_LINK}" ]; then
  echo "[SKIP] Skill already exists at ${SKILL_LINK}"
  echo "       Remove it first if you want to reinstall: rm -rf ${SKILL_LINK}"
else
  ln -sf "${SCRIPT_DIR}/skills/memory-recall" "${SKILL_LINK}"
  echo "[OK] Skill symlinked: ${SKILL_LINK} -> ${SCRIPT_DIR}/skills/memory-recall"
fi
echo ""

# 4. Install plugin dependencies
echo "[INFO] Installing plugin dependencies..."
if command -v npm &>/dev/null; then
  (cd "${SCRIPT_DIR}" && npm install --save-dev @opencode-ai/plugin 2>/dev/null) && echo "[OK] Dependencies installed" || echo "[WARN] npm install failed — plugin may still work if OpenCode provides the SDK"
else
  echo "[WARN] npm not found — plugin may still work if @opencode-ai/plugin is available"
fi
echo ""

# 5. Show next steps
echo "=== Installation Complete ==="
echo ""
echo "The plugin will be auto-loaded next time you start OpenCode."
echo ""
echo "To verify, start OpenCode and check if memory_search tool appears:"
echo "  opencode"
echo ""
echo "Optional: Add to opencode.json for npm-based install:"
echo '  "plugin": ["memsearch-opencode"]'
echo ""
echo "Memory files will be stored in: <project>/.memsearch/memory/"
echo "Collection name is derived per-project for isolation."
