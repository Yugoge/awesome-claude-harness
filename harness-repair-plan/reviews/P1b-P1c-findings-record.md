# P1b and P1c review findings: record

This file records the verification of the 95 findings in reviews/P1b-P1c-review-findings.md: each finding went to two
refuters, and the record gives their verdicts, what was applied to prompts/P1b.md, prompts/P1c.md and inventory/, what
remains for other plan files, the verification rounds that followed, and the verdicts on the two prompts and the
inventory. It was checked at planning commit 382d857. Line references to P1b.md, P1c.md and inventory/ are at ef34dbc
unless a section says otherwise; 382d857 changed one line of P1b.md in place (row 11, :766), so the line numbers also
hold at 382d857. The review session's working records (refuter verdicts, apply and fix logs, verification reports, lane
notes and patch notes) are not committed; this record names them by cluster, round and report. Non-ASCII text appears
only in verbatim owner quotes inside the old and new texts under "For the plan files".

## Summary

- **Findings: 95.** Each went to two refuters who worked independently (refuter A checked the evidence first, refuter B
  the proposed fix and the owner's rulings first). A finding stands unless both refuted it.
  - 89 stand. 81 of them were applied to the prompts and the map: 58 touch P1b.md, 43 P1c.md and 13 inventory/ (many
    touch more than one), in wave 1 (2e7d4c0: the blockers, the highs and the findings on the same passages; clusters
    C1-C13, D1-D8, I1) or wave 2 (d22c669: the rest; clusters W1-W15, V1-V15, I2-I3), with later fix commits named under
    each finding. owner-R20 is carried by feasible-L2's override bullet. The other 8 target only other plan files:
    format-FH-5, plan-FIT-07, plan-FIT-08 and plan-FIT-09 are fully carried by the other session's commits, and
    format-FH-11, plan-FIT-06, plan-FIT-16 and plan-FIT-22 still have pending items under "For the plan files".
    format-FH-4, plan-FIT-12 and facts-F18 stand on refuter B alone, refuter A having refuted them.
  - 6 were refuted by both refuters: feasible-M1, feasible-M8, owner-R13 and owner-R14 (medium), feasible-L6 and
    format-FH-7 (low). Nothing was applied for them.
- **For the plan files.** 41 findings have a part for a plan file other than P1b.md, P1c.md and inventory/. Counting
  also the records that later fix logs and verification reports wrote, the items stand as follows (the review session's
  scope was P1b.md, P1c.md and inventory/, so it applied none of them):

| Target group | Pending | Already applied | Superseded | Total |
|---|---|---|---|---|
| PLAN-v2.md | 16 (3 optional) | 63 (7 since c33ca28, 56 before) | 4 (2 since c33ca28, 2 MOOT before) | 83 |
| reviews/P1b-plan-sync.md | 14 (1 optional, and 1 optional entry inside S37) | 0 | 37 (MOOT) | 51 |
| Other prompts and prompts/_common.md | 84 (17 optional, 1 conditional) | 32 | 19 | 135 |
| Other planning files (DECISIONS.md, COVERAGE.md, HANDOVER.md, README.md, audit/) | 5 (2 optional) | 6 | 7 | 18 |
| Total | 119 | 101 | 67 | 287 |

Each group also lists records it does not carry, with the reason: 2 for PLAN-v2.md and 6 for the sync file (both inside
those groups' item counts), 10 entries for the other prompts and 4 for the other planning files.

- **Open low items: 13** (16 low ids): 7 from P1b round 19b, 3 from the check of its one fix, 1 from P1c round 24 and 2
  round-18b items on P1b that the owner's ruling left unfixed. None is applied.
- **Inventory: 22 entries with known errors** (K1-K22, rows and README lines of the map at 37a259a), and 2 round-16
  items that were refuted.
- **Verification rounds.** P1b: 19 rounds (r1-r9, r10b-r19b). P1c: 24 rounds (r1-r24, two of them cross-checks). The
  inventory: 16 rounds (r1-r4, r5inv-r16inv).
- **Commits: 102.** These are the planning-branch commits that changed P1b.md, P1c.md or inventory/ in this work, from
  `git log` since the branch's first findings commit 2e7d4c0 (first 2e7d4c0, last 382d857). 37 changed P1b.md, 35 P1c.md
  and 35 inventory/. Every merge in that range took these files unchanged from one parent, and no commit of the other
  session touched them.

| Commit | File | Subject (after "docs: ") |
|---|---|---|
| 2e7d4c0 | P1b.md, P1c.md, inventory/ | P1b, P1c, inventory: apply the blocker and high review findings |
| d22c669 | P1b.md, P1c.md, inventory/ | P1b, P1c, inventory: apply the remaining review findings |
| 3646c24 | inventory/ | inventory: verification round 2 fixes |
| 76fc635 | P1c.md, inventory/ | P1c, inventory: verification round 2 fixes |
| 0cbfbd3 | inventory/ | inventory: verification round 3 fixes |
| 8ad26bc | P1c.md | P1c: verification round 3 fixes |
| 9f214f3 | P1c.md | P1c: verification round 4 fixes |
| 10bee66 | inventory/ | inventory: correct the citations the P1b reference check found |
| 14d2a32 | P1c.md | P1c: verification round 5 fixes |
| 618e22e | P1b.md | P1b: verification round 1 fixes |
| 65dd54a | P1c.md | P1c: verification round 6 fixes |
| 7304b34 | P1b.md | P1b: verification round 2 fixes |
| a34e686 | P1c.md | P1c: align with P1b's round 2 fixes |
| 64bec4f | P1b.md | P1b: verification round 3 fixes |
| e1762a6 | P1c.md | P1c: align with P1b's round 3 fixes |
| 0625898 | P1b.md | P1b: verification round 4 fixes |
| c68a19f | P1c.md | P1c: verification round 8 fixes |
| 0372d14 | inventory/ | inventory: verification round 4 fixes |
| cf2f197 | inventory/ | inventory: correct row A93 (the keystone grant) |
| afb0d6b | inventory/ | inventory: rows A54 and A93 |
| a19d839 | P1b.md | P1b: verification round 5 fixes |
| c6e3942 | P1c.md | P1c: verification round 9 fixes |
| e23f583 | P1b.md | P1b: verification round 6 fixes |
| 134db19 | inventory/ | inventory: row A01's G2 regex range |
| 822621b | inventory/ | inventory: row A98's prose writers |
| eef8a5c | P1c.md | P1c: verification round 10 fixes |
| 787167e | P1b.md | P1b: verification round 7 fixes |
| e8e5817 | P1c.md | P1c: verification round 11 fix |
| 88b240c | P1c.md | P1c: verification round 12 fixes |
| 5922f1f | P1b.md | P1b: verification round 8 fix |
| db16126 | P1c.md | P1c: verification round 13 fixes |
| 07a3905 | P1b.md | P1b: row 14 keeps one decider per user-intent flag |
| 7f0cae4 | inventory/ | inventory: fix A03, A54, A89, A91, A93 and recount (round 5) |
| 2505633 | P1c.md | P1c: X3 deletes the G2-only copies when it sets the switch |
| 28a7074 | inventory/ | inventory: A91 names the status and finalize deciders (round 6) |
| 602ec91 | P1b.md | P1b: row 18 keeps the user-intent and task-id command lists |
| 1fcbfbc | P1b.md | P1b: row 14 names every false guard claim and the full _sentinel_live span |
| 453308f | P1c.md | P1c: X8 deletes the overnight wake at the session's end |
| 8611f23 | inventory/ | inventory: A103 drops the receipt write as a decider and recounts (round 6) |
| 397a965 | P1c.md | P1c: acceptance 2 cites baseline.yml lines at 2acc29b |
| a238571 | P1c.md | P1c: reflow the Faults paragraph's short line |
| 1bf33ef | inventory/ | inventory: A103 names its in-project producers and pointer path |
| 07ff67a | inventory/ | inventory: the user-intent and task-id command lists are not hand-written tables |
| 60d2902 | inventory/ | inventory: the commit flag's read runs to write-commit-grant.py:473 |
| 861c102 | P1b.md | P1b: close QA keeps its role on /do after row 1 removes the arming |
| 07dc782 | P1c.md | P1c: /stop deletes the overnight wake too |
| a263825 | P1b.md | P1b: a base-text /close of a /do or /dev-command task exits 0 |
| 082ba74 | P1c.md | P1c: the wake step completes only on a recurring CronCreate of the wake's text |
| 9f03fea | inventory/ | inventory: A103 names the session-resources CLI as a decider (round 7) |
| c6bd5d4 | P1b.md | P1b: row 15 keeps session_resources.py's one conclusion as the decider |
| c84d0fe | P1c.md | P1c: hand P2 and P5 the wake check and its CronDelete step |
| 5a88edc | P1c.md | P1c: name the G2 arming commit by its Rollback step |
| a966aa1 | inventory/ | inventory: A103 lists provision and the timelock's second call (round 8) |
| 040759f | P1b.md | P1b: row 18 says how /do reaches row 1's mint |
| 045c38a | P1b.md | P1b: acceptance 4 states how the runner records a failed call |
| b67cd4e | P1b.md | P1b: row 19 rule 1 fixes the replacement order for minted ids |
| ba99401 | P1c.md | P1c: the /stop wake replay counts from stop.md's CronDelete |
| 34565c6 | P1b.md | P1b: acceptance 4 follows rule 1's id order as a rule |
| a0a5b6c | inventory/ | inventory: A103's terminal receipt is read never written (round 9) |
| dffe658 | inventory/ | inventory: README says how /do reaches the task-id mint |
| f818b75 | inventory/ | inventory: A01 counts seven filename regexes |
| 0be8bf0 | P1b.md | P1b: row 15 gives the terminal receipt a writer that runs |
| c33ca28 | P1c.md | P1c: P1b's dead-end list comes from its acceptances 14 and 21 |
| afc6773 | inventory/ | inventory: A63 names the commit grant's real readers and its /tmp home (round 11) |
| 660e8da | P1b.md | P1b: acceptance 21 runs provision in the kit and records phase environments |
| 6085619 | inventory/ | inventory: A62's commit manifest is read never written at /tmp (round 11) |
| 174281c | inventory/ | inventory: A70's journal is read by the changelog-analyst under the state dir (round 11) |
| a58ee3d | P1b.md | P1b: the guard is the commit grant's one decider; E5's own rule goes |
| d87af6b | inventory/ | inventory: A94 and A124 name their real locations (round 11) |
| 4dab588 | inventory/ | inventory: correct cite ranges in A01, A03, A105 and A119 (round 11) |
| 77df077 | P1b.md | P1b: an unattributed product file's finding returns to its own QA round |
| 2d59577 | P1c.md | P1c: close-QA findings on unattributed product files return to their round |
| cb35479 | P1b.md | P1b: acceptance 9 covers hook state and names what is not hook state |
| eb31066 | inventory/ | inventory: A105 traces the settings overlay's producers and deciders (round 11) |
| b12f0de | inventory/ | inventory: A104 traces the project settings' readers and deciders (round 11) |
| 7c93969 | P1b.md | P1b: bare line cites name the file they point into |
| 31acd8f | inventory/ | inventory: apply the round-12 full-sweep fixes to 83 rows |
| 0bdd73d | P1b.md | P1b: align rows 1-17, E9, E10 and acceptance 7 with the swept inventory |
| fb8f42c | inventory/ | inventory: correct nine rows the P1b knock-on lanes re-checked |
| a12fb1d | P1b.md | P1b: round-15 fixes for the disclosure re-checks, row 16 and Rollback |
| 59b483a | P1c.md | P1c: name P1b acceptance 7's two late-repair replays |
| a9a9b98 | P1c.md | P1c: list the graphify sentinel read only if the base still shows it |
| d6409c2 | inventory/ | inventory: apply the round-13 full-sweep fixes |
| 5b2b3d9 | P1b.md | P1b: align E9 and rows 1, 2, 4, 8, 13, 15-18 with the round-13 inventory |
| abb33b2 | inventory/ | inventory: fix the leftover A108 and A120 cells the P1b lanes found |
| 5530a7e | P1c.md | P1c: rewrap the faults paragraph after the replay list |
| 7284365 | P1c.md | P1c: Rollback says which commits revert alone and which revert together |
| 0381276 | P1b.md | P1b: round-16 fixes for row 6's effective-report checks and replays |
| 4ce4271 | inventory/ | inventory: apply the round-14 full-sweep fixes |
| 87cdbe3 | P1b.md | P1b: align E3 and rows 2, 6, 8, 13-15 and 17 with the round-14 inventory |
| 3ca4af4 | P1b.md | P1b: the spec coverage rule moves to G2 at the spec subagent's stop |
| 00d8894 | P1c.md | P1c: every transcript decider P1c adds takes P1b row 18's one reader |
| eb7e42d | P1c.md | P1c: clarify the Rollback revert rule's antecedent |
| e73c58d | P1b.md | P1b: round-17 fixes for the spec rule's landing, closeout and replays |
| 95ff638 | P1c.md | P1c: P1b row 13 deletes closeout's pre-deadline block |
| 0bd2568 | P1b.md | P1b: the release note states the merge-time window for stops before the merge |
| 37a259a | inventory/ | inventory: apply the round-15 sweep fixes and add the codex skill ledger row |
| b155101 | P1b.md | P1b: account for the round-15 inventory changes |
| c273acd | P1c.md | P1c: X3's fallback claims safety only for producer stops after the merge |
| 9bd18bb | P1c.md | P1c: acceptance 12 lists the transcripts and the wake's cron records |
| ef34dbc | P1b.md | P1b: row 11 keeps the grant pointer the journal writer needs; rule 5 scopes the main agent's writes |
| 382d857 | P1b.md | P1b: row 11 lets the one dispatch commit every repository its plan names |

## Verdicts

- **P1b.md is ready for implementation.** The final round, r19b (P1b.md at ef34dbc), found one medium and seven lows.
  The medium, R19B-1 (row 11: spending the changelog-analyst's dispatch attestation by deletion refuses the second
  repository of a two-repository /commit, a dead end), was fixed in 382d857, and an independent check of that commit
  (round r19b report fix-R19B-1) confirmed the fix and found no defect at medium or above. No defect at medium or above
  is open. Open low items: 12 (13 low ids), 10 from round 19b and its fix check and 2 from round 18b; one of them,
  R18B-FR-3, also edits P1c.md.
- **P1c.md is ready for implementation.** The final round, r24 (P1c.md at 9bd18bb, P1b.md at ef34dbc), found nothing at
  medium or above. Open low items: 1 (R24-1, the same defect as RA24-1, with R24-2), plus the P1c.md edit of the
  round-18b item R18B-FR-3.
- **The inventory** (inventory/artifact-map-d625284.tsv and inventory/README.md, unchanged since 37a259a) is planning
  evidence, with its 22 known errors listed under "Inventory: rows with known errors". P1b's first implementation step
  (row 0) regenerates the map on that day's master, and P1b's acceptance is measured on that map.
- **The owner's rulings that ended the loop.** First, in the final round only defects rated medium or above are fixed;
  each low one is recorded with its file, location, problem and suggested fix. Second, no further inventory sweep is
  run: the inventory is planning evidence that P1b regenerates, so it need not reach zero differences here, and the rows
  with known errors are listed instead of fixed.

## Findings

One entry per finding, blockers first, then highs, mediums and lows. Each entry gives the two refuters' verdicts, the
reason, where the finding was applied (file, cluster and commit, with line references at ef34dbc) and the later commits
that changed the same text, and, where it has one, its part for the other plan files. A refuter's STANDS-CORRECTED means
the defect exists but the proposed fix needed the correction the refuter gave; the applied text follows the corrected
fixes.

### feasible-B1 (blocker): Acceptance 4's "0 blocks from any hook" cannot be met inside P1b's scope

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed base blocks at d625284 that no P1b row touches (changelog-analyst's `rm -f`,
  merge.sh's untracked-file refusal, the overnight guard and time-lock), so "0 blocks" contradicted P1b's own "not
  worse", Out of scope and DO NOT, and "once E13 lets them run" was false. They corrected the fix: keep the table and
  the hook-error definition, and replace "the step the pilot used" (no pilot drivers exist) with the smallest step
  that produces the refused step's effect, compared by refusal text with run ids aside.
- **Edit**: P1b.md, cluster C1, commit 2e7d4c0: acceptance 4 (:853-882) compares every block with the base kit and
  passes a kept base block only by a marked `DEVIATION:` driver step listed under "Hand-off to P1c"; E5, E8, E13, E14
  and row 13 reach later steps through those deviations; "What you hand to P1c" (:75-79), the Hand-off heading and
  the DO NOT driver line follow. P1c.md, cluster D5, commit 2e7d4c0: the Interfaces P1b bullet (:48-57), the
  paragraph "Rows 18 and 19, P1b's kept base blocks" (:557-566) and acceptance 3's `git grep -n 'DEVIATION:'`.
  Later fix commits on the same text: 7304b34 (DO NOT exception adds row 7's respellings; heading adds acceptance 9),
  64bec4f (acceptance 4 rewritten: the driver records every block, a deviation on the branch's own text passes only a
  kept base block, and deviations that fire only on the base's text are listed apart; the same in :75-79, E13, the
  heading and DO NOT), a263825 (acceptance 4: "in-flight replays"); in P1c.md a34e686 and e1762a6 aligned the
  Interfaces bullet, the rows 18-19 paragraph and acceptance 3 with those P1b rounds.

### owner-R1 (blocker): /close and /commit only report an unfinished cycle instead of completing it

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the base re-dispatches through the routing loops (close.md:282-321,
  commit.md:144-178) and that P1b's release note, row 10 and Out of scope reduced this to reporting, the alternative
  CC4 and D7 reject. They corrected the fix for an artifact no dispatch declared (the canonical todo step), a product
  file a close-QA round names, and the dangling Out of scope clause.
- **Edit**: P1b.md, cluster C2, commit 2e7d4c0: the release note (:115-122) dispatches each gap's declaring dispatch
  again or the canonical todo step's role; row 10 routes both loops through E3's reader, drops `producer_role` (D21)
  and sends a product-file finding to the writer E6's kept producer records; Out of scope rewritten; acceptance 7
  (:903-940) gains four replays with no human action. Later fix commits on the same text: 618e22e (the main agent's
  own step, a /dev from an earlier session, the chain call's `errors[]`, a finding that names no artifact), 7304b34
  (E5 (a) and (b) aggregate gaps, the /do task route), a19d839 (row 10: a file a /do task's main agent wrote),
  77df077 (row 10 and acceptance 7: a product file no dispatch wrote returns to its QA round); acceptance 7 later
  gained further replays in 0bdd73d, a12fb1d and 0381276.
  - For the plan files: reviews/P1b-plan-sync.md:230 (both loops take each gap's producer from E3's reader);
    optional source line numbers of rows CC4 and CC5 in audit/2026-10-23/register.md; prompts/P4.md Goal 1's "dev when
    none" default, to be checked against D21.

### plan-FIT-01 (blocker): P1b's acceptance 4, E13 and E5 need P1c's rows 18-19 work

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the overnight seed, the overnight guard and the time-lock blocks persist
  at d625284, master, p7b and p8, so zero blocks in all ten pipelines is P1c's requirement (1). Both judged the DO NOT
  and acceptance 14 conflicts overstated and found the fix incomplete (the old "Any block is either ..." sentence,
  the unqualified DO NOT line, E5 and row 13).
- **Edit**: Merged with feasible-B1 in clusters C1 and D5, commit 2e7d4c0: acceptance 4 as there; E13's decision rule
  (:612) asks 0 blocks only of the contract and state hooks, other base blocks passed by deviations; the DO NOT driver
  line gains the one exception; "What you hand to P1c" says P1c removes each deviation with its block; in P1c.md the
  rows 18-19 paragraph and acceptance 3. Later fix commits on the same text: 7304b34 and 64bec4f (E13 says "kept" base
  blocks; acceptance 4 and DO NOT as under feasible-B1), a263825; in P1c.md a34e686 and e1762a6.

### facts-F1 (high): Row 18 deletes reading branches of files that are in fact written

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters verified that four of the five "nothing writes" files have a writer or are inputs by
  design (protected-runtime.json from scripts/bootstrap:362-386, the tracked `.awesome-claude-harness`, the human's
  `.hook-refactor-allow`, the CLI's project CLAUDE.md) and that the generic grant probe is the uncalled
  `_find_grant_any`. Both refuted the claim that the extractor skipped scripts/bootstrap for lack of an extension.
- **Edit**: P1b.md, cluster C5, commit 2e7d4c0: row 18 deletes only the agent-bookmark reading branch and the uncalled
  `_find_grant_any` (D17 proof) and keeps the four reads with their writers; row 19 rule 1 counts tracked files,
  files the CLI loads and files the reading code says the user creates by hand as inputs and parses
  scripts/bootstrap. inventory/, cluster I1, commit 2e7d4c0: A117 (TSV line 115) narrowed to agent-bookmark-* and
  spec-continuation-*, the counts, and a README paragraph that names protected-runtime.json. Later fix commits on the
  same text: d22c669 (A117's spec-continuation path and reader cite :671; the README paragraph rewritten), 31acd8f
  (A117, round-12 sweep). The row 18 and row 19 sentences are unchanged since 2e7d4c0.

### facts-F2 (high): Acceptance 9's grep cannot see the path-rule defects it targets

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters ran the grep at d625284 (18 lines) and found none of the guard's single-quoted reads
  (:274, :328, :2093) and no prose writer. Both rejected the fix's "same fixed root" carve-out, which contradicts
  "`harness_state_dir()` on both sides of every state file"; B showed that a bare `"/tmp"` default
  (break-overnight-lock.py:35) escapes every `/tmp/claude-` pattern.
- **Edit**: P1b.md, cluster C6, commit 2e7d4c0: acceptance 9 (:945-983) runs two greps (an anchored
  `/tmp/(claude-|agentic-commit|overnight-)` over hooks, scripts, commands and agents, and bare `"/tmp"` defaults),
  allows only the helper's default, its import fallbacks, prose and non-state uses, and has the PR give each remaining
  line's category (133 and 23 lines at d625284). Later fix commit on the same text: cb35479 (acceptance 9 covers hook
  state and names the file families that are not hook state).

### facts-F3 (high): The path rule cites a wrong location, misses two mismatches, and row 12 would add one

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed all four parts: guard :2093 is only the block message (the read is `_find_grant`
  :328, called at :2135); do.md:57 reads the /do sidecar under /tmp while prompt-workflow.py:1419 writes the state
  dir; execute-push.py:35 is also the push-analyst grant's read root, so moving it alone splits the grant; the token's
  writer prose is changelog-analyst.md :1221, :1247. B added the analyst's write permission (tool-policy.v1.json:800)
  and that do.md:57 sat in no row.
- **Edit**: P1b.md, cluster C6, commit 2e7d4c0: the release note (:124-125), Correction 4 (:674-704, "a writer moves
  with its prose and its write permission"), row 9 (do.md:57), row 12 (execute-push.py:35 with the push-analyst's
  grant path, path rules and permission; guard :328) and acceptance 9 (the /push grant and sidecar checks).
  inventory/, cluster I1, commit 2e7d4c0: A52 and A71 gain "read never written (with CLAUDE_STATE_DIR set)", A73
  cites `_find_grant` :328, and the README's counts and token writer. Later fix commits on the same text: 618e22e
  (Correction 4, row 12 and acceptance 9 add agents/cleaner.md:111 as a token writer and row 11's one writer);
  TSV A52 d6409c2 and 37a259a, A71 d6409c2 and 4ce4271, A73 31acd8f (inventory sweeps).

### facts-F4 (high): E8's one function would pass the pending skeleton; its fallback reads a missing record

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that TERMINAL_VOCABULARY's do-report entry is the schema's whole enum {pending,
  completed, blocked} (obligation.py:138), that today's deciders disagree with it, and that /do dispatches nothing; B
  showed that the close QA's own obligation can carry `expected_absent`. Both rejected a second drift-tested set in
  code.
- **Edit**: P1b.md, cluster C7, commit 2e7d4c0: E8 (:494-516) removes `pending` at the schema, the one function
  returns the status and only `completed` counts as done; the fallback has the close QA's dispatch declare profile
  `do-close` and `expected_absent`; row 9 names E8's one function. Later fix commits on the same text: 618e22e (only
  stop-do-report-gate.py, /close preflight and dev-lifecycle.py decide `do.status`), a19d839 (the Stop gate's
  pending-to-blocked rewrite named as a third writer).
  - For the plan files: prompts/P5.md, PLAN-v2.md, prompts/P3.md and prompts/P4.md: the passages that find an
    unfinished /do task by "pending" and the enum [pending, completed].

### feasible-H1 (high): Kept literal sets and two deciders contradict the zero-exception check

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that ROLES (10 roles against the schema's 7), PIPELINES, the TERMINAL_VOCABULARY
  mirror, the tool-policy file prefixes and the e2e gate beside G2 would fail the check or need an exemption. Both
  rejected the fix's timed "until P5" exemption and its too-broad table definition; B refuted the Stop-gate part,
  which the merged owner-R10 text answers.
- **Edit**: P1b.md, cluster C4, commit 2e7d4c0 (merged with owner-R10, owner-R11, feasible-H2, plan-FIT-15): row 6
  keeps in TERMINAL_VOCABULARY only which field is terminal, read from the schema; row 7 splits the deciders (G2:
  existence and shape; the e2e gate: the status policy; its missing-report block goes with G2's arming); row 18
  removes ROLES, PIPELINES, the schema's role and pipeline enums and QUESTION_ARTIFACT_ROLES and reads PROFILES from
  the schema; Goal 5 points to row 19. P1c.md, cluster V14, commit d22c669: row 10 (:544) states the split. No later
  change to these sentences.
  - For the plan files: prompts/P5.md:318 and prompts/P10.md:342 (TERMINAL_VOCABULARY follows the schema; no drift
    test is left).

### feasible-H2 (high): The CI check's derivation rules are undefined

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters found the map's reader exclusions made by hand with no rule in row 19, no determinism
  requirement and no coverage floor. Both refuted parts of the claim ("can never fire", "re-check" undefined) and
  corrected the fix's rules (excluding tracked files drops A104, A105 and A108; the listing clause drops the
  aggregator's lane reads; "not under /tmp" conflicts with P8's conftest).
- **Edit**: P1b.md, cluster C4, commit 2e7d4c0: row 19's numbered derivation rules (1) to (10) (rules 2, 5 and 7 from
  the merged findings), Goal 5's pointer and prose-coverage sentences (:104-110), and acceptance 6's coverage floor,
  compared by hand. Later fix commits on the same text: 618e22e (the floor compares the code site found again with
  line numbers ignored; rule 5's chain-call positions and the CI job), b67cd4e (rule 1, minted ids), e73c58d and
  ef34dbc (rule 5).

### feasible-H3 (high): E5's two candidates cannot reach the aggregator in the kit's product repository

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the hook (:216-218) and Step 11 (dev.md:885, :923) use product-relative
  paths and that toyproj has no scripts/ or venv/, so neither candidate writes the canonical and G3 blocks fan-out QA.
  They corrected the fix: `~/.claude/scripts` is the base's own harness-home spelling, not TC-44's form; the
  aggregator also needs the project root; and the finding's row 7 list was mislabelled.
- **Edit**: P1b.md, cluster C8, commit 2e7d4c0 (one text with facts-F9): E5 (:406-437) states the product-path fact,
  gives both candidates the harness's copy before the experiment (the hook from its own file; Step 11 by
  `python3 ~/.claude/scripts/aggregate-dev-report.py`; a `--project-dir` option) and adds a Fallback; row 7's kept
  chain calls run the harness's copy. Later fix commits on the same text: 7304b34 (E5 routes a missing canonical
  through row 10's loop; row 7 respells every repository-relative harness script close.md and commit.md run),
  64bec4f (E5: a base-text replay runs Step 11 in the harness copy), 618e22e and 0625898 (row 7's cites and the venv
  activation).
  - For the plan files: prompts/P2.md row 4 (two cells) and acceptance 5, PLAN-v2.md:1212 (P1b's E5 keeps one
    producer and makes it reach the harness's copy).

### feasible-H4 (high): E2 sets no effective CI budget and P1c's X10 could move the traced D24 run

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters refuted "shard count unlimited" (sharding by pipeline caps the matrix at ten) and found X10
  an ambiguity rather than a conflict, but confirmed that E1's differential runs and the settings mode were never
  counted. Both rejected the fix's path-filter fallback.
- **Edit**: P1b.md, cluster C9, commit 2e7d4c0: E2 (:250-278) counts setup and the differential runs in the 25-minute
  budget, at most one traced job per pipeline, falls back only after E1's fallback, and traces with the tree's own
  settings.json. P1c.md, cluster D8, commit 2e7d4c0: X10's last sentence keeps P1b's D24 check per PR, outside the
  split. Later fix commit on the same text: 14d2a32 (X10: "its own job, P1b's E2 and P1b's row 19").

### feasible-H5 (high): P1c rebuilds N1 and V1-1/NV-1 from guesses although P7b's records exist

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters found the records on P1c's base and the planning branch (commits 8ab874b, 96bcb8f and
  921b512, tests/test_landing.py, the N1, V1-1 and NV-1 rows of reviews/P7b-PR-record.md) and showed that X9
  reproduces a different defect (a stash-pop conflict) while R-V1 folded V1-1/NV-1 into F4c. They extended the fix to
  R-N1's before, acceptance 6, row 20, X7 and row 14.
- **Edit**: P1c.md, cluster D1, commit 2e7d4c0 (one set with plan-FIT-04 and facts-F13): X9 (:471-490) rewritten from
  the record (before 1d10ae0, the window rule, Fact 1), R-N1 and R-V1 (:735-748, befores 26a7ea7 and 96bcb8f), row 20,
  X7's heading, row 14's label, acceptance 6 and Rollback step 5. No later change to these passages.
  - For the plan files: reviews/P1b-plan-sync.md V-31, H-10, K-12 and the D25 (4) coverage row (the records exist);
    COVERAGE.md:272-274 (P7b fact 9 recorded as a fact, nobody asked).

### feasible-H6 (high): P1c is written as if P1b had not run

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that about ten P1c rows target sites P1b removes and that several hand-offs go
  to P1b, which merges first. B showed P1c already says a closed defect needs only its replay, so "cannot tell which
  governs" was partly refuted; both refuted the R-P1 change.
- **Edit**: P1c.md, cluster D3, commit 2e7d4c0: the "Delivered by P1b." paragraph (:518-532), leads in rows 7, 10, 13
  and 19, Out of scope rewritten, R-E1's before on the first parent of P1b's merge and acceptance 6, the `-F` and
  found-by-pilot items made conditional, and the hand-off; the driver parts were left to V1 (format-FH-3). Later fix
  commits on the same text: d22c669 (V12 adds row 12, V14 replaces row 10's sentence, the list drops spec-update.md:115
  and adds push.md's token scan and the resolver respellings), 76fc635, a34e686, e1762a6, c68a19f and eef8a5c (the
  Delivered list follows later P1b rounds).

### feasible-H7 (high): P1c's net-code cap of <= 0 is paid for by deletions P1b makes first

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the cap's funding (the G2 hand-off, the empty contract) is deleted by P1b's
  row 3 and E13 and that the cap could push X7 and X8 toward their no-code options. Both refuted the proposed formula,
  which counts deletions twice, and gave net <= +150 measured on P1c's base.
- **Edit**: P1c.md, cluster D3, commit 2e7d4c0: Net code cap (:974-984) and acceptance 15 (:942) set <= +150 against
  the base with per-row counts, X7 and X8 decided by their own rules. P1b.md, cluster C13, commit 2e7d4c0:
  Correction 1's PLAN-v2 row carries "net code cap <= +150". Later fix commits on the same text: d22c669
  (`_write_blocked_aggregate` is 60 lines; acceptance 15's pathspec), 618e22e (P1b Correction 1 cites the rows
  PLAN-v2.md:133-134 now carries).
  - For the plan files: PLAN-v2.md:105 (P1c may be positive); reviews/P1b-plan-sync.md :95, :406, :468 ("<= +150").

### format-FH-1 (high): The PR body cannot hold the required maps and D24 table

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed GitHub's 65,536-character limit on a body or comment, the 79,334-character
  planning TSV and the body headings that ask for every artifact. B refuted the row 0 part (it says only "in the PR")
  and both corrected the Inventory heading, which asked for rows the check cannot derive.
- **Edit**: P1b.md, cluster C10, commit 2e7d4c0: row 0, acceptance 6 (:895-902), acceptance 16, the D24 table,
  Inventory and Decided-by-experiment headings, and a size bullet (:1171-1180: at most 60,000 UTF-8 bytes per body or
  comment, the rest in linked comments, never in the repository). P1c.md: cluster D7, commit 2e7d4c0, the same bullet
  (:1071); cluster V15, commit d22c669, `wc -c` and "raw counts or exit codes" in that bullet and heading (:1041). No
  later change.
  - For the plan files: optional prompts/_common.md "Test evidence" sentence on the 60,000-byte rule.

### format-FH-2 (high): P1c repeats P1b's deletions and counts them toward its cap and retired rules

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed the overlaps and the stale hand-offs (X2, row 10, Out of scope) and found more
  (close.md :337 and :507, commit.md :334, spec-update.md:115). A refuted "redoes P1b's work" given P1c's own "needs
  only its replay", and both left row 10's no-obligation case and row 13's "or escalate" with P1c.
- **Edit**: P1c.md, cluster D3, commit 2e7d4c0 (merged with feasible-H6, plan-FIT-11, owner-R16): the "Delivered by
  P1b." paragraph, the X2 rule, Out of scope's D24 bullet, the found-by-pilot items, the Retired header with "P1b"
  markers and acceptance 13 C1; the cap through feasible-H7. Later fix commits on the same text: d22c669 replaced D3's
  X2 sentence (V5, feasible-M7) and set the Retired count to at least 4 (V12, feasible-M2).

### owner-R2 (high): P1b ships a live-home window in which faults its deleted checks stopped pass unstopped

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that P1b deletes consumer-side checks while G1-G3 stay advisory and E4 ships an
  escape list, on a master that lands on /pull, and that E12 removes the advisory records E4 relied on. A showed some
  faults stay stopped (G2's legacy path, the e2e gate, the chain call); both refuted the fix's part (4), keeping
  advisory logs that no command names.
- **Edit**: P1b.md, cluster C3, commit 2e7d4c0 (one rule with plan-FIT-02): E4 (:368-405): no escape at any commit;
  P1b arms G2 by adding `CLAUDE_OBLIGATION_STOPGATE` with the G2-only copies' deletions after a false-block replay; a
  copy only G1 or G3 would stop stays until P2. The header, Goal 3, the release note, Corrections 7, E12, row 19's
  switches, Out of scope, acceptances 5 and 13, Rollback (4) and (7), the Faults heading and DO NOT follow. P1c.md,
  cluster D6, commit 2e7d4c0: X3 replays only when the base sets the switch; row 9, Rollback step 7, the hand-off and
  Rules added. Later fix commits on the same text: 618e22e (the arming commit is Rollback's (7), later commits keep
  the switch, G2 reads the harness home's settings when its env lacks the key), e23f583 (the CLAUDE_HOME case),
  787167e, 5922f1f and 7c93969 (E4's cites), 0bd2568 (the release note's merge-time window); in P1c.md 14d2a32,
  2505633 (X3 deletes the G2-only copies), 5a88edc and c273acd.
  - For the plan files: PLAN-v2.md (:103, :132, :166, :338, :351, optional :674), prompts/P2.md (:1, :5, :14, Goal 7,
    row 17) and reviews/P1b-plan-sync.md (:143, :180, :925-928): G2 is armed by P1b, P2 arms G1 and G3 and deletes the
    copies P1b keeps for them.

### owner-R3 (high): X7's option (B) asks the owner about a stale git lock

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that (B)'s in-turn ask is a human event that fails F4s and D25 (2) and that (B)
  is a likely outcome. Both found D20 not engaged (sync-shared runs only under a typed /commit) and rejected the fix's
  ps, fuser and lsof route, which also reads /proc and would unlink a live holder's lock in the fixture.
- **Edit**: P1c.md, cluster D2, commit 2e7d4c0: X7 (:380-405): option (B) is (A) plus a no-git-process condition read
  from /proc, the rule holds both options to the same conditions before merge, and no option asks the owner or the
  orchestrator inside or outside /dev-overnight; row 14 adds no check. Later fix commits on the same text: d22c669
  (P1c round-1 fix: the no-/proc pass condition and the exclusive-create live holder), 76fc635 (the linked-worktree
  case), 14d2a32 (row 14's analyst sentence reworded).

### owner-R4 (high): The suite never replays /close or /commit completing an unfinished cycle

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that none of the 17 faults makes /close or /commit meet an unfinished cycle, so
  CC4 is never proven. Both refuted the fix's injection point (a report removed after QA's stop is caught at /dev's own
  end), its self-contradicting F8c and the R-CC4 regression entry, which was not added.
- **Edit**: P1c.md, cluster D4, commit 2e7d4c0: faults F8, F8q, F8p and F8c (:675-700) mirror P1b acceptance 7's four
  replays (count 21), with their assertions, the Next round definition, the routing loops under "Delivered by P1b",
  Out of scope, acceptance 4 and the X10 estimate. P1b.md, cluster C13, commit 2e7d4c0: acceptance 7's first replay
  removes the report after /dev reached its terminal. Later fix commits on the same text (P1c.md): d22c669, 14d2a32
  (later-session replays, a finding that cites no artifact, E5 (b)), a34e686 (a /do task), 2d59577 (a product file no
  dispatch wrote), 59b483a (the late-repair replays).
  - For the plan files: reviews/P1b-plan-sync.md :143 and :840 (optional :418, :844): 21 faults, four of them CC4's
    case; optional prompts/P4.md acceptance 4 cross-references.

### plan-FIT-02 (high): G1-G3 stay advisory after P1b deletes consumer checks, against D25 on the live home

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that STOPGATE defaults to advisory and that row 7 deletes /close's schema gate, so
  a schema-invalid report passes on the live master until arming; A judged the window narrower (F1, F2j, F1q stay
  caught). Both rejected the fix's "list for P2, never keep a copy" branch and found it left :75, :96, :419, :501, :541
  and P1c :733 unchanged.
- **Edit**: The same text as owner-R2 (clusters C3 and D6, commit 2e7d4c0), with plan-FIT-02-A's clean form and
  env-reach measurement and plan-FIT-02-B's false-block clause. Later fix commits: as owner-R2 (618e22e, e23f583,
  0bd2568 in P1b.md; 14d2a32, 2505633, 5a88edc, c273acd in P1c.md).
  - For the plan files: as owner-R2, including reviews/P1b-plan-sync.md P2-4 (:925).

### plan-FIT-03 (high): E13 makes the orchestrator the cycle contract's writer and drops /stop's state write

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that E13's main variant reverts TC-43 (ledger L46) and that deleting
  break-overnight-lock.py's write loses the base's only /stop release. They corrected the fix: the base writes no
  `terminal_status`, the base's /stop meets the closeout block rather than closing cleanly, a write that simply stays
  is a second writer, and `cycle_index(state)` is P2 row 7's.
- **Edit**: P1b.md, cluster C11, commit 2e7d4c0: Decided technical choices (:210-213) names TC-43; E13 (:589-619): the
  PM TRIAGE handler as the contract's only writer, /stop's fields written through the launcher's write path, the cycle
  index through `cycle_index(state)`, a /stop replay in the decision rule, a fallback that forbids an
  orchestrator-written contract; row 13 deletes the orchestrator's contract write. Later fix commit on the same text:
  a19d839 (`cycle_index` is P2 row 7's function, which P1b adds early).
  - For the plan files: prompts/P2.md row 14 (the base records no `terminal_status`); reviews/P1b-plan-sync.md P2-4
    (the contract's one writer and /stop's state write).

### plan-FIT-04 (high): R-N1 and R-V1 replay the wrong defects, and N1's window and Fact 1 have no owner

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters found the records at the branch head (reviews/P7b-PR-record.md rows N1, V1-1 and NV-1) and
  showed that X9 rebuilds P7b facts 2 and 9; both confirmed nobody owned N1's remaining window or Fact 1 (`safe_pull`
  deciding by `tee`'s status). A judged "unreachable" overstated; both kept fact 9 out of P1c.
- **Edit**: P1c.md, cluster D1, commit 2e7d4c0: as feasible-H5, with N1's window and Fact 1 given to row 20. P1b.md,
  cluster W3, commit d22c669: row 0 names P7's record, P7b's marker and the lock as three files (with facts-F7). No
  later change to these passages.
  - For the plan files: as feasible-H5; COVERAGE.md:272-274 records fact 9 as a fact for whoever edits the plan files.

### plan-FIT-05 (high): E6 keeps the journal and deletes the ENTANGLED wire, against P6 and TC-46

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that E6 keeps the journal in every branch and deletes `_wire_ledger_judgment`,
  while P6 and TC-46 name the transcript write set and keep that check. They corrected the fix: `write_set()` does not
  exist yet, the oracle must be the replay's write trace, and the fallback must not be circular.
- **Edit**: P1b.md, cluster C12, commit 2e7d4c0: E6 (:438-461) adds candidate (c), the CLI transcript's write set
  computed by the replay kit, judged against the write trace (take (c), else (a), never (b)); `_wire_ledger_judgment`
  and dev's declared lists stay; row 10's route reads the kept record through one function; row 6's deletion list
  follows. No later change.
  - For the plan files: reviews/P1b-plan-sync.md P6-4, V-17, P4-4 (a new bullet), P5-4 and V-15 (E6 decided by
    experiment; one write-set reader).

### plan-FIT-06 (high): Sync notes ignore goals the batch already added; batch texts name the wrong deleters

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the sync predates batch 06794d9, so V-24, V-13, P4-4 and P10-4 only insert
  "do not add" notes beside texts that still order a second inventory, and that P9 and P10 name P2-P4 as deleters of
  artifacts P1b deletes. Both corrected the fix's texts (L39, L18, L21, row 4).
- **Edit**: none in P1b.md, P1c.md or inventory/ (a plan-files-only finding).
  - For the plan files: c728380 (the sync list applied) already carries parts (1)-(4) (PLAN-v2.md :844 and :483,
    P10.md's goal and row 19, P4.md Goal 8 and acceptance 21), and fa5659d carries P9.md:657 ("which P1b deletes");
    still to apply at ef34dbc: prompts/P2.md :186-187 and :871-872, prompts/P3.md :691-695, prompts/P9.md:661.

### facts-F5 (medium): Acceptance 8's grep misses one of P1b's own targets and overlaps P1c's work

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the case-sensitive grep misses dev.md:128-129 and the prefix strip at
  dev-command.md:890. A found the e2e overlap real and B refuted it, so that part stands and the e2e carve-out stays;
  both refuted the G2 overlap, since row 1 deletes that block.
- **Edit**: P1b.md, cluster W2, commit d22c669: acceptance 8 (:941-944) greps with `-niE` and `DEV_SESSION_ID#` and
  leaves only the e2e gate's resolution for a QA dispatch without an obligation, listed under "Hand-off to P1c" for
  P1c row 10; its Retired-list item was superseded in the same commit by W14's pointer to the Scope rows. Later fix
  commits around that heading clause: 7304b34 and 64bec4f.

### facts-F6 (medium): Prose copies of the routing tables and a third "no code table" claim are missed

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that close.md:276 and commit.md:88-97 restate the tables in prose, that
  close.md:278 is a third claim, and that acceptance 7's grep sees none of them. Both found the proposed grep
  case-sensitive against commit.md:83 ("No code, table"); B added commit.md :350-351, :680-681 and :852.
- **Edit**: P1b.md, cluster C2, commit 2e7d4c0 (one text with owner-R1): E3's table list adds the prose copies and row
  references, row 10 cites them and close.md:278, and acceptance 7 uses the merged `-niE` grep (24 lines at d625284)
  with the "in any other words" clause. Later fix commits on the same text: 7304b34 and 64bec4f (E3: Step 8's
  selection routes through the reader, commit.md:910 loses `artifact_role`, close.md:414's pointer).
  - For the plan files: prompts/P9.md acceptance (close.md:278 and :288; "if P1b left them"); optional prompts/P4.md
    rows 2 and 5 ("only if P1b left them").

### facts-F7 (medium): P1b, the README and the TSV describe P7b from a reviewer's copy, not the merged head

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that P7b merged at 1071ad3 (301d696), that `claude-settings.applied` is P7's
  record while the `.checked` marker and the landing lock are P7b's own files, that logs/landing.log has two writers,
  and that checkpoint-core.sh is a missed settings_env reader. Both refuted "760f06e, not yet pushed" and the f8c18c2
  base.
- **Edit**: P1b.md, cluster W3, commit d22c669: the Interfaces P7b bullet (:61-71), row 0 and row 16 cite P7b as merged
  (lines on master 2acc29b). inventory/, clusters I2 and I3, commit d22c669: A88, A105, A106 and the README's
  `p7b_p8_effect` column and Limits line. Later fix commits on the same text: 618e22e (the bullet cites `save_record`;
  row 16 leaves land the log's one writer), 5922f1f (row 16); TSV A88 76fc635, 0372d14, d6409c2, 4ce4271 and 37a259a,
  A105 4dab588, eb31066 and d6409c2.

### facts-F8 (medium): The pull-analyst "grant" row describes a file nothing writes

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the pull-analyst writes no file (agents/pull-analyst.md:33-34, :157-158;
  no Write in its tool policy) and that the path appears only in two prohibitions. B added that the fix missed row
  12's "(A71-A75, A123)" label.
- **Edit**: P1b.md, cluster C6, commit 2e7d4c0: E3 says "(the pull-analyst writes no file)", row 12's group reads
  "(A71-A75)" and its pull-analyst clause is gone. inventory/, clusters I2 and I3, commit d22c669: A123 deleted, the
  counts, the README's `id` column and its "Excluded" entry. No later change to these texts.
  - For the plan files: the count line at reviews/P1b-plan-sync.md:419 (its figure was superseded by later inventory
    rounds).

### facts-F9 (medium): E5's candidate (a) never writes in a product repository

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the hook resolves the aggregator in the product repository (:90-91,
  :216-218) and returns silently there. Both found that candidate (b) has the same defect and that the fix's
  `.resolve()` cite was wrong (:557, not :1576), and refuted the escape "record that (a) was unreachable" (D18).
- **Edit**: P1b.md, cluster C8, commit 2e7d4c0: one text with feasible-H3 in E5. Later fix commits: as feasible-H3
  (7304b34, 64bec4f).
  - For the plan files: merged into feasible-H3's prompts/P2.md row 4 and acceptance 5 records.

### facts-F10 (medium): Row 17 deletes doc-sync's dedupe state, which its writer reads back

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that hooks/doc_sync/notice.py reads the state back at :469-470 to decide what
  prints (a cache, a consumer under the inventory's own definition) and that the main audience writes its own file.
  Both refuted the fix's "goes only if E9 removes every notice source", which E9 never decides.
- **Edit**: P1b.md, cluster W4a, commit d22c669: row 17 keeps the dedupe state with its reader; its Retired item went
  (the list became W14's pointer in the same commit). inventory/, cluster I2, commit d22c669: A109 renamed "doc-sync
  notice dedupe state" with its reader and violation reclassified. Later fix commit on the same text: 4ce4271 (A109,
  round-14 sweep).

### facts-F12 (medium): Row 17 deletes the spec-update temp note outright, skipping E12

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that /spec's Step 7 output prints the note's path (spec.md:473), so E12 keeps
  it with the owner, while the /dev, /dev-command and /close notes are unnamed, and that `/spec-update --temp` is a
  feature (Principle 6). Both rejected "fixed in the prose", since X4 picks the side.
- **Edit**: P1b.md, cluster W4a, commit d22c669 (wording aligned by W4b in the same commit): row 17 keeps /spec's note,
  deletes the others unless an owner-facing output names them, and leaves the refused mktemp-then-Write to P1c row 18
  under X4. inventory/, cluster I2, commit d22c669: A112. No later change.

### facts-F13 (medium): P1c says no record of N1 or V1-1/NV-1 exists

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters found the records on master 301d696 (scripts/install/land, tests/test_landing.py) and on
  the planning branch, and that X9 and R-V1 describe other defects. Both refuted the fix's p7b/PR-BODY.md cite, its
  head 760f06e and NF-1 as a defect.
- **Edit**: P1c.md, cluster D1, commit 2e7d4c0: as feasible-H5 (R-N1's before 1d10ae0; R-V1's befores 26a7ea7 and
  96bcb8f). No later change.
  - For the plan files: as feasible-H5.

### feasible-M1 (medium): Acceptance 8 contradicts rows 1 and 6 on session_ts

- **Status**: REFUTED (refuter A: REFUTED; refuter B: REFUTED).
- **Reason**: Both refuters showed that the legacy correlation path is not built only on session_ts: its third
  dimension, the sentinel's exact task anchor (`_find_correlated_reports` :237-247), uses none, and row 1 already names
  that anchor as what G2 and the e2e gate keep, while the Retired list and row 3 name the e2e gate's session_ts
  branches. Both added that the fix would pull P1c's F7b repair into P1b and break P1c's R-P1 "before".
- **Edit**: none.

### feasible-M2 (medium): The stale v1 qa-report dead end comes from the resolver's optional-parent read

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that F3b's second blocker is `_optional_parent_result`
  (resolve-dev-artifact-chain.py:1146-1170), a read nothing writes in fan-out (dev.md:99, :1342-1343), that no P1b row
  removed, and that E4's rule cannot fix an over-block. Both refuted "dev-command.md's copy".
- **Edit**: P1b.md, cluster C3, commit 2e7d4c0: row 7 deletes the optional-parent read and dev.md:1340-1342's
  sentence; E4 and acceptance 5 say a stale file at an undeclared path blocks nothing; its Retired-list item was
  replaced in d22c669 by W14's pointer (row 7 still names it). P1c.md, cluster V12, commit d22c669: "Delivered by P1b"
  lists row 12, row 12 gets the delivered sentence, and the Retired count becomes at least 4. No later change.

### feasible-M3 (medium): The required PR body exceeds GitHub's 65,536-character limit

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the planning TSV alone is 79,334 characters. Both rejected the fix's single
  "PR comment" (a comment has the same cap) and the CI artifact as the only home (session outputs; artifacts expire).
- **Edit**: One text with format-FH-1: P1b.md, cluster C10, commit 2e7d4c0 (size bullet :1171-1180, row 0, acceptance
  6); P1c.md, cluster D7, commit 2e7d4c0 (bullet :1071) and cluster V15, commit d22c669. No later change.
  - For the plan files: optional prompts/_common.md "Test evidence" sentence (as format-FH-1).

### feasible-M4 (medium): E12 would delete logs/landing.log although the landing's notice names it

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that land :230, :239, :247 and :249 name logs/landing.log in a notice that
  auto-commit.sh relays as a systemMessage. B added that auto-commit.sh:51's notice names logs/checkpoint.log and that
  command-only wording remained in rows 7, 15 and 19 and the Retired list.
- **Edit**: P1b.md, cluster W4b, commit d22c669 (with owner-R17 and plan-FIT-14): E12 (:572-588) counts owner-facing
  outputs, relayed systemMessages included; rows 7, 15, 16, 17 and 19, Technical choices and the Retired list follow,
  and landing.log stays. Later fix commits on the same text: 618e22e (E12: a script a command runs and a command's
  output; row 15: /checkpoint's own output; row 16: land as the log's one writer), 5922f1f (row 16), 0bdd73d (row 7).

### feasible-M5 (medium): X8 (A) widens a CLAUDE.md-backed denial that P1c's own DO NOT forbids

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: A: the DO NOT conflict stands, and the "no outcome" part is refuted (P1 captured the scheduled-record
  shape, COV-7). B: (A) is lawful, but the DO NOT read literally also forbids rows 7, 16 and 17, and four lines in
  CLAUDE.md, README.md and ARCHITECTURE.md become false. Both rejected the "otherwise (B)" fallback and ranking T0
  above CLAUDE.md.
- **Edit**: P1c.md, cluster V3, commit d22c669 (with plan-FIT-18, owner-R12): X8 (:406-470) cites COV-7, makes the
  widened exception row 17's own decision under D20 and SG6 (not an X4 case) and ships the wake on its replays with no
  owner wait; DO NOT (:1099) reads "Such a security hook" and names the one widened exception. Later fix commits on
  the same text: 76fc635, c6e3942, 88b240c, db16126 (the DO NOT exception limited to the overnight wake inside its
  span), 453308f, 07dc782, 082ba74 (COV-7: ScheduleWakeup unavailable outside `/loop`) and ba99401.
  - For the plan files: a new reviews/P1b-plan-sync.md entry P9-8b for P9.md rows 14 and 16 (CLAUDE.md :41 and :62,
    README.md:477, ARCHITECTURE.md:178).

### feasible-M6 (medium): X6 cannot prove requirement (3) as written

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the rule has no branch for recall below 100%, that class G's "next permitted
  action" is undefined and that the DO NOT forbids X6's own overnight fixes. Both rewrote each proposed edit: recall
  counts blocks from hook code (with the hooks a registered hook runs), class G is judged per state, and the DO NOT
  admits rows 13 and 17.
- **Edit**: P1c.md, cluster V4, commit d22c669: X6's class G, the rule paragraph ("the method is required") and the
  DO NOT's last bullet (:1111). Later fix commit on the same text: 2505633 (that bullet adds X3's deletions).

### feasible-M7 (medium): X2's fixture home is not a git repository and tolerates /tmp writes P1b removes

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the landing run at Stop needs git in the harness home (land:31) and that
  the session-id tolerance is stale after P1b's path rule. Both refuted the R-N1 and F4 dependencies, and A refuted "a
  regression would not be caught".
- **Edit**: P1c.md, cluster V5, commit d22c669: X2 (:262-287) builds a landed git clone (overlay, bootstrap steps 3-5,
  `land --state` prints `landed`), the write audit allows no file outside tmp_path, and acceptance 7 (:884) checks
  both; it replaced D3's X2 sentence. No later change to these sentences.

### feasible-M8 (medium): P1b is too large for one reviewable pull request

- **Status**: REFUTED (refuter A: REFUTED; refuter B: REFUTED).
- **Reason**: Both refuters found the figures mostly accurate but no defect: one session, branch and PR per phase is
  governing (DECISIONS.md:200 and the shared tail), phases with more cited sites landed as one PR, and P1b's six
  ordered, independently revertible commits already give reviewability (P5's "split" is commit groups inside one PR).
  B added that the fix's "listed base block" pass is a committed exception list the check forbids, and that its
  net-cap counting conflicts with acceptance 20.
- **Edit**: none.

### format-FH-3 (medium): P1c builds a second scenario-driver set next to P1b's drivers

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that P1b ships the runner and the ten drivers in every E1 outcome, that P1c's
  Interfaces bullet omits the drivers, that X1's static-only branch is dead and that row 1's "one exception" is false.
  Both corrected the fix's anchors, which dropped line breaks, and its leftover sentences.
- **Edit**: P1c.md, cluster V1, commit d22c669 (with plan-FIT-21): the Interfaces bullet names the ten drivers ("you
  extend them, never a second set"), X1 extends P1b's runner and records each addition, and row 1, the pilot record,
  Technical choices and Rollback step 1 follow. Later fix commits on the same text: 76fc635 and 14d2a32 (X1's path
  sets).

### format-FH-4 (medium): Neither prompt states the commit format or the attribution trailers

- **Status**: STANDS (refuter A: REFUTED; refuter B: STANDS-CORRECTED).
- **Reason**: It stands because B did not refute it: B confirmed that neither prompt states a commit form and that the
  shared DO NOT, read literally, forbids the trailer's model name. A refuted it on precedent (COV-2 in
  reviews/P1-PR5-review-followup.md:23 dismissed the contradiction, and three phases kept the trailer unprompted); A's
  observation that P7b's subjects take the form `P7b (R...)` went into the text.
- **Edit**: P1b.md, cluster W13, commit d22c669: a Commits bullet (:1153-1158). P1c.md, cluster V11, commit d22c669:
  the same bullet (:1033). No later change.
  - For the plan files: prompts/_common.md, DO NOT (all phases): the attribution trailer lines as the one exception.

### format-FH-5 (medium): Six sync anchors are gone from the batch, and two replacements would undo its corrections

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters ran the sync file's own verification: V-5, V-8, P3-4, P6-5, P9-5 and P9-8 miss at be06811
  and aaf072c, V-8's text would bring back "(human-run, last)" and P9-5's would drop "(four if E4 drops ...)". Both
  corrected P6-5, which would have landed before the batch's D24 item.
- **Edit**: none in P1b.md, P1c.md or inventory/ (a plan-files-only finding).
  - For the plan files: c728380 (the sync list applied) already carries all six outcomes (PLAN-v2.md :142, :144 and
    :193, P3.md:750, P6.md :749 and :101, P9.md :112-113 and :465 at c461cde); the refuters' sync-file edits are
    superseded.

### format-FH-6 (medium): The never-fail rule has two names, a cut quote and a source the implementer cannot open

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that P1b and P1c called the rule "the owner's rule of 2026-10-24" while
  DECISIONS.md calls it D25, that the quote starts mid-sentence without the elision mark DECISIONS.md uses, that P1b
  cites a task nobody can open, and that P1c credits the suite design to the owner. Both reused DECISIONS.md's English
  rendering instead of adding a fourth.
- **Edit**: P1b.md, cluster W1, commit d22c669: the intro names "D25 (never fail)" (:13), the "D25 Never fail" bullet
  (:201-209) quotes DECISIONS.md:70 in full with its rendering and source, and acceptance 17's label becomes D25.
  P1c.md, cluster V7, commit d22c669: the same bullet (:162). No later change.
  - For the plan files: the D25 quotes in prompts/P2.md, P3.md, P4.md, P5.md and P6.md (start at the full sentence),
    and record corrections in reviews/P1b-plan-sync.md (:31-32, :36-39, :83, :444-447, D-1, :674, :762 and the five
    P2-P6 entries).

### owner-R5 (medium): Reviewer proposals are presented as the owner's words

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters found that DECISIONS.md D25 quotes one sentence and gives the suite as plan prose
  ("Measured by a replay suite in CI ..."), while P1b and P1c credited the owner with a ranking against D24, the
  suite's parts (1)-(4) and the merge rule. Both dropped the fix's [INFERRED] tag and its transcript timestamp.
- **Edit**: P1b.md, cluster W1, commit d22c669: the ranking is deleted and the suite is attributed to the reviewing
  session as D25's recorded measure (:201-209). P1c.md, cluster V7, commit d22c669: the same for the suite and the
  merge rule, and Goal 1 says "D25's four requirements" (:118). No later change.
  - For the plan files: as format-FH-6.

### owner-R6 (medium): Row 1's "re-run the command" turns a lost hook output into a step for the human

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that only UserPromptSubmit mints the id, so re-running is an owner step against
  D19 and D25, and that the mint already writes `task_id` into the session-keyed bookmark. Both refuted the fix's
  circular second source and its "never mint" dead end when the hook failed.
- **Edit**: P1b.md, cluster W7, commit d22c669: row 1 (:756) has the orchestrator use the `task_id` the hook wrote into
  the session's bookmark, or call the hook's own start function when none was recorded; acceptance 14 (:1001-1009)
  adds the compaction and hook-failure replays; /do's route is unchanged (B's /do part would let an agent grant itself
  /do consent). Later fix commit on the same text: 618e22e (acceptance 14: a bookmark that holds an earlier /dev's id;
  the one /restart the human types).
  - For the plan files: prompts/P9.md rows 5 and 8 (the fallback loops are gone; no owner retyping).

### owner-R7 (medium): Row 16 replaces the QA-validated permission write with reporting

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that /dev-overnight writes permissions through apply-permissions.sh and /dev and
  /dev-command through jq, that reporting instead gives the owner a manual step (D19) or unattended prompts (D20) and
  retires a feature, and that no owner ruling backs it. Both refuted the fix's "single function both call" and its
  experiment, which cannot observe prompts.
- **Edit**: P1b.md, cluster W8, commit d22c669: row 16 keeps scripts/apply-permissions.sh as the one harness writer of
  `.claude/settings.json` (create-worktree.sh stays for settings.local.json) and has the jq steps call it; row 7
  points to row 16. Later fix commit on the same text: a12fb1d (row 16's acceptance starts in toyproj, where a missing
  settings file is an empty object to the merge).
  - For the plan files: prompts/P9.md:457 (row 8): three edits to the Step 15 permission text.

### owner-R8 (medium): Acceptance 17 lets P1b add blocks on an in-flight compliant cycle

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that "no hook exits 2 except a block your rows make correct" lets the implementer
  add blocks on a live cycle, against Goal 6, "not worse", D25 and P1c's stricter acceptance. A's absolute "no hook
  exits 2" cannot hold while base blocks remain, so B's comparison with the base kit was taken.
- **Edit**: P1b.md, cluster C1, commit 2e7d4c0: acceptance 17 (:1014-1050) allows no block or deny decision that the
  base kit's same replay does not show at the same hook, step and refusal text, and Goal 6 (:111) says "nothing new
  blocks". Later fix commits on the same text: d22c669 (the rule's label becomes D25), 64bec4f (the in-flight cycle is
  a replay of the base's text; each base block is listed with its deviation as acceptance 4 says), a263825 (the
  in-flight closes).

### owner-R9 (medium): Acceptance 4 demands 0 blocks that only P1c and P2 can remove

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that acceptance 4 required 0 blocks on all ten pipelines while the overnight,
  /merge, /dev-command and close.md Step 0 refusals owned by P1c rows 18-19 and P2 still exist on master and P8's
  head, so the trace also misses every later step. Both corrected the fix to "no new block versus the base" with
  marked driver deviations, because an exception keyed to P1c's lists would excuse blocks P1b's own rows remove.
- **Edit**: P1b.md and P1c.md, merged with feasible-B1 and plan-FIT-01 into one mechanism, commit 2e7d4c0. Cluster C1
  (P1b): acceptance 4 compares with the base kit and passes a kept base block only by a `DEVIATION:` step listed
  under "Hand-off to P1c"; E5, E13 and row 13 reach the overnight cycles through those deviations. Cluster D5 (P1c):
  the Interfaces P1b bullet, the "Rows 18 and 19, P1b's kept base blocks" paragraph and acceptance 3's
  `git grep -n 'DEVIATION:'`. Later: 64bec4f made the base-kit comparison one mechanism (every block recorded,
  base-text replays) and E13 say "kept base blocks", and a263825 edited acceptance 4 again (P1b.md:853-875);
  e1762a6 split P1b's hand-off into two lists in the bullet, the paragraph (P1c.md:557) and acceptance 3
  (P1c.md:862-865); a34e686, 76fc635, d22c669 and c33ca28 edited other parts of the bullet (P1c.md:49-58).

### owner-R10 (medium): The allowed positions omit the kept chain-function call and the Stop gate

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that goal 3 allowed only the producer's stop, G1 and G3, while row 7 keeps one
  chain-function call at /dev's end, /close and /commit and D21/SG1 keep a Stop gate, so the zero-exception check
  would fail on P1b's own design and on P5's gate. Both dropped the fix's "G4 now" (row 3 and correction 6 stub G4)
  and allowed the Stop position only as a user of the chain function's conclusion that re-validates nothing.
- **Edit**: P1b.md, cluster C4 (one definition merged with feasible-H1, feasible-H2, owner-R11 and plan-FIT-15),
  commit 2e7d4c0: goal 3 names two completion reads, the single chain-function call and the command's Stop gate
  (P1b.md:90-99); the owner-rulings paragraph adds them (P1b.md:184-187); E1's re-check is a read outside goal 3's
  positions (P1b.md:245); row 19 reads positions from settings.json's event and matcher and the chain function's call
  sites and gains rule 5; acceptance 3's mutation is "a second resolver run ... or a Stop hook re-validating a
  subagent's artifact" (P1b.md:841-845). Goal 3 and acceptance 3 are unchanged since; rule 5 was later extended by
  618e22e (the routing loop's re-run is the same call), e73c58d (rule 6's measured clause) and ef34dbc (what counts
  as the main agent's writes).

### owner-R11 (medium): Hand-written role and pipeline lists and file prefixes survive a zero-exception check

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that obligation.ROLES and PIPELINES (obligation.py:74-83 at d625284) were kept
  or extended by E3's fallback while row 18 deleted PIPELINES and acceptance 3 must fail on a hand-written role list.
  Both corrected the fix: G1 and G2 read ROLES as their producer test (graphify is dispatched without a block,
  commands/dev.md:763-775), the schema enums are a third copy, and the finding's prefix assertion would also hit the
  directory and wildcard prefixes P5-a narrows.
- **Edit**: P1b.md, cluster C4, commit 2e7d4c0: E3's fallback validates role against the roster function and pipeline
  against the command files (P1b.md:322-323); row 18 drops ROLES, PIPELINES and the schema's role and pipeline enums,
  reads G1's must-carry test and G2's expected_role from the active command's declaration and limits the roster to agent
  files with front matter (P1b.md:773); E3 fails on a file prefix naming a derived artifact and keeps directory and
  wildcard prefixes (P1b.md:332-339); row 19 rule 7. Later: d22c669 (cluster W10, plan-FIT-12) narrowed E3's and rule
  7's prefix rule to allow prefixes, deny prefixes staying; 618e22e and 7304b34 edited E3's fallback paragraph.
  - For the plan files: P9.md Correction 17 and acceptance 7 no longer keep ROLES as a subset (in P9.md since f65290d);
    P6.md row 3's "obligation.ROLES" clause (optional, still to apply).

### owner-R12 (medium): X8 (B) leaves an unattended overnight session waiting while the DO NOT says it adds no wait

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that X8 (B) kept the human /restart inside /dev-overnight while the DO NOT
  claimed "(B) adds no wait" and F6o asserted no human event, so the suite could not go green under (B). Both rejected
  the fix's option (C), since no tree ships such a wake, and its "never counted as passed" F6o, which breaks the
  no-xfail DO NOT.
- **Edit**: P1c.md, cluster V3 (merged with feasible-M5 and plan-FIT-18), commit d22c669. Neither refuter's text was
  used, since both kept (B) with an explicit human wait that D20 forbids: V3 removed (B), so X8 always ships the wake;
  row 17 became "F6o, X8's wake" (P1c.md:551); Rules added and Technical choices dropped "if A"; the DO NOT dropped
  "adds no wait". In the same commit the round-1 hand-off fix corrected V3's new DO NOT sentence, false in X8's own
  CLI-limit case, to the refuters' reading: where the CLI cannot fire the wake the cut still waits for his /restart
  and the PR reports that CLI limit, never as met (P1c.md:1088-1093). Later c6e3942 (a pre-merge session has no wake
  step) and db16126 (the wake's span) extended that bullet; row 17 was later edited by c68a19f, c6e3942, eef8a5c,
  88b240c, db16126, 453308f and 07dc782.

### owner-R13 (medium): The suite leaves out the overnight producer-question path that still parks

- **Status**: REFUTED (refuter A: REFUTED; refuter B: REFUTED).
- **Reason**: Both refuters agreed that master's dev-overnight.md still parks and asks after end_time, but held the
  flagged P1c text correct: D20 assigns the proof to P2's acceptance 14, D25 has each later phase add the replays for
  the flows it changes, P2 rows 10 and 15 and acceptance 14 already hold the deny, the parking removal and the
  unattended-decision replay, and X5 covers blocks on the compliant path, not prose behaviour. The fix would also
  contradict P1c's Out of scope and, without P2's deny, assert only what the driver chose to do.
- **Edit**: none.

### owner-R14 (medium): Class D proven by the compliant scenario lets fault-state dead ends pass

- **Status**: REFUTED (refuter A: REFUTED; refuter B: REFUTED).
- **Reason**: Both refuters showed that the cited traps (F3b, F4c, F4s) are requirement (2) faults, each asserted to
  reach its terminal with 0 human events, and that merge.md's grant `rm -f` lies on the compliant path (row 18), so
  the full-set merge condition already catches them. The fix's "every replay ... reaches its terminal" would fail each
  D site's hook-level proof replay, and its "0 human events" contradicts the /restart exception of F5, F5f and F6.
- **Edit**: none.

### owner-R15 (medium): The full-set run and the fault-coverage step rest on discipline

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the full set ran only on workflow_dispatch or the one-time
  ready_for_review event and that a PR-body sentence could exempt a changed command or agent file (HC2). Both rejected
  the fix's "required status check" (a repository setting no PR makes), "shard further" (breaks X10's bound) and
  "extract every fenced block" (it would block prose-only edits).
- **Edit**: P1c.md, cluster V6 (with feasible-L1's P1c part), commit d22c669: X10's full set starts on every
  pull_request event of a PR to master, a newer push cancelling the older run (P1c.md:504-510), and the merge rule
  prints a commands/ or agents/ file no scenario reads and reads no PR-body reason. The coverage step was reworked by
  the round-1 coverage fix in the same commit, by 76fc635 (it fails only on a changed definition a replayed pipeline
  reaches and no replay reads, printing the rest, as both refuters ruled), 9f214f3, 14d2a32 (one rule) and 65dd54a;
  "asks for and reads no PR-body reason" is at P1c.md:787. 14d2a32 also edited X10's last sentence.

### owner-R16 (medium): P1c treats P1b as a later phase and never binds its D24 check

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed the stale ordering ("list them for P1b's table; do not merge them here",
  "Removing the re-checks at /close and /commit (P4)") although P1b merges first. Both refuted "never requires the
  check green" (acceptances 2 and 17 imply it) and the fix's whole-bullet replacement, which dropped a scope limit.
- **Edit**: P1c.md, cluster D3 (with feasible-H6, format-FH-2, plan-FIT-11 and feasible-H7), commit 2e7d4c0: the
  /close and /commit Out of scope bullet names the P1b rows that removed their re-checks; the D24 bullet says P1b's
  check stays green with no exception and a second producer or decider found on the base goes under "Out of scope,
  found" (P1c.md:815-819, unchanged since); row 10 keeps what P1b merged; acceptances 2 and 17 include P1b's D24
  check (P1c.md:847, :949). Later: d22c669 (cluster V14, feasible-H1's P1c part) replaced row 10's sentence with P1b
  row 7's split by property; 14d2a32 and 2505633 extended the /close and /commit bullet (P1c.md:812-814); 76fc635 and
  14d2a32 edited acceptances 2 and 17 around the inserted words.

### plan-FIT-07 (medium): Six sync-list anchors are gone at be06811, and V-8 brings back "(human-run, last)"

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Neither refuter refuted it: the V-5, V-8, P3-4, P6-5, P9-5 and P9-8 anchors no longer matched at
  be06811, and V-8's new text restored the removed "(human-run, last)". It duplicates format-FH-5.
- **Edit**: none in P1b.md, P1c.md or inventory/ (plan-files-only cluster).
  - For the plan files: PLAN-v2.md's P11 row and wave 9, P3.md's dependencies, P6.md's never-fail acceptance and its
    cross-reference, and P9.md's include-file note and row 16 already carry every outcome since c728380; the
    re-anchoring of reviews/P1b-plan-sync.md is superseded because the list is applied. Nothing is left.

### plan-FIT-08 (medium): The sync list puts each never-fail item ahead of the batch's D24 acceptance

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters refuted only the "two items of the same number" wording, which the sync's renumber rule
  prevents; the placement defect stood: inserting after the net-code line put each never-fail item before the
  batch's D24 acceptance, and the cross-references pointed at the wrong item.
- **Edit**: none in P1b.md, P1c.md or inventory/ (plan-files-only cluster).
  - For the plan files: in P2.md, P3.md, P4.md, P5.md, P6.md and P9.md each never-fail item is the last acceptance with
    the next free number and each Merge rule bullet cites it, already so since c728380; nothing is left (P9-6's
    cross-reference, refuted by both, is not recorded).

### plan-FIT-09 (medium): DECISIONS.md lets D20-D24 override D25, and D-1 would add a second D25

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed the duplicate D25 that D-1 would insert and the heading at DECISIONS.md:7 that
  put D20-D24 above D25. Both corrected the fix, whose "except D25, PLAN-v1, PLAN-v2 and every prompt" reads as one
  exception list, and whose "D20-D25" edits in P1b and P1c would misdate D25 and point at a file without it.
- **Edit**: none in P1b.md, P1c.md or inventory/; clusters W1 and V7 (commit d22c669) left out the "(latest; ranks with
  D24)" ranking, which owner-R5 and format-FH-6 attribute to the reviewer, not the owner.
  - For the plan files: DECISIONS.md:7's heading now lets the 2026-10-23 rulings override PLAN-v1, PLAN-v2, every prompt
    and every decision below except D25 (fa5659d); the 2026-10-24 heading at :68 (c728380, with fa5659d's "D25 and
    D20-D24 do not override one another") and the single D25 bullet keep D-1 from adding a second D25. Nothing is left.

### plan-FIT-10 (medium): D25 (2) says "no human action" while D22's /restart and P1c's suite need one

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed the conflict between D25 (2), D22's human-only /restart and P1c's exception, and
  found the same contradiction inside P1c (Goal 1 (2) had no exception). Both corrected the scope ("outside
  /dev-overnight" binds only the usage-limit cut) and the citation (teachings:295 says only "use the restart
  command"; the human-only design is restart.md's `disable-model-invocation` and the `Skill(restart:*)` deny).
- **Edit**: P1c.md, cluster V9, commit d22c669: one clause, word for word in Goal 1 (2), the suite's human-events
  assertion and acceptance 4 (P1c.md:124, :703, :868): the one /restart the human types in F5, F5f and F6 and the /close
  or /commit the human types in each F8 fault, F6o resuming with no human action at all (D20, X8). Unchanged since.
  - For the plan files: DECISIONS.md D25 (2) was rewritten by f65290d to "no human action beyond the owner's own
    commands", so its record is moot; PLAN-v2.md:1175 (c728380) and section 15's P1c bullet (fa5659d, f65290d) and
    COVERAGE.md's D25 (2) row (f65290d) carry the exception; the sync-list rows are moot.

### plan-FIT-11 (medium): P1c redoes work P1b delivers and pays its net cap with P1b's deletions

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that rows 7, 10, 13 and 19, row 18's do.md and /dev-command bullets, Out of
  scope and X2 repeat P1b's rows or hand items to "P1b's table" after P1b merged, and that the "<= 0" cap was paid by
  lines P1b deletes. Both refuted the per-row prefix as written and the row-18 bullet deletions (the /dev-command
  bullet holds P1c-only work).
- **Edit**: P1c.md, cluster D3, commit 2e7d4c0: a "Delivered by P1b" paragraph (P1c.md:518); short leads on rows 7,
  10 and 13 and on row 19's seed bullet (verify on your base, add the replay, change only what P1b's PR left); Out of
  scope items listed only if the base still shows them; R-E1's "before" on the first parent of P1b's merge; the
  hand-off's 2.30 credited to P1b row 3; the net code cap <= +150 against the base, feasible-H7's bound
  (P1c.md:976-983). Later: cluster V5 (d22c669) replaced D3's X2 text with the write audit (plan-FIT-17); the
  "Delivered by P1b" paragraph was extended by d22c669, 76fc635, a34e686, e1762a6, c68a19f and eef8a5c; d22c669 also
  edited the cap paragraph.

### plan-FIT-12 (medium): E3 repeats P5 row 1 and never says how its permission ships

- **Status**: STANDS (refuter A: REFUTED; refuter B: STANDS-CORRECTED).
- **Reason**: Refuter A refuted it: the per-role prefixes are allow entries under a default deny, so deleting them
  loses no deny, and acceptance 4 already forces the derived permission to be live. Refuter B agreed on the
  allow-prefix point but confirmed that P1b never says where the permission ships or whether it enforces, and that
  Out of scope gave P5 an undeclared-path deny P5 does not plan. It stands because B did not refute it.
- **Edit**: P1b.md, cluster W10 (refuter B's fix, adapted), commit d22c669: E3's derived permission ships in
  hooks/pretool-tool-policy.py, enforcing with no switch, for every caller (the main agent's half left to P5 row 1 only
  if acceptance 17 shows a new main-agent deny), with its acceptance and a count-above-0 rule (P1b.md:341-354); the
  prefix rule covers allow prefixes and deny prefixes stay; row 19 rule 7 likewise; Out of scope names P5 rows 2 and 3
  (P1b.md:810). Later 618e22e (a dispatch made from the base's templates may write what its template declares; the
  acceptance replayed on the branch) and 64bec4f edited the same E3 passage.
  - For the plan files: PLAN-v2.md (:87 fa5659d, :536 b335a0e), P5.md and P6.md already say P1b ships the deny and P5-a
    verifies it; one optional PLAN-v2.md section 11 row is still to apply.

### plan-FIT-13 (medium): E8's tie-break silently removes the pending skeleton P5's TC-18 needs

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that preferring (a) removes the hook-written pending skeleton P5 rows 15 and 21
  rely on, and that P1b never tells P5. Both rejected switching the tie-break to (b), whose two writers fail D24, and
  gating (a) on a TC-18 replay that cannot run in P1b.
- **Edit**: P1b.md, cluster C7 (with facts-F4), commit 2e7d4c0: a new Correction 8 tells P5 that `pending` leaves the
  enum and asks the replay to name the hook-written record that still names the first task (P1b.md:707-714); E8 points
  to it (P1b.md:512). Later a19d839 added row 9's deletion of the /do gate's `blocked` rewrite and 787167e the P5.md:841
  cite.
  - For the plan files: P5.md's row 15, acceptance 5, row 21 enum and S9 are overridden in place since f65290d; P3.md
    and PLAN-v2.md already carry it (PLAN-v2.md through f65290d and b335a0e).

### plan-FIT-14 (medium): E12 deletes logs/landing.log that P10, P11 and P1c's R-V1 rely on

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that E12's rule deletes the log P11's landing step appends to and P10 scans.
  Both refuted the sub-claim that P1c's R-V1 loses its target in the deletion case, and both preferred keeping the
  log over the fix's move of its content into the one-line notice.
- **Edit**: P1b.md, cluster W4b (merged with feasible-M4 and owner-R17), commit d22c669: E12 counts an owner-facing
  output (a command's output, or a hook systemMessage that reaches the owner) and row 16 keeps logs/landing.log with
  the owner as its consumer through the landing's notice (P1b.md:570-585, :771). Later 618e22e widened E12 to a
  script the command runs and left land the log's one writer, and 5922f1f named row 16's tree (master 2acc29b). No
  plan-file change: P10, P11 and R-V1 keep their target.

### plan-FIT-15 (medium): The CI check misses the artifacts that are not files

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the check derived relations only from file operations and literal paths,
  so the task-id rule, obligation records, the terminal vocabulary, the resolver's stdout and response blocks had no
  one-producer check once the sync dropped P10's goal. Both rejected "callers of the parsing function" as the only
  reader source, since a second parser need not call it.
- **Edit**: P1b.md, cluster C4, commit 2e7d4c0: row 19 rule 2 finds a non-file artifact from what declares it
  (markers and regexes, schema enums, minted ids, a script's invocation) and measures its deciders as in E1
  (P1b.md:774); acceptance 3 adds mutations for a second response-block parser, a second task-id derivation, a copied
  terminal vocabulary and a script deciding on the resolver's stdout (P1b.md:841-848). Both texts are unchanged since.

### facts-F11 (low): Inventory row A58 reverses the close-report markers' relation

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that close-report-append.py writes the markers (`_write_failure_marker`, open
  "x" at :296, a fixed /tmp at :232) and that :771 is a run() call, not a delete, so A58 is written never read, not
  read never written.
- **Edit**: inventory/, cluster I2, commit d22c669: A58's paths, producer (:250-317), readers, violation and resolution
  corrected, and the README counts recomputed (written never read +1, read never written -1). A58 is unchanged since;
  the README counts were recomputed again by every later inventory round.
  - For the plan files: the map figure quoted at PLAN-v2.md:1176 and reviews/P1b-plan-sync.md:419 (one combined record,
    superseded by the later recounts).

### facts-F14 (low): Correction 5's one-line -F parsing fix cannot restore the subject check

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the guard sees the unexpanded `${MSGFILE}` at PreToolUse, so stripping the
  quotes still opens a path nobody wrote. Both added the bulk loop's `; then` form and corrected the trace-a
  description: it opened a quoted literal path.
- **Edit**: P1b.md, cluster W5, commit d22c669: Correction 5 takes the operand from the shell-tokenised invocation,
  makes the analyst and the guard name one path (chosen by experiment, no new state file) and tests the three forms
  the analyst's prose gives (P1b.md:689-705); later 7c93969 made its bare cites name their file. P1c.md: the "Out of
  scope, found" -F bullet states the same causes (round-1 hand-off fix in d22c669, on cluster D3's 2e7d4c0 wording;
  later edited by 76fc635; P1c.md:823).

### facts-F15 (low): E7 lists only /dev's qa_mode call sites

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that write-qa-mode.sh is also called from dev-command.md and dev-overnight.md
  (and close.md's arming), so removing the file write would strand those calls. Both added dev-overnight.md:1503 and
  :1648 and the dependents (the settings.json:52 allow rule and the overnight sandbox's RW bind).
- **Edit**: P1b.md, cluster W6, commit d22c669: E7 cites every call site at d625284 (P1b.md:462-464), each call drops
  its flip and goes with the script when nothing is left, close.md's arming stays under row 1, and the two dependents
  follow what they depend on. Later 618e22e (E7's second qa_mode reader) and 64bec4f (calls get the project root on
  the command line) edited the same paragraph.

### facts-F16 (low): X7 cites the wrong lock-sensitive lines and misses the silent deletion path

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that session_index.py:231-235 is `git diff-tree`, which takes no lock, and that
  the deletion branch's `update-index --force-remove` ignores its exit code, so a deletion-only commit is reported
  synced. Both corrected the line anchors and asked for a separate deletion-only run.
- **Edit**: P1c.md, cluster D2, commit 2e7d4c0: X7's citation (P1c.md:380-384, unchanged since); the experiment runs
  each case with a modifying and a deletion-only commit (P1c.md:392-395, later edited by the round-1 X7 fix in
  d22c669); row 14's third and fourth cells; the F4c fault (later edited by 76fc635 and 8ad26bc).

### facts-F17 (low): Three stale location claims

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that stop-do-report-gate.py:23-26 is docstring (the set is :59, used at :101),
  that aggregate-dev-report.py keeps its own sets (:2099, and the shard check :784), and that push.md:82-84 is
  push.sh's read side while the agent's scan is Step 1, :140-149.
- **Edit**: P1b.md, cluster C7, commit 2e7d4c0: row 9 cites :59 with :101, :104 and the docstring; row 6 adds
  aggregate-dev-report.py:2099, the shard check :784 staying with P1c row 11 (P1b.md:761, :764); unchanged since.
  P1c.md, cluster V10, commit d22c669: row 18's push.md bullet cites Step 1 (:140-149) and :82-84 for the `find`
  form (P1c.md:585); unchanged since. inventory/, cluster I2, commit d22c669: A40 lists :784 (the shard status check)
  and :2099; A40 was later edited by 31acd8f (round-12 sweep), which kept that text.

### facts-F18 (low): Unregistered scripts presented as live producers and readers

- **Status**: STANDS (refuter A: REFUTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters refuted the stop-cleanup-allowlist.sh part: the registered Stop coordinator runs it as its
  cleanup phase (stop-workflow-coordinator.py:72), so A63, A98's :28 and row 14 are right. Refuter B confirmed the
  rest: audit-slashcommand.sh and session_start.sh are registered nowhere and run by nothing. It stands because B did
  not refute it.
- **Edit**: P1b.md, cluster C5, commit 2e7d4c0: row 14 cites stop-cleanup-allowlist.sh:26-29 as the Stop
  coordinator's cleanup phase (P1b.md:769); row 18's session_start.sh cite went with facts-F1's row 18 rewrite.
  inventory/, cluster I2, commit d22c669: A98 marks pretool-overwrite-guard.py:125 and audit-slashcommand.sh:39 as
  unregistered with no live entry point (P10 row 4 deletes both). That note survives; A98 was later edited by 822621b,
  31acd8f, d6409c2 and 4ce4271.

### feasible-L1 (low): "Required check" is a repository setting no PR can create

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that no tree configures branch protection and a PR cannot make a check
  required, so the wording read as an administrator step that D19 rules out; baseline.yml's comment calling the job
  "already-required" is false too.
- **Edit**: P1b.md, cluster C9, commit 2e7d4c0: E2's fallback job "must be green on the PR head before the reviewer
  merges (...; the PR changes no repository setting)" (P1b.md:272-274; rewrapped by 618e22e). P1c.md, cluster V6
  (with owner-R15), commit d22c669: X10 drops "as a required check" and states the same merge condition
  (P1c.md:508-509); row 6 drops "required on pull_request" and says the baseline.yml comment loses its claims
  (P1c.md:540).

### feasible-L2 (low): Shared text copied into P1b and P1c is stale

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the shared CI section dates from a red master and that "keep CI no worse
  than master" and "tell the owner" contradict P8's green CI and D18/D19. Both moved the fix out of the byte-identical
  tail into an override bullet and dropped the fix's new stop condition, a possible dead end under D25.
- **Edit**: P1b.md (cluster W13) and P1c.md (cluster V11), commit d22c669: a bullet under "Branch and pull request"
  says the bullets above the tail govern: CI green, and "tell the reviewer ..., never the owner" (P1b.md:1145-1151,
  P1c.md:1027-1033). Later 618e22e (P1b) and 76fc635 (P1c) edited the acceptance references in it. For the plan
  files: prompts/_common.md's Planning documents, DO NOT (commit trailers), CI and Pull request sections, then the
  tail resynced into every prompt that ends with it (still to apply).

### feasible-L3 (low): Acceptance 9's grep finds 14 sites where row 12 names three

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed the grep's extra hits and asked that each moved path move writer and reader
  together (the residual override's reader is single-quoted), without calling the hero demo's scans readers.
- **Edit**: P1b.md, cluster C6, commit 2e7d4c0: row 12 moves every other fixed state path acceptance 9's greps list
  on the base, writer and reader together, with the d625284 sites as examples (the merge-analyst grant, the residual
  override, the /stop helper-auth read, the hero demo's grant and its `/claude-grants/` scans, the close-report
  markers if E12 keeps them) (P1b.md:767). Unchanged since.

### feasible-L4 (low): E2's experiment cannot start from a push to the branch

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that baseline.yml's push trigger names only master and main and that
  workflow_dispatch exists only from P8. Both rejected "remove before the first commit the PR keeps": without a
  force-push every pushed commit stays.
- **Edit**: P1b.md, cluster C9, commit 2e7d4c0: E2 runs the probe in the PR's runs (an early draft is still the one
  PR) or through P8's workflow_dispatch, adds and deletes it in two commits that stay, keep the suite green and revert
  on their own, and puts the run URL and measurements in the PR (P1b.md:260-266). Unchanged since.

### feasible-L5 (low): P1b names P7b's git-directory files with an "or" although both exist

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the record (`claude-settings.applied`) and the marker
  (`claude-settings.checked`) both exist at P7b's head, and that facts-F7's fix subsumes this one at the same anchors.
- **Edit**: P1b.md, cluster W3, commit d22c669, through facts-F7's merged text: the Interfaces P7b bullet and row 0
  name the record, the marker and the lock as three files to map (P1b.md:60-71, :755). Later 618e22e edited the
  bullet (the record's writer; land as the log's one writer).

### feasible-L6 (low): Map rows with violations have no scope row

- **Status**: REFUTED (refuter A: REFUTED; refuter B: REFUTED).
- **Reason**: Both refuters showed that every violation of the regenerated map is already in scope (goals 2 and 5,
  row 0 and acceptance 6), each cited id falls in a scope row's group range, and the example list was wrong for most
  rows: A29 and A87 have real writers the replay did not reach, A58's evidence is wrong (facts-F11), and A82 is the
  owner-read summary.
- **Edit**: none.

### feasible-L7 (low): Row 1's armed mode leaves out STOPGATE

- **Status**: STANDS (refuter A: STANDS; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that P1c row 1's armed mode set only GATE and BARRIER, so before Rollback step 7
  it did not arm G2, unlike P1b E4's armed mode and the pilot's column the fault table quotes. Refuter B added the
  Rollback steps the change would otherwise make false.
- **Edit**: P1c.md, cluster V2 (refuter B's fix), commit d22c669: row 1's armed mode adds CLAUDE_OBLIGATION_STOPGATE
  (P1c.md:535); Rollback step 3 takes the armed replays that pass at that commit and step 7 keeps only the
  shipped-mode replays (P1c.md:1002-1010). Step 7 was later extended by 2505633 (X3's deletion of the G2-only
  copies).

### feasible-L8 (low): C1's subset test and E4's escape list fail by construction

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the branch's replays reach steps the base never reaches (the overnight
  cycles), so the subset test fails, and that after E12 no advisory record exists, so E4's list comes out empty. Both
  corrected the fix, whose "literal writer site" fails for paths assembled at run time.
- **Edit**: P1b.md, cluster C3, commit 2e7d4c0: acceptance 11 compares only steps both trees reach and lists each
  branch-only pattern with its writer site on the base (P1b.md:988-992); E4's sentence went with owner-R2's rewrite,
  its point kept as E4's "(an advisory record stops nothing)" and E12's "no fault relies on such a record". Later
  64bec4f reworded acceptance 11's branch-only case ("one the base kit does not reach, even past its blocks").

### format-FH-7 (low): "Owner steps: none." as the prompts' first line

- **Status**: REFUTED (refuter A: REFUTED; refuter B: REFUTED).
- **Reason**: Both refuters held the flagged text correct: the brief requires each prompt's first line to be exactly
  "Owner steps: none.", stating the PR-body rule in the D19 paragraph and in the PR section follows the series (P7b,
  P9, P10), and the finding miscounted the PR rule (line 1 is the prompt's header, not a PR rule).
- **Edit**: none.

### format-FH-8 (low): The inventory README's recipe runs unpublished scratch scripts

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the README's commands and inputs live only in unpublished scratch, so an
  implementer can neither run nor read them, and that "16 to 18 claims" disagreed with the README's own 18 and P1b.
  Both replaced the recipe with prose.
- **Edit**: inventory/, cluster I3, commit d22c669: "How it was produced" names the unpublished scripts and says P1b
  does not rerun them (scope row 0 regenerates the map), the Sources table marks the inputs "(not published)", the
  count reads "18 claims", and the six-row paragraph drops its false "differs ... in those rows only" (README.md:41,
  :91-94, :143-150). Unchanged since.

### format-FH-9 (low): Restated lists that must agree

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed item (1) (the Retired list restates the Scope table) and item (5) (a second
  "Out of scope, found" PR heading); for item (2) (the README restates P1b's coverage section) A corrected the fix and
  B refuted it. Both refuted item (3) as proposed (land writes and reads the claude-settings.checked marker) and
  item (4) (the register row ranges are an index into a frozen audit).
- **Edit**: P1b.md, cluster W14, commit d22c669: the Retired list points at the Deleted and Moves cells of rows 1-18
  (P1b.md:1095-1096), the CLI's modelled writes include settings (P1b.md:741), and the PR heading list drops the
  duplicate (P1b.md:1170; the list around it later edited by 7304b34 and 64bec4f); item (3) corrected through
  facts-F7's text (cluster W3). P1c.md, cluster V13, commit d22c669: the same duplicate heading removed
  (P1c.md:1070). inventory/, cluster I3, commit d22c669: README's first "Not covered" bullet points at P1b's section
  and keeps the two facts only it held (README.md:134-136).

### format-FH-10 (low): P1c restates pre-P1b and duplicated text

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the wave paragraph predates P1b (no wave id 2c), that X10 restated the
  pilot timings, that the Out of scope bullet repeated the #5 conflict and that the D18/D19 entry repeated the
  opening. Both kept the DT4 note and the P9 hand-off.
- **Edit**: P1c.md, cluster V8, commit d22c669: "Wave 2c: right after P1b (wave 2b), before P2 and P3" (P1c.md:8-16);
  X10's inputs point at the pilot section and P1b's traced CI job (P1c.md:491); Out of scope "CLAUDE.md (P9),
  DECISIONS.md and the planning documents" (P1c.md:820); the D18/D19 pointer line (P1c.md:199). Unchanged since.

### format-FH-11 (low): The sync list's PLAN-v2 section 15 restates material placed elsewhere

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that sync V-31, which c728380 carried into PLAN-v2.md section 15, restates
  P1b's takeover list (already in each phase's section), the CLAUDE.md #5 note (P9's CLAUDE.md row) and P1b's own
  corrections.
- **Edit**: none in P1b.md, P1c.md or inventory/ (plan-files-only; cluster V8 notes it only).
  - For the plan files: PLAN-v2.md section 15's takeover list becomes a pointer to each phase's "After P1b and P1c"
    paragraph, and its CLAUDE.md and corrections bullets go (the last re-anchored after f65290d and b335a0e rewrote it);
    reviews/P1b-plan-sync.md:57's note on D-1 (all still to apply).

### owner-R17 (low): E12's rule deletes logs/landing.log although the landing's notice names it

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that E12 counted only a command file's output as read by the owner, so the
  landing's own "see logs/landing.log" notice would point at a deleted file, while D24 counts the owner as a
  consumer.
- **Edit**: P1b.md, cluster W4b (merged with feasible-M4 and plan-FIT-14), commit d22c669: E12 counts any
  owner-facing output, a hook's systemMessage included, and row 16 keeps the log with the owner as its consumer
  (P1b.md:570-585, :771); later 618e22e and 5922f1f, as under plan-FIT-14. inventory/, cluster I2, commit d22c669:
  A106 names the owner as reader through the landing's notices; unchanged since.

### owner-R18 (low): E14 candidate (a) gives the spec monolith three writers

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that one writer per section is several producers of one file under a file-level
  trace and row 19 rule 1, so (a) could never pass goal 1. Both named the /spec orchestrator, not the spec agent, as
  the one writer and added a fallback.
- **Edit**: P1b.md, cluster W9, commit d22c669: E14 "One producer for the spec monolith": the /spec orchestrator is
  the one writer, every other writer the map finds stops, and QA's section text stays in its own report (row 7)
  (P1b.md:620-640). Later 618e22e (round-1 fix) restored /commit Step 8's spec block and /spec-update's modes, which
  W9 had dropped, as writes through the one writer's code path, and W9's plan-file records were dropped. inventory/,
  cluster I2, commit d22c669: A47 lists /spec-update's continuation mode and the /dev-command and /dev-overnight
  writers; A47 was later edited by 0372d14, 31acd8f, d6409c2 and 37a259a, which kept that text.

### owner-R19 (low): Row 11 fixes the orchestrator as the aggregate's re-runner; GATE_FAULT "stays"

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed the row 11 half: P1b's E5 may make another actor the canonical aggregate's one
  producer, so P1c must not name the orchestrator. Both refuted the GATE_FAULT half (it does fit X6's classes) and
  the proposed class E.
- **Edit**: P1c.md, cluster V4, commit d22c669: row 11 says the canonical's one producer, as P1b's E5 chose, writes it
  once the lane is repaired (P1c.md:545); row 7's GATE_FAULT sentence says X6 classes its site like any other, G or U
  (P1c.md:541). Both unchanged since; no class E was added.

### owner-R20 (low): Shared text tells the session to tell the owner, and the CI paragraph is stale

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that "stop and tell the owner" contradicts D18/D19 and both prompts' own "tell
  the reviewer", and that the CI paragraph allows pre-existing failures although P8 makes CI green first. Both put
  the fix in `_common.md` with a tail resync.
- **Edit**: P1b.md and P1c.md: covered by feasible-L2's override bullet (clusters W13 and V11, commit d22c669); no
  separate edit.
  - For the plan files: prompts/_common.md's Planning documents, CI and Pull request sections with the tail resync, and
    the "Before you start" lines of P2-P6, P7b, P8 and P10 that say "tell the owner" (still to apply).

### plan-FIT-16 (low): The sync's P2 block leaves out what P1b and P1c deliver

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that P2's rows still edit and test write-qa-mode.sh and the overnight-state
  writers that P1b removes, and that neither the sync's P2 block nor PLAN-v2's P2 paragraph names them or P1c's X5
  deliveries.
- **Edit**: none in P1b.md, P1c.md or inventory/ (plan-files-only); cluster C11 (plan-FIT-03, commit 2e7d4c0) worded P1b
  E13's /stop state write through the launcher's write path, which the P2 record follows.
  - For the plan files: P2.md's "Already done" bullet gains that its rows act only on what P1b left and how /stop's
    record follows P1b's E13 (still to apply); the bullet's list itself is in P2.md since c728380 and PLAN-v2.md's P2
    paragraph carries it since b335a0e.

### plan-FIT-17 (low): X2, X10 and the coverage step do not fit P1b and the later phases

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED, refuting the X10 part).
- **Reason**: Both refuters confirmed that X2 tolerated fixed /tmp writes P1b's path rule removes and that the
  coverage step required a changed settings.json to lie on a path it never defined. Refuter B refuted the X10 part,
  which cluster D8's sentence already covered.
- **Edit**: P1c.md, cluster V5 (with feasible-M7), commit d22c669: X2's fixture writes no file outside tmp_path, a
  state file found there being a path-rule defect fixed at its writer (P1c.md:279-288, unchanged since); the merge
  rule compares settings.json key by key; acceptances 7, 8 and 12 and Rollback step 1 follow. The X10 part is cluster
  D8's sentence (commit 2e7d4c0; 14d2a32 later made it "its own job"). The merge rule and acceptance 8 were reworked
  by the round-1 coverage fix (d22c669), 76fc635, 9f214f3, 14d2a32, 65dd54a and a34e686, keeping the key-by-key rule
  (P1c.md:770-775).

### plan-FIT-18 (low): X8's widened SendMessage exception makes four repository lines false

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that widening the exception to the overnight session's own wake makes
  CLAUDE.md:62's "sole SendMessage exception" and Lesson 16 (:41), README.md:477 and ARCHITECTURE.md:178 false,
  while P1c's hand-offs named only Hook Discipline #5.
- **Edit**: P1c.md, cluster V3 (with feasible-M5), commit d22c669: a hand-off bullet names the four lines for P9 rows 16
  and 14, backed by an E3 replay of the widened exception (P1c.md:1062-1066); the "only if X8 took (A)" condition was
  dropped because X8 always ships the wake. Later db16126 aligned it with the wake's span.
  - For the plan files: P9.md carries the hand-off as its own paragraph joined to rows 16 and 14 since f65290d; the sync
    entry and the row edits are moot.

### plan-FIT-19 (low): Experiment and probe ids clash across P1b, P1c and the ledger

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that the bare "E1" in P1b's row 6 and Out of scope reads as P1b's own
  experiment E1 rather than the ledger's E1. Both refuted the probe rename (the Q ids are taken; it would leave cells
  half renamed) and the optional P1c X-id rename.
- **Edit**: P1b.md, cluster W11, commit d22c669: row 6 "fixes the ledger's E1, the v1/v2 contract conflict" and Out of
  scope "the ledger's E1 (the v1/v2 contract conflict)" (P1b.md:761, :798); unchanged since. P1c.md and inventory/
  unchanged (probe ids kept).
  - For the plan files: P6.md's never-fail acceptance already ties F3.a to its own Goal 4 since c728380; an explicit
    contrast with P1c's fault F3a is optional.

### plan-FIT-20 (low): P1b reworks scoring scripts P9 deletes, and both phases count the same 146 lines

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters refuted the rewrite claims: close-scoring-decide.py and score-update.sh keep callers until
  P4 and P9, and lifecycle-baseline-import.sh is already deleted whole. What stands is that row 15 should say the
  script goes whole and that P1b and P9 count the same 146 lines.
- **Edit**: P1b.md, cluster W12, commit d22c669: row 15 deletes lifecycle-baseline-import.sh whole with its allow rule
  (settings.json:40) and its one test case (P1b.md:770, unchanged since), and the net-code estimate names the file
  (P1b.md:1105, later edited by 64bec4f).
  - For the plan files: P9.md's goal 3, D17 bullet, row 10 and net-code cap count the three scripts P1b leaves (still to
    apply), with related P4.md (optional) and sync-list records.

### plan-FIT-21 (low): P1c would build a second driver set

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that P1b ships the ten compliant drivers for P1c to extend while P1c's X1 and
  row 1 had it add a new scenario library. Both partly refuted the finding's named list of missing scenarios.
- **Edit**: P1c.md, cluster V1 (merged with format-FH-3), commit d22c669: Interfaces names P1b's ten drivers ("you
  extend them, never a second set"), X1 imports P1b's runner and drivers and extends them, row 1 reads "Extend the
  drivers P1b committed; do not build a second set", and Technical choices and Rollback step 1 follow (P1c.md:49-50,
  :249-251, :535). These words are unchanged since; other parts of the Interfaces bullet changed later (owner-R9).

### plan-FIT-22 (low): PLAN-v2 and later prompts still credit P3; the README index is incomplete

- **Status**: STANDS (refuter A: STANDS-CORRECTED; refuter B: STANDS-CORRECTED).
- **Reason**: Both refuters confirmed that PLAN-v2, P4, P5 and P6 still named P3 as the builder of the
  declaring-dispatch reader and the remover of the G2 escalation stores, which P1b and P1c deliver, and that
  README.md's index lacked audit/, inventory/ and reviews/. Both refuted the sub-claims that README.md misses prompts
  P1b and P1c (the prompts/ row covers them) and that TC-21 carries the stale text.
- **Edit**: none in P1b.md, P1c.md or inventory/ (plan-files-only).
  - For the plan files: PLAN-v2.md's lines are already reworded (c728380, fa5659d, b335a0e, f65290d) and P4.md's and
    P5.md's applied or overridden in place; P6.md:66-68 and README.md's PLAN-v2 row and new inventory/, audit/ and
    reviews/ rows are still to apply.

## For the plan files

The findings' parts for other plan files, and the records the later fix logs and verification reports wrote for them,
are listed here by target file with their exact texts and states. The review session's scope was P1b.md, P1c.md and
inventory/, so it applied none of them; the Summary gives the counts. Source labels name the review session's working
records, which are not committed: "apply log C3" (a wave-1 or wave-2 cluster's apply log), "fix log r15-P1c-FR15-1" (a
fix log), "round r9 report faithful-rules-P1b" (a verification report), the round-N P1b records and patch notes, the
round-16 adjudication, the c33ca28 and d22c669 plan-file records and the plan-files-only record (consolidations of those
records), and item ids such as DP-6 or "plan-sync Fix 35" from them.

### PLAN-v2.md and reviews/P1b-plan-sync.md

Every "For the plan files" item whose target is `harness-repair-plan/PLAN-v2.md` or
`harness-repair-plan/reviews/P1b-plan-sync.md` (the sync file), re-anchored at HEAD ef34dbc. Nothing here is applied.

#### Base and conventions

- HEAD ef34dbc, working tree clean. PLAN-v2.md: 1353 lines, md5 b0199e34d7da409dd784164571df7501, last changed in
  bb56fe5. The sync file: 1646 lines, md5 67e0abff4f8331796d339838812cab34, unchanged since c1bdc15.
- Sources: the two plan-file records as of c33ca28 (one per file), and every record written since: the round-12 to
  round-18 P1b apply records, the round-12 to round-16 inventory patch notes and their collected records (round 15's
  included), the round-18 second-pass fix notes, and the fix logs written after c33ca28.
- Since c33ca28 the other session changed PLAN-v2.md in 7beb706, e428c5b and bb56fe5, each keeping the line count
  (lines 44, 180, 357, 385, 423, 474, 478, 493, 536, 539, 566, 576, 604, 812-813, 1077, 1176 and 1217). Line numbers
  below are those at ef34dbc; for PLAN-v2.md and the sync file they equal the c33ca28 numbers.
- "part of line": old is a substring of one line. "whole lines": old is complete lines without the final line break;
  a deletion removes them with their line breaks. Table rows, and the one-line paragraphs and bullets of PLAN-v2
  sections 0-13, stay one line.
- States: pending; already applied (commit named); superseded (by what); not carried (why). Grades are the source
  log's: necessary or optional.
- Owner quotes: the old and new texts copy the owner's words verbatim from the committed lines they come from: D25's
  sentence from DECISIONS.md:70 (52 characters; the plan files quote it whole or without its first 11 characters, and
  the sync file's S3, S25 and S28 olds break it where the file does), the reviewing session's 23 characters after the
  last double quote of sync :39 (S3 keeps them) and the owner's DT4 words quoted at PLAN-v2.md:1348 (9 characters). Each
  was copied from that line at 382d857.
- Checks (read only, at ef34dbc): every pending old text occurs exactly once in its file, and exactly once at its turn
  when that file's pending items are applied in memory in the order listed; each new text then occurs exactly once.
  PLAN-v2.md goes from 1353 to 1338 lines and still ends with "- **Caps.** See the note under section 5." and one line
  break; the sync file goes from 1646 to 1722 lines. Every quote given for an applied or superseded item occurs at the
  line given.
- The figure at PLAN-v2.md:1176 and sync :419 is the inventory as committed at 37a259a: inventory/README.md:17-24
  there reads 121 rows, several producers 43, several deciding consumers 56, written never read 29, read never
  written 24. inventory/ is unchanged from 37a259a to ef34dbc. The round-16 inventory patches were not applied (owner
  ruling), so their figures do not count.

#### Counts

| File | Items | Pending | Applied since c33ca28 | Superseded | Not carried | Applied before c33ca28 | MOOT before c33ca28 |
|---|---|---|---|---|---|---|---|
| PLAN-v2.md | 85 | 16 (3 optional) | 7 (all e428c5b) | 2 | 2 | 56 | 2 |
| reviews/P1b-plan-sync.md | 57 | 14 (1 optional, and 1 optional entry inside S37) | 0 | 37 (MOOT) | 6 | 0 | 0 |

Superseded figure records are folded into PV-14 and S16 and not counted (listed under "Conflicts settled").

#### PLAN-v2.md: pending items (apply in this order)

**PV-1.** `PLAN-v2.md`:135, part of line (section 5 table, the P2 row; stays one line).
- State: pending; necessary.
- Source: DP-6; findings owner-R2, plan-FIT-02 (apply log C3, same fix in apply log D6). Basis at ef34dbc: P1b.md:705
  (correction 7) "P1b arms G2 (E4); P2 arms G1 and G3"; PLAN-v2.md:104 agrees.

old:
~~~
D6 landing route; arm G1-G3 | 3 |
~~~
new:
~~~
D6 landing route; arm G1 and G3 | 3 |
~~~

**PV-2.** `PLAN-v2.md`:353, whole line (the P2 heading).
- State: pending; necessary.
- Source: DP-10; owner-R2, plan-FIT-02 (apply log C3). Same basis as PV-1.

old:
~~~
## P2 Run in any repo; overnight starts and ends; unattended overnight (D20); D6 landing route; arm G1-G3
~~~
new:
~~~
## P2 Run in any repo; overnight starts and ends; unattended overnight (D20); D6 landing route; arm G1 and G3
~~~

**PV-3.** `PLAN-v2.md`:368, whole line (P2 goals; a one-line bullet).
- State: pending; necessary.
- Source: DP-12; owner-R2, plan-FIT-02 (apply log C3, apply log D6). Agrees with :181 (f732f26) and :357, which 7beb706,
  e428c5b and bb56fe5 edited without touching the arming sentence PV-3 relies on.

old:
~~~
- The last commit arms G1-G3.
~~~
new:
~~~
- The last commit arms G1 and G3 (P1b arms G2 under its E4, or P1c under X3 if P1b could not) and deletes the consumer-side copies P1b's PR keeps for them.
~~~

**PV-5.** `PLAN-v2.md`:474, part of line (P4 "After P1b and P1c"; one-line paragraph).
- State: pending; necessary.
- Source: DP-14, narrowed; owner-R1 (apply log C2). P1b.md:281 (E3) deletes both tables "with their prose copies" and
  acceptance 7 (P1b.md:906-908) checks them gone. 7beb706 and e428c5b rewrote other clauses of :474, not this one.
  DP-14's parenthetical on the routing loops was MOOT at c33ca28 and stays MOOT.

old:
~~~
both routing tables and their "no code table" claims
~~~
new:
~~~
both routing tables, their prose copies and their "no code table" claims
~~~

**PV-9.** `PLAN-v2.md`:704, part of line (P7 not-doing list).
- State: pending; optional.
- Source: DP-22 (optional in its log); owner-R2, plan-FIT-02 (apply log C3).

old:
~~~
G1-G3 arm in P2, the command gate in P5.
~~~
new:
~~~
G2 arms in P1b, G1 and G3 in P2, the command gate in P5.
~~~

**PV-10.** `PLAN-v2.md`:784, part of line (P9 "After P1b and P1c"; one-line paragraph).
- State: pending; necessary.
- Source: fix log r1-P1b-spec, plan-file item 1 (round-1 faithful-P1b F-6). Basis at ef34dbc: P1b.md:636-638 (E14), "a
  call of the one writer naming such a file counting as such a write".

old:
~~~
(P1b row 8, E14: the explicit --spec, else the session's last Write or Edit to docs/dev/specs/*.md)
~~~
new:
~~~
(P1b row 8, E14: the explicit --spec, else the session's last Write or Edit to docs/dev/specs/*.md, a call of the spec monolith's one writer naming such a file counting as such a write)
~~~

**PV-11.** `PLAN-v2.md`:800, part of line (P9 table, spec_path row; stays one line).
- State: pending; necessary.
- Source: fix log r1-P1b-spec, plan-file item 2. Same clause as PV-10.

old:
~~~
taken from the transcript's last Write/Edit to docs/dev/specs/*.md.
~~~
new:
~~~
taken from the transcript's last Write/Edit to docs/dev/specs/*.md (or call of the spec monolith's one writer naming such a file, P1b E14).
~~~

**PV-13.** `PLAN-v2.md`:1092, part of line (section 9, TC-26 row).
- State: pending; necessary.
- Source: round-9 P1b report (round r9 report faithful-rules-P1b, plan-file item 2). P1b.md:710 (correction 8) cites
  prompt-workflow.py:1425, the "[/do] task-id minted" print; :1092 still cites :1427.

old:
~~~
prompt-workflow.py:1427
~~~
new:
~~~
prompt-workflow.py:1425
~~~

**PV-21.** `PLAN-v2.md`:1158, whole line (section 11 bullet; stays one line).
- State: pending; necessary. New since c33ca28.
- Source: round-17 spec-coverage fix (fix log r17-P1b-spec-coverage record 1; carried unchanged by the round-17 P1b
  apply records, section 2.1, and its speclanding note). Basis at ef34dbc: P1b.md:715-717 (correction 9) "Row 8 moves
  its rule to G2 at the spec subagent's stop and leaves stop-spec-coverage-enforce.py an exit-0 stub" (3ca4af4).

old:
~~~
- No gates for graphify dispatches, and no new Stop gate for /spec; the existing coverage phase (stop-spec-coverage-enforce.py, bounded by stop_hook_active, outside D4) stays unchanged.
~~~
new:
~~~
- No gates for graphify dispatches, and no new Stop gate for /spec; the existing coverage phase (stop-spec-coverage-enforce.py, bounded by stop_hook_active, outside D4) blocks nothing after P1b, which moves its rule to G2 at the spec subagent's stop and leaves the hook an exit-0 stub (P1b row 8).
~~~

**PV-14.** `PLAN-v2.md`:1176, part of line (section 11 table, map figures).
- State: pending; necessary. Re-anchored and superseding.
- Source: round-15 inventory record PF-1 (the round-15 patch notes' P1b records; fix log r15inv-apply; carried by the
  round-18 P1b apply records, section 5), with the 37a259a figure. The c33ca28 text of PV-14 ("38 / 37 / 27 / 20 of
  121" -> "38 / 34 / 28 / 22 of 121") is gone: e428c5b wrote round 13's "43 / 52 / 26 / 24 of 120". Grade: the round-14
  notes call the figure records required; the round-18 apply records leave the grade to the plan-file owner.

old:
~~~
43 / 52 / 26 / 24 of 120
~~~
new:
~~~
43 / 56 / 29 / 24 of 121
~~~

**PV-15.** `PLAN-v2.md`:1192, part of line (section 11 table, V7a row).
- State: pending; optional.
- Source: DP-32 (optional in its log); plan-FIT-12 (apply log W10 item 5). :87 and :536 already have P1b E3 ship the
  deny.

old:
~~~
denied to every non-owner caller after P5 (D8,
~~~
new:
~~~
denied to every non-owner caller after P1b (the main agent after P5 where P1b's PR leaves it to P5-a) (D8,
~~~

**PV-16.** `PLAN-v2.md`:1250, part of line (section 13 found-items table, P2 row).
- State: pending; necessary.
- Source: DP-35; feasible-H3, facts-F9 (apply log C8). Basis at ef34dbc: P1b.md:762 (row 7) respells each kept resolver
  call with the harness-home path, "since a product repository has no scripts/".

old:
~~~
scripts/resolve-dev-artifact-chain.py,
~~~
new:
~~~
scripts/resolve-dev-artifact-chain.py (P1b row 7 respells the calls it keeps),
~~~

**PV-17.** `PLAN-v2.md`:1260, part of line (section 13 found-items table, P6 row).
- State: pending; optional.
- Source: fix log r10-P1b-qa-arming (round 10; optional, P6's lane). P1b.md:756 (row 1) still deletes /close's QA
  re-arming (close.md:244-274). Carried note: the row's premise (the CLI registers no FIRST ACTION Read of a missing
  file) is unverified; P6 should measure it before relying on either text.

old:
~~~
/commit's commit-QA and changelog-analyst prompts and the /do-path inspectors have no resolvable FIRST ACTION sentinel
~~~
new:
~~~
/commit's commit-QA and changelog-analyst prompts, the /do-path inspectors and, after P1b deletes /close's QA arming (its only writer there), the /do-path close QA have no resolvable FIRST ACTION sentinel
~~~

**PV-18.** `PLAN-v2.md`:1318-1328, whole lines (section 15, the takeover list).
- State: pending; necessary.
- Source: the plan-files-only record's Fix 41; format-FH-11. It restates P1b.md:657-670 ("Corrections to PLAN-v2", item
  2); each phase section names its share under "After P1b and P1c" (:357, :423, :474, :536, :637, :784; P10 at :844 and
  :858).
- Coupled edit outside these files: PV-18 moves the P1c bullet from :1329 to :1321, so P1b.md:655 (correction 1,
  "the caps again at :1199, :1311 and :1329") then needs ":1321". Records under reviews/ cite PLAN-v2 lines at their
  own commits and are not changed.

old:
~~~
- P1b takes over these rows (prompts/P1b.md, "Corrections to PLAN-v2", item 2): from P2, the canonical aggregate's
  producer, closeout's harness-report writer, the cycle contract's single writer, path, no seed and obligation-sourced
  schema (TC-35 as corrected), the aggregate-pending and continuation-sentinel writers; from P3, the declaring-dispatch
  reader, the escalation stores and the arbitration path, journal-view, the completion report leaving the required
  chain, the TERMINAL_VOCABULARY imports, BA's ba-qa-report permission; from P4, the class-b/c re-checks, both routing
  tables, the close-force readers and the D24 table for L17, L18, L22, L23, L28, L31, L32, L40, L41, L42 and L53; from
  P5, G4's re-validation, the todo-file writers, the do.status deciders, merge.md's validate-and-unlink and the write
  permission derived from dispatch records (TC-20 as corrected; P1b's E3); from P9, the spec_path producer, doc-sync
  update-only (if P1b's E9 deletes creation), the one /do consent reader, the roster from agents/*.md stems and the
  one-writer proofs for L01, L24, L42, L44 and L51; from P10, the artifact-level goal of corrections.md 2.61, replaced
  by the CI check (P10 keeps file-level D17).
~~~
new:
~~~
- P1b takes over per-artifact rows of P2, P3, P4, P5, P9 and P10 (prompts/P1b.md, "Corrections to PLAN-v2", item 2);
  each phase's section above names its share under "After P1b and P1c (2026-10-24)" (P10: its goals and its dead-code
  row).
~~~

**PV-19.** `PLAN-v2.md`:1347-1349, whole lines (section 15, the CLAUDE.md bullet), delete.
- State: pending; necessary.
- Source: the plan-files-only record's Fix 42; format-FH-11. P9's CLAUDE.md row (:813) carries the #5 rewrite and the
  DT4 conflict.

old:
~~~
- **CLAUDE.md.** Hook Discipline #5 ("Ordinary /dev recovery has an honest terminal branch", master CLAUDE.md:98 at
  d625284) conflicts with the owner's "诚实终态永远不允许" (DT4) and with D25's requirement (3). P9 rewrites it under D20 and
  D23 (the CLAUDE.md row of P9). P1b and P1c do not edit CLAUDE.md.
~~~
new: (empty: delete these whole lines with their line breaks)

**PV-20.** `PLAN-v2.md`:1350-1353, whole lines (section 15, the last bullet; the last lines of the file), delete.
- State: pending; necessary.
- Source: the plan-files-only record's Fix 43, re-anchored at c33ca28 on the text f65290d and b335a0e wrote (unchanged
  since); format-FH-11; INV2-5 folded (MOOT, below). The bullet restates P1b's own corrections 3-8 (P1b.md:671-714).

old:
~~~
- **Corrections P1b records in its PR:** the audit ledger's counts are superseded by the d625284 map (inventory/README.md;
  L04's MC label withdrawn); the hook-state path rule (wherever its correction 4 finds hook state written under harness_state_dir()
  and read at a fixed /tmp path, or the reverse); the privilege guard's quoted `-F` read; G4 left as an exit-0 stub for
  P5; P1b arms G2 (E4), and P2 arms G1 and G3 with P1b's E4 list as its input, its arming commit deleting the consumer-side copies P1b kept for them; E8 removes `pending` from the do-report's do.status, so `/do <task-id>` (TC-18, if kept) finds the unfinished task from a hook-written record with no completed do-report, and P5-d's enum has no `pending`.
~~~
new: (empty: delete these whole lines with their line breaks)

#### PLAN-v2.md: applied, superseded or not carried since c33ca28

Applied in other words means the target now carries the item's sense in the other session's wording; that wording is
kept (a later change over an earlier record). Each quote occurs once, at the line given.

**PV-4.** `PLAN-v2.md`:385, part of line (P2 table, hooks/stop-overnight-timelock.py row).
- State: already applied, other words, e428c5b.
- Source: fix log r15-P1c-FR15-1 record 7 (superseding fix log r14-P1c-RA14-1 record 5). :385 now ends with a sentence
  that keeps the wake check; quote: `Keep P1c row 17's wake check: a Stop after end_time (once the closeout`. PV-4's old
  text still occurs once; do not apply it, or the row states the check twice.

old:
~~~
Thin the hook to a caller of lib/overnight (window_open, closeout_gaps).
~~~
new:
~~~
Thin the hook to a caller of lib/overnight (window_open, closeout_gaps), keeping P1c's wake check after closeout_gaps and on the /stop release (P1c X8).
~~~

**PV-6.** `PLAN-v2.md`:536, part of line (P5 "After P1b and P1c").
- State: already applied, e428c5b (verbatim, with a clause added).
- Source: fix log r15-P1c-FR15-2 record 2. Quote: `only after a recurring CronCreate of the wake's text in the span`,
  followed by ", the call whose id the wake's deletions and the time-lock name".

old:
~~~
P1c row 17 made /dev-overnight's wake step complete only after a CronCreate or ScheduleWakeup call in the span
~~~
new:
~~~
P1c row 17 made /dev-overnight's wake step complete only after a recurring CronCreate of the wake's text in the span
~~~

**PV-7.** `PLAN-v2.md`:563, part of line (P5 table, stop-command-gate row, step 4).
- State: superseded by e428c5b at :536.
- Source: fix log r15-P1c-FR15-1 record 8. :536 now states the rule for P5's gate; quote: `the gate, which takes over
  the time-lock's clause, keeps X8's wake check` (one line in the file). The row at :563 is unchanged and its old text
  still occurs once, so PV-7 stays applicable as written if the row should repeat :536 (optional now).

old:
~~~
4. Time-lock clause: lib/overnight.window_open(payload) -> block whatever the span, with "overnight window open until <end_time>; continue the remaining pipelines" (TC-12).
~~~
new:
~~~
4. Time-lock clause: lib/overnight.window_open(payload) -> block whatever the span, with "overnight window open until <end_time>; continue the remaining pipelines" (TC-12); once the window is closed, P1c's undeleted wake -> block naming its id whatever the span but /dev-overnight's, whose predicate checks it after closeout_gaps (P1c X8).
~~~

**PV-8.** `PLAN-v2.md`:563, part of line (same row, the dev-overnight predicate).
- State: superseded by e428c5b at :536.
- Source: fix log r14-P1c-RA14-1 record 6. Same as PV-7; old text still occurs once (optional now).

old:
~~~
dev-overnight: time-lock released, every session_families member chain_pass at the working root, and closeout_gaps empty.
~~~
new:
~~~
dev-overnight: time-lock released, every session_families member chain_pass at the working root, closeout_gaps empty, and then P1c's wake deleted (P1c X8).
~~~

**PV-12.** `PLAN-v2.md`:813, part of line (P9 table, CLAUDE.md row).
- State: already applied, other words, e428c5b.
- Source: fix log r13-P1c record 3 (FR13-2). Quote: `any prompt that starts with /restart (P1c X8 and its hand-off to
  P9` (one line in the file). The old text is gone.

old:
~~~
Lesson 16 (:41) and :62 name the SendMessage exception as P1c's merged hook has it: the typed /restart, or the /dev-overnight session's own wake inside its span, with the same fixed message and id rule (P1c X8, D20);
~~~
new:
~~~
Lesson 16 (:41) and :62 name the SendMessage exception as P1c's merged hook has it: the typed /restart, or the /dev-overnight session's own wake inside its span, with the same fixed message and id rule, and, where P1c's PR records under X8 that the hook cannot tell a scheduled prompt from a typed one, any prompt that starts with /restart (P1c X8, D20);
~~~

**PV-22.** `PLAN-v2.md`:423, part of line (P3 "Delivered before P3").
- State: already applied, other words, e428c5b. New since c33ca28.
- Source: round-13 E5 lane (fix log r13-P1b-E5 record 3; grade not stated). Quote: `the gitignore preflight's exemption
  of the commit-landing profile, read from the dispatch's own obligation` (one line in the file). Old gone.

old:
~~~
the resolver's fan-out optional-parent read (P1b row 7, P1c row 12). The disposition is
~~~
new:
~~~
the resolver's fan-out optional-parent read (P1b row 7, P1c row 12); the gitignore preflight's exemption of a `commit-landing` dispatch for its own report's task, keyed on its obligation in place of the commit grant (P1b row 11; the S7 row below adds the other producer profiles). The disposition is
~~~

**PV-23.** `PLAN-v2.md`:474, part of line (P4 "After P1b and P1c").
- State: already applied, other words, e428c5b. New since c33ca28.
- Source: round-13 row-10 lane (fix log r13-P1b-row10, PLAN-v2.md record 1; grade not stated; the round-19 P1c row-10
  log says these records stand). Quote: `sent back to that round's own QA dispatch through that round's report`. Old
  gone.

old:
~~~
along the do-report's route (P1b row 10; P1c's F8 faults replay it),
~~~
new:
~~~
along the do-report's route (P1b row 10; P1c's F8 faults replay it), or, for one no dispatch of the task wrote, to the close-QA or commit-QA round that named it, through that round's own report (P1b E3 and row 10, no default role; P1b acceptance 7 replays it),
~~~

**PV-24.** `PLAN-v2.md`:478, part of line (P4 goals, close-QA findings).
- State: already applied, other words, e428c5b. New since c33ca28.
- Source: the same log, record 2 (it also answers the orchestrator's top-up note for :478). Quote: `goes back to that
  close-QA round's own QA dispatch through that round's report, with no default role (P1b E3)` (one line in the
  file). "dev when none is recorded" no longer occurs in PLAN-v2.md.

old:
~~~
(P1b row 10, verified on the base), dev when none is recorded [INFERRED; decided by the P4 sandbox replay named in the close.md row].
~~~
new:
~~~
(P1b row 10, verified on the base); when none is recorded, along P1b row 10's route for the file (a /do task's do-report route, else the close-QA round's own dispatch through E3's reader; no default role, D21) [INFERRED; decided by the P4 sandbox replay named in the close.md row].
~~~

**PV-25.** `PLAN-v2.md`:493, part of line (P4 table, close.md row).
- State: already applied, other words, e428c5b. New since c33ca28.
- Source: the same log, record 3 (the top-up note for :493). Quote: `with no default role (P1b E3) [INFERRED; decide by
  a P4 sandbox replay` (one line in the file). Old gone.

old:
~~~
records as the file's writer, dev when none is recorded [INFERRED; decide by a P4 sandbox replay of a close-QA finding on a file that producer attributes and on one it does not]
~~~
new:
~~~
records as the file's writer, or, when none is recorded, follows P1b row 10's route for the file (no default role, D21) [INFERRED; decide by a P4 sandbox replay of a close-QA finding on a file that producer attributes and on one it does not]
~~~

**PV-26.** `PLAN-v2.md`:174, part of line (section 6, wave 2c).
- State: not carried. New since c33ca28.
- Source: round-20 P1c cross-check C20-1 (round r20 report P1c-cross, "only if this fix is applied"). Its condition
  never held: C20-1 is not needed once P1b carries row 6's late-repair fix (round-15 P1b apply records, section 3.2; fix
  log r15-P1b-apply, line 237). :174 keeps "21 faults".

old:
~~~
shipped and armed settings; 21 faults; the no-dead-end
~~~
new:
~~~
shipped and armed settings; 22 faults; the no-dead-end
~~~

**R5FR-1 alternative.** Not carried (as at c33ca28): the round-5 P1c report's plan-file alternative (move P10's size
ratchet under tests/, with edits to PLAN-v2.md:870 and :1144) applied only if the fixer rejected its option (a); the
fixer took (a) (fix log r5-P1c-coverage), and the report gave no exact text.

#### PLAN-v2.md: applied or MOOT before c33ca28 (re-checked at ef34dbc)

The c33ca28 record lists 56 recorded fixes and log items as already applied, with a quote each. Every quote still
occurs at the line it gives; the lines e428c5b, 7beb706 or bb56fe5 edited since (:357, :474, :536) still hold their
quotes. No text is left to apply for any of them.

| Item | Line | Commit (as the c33ca28 record gives) | Finding |
|---|---|---|---|
| the plan-files-only record's Fix 10 | 1334-1335 | fa5659d, f65290d | plan-FIT-10 |
| the plan-files-only record's Fix 12 | 357 | b335a0e | plan-FIT-16 |
| the plan-files-only record's Fixes 13-21 | 47, 102, 183, 485, 547, 560 (two), 567, 606 | fa5659d | plan-FIT-22 |
| the plan-files-only record's Fixes 22, 23 | 1086 | b335a0e | plan-FIT-22 |
| the plan-files-only record's Fixes 24, 25 | 1151, 1166 | fa5659d | plan-FIT-22 |
| the plan-files-only record's Fix 26 | 1258 | f65290d | plan-FIT-22 |
| DP-1, DP-13, DP-24, DP-25, DP-26, DP-29 | 55, 450, 952, 957, 1084, 1152 | f65290d | facts-F4, plan-FIT-13 |
| DP-18, DP-19, DP-20 | 574, 576, 591 | b335a0e | facts-F4, plan-FIT-13 |
| DP-2 (optional) | 87 | fa5659d | plan-FIT-12 |
| DP-27, DP-28 | 1086 | b335a0e | plan-FIT-12 |
| DP-3, DP-11 | 104, 357 | b335a0e | owner-R2, plan-FIT-02 |
| fix log r5-P1c-small (optional) | 104 | b335a0e | R5 X3 wording |
| DP-8 | 174 | f65290d | owner-R2, plan-FIT-02 |
| DP-9 | 181 | f732f26 | owner-R2, plan-FIT-02 |
| DP-4, DP-5, DP-33, DP-36 | 106, 134, 1199, 1329 | f65290d | feasible-H7 |
| DP-7 | 174 | f65290d | owner-R4 |
| DP-30, DP-37 | 1175, 1335 | f65290d | owner-R4, plan-FIT-10 |
| DP-15 | 474 | b335a0e | owner-R1 |
| DP-17 | 536 | b335a0e | plan-FIT-05 |
| DP-21 | 637 | f65290d | plan-FIT-05 |
| DP-23 (optional) | 808 | f65290d | plan-FIT-20 |
| DP-34 | 1250 | f65290d | feasible-H3, facts-F9 |
| Log item (sync V-5, V-8) | 142, 144, 193 | earlier recorders | format-FH-5, plan-FIT-07 |
| Log item (sync V-24, V-13) | 844, 483 | earlier recorders | plan-FIT-06 |
| Log item | 432 | earlier recorders | plan-FIT-22 |
| Log item (sync V-1, V-31) | 96, 1303 | earlier recorders | format-FH-6, owner-R5 |
| Log item (D1, V-31) | 1336-1337 | earlier recorders | feasible-H5, plan-FIT-04, facts-F13 |
| Log item (sync V-29) | 1175 | earlier recorders | plan-FIT-10 |
| Log item (sync V-15, V-17) | 536, 637 | earlier recorders | plan-FIT-12 |

That is 45 recorded fixes (16 the plan-files-only record fixes, 28 DP items, the round-5 P1c note) and 11 log items.

MOOT before c33ca28, still MOOT:
- **DP-16** (:496, the step7-spec-update.py row; owner-R18). Its old text still occurs at :496, but P1b keeps /commit
  Step 8's selection and the script (P1b.md:635, "scripts/step7-spec-update.py), stays"; PLAN-v2.md:474 "Step 8's
  selection, which stays"); fix log r1-P1b-spec dropped W9's plan-file items.
- **INV2-5** (round-2 inventory report; :1350 "in four places"). f65290d removed the count (:1351 now has the rule
  with no number); PV-20 deletes the bullet anyway.

#### reviews/P1b-plan-sync.md: pending items (apply in this order)

The sync file's rule (from the c33ca28 record): its list was applied in c728380, so an entry whose target now carries
the correction is MOOT; an item stays pending when its target still lacks the correction or when it corrects the sync
file's own text. Fences below are five tildes because S37 holds `~~~` lines.

**S1.** `reviews/P1b-plan-sync.md`:5, whole line (a new paragraph after "Status").
- State: pending; optional.
- Source: plan-sync Fix 35 (conflict C-5 of the earlier sync record; used instead of the plan-files-only record's
  bookkeeping line, N1). Target: none. P9.md still lacks P9-11 to P9-14 at ef34dbc (S37). Without the optional P9-14,
  write "P9-11 to P9-13".

old:
~~~~~
make the rest of the plan agree with prompts/P1b.md and prompts/P1c.md. New file; no other file was touched.
~~~~~
new:
~~~~~
make the rest of the plan agree with prompts/P1b.md and prompts/P1c.md. New file; no other file was touched.

Applied to the plan files in c728380 (57 edits as written, 44 adapted to the batch; the per-edit record is
reviews/D20-D25-residuals-and-sync-record.md, Part 2); do not apply those again. P9-11 to P9-14 were added after
c728380 and are not applied yet: apply only them, to prompts/P9.md, each where P9.md does not already carry its new
text.
~~~~~

**S2.** `reviews/P1b-plan-sync.md`:31-32, whole lines ("How to apply", Decision id).
- State: pending; necessary.
- Source: format-FH-6, owner-R5 (apply log V7 item 1 = apply log W1 item 1; plan-sync Fix 1, re-anchored). Target: none.
  DECISIONS.md is unchanged since c33ca28, so ":68-87" holds.

old:
~~~~~
- **Decision id.** This file records the owner's rule of 2026-10-24 as **D25** (DECISIONS.md edit D-1).
  prompts/P1b.md and P1c.md call it "the owner's rule of 2026-10-24"; both names mean the same ruling.
~~~~~
new:
~~~~~
- **Decision id.** The owner's rule of 2026-10-24 is **D25** (DECISIONS.md:68-87); prompts/P1b.md and P1c.md call
  it D25.
~~~~~

**S3.** `reviews/P1b-plan-sync.md`:36-39, whole lines ("Sources", first bullet).
- State: pending; necessary.
- Source: format-FH-6, owner-R5 (apply log V7 item 2 = apply log W1 item 2; plan-sync Fix 2, rewrapped). Target: none.
  D25's quote is alone on its line.

old:
~~~~~
- The owner, 2026-10-24, relayed verbatim in the request that commissioned P1b and P1c: "永远不能失败！每一次开发一定不会在
  流程上出现任何错误！出现了错误也可以立刻被修复！" ("It must never fail! No development run may ever hit an error in the process!
  And if an error does occur, it can be fixed at once!"), ranked with "one producer, one consumer". The same request
  asks for a CI replay suite on the runtime trace with parts (1)-(4), and: "之后每个阶段合并的条件之一是这套测试保持全绿，
~~~~~
new:
~~~~~
- The owner, 2026-10-24, to the reviewing session (recorded verbatim in DECISIONS.md D25):
  "还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"
  ("One more thing I care about! It must never fail! No development run may ever hit an error in the process! And if
  an error does occur it can be repaired immediately!"). The reviewing session's reply, which the owner forwarded (not
  his words), asks for a CI replay suite on the runtime trace with parts (1)-(4), and:
  "之后每个阶段合并的条件之一是这套测试保持全绿，
~~~~~

**S4.** `reviews/P1b-plan-sync.md`:57, whole line.
- State: pending; necessary.
- Source: the plan-files-only record's Fix 44 (format-FH-11). Target: none; DECISIONS.md:86-87 holds the sentence.

old:
~~~~~
COVERAGE.md K-7, DECISIONS.md D-1 (last sentence), HANDOVER.md H-10.
~~~~~
new:
~~~~~
COVERAGE.md K-7, HANDOVER.md H-10; DECISIONS.md D25 already states it (:86-87).
~~~~~

**S13.** `reviews/P1b-plan-sync.md`:302, part of line (V-19, the P9 section).
- State: pending; necessary.
- Source: fix log r1-P1b-spec, plan-file item 1. Target: PLAN-v2.md:784 still lacks the clause (PV-10).

old:
~~~~~
(P1b row 8, E14: the explicit --spec, else the session's last Write or Edit to docs/dev/specs/*.md)
~~~~~
new:
~~~~~
(P1b row 8, E14: the explicit --spec, else the session's last Write or Edit to docs/dev/specs/*.md, a call of the spec monolith's one writer naming such a file counting as such a write)
~~~~~

**S16.** `reviews/P1b-plan-sync.md`:419, part of line (V-29, the map figures).
- State: pending; necessary. Re-anchored and superseding.
- Source: round-15 inventory record PF-2 (the round-15 patch notes' P1b records; fix log r15inv-apply; carried by the
  round-18 P1b apply records, section 5), with the 37a259a figure; it supersedes the c33ca28 text of S16 (new "38 / 34 /
  28 / 22 of 121"). Target: PLAN-v2.md:1176 (PV-14). Grade as PV-14.

old:
~~~~~
35 / 37 / 29 / 18 of 122
~~~~~
new:
~~~~~
43 / 56 / 29 / 24 of 121
~~~~~

**S25.** `reviews/P1b-plan-sync.md`:913-920, whole lines (P2-4 new block; only :913-914 change).
- State: pending; necessary.
- Source: format-FH-6, owner-R5 (apply log V7 item 8 = apply log W1 item 8; plan-sync Fix 21, rewrapped). Target:
  P2.md:92 still quotes the cut sentence at ef34dbc.

old:
~~~~~
a CI check that derives the artifact graph at test time. P1c turned the owner's rule of 2026-10-24 (D25: "永远不能失败！
每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！") into the CI replay suite under tests/replay/. For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact: the check sits at that artifact's
  producer stop, at dispatch (G1) or at collection (G3), and the artifact keeps one producer and one deciding consumer.
  A row that would add a second producer, a second deciding consumer or a consumer-side re-check is dropped and listed
  under "Corrections to PLAN-v2". P1b's CI check stays green.
- Already done (verify each on your base and do not redo it; where a P1b experiment took the other outcome, follow
  P1b's PR): the canonical aggregate's one producer (P1b E5) and the aggregate-pending writer's removal; closeout's
~~~~~
new:
~~~~~
a CI check that derives the artifact graph at test time. P1c turned the owner's rule of 2026-10-24
(D25: "还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！")
into the CI replay suite under tests/replay/. For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact: the check sits at that artifact's
  producer stop, at dispatch (G1) or at collection (G3), and the artifact keeps one producer and one deciding consumer.
  A row that would add a second producer, a second deciding consumer or a consumer-side re-check is dropped and listed
  under "Corrections to PLAN-v2". P1b's CI check stays green.
- Already done (verify each on your base and do not redo it; where a P1b experiment took the other outcome, follow
  P1b's PR): the canonical aggregate's one producer (P1b E5) and the aggregate-pending writer's removal; closeout's
~~~~~

**S28.** `reviews/P1b-plan-sync.md`:1017-1024, whole lines (P3-5 new block; only :1017-1018 change).
- State: pending; necessary.
- Source: the same (plan-sync Fix 24). Target: P3.md:92 still quotes the cut sentence.

old:
~~~~~
a CI check that derives the artifact graph at test time. P1c turned the owner's rule of 2026-10-24 (D25: "永远不能失败！
每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！") into the CI replay suite under tests/replay/. For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact: the check sits at that artifact's
  producer stop, at dispatch (G1) or at collection (G3), and the artifact keeps one producer and one deciding consumer.
  A row that would add a second producer, a second deciding consumer or a consumer-side re-check is dropped and listed
  under "Corrections to PLAN-v2". P1b's CI check stays green.
- Already done (verify each on your base and do not redo it; where a P1b experiment took the other outcome, follow
  P1b's PR): the declaring-dispatch reader in hooks/lib/obligation.py (P1b E3; your row 1 as corrections.md rewrites it
~~~~~
new:
~~~~~
a CI check that derives the artifact graph at test time. P1c turned the owner's rule of 2026-10-24
(D25: "还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！")
into the CI replay suite under tests/replay/. For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact: the check sits at that artifact's
  producer stop, at dispatch (G1) or at collection (G3), and the artifact keeps one producer and one deciding consumer.
  A row that would add a second producer, a second deciding consumer or a consumer-side re-check is dropped and listed
  under "Corrections to PLAN-v2". P1b's CI check stays green.
- Already done (verify each on your base and do not redo it; where a P1b experiment took the other outcome, follow
  P1b's PR): the declaring-dispatch reader in hooks/lib/obligation.py (P1b E3; your row 1 as corrections.md rewrites it
~~~~~

**S29.** `reviews/P1b-plan-sync.md`:1107-1109, whole lines (P4-4 new block; only :1107 changes).
- State: pending; necessary.
- Source: format-FH-6, owner-R5 (apply log V7 item 9 = apply log W1 item 8; plan-sync Fix 25, rewrapped). Target:
  P4.md:74.

old:
~~~~~
(D25: "永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"). For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact (one producer, one deciding consumer,
  checks only at the producer's stop, G1 and G3); a row that would add a second decider or a consumer-side re-check is
~~~~~
new:
~~~~~
(D25: "还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！").
For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact (one producer, one deciding consumer,
  checks only at the producer's stop, G1 and G3); a row that would add a second decider or a consumer-side re-check is
~~~~~

**S31.** `reviews/P1b-plan-sync.md`:1195-1196, whole lines (P5-4 new block; only :1195 changes).
- State: pending; necessary.
- Source: the same (plan-sync Fix 27). Target: P5.md:89.

old:
~~~~~
(D25: "永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"). For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact: the gate's predicates call the one chain
~~~~~
new:
~~~~~
(D25: "还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！").
For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact: the gate's predicates call the one chain
~~~~~

**S33.** `reviews/P1b-plan-sync.md`:1284-1286, whole lines (P6-4 new block; only :1284 changes).
- State: pending; necessary.
- Source: the same (plan-sync Fix 29). Target: P6.md:83.

old:
~~~~~
(D25: "永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"). For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact (one producer, one deciding consumer,
  checks only at the producer's stop, G1 and G3). P1b's CI check stays green.
~~~~~
new:
~~~~~
(D25: "还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！").
For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact (one producer, one deciding consumer,
  checks only at the producer's stop, G1 and G3). P1b's CI check stays green.
~~~~~

**S35.** `reviews/P1b-plan-sync.md`:1318, whole line (the P9.md file heading).
- State: pending; necessary.
- Source: plan-FIT-20 (apply log W12 item 9, apply log V3 item 1; supersedes plan-sync Fix 31's "20 edits"). 10 entries
  plus S37's four; 13 without the optional P9-14.

old:
~~~~~
## File: prompts/P9.md (10 edits)
~~~~~
new:
~~~~~
## File: prompts/P9.md (14 edits)
~~~~~

**S37.** `reviews/P1b-plan-sync.md`:1459-1460, whole lines (insert P9-11 to P9-14 after P9-10).
- State: pending; necessary (P9-14 optional).
- Source: plan-FIT-20 (apply log W12 item 9 with items 1-8; plan-sync Fix 33, narrowed: five of its nine entries are
  MOOT). Re-checked at ef34dbc: each of the four anchors occurs once in prompts/P9.md, at :212, :385, :699 and :509, as
  at c33ca28 (P9.md changed since only at :459-460 and :465), and P9.md does not yet carry any new text.

old:
~~~~~
    table, the scoring retirement, the E2 change if any) each lie on a fault replay's path.
~~~
~~~~~
new:
~~~~~
    table, the scoring retirement, the E2 change if any) each lie on a fault replay's path.
~~~

#### P9-11. Owner decisions, the D17 bullet (:212-214)

REPLACE. Added after the sync was applied (c728380); the anchor occurs once in prompts/P9.md at c33ca28 and at
c1bdc15. P1b row 15 deletes scripts/lifecycle-baseline-import.sh whole (plan-FIT-20).

~~~anchor
- **D17.** Code no live entry point reaches is deleted only with a reachability proof. This phase deletes the four D9a
  scripts, the two score shell tests and scripts/iterate-failed-pipelines.py (row 7) with that proof; anything else that
  loses its last caller goes to "Now unreferenced" for P10.
~~~
~~~new
- **D17.** Code no live entry point reaches is deleted only with a reachability proof. This phase deletes the three D9a
  scripts P1b left (P1b row 15 deleted lifecycle-baseline-import.sh), the two score shell tests and
  scripts/iterate-failed-pipelines.py (row 7) with that proof; anything else that loses its last caller goes to "Now
  unreferenced" for P10.
~~~

#### P9-12. Corrections to PLAN-v2, item 1 (:384-385)

REPLACE. Added after the sync was applied (c728380); the anchor occurs once in prompts/P9.md at c33ca28 and at
c1bdc15. P1b row 15 deletes scripts/lifecycle-baseline-import.sh whole (plan-FIT-20).

~~~anchor
   the D9a row omits; delete all three with their scripts.
~~~
~~~new
   the D9a row omits; P1b row 15 deleted :40 with that script (verify it is gone); delete the other two with their
   scripts.
~~~

#### P9-13. Net code cap (:699-701)

REPLACE. Added after the sync was applied (c728380); the anchor occurs once in prompts/P9.md at c33ca28 and at
c1bdc15. P1b row 15 deletes scripts/lifecycle-baseline-import.sh whole (plan-FIT-20). 204 + 252 + 431 = 887.

~~~anchor
Net lines in hooks/, scripts/ and schemas/ (tests excluded) must be <= -900 (PLAN-v2.md section 5). The four D9a scripts
are -1,033 lines at f8c18c2, OPTIONS_XML about -50, doc-sync's creation paths and `_maybe_regen_global` more; the spec_path
producer, has_do_consent and the option table pay for themselves. commands/, agents/, CLAUDE.md, README.md and
~~~
~~~new
Net lines in hooks/, scripts/ and schemas/ (tests excluded) must be <= -900 (PLAN-v2.md section 5). The three D9a
scripts P1b left are -887 lines at f8c18c2 (P1b row 15 deleted lifecycle-baseline-import.sh, 146), OPTIONS_XML about
-50, doc-sync's creation paths and `_maybe_regen_global` more; the spec_path producer, has_do_consent and the option
table pay for themselves. commands/, agents/, CLAUDE.md, README.md and
~~~

#### P9-14. Out of scope, first bullet (:509-510; optional)

REPLACE (whole lines, rewrapped so that the P9.md lines stay within 120 characters). Added after the sync was applied
(c728380); the anchor occurs once in prompts/P9.md at c33ca28 and at c1bdc15. P1b row 15 deletes
scripts/lifecycle-baseline-import.sh whole (plan-FIT-20).

~~~anchor
- P10's work: deleting scripts, hooks, schemas and docs that lose their last caller (except the four D9a scripts and
  iterate-failed-pipelines.py named here), the stubs and doctor's STUB-reference check, .gitignore minimisation beyond
~~~
~~~new
- P10's work: deleting scripts, hooks, schemas and docs that lose their last caller (except the three D9a scripts P1b
  left and iterate-failed-pipelines.py named here), the stubs and doctor's STUB-reference check, .gitignore
  minimisation beyond
~~~
~~~~~

**S38.** `reviews/P1b-plan-sync.md`:1613-1621, whole lines (counts table, last rows, and "Anchors not placed").
- State: pending; necessary.
- Source: plan-FIT-20 (apply log W12 item 9, apply log V3 item 1; supersedes plan-sync Fix 34's "20" and "111"). 14 and
  105; 13 and 104 without the optional P9-14 (then also "P9-11 to P9-13").

old:
~~~~~
| prompts/P9.md | 10 |
| prompts/P10.md | 6 |
| prompts/P11.md | 3 |
| total | 101 |

Anchors not placed: none at dac09ec9 (101 of 101 found exactly once, and the edits applied in order to a scratch copy
leave every later anchor unique). Not verified: the P2 and P3 anchors against the refreshed p23 copies, which are not on
the planning branch (see "How to apply"). One anchor changes if corrections.md is applied first: P9-5 (its overlap note
gives the alternative text).
~~~~~
new:
~~~~~
| prompts/P9.md | 14 |
| prompts/P10.md | 6 |
| prompts/P11.md | 3 |
| total | 105 |

Anchors not placed: none at dac09ec9 (101 of 101 found exactly once, and the edits applied in order to a scratch copy
leave every later anchor unique); P9-11 to P9-14 were added after the sync was applied (c728380) and are anchored on
prompts/P9.md at c33ca28 (each anchor also occurs once at c1bdc15). Not verified: the P2 and P3 anchors against the
refreshed p23 copies, which are not on the planning branch (see "How to apply"). One anchor changes if corrections.md
is applied first: P9-5 (its overlap note gives the alternative text).
~~~~~

#### reviews/P1b-plan-sync.md: MOOT and not carried

MOOT (superseded by the target's own text; re-checked at ef34dbc: each quote the c33ca28 record gives still occurs in
its target). No text is applied for these.

| Item | Sync line | Target at ef34dbc | Carried by | Finding |
|---|---|---|---|---|
| S5 | 95 | PLAN-v2.md:134 | f65290d | feasible-H7 |
| S6 | 143 | PLAN-v2.md:174; CC4 at :1175, :1334-1335 | f65290d | owner-R4 |
| S7 | 143 | PLAN-v2.md:174 | f65290d | owner-R2, plan-FIT-02 |
| S8 | 180 | PLAN-v2.md:357 (edited since by 7beb706, e428c5b, bb56fe5; the quoted sentences stay) | f65290d | owner-R2, plan-FIT-02 |
| S9, S10 | 230 | PLAN-v2.md:474 | f65290d | owner-R1 |
| S11 | 255 | PLAN-v2.md:536 | f65290d | plan-FIT-05 |
| S12 | 278 | PLAN-v2.md:637 | f65290d | plan-FIT-05 |
| S14 | 406 | PLAN-v2.md:1199 | f65290d | feasible-H7 |
| S15 | 418 | PLAN-v2.md:1175 | f65290d | plan-FIT-10, owner-R4 |
| S17 | 468 | PLAN-v2.md:1329 | f65290d | feasible-H7 |
| S18 | 473-479 | PLAN-v2.md:1334-1337 | f65290d | plan-FIT-10; feasible-H5, plan-FIT-04, facts-F13 |
| S19 | 489-491 | PLAN-v2.md:1351-1352 (PV-20 deletes that bullet) | f65290d | INV2-5 |
| S20, S21 | 840 | COVERAGE.md:308 | f65290d | plan-FIT-10; owner-R4 |
| S22 | 842 | COVERAGE.md:310 | f65290d | feasible-H5, plan-FIT-04, facts-F13 |
| S23 (optional) | 844 | COVERAGE.md:308 (and :312, unchanged) | f65290d | owner-R4 |
| S24 | 850-851 | COVERAGE.md:318-322 | f65290d | feasible-H5, plan-FIT-04, facts-F13 |
| S26 | 921-924 | P2.md:101-103 | fa5659d | plan-FIT-03 |
| S27 | 925-928 | P2.md:113-117 | f65290d | owner-R2, plan-FIT-02 |
| S30 | 1120-1122 | P4.md:92-97 | f65290d | plan-FIT-05 |
| S32 | 1203-1204 | P5.md:105-107 | f65290d | plan-FIT-05 |
| S34 | 1287-1291 | P6.md:86-95 | f65290d | plan-FIT-05 |
| S36 | 1435 | P9.md:458-465 (edited since by e428c5b; it still carries P9-8b's four parts and the E3 replay) | f65290d | plan-FIT-18, feasible-M5 |
| S39 (new) | 205 | PLAN-v2.md:423 (PV-22) | e428c5b | round-13 E5 lane, optional part |
| M1 | 83 | PLAN-v2.md:96 | earlier recorders | format-FH-6, owner-R5 |
| M2 | 444-447 | PLAN-v2.md:1303-1309 | earlier recorders | format-FH-6, owner-R5 |
| M3 | 498-530 | DECISIONS.md:68-87 | earlier recorders | format-FH-6, owner-R5 |
| M4 | 674 | HANDOVER.md:112-113 | earlier recorders | format-FH-6, owner-R5 |
| M5 | 762 | COVERAGE.md:73 | earlier recorders | format-FH-6, owner-R5 |
| M6 | 474-475 | PLAN-v2.md:1336-1337 | earlier recorders | feasible-H5, plan-FIT-04, facts-F13 |
| M7 | 682-683 | HANDOVER.md:122 | earlier recorders | feasible-H5, plan-FIT-04, facts-F13 |
| M8 | 255 | PLAN-v2.md:536 | earlier recorders | plan-FIT-12 |
| M9, M10 | 1184-1185, 1204 | P5.md:109-111 | earlier recorders | plan-FIT-12 |
| M11 | 278, 1293 | PLAN-v2.md:637; P6.md:102 | earlier recorders | plan-FIT-12 |
| M12 | 1313 | P6.md:760 and :129 | earlier recorders | plan-FIT-19 |

S39 is the round-13 E5 lane's optional sync record (fix log r13-P1b-E5, record 3's last line): insert, after `the
resolver's fan-out optional-parent read (P1c row 12)` (sync :205, once), the clause PV-22 gives PLAN-v2.md:423; the log
gives no separate text. Its target, PLAN-v2.md:423, has carried that clause since e428c5b, so under the sync file's rule
it is MOOT.

Not carried (as at c33ca28; each reason re-checked):
- **N1.** the plan-files-only record's optional bookkeeping line after sync :5; its "do not apply it again" would also
  stop S37's entries. S1 is used instead.
- **N2.** The superseded figure records for :419 up to c33ca28 (folded into S16; listed under "Conflicts settled").
- **N3.** The superseded INV2-5 texts for :490 ("six" and "seven" state files); fix log r4-inventory item 3 replaced
  them, and that item is S19 (MOOT).
- **N4.** apply log D4's optional :418 text, superseded by apply log V9 item 2 (S15, MOOT).
- **N5.** apply log V9 item 3's words for :473, replaced by the plan-files-only record's Fix 10's words (S18, MOOT).
- **N6.** The round-4 P1c report's note that the D2 clause "and a hook rejection are process steps" stays at sync
  :1414 and :1417; no text was recorded, and :1414 is P9-7's anchor on P9.md's own text.

#### Conflicts settled (later records over earlier ones)

- **The figure (PV-14, S16).** The 37a259a figure "43 / 56 / 29 / 24 of 121" (round 15) supersedes every earlier
  record for PLAN-v2.md:1176 and sync :419, oldest first:
  - at c33ca28, "38 / 34 / 28 / 22 of 121" (fix log r9inv-A103), which had folded DP-31, plan-sync Fix 13 and the
    rounds-1 to 8 records;
  - round 11: "38 / 35 / 28 / 23" (fix log r11inv-A63, interim), "38 / 35 / 28 / 24" (fix log r11inv-A62; restated by
    fix log r11inv-A70 and fix log r11inv-A94-A124), "38 / 36 / 28 / 24" (fix log r11inv-A105), "38 / 37 / 28 / 24" (fix
    log r11inv-A104);
  - round 12: single parts "40 / 44 / 24 / 22", "40 / 39 / 28 / 25" and "39 / 38 / 31 / 25"; merged "43 / 47 / 27 / 24
    of 121" (the round-12 patch notes' P1b records, fix log r12inv-apply, fix log r12-inv-from-p1b);
  - round 13: part 1 alone "43 / 49 / 26 / 24 of 120"; merged "43 / 52 / 26 / 24 of 120" (the round-13 patch notes' P1b
    records, fix log r13inv-apply, fix log r13-inv-leftovers), which e428c5b wrote into PLAN-v2.md:1176 but not into
    sync :419;
  - round 14: "43 / 52 / 28 / 24 of 120" (the round-14 patch notes' P1b records, fix log r14inv-apply);
  - round 15: single parts "42 / 52 / 28 / 24 of 121", "43 / 55 / 28 / 24 of 120" and "44 / 53 / 29 / 24 of 120", and
    part 3's merged "of 120", which misses A125; the collected record's recount gives "43 / 56 / 29 / 24 of 121";
  - round 16: "44 / 57 / 29 / 24 of 122" (the round-16 patch notes, part 3; "45 / 57 / 29 / 24 of 122" with its optional
    edits) and the round-16 adjudication's moved counts: not taken, since the round-16 inventory patches were not
    applied.
- **PV-4, PV-7, PV-8 and e428c5b.** e428c5b put the wake check into :385 and :536 in its own words; that wording is
  kept. PV-4 is not to be applied; PV-7 and PV-8 are optional restatements in the :563 row.
- **The round-13 PLAN-v2.md records (PV-22 to PV-25) and e428c5b.** e428c5b carries each in other words; its wording is
  kept, and the optional sync record S39 is MOOT with it.
- **C20-1's PLAN-v2.md:174 record (PV-26)** gives way to the round-15 disclosure lane, which made it unnecessary.

#### Notes with no text (accounted for; no item)

- Round-12 P1b apply records, 2.5: PLAN-v2.md and the sync file need no text (the row 1, 2, 4, 7, 10, 15, 16, e10 and
  n1 notes); 5.3 (n1): PLAN-v2 gives P4 only D1.e's advisory sinks, outside D24.
- Round-13 P1b apply records: no plan-file text besides a pointer to the round-13 figure record.
- Round-14 P1b apply records: PLAN-v2.md:1272 (P1's carry-over) stays; :696 and :733 (doctor's strict handshake, which
  exits 1 at d625284) are an observation; :979 (U-E1a, D17) backs E3's deletion (also fix log r14-P1b-apply, line 145).
- Round-15 P1b apply records, 2.5 and 3.4: PLAN-v2.md names only Rollback's (7); :959 holds; :65 keeps
  install-auto-sync.sh as an opt-in path, whose fate is left to the coordinator.
- Round-16 P1b apply records, 2.3: PLAN-v2.md:959 and :104 hold; PLAN-v2 cites E9's outcome only.
- Round-18 P1b apply records, 2 and 5: no text. Its note that PLAN-v2.md:387, :399 and :1271 still edit or run
  scripts/update-overnight-state.sh, which E13 and row 13 delete, points to the existing plan-FIT-16 record (apply log
  C11) and adds none; that record is the plan-files-only record's Fix 12, applied in other words in b335a0e (:357 lists
  "the overnight state's extra writers" among what P1b delivers before P2).
- Round-18 second-pass notes (prnames, row11lck, rule5, removals) and fix log r18b-P1b-apply: plan files none;
  PLAN-v2.md:357 stays true (prnames).
- fix log r13-P1b-acc9: PLAN-v2.md:1351 and sync :489 agree with acceptance 9's categories. fix log r11inv-A70:
  PLAN-v2.md:1089's commit_journal.py cite is unaffected. fix log r17-P1b-spec-coverage: PLAN-v2.md:284, :565 and TC-2
  (:1068) need no change. fix log r18-P1b-transition: none. the round-16 patch notes, parts 1 and 2 and the round-16
  adjudication: no plan-file text.
- The observations (no text) in the two c33ca28 records are not items and are not repeated here.

### The other phase prompts and the shared tail

Scope: every "For the plan files" item whose target is a prompt under `harness-repair-plan/prompts/` other than P1b.md
and P1c.md: `_common.md` (the shared tail), P2.md to P6.md, P7b.md, P8.md, P9.md and P10.md, plus the tails of P0.md,
P1.md, P7.md and P11.md. Nothing here is applied.

#### Conventions

- Base: HEAD ef34dbc of `claude/vibrant-hopper-bazrn8`; prompts/ has no uncommitted change. Paths are relative to
  `harness-repair-plan/`. Line numbers are those at ef34dbc and only orient: find each edit by its text.
- Since c33ca28, the base of the earlier records, three commits of the other session changed these prompts, each with
  line-count-preserving edits: 7beb706 (verification round 6: P2, P3, P4, P5, P9), e428c5b (round 7: P2, P3, P4, P5,
  P9) and bb56fe5 (round 8: P2, P3, P4, P5, P6). `_common.md`, P7b.md, P8.md, P10.md and P11.md are unchanged since
  c33ca28. Every item was re-anchored on the files at ef34dbc.
- Sources: the c33ca28 prompts record and its P4 D21 record (the plan-file records as of c33ca28; their ids F-... are
  kept and their "Finding" and "Source" fields are given as the source); the round-12 to round-18 P1b records; the fix
  logs written after c33ca28 that name a prompt in scope (r11inv-A63, r11inv-A70, r11inv-cites, r13-P1b-E5,
  r13-P1b-row10, r14-P1b-apply, r15-P1b-apply, r16-P1b-apply, r17-P1b-spec-coverage, r17-P1b-apply, r19-P1c-row10,
  r22-P1c-R22-1, r22-P1c-closeout; the other logs mention these prompts only to say a tail is byte-identical). Items
  first recorded after c33ca28 get ids L-<file>-NN. The round-12 to round-16 patch notes and the round-18b lane notes
  hold no prompt text in this scope: their plan-file records are the PLAN-v2.md:1176 and reviews/P1b-plan-sync.md:419
  figures, they cite P2.md and P10.md:359 only as evidence, and the round-18b lanes each say "Plan files: none".
- Duplicates are merged into one entry that names every record carrying it. Where records conflict, the later one is
  kept and the entry says so.
- State: "pending" (the old occurs exactly once now); "already applied" (with the commit; "in substance" when a later
  commit made the change in its own words, so the record's new text is not used); "superseded" (by what); "needs
  re-anchoring" (none is left: every lost anchor resolved to applied or superseded). As in the c33ca28 prompts record,
  where a later commit added an in-place clause that covers an item, the item is superseded; if its old still occurs
  once, applying it as well is harmless.
- Grade: "necessary" or "optional" as the record gives it (the c33ca28 prompts record's TO APPLY is necessary, TO APPLY
  (optional) is optional). Where a later record gives no grade, the entry says so and gives the grade its reason
  implies.
- Edit form: replace old by new exactly. "whole line(s)": old is complete lines without the final line break; "part of
  line(s)": a substring. Old and new are verbatim in the fenced blocks, so some lines there exceed 120 columns where the
  plan lines they quote do (table rows and long lines). For applied and superseded entries the old -> new is shown as
  recorded where the record gives it; entries that the c33ca28 prompts record gave only by the line that shows them say
  so.
- D25 quote: P2.md:92, P3.md:92, P4.md:74, P5.md:89 and P6.md:83 quote DECISIONS.md:70's sentence without its first two
  clauses (the first 11 characters); the five D25 items restore the full sentence, as the c33ca28 prompts record has it.
  The old and new texts give both forms verbatim, copied from those committed lines at 382d857.
- Checked at ef34dbc (Python, in memory, on the real text): each of the 84 pending olds occurs exactly once in its
  file; applied file by file in the order listed (top to bottom), each occurs exactly once at its turn, and every new
  occurs afterwards (0 failures). Every text quoted for an applied or superseded entry occurs in its file.

#### Counts

| Class | Count |
|---|---|
| Entries (duplicates merged) | 135 (115 F from the c33ca28 records, 20 L from later records) |
| Pending | 84 (66 necessary, 17 optional, 1 conditional) |
| Already applied | 32 (9 since c33ca28, in substance; 23 recorded ALREADY APPLIED at c33ca28) |
| Superseded | 19 (8 since c33ca28; 11 recorded MOOT at c33ca28, covering 24 fixes as the c33ca28 prompts record counted them) |
| Needs re-anchoring | 0 (one pending anchor, F-P2-07, changed from whole line to part of line; noted there) |

Pending by file: _common.md 5, P2.md 24, P3.md 5, P4.md 10, P5.md 8, P6.md 7, P7b.md 1, P8.md 1, P9.md 20, P10.md 3.
Accounted for without an entry: the no-text notes at the end of each file section, and the c33ca28 prompts record's "Not
carried" list (last section).

#### prompts/_common.md (the shared tail)

**F-C-01** `prompts/_common.md`:34, whole line.
- Source: finding owner-R20, feasible-L2; apply log V11 item 1, apply log W13; record: the d22c669 prompts record's Fix
  C-1.
- Grade: necessary.
- State: pending.
- Note: The same old occurs once in every shared tail (see "Tails" below).

old:
~~~
If you cannot fetch or read the planning documents, stop and tell the owner instead of guessing.
~~~
new:
~~~
If you cannot fetch or read the planning documents, stop and tell the reviewer in your session output (never
the owner, D18) instead of guessing.
~~~

**F-C-02** `prompts/_common.md`:71, whole line.
- Source: finding format-FH-4, feasible-L2; apply log V11 item 2, apply log W13; record: the d22c669 prompts record's
  Fix C-2.
- Grade: necessary.
- State: pending.
- Note: The same old occurs once in every shared tail (see "Tails" below).

old:
~~~
- Do not run nested `claude` CLI sessions. Do not put model identifiers in commits or the PR.
~~~
new:
~~~
- Do not run nested `claude` CLI sessions. Do not put model identifiers in commits or the PR, except the
  attribution trailer lines your session's own attribution instructions give for commits (today `Co-Authored-By`
  and `Claude-Session`), which end every commit message unchanged, none added or dropped.
~~~

**F-C-03** `prompts/_common.md`:76-79, whole lines.
- Source: finding owner-R20, feasible-L2; apply log V11 item 3, apply log W13; record: the d22c669 prompts record's Fix
  C-3.
- Grade: necessary.
- State: pending.
- Note: The same old occurs once in every shared tail (see "Tails" below).

old:
~~~
Baseline CI (`.github/workflows/baseline.yml`) has been red on master since 2026-07-26 (latest run at
09ab15b failed). Before changing anything, run the workflow's steps locally on python 3.12 against
`origin/master` and record which steps/tests fail. Repeat on your branch. Your PR must add no new failure.
Pre-existing failures outside your scope are not yours to fix (phase P8 makes CI green); list them in the PR.
~~~
new:
~~~
Baseline CI (`.github/workflows/baseline.yml`) is green on master once phase P8 is merged. Before changing
anything, run the workflow's steps locally on python 3.12 against `origin/master` and record the result. Repeat
on your branch. If P8 is merged, your PR keeps every job green. Before that, your PR must add no new failure, and
pre-existing failures outside your scope are not yours to fix (phase P8 makes CI green); list them in the PR.
~~~

**F-C-04** `prompts/_common.md`:89, whole line.
- Source: finding format-FH-1, feasible-M3; apply log C10 item 1, apply log D7 item 1, apply log V15; record: the
  d22c669 prompts record's Fix C-4.
- Grade: optional.
- State: pending.
- Note: The same old occurs once in every shared tail (see "Tails" below).

old:
~~~
- **Test evidence**: commands and their output (CI baseline before/after, acceptance tests, sandbox replays).
~~~
new:
~~~
- **Test evidence**: commands and their output (CI baseline before/after, acceptance tests, sandbox replays).
  The body and each comment stay at or under 60,000 UTF-8 bytes (GitHub refuses more than 65,536 characters):
  output that does not fit goes in PR comments, split as needed and linked from this heading, never in the
  repository.
~~~

**F-C-05** `prompts/_common.md`:95-97, whole lines.
- Source: finding owner-R20, feasible-L2; apply log V11 item 4, apply log W13; record: the d22c669 prompts record's Fix
  C-5.
- Grade: necessary.
- State: pending.
- Note: The same old occurs once in every shared tail (see "Tails" below).

old:
~~~
After opening the PR, subscribe to its activity and drive it: answer and fix every review comment, keep
CI no worse than master, and when master moves (another phase merged) merge `origin/master` into your
branch (a merge commit; no rebase) and resolve conflicts. Stop when the PR is merged or closed.
~~~
new:
~~~
After opening the PR, subscribe to its activity and drive it: answer and fix every review comment, keep
CI green (before P8 is merged: no worse than master), and when master moves (another phase merged) merge
`origin/master` into your branch (a merge commit; no rebase) and resolve conflicts. Stop when the PR is
merged or closed.
~~~

**Tails.** C-1 to C-5 change the shared tail: the text from the heading line "## Context (read once)" to the end.

| Prompt | Heading line | Tail equals `_common.md` | C-1 to C-5 olds (each once) | Re-sync |
|---|---|---|---|---|
| P1.md | :876 | yes | :909, :946, :951-954, :964, :970-972 | optional (phase merged) |
| P1b.md | :1214 | yes | :1247, :1284, :1289-1292, :1302, :1308-1310 | required (byte-identity rule; the P1b lane applies it) |
| P1c.md | :1115 | yes | :1148, :1185, :1190-1193, :1203, :1209-1211 | required (byte-identity rule; the P1c lane applies it) |
| P2.md | :940 | yes | :973, :1010, :1015-1018, :1028, :1034-1036 | required (byte for byte) |
| P3.md | :768 | yes | :801, :838, :843-846, :856, :862-864 | required (byte for byte) |
| P4.md | :798 | yes | :831, :868, :873-876, :886, :892-894 | required (byte for byte) |
| P5.md | :902 | yes | :935, :972, :977-980, :990, :996-998 | required (byte for byte) |
| P6.md | :816 | yes | :849, :886, :891-894, :904, :910-912 | required (byte for byte) |
| P7b.md | :646 | yes | :679, :716, :721-724, :734, :740-742 | optional (phase merged) |
| P8.md | :816 | yes | :849, :886, :891-894, :904, :910-912 | optional (phase merged) |
| P9.md | :768 | yes | :801, :838, :843-846, :856, :862-864 | required (byte for byte) |
| P0.md | :229 | no | :262, :298, :303-306, :316, :322-324 | leave, or apply C-1 to C-5 by hand (older Principle 7; phase ran) |
| P7.md | :422 | no | :455, :491, :496-499, :509, :515-517 | leave, or apply C-1 to C-5 by hand (older Principle 7; phase ran) |
| P10.md | :792 | no | :826, :863, :868-871, :881, :887-889 | apply C-1 to C-5 by hand (its tail differs only by the D20-D25 rulings sentence) |
| P11.md | :768 | no | :802, :839, :844-847, :857, :863-865 | apply C-1 to C-5 by hand (its tail differs only by the D20-D25 rulings sentence) |

For P1b.md and P1c.md (outside this group's scope; their lanes apply it), the notes of the c33ca28 prompts record F-C-01
to F-C-05 re-anchor at ef34dbc as follows. The "Planning documents" sentence that repeats C-1 is P1b.md:1151-1152 and
part of P1c.md:1031-1032. The "Commits" bullet that restates C-2 is P1b.md:1153-1158 and P1c.md:1033-1038. The CI part
of the override bullet that C-3 and C-5 make redundant is P1b.md:1145-1150 (to "(acceptance 19).") and P1c.md:1027-1031
(to "(acceptance 17)."). The PR-size bullet that stays beside C-4 starts at P1b.md:1171 and P1c.md:1071. The "After
opening the PR" bullet that already says "keep CI green" is P1b.md:1180-1181 and P1c.md:1080-1081.

#### prompts/P2.md

**F-P2-01** `prompts/P2.md`:1, part of line.
- Source: finding owner-R2, plan-FIT-02; apply log C3, apply log D6; record: the d22c669 prompts record's Fix P2-1.
- Grade: necessary.
- State: pending.

old:
~~~
D6 landing route; arm G1-G3
~~~
new:
~~~
D6 landing route; arm G1 and G3
~~~

**F-P2-02** `prompts/P2.md`:5, whole line.
- Source: finding owner-R2, plan-FIT-02; apply log C3, apply log D6; record: the d22c669 prompts record's Fix P2-2.
- Grade: necessary.
- State: pending.

old:
~~~
landing route, arm G1-G3`).
~~~
new:
~~~
landing route, arm G1 and G3`).
~~~

**F-P2-03** `prompts/P2.md`:15, part of line.
- Source: finding owner-R2, plan-FIT-02; apply log C3, apply log D6; record: the d22c669 prompts record's Fix P2-3.
- Grade: necessary.
- State: pending.

old:
~~~
your last commit arms G1-G3
~~~
new:
~~~
your last commit arms G1 and G3
~~~

**F-P2-04** `prompts/P2.md`:82-83, whole lines.
- Source: finding owner-R20 (refuter B); apply log V11 item 6; record: the d22c669 prompts record's Fix P2-5.
- Grade: necessary.
- State: pending.

old:
~~~
- If any check fails, stop and tell the owner that wave 3 starts only after P1, P8, P7b, P1b and P1c are merged. Do not start
  from an older base.
~~~
new:
~~~
- If any check fails, stop and tell the reviewer in your session output (never the owner) that wave 3 starts only
  after P1, P8, P7b, P1b and P1c are merged. Do not start from an older base.
~~~

**F-P2-05** `prompts/P2.md`:92-93, whole lines.
- Source: finding format-FH-6, owner-R5; apply log W1 item 1; record: the d22c669 prompts record's Fix P2-4.
- Grade: necessary.
- State: pending.

old:
~~~
(D25: "永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！") into the CI replay suite under
tests/replay/. For this phase:
~~~
new:
~~~
(D25: "还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！")
into the CI replay suite under tests/replay/. For this phase:
~~~

**F-P2-06** `prompts/P2.md`:101.
- Source: finding plan-FIT-03 (refuter B); apply log C11; record: the d22c669 prompts record's Fix P2-9.
- Grade: necessary.
- State: already applied: the text below is in the file since f65290d (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
(row 9); the cycle contract's one path and its one writer, the PM TRIAGE handler of TC-43, which P1b's E13 delivered
~~~

**L-P2-01** `prompts/P2.md`:107.
- Source: round-12 P1b records 2.2 (lane row13), repeated as round-15 P1b records 2.2 (still open there; R15B-FR-4
  relies on it) and round r15b refs-acceptance O-7.
- Grade: necessary (no grade in the source; P2's early-delivery list lacked P1b row 13's one state function).
- State: already applied in substance by e428c5b (P2.md:107 names the overnight state's one deciding function, P1b row
  13, delivered early for row 7); the old no longer occurs and the new is not used.

old (no longer occurs):
~~~
`cycle_index(state)` in hooks/lib/overnight.py, which every reader of the cycle number already calls (P1b E13,
  from your row 7; rows 7, 11 and 12 keep the rest of the locator and the parser);
~~~
new (not used):
~~~
`cycle_index(state)` in hooks/lib/overnight.py, which every reader of the cycle number already calls (P1b E13,
  from your row 7), and the one function there that every deciding reader of the overnight state calls for its
  verdicts (P1b row 13); rows 7, 11 and 12 keep the rest of the locator and the parser, changed in that function;
~~~

The text that shows it now:
~~~
and the overnight state's one deciding function there, which every other deciding reader of the record already calls in place of its own reading
~~~

**F-P2-07** `prompts/P2.md`:112, part of line.
- Source: finding plan-FIT-16 (with apply log C11 wording); record: the plan-files-only record's Fix 11.
- Grade: necessary.
- State: pending.
- Note: Re-anchored: the old was the whole of :112 at c33ca28; e428c5b appended P1c X8's wake sentence to that line, so
  the old is now its first part and that sentence follows the new text's last line. This is plan-FIT-16's prompt text
  (the plan-files-only record's Fix 11); round-18 P1b records section 5 cites the same defect at P2 row 14 and
  acceptance 8 (P2.md:332, :799, :885: scripts/update-overnight-state.sh, which P1b E13 deletes) and adds no text, so it
  is merged here.

old:
~~~
  its suite needed: complete each in the same mechanism and do not rebuild it.
~~~
new:
~~~
  its suite needed: complete each in the same mechanism and do not rebuild it. Rows 4, 7, 11, 14, 15 and 18, acceptances
  5 and 8, "Rules added" and the technical choices act only on the scripts and state writers P1b left; an item about a
  removed one is met by its absence, and the PR says so. The /stop release stays the human-typed /stop prompt record
  (row 8); whether break-overnight-lock.py still records `terminal_status=cancelled_by_user` and
  `current_phase=completed` (row 14; lib/overnight's session-agnostic exemption, row 7) follows P1b's PR, whose E13
  sends /stop's state write through the launcher's write path.
~~~

**F-P2-08** `prompts/P2.md`:113.
- Source: finding owner-R2, plan-FIT-02; apply log C3 (sync :925-928), apply log D6; record: the d22c669 prompts
  record's Fix P2-8.
- Grade: necessary.
- State: superseded by the in-place text below, in the file since b335a0e (recorded MOOT at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The covering text now:
~~~
- Arming: if P1b's E4 (in P1b's arming commit, its Rollback step (7), which its later review-fix and merge commits keep) or, failing that, P1c's X3 already set `CLAUDE_OBLIGATION_STOPGATE`
~~~

**F-P2-09** `prompts/P2.md`:113.
- Source: finding M1 (round r1 report acceptance-P1b); record: fix log r1-P1b-ci "For the plan files" item 3 (optional),
  superseded by fix log r5-P1c-small "For the plan files" (P2.md:113).
- Grade: optional.
- State: already applied: the text below is in the file since b335a0e (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
in P1b's arming commit, its Rollback step (7), which its later review-fix and merge commits keep
~~~

**F-P2-10** `prompts/P2.md`:157-158, whole lines.
- Source: finding owner-R2, plan-FIT-02; apply log C3, apply log D6; record: the d22c669 prompts record's Fix P2-6.
- Grade: necessary.
- State: pending.

old:
~~~
7. **Arm G1-G3.** The last commit sets CLAUDE_OBLIGATION_GATE, CLAUDE_OBLIGATION_STOPGATE and
   CLAUDE_OBLIGATION_BARRIER to `block` in the tracked settings.json. CLAUDE_OBLIGATION_TERMINAL is never added.
~~~
new:
~~~
7. **Arm G1 and G3.** The last commit sets CLAUDE_OBLIGATION_GATE and CLAUDE_OBLIGATION_BARRIER to `block` in the
   tracked settings.json (CLAUDE_OBLIGATION_STOPGATE is already `block` from P1b's E4 or P1c's X3; set it here only
   if your base lacks it), and deletes the consumer-side copies P1b's PR keeps for G1 and G3.
   CLAUDE_OBLIGATION_TERMINAL is never added.
~~~

**F-P2-11** `prompts/P2.md`:162.
- Source: finding owner-R2, plan-FIT-02; apply log C3, apply log D6; record: the d22c669 prompts record's Fix P2-7.
- Grade: necessary.
- State: superseded: Goal 7's last sentence was rewritten in 9380922 (recorded MOOT at c33ca28); 7beb706 then added "G2"
  to the quoted line, requoted here; the c33ca28 prompts record gave it by this line only; its old -> new is in the
  record it cites.

The covering text now:
~~~
   it on your base, take no G2 hunk of P3's and do not wait for P3; if P1b's E4 or P1c's X3 already set STOPGATE, the
~~~

**F-P2-12** `prompts/P2.md`:186-187, whole lines.
- Source: finding plan-FIT-06; record: the plan-files-only record's Fix 6.
- Grade: necessary.
- State: pending.

old:
~~~
    and consumers that trust one conclusion: the lane-completeness hook is the canonical aggregate's only producer
    (row 4), writers with no reader go (rows 4, 9), a contract entry and its obligation declare one schema ("The
~~~
new:
~~~
    and consumers that trust one conclusion: P1b gave the canonical aggregate one producer (E5) and deleted the writers
    with no reader (verify both), a contract entry and its obligation declare one schema ("The
~~~

**F-P2-13** `prompts/P2.md`:224.
- Source: finding INV9-1 (round r9inv report inventory), the A103 terminal receipt; record: fix log
  r12-P1b-terminal-receipt "For the plan files" (P2.md:223-224, optional); supersedes fix log r9inv-A103, lines 260-265
  and the corrected anchor of round r10inv report inventory section E item 2; round r13b report faithful-rules-P1b,
  lines 151-153 (P2.md:224 becomes true on P2's base, so the text stays an optional clarification).
- Grade: optional.
- State: already applied in substance by e428c5b, which rewrote the D15 bullet (now P2.md:223-228) to name the one
  terminal-receipt call P1b row 15 left; the old no longer occurs and the new is not used.

old (no longer occurs):
~~~
- **D15.** No feature retirement: `scripts/commit.sh` stays in the tree, unreferenced by the overnight prose; the
  terminal receipts (`session_resources.publish_overnight_receipt`) keep being published; /stop keeps releasing the
  isolation fields its token gates today. A hook you unregister stays an exit-0 stub with a `# STUB:` line until P10
  (you are not expected to unregister any). Running sessions keep the hook list and the env they loaded, and run the
  current hook files.
~~~
new (not used):
~~~
- **D15.** No feature retirement: `scripts/commit.sh` stays in the tree, unreferenced by the overnight prose; the
  terminal receipts keep being published by the one call P1b's row 15 left (at d625284 the time-lock's
  `session_resources.publish_overnight_receipt` call wrote nothing: the Stop coordinator ran it without the trust keys,
  inventory A103); /stop keeps releasing the isolation fields its token gates today. A hook you unregister stays an
  exit-0 stub with a `# STUB:` line until P10 (you are not expected to unregister any). Running sessions keep the hook
  list and the env they loaded, and run the current hook files.
~~~

The text that shows it now:
~~~
keep being published, through the one call P1b row 15 made meet finalize's read
~~~

**F-P2-14** `prompts/P2.md`:322, part of line.
- Source: finding feasible-H3, facts-F9; apply log C8; record: the d22c669 prompts record's Fix P2-12.
- Grade: necessary.
- State: pending.

old:
~~~
`_invoke_aggregator` :210-236 (script path :216, the silent return :217-218);
~~~
new:
~~~
`_invoke_aggregator` :210-236 (script path :216, the silent return :217-218; P1b's E5 fixed or deleted it);
~~~

**F-P2-15** `prompts/P2.md`:322, part of line.
- Source: finding feasible-H3, facts-F9; apply log C8; record: the d22c669 prompts record's Fix P2-10.
- Grade: necessary.
- State: pending.

old:
~~~
B1.e, B1.g. The aggregator resolves relative to the hook's own file, so a product repo's fan-out gets its canonical aggregate (the armed test's 2-pipeline overnight run needed it).
~~~
new:
~~~
B1.e, B1.g. P1b's E5 made both aggregate producers reach the harness's aggregator (the hook from its own file, /dev Step 11 by its harness-home spelling, the aggregator's --project-dir) and kept one of them (its PR): verify it on your base and redo nothing.
~~~

**F-P2-16** `prompts/P2.md`:322, part of line.
- Source: finding feasible-H3, facts-F9; apply log C8; record: the d22c669 prompts record's Fix P2-11.
- Grade: necessary.
- State: pending.

old:
~~~
The lane-completeness hook is the canonical aggregate's only producer. Delete the orchestrator aggregation step in dev.md (:885 and the "MUST write" block :898-923) and its dev-command.md equivalent instead of respelling them, and delete
~~~
new:
~~~
The canonical aggregate's only producer is the one P1b's E5 kept (its PR). If that is the hook, delete the orchestrator aggregation step in dev.md (:885 and the "MUST write" block :898-923) and its dev-command.md equivalent if P1b left them; if it is Step 11, the hook makes no aggregator call. Delete
~~~

**F-P2-17** `prompts/P2.md`:327, part of line.
- Source: finding FR15-1 (round r15 report faithful-rules-P1c); record: fix log r15-P1c-FR15-1 record 1 (supersedes fix
  log r14-P1c-RA14-1 record 1 and the part (e) text of round r15 report faithful-rules-P1c FR15-1); confirmed by fix log
  r15-P1c-FR15-3 and fix log r16-P1c-RA16-1.
- Grade: necessary.
- State: superseded by the in-place clause e428c5b appended to P2.md:112 (P1c X8's wake check, which the thinned
  time-lock of row 9 keeps); the old still occurs once (row 9), so applying it as well is harmless.

old:
~~~
else a /stop record released it, allow and publish the `cancelled_by_user` receipt (no closeout check: /stop is a human exit, and B2.b found today's /stop landing in the closeout block); else end_time has passed, block with `closeout_gaps` named on stderr until it is empty, then allow and publish `completed_by_deadline`.
~~~
new:
~~~
else a /stop record released it, block while P1c's wake is undeleted (below), then allow and publish the `cancelled_by_user` receipt (no closeout check: /stop is a human exit, and B2.b found today's /stop landing in the closeout block; the wake is the orchestrator's own schedule, not a closeout artifact); else end_time has passed, block with `closeout_gaps` named on stderr until it is empty, then block while P1c's wake is undeleted, then allow and publish `completed_by_deadline`. P1c's wake is undeleted while the session's transcript holds a CronCreate of its text whose id no later CronDelete names; the block names that id, and the orchestrator's own CronDelete clears it (P1c X8).
~~~

The covering text now:
~~~
so row 9's /stop and after-end_time allows apply only once the wake is deleted
~~~

**L-P2-03** `prompts/P2.md`:327, part of line.
- Source: round-17 P1b records 1.2 (lane closeout, after round r17b's R17B-4, low), restated by fix log
  r22-P1c-closeout; round r17b refs-acceptance gives the same edit with "deleted the" where both later records say
  "deleted its": the later wording is kept.
- Grade: necessary (no grade in the source; the old offers P2 a choice that P1b row 13's deletion of the block
  removed).
- State: pending.
- Note: Row 9, "Change" column; the row stays one line.

old:
~~~
(`_invoke_closeout` goes, or keeps only the `has_pending_required_calls` check if you keep the block below)
~~~
new:
~~~
(`_invoke_closeout` goes; P1b row 13 deleted its `has_pending_required_calls` block)
~~~

**L-P2-04** `prompts/P2.md`:327, part of line.
- Source: round-17 P1b records 1.3, restated by fix log r22-P1c-closeout and round r17b refs-acceptance (same text).
- Grade: necessary (no grade in the source; same reason as L-P2-03).
- State: pending.
- Note: Row 9; the row stays one line.

old:
~~~
The pending-required-calls block before end_time is dead (the lock blocks anyway, B2.e), so drop it or keep it (D10).
~~~
new:
~~~
The pending-required-calls block before end_time, dead since the lock blocks anyway (B2.e), went in P1b row 13.
~~~

**F-P2-18** `prompts/P2.md`:332, part of line.
- Source: finding plan-FIT-03 (refuter A); apply log C11; record: the d22c669 prompts record's Fix P2-14.
- Grade: necessary.
- State: pending.

old:
~~~
It may still record `terminal_status=cancelled_by_user` and `current_phase=completed` for the summary
~~~
new:
~~~
It may record `terminal_status=cancelled_by_user` (the base writes none) and keep recording `current_phase=completed` for the summary, through the launcher's write path P1b's E13 gave /stop's write
~~~

**F-P2-19** `prompts/P2.md`:332, part of line.
- Source: finding FR15-1; record: fix log r15-P1c-FR15-1 record 2.
- Grade: necessary.
- State: superseded by the same in-place clause at P2.md:112 (e428c5b), which names row 14's stop.md rewrite; the old
  still occurs once (row 14), so applying it as well is harmless.

old:
~~~
stop.md's description and "What it does" so they say what /stop now does.
~~~
new:
~~~
stop.md's description and "What it does" so they say what /stop now does, and keep stop.md's last step, the CronDelete of P1c's wake (P1c X8).
~~~

The covering text now:
~~~
row 14's stop.md rewrite keeps stop.md's last step, the wake's CronDelete
~~~

**F-P2-20** `prompts/P2.md`:335, part of line.
- Source: finding owner-R2, plan-FIT-02; apply log C3, apply log D6; record: the d22c669 prompts record's Fix P2-15.
- Grade: necessary.
- State: pending.

old:
~~~
add `"CLAUDE_OBLIGATION_GATE": "block"`, `"CLAUDE_OBLIGATION_STOPGATE": "block"`, `"CLAUDE_OBLIGATION_BARRIER": "block"` to env.
~~~
new:
~~~
add `"CLAUDE_OBLIGATION_GATE": "block"` and `"CLAUDE_OBLIGATION_BARRIER": "block"` to env (and `"CLAUDE_OBLIGATION_STOPGATE": "block"` only if your base lacks it), and delete the consumer-side copies P1b's PR keeps for G1 and G3.
~~~

**L-P2-02** `prompts/P2.md`:380-383, part of lines.
- Source: round-12 P1b records 2.3 (lane row13), repeated as round-15 P1b records 2.3; round r15b refs-acceptance O-7
  and faithful-rules ("P2.md:380-383 still files the script").
- Grade: necessary (no grade in the source; after P1b row 13 the script prints the window verdict, so the old text
  files a defect P1b removed).
- State: pending.
- Note: The old starts mid-line 380, after "edits them. "; rewrap as needed.

old:
~~~
Also list under "Out of scope, found": the kept TIME CHECK paragraph (dev-overnight.md:1568) says
scripts/overnight-status.sh "reports remaining wall-time relative to `end_time` and exits non-zero if the session has
expired", but the script only prints the state with jq (no time computation, exit 0) and looks in `docs/dev/overnight`
by default, not `.claude/`; the loop hook's end_time message is what ends the cycle loop.
~~~
new:
~~~
The kept TIME CHECK paragraph (dev-overnight.md:1568) routes on scripts/overnight-status.sh's window verdict, which
P1b row 13 takes from hooks/lib/overnight.py; it follows `window_open` once that function computes it.
~~~

**F-P2-21** `prompts/P2.md`:472-474, whole lines.
- Source: finding RA14-1 (round r14 report refs-acceptance-P1c); record: fix log r14-P1c-RA14-1 record 2 (still valid
  per fix log r15-P1c-FR15-1 and fix log r15-P1c-FR15-3).
- Grade: necessary.
- State: pending.
- Note: P2.md:112 (e428c5b) now states the wake rule for row 9; this bullet still ends the session on `closeout_gaps`
  alone.

old:
~~~
- After end_time nobody is asked. The session ends once closeout_gaps is empty (retro reports and summary). If every
  pipeline is done before end_time, the time-lock still blocks until end_time; the PM step plans further work, and
  /stop is the human control.
~~~
new:
~~~
- After end_time nobody is asked. The session ends once closeout_gaps is empty (retro reports and summary) and P1c's
  wake is deleted (P1c X8). If every pipeline is done before end_time, the time-lock still blocks until end_time; the PM
  step plans further work, and /stop is the human control.
~~~

**F-P2-22** `prompts/P2.md`:558-559, whole lines.
- Source: finding FR15-4 (round r15 report faithful-rules-P1c), its observation on P2; record: the orchestrator's
  running notes ("fix log r15-P1c-FR15-4: P2.md names its own arming commit 'the last commit' while requiring later
  review-fix and merge commits ... -> plan-file record for P2.md"); fix log r15-P1c-FR15-4 "Observation"; round r16
  report faithful-rules-P1c observation 3.
- Grade: necessary.
- State: pending.
- Note: This is the P2 arming-commit gap (the orchestrator's running notes, from fix log r15-P1c-FR15-4: P2 calls its
  arming commit "the last commit" while requiring later review-fix and merge commits).

old:
~~~
- The arming commit is the last commit and holds only the three env keys (row 17), plus the docs lines arming makes
  false (row 16) if you prefer them there.
~~~
new:
~~~
- The arming commit is the last commit you plan; a commit after it (a review fix, a merge of `origin/master`) keeps its
  switches, as P1b's E4 says of G2's. It holds only the env keys row 17 adds and the deletion of the consumer-side
  copies P1b kept for G1 and G3 ("P1b and P1c", Arming), plus the docs lines arming makes false (row 16) if you prefer
  them there.
~~~

**L-P2-05** `prompts/P2.md`:585, whole line.
- Source: round-17 P1b records 1.4, restated by fix log r22-P1c-closeout (lane note: "the choice it names no longer
  exists").
- Grade: necessary (no grade in the source; the lane note's reason).
- State: pending.
- Note: Technical choices list.

old:
~~~
- the write-qa-mode.sh fallback root, and whether the time-lock keeps the dead pending-required-calls branch;
~~~
new:
~~~
- the write-qa-mode.sh fallback root;
~~~

**F-P2-23** `prompts/P2.md`:775-776, whole lines.
- Source: finding feasible-H3, facts-F9; apply log C8 (acceptance 5 record); record: the d22c669 prompts record's Fix
  P2-13.
- Grade: necessary.
- State: pending.

old:
~~~
5. **Code paths (B1.e, section 13).** posttool-lane-completeness-watch in `/root/toyproj` with 2 valid lane reports:
   the canonical aggregate is written (before: silent return). specialist_yield reads the shipped policy (before: the
~~~
new:
~~~
5. **Code paths (B1.e, section 13).** posttool-lane-completeness-watch in `/root/toyproj` with 2 valid lane reports:
   the canonical aggregate is written if P1b's E5 kept the hook, and the hook makes no aggregator call if it kept Step
   11 (before: silent return). specialist_yield reads the shipped policy (before: the
~~~

**F-P2-24** `prompts/P2.md`:777-778, whole lines.
- Source: finding open item 2 of fix log r3-P1b-basekit (acceptance 17: scripts the branch deletes); record: fix log
  r3-P1b-qamode "For the plan files" item 2.
- Grade: necessary.
- State: pending.

old:
~~~
   fallback). write-qa-mode.sh, if P1b's PR left it (its row 1 and E7), from a product root with CLAUDE_PROJECT_DIR unset
   writes in that product's registry (before: rc 1 "CLAUDE_PROJECT_DIR not set"; the script is unchanged since f8c18c2, P8 changed
~~~
new:
~~~
   fallback). write-qa-mode.sh, if P1b's PR left its `qa_mode` write (its row 1 and E7; not its exit-0 stub, P1b
   acceptance 17), from a product root with CLAUDE_PROJECT_DIR unset writes in that product's registry (before: rc 1
   "CLAUDE_PROJECT_DIR not set"; the script is unchanged since f8c18c2, P8 changed
~~~

**F-P2-25** `prompts/P2.md`:785, whole line.
- Source: finding RA14-1; record: fix log r14-P1c-RA14-1 record 3 (acceptance 6; still valid per fix log r15-P1c-FR15-1
  and FR15-3).
- Grade: necessary.
- State: pending.
- Note: Acceptance 6 still tests `closeout_gaps` alone; P2.md:112 (e428c5b) states the rule but adds no acceptance
  case.

old:
~~~
   - after end_time: `closeout_gaps` is evaluated and named on stderr;
~~~
new:
~~~
   - after end_time: `closeout_gaps` is evaluated and named on stderr, then P1c's undeleted wake (P1c X8);
~~~

**F-P2-26** `prompts/P2.md`:802-804, whole lines.
- Source: finding FR15-1; record: fix log r15-P1c-FR15-1 record 3 (acceptance 8).
- Grade: necessary.
- State: pending.
- Note: Acceptance 8 is unchanged since c33ca28; see F-P2-25.

old:
~~~
   the time-lock releases with no closeout check and the `cancelled_by_user` receipt, the deny lifts, the next
   all-completed TodoWrite prints no loop continuation, and the next plain prompt gets no overnight continuation from
   prompt-workflow. The same `/stop` text in a Skill-produced, scheduled or isMeta record releases nothing.
~~~
new:
~~~
   the time-lock releases with no closeout check and the `cancelled_by_user` receipt (with P1c's wake undeleted in the
   transcript, only after a block naming its id that the orchestrator's CronDelete clears; P1c X8), the deny lifts, the
   next all-completed TodoWrite prints no loop continuation, and the next plain prompt gets no overnight continuation
   from prompt-workflow. The same `/stop` text in a Skill-produced, scheduled or isMeta record releases nothing.
~~~

**F-P2-27** `prompts/P2.md`:871-872, whole lines.
- Source: finding plan-FIT-06; record: the plan-files-only record's Fix 5.
- Grade: necessary.
- State: pending.

old:
~~~
    for overnight state, cycle contract, retro report, summary, canonical aggregate, advisory logs,
    harness-report.json, continuation sentinel, aggregate-pending and terminal receipts.
~~~
new:
~~~
    for the retro report, the summary, the terminal receipts and every artifact your rows change (P1b's table covers the
    overnight state, cycle contract, canonical aggregate, advisory logs, harness-report.json, continuation sentinel and
    aggregate-pending).
~~~

**Accounted for, no text:**

- round-12 P1b records 2.4: P2.md:372-379 (the other end_time parsers) needs no text; P2.md:98 ("verify each on your
  base and do not redo it") covers P1b row 13. Its note on the net code cap (P2.md:907): re-measured against the master
  P1b leaves, as P1b's Correction 2 says. No change.
- round-14 P1b records 2.3: P2's Arming paragraph already covers the deletion of the preflight's consumer-side copy. No
  change.
- round-15 P1b records 3.3: P2.md:100 already lists the continuation-sentinel deletion as delivered by P1b. No change.
- round-16 P1b records 2.3: P2.md:113 names only P1b's Rollback step (7); no file cites (4)'s row list. No change.
- round-18 P1b records section 4 (lane e13): once update-overnight-state.sh goes, the overnight guard's two exemptions
  for it sanction nothing; left as "row 13's and P2's guard business". No text.
- the round-15 patch notes, part 2, E.1: P2.md already describes the time-lock's after-end_time closeout block. No edit.
- Fix log r22-P1c-R22-1: P2.md:97, P3.md:96, P5.md:91 and P6.md:85 already say that the CLI's transcripts and agent
  meta have one reader since P1b row 18 (added in bb56fe5); P1c took the same sentence. No text.

#### prompts/P3.md

**F-P3-01** `prompts/P3.md`:82-83, whole lines.
- Source: finding owner-R20 (refuter B); apply log V11 item 6; record: the d22c669 prompts record's Fix P3-1.
- Grade: necessary.
- State: pending.

old:
~~~
- If any check fails, stop and tell the owner that wave 3 starts only after P1, P8, P7b, P1b and P1c are merged. Do not start
  from an older base.
~~~
new:
~~~
- If any check fails, stop and tell the reviewer in your session output (never the owner) that wave 3 starts only
  after P1, P8, P7b, P1b and P1c are merged. Do not start from an older base.
~~~

**F-P3-02** `prompts/P3.md`:92, whole line.
- Source: finding format-FH-6, owner-R5; apply log W1 item 2; record: the d22c669 prompts record's Fix P3-2.
- Grade: necessary.
- State: pending.

old:
~~~
"永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！") into the CI replay suite under tests/replay/. For this phase:
~~~
new:
~~~
"还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！") into the CI
replay suite under tests/replay/. For this phase:
~~~

**F-P3-03** `prompts/P3.md`:235.
- Source: finding facts-F4, plan-FIT-13; apply log C7; record: the d22c669 prompts record's Fix P3-3.
- Grade: necessary.
- State: already applied: the S9 bullet said so since b335a0e (recorded ALREADY APPLIED at c33ca28); 7beb706 rewrote the
  line, which still names P1b E8's removal of `pending`, requoted here; the c33ca28 prompts record gave it by this line
  only; its old -> new is in the record it cites.

The text that shows it now:
~~~
  unwritten `do.status` (P1b E8 removed `pending`), a /do task's missing do-report (P1b E8 (a)) and `blocked` (still a schema value until P5-d) to a fact gap naming the do-report, never to chain_pass.
~~~

**F-P3-04** `prompts/P3.md`:288, part of line.
- Source: finding faithful F-5, F-7 (round r1 report faithful-P1b), the orchestrator's running notes C2 and C12; record:
  fix log r1-P1b-reader "For the plan files" (P3.md:288, row 1).
- Grade: necessary.
- State: pending.

old:
~~~
for a never-dispatched artifact, return the command's canonical todo step.
~~~
new:
~~~
for a never-dispatched artifact, return the command's canonical todo step with its subagent_call, or none for the main agent's own step; read the task's dispatch records from every session of the project, keyed by the obligation's task_id (P1b E3).
~~~

**L-P3-02** `prompts/P3.md`:299, whole line.
- Source: fix log r13-P1b-E5, "For the plan files" item 1 (the P1b change is a58ee3d); it carries fix log r11inv-A63's
  coupled note ("if P1b removes E5, P3.md:299 ... needs rewording"), merged here.
- Grade: necessary when recorded (no grade in the source; row 13's "the way the live commit grant is" named a rule P1b
  row 11 removed).
- State: superseded by the in-place clause e428c5b added at P3.md:102 (P1b row 11's `commit-landing` exemption,
  delivered early, is what row 13's phrase means); the old still occurs once (row 13), so applying it as well is
  harmless.

old:
~~~
| 13 | hooks/pretool-gitignore-preflight.py | `main` :717-820 (the E5 exemption :807-811; `has_live_commit_grant` :669) | S7 (design G3). A dispatch whose obligation (parsed with `obligation.parse_obligation`) has profile `commit-qa`, `commit-landing`, `do-close` or `final_verification` is exempt, the way the live commit grant is (commit #260, close #122/#140). Dev-side dispatches keep the guard. |
~~~
new:
~~~
| 13 | hooks/pretool-gitignore-preflight.py | `main` :717-820 (the E5 exemption :807-811, which P1b row 11 keys on the dispatch's obligation instead of `has_live_commit_grant` :669) | S7 (design G3). A dispatch whose obligation (parsed with `obligation.parse_obligation`) has profile `commit-qa`, `commit-landing`, `do-close` or `final_verification` is exempt, as P1b row 11 already exempts a `commit-landing` dispatch for its own report's task in place of the live commit grant (commit #260, close #122/#140). Dev-side dispatches keep the guard. |
~~~

The covering text now:
~~~
its "the way the live commit grant is" means that exemption, and acceptance 11's `commit-landing` case exits 0 on your base already
~~~

**F-P3-05** `prompts/P3.md`:343.
- Source: finding facts-F4, plan-FIT-13; apply log C7; record: the d22c669 prompts record's Fix P3-4.
- Grade: necessary.
- State: already applied: the text below is in the file since b335a0e (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
file-list check to it (TC-46), and P4 decides the /close route for a /do task with no completed do-report (Q7);
~~~

**L-P3-01** `prompts/P3.md`:490, whole line.
- Source: round-14 P1b records 2.1 (lane e3; the applier's check of E3's D17 ruling), repeated in fix log r14-P1b-apply;
  round r17b faithful-rules lists it as still open.
- Grade: necessary (the record's grade).
- State: pending.

old:
~~~
- scripts/close-commit-repair-orchestrate.py and the late-repair route (D15): kept.
~~~
new:
~~~
- The late-repair route (D15): kept; scripts/close-commit-repair-orchestrate.py, which nothing runs, goes in P1b with the repair map (P1b E3, D17).
~~~

**F-P3-06** `prompts/P3.md`:574.
- Source: finding facts-F4, plan-FIT-13; apply log C7; record: the d22c669 prompts record's Fix P3-5.
- Grade: necessary.
- State: already applied: the text below is in the file since b335a0e (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
or (P1b E8 (b)) its skeleton with `do.status` unwritten -> a gap naming `docs/dev/do-report-<task>.json` (P1b E8 removed `pending`)
~~~

**L-P3-03** `prompts/P3.md`:637-638, whole lines.
- Source: fix log r13-P1b-E5, "For the plan files" item 2 (coupled with item 1).
- Grade: necessary when recorded (no grade in the source; coupled with L-P3-02).
- State: superseded by the same in-place clause at P3.md:102 (e428c5b: acceptance 11's `commit-landing` case is listed
  as P1b's); the old still occurs once (acceptance 11), so applying it as well is harmless.

old:
~~~
    - gitignore-preflight: a dispatch whose obligation profile is `final_verification`, `do-close`, `commit-qa` or
      `commit-landing`, citing a dev-report that lists a gitignored path -> exit 0 (before: exit 2); a `singular` dev
~~~
new:
~~~
    - gitignore-preflight: a dispatch whose obligation profile is `final_verification`, `do-close`, `commit-qa` or
      `commit-landing`, citing a dev-report that lists a gitignored path -> exit 0 (before: exit 2, except a
      `commit-landing` dispatch citing its own task's report, which P1b row 11 admits); a `singular` dev
~~~

The covering text now:
~~~
its "the way the live commit grant is" means that exemption, and acceptance 11's `commit-landing` case exits 0 on your base already
~~~

**F-P3-07** `prompts/P3.md`:691-695, whole lines.
- Source: finding plan-FIT-06; record: the plan-files-only record's Fix 7.
- Grade: necessary.
- State: pending.

old:
~~~
    escalation stores (L25), journal-view (L26), completion (L23), ba-qa-report (L14: BA's write permission at
    policies/tool-policy.v1.json:129 is P1b's to drop, prompts/P1b.md row 4, else P5-a's, prompts/P5.md row 1;
    you do not edit the policy file), the canonical aggregate (L18) and terminal vocabulary (L21: remaining consumers
    import obligation.TERMINAL_VOCABULARY; a private set left in a file this phase may not edit is listed with the
    phase that deletes it).
~~~
new:
~~~
    and every other artifact your rows still change, measured on your base (P1b's D24 table, covering L25, L26, L23,
    L14, L18 and L21, is the before: verify each; L14: BA's write permission at policies/tool-policy.v1.json:129 is
    P1b's to drop, prompts/P1b.md row 4, else P5-a's, prompts/P5.md row 1, and you do not edit the policy file; L21: a
    private terminal set left in a file this phase may not edit is listed with the phase that deletes it).
~~~

**Accounted for, no text:**

- Fix log r13-P1b-E5: P3.md:130 and :148 stay true after P3. No change.
- round-17 P1b records section 1 (lane row6e5): P3.md row 13 already names `has_live_commit_grant`. No text.

#### prompts/P4.md

**F-P4-01** `prompts/P4.md`:42.
- Source: finding plan-FIT-22; record: the plan-files-only record's Fix 27.
- Grade: necessary.
- State: already applied: the text below is in the file since b335a0e (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
`git show origin/master:hooks/lib/obligation.py` contains the declaring-dispatch reader (P1b E3; use the name P1b's
~~~

**F-P4-02** `prompts/P4.md`:46-47, whole lines.
- Source: finding owner-R20 (refuter B); apply log V11 item 6; record: the d22c669 prompts record's Fix P4-1.
- Grade: necessary.
- State: pending.

old:
~~~
- If any check fails, stop and tell the owner that P4 starts only after P1, P8, P7b, P1b, P1c, P2 and P3 are merged. Do not
  start from an older base.
~~~
new:
~~~
- If any check fails, stop and tell the reviewer in your session output (never the owner) that P4 starts only after
  P1, P8, P7b, P1b, P1c, P2 and P3 are merged. Do not start from an older base.
~~~

**F-P4-03** `prompts/P4.md`:74, whole line.
- Source: finding format-FH-6, owner-R5; apply log W1 item 3; record: the d22c669 prompts record's Fix P4-2.
- Grade: necessary.
- State: pending.

old:
~~~
(D25: "永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"). For this phase:
~~~
new:
~~~
(D25: "还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！").
For this phase:
~~~

**F-P4-04** `prompts/P4.md`:88.
- Source: finding plan-FIT-22; record: the plan-files-only record's Fix 28.
- Grade: necessary.
- State: superseded by the in-place text below, in the file since fa5659d (recorded MOOT at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The covering text now:
~~~
says P3's reader or P3 row 1, it means this one, which P3 consumes, under the name P1b's PR gives); the D24 table for
~~~

**F-P4-05** `prompts/P4.md`:88.
- Source: finding plan-FIT-22; record: the plan-files-only record's Fix 29.
- Grade: necessary.
- State: superseded by the in-place text below, in the file since fa5659d (recorded MOOT at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The covering text now:
~~~
says P3's reader or P3 row 1, it means this one, which P3 consumes, under the name P1b's PR gives); the D24 table for
~~~

**F-P4-06** `prompts/P4.md`:88.
- Source: finding plan-FIT-22; record: the plan-files-only record's Fix 30.
- Grade: necessary.
- State: superseded by the in-place text below, in the file since fa5659d (recorded MOOT at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The covering text now:
~~~
says P3's reader or P3 row 1, it means this one, which P3 consumes, under the name P1b's PR gives); the D24 table for
~~~

**F-P4-07** `prompts/P4.md`:94.
- Source: finding plan-FIT-05; apply log C12 item 3; record: the d22c669 prompts record's Fix P4-3.
- Grade: necessary.
- State: already applied: the text below is in the file since b335a0e (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
returns one, or, when that step names no role, the step run by the /close or /commit main agent itself under the same task id
~~~

**F-P4-08** `prompts/P4.md`:94.
- Source: finding faithful F-5, F-7 (round r1 report faithful-P1b); FR2-1, FR2-2 (round r2 report faithful-rules-P1b);
  record: fix log r1-P1b-reader "For the plan files" (P4.md:93-94), extended and superseded by fix log r2-P1b-routes
  "P4.md" item 1; round r2 report faithful-rules-P1b, line 250.
- Grade: necessary.
- State: already applied: the text below is in the file since b335a0e (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
a /do task's do-report gap keeps the base's route, close.md:414, dev dispatched again under the same task id, never /do's Step 5)
~~~

**L-P4-01** `prompts/P4.md`:95.
- Source: fix log r13-P1b-row10, P4-R13-4 (a new item there; r19-P1c-row10 says r13's P4.md records stand).
- Grade: necessary (no grade in the source; it names P1b row 10's route for a product file no dispatch of the task
  wrote).
- State: already applied in substance by e428c5b (P4.md:95); the old no longer occurs and the new is not used.

old (no longer occurs):
~~~
writer (for a file a /do task's main agent wrote, along the do-report's route); Goals 1-2 and rows 2 and 5 keep each of these routes.
~~~
new (not used):
~~~
writer (for a file a /do task's main agent wrote, along the do-report's route; for one no dispatch of the task wrote, to the close-QA or commit-QA round that named it, through that round's own report as E3 routes a finding that cites no artifact); Goals 1-2 and rows 2 and 5 keep each of these routes.
~~~

The text that shows it now:
~~~
or whose only path is a product file no dispatch of the task wrote, back to that round's own QA dispatch
~~~

**F-P4-D21-1** `prompts/P4.md`:120.
- Source: finding owner-R1 (its open note). Records: apply log C2 Notes, apply log C12, the d22c669 prompts record
  "Notes recorded without a fix (P4)", fix log r1-P1b-reader, the c33ca28 prompts record "Not carried"; amended by
  P4-R13-1 (fix log r13-P1b-row10, after P1b row 10 gained a route for a product file no dispatch wrote; r19-P1c-row10
  says r13's P4.md records stand): the later record's new text is shown.
- Grade: necessary.
- State: already applied in substance by e428c5b (P4.md:120); "dev when none" and "falls back to dev" no longer occur
  in P4.md. e428c5b's wording follows P4-R13-1 (that close-QA round's own QA dispatch, no default role); the old no
  longer occurs and neither new text is used.

old (no longer occurs):
~~~
   Close-QA findings go to the subagent the attribution journal records as the file's writer, dev when none
~~~
new (not used):
~~~
   Close-QA findings go to the subagent the attribution journal records as the file's writer, or, when none is
   recorded, along P1b row 10's route for the file (a /do task's do-report route; otherwise, as for a gap above, the
   dispatch the declaring-dispatch reader returns for that close-QA round's own report; no default role, D21)
~~~

The text that shows it now:
~~~
back to that close-QA round's own QA dispatch through its report, with no default role (P1b E3, row 10)
~~~

**F-P4-09** `prompts/P4.md`:127.
- Source: finding faithful F-5, F-7; FR2-1, FR2-2; record: fix log r1-P1b-reader (P4.md Goal 1 and Goal 2 insert),
  superseded by fix log r2-P1b-routes "P4.md" item 2.
- Grade: necessary.
- State: already applied: the text below is in the file since b335a0e (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
or, when that step names no role, /commit's main agent runs it itself under the same task id (P1b row 10)
~~~

**F-P4-10** `prompts/P4.md`:251.
- Source: finding facts-F4, plan-FIT-13; apply log C7; record: the d22c669 prompts record's Fix P4-4.
- Grade: necessary.
- State: already applied: the text below is in the file since b335a0e (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
Q7 (a /do-origin task with no completed do-report, P1b E8: Step 0 dispatches dev again
~~~

**F-P4-11** `prompts/P4.md`:296, part of line.
- Source: finding FR2-1, FR2-2 (round r2 report faithful-rules-P1b); record: fix log r2-P1b-routes "P4.md" item 3 (scope
  row 1, third cell).
- Grade: necessary.
- State: pending.

old:
~~~
(the canonical aggregate's producer is the lane-completeness hook, whose path P2 fixed; a missing or stale aggregate is a gap like any other, facts only, D21)
~~~
new:
~~~
(the canonical aggregate's producer is the one P1b's E5 kept, the lane-completeness hook or /dev Step 11; a missing or stale aggregate is a gap like any other, facts only, D21, which the re-dispatch returns to that producer as P1b row 10 does)
~~~

**F-P4-12** `prompts/P4.md`:297, part of line.
- Source: finding facts-F6 (refuter B); apply log C2; record: the d22c669 prompts record's Fix P4-6.
- Grade: optional.
- State: pending.

old:
~~~
mapping rows, source_check list and the closed cause set :276-280;
~~~
new:
~~~
mapping rows, source_check list and the closed cause set :276-280 (the mapping rows and the "no code table" claim only if P1b left them);
~~~

**F-P4-13** `prompts/P4.md`:300, part of line.
- Source: finding facts-F6 (refuter B); apply log C2; record: the d22c669 prompts record's Fix P4-7.
- Grade: optional.
- State: pending.

old:
~~~
"### Artifact-to-role routing and the awaiting-input line" :80-142 (artifact_role :100-117,
~~~
new:
~~~
"### Artifact-to-role routing and the awaiting-input line" :80-142 (artifact_role :100-117 and its prose copies, if P1b left them;
~~~

**L-P4-04** `prompts/P4.md`:306, part of line.
- Source: round-16 P1b records 2.2 (lane disclosure), repeated in fix log r16-P1b-apply; round r17b faithful-rules lists
  it as still open.
- Grade: optional (the record's grade).
- State: pending.
- Note: Row 11 (scripts/todo/close.py); the row stays one line and gains no `|`.

old:
~~~
Delete the forced list and `_is_forced`.
~~~
new:
~~~
Delete the forced list and `_is_forced`; keep the `--late-repair` list P1b's row 6 adds (finalize's step, which P1b E3's reader returns for the effective report).
~~~

**F-P4-D21-2** `prompts/P4.md`:325.
- Source: the same records as F-P4-D21-1; amended by P4-R13-2 (fix log r13-P1b-row10, after P1b row 10 gained a route
  for a product file no dispatch wrote; r19-P1c-row10 says r13's P4.md records stand): the later record's new text is
  shown.
- Grade: necessary.
- State: already applied in substance by e428c5b (P4.md:324-325); "dev when none" and "falls back to dev" no longer
  occur in P4.md. e428c5b's wording follows P4-R13-2 (that close-QA round's own QA dispatch, no default role); the old
  no longer occurs and neither new text is used.

old (no longer occurs):
~~~
- **Close-QA findings.** Dispatch the subagent the attribution journal records as each named file's writer (dev when
  none), re-run `--disposition --stage dev`, then a fresh close-QA round. No include. [INFERRED; decide by sandbox
~~~
new (not used):
~~~
- **Close-QA findings.** Dispatch the subagent the attribution journal records as each named file's writer (when none
  is recorded, P1b row 10's route for the file: a /do task's do-report route, otherwise the dispatch the
  declaring-dispatch reader returns, as in Step 0, for that close-QA round's own report; no default role, D21), re-run
  `--disposition --stage dev`, then a fresh close-QA round. No include. [INFERRED; decide by sandbox
~~~

The text that shows it now:
~~~
  none: that close-QA round's own QA dispatch through its report, with no default role, P1b E3 and row 10;
~~~

**F-P4-D21-3** `prompts/P4.md`:330.
- Source: the same records as F-P4-D21-1; amended by P4-R13-3 (fix log r13-P1b-row10, after P1b row 10 gained a route
  for a product file no dispatch wrote; r19-P1c-row10 says r13's P4.md records stand): the later record's new text is
  shown.
- Grade: necessary.
- State: already applied in substance by e428c5b (P4.md:329-330); "dev when none" and "falls back to dev" no longer
  occur in P4.md. e428c5b's wording follows P4-R13-3 (that close-QA round's own QA dispatch, no default role); the old
  no longer occurs and neither new text is used.

old (no longer occurs):
~~~
  second, the route falls back to dev, keep the journal route; otherwise dispatch again the declaring dispatch of each
  file a close-QA finding names (the declaring-dispatch reader, as in Step 0), dev when none, and record the miss.]
~~~
new (not used):
~~~
  second, the route is P1b row 10's (that close-QA round's own dispatch, which the declaring-dispatch reader returns
  for the round's report), keep the journal route; otherwise dispatch again the declaring dispatch of each file a
  close-QA finding names (the declaring-dispatch reader, as in Step 0), and record the miss. A file the reader answers
  nothing for takes P1b row 10's route; one that route gives no dispatch is a miss handled as in acceptance 4's case
  of a task whose lane QA was never dispatched (no table, no default role, no local workaround, D21).]
~~~

The text that shows it now:
~~~
that round's own QA dispatch when none (P1b E3), and record the miss.]
~~~

**L-P4-02** `prompts/P4.md`:337, part of line.
- Source: round-15 P1b records 2.1 (lane disclosure).
- Grade: optional (the record's grade).
- State: superseded by round-16 P1b records 2.1 (L-P4-03), which says so; same old.

old:
~~~
artifact: dispatch again its declaring dispatch, then re-run `verify-disclosure`.
~~~
new:
~~~
artifact: dispatch again its declaring dispatch, then run `finalize` and `verify-disclosure` again (P1b's row 6:
  no stage report is compared, and a stage the route runs again is recorded again).
~~~

**L-P4-03** `prompts/P4.md`:337, part of line.
- Source: round-16 P1b records 2.1 (lane disclosure), repeated in fix log r16-P1b-apply; round r17b faithful-rules lists
  it as still open.
- Grade: optional (the record's grade).
- State: pending.
- Note: The old starts mid-line 337, after the line's two-space indent; the new lines keep that indent.

old:
~~~
artifact: dispatch again its declaring dispatch, then re-run `verify-disclosure`.
~~~
new:
~~~
artifact: dispatch again its declaring dispatch (for the effective report, finalize's own step, which the main
  agent runs; P1b's row 6), then run `finalize` and `verify-disclosure` again (P1b's row 6: no stage report is
  compared, a stage the route runs again is recorded again, and finalize checks the effective report it writes).
~~~

**F-P4-14** `prompts/P4.md`:530-532, whole lines.
- Source: finding plan-FIT-20 (refuter A); apply log W12 item 10; record: the d22c669 prompts record's Fix P4-9.
- Grade: optional.
- State: pending.

old:
~~~
- P9's work (D9a retirement): scripts/score-update.sh, score-inject.sh, close-scoring-decide.py,
  lifecycle-baseline-import.sh, the score shell tests, dev.md's injection, Step 14 scoring and score table, the agents'
  echo contracts, style-inspector.md:339, OPTIONS_XML in hooks/pretool-orchestrator-prompt-purity.py,
~~~
new:
~~~
- P9's work (D9a retirement): scripts/score-update.sh, score-inject.sh, close-scoring-decide.py
  (lifecycle-baseline-import.sh goes in P1b), the score shell tests, dev.md's injection, Step 14 scoring and score
  table, the agents' echo contracts, style-inspector.md:339, OPTIONS_XML in hooks/pretool-orchestrator-prompt-purity.py,
~~~

**F-P4-15** `prompts/P4.md`:623, part of line.
- Source: finding owner-R4 (refuter B, adapted); apply log D4; record: the d22c669 prompts record's Fix P4-10.
- Grade: optional.
- State: pending.

old:
~~~
failed" text and no AWAITING_INPUT line;
~~~
new:
~~~
failed" text and no AWAITING_INPUT line (P1c's F8 replays this in CI and stays green);
~~~

**F-P4-16** `prompts/P4.md`:634.
- Source: finding facts-F4, plan-FIT-13; apply log C7; record: the d22c669 prompts record's Fix P4-12.
- Grade: necessary.
- State: already applied: the text below is in the file since b335a0e (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
- a /do-origin task with no completed do-report (Q7; P1b E8 removed `pending`)
~~~

**F-P4-17** `prompts/P4.md`:639, part of line.
- Source: finding owner-R4 (refuter B, adapted); apply log D4; record: the d22c669 prompts record's Fix P4-11.
- Grade: optional.
- State: pending.
- Note: e428c5b and bb56fe5 appended routes after the anchor on :639; the anchor is part of the line, as recorded.

old:
~~~
id, the disposition is re-run, a fresh close-QA round lands;
~~~
new:
~~~
id, the disposition is re-run, a fresh close-QA round lands (P1c's F8p);
~~~

**Accounted for, no text:**

- round-16 P1b records 2.3: P4.md:209 (D15, "unchanged behaviour") still holds. No change.
- round-12 P1b records 2.5: P4 row 3 (P4.md:298) already deletes close.md:567, which P1b row 10's deletion matches. No
  change.

#### prompts/P5.md

**F-P5-01** `prompts/P5.md`:54-55.
- Source: finding plan-FIT-22; record: the plan-files-only record's Fix 31.
- Grade: necessary.
- State: already applied: the text below is in the file since b335a0e (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
contains the declaring-dispatch reader (P1b E3; use the name P1b's
    PR gives) (P3, P1b);
~~~

**F-P5-02** `prompts/P5.md`:59-60, whole lines.
- Source: finding owner-R20 (refuter B); apply log V11 item 6; record: the d22c669 prompts record's Fix P5-1.
- Grade: necessary.
- State: pending.

old:
~~~
- If any check fails, stop and tell the owner that P5 starts only after P1, P8, P7b, P1b, P1c, P2, P3 and P4 are merged. Do not
  start from an older base.
~~~
new:
~~~
- If any check fails, stop and tell the reviewer in your session output (never the owner) that P5 starts only after
  P1, P8, P7b, P1b, P1c, P2, P3 and P4 are merged. Do not start from an older base.
~~~

**F-P5-03** `prompts/P5.md`:89, whole line.
- Source: finding format-FH-6, owner-R5; apply log W1 item 3; record: the d22c669 prompts record's Fix P5-2.
- Grade: necessary.
- State: pending.

old:
~~~
(D25: "永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"). For this phase:
~~~
new:
~~~
(D25: "还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！").
For this phase:
~~~

**F-P5-04** `prompts/P5.md`:95.
- Source: finding plan-FIT-22; record: the plan-files-only record's Fixes 32, 33, 34, 36, 37.
- Grade: necessary.
- State: superseded by the in-place text below, in the file since fa5659d (recorded MOOT at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The covering text now:
~~~
this prompt says P3's reader or P3 row 1, it means this one, under the name P1b's PR gives); row 11 deletes the
~~~

**F-P5-05** `prompts/P5.md`:100.
- Source: finding facts-F4, plan-FIT-13 (apply log C7); for P5-7 also feasible-H1 (apply log C4, apply log V14); record:
  the d22c669 prompts record's Fixes P5-4, P5-5, P5-6, P5-7, P5-9, P5-10 (C7, with C4 and V14 for P5-7).
- Grade: necessary.
- State: superseded by the in-place text below, in the file since f65290d (recorded MOOT at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The covering text now:
~~~
rows 15 and 21 build on it), with `pending` gone from the `do.status` enum (P1b correction 8): where rows 15 and 21,
~~~

**F-P5-06** `prompts/P5.md`:106.
- Source: finding plan-FIT-05 (apply log C12 item 4) and plan-FIT-12 (apply log W10 item 1); record: the d22c669 prompts
  record's Fix P5-3 (C12 item 4 with W10 item 1).
- Grade: necessary.
- State: already applied: the text below is in the file since f65290d (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
hooks/lib/command_span.py for any transcript path, if P1b's E6 took the CLI-recorded write set (row 8's
~~~

**F-P5-07** `prompts/P5.md`:114.
- Source: finding FR15-2 = RA15-1 (round r15); record: fix log r15-P1c-FR15-2 record 1 (= round r15 report
  refs-acceptance-P1c RA15-1 (b) and round r15 report faithful-rules-P1c FR15-2); supersedes the "not needed" note on
  P5.md:114-115 in fix log r14-P1c-RA14-1; round r16 report faithful-rules-P1c observation 3 confirms it is still open.
- Grade: necessary.
- State: already applied in substance by e428c5b (P5.md:114-115 now read "a recurring CronCreate of the wake's text in
  the span"); the old no longer occurs and the new is not used.

old (no longer occurs):
~~~
completes only after a CronCreate or ScheduleWakeup
  call in the span (P1c row 17, X8)
~~~
new (not used):
~~~
completes only after a recurring CronCreate of the
  wake's text in the span (P1c row 17, X8)
~~~

The text that shows it now:
~~~
completes only after a recurring CronCreate of the wake's
~~~

**F-P5-08** `prompts/P5.md`:115.
- Source: finding RA9-4 (round r9 report refs-acceptance-P1c); record: fix log r9-P1c RA9-4 (round r9 report
  refs-acceptance-P1c; P5.md:113-117) with its "Note for the P5 lane"; round r10 report faithful-rules-P1c :63.
- Grade: necessary.
- State: already applied: the text below is in the file since b335a0e (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
row 18's rewrite keeps both rules and P1c row 17's one pairing rule (each todo pairs with the canonical step of the same content, never of the same index
~~~

**L-P5-01** `prompts/P5.md`:265, part of line.
- Source: fix log r17-P1b-spec-coverage, "Records for other plan files" item 2, carried by round-17 P1b records 2.2
  ("still apply unchanged"); round r17b faithful-rules lists it as still open.
- Grade: necessary (the record's grade).
- State: pending.

old:
~~~
path, the coverage phase for /spec, auto-commit and cleanup all keep working.
~~~
new:
~~~
path, the /spec coverage rule (G2 at the spec subagent's stop since P1b row 8), auto-commit and cleanup all keep working.
~~~

**F-P5-09** `prompts/P5.md`:341.
- Source: finding plan-FIT-12; apply log W10 item 2; record: the d22c669 prompts record's Fix P5-11 (W10 item 2).
- Grade: necessary.
- State: superseded by the in-place text below, in the file since b335a0e (recorded MOOT at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The covering text now:
~~~
Record the counts. There is no prefix-row fallback, and no prefix row that names a file comes back
~~~

**L-P5-02** `prompts/P5.md`:350, part of line.
- Source: fix log r17-P1b-spec-coverage, "Records for other plan files" item 5, carried by round-17 P1b records 2.5
  ("still apply unchanged"); round r17b faithful-rules lists it as still open.
- Grade: optional (the record's grade).
- State: pending.
- Note: Row 9.

old:
~~~
only coverage and completion may block
~~~
new:
~~~
only coverage (P1b's exit-0 stub, so in effect none) and completion may block
~~~

**F-P5-10** `prompts/P5.md`:354, part of line.
- Source: finding FR15-1; record: fix log r15-P1c-FR15-1 record 6.
- Grade: necessary.
- State: superseded by the in-place clause e428c5b added at P5.md:117 (row 13's stop.md rewrite keeps the wake's
  CronDelete); the old still occurs once (row 13), so applying it as well is harmless.

old:
~~~
break-overnight-lock.py may record `terminal_status=cancelled_by_user` for the summary, which no gate reads.
~~~
new:
~~~
break-overnight-lock.py may record `terminal_status=cancelled_by_user` for the summary, which no gate reads; stop.md's last step stays the CronDelete of P1c's wake (P1c X8).
~~~

The covering text now:
~~~
row 13's stop.md rewrite keeps stop.md's last step, the wake's CronDelete.
~~~

**F-P5-11** `prompts/P5.md`:362, part of line.
- Source: finding facts-F4, plan-FIT-13; apply log C7; record: the d22c669 prompts record's Fix P5-8 (C7).
- Grade: necessary.
- State: pending.

old:
~~~
do.md :51; the skeleton message :1434-1437;
~~~
new:
~~~
do.md :51; the skeleton message :1434-1437 (only if P1b E8 kept the skeleton, its candidate (b));
~~~

**F-P5-12** `prompts/P5.md`:374, whole line.
- Source: finding FR15-1 (with RA14-1); record: fix log r15-P1c-FR15-1 record 5 (the new place of fix log r14-P1c-RA14-1
  record 4's rule).
- Grade: necessary.
- State: superseded by the in-place clause at P5.md:117 (e428c5b): the gate (row 7) keeps X8's wake check after
  end_time and after /stop; the old still occurs once (gate step 4), so applying it as well is harmless.

old:
~~~
   `overnight window open until <end_time>; continue the remaining pipelines` (TC-12).
~~~
new:
~~~
   `overnight window open until <end_time>; continue the remaining pipelines` (TC-12). Once the window is closed, P1c's
   undeleted wake (a CronCreate of its text in the session's transcript whose id no later CronDelete names) -> block
   naming that id, in both modes, whatever the span but /dev-overnight's, whose predicate checks it after
   `closeout_gaps` (P1c X8; the orchestrator's own CronDelete clears it).
~~~

The covering text now:
~~~
keeps X8's wake check as P2 left it in the time-lock
~~~

**F-P5-13** `prompts/P5.md`:406-410, whole lines.
- Source: finding FR15-1 (with RA14-1); record: fix log r15-P1c-FR15-1 record 4 (supersedes fix log r14-P1c-RA14-1
  record 4).
- Grade: necessary.
- State: superseded by the same in-place clause at P5.md:117 (e428c5b), which covers the /dev-overnight predicate's
  Stop after end_time; the old still occurs once, so applying it as well is harmless.

old:
~~~
  `state.worktree_path`); P2's `closeout_gaps` empty. An unanswered producer-question file inside the span is the
  disposition's fact gap (problem=unanswered for that path, printed exactly as P3 reports it); the orchestrator clears
  it itself (an experiment when one can be run, else the question's default, recorded; [INFERRED, D20/ON9; decided by
  P2's acceptance 14 unattended-decision replay and re-checked here by acceptances 12 and 20 (arm-overnight: 0
  AskUserQuestion calls, the decision recorded)]) and re-dispatches the role. No landing step (D6a).
~~~
new:
~~~
  `state.worktree_path`); P2's `closeout_gaps` empty; then P1c's wake deleted (step 4's wake check). An unanswered
  producer-question file inside the span is the disposition's fact gap (problem=unanswered for that path, printed
  exactly as P3 reports it); the orchestrator clears it itself (an experiment when one can be run, else the question's
  default, recorded; [INFERRED, D20/ON9; decided by P2's acceptance 14 unattended-decision replay and re-checked here by
  acceptances 12 and 20 (arm-overnight: 0 AskUserQuestion calls, the decision recorded)]) and re-dispatches the role. No
  landing step (D6a).
~~~

The covering text now:
~~~
keeps X8's wake check as P2 left it in the time-lock
~~~

**F-P5-14** `prompts/P5.md`:448.
- Source: finding plan-FIT-22; record: the plan-files-only record's Fix 35.
- Grade: necessary.
- State: already applied: the text below is in the file since fa5659d (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
P1b's declaring-dispatch replay, P1b acceptance 7 (its canonical-todo-step case; P3 acceptance 8 reruns the reader),
~~~

**L-P5-03** `prompts/P5.md`:607, whole line.
- Source: fix log r17-P1b-spec-coverage, "Records for other plan files" item 3, carried by round-17 P1b records 2.3
  ("still apply unchanged"); round r17b faithful-rules lists it as still open.
- Grade: necessary (the record's grade).
- State: pending.

old:
~~~
- The /spec coverage phase (bounded, outside D4) and graphify dispatches: unchanged.
~~~
new:
~~~
- Graphify dispatches: unchanged. The /spec coverage phase is P1b's exit-0 stub (P1b row 8 moved its rule to G2 at the spec subagent's stop): leave it.
~~~

**F-P5-15** `prompts/P5.md`:747-749, whole lines.
- Source: finding FR15-3 (round r15 report faithful-rules-P1c); record: fix log r15-P1c-FR15-3 record 9 (acceptance 12,
  "Time-lock").
- Grade: necessary.
- State: pending.
- Note: P5.md:117 (e428c5b) states the wake rule; acceptance 12 still has no case for it.

old:
~~~
    question file after end_time -> rc 2 until that family is chain_pass; every family passes and closeout is complete
    -> rc 0. break-overnight-lock.py touches no todos file. arm-overnight shows 0 AskUserQuestion calls and 0 parked
    families; the after-end_time block text names no AskUserQuestion.
~~~
new:
~~~
    question file after end_time -> rc 2 until that family is chain_pass; every family passes and closeout is complete
    -> rc 0. P1c's wake (X8): with a CronCreate of the wake's text in the transcript whose id no later CronDelete names,
    that Stop and the Stop after a human /stop record -> rc 2 naming that id, and rc 0 once a CronDelete names it.
    break-overnight-lock.py touches no todos file. arm-overnight shows 0 AskUserQuestion calls and 0 parked families;
    the after-end_time block text names no AskUserQuestion.
~~~

**L-P5-04** `prompts/P5.md`:753, part of line.
- Source: fix log r17-P1b-spec-coverage, "Records for other plan files" item 4, carried by round-17 P1b records 2.4
  ("still apply unchanged"); round r17b faithful-rules lists it as still open.
- Grade: necessary (the record's grade).
- State: pending.
- Note: Acceptance 13.

old:
~~~
A /spec coverage block -> rc 2 as before.
~~~
new:
~~~
The /spec coverage phase, P1b's exit-0 stub, allows (rc 0).
~~~

**F-P5-16** `prompts/P5.md`:841.
- Source: finding RA5-1 (round r5 report refs-acceptance-P1b); record: fix log r5-P1b RA5-1 "For the plan files"
  (prompts/P5.md:839; = round r5 report refs-acceptance-P1b fix item 4).
- Grade: necessary.
- State: already applied: the text below is in the file since b335a0e (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
- stop-do-report-gate's MAX_BLOCKS force-allow and its block (its `blocked` rewrite of the agent's report went with `pending` in P1b row 9; P1b correction 8);
~~~

#### prompts/P6.md

**F-P6-01** `prompts/P6.md`:49-50, whole lines.
- Source: finding owner-R20 (refuter B); apply log V11 item 6; record: the d22c669 prompts record's Fix P6-1.
- Grade: necessary.
- State: pending.

old:
~~~
- If any check fails, stop and tell the owner that P6 starts only after P1, P8, P7b, P1b, P1c, P2, P3, P4 and P5 are merged. Do
  not start from an older base.
~~~
new:
~~~
- If any check fails, stop and tell the reviewer in your session output (never the owner) that P6 starts only after
  P1, P8, P7b, P1b, P1c, P2, P3, P4 and P5 are merged. Do not start from an older base.
~~~

**F-P6-02** `prompts/P6.md`:66-68, whole lines.
- Source: finding plan-FIT-22; record: the plan-files-only record's Fix 38.
- Grade: necessary.
- State: pending.

old:
~~~
  agent has no role), and the release-input denies (the CLI transcripts, any G2 escalation records P3 left, the /do
  sidecar, the overlay, the private-literal list) that make the transcript a trustworthy input. The /do Q7 route trusts
  the G2-verified dev-report's file lists; your A3.a check is what makes that trust correct.
~~~
new:
~~~
  agent has no role), and the release-input denies (the CLI transcripts, any G2 escalation records P1b and P1c left, the
  /do sidecar, the overlay, the private-literal list) that make the transcript a trustworthy input. The /do Q7 route
  trusts the G2-verified dev-report's file lists; your A3.a check is what makes that trust correct.
~~~

**F-P6-03** `prompts/P6.md`:83, whole line.
- Source: finding format-FH-6, owner-R5; apply log W1 item 3; record: the d22c669 prompts record's Fix P6-2.
- Grade: necessary.
- State: pending.

old:
~~~
(D25: "永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"). For this phase:
~~~
new:
~~~
(D25: "还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！").
For this phase:
~~~

**F-P6-04** `prompts/P6.md`:88.
- Source: finding plan-FIT-05; apply log C12 item 1; record: the d22c669 prompts record's Fix P6-3 (C12 item 1,
  re-anchored there from sync P6-4).
- Grade: necessary.
- State: already applied: the text below is in the file since f65290d (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
matched it; never dev's self-report) and of the baseline. It kept G2's `_wire_ledger_judgment` with the
~~~

**F-P6-05** `prompts/P6.md`:350, part of line.
- Source: finding owner-R11; apply log C4; record: the d22c669 prompts record's Fix P6-4.
- Grade: optional.
- State: pending.

old:
~~~
(not only when it is in `obligation.ROLES`)
~~~
new:
~~~
(not only when the active command's declaration names it, P1b row 18)
~~~

**L-P6-01** `prompts/P6.md`:417-418, whole lines.
- Source: round-12 P1b records 2.1 (lane row8; cited there as :416-418, the old being on :417-418).
- Grade: conditional (the record's own condition): necessary if P1b's replay drops agent_resolver's cp-state read (P1b
  row 8's one rule for cp-state, a technical choice), else optional.
- State: pending.

old:
~~~
  new prompts add no agent-index entry, so such a subagent gets a role only from a cp-state Read (row 2 keeps that
  check-in) and otherwise none, as an unregistered agent does on origin/master; say so in the PR.
~~~
new:
~~~
  new prompts add no agent-index entry, so such a subagent gets a role only from a cp-state match, where P1b row 8
  kept agent_resolver's cp-state read, and otherwise none, as an unregistered agent does on origin/master; say so in
  the PR.
~~~

**F-P6-06** `prompts/P6.md`:510-512, whole lines.
- Source: finding the qa-arming aside of fix log r10-P1b-A03 (round r6inv report inventory observation 5); record: fix
  log r10-P1b-qa-arming "Records for other plan files" (P6.md:509-511); the orchestrator's running notes; round r11b
  report faithful-rules-P1b, line 140.
- Grade: optional.
- State: pending.
- Note: The record's plan-file note stands: the premise that a FIRST ACTION Read of a missing file registers no
  sentinel is unverified; P6's row 1 replay decides it (D18).

old:
~~~
    ACTION registration. /commit's commit-QA and changelog-analyst prompts and the /do-path inspectors have no
    resolvable FIRST ACTION sentinel, so their roles stay unresolved and tool-policy allows. Row 1 (A4.a) is this
    fix.
~~~
new:
~~~
    ACTION registration. /commit's commit-QA and changelog-analyst prompts, the /do-path inspectors and, after P1b
    deletes /close's QA arming (its only writer there), the /do-path close QA have no resolvable FIRST ACTION sentinel,
    so their roles stay unresolved and tool-policy allows. Row 1 (A4.a) is this fix.
~~~

**F-P6-07** `prompts/P6.md`:760.
- Source: finding plan-FIT-19; apply log W11; record: the d22c669 prompts record's Fix P6-5 (W11).
- Grade: necessary.
- State: already applied: the text below is in the file since c728380 (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
    dev's rewrite), a syntax-broken harness hook (F3.a, Goal 4), and a grant claimed by the wrong role.
~~~

**F-P6-07a** `prompts/P6.md`:760, whole line.
- Source: the optional wording the c33ca28 prompts record gave with F-P6-07 (the d22c669 prompts record's Fix P6-5,
  W11).
- Grade: optional.
- State: pending.

old:
~~~
    dev's rewrite), a syntax-broken harness hook (F3.a, Goal 4), and a grant claimed by the wrong role.
~~~
new:
~~~
    dev's rewrite), a syntax-broken harness hook (this prompt's F3.a predicate, Goal 4, not P1c's fault F3a), and a
    grant claimed by the wrong role.
~~~

**Accounted for, no text:**

- round-12 P1b records 2.1, observation: P6 row 2 (P6.md:349) calls pretool-cp-checkin.py's cp-state check-in
  "unchanged", but P1b row 8 deletes that hook's cp-state payload writes; left "for the P6 sync". No text.
- Fix log r11inv-A70: P6.md:321 and :636 name the lock's /tmp path, which is still right. No change.

#### prompts/P7b.md (phase merged; optional)

**F-P7b-01** `prompts/P7b.md`:50-51, whole lines.
- Source: finding owner-R20 (refuter B); apply log V11 item 6; record: the d22c669 prompts record's Fix P7b-1.
- Grade: optional.
- State: pending.

old:
~~~
`git cat-file -e origin/master:settings.machine.example.json`. If either fails, stop and tell the owner that P7b
starts only after P7 is merged. Your acceptance tests check out the pre-P7 revisions
~~~
new:
~~~
`git cat-file -e origin/master:settings.machine.example.json`. If either fails, stop and tell the reviewer in your
session output (never the owner) that P7b starts only after P7 is merged. Your acceptance tests check out the pre-P7
revisions
~~~

**Accounted for, no text:**

- Fix log r17-P1b-spec-coverage: P7b.md:220 records a merged phase. No change.

#### prompts/P8.md (phase merged; optional)

**F-P8-01** `prompts/P8.md`:40, whole line.
- Source: finding owner-R20 (refuter B); apply log V11 item 6; record: the d22c669 prompts record's Fix P8-1.
- Grade: optional.
- State: pending.

old:
~~~
fails, stop and tell the owner that wave 2 starts only after P0 and P7 are merged; do not start on a pre-P7 master.
~~~
new:
~~~
fails, stop and tell the reviewer in your session output (never the owner) that wave 2 starts only after P0 and P7 are
merged; do not start on a pre-P7 master.
~~~

**Accounted for, no text:**

- Fix log r11inv-A63: P8.md:288 (row 5f) records the commit-grant split as a "Real defect"; the round-18b lane row11lck:
  P8.md row 5f moves the pointer template only. No text.

#### prompts/P9.md

**F-P9-01** `prompts/P9.md`:18-19, whole lines.
- Source: finding RULES-P1c-2 (round r1 report rules-P1c); fix log r1-P1c-rules; record: the d22c669 prompts record's
  Fix P9-1 (= fix log r1-P1c-rules "For the plan files"; round r1 report rules-P1c, line 59).
- Grade: necessary.
- State: pending.

old:
~~~
The owner wants every phase finished fast. Do not wait for anything except the merges above; run independent
experiments and test runs in parallel; never stop to ask.
~~~
new:
~~~
Do not wait for anything except the merges above; run independent experiments and test runs in parallel; never stop
to ask.
~~~

**F-P9-02** `prompts/P9.md`:124, whole line.
- Source: finding plan-FIT-20; apply log W12 item 1; record: the d22c669 prompts record's Fix P9-2.
- Grade: necessary.
- State: pending.

old:
~~~
   contracts, the four scripts, their shell tests, OPTIONS_XML, the score allows and allowlist entries leave together.
~~~
new:
~~~
   contracts, the three scripts P1b left (its row 15 deleted lifecycle-baseline-import.sh with its allow and test
   case), their shell tests, OPTIONS_XML, the score allows and allowlist entries leave together.
~~~

**F-P9-03** `prompts/P9.md`:212-214, whole lines.
- Source: finding plan-FIT-20; apply log W12 item 2; record: the d22c669 prompts record's Fix P9-3.
- Grade: necessary.
- State: pending.

old:
~~~
- **D17.** Code no live entry point reaches is deleted only with a reachability proof. This phase deletes the four D9a
  scripts, the two score shell tests and scripts/iterate-failed-pipelines.py (row 7) with that proof; anything else that
  loses its last caller goes to "Now unreferenced" for P10.
~~~
new:
~~~
- **D17.** Code no live entry point reaches is deleted only with a reachability proof. This phase deletes the three D9a
  scripts P1b left (P1b row 15 deleted lifecycle-baseline-import.sh), the two score shell tests and
  scripts/iterate-failed-pipelines.py (row 7) with that proof; anything else that loses its last caller goes to "Now
  unreferenced" for P10.
~~~

**F-P9-04** `prompts/P9.md`:242, part of line.
- Source: finding plan-FIT-20; apply log W12 item 3; record: the d22c669 prompts record's Fix P9-4.
- Grade: necessary.
- State: pending.

old:
~~~
lifecycle-baseline-import.sh you delete.
~~~
new:
~~~
lifecycle-baseline-import.sh P1b deleted.
~~~

**F-P9-05** `prompts/P9.md`:385, whole line.
- Source: finding plan-FIT-20; apply log W12 item 4; record: the d22c669 prompts record's Fix P9-5.
- Grade: necessary.
- State: pending.

old:
~~~
   the D9a row omits; delete all three with their scripts.
~~~
new:
~~~
   the D9a row omits; P1b row 15 deleted :40 with that script (verify it is gone); delete the other two with their
   scripts.
~~~

**F-P9-06** `prompts/P9.md`:428.
- Source: finding owner-R11; apply log C4; record: the d22c669 prompts record's Fix P9-6 (C4).
- Grade: necessary.
- State: already applied: the text below is in the file since f65290d (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
P1b row 18 then deleted ROLES itself (parse_obligation validates a role against the roster function).
~~~

**L-P9-01** `prompts/P9.md`:448, part of line.
- Source: round-13 P1b records 2 R1 (lane row15), repeated in fix log r13-P1b-apply; round r16b faithful-rules lists it
  as still open.
- Grade: necessary (no grade in the source; without it the one score-log reader P1b row 15 adds is left with no
  caller).
- State: pending.
- Note: The sentence starts and ends on :448 and the line goes on with " Rows 5"; rewrap the paragraph to about 120
  columns.

old:
~~~
Goal 3, E1 and rows 3 and 10 retire the three other D9a scripts and only what P1b's PR left of that one.
~~~
new:
~~~
Goal 3, E1 and rows 3 and 10 retire the three other D9a scripts and only what P1b's PR left of that one; row 10
  also deletes the one function P1b row 15 gave score-update.sh and score-inject.sh to read the score log's lines,
  with its tests.
~~~

**F-P9-07** `prompts/P9.md`:459.
- Source: finding RA13-2 (round r13 report refs-acceptance-P1c); record: fix log r13-P1c "For other plan files" 1 (=
  round r13 report refs-acceptance-P1c RA13-2, verbatim); round r14 report faithful-rules-P1c, line 274 (not applied
  yet).
- Grade: necessary.
- State: already applied in substance: 7beb706 named the capability's issuer, decider and takers, and e428c5b added
  the wake-after-/stop case and the scheduled-/restart clause (P9.md:458-461); the old no longer occurs and the new is
  not used.

old (no longer occurs):
~~~
**P1c's widened SendMessage exception (X8; P1c's "Hand-offs for the sync list").** P1c's row 17 widened
hooks/pretool-block-background-tasks.py's SendMessage exception from a typed /restart to a typed /restart or the
/dev-overnight session's own wake inside its span, with the same fixed message and id rule (D20). Four lines then name
~~~
new (not used):
~~~
**P1c's widened SendMessage exception (X8; P1c's "Hand-offs for the sync list").** P1c's row 17 widened
the SendMessage exception that hooks/pretool-block-background-tasks.py and the orchestrator gate take from the
/restart capability hooks/userprompt-restart-authorize.py issues, from a typed /restart to a typed /restart or the
/dev-overnight session's own wake inside its span, with the same fixed message and id rule (D20). Four lines then name
~~~

The text that shows it now:
~~~
the /restart SendMessage exception (where the /restart capability is issued, hooks/userprompt-restart-authorize.py;
~~~

**F-P9-09** `prompts/P9.md`:463.
- Source: finding plan-FIT-18, feasible-M5; apply log V3 item 1; record: the d22c669 prompts record's Fixes P9-16,
  P9-17, P9-18, P9-19, P9-20 (V3 item 1).
- Grade: necessary.
- State: superseded by the in-place text below, in the file since f65290d (recorded MOOT at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The covering text now:
~~~
and ARCHITECTURE.md:178 (lines at d625284; find each by its text). They join rows 16 and 14: state the exception as
~~~

**F-P9-08** `prompts/P9.md`:465.
- Source: finding RA13-1 (c) with FR13-2 (round r13); record: fix log r13-P1c "For other plan files" 2 (round r13 report
  refs-acceptance-P1c RA13-1 (c), adapted to FR13-2); round r14 report faithful-rules-P1c, line 274.
- Grade: necessary.
- State: already applied in substance by e428c5b (P9.md:459-465: the scheduled-/restart clause and the replay's fourth
  case); the old no longer occurs and the new is not used.

old (no longer occurs):
~~~
and ARCHITECTURE.md:178 (lines at d625284; find each by its text). They join rows 16 and 14: state the exception as
the merged hook does, backed by an E3 replay of the widened exception (an accepted wake, a refused other message, a
refused other id).
~~~
new (not used):
~~~
and ARCHITECTURE.md:178 (lines at d625284; find each by its text). They join rows 16 and 14: state the exception as
the merged hook does (where P1c's X8 records that the hook cannot tell a scheduled prompt from a typed one, any
prompt that starts with /restart also gets the capability), backed by an E3 replay of the widened exception (an
accepted wake, a refused other message, a refused other id, no capability for a wake that fires after the owner's
/stop).
~~~

The text that shows it now:
~~~
refused other id, no capability for a wake that fires after the owner's /stop).
~~~

**F-P9-10** `prompts/P9.md`:469, part of line.
- Source: finding faithful F-6 (round r1 report faithful-P1b); record: fix log r1-P1b-spec "For the plan files" new item
  3 (P9.md:451, now row 1 at :469).
- Grade: necessary.
- State: pending.

old:
~~~
else the session transcript's last Write or Edit to `docs/dev/specs/*.md` (INDEX.md and README.md excluded)
~~~
new:
~~~
else the session transcript's last Write or Edit to `docs/dev/specs/*.md` (INDEX.md and README.md excluded; a call of the spec monolith's one writer, P1b E14, naming such a file counts as such a write)
~~~

**F-P9-11** `prompts/P9.md`:471, part of line.
- Source: finding plan-FIT-20; apply log W12 item 5; record: the d22c669 prompts record's Fix P9-7.
- Grade: necessary.
- State: pending.

old:
~~~
score allows :40, :50-51 |
~~~
new:
~~~
score allows :50-51 (P1b row 15 deleted the :40 allow with its script) |
~~~

**F-P9-12** `prompts/P9.md`:471, part of line.
- Source: finding plan-FIT-20; apply log W12 item 5; record: the d22c669 prompts record's Fix P9-8.
- Grade: necessary.
- State: pending.
- Note: With it applied, P9.md:689 ("three score allows") would differ; no record gives text for :689 ("Not carried"
  below).

old:
~~~
and the three score allows.
~~~
new:
~~~
and the two score allows.
~~~

**L-P9-02** `prompts/P9.md`:473, part of line.
- Source: fix log r11inv-cites, "For the plan files" (the orchestrator's running notes: "P9.md:473 agent_types range
  record").
- Grade: optional (no grade in the source; a cite range: at P9's base f8c18c2 the list is :1514-1526).
- State: pending.
- Note: Row 5; the row stays one line.

old:
~~~
`_init_dev_registry` agent_types :1514-1518 (18)
~~~
new:
~~~
`_init_dev_registry` agent_types :1514-1526 (18)
~~~

**F-P9-13** `prompts/P9.md`:473, part of line.
- Source: finding owner-R6; apply log W7; record: the d22c669 prompts record's Fix P9-9 (W7).
- Grade: necessary.
- State: pending.
- Note: round-13 P1b records section 4 (lane row1) also observes that this line names overnight-init.sh's sentinel count
  check, which P1b row 1 deleted before round 13; no text.

old:
~~~
The prose fallback loops become "re-run the command" (or go, if P6's option made the registry sentinels inert).
~~~
new:
~~~
The prose fallback loops are gone (P1b row 1: the orchestrator uses the task id the hook recorded, or calls the hook's own start function when it recorded none).
~~~

**F-P9-14** `prompts/P9.md`:476, part of line.
- Source: finding owner-R7 (refuter B); apply log W8 item 1; record: the d22c669 prompts record's Fix P9-10.
- Grade: necessary.
- State: pending.

old:
~~~
specialists); close.md :156 ("Define these functions once"); dev.md Step 15 :1106-1178 (self-edits settings); dev-overnight.md
~~~
new:
~~~
specialists); close.md :156 ("Define these functions once"); dev-overnight.md
~~~

**F-P9-15** `prompts/P9.md`:476, part of line.
- Source: finding owner-R7 (refuter B); apply log W8 item 2; record: the d22c669 prompts record's Fix P9-11.
- Grade: necessary.
- State: pending.

old:
~~~
the design doc's two switch names follow the code; Step 15 reports suggested permissions instead of editing settings; drop
~~~
new:
~~~
the design doc's two switch names follow the code; Step 15 calls scripts/apply-permissions.sh as P1b row 16 left it; drop
~~~

**F-P9-16** `prompts/P9.md`:476, part of line.
- Source: finding owner-R6; apply log W7; record: the d22c669 prompts record's Fix P9-12.
- Grade: necessary.
- State: pending.

old:
~~~
The whole fallback block (dev.md:196-218, dev-command.md:142-150) becomes "re-run the command" (L02 docs/dev/user-requirement-<sid>.md, L03 the dev-registry agent sentinels, L05 the {e2e,codex,artifact-contract}-enforce.json flags; Correction 11's lines inside it, if still there, stay and are listed).
~~~
new:
~~~
Confirm that P1b row 1 replaced the whole fallback block (dev.md:196-218, dev-command.md:141-163; L02 docs/dev/user-requirement-<sid>.md, L03 the dev-registry agent sentinels, L05 the {e2e,codex,artifact-contract}-enforce.json flags) and that no command text asks the owner to type a command again; Correction 11's lines inside it, if still there, stay and are listed.
~~~

**F-P9-17** `prompts/P9.md`:476, part of line.
- Source: finding owner-R7 (refuter B); apply log W8 item 3; record: the d22c669 prompts record's Fix P9-13.
- Grade: necessary.
- State: pending.

old:
~~~
if P2 did not). dev-overnight.md reports suggested permissions instead of writing them (:1518-1519, L55 settings-derived files). |
~~~
new:
~~~
if P2 did not). |
~~~

**F-P9-18** `prompts/P9.md`:478, part of line.
- Source: finding plan-FIT-20; apply log W12 item 6; record: the d22c669 prompts record's Fix P9-15.
- Grade: necessary.
- State: pending.

old:
~~~
Delete the four scripts and the two shell tests with their directories, and the index rows that name them
~~~
new:
~~~
Delete the three scripts P1b left and the two shell tests with their directories (P1b row 15 deleted scripts/lifecycle-baseline-import.sh, its settings.json:40 allow and test-lifecycle-cas.sh's case (d): verify they are absent), and the index rows that name any of the four
~~~

**F-P9-19** `prompts/P9.md`:509-510, whole lines.
- Source: finding plan-FIT-20; apply log W12 item 8; record: the d22c669 prompts record's Fix P9-21.
- Grade: optional.
- State: pending.

old:
~~~
- P10's work: deleting scripts, hooks, schemas and docs that lose their last caller (except the four D9a scripts and
  iterate-failed-pipelines.py named here), the stubs and doctor's STUB-reference check, .gitignore minimisation beyond
~~~
new:
~~~
- P10's work: deleting scripts, hooks, schemas and docs that lose their last caller (except the three D9a scripts P1b
  left and iterate-failed-pipelines.py named here), the stubs and doctor's STUB-reference check, .gitignore
  minimisation beyond
~~~

**F-P9-20** `prompts/P9.md`:567.
- Source: finding owner-R11; apply log C4; record: the d22c669 prompts record's Fix P9-22 (C4).
- Grade: necessary.
- State: already applied: the text below is in the file since f65290d (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
if P6 made the registry sentinels inert, no CP_AGENTS consumer is left); no obligation.ROLES,
~~~

**F-P9-21** `prompts/P9.md`:657.
- Source: finding plan-FIT-06; record: the plan-files-only record's Fix 3.
- Grade: necessary.
- State: already applied: the text below is in the file since fa5659d (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
the forced-close flag <state>/claude-close-force-<sid>.flag (read, never written), which P1b deletes (its PR's
~~~

**F-P9-22** `prompts/P9.md`:661, part of line.
- Source: finding facts-F6 (refuter A); apply log C2; record: the d22c669 prompts record's Fix P9-23.
- Grade: necessary.
- State: pending.

old:
~~~
(close.md:278, commit.md:83-84)
~~~
new:
~~~
(close.md:278, :288, commit.md:83-84)
~~~

**F-P9-23** `prompts/P9.md`:661, part of line.
- Source: finding plan-FIT-06; record: the plan-files-only record's Fix 4.
- Grade: necessary.
- State: pending.

old:
~~~
if P4 left them.
~~~
new:
~~~
if P1b left them.
~~~

**F-P9-24** `prompts/P9.md`:665.
- Source: finding A1 (round r1 report acceptance-P1c), FP1c-r2-1 (round r2 report faithful-P1c); record: the d22c669
  prompts record's Fix P9-24 (fix log r1-P1c-A1), superseded by fix log r2-P1c-consistency (= round r2 report
  faithful-P1c FP1c-r2-1 item 3); fix log r4-P1c and fix log r5-P1c-coverage ("stays as recorded").
- Grade: necessary.
- State: already applied: the text below is in the file since f65290d (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
command or agent definition (a commands/ or agents/ file with YAML frontmatter on the base or the head) that a
~~~

**F-P9-25** `prompts/P9.md`:699-701, whole lines.
- Source: finding plan-FIT-20; apply log W12 item 7; record: the d22c669 prompts record's Fix P9-25.
- Grade: necessary.
- State: pending.

old:
~~~
Net lines in hooks/, scripts/ and schemas/ (tests excluded) must be <= -900 (PLAN-v2.md section 5). The four D9a scripts
are -1,033 lines at f8c18c2, OPTIONS_XML about -50, doc-sync's creation paths and `_maybe_regen_global` more; the spec_path
producer, has_do_consent and the option table pay for themselves. commands/, agents/, CLAUDE.md, README.md and
~~~
new:
~~~
Net lines in hooks/, scripts/ and schemas/ (tests excluded) must be <= -900 (PLAN-v2.md section 5). The three D9a
scripts P1b left are -887 lines at f8c18c2 (P1b row 15 deleted lifecycle-baseline-import.sh, 146), OPTIONS_XML about
-50, doc-sync's creation paths and `_maybe_regen_global` more; the spec_path producer, has_do_consent and the option
table pay for themselves. commands/, agents/, CLAUDE.md, README.md and
~~~

**Accounted for, no text:**

- round-15 P1b records 2.5 (lane applyperm): P9.md:451-453 is now true for a repository without the settings file. No
  change.
- round-16 P1b records 2.3 (lane e9): P9 cites E9's outcome, not its replay setup. No change.
- round-18 P1b records section 5 (lane row11): P9 row 16 already rewrites CLAUDE.md:102. No change.

#### prompts/P10.md

**F-P10-01** `prompts/P10.md`:48-49, whole lines.
- Source: finding owner-R20 (refuter B); apply log V11 item 6; record: the d22c669 prompts record's Fix P10-2.
- Grade: necessary.
- State: pending.

old:
~~~
- If any check fails, stop and tell the owner that P10 starts only after P7b, P1, P8, P1b, P1c, P2, P3, P4, P5, P6 and P9 are
  merged. Do not start from an older base.
~~~
new:
~~~
- If any check fails, stop and tell the reviewer in your session output (never the owner) that P10 starts only after
  P7b, P1, P8, P1b, P1c, P2, P3, P4, P5, P6 and P9 are merged. Do not start from an older base.
~~~

**F-P10-02** `prompts/P10.md`:57.
- Source: finding open item 2 of fix log r3-P1b-basekit; record: fix log r3-P1b-qamode "For the plan files" item 1; fix
  log r8-P1c-align "For the plan files".
- Grade: necessary.
- State: already applied: the text below is in the file since b335a0e (recorded ALREADY APPLIED at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The text that shows it now:
~~~
the registered hook files and the harness scripts it emptied to exit-0 `# STUB:` stubs and kept for you (D15)
~~~

**L-P10-01** `prompts/P10.md`:359, part of line.
- Source: round-14 P1b records 2.2 (lane e3), repeated in fix log r14-P1b-apply; round r17b faithful-rules lists it as
  still open.
- Grade: optional (the record's grade).
- State: pending.
- Note: Row 6; the new text holds no ` | `.

old:
~~~
at f8c18c2 nothing runs close-commit-repair-orchestrate.py or the repair-map engine: the proof decides, and say so in the PR.
~~~
new:
~~~
at f8c18c2 nothing runs close-commit-repair-orchestrate.py or the repair-map engine: the proof decides, and say so in the PR; P1b's E3 deletes those two scripts, schemas/repair-map.v1.json and their three tests (D17), so a base without them lists them as P1b's.
~~~

**F-P10-03** `prompts/P10.md`:360, part of line.
- Source: finding feasible-H1 (refuter B); apply log C4, apply log V14; record: the d22c669 prompts record's Fix P10-1
  (C4, V14).
- Grade: necessary.
- State: pending.

old:
~~~
TC-35 per experiment 8; the drift test between TERMINAL_VOCABULARY and the schemas stays green.
~~~
new:
~~~
TC-35 per experiment 8; TERMINAL_VOCABULARY reads its enum from the schemas (P1b), so no drift test is left.
~~~

**F-P10-04** `prompts/P10.md`:372.
- Source: finding plan-FIT-06; record: the plan-files-only record's Fix 1.
- Grade: necessary.
- State: superseded by the in-place text below, in the file since fa5659d (recorded MOOT at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The covering text now:
~~~
the qa-input reader (L56); leftover G2 escalation stores (L25); the advisory writers (L54:
~~~

**F-P10-05** `prompts/P10.md`:372.
- Source: finding plan-FIT-06; record: the plan-files-only record's Fix 2.
- Grade: necessary.
- State: superseded by the in-place text below, in the file since fa5659d (recorded MOOT at c33ca28); the c33ca28
  prompts record gave it by this line only; its old -> new is in the record it cites.

The covering text now:
~~~
the qa-input reader (L56); leftover G2 escalation stores (L25); the advisory writers (L54:
~~~

**Accounted for, no text:**

- round-14 P1b records 2.3: P10.md:54 (P1's "Out of scope, found" record) stays; P10.md:56-57 says "What P1b deleted is
  not yours to delete again". No text.
- round-18 P1b records section 5 (plan-FIT-16): P10.md:55 names scripts/update-overnight-state.sh `--inc-fail` from P1's
  PR, a script P1b's E13 deletes. No record gives P10 text (plan-FIT-16's prompt text is F-P2-07); P10.md:56-57 covers
  it.
- round-12 P1b records 2.5: P10's guard-integrity cite (P10.md:168) and acceptance (:712) stay true. No change.
- Verify r17b faithful-rules observation 9 ("for the plan files, optional"): P10.md:57's stub list "at the time of
  writing" lacks stop-spec-coverage-enforce.py, which P1b row 8 leaves an exit-0 stub; P10 reads the stubs from P1b's
  PR rows, so nothing breaks. No text.

#### prompts/P0.md, P1.md, P7.md and P11.md

No body item is recorded for them; their tails take C-1 to C-5 as the "Tails" table under `_common.md` says.

**Accounted for, no text:**

- round-15 P1b records 3.4 (lane row16prod, observation 1): P0.md:46 keeps hooks/install-auto-sync.sh as an opt-in path,
  and the script's dead `cp` (:101) is a fourth harness producer of A105 that P1b row 16 does not name; its fate is for
  the coordinator or a later lane. No text.
- Fix log r17-P1b-spec-coverage: P1.md:346 records a merged phase (the coordinator's "Who may block"). No change.

#### Not carried in the c33ca28 prompts record, at ef34dbc

- the d22c669 prompts record's Fixes P4-5, P4-8, P4-13 and P9-14 (owner-R18; W9), counted 4: dropped by fix log
  r1-P1b-spec because P1b E14 keeps /commit Step 8's selection; P4.md:86 still says so. Still not carried.
- fix log r3-P1b-qamode item 3 (P2 row 4, optional, no text; "Not a defect"), counted 1. Still not carried.
- fix log r4-P1b RA4-1 note (P2's TC-44 site list, now P2.md:494), counted 1: no text. Still not carried.
- P4.md's "dev when none" default, counted 1: it became F-P4-D21-1 to -3, now already applied in substance by e428c5b
  (P4.md above). Closed.
- P9.md:190-191, the D2 bullet's "QA fail, BA needs_clarification and a hook rejection are process steps", counted 1:
  observation, no text; the clause is still there. Still not carried.
- P2 row 4's last sentence ("Replay: ... with 0 orchestrator aggregation calls (D24, D8).", P2.md:322), counted 1:
  observation, no text; unchanged. Still not carried.
- The observation on P4.md's "Already done by P1b" routing tables, counted 1: no record for P4. Still not carried.
- P9.md:689 ("the two missing-script allows and three score allows"), counted 1: no text; with F-P9-12 applied it
  would say "three" where row 3 says "two". Still present.
- Notes W12 (P9's net cap), W8 (harness dev.md and dev-command.md keep "Ask user to fix manually" in Step 15) and fix
  log r1-P1b-producers (/clean's own route), counted 3: no text. Unchanged.
- Six earlier observations resolved by later plan text, counted 6: nothing to record.

### Other planning files: DECISIONS.md, COVERAGE.md, HANDOVER.md, README.md, audit/, reviews/, tools/ and the rest

Scope: every "For the plan files" item whose target is a planning file other than PLAN-v2.md,
reviews/P1b-plan-sync.md, prompts/ (P1b.md and P1c.md with them) and inventory/. That is DECISIONS.md, COVERAGE.md,
COVERAGE-P9-P11.md, HANDOVER.md, README.md (the planning index), audit/2026-10-23/, landscape/, reports/, PLAN-v1.md,
tools/ (the sandbox kit) and the other files under reviews/. Items on the harness's own CLAUDE.md, which lies outside
harness-repair-plan/, close this group as notes for the phase that owns them. Nothing here is applied.

Base and sources:
- Read at ef34dbc, the head of claude/vibrant-hopper-bazrn8 (clean tree, equal to origin's). Paths are relative to
  harness-repair-plan/. Line numbers are those at ef34dbc and only help orientation; each item is found by its text.
- FD-1 to FD-17 are the plan-file record of this scope as of c33ca28, which read the files at 0be8bf0. FD-18 and the
  no-edit entries come from the records written since: the round-12 to round-18 P1b apply records, the round-12 to
  round-16 inventory patch notes with the round-16 adjudication, the round-18b fix notes and the 39 fix logs the
  c33ca28 record had not read (from c33ca28's own log, r18-P1c-C18-1, on).
- Since 0be8bf0 only two commits changed files of this scope, each line in place: 7beb706 and e428c5b rewrote
  COVERAGE.md:3 (the status line) and HANDOVER.md:51 and :83. No line was added or removed and no item's text was
  touched, so every line number of the c33ca28 record holds at ef34dbc. The other files' last changes: DECISIONS.md
  b335a0e, README.md 54393f8, audit/2026-10-23/ dac09ec, COVERAGE-P9-P11.md 86b7cbc, tools/ 54393f8, landscape/,
  reports/ and PLAN-v1.md d9e6978; the newest change under reviews/ outside the sync list is 4cc52aa.
- Grade: necessary or optional, as the source record gives it; where two records disagree the later one is kept and
  the item says so. State: pending; already applied (the commit); superseded (by what); needs re-anchoring (none in
  this group).

#### Items

| Id | Target at ef34dbc | Grade | State | Source finding or round |
|---|---|---|---|---|
| FD-1 | DECISIONS.md:68-87 (D25) | necessary | already applied (06794d9) | format-FH-6, owner-R5 (wave-2 sync logs) |
| FD-2 | DECISIONS.md:7 (heading of the 2026-10-23 rulings) | necessary | already applied (fa5659d) | plan-FIT-09 |
| FD-3 | DECISIONS.md:79-82 (D25 (2)) | necessary | superseded by f65290d | plan-FIT-10 |
| FD-4 | DECISIONS.md:80-81 (D25 (2), the F8 insert) | optional | superseded by f65290d | plan-FIT-10, owner-R4 |
| FD-5 | COVERAGE.md:73 (never-fail row) | necessary | already applied (c728380; second cell fa5659d) | format-FH-6, owner-R5 |
| FD-6 | COVERAGE.md:308, third cell (the /restart half) | necessary | already applied (c728380; reworded f65290d) | plan-FIT-10 |
| FD-7 | COVERAGE.md:282-284 ("Gaps the owner must decide", item 2) | necessary | pending | plan-FIT-04 |
| FD-8 | COVERAGE.md:308, second cell (the fault list) | necessary | superseded by f65290d | owner-R4 |
| FD-9 | COVERAGE.md:308, third cell (the F8 half) | necessary | superseded by f65290d | plan-FIT-10, owner-R4 |
| FD-10 | COVERAGE.md:310 (D25 (4) row) | necessary | superseded by f65290d | feasible-H5, plan-FIT-04 |
| FD-11 | COVERAGE.md:312 (earlier-words row) | optional | pending | owner-R4 |
| FD-12 | COVERAGE.md:318-322 ("Found while syncing", first bullet) | necessary | superseded by f65290d | feasible-H5, plan-FIT-04, facts-F13 |
| FD-13 | HANDOVER.md:112-113 (the D25 quote) | necessary | already applied (c728380) | format-FH-6, owner-R5 |
| FD-14 | HANDOVER.md:122 (N1, V1-1, NV-1 record) | necessary | already applied (c728380) | feasible-H5, plan-FIT-04, facts-F13 |
| FD-15 | README.md:9 (PLAN-v2 row) | necessary | pending | plan-FIT-22 |
| FD-16 | README.md:14 (tools/ row, three rows after it) | necessary | pending | plan-FIT-22 |
| FD-17 | audit/2026-10-23/register.md:15 (`plan:F:N`) | optional | pending | verification round 1, refs-P1c R1 |
| FD-18 | COVERAGE.md:308, second cell (fault count) | conditional | superseded by a12fb1d (P1b row 6) | verification round 20, C20-1 |

Pending: 5 (FD-7, FD-11, FD-15, FD-16, FD-17; two optional). Already applied: 6. Superseded: 7. Needs re-anchoring: 0.
No two items touch the same text; no record conflicts with another except where FD-5, FD-17 and FD-18 say so.

#### Pending, in application order

Apply in this order: FD-7, FD-11, FD-15, FD-16, FD-17. Replace `old` by `new` exactly; "whole lines" means
complete lines without the final line break, "part of line" a substring.

**FD-7.** COVERAGE.md:282-284, whole lines. Necessary. Finding plan-FIT-04 (both refuters; P7b fact 9); the
wave-1 D1 apply log and the decisions consolidation (DP-38). The text still says the reviewer's 2026-10-18 request is
open, which asks the owner about what D18 and D19 settle by recording a fact. Since c33ca28, 7beb706 and e428c5b
made the status line COVERAGE.md:3 say that "Gaps the owner must decide" are no longer asked and that gap 2's /pull
question was answered on 2026-10-19 (D19); item 2's own words still contradict that line, so the item stays as
recorded. COVERAGE-P9-P11.md:169 (row 7) still holds the quoted 'P7b R2 (S3 repaired, S4 reported)'. New lines are
119, 118 and 120 columns.

old:
~~~
   manually started fswatch daemon pulls. Every "live landing" acceptance assumes the merge arrives. Also unanswered:
   whether a home already pulled P7 alone and sits in S3/S4, where P7b can never reach it (P7b fact 9; the reviewer's
   2026-10-18 09:18 request is open).
~~~
new:
~~~
   manually started fswatch daemon pulls. Every "live landing" acceptance assumes the merge arrives. A home that pulled
   P7 alone and sits in S3 or S4 receives no code by any pull path (P7b fact 9); this is recorded as a fact and nobody
   is asked (D18, D19). COVERAGE-P9-P11.md row 7's 'P7b R2 (S3 repaired, S4 reported)' holds only for homes P7b reaches.
~~~

**FD-11.** COVERAGE.md:312, part of line (section (e), the earlier-words row). Optional. Finding owner-R4; the
wave-1 D4 apply log (sync :844, optional) and DP-42. The row still credits CC4 only to P1c's "Owner decisions", while
:308's third cell cites register CC4 for the F8 aside. The row stays one line.

old:
~~~
| P1c "Owner decisions" (quoted with sources); DT4 against CLAUDE.md #5: P9 (C12) |
~~~
new:
~~~
| P1c "Owner decisions" (quoted with sources); CC4 replayed by P1c's F8 faults; DT4 against CLAUDE.md #5: P9 (C12) |
~~~

**FD-15.** README.md:9, whole line (the PLAN-v2 row). Necessary as recorded. Finding plan-FIT-22 (both refuters);
refuter A's row text, not B's "sections 5, 6 and 15" variant. PLAN-v2.md still has section 14 (P7b, :1274) and
section 15 (P1b and P1c, :1301) at ef34dbc. The row stays one line.

old:
~~~
| PLAN-v2.md | The current plan, phases P0-P11: goal, file:line scope, acceptance tests, risks, technical choices, decision ledger, waves. Line numbers at master 09ab15b. |
~~~
new:
~~~
| PLAN-v2.md | The current plan, phases P0-P11 plus P7b (section 14), P1b and P1c (section 15): goal, file:line scope, acceptance tests, risks, technical choices, decision ledger, waves. Line numbers at master 09ab15b. |
~~~

**FD-16.** README.md:14, whole line, with three rows added after it. Necessary as recorded. Finding plan-FIT-22
(both refuters refuted the claim that prompts P1b and P1c are missing; the index does lack inventory/, audit/ and
reviews/). Each row is one line.

old:
~~~
| tools/ | The sandbox used for the runtime evidence (below). tools/proto/ holds the planning prototypes of the unified Stop gate (stop_command_gate.py, command_span.py, run_scenarios.py, txbuild.py) and the crash/slow phase stubs PLAN-v2 cites. |
~~~
new:
~~~
| tools/ | The sandbox used for the runtime evidence (below). tools/proto/ holds the planning prototypes of the unified Stop gate (stop_command_gate.py, command_span.py, run_scenarios.py, txbuild.py) and the crash/slow phase stubs PLAN-v2 cites. |
| inventory/ | The d625284 artifact map (P1b planning evidence). |
| audit/ | The 2026-10-23 owner register, artifact ledger, corrections and report-zh. |
| reviews/ | Review records and plan-sync lists. |
~~~

**FD-17.** audit/2026-10-23/register.md:15, whole line ("Source abbreviations"). Optional: verification round 1
(refs-P1c, R1, medium) fixed P1c and marked the register line "optional, for the plan files"; the c33ca28 record
lists it without a grade, and the earlier grade is kept. Each `plan:` citation is read on the moving branch: at
ef34dbc the D7 quote CC4 cites as `plan:prompts/P4.md:100-102` is at prompts/P4.md:177 and CC6's quote (cited :174)
at :258, while at 3ce5882 the cited lines hold the quotes. Only the abbreviation's definition changes; no owner word,
row or status does. Wrapped as two lines (113 and 49 columns).

old:
~~~
- `plan:F:N`: refs/remotes/origin/claude/vibrant-hopper-bazrn8, file harness-repair-plan/F, line N.
~~~
new:
~~~
- `plan:F:N`: file harness-repair-plan/F, line N, at planning commit 3ce5882 (the branch has moved since; read it
  with `git show 3ce5882:harness-repair-plan/F`).
~~~

#### Already applied

- **FD-1.** DECISIONS.md:68-87. The recorded outcome (D25 as one bullet, :70, with the owner's full sentence and no
  ranking against D24; :75 "Measured by a replay suite in CI that every later phase keeps green") has been in the file
  since 06794d9. The wave-2 sync logs recorded "no change" and "already carried"; the sync list's own D-1 text is
  superseded in the sync-list group. "as important as D24" occurs 0 times in DECISIONS.md and in its history. The quote
  at :70 is byte-equal to HANDOVER.md:113's (CJK text; not reproduced here).
- **FD-2.** DECISIONS.md:7. Applied by fa5659d as
  `## Owner rulings of 2026-10-23 (they override PLAN-v1, PLAN-v2, every prompt and every decision below except D25)`.
  The record had "other than D25" (0 occurrences); the sense is the same, the exception binding "every decision below"
  only. Its "(latest; ranks with D24)" had already been dropped by the wave-2 sync logs.
- **FD-5.** COVERAGE.md:73, one table row:
  `| 2026-10-24 never fail (D25): measured by the CI replay suite (1)-(4); ... (P1c's merge rule) | P1c; P2-P6 and
  P9-P11 acceptance (this sync) | - |` (one line in the file). Added by c728380; "as important as D24" occurs 0
  times. The c33ca28 record names f65290d as the commit that changed the second cell; `git log -L` shows fa5659d did
  (from "P1c; P2-P11 acceptance (this sync)").
- **FD-6.** COVERAGE.md:308, third cell. c728380 applied the /restart aside (`P1c acceptance 4 (the human /restart of
  F5, F5f and F6 aside: D22, register RD4)`); f65290d reworded the cell and kept it:
  `P1c acceptance 4 (aside: the human /restart of F5, F5f and F6, D22, register RD4; the human /close or /commit of each
  F8 fault, D7, register CC4)`.
- **FD-13.** HANDOVER.md:112-113 (sync H-10). Added by c728380: :112 names D25 and :113 is the full quote, byte-equal
  to DECISIONS.md:70's; the D24 ranking phrase occurs 0 times (CJK text; not reproduced).
- **FD-14.** HANDOVER.md:122 (sync H-10). c728380 wrote the parenthetical that N1, V1-1 and NV-1 are recorded in
  reviews/P7b-PR-record.md with before and after evidence; the old claim that the last two have no record in the
  repository or the planning branch occurs 0 times (CJK text; not reproduced).

#### Superseded

Each old text below occurs 0 times at ef34dbc.

- **FD-3.** DECISIONS.md D25 (2). The record (refuter A fix 1 merged with refuter B's DECISIONS.md fix) replaced
  `  artifact and failing check, and repaired at the next round with no human action; (3) no dead end: no state exists`
  with a five-line exception naming the owner's /restart (D22, register RD4, the human-only evidence) and the
  /dev-overnight usage-limit resume (D20). f65290d rewrote (2) instead, :79-82:
  `and repaired at the next round with no human action beyond the owner's own commands` /
  `(his /restart of a session he interrupted or of one a usage limit cut outside /dev-overnight, D22; his /close or` /
  `/commit that meets an unfinished cycle, D7; inside /dev-overnight a usage-limit cut resumes with no human action,` /
  `D20; P1c Goal 1 (2) and acceptance 4)`. The defect (D25 (2)'s "no human action" against D22's human /restart) is
  gone. The record's extra citations (register RD4; commands/restart.md `disable-model-invocation: true` and the
  `Skill(restart:*)` deny) change no rule and are carried by D22 and P1c; not carried.
- **FD-4.** DECISIONS.md D25 (2), the optional F8 insert (DP-44, from the wave-2 V9 log; it anchored on FD-3's new text,
  which never landed): `the /close or /commit the owner types completes a cycle it meets unfinished with no further
  human action (CC4)`. f65290d's :80-81 carry its sense:
  `his /close or` / `/commit that meets an unfinished cycle, D7;`.
- **FD-8.** COVERAGE.md:308, second cell. Record (DP-39): `F7, F7b (fan-out lane), each in 2 modes` -> `F7, F7b
  (fan-out lane), F8, F8q, F8p, F8c (an unfinished cycle met by /close or /commit, CC4; P1b row 10), each in 2 modes`.
  f65290d wrote: `F7, F7b (fan-out lane), F8, F8q, F8p, F8c (an unfinished cycle met by the human's /close or /commit;
  P1b's routing loops, replayed): 21 faults, each in 2 modes`.
- **FD-9.** COVERAGE.md:308, third cell, the F8 half. Record (DP-40): `P1c acceptance 4 (the human /restart of F5, F5f
  and F6 aside: D22, register RD4)` -> `P1c acceptance 4 (the human /restart of F5, F5f and F6 and the /close or
  /commit of each F8 fault aside: D22, register RD4, CC4; F6o none)`. The cell quoted under FD-6 names the F8 faults'
  /close or /commit with D7 and register CC4. "F6o none" is not in the cell: the aside lists F5, F5f, F6 and the F8
  faults only, so F6o has no human action by omission; not carried.
- **FD-10.** COVERAGE.md:310. Record (DP-41): `R-N1 (X9, row 20), R-V1 (X7, row 14)` -> `R-N1 (X9, row 20), R-V1
  (P7b's landed repair; no P1c row)`. f65290d wrote `R-V1 (P7b's V1-1/NV-1 fix, commits 96bcb8f and 921b512, replayed
  with index.lock held)`, which agrees with P1c.md:738-744 (R-V1 asserts "with index.lock held").
- **FD-12.** COVERAGE.md:318-322. Record (DP-43, re-anchored on c728380's bullet): the bullet's "P1c's X9 and R-V1
  predate that record ... no phase owns them yet" -> a bullet saying P1c replays N1, V1-1 and NV-1 (X9, R-V1) and its
  row 20 takes N1's remaining window and safe_pull's tee. "predate that record" and "no phase owns them yet" occur 0
  times; f65290d's :319-322 say `P1c's X9 and R-V1 now reproduce them from that record` and that P1c takes N1's
  remaining window and safe_pull's tee without pipefail (row 20).
- **FD-18.** COVERAGE.md:308, second cell. Source: verification round 20, C20-1 (medium), "records for other plan files
  (only if this fix is applied)"; its PLAN-v2.md:174 twin belongs to the PLAN-v2 group. Its old text still occurs once
  (:308, part of line):
  `F8, F8q, F8p, F8c (an unfinished cycle met by the human's /close or /commit; P1b's routing loops, replayed): 21
  faults, each in 2 modes` -> `F8, F8q, F8p, F8c, F8r (an unfinished cycle met by the human's /close or /commit; P1b's
  routing loops, replayed; F8r after a /close --late-repair, P1c row 18): 22 faults, each in 2 modes`.
  Superseded, the later records kept: the round-15 P1b records (section 3.2) and the r15-P1b-apply and r20-P1c-C20-2
  logs find C20-1 not needed, because P1b's row 6 (a12fb1d) deletes the late-repair re-record refusal
  (late-repair-controller.py:285-286), acceptance 14 lists that base dead end for P1c and acceptance 7 replays it.
  P1c at ef34dbc has no F8r and still counts 21 faults (P1c.md:537), so :308 stays consistent. Do not apply.

#### Not carried (from the c33ca28 record; unchanged at ef34dbc)

1. register.md CC4 and CC5 renumbering (owner-R1, optional; wave-1 C2 log: `plan:prompts/P4.md:100-102` -> `:135-138`,
   `:103-104` -> `:138-139`). Superseded by FD-17, which pins the revision. The numbers are stale again: the D7 quote is
   at prompts/P4.md:177 at ef34dbc.
2. D25 (3) "apart from the owner's own /stop or interrupt": a refuter's suggestion with no fix text (wave-2 V9 log).
   D25 (3) at :82-83 reads "apart from the owner's own /stop".
3. D15's "for one phase" against P1b and P1c's "until P10" (verification rounds 8-10, faithful-rules-P1c): no
   plan-file target and no text; DECISIONS.md D15 is the owner's decision and stays.
4. DECISIONS.md:68 heading without "latest" (wave-2 V7 log, written before a merge): superseded by the W1 log (keep the
   merged heading) and by fa5659d's rewrite of the heading. No record asks for a change.

#### Records with no edit (checked at ef34dbc)

From the c33ca28 record (each anchor unchanged, the files untouched since):
- DECISIONS.md: the wave-1/2 C10, V3, V7, D1, D4 (its D25 (2) "no change" overtaken by f65290d) and W12 logs, and
  fix log r10-P1b-live-landing (DECISIONS.md does not mention `--init-if-missing`).
- audit/2026-10-23/corrections.md:681 and landscape/00-INDEX.md:1052 (W7: the auditor's and landscape's words);
  corrections.md:683 and landscape/00-INDEX.md:1113 (W8: historical evidence); audit/2026-10-23/ledger.md:47,
  corrections.md:420 and landscape/G-stop-gates.md:28 and :30 (r11-P1b-row18: consistent, or pinned to 09ab15b).
- audit/2026-10-23/report-zh.md: a dated record that COVERAGE.md:325-326 says is not edited.
- reports/runtime-verification.md:343 (r9inv-A103: agrees) and :389 (round-5 inventory verification: evidence only).
- COVERAGE-P9-P11.md:169, row 7 (evidence for FD-7 only).
- reviews/D20-D25-residuals-and-sync-record.md:818 (r4-P1b: a note, no fix) and :721-726 with its item on
  DECISIONS.md:79 (settled by P1c's round-5 fix and the merged D25 (2)); reviews/P7b-PR-record.md and
  reviews/P1-PR5-review-followup.md are cited as evidence only.

From the records written since c33ca28:
- DECISIONS.md: no text needed by any round-12 P1b lane (round-12 P1b records, section 2.5).
- DECISIONS.md:236 (TC-47, "BA may write" the observations ledger): round-12 P1b records 5.3, row4 lane. A permission
  is no write/read relation the D24 check derives; if E12 keeps the ledger, E3 and rule (7) govern the prefix. No text.
- DECISIONS.md:186-191 (D17) and audit/2026-10-23/register.md:279 (X6): the basis of P1b E3's deletions (round-14 P1b
  records 4.7, log r14-P1b-apply). Evidence; no edit. The same log's note that P1b's D17 summary leaves out a D17
  sentence targets P1b.md and belongs to the P1b group.
- DECISIONS.md:28-42 and :58-66 (D21, D24): read as the basis of P1b row 10's fix (log r13-P1b-row10). No edit.
- landscape/00-INDEX.md:949 (D1.e, "write only to stderr"): round-12 P1b records 5.3 (n1) say no phase prompt takes up
  the exit-0 stderr channel, outside D24; round-15 P1b records 2.5 (row4warn) call the line planning evidence, no fix.
- reviews/P1b-P1c-review-findings.md:896 (the historical "33" code-only rows, written at c1bdc15): stays (round-13 P1b
  records, section 2, trace note). Its P1c cites are pinned to c1bdc15, so no shift breaks them (log r20-P1c-C20-3).
- audit/2026-10-23/ledger.md:49 and :64 (the same short ranges as A119's old cite): a source record, noted only (log
  r11inv-cites). ledger.md:315 agrees with A70's corrected reader, and reports/runtime-verification.md:256 is a
  proposal, not a reader (log r11inv-A70).
- PLAN-v1.md: superseded, no change (log r13-P1b-E5).
- "README.md need no change" (log r13-P1b-acc9; the log does not say which README; neither the planning index nor
  inventory/README.md gets text from it).
- tools/ (the kit): no record proposes kit text. Round-12 P1b records 5.2 found apply-permissions.sh exits 1 in the
  kit's toy repository, which has no `.claude/` (tools/sb-setup.sh:35-46); the round-15 applyperm lane settled it in
  P1b (a12fb1d: row 16's replays start in the toy repository with no `.claude/settings.json`, and "a missing file is
  an empty object to the merge", P1b.md:771). Round-16 P1b records 3.5 (A-O1) note the kit writes no agent meta
  (tools/baseline.py:48-51), an observation on P1b row 18. tools/sb-setup.sh:39, tools/reset.sh:11 and
  tools/baseline.py `tool()` (:92-110) and `base` (:56-62) are cited as evidence by the round-15/16 P1b logs, the
  round-18b row11lck and rule5 notes and log r23-P1c-RA23-1.
- Plan files "none" (no text for this group): round-18 P1b records section 2 and the r18-P1b-apply, r18b-P1b-apply,
  r18-P1b-transition, r13-P1b-acc21, r14-P1b-cites, r18-P1c-C18-1, r19-P1c-row10, r20-P1c-C20-2, r21-P1c-R21-1,
  r21-P1c-RA21-1, r22-P1c-R22-1, r22-P1c-R22-2, r23-P1c-R23-1 and r23-P1c-RA23-1 logs; the round-18b prnames, removals,
  row11lck and rule5 notes; the round-13 part-2, round-14 part-1 and round-16 part-1 inventory notes.

Outside this group, from the same sources: the PLAN-v2.md:1176 and reviews/P1b-plan-sync.md:419 figure (round-15
PF-1 and PF-2, `43 / 56 / 29 / 24 of 121`, which round-16 part 3 restates for A126), C20-1's
PLAN-v2.md:174, the round-17 spec-coverage records (PLAN-v2.md:1158, P5.md), and the P2, P3, P4, P6, P9, P10, P1b, P1c
and inventory records belong to the other groups. That covers every plan-file record in the round-11 inventory logs
(A62, A63, A70, A94-A124, A104, A105, cites), the round-12 to round-15 inventory apply logs, the r12-inv-from-p1b and
r13-inv-leftovers logs, the r13-P1b-E5, r13-P1b-row10, r17-P1b-spec-coverage and r22-P1c-closeout logs, the round-12
to round-17 P1b apply logs and records, and the round-12 to round-16 inventory patch notes: none targets a file of this
group.

#### Observations with no record (not items)

- COVERAGE.md:280 still reads "(one answer for P2's G1-G3 arming and P5-d, fix 2)" (owner-R2's defect: G2 arms in
  P1b's E4, or else in P1c's X3). Since c33ca28, COVERAGE.md:3 (7beb706, e428c5b) says the file's gaps are no longer
  asked and that fix 2's arming statement no longer holds, and HANDOVER.md:51 (7beb706) says G2 is armed in P1b and
  G1 and G3 in P2; :280's own label is unchanged. No log anchors a fix.
- HANDOVER.md:21 (P2 row, f65290d) and :121 (fa5659d's /restart, overnight and /close-or-/commit exceptions) still
  resolve the consolidation's earlier HANDOVER observations.
- README.md's index also has no row for COVERAGE.md, COVERAGE-P9-P11.md or HANDOVER.md; FD-16 adds only what its
  record names.

#### Notes for the phase that owns the harness CLAUDE.md (outside harness-repair-plan/; this session does not touch it)

- **CM-1.** CLAUDE.md:102 (at d625284; the same line in the checkout), the sentinel-grant paragraph's last sentence on
  hooks/stop-cleanup-allowlist.sh: its second clause, "so it does not reap expired sentinels at session end", is false
  at d625284, because stop-workflow-coordinator.py:72 runs the script as its cleanup phase. Source: round-18 P1b
  records section 5 (row11 lane), repeated in log r18-P1b-apply. P1b must not edit CLAUDE.md. Owner: P9 row 16
  (prompts/P9.md:484 at ef34dbc: ":102 per E3 (the sentinel lives under the hook state directory; the cleanup phase
  runs on an allowed Stop)"). No other text was proposed. State: pending in P9.

#### Checks

- At ef34dbc each pending `old` (FD-7, FD-11, FD-15, FD-16, FD-17) occurs exactly once in its file, and still exactly
  once at its turn when the five are applied in the order above (in memory); each `new` then occurs once. New prose
  lines are at most 120 columns; table rows stay one line.
- Each superseded item's old text occurs 0 times, except FD-18's, which occurs once and is not to be applied.
- Each already-applied item's quoted text occurs once at ef34dbc.
- No item adds or changes an owner quote, brings back a rejected idea, or carries personal data or a model identifier.

## Verification rounds

Sources: the verification reports of every round, the apply and fix logs, the lane notes and records of the patch
rounds, the round-16 adjudication, the orchestrator's running notes (none of these is committed; they are named here by
round and report), and `git log` of the planning branch (read at ef34dbc, working tree clean). Defect counts are written
blocker/high/medium/low, exactly as each report states them; every stated count was compared with the report's own
defect headings and none differs. "0" means a report with no defect, and a dash means the round had one report only. A
defect that both lenses found is counted once in each lens.

### Method

- **Refutation.** Each of the 95 review findings went to two refuters who worked independently: refuter A checked the
  evidence first, refuter B the proposed fix and the owner's rulings first. A finding stood unless both refuted it: 89
  stood and 6 were refuted by both (see Findings).
- **Apply clusters.** Standing findings were applied one cluster per agent, the lanes of one file running one after
  another. Wave 1 (blockers, highs, and the mediums and lows that edit the same sentences) was P1b C1-C13, P1c D1-D8
  and inventory I1, committed in 2e7d4c0. Wave 2 (the rest) was P1b W1-W15, P1c V1-V15 and inventory I2-I3,
  committed in d22c669. Each applier used the refuters' corrected fixes and recorded the parts that land in other
  plan files instead of applying them.
- **Two verifiers per prompt per round.** Lens "faithful+rules" checked that every standing finding and every earlier
  fix is applied faithfully, that the file is consistent with itself and with the other prompt, and the fixed rules
  (first line, shared tail, owner quotes, wrapping). Lens "refs+acceptance" checked every file:line, commit and plan
  cite against the d625284 and master 2acc29b trees, and that every acceptance item runs in the kit and in CI. In
  round 1 (both prompts) and round 2 (P1c) the four lenses wrote separate reports; the tables add them per pair. From
  round 2 on, each verifier re-checked the whole file, checked that the earlier fixes held, and did not re-raise an
  item a fix log had rejected with sound evidence. P1c rounds 18 and 20 were single cross-checks of P1c against new
  P1b and inventory commits.
- **Fixes.** A fix agent re-checked each defect before editing (HOLDS or DOES NOT HOLD, with the reason) and logged
  every edit and every record for another plan file. A lane that found no defect made no edit (for example the P1b
  A03 lane of the r10b batch and the P1c X3 lane after P1b round 9).
- **Inventory sweeps.** Inventory rounds 1-11 had one verifier each. Rounds 12-15 were full sweeps in three parts:
  part 1 rows A01-A40 with the README's counts and format, part 2 rows A41-A80, part 3 rows A81-A124. Round 16 was a
  targeted read in three parts of named rows (15, 25 and 22 rows) and the README.
- **Patch-then-apply lanes, one issue per agent.** From inventory round 12 and from the P1b knock-on lanes of that round
  on, an agent did not edit the file. Each lane took one issue, judged each record HOLDS, HOLDS WITH CORRECTION or DOES
  NOT HOLD, and wrote a patch (exact old -> new edits, each old text occurring once) dry-run on a copy of the file. One
  applier per round then checked each patch alone against its lane's own result, checked that the lane order did not
  change the result, applied every patch, checked the first line, the shared tail and the table rows, and the round was
  committed once. The P1b fixes of verification rounds 15b-18b used the same scheme.

### P1b rounds

Rounds 1-9 share the round ids r1-r9 with P1c; rounds 10-19 have the ids r10b-r19b.

| Round | Commit verified | faithful+rules | refs+acceptance | Fix commits | Clean |
|---|---|---|---|---|---|
| r1 | d22c669 | 0/2/5/13 (faithful 0/2/5/8, rules 0/0/0/5) | 0/1/12/22 (refs 0/0/4/11, acceptance 0/1/8/11) | 618e22e (nine lanes) | no |
| r2 | 618e22e | 0/0/2/5 | 0/0/1/7 | 7304b34 | no |
| r3 | 7304b34 | 0/0/1/4 | 0/0/2/4 | 64bec4f | no |
| r4 | 64bec4f | 0/0/0/2 | 0/0/1/1 | 0625898 | no |
| r5 | 0625898 | 0/0/0/3 | 0/0/0/2 | a19d839 | no |
| r6 | a19d839 | 0/0/0/3 | 0/0/1/3 | e23f583 | no |
| r7 | e23f583 | 0/0/0/3 | 0/0/0/3 | 787167e | no |
| r8 | 787167e | 0 | 0/0/0/1 | 5922f1f | no |
| r9 | 5922f1f (head ec2681d) | 0 | 0 | none | yes |
| r10b | 07a3905 (head 7f0cae4) | 0/0/0/1 | 0/0/0/3 | 602ec91, 1fcbfbc | no |
| r11b | c6bd5d4 | 0 | 0/0/0/1 | 040759f; from the round's observations 045c38a, b67cd4e | no |
| r12b | b67cd4e | 0 | 0/0/0/1 | 34565c6 | no |
| r13b | 0be8bf0 | 0 | 0/0/0/3 | 660e8da | no |
| r14b | cb35479 | 0/0/1/0 | 0/0/0/3 | 7c93969 (R14B-1, R14B-2); 0bdd73d (R14B-FR-1, R14B-3's decider part); a12fb1d (R14B-3's edit 1, as R15B-7) | no |
| r15b | 0bdd73d | 0/0/1/5 | 0/0/1/6 | a12fb1d (ten lanes) | no |
| r16b | 5b2b3d9 | 0/0/1/3 | 0/0/0/6 | 0381276 (eight lanes) | no |
| r17b | 3ca4af4 | 0/0/1/3 | 0/0/1/5 | e73c58d (seven lanes); 0bd2568 (the transition gap its apply log found) | no |
| r18b | b155101 | 0/0/1/2 | 0/0/2/1 | ef34dbc (two lanes: R18B-FR-1 with R18B-1, and R18B-2) | no |
| r19b (final) | ef34dbc | 0/0/0/4 | 0/0/1/3 | 382d857 (R19B-1); its check fix-R19B-1 at 382d857: 0/0/0/3, recorded as R19B-1-V1 to V3 | no; 0 medium or above after 382d857 |

Notes on the P1b table:
- Same defect in both lenses: r2 FR2-3 = RA2-6, FR2-4 = RA2-2, FR2-6 = RA2-4; r3 FR3-1 = RA3-2, FR3-2 = RA3-5, FR3-3 =
  RA3-6; r7 FR7-1 = RA7-3; r10b FR10-1 = R10B-2; r18b R18B-FR-1 and R18B-1 (one lane); r19b R19B-FR-2 and R19B-2 (each
  lens gave its own text, both recorded).
- r1's H1/F-1/R1 (row 7 and /commit's chain call) also closed P1c r2's FP1c-r2-2; r1's producers lane closed the
  inventory round 2 item INV2-1 that lands in P1b.md.
- r18b: the three lows (R18B-FR-2, R18B-FR-3, R18B-3) have patches (lanes removals and prnames) that were not applied,
  because the owner ruled that lows are recorded, not fixed (fix log r18b-P1b-apply).
- r19b: R19B-1 (medium) was fixed in 382d857, and an independent check of that commit (report fix-R19B-1) confirmed the
  fix and found three lows in the new text; the round's seven lows and those three are recorded under "Open low items",
  not applied.
- P1b commits between rounds that came from other sources: 07a3905 (inventory r5inv's INV5-6, medium) before r10b;
  861c102, a263825 and c6bd5d4 (follow-ups of the r10b batch and inventory row A103) before r11b; 0be8bf0 (the
  terminal receipt's writer, from inventory r9inv's INV9-1) before r13b; a58ee3d, 77df077 and cb35479 (the commit
  grant's second decider after inventory r11, row 10's unattributed product file, acceptance 9) before r14b;
  0bdd73d, 5b2b3d9, 87cdbe3 and b155101 (the knock-on lanes of inventory rounds 12, 13, 14 and 15); 3ca4af4 (the
  spec coverage rule, from a round-14 knock-on lane's observation).

### P1c rounds

| Round | Commit verified | faithful+rules | refs+acceptance | Fix commits | Clean |
|---|---|---|---|---|---|
| r1 | working tree on c461cde with the wave-2 P1c clusters, uncommitted (md5 2c9077a8) | 0/0/0/8 (faithful 0/0/0/5, rules 0/0/0/3) | 0/1/6/14 (refs 0/0/1/5, acceptance 0/1/5/9) | d22c669 (seven lanes, with wave 2) | no |
| r2 | d22c669 content (md5 0586b203) | 0/0/2/6 (faithful 0/0/2/3, rules 0/0/0/3) | 0/1/1/10 (refs 0/0/0/1, acceptance 0/1/1/9) | 76fc635; FP1c-r2-2 in P1b 618e22e | no |
| r3 | 76fc635 | 0/0/0/4 | 0/0/0/2 | 8ad26bc | no |
| r4 | 8ad26bc | 0/0/0/1 | 0/1/0/1 | 9f214f3 | no |
| r5 | 9f214f3 | 0/0/1/1 | 0/1/0/1 | 14d2a32 | no |
| r6 | 14d2a32 | 0/0/0/3 | 0/0/0/2 | 65dd54a | no |
| r7 | 65dd54a | 0/0/0/1 | 0 | a34e686 (with the alignment to P1b round 2) | no |
| r8 | e1762a6 | 0/0/0/1 | 0/0/1/0 | c68a19f | no |
| r9 | c68a19f | 0/0/0/1 | 0/0/1/3 | c6e3942 | no |
| r10 | c6e3942 | 0 | 0/0/0/2 | eef8a5c | no |
| r11 | eef8a5c | 0/0/0/1 | 0/0/0/1 | e8e5817 | no |
| r12 | e8e5817 | 0 | 0/0/1/0 | 88b240c | no |
| r13 | 88b240c | 0/0/1/1 | 0/0/1/1 | db16126 | no |
| r14 | db16126 | 0/0/1/2 | 0/0/1/1 | 2505633, 453308f, 397a965, a238571 | no |
| r15 | a238571 | 0/0/1/3 | 0/0/0/1 | 07dc782, 082ba74, c84d0fe, 5a88edc | no |
| r16 | 5a88edc | 0 | 0/0/1/0 | ba99401 | no |
| r17 | ba99401 | 0 | 0 | none | yes |
| r18 (cross-check) | ba99401 against P1b 34565c6, 0be8bf0 and inventory a0a5b6c, dffe658, f818b75 | one report: 0/0/0/1 | - | c33ca28 | no |
| r19 | 2d59577 (P1b at cb35479) | 0 | 0 | none | yes |
| r20 (cross-check) | 2d59577 against P1b 7c93969, 0bdd73d and inventory 31acd8f | one report: 0/0/1/2 | - | 59b483a, a9a9b98; C20-1 closed in P1b by a12fb1d, no P1c edit | no |
| r21 | a9a9b98 (P1b at 5b2b3d9) | 0/0/0/1 | 0/0/0/1 | 5530a7e, 7284365 | no |
| r22 | 7284365 (P1b at 3ca4af4) | 0/0/0/2 | 0/0/0/1 | 00d8894, eb7e42d | no |
| r23 | 95ff638 (P1b at b155101) | 0/0/0/1 | 0/0/0/1 | c273acd, 9bd18bb | no |
| r24 (final) | 9bd18bb (P1b at ef34dbc) | 0/0/0/2 | 0/0/0/1 (RA24-1, the same item as R24-1) | none: lows recorded | no; 0 medium or above |

Notes on the P1c table:
- Same defect in both lenses: r6 R6FR-1 = RA6-2; r11 FR11-1 = RA11-1; r14 FR14-2 = RA14-2; r15 FR15-2 = RA15-1; r22
  R22-1 = RA22-1; r24 R24-1 = RA24-1. In r8, R8FR-1 and RA8-1 were fixed together in acceptance 11.
- P1c commits between rounds that align P1c with P1b: e1762a6 (P1b round 3, verified by r8), 2d59577 (P1b row 10
  after 77df077, verified by r19), 95ff638 (P1b row 13 after e73c58d, verified by r23). c68a19f also carries a record
  from P1b round 4 (the commit.md grant-writer lines).

### Inventory rounds

Rounds 1-4 share the round ids r1-r4 with the prompts; later rounds have the ids r5inv-r16inv. Counts are the README's
Counts figures (I1's recount method); "check positions" is producer stop / G1 dispatch / G3 collection / elsewhere.

| Round | State checked | Defects per part | Apply commits | Count changes |
|---|---|---|---|---|
| r1 | working tree after I1 (2e7d4c0), I2, I3 and a README fix, uncommitted | 0/0/0/7 | d22c669 | several producers 36 -> 37 |
| r2 | d22c669 | 0/0/1/4 | 3646c24; INV2-1 to P1b 618e22e; 76fc635 (A88, from P1b r1 refs R2) | none |
| r3 | 76fc635 | 0/0/0/2 | 0cbfbd3 | none |
| r4 | e1762a6 | 0/0/0/7 | 0372d14; cf2f197 (A93, found while fixing) | several producers 37 -> 38; read never written 19 -> 20; no violation found 21 -> 20 |
| r5inv | db16126 | 0/0/1/5 | 7f0cae4; INV5-6 to P1b 07a3905 | several deciding consumers 37 -> 35 (the report forecast 37 -> 36); written never read 27 -> 28; read never written 20 -> 21; no violation found 20 -> 21 |
| r6inv | 7f0cae4 | 0/0/0/2 | 28a7074, 8611f23; 1bf33ef (A103 cells the fix noted) | several deciding consumers 35 -> 34; no violation found 21 -> 22 |
| r7inv | 60d2902 | 0/0/0/2 | 9f03fea | none |
| r8inv | 9f03fea | 0/0/0/1 | a966aa1 | none |
| r9inv | a966aa1 | 0/0/1/0 | a0a5b6c | read never written 21 -> 22; no violation found 22 -> 21 |
| r10inv | dffe658 | 0/0/0/1 | f818b75 | none |
| r11inv | f818b75 (then 0be8bf0, c33ca28) | 0/0/1/5 | afc6773, 6085619, 174281c, d87af6b, 4dab588; eb31066 (A105, from the cites lane's observations), b12f0de (A104, the same gap) | several deciding consumers 34 -> 37; read never written 22 -> 24; G1 dispatch 13 -> 14; elsewhere 67 -> 68 |
| r12inv | b12f0de | part 1 0/0/5/8; part 2 0/0/9/11; part 3 0/0/5/9 (47) | 31acd8f (259 edits, 83 rows); fb8f42c (9 rows from the P1b knock-on lanes) | several producers 38 -> 43; several deciding consumers 37 -> 47; consumer-side re-check 29 -> 28; written never read 28 -> 27; hand-written table 26 -> 27; no violation found 21 -> 20; check positions 30/14/18/68 -> 37/10/20/74 |
| r13inv | fb8f42c | part 1 0/0/5/15; part 2 0/0/6/14; part 3 0/0/5/5 (50) | d6409c2 (186 edits, A17 dropped); abb33b2 (A108, A120 leftovers) | rows 121 -> 120; several deciding consumers 47 -> 52; re-check 28 -> 29; written never read 27 -> 26; no violation found 20 -> 18; code-only rows 33 -> 32; check positions 37/10/20/74 -> 34/9/27/77; G03 5 -> 4; then producer stop 34 -> 33 (abb33b2) |
| r14inv | abb33b2 | part 1 0/0/4/6; part 2 0/0/5/8; part 3 0/0/4/6 (33) | 4ce4271 (111 edits, 40 rows) | re-check 29 -> 32; written never read 26 -> 28; hand-written table 27 -> 32; producer stop 33 -> 37 |
| r15inv | 4ce4271 | part 1 0/0/2/5; part 2 0/0/5/10; part 3 0/0/3/8 (33) | 37a259a (68 cell edits on 36 rows, A125 added) | rows 120 -> 121; outside the ledger 39 -> 40; several deciding consumers 52 -> 56; written never read 28 -> 29; hand-written table 32 -> 35; no violation found 18 -> 15; code-only rows 32 -> 33; check positions 37/9/27/77 -> 41/9/28/78; G01 8 -> 9 |
| r16inv (targeted) | 37a259a (head b155101) | part 1 0/0/1/3; part 2 0/0/0/7; part 3 0/0/1/5 (17) | none: patches prepared, not applied | none |

Notes on the inventory table:
- Inventory commits between rounds: 10bee66 (cites from P1b round 1's refs lane) before r4; afb0d6b (A54 from P1b
  round 5, A93 left open by round 4), 134db19 (A01, from P1b round 6) and 822621b (A98, from the round-6 inventory fix
  log) before r5inv, with no count change; 07ff67a (hand-written table 27 -> 26) and 60d2902, records of the P1b r10b
  lanes, before r7inv; dffe658 (the README's /do mint wording, a record of P1b r11b) before r10inv.
- Where the parts' forecasts differed, the applier took its own recount: r13 G3 collection 27 (part 2 said 26); r14
  producer stop 37 (the notes said 34, 32 and 37); r15 producer stop 41 (part 1 said 40) and hand-written table 35
  (part 3 said 34).

**Stopping history.** The four full sweeps kept finding defects in the map itself, all medium or low: 47 in round
12, 50 in round 13, 33 in round 14 and 33 in round 15. Each applied sweep was followed by P1b knock-on lanes (0bdd73d,
5b2b3d9, 87cdbe3, b155101), and P1c was cross-checked where P1b changed.

**Targeted round 16.** Round 16 then read only named rows: 15 rows and the README (part 1), 25 rows (part 2) and 22 rows
(part 3). It found 17 defects (2 medium, 15 low). The part 2 patch lane judged its D7 (A80) DOES NOT HOLD. The round-16
adjudication ruled that hooks/posttool-subagent-track.py's contract path never runs at d625284 (it only asks for cycle-0
contracts). Two part 1 defects fell or narrowed on that ruling: INV16-3 (A28) became DOES NOT HOLD, and INV16-2 (A44)
kept only its check-overnight-reports.py half (edit 5 dropped, edits 3 and 4 reworded). The adjudication also wrote a
follow-up patch for the other cells resting on the same path (A09, A19, A34, A77, A78, A79).

**Owner's ruling.** The inventory is planning evidence. P1b's first implementation step regenerates it on that day's
master, so it need not reach zero differences here; no further full sweep is run, and rows with known errors are listed
(see "Inventory: rows with known errors"). The round 16 patches (parts 1-3 and the adjudication's follow-up) were
therefore prepared but not applied. The inventory stays at 37a259a.

### Operational notes

- **Restarts and resumed agents.** The orchestrator's notes for the state after b155101 record the inventory round 16
  parts 1-3 as "resumed after restart". The P1c round 1 setup lane logs one usage-limit interruption in mid-task; it
  resumed after re-reading the file and repeated no edit. No source records the agent ids of resumed agents. The
  apply logs' file times show two long pauses during the review-findings apply (10-25 17:28 to 10-26 01:23, and
  10-26 03:04 to 07:31); no log records their cause.
- **Merges of the other session's commits.** The other session worked on DECISIONS.md, PLAN-v2.md, COVERAGE.md,
  COVERAGE-P9-P11.md, HANDOVER.md, two reviews files and prompts P2-P11. Its commits were merged ten times: c461cde
  (86b7cbc, c728380), 1715fdd (fa5659d), 3c5cc08 (32a6967, f65290d), d6c7d19 (f732f26), cf5d5a8 (4cc52aa), 02f2e6f
  (9380922), ec2681d (b335a0e), 976adef (7beb706), 9e796b8 (e428c5b) and 00b8c18 (bb56fe5). None of them changed
  P1b.md, P1c.md or inventory/. After a merge the next verifiers re-checked owner quotes against the merged
  DECISIONS.md and every P1c or P1b cite into the merged files (for example P1c r4 after 1715fdd, r5 after 3c5cc08).
  The other session's own merges of this branch (686b375, 3f01eea, 4ab7cf1, 92b4d9b, ad5674b, 2b4ea19, 3ef1eca,
  a085da8, d16129f) came back through those merges.
- **Batching.** P1b and P1c were verified on their own clocks: P1c round 1 ran right after the P1c clusters, P1b round 1
  only after wave 2 was committed, and P1c reached round 24 while P1b reached round 19 (r19b). Verifiers of one prompt
  often worked while the other prompt or the inventory was being edited; they recorded the md5 or commit they read and
  reported a cross-file mismatch only where their own file was wrong. Fix lanes of P1b rounds 1-8 and of P1c rounds 1-13
  edited the working file directly and were committed once per round (P1c round 1 with wave 2, in d22c669); the
  single-issue P1b lanes of r10b-r14b and every P1c fix lane from round 14 on were committed alone. Patch rounds applied
  many lanes in one commit: 16 lanes (44 edits) in 0bdd73d, 12 in 5b2b3d9, 8 in 87cdbe3, 10 in a12fb1d, 8 in 0381276, 7
  in e73c58d, 7 in b155101, 2 in ef34dbc; inventory sweeps applied all three parts at once (31acd8f, d6409c2, 4ce4271,
  37a259a). In round 16 the P1b lanes' work folder was briefly renamed; the applier checked that each patch file was the
  one its lane had run (8 of 8 matched) before applying.
- **Refused file write.** One report was returned as text: the inventory round 14 part 3 verifier's write was
  refused, and the orchestrator saved its reply verbatim as that part's report (the report's own header says so).
  Most patch and lane roles from round 14 on tell agents to do exactly this.

### Round ids

- r1-r9: P1b and P1c rounds 1-9; r1-r4 are also inventory rounds 1-4.
- r10-r24: P1c rounds 10-24, with the cross-checks r18 and r20; r24 is P1c's final round.
- r10b-r19b: P1b rounds 10-19; r19b, with the check fix-R19B-1 of its one fix, is P1b's final round.
- r5inv-r16inv: inventory rounds 5-16; r16inv is the last (targeted) round.

## Open low items

The owner ruled that only defects rated medium or above in the final round get fixed. Each low one is listed here with
its file, location, problem and suggested fix. This section holds every low defect of the final round (P1b round 19b
with the check of its one fix, P1c round 24) and the three round-18b lows on P1b that the ruling left unfixed. None of
them is applied.

### Base and conventions

- **Files read.** HEAD 382d857; the working tree was clean.
  - prompts/P1b.md: 1311 lines, md5 402e13fc2d0c8eeaf8ced3029e13a3ed, `## Context (read once)` at :1214.
  - prompts/P1c.md: 1212 lines, md5 7e5f22f878acd2fcf6009659fbe87249, unchanged since 9bd18bb, `## Context (read
    once)` at :1115.
  - Line numbers below are these files' at 382d857. Code cites inside quoted texts are the sources' own, at d625284.
- **Changes after the sources were written.**
  - The round-18b lane patches were written at b155101. ef34dbc then changed P1b.md:766 (row 11) and :774 (row 19,
    rule 5), and 382d857 changed :766 again (R19B-1's fix, the attestation clause).
  - The round-19b and round-24 reports were written at ef34dbc. Since then only P1b.md:766 changed (382d857).
  - The R19B-1 fix log records no new low item and leaves every item below as recorded. The independent check of 382d857
    (round r19b report fix-R19B-1) found three lows in the clause it added, R19B-1-V1 to R19B-1-V3, listed below.
- **Re-anchoring.** Every old text below was checked against the two files at 382d857, read only and in memory.
  - Each occurs exactly once in its file and 0 times in the other prompt.
  - This holds for the six row 11 texts (R19B-FR-1, R19B-4 edit 1, R18B-3 edit 2, R19B-1-V1 to V3) after 382d857 and for
    the row 19 text (R18B-3 edit 1) after ef34dbc. No old text needed a correction.
  - Each new text is ASCII, adds no `|`, keeps its old text's parenthesis balance and adds backticks only in pairs.
- **Text forms.** "Part of line": the old text is a substring of one line; each table row is one line and stays one.
  "Whole lines": the old text is complete lines with their leading spaces and without the final line break, and the
  new text replaces them. The fences hold the texts exactly.
- **Line shifts.** Five edits add lines: R18B-FR-3 edit 1 (+5 at P1b :894), R19B-4 edit 2 (+1 at :997), R19B-3 (+1 at
  :1063), R18B-FR-3 edit 2 (+1 at :1166) and R18B-FR-3 edit 3 (+3 at P1c :924). Each line number below is the one
  before any edit; an applier finds old texts by content.

### Index

16 low ids from seven reports, in 13 items. RA24-1 is R24-1 found by the other lens, so the two share one item. R19B-2
and R19B-FR-2 also describe one defect, but each lens gave its own text, so each keeps its item (see "How the edits
compose").

| Id | Found in | File | Line at 382d857 | Place | Edits | Composes with |
|---|---|---|---|---|---|---|
| R19B-FR-1 | round 19b, faithful/rules | P1b.md | 766 | row 11, Deleted | 1 | R19B-4 edit 1 (overlap: joint text, see "How the edits compose") |
| R19B-FR-2 | round 19b, faithful/rules | P1b.md | 768 | row 13, Deleted | 1 | R19B-2 (overlap: apply one, see "How the edits compose") |
| R19B-FR-3 | round 19b, faithful/rules | P1b.md | 772, 773 | rows 17 and 18, Deleted | 1, plus 1 optional | none |
| R19B-FR-4 | round 19b, faithful/rules | P1b.md | 768 | row 13, Deciding consumer kept | 1 | none |
| R19B-2 | round 19b, refs/acceptance | P1b.md | 768 | row 13, Deleted | 1 | R19B-FR-2 |
| R19B-3 | round 19b, refs/acceptance | P1b.md | 1063 | acceptance 21 | 1 | none |
| R19B-4 | round 19b, refs/acceptance | P1b.md | 766, 997 | row 11, Deleted; acceptance 12 | 2 | R19B-FR-1 |
| R19B-1-V1 | round 19b, check of the R19B-1 fix | P1b.md | 766 | row 11, Deleted (382d857's clause) | 1 | none (disjoint from every other text) |
| R19B-1-V2 | round 19b, check of the R19B-1 fix | P1b.md | 766 | row 11, Deleted (382d857's clause) | 1 | none (disjoint from every other text) |
| R19B-1-V3 | round 19b, check of the R19B-1 fix | P1b.md | 766 | row 11, Deleted (382d857's clause) | 1 | none (disjoint from every other text) |
| R24-1 = RA24-1, R24-2 | round 24, both lenses | P1c.md | 932-934 | acceptance 12 | 1 (joint) | none |
| R18B-3, R18B-FR-2 | round 18b, both lenses; removals lane | P1b.md | 766, 769, 772, 774 | rows 11, 14, 17, 19 | 6 | none |
| R18B-FR-3 | round 18b, faithful/rules; prnames lane | P1b.md, P1c.md | P1b 894, 1166-1167; P1c 924 | acceptance 5; PR body; P1c acceptance 11 | 3 | none |

### Final round, P1b (round 19b)

Sources: the round r19b reports faithful-rules-P1b (R19B-FR-1 to FR-4) and refs-acceptance-P1b (R19B-2 to R19B-4), both
written at ef34dbc. Each report rated these items low and gave the fix texts used below.

#### R19B-FR-1 (low): row 11's `.lck` deletion leaves the finalizer's stale-pointer reap without its liveness input

- **File.** harness-repair-plan/prompts/P1b.md.
- **Location.** :766, row 11, column "Deleted"; part of line: "and the PostToolUse finalizer's restore and lock reap
  (hooks/posttool-allowlist-consume.py :669-684, :410-457; a failed commit's next attempt takes a fresh grant from
  /commit's retry routes, commit.md:817-828, :843-844);".
- **Problem.** Row 11 deletes every `.lck` read and takes the grant's two paths out of the pointer. The finalizer's
  kept stale-pointer reap (`_reap_stale_pointers` :460-534) then loses the repository its liveness test reads
  (`_locked_grant_repo` :402-407, at :526). Read literally, it reaps a still-running commit's pointer once that pointer
  is 1800 s old, and that commit gets no commit-journal entry (A70).
- **Fix.** Old:

~~~
and the PostToolUse finalizer's restore and lock reap (hooks/posttool-allowlist-consume.py :669-684, :410-457; a failed commit's next attempt takes a fresh grant from /commit's retry routes, commit.md:817-828, :843-844);
~~~

New:

~~~
and the PostToolUse finalizer's restore and lock reap (hooks/posttool-allowlist-consume.py :669-684, :410-457, called at :531-533; a failed commit's next attempt takes a fresh grant from /commit's retry routes, commit.md:817-828, :843-844), while its stale-pointer reap (`_reap_stale_pointers` :460-534) keeps its test that no commit runs in the grant's repository (:523-530), taking that repository from the pointer in place of the `.lck` (`_locked_grant_repo` :402-407);
~~~

- **Composes.** Its old text contains R19B-4 edit 1's old text; see "How the edits compose" for the joint text.

#### R19B-FR-2 (low): row 13 names posttool-subagent-track.py's never-run contract test as a second deciding rule

- **File.** harness-repair-plan/prompts/P1b.md.
- **Location.** :768, row 13, column "Deleted"; part of line: "posttool-subagent-track.py's second reading of the
  contract bookmark (:397) and its own existence and schema test of the matched entry's file ... a second rule beside
  posttool-overnight-file-check.py's at the same PostToolUse; the artifact-status sidecar writer
  (posttool-overnight-file-check.py:316-330) if its reader (posttool-subagent-track.py:358-368, called at :403; A79)
  is gone;".
- **Problem.** The hook's contract path never runs: it asks only for cycle 0's contract (:269-288), no writer sets a
  cycle in the workflow bookmark, and contracts start at cycle 1. So the deletion is D17 dead code, not a D24 second
  rule. The sidecar's only reader sits in the same dead path, so "if its reader ... is gone", read literally, can leave
  both the reader and the sidecar writer in place.
- **Fix.** Old:

~~~
posttool-subagent-track.py's second reading of the contract bookmark (:397) and its own existence and schema test of the matched entry's file (`_validate_artifact_for_entry` :341-355, called at :402; A19, A34), a second rule beside posttool-overnight-file-check.py's at the same PostToolUse; the artifact-status sidecar writer (posttool-overnight-file-check.py:316-330) if its reader (posttool-subagent-track.py:358-368, called at :403; A79) is gone;
~~~

New:

~~~
posttool-subagent-track.py's contract path (`_enforce` :391-407: its reading of the contract bookmark, :397, its existence and schema test of the matched entry's file, `_validate_artifact_for_entry` :341-355, called at :402, A19, A34, and its read of the artifact-status sidecar, :358-368, called at :403, A79), which no run reaches (D17 reachability proof): the hook loads a contract only for the cycle the workflow bookmark's `cycle`, `cycle_id` or `active_cycle` key names, else 0 (:269-288, called at :480), no writer of the bookmark sets those keys, and contracts start at cycle 1 (create-overnight-state.sh:709-711, dev-overnight.md:833); the artifact-status sidecar writer (posttool-overnight-file-check.py:316-330), whose only reader is in that path;
~~~

The report notes that this text differs from the round-16 adjudication's PB1 text, which labels A79 by the
unapplied map patch's wording.
- **Composes.** R19B-2 edits a text inside this old text; apply one of the two ("How the edits compose").

#### R19B-FR-3 (low): doc-sync's CLAUDE.md creation and header prepend fall between P1b and P9

- **File.** harness-repair-plan/prompts/P1b.md.
- **Location.** :772, row 17, column "Deleted"; part of line: "and with it the hook-landed-files ledger and the
  aggregator's merge (row 6);". Optional second edit: :773, row 18, column "Deleted"; part of line:
  "`<proj>/.claude/CLAUDE.md` (read at session-info.sh:26; the user's project file, which the CLI loads)".
- **Problem.** doc-sync creates a missing project CLAUDE.md, prepends its header to one without it and rewrites its
  AUTO sections (hooks/doc_sync/claude.py:18-30, patch.py:135-162), and its prompt-time re-run does the same to the
  `.claude/` copies (userprompt-doc-sync-check.py:186). E9 (:517-544) and row 17 name only INDEX.md and README.md,
  while P9.md:437-440 says P1b took these creation paths.
- **Fix, row 17.** Old:

~~~
and with it the hook-landed-files ledger and the aggregator's merge (row 6);
~~~

New:

~~~
and with it the hook-landed-files ledger and the aggregator's merge (row 6); under E9's update-only rule, doc-sync's creation of a missing CLAUDE.md and its header prepend to one without its header (hooks/doc_sync/claude.py `ensure_claude_md` :18-30, called at patch.py:135, in both doc-sync runs: posttool-doc-sync.py, and the prompt-time re-run, which takes `<root>/.claude` as the project, userprompt-doc-sync-check.py:186), so it writes only inside the AUTO sections a CLAUDE.md already holds (patch.py:137-162; the date block among them stays P9's, P9 row 2);
~~~

- **Fix, row 18 (optional; it completes a true sentence).** Old:

~~~
`<proj>/.claude/CLAUDE.md` (read at session-info.sh:26; the user's project file, which the CLI loads)
~~~

New:

~~~
`<proj>/.claude/CLAUDE.md` (read at session-info.sh:26; the user's project file, which the CLI loads and doc-sync's prompt-time re-run also writes, row 17)
~~~

#### R19B-FR-4 (low): row 13's list of the overnight state's deciding readers leaves out hooks/merge.sh

- **File.** harness-repair-plan/prompts/P1b.md.
- **Location.** :768, row 13, column "Deciding consumer kept"; part of line: "git-policy-shim:246-267); /stop's read
  (break-overnight-lock.py:118) belongs to its write".
- **Problem.** hooks/merge.sh's cleanup after a merge (:338-355) globs the overnight state records, reads
  `worktree_branch` (else `branch` or `focus_branch`) by its own rule and removes the record that names the merged
  branch. Row 13's list omits it, although its clause "every other deciding reader" covers it.
- **Fix.** Old:

~~~
git-policy-shim:246-267); /stop's read (break-overnight-lock.py:118) belongs to its write
~~~

New:

~~~
git-policy-shim:246-267), and hooks/merge.sh, whose cleanup after a merge reads each record's worktree_branch (else branch or focus_branch) and removes the one that names the merged branch (:341-355; A76); /stop's read (break-overnight-lock.py:118) belongs to its write
~~~

#### R19B-2 (low): row 13 calls the contract-entry test a live second rule, but no real run reaches it

- **File.** harness-repair-plan/prompts/P1b.md.
- **Location.** :768, row 13, column "Deleted"; part of line: "its own existence and schema test of the matched entry's
  file (`_validate_artifact_for_entry` :341-355, called at :402; A19, A34), a second rule beside
  posttool-overnight-file-check.py's at the same PostToolUse;".
- **Problem.** The same defect as R19B-FR-2, found by the other lens: the test runs only on the contract path, which
  no Agent call reaches because the hook loads cycle 0's contract and none exists. The deletion is still right, but
  its proof is D17 reachability, not goal 2.
- **Fix.** Old:

~~~
its own existence and schema test of the matched entry's file (`_validate_artifact_for_entry` :341-355, called at :402; A19, A34), a second rule beside posttool-overnight-file-check.py's at the same PostToolUse;
~~~

New:

~~~
its own existence and schema test of the matched entry's file (`_validate_artifact_for_entry` :341-355, called at :402; A19, A34), a second rule beside posttool-overnight-file-check.py's at the same PostToolUse wherever its contract path runs, which at d625284 no real run reaches (the hook asks for cycle 0's contract, `_cycle_id_from_state` :269-277, called at :285, since nothing writes a cycle into the bookmark, and no contract is numbered 0, so every Agent call takes :493-525): the PR gives that reachability proof (D17), as for the sidecar read at :403;
~~~

- **Composes.** Its old text lies inside R19B-FR-2's; apply one of the two ("How the edits compose").

#### R19B-3 (low): acceptance 21's provision call is attributed to no session under rule 5's scope

- **File.** harness-repair-plan/prompts/P1b.md.
- **Location.** :1063, acceptance 21; whole line: "    hooks/tests/test_laneb_stop_coordinator.py:38-45 does. Bind a
  resource session to an overnight session with". :1064 stays as it is.
- **Problem.** Under row 19 rule 5's scope (ef34dbc), the replay's `session-resources.py provision` call is the main
  agent's write only if it runs as one of that agent's tool calls. Run as a plain process, it makes the Stop
  coordinator's finalize decision on the resource record a completion read that rule 5 fails, so the check is red at
  Rollback's (6).
- **Fix.** Old (one whole line):

~~~
    hooks/tests/test_laneb_stop_coordinator.py:38-45 does. Bind a resource session to an overnight session with
~~~

New (two lines, 116 and 107 characters):

~~~
    hooks/tests/test_laneb_stop_coordinator.py:38-45 does. Bind a resource session to an overnight session through a
    Bash call of the replay's main agent (row 19 rule 5 then counts its writes as that session's) that runs
~~~

#### R19B-4 (low): the text that describes the deleted restore and `.lck` is left in place

- **File.** harness-repair-plan/prompts/P1b.md.
- **Location.**
  - Edit 1: :766, row 11, column "Deleted"; part of line: "a failed commit's next attempt takes a fresh grant from
    /commit's retry routes, commit.md:817-828, :843-844);".
  - Edit 2: :997, acceptance 12; whole line: "    main agent's own step), or a reworded path or commit line (row 12,
    Correction 5).".
- **Problem.** Once row 11 deletes the finalizer's restore and the `.lck`, the text that describes them becomes false
  (commands/commit.md:1038; agents/changelog-analyst.md:1657-1659, :1960, :1962), and row 11 does not name it.
  Shortening such a line adds a numstat line that none of acceptance 12's listed kinds covers.
- **Fix, edit 1.** Old:

~~~
a failed commit's next attempt takes a fresh grant from /commit's retry routes, commit.md:817-828, :843-844);
~~~

New:

~~~
a failed commit's next attempt takes a fresh grant from /commit's retry routes, commit.md:817-828, :843-844; the clauses that describe that restore or the `.lck` go with them, commands/commit.md:1038, agents/changelog-analyst.md:1657-1659, :1960, :1962);
~~~

- **Fix, edit 2.** Old (one whole line):

~~~
    main agent's own step), or a reworded path or commit line (row 12, Correction 5).
~~~

New (two lines, 119 and 42 characters):

~~~
    main agent's own step), a reworded path or commit line (row 12, Correction 5), or a line left without a clause that
    describes code a row deletes (row 11).
~~~

- **Composes.** Edit 1's old text is the end of R19B-FR-1's old text; see "How the edits compose" for the joint text.

### Final round, P1b: the check of R19B-1's fix (382d857)

Source: round r19b report fix-R19B-1, the independent check of 382d857, written at 382d857. It found that 382d857 fixes
R19B-1 and adds no defect of medium or above, and rated these three items low. Their old texts lie in the clause 382d857
inserted in row 11; for this record each was checked once against P1b.md at 382d857: it occurs once there and 0 times in
P1c.md, and each new text is ASCII and adds no `|`.

#### R19B-1-V1 (low): row 11's reason ignores the live, unclaimed attestation of Step 6's dry-run dispatch

- **File.** harness-repair-plan/prompts/P1b.md.
- **Location.** :766, row 11, column "Deleted", in 382d857's clause; part of line: "and an attestation deleted at the
  first commit refuses the second, a hook rejection that /commit turns into an AWAITING_INPUT line for a human,
  commit.md:846-849;".
- **Problem.** /commit's Step 6 always dispatches the changelog-analyst with `DRYRUN=true` after Step 5's mint, and that
  run never commits (commit.md:476-483). The attest hook writes an attestation for every changelog-analyst dispatch
  (pretool-commit-dispatch-attest.py:70-107; commit_pipeline.py:519-571), and the selector takes any attestation that is
  live (30 minutes, :128, :575-592), post-mint and unclaimed (:641-645), newest first (:669-676). So within 30 minutes
  of Step 6 an attestation deleted at the first commit does not refuse the second: the second commit is admitted on the
  dry run's attestation, and the base's own claim lets a stray subagent spend the second grant on it. The fix's
  requirement and replay still catch both failures; the clause is an incomplete reason that hides the hole the chosen
  form must close.
- **Fix.** Old:

~~~
and an attestation deleted at the first commit refuses the second, a hook rejection that /commit turns into an AWAITING_INPUT line for a human, commit.md:846-849;
~~~

New:

~~~
and an attestation deleted at the first commit refuses the second, a hook rejection that /commit turns into an AWAITING_INPUT line for a human, commit.md:846-849, or, while the attestation of Step 6's dry-run dispatch, which no commit claims (commit.md:483), is live (30 minutes, hooks/lib/commit_pipeline.py:128), admits the second on that one, which the selector also gives any other subagent (:641-645);
~~~

#### R19B-1-V2 (low): the replay's refusal does not name the hook that must refuse

- **File.** harness-repair-plan/prompts/P1b.md.
- **Location.** :766, row 11, column "Deleted", in 382d857's clause; part of line: "and another subagent's `git commit`
  on the second repository between them is refused;".
- **Problem.** The replay's positive half names its decider ("no block from the privilege guard"), and the clause before
  it makes the guard the attestation's one decider, but the negative half names none. In the sandbox-armed kit a refusal
  from another hook, for example a G1 or subagent-enforce refusal of an unregistered subagent, would satisfy it without
  exercising the binding.
- **Fix.** Old:

~~~
and another subagent's `git commit` on the second repository between them is refused;
~~~

New:

~~~
and another subagent's `git commit` on the second repository between them is refused by the privilege guard;
~~~

#### R19B-1-V3 (low): "its one decider" and "of it" can be read as the plan

- **File.** harness-repair-plan/prompts/P1b.md.
- **Location.** :766, row 11, column "Deleted", in 382d857's clause; part of line: "with the guard as its one decider,
  no second writer of it, no state file added".
- **Problem.** The nearest antecedent of "its" and "it" is "that dispatch's plan", while the fix means the attestation.
  Read as the plan, the clause makes the guard a decider of the manifest's plan, whose decider is
  `verify_pipeline_dispatch` (column "Deciding consumer kept"; A62).
- **Fix.** Old:

~~~
with the guard as its one decider, no second writer of it, no state file added
~~~

New:

~~~
with the guard as the attestation's one decider, no second writer of the attestation, no state file added
~~~

### Final round, P1c (round 24)

Sources: the round r24 reports faithful-rules-P1c (R24-1, R24-2) and refs-acceptance-P1c (RA24-1), both written at
ef34dbc with P1c.md at 9bd18bb. The refs lens rated RA24-1 the same defect as R24-1 and gave the faithful lens's joint
text, so this record carries one edit.

#### R24-1 = RA24-1 and R24-2 (low): acceptance 12's D24 list misattributes settings.json and omits X3's artifacts

- **File.** harness-repair-plan/prompts/P1c.md.
- **Location.** :932-934, acceptance 12 ("**D24 table** for every artifact rows 7-20 or X2 touch", :925); whole
  lines. :932 holds "settings.json (row 20, if taken), each".
- **Problem, R24-1 = RA24-1.** The list credits settings.json only to row 20, but row 9 (X3, :543) is the row that
  writes it (the `CLAUDE_OBLIGATION_STOPGATE` switch), and with a deleted copy G2 reads it at run time (:302-304). On
  a branch where X3 arms G2 and X9 (ii) holds, "(row 20, if taken)" leaves settings.json out of the D24 table.
- **Problem, R24-2.** No list item names the artifacts on which X3's deletions remove a deciding copy, for example
  the spec views that stop-spec-coverage-enforce.py's `--strict` rule decided on. Both stay low because the item's
  lead (:925) and D24 (:215-217) cover these artifacts.
- **Fix (joint, R24-1 and R24-2).** Old (three whole lines):

~~~
    orchestrator's own calls; row 17, X8), the product command files (row 18), settings.json (row 20, if taken), each
    state file X2's write audit moved: producers before -> after, deciding consumers before -> after, proof (writer and
    reader grep plus the suite's trace).
~~~

New (116, 113 and 111 characters; the line count is unchanged):

~~~
    orchestrator's own calls; row 17, X8), the product command files (row 18), settings.json (rows 9 and 20, each if
    taken), each artifact a copy X3 deleted decided on (row 9), each state file X2's write audit moved: producers
    before -> after, deciding consumers before -> after, proof (writer and reader grep plus the suite's trace).
~~~

- **Fix, R24-1 alone (if R24-2 is not taken).** Same old text. New (116, 114 and 58 characters):

~~~
    orchestrator's own calls; row 17, X8), the product command files (row 18), settings.json (rows 9 and 20, each if
    taken), each state file X2's write audit moved: producers before -> after, deciding consumers before -> after,
    proof (writer and reader grep plus the suite's trace).
~~~

### Round-18b lows left open (P1b)

Sources: the round r18b reports refs-acceptance-P1b (R18B-3) and faithful-rules-P1b (R18B-FR-2, R18B-FR-3), written at
b155101, with the round-18b lane notes removals and prnames. Each lane judged its defects HOLDS WITH CORRECTION, and its
patch supersedes the fix text the reports proposed. Neither patch was applied in ef34dbc or 382d857.

#### R18B-3 and R18B-FR-2 (low): row 19 does not say how a removal counts

- **File.** harness-repair-plan/prompts/P1b.md.
- **Location.** :774, row 19, rule (1), in the row's last column; part of line: "a file one process creates and
  removes within one run is its private scratch;". Edits 2-6 align rows 11 (:766), 14 (:769) and 17 (:772) with it.
- **Problem, R18B-3.** Row 19 does not say whether removing a file is a write, a consumption or a decision output.
  Row 11 calls the grant spend consumption, rows 14 and 17 route unlinks through the one writer, and the inventory
  counts a removal as a producer (A90), so row 14's tool-streak replay and the rule-5 status of the Stop reaps turn on
  an unstated answer.
- **Problem, R18B-FR-2.** No rule classes the host cron's /tmp sweep (scripts/install/tmp-cleanup-install.sh:150-165
  through `run_tmp` :85-111), which no hook, command, agent or skill runs. Whether the check fails on nine hook-state
  families (A90 among them) therefore depends on the static parser's recall, not on a rule.
- **Fix.** The removals lane's six edits, in order (all part of line). Each old text was written at b155101; edit 2
  (row 11) still occurs once after ef34dbc and 382d857, edit 1 (row 19) still occurs once after ef34dbc, and none
  needed a correction. The reaps that edit 2's "each reap below" refers to still follow in the same cell.
- **Edit 1, row 19 rule (1).** Old:

~~~
a file one process creates and removes within one run is its private scratch;
~~~

New:

~~~
a file one process creates and removes within one run is its private scratch; removing a file writes it, except that a reader of that file (rule 3) that removes it consumes it (the guard's spend of a single-use grant, a sentinel consumed at its command's terminal result, a Stop reap of an expired one): the removal is part of that read, and a decision output of it (E1) only where it follows a test of the content other than the return value of that file's one deciding function (rule 4); a SessionEnd hook's removal of files whose path holds the ending session's id (sessionend-scratch-sweep.sh:94, that session's own directory) writes none of them; and host housekeeping that no hook, command, agent or skill runs, directly or through another script, and that selects files by a name pattern and stat data (age, type) alone, reading none (the installer's cleanup rules, as acceptance 9 classes them: scripts/install/tmp-cleanup-install.sh, which the operator installs for cron, :150-165 through `run_tmp` :85-111, and the tmpfiles rules beside it), is the host's, as the CLI's own loads are the platform's: neither a write nor a read;
~~~

- **Edit 2, row 11, column "Deciding consumer kept".** Old:

~~~
(spending a single-use grant deletes it: consumption;
~~~

New:

~~~
(spending a single-use grant deletes it, as each reap below deletes what it read: consumption, row 19 rule 1;
~~~

- **Edit 3, row 14, column "One producer kept".** Old:

~~~
(`_clear_turn_state` :1999-2016, today a second code path that unlinks the file)
~~~

New:

~~~
(`_clear_turn_state` :1999-2016, today a second writer: it unlinks the file and reads none of it, row 19 rule 1)
~~~

- **Edit 4, row 14, column "Deciding consumer kept".** Old:

~~~
its sentinel reap (stop-cleanup-allowlist.sh:39-45, hooks/lib/allowlist.py `reap_expired_sentinel_grants` :712-747) takes
~~~

New:

~~~
its sentinel reap (stop-cleanup-allowlist.sh:39-45, hooks/lib/allowlist.py `reap_expired_sentinel_grants` :712-747), a consumption (row 19 rule 1), takes
~~~

- **Edit 5, row 17, column "One producer kept".** Old:

~~~
also unlinks INDEX.md from one whose list is left empty (:164-176): that removal goes through the same function (A108).
~~~

New:

~~~
also unlinks INDEX.md from one whose list is left empty (:164-176), reading none of it: that removal, a second writer (row 19 rule 1), goes through the same function (A108).
~~~

- **Edit 6, row 17, column "Deciding consumer kept".** Old:

~~~
the sweep (sessionend-scratch-sweep.sh:75-92, which deletes the directory only then)
~~~

New:

~~~
the sweep (sessionend-scratch-sweep.sh:75-92, which deletes the directory only then, :94, a removal that writes none of the files it holds, the notice's dedupe state among them: row 19 rule 1)
~~~

#### R18B-FR-3 (low): the release note's "the PR names each such fault" has no instruction behind it

- **Files.** harness-repair-plan/prompts/P1b.md and harness-repair-plan/prompts/P1c.md.
- **Location.** The promise: P1b.md:132-137, the release note under "Goal", ending "the PR names each such fault."
  (:136-137). The edits: P1b.md:894 (acceptance 5's last line, whole line), P1b.md:1166-1167 ("Branch and pull
  request", the PR-body bullet's Faults heading, whole lines) and P1c.md:924 (acceptance 11's last line, whole line).
- **Problem.** No acceptance item and no PR heading says how to find or list the faults that pass because their
  producer's last stop came before the merge. The prnames lane found that a static test ("whether a check an in-flight
  run still reaches decides on that artifact") misreads row 8's own instance, so its fix measures them by replay.
  P1c's X3 makes the same promise (:310, "the PR names each such fault and the deleted copy that stopped it") with
  nothing to measure it.
- **Edit 1, P1b.md:894, acceptance 5.** Old (one whole line):

~~~
   and never on a compliant split of that text.
~~~

New (six lines, 120, 118, 118, 115, 120 and 50 characters):

~~~
   and never on a compliant split of that text. Replay once more, in acceptance 17's in-flight form (the base's text and
   settings.json in your branch's kit), each fault whose stop on your base, shipped, is a check you delete from a hook
   or script file, with the fault made just after its producer's last stop (a stop before your merge, where the base's
   G2 blocked nothing): name the check that stops it there, or, where none does before the run's terminal, name the
   fault and the deleted check that stopped it on your base as a fault that passes in the release notes' window (row 8's
   split is one; row 19 lets no copy stay for it).
~~~

- **Edit 2, P1b.md:1166-1167, the Faults heading.** From "exist on your" on, the bullet is unchanged. Old (two whole
  lines):

~~~
  each); **Faults** (acceptance 5: the stop of each fault a deleted check used to stop, and the copies E4 keeps for P2
  with their gates); **Hand-off to P1c** (the runner, the drivers, how to add a fault, the dead ends that exist on your
~~~

New (three lines, 119, 117 and 118 characters):

~~~
  each); **Faults** (acceptance 5: the stop of each fault a deleted check used to stop, the copies E4 keeps for P2 with
  their gates, and each fault that passes when its producer's last stop came before the merge, with the deleted check
  that stopped it); **Hand-off to P1c** (the runner, the drivers, how to add a fault, the dead ends that exist on your
~~~

- **Edit 3, P1c.md:924, acceptance 11 (the text in the lane note).** It matters only on X3's branch that deletes
  copies. Old (one whole line):

~~~
    failing check, and the next round passes. Repeat with your branch's settings.json.
~~~

New (four lines, 118, 117, 98 and 74 characters):

~~~
    failing check, and the next round passes. Each such fault made instead just after its producer's last stop (a stop
    before your merge, where your base's G2 blocked nothing) is replayed too: name the check that stops it, or, where
    none does before the run's terminal, name the fault and the deleted copy that stopped it under
    "Decided by experiment" (X3). Repeat with your branch's settings.json.
~~~

The lane's working copy of this text wraps the same words differently; this record uses the lane note's.

### How the edits compose

- **R19B-FR-1 and R19B-4 edit 1 (row 11, Deleted).** R19B-4's old text is the end of R19B-FR-1's, so either edit
  removes the other's old text. To take both, replace R19B-FR-1's old text with this joint text (R19B-4's clause
  placed inside R19B-FR-1's new parenthesis; it equals applying R19B-4 first and then R19B-FR-1 on the shifted text):

~~~
and the PostToolUse finalizer's restore and lock reap (hooks/posttool-allowlist-consume.py :669-684, :410-457, called at :531-533; a failed commit's next attempt takes a fresh grant from /commit's retry routes, commit.md:817-828, :843-844; the clauses that describe that restore or the `.lck` go with them, commands/commit.md:1038, agents/changelog-analyst.md:1657-1659, :1960, :1962), while its stale-pointer reap (`_reap_stale_pointers` :460-534) keeps its test that no commit runs in the grant's repository (:523-530), taking that repository from the pointer in place of the `.lck` (`_locked_grant_repo` :402-407);
~~~

- **R19B-FR-2 and R19B-2 (row 13, Deleted).** One defect, two texts. R19B-2's old text lies inside R19B-FR-2's, and
  either edit removes the other's old text, so apply one. R19B-FR-2's text also rewrites the sidecar clause ("if its
  reader ... is gone"); R19B-2's keeps that clause and adds the reachability proof beside "a second rule".
- **Same row, disjoint texts (any order).**
  - Row 11: R19B-FR-1 and R19B-4 edit 1 in "Deleted"; R18B-3 edit 2 in "Deciding consumer kept"; R19B-1-V1 to V3 in
    "Deleted", inside 382d857's attestation clause, which none of the others touches. The three V texts do not overlap
    one another.
  - Row 13: R19B-FR-2 or R19B-2 in "Deleted"; R19B-FR-4 in "Deciding consumer kept".
  - Row 17: R19B-FR-3 in "Deleted"; R18B-3 edits 5 and 6 in "One producer kept" and "Deciding consumer kept".
- **R19B-FR-4 and R18B-3.** No shared text. The removals lane reads merge.sh's removal after its own test of the
  record as a decision (round-16 inventory part 2, D3/R1), which agrees with R19B-FR-4 naming merge.sh among the
  deciding readers.
- **All together, in memory at 382d857** (the joint row 11 text, R19B-FR-2 in place of R19B-2, every other edit,
  R19B-1-V1 to V3 included; re-run for this record):
  - every old text occurs once at its turn and every new text once after;
  - P1b.md goes from 1311 to 1319 lines, keeps its 35 table lines with the same count of `|` outside code spans,
    keeps 455 non-ASCII characters, line 1 `Owner steps: none.` and the tail from `## Context (read once)`;
  - P1c.md goes from 1212 to 1215 lines and keeps its tail.

### Notes for other plan files

- **P2 row 9's retro read in `closeout_gaps` (record for the plan files; no P1c fix).**
  - Source: round r24 report refs-acceptance-P1c, observation 2.
  - Target: harness-repair-plan/prompts/P2.md (last changed bb56fe5). :362-365, "- **`closeout_gaps(state,
    working_root)`**: `retro-report-cycle*.json` under ..." (Step 20's retro report and Step 21's summary), and :472,
    "The session ends once closeout_gaps is empty (retro reports and summary)."
  - Conflict: under P1b row 19 rule 5 (ef34dbc, P1b.md:774) the Step 21 summary is the main agent's own Write, so a
    time-lock check of it is on the producer side. The retro report is the PM subagent's (dev-overnight.md Step 20
    :1577, `subagent_type: "pm"` :1587, write path :1632), checked by G2 at its stop after P1b row 13. A time-lock read
    of it would be a second deciding rule (rule 4) and, with G2 armed, a Stop-time decision that rule 5 fails.
  - P1c already rules that read out (P1c.md:816-817 and acceptance 2), so P1c is not the file to change. The report
    gives no text: the plan-file lane should check P2.md:362-365 and :472 against P1b row 19 rules 4 and 5.
- **Coupled edit for PV-18 (P1b.md).**
  - PV-18 (For the plan files, PLAN-v2.md:1318-1328; pending, necessary) replaces section 15's 11-line takeover list
    with 3 lines, so the P1c bullet moves from PLAN-v2.md:1329 to :1321.
  - P1b.md:655 (correction 1) cites that bullet. Part of line; the old text occurs once in P1b.md and 0 times in
    P1c.md at 382d857. Apply it only together with PV-18:

    ~~~
    the caps again at :1199, :1311 and :1329, and
    ~~~

    becomes

    ~~~
    the caps again at :1199, :1311 and :1321, and
    ~~~

  - The orchestrator's running notes give this line as P1b.md:621, its number at an earlier commit; at 382d857 it is
    :655.

## Inventory: rows with known errors

The inventory (inventory/artifact-map-d625284.tsv, 121 rows, and inventory/README.md, both unchanged since 37a259a) is
planning evidence. P1b's first implementation step, row 0, regenerates the map on that day's master before anything
changes, and acceptance is measured on that map ("The d625284 map is a starting point", prompts/P1b.md:755 at
ef34dbc). The owner therefore stopped the inventory loop after round 16's targeted check. The rows below are listed,
not fixed here: the round-16 reports (parts 1-3), their patches (parts 1-3), the adjudication of the one dispute
between parts 1 and 2, and the adjudication's follow-up were not applied. The figures the plan files cite are those at
37a259a: P1b.md:743 counts 33 map rows whose evidence is code, and the plan-file records PF-1 and PF-2 (round 15) give
PLAN-v2.md:1176 and reviews/P1b-plan-sync.md:419 "43 / 56 / 29 / 24 of 121" (several producers / several deciding
consumers / written never read / read never written). P1c quotes no map figure and names no row id.

### What the unapplied patches would change in the counts

Applied together (part 1 as the adjudication rules it, part 2, part 3 with its new row A126, then the follow-up), the
patches move these README figures (I1's method). Parts 1 and 2 move none on their own.

| figure (README line at 37a259a) | 37a259a | all patches | with A109's optional edits (K19) |
|---|---|---|---|
| artifacts (rows) (:18) | 121 | 122 (A126) | 122 |
| covering the ledger rows / outside the ledger (:19, :20; "adds N" at :40) | 81 / 40 | 81 / 41 | 81 / 41 |
| several producers (:21) | 43 | 44 (A126) | 45 (A109) |
| several deciding consumers (:22) | 56 | 56 (A126 +1, A78 -1) | 56 |
| consumer-side re-check / read never written / hand-written table (:23, :25, :26) | 32 / 24 / 35 | 32 / 24 / 35 | 32 / 24 / 35 |
| written never read (:24) | 29 | 30 (A79) | 30 |
| no violation found (:27) | 15 | 14 (A79) | 13 (A109) |
| evidence both / code / trace (:28); "N rows rest on code reading alone" (:138) | 87 / 33 / 1; 33 | 87 / 34 / 1; 34 (A126) | 87 / 34 / 1; 34 |
| check positions: producer stop / G1 / G3 / elsewhere (:30) | 41 / 9 / 28 / 78 | 41 / 9 / 27 / 78 (A79) | 41 / 9 / 27 / 78 |
| G17 (:37) | 8 | 9 (A126) | 9 |
| id range (:48) | A01-A125 | A01-A126 | A01-A126 |
| plan-file figure (PLAN-v2.md:1176, reviews/P1b-plan-sync.md:419) | 43 / 56 / 29 / 24 of 121 | 44 / 56 / 30 / 24 of 122 | 45 / 56 / 30 / 24 of 122 |

- Part 3's notes give 122 rows, 41 outside the ledger, several producers 44 (45 with A109's optional edits), several
  deciding consumers 57, 34 code-only rows, G17 9 and A01-A126. Their plan-file text, "44 / 57 / 29 / 24 of 122",
  predates the follow-up.
- The adjudication's follow-up then gives, on the same base with part 3: several deciding consumers 57 -> 56 (A78),
  written never read 29 -> 30, no violation found 15 -> 14 and G3 collection 28 -> 27 (A79). With part 1 as ruled and
  part 2 alone, I1's counts are unchanged.
- The "all patches" column composes the two. An in-memory recount by I1's method of the four edit lists, in that order,
  on the 37a259a TSV gives the same figures, and with A109's optional edits on top, 45 and 13.
- The README's `build_map.py` list (:507-510) changes by I2's rule: part 3 drops "122 rows" and adds "40 outside the
  ledger", "33 code-only rows" and "G17 8"; the follow-up adds "written never read 29".

### Trace T: the hook path several rows rest on (adjudication, code at d625284)

hooks/posttool-subagent-track.py (PostToolUse, matcher Agent) runs its contract path, `_enforce` (:391-407), only when
`_try_load_contract` (:280-288, called at :480) returns a contract (:480-491). That path holds the test of a contract
entry's file (:341-355, called at :402), the contract-bookmark read (:397), the artifact-status sidecar read (:358-368,
called at :403) and contract_runtime's reconcile (hooks/lib/contract_runtime.py:1208-1250, whose only caller is :377).
The cycle asked for is the one the workflow bookmark's `cycle`, `cycle_id` or `active_cycle` key names, else 0
(:269-277). No writer of the bookmark sets those keys (hooks/prompt-workflow.py `_write_bookmark` :1980-1994 and the
later todo, gate and Path B writers), so `load_contract` tries only cycle-0 names (hooks/lib/contract_runtime.py
:79-98, :118-126), while contracts are numbered from 1 (scripts/create-overnight-state.sh:709-711;
commands/dev-overnight.md:833). The hook therefore always takes Path B (:493-525), which marks steps from the todo list
and opens no artifact.

### Known errors

TSV lines count the header as line 1. P1b.md and P1c.md lines are at ef34dbc. Every old text the records quote still
occurs once there, at the line the patch notes give against b155101 (P1b.md) and 95ff638 or 9bd18bb (P1c.md). Patch ids:
"part1 edit N" and "part3 edit N" are 0-based positions in those patches' EDITS, "part2 EN" 1-based, "follow-up edit N"
0-based in the adjudication's follow-up list. Severity is the verifier's; the follow-up gives none.

| # | row or README line at 37a259a | source | error | evidence (d625284) | fix as the patch notes give it | count effect | P1b.md / P1c.md |
|---|---|---|---|---|---|---|---|
| K1 | A09 (TSV :10) | part 1 INV16-1, medium | `readers`, `deciding_consumers` and `check_producer_stop` file hooks/prompt-workflow.py's progress notice and workflow-conflict warning, which only print, as a decider and a producer-stop check; its one deciding read, the archive's collision check at a /dev, /dev-command or /redev start, is not among the readers. | hooks/prompt-workflow.py:1205-1227 (called :1259), :1286-1293, :1298-1307 (called :1874, :1935); archive :1802-1828 (called :1893), raise :1825-1828, swallowed by main :2052-2054 | `readers`: name both print-only reads and add the archive's read (part1 edit 0); `deciding_consumers`: prompt-workflow.py only for the collision check (edit 1); `check_producer_stop`: the same (edit 2); README: the A09 sentence of part 1's correction passage before :507 (part1 R2) | none | none (P1b.md:757, row 2, calls both reads readers and deletes workflow-history with the check) |
| K2 | A09 (TSV :10) | follow-up | `producers` names contract_runtime's reconcile as a writer, a write that never happens (trace T); `resolution` calls that branch only "not replayed". | trace T; hooks/posttool-subagent-track.py:377 | `producers`: delete the reconcile entry (follow-up edit 20); `resolution`: state that it never runs (edit 21); README: the follow-up's correction passage | none | P1b.md:595 (E13): PB3, optional (the reconcile never runs) |
| K3 | A19 (TSV :19) | follow-up | `readers`, `deciding_consumers` and `check_G3_collection` name posttool-subagent-track.py's test of the file of the contract's BA entry, which never runs. | trace T; commands/dev-overnight.md:836 | `readers`: posttool-overnight-file-check.py `_run_check` :343-370 alone (follow-up edit 0); `deciding_consumers`: delete the hook (1); `check_G3_collection`: drop the hook (2); README :392-396: "four checks" -> "three checks", the hook dropped (follow-up README 5) | none (other deciders and a G3 entry remain) | P1b.md:768 (row 13, Deleted): PB1, required ("a second rule beside posttool-overnight-file-check.py's at the same PostToolUse" is false) |
| K4 | A30 (TSV :29) | part 1 INV16-4, low | graphify-enrich.py writes the cache and reads graph.json back to decide whether to enrich, but that check sits under `check_elsewhere`, while the same rule puts ensure-async under `check_producer_stop`. | scripts/graphify-enrich.py:499-507, :515-518, :536; scripts/graphify_lib.py:245-263, :295; scripts/graphify-maintain.py:675-691 | `check_producer_stop`: add graphify-enrich.py:499-507 (part1 edit 11); `check_elsewhere`: delete it (edit 12); README :295: "ensure-async," -> "ensure-async and graphify-enrich.py's cache check," (part1 R1) and the passage's A30 sentence | none | none |
| K5 | A34 (TSV :33) | follow-up | As K3, for the contract's dev entry: the three cells name the hook's never-running test of the dev report. | trace T; commands/dev-overnight.md:837 | `readers`, `deciding_consumers`, `check_G3_collection`: drop the hook (follow-up edits 3-5); README :392-396 as K3 | none | P1b.md:768: PB1, as K3 |
| K6 | A44 (TSV :43) | part 1 INV16-2, low, as ruled | The cycle contract's QA entry names A44's report, and scripts/check-overnight-reports.py decides on it (exit 1), but no A44 cell names that script. The verifier's other half, posttool-subagent-track.py, is dropped (trace T). | commands/dev-overnight.md:838, :682; scripts/check-overnight-reports.py:25-48, :75-86, :124-148 | `readers` and `deciding_consumers`: add the script (part1 edits 3 and 4 as the adjudication reworded them); `check_elsewhere`: add it (edit 6); edit 5 (`check_G3_collection`, the hook alone) dropped; README: the passage's A44 clause without the hook (adjudication's rewording of part1 R2) | none | none: P1b.md:768 deletes the script's re-check with no row id; part 1's optional row-13 record dropped by the adjudication |
| K7 | A45 (TSV :44) | part 2 D1, low | `readers` lists the G2 qa wire, which builds the completion report's path only to drop the resolver's missing-artifact error for it and opens no file. | hooks/subagentstop-artifact-contract-enforce.py:528, :529-532, :554-555 | `readers`: delete the qa-wire entry (part2 E01); `resolution`: add the code read (E02); README: part 2's correction passage (part2 README 2) | none (the resolver stays a reader) | none |
| K8 | A48 (TSV :47) | part 2 D4, low, holds with correction | /close hands the close QA cp-state-qa.json and its SECOND ACTION only when that file exists, a route by its own rule, but A48 names /close only as a reader. | commands/close.md:511, :521-523, :525-527, :603 | `deciding_consumers`: add /close's orchestrator `{p}` (part2 E03); `check_elsewhere`: add close.md:511, :521-523 (E04); `violations`: name the existence test in the detail (E05); wording "the close QA", not "the QA close gate"; README: part 2's passage | none | none: P1b.md:763 (row 8) deletes close.md:504-519; whether :521-523 stays is the lane's design call, no record |
| K9 | A63 (TSV :62) | part 2 D6, low, holds with correction | hooks/posttool-allowlist-consume.py's finalizer reads the pointer named for its own event and consumes or restores the locked grant by the event's identity and the command's terminal result, after reaping over-age pointers no running commit claims; A63 lists it only as a reader. | hooks/posttool-allowlist-consume.py:460-534 (called :592), :537-686 (called :865-867), :590, :602, :616-624, :629-684, :686; settings.json:651-656, :776-781 | `deciding_consumers`: add the finalizer (part2 E06); `check_elsewhere`: add it at the commit's PostToolUse (E07); `violations`: name the Stop sweep's and the finalizer's rules in the detail (E08, added by the patch notes); README: part 2's passage | none | P1b.md:766 (row 11): R3, optional, written against b155101 and not applied; row 11 at ef34dbc names the finalizer as the grant pointer's one decider and its restore and lock reap under Deleted |
| K10 | A76 (TSV :75) | part 2 D3, low, holds with correction | hooks/merge.sh removes the overnight-state record whose branch field names the merged branch, by its own reading of the record, but A76 lists it only as a reader. | hooks/merge.sh:341-355; commands/merge.md:187, :210-213 | `deciding_consumers`: add merge.sh, citing commands/merge.md:210-213, not :212 (part2 E09); `check_elsewhere`: add it (E10); README: part 2's passage | none | P1b.md:768 (row 13, Deciding consumer kept): R1, recommended (merge.sh missing from "every other deciding reader"); E13's "four writers" stays true |
| K11 | A77 (TSV :76) | follow-up | `deciding_consumers` and `check_G3_collection` name the hook, and `readers` names its reconcile and sidecar read, all on the contract path that never runs; the "read never written" detail says the hook probes cycle 0 only outside overnight; `producers` names the reconcile's write and posttool-subagent-track.py:404{s}. | trace T; for PC1: hooks/posttool-overnight-file-check.py:109-114, :351; scripts/create-overnight-state.sh:774; hooks/stop-overnight-timelock.py:100-120; hooks/posttool-overnight-loop.py:120; hooks/pretool-subagent-enforce.py:86-99 | `readers`: the hook's `_try_load_contract` alone, with why it never loads (follow-up edit 6); `deciding_consumers` and `check_G3_collection`: delete the hook (7, 8); `violations`: "inside overnight too" (9); `producers`: delete the reconcile and :404{s} (19); README :113-114: add the probe inside overnight (follow-up README 2) | none | P1b.md:768 (row 13): PB2, optional; P1b.md:595 (E13): PB3, optional; P1c.md:622: PC1, recommended (the file check and pretool-subagent-enforce.py always say cycle 1, closeout the state's cycle_count, 0 in cycle 1, the hook always 0) |
| K12 | A78 (TSV :77) | follow-up | `readers`, `deciding_consumers` and `check_G3_collection` name the hook's contract-bookmark read, on the contract path that never runs, so "several deciding consumers" does not hold. | trace T; hooks/posttool-subagent-track.py:397 (through :309-318) | drop the hook from the three cells; `deciding_consumers`: posttool-overnight-file-check.py alone; `violations`: "hand-written table" alone (follow-up edits 10-13) | several deciding consumers -1 | P1b.md:768: PB1 (it names the hook's second reading of the contract bookmark, :397) |
| K13 | A79 (TSV :78) | follow-up | The artifact-status sidecar's only reader and decider, the hook's `_consult_artifact_status_sidecar`, is on the contract path that never runs, so the file is written never read; the row shows a reader, a decider, a G3 entry and "none found". | trace T; hooks/posttool-subagent-track.py:358-368 (called :403); writer hooks/posttool-overnight-file-check.py:316-330 | `readers`: "none: ..." (follow-up edit 14); `deciding_consumers` and `check_G3_collection`: none (15, 16); `violations`: written never read (17); `resolution`: add the code read (18); README :275-278 and :301: drop A79's reader (follow-up README 3, 4) | written never read +1; no violation found -1; G3 collection -1 | P1b.md:768: PB1, required (row 13 makes the sidecar writer's deletion depend on its reader going) |
| K14 | A88 (TSV :87) | part 2 D2, low | The Stop cleanup removes the legacy flag whenever it exists, with no read and no exit code; A88 names that as a decision, while README:467-469 counts such a removal by another component as a producer (A90's turn reset). | hooks/stop-cleanup-allowlist.sh:26-30, run by hooks/stop-workflow-coordinator.py:72; the sentinel reap (:39-45, hooks/lib/allowlist.py:712-747) stays a decider | `producers`: add the Stop removal (part2 E11); `deciding_consumers`: the phase only for the sentinel reap (E12); `violations`: the detail names the removal (E13); README :412-414 (part2 README 1) and part 2's passage | none (A88 already shows several producers) | none false: P1b.md:769 (row 14) deletes the legacy flag either way |
| K15 | A98 (TSV :97) | part 2 F.1, handled as part 3 P2-F.1 | `producers` lists scripts/install/tmp-cleanup-install.sh:47 without the "run by nothing" mark the cell gives its other unrun writers; the script is the host's cron script, which no harness entry point deploys or runs. | scripts/install/tmp-cleanup-install.sh:2, :7, :47; docs/reference/tmp-cleanup-convention.md:13-14; scripts/canary-verify.sh:156-180 | `producers`: add the mark (part3 edit 0); README: part 3's passage | none | none |
| K16 | A99 (TSV :98) | part 3 D2 and D3, low; part 3 E.2 | After round 15 the row gives no basis for "several producers": each file has one writer, and the label holds only because the watcher's log lines also land in logs/fswatch-<repo>.log when start-fswatch-all.sh starts it. Its producers carry `{s}` though a code read confirmed them. | hooks/git-fswatch.sh:27, :42-48, :91, :113, :180, :544; hooks/start-fswatch-all.sh:62-63, :71; hooks/fswatch-manager.sh:81 | `violations`: state that basis (part3 edit 1); `producers`: `{s}` -> `{c}` (edit 2); README: part 3's passage | none | P1b.md:770 (row 15, Deleted): D3, R1, recommended ("planning evidence for the fswatch state's writers is static only, A99" is false against the map) |
| K17 | A103 (TSV :102) | part 3 D4, low | `producers` says "no command, hook or script runs it" beside the script that runs scripts/session-resources.py on a fixture, scripts/laneb-integration-gate.py, which only a test runs. | scripts/laneb-integration-gate.py:1667, :1802; hooks/tests/test_laneb_integration_gate.py:27, :639-640 | `producers`: "no command, hook or live script", its one runner run only by a test (part3 edit 3); `deciding_consumers`: "live script" (edit 4); README:363's alignment optional, not proposed | none | none |
| K18 | A108 (TSV :107); README :502 | part 3 D1, low | The prompt-time hook removes INDEX.md where its file list, which leaves out INDEX.md, README.md, __init__.py and .DS_Store, is empty; the row says "left with no other file" and README:502 "left empty". | hooks/userprompt-doc-sync-check.py:39, :164-176 | `producers`: the list rule (part3 edit 5); README :502: "whose file list is left empty" (part3 README 10) | none | none (P1b.md:772, row 17, already says "whose list is left empty"); supersedes the P1b lane's optional A108 wording |
| K19 | A109 (TSV :108), optional | part 2 F.2; part 3 E.1, handled as P2-F.2 | Only if K14 lands: the SessionEnd sweep removes the dedupe state with the session directory, whatever it holds and without reading it, a removal by another component under README:467-469; the row says "none in D24 terms". | hooks/sessionend-scratch-sweep.sh:52, :75-92, :94 | `producers`: add the sweep (part3 O0); `readers`: drop the sweep's `{t}` entry (O1); `violations`: several producers (O2); README: part 3's passage opener "six rows" and one sentence | only with O0-O2: several producers +1; no violation found -1 | none |
| K20 | A119 (TSV :117) | part 3 D5, low, holds with correction | Round 15 added agents/spec.md's view consumer set to `producers` only; `paths`, `deciding_consumers` (`{c}` only) and `check_elsewhere` describe only code lists and registry loops, though the spec subagent decides on that prose set inside its own work. | agents/spec.md:48-63 (set :52-57); commands/dev.md:202-208; commands/dev-command.md:146-151 | `paths`: add the set (part3 edit 7); `deciding_consumers` (whole cell): keep the code lists and prose loops, add the spec subagent `{p}` (edit 8); `check_elsewhere` (whole cell): except agents/spec.md (edit 9); README: part 3's passage | none | none |
| K21 | no row (proposed A126, G17); A117 (TSV :115) `resolution`; README :162-167 | part 3 D6, medium | doc-sync creates `<proj>/CLAUDE.md`, prepends a header to one that lacks it and rewrites the AUTO sections of the project CLAUDE.md; its prompt-time re-run does the same under `<root>/.claude` for each root, the home directory among them; BA, QA and the PM decide on the file. No row covers it, and README:163-164 says the harness does not write `<proj>/.claude/CLAUDE.md`. | settings.json:691, :699, :351; hooks/doc_sync/main.py:49-57, :169, :183; hooks/doc_sync/claude.py:18-30; hooks/doc_sync/patch.py:135, :137-162; hooks/userprompt-doc-sync-check.py:46-63, :186; agents/ba.md:627-644; agents/qa.md:642-654; agents/pm.md:232-236, :290-292 | add row A126 after A125 (part3 ADD_ROWS: G17, outside the ledger; producers the user and both doc-sync runs `{c}`; readers the CLI, BA, QA, the PM, the specialists, session-info.sh:26 and doc-sync's own tests; deciders BA, QA and the PM `{p}`; four check cells none; violations several producers and several deciding consumers; evidence code); A117 `resolution`: point to A126 (part3 edit 6); README :162-167 rewritten, and the counts, :37, :40, :48, :138 and the `build_map.py` list updated (part3 README 1-10) | rows +1; outside the ledger +1; several producers +1; several deciding consumers +1; code-only rows +1; G17 +1; ids to A126 | P1b.md:772 (row 17): R2-R4, required; P1b.md:743 "33" -> "34": R5, required; P1b.md:773 (row 18): R6, optional; P1c none (P1c.md:738-739 stays true) |
| K22 | README "Excluded (not artifacts)", after :125 | part 2 D5, low, holds with correction | The operator's /tmp sweep is named nowhere, though it removes nine rows' hook-state files by age and README:467-469's removal reading would reach it; the operator-deployed tmpfiles.d rules are of the same kind. No harness entry point deploys or runs any of them. | scripts/install/tmp-cleanup-install.sh:2, :7, :93, :104, :155-166; docs/reference/tmp-cleanup-convention.md:13-14; scripts/canary-verify.sh:156-186; scripts/install/tmpfiles-claude-scratch.conf:50; scripts/install/tmpfiles-tmp-override.conf:19 | README: one bullet before "- Dropped rows:" that names the script and the tmpfiles rules, the rows they reach (A51, A52, A53, A63, A73, A78, A79, A90, A101; A109, A111, A112) and that none of them counts as a producer or decider (part2 README 3) | none | none (P1b.md:969-970, acceptance 9, already classes the installer's cleanup rules as not hook state) |

### Refuted

- **INV16-3 (part 1, low; A28).** The verifier filed hooks/posttool-subagent-track.py as a reader, decider and check
  elsewhere of A28's cycle copy, the file of the contract's Step 11g entry (commands/dev-overnight.md:840), at the
  graphify Agent call. The patch notes held it with a correction (part1 edits 7-10). The adjudication ruled that it
  does not hold: the hook's contract path never runs (trace T), so the hook is neither reader nor decider of A28.
  Dropped with it: part1 edits 7-10, the README passage's A28 clause and "A28" in its opener, part 1's optional P1b
  record for row 13 (P1b.md:768), and part 1's Observation 1, which is moot because Path B marks Step 11g.
- **D7 (part 2, low; A80), with part 1's cross-range note under INV16-2.** The verifier filed the same hook's test of
  the files of the contract's PM PLAN, TRIAGE and RETRO entries (commands/dev-overnight.md:846). The patch notes judged
  that it does not hold, on trace T, and the adjudication confirmed it. Withdrawn: the verifier's edits G.13-G.16, the
  A80 clause of its README insert and its P1b record R4.

### Other items in the round-16 reports (no map error)

- Part 2's record R2 (optional): P1b.md:766 (row 11, One producer kept) does not name A65's one producer,
  hooks/userprompt-bulk-commit-capability.py through scripts/write-bulk-commit-sentinel.py:97. The map names it; this is
  a P1b record only. It was not applied.
- Left by their authors with reasons, no edit: part 2's F.3-F.5 (A76's launch rollback, A76's G3 practice, A60's human
  producer) and part 3's E.3-E.6 and E.8-E.10.
