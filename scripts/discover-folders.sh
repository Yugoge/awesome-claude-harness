#!/usr/bin/env bash
# Description: Dynamically discover project folders excluding system directories
# Usage: discover-folders.sh <project_root>
# Exit codes: 0=success, 1=failure

set -euo pipefail

PROJECT_ROOT="${1:?Missing project root path}"

# Validate project root exists
if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "Error: Project root not found: $PROJECT_ROOT" >&2
  exit 1
fi

# Change to project root
cd "$PROJECT_ROOT"

# Excluded directories (system, build, cache, venv)
EXCLUDES=(
  ".git"
  ".github"
  "venv"
  ".venv"
  "env"
  ".env"
  "node_modules"
  "__pycache__"
  ".pytest_cache"
  ".mypy_cache"
  ".ruff_cache"
  "htmlcov"
  ".coverage"
  "dist"
  "build"
  "*.egg-info"
  ".tox"
  ".nox"
  "target"
  ".cargo"
  ".next"
  ".nuxt"
  "out"
  ".output"
  ".cache"
  ".DS_Store"
  "Thumbs.db"
)

# Build find exclude arguments
EXCLUDE_ARGS=()
for exclude in "${EXCLUDES[@]}"; do
  EXCLUDE_ARGS+=(-name "$exclude" -prune -o)
done

# Find all directories (excluding system dirs)
find . \
  "${EXCLUDE_ARGS[@]}" \
  -type d -print | \
  grep -v '^\.$' | \
  sed 's|^\./||' | \
  sort

exit 0
