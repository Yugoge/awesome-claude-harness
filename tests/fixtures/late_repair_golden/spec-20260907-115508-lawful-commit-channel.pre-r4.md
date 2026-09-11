# Spec — every completed unit of work must have a lawful, non-force route to `/commit`

**Spec id**: `spec-20260907-115508-lawful-commit-channel`
**Created**: 2026-09-07
**Origin task**: `20260907-115508` (Paseo history investigation; its own commit was blocked by this gap)
**Status**: ready for a `/dev` cycle to consume

---

## 0. The invariant to restore

> **A more complete artifact set must never have fewer lawful routes to commit than a less
> complete one.**

This is violated today, and the violation is the whole spec. Work with **no** dev-report
has a lawful non-force route (the `/close` do-report path). Work **with** a dev-report but
a broken close chain has **none**. The artifact set that represents *more* completed
process is the one that gets trapped.

Because `--force` is permanently prohibited, "only force remains" is equivalent to **no
route exists**, and the work is stranded as untracked files — one cleanup away from loss.

## 1. Measured evidence

Both instances measured `2026-09-07T11:58:50Z`–`11:59:05Z`.

### R1 — the trap (repo `/root/.claude`, lane `20260906-085036`)

```
dev-report = Y   qa-report = N   do-report = N   close-report = N
```

- The dev-report exists, so `/close` resolves this as a **dev chain**.
- The dev chain's preflight requires a passing `qa-report`. QA was never run, so it fails.
- The do-report lite path is **barred by rule**: *"A canonical dev-report takes precedence
  and is resolved as a dev chain; do not use a do-report to bypass a failing dev chain."*
- Remainder: `--force` only. Prohibited. **Stranded.**

### R2 — the near-miss (task `20260907-115508`, repo `/root`)

The `/do` consent sidecar is **session-keyed and never rotates**:

```
/tmp/claude-do-task-4bb3236c-….json  ->  task_id 20260903-005106,
                                         created 2026-09-03T00:51:06Z
```

That id was **already consumed**: `do-report-20260903-005106.json` and
`close-report-20260903-005106.md` both exist. The documented resolution order says to use
the sidecar's `task_id`. Following it literally would have **overwritten a closed task's
artifacts** and misattributed 2026-09-07 work to a task closed four days earlier.

This is a **data-loss-grade defect**, caught only because a collision check was run by
hand. A long-lived session gets **one** task-id for its entire life; every `/do`-shaped
unit of work after the first either silently falls back or destroys a closed task's record.

## 2. Requirements

### R1 — a completed dev chain missing only QA must be completable, not forced

**The remedy is to run the QA that was never run — not to skip it.** `--force` must remain
prohibited and must not be widened.

- **R1.1** `/close <task-id>` on a dev chain whose only preflight failure is an absent or
  non-passing `qa-report` MUST offer a *completion* route: dispatch the missing QA for the
  task's declared file set, then re-run the preflight.
- **R1.2** That dispatch MUST be a genuine verification producing a genuine verdict. A
  `fail` or `warning` verdict MUST propagate honestly and MUST NOT be upgraded to unblock
  the close. **The route creates a missing artifact by earning it; it never fabricates one.**
- **R1.3** If QA returns a non-passing verdict, `/close` MUST report `CLOSE: NO` with the
  verdict, and the work stays uncommitted. That is a correct terminal state, not a failure
  of this mechanism.
- **R1.4** The route MUST refuse when the chain is missing more than QA (e.g. absent
  ticket/context/dev-report). It closes exactly one gap and does not become a general
  chain-repair bypass.
- **R1.5** Every artifact created by this route MUST record that it was produced by
  late completion, with its measurement moment — never presented as contemporaneous with
  the original cycle.

### R2 — `/do` task-id issuance must be per-unit-of-work, not per-session

- **R2.1** A sidecar `task_id` that already has a `do-report-<id>.json` or
  `close-report-<id>.md` on disk MUST be treated as **consumed** and MUST NOT be reused.
- **R2.2** On detecting a consumed sidecar, the resolver MUST mint a fresh id via the
  documented atomic `set -o noclobber` reservation and MUST record the substitution and
  its reason in the resulting do-report.
- **R2.3** Writing a `do-report-<id>.json` over an existing file MUST be refused
  outright. Overwriting a closed task's artifacts is never a valid outcome.
- **R2.4** The collision check MUST be automatic. R2's near-miss was caught by hand; the
  mechanism must not depend on an operator remembering.

### R3 — no completed work may be left with zero lawful routes

- **R3.1** When `/close` or `/commit` refuses, the refusal MUST name at least one lawful
  route to completion, or state explicitly that none exists and that the work is stranded.
- **R3.2** A refusal MUST NOT name `--force` as its only remedy, since force is
  prohibited. Today's guard text names `/commit <task-id>` and bare `git commit` — the
  first is unreachable without a chain, and the second is prohibited.

## 3. Acceptance criteria

- **AC-1** Lane `20260906-085036` reaches `/commit` **without force**, via R1's QA
  completion route, or is honestly recorded as `CLOSE: NO` on a real non-passing verdict.
- **AC-2** A test proves R1.2: a QA verdict of `fail` on the completion route blocks the
  close, and no artifact is rewritten to unblock it.
- **AC-3** A test proves R2.1–R2.3: given a sidecar whose `task_id` already has a
  close-report, the resolver mints a new id and **refuses** to overwrite the existing
  do-report. Negative control: a sidecar with an unconsumed id is used unchanged.
- **AC-4** R1.4 proven by a chain missing ticket *and* QA: the route refuses rather than
  repairing both.
- **AC-5** No change widens `--force`, and no test requires it.

## 4. Explicitly out of scope

- Widening `--force`, or adding any new bypass flag.
- Auto-generating tickets/contexts/dev-reports for work that never produced them.
  R1 completes **one** missing verification by performing it; it does not backfill process
  that never happened.
- The two deferred design decisions in `docs/paseo-history-investigation-20260907.md` §4
  (WARM `--safe-links` gap; watchdog registry churn). Unrelated, user's call.

## 5. Provenance note

`/root/docs/dev/` is gitignored (`.gitignore:230`), so this spec is durable against the
conversation ending but **not** against a working-tree cleanup — the same exposure that
motivated the spec. Relocate it to a tracked path if it should survive that too.

The lane in R1 lives in `/root/.claude`, a **separate git repository** on tmpfs; the origin
task in R2 lives in `/root`. The gap spans both, so a fix must not assume a single repo.

---

<!-- spec-continuation-of: 20260906-085036 -->

### Cycle 1

## 2. What was attempted, and why it did not finish

R1's completion route was exercised end to end on lane `20260906-085036`, under explicit
human authorization to run it as a genuine repair rather than a backfill: an independent BA
subagent performed real retrospective requirements analysis (verifying the diff against
`HEAD`, re-running the 63-test suite itself, correcting a drifted `Request ID` metadata
label, and correcting the record's own attribution of an earlier QA finding), producing
`ticket-20260906-085036.md` and `context-20260906-085036.json`. The orchestrator then wrote
a `completion-20260906-085036.md` explicitly labeled as a late/retrospective completion, per
R1.5. `scripts/resolve-dev-artifact-chain.py` returned `status: pass, errors: 0` for the
resulting five-artifact chain (ticket/context/dev-report/qa-report/completion), and
`/close 20260906-085036 --codex` was run for real.

QA, with a mandatory adversarial codex round, returned **CLOSE: NO** — correctly, on real
measurement, not manufactured to make this spec's AC-1 pass. Three findings, independently
confirmed by QA itself (not taken from codex's word):

1. **A separate, later narrowing step (2026-09-07) modified the same two implementation
   files** (`hooks/pretool-gitignore-preflight.py`,
   `hooks/tests/test_gitignore_preflight_close_contract.py`) after this task's dev-report
   was finalized (2026-09-06). The dev-report's provenance metadata (`owned_edits`,
   `final_source_hashes`, `untracked_modified_provenance`) describes only this task's own
   endpoint, not the current combined worktree state. QA ran
   `scripts/stage-owned-hunks.py` directly against the live dev-report and worktree: **both
   files `EXCLUDE` with exit code 10.** `resolve-dev-artifact-chain.py`'s `status: pass`
   validates artifact-path *structure* only; it does not prove the underlying source diff
   is still stageable once a second, independent change has interleaved into the same
   files. A `/commit` run today would silently exclude both implementation files.
2. The existing `qa-report-20260906-085036.json`'s `pass` verdict is semantically about a
   *different* narrowing step (E2) that a QA round-1 finding was actually about, not the
   step (E4) this task's own diff implements — a real, honestly-disclosed caveat, not
   independently blocking, but symptomatic of the same "no artifact accounts for the
   combined end state" gap as (1).
3. **This spec's own text directly conflicts with itself once R1's route actually runs.**
   R1.4 requires the completion route to *refuse* when the chain is missing more than QA
   (e.g. ticket/context also absent). §4 puts "auto-generating tickets/contexts... for work
   that never produced them" explicitly out of scope. Lane `20260906-085036` was missing
   ticket, context, acceptance-criteria, *and* completion when this cycle began — not only
   QA. The retrospective BA ticket/context this cycle produced, even though genuinely
   analyzed and independently verified rather than invented, is exactly the backfill §4
   prohibits and R1.4 says the route must refuse rather than perform.

Both human errors behind letting this run anyway are recorded, not hidden: the 06:55Z
ruling ordered "§4 stays intact" in the same breath as authorizing exactly what §4
excludes, and across all four QA/close rounds on this lane nobody was asked to verify
whether the *recorded provenance* could still drive a real `git add` once other work had
touched the same files — every round checked "is the code correct," none checked "can the
staging mechanism actually stage it."

## 3. Changed files / artifact references (not duplicated here)

- `hooks/pretool-gitignore-preflight.py`, `hooks/tests/test_gitignore_preflight_close_contract.py`
  — the implementation under evaluation.
- `docs/dev/{ticket,context,dev-report,qa-report,completion,close-report}-20260906-085036.*`
  in `/dev/shm/dev-workspace/dot-claude` (== `/root/.claude`) — the full chain, all still on
  disk, undestroyed, self-labeled retrospective/late where applicable.
- `docs/dev/specs/spec-20260904-harness-fixes.md` R64, same repo — the unrelated harness
  defect (`pretool-subagent-enforce.py` contract-gate) that had to be worked around via
  disclosed, narrow `cycle-contract.json` repairs to make any of the above dispatches
  possible at all; orthogonal to this spec but part of the honest record of how this cycle
  ran.
- `scripts/stage-owned-hunks.py` — the staging mechanism whose `EXCLUDE`/exit-10 behavior
  is the concrete failure mode R4 below must close.

## 4. Current measured state

`resolve-dev-artifact-chain.py --task-id 20260906-085036`: `status: pass, mode: singular,
errors: 0`. `docs/dev/close-report-20260906-085036.md` last line: `CLOSE: NO`. Three
inspector reports (style, cleanliness, prompt) all returned zero blocking findings against
this diff. `scripts/stage-owned-hunks.py --file hooks/pretool-gitignore-preflight.py
--ledger docs/dev/dev-report-20260906-085036.json ...`: `EXCLUDE`, exit 10 (QA's direct
run; not independently re-derived by this orchestrator with matching arguments — a partial
orchestrator re-check using incomplete arguments produced a different, inconclusive error
and is not evidence either way).

## 5. Remaining acceptance criterion (new)

### 5.1 (new) — R4, a deliberate late-repair route that does not collide with §4/R1.4

AC-1 as originally written is satisfiable in its `OR` branch (an honest `CLOSE: NO` on a
real non-passing verdict) and that branch is now demonstrated. What remains undone is the
first branch — reaching `/commit` lawfully — because no route in this spec's current text
can do that for a lane missing more than QA without either violating §4 (backfilling
process that never happened) or requiring `--force` (permanently prohibited). See R4 below.

## 6. Gap between current state and done

Two gaps, not one:

(a) This spec has no route for the case R1 assumed would not occur: legitimate,
independently-verified late analysis that is nonetheless barred by the spec's own §4/R1.4
text because the chain was missing more than QA. Today's run is the empirical proof this
case is real, not hypothetical.

(b) This spec (and the harness generally) has no mechanism to detect or repair provenance
staleness when a second, unrelated change interleaves into the same files a dev-report
already described. Every prior verification round on this lane (dev, QA round 1, QA round
2, retrospective BA) checked content correctness and none checked stageability — the gap
that produced `stage-owned-hunks.py`'s exit 10 was invisible to all of them until this
cycle's `/close --codex` finally ran the actual staging tool.

## 7. Concrete next plan for the next `/dev` run

Implement **R4** as a new numbered requirement under this spec's §2, alongside R1/R2/R3,
with acceptance criteria appended under §3 (do not renumber R1/R2/R3 or their existing
ACs; append only). R4 must specify, at minimum:

- **R4.1 — genuine re-run, not backfill-with-a-label.** When a chain is missing more than
  QA (the case R1.4 currently refuses outright), the lawful route is to *actually run* the
  skipped BA/Dev/QA stages against the current state of the work — not to write ticket and
  context describing history after the fact. Where the implementation is already complete
  and only the process artifacts are missing (this lane's exact shape), BA's role becomes
  requirements reconstruction *plus a live re-verification pass*, not narrative-only
  analysis; Dev's role, if the diff needs reconciling with interleaved later changes (see
  R4.3), is to perform that reconciliation as real, reviewable work product.
- **R4.2 — mandatory non-contemporaneous disclosure, made a hard gate, not a convention.**
  Every artifact produced by a late/retrospective route must carry an explicit,
  machine-checkable label (not just prose) stating it is retrospective and naming its real
  production moment versus the original cycle's moment. `/close`'s QA gate should verify
  the label is present before treating such a chain as eligible for its completion route at
  all — today this was done by convention (completion.md's late-completion notice,
  ticket.md's retrospective dating) with no gate enforcing it.
- **R4.3 — merged-tree provenance refresh, closing the `stage-owned-hunks.py` exit-10
  class.** Before a chain missing more than QA is allowed to proceed toward `/commit`, the
  route must refresh the dev-report's provenance (`owned_edits`, `final_source_hashes`,
  `untracked_modified_provenance`, `pre_edit_snapshots`) against the file's *current*
  on-disk state, not merely the state at the original dev-report's timestamp, when any
  other change has touched the same file since. This is what would have caught today's
  exit-10 before QA had to discover it manually. Acceptance: a test proving that a
  dev-report whose recorded provenance is stale relative to a live interleaved change is
  either refreshed or explicitly refused — never silently passed through to a staging
  attempt that will fail.
- Do not let R4 become a second route around R1.4/§4's genuine protective intent (blocking
  fabrication). R4.1's "genuine re-run" requirement is what keeps it from being a
  downgrade: the route still requires real verification work, not merely a permissive
  re-reading of what counts as "not fabricated."

## 8. Traps and stale assumptions for the next agent

- **Do not read this cycle's `CLOSE: NO` as a defect to route around.** QA and codex both
  functioned correctly here; the AC-4 negative case (refuse when missing more than QA) is
  the spec working as designed, not a bug. R4 must *add* a lawful route for this shape, not
  weaken the existing refusal.
- **The exit-10 provenance-staleness bug is easy to miss** because four independent
  verification passes (dev, QA×2, retrospective BA) each checked "is the code correct" and
  none checked "can the recorded provenance still drive a real stage/commit." Any future
  verification of a late-completion chain must explicitly run the actual staging tool, not
  just the read-only artifact-chain resolver.
- **§4's backfill prohibition is not a formality to route around with sufficiently genuine
  analysis.** Today's BA analysis WAS genuine (independently re-verified, not invented) and
  §4/R1.4 still correctly barred the route, because the chain was missing more than QA. R4
  must be a distinct, narrower route with its own real-verification requirement (R4.1), not
  a reinterpretation that lets "genuine enough" analysis satisfy §4.
- **`/allow`'s grant mechanism for the `Agent` tool was independently measured
  non-functional this cycle** (a documented `/allow --tool Agent` invocation, confirmed
  issued with no error, produced no grant file at either checked path). This is unrelated
  to R1-R4 but was discovered while working this lane and is recorded here so it is not
  lost; it belongs in a harness-fix spec (see `spec-20260904-harness-fixes.md`), not this
  one.
- The two-repository split noted in the original §5 provenance note still applies: this
  spec lives in `/root/docs/dev/` (gitignored there), while lane `20260906-085036`'s
  artifacts live in `/root/.claude` (`/dev/shm/dev-workspace/dot-claude`), a separate git
  repository. Any `/dev --spec` run against this continuation must resolve artifacts from
  the *lane's* repository, not this spec's own.
