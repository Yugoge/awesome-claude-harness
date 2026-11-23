#!/usr/bin/env bash
# Description: Discover auditable files and split into groups for parallel style inspection
# Usage: plan-style-inspection.sh <project_root> [files_per_agent]
# Exit codes: 0=success, 1=failure

set -euo pipefail

PROJECT_ROOT="${1:?Missing required PROJECT_ROOT argument}"
FILES_PER_AGENT="${2:-5}"

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "Error: Directory not found: $PROJECT_ROOT" >&2
  exit 1
fi

if ! [[ "$FILES_PER_AGENT" =~ ^[0-9]+$ ]] || [[ "$FILES_PER_AGENT" -lt 1 ]]; then
  echo "Error: files_per_agent must be a positive integer, got: $FILES_PER_AGENT" >&2
  exit 1
fi

# Collect files by category (commands, agents, scripts) sorted alphabetically within each
ALL_FILES=()

# Category 1: Commands
while IFS= read -r f; do
  ALL_FILES+=("$f")
done < <(find "$PROJECT_ROOT/.claude/commands" -maxdepth 1 -name '*.md' -type f 2>/dev/null | sort)

# Category 2: Agents
while IFS= read -r f; do
  ALL_FILES+=("$f")
done < <(find "$PROJECT_ROOT/.claude/agents" -maxdepth 1 -name '*.md' -type f 2>/dev/null | sort)

# Category 3: Python scripts
while IFS= read -r f; do
  ALL_FILES+=("$f")
done < <(find "$PROJECT_ROOT/scripts" -maxdepth 2 -name '*.py' -type f 2>/dev/null | sort)

# Category 4: Shell scripts
while IFS= read -r f; do
  ALL_FILES+=("$f")
done < <(find "$PROJECT_ROOT/scripts" -maxdepth 2 -name '*.sh' -type f 2>/dev/null | sort)

TOTAL="${#ALL_FILES[@]}"

if [[ "$TOTAL" -eq 0 ]]; then
  # Output valid JSON with zero files
  echo '{"total_files":0,"files_per_agent":'"$FILES_PER_AGENT"',"agent_count":0,"groups":[],"all_files":[]}'
  exit 0
fi

# Calculate agent count (ceiling division)
AGENT_COUNT=$(( (TOTAL + FILES_PER_AGENT - 1) / FILES_PER_AGENT ))

# Build JSON output
# Use jq if available, otherwise build manually
if command -v jq &>/dev/null; then
  ALL_FILES_JSON=$(printf '%s\n' "${ALL_FILES[@]}" | jq -R . | jq -s .)

  GROUPS_JSON="[]"
  GROUP_ID=1
  for ((i=0; i<TOTAL; i+=FILES_PER_AGENT)); do
    END=$((i + FILES_PER_AGENT))
    [[ $END -gt $TOTAL ]] && END=$TOTAL

    GROUP_FILES_JSON=$(printf '%s\n' "${ALL_FILES[@]:i:FILES_PER_AGENT}" | jq -R . | jq -s .)

    GROUPS_JSON=$(echo "$GROUPS_JSON" | jq \
      --argjson gid "$GROUP_ID" \
      --argjson files "$GROUP_FILES_JSON" \
      '. + [{"group_id": $gid, "files": $files}]')

    GROUP_ID=$((GROUP_ID + 1))
  done

  jq -n \
    --argjson total "$TOTAL" \
    --argjson fpa "$FILES_PER_AGENT" \
    --argjson ac "$AGENT_COUNT" \
    --argjson groups "$GROUPS_JSON" \
    --argjson all "$ALL_FILES_JSON" \
    '{
      total_files: $total,
      files_per_agent: $fpa,
      agent_count: $ac,
      groups: $groups,
      all_files: $all
    }'
else
  # Fallback: build JSON manually without jq
  echo -n '{"total_files":'"$TOTAL"',"files_per_agent":'"$FILES_PER_AGENT"',"agent_count":'"$AGENT_COUNT"',"groups":['

  GROUP_ID=1
  for ((i=0; i<TOTAL; i+=FILES_PER_AGENT)); do
    [[ $i -gt 0 ]] && echo -n ','
    echo -n '{"group_id":'"$GROUP_ID"',"files":['

    END=$((i + FILES_PER_AGENT))
    [[ $END -gt $TOTAL ]] && END=$TOTAL
    FIRST=1
    for ((j=i; j<END; j++)); do
      [[ $FIRST -eq 0 ]] && echo -n ','
      FIRST=0
      # Escape quotes in filenames
      ESCAPED="${ALL_FILES[$j]//\\/\\\\}"
      ESCAPED="${ESCAPED//\"/\\\"}"
      echo -n '"'"$ESCAPED"'"'
    done

    echo -n ']}'
    GROUP_ID=$((GROUP_ID + 1))
  done

  echo -n '],"all_files":['
  FIRST=1
  for f in "${ALL_FILES[@]}"; do
    [[ $FIRST -eq 0 ]] && echo -n ','
    FIRST=0
    ESCAPED="${f//\\/\\\\}"
    ESCAPED="${ESCAPED//\"/\\\"}"
    echo -n '"'"$ESCAPED"'"'
  done
  echo ']}'
fi
