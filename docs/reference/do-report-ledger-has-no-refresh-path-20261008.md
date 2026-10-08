# The `/do` ledger has no refresh path, so a cycle that keeps working becomes unclosable

Filed 2026-10-08. Structural gap, measured. Cycle `20261006-021155` is recorded here as
**BLOCKED on Workflow Integrity bullet 1 / 4(i)**, with the unmet criterion named.

## The gap

On the `/do` path, `docs/dev/do-report-<task-id>.json` is the **staging-whitelist source**.
`/close`'s Workflow Integrity bullet 1 (downstream consumability) fails when a human would
have to patch an artifact for the cycle's work to be landable.

The ledger is written **once**, at step 5 of the `/do` session. There is no supported way to
refresh it afterwards. Therefore **any `/do` cycle whose work continues after step 5 is
permanently unclosable on bullet 1** — the ledger cannot name files that did not exist when
it was authored, and nothing may legitimately add them later.

This is not a defect in any one cycle. It is a missing mechanism in the path.

## Measurement, with method and control

Searched with `/usr/bin/grep -rn` directly, **not** the interactive shell's default `grep`
(a wrapper that execs `ugrep --ignore-files` and would have skipped ignored paths).

- `scripts/aggregate-dev-report.py` (4048 lines) — `do-report` / `do_report`: **0 hits**.
  It is a shard-merger for `dev-report-<task-id>.json` and cannot target a report whose
  `source` is `"do"`.
  **Positive control**: the same tool and pattern form found `dev-report` **41 times** in
  that same file, so the zero is a real zero and not a broken search.
- Only two writers exist anywhere under `scripts/`, `hooks/`, `commands/`:
  - `hooks/prompt-workflow.py:1366-1437` — pre-writes the pending skeleton at `/do` consent
    time. Runs once, at consent. Not a refresh path.
  - the `/do` session itself, at step 5 (`scripts/todo/do.py:14`).
- Every other hit is a reader or validator: `scripts/resolve-commit-repos.py:423`,
  `scripts/dev-lifecycle.py:182` and `:589`, `hooks/stop-do-report-gate.py`,
  `hooks/subagentstop-e2e-enforce.py`.
- The ledger carries **no digest or integrity field**. Top-level keys: `report_version`,
  `task_id`, `request_id`, `source`, `request`, `profile`, `expected_absent`, `do`.
  So no content hash would be invalidated by a refresh — the obstacle is the absence of a
  writer, not a provenance seal.

Scope of the negative result: those three directories and the filename patterns
`do-*`, `*ledger*`, `*skeleton*`. Not an exhaustive audit of the whole repository.

## Cycle 20261006-021155 — disposition

`/close` returned `CLOSE_FINDINGS: 9 items` (close-report line 434), QA position **NO**,
bullets 1 and 4 **FAIL**. Of the nine:

- **Seven were repaired and independently re-verified** (verb alternation hoisted to a single
  shared definition referenced by both layers; the surviving absolute forgery claim removed;
  the second frozen host-specific count replaced with a re-derivable method; the
  "none of them a relaxation" assertion corrected *and* the real coverage hole it concealed
  closed; the unqualified "read-only inspection: permitted" claim qualified to measured
  behaviour; branch 2's over-block fixed so mere co-occurrence of the namespace with an
  enumerated interpreter no longer refuses; the same-cycle "mirrors Layer 1.E2" contradiction
  resolved).
- **Finding 8 (`stage`)** — reclassified on measurement. Its mtime is `2026-10-07 22:10:38Z`,
  **20 minutes before** the ledger was authored at `22:30:02Z`, so its omission is *not*
  staleness and it was never this cycle's deliverable. It is an 11-byte probe byproduct
  (`ABSENT - 2`), untracked and matched by no ignore rule. Deletion is unavailable to an
  agent: `rm` is blocked unconditionally, and the `git clean` family is blocked by a separate
  rule whose only escapes are human-only. Under the operator's standing ruling that a discard
  requires recovery coordinates, it therefore **lands** rather than being skipped, with
  recovery coordinate `337afc59f2c8cf7282d74c07e9b2e25b1dc86610` — a durable checkpoint commit
  named by its own hash, **reachable from** `refs/checkpoints/master` and **not reachable
  from** `master`. No tip is named here on purpose: that ref auto-advances on its own schedule,
  so any tip written down is stale by design, while reachability from it only ever grows. That
  commit's full tree holds **878** paths — an ordinary whole-repo snapshot, not a single-file
  commit. What makes it a usable coordinate is that its blob for this path,
  `7bfdea69aa93942431dc83eeec1ced2d2b78f316`, is byte-identical to the 11-byte file being
  landed: extracting the blob and comparing it against the working-tree file reports no
  difference, and hashing the working-tree file returns that same digest.
  Removal needs a human-authorized deletion and is left open.

  *Correction, same day.* Two earlier revisions of the lines above framed this coordinate
  wrongly, and in the same way twice. The first claimed the commit *was*
  `refs/checkpoints/master` and that its "entire file list is that one path": it is one commit
  reachable from that ref, and its tree holds 878 paths, not one. That error came from reading
  a pathspec-filtered history listing as the commit's full tree — asking for the commits
  touching one path returns a per-commit file list already narrowed to that path, which looks
  identical to a commit that genuinely contains nothing else. The second revision fixed the
  tree claim but parenthesised the ref's then-current tip commit, which went stale inside the
  hour as the ref advanced and left the named tip a mere ancestor of the new one. Both are one
  underlying mistake — recording a momentary observation as a stable property — so the repair
  is structural, not a fresher value: name only the immutable commit and the monotone
  reachability relation, and no further advance can falsify the sentence. The recoverability
  claim survived both corrections because it rests on the blob digest above, measured
  separately; only the framing around it failed. Neither error reached permanent history — the
  first was caught by the pre-commit review gate, the second by the operator noticing the
  named tip had already moved, which is both checks working as intended.
- **Finding 9 (this file's subject)** — not repairable from inside the cycle. No mechanism
  exists.

## What would close it

1. A supported regenerate-from-observed-state writer for `do-report-*.json`, so a cycle whose
   work continued can re-author its own ledger without a human patching JSON.
2. Failing that, a `/close` rule change: on the `/do` path, evaluate bullet 1 against the
   ledger **plus** the bulk-landing channel, since `/commit --bulk` does not consult the
   ledger and can land files the ledger omits. Today bullet 1 reads the ledger as the sole
   whitelist, which is what makes the omission terminal.

Option 2 is the cheaper of the two and does not weaken any gate: it widens the evaluated
evidence rather than lowering the bar.

## Why this is filed rather than worked around

Hand-editing the ledger would satisfy bullet 1's own failure trigger — a human patching the
artifact — while also putting a hand-authored claim into a record meant to be machine-produced.
The lane was stopped and reported instead. Related: `docs/reference/merge-pipeline-blocked-steps-20261007.md`
(two earlier structural gaps on the merge path) and
`docs/reference/bash-safety-verb-anchoring-20261008.md` (the verb-anchoring defect class).
