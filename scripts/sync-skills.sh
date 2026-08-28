#!/bin/bash
# Sync the canonical skill sources under plugins/_shared/skills/ to all five
# platform plugin directories, prepending each platform's own frontmatter.
#
# Run this after editing plugins/_shared/skills/**; the copies are committed so
# each platform package ships self-contained skills. tests/test_skills_sync.py
# enforces that the copies stay in sync with the canonical source.
#
# Scope: memory-config and memory-to-skill. These two bodies are
# platform-independent; platform-specific details live in each skill's
# references/*.md, which the sync copies wholesale. memory-recall is NOT synced:
# its platform differences are structural (OpenClaw uses MCP tools, and each
# platform's collection/L3 commands embed install-time path placeholders that
# each platform's own install/runtime resolves), so it stays hand-maintained.
#
# Per-platform frontmatter (the ONLY per-platform divergence for the two synced
# skills):
#   - claude-code: context: fork + allowed-tools: Bash
#   - opencode:    allowed-tools: Bash
#   - openclaw:    metadata.openclaw.emoji
#   - codex:       (standard name/description only)
#   - dsh:         runtime-registered; body keeps {{PLACEHOLDER}} tokens and no
#                  frontmatter (index.js injects name/description at register time)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SHARED_DIR="$REPO_ROOT/plugins/_shared/skills"

SKILLS=(memory-config memory-to-skill)
# Platforms that ship a standard filesystem skill (SKILL.md + frontmatter).
PLATFORMS=(claude-code codex openclaw opencode)

# Frontmatter lines to insert after the shared `description:` line, per platform.
gen_frontmatter() {
  local platform="$1" name="$2" description="$3"
  case "$platform" in
    claude-code)
      printf '%s\n' \
        "---" \
        "name: ${name}" \
        "description: ${description}" \
        "context: fork" \
        "allowed-tools: Bash" \
        "---"
      ;;
    opencode)
      printf '%s\n' \
        "---" \
        "name: ${name}" \
        "description: ${description}" \
        "allowed-tools: Bash" \
        "---"
      ;;
    openclaw)
      printf '%s\n' \
        "---" \
        "name: ${name}" \
        "description: ${description}" \
        "metadata:" \
        "  openclaw:" \
        '    emoji: "🧠"' \
        "---"
      ;;
    *)
      printf '%s\n' \
        "---" \
        "name: ${name}" \
        "description: ${description}" \
        "---"
      ;;
  esac
}

# Extract the name and description from a shared SKILL.md frontmatter.
read_frontmatter() {
  local file="$1" key="$2"
  sed -n '2,20p' "$file" | grep -m1 "^${key}:" | sed "s/^${key}:[[:space:]]*//"
}

# Strip the shared frontmatter (everything between the first two `---` lines)
# so only the platform-independent body remains.
strip_frontmatter() {
  awk 'BEGIN { in_fm = 0; seen = 0 }
       /^---[[:space:]]*$/ {
         if (seen == 0) { seen = 1; in_fm = 1; next }
         else if (in_fm) { in_fm = 0; next }
       }
       !in_fm { print }'
}

for skill in "${SKILLS[@]}"; do
  src="$SHARED_DIR/$skill/SKILL.md"
  if [ ! -f "$src" ]; then
    echo "  ! skipping $skill: no shared SKILL.md" >&2
    continue
  fi
  name="$(read_frontmatter "$src" name)"
  description="$(read_frontmatter "$src" description)"
  body="$(strip_frontmatter < "$src")"

  # 1) Filesystem-shipped platforms: shared frontmatter + platform extras.
  for platform in "${PLATFORMS[@]}"; do
    dest_dir="$REPO_ROOT/plugins/$platform/skills/$skill"
    mkdir -p "$dest_dir"
    {
      gen_frontmatter "$platform" "$name" "$description"
      printf '%s\n' "$body"
    } > "$dest_dir/SKILL.md"
    # Copy the references/ directory wholesale (all platform files included).
    if [ -d "$SHARED_DIR/$skill/references" ]; then
      rm -rf "$dest_dir/references"
      cp -R "$SHARED_DIR/$skill/references" "$dest_dir/references"
    fi
    echo "  synced → plugins/$platform/skills/$skill/"
  done

  # 2) DSH: runtime-registered body, no frontmatter (name/description from index.js).
  dsh_dir="$REPO_ROOT/plugins/dsh/skills/$skill"
  mkdir -p "$dsh_dir"
  {
    printf '<!--\n  memsearch-dsh %s skill body.\n  Registered at plugin load by plugins/dsh/index.js via ctx.skills.register()\n  with metadata (name: %s, description, whenToUse) supplied in code.\n-->\n\n' "$skill" "$name"
    printf '%s\n' "$body"
  } > "$dsh_dir/SKILL.md"
  if [ -d "$SHARED_DIR/$skill/references" ]; then
    rm -rf "$dsh_dir/references"
    cp -R "$SHARED_DIR/$skill/references" "$dsh_dir/references"
  fi
  echo "  synced → plugins/dsh/skills/$skill/"
done

echo "Done. All platform skills are in sync with plugins/_shared/skills/."
