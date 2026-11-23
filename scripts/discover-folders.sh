#!/usr/bin/env bash
# Description: Dynamically discover project folders excluding system directories
# Usage: discover-folders.sh <project_root>
# Exit codes: 0=success, 1=failure

set -euo pipefail

PROJECT_ROOT="${1:?Missing project root path}"

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "Error: Project root not found: $PROJECT_ROOT" >&2
  exit 1
fi

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
  ".claude"
)
# The harness's own directories in a project: .claude (above; Claude Code's and the harness's runtime
# files) and the JSON-only workflow directories commands/clean.md's documentation rules name. A README or
# INDEX the rule-inspector writes there is read by no one and stays behind untracked.
EXCLUDE_PATHS=(
  "./docs/dev"
  "./docs/clean"
)

EXCLUDE_ARGS=()
for exclude in "${EXCLUDES[@]}"; do
  EXCLUDE_ARGS+=(-name "$exclude" -prune -o)
done
for exclude in "${EXCLUDE_PATHS[@]}"; do
  EXCLUDE_ARGS+=(-path "$exclude" -prune -o)
done

find . \
  "${EXCLUDE_ARGS[@]}" \
  -type d -print | \
  grep -v '^\.$' | \
  sed 's|^\./||' | \
  sort

exit 0
