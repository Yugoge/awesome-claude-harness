#!/usr/bin/env bash
# Description: Analyze git history for edge cases from bug fix commits
# Usage: analyze-git-edge-cases.sh --project-root <path> [--since-date <date>] [--output <file>]
# Exit codes: 0=success, 1=failure

set -euo pipefail

PROJECT_ROOT=""
SINCE_DATE="90.days.ago"
OUTPUT_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --since-date)
      SINCE_DATE="$2"
      shift 2
      ;;
    --output)
      OUTPUT_FILE="$2"
      shift 2
      ;;
    *)
      echo "Error: Unknown parameter: $1" >&2
      echo "Usage: analyze-git-edge-cases.sh --project-root <path> [--since-date <date>] [--output <file>]" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$PROJECT_ROOT" ]]; then
  echo "Error: --project-root is required" >&2
  exit 1
fi

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "Error: Project root not found: $PROJECT_ROOT" >&2
  exit 1
fi

if [[ ! -d "$PROJECT_ROOT/.git" ]]; then
  echo "Error: Not a git repository: $PROJECT_ROOT" >&2
  exit 1
fi

if [[ -z "$OUTPUT_FILE" ]]; then
  OUTPUT_FILE="$PROJECT_ROOT/docs/test/edge-case-analysis.json"
fi

mkdir -p "$(dirname "$OUTPUT_FILE")"

cd "$PROJECT_ROOT"

# Keywords that indicate bug fixes or edge cases
KEYWORDS=(
  "fix:"
  "fix("
  "bug:"
  "bug("
  "error:"
  "issue:"
  "problem:"
  "resolve:"
  "resolved:"
  "hotfix:"
)

PATTERN=$(IFS='|'; echo "${KEYWORDS[*]}")

echo "Analyzing git history since $SINCE_DATE..." >&2
echo "Keywords: ${KEYWORDS[*]}" >&2

COMMITS=$(git log --since="$SINCE_DATE" --pretty=format:'%H|%ai|%s' --all 2>/dev/null | grep -iE "$PATTERN" || true)

if [[ -z "$COMMITS" ]]; then
  echo "No bug fix commits found in git history" >&2
  cat > "$OUTPUT_FILE" <<EOF
{
  "analysis_timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "project_root": "$PROJECT_ROOT",
  "since_date": "$SINCE_DATE",
  "commits_analyzed": 0,
  "edge_cases": [],
  "keywords_searched": $(printf '%s\n' "${KEYWORDS[@]}" | jq -R . | jq -s .),
  "summary": {
    "total_edge_cases": 0,
    "commits_with_fixes": 0
  }
}
EOF
  echo "Created empty edge case analysis: $OUTPUT_FILE" >&2
  exit 0
fi

TOTAL_COMMITS=$(echo "$COMMITS" | wc -l)
echo "Found $TOTAL_COMMITS bug fix commits" >&2

EDGE_CASES="[]"
COMMIT_COUNT=0

while IFS='|' read -r commit_hash commit_date commit_message; do
  COMMIT_COUNT=$((COMMIT_COUNT + 1))

  # Extract edge case identifier if present (e.g., "EC002", "EC006")
  EDGE_CASE_ID=$(echo "$commit_message" | grep -oE 'EC[0-9]{3}' | head -n 1 || echo "")

  FILES_CHANGED=$(git diff-tree --no-commit-id --name-only -r "$commit_hash" 2>/dev/null | jq -R . | jq -s -c . || echo "[]")

  EDGE_CASE_ENTRY=$(jq -n \
    --arg commit "$commit_hash" \
    --arg date "$commit_date" \
    --arg message "$commit_message" \
    --arg edge_case_id "$EDGE_CASE_ID" \
    --argjson files "$FILES_CHANGED" \
    '{
      commit: $commit,
      date: $date,
      message: $message,
      edge_case_id: $edge_case_id,
      files_changed: $files,
      severity: (if ($message | test("critical|breaking|security"; "i")) then "critical"
                 elif ($message | test("important|major"; "i")) then "high"
                 else "medium" end)
    }')

  EDGE_CASES=$(echo "$EDGE_CASES" | jq --argjson entry "$EDGE_CASE_ENTRY" '. += [$entry]')

done <<< "$COMMITS"

GROUPED_EDGE_CASES=$(echo "$EDGE_CASES" | jq 'group_by(.edge_case_id) | map({
  edge_case_id: .[0].edge_case_id,
  description: (.[0].message | split(":") | .[1:] | join(":") | ltrimstr(" ")),
  occurrences: length,
  commits: map({commit: .commit, date: .date, message: .message}),
  severity: ([.[].severity] | if any(. == "critical") then "critical" elif any(. == "high") then "high" else "medium" end),
  files_affected: ([.[].files_changed | .[]] | unique)
})')

TOTAL_EDGE_CASES=$(echo "$GROUPED_EDGE_CASES" | jq 'length')

cat > "$OUTPUT_FILE" <<EOF
{
  "analysis_timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "project_root": "$PROJECT_ROOT",
  "since_date": "$SINCE_DATE",
  "commits_analyzed": $COMMIT_COUNT,
  "edge_cases": $GROUPED_EDGE_CASES,
  "keywords_searched": $(printf '%s\n' "${KEYWORDS[@]}" | jq -R . | jq -s .),
  "summary": {
    "total_edge_cases": $TOTAL_EDGE_CASES,
    "commits_with_fixes": $COMMIT_COUNT,
    "severity_breakdown": {
      "critical": $(echo "$GROUPED_EDGE_CASES" | jq '[.[] | select(.severity == "critical")] | length'),
      "high": $(echo "$GROUPED_EDGE_CASES" | jq '[.[] | select(.severity == "high")] | length'),
      "medium": $(echo "$GROUPED_EDGE_CASES" | jq '[.[] | select(.severity == "medium")] | length')
    }
  }
}
EOF

echo "Edge case analysis complete: $OUTPUT_FILE" >&2
echo "Found $TOTAL_EDGE_CASES unique edge cases from $COMMIT_COUNT commits" >&2

exit 0
