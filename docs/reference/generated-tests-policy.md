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

## Why it is excluded from the default runner

Because the skeletons intentionally fail, running them in the default suite would
turn every cycle red. Both runners therefore skip the tree:

| Runner       | Location          | Flag                        |
|--------------|-------------------|-----------------------------|
| `pytest.ini` | `addopts` line    | `--ignore=tests/generated`  |
| `scripts/test` | invocation line | `--ignore=tests/generated`  |

The real, runnable suite lives under `hooks/tests/` (and the non-generated part
of `tests/`), which is what `testpaths` targets.

## Why it is kept in version control

The skeletons are per-cycle **acceptance-criteria provenance**: they record what
each cycle's ACs were and give the next cycle a concrete starting point to
complete. Keeping them in VCS ties the AC set to the commit that produced it.

## Honest caveat — legacy tracked residue

`.gitignore` (see the `tests/generated/*` block) intends to retain only two
pinned dirs (`20260704-134650`, `20260704-225139`) and ignore the rest. But git
negations do **not** retroactively untrack files that were already committed, so
a legacy residue remains tracked: currently **566 files across ~48 task dirs**,
with **90 `TEST_INCOMPLETE` sentinels in 58 files**.

Reconciling that (a bulk `git rm --cached` of the un-pinned dirs) is a larger VCS
operation touching generated content and is deliberately **out of scope** for this
note. It is documented here as a known state, not fixed.
