#!/bin/bash
# posttool-git-warn.sh - PostToolUse (Bash): after a git commit, tell the model which files it left untracked.
#
# On when GIT_WARN_UNTRACKED=1 (settings.json sets it). A matcher matches the tool's name,
# which is "Bash" for every shell call, so the hook is registered on Bash and finds the
# commit in the command it is given on stdin (the CLI passes hook input on stdin only).
# PostToolUse runs only after the command succeeded. The warning goes to the model as
# PostToolUse additionalContext; plain stdout would reach no one. It names where the files are (each
# top-level directory with its count), not the files.

if [ "$GIT_WARN_UNTRACKED" != "1" ]; then
  exit 0
fi

INPUT=$(cat 2>/dev/null || true)
case "$INPUT" in
  *commit*) ;;
  *) exit 0 ;;   # no git commit in this call: nothing to check
esac

printf '%s' "$INPUT" | python3 -c '
import json, re, subprocess, sys
try:
    data = json.load(sys.stdin)
    command = (data.get("tool_input") or {}).get("command") or ""
except Exception:
    sys.exit(0)
if data.get("tool_name") != "Bash" or not re.search(r"(?:^|[\s;&|()`])git(?:\s+-C\s+\S+)?\s+commit(?![\w-])", command):
    sys.exit(0)
try:
    out = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                         capture_output=True, text=True, timeout=10).stdout
except Exception:
    sys.exit(0)
files = [line for line in out.splitlines() if line]
if not files:
    sys.exit(0)
# Where they are, by top-level entry, not their names: a name can carry a task or spec id, and
# an id this hook prints that its payload did not hold would read as one it minted.
where = {}
for f in files:
    top = f.split("/", 1)[0] + ("/" if "/" in f else "")
    where[top] = where.get(top, 0) + 1
shown = [f"{top} ({n})" if top.endswith("/") else top for top, n in sorted(where.items())]
text = "\n".join([f"Warning: {len(files)} untracked file(s) after this commit, in: " + ", ".join(shown[:20])
                  + (f", and {len(shown) - 20} more" if len(shown) > 20 else ""),
                  "Run git status to see them; commit them with /commit if they belong to the change, "
                  "or add them to .gitignore."])
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
' 2>/dev/null

exit 0
