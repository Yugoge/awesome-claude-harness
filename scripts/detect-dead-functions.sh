#!/bin/bash
set -e

PROJECT_ROOT="${1:-.}"
HARNESS_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"  # install location, resolved before the cd below
cd "$PROJECT_ROOT"

# Override paths via CLI args or environment variables
# Arg 2: commands directory (default: <harness home>/commands)
COMMANDS_DIR="${2:-${CLAUDE_COMMANDS_DIR:-${HARNESS_HOME}/commands}}"
# Arg 3: agents directory (default: <harness home>/agents)
AGENTS_DIR="${3:-${CLAUDE_AGENTS_DIR:-${HARNESS_HOME}/agents}}"

# Only scan Python files in scripts/ directory (the active codebase)
SCRIPTS_DIR="${PROJECT_ROOT}/scripts"
if [ ! -d "$SCRIPTS_DIR" ]; then
    echo '{"detector":"dead-functions","findings":[],"summary":{"total":0}}'
    exit 0
fi

temp_file=$(mktemp)
> "$temp_file"

# For each Python file, find top-level functions/classes
for pyfile in "$SCRIPTS_DIR"/*.py; do
    [ -f "$pyfile" ] || continue
    basename=$(basename "$pyfile")

    # Get top-level function/class definitions (no leading whitespace)
    grep -nE '^(def |class )' "$pyfile" 2>/dev/null | while IFS=: read -r lineno defline; do
        name=$(echo "$defline" | sed -E 's/^(def |class )([a-zA-Z_][a-zA-Z0-9_]*).*/\2/')

        # Skip dunder methods and main()
        if [[ "$name" == __* ]] || [[ "$name" == "main" ]]; then
            continue
        fi

        # Check if called WITHIN its own file (exclude the def line itself)
        internal_calls=$(grep -c "\b${name}\b" "$pyfile" 2>/dev/null || echo "0")
        # Subtract 1 for the def line itself
        internal_calls=$((internal_calls - 1))

        # If called internally, it's not dead
        if [ "$internal_calls" -gt 0 ]; then
            continue
        fi

        # Not called internally — check if called from OTHER files
        ref_count=$(grep -rl "\b${name}\b" "$SCRIPTS_DIR"/*.py 2>/dev/null | grep -v "$basename" | wc -l)
        cmd_refs=$(grep -rl "\b${name}\b" "$COMMANDS_DIR"/*.md "$AGENTS_DIR"/*.md 2>/dev/null | wc -l)

        total_refs=$((ref_count + cmd_refs))

        if [ "$total_refs" -eq 0 ]; then
            if echo "$defline" | grep -q "^class "; then
                kind="class"
            else
                kind="function"
            fi
            echo "{\"file\": \"$basename\", \"line\": $lineno, \"name\": \"$name\", \"type\": \"$kind\", \"external_references\": 0, \"severity\": \"major\"}"
        fi
    done
done | jq -s '.' > "$temp_file" 2>/dev/null || echo "[]" > "$temp_file"

items=$(cat "$temp_file")
rm -f "$temp_file"

total=$(echo "$items" | jq 'length')
cat <<EOF
{
  "detector": "dead-functions",
  "project_root": "$PROJECT_ROOT",
  "scan_dir": "$SCRIPTS_DIR",
  "findings": $items,
  "summary": {
    "total": $total,
    "severity": $([ "$total" -gt 0 ] && echo '"major"' || echo '"none"')
  }
}
EOF
