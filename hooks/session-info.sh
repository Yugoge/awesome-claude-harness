#!/bin/bash
# session-info.sh — SessionStart: the session's directory, git state and project metadata, for the model.
# A SessionStart hook's plain-text stdout is added to the model's context
# (code.claude.com/docs/en/hooks, "SessionStart"); only a JSON object on stdout is parsed as
# control. Stderr on exit 0 reaches no one, which is where this banner used to go.
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/harness_switch.sh" 2>/dev/null && harness_switch_exit_if_off  # the harness switch: no harness hook runs while /harness off holds

echo "Session info:"
echo "  Dir: $(pwd)"

# Git info
if [ -d .git ]; then
    branch=$(git branch --show-current 2>/dev/null || echo "detached")
    modified=$(git status --porcelain 2>/dev/null | wc -l)
    if [ "$modified" -gt 0 ]; then
        echo "  Git: $branch  (! $modified uncommitted files)"
    else
        echo "  Git: $branch  (clean)"
    fi
fi

# Project metadata
[ -f .claude/CLAUDE.md ] && echo "  CLAUDE.md: project instructions loaded"
cmd_count=$(find .claude/commands -name "*.md" 2>/dev/null | wc -l)
agent_count=$(find .claude/agents -name "*.md" 2>/dev/null | wc -l)
[ "$cmd_count" -gt 0 ] && echo "  Commands:  $cmd_count available"
[ "$agent_count" -gt 0 ] && echo "  Agents:    $agent_count available"

# The checklist gates read TodoWrite, which the CLI offers only while CLAUDE_CODE_ENABLE_TASKS reads
# false (settings.json env pins it); the Stop gate names the same gap (stop-command-gate.py todo_gaps).
tasks=${CLAUDE_CODE_ENABLE_TASKS-}
tasks=${tasks#"${tasks%%[![:space:]]*}"}  # trim both ends and lowercase, as the CLI reads the switch
tasks=${tasks%"${tasks##*[![:space:]]}"}
tasks=$(printf '%s' "$tasks" | tr '[:upper:]' '[:lower:]')  # tr, not ${,,}: macOS ships bash 3.2
case "$tasks" in
    0|false|no|off) ;;
    *) echo "WARNING: CLAUDE_CODE_ENABLE_TASKS is '${CLAUDE_CODE_ENABLE_TASKS-}', not false: this session has the Task tools, not TodoWrite, and gated commands cannot end (settings.json env pins it to false)" ;;
esac
exit 0
