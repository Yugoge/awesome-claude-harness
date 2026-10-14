#!/bin/bash
# File reference detection script - used by /clean command
# Checks if a file is referenced in the project (including docs, code, config files, etc.)

set -euo pipefail

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Usage help
usage() {
    cat <<EOF
Usage: $0 <file-to-check> [project-root]

Check if a file is referenced in the project

Arguments:
  file-to-check    File path to check (relative or absolute)
  project-root     Project root directory (default: current directory)

Examples:
  $0 scripts/test-migration.sh
  $0 tests/test_old.py /root/my-project

Output:
  - List of reference locations
  - Git history analysis
  - Reference type classification (functional vs historical)
  - Delete/archive recommendations

Exit codes:
  0 - File has no references (safe to delete)
  1 - File has references (should not delete) or has functional references (must keep)
  2 - Only referenced by historical docs (suggest archive)
  3 - Error
EOF
    exit 3
}

# Parameter check
if [[ $# -lt 1 ]]; then
    usage
fi

TARGET_FILE="$1"
PROJECT_ROOT="${2:-.}"

# Ensure project root exists
if [[ ! -d "$PROJECT_ROOT" ]]; then
    echo -e "${RED}Error: Project directory does not exist: $PROJECT_ROOT${NC}" >&2
    exit 3
fi

HARNESS_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"  # install location, resolved before the cd below
cd "$PROJECT_ROOT"

# Ensure file exists
if [[ ! -f "$TARGET_FILE" ]]; then
    echo -e "${RED}Error: File does not exist: $TARGET_FILE${NC}" >&2
    exit 3
fi

# Get filename (for searching references)
FILENAME=$(basename "$TARGET_FILE")
FILENAME_NO_EXT="${FILENAME%.*}"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}📋 File Reference Detection Report${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "File: ${YELLOW}$TARGET_FILE${NC}"
echo -e "Project: ${YELLOW}$PROJECT_ROOT${NC}"
echo ""

# ============================================
# 1. Git History Analysis
# ============================================
echo -e "${BLUE}## 1. Git History Analysis${NC}"
echo ""

if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    # File creation time
    FILE_CREATED=$(git log --diff-filter=A --follow --format=%aI -1 -- "$TARGET_FILE" 2>/dev/null || echo "Unknown")

    # Last modified time
    FILE_MODIFIED=$(git log -1 --format=%aI -- "$TARGET_FILE" 2>/dev/null || echo "Unknown")

    # Commit count
    COMMIT_COUNT=$(git log --follow --oneline -- "$TARGET_FILE" 2>/dev/null | wc -l)

    # Last commit info
    LAST_COMMIT=$(git log -1 --format="%h - %s (%ar)" -- "$TARGET_FILE" 2>/dev/null || echo "No commit history")

    echo -e "  Created: ${GREEN}$FILE_CREATED${NC}"
    echo -e "  Last modified: ${GREEN}$FILE_MODIFIED${NC}"
    echo -e "  Commit count: ${GREEN}$COMMIT_COUNT${NC}"
    echo -e "  Last commit: ${GREEN}$LAST_COMMIT${NC}"

    # Check if one-time file
    if [[ $COMMIT_COUNT -le 2 ]]; then
        echo -e "  ${YELLOW}⚠️  Low commit count (≤2), possibly a one-time file${NC}"
    fi
else
    echo -e "  ${YELLOW}⚠️  Not a Git repository, skipping Git analysis${NC}"
fi

echo ""

# ============================================
# 2. Documentation Reference Check
# ============================================
echo -e "${BLUE}## 2. Documentation Reference Check (.md, .txt, README, etc.)${NC}"
echo ""

MD_REFS=$(grep -r "$FILENAME" . \
    --include="*.md" \
    --include="*.txt" \
    --include="README*" \
    --exclude-dir=.git \
    --exclude-dir=node_modules \
    --exclude-dir=venv \
    --exclude-dir=.venv \
    --exclude-dir=__pycache__ \
    --exclude-dir=.pytest_cache \
    --exclude-dir=docs/archive \
    2>/dev/null || true)

if [[ -n "$MD_REFS" ]]; then
    echo -e "  ${RED}❌ Found documentation references:${NC}"
    echo "$MD_REFS" | while IFS= read -r line; do
        echo -e "    ${YELLOW}$line${NC}"
    done
    DOC_REF_FOUND=1
else
    echo -e "  ${GREEN}✅ No documentation references${NC}"
    DOC_REF_FOUND=0
fi

echo ""

# ============================================
# 3. Code Reference Check
# ============================================
echo -e "${BLUE}## 3. Code Reference Check (.py, .js, .ts, .sh, etc.)${NC}"
echo ""

CODE_REFS=$(grep -r "$FILENAME" . \
    --include="*.py" \
    --include="*.js" \
    --include="*.ts" \
    --include="*.tsx" \
    --include="*.sh" \
    --include="*.bash" \
    --include="*.go" \
    --include="*.rs" \
    --exclude-dir=.git \
    --exclude-dir=node_modules \
    --exclude-dir=venv \
    --exclude-dir=.venv \
    --exclude-dir=__pycache__ \
    --exclude-dir=.pytest_cache \
    --exclude-dir=dist \
    --exclude-dir=build \
    --exclude="$TARGET_FILE" \
    2>/dev/null || true)

if [[ -n "$CODE_REFS" ]]; then
    echo -e "  ${RED}❌ Found code references:${NC}"
    echo "$CODE_REFS" | while IFS= read -r line; do
        echo -e "    ${YELLOW}$line${NC}"
    done
    CODE_REF_FOUND=1
else
    echo -e "  ${GREEN}✅ No code references${NC}"
    CODE_REF_FOUND=0
fi

echo ""

# ============================================
# 4. Config File Reference Check
# ============================================
echo -e "${BLUE}## 4. Config File Reference Check (settings.json, package.json, Makefile, etc.)${NC}"
echo ""

CONFIG_FILES=(
    ".claude/settings.json"
    "$HARNESS_HOME/settings.json"
    "package.json"
    "Makefile"
    "makefile"
    "pyproject.toml"
    "setup.py"
    "tox.ini"
    ".github/workflows/*.yml"
    ".github/workflows/*.yaml"
    ".gitlab-ci.yml"
)

CONFIG_REF_FOUND=0

for config_pattern in "${CONFIG_FILES[@]}"; do
    # Use find to handle wildcards
    if [[ "$config_pattern" == *"*"* ]]; then
        mapfile -t found_files < <(find . -path "./$config_pattern" 2>/dev/null)
    else
        found_files=("$config_pattern")
    fi

    for config_file in "${found_files[@]}"; do
        if [[ -f "$config_file" ]]; then
            if grep -q "$FILENAME" "$config_file" 2>/dev/null; then
                echo -e "  ${RED}❌ Found reference in $config_file:${NC}"
                grep -n "$FILENAME" "$config_file" | while IFS= read -r line; do
                    echo -e "    ${YELLOW}$line${NC}"
                done
                CONFIG_REF_FOUND=1
            fi
        fi
    done
done

if [[ $CONFIG_REF_FOUND -eq 0 ]]; then
    echo -e "  ${GREEN}✅ No config file references${NC}"
fi

echo ""

# ============================================
# 5. Script Cross-Reference Check (source/exec)
# ============================================
echo -e "${BLUE}## 5. Script Cross-Reference Check (source, exec, . )${NC}"
echo ""

if [[ "$FILENAME" == *.sh ]] || [[ "$FILENAME" == *.bash ]]; then
    SCRIPT_REFS=$(grep -rE "(source|\.|\bexec)\s+.*$FILENAME_NO_EXT" . \
        --include="*.sh" \
        --include="*.bash" \
        --exclude-dir=.git \
        --exclude="$TARGET_FILE" \
        2>/dev/null || true)

    if [[ -n "$SCRIPT_REFS" ]]; then
        echo -e "  ${RED}❌ Found script references:${NC}"
        echo "$SCRIPT_REFS" | while IFS= read -r line; do
            echo -e "    ${YELLOW}$line${NC}"
        done
        SCRIPT_REF_FOUND=1
    else
        echo -e "  ${GREEN}✅ No script references${NC}"
        SCRIPT_REF_FOUND=0
    fi
else
    echo -e "  ${YELLOW}⊘ Not a script file, skipping${NC}"
    SCRIPT_REF_FOUND=0
fi

echo ""

# ============================================
# 6. Import Reference Check (Python import, JS require/import)
# ============================================
echo -e "${BLUE}## 6. Import Reference Check (import, require, use)${NC}"
echo ""

if [[ "$FILENAME" == *.py ]] || [[ "$FILENAME" == *.js ]] || [[ "$FILENAME" == *.ts ]]; then
    IMPORT_REFS=$(grep -rE "(import|require|use|from).*$FILENAME_NO_EXT" . \
        --include="*.py" \
        --include="*.js" \
        --include="*.ts" \
        --include="*.tsx" \
        --exclude-dir=.git \
        --exclude-dir=node_modules \
        --exclude-dir=venv \
        --exclude-dir=__pycache__ \
        --exclude="$TARGET_FILE" \
        2>/dev/null || true)

    if [[ -n "$IMPORT_REFS" ]]; then
        echo -e "  ${RED}❌ Found import references:${NC}"
        echo "$IMPORT_REFS" | while IFS= read -r line; do
            echo -e "    ${YELLOW}$line${NC}"
        done
        IMPORT_REF_FOUND=1
    else
        echo -e "  ${GREEN}✅ No import references${NC}"
        IMPORT_REF_FOUND=0
    fi
else
    echo -e "  ${YELLOW}⊘ Not a Python/JS/TS file, skipping${NC}"
    IMPORT_REF_FOUND=0
fi

echo ""

# ============================================
# 7. File Modification Time Check
# ============================================
echo -e "${BLUE}## 7. File Modification Time Check${NC}"
echo ""

FILE_MTIME=$(stat -c %Y "$TARGET_FILE" 2>/dev/null || stat -f %m "$TARGET_FILE" 2>/dev/null)
CURRENT_TIME=$(date +%s)
DAYS_SINCE_MODIFIED=$(( (CURRENT_TIME - FILE_MTIME) / 86400 ))

echo -e "  Last modified: ${GREEN}${DAYS_SINCE_MODIFIED} days ago${NC}"

if [[ $DAYS_SINCE_MODIFIED -lt 7 ]]; then
    echo -e "  ${YELLOW}⚠️  Modified within 7 days, suggest careful deletion${NC}"
    RECENT_MODIFIED=1
else
    echo -e "  ${GREEN}✅ Not modified for over 7 days${NC}"
    RECENT_MODIFIED=0
fi

echo ""

# ============================================
# 8. Reference Type Classification (Functional vs Historical)
# ============================================
echo -e "${BLUE}## 8. Reference Type Classification${NC}"
echo ""

# Check for functional references (references in commands, agents, scripts)
FUNCTIONAL_REF_FOUND=0

if [[ -n "$MD_REFS" ]]; then
    # Check if referenced in .claude/commands/, .claude/agents/, scripts/
    FUNCTIONAL_REFS=$(echo "$MD_REFS" | grep -E "\.claude/commands/|\.claude/agents/|scripts/.*\.(sh|py)" || true)

    if [[ -n "$FUNCTIONAL_REFS" ]]; then
        echo -e "  ${RED}❌ Found functional references (commands/agents/scripts):${NC}"
        echo "$FUNCTIONAL_REFS" | while IFS= read -r line; do
            echo -e "    ${YELLOW}$line${NC}"
        done
        FUNCTIONAL_REF_FOUND=1
    fi
fi

if [[ $CODE_REF_FOUND -eq 1 ]] || [[ $CONFIG_REF_FOUND -eq 1 ]] || [[ $SCRIPT_REF_FOUND -eq 1 ]] || [[ $IMPORT_REF_FOUND -eq 1 ]]; then
    FUNCTIONAL_REF_FOUND=1
fi

if [[ $FUNCTIONAL_REF_FOUND -eq 1 ]]; then
    echo -e "  ${RED}⚠️  File has functional references (commands/agents/scripts/code)${NC}"
    echo -e "  ${RED}→ This is a functional doc/script, cannot delete or archive${NC}"
else
    # Check if only referenced by historical docs
    if [[ $DOC_REF_FOUND -eq 1 ]]; then
        # Check if referenced by docs/ or reports/ or historical .md files
        HISTORICAL_REFS=$(echo "$MD_REFS" | grep -E "docs/|reports/|chats/|.*-report\.md|.*-summary\.md|.*-plan\.md" || true)

        if [[ -n "$HISTORICAL_REFS" ]]; then
            echo -e "  ${YELLOW}⚠️  Only referenced by historical docs (docs/reports/chats):${NC}"
            echo "$HISTORICAL_REFS" | head -5 | while IFS= read -r line; do
                echo -e "    ${YELLOW}$line${NC}"
            done
            echo -e "  ${YELLOW}→ This is a historical doc, can be archived${NC}"
        fi
    else
        echo -e "  ${GREEN}✅ No references${NC}"
    fi
fi

echo ""

# ============================================
# 9. Comprehensive Evaluation and Recommendations
# ============================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}## 📊 Comprehensive Evaluation${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Calculate total references
TOTAL_REFS=$((DOC_REF_FOUND + CODE_REF_FOUND + CONFIG_REF_FOUND + SCRIPT_REF_FOUND + IMPORT_REF_FOUND))

echo -e "Reference statistics:"
echo -e "  - Documentation references: $([ $DOC_REF_FOUND -eq 1 ] && echo "${RED}Yes${NC}" || echo "${GREEN}No${NC}")"
echo -e "  - Code references: $([ $CODE_REF_FOUND -eq 1 ] && echo "${RED}Yes${NC}" || echo "${GREEN}No${NC}")"
echo -e "  - Config references: $([ $CONFIG_REF_FOUND -eq 1 ] && echo "${RED}Yes${NC}" || echo "${GREEN}No${NC}")"
echo -e "  - Script references: $([ $SCRIPT_REF_FOUND -eq 1 ] && echo "${RED}Yes${NC}" || echo "${GREEN}No${NC}")"
echo -e "  - Import references: $([ $IMPORT_REF_FOUND -eq 1 ] && echo "${RED}Yes${NC}" || echo "${GREEN}No${NC}")"
echo -e "  - ${YELLOW}Functional references: $([ $FUNCTIONAL_REF_FOUND -eq 1 ] && echo "${RED}Yes (cannot delete)${NC}" || echo "${GREEN}No${NC}")${NC}"
echo ""

# Delete recommendation (considering functional references)
if [[ $FUNCTIONAL_REF_FOUND -eq 1 ]]; then
    echo -e "${RED}❌ Deletion recommendation: Cannot delete${NC}"
    echo -e "   Reason: Has functional references in commands/agents/scripts"
    echo -e "   ${YELLOW}→ This is a functional doc/script, must keep${NC}"
    EXIT_CODE=1
elif [[ $TOTAL_REFS -eq 0 ]] && [[ $RECENT_MODIFIED -eq 0 ]]; then
    echo -e "${GREEN}✅ Deletion recommendation: Safe to delete${NC}"
    echo -e "   Reason: No references and not modified within 7 days"
    EXIT_CODE=0
elif [[ $TOTAL_REFS -eq 0 ]] && [[ $RECENT_MODIFIED -eq 1 ]]; then
    echo -e "${YELLOW}⚠️  Deletion recommendation: Delete with caution${NC}"
    echo -e "   Reason: No references but recently modified"
    EXIT_CODE=0
elif [[ $DOC_REF_FOUND -eq 1 ]] && [[ $CODE_REF_FOUND -eq 0 ]] && [[ $CONFIG_REF_FOUND -eq 0 ]]; then
    echo -e "${YELLOW}📦 Archive recommendation: Can be archived${NC}"
    echo -e "   Reason: Only referenced by historical docs, no functional references"
    echo -e "   ${YELLOW}→ Suggest moving to docs/archive/ or appropriate archive directory${NC}"
    EXIT_CODE=2  # New exit code: 2 = suggest archive
else
    echo -e "${RED}❌ Deletion recommendation: Not recommended${NC}"
    echo -e "   Reason: Has references, deletion may cause issues"
    EXIT_CODE=1
fi

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

exit $EXIT_CODE
