# Root-level `workflow-*.json` bookmarks have no lifecycle management; 22/22 are orphans

**Measured 2026-10-05.** The repository root currently holds 113 entries; git tracks only 37 of them, and the rest are gitignored. The gap is not a missing `.gitignore` rule — it is the absence of any reclaimer for the largest ignored category.

## What these files are

`workflow-<session-id>.json` is a per-session bookmark written by `hooks/prompt-workflow.py` and read by at least eight other hooks (`pretool-workflow-gate.py`, `pretool-subagent-enforce.py`, `posttool-todo-tracker.py`, `posttool-todo-count.py`, `pretool-todo-validate.py`, `pretool-spec-block-foreground-agent.py`, `posttool-subagent-track.py`, `pretool-block-background-tasks.py`). It records the bound command and the canonical todo-step sequence for that session.

## Measured: 22 of 22 are orphans

Every `workflow-*.json` file at the repo root was checked by session id against the transcript directories of all three account directories under `/var/lib/claude-accounts/` (`orchestrade`, `yugetang`, `yugoge`). **Zero** have a matching transcript under any of the three; all 22 are orphans. Dates range from 2026-03-25 (oldest) to 2026-09-18 (newest); total size is 40106 bytes. (An earlier verbal estimate of "~104K" for this total does not match a direct byte count — recorded here as the measured figure, not the estimate.)

Checking fewer than all three accounts is not a hypothetical risk: earlier the same evening, a transcript was declared absent after checking only one account, when it in fact existed — intact, 604 lines — under a different one. Any orphan judgment for this file category that does not check every account directory is unreliable by demonstrated precedent, not just in theory.

## Measured: lifecycle coverage is a single conditional happy-path, not "none"

A full-repo search for code that deletes or otherwise manages the end-of-life of these bookmarks found exactly one site: `hooks/posttool-todo-tracker.py`, which unlinks a session's own bookmark when every canonical todo step for that session has been marked `completed` (also documented in this file's entry `#109`). This is a narrow, same-session, happy-path cleanup — a session that is abandoned, interrupted, or never reaches full completion leaves its bookmark behind permanently, with nothing in the codebase that later reclaims it. The 22 orphans above are exactly that unhappy path, accumulated with no sweep.

## Measured: this repository already has five same-family reclaimers, and lacks exactly this one

`hooks/sessionend-scratch-sweep.sh`, `hooks/stop-cleanup-allowlist.sh`, `scripts/checkpoint-prune.sh`, and `scripts/cleanup-tests-folder.sh` each reclaim a different stale-artifact category (own-session scratch directories, expired consent/grant sentinels, excess checkpoint refs, orphaned test validators). A fifth, `hooks/cleanup-close-force-sentinel.sh`, was named as part of this same-family set but does not exist at that path in this checkout — noted here as a discrepancy rather than silently treated as read. None of the five touch root-level `workflow-*.json` bookmarks.

`scripts/prune-orphaned-workflow-bookmarks.sh` fills exactly that gap, following `scripts/checkpoint-prune.sh`'s conventions most closely among the five (a standalone CLI with `--help`, environment-variable overrides, running counters, and a final summary line) since it is likewise an operator-invoked tool rather than an event-triggered hook. It defaults to report-only; deleting anything requires the explicit `--delete` flag. A candidate must satisfy two independent conditions — no transcript under any account directory, AND an mtime at or past a configurable age floor (default 14 days) — so a just-created session whose transcript has not yet landed is never mistaken for a dead one. It never accepts a wildcard delete target, never touches a path outside the repository root, never deletes a git-tracked file, and re-validates all three of those immediately before each deletion, not only during the initial scan.

## Measured: stale bookmarks actively interlock a session, not merely accumulate

A session carrying a stale workflow bookmark can be hook-interlocked: the same per-session state that the lock hooks read (canonical step count, completion status) blocks both the foreground and the background subagent-dispatch paths at once, with no self-service release short of marking steps complete that were never actually executed (see this file's entry `#109` for the full mechanism). This is a measured failure mode from earlier the same evening, not a hypothetical one.

## Why `pretool-bash-safety.sh` could not have been this reclaimer

`hooks/pretool-bash-safety.sh` already contains a rule that blocks any `rm`/`mv` command whose text matches `workflow-[^/]*\.json`, with no exception for an orphan. That rule is a safety backstop, not a lifecycle mechanism: it stops an ad hoc delete of a file that might still be live, but it cannot distinguish an orphan from a live bookmark, so it cannot be loosened into a reclaimer without losing the protection it provides for live sessions. A reviewed, committed script — invoked as a script rather than as a literal top-level `rm`/`mv`, and carrying its own independent orphan/age criteria — is the only way this category was ever going to get a reclaimer under the existing safety design.
