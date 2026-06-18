#!/bin/bash
set -e

PROJECT_ROOT="${1:-.}"
cd "$PROJECT_ROOT"

# Patterns that indicate hardcoded environment-specific paths
# Exclude: comments, strings in docs, archive files
PATTERNS='/root/|/home/[a-z]|/tmp/[a-z]|/Users/[A-Z]'

# Search in tracked files, exclude venv/archive/node_modules
matches=$(grep -rnE "$PATTERNS" \
    --include="*.py" --include="*.sh" --include="*.md" --include="*.yml" --include="*.yaml" \
    --exclude-dir=venv --exclude-dir=node_modules --exclude-dir=.git \
    --exclude-dir="docs/archive" --exclude-dir="archive" \
    . 2>/dev/null || true)

items="[]"
if [ -n "$matches" ]; then
    items=$(echo "$matches" | while IFS=: read -r file line content; do
        # Extract the hardcoded path
        path=$(echo "$content" | grep -oE '/root/[^ "'"'"']+|/home/[a-z][^ "'"'"']+|/tmp/[a-z][^ "'"'"']+|/Users/[A-Z][^ "'"'"']+' | head -1)
        echo "{\"file\": \"$file\", \"line\": $line, \"hardcoded_path\": \"$path\", \"severity\": \"critical\"}"
    done | jq -s '.')
fi

total=$(echo "$items" | jq 'length')
cat <<EOF
{
  "detector": "hardcoded-paths",
  "project_root": "$PROJECT_ROOT",
  "findings": $items,
  "summary": {
    "total": $total,
    "severity": $([ "$total" -gt 0 ] && echo '"critical"' || echo '"none"')
  }
}
EOF
