#!/usr/bin/env bash
# Description: Remove validators that don't match git edge cases, preserving reports/
# Usage: cleanup-tests-folder.sh --project-root <path> --edge-case-analysis <json-file>
# Exit codes: 0=success, 1=failure

set -euo pipefail

PROJECT_ROOT=""
EDGE_CASE_ANALYSIS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --edge-case-analysis)
      EDGE_CASE_ANALYSIS="$2"
      shift 2
      ;;
    *)
      echo "Error: Unknown parameter: $1" >&2
      echo "Usage: cleanup-tests-folder.sh --project-root <path> --edge-case-analysis <json-file>" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$PROJECT_ROOT" ]]; then
  echo "Error: --project-root is required" >&2
  exit 1
fi

if [[ -z "$EDGE_CASE_ANALYSIS" ]]; then
  echo "Error: --edge-case-analysis is required" >&2
  exit 1
fi

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "Error: Project root not found: $PROJECT_ROOT" >&2
  exit 1
fi

if [[ ! -f "$EDGE_CASE_ANALYSIS" ]]; then
  echo "Error: Edge case analysis file not found: $EDGE_CASE_ANALYSIS" >&2
  exit 1
fi

TESTS_DIR="$PROJECT_ROOT/tests"
if [[ ! -d "$TESTS_DIR" ]]; then
  echo "No tests/ folder found at $TESTS_DIR - nothing to clean" >&2
  exit 0
fi

echo "Cleaning tests folder: $TESTS_DIR" >&2

# Extract edge case IDs from git analysis
VALID_EDGE_CASES=$(jq -r '.edge_cases[].edge_case_id' "$EDGE_CASE_ANALYSIS" | grep -v '^$' | sort -u)

if [[ -z "$VALID_EDGE_CASES" ]]; then
  echo "No edge cases found in git history - skipping cleanup" >&2
  exit 0
fi

echo "Valid edge cases from git history:" >&2
echo "$VALID_EDGE_CASES" >&2

REMOVED_COUNT=0
PRESERVED_COUNT=0

if [[ -d "$TESTS_DIR/scripts" ]]; then
  echo "Scanning tests/scripts/ for validators..." >&2

  for validator in "$TESTS_DIR/scripts"/validate-*.py "$TESTS_DIR/scripts"/validate-*.sh; do
    if [[ ! -e "$validator" ]]; then
      continue
    fi

    # Extract edge case ID from validator header/comments
    # Look for patterns like "EC002", "Edge Case: EC006", etc.
    VALIDATOR_EC=$(head -n 20 "$validator" 2>/dev/null | grep -oE 'EC[0-9]{3}' | head -n 1 || echo "")

    if [[ -z "$VALIDATOR_EC" ]]; then
      echo "  Warning: No edge case ID found in $(basename "$validator") - preserving" >&2
      PRESERVED_COUNT=$((PRESERVED_COUNT + 1))
      continue
    fi

    # Check if this edge case exists in git history
    if echo "$VALID_EDGE_CASES" | grep -q "^${VALIDATOR_EC}$"; then
      echo "  ✅ Preserving $(basename "$validator") - matches $VALIDATOR_EC from git history" >&2
      PRESERVED_COUNT=$((PRESERVED_COUNT + 1))
    else
      echo "  ❌ Removing $(basename "$validator") - $VALIDATOR_EC not found in git history" >&2
      rm -f "$validator"
      REMOVED_COUNT=$((REMOVED_COUNT + 1))
    fi
  done
fi

if [[ -d "$TESTS_DIR/instructions" ]]; then
  echo "Scanning tests/instructions/ for validator instructions..." >&2

  # Find all instruction files (excluding guides)
  for instruction in "$TESTS_DIR/instructions"/*.md; do
    if [[ ! -e "$instruction" ]]; then
      continue
    fi

    if [[ "$(basename "$instruction")" == *"guide.md" ]]; then
      continue
    fi

    # Extract edge case ID from instruction header
    INSTRUCTION_EC=$(head -n 20 "$instruction" 2>/dev/null | grep -oE 'EC[0-9]{3}' | head -n 1 || echo "")

    if [[ -z "$INSTRUCTION_EC" ]]; then
      echo "  Warning: No edge case ID found in $(basename "$instruction") - preserving" >&2
      PRESERVED_COUNT=$((PRESERVED_COUNT + 1))
      continue
    fi

    # Check if this edge case exists in git history
    if echo "$VALID_EDGE_CASES" | grep -q "^${INSTRUCTION_EC}$"; then
      echo "  ✅ Preserving $(basename "$instruction") - matches $INSTRUCTION_EC from git history" >&2
      PRESERVED_COUNT=$((PRESERVED_COUNT + 1))
    else
      echo "  ❌ Removing $(basename "$instruction") - $INSTRUCTION_EC not found in git history" >&2
      rm -f "$instruction"
      REMOVED_COUNT=$((REMOVED_COUNT + 1))
    fi
  done
fi

# Always preserve reports/ folder and its contents
if [[ -d "$TESTS_DIR/reports" ]]; then
  echo "✅ Preserving tests/reports/ folder and all contents" >&2
fi

# Always preserve data/ folder
if [[ -d "$TESTS_DIR/data" ]]; then
  echo "✅ Preserving tests/data/ folder and all contents" >&2
fi

# Always preserve README and INDEX files
for file in "$TESTS_DIR/README.md" "$TESTS_DIR/INDEX.md"; do
  if [[ -f "$file" ]]; then
    echo "✅ Preserving $(basename "$file")" >&2
  fi
done

echo "" >&2
echo "Cleanup summary:" >&2
echo "  Validators preserved: $PRESERVED_COUNT" >&2
echo "  Validators removed: $REMOVED_COUNT" >&2
echo "  Reports preserved: all" >&2

exit 0
