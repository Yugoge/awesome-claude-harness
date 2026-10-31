#!/usr/bin/env bash
# update-gitignore.sh - Auto-update .gitignore with project-specific rules
#
# Usage: update-gitignore.sh [project_directory]
#        update-gitignore.sh project_directory --init
#        update-gitignore.sh project_directory [--comment TEXT] --rule RULE [--rule RULE ...]
#
# Detects existing cache/temp files and adds missing rules to .gitignore
# Adds project-type-specific rules (Python, Node.js) if applicable
# --init: create the default .gitignore when there is none (hooks/session-git-init.sh).
# --rule: append each RULE the file does not hold yet, under a `# TEXT` line when
#   --comment is given (hooks/session-gitignore-propagate.sh).
# This script is the harness's one writer of a project's .gitignore.
#
# Exit codes:
# 0 - Success (updated or already current)
# 1 - No .gitignore file exists
# 2 - Error

set -euo pipefail

PROJECT_DIR="${1:-.}"
INIT=0
COMMENT=""
RULES=()
[[ $# -gt 0 ]] && shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        --init) INIT=1; shift ;;
        --comment) COMMENT="${2:?--comment needs a value}"; shift 2 ;;
        --rule) RULES+=("${2:?--rule needs a value}"); shift 2 ;;
        *) echo "update-gitignore.sh: unknown argument: $1" >&2; exit 2 ;;
    esac
done

cd "$PROJECT_DIR" || exit 2

if [[ $INIT -eq 1 ]]; then
    [[ -f .gitignore ]] && exit 0
    cat > .gitignore << 'EOF'
# Dependencies
node_modules/
venv/
__pycache__/
*.pyc
.Python
env/
build/
dist/
*.egg-info/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Environment variables
.env
.env.local
.env.*.local

# Logs
*.log
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Claude Code local settings
.claude/settings.local.json
EOF
    echo "created"
    exit 0
fi

if [[ ! -f .gitignore ]]; then
    echo "⚠️  .gitignore does not exist in $PROJECT_DIR"
    exit 1
fi

if [[ ${#RULES[@]} -gt 0 ]]; then
    for rule in "${RULES[@]}"; do
        if ! grep -qF "$rule" .gitignore; then
            if [[ -n "$COMMENT" ]]; then
                printf '# %s\n%s\n' "$COMMENT" "$rule" >> .gitignore
            else
                printf '%s\n' "$rule" >> .gitignore
            fi
        fi
    done
    exit 0
fi

NEEDS_UPDATE=0

# Scan for existing cache/temp files
FOUND_PYCACHE=$(find . -type d -name "__pycache__" ! -path "./venv/*" ! -path "./.venv/*" -print -quit)
FOUND_PYTEST_CACHE=$(find . -type d -name ".pytest_cache" -print -quit)
FOUND_DS_STORE=$(find . -name ".DS_Store" -print -quit)

# Add individual patterns if found
if [[ -n "$FOUND_PYCACHE" ]] && ! grep -q "__pycache__" .gitignore; then
    echo "__pycache__/" >> .gitignore
    echo "✅ Added __pycache__/ to .gitignore"
    NEEDS_UPDATE=1
fi

if [[ -n "$FOUND_PYTEST_CACHE" ]] && ! grep -q ".pytest_cache" .gitignore; then
    echo ".pytest_cache/" >> .gitignore
    echo "✅ Added .pytest_cache/ to .gitignore"
    NEEDS_UPDATE=1
fi

if [[ -n "$FOUND_DS_STORE" ]] && ! grep -q ".DS_Store" .gitignore; then
    echo ".DS_Store" >> .gitignore
    echo "✅ Added .DS_Store to .gitignore"
    NEEDS_UPDATE=1
fi

# Add project-type-specific rules
if [[ -f "requirements.txt" ]] || [[ -f "pyproject.toml" ]]; then
    # Python project
    if ! grep -q "*.py\[cod\]" .gitignore && ! grep -q "\*.pyc" .gitignore; then
        cat >> .gitignore << 'EOF'

# Python
*.py[cod]
*.pyo
__pycache__/
.pytest_cache/
.mypy_cache/
.coverage
htmlcov/
EOF
        echo "✅ Added Python standard rules to .gitignore"
        NEEDS_UPDATE=1
    fi
fi

if [[ -f "package.json" ]]; then
    # Node.js project
    if ! grep -q "node_modules" .gitignore; then
        cat >> .gitignore << 'EOF'

# Node.js
node_modules/
npm-debug.log*
.eslintcache
dist/
EOF
        echo "✅ Added Node.js standard rules to .gitignore"
        NEEDS_UPDATE=1
    fi
fi

if [[ $NEEDS_UPDATE -eq 1 ]]; then
    echo "✅ .gitignore updated"
else
    echo "✅ .gitignore is already current"
fi

exit 0
