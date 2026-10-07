---
description: Merge any resolvable commit-ish into the default branch, on either a linked (registered_worktree) worktree or an in_place one (the main checkout -- see commands/dev-overnight.md's isolation_kind vocabulary). On a linked worktree, the agent infers the branch from active overnight state, auto-removes the worktree, deletes the merged branch, and removes the overnight-state file. In_place, the agent merges the current (or explicit) ref directly in the main root, requires a clean tree first, and keeps the branch afterward. Bare /merge typical; explicit /merge <ref> overrides.
disable-model-invocation: true
---

# /merge - Merge

Merge a source commit-ish into the repository default branch using a proper merge that preserves full commit history. The merge itself runs identically regardless of worktree shape; only source resolution and post-merge cleanup differ, per the worktree-shape table in Step 0. After a clean successful merge on a linked worktree, the wrapper auto-cleans the worktree, deletes the merged branch, and removes any overnight-state-*.json referencing it; in_place, the source branch and its directory are untouched by cleanup.

## Usage

```
/merge                          # agent infers the source: overnight-state first, then (in_place only) the current branch
/merge <ref>                    # explicit override, works on either worktree shape
```

`<ref>` is ANY commit-ish this repository can resolve, not only a local branch head:

| Source shape | Example | Lifecycle cleanup |
|---|---|---|
| Local branch | `worktree-overnight-20260809-685c203b` | worktree removal + branch deletion + overnight-state removal, subject to the in_place rules below |
| Remote-tracking ref | `origin/master`, `refs/remotes/origin/master` | none applicable -- skipped and announced |
| Tag (annotated or lightweight) | `v1.2.3` | none applicable -- skipped and announced |
| Bare commit hash | `fa0aea69ccedee7a9fdc71f3b0bfece0fc86c983` | none applicable -- skipped and announced |

Validation is "does `<ref>` resolve to a commit object", never a `refs/heads/` prefix match.
Accepting every ref shape relaxes NO check: the clean-tree precondition, the untracked-overlap
preflight, merge-analyst's conflict-marker pre-check, the merge-analyst grant binding and the
post-merge containment invariant all run on a remote-tracking ref, a tag and a bare hash exactly
as they run on a local branch. The only thing a non-branch source changes is the Lifecycle
cleanup column above: each cleanup step is conditional on its artifact existing, and for a
non-branch source that absence is the EXPECTED state -- announced and skipped, never a failure,
because there is provably no worktree, branch or overnight-state file for it to act on. This
paragraph is the normative home for both halves of that rule.

When invoked bare, the orchestrator resolves the source per Step 0's three tiers. No filesystem fallback to "newest branch", no guessing - if no tier resolves a source, exit with error asking the user to pass an explicit ref.

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

The orchestrator then resolves the merge source in this order: (1) the explicit argument, if
supplied; (2) conversation context's most recent overnight-state-*.json with a
`worktree_branch` field; (3) when `IS_IN_PLACE` is true, `git branch --show-current`. Do NOT
guess from filesystem listing beyond tier 3. If no tier resolves a source, exit with an error
asking the user to pass an explicit ref.

Tier 3 degenerates when the current branch already IS the default branch: source and target
resolve to the same commit, which Step 1 refuses as a self-merge before any dispatch.

### Step 1: Compute pre-merge snapshot

```bash
RESOLVED_REF=<the-resolved-merge-source>
SOURCE_TIP=$(git rev-parse --verify --quiet "${RESOLVED_REF}^{commit}" || echo "MISSING")
DEFAULT_BRANCH=$(bash ~/.claude/scripts/derive-default-branch.sh)
DEFAULT_TIP=$(git rev-parse --verify --quiet "refs/heads/${DEFAULT_BRANCH}^{commit}" || echo "MISSING")
REPO_ROOT=$(realpath "$(git rev-parse --show-toplevel)")
REPO_HASH=$(printf '%s' "$REPO_ROOT" | sha256sum | cut -c1-16)
REQUEST_ID=$(openssl rand -hex 16)
SESSION_ID="${CLAUDE_SESSION_ID}"
```

`SOURCE_TIP` is resolved through `${RESOLVED_REF}^{commit}` rather than
`refs/heads/${RESOLVED_REF}`, so a remote-tracking ref, a tag (peeled to its commit) and a bare
commit hash all resolve. `--verify` makes an ambiguous or unknown name a hard MISSING instead of
a silent empty string.

If `SESSION_ID` is empty or unset, abort immediately with:
"Cannot dispatch merge-analyst: CLAUDE_SESSION_ID not set. Invoke /merge from within a Claude Code session."

If either tip is "MISSING", abort with an error describing which ref was not found.

If `SOURCE_TIP` equals `DEFAULT_TIP`, abort with "refusing self-merge: `<RESOLVED_REF>` and
`<DEFAULT_BRANCH>` are the same commit `<SOURCE_TIP>` — nothing to merge". Do NOT dispatch
merge-analyst for a no-op. Note this rejects only an EXACT same-commit pair; a source that is a
strict ancestor of the target still proceeds to git's genuine "Already up to date" path, which is
what makes re-invoking /merge after a completed merge idempotent (merge no-ops, cleanup runs).
This step is the normative home for the self-merge rule: a source and target resolving to the
SAME commit are an error, not a success, and `hooks/merge.sh` refuses the identical condition
independently with a non-zero exit (defense in depth -- the wrapper never trusts having been
reached through this document).

### Step 2: Dispatch merge-analyst subagent

Dispatch the `merge-analyst` subagent with the following context:

```
RESOLVED_REF=<RESOLVED_REF>
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
- `branch` field matches `RESOLVED_REF` (the grant field is still named `branch` for
  backward compatibility with `pretool-git-privilege-guard.py`'s reader; it carries whatever
  ref shape was resolved, not necessarily a branch name)
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
CURRENT_SOURCE_TIP=$(git rev-parse --verify --quiet "${RESOLVED_REF}^{commit}")
CURRENT_DEFAULT_TIP=$(git rev-parse --verify --quiet "refs/heads/${DEFAULT_BRANCH}^{commit}")
```

If either tip differs from the value stored in the grant (`source_tip`, `default_tip`):
abort with "Tips changed since merge-analyst ran — re-run /merge to get a fresh analysis".

### Step 5: Call merge.sh

The orchestrator calls the wrapper exactly once with the resolved ref:

```bash
bash ~/.claude/hooks/merge.sh "<resolved-ref>"
```

Add `--no-commit` when the merge must be inspected before it becomes history: the wrapper applies
the merge to the index and working tree, prints the finalize (`git commit --no-edit`) and
single-step rollback (`git merge --abort`) commands, and exits 0 WITHOUT running cleanup -- there
is no merge commit yet, so the post-merge containment invariant cannot hold. It implies `--no-ff`,
because git cannot hold a fast-forward uncommitted (a fast-forward creates no merge commit). It
weakens no check -- every preflight runs first, it simply stops earlier. Re-run without
`--no-commit` after committing to execute the cleanup section.

The wrapper handles every step internally so that the privilege-guard literal-string match on the merge command does not fire on main-agent PreToolUse (the wrapper runs git operations in its OWN subprocess, which is not seen by main-agent hooks):

1. User-intent sentinel check (must come from /merge slash command, not bash tool)
2. Default-branch resolution (via ~/.claude/scripts/derive-default-branch.sh)
3. Source resolution -- `git rev-parse --verify --quiet "<ref>^{commit}"`; a ref resolving to no commit object is rejected
4. Self-merge refusal -- resolved source sha equals resolved default-branch sha: abort non-zero (rule stated at Step 1)
5. Worktree-shape detection (`IS_IN_PLACE`, same read-only check as Step 0, re-run inside the wrapper's own subprocess)
6. Clean-tree precondition -- in_place only: abort with the `git status --porcelain` output if the tree is dirty; the condition table in Step 0 states why this is required. Unaffected by source shape: it guards the directory the merge lands in, not the ref being merged
7. Untracked-overlap preflight (per spec 5.2.1.3 R3b) -- its two diff endpoints are the resolved shas, so it works for every source shape. In_place the clean-tree precondition is strictly stronger and refuses first (it rejects ANY untracked file, overlapping or not), so this preflight is only separately reachable on a linked worktree
8. Source-moved recheck -- the ref must still resolve to the sha pinned during preflight, or abort; the merge is issued by ref (so the merge message names something a human recognizes) while every post-merge assertion is made against the pinned sha
9. Checkout default branch + perform the merge with --no-edit (or `--no-commit --no-ff` then stop, under `--no-commit`)
10. Post-merge invariant: no unmerged index entries remain, AND the new HEAD CONTAINS the source commit (`git merge-base --is-ancestor`). The test is ancestry/containment, NOT tree-equality: a genuine three-way merge yields a tree differing from BOTH parents, so a `git diff --quiet <ref>` proxy must never be reintroduced. Containment is well-defined even for a bare commit hash with no ref name. A containment failure exits non-zero
11. Cleanup ONLY when the invariant holds, and each step ONLY when its artifact exists:
   - Non-branch source (remote-tracking ref, tag, bare hash): nothing to clean -- no registered worktree, no branch to delete, no overnight-state file that can key on it. All three steps are announced and skipped (the expected state, per Usage)
   - Linked worktree, local-branch source: git worktree remove --force for the worktree directory, git branch -d for the merged branch, rm any overnight-state-*.json whose worktree_branch field matches. A local branch with no registered worktree skips only the worktree step
   - In_place, local-branch source: skip worktree removal and branch deletion -- the main worktree cannot be removed and the source branch is not disposable, so it stays on disk; overnight-state cleanup still runs (removes only files whose worktree_branch matches, which is correct stale-bookkeeping cleanup either way)

If the merge has conflicts, the wrapper exits non-zero and the user resolves manually. The wrapper does NOT auto-resolve.

## Critical rules

- The orchestrator MUST call the wrapper, NOT inline git commands. Inline forms get string-matched by pretool-git-privilege-guard.py and rejected; the wrapper is the only authorized path from agent context.
- If the user wants a manual merge (e.g., to inspect partial state first), they should run from their own terminal - the hook only restricts the agent bash tool, not the user shell.
- In_place, the merge requires a clean tree first and never deletes the source branch afterward - see the worktree-shape table in Step 0. Nothing about in_place relaxes the untracked-overlap preflight, the merge-analyst grant, or the post-merge invariant; those run exactly as they do on a linked worktree.

## Out of scope

- Squash merge / rebase / cherry-pick - never. The worktree branch individual commits must be preserved on the default branch.
- Pushing to remote - see /push.
- Three-step composite (commit + merge + push) - /ship-overnight was retired; run the three commands separately so each carries its own audit trail.
