#!/usr/bin/env bash
# Description: Scan project structure and detect project type
# Usage: scan-project.sh <PROJECT_ROOT>
# Output: JSON with project_type and file_counts
# Exit codes: 0=success, 1=error

set -euo pipefail

PROJECT_ROOT="${1:?Missing PROJECT_ROOT parameter}"

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "{\"error\": \"Project root not found: $PROJECT_ROOT\"}" >&2
  exit 1
fi

cd "$PROJECT_ROOT"

# Detect project type
PROJECT_TYPE="Generic"
if [[ -f "requirements.txt" ]] || [[ -f "pyproject.toml" ]]; then
  PROJECT_TYPE="Python"
elif [[ -f "package.json" ]]; then
  PROJECT_TYPE="Node.js"
elif [[ -f "go.mod" ]]; then
  PROJECT_TYPE="Go"
fi

TOTAL_FILES=$(find . -type f ! -path "./.git/*" 2>/dev/null | wc -l)
DOC_FILES=$(find . -name "*.md" -type f ! -path "./.git/*" 2>/dev/null | wc -l)
SCRIPT_FILES=$(find . -name "*.sh" -type f ! -path "./.git/*" 2>/dev/null | wc -l)
TEST_FILES=$(find . \( -name "test*.py" -o -name "*_test.py" \) -type f 2>/dev/null | wc -l)

jq -n \
  --arg project_type "$PROJECT_TYPE" \
  --argjson total "$TOTAL_FILES" \
  --argjson docs "$DOC_FILES" \
  --argjson scripts "$SCRIPT_FILES" \
  --argjson tests "$TEST_FILES" \
  '{
    project_type: $project_type,
    file_counts: {
      total: $total,
      docs: $docs,
      scripts: $scripts,
      tests: $tests
    }
  }'

exit 0
