# Open findings from read-only cycles — extracted 2026-10-05

Two cycles were scoped, by explicit instruction, to **diagnose and report only**. Both
did that correctly and both produced real findings. Those findings then lived in exactly
one place: the transcript of a workspace queued for deletion.

This file extracts them so the workspaces can be deleted without discarding the analysis.
Nothing here has an owner yet. None of it has been acted on.

## Why this file exists at all

A read-only cycle's output looks like a finished deliverable — a careful, accurate
report that survives scrutiny when read on its own. What it does not have is a
successor. The defect it names stays open, and the record of it is bound to a container
that cleanup is supposed to remove.

This is the third time today the same shape appeared. An earlier `spec` desk opened only
because its predecessor had "announced but not written to disk" its rulings, which then
vanished with the session. Code survives in git; **reasoning survives only where someone
writes it down**.

---

## A. Specification defects found by the comprehension self-report cycle

Dispatch (2026-09-30T10:38:21Z) was explicit: *"your ONLY task right now is a
comprehension self-report… DO NOT: modify, create, or delete any file… This is a
read-and-report exercise only."* The cycle obeyed that and reported 33 issues across two
rounds. Seven are substantive:

| # | Finding | Severity as reported |
|---|---|---|
| 6 | `commit` treats "cannot compute" as "nothing to commit" — a category error, not a threshold | real defect |
| 7 | Three return codes are referenced but missing from the table that defines them | load-bearing gap |
| 8 | A `recheck` field is marked as read by nobody — measurement showed it had since been corrected | self-refuting |
| 19 | Step 17's dispatch lacks an obligation-block definition | could not confirm |
| 20 | A stderr format reference points at the wrong thing — measurement showed it corrected | self-refuting |
| 21 | A `CLOSE: NO` example is labelled stale but is in fact live wiring | severity understated |
| 25 | A line-number count is off by 26 | arithmetic error |

The same cycle produced a rework plan (R1–R10) marked *"可直接投 spec"* — ready to
dispatch as a specification. It was never dispatched.

Two of the seven (#8, #20) are worth noting as a class: the cycle **reported its own
earlier claims as refuted by later measurement** rather than quietly dropping them.

---

## B. Workspace disposition verdicts

Recorded separately in `workspace-disposition-criteria-20261005.md`: an A/B/C criterion
for stale-workspace disposition plus five evidence-backed verdicts, likewise never acted
on. The B category — *superseded path, name the commit that replaced it* — is absent from
the two-way "residue + requirement satisfied" test used during the cleanup, and is the
reason a workspace can be neither finished nor unfinished.

---

## C. What would close these out

Nothing here needs a decision about priority to be preserved — preservation is this
file. What is still missing for each item is an owner. The seven specification defects
in section A need either a `/spec` cycle that consumes the R1–R10 plan, or an explicit
ruling that they are accepted as known and will not be fixed. Either is a terminal
state; neither has happened.
