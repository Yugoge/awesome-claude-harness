# Abandoned cycles — terminal determination

**Date**: 2026-09-05
**Subject**: two stranded `/dev` cycles, `20260902-140306` and `20260903-115527`, which
are terminal and cannot be closed.
**Provenance**: measurements taken first-hand by four parallel audits on 2026-09-05.
Figures marked **[re-verified]** were additionally re-measured while writing this
document. Every one of them was re-measured again at **2026-09-05T12:54Z** (`HEAD`
`b4b5f13b`) and reproduced exactly — with one exception: the *verdict* column of the §4
resolver table did not, and §4 now carries the corrected measurement and says so. A
`[re-verified]` mark is worth its ink only with the instant attached, so the instants are
stated at the figures below rather than left to the document date.

## Why this file exists

Detailed per-cycle records already exist:

- `/dev/shm/dev-workspace/dot-claude/.claude/worktrees/overnight-20260810-019fe5c1/docs/dev/abandonment-20260902-140306.md`
  — **19,509 bytes**, sha256 `ca88ba26c7bc3429b40f348033bf702bd88efc6b87db02020d91dcc082bf2d44` **[re-verified]**
- `/dev/shm/dev-workspace/dot-claude/.claude/worktrees/overnight-20260810-019fe5c1/docs/dev/abandonment-20260903-115527.md`
  — **24,061 bytes**, sha256 `56af2b646e23f73380ab890e84e5a8e113da5cde4a944f71c87e0f0afb969d6b` **[re-verified]**

Both sit inside the overnight worktree at
`/dev/shm/dev-workspace/dot-claude/.claude/worktrees/overnight-20260810-019fe5c1`, under a
`docs/dev/` path. That tree is **ignored** and **will not survive a clone**.

The governing rule is **`.gitignore:93` — `worktrees/`**, not the `docs/dev/` rule. This was
asked of the ignore machinery itself rather than inferred; `git check-ignore -v` on both
records, at 2026-09-05T11:43Z, answers:

```
.gitignore:93:worktrees/   .claude/worktrees/overnight-20260810-019fe5c1/docs/dev/abandonment-20260902-140306.md
.gitignore:93:worktrees/   .claude/worktrees/overnight-20260810-019fe5c1/docs/dev/abandonment-20260903-115527.md
```

An earlier revision of this document cited `.gitignore:142` (`docs/dev/`). That was wrong:
`docs/dev/` contains an internal slash, so git anchors it to the repository root, and it
therefore does **not** match a `docs/dev/` directory nested at depth inside the worktree.
`worktrees/` has no internal slash and so matches at any depth — it catches the whole
worktree at `.claude/worktrees/`, records included. The practical consequence is unchanged
(the tree is ignored and does not survive a clone), but the rule a reader would go read to
confirm it is line 93. This durable summary exists so the determination is not lost with it. The detailed
records remain authoritative for per-cycle narrative; nothing in them is edited or
superseded here.

---

## 1. The remediation question was answered on evidence

**The proven approach is preventive only.**

It works by evaluating the close-gate dimension **while a member is still awaiting
verification** — that is, at a point in the lifecycle where a **non-pass edge remains
available**. Once a member has reached a terminal passing state, that edge is gone, and the
approach has nothing to act on.

**Neither stranded cycle satisfies that precondition.** Both were probed directly against
the live validator rather than argued about.

### 1.1 The cycle at a terminal passing state

All **seven** possible successor states were appended to the cycle's **real declaration in
memory** — not to a synthetic fixture — and submitted to the **live validator**:

- the **unmodified control** was **accepted with zero errors**;
- **every one of the seven** was **rejected as a forbidden edge**;
- **two of the seven** were additionally rejected as an **absorbing terminal state**.

The control establishes that the validator accepts the declaration as it stands, so the
seven rejections are properties of the attempted transitions and not of the harness or the
input. There is no successor state reachable from where this cycle sits.

### 1.2 The declaration-less cycle

A **truthful two-round history** was probed directly and **collides with a
single-mutable-path contradiction**: recording the first round honestly requires the
verification path to hold the failing bytes, and recording the second round honestly
requires the same single path to hold the passing bytes. One path cannot hold both, and the
lifecycle provides no second path.

The **positive control** — binding the live bytes to a passing transition — returned **zero
errors**, which establishes that the validator will accept a well-formed binding for this
cycle and that the contradiction is in the two-round history, not in the probe.

---

## 2. What survives

**Both cycles' substance shipped in commit `dce9fff9`.** **[re-verified: `dce9fff9` is an
ancestor of `origin/master`.]**

The delta between the predecessors' frozen bytes and what shipped is **exactly four lines**.
The frozen bytes are **locatable**, and the delta was re-derived from them by direct `diff -u`
at **2026-09-05T12:54Z**. The durable identifiers are the digests, not the paths:

| file | frozen sha256 | committed at `dce9fff9` |
|---|---|---|
| `hooks/lib/contract_runtime.py` | `0fa19fda000b4b9d886c3f5df31d4e21c620961263d69d63b4fbd5d381a8dc6c` | `dfbd03066a13b0efd44269eb16ae31491dc644cb2495782023a689db4a40ace7` |
| `hooks/tests/test_report_projection_contract.py` | `7e12efca981f915885dff9e58594f339a3138e5cf4cf43a0d150ddef4f6b921e` | `fdc470f8b918d4abf83d3fb34fe8512f3c5cefb66b4147dc2faf7407dfebc1f5` |

Both frozen files sit together, at those digests, outside the repository at
`/var/backups/shm-graveyard-20260905/tmp.NrMmvMVeLB/`, under the same two relative paths. That
same walk found **161** directories carrying both frozen files — **22** on `/dev/sda1` under
the graveyard and **139** on the reapable `/dev/shm` tmpfs — so match on the digests, not on
any one path. The four lines are:

- **three** comment lines in `hooks/lib/contract_runtime.py` (frozen lines 720-722, inside the
  717-725 span) whose absolute-line-number citations were **replaced** with symbolic ones
  naming the emitting function and construct — replaced, not removed; and
- **one removed** `import os` in `hooks/tests/test_report_projection_contract.py`.

Stated precisely so that no reader concludes the work was lost: **the work was not lost.**
What is terminal is the *cycle bookkeeping* — the lifecycle records that would have carried
these cycles to a closed state — not the engineering content, which is merged and reachable
from `origin/master`. `dce9fff9` landed
`hooks/lib/contract_runtime.py` (+268) and `hooks/tests/test_report_projection_contract.py`
(+900), 1155 insertions and 13 deletions across two files. **[re-verified]**

---

## 3. Correction to an earlier record

This correction is recorded prominently because **it corrects a claim I made myself in an
earlier record.**

The existing **completion record** for one of these cycles states that **no copy of the
predecessor's failing verification bytes survives.**

**That claim is false**, and it remains false. A copy of the failing bytes exists
**outside the repository**. The bytes originally cited were:

```
size   : 87,706 bytes
sha256 : a9eb0e254ef4aaf78b02081c54c31e1496b564236726e24c7f95d7c4faf24448
qa.status  : "fail"
qa.failures: 14 findings   (qa.all_findings likewise 14)
task_id / request_id : both 20260902-140306
```

**The originally cited path is gone.** As of **2026-09-05T11:43Z**:

```
/dev/shm/claude-tmp/tmp.BO8RxnvGzR/dev/qa-report-20260902-140306.json   -> No such file or directory
/dev/shm/claude-tmp/tmp.BO8RxnvGzR                                     -> No such file or directory  (reaped)
/dev/shm/claude-tmp                                                    -> exists, 25,527 entries     (root survives)
```

The random temporary directory was reaped; only its parent root survives. That path was the
**sole locating evidence** offered for this self-correction, so as originally written the
correction had become uncheckable.

**The bytes themselves were relocated, not destroyed.** An ignore-blind filesystem walk
(`find`, not the shell's ignore-applying `grep` wrapper) over `/` (`-xdev`) and `/dev/shm`
at 2026-09-05T11:43Z finds the reaped directory preserved under a dated graveyard on disk:

```
path   : /var/backups/shm-graveyard-20260905/tmp.BO8RxnvGzR/dev/qa-report-20260902-140306.json
size   : 87,706 bytes                                                    (matches)
sha256 : a9eb0e254ef4aaf78b02081c54c31e1496b564236726e24c7f95d7c4faf24448 (matches, exactly)
mtime  : 2026-09-03T02:58:53Z
qa.status "fail", 14 findings, task_id / request_id both 20260902-140306
```

The digest and byte count are **byte-for-byte the values recorded above**, so this is the
same artifact, not a lookalike. **Treat this path as volatile too**: it is a dated reaping
directory outside the repository (on `/dev/sda1`, not on the `/dev/shm` tmpfs that was
reaped), and nothing guarantees it outlives the next sweep. The digest is the durable
identifier; the path is not.

**The aggravating fact, and the reason a re-checker is likely to conclude the opposite.**
Of the **102** surviving copies of a `qa-report-20260902-140306.json` located by that walk,
**101 carry a passing `qa.status`** and exactly **one** carries `"fail"` — the graveyard
copy above. Measured 2026-09-05T11:43Z, and re-measured by an independent walk at
**2026-09-05T12:52Z**: 102 copies again, the same four rows, the same single failing copy.

| `qa.status` | findings | bytes | sha256 (first 12) | copies |
|---|---:|---:|---|---:|
| `"pass"` | 0 | 71,298 | `9ca4e7d1e3ed…` | 99 |
| `"pass"` | 14 | 83,490 | `3063b8e0b975…` | 1 |
| `"pass"` | 14 | 83,520 | `d056a25489b6…` | 1 |
| **`"fail"`** | **14** | **87,706** | **`a9eb0e254ef4…`** | **1** |

So a future reader who re-checks this correction by looking up the task identifier is
overwhelmingly likely to land on a passing copy — 99 of them report a clean pass with **zero
findings**, and two more report `"pass"` while carrying fourteen findings, which is
misleading on its own terms. The failing bytes are a **single copy out of 102**, reachable
only at the graveyard path. They were *located* by an ignore-blind walk — but an earlier
revision of this sentence went on to claim they were reachable **only** by one, and that is
**false**. Tested 2026-09-05T12:52Z: no `.gitignore` or `.ignore` file exists at any level of
`/var/backups` down to that directory, and the shell's ordinary ignore-**applying** matcher —
the very wrapper this document warns about — run rooted at the graveyard directory returns the
file, **exit 0**. Ignore-blindness is not what makes the copy hard to find; **reason 2 below
is** — it sits outside the repository. **Match on the digest
`a9eb0e25…` / 87,706 bytes, not on the filename or the task id.**

**The correction stands.** The completion record's "no copy survives" claim is wrong: a copy
does survive, and it is identified above. What changed since this correction was first
written is only the *location* of the evidence, not its existence.

**The conclusion is unaffected**, for three independent reasons:

1. Its **status vocabulary is the wrong one for the lifecycle** — it emits `"fail"`, which
   is not the value the lifecycle recognises as its non-pass verdict.
2. It **sits outside the repository** — originally under a temporary directory, now under a
   dated graveyard directory — so the reader of the repository never sees it. The reaping
   of the original path, and the survival of the bytes at the graveyard path, both leave
   this reason intact: neither location is inside the repository.
3. **Restoring it would break the passing binding** — the single mutable verification path
   currently holds the passing bytes, and overwriting them re-creates precisely the
   contradiction described in §1.2.

But **the claim as written is wrong, and the correction belongs on the record.** Per the
constraints of this task, **the completion record itself is not edited**; the correction is
stated here and here only. A reader who encounters the "no copy survives" sentence in that
record should treat it as superseded by this section.

---

## 4. The resolver disagreement

This bears directly on whether these cycles are **truly** terminal, and it should not be
flattened.

**Three revisions of the artifact-chain resolver are in play on this machine, and they do not
agree on the same chain** — the chain of `20260902-140306`, the declaration-less cycle of §1.2. **[re-verified, and corrected:
an earlier revision of this table named the wrong failing revision. See "The correction" below.]**

| revision | blob | verdict on `20260902-140306` |
|---|---|---|
| committed at `dce9fff9` (identical at `origin/master` and at `HEAD` `b4b5f13b`) | `df44bc6885a92f24169599f3ba8d732df42b2b44` | **pass** |
| main checkout working tree, reached through `/root/.claude` (**volatile**) | `c02db5f674914cd6d1a5661bc2cdc27b3cfe7aa2` | **pass** |
| overnight worktree working tree, uncommitted (**volatile**) | `b89d551bca593d68166fd810c320cb0fc8433868` | **fail — `MISSING_DECLARATION`** |

All three blob identifiers and all three verdicts were measured at **2026-09-05T13:00Z**; the
first two identifiers were also confirmed at 11:43Z and are unchanged. The committed one is
durable; both **working-tree blob ids are inherently volatile** — those files are edited by
concurrent sessions, and an id changes with every edit. If a reader's `git hash-object`
disagrees, the tree has moved on; re-derive it rather than assuming this table is wrong.

**The correction.** An earlier revision of this table had two rows and attributed the
missing-declaration failure to `c02db5f6…`, the main checkout's revision reached through the
`/root/.claude` symlink. **That attribution is false**, and it was measured false: run against
the same project directory and the same chain, `c02db5f6…` returns **pass**, exactly as the
committed revision does. Over every project root on this machine that holds these artifacts —
40 (root, task-id) cells — the committed and main-checkout revisions returned the identical
verdict in **every** cell and disagreed in **none**. The revision that actually emits
`MISSING_DECLARATION` is `b89d551b…`, the resolver **checked out and uncommitted inside the
overnight worktree**, which is the invocation the abandonment record quotes
(`--project-dir <this worktree>`, run from that worktree). Its sibling is what distinguishes
it: only the overnight worktree's uncommitted `scripts/aggregate-dev-report.py` (`ff229ed8…`)
defines the lifecycle vocabulary this failure is expressed in — `PHASE_STATES` (seven states)
and `TERMINAL_STATES` (`qa_pass`, `superseded`). That vocabulary is **absent from
`origin/master`, from `dce9fff9`, from `HEAD` and from the main checkout**. The disagreement is
therefore real, and the conclusion below stands; only the failing side was misnamed.

`scripts/resolve-dev-artifact-chain.py` is modified in **both** working trees: a 174-line diff
against `HEAD` in the main checkout (**re-measured 2026-09-05T12:54Z**), and a separate
uncommitted revision inside the overnight worktree. The blob committed at `dce9fff9` and the
blob at `origin/master` are byte-identical, so the published resolver is the one that returns
a **passing** verdict.

**A fresh clone runs the committed one.**

Therefore, stated plainly rather than flattened: **the cycle is stranded under the
machinery this machine actually executes, and not necessarily under the machinery that is
published.** The strandedness is a property of the *uncommitted* resolver-and-aggregator pair
**inside the overnight worktree** — not of the main checkout, which passes, and not of anything
published. A clean checkout running `df44bc68` gets a passing verdict on this chain; so does
the main checkout. Which revision is *correct* is not settled by this document — but any reader
reproducing the determination must first establish **which resolver revision they are running,
and from which checkout**, or they will not reproduce it.

---

## 5. Determination

**Three** cycles are **terminal and cannot be closed**:

- `20260903-115527` — at a terminal passing state; all seven successor states rejected by
  the live validator, two of them as absorbing terminal states; control accepted with zero
  errors. (§1.1)
- `20260902-140306` — declaration-less; a truthful two-round history is unrepresentable
  under one mutable verification path per singular parent; positive control returned zero
  errors. (§1.2)
- `20260904-181435` — implementation complete and verified, blocked by the **aggregation
  contract**: the canonical aggregate's `baseline_dirty_snapshot` equality invariant is
  constructionally inapplicable under the sequential dispatch its own file-overlap forced.
  Both lane shards are `completed` with empty `blocking_issues`. (§6)

**These two bullets were transposed in an earlier revision of this section**, which attached
the terminal-state finding to `20260902-140306` and the declaration-less finding to
`20260903-115527` — contradicting §1.1, §1.2 and §3 of this same document. Measured
2026-09-05T12:59Z, on the canonical artifacts themselves: `dev-report-20260902-140306.json`
carries **no** `artifact_chain_declaration`, and the resolver the overnight worktree runs
rejects it with `MISSING_DECLARATION` at that path; `dev-report-20260903-115527.json` **does**
carry one, whose single member sits at `qa_pass` — a member of `TERMINAL_STATES`. The "seven"
and the "two" are the sizes of `PHASE_STATES` and `TERMINAL_STATES` in that same lifecycle
implementation.

**Their substance is not lost** — it shipped in `dce9fff9`, **three comment lines replaced and
one import removed** from the predecessors' frozen bytes (§2 states the delta once, with
locators and digests), and is reachable from `origin/master`.

The structural causes are recorded as new defects **R30–R35** in
`docs/dev/specs/spec-20260904-harness-fixes.md`, section "2026-09-05 追加", and were left
unfixed by instruction. **That pointer does not survive a clone**: `git check-ignore -v` on it
answers `.gitignore:142:docs/dev/` (measured 2026-09-05T13:02Z), so the spec is ignored for the
same practical reason the worktree records above are — which is why each defect's substance is
restated here rather than left to the pointer. All **six** map to a section of this document:
**R30** (close gate positioned after an absorbing terminal state) is the cause of §1.1;
**R31** (one mutable verification path per singular parent) is the cause of §1.2; **R32**
(status-vocabulary mismatch) and **R34** (the wrong survival claim) are the subject of §3;
**R33** is the resolver disagreement of §4; and **R35** (the shell's default text matcher
applies ignore rules, so a whole-tree scan silently under-reports) is why §3's population walk
was done ignore-blind — though, as §3 now records, no ignore rule governs the graveyard path
itself. Six identifiers, six mappings: an earlier revision listed only five, omitting R35.

**Numbering note**: these six were first appended to the spec as R22–R27 and were
**renumbered to R30–R35** on 2026-09-05. A concurrent session had independently numbered an
unrelated `push.sh` item R22, leaving two `### R22.` headings in one file; the six were
moved above every heading then present (the highest was R29) to clear the collision. The
other session's R22 was not touched. Cite these defects by the new numbers — the old
R22–R27 numbers no longer identify them, and R22 in particular now resolves to a different
item entirely.

---

## 6. The cycle blocked by its own aggregation contract

`20260904-181435` — fan-out, two lanes (`-a` = req-01, `-b` = req-02), parent session
`dev-20260904-181435`. **Terminated blocked at Step 12 of 17.** Steps 13–17 were not run and
are not marked run.

### 6.1 The implementation is good; the contract stopped it

Both lane shards report `dev.status: "completed"` with **empty** `blocking_issues`, and both
were verified by execution rather than by reading:

- **lane a** — 26 of 26 executable criteria pass under their own recipes, plus one `data`
  criterion; **four adversarial ledger rebuilds each fail as required** (`newkeyonly` 4 failed,
  `windowonly` 3, `constreason` 2 — the last caught *solely* by the reason-equality assertion,
  proving the two assertions are non-subsuming — and `alwaysrearm` 7), while the conforming
  build passes 7.
- **lane b** — 12 of 12 criteria pass across **129 machine assertions, zero failures**; it found
  and fixed one regression in the sibling lane's tests by execution.

### 6.2 Two figures this record originally carried, and their refutation

Both were refuted by an **independent test-executor that wrote none of the code**. The
superseded values are kept deliberately: a record that preserves its own overturned numbers is
more trustworthy than one that reads as though it were right the first time.

| Claim as first recorded | Independently measured | Disposition |
|---|---|---|
| facade module `159 collected / 159 passed`, ~112s | **`167 passed in 121.93s`** — 167 collected, 0 failed, 0 error, 0 skipped, 0 xfail | **Refuted by +8.** 159 was *correct when taken*; lane b afterwards added 8 tests to the same uncommitted file. Stale, not wrong-at-source. |
| whole `tests/` tree `167 passed, 0 skipped` | **`51 failed, 824 passed` of 875 collected**, 467.27s | **Refuted by +657.** A lane reported its own **single-module** count as a whole-tree result. That is an error in the lane's report, corrected here and in the aggregate. |

Generated skeleton trees contribute **0** to both figures (`conftest.py`'s `pytest_ignore_collect`
never descends without opt-in; the bare `875 tests collected` carries no `deselected` suffix,
proving non-collection). Under explicit opt-in this cycle's two trees hold 94 tests, **all**
unrealized `TEST_INCOMPLETE` stubs converted to xfail — zero realized.

### 6.3 The 51 red tests — attribution is PROVISIONAL and must be re-measured

They sit in two modules: 50 in `tests/test_public_core_residue_gate.py`, 1 in
`tests/test_release_pipeline_contract.py::test_wellformed_sbom_verifies`. Single shared root
cause: `scripts/check-public-core.sh` is red against the working tree, so that module's
in-source "causal control" fails and its dependents fall with it. Zero failures in the facade
module inside the tree run; the two modules run alone reproduce exactly `51 failed, 21 passed`,
so the failures are neither order-dependent nor cross-module pollution.

The evidence pointed to *pre-existing and unrelated*: three residue lines are committed **at
HEAD** (`hooks/pretool-git-privilege-guard.py:1372`, `hooks/tests/test_bulk_commit_sentinel.py:668`,
`hooks/tests/test_residual_false_positives.py:125`) and clean in `git status`; a further new
residue line at `commands/dev-overnight.md:1070` is a **concurrent session's** uncommitted edit;
and the one flagged lane file (`commands/paseo-daemon.md:432`, `/root/bin/*`) is pre-existing —
the identical line sits at HEAD line 310 and `git diff -U0 HEAD` contains no hunk adding it.

**Do not inherit that attribution as settled.** It was measured against HEAD `71f5dfbc`. HEAD has
since advanced to `68a2205b` (via `b4b5f13b`), so **the 51 failures and their attribution must be
re-measured before any downstream cycle relies on them.**

### 6.4 Why the cycle cannot complete

The two lanes' target file sets **overlap completely** — `scripts/paseo-daemon-ledger.py`,
`tests/test_paseo_daemon_ledger.py`, `commands/paseo-daemon.md`. Parallel dispatch would
therefore lose updates, so the orchestrator dispatched them **sequentially**. Lane b consequently
observed a working tree that already contained lane a's edits, including the new file
`tests/fixtures/paseo_cron_vendor_vectors.json`.

The canonical aggregate requires every worker's `baseline_dirty_snapshot` to be **equal**. Under
sequential dispatch that invariant is not violated — it is **constructionally inapplicable**, and
the mismatch is a *true* report of a real difference. `scripts/aggregate-dev-report.py:270`
reports `shard 'b': baseline_dirty_snapshot mismatch`; `:447` then errors with **zero artifact**,
where `commands/dev.md` Step 11 prescribes writing a **blocked** aggregate instead. Both defects
are recorded as **R28** and **R29** in `docs/dev/specs/spec-20260904-harness-fixes.md` (that
pointer does not survive a clone — `docs/dev/` is ignored at `.gitignore:142` — which is why the
substance is restated here).

The orchestrator wrote the blocked aggregate **by hand, per the specification**, and did **not**
edit either shard to equalise the field: forcing the two values equal would assert that both
lanes saw the same tree, which is false. The read-only artifact-chain resolver then returned
`status: fail`, exit 2, six errors:

    INVALID_DEV_STATUS    dev.status is 'blocked'; expected 'completed'
    UNRESOLVED_BLOCKERS   blocking_issues is not empty
    INVALID_SHARD_SET     shard 'b': baseline_dirty_snapshot mismatch
    MISSING_ARTIFACT      docs/dev/completion-20260904-181435.md
    MISSING_ARTIFACT      docs/dev/qa-report-20260904-181435-a.json
    MISSING_ARTIFACT      docs/dev/qa-report-20260904-181435-b.json

The last three are Steps 13/17 output, not yet produced. Producing them would retire **two** of
the six; **the first three survive any amount of further work**, which is why Step 13 was not run
and the cycle was terminated here rather than pushed toward a completion it cannot reach.

### 6.5 Disposition

Nothing from this cycle was committed, staged or pushed. Its artifacts remain on disk under
`docs/dev/` (ignored, so not clone-reachable): two lane tickets, contexts and criteria files, the
per-lane BA-QA reports carrying three full validation rounds plus two narrow verifications each,
two lane dev-reports, the hand-written blocked aggregate, two test-writer reports and two
generated skeleton trees. Recorded 2026-09-05; determination **blocked-terminal**.
