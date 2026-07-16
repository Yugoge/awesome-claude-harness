# `tests/generated/` policy — tracked but ignored, on purpose

> Last updated: 2026-07-16 (Phase 1 of `docs/reference/test-suite-overhaul-plan.md`)

`tests/generated/` is git-tracked yet excluded from the default test run. This
looks contradictory at a glance, so this note records the intent **and the
ratified go-forward decision** (gate-behind-a-marker, see below). Phase 1 changes
no runner and untracks nothing — it only ratifies the decision and corrects this
doc's earlier claim (which said every skeleton hard-stops) to the measured reality.

## What is in `tests/generated/`

The `test-writer` subagent emits one pytest skeleton per acceptance criterion
from a cycle's `acceptance-criteria-<task_id>.json`. A fresh skeleton is a stub
that hard-stops via `pytest.fail("TEST_INCOMPLETE: ...")` so it can never
masquerade as a passing test — but **most skeletons no longer hard-stop.**

**Measured reality (2026-07-16, per `test-suite-overhaul-plan.md` §1):** of the
**449** `test_*.py` skeletons, **≈393 have been realized** into real assertions
(the hard-stop removed as a human/cycle filled them in) and only **≈56 still
hard-stop** by design. So the tree is a *mix* of realized tests and stubs, not a
uniform wall of `TEST_INCOMPLETE`. (The residue caveat below counts **58** files
bearing a `TEST_INCOMPLETE` sentinel; that grep also matches non-`test_` and
archived files, hence the small delta from 56.) A sampled run of the realized
files showed ≈10% bit-rot — they assert against paths/behaviors that have since
drifted — so the realized set is **not green as-is** and cannot simply be
un-`--ignore`d.

## Why it is excluded from the default runner (today)

The tree is a mix of ≈56 hard-stopping stubs and ≈393 realized-but-~10%-bit-rotted
tests. Either category would turn the default suite red — the stubs by design, the
bit-rotted realized ones by drift — so **today both runners blanket-skip the whole
directory:**

| Runner       | Location          | Flag                        |
|--------------|-------------------|-----------------------------|
| `pytest.ini` | `addopts` line    | `--ignore=tests/generated`  |
| `scripts/test` | invocation line | `--ignore=tests/generated`  |

The real, runnable suite lives under `hooks/tests/` (and the non-generated part
of `tests/`), which is what `testpaths` targets. See
[../../tests/TESTING.md](../../tests/TESTING.md) for the full surface/runner map.

## Ratified go-forward policy — gate-behind-a-marker (Phases 2–3)

**Decision (ratified 2026-07-16):** replace the blanket `--ignore=tests/generated`
with a **`generated` pytest marker** so realized+green skeletons become
*opt-in-runnable* rather than *invisible*:

| Category | Marker treatment | Runs on default `scripts/test`? |
|---|---|:--:|
| Realized **and** green | tagged `@pytest.mark.generated`, opt-in via `pytest -m generated` | ❌ (deselected by marker, not `--ignore`) |
| `TEST_INCOMPLETE` stub | quarantined (not tagged into the opt-in path) | ❌ |
| Realized but bit-rotted | quarantined until repaired | ❌ |

Why a marker and not un-`--ignore`ing: the default run must stay at the **green
floor (1250 passed / 9 xpassed)**. A marker deselects the tree from the default
run *by tag* while making the realized+green subset runnable on demand
(`pytest -m generated`) — turning the tree from "tracked and invisible" into
"tracked and deliberately runnable."

**Not implemented in Phase 1.** This section only *ratifies* the decision so
Phases 2–3 can execute it. The wiring (marker registration in `pytest.ini`,
`scripts/test` gating, and the `test-writer` emit-contract update) lands in
**Phase 2/3** per the plan's phased sequence — nothing in Phase 1 touches
`pytest.ini`, `scripts/test`, or any runner.

## Why it is kept in version control

The skeletons are per-cycle **acceptance-criteria provenance**: they record what
each cycle's ACs were and give the next cycle a concrete starting point to
complete. Keeping them in VCS ties the AC set to the commit that produced it.

## VCS reconcile — DONE (legacy tracked residue removed from the index)

`.gitignore` (see the `tests/generated/*` block) intends to retain only two
pinned dirs (`20260704-134650`, `20260704-225139`) and ignore the rest. git
negations do **not** retroactively untrack files that were already committed, so
a legacy residue had remained tracked (**566 files across ~48 task dirs**).

That residue has now been **reconciled**: a bulk `git rm --cached` of the 46
un-pinned dated subtrees (507 files) removed them from the index while leaving
every file **on disk**. The VCS state now matches the `.gitignore` intent —
`git ls-files tests/generated` = **59** (the 2 pinned dirs = 56 files, plus the
doc-sync `INDEX.md`/`README.md` and the `manifest.json` provenance ledger), and
`git check-ignore` reports the un-pinned generated files as ignored. The files
stay on disk and remain opt-in-runnable via the `generated` marker
(`pytest tests/generated -m generated`) — untracking did not remove them from
collection. Only the pinned dirs and the three management files stay tracked.
