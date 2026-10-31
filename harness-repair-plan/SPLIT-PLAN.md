# Split plan: the L and XL phases cut into sub-phases of at most M (D26)

D26 (DECISIONS.md, 2026-10-30): no phase is handed out with an effort above M (about one day of work). Each L or XL
phase below is split into sub-phases, each with its own branch, PR, acceptance tests and merge. The reviewer hands
consecutive sub-phases to different accounts, and sub-phases marked parallel to different accounts at the same time.

- Source of each split: the phase's short prompt, `prompts/short/<phase>.md`. Row ids (R..., X..., C..., suite parts)
  and acceptance-test ids (A...) are that prompt's own. Every one is assigned to exactly one sub-phase.
- Not split: P1b (finished as PR #8), P6 (M), P11 (M).
- Phase order is unchanged: P1b -> P1c -> P2 and P3 -> P4 -> P5 -> P6 -> P9 -> P10 -> P11. A phase starts when every
  sub-phase of the phases its prompt names as dependencies is merged.
- Mergeable alone: every sub-phase leaves master working and CI green, and from P1c-1 on keeps P1c's replay suite
  green (D25's merge rule). P1c-1 is the sub-phase that creates that suite.
- Effort: S is half a day or less, M about one day.

## Hand-off header

The reviewer puts this header in front of the short prompt, with the angle-bracket fields filled from the sub-phase's
row in the tables below.

```markdown
# Sub-phase <ID> of <PHASE>: <goal>

Effort: <S|M> (D26). Split: <PHASE> is cut into <PHASE>-1 ... <PHASE>-<N> (harness-repair-plan/SPLIT-PLAN.md).
You do sub-phase <ID> only. Read this header first, then the prompt below in full. The prompt is the phase
specification; its rules hold except where this header narrows them.

## Your scope
- Do only sub-phase <ID>: rows and items <ROWS>, and acceptance tests <TESTS>. Every other row and acceptance test in
  the prompt belongs to another sub-phase of <PHASE>. Leave it to that sub-phase; do not do it early.
- Everything else in the prompt binds you unchanged: its owner rulings, its DO NOT list, its merge rule. A net code cap
  in the prompt is the phase's total across all its sub-phases; your PR states your sub-phase's net and the phase's
  running total with the merged sub-phases.
- Start checks: run the prompt's start checks, and also check that <DEPENDS ON> are merged into origin/master. Where a
  start check names a merged PR titled `<P>: ...` for a phase that was split, it is met when every sub-phase PR of that
  phase (`<P>-1: ...`, `<P>-2: ...`, ...) is merged. If a check fails, stop and tell the reviewer in your session
  output (never the owner).
- Pull request: one PR for this sub-phase from your session's branch, titled `<ID>: <short goal>`. The prompt's pull
  request section applies to it, with only your acceptance tests. The body's first lines are the prompt's required
  first line, then `Sub-phase <ID> of <PHASE> (harness-repair-plan/SPLIT-PLAN.md). Effort <S|M>.`
- Your PR is mergeable on its own: master keeps working, CI stays green, and P1c's replay suite stays green (D25).

## Budget and stopping rules (they take precedence over any wording in the prompt that asks for open-ended checking)
- Build your sub-phase's rows as specified, run each of your acceptance tests, and record each command and its output
  in the PR.
- Run one self-check round over your own diff; run a second only if the first found a high-severity defect. Fix only
  defects of medium severity or higher; list lower ones in the PR under "Out of scope, found".
- At most three subagents at a time; no refuter panels. Independent review of your PR is the reviewer's; do not
  imitate it with your own multi-agent review.
- Push after each commit, so the work survives a usage limit. If you hit a usage limit, resume the same work after the
  reset; do not start over.
- You are done when your acceptance tests pass, CI is green on your head and your PR is open with its body. Then stop;
  do not start another sub-phase.
- Ask the owner nothing (D18, D19).
```

## P3 (L, about 3 days; 5 sub-phases)

Source: `prompts/short/P3.md`.

| Id | Goal | Rows and items | Acceptance tests | Main files | Depends on | Parallel with | Effort |
|---|---|---|---|---|---|---|---|
| P3-1 | Consumers stop using the deviation provider; strict pass in /close Step 0 and the QA close gate | R4; R16 for R4 (test_dev_lifecycle.py, test_late_repair_route.py, test_dev_artifact_chain_consumer_contracts.py qa.md pins) | none of its own (A1, A15, A20 rules apply to the PR) | `scripts/dev-lifecycle.py`, `scripts/close-route-select.py`, `agents/qa.md` | none (phase start) | P3-3 | S |
| P3-2 | One importable disposition (dev, close, commit, do branch), strict resolver and aggregator, provider deleted | R1, R2, R3, R5; R16 for them (test_resolve_dev_artifact_chain.py, test_aggregate_dev_report.py, test_ac_deviation_record_chain.py, test_ac_deviation_fanout_consumer.py; new: the disposition, R1) | A2, A5, A6, A7, A8 | `scripts/resolve-dev-artifact-chain.py`, `scripts/aggregate-dev-report.py`, `schemas/dev-report.v2.json`, `hooks/lib/obligation.py` (verify) | P3-1 | P3-3 | M |
| P3-3 | Plain failing G2 stop, no arbitration phases; 60 s replay window; codex-enforce skips close/commit | R6, R7, R10, R11; R16 for them (hooks/tests/test_progress_measure.py, test_artifact_contract_enforce.py incl. test_l2_ac7/test_l2_ac13; new: R10, /redev minting as /dev, R11) | A4, A9, A10, A19 | `hooks/lib/progress_measure.py`, `hooks/subagentstop-artifact-contract-enforce.py`, `hooks/prompt-workflow.py`, `hooks/subagentstop-codex-enforce.py` | none (phase start) | P3-1, P3-2 | S |
| P3-4 | Warning commit: scoped and validated aggregate check, close-side exemptions, G2 freshness and lane echo, G1 dispatch order; callers on the disposition | R12, R13, R14, R15, R17 (warning-only, per the "Warning and promotion" item); R16 for them (test_gitignore_preflight_close_contract.py, test_obligation_gate.py, test_artifact_contract_enforce.py G2 part; new: R12-R14, R17) | A11, A13, A18 | `hooks/pretool-aggregate-check.py`, `hooks/pretool-gitignore-preflight.py`, `hooks/subagentstop-artifact-contract-enforce.py`, `hooks/pretool-obligation-gate.py`, `agents/dev.md`, `agents/qa.md` | P3-2, P3-3 | none | M |
| P3-5 | Armed replay, then promotion commit (R12(b), R14, R17 exit 2); whole-phase checks | promotion commit of the "Warning and promotion" item | A1, A3, A12, A14, A15, A16, A17, A20 | `hooks/pretool-aggregate-check.py`, `hooks/subagentstop-artifact-contract-enforce.py`, `hooks/pretool-obligation-gate.py` | P3-4; P2's arming sub-phase merged | none | M |

Coverage: rows R1, R2, R3, R4, R5, R6, R7, R10, R11, R12, R13, R14, R15, R16, R17 (no R8, R9 in the prompt) -> each in exactly one sub-phase, R16 is a list of test files and new tests: each listed file and each new test lands in exactly one sub-phase, with the row it tests (see notes); acceptance tests A1-A20 -> each in exactly one sub-phase.

Notes:
- Merge order: P3-1 -> P3-2; P3-3 alongside either; P3-4 after P3-2 and P3-3; P3-5 last. Sum 4 days (S+M+S+M+M) against the L estimate of about 3 days; P3-5 is M because the five-sandbox armed replay (A12), A16 and A20's fault replays run there.
- Provider coupling: the resolver exposes `ac_deviation_provider()` and passes `deviation=` to the aggregator; dev-lifecycle forwards it too. P3-1 (R4) stops dev-lifecycle using it and drops close-route-select's lookup of constants R2 deletes. R2 deletes the provider "with R3's deviation parameters", so R2 and R3 stay together in P3-2. Master never holds a caller of a deleted name.
- R16 is one row, but its test edits must land with the code they test (the prompt's test-dispositions item: "a prose pin: in its prose's commit"), or master breaks. So each sub-phase takes R16's files and new tests for its own rows, and each test edit lands in exactly one sub-phase. test_artifact_contract_enforce.py is edited in P3-3 (R6/R7, l2_ac7/l2_ac13) and in P3-4 (R14), in that order.
- "Warning and promotion": R12(b), R14 and R17 warn with R15 in one commit (P3-4, R12 kept whole). A12's armed replay runs between the commits on master, after P3-4 and P2's arming sub-phase have merged and P3-5 has merged origin/master (merge commit, no rebase). P3-5 then adds the promotion commit. A12 sits in P3-5 because it covers both commits. Its warning-commit cases run on P3-4's merged head before the promotion.
- A3 covers the R2 disposition sequences (P3-2) and the G1 replay. That replay denies only after promotion, so A3 sits in P3-5. R17's ordering rule ([INFERRED]) ships warning-only in P3-4, and A3 settles it before promotion.
- Whole-phase tests sit in P3-5: A1 (pytest over every touched file), A14 (whole diff), A15 (baseline), A16 (master-settings replay across all rows plus both commits), A17 (net cap, the phase total across all five PRs: <= -50) and A20 (full replay suite, per-stage and promoted-check fault replays). D25 still binds every PR: CI and P1c's replay suite green on each head, and each PR re-runs its tests after merging origin/master.
- Other multi-sub-phase tests sit in the last sub-phase they cover. A7 (resolver, aggregator, dev-lifecycle, close-route-select, qa.md) goes in P3-2. A13 (Bash lines from R4/R15, disposition run) and A18 (D24 table: P3-2 and P3-3 artifacts, plus moving the `resolve_chain` callers in dev-lifecycle, close-route-select and G2's `_wire_qa_chain` to P3-2's function) go in P3-4. A11 (R11 in P3-3, R12(a)/R13 in P3-4) also goes in P3-4. A10 is a placeholder with no test, kept with R10.
- Shared with P2: P3-4 and P3-5 edit G1's `main` and G3 near `_run_obligation_barrier`. Whichever PR merges second merges origin/master and keeps both sides. R13 adds profiles to the preflight's copy only while the sub-phase's base still has it. P2's merge state decides the `${CLAUDE_HOME:-$HOME/.claude}` spelling in agents/ edits (P3-1, P3-4).
- Choices decided by experiment go with their row's sub-phase: dev-lifecycle provider removal in P3-1. Gap quoting, function signature, failure exit code, project root, do-branch record access, aggregator helpers and mismatch shape, and reader coverage (A8) in P3-2. Codex-enforce resolution and A19 in P3-3. Roster comparison, canonical schema check site, freshness clock and echo comparison in P3-4. The staleness/R17 rule in P3-5 via A3.
- The start checks, owner rulings, DO NOT list, PR section (body shape; the title is `P3-<k>: …`, as the hand-off header says) and the P1b/P1c verify-not-redo item apply unchanged to every sub-phase.
