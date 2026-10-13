#!/bin/bash
# single.sh <hook-relpath> <json-payload>  -- run one hook directly, print rc + output (inside ns)
H="$1"; P="$2"
case "$H" in *.py) I=python3;; *) I=bash;; esac
out=$(printf '%s' "$P" | env -i PATH="$PATH" HOME=/root CLAUDE_PROJECT_DIR=/root/toyproj TMPDIR=/var/tmp/claude-scratch $I "/root/.claude/hooks/$H" 2>/tmp/.e); rc=$?
echo "rc=$rc stdout=$(echo "$out" | head -c 300 | tr '\n' ' ') stderr=$(head -c 400 /tmp/.e | tr '\n' ' ')"
