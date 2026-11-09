---
description: Merge any resolvable commit-ish into the default branch with a real merge that keeps the full history. Bare /merge infers the source (overnight state, then the current branch in the main checkout); /merge <ref> names it. A linked (registered_worktree) worktree is removed afterward with its merged branch and overnight-state file; in the main checkout (in_place) the tree must be clean first and the branch stays.
disable-model-invocation: true
---

# /merge - Merge

Merge a source commit-ish into the repository default branch with a proper merge that preserves full commit history. The merge is the same on every worktree shape; only the source resolution (Step 0) and the post-merge cleanup differ.

## Usage

```
/merge                          # the agent infers the source: overnight state first, then (in_place only) the current branch
/merge <ref>                    # explicit; works on either worktree shape
```

`<ref>` is any commit-ish this repository resolves: validation is "names a commit object", never a `refs/heads/` prefix. Every check runs on every ref shape; only the cleanup differs, and a cleanup step whose artifact does not exist is announced and skipped, never a failure:

| Source shape | Example | Cleanup after a clean merge |
|---|---|---|
| Local branch, linked worktree | `worktree-overnight-<date>-<id>` | worktree removed, branch deleted, matching `overnight-state-*.json` removed |
| Local branch, in_place | the current branch | branch and directory kept; matching overnight-state removed |
| Remote-tracking ref, tag, bare commit hash | `origin/master`, `v1.2.3`, `<40-hex commit id>` | none |

In_place means the main checkout, which other sessions may share: `hooks/merge.sh` requires a clean tree first and never deletes the source branch. A linked worktree is exclusive to one session, so neither applies.

## Implementation

**Refusals.** Where a step below refuses, ask ONE AskUserQuestion in this turn instead of exiting: the
question is the refusal's message with its facts; the options are the action the refusal names, marked
(Recommended), and "I give another instruction". Act on the answer. A refusal met again after the
answer is reported in the reply, not asked again.

### Step 0: Determine worktree shape, then resolve branch name

Everything in this step is read-only; nothing is created. `IS_IN_PLACE` is true when the first entry of `git worktree list` is the directory `git rev-parse --show-toplevel` prints (the main checkout), false on a linked worktree. It is computed fresh, not read from a state file: /merge can run with no overnight session at all.

The source is the first tier that yields one:

1. the argument, if given;
2. the most recent `overnight-state-*.json` in the conversation's context that has a `worktree_branch`;
3. when `IS_IN_PLACE` is true, `git branch --show-current`.

Guess nothing else (no "newest branch" from a directory listing). If no tier yields a source, refuse: "no tier resolved a merge source" (action "name the ref to merge"). When the current branch is the default branch, tier 3 yields a self-merge, which Step 1 refuses.

### Step 1: Compute pre-merge snapshot

```bash
python3 "<HARNESS_ROOT>/scripts/steps/merge-snapshot.py" snapshot "<resolved-ref>"
```

It prints eight `KEY=value` lines, which Steps 2 to 4 read by key: `RESOLVED_REF`, `SOURCE_TIP`, `DEFAULT_BRANCH`, `DEFAULT_TIP`, `REQUEST_ID`, `SESSION_ID`, `REPO_HASH`, `REPO_ROOT`. A tip that names no commit is `MISSING`. Refuse when:

- `SESSION_ID` is empty: "Cannot dispatch merge-analyst: CLAUDE_CODE_SESSION_ID not set" (action "re-run the snapshot now").
- `SOURCE_TIP` or `DEFAULT_TIP` is `MISSING`: "`<ref>` does not resolve to a commit" (action "name the ref to merge").
- `SOURCE_TIP` equals `DEFAULT_TIP`: "refusing self-merge: `<RESOLVED_REF>` and `<DEFAULT_BRANCH>` are the same commit `<SOURCE_TIP>` — nothing to merge" (action "name the ref to merge"). Do not dispatch merge-analyst for a no-op.

Only the exact same commit is a self-merge. A source that is a strict ancestor of the target goes on to git's "Already up to date", which makes a repeated /merge after a completed one idempotent (the merge no-ops, the cleanup runs). `hooks/merge.sh` refuses the same-commit pair too.

### Step 2: Dispatch merge-analyst subagent

Dispatch the `merge-analyst` subagent (Agent tool, `run_in_background: false`) with the eight lines Step 1 printed, a blank line, then the obligation:

```
<the eight lines Step 1 printed>

<obligation v="1">
{"task_id": null, "lane": null, "lane_set": null, "role": "merge-analyst", "pipeline": "merge", "profile": "ad_hoc", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this dispatch, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "response_line", "terminal_line_regex": "^merge-analyst grant written: \\S+\\.json$"}]}
</obligation>
```

The obligation's artifact is the merge-analyst's closing `merge-analyst grant written: <GRANT_PATH>` line (agents/merge-analyst.md Phase 8): the grant itself lives in the state dir, outside the repository, where no obligation path can name it. To re-run the analysis (the action of a refusal in Steps 3 and 4), run Step 1 again for fresh tips and a fresh `REQUEST_ID`, then dispatch again.

### Step 3: Read the merge-analyst grant

Read the grant at:
```
<state dir>/agentic-commit/merge-analyst/<REPO_HASH>/<SESSION_ID>/<REQUEST_ID>.json
```
(the state dir is `$CLAUDE_STATE_DIR` when that is an absolute path, else `/tmp`) and act on its `verdict` and `risks`. `hooks/lib/merge_grant.py` validates the grant once, on the analyst's own Write (run from `hooks/posttool-allowlist-consume.py`, which the ledger rates `detected`); this step re-checks none of it.

- No grant at that path: refuse: "merge-analyst did not write a grant" (action "re-run the analysis now").
- `verdict` = `blocked`: refuse: "merge-analyst blocked the merge" with `risks[]` (action "resolve the listed risks first"; never "merge anyway"). Do not call merge.sh.
- `verdict` = `approved`: continue to Step 4.

### Step 4: Revalidate branch tips

Immediately before calling merge.sh, read the tips again:

```bash
python3 "<HARNESS_ROOT>/scripts/steps/merge-snapshot.py" tips "<RESOLVED_REF>" "<DEFAULT_BRANCH>"
```

If `CURRENT_SOURCE_TIP` differs from the grant's `source_tip`, or `CURRENT_DEFAULT_TIP` from its `default_tip`, refuse: "Tips changed since merge-analyst ran" (action "re-run the analysis now").

### Step 5: Call merge.sh

Call the wrapper once with the resolved ref:

```bash
bash "<HARNESS_ROOT>/hooks/merge.sh" "<resolved-ref>"
```

The wrapper does the merge in its own subprocess and carries every other check itself: the self-merge refusal, the in_place clean-tree precondition, the untracked-overlap preflight, the source-moved recheck, the post-merge containment invariant (the new HEAD contains the source commit; tree equality is the wrong test for a three-way merge), and the cleanup of the Usage table, which runs only when that invariant holds.

Add `--no-commit` to inspect the merge before it becomes history: the wrapper applies it to the index and working tree (it implies `--no-ff`), prints the finalize (`git commit --no-edit`) and rollback (`git merge --abort`) commands, and exits 0 without cleanup, because no merge commit exists yet. Every preflight still runs first. Re-run without `--no-commit` after committing to run the cleanup.

If the merge has conflicts, the wrapper exits non-zero and does not auto-resolve: refuse with its output (action "I resolve the conflicts myself, then you continue"; on that answer, go on from Step 1 with the same ref).

## Critical rules

- Merge only through the wrapper, never an inline `git merge`: `pretool-git-privilege-guard.py` refuses an agent `git merge` (the ledger rates that hook advisory, so a slip is not guaranteed to be caught), and the wrapper runs git in its own subprocess, which no agent hook sees.
- A manual merge belongs in the owner's own terminal; the guard restricts only the agent's Bash.

## Out of scope

- Squash merge, rebase and cherry-pick: never; the source branch's individual commits stay on the default branch.
- Pushing: see /push.
- Commit, merge and push in one command: run /commit, /merge and /push separately, so each keeps its own audit trail.
