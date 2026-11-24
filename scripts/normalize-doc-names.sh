#!/usr/bin/env bash
# normalize-doc-names.sh - Detect and report non-compliant documentation file names
#
# Usage: normalize-doc-names.sh [docs_directory]
#
# Scans markdown files and reports naming violations:
# - Uppercase letters → lowercase
# - Underscores → hyphens
# - CamelCase → kebab-case
#
# Exit codes:
# 0 - All files compliant
# 1 - Non-compliant files found
# 2 - Error

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

DOCS_DIR="${1:-.claude/docs}"
NON_COMPLIANT=0

if [[ ! -d "$DOCS_DIR" ]]; then
    echo -e "${RED}Error: Directory '$DOCS_DIR' does not exist${NC}" >&2
    exit 2
fi

echo "Scanning $DOCS_DIR for non-compliant file names..."
echo ""

# Find all .md files (excluding archive/)
while IFS= read -r -d '' file; do
    basename=$(basename "$file")

    if [[ "$basename" =~ ^[a-z0-9-]+\.md$ ]]; then
        continue
    fi

    suggested="$basename"
    violations=()

    if [[ "$basename" =~ [A-Z] ]]; then
        suggested=$(echo "$suggested" | tr '[:upper:]' '[:lower:]')
        violations+=("uppercase")
    fi

    if [[ "$basename" =~ _ ]]; then
        suggested=$(echo "$suggested" | sed 's/_/-/g')
        violations+=("underscore")
    fi

    # Check for camelCase (lowercase followed by uppercase)
    if [[ "$basename" =~ [a-z][A-Z] ]]; then
        suggested=$(echo "$suggested" | sed 's/\([a-z]\)\([A-Z]\)/\1-\2/g' | tr '[:upper:]' '[:lower:]')
        violations+=("camelCase")
    fi

    if [[ ${#violations[@]} -gt 0 ]]; then
        echo -e "${YELLOW}❌ Non-compliant:${NC} $file"
        echo -e "   ${RED}Issues:${NC} ${violations[*]}"
        echo -e "   ${GREEN}Suggested:${NC} $(dirname "$file")/$suggested"
        echo ""
        NON_COMPLIANT=1
    fi
done < <(find "$DOCS_DIR" -name "*.md" -type f ! -path "*/archive/*" -print0)

if [[ $NON_COMPLIANT -eq 0 ]]; then
    echo -e "${GREEN}✅ All files are compliant!${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠️  Non-compliant files found. Please rename manually.${NC}"
    exit 1
fi
