---
description: Merge a branch into the default branch, on either a linked (registered_worktree) worktree or an in_place one (the main checkout -- see commands/dev-overnight.md's isolation_kind vocabulary). On a linked worktree, the agent infers the branch from active overnight state, auto-removes the worktree, deletes the merged branch, and removes the overnight-state file. In_place, the agent merges the current (or explicit) branch directly in the main root, requires a clean tree first, and keeps the branch afterward. Bare /merge typical; explicit /merge <branch> overrides.
disable-model-invocation: true
---

# /merge - Branch Merge

Merge a source branch into the repository default branch using a proper merge that preserves full commit history. The merge itself runs identically regardless of worktree shape; only branch resolution and post-merge cleanup differ, per the worktree-shape table in Step 0. After a clean successful merge on a linked worktree, the wrapper auto-cleans the worktree, deletes the merged branch, and removes any overnight-state-*.json referencing it; in_place, the source branch and its directory are untouched by cleanup.

## Usage

```
/merge                          # agent infers the branch: overnight-state first, then (in_place only) the current branch
/merge <branch>                 # explicit override, works on either worktree shape
```

When invoked bare, the orchestrator resolves the branch per Step 0's three tiers. No filesystem fallback to "newest branch", no guessing - if no tier resolves a branch, exit with error asking the user to pass an explicit branch.

## Implementation

### Step 0: Determine worktree shape, then resolve branch name

The orchestrator classifies the current invocation using only read-only git state --
no branch, PR, or worktree is created or touched by this classification. `IS_IN_PLACE` is
true exactly when the current working tree is the repository's main worktree rather than a
linked one. `hooks/merge.sh` holds the actual read-only check (comparing `git worktree
list`'s first entry against the current `git rev-parse --show-toplevel`); this document
states the judgment, not the mechanics. This mirrors `commands/dev-overnight.md`'s own
`isolation_kind` definition (`in_place` iff `worktree_path` equals `main_root`), computed
fresh rather than read from a state file -- /merge can run with no live overnight session
governing the branch at all.

Worktree-shape condition table -- each condition is read-only; none creates a branch, PR, or worktree:

| Judgment condition | Holds on a linked (registered_worktree) worktree | Holds in_place (the main checkout, e.g. this shared tree) |
|---|---|---|
| `IS_IN_PLACE` is false (cwd is not `git worktree list`'s first entry) | Yes -- `scripts/create-worktree.sh::validate_worktree` requires `rp_wt != rp_main` at creation time, so a linked worktree is never the main one | No -- cwd IS the main worktree |
| An `.claude/overnight-state-*.json` exists with a matching `worktree_branch` | Yes, normally | Not required -- /merge classifies by git topology, not by reading overnight state |
| The directory is exclusive to one session while the merge runs | Yes, by construction -- created fresh per cycle, deleted right after | No -- other sessions may hold uncommitted edits here concurrently |
| `pretool-git-privilege-guard.py::_evaluate_merge` / `_enforce_merge_grant_binding` gate on worktree shape | No -- `_is_overnight_active()` is unreferenced by `_evaluate_merge`, `_enforce_merge_grant`, and `_enforce_merge_grant_binding`; the grant check validates only repo_root/branch/tips/session | Same -- already shape-agnostic, no change needed |
| `merge-analyst`'s 8 phases depend on worktree shape | No -- Phase 5's overnight-state check is informational-only and already no-ops when no matching state file exists; every other phase works on refs, not paths | Same -- already shape-agnostic, no change needed |
| Safe to `git checkout $DEFAULT_BRANCH` in place with no precondition | Yes -- exclusivity (row 3) makes this safe for free | No -- merge.sh now requires a clean tree (`git status --porcelain` empty) before checkout, as the equivalent of that exclusivity guarantee |
| Safe to auto-delete the branch after a clean merge | Yes -- the branch is single-purpose and disposable | No -- the branch may be a long-lived shared branch; merge.sh skips deletion and leaves it on disk |

Only the last two rows require new handling in_place (the clean-tree precondition and the
skipped branch deletion, both in `hooks/merge.sh`); every other row already holds, or already
degrades safely, with zero code change.

The orchestrator then resolves the source branch in this order: (1) the explicit argument, if
supplied; (2) conversation context's most recent overnight-state-*.json with a
`worktree_branch` field; (3) when `IS_IN_PLACE` is true, `git branch --show-current`. Do NOT
guess from filesystem listing beyond tier 3. If no tier resolves a branch, exit with an error
asking the user to pass an explicit branch.

### Step 1: Compute pre-merge snapshot

```bash
RESOLVED_BRANCH=<the-resolved-branch>
SOURCE_TIP=$(git rev-parse "refs/heads/${RESOLVED_BRANCH}" 2>/dev/null || echo "MISSING")
DEFAULT_BRANCH=$(bash ~/.claude/scripts/derive-default-branch.sh)
DEFAULT_TIP=$(git rev-parse "refs/heads/${DEFAULT_BRANCH}" 2>/dev/null || echo "MISSING")
REPO_ROOT=$(realpath "$(git rev-parse --show-toplevel)")
REPO_HASH=$(printf '%s' "$REPO_ROOT" | sha256sum | cut -c1-16)
REQUEST_ID=$(openssl rand -hex 16)
SESSION_ID="${CLAUDE_SESSION_ID}"
```

If `SESSION_ID` is empty or unset, abort immediately with:
"Cannot dispatch merge-analyst: CLAUDE_SESSION_ID not set. Invoke /merge from within a Claude Code session."

If either tip is "MISSING", abort with an error describing which branch was not found.

### Step 2: Dispatch merge-analyst subagent

Dispatch the `merge-analyst` subagent with the following context:

```
RESOLVED_BRANCH=<RESOLVED_BRANCH>
SOURCE_TIP=<SOURCE_TIP>
DEFAULT_BRANCH=<DEFAULT_BRANCH>
DEFAULT_TIP=<DEFAULT_TIP>
REQUEST_ID=<REQUEST_ID>
SESSION_ID=<SESSION_ID>
REPO_HASH=<REPO_HASH>
REPO_ROOT=<REPO_ROOT>
```

Wait for the subagent to complete before proceeding.

### Step 3: Read and validate merge-analyst grant

`pretool-git-privilege-guard.py::_evaluate_merge` ALSO requires and
validates this same grant (repo_root/branch/source_tip/default_branch/default_tip,
verdict=approved, unexpired, single-use) before it will admit the wrapper's inner
`git merge`. The steps below remain required anyway — they are defense-in-depth,
not replaced by the hook-level check, and they fail fast with a clear message
instead of letting the orchestrator discover the grant is bad only when merge.sh's
subprocess gets blocked.

Read the grant at:
```
/tmp/agentic-commit/merge-analyst/<REPO_HASH>/<SESSION_ID>/<REQUEST_ID>.json
```

Validate the following fields:
- File exists (if absent: abort with "merge-analyst did not write a grant — aborting merge")
- Grant is valid JSON (if not: abort with "merge-analyst grant is not valid JSON — aborting merge")
- `nonce` field matches `REQUEST_ID`
- `repo_root` field matches `REPO_ROOT`
- `branch` field matches `RESOLVED_BRANCH`
- `source_tip` field matches `SOURCE_TIP`
- `default_tip` field matches `DEFAULT_TIP`
- `default_branch` field matches `DEFAULT_BRANCH`
- `session_id` field matches `SESSION_ID`
- `verdict` field is one of: `"approved"`, `"blocked"` (reject unknown verdicts)
- `risks` field is a JSON array (even if empty)
- `expires_at` is in the future (60s expiry — parse ISO-8601, compare to current UTC time)

If expired: re-dispatch merge-analyst (return to Step 2 with a fresh REQUEST_ID). Report
to the user that the grant expired and a fresh analysis is running.

If any non-expiry field mismatches, is absent, or has wrong type: abort with a descriptive error naming the failing field.

Consume (unlink) the grant:
```bash
rm -f "/tmp/agentic-commit/merge-analyst/${REPO_HASH}/${SESSION_ID}/${REQUEST_ID}.json"
```

If verdict=blocked: display `risks[]` to the user and abort. Do NOT call merge.sh.

### Step 4: Revalidate branch tips

Immediately before calling merge.sh, re-read current branch tips:

```bash
CURRENT_SOURCE_TIP=$(git rev-parse "refs/heads/${RESOLVED_BRANCH}" 2>/dev/null)
CURRENT_DEFAULT_TIP=$(git rev-parse "refs/heads/${DEFAULT_BRANCH}" 2>/dev/null)
```

If either tip differs from the value stored in the grant (`source_tip`, `default_tip`):
abort with "Branch tips changed since merge-analyst ran — re-run /merge to get a fresh analysis".

### Step 5: Call merge.sh

The orchestrator calls the wrapper exactly once with the resolved branch:

```bash
bash ~/.claude/hooks/merge.sh "<resolved-branch-name>"
```

The wrapper handles every step internally so that the privilege-guard literal-string match on the merge command does not fire on main-agent PreToolUse (the wrapper runs git operations in its OWN subprocess, which is not seen by main-agent hooks):

1. User-intent sentinel check (must come from /merge slash command, not bash tool)
2. Default-branch resolution (via ~/.claude/scripts/derive-default-branch.sh)
3. Worktree-branch existence check
4. Worktree-shape detection (`IS_IN_PLACE`, same read-only check as Step 0, re-run inside the wrapper's own subprocess)
5. Clean-tree precondition -- in_place only: abort with the `git status --porcelain` output if the tree is dirty; the condition table in Step 0 states why this is required
6. Untracked-overlap preflight (per spec 5.2.1.3 R3b) -- unchanged, runs on both shapes
7. Checkout default branch + perform the merge with --no-edit
8. Post-merge sanity check (diff vs branch must be empty)
9. Cleanup ONLY when sanity passes:
   - Linked worktree: git worktree remove --force for the worktree directory, git branch -d for the merged branch, rm any overnight-state-*.json whose worktree_branch field matches
   - In_place: skip worktree removal and branch deletion -- the main worktree cannot be removed and the source branch is not disposable, so it stays on disk; overnight-state cleanup still runs (removes only files whose worktree_branch matches, which is correct stale-bookkeeping cleanup either way)

If the merge has conflicts, the wrapper exits non-zero and the user resolves manually. The wrapper does NOT auto-resolve.

## Critical rules

- The orchestrator MUST call the wrapper, NOT inline git commands. Inline forms get string-matched by pretool-git-privilege-guard.py and rejected; the wrapper is the only authorized path from agent context.
- If the user wants a manual merge (e.g., to inspect partial state first), they should run from their own terminal - the hook only restricts the agent bash tool, not the user shell.
- In_place, the merge requires a clean tree first and never deletes the source branch afterward - see the worktree-shape table in Step 0. Nothing about in_place relaxes the untracked-overlap preflight, the merge-analyst grant, or the post-merge sanity check; those run exactly as they do on a linked worktree.

## Out of scope

- Squash merge / rebase / cherry-pick - never. The worktree branch individual commits must be preserved on the default branch.
- Pushing to remote - see /push.
- Three-step composite (commit + merge + push) - /ship-overnight was retired; run the three commands separately so each carries its own audit trail.
