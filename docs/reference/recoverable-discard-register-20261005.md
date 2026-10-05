# Recoverable-discard register — 2026-10-05 tree-to-zero campaign

Operator ruling (2026-10-04, verbatim): **"你可以丢弃，但是要可恢复，同时明早给我汇报"**
— discarding uncommitted work is permitted **only** when its content is first written
to a recoverable reference and the discard action is recorded **paired** with its
recovery coordinates. **No recovery coordinate, no discard.**

This file is the register. It is kept under `docs/reference/` because `docs/dev/` is
gitignored and cannot be landed (operator ruling 3: deprecation marks go in **both**
a landable `docs/reference/` record **and** the terminating commit message).

## Status

| | |
|---|---|
| Discards performed so far | **2** (untracked scratch files removed by decision, 2026-10-05, after this entry landed) + **2 pending** (`.claude/scratch_pre_a.txt`, `.claude/tmp-codex-prompt-XeWFCx.txt`, confirmed empty by the zero-coverage takeover-landing pass, 2026-10-05; removal to be attempted after this register update lands) |
| Recovery coordinates on record | 2 pre-emptive (bytes destroyed by a concurrent session, not discarded by decision) + 4 by-decision (scratch files, full content inlined below — too small to need a blob coordinate) |
| Register opened | 2026-10-05T06:50Z |

## Discards by decision

Per the operator ruling above: content recorded here BEFORE removal. Both files were
untracked scratch residue from an earlier attribution self-test in this same takeover
cycle (write-then-read-back of a small file to prove the write-time attribution journal
observes an agent's own writes). Full content is inlined verbatim — each file is a
single short line, far below the size where a blob-sha coordinate would add anything.

| Path | Content (verbatim) | Reasoning |
|---|---|---|
| `scratch-attribution-selfproof.txt` | `v2 from interpreter` | pure self-test residue — its only reason for existing was to be read back by its own test |
| `scratch-attribution-selfproof2.txt` | `v1 from interpreter` | pure self-test residue — its only reason for existing was to be read back by its own test |
| `.claude/scratch_pre_a.txt` | *(empty — 0 bytes, verified `wc -c` 2026-10-05)* | zero-coverage takeover-landing pass (2026-10-05): confirmed empty, no recoverable content to lose |
| `.claude/tmp-codex-prompt-XeWFCx.txt` | *(empty — 0 bytes, verified `wc -c` 2026-10-05)* | zero-coverage takeover-landing pass (2026-10-05): confirmed empty, no recoverable content to lose |

**Correction to the zero-coverage pass's own working assumption**: a third file carried into this
pass as "confirmed empty, pure throwaway junk" — `.scratch_subagentstop_ancestor.txt` — was
re-verified here (`wc -c`) and found to be **26416 bytes**, a complete SubagentStop
producer-side artifact-schema-gate hook draft (tickets `do-20260926-073930`,
`20261001-161041-r01`/`r12`, `spec-20260914-052140`, `spec-20260916-031427`). It is **not**
discarded and has **no row** in this register — it is landed as real content in the same
commit as the other misleading-filename "scratch"/"tmp" artifacts, with a note in that commit
message. Recorded here only so the discrepancy between the incoming disposition and the
verified file state is not silently lost.

Nothing has been discarded by decision. The two entries below are **not** discards;
they are bytes a concurrent session destroyed in the shared worktree, recorded here so
the content remains retrievable. They are listed in the same register because the
operator's requirement is about retrievability, and these have the same shape.

## Recovery coordinates

Both blobs were verified by reading their content, not by trusting a reported sha.

| Full blob sha | Size | Path it belonged to | Verification basis |
|---|---|---|---|
| `dcc331935c632ec546f6648565fbc2e59fe5ebf4` | 39684 B | `schemas/owned-edits-ledger.v1.json` | blob contains `$id` = `https://claude.local/schemas/owned-edits-ledger.v1.json`, title "Owned-edits ledger contract (v1)" |
| `9ca5dfeb89f27733bc4c7f803ffbe6499b832988` | 77098 B | `tests/test_stage_owned_hunks_boundary.py` | blob contains docstring "Regression coverage for scripts/stage-owned-hunks.py's pure-insertion content-anchor-retry boundary/coordinate-space defect (task 20260912-015952)" |

Retrieve with `git cat-file -p <sha>`. Both are reachable objects in this repository.

### Unclaimed content inside `dcc33193`

The same blob `dcc331935c632ec546f6648565fbc2e59fe5ebf4` also carries roughly 101 lines
belonging to a **different owner**: an `x-classification-contract` block (INV-01..INV-12,
an authorization ruling), journal session `7608a10e`, timestamped 2026-10-03T06:47:51Z.
That content was **not** touched and **not** claimed by the cycle that recorded these
coordinates. Anyone restoring `dcc33193` restores that block too, and owes it a ticket.

## Known residue that is not a discard

| Item | State | Why it is here |
|---|---|---|
| `/tmp/commit-msg-496d4d98-g{1,2,3}.txt` | on disk | message files preserved after `pretool-bash-safety.sh` refused their cleanup; audit trail intact, removal needs a human |
| 27 of 37 `/tmp` commit-grant files | unparseable JSON | the privilege guard treats a parse failure as expired, so they are inert and block nothing — but they are noise that can mask a genuinely live grant |
| Four never-terminal lanes of task 20261003-020648 | l4, l8 dev never ran; l10's record refused by `pretool-gitignore-preflight.py`; l6 QA killed by quota | disclosed in commit `5093dc63d` and in the landed takeover record, not silently dropped |

## Campaign ledger (commits landing tree residue)

| Commit | Workspace | Files | Note |
|---|---|---|---|
| `02fe8fe83` | COMMIT-MACHINE journal scope replaces ownership gate | `settings.json` | carried four hook registrations whose targets are untracked — HEAD is not self-consistent on a clean checkout; defect recorded, not hidden |
| `689375901` | same | `agents/changelog-analyst.md` | entangled-file whole-landing standing rule |
| `2101f6d84` | MERGE support non-overnight worktree | `hooks/merge.sh`, `commands/merge.md` | in_place support; clean-tree precondition |
| `8edbfe156` | LEASE enforce holder at ledger CLI | 1 doc | caller-id rollout incident disclosure |
| `2df31d56c` | same | 4 files | dual-ticket landing satisfying a historical `COMMIT: REJECT`; `Task-id` + `Co-landed-task-id` |
| `5093dc63d` | /dev-command takeover cycle | 2 files | operator-authorized `--bulk`; positive-control attribution evidence in the message |
