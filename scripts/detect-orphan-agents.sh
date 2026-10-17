#!/usr/bin/env bash
# Description: Detect agents not referenced by any command
# Usage: detect-orphan-agents.sh [project-root]
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

# Exception list: agents invoked dynamically by orchestrators
WORKFLOW_ORCHESTRATED_AGENTS=(
    "git-edge-case-analyst"    # Invoked by /test Step 1 for git history analysis
    "cleaner"                   # Invoked by /clean workflow Step 11
    "layout-optimizer"            # Invoked by resume optimization workflows
    "rule-inspector"              # Invoked by /clean workflow Step 4
    "style-inspector"             # Invoked by /clean workflow Step 6
    "prompt-inspector"            # Invoked by cleanup workflows
    "test-validator"              # Invoked by /test workflow
    "resume-critique"            # Invoked by resume workflows
    "resume-refiner"              # Invoked by resume workflows
    "resume-tailor"              # Invoked by resume workflows
    "cover-letter-writer"         # Invoked by job application workflows
    "job-parser"                 # Invoked by job application workflows
)

# Initialize JSON output
orphan_agents=""
total_count=0

# Function to check if agent is in exception list
is_excepted() {
    local agent_name="$1"

    for excepted_agent in "${WORKFLOW_ORCHESTRATED_AGENTS[@]}"; do
        if [[ "$agent_name" == "$excepted_agent" ]]; then
            echo "true"
            return
        fi
    done

    echo "false"
}

# Function to check if agent is referenced by commands
check_agent_references() {
    local agent_name="$1"

    local referenced=false

    # Check in .claude/commands/*.md (local)
    if [[ -d "${CLAUDE_DIR}/commands" ]]; then
        if grep -rqE "(subagent_type.*${agent_name}|Task.*${agent_name}|agents/${agent_name}\.md|${agent_name}-agent|Dispatch.*${agent_name})" "${CLAUDE_DIR}/commands/" 2>/dev/null; then
            referenced=true
        fi
    fi

    # Check in .claude/commands/*.md (global)
    if [[ -d "${GLOBAL_CLAUDE_DIR}/commands" ]]; then
        if grep -rqE "(subagent_type.*${agent_name}|Task.*${agent_name}|agents/${agent_name}\.md|${agent_name}-agent|Dispatch.*${agent_name})" "${GLOBAL_CLAUDE_DIR}/commands/" 2>/dev/null; then
            referenced=true
        fi
    fi

    # Also check in other agents (for orchestration patterns)
    if [[ -d "${CLAUDE_DIR}/agents" ]]; then
        local agent_refs
        agent_refs=$(grep -rE "(subagent_type.*${agent_name}|Task.*${agent_name}|${agent_name}-agent|Dispatch.*${agent_name})" "${CLAUDE_DIR}/agents/" 2>/dev/null | grep -v "agents/${agent_name}.md" || true)
        if [[ -n "$agent_refs" ]]; then
            referenced=true
        fi
    fi

    if [[ -d "${GLOBAL_CLAUDE_DIR}/agents" ]]; then
        local global_agent_refs
        global_agent_refs=$(grep -rE "(subagent_type.*${agent_name}|Task.*${agent_name}|${agent_name}-agent|Dispatch.*${agent_name})" "${GLOBAL_CLAUDE_DIR}/agents/" 2>/dev/null | grep -v "agents/${agent_name}.md" || true)
        if [[ -n "$global_agent_refs" ]]; then
            referenced=true
        fi
    fi

    echo "$referenced"
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
ORPHAN_MAJOR_COMMIT_THRESHOLD="${ORPHAN_MAJOR_COMMIT_THRESHOLD:-2}"
ORPHAN_MAJOR_DAYS_THRESHOLD="${ORPHAN_MAJOR_DAYS_THRESHOLD:-60}"
ORPHAN_MAJOR_AGE_THRESHOLD="${ORPHAN_MAJOR_AGE_THRESHOLD:-90}"

# Function to determine severity
get_severity() {
    local commit_count="$1"
    local days_ago="$2"

    # Extract numeric value from "X days ago"
    local days=${days_ago%% *}

    if [[ $commit_count -le $ORPHAN_MAJOR_COMMIT_THRESHOLD ]] && [[ $days -gt $ORPHAN_MAJOR_DAYS_THRESHOLD ]]; then
        echo "major"
    elif [[ $days -gt $ORPHAN_MAJOR_AGE_THRESHOLD ]]; then
        echo "major"
    else
        echo "minor"
    fi
}

# Scan agents in local .claude/agents/ directory
if [[ -d "${CLAUDE_DIR}/agents" ]]; then
    for agent_file in "${CLAUDE_DIR}/agents/"*.md; do
        [[ ! -f "$agent_file" ]] && continue

        agent_name=$(basename "$agent_file" .md)

        # Skip INDEX.md and README.md
        [[ "$agent_name" == "INDEX" ]] && continue
        [[ "$agent_name" == "README" ]] && continue

        # Skip meta-agents
        [[ "$agent_name" =~ ^(orchestrator|dispatcher|coordinator)$ ]] && continue

        # Check exception list
        if [[ $(is_excepted "$agent_name") == "true" ]]; then
            continue
        fi

        # Check if referenced
        is_referenced=$(check_agent_references "$agent_name")

        if [[ "$is_referenced" == "false" ]]; then
            last_modified=$(get_last_modified "$agent_file")
            commit_count=$(get_commit_count "$agent_file")
            severity=$(get_severity "$commit_count" "$last_modified")

            # Build JSON object
            if [[ -n "$orphan_agents" ]]; then
                orphan_agents="${orphan_agents},"
            fi

            orphan_agents="${orphan_agents}
    {
      \"file\": \"${agent_file}\",
      \"reason\": \"Not referenced by any command\",
      \"last_modified\": \"${last_modified}\",
      \"commit_count\": ${commit_count},
      \"severity\": \"${severity}\"
    }"

            total_count=$((total_count + 1))
        fi
    done
fi

# Scan agents in global ~/.claude/agents/ directory
if [[ -d "${GLOBAL_CLAUDE_DIR}/agents" ]]; then
    for agent_file in "${GLOBAL_CLAUDE_DIR}/agents/"*.md; do
        [[ ! -f "$agent_file" ]] && continue

        agent_name=$(basename "$agent_file" .md)

        # Skip INDEX.md and README.md
        [[ "$agent_name" == "INDEX" ]] && continue
        [[ "$agent_name" == "README" ]] && continue

        # Skip meta-agents
        [[ "$agent_name" =~ ^(orchestrator|dispatcher|coordinator)$ ]] && continue

        # Check exception list
        if [[ $(is_excepted "$agent_name") == "true" ]]; then
            continue
        fi

        # Check if referenced
        is_referenced=$(check_agent_references "$agent_name")

        if [[ "$is_referenced" == "false" ]]; then
            last_modified=$(get_last_modified "$agent_file")
            commit_count=$(get_commit_count "$agent_file")
            severity=$(get_severity "$commit_count" "$last_modified")

            # Build JSON object
            if [[ -n "$orphan_agents" ]]; then
                orphan_agents="${orphan_agents},"
            fi

            orphan_agents="${orphan_agents}
    {
      \"file\": \"${agent_file}\",
      \"reason\": \"Not referenced by any command\",
      \"last_modified\": \"${last_modified}\",
      \"commit_count\": ${commit_count},
      \"severity\": \"${severity}\"
    }"

            total_count=$((total_count + 1))
        fi
    done
fi

# Output JSON
cat <<EOF
{
  "orphan_agents": [${orphan_agents}
  ],
  "summary": {
    "total": ${total_count}
  }
}
EOF

exit 0
