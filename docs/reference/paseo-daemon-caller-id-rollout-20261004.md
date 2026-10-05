# `--caller-id` enforcement: immediate rollout, no deploy step, doc gap

**Date**: 2026-10-04
**Subject**: task `20261004-085212` added a mandatory `--caller-id`
authorization check to the ledger CLI. Rollout mechanics and real
operational impact, recorded factually.

---

## What changed
Task `20261004-085212` added `require_lease_holder` /
`require_unsuperseded_holder` checks (`scripts/paseo-daemon-ledger.py`) to
the ledger CLI's mutating subcommands: once a lease exists, only its current
holder may mutate the ledger. Calls without a matching `--caller-id` are
refused.

## No separate rollout step
`~/.claude` resolves to this exact repo checkout. The check took effect for
the live, separately-running controller session the instant the file was
saved — no deploy, restart, or cache-invalidation step between "file
written" and "enforced."

## Observed impact (`.claude/paseo-daemon/journal.ndjson`)
- Live controller went silent ~1h45m: fires from 11:53Z to 12:57Z on
  2026-10-04 are absent from the journal (`fail()` never journals a refused
  call, so only the gap in expected fires shows it).
- Resumed at a fresh `lease-acquire` at 13:12:48Z (incarnation 44).
- Following `wake-observe` reported `missed_fires: 7` vs configured
  `tolerated_missed_fires: 1`.

## Root cause
`commands/paseo-daemon.md` (the controller's own operating instructions)
does not mention `--caller-id` at all, and task `20261004-085212` could not
update it: the file was already dirty with an unrelated, separately
in-flight prose-trim cycle's uncommitted edits (confirmed via `git log -1`
predating the working-tree diff). A controller has no way to learn the new
required flag from its own documented instructions.

## Mitigation landed this cycle
The refusal messages now explicitly name the missing/mismatched
`--caller-id` value and the exact flag+value to pass, so any caller can
self-correct within one invocation instead of needing multiple failed
attempts across ticks.

## Residual risk, disclosed
Until `commands/paseo-daemon.md` is updated (blocked on that file becoming
available), a brand-new controller session starting cold from that doc alone
will still need to discover `--caller-id` via the improved error message
rather than finding it documented. Same disclosure pattern as task
`20261004-050913`'s own `commands/paseo-daemon.md` gap (see that cycle's
do-report).
