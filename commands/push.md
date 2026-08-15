---
description: "Push Command"
disable-model-invocation: true
---

# Push Command

`/push` is the validated wrapper for normal branch publication. Note: pretool-git-privilege-guard.py is REGISTERED in settings.json (PreToolUse, Bash matcher) and enforces commit authorization — agents must hold a valid commit grant or use the `auto-bulk:` bridge prefix to commit. The wrapper
script `~/.claude/hooks/push.sh` produces a valid push grant recognized by the guard.

The slash entry has `disable-model-invocation: true` to prevent the model
from autonomously self-dispatching `/push` via SlashCommand. It does NOT
forbid agent execution of the wrapper script. When the user invokes
`/push` in conversation and this docstring is injected into the agent's
context, the agent's correct response is to execute the **Agentic dispatch
protocol** documented below (Steps 0-5), then call `push.sh` ONLY after
push-analyst grant validation passes. Do NOT call `push.sh` directly
without first dispatching `push-analyst` — the analyst gate is mandatory.
Do NOT bounce the work back to the user with "please run X manually" —
that violates the harness's delegation design.

## Usage

```bash
/push
/push <remote>
```

No force, delete, or ref-rewrite mode is available through `/push`. The wrapper
accepts only an optional remote and `--auto` for non-interactive lock handling.

## Behavior summary

1. Refuse detached HEAD.
2. Print staged / modified / untracked files for context only.
3. Treat dirty worktree state as non-blocking; only committed objects push.
4. Exit cleanly when there is nothing ahead of upstream.
5. Emit a single-use push grant binding branch, current HEAD, remote, SID,
   nonce, ppid, and timestamp.
6. Export the wrapper-only push env var for the child process.
7. Run a normal branch push, with `-u` only when setting an upstream.
8. Append the push audit log on success.

## Safety contract

- `/push` never stages, commits, resets, deletes branches, force-publishes, or
  mutates refs directly.
- `--force`, `-f`, `--force-with-lease`, `--delete`, `-d`, and `--mirror`
  fail with exit 2 before any grant is written.
- Automatic post-commit backup is separate from `/push` and uses only
  `refs/backups/claude/<branch>/<short-sha>` recovery refs. It never publishes
  `refs/heads/<branch>` in the background.

## Session commit prerequisite (push-gate)

`/push` requires a valid push-gate token written by a prior `/commit` in this session.

Token location: `/tmp/agentic-commit/push/<repo-hash>/<session-digest>/<branch-encoded>.json`

- `repo-hash` = `sha256(os.path.realpath(repo_root)).hexdigest()[:16]`
- `session-digest` = `sha256(<raw session id>).hexdigest()[:16]`, where the raw session id is
  `CLAUDE_CODE_SESSION_ID`, else `CLAUDE_SESSION_ID`, else the literal `unknown`. The raw id is
  digested rather than used verbatim because it becomes a path segment and arrives from the
  environment: a value carrying `/` or `..` would escape the session directory, and two ids
  normalizing to the same segment would recreate the very collision session-scoping removes.
- `branch-encoded` = branch name with `/` replaced by `__`
- Token content: `{"commit_sha": "<sha>", "branch": "<branch>", "repo_root": "<root>"}`
- Legacy fallback: a session-less token at `/tmp/agentic-commit/push/<repo-hash>/<branch-encoded>.json`,
  written by a pre-migration `/commit`, is still honoured by `push.sh` when no session-scoped token
  exists. Pre-validation MUST check that path too — aborting because the session-scoped path alone
  is empty makes the fallback unreachable through this wrapper.

**Rejection conditions** (push is blocked if any hold):
- No token file at either the session-scoped or the legacy path (no `/commit` ran in this session)
- Token `commit_sha` does not match current `git rev-parse HEAD` (HEAD moved since commit)

**Resolution**: run `/commit [<task-id>]` first. The `changelog-analyst` subagent writes
the token after a successful real-branch commit. The token is consumed (deleted) after
a successful push.

**Guard registration note**: `pretool-git-privilege-guard.py` is REGISTERED in `settings.json` (PreToolUse, Bash matcher). changelog-analyst commits require either a valid commit grant (written by `/commit` Step 5) or the `auto-bulk:` prefix (matched by `BLESSED_BRIDGE_RE`). Direct `git commit` by agents without a grant or blessed prefix is blocked.

## Pre-conditions for success

- On a real branch.
- Branch has commits ahead of upstream, or has no upstream yet.
- The selected remote exists locally.
- A valid push-gate token exists at the path above (see Session commit prerequisite).

## Exit codes

| Exit | Meaning |
|------|---------|
| 0    | Push succeeded, or nothing to push |
| 1    | Detached HEAD, missing remote, or normal push failure |
| 2    | Blocked option such as force/delete/ref-rewrite mode |

## Agentic dispatch protocol (pre-execution)

Before calling `push.sh`, the orchestrator MUST execute the following steps in order:

**Step 0: Parse arguments and resolve remote**

Parse user-supplied arguments (optional `<remote>`, optional `--auto`). Resolve the push
target remote using the same fork-prefer-origin logic as push.sh lines 38-42:

```bash
if git remote get-url fork >/dev/null 2>&1; then
    RESOLVED_REMOTE="fork"
else
    RESOLVED_REMOTE="origin"
fi
# Explicit user-provided remote argument overrides the above
```

**Step 1: Validate push-gate token (Chain A — existing, unchanged)**

This is the existing session commit prerequisite check. Verify the push-gate token at
`/tmp/agentic-commit/push/<repo-hash>/<branch-encoded>.json` exists and that its
`commit_sha` matches the current `git rev-parse HEAD`. If the token is absent or
mismatched, abort and instruct the user to run `/commit` first.

**Step 2: Compute pre-push snapshot**

```bash
PRE_HEAD=$(git rev-parse HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD)
REMOTE_URL=$(git remote get-url "${RESOLVED_REMOTE}" 2>/dev/null || echo "unknown")
REPO_ROOT=$(realpath "$(git rev-parse --show-toplevel)")
REPO_HASH=$(printf '%s' "${REPO_ROOT}" | sha256sum | cut -c1-16)
REQUEST_ID=$(openssl rand -hex 16)
SESSION_ID="${CLAUDE_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-}}"
```

If `SESSION_ID` is empty or unset, abort immediately with:
"Cannot dispatch push-analyst: CLAUDE_SESSION_ID (and CLAUDE_CODE_SESSION_ID) not set. Invoke /push from within a Claude Code session."

**Step 3: Dispatch push-analyst subagent**

Dispatch the `push-analyst` subagent with the following context:

```
BRANCH=<BRANCH>
PRE_HEAD=<PRE_HEAD>
REMOTE_NAME=<RESOLVED_REMOTE>
REMOTE_URL=<REMOTE_URL>
REQUEST_ID=<REQUEST_ID>
SESSION_ID=<SESSION_ID>
REPO_HASH=<REPO_HASH>
```

Wait for the subagent to complete before proceeding.

**Step 4: Grant validation and sentinel write (Chain B) — performed by execute-push.py**

`execute-push.py` (Step 5) is the sole grant validator and consumer. The orchestrator
MUST NOT manually read, validate, or unlink the push-analyst grant file. Pass all Step 2
snapshot values to the script directly. No subagent delegation.

For reference, the script validates the following grant fields from
`/tmp/agentic-commit/push-analyst/<REPO_HASH>/<SESSION_ID>/<REQUEST_ID>.json`:
- File exists and is valid JSON
- `nonce` field matches `REQUEST_ID`
- `branch` field matches `BRANCH`
- `head_sha` field matches current `git rev-parse HEAD` (single drift check at step 9)
- `remote_name` field matches `RESOLVED_REMOTE`
- `session_id` field matches `SESSION_ID`
- `verdict` field is one of: `"approved"`, `"warn"`, `"blocked"`
- `risks` field is a JSON array
- `expires_at` is in the future (ISO-8601 UTC, Z-suffix normalized)

The script applies verdict logic, consumes the grant, writes the Chain-B sentinel
atomically, and exec's push.sh — all in a single process. See Step 5.

**Step 5: Call push.sh via execute-push.py (single-process pattern)**

> **WARNING — ORCHESTRATOR MUST EXECUTE DIRECTLY, NOT VIA SUBAGENT**: Steps 4 and 5
> MUST NOT be delegated to a subagent. Two reasons: (a) subagents legitimately reject
> writing the Chain-B sentinel as a privilege escalation; (b) the Chain-B sentinel's
> 60-second mtime gate in `push.sh` cannot survive two sequential agent dispatch delays
> (30-90s each). The orchestrator MUST run the bash invocation below directly.

Per task 20260519-211515 R1 / AC1, validate-push and the actual push MUST be a
**single-process exec pattern** — `execute-push.py` writes a Chain-B success
sentinel at
`/tmp/agentic-commit/push-analyst/<REPO_HASH>/<BRANCH_ENCODED>-chainB.validated.sentinel.json`
(atomic temp+rename, mtime ≤ 60s, bound to `request_id` + `head` + `branch` + `remote`)
and then `os.execv`s `~/.claude/hooks/push.sh` so both run as ONE PID. The sentinel
is read ONLY once from inside push.sh; missing / expired / FAIL / mismatched sentinel
triggers `exit 1` BEFORE any `git push` is reached.

```bash
# Without --auto:
python3 ~/.claude/scripts/execute-push.py \
  --repo-hash "${REPO_HASH}" \
  --branch "${BRANCH}" \
  --remote "${RESOLVED_REMOTE}" \
  --request-id "${REQUEST_ID}" \
  --repo-root "${REPO_ROOT}"

# With --auto (only when /push was invoked with --auto):
python3 ~/.claude/scripts/execute-push.py \
  --repo-hash "${REPO_HASH}" \
  --branch "${BRANCH}" \
  --remote "${RESOLVED_REMOTE}" \
  --request-id "${REQUEST_ID}" \
  --repo-root "${REPO_ROOT}" \
  --auto
```

This script validates the grant (non-head_sha fields), acts on verdict, checks HEAD drift
(single check: grant.head_sha vs current HEAD), consumes the grant, writes the Chain-B
sentinel atomically, and replaces itself with push.sh via `os.execv`. No subagent
delegation. No `&&` chaining. The orchestrator calls this directly.

`--auto` is a boolean flag with no value argument. Do NOT pass `--auto "$AUTO"`.
`CLAUDE_SESSION_ID` is read from the environment automatically; do NOT pass it as a
CLI argument.

Note: `python3` is used directly (no venv activation needed) because the script
uses only Python stdlib modules (argparse, json, os, subprocess, sys, tempfile,
datetime, pathlib). This matches the `Bash(python3:*)` allow entry in settings.json
— no additional permission is required.

## Push-analyst grant TTL

The push-analyst writes its Chain-B grant with a default TTL of
`PUSH_ANALYST_GRANT_TTL_SECONDS = 600` seconds (10 minutes) — raised from 120s
to 180s in task 20260519-211515 R4 / AC4, then raised from 180s to 600s in task
dev-20260527-063758-T3 to cover the full orchestrator → push-analyst →
orchestrator result-processing → execute-push.py round trip, which frequently
exceeded the previous 180s window. The 600s TTL is the named constant defined in
`agents/push-analyst.md` Phase 7. The commit-grant mechanism at
`scripts/write-commit-grant.py` (`GRANT_TTL_MINUTES = 30`) is a DIFFERENT
mechanism and has since been updated to 30.

## Related

- `/commit <task-id>` — automatic semantic commit for a closed task.
- Direct `git push` — agents must use `/push` via the wrapper script; the privilege guard is registered and enforces commit authorization before push is meaningful.
