#!/bin/bash
# audit-slashcommand.sh
# Audit logging for slash command usage
# Location: ~/.claude/hooks/audit-slashcommand.sh
# Usage: Automatically called by PostToolUse hooks when SlashCommand is invoked

# Create logs directory if it doesn't exist
LOGS_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/logs"
mkdir -p "$LOGS_DIR"

# Audit log file
AUDIT_LOG="$LOGS_DIR/slashcommand-audit.log"

# Get current timestamp
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Get current working directory
WORKDIR=$(pwd)

# Try to extract command from stdin (if available from hook)
# Format expected: {"tool": "SlashCommand", "arguments": {"command": "/think ..."}}
COMMAND_INFO="unknown"
if [ -t 0 ]; then
  # No stdin (interactive mode)
  COMMAND_INFO="interactive"
else
  # Try to read from stdin
  INPUT=$(cat)
  if command -v jq &> /dev/null; then
    # If jq is available, parse JSON
    COMMAND_INFO=$(echo "$INPUT" | jq -r '.arguments.command // "unknown"' 2>/dev/null || echo "parse-failed")
  else
    # Fallback: simple grep
    COMMAND_INFO=$(echo "$INPUT" | grep -oP '(?<="command":").*?(?=")' | head -1 || echo "no-jq")
  fi
fi

# Log entry format: timestamp|workdir|command
echo "${TIMESTAMP}|${WORKDIR}|${COMMAND_INFO}" >> "$AUDIT_LOG"

# Optional: Also log to system log
# logger -t claude-slashcommand "Command: $COMMAND_INFO in $WORKDIR"

# Exit successfully (don't block operation)
exit 0
