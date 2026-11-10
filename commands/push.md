---
description: "Push Command"
disable-model-invocation: true
summary: "Publish the current branch through the push wrapper after the push analyst reviews what would go out; it needs a commit made by /commit."
group: Ship
---

# Push Command

`/push [<remote>] [--auto]` publishes the current branch through the wrapper `<HARNESS_ROOT>/hooks/push.sh`, after the push-analyst has reviewed what would go out. Run the dispatch protocol below yourself, in order, and reach `push.sh` only through Step 5. Do not hand the push back to the user as "please run X". `disable-model-invocation: true` only stops the model from invoking the slash command on its own; it does not forbid running the wrapper.

`/push` never stages, commits, resets, deletes branches or writes refs itself, and has no force, delete or ref-rewrite mode: push.sh refuses `--force`, `-f`, `--force-with-lease`, `--delete`, `-d` and `--mirror` with exit 2 before any grant is written. A dirty worktree does not block it (only committed objects are pushed), and push.sh exits 0 when nothing is ahead of `refs/remotes/<remote>/<branch>`. Never run `git push` directly (`hooks/pretool-git-privilege-guard.py`).

## Session commit prerequisite (push-gate)

`hooks/push.sh` is the push-gate token's one decider: it exits 3 unless some token for this branch, written by any session's `/commit` (`scripts/write-push-gate-token.py`), names a commit that is an ancestor of HEAD, not necessarily HEAD itself (on a shared branch, equality would let any session's next commit void every other session's token). Run `/commit [<task-id>]` in any session to mint one; a successful push consumes it.

## Exit codes

| Exit | Meaning |
|------|---------|
| 0    | Push succeeded, or nothing to push |
| 1    | Detached HEAD, missing remote, or normal push failure |
| 2    | Blocked option such as force/delete/ref-rewrite mode |
| 3    | No push-gate token names an ancestor of HEAD |

## Agentic dispatch protocol (pre-execution)

Run these steps in order. Where one refuses, ask ONE AskUserQuestion in this turn instead of exiting: the question is the refusal's message with its facts; the options are the action the refusal names, marked (Recommended), and "I give another instruction". Act on the answer; a refusal met again after it is reported in the reply, not asked again.

**Step 0: Parse arguments and resolve remote**

Read the typed arguments: an optional `<remote>` and an optional `--auto`. Step 2's call resolves the remote: the typed one, else `fork` when that remote exists locally, else `origin`.

**Step 1: Push-gate token (Chain A)**

`push.sh` is the push-gate token's one decider (Session commit prerequisite): it exits 3 when no token names an ancestor of HEAD. This step reads nothing; go on to Step 2.

**Step 2: Compute pre-push snapshot**

```bash
# Bare /push:
python3 "<HARNESS_ROOT>/scripts/steps/push-snapshot.py"

# /push <remote>:
python3 "<HARNESS_ROOT>/scripts/steps/push-snapshot.py" --remote <remote>
```

It prints `KEY=value` lines: `BRANCH`, `PRE_HEAD`, `RESOLVED_REMOTE`, `DEFAULT_REMOTE` (what a bare `/push` targets), `REMOTE_URL` (`unknown` when that remote does not exist), `REQUEST_ID`, `SESSION_ID`, `REPO_ROOT` and `REPO_HASH`. Later steps are separate calls: copy these values from the output into the placeholders of the same name.

If `BRANCH` is `HEAD`, refuse: "HEAD is detached" (action "check out the branch to push"). If `SESSION_ID` is empty, refuse: "Cannot dispatch push-analyst: no session id" (action "re-run the snapshot now").

**Step 3: Dispatch push-analyst subagent**

Dispatch the `push-analyst` subagent (Agent tool, `run_in_background: false`) with the following context:

```
BRANCH=<BRANCH>
PRE_HEAD=<PRE_HEAD>
REMOTE_NAME=<RESOLVED_REMOTE>
REMOTE_URL=<REMOTE_URL>
REQUEST_ID=<REQUEST_ID>
SESSION_ID=<SESSION_ID>
REPO_HASH=<REPO_HASH>

<obligation v="1">
{"task_id": null, "lane": null, "lane_set": null, "role": "push-analyst", "pipeline": "push", "profile": "ad_hoc", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this dispatch, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "response_line", "terminal_line_regex": "^push-analyst grant written: \\S+\\.json$"}]}
</obligation>
```

The grant lives in the state dir, outside the repository, so the artifact the obligation declares is the push-analyst's closing `push-analyst grant written: <GRANT_PATH>` line (agents/push-analyst.md Phase 7). Wait for the subagent to complete before proceeding.

**Step 4: Grant validation and sentinel write (Chain B) — performed by execute-push.py**

`execute-push.py` (Step 5) is the sole validator and consumer of the push-analyst grant at `<state dir>/agentic-commit/push-analyst/<REPO_HASH>/<SESSION_ID>/<REQUEST_ID>.json`. Do not read, validate or delete the grant file yourself, and delegate nothing: pass Step 2's values to the script.

**Step 5: Call push.sh via execute-push.py (single-process pattern)**

Run this yourself, never through a subagent: a subagent rightly refuses to write the Chain-B sentinel as a privilege escalation, and push.sh's 60-second sentinel window cannot survive two dispatch delays. `execute-push.py` validates and spends the grant, writes the sentinel and `os.execv`s `<HARNESS_ROOT>/hooks/push.sh`, so validation and push run as one process; push.sh exits 1 on a missing, stale or mismatched sentinel before any `git push`.

```bash
# Without --auto:
python3 "<HARNESS_ROOT>/scripts/execute-push.py" \
  --repo-hash "<REPO_HASH>" \
  --branch "<BRANCH>" \
  --remote "<RESOLVED_REMOTE>" \
  --request-id "<REQUEST_ID>" \
  --repo-root "<REPO_ROOT>"

# With --auto (only when /push was invoked with --auto):
python3 "<HARNESS_ROOT>/scripts/execute-push.py" \
  --repo-hash "<REPO_HASH>" \
  --branch "<BRANCH>" \
  --remote "<RESOLVED_REMOTE>" \
  --request-id "<REQUEST_ID>" \
  --repo-root "<REPO_ROOT>" \
  --auto
```

`--auto` takes no value, and the session id comes from the environment, not from an argument. Run the call alone, with no `&&` chaining. Its refusals: "push BLOCKED by push-analyst" (action "resolve the listed risks first"); exit 3, no push-gate token (action "run /commit first").
