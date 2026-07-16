# `tests/generated/` policy — tracked but ignored, on purpose

> Last updated: 2026-07-16 (Phase 1 of `docs/reference/test-suite-overhaul-plan.md`)

`tests/generated/` is git-tracked yet excluded from the default test run. This
looks contradictory at a glance, so this note records the intent **and the
ratified go-forward decision** (gate-behind-a-marker, see below). Phase 1 changes
no runner and untracks nothing — it only ratifies the decision and corrects this
doc's earlier claim (which said every skeleton hard-stops) to the measured reality.

## What is in `tests/generated/`

The `test-writer` subagent emits one pytest skeleton per acceptance criterion
from a cycle's `acceptance-criteria-<task_id>.json`. Each skeleton is a stub: it
hard-stops immediately via `pytest.fail("TEST_INCOMPLETE: ...")` so a stub can
never masquerade as a passing test. They are scaffolds a human (or a later cycle)
fills in — not runnable assertions yet.

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
