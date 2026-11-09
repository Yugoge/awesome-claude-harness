# Infra-Hook Eval Case infra-hook-002: pretool-git-safety.py

## Trigger
PreToolUse with matcher `Bash`. Hook fires before any Bash invocation
that contains a `git` verb in the tokenized command line.

## Behavior Required
- Reads PreToolUse hook input JSON from stdin and parses `tool_name`
  and `tool_input.command`.
- Tokenizes the command and detects history-mutating git verbs
  (`reset --hard`, `push --force`, `branch -D`, `revert <hash>`).
- Allows whitelisted read-only git verbs (`status`, `log`, `diff`,
  `show`, `blame`, `ls-files`) without comment.
- Blocks history-mutating verbs with structured stderr describing the
  rejected verb and the safety rule citation.
- Distinguishes orchestrator-allowed forms from subagent-blocked forms
  using the presence of `agent_id` in the hook input.

## Exit Code Contract
- exit 0: command is read-only or is a non-history-mutating git verb.
- exit 2: command is history-mutating AND caller is a subagent OR is
  globally blocked (e.g., `push --force` to `main`).

## Acceptance
- AC-1: rejects `git reset --hard HEAD~3` when `agent_id` present with
  exit 2 and stderr containing the verb name.
- AC-2: allows `git status` and `git log --oneline` with exit 0 and
  empty stderr.
- AC-3: rejects `git push --force origin main` regardless of caller.
