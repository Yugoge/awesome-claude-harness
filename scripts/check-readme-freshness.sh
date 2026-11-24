#!/bin/bash
# Check README.md freshness for all major folders
# Outputs JSON array with stale days and required action
# Usage: check-readme-freshness.sh /path/to/project [max_depth] [full_threshold_days] [incremental_threshold_days] [folders...]

set -euo pipefail

PROJECT_ROOT="${1:-.}"
# Override via CLI: max directory depth for find commands (default 2)
MAX_DEPTH="${2:-${README_MAX_DEPTH:-2}}"
# Override via CLI: days before a README is considered fully stale (default 7)
FULL_THRESHOLD="${3:-${README_FULL_THRESHOLD:-7}}"
# Override via CLI: days before a README needs incremental update (default 3)
INCREMENTAL_THRESHOLD="${4:-${README_INCREMENTAL_THRESHOLD:-3}}"
NOW=$(date +%s)

# Major folders to check (root + top-level); override via CLI args 5+
if [[ $# -ge 5 ]]; then
    shift 4
    FOLDERS=("$@")
else
    FOLDERS=(${README_FOLDERS:-". scripts data docs tests config tmp backups output"})
fi

echo "["
FIRST=true

for folder in "${FOLDERS[@]}"; do
  FOLDER_PATH="$PROJECT_ROOT/$folder"
  [[ ! -d "$FOLDER_PATH" ]] && continue

  README_PATH="$FOLDER_PATH/README.md"

  # Get latest content modification time in folder (excluding README itself)
  CONTENT_MTIME=$(find "$FOLDER_PATH" -maxdepth "$MAX_DEPTH" -type f ! -name "README.md" ! -name "INDEX.md" ! -path "*/.git/*" ! -path "*/venv/*" ! -path "*/__pycache__/*" -printf '%T@\n' 2>/dev/null | sort -rn | head -1)
  CONTENT_MTIME=${CONTENT_MTIME%.*}
  CONTENT_MTIME=${CONTENT_MTIME:-$NOW}

  if [[ -f "$README_PATH" ]]; then
    README_MTIME=$(stat -c %Y "$README_PATH")
    STALE_SECONDS=$((CONTENT_MTIME - README_MTIME))
    STALE_DAYS=$((STALE_SECONDS / 86400))
    [[ $STALE_DAYS -lt 0 ]] && STALE_DAYS=0

    if [[ $STALE_DAYS -gt $FULL_THRESHOLD ]]; then
      ACTION="FULL_UPDATE_REQUIRED"
    elif [[ $STALE_DAYS -gt $INCREMENTAL_THRESHOLD ]]; then
      ACTION="INCREMENTAL_UPDATE"
    else
      ACTION="FRESH"
    fi

    # Count lines to gauge README size
    LINE_COUNT=$(wc -l < "$README_PATH")
  else
    STALE_DAYS=-1
    ACTION="CREATE_NEW"
    README_MTIME=0
    LINE_COUNT=0
  fi

  FILE_COUNT=$(find "$FOLDER_PATH" -maxdepth "$MAX_DEPTH" -type f ! -path "*/.git/*" ! -path "*/venv/*" ! -path "*/__pycache__/*" 2>/dev/null | wc -l)

  SUBFOLDER_COUNT=$(find "$FOLDER_PATH" -mindepth 1 -maxdepth 1 -type d ! -name ".git" ! -name "venv" ! -name "__pycache__" 2>/dev/null | wc -l)

  $FIRST || echo ","
  FIRST=false

  cat <<ENTRY
  {
    "folder": "$folder",
    "readme_exists": $([ -f "$README_PATH" ] && echo true || echo false),
    "stale_days": $STALE_DAYS,
    "action": "$ACTION",
    "readme_lines": $LINE_COUNT,
    "file_count": $FILE_COUNT,
    "subfolder_count": $SUBFOLDER_COUNT
  }
ENTRY

done

echo "]"
