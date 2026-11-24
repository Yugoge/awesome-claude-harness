#!/bin/bash
set -e

PROJECT_ROOT="${1:-.}"
cd "$PROJECT_ROOT"

# Find unresolved merge conflict markers in tracked files
conflicts=$(git grep -l '<<<<<<< \|=======$\|>>>>>>> ' -- ':!venv/' ':!node_modules/' ':!docs/archive/' 2>/dev/null || true)

items="[]"
if [ -n "$conflicts" ]; then
    items=$(echo "$conflicts" | while IFS= read -r file; do
        count=$(grep -c '<<<<<<< \|=======$\|>>>>>>> ' "$file" 2>/dev/null || echo "0")
        echo "{\"file\": \"$file\", \"marker_count\": $count, \"severity\": \"critical\"}"
    done | jq -s '.')
fi

total=$(echo "$items" | jq 'length')
cat <<EOF
{
  "detector": "merge-conflicts",
  "project_root": "$PROJECT_ROOT",
  "findings": $items,
  "summary": {
    "total": $total,
    "severity": $([ "$total" -gt 0 ] && echo '"critical"' || echo '"none"')
  }
}
EOF
