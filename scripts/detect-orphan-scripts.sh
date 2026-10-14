#!/usr/bin/env bash
# Description: Detect scripts not referenced by any command/agent/other script
# Usage: detect-orphan-scripts.sh [project-root]
# Exit codes: 0=success

set -euo pipefail

# Parameters
PROJECT_ROOT="${1:-.}"
HARNESS_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"  # install location, resolved before the cd below

# Navigate to project root
cd "$PROJECT_ROOT"

# Get .claude directory (check both local and global)
CLAUDE_DIR="${PROJECT_ROOT}/.claude"
GLOBAL_CLAUDE_DIR="$HARNESS_HOME"

# Patterns indicating one-time fix scripts
ONE_TIME_PATTERNS=("-fix" "-v2" "-patch" "-migration" "-cleanup" "-repair" "-reextract" "-batch")

# Initialize JSON output
orphan_scripts=""
total_count=0
one_time_fix_count=0
general_orphan_count=0

# Function to check if script is referenced
check_script_references() {
    local script_file="$1"
    local script_name
    script_name=$(basename "$script_file")
    local script_name_no_ext="${script_name%.*}"

    local referenced=false

    # Check in .claude/commands/*.md (local)
    if [[ -d "${CLAUDE_DIR}/commands" ]]; then
        if grep -rq "$script_name" "${CLAUDE_DIR}/commands/" 2>/dev/null; then
            referenced=true
        fi
    fi

    # Check in .claude/commands/*.md (global)
    if [[ -d "${GLOBAL_CLAUDE_DIR}/commands" ]]; then
        if grep -rq "$script_name" "${GLOBAL_CLAUDE_DIR}/commands/" 2>/dev/null; then
            referenced=true
        fi
    fi

    # Check in .claude/agents/*.md (local)
    if [[ -d "${CLAUDE_DIR}/agents" ]]; then
        if grep -rq "$script_name" "${CLAUDE_DIR}/agents/" 2>/dev/null; then
            referenced=true
        fi
    fi

    # Check in .claude/agents/*.md (global)
    if [[ -d "${GLOBAL_CLAUDE_DIR}/agents" ]]; then
        if grep -rq "$script_name" "${GLOBAL_CLAUDE_DIR}/agents/" 2>/dev/null; then
            referenced=true
        fi
    fi

    # Check in other scripts (excluding self by source file, not content)
    if [[ -d "scripts" ]]; then
        local script_refs
        script_refs=$(grep -r "$script_name" scripts/ --include="*.sh" --include="*.py" 2>/dev/null | grep -v "^${script_file}:" || true)
        if [[ -n "$script_refs" ]]; then
            referenced=true
        fi
    fi

    # Check in .claude/scripts (global)
    if [[ -d "${GLOBAL_CLAUDE_DIR}/scripts" ]]; then
        local global_script_refs
        global_script_refs=$(grep -r "$script_name" "${GLOBAL_CLAUDE_DIR}/scripts/" --include="*.sh" --include="*.py" 2>/dev/null | grep -v "^${script_file}:" || true)
        if [[ -n "$global_script_refs" ]]; then
            referenced=true
        fi
    fi

    # Check in .claude/settings.json (local and global)
    if [[ -f "${CLAUDE_DIR}/settings.json" ]]; then
        if grep -q "$script_name" "${CLAUDE_DIR}/settings.json" 2>/dev/null; then
            referenced=true
        fi
    fi
    if [[ -f "${GLOBAL_CLAUDE_DIR}/settings.json" ]]; then
        if grep -q "$script_name" "${GLOBAL_CLAUDE_DIR}/settings.json" 2>/dev/null; then
            referenced=true
        fi
    fi

    # Check Python import references (for .py scripts)
    # Catches: "from utils import ...", "import load_resume_data", "from utils."
    if [[ "$script_name" == *.py ]] && [[ "$referenced" == "false" ]]; then
        local import_pattern="(import ${script_name_no_ext}|from ${script_name_no_ext} import|from ${script_name_no_ext}\.)"
        if [[ -d "scripts" ]]; then
            local py_import_refs
            py_import_refs=$(grep -rE "$import_pattern" scripts/ --include="*.py" 2>/dev/null | grep -v "^${script_file}:" || true)
            if [[ -n "$py_import_refs" ]]; then
                referenced=true
            fi
        fi
        if [[ "$referenced" == "false" ]] && [[ -d "${GLOBAL_CLAUDE_DIR}/scripts" ]]; then
            local global_py_import_refs
            global_py_import_refs=$(grep -rE "$import_pattern" "${GLOBAL_CLAUDE_DIR}/scripts/" --include="*.py" 2>/dev/null | grep -v "^${script_file}:" || true)
            if [[ -n "$global_py_import_refs" ]]; then
                referenced=true
            fi
        fi
    fi

    # Check subprocess/shell invocation references (python scripts/X.py or python3 scripts/X.py)
    # Catches scripts called from shell scripts via python/python3
    if [[ "$referenced" == "false" ]]; then
        local subprocess_pattern="python[3]?\s+(scripts/)?${script_name}"
        if [[ -d "scripts" ]]; then
            local subprocess_refs
            subprocess_refs=$(grep -rE "$subprocess_pattern" scripts/ --include="*.sh" 2>/dev/null | grep -v "^${script_file}:" || true)
            if [[ -n "$subprocess_refs" ]]; then
                referenced=true
            fi
        fi
        if [[ "$referenced" == "false" ]] && [[ -d "${GLOBAL_CLAUDE_DIR}/scripts" ]]; then
            local global_subprocess_refs
            global_subprocess_refs=$(grep -rE "$subprocess_pattern" "${GLOBAL_CLAUDE_DIR}/scripts/" --include="*.sh" 2>/dev/null | grep -v "^${script_file}:" || true)
            if [[ -n "$global_subprocess_refs" ]]; then
                referenced=true
            fi
        fi
    fi

    # Check path-based references in command .md files (scripts/X.py or scripts/X.sh)
    # Catches references like "python3 scripts/check_page_height.py" in command docs
    if [[ "$referenced" == "false" ]]; then
        local path_pattern="scripts/${script_name}"
        if [[ -d "${CLAUDE_DIR}/commands" ]]; then
            if grep -rq "$path_pattern" "${CLAUDE_DIR}/commands/" 2>/dev/null; then
                referenced=true
            fi
        fi
        if [[ "$referenced" == "false" ]] && [[ -d "${GLOBAL_CLAUDE_DIR}/commands" ]]; then
            if grep -rq "$path_pattern" "${GLOBAL_CLAUDE_DIR}/commands/" 2>/dev/null; then
                referenced=true
            fi
        fi
    fi

    # DO NOT check INDEX.md or docs/ references
    # Scripts with only INDEX/docs references are still orphans
    # They need to be directly invoked by commands/agents/scripts

    echo "$referenced"
}

# Function to check if script is one-time fix
is_one_time_fix() {
    local script_name="$1"

    for pattern in "${ONE_TIME_PATTERNS[@]}"; do
        if [[ "$script_name" == *"$pattern"* ]]; then
            echo "true"
            return
        fi
    done

    echo "false"
}

# Function to check for corresponding report
# NOTE: Has_report does NOT affect orphan status
# Scripts with only docs/reports references are STILL orphans
has_report() {
    local script_file="$1"
    local script_name
    script_name=$(basename "$script_file")
    local script_name_no_ext="${script_name%.*}"
    local script_dir
    script_dir=$(dirname "$script_file")

    # Always return false - docs/reports don't count as functional references
    echo "false"
}

# Function to get last modified time
get_last_modified() {
    local file="$1"
    local current_time
    current_time=$(date +%s)
    local file_mtime
    file_mtime=$(stat -c %Y "$file" 2>/dev/null || stat -f %m "$file" 2>/dev/null)
    local days_ago=$(( (current_time - file_mtime) / 86400 ))
    echo "${days_ago} days ago"
}

# Function to get commit count
get_commit_count() {
    local file="$1"
    local count
    if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
        count=$(git log --follow --oneline -- "$file" 2>/dev/null | wc -l | tr -d ' ' || echo "0")
        # Handle case where file is outside git repo
        if [[ -z "$count" ]] || [[ ! "$count" =~ ^[0-9]+$ ]]; then
            echo "0"
        else
            echo "$count"
        fi
    else
        echo "0"
    fi
}

# Severity thresholds (override via env vars)
ORPHAN_ONE_TIME_COMMIT_THRESHOLD="${ORPHAN_ONE_TIME_COMMIT_THRESHOLD:-3}"
ORPHAN_ONE_TIME_DAYS_THRESHOLD="${ORPHAN_ONE_TIME_DAYS_THRESHOLD:-30}"
ORPHAN_MAJOR_COMMIT_THRESHOLD="${ORPHAN_MAJOR_COMMIT_THRESHOLD:-2}"
ORPHAN_MAJOR_DAYS_THRESHOLD="${ORPHAN_MAJOR_DAYS_THRESHOLD:-60}"

# Function to determine severity
get_severity() {
    local is_one_time="$1"
    local commit_count="$2"
    local days_ago="$3"

    # Extract numeric value from "X days ago"
    local days=${days_ago%% *}

    if [[ "$is_one_time" == "true" ]] && [[ $commit_count -le $ORPHAN_ONE_TIME_COMMIT_THRESHOLD ]] && [[ $days -gt $ORPHAN_ONE_TIME_DAYS_THRESHOLD ]]; then
        echo "major"
    elif [[ $commit_count -le $ORPHAN_MAJOR_COMMIT_THRESHOLD ]] && [[ $days -gt $ORPHAN_MAJOR_DAYS_THRESHOLD ]]; then
        echo "major"
    else
        echo "minor"
    fi
}

# Scan scripts in local scripts/ directory
if [[ -d "scripts" ]]; then
    while IFS= read -r -d '' script_file; do
        script_name=$(basename "$script_file")

        # Check if referenced
        is_referenced=$(check_script_references "$script_file")

        if [[ "$is_referenced" == "false" ]]; then
            is_one_time=$(is_one_time_fix "$script_name")
            has_report_file=$(has_report "$script_file")
            last_modified=$(get_last_modified "$script_file")
            commit_count=$(get_commit_count "$script_file")
            severity=$(get_severity "$is_one_time" "$commit_count" "$last_modified")

            # Build JSON object
            if [[ -n "$orphan_scripts" ]]; then
                orphan_scripts="${orphan_scripts},"
            fi

            orphan_scripts="${orphan_scripts}
    {
      \"file\": \"${script_file}\",
      \"reason\": \"No references in commands/agents/scripts\",
      \"one_time_fix\": ${is_one_time},
      \"has_report\": ${has_report_file},
      \"last_modified\": \"${last_modified}\",
      \"commit_count\": ${commit_count},
      \"severity\": \"${severity}\"
    }"

            total_count=$((total_count + 1))
            if [[ "$is_one_time" == "true" ]]; then
                one_time_fix_count=$((one_time_fix_count + 1))
            else
                general_orphan_count=$((general_orphan_count + 1))
            fi
        fi
    done < <(find scripts/ -type f \( -name "*.sh" -o -name "*.py" \) -print0 2>/dev/null)
fi

# Scan scripts in global ~/.claude/scripts/ directory
if [[ -d "${GLOBAL_CLAUDE_DIR}/scripts" ]]; then
    while IFS= read -r -d '' script_file; do
        script_name=$(basename "$script_file")

        # Skip INDEX.md and README.md
        [[ "$script_name" == "INDEX.md" ]] && continue
        [[ "$script_name" == "README.md" ]] && continue

        # Skip todo scripts (they are managed separately)
        [[ "$script_file" == *"/todo/"* ]] && continue

        # Check if referenced
        is_referenced=$(check_script_references "$script_file")

        if [[ "$is_referenced" == "false" ]]; then
            is_one_time=$(is_one_time_fix "$script_name")
            has_report_file=$(has_report "$script_file")
            last_modified=$(get_last_modified "$script_file")
            commit_count=$(get_commit_count "$script_file")
            severity=$(get_severity "$is_one_time" "$commit_count" "$last_modified")

            # Build JSON object
            if [[ -n "$orphan_scripts" ]]; then
                orphan_scripts="${orphan_scripts},"
            fi

            orphan_scripts="${orphan_scripts}
    {
      \"file\": \"${script_file}\",
      \"reason\": \"No references in commands/agents/scripts\",
      \"one_time_fix\": ${is_one_time},
      \"has_report\": ${has_report_file},
      \"last_modified\": \"${last_modified}\",
      \"commit_count\": ${commit_count},
      \"severity\": \"${severity}\"
    }"

            total_count=$((total_count + 1))
            if [[ "$is_one_time" == "true" ]]; then
                one_time_fix_count=$((one_time_fix_count + 1))
            else
                general_orphan_count=$((general_orphan_count + 1))
            fi
        fi
    done < <(find "${GLOBAL_CLAUDE_DIR}/scripts/" -type f \( -name "*.sh" -o -name "*.py" \) -not -path "*/todo/*" -print0 2>/dev/null)
fi

# Output JSON
cat <<EOF
{
  "orphan_scripts": [${orphan_scripts}
  ],
  "summary": {
    "total": ${total_count},
    "one_time_fixes": ${one_time_fix_count},
    "general_orphans": ${general_orphan_count}
  }
}
EOF

exit 0
