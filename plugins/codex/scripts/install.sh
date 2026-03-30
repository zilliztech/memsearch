#!/usr/bin/env bash
# One-click installer for memsearch Codex CLI plugin.
# Creates skill copy, generates hooks.json, enables feature flag.
#
# Usage: bash plugins/codex/scripts/install.sh

set -euo pipefail

# Determine install directory (parent of scripts/)
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== memsearch Codex CLI Plugin Installer ==="
echo "Install directory: $INSTALL_DIR"
echo ""

# --- 1. Check memsearch availability ---
echo "[1/6] Checking memsearch..."
if command -v memsearch &>/dev/null; then
  MS_VERSION=$(memsearch --version 2>/dev/null || echo "unknown")
  echo "  ✓ memsearch found: $(command -v memsearch) ($MS_VERSION)"
elif command -v uvx &>/dev/null; then
  echo "  ✓ uvx found — will use: uvx --from memsearch[onnx] memsearch"
  echo "  Warming up cache (first run may take ~30s)..."
  uvx --from 'memsearch[onnx]' memsearch --version 2>/dev/null || true
else
  echo "  ✗ memsearch not found. Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  echo "  Warming up uvx cache (first run may take ~30s)..."
  uvx --from 'memsearch[onnx]' memsearch --version 2>/dev/null || true
fi

# --- 2. Install memory-recall skill ---
echo "[2/6] Installing memory-recall skill..."
SKILL_SRC="$INSTALL_DIR/skills/memory-recall"
SKILL_DST="$HOME/.agents/skills/memory-recall"
mkdir -p "$HOME/.agents/skills"

if [ -d "$SKILL_DST" ] || [ -L "$SKILL_DST" ]; then
  echo "  ⚠ Existing memory-recall skill found — replacing"
  rm -rf "$SKILL_DST"
fi

# Copy (not symlink) so we can substitute __INSTALL_DIR__ placeholder
cp -r "$SKILL_SRC" "$SKILL_DST"
echo "  ✓ Copied skill to $SKILL_DST"

# --- 3. Replace __INSTALL_DIR__ placeholder in SKILL.md ---
echo "[3/6] Configuring skill paths..."
if [ -f "$SKILL_DST/SKILL.md" ]; then
  sed -i "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$SKILL_DST/SKILL.md"
  echo "  ✓ Updated SKILL.md with install path: $INSTALL_DIR"
fi

# --- 4. Generate hooks.json ---
echo "[4/6] Configuring hooks..."
CODEX_DIR="$HOME/.codex"
mkdir -p "$CODEX_DIR"
HOOKS_FILE="$CODEX_DIR/hooks.json"

NEW_HOOKS=$(cat <<EOF
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash $INSTALL_DIR/hooks/session-start.sh",
            "timeout": 30
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash $INSTALL_DIR/hooks/user-prompt-submit.sh",
            "timeout": 10
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash $INSTALL_DIR/hooks/stop.sh",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
EOF
)

if [ -f "$HOOKS_FILE" ]; then
  echo "  ⚠ Existing hooks.json found — backing up to hooks.json.bak"
  cp "$HOOKS_FILE" "${HOOKS_FILE}.bak"
fi
echo "$NEW_HOOKS" > "$HOOKS_FILE"
echo "  ✓ Generated $HOOKS_FILE"

# --- 5. Enable codex_hooks feature flag ---
echo "[5/6] Enabling codex_hooks feature flag..."
CONFIG_FILE="$CODEX_DIR/config.toml"
if [ -f "$CONFIG_FILE" ]; then
  if grep -q "codex_hooks" "$CONFIG_FILE"; then
    # Update existing flag
    sed -i 's/codex_hooks.*/codex_hooks = true/' "$CONFIG_FILE"
    echo "  ✓ Updated existing codex_hooks flag"
  else
    # Add under [features] section if it exists, otherwise create it
    if grep -q '^\[features\]' "$CONFIG_FILE"; then
      sed -i '/^\[features\]/a codex_hooks = true' "$CONFIG_FILE"
    else
      echo -e "\n[features]\ncodex_hooks = true" >> "$CONFIG_FILE"
    fi
    echo "  ✓ Added codex_hooks = true to config.toml"
  fi
else
  cat > "$CONFIG_FILE" <<'TOML'
[features]
codex_hooks = true
TOML
  echo "  ✓ Created config.toml with codex_hooks enabled"
fi

# --- 6. Make scripts executable ---
echo "[6/6] Setting permissions..."
chmod +x "$INSTALL_DIR/hooks/"*.sh
chmod +x "$INSTALL_DIR/scripts/"*.sh
echo "  ✓ All scripts marked executable"

echo ""
echo "=== Installation Complete ==="
echo ""
echo "The memsearch plugin is now configured for Codex CLI."
echo ""
echo "What happens automatically:"
echo "  • SessionStart: indexes project memory, injects recent context"
echo "  • Stop: summarizes each turn and saves to memory"
echo "  • UserPromptSubmit: reminds Codex about memory-recall skill"
echo "  • memory-recall skill: search past memories when relevant"
echo ""
echo "Memory files:   <project>/.memsearch/memory/*.md"
echo "Hooks config:   $HOOKS_FILE"
echo "Skill location: $SKILL_DST"
echo "Feature flag:   codex_hooks = true in $CONFIG_FILE"
echo ""
echo "To verify: start a new codex session and check for [memsearch] status line."
