#!/usr/bin/env bash
# Derive a unique Milvus collection name from a project directory path.
# Used by hooks (via common.sh) and skill (via SKILL.md ! syntax).
#
# Usage: derive-collection.sh [project_dir]
#   If no argument given, uses pwd.
#
# Output: ms_<sanitized_basename>_<8char_sha256>
#   e.g. /home/user/my-app → ms_my_app_a1b2c3d4

set -euo pipefail

PROJECT_DIR="${1:-$(pwd)}"

# Resolve to absolute path (realpath preferred, cd fallback, raw last resort)
if command -v realpath &>/dev/null; then
  PROJECT_DIR="$(realpath -m "$PROJECT_DIR")"
elif [ -d "$PROJECT_DIR" ]; then
  PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
else
  # If directory doesn't exist and no realpath, ensure it starts with /
  case "$PROJECT_DIR" in
    /*) ;; # already absolute
    *)  PROJECT_DIR="$(pwd)/$PROJECT_DIR" ;;
  esac
fi

# Extract basename and sanitize:
# - lowercase
# - replace non-alphanumeric with underscore
# - collapse consecutive underscores
# - trim leading/trailing underscores
# - truncate to 40 chars
sanitized=$(basename "$PROJECT_DIR" \
  | tr '[:upper:]' '[:lower:]' \
  | sed 's/[^a-z0-9]/_/g' \
  | sed 's/__*/_/g' \
  | sed 's/^_//;s/_$//' \
  | cut -c1-40)

# Compute 8-char SHA-256 hash of the full absolute path
if command -v sha256sum &>/dev/null; then
  hash=$(printf '%s' "$PROJECT_DIR" | sha256sum | cut -c1-8)
elif command -v shasum &>/dev/null; then
  hash=$(printf '%s' "$PROJECT_DIR" | shasum -a 256 | cut -c1-8)
else
  hash=$(python3 -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:8])" "$PROJECT_DIR")
fi

echo "ms_${sanitized}_${hash}"
