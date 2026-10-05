# Workspace disposition criteria, and the five verdicts that existed only in a transcript

Two things are recorded here. First, a three-way criterion for deciding what to do with
a stale workspace, which an earlier audit cycle defined and which is better than the
two-way test used during the 2026-10-05 cleanup. Second, the five verdicts that cycle
produced — they were printed to its own stdout and **never written to a file**, so
deleting its workspace would have destroyed the only copy.

## The criteria (from the audit cycle, 2026-10-05T02:47Z)

A workspace judged "not delivered" gets exactly one of:

- **A — finish the development and land it.** The uncommitted content is still valid and
  does not conflict with the current architecture. Produce the file list; do not land it
  from the audit itself.
- **B — superseded path.** What this cycle was fixing has since been replaced or deleted
  by later work. **Name the commit that superseded it**, and mark the draft record void.
- **C — nothing to dispose of.** Requires a stated method and a **positive control** —
  search for something known to be present first, to prove the search would have found a
  hit, before reporting zero.

**Why B matters.** The cleanup that followed used only "residue + requirement satisfied",
which has no B. A workspace can be neither finished nor unfinished but simply *aimed at
something that no longer exists*. Without a B category, every later reader has to
re-derive that conclusion from scratch.

**Why C's positive control matters.** A bare "no occurrences" is not evidence; it is
equally consistent with a broken search. This was demonstrated twice during the cleanup:
a reader reported a file as untracked when it had since been committed, and the
orchestrator grepped for a Chinese phrase against machinery that emits English, getting
zero hits on a report that was in fact correct.

## The five verdicts

| # | Workspace | Verdict | Evidence cited |
|---|---|---|---|
| 1 | two specs, neither implemented | **B** | spec-20260726-210921 claimed by cycle 20260726-221830; attribution removed afterwards by `eed4787ed` |
| 2 | 434 uncommitted spec lines | **B + A split** | `spec-20260904-harness-fixes.md:1441–1874`, gitignored, BA/QA pass |
| 3 | quota-interrupted dev cycle | **A** | 9 lanes (`20260930-132644-l1…l9`) contain only graphify/test-writer output; no dev, qa or commit |
| 4 | incident record only in a checkpoint | **A** | HEAD 119 lines vs worktree 256; checkpoint `954c7deeb` holds the complete version |
| 5 | close/commit cannot be correlated | **B / A / undecided split** | of 238 close task-ids, 178 map to commits; 60 do not (30 `CLOSE:NO`, 30 `CLOSE:YES`) |

The audit was explicitly read-only — it was told not to land, stage, or touch indexes —
so none of these five was acted on. They remain open.

## The shape of the loss this file prevents

The audit ran to completion, obeyed every constraint, and produced correct evidence-backed
judgements. Its output then lived in exactly one place: the transcript of a workspace
queued for deletion. Code survives in git; **reasoning survives only where someone writes
it down**. Any cleanup that deletes workspaces should extract this class of output first,
or accept that it is discarding the analysis along with the container.
