# Infra-Hook Eval Case infra-hook-004: pretool-file-write-policy.py

## Trigger
PreToolUse with matcher `Write`. Hook fires before any Write tool
invocation regardless of caller (orchestrator or subagent).

## Behavior Required
- Reads PreToolUse hook input JSON on stdin.
- Parses `tool_input.file_path` and normalizes via `os.path.realpath`
  to defeat symlink-escape attempts.
- Maintains a deny-list of write-forbidden directories: `/etc/`,
  `/usr/`, `/var/lib/docker/`, `/proc/`, `/sys/`, and the production
  binary install paths from CLAUDE.md.
- Maintains an allow-list of permitted write roots: `/root/`, `/tmp/`,
  `/dev/shm/dev-workspace/`, the worktree paths, and `~/.claude/`.
- Emits structured stderr naming the rejected absolute path and the
  matched deny rule.

## Exit Code Contract
- exit 0: target path resolves under an allow-list root and not under
  any deny-list root.
- exit 2: target path resolves under a deny-list root or escapes the
  allow-list via `..` traversal.

## Acceptance
- AC-1: rejects Write to `/etc/passwd` with exit 2.
- AC-2: rejects Write to `/root/../etc/hosts` with exit 2 (path
  traversal).
- AC-3: allows Write to `/root/docs/dev/dev-report-foo.json` with
  exit 0.
