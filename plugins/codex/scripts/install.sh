#!/usr/bin/env bash
# One-click installer for memsearch Codex CLI plugin.
# Copies the skill, installs or updates memsearch hook entries, enables feature flag.
#
# Usage: bash plugins/codex/scripts/install.sh

set -euo pipefail

# Determine install directory (parent of scripts/)
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

replace_text_in_file() {
  local target_file="$1"
  local old_text="$2"
  local new_text="$3"

  python3 - "$target_file" "$old_text" "$new_text" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
old = sys.argv[2]
new = sys.argv[3]

text = path.read_text()
path.write_text(text.replace(old, new))
PY
}

ensure_codex_hooks_enabled() {
  local config_file="$1"

  python3 - "$config_file" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
if not path.exists():
    path.write_text("[features]\ncodex_hooks = true\n")
    raise SystemExit

text = path.read_text()

if re.search(r"(?m)^codex_hooks\s*=", text):
    text = re.sub(r"(?m)^codex_hooks\s*=.*$", "codex_hooks = true", text)
elif re.search(r"(?m)^\[features\]\s*$", text):
    text = re.sub(r"(?m)^\[features\]\s*$", "[features]\ncodex_hooks = true", text, count=1)
else:
    if text and not text.endswith("\n"):
        text += "\n"
    text += "\n[features]\ncodex_hooks = true\n"

path.write_text(text)
PY
}

install_or_update_hooks_file() {
  local hooks_file="$1"
  local install_dir="$2"

  python3 - "$hooks_file" "$install_dir" <<'PY'
from pathlib import Path
import json
import math
import os
import sys

hooks_file = Path(sys.argv[1])
install_dir = sys.argv[2]

spec = {
    "SessionStart": {"script": "session-start.sh", "timeout": 30},
    "UserPromptSubmit": {"script": "user-prompt-submit.sh", "timeout": 10},
    "Stop": {"script": "stop.sh", "timeout": 30},
}


def convert_legacy_array(items):
    data = {"hooks": {}}
    for item in items:
        if not isinstance(item, dict):
            continue
        event = item.get("event")
        command = item.get("command")
        if not event or not command:
            continue
        hook = {"type": "command", "command": command}
        timeout_ms = item.get("timeout_ms")
        if isinstance(timeout_ms, (int, float)):
            hook["timeout"] = max(1, math.ceil(timeout_ms / 1000))
        if item.get("async") is True:
            hook["async"] = True
        data["hooks"].setdefault(event, []).append(
            {"matcher": item.get("matcher", ""), "hooks": [hook]}
        )
    return data


def load_existing():
    if not hooks_file.exists():
        return {"hooks": {}}

    parsed = json.loads(hooks_file.read_text())
    if isinstance(parsed, list):
        return convert_legacy_array(parsed)
    if isinstance(parsed, dict) and isinstance(parsed.get("hooks"), dict):
        return parsed
    return {"hooks": {}}


def strip_old_memsearch(entries, script_name):
    marker = f"plugins/codex/hooks/{script_name}"
    cleaned = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        hooks = []
        for hook in entry.get("hooks", []):
            command = hook.get("command", "") if isinstance(hook, dict) else ""
            if marker in command:
                continue
            hooks.append(hook)
        if hooks:
            copied = dict(entry)
            copied["hooks"] = hooks
            cleaned.append(copied)
    return cleaned


data = load_existing()
hooks = data.setdefault("hooks", {})

for event, details in spec.items():
    script = details["script"]
    cleaned = strip_old_memsearch(hooks.get(event, []), script)
    cleaned.append(
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": f"bash {install_dir}/hooks/{script}",
                    "timeout": details["timeout"],
                }
            ],
        }
    )
    hooks[event] = cleaned

# Write via sibling temp + os.replace so an interrupted write never leaves hooks_file truncated.
tmp = hooks_file.with_name(hooks_file.name + ".tmp")
tmp.write_text(json.dumps(data, indent=2) + "\n")
os.replace(tmp, hooks_file)
PY
}

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
  replace_text_in_file "$SKILL_DST/SKILL.md" "__INSTALL_DIR__" "$INSTALL_DIR"
  echo "  ✓ Updated SKILL.md with install path: $INSTALL_DIR"
fi

# --- 4. Install or update hooks.json ---
echo "[4/6] Configuring hooks..."
CODEX_DIR="$HOME/.codex"
mkdir -p "$CODEX_DIR"
HOOKS_FILE="$CODEX_DIR/hooks.json"

if [ -f "$HOOKS_FILE" ]; then
  echo "  ⚠ Existing hooks.json found — backing up to hooks.json.bak"
  cp "$HOOKS_FILE" "${HOOKS_FILE}.bak"
fi
install_or_update_hooks_file "$HOOKS_FILE" "$INSTALL_DIR"
echo "  ✓ Installed memsearch hooks in $HOOKS_FILE"

# --- 5. Enable codex_hooks feature flag ---
echo "[5/6] Enabling codex_hooks feature flag..."
CONFIG_FILE="$CODEX_DIR/config.toml"
ensure_codex_hooks_enabled "$CONFIG_FILE"
echo "  ✓ Ensured codex_hooks = true in $CONFIG_FILE"

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
