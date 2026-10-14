#!/usr/bin/env bash
# Description: Detect orphan commands (one-time patterns, no todo script, unused)
# Usage: detect-orphan-commands.sh [project-root]
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

# One-time command patterns
ONE_TIME_PATTERNS=("-fix" "-migrate" "-patch" "-migration" "-cleanup" "-repair")

# Initialize JSON output
orphan_commands=""
total_count=0

# Function to check if command has one-time pattern
has_one_time_pattern() {
    local command_name="$1"

    for pattern in "${ONE_TIME_PATTERNS[@]}"; do
        if [[ "$command_name" == *"$pattern"* ]]; then
            echo "true"
            return
        fi
    done

    echo "false"
}

# Function to check if command has corresponding todo script
has_todo_script() {
    local command_name="$1"

    # Check in global todo scripts
    if [[ -f "${GLOBAL_CLAUDE_DIR}/scripts/todo/${command_name}.py" ]] || \
       [[ -f "${GLOBAL_CLAUDE_DIR}/scripts/todo/${command_name}.sh" ]]; then
        echo "true"
        return
    fi

    # Check in local todo scripts
    if [[ -f "${CLAUDE_DIR}/scripts/todo/${command_name}.py" ]] || \
       [[ -f "${CLAUDE_DIR}/scripts/todo/${command_name}.sh" ]]; then
        echo "true"
        return
    fi

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

# Function to get days since modified
get_days_since_modified() {
    local file="$1"
    local current_time
    current_time=$(date +%s)
    local file_mtime
    file_mtime=$(stat -c %Y "$file" 2>/dev/null || stat -f %m "$file" 2>/dev/null)
    echo $(( (current_time - file_mtime) / 86400 ))
}

# Function to check if command was used recently in git log
check_recent_usage() {
    local command_name="$1"
    local days_threshold="${2:-90}"

    if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
        # Search for command invocation in commit messages
        local since_date
        since_date=$(date -d "${days_threshold} days ago" +%Y-%m-%d 2>/dev/null || date -v-${days_threshold}d +%Y-%m-%d 2>/dev/null)

        if git log --since="$since_date" --all --grep="/${command_name}" --oneline 2>/dev/null | grep -q .; then
            echo "true"
            return
        fi

        # Also check for command name in recent commits
        if git log --since="$since_date" --all --oneline 2>/dev/null | grep -qi "${command_name}"; then
            echo "true"
            return
        fi
    fi

    echo "false"
}

# Function to determine severity
get_severity() {
    local has_pattern="$1"
    local has_todo="$2"
    local days_ago="$3"

    if [[ "$has_pattern" == "true" ]] && [[ "$has_todo" == "false" ]]; then
        echo "minor"
    elif [[ $days_ago -gt 90 ]]; then
        echo "minor"
    else
        echo "minor"
    fi
}

# Function to determine reason
get_reason() {
    local has_pattern="$1"
    local has_todo="$2"
    local days_ago="$3"
    local recent_usage="$4"

    local reasons=()

    if [[ "$has_pattern" == "true" ]]; then
        reasons+=("One-time command pattern")
    fi

    if [[ "$has_todo" == "false" ]]; then
        reasons+=("no todo script")
    fi

    if [[ "$recent_usage" == "false" ]] && [[ $days_ago -gt 90 ]]; then
        reasons+=("unused for ${days_ago} days")
    fi

    # Join reasons
    local result=""
    for reason in "${reasons[@]}"; do
        if [[ -n "$result" ]]; then
            result="${result}, ${reason}"
        else
            result="$reason"
        fi
    done

    echo "$result"
}

# Scan commands in local .claude/commands/ directory
if [[ -d "${CLAUDE_DIR}/commands" ]]; then
    for command_file in "${CLAUDE_DIR}/commands/"*.md; do
        [[ ! -f "$command_file" ]] && continue

        command_name=$(basename "$command_file" .md)

        # Skip INDEX.md and README.md
        [[ "$command_name" == "INDEX" ]] && continue
        [[ "$command_name" == "README" ]] && continue

        # Check criteria
        has_pattern=$(has_one_time_pattern "$command_name")
        has_todo=$(has_todo_script "$command_name")
        days_ago=$(get_days_since_modified "$command_file")
        recent_usage=$(check_recent_usage "$command_name")

        # Determine if orphan
        is_orphan=false

        # Criteria 1: One-time pattern + no todo script
        if [[ "$has_pattern" == "true" ]] && [[ "$has_todo" == "false" ]]; then
            is_orphan=true
        fi

        # Criteria 2: Not used in 90+ days + no todo script
        if [[ "$recent_usage" == "false" ]] && [[ $days_ago -gt 90 ]] && [[ "$has_todo" == "false" ]]; then
            is_orphan=true
        fi

        if [[ "$is_orphan" == "true" ]]; then
            last_modified=$(get_last_modified "$command_file")
            reason=$(get_reason "$has_pattern" "$has_todo" "$days_ago" "$recent_usage")
            severity=$(get_severity "$has_pattern" "$has_todo" "$days_ago")

            # Build JSON object
            if [[ -n "$orphan_commands" ]]; then
                orphan_commands="${orphan_commands},"
            fi

            orphan_commands="${orphan_commands}
    {
      \"file\": \"${command_file}\",
      \"reason\": \"${reason}\",
      \"one_time_pattern\": ${has_pattern},
      \"last_modified\": \"${last_modified}\",
      \"severity\": \"${severity}\"
    }"

            total_count=$((total_count + 1))
        fi
    done
fi

# Scan commands in global ~/.claude/commands/ directory
if [[ -d "${GLOBAL_CLAUDE_DIR}/commands" ]]; then
    for command_file in "${GLOBAL_CLAUDE_DIR}/commands/"*.md; do
        [[ ! -f "$command_file" ]] && continue

        command_name=$(basename "$command_file" .md)

        # Skip INDEX.md and README.md
        [[ "$command_name" == "INDEX" ]] && continue
        [[ "$command_name" == "README" ]] && continue

        # Check criteria
        has_pattern=$(has_one_time_pattern "$command_name")
        has_todo=$(has_todo_script "$command_name")
        days_ago=$(get_days_since_modified "$command_file")
        recent_usage=$(check_recent_usage "$command_name")

        # Determine if orphan
        is_orphan=false

        # Criteria 1: One-time pattern + no todo script
        if [[ "$has_pattern" == "true" ]] && [[ "$has_todo" == "false" ]]; then
            is_orphan=true
        fi

        # Criteria 2: Not used in 90+ days + no todo script
        if [[ "$recent_usage" == "false" ]] && [[ $days_ago -gt 90 ]] && [[ "$has_todo" == "false" ]]; then
            is_orphan=true
        fi

        if [[ "$is_orphan" == "true" ]]; then
            last_modified=$(get_last_modified "$command_file")
            reason=$(get_reason "$has_pattern" "$has_todo" "$days_ago" "$recent_usage")
            severity=$(get_severity "$has_pattern" "$has_todo" "$days_ago")

            # Build JSON object
            if [[ -n "$orphan_commands" ]]; then
                orphan_commands="${orphan_commands},"
            fi

            orphan_commands="${orphan_commands}
    {
      \"file\": \"${command_file}\",
      \"reason\": \"${reason}\",
      \"one_time_pattern\": ${has_pattern},
      \"last_modified\": \"${last_modified}\",
      \"severity\": \"${severity}\"
    }"

            total_count=$((total_count + 1))
        fi
    done
fi

# Output JSON
cat <<EOF
{
  "orphan_commands": [${orphan_commands}
  ],
  "summary": {
    "total": ${total_count}
  }
}
EOF

exit 0
