# D20-D25 batch residuals and P1b plan sync: record

Status 2026-10-27, branch `claude/vibrant-hopper-bazrn8` at d347b2f. The standing batch residuals were applied in commit
86b7cbc. The P1b plan-sync list was applied in the commit after it (the sync commit, c728380). Ten verification rounds
followed: rounds 1-9 fixed what their independent verifiers found (fa5659d, f65290d, f732f26, 9380922, b335a0e, 7beb706,
e428c5b, bb56fe5, 32fe0e0); round 10, the final confirmation round, fixed its findings in 5a4e0a3, and a further check
of those edits found one more, fixed in d347b2f; merges of the P1b/P1c session's commits came in between. e712310 merges
that session's commits up to facc385 onto round 9's fixes, and prompts/P1b.md, prompts/P1c.md and inventory/ are
unchanged since, so every status this record takes on them at e712310 holds at d347b2f. This record changes no other
file; its draft was committed in 32a6967. Parts 1 and 2 record what 86b7cbc and the sync commit applied, with the
decisions and counts those commits made; the later fixes belong to "Verification rounds". Residual items R1-R91
(reviews/D20-D25-batch-residuals.md, 91 items): 66 stand and were applied, 5 stand with no text change (R3, R39, R43,
R44, R83), 9 are covered by another item (R2, R6, R11, R18, R38, R45, R65, R71, R81) and 11 are refuted (R1, R9, R12,
R13, R25, R26, R28, R29, R31, R66, R72); 66 + 5 + 9 + 11 = 91. Sync edits V-1 ... P11-3 (reviews/P1b-plan-sync.md, 101
edits): 57 applied as written, 44 adapted, 0 not applied; 57 + 44 = 101. D-1 counts as adapted: only its heading fix
landed (Part 2).

Some of what Parts 1 and 2 applied was later rewritten on purpose, keeping each item's point. At d347b2f, as at e712310,
30 of the 132 residual replacements (manifest entries, numbered from 0) no longer stand verbatim: R4 #0, R15 #16-#17,
R21 #26, R24 #29, R30 #33, #35, #38 and #40, R32 #41, R37 #49, R46 #56, R51 #61, R52 #63-#67, R56 #74 and #77, R58 #80,
R61 #90, R62 #91, R68 #96-#98, R69 #99, R76 #106, R82 #111 and R89 #122. The sync itself changed four of them (#106,
#111 and #122 as "Residual text the sync later changed" says, #77 by V-9), round 9 changed #99, and rounds 1-8 the rest;
round 9's res-a and res-b verifiers re-read the other 29, round 10's res verifier all 30, and each still makes its
item's point. Of the 101 sync edits, later rounds rewrote 24 the same way, and the sync verifiers trace each to the
round entries that replaced it: V-1, V-11, V-13, V-15, V-17, V-29, V-31, D-1, H-10, K-1, K-4, K-6, K-8, K-12, P2-4,
P3-5, P4-4, P4-5, P5-4, P6-4, P9-6, P9-7, P9-10 and P10-4.

Line numbers: in Part 1 the item locations are the residual file's own numbers (the refuters found many of them 1 to 23
lines off); in Part 2 they are at 86b7cbc unless a line says otherwise; in "Conflicts and choices" the bullets added for
the verification rounds are at e712310 (the earlier bullets keep the numbers of the part they belong to); in
"Verification rounds" a line number is at that round's baseline; in "For the P1b/P1c session" the sync evaluators' items
first give the sync commit's numbers, the version of prompts/P1b.md and prompts/P1c.md the evaluators read (neither
86b7cbc nor the sync commit touched those files or inventory/), and end with where the point stands at e712310, and the
items the rounds sent are at e712310; in "Left for the reviewer" they are at e712310. 5a4e0a3 and d347b2f kept every
line count, so all of these numbers also hold at d347b2f; where those two commits changed a cited line, the record says
so.

## Method

- Two independent refuters (A and B) per R item, each trying to show the item wrong. They read the plan at be06811
  (the batch with the planning merge) and the code on origin/master (d625284, P1 merged), origin/repair/P8 and
  origin/claude/eager-allen-gf06hy (P7b), and in the merged expected tree (master with P8 and P7b). Each wrote a
  VERDICT (REFUTED, STANDS or STANDS-CORRECTED), REASON, FIX, OPTION CHOSEN and TOUCHES: 182 results.
- The rule applied: an item stands if at least one of its two refuters could not refute it. A refuter's corrected fix
  is used when it gives one. Where items conflict, the owner's rulings decide and the choice is recorded under
  "Conflicts and choices". The decision per item names the refuter whose fix was used (A, B, a stated modification of
  one, or a mix) and why.
- The residual fixes were applied as 132 exact replacements in 66 items; each OLD text was checked to occur exactly once
  in its file before it was replaced (commit 86b7cbc).
- One evaluator per sync edit (101) checked its anchor and its meaning against the plan at 86b7cbc and wrote a VERDICT
  (APPLY, ADAPT or NOT-APPLIED), the exact operations, the new anchor, the decision ids, the acceptance number and the
  notes for P1b/P1c. The orchestrator changed one result (D-1, recorded below). The 114 operations were applied in the
  sync list's order, each on an anchor that occurred exactly once; none failed (the sync commit).
- Verification, rounds 1-9: seven independent verifiers per round, none of whom had made an edit, each with a fixed
  scope: res-a (R1-R45) and res-b (R46-R91, with the items they cover); sync-V (PLAN-v2.md), sync-dhk (DECISIONS.md,
  HANDOVER.md, COVERAGE.md, COVERAGE-P9-P11.md) and sync-p (prompts P2-P6 and P9-P11), each with the sync edits and
  every earlier round's fixes in its files; quotes (every line this work added or changed: rejected ideas, owner words
  and owner credit, personal data and model names); structure (first lines and _common.md tails, untouched files,
  decision ids, acceptance numbering, cross-references). Each wrote one result file: DEFECTS, each with file:line, the
  problem and an exact fix (an OLD unique in its file, and the NEW). Round 10, the final confirmation round, ran four
  verifiers (res, plan, prompts, quotes-structure) over the same ground, and one more verifier checked the edits that
  fixed its findings.
- One fixed baseline per round, named in its addendum to the verifier brief (round 1: the sync commit's head): every
  reference this work makes into prompts/P1b.md, prompts/P1c.md and inventory/ had to hold there. The P1b/P1c session
  kept committing; a commit of theirs newer than the baseline was reported under "AFTER <baseline>" and either recorded
  for that session or, when it broke a reference of this work, fixed in the next round.
- Counting rule (from round 3): a DEFECT is text this work added or changed that is wrong, or a reference this work made
  that is broken at the baseline; older text this work did not add and does not contradict is NOT COUNTED, one line each
  (those still open are under "Left for the reviewer"). From round 5 on, the reviewer session's findings
  (reviews/D20-D25-reviewer-findings-on-A.md) were checked as claims. During the rounds the owner asked this work to
  focus on the big picture (a request, not a ruling in DECISIONS.md), so round 10 raised the bar: a DEFECT only where
  the text would make a phase executor do the wrong thing, fail or not find what it needs; anything less is MINOR. From
  round 10 on, minor items are recorded for the reviewer, not fixed.
- Applying: the same defect reported by several verifiers was merged into one fix, and each round's fixes went in as a
  manifest of exact replacements (each OLD occurring once in its file) in one fix commit. From round 5 on, one
  integration step did the merging and kept each NEW to its OLD's number of line breaks, so no file changed its line
  count and P1b's and P1c's line citations into this work's files kept holding (checked before and after).
- Refuters: a fix that reversed an earlier choice or changed a design went first to one independent refuter, whose
  corrected fix replaced the verifier's when the defect held: round 5's two reversals (r5x-sidecar, r5x-arming) and
  round 8's launcher change (r8x-launcher). All three held.
- Agents interrupted by a usage limit were resumed on the same agent id with a message (Lesson 16): some sync
  evaluators, round-1 verifiers, the first record drafter, round-4 verifiers, the round-6 integration agent and the
  round-9 PLAN-v2 verifier. Where an interrupted dispatch had no agent id to resume, it was dispatched again.

## Part 1: residual items R1-R91

- **R1** DECISIONS.md:23-25 (D20 tag). A REFUTED, B REFUTED. **Refuted.** Both found that P2's acceptance 14 as
  committed already runs two stand-in genuine decisions and one stand-in user gate, lists the gate first and expects 0
  AskUserQuestion records, and that TC-15 already points at that replay; "extended to" would claim work still owed.
  Edit: none.
- **R2** DECISIONS.md:139-140 (D1 wording). A STANDS-CORRECTED, B STANDS-CORRECTED. **Covered by R86.** Both keep D1's
  new "with D16's single confirmation at that time": it is the minimum edit consistent with D16 and D18's single
  confirmation, and a revert would reopen a second ask. Record note the item asks for: D1's wording is an R1
  consistency edit beyond the correction rows. Edit: no DECISIONS.md change; the P11.md D1-bullet alignment is word for
  word R86's edit and was applied once there.
- **R3** DECISIONS.md:166, :196, :208-209, :108. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, no text change.**
  Every text the item names is correct; the item's lines are 23 off and it misdescribes two of the four changes.
  Record note, as both refuters corrected it: three cross-reference anchors replace row line numbers (row 1.1's D21
  pointer to the P9/P10 bullets, row 1.8's "quoted in prompts/P11.md, the D16 and D1 bullets", row 1.11's "PLAN-v2.md,
  'Decision 7 (producer waiver)'"), and two tag wordings that no row supplies were written under R2 (the D18 tag's
  "; no experiment decides it"; the D8 tag's "prove by", since replaced by R4).
- **R4** DECISIONS.md:108 (D8 tag). A STANDS, B STANDS-CORRECTED. **Stands, applied.** The D8 tag pointed only at
  D21's generic sandbox replay and named no deciding experiment (R2). Edit: DECISIONS.md D8 tag names P3's acceptance 8
  replay (the declaring-dispatch reader) and, for the deny, the P5-a arm-* sandbox replay (TC-20 revised: 0 compliant
  writes denied, 0 V7a writes allowed). B's corrected fix: no "D21's replay" label (acceptance 8 covers declared
  artifacts only) and "TC-20 revised". Both left out the optional :39 edit (D21's tag is row 1.1 verbatim).
- **R5** DECISIONS.md:172-173 (D16 tag). A STANDS-CORRECTED, B REFUTED. **Stands, applied.** A could not refute it:
  "extended to" reads as pending work although P11's acceptance 14 already holds both cases (the words came from rows
  written against the old acceptance 14). B held the wording accurate and wanted parity with PLAN-v2 and P11.md. Edit: the
  D16 tag now names "P11's acceptance 14 (a /push of a new branch and a plain git push, each on a pulled and an
  unpulled home)", A's form (the item's OLD matched 0 times because of a line break).
- **R6** PLAN-v2.md:850-851. A STANDS-CORRECTED, B STANDS-CORRECTED. **Covered by R50.** The P11 intro cited the
  go-ahead quotes as "prompts/P11.md:76-80", now a heading; applied once in R50's form, which keeps the line break.
- **R7** PLAN-v2.md:946 (U-E1a). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** U-E1a still made P10's
  deletion of unregistered hook files wait for "TC-37's per-home doctor check", which TC-37 no longer has (the stubs stay
  tracked, D19). Edit: PLAN-v2 U-E1a row as the item wrote it, plus the same broken reference in the P8 D17 row, which
  both refuters found; that row now goes with P10's migration fix and overlay repair (P10 prompt R-e), the stubs staying
  tracked (TC-37, D19). A's wording, which keeps the TC-37 mention parallel to U-E1a.
- **R8** PLAN-v2.md:74, :682. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** Only the stub half held:
  the list still said P10 deletes stubs. The "doctor check" half was false (P10 still calls it that; doctor runs
  render-settings check). Edit: PLAN-v2 "Deleting hooks or dead installers (P10; the stubs stay tracked, TC-37, D19)";
  no rename and no :74 note (both refuters). B's form, closer to the original punctuation.
- **R9** PLAN-v2.md:550 (also :567, :585, :604). A REFUTED, B REFUTED. **Refuted.** The batch had already made all
  four P5-section places conditional on TC-18; the item's anchor and lines are pre-batch (0 matches). Edit: none (the
  optional section-13 edit both refuters noted is under "Left for the reviewer").
- **R10** PLAN-v2.md:543, :1222 against P5.md:305, :514. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.**
  The reader half was already fixed by the batch (P5 row 11 keeps P3's reader; the PLAN-v2 citation is right). What
  stood: P5 still said the stubs were "kept until P10" and deleted by P10, against TC-37/D19. Edit: seven replacements
  in prompts/P5.md saying the stubs stay tracked (TC-37, D19). B's fix, which covers all seven sites (A's four).
- **R11** PLAN-v2.md:66. A STANDS-CORRECTED, B STANDS-CORRECTED. **Covered by R54.** The section-1 line stated the
  pre-push guard as fact under D19 with no [INFERRED] tag; the same :66 text was edited once in R54-B's form.
- **R12** PLAN-v2.md:488. A REFUTED, B REFUTED. **Refuted.** The clause "a /redev prompt is minted exactly like /dev"
  is corrections 3.3 row ":519" (P4's acceptance 2), P4's only D22 check, and a regression check after P4 edits the
  shared mint path. Optional record note from both: the PLAN-v2 bullet mirrors 3.3 ":519", a sync no section-2 row
  covered. Edit: none.
- **R13** PLAN-v2.md:504. A REFUTED, B REFUTED. **Refuted.** The batch had already replaced "a continuation dispatch"
  with the re-dispatch of the gap's declaring dispatch (D21) or an in-turn AskUserQuestion (D23); the OLD text has 0
  matches. Edit: none.
- **R14** P2.md:289 (row 15), :777 (acceptance 12). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.**
  Row 15's new Hard Rule 5 ended "nothing parks", which acceptance 12's `grep -ni park` hits. Edit: P2.md row 15 and
  its PLAN-v2 copy end "nothing waits for the owner" (D20's planner wording, not an owner quote). A's fix (the same in
  both). Loosening acceptance 12 instead was rejected: P9's acceptance 10 would fail.
- **R15** P2.md:706-713 (acceptance 2), :460-463. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.**
  Acceptance 2 still ran close.md Step 0, its QA-arming block and commit.md Step 5 in the scratch product repo, where
  Step 5's until-loop calls an undefined `route_finding` and can loop until the timeout; the substitution paragraph did
  not name the QA-arming block P4 row 2 deletes. Edit: prompts/P2.md acceptance 2 drops the three blocks and says the
  lines left for P4 are not run; its B1 "Before" rows narrow to P5 and P6 (rows P1, P2 and P4 are the blocks no longer
  run); the substitution paragraph names the QA-arming block. B's form (keeps the line width, names Step 0's
  re-validation as the substitution paragraph does).
- **R16** P2.md:289 (row 15). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** The row's list of parking
  clauses left out dev-overnight.md:887 ("apart from parked pipelines"), so acceptance 12's grep would still hit.
  Edit: :887 added to the list in P2.md row 15 and in its PLAN-v2 copy. A's fix (the same in both).
- **R17** P3.md:263 (row 7), :686, :335. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** P3's Retired
  list and test dispositions retire G2's escalation stores, but rows 6 and 7 left `_write_side_records`' writes of
  `upstream_defect_notice` records into escalations/. Edit: P3.md row 7 also deletes that write (the duplicate scan and
  `_mint_record` call; the advisory stays, P4's) and says nothing reads the three writes except the notice write's own
  duplicate scan, which goes with it (L25, L26). Deleting, not narrowing the claims (D24, PLAN-v2's P3 rows); A's
  wording.
- **R18** P3.md:654-658 (acceptance 18). A STANDS-CORRECTED, B STANDS-CORRECTED. **Covered by R59.** Acceptance 18
  told P3 to edit policies/tool-policy.v1.json, which no P3 scope row names. Both rejected the item's new scope row,
  because D24 and P1b row 4 own that deletion; the clause was edited once in R59-A's form.
- **R19** P3.md:657-658 (L21 clause). A STANDS-CORRECTED, B REFUTED. **Stands, applied.** A could not refute it: "remaining
  consumers import obligation.TERMINAL_VOCABULARY" cannot hold while hooks/posttool-overnight-loop.py:32, a file P3 may
  not edit, re-declares the set. B argued P1b row 6 removes it before P3 and gave a fallback. Edit: the clause adds "a
  private set left in a file this phase may not edit is listed with the phase that deletes it" (B's neutral fallback;
  see "Conflicts and choices").
- **R20** P3.md:271 (row 16). A STANDS, B STANDS. **Stands, applied.** Row 17's new blocking G1 check had no named
  committed test. Edit: row 16 names hooks/tests/test_obligation_gate.py (P1; the G1 staleness preconditions, row 17)
  and adds the G1 staleness preconditions to its new-tests list. A's fix (same effect as B's, longer OLD).
- **R21** P3.md:566, :569-570 (acceptance 4). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** Two
  bullets assumed hooks/lib/progress_measure.py survives and that a reader of the old phases is left; row 6's D17 clause
  can delete both. Edit: the `grep -c arbitration hooks/lib/progress_measure.py` clause is deleted (the remaining greps
  cover it) and the old-state case now expects the dev's failing stop to exit 2 as it does without the file. B's fix:
  A's conditional grep would hit out-of-scope INDEX and README files.
- **R22** P3.md:551-552. A STANDS, B REFUTED. **Stands, applied.** A could not refute it: the batch rewrote the
  bullet's second clause, which no row asked for, into "after the re-dispatched BA writes ...", which does not fit a
  fixture test with no dispatch. B argued the new words are PLAN-v2's own acceptance text. Edit: P3.md back to "after a
  newer ticket and context -> the question gap is gone" (A).
- **R23** P4.md:250 (row 5). A STANDS-CORRECTED, B STANDS. **Stands, applied.** "Keep Step 6's REJECT and its rule
  that a code or doc file it names goes to dev" keeps a file-kind-to-role rule (D21). Edit: "Keep Step 6's REJECT.",
  the row's exact text (the item's minimal alternative); the item's main replacement adds a routing rule no row asks
  for. A's fix (the same in both).
- **R24** P4.md:279-280. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** The close-QA fallback brought
  back "a code or doc file goes to dev" (D21) and gave no route for other files. Edit: the fallback dispatches again
  the declaring dispatch of each file a close-QA finding names (the declaring-dispatch reader, as in Step 0), dev when
  none, and records the miss. B's form (same meaning as A's, shorter); the item's "every finding to dev" not taken.
- **R25** P4.md:54-56. A REFUTED, B REFUTED. **Refuted.** The canonical-todo-step half of P3 row 1 is already in the
  same bullet (P4.md:56-57); inserting it would duplicate it. Edit: none.
- **R26** P4.md:99-100 (Goal 8). A REFUTED, B REFUTED. **Refuted.** The ledger is reachable: the merge be06811 added
  audit/2026-10-23/ledger.md and P4 extracts the whole plan directory. Edit: none.
- **R27** P4.md:429-430. A STANDS, B STANDS. **Stands, applied.** The P1 carry-over still listed "TC-13's
  `session_families()`" unconditionally, while the loop's print, its only consumer, became conditional. Edit: ", if
  the loop's print stays" added. A's fix (same meaning as B's).
- **R28** P4.md:417, :420. A REFUTED, B REFUTED. **Refuted.** The S2 and TC-34 rows the Background points at state
  SUPERSEDED/WITHDRAWN in their first words and carry the rules P4 implements; P4 repeats both statuses. Edit: none.
- **R29** P5.md:294 (row 1). A REFUTED, B REFUTED. **Refuted.** Dropping row 3.4's comparison "against the table
  variant" and its "less code" tie-break follows D8 ("never from a table (D21)"): at 0/0 the tie-break would let the
  existing per-role prefix rows, a filename-to-role table, win. Record note: P5 row 1 keeps corrections 2.82's fallback
  rule and leaves row 3.4's tie-break out on purpose (D8, D21). Edit: none.
- **R30** P5.md:372-374, :382-383, :645-652 (merge and push predicates, acceptance 6). A STANDS-CORRECTED, B
  STANDS-CORRECTED. **Stands, applied.** For a bare /merge the any-entry rule made any merge release the span, and for a
  typed /push "HEAD equals the upstream tip" released a push to the wrong remote, so acceptance 6 could not decide
  either case. Edit: five replacements in P5.md and five in PLAN-v2.md (gate row, TC-25), B's fix with one part of A's
  (see "Conflicts and choices").
- **R31** P5.md:361. A REFUTED, B REFUTED. **Refuted.** The committed tag already names its deciding experiment (P2's
  acceptance 14 replay, re-checked by P5 acceptances 12 and 20); the OLD text has 0 matches. Edit: none.
- **R32** P5.md:393. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** The tag on the canonical-todo-step
  fallback named only P3 acceptance 8, which covers declared artifacts. Edit: the tag adds "plus acceptance 2 here (QA
  never dispatched: the block lists the missing dispatch)". B's "plus" form, as P4 uses it (R61, R62).
- **R33** P5.md:458-460. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** The push bullet under
  "Corrections to PLAN-v2" quoted PLAN-v2 text that the batch had already replaced, so it named a correction PLAN-v2 no
  longer needs. Edit: the bullet is deleted (both refuters' corrected fix, the same as R65's); applied once here.
- **R34** P6.md:496-501. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** P6 kept the changelog-analyst's
  adoption carve-out, part of the git provenance filter that row 3.5 deletes, and left it running with no baseline
  guard. Edit: three replacements in P6.md applying row 3.5 as written (option (a)), B's form; see "Conflicts and
  choices".
- **R35** P6.md:381-383. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** P6 called the dev-registry FIRST
  ACTION lines inert without the condition option one sets (`agent_type` in the payload). Edit: P6.md adds that the
  lines are inert whenever the payload carries `agent_type`, and what a CLI without it and without a meta file gets.
  B's form (same meaning; A's "resolves to no role" was too strong).
- **R36** P9.md:444 (row 16). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** Hook Discipline #1/#3 and
  the :108 rule were scoped to gated commands other than /dev-overnight, with nothing said for /dev-overnight (D20).
  Edit: row 16 adds that inside /dev-overnight nobody is asked, the rejected operation is neither retried nor
  circumvented (#2, #4), the session decides without the owner how to proceed and records it; :108 takes option (1)
  or (2) and records which. A's form: no new [INFERRED] tag (B's names an acceptance not checked).
- **R37** P9.md:390-391 (Correction 8). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** Correction 8 still
  said acceptance 10 expects 0 in commands/ and agents/. Edit: "apart from `blocked` hits that are not a cycle
  terminal, each listed with its reader". B's wording with the bare word, to match R75.
- **R38** P9.md:545-551 (acceptance 10). A STANDS-CORRECTED, B STANDS-CORRECTED. **Covered by R75.** The quoted
  `"blocked"` form misses unquoted and backticked terminal prose; R75's edit fixes the same text once.
- **R39** P9.md:440 (row 12). A STANDS, B STANDS. **Stands, no text change.** Row 12 quotes P2's deny message, not row
  3.6's shorthand. Record note: a deliberate deviation from row 3.6 :404's literal message, because P9 uses P2's message
  as merged (P9's "Interfaces you consume") and that message is the one the plan defines (P2.md, corrections 3.1).
- **R40** P9.md:436 (row 8). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** commands/redev.md:12-13
  still allow a /redev continuation target (D22), and nothing in P9 removed them. Edit: row 8 states /redev = /dev
  with a fresh task id and drops the continuation-target clauses (D22); the quoted anchors go in the Locations column;
  the D22 bullet points at rows 8 and 14. B's form (quotes in Locations only).
- **R41** P10.md:205-206 (experiment 6). A STANDS, B STANDS. **Stands, applied.** "deleted with R-a..R-i" included R-e,
  which P10 keeps. Edit: "R-a..R-d and R-f..R-i". A's fix (the same in both; also R81's).
- **R42** P10.md:254-256 (TC-56, TC-57). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** Both lines
  assumed the size budget that experiment 12 may drop. Edit: TC-56: the size ratchet measures it (`docs_reference_bytes`)
  and the budget counts it if experiment 12 keeps the budget; TC-57: capped by the docs budget if experiment 12 keeps
  it. A's form (the item's words, rewrapped).
- **R43** P10.md:340 (row 4), :520-521, :601. A STANDS, B STANDS. **Stands, no text change.** Row 4's stub-or-residual
  rule is an editor addition beyond corrections 3.7; both refuters keep it (see "Conflicts and choices" for the record
  note).
- **R44** P10.md:262-263, :527, :662, :713, :736 (line width). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, no
  text change.** The overlong lines are real but cosmetic; the optional re-wrap was not applied (see "Conflicts and
  choices").
- **R45** P11.md:648-649 (acceptance 17). A STANDS-CORRECTED, B STANDS-CORRECTED. **Covered by R84.** The sentence had
  no verb; R84-B's merged text carries R45's verb and target.
- **R46** P11.md:587-593. A STANDS, B STANDS-CORRECTED. **Stands, applied.** The intro reduced scenarios 3-6 to one
  expectation while scenarios 3 and 4 still listed old pull results. Edit: the intro adds that the pull results named
  in 3 and 4 are fact 4's and describe the steps, that scenario 3's /pull completing is acceptance 14's precondition,
  and that 5b also carries B2's experiment. B's form: A's "not checked" would stop checking scenario 3's /pull.
- **R47** P11.md:525. A REFUTED, B STANDS. **Stands, applied.** B could not refute it: the "never aborts, continues or
  resets a rebase or merge" rule now lives only in B2. A held B3/B6/B7 right for the other four clauses. Edit: "(B2,
  B3, B6, B7)" (both fixes identical).
- **R48** P11.md:587-589 (test (iii)). A STANDS-CORRECTED, B REFUTED. **Stands, applied.** A could not refute it: (iii)
  counts only stand-in literals, so a push that carries real pre-rewrite literals passes. B held that the item's own
  example cannot happen. Edit: (iii) adds a scan with the derived list (copied into the sandbox, mode 0600, never
  printed) of the objects reachable from the sandbox origin's refs other than refs/pull/*. A's corrected form.
- **R49** PLAN-v2.md:879. A STANDS, B STANDS-CORRECTED. **Stands, applied.** The P11 acceptance bullet credited
  doctor --strict and the machine-form check to acceptances that do not run them. Edit: the bullet now states the
  stand-in count of (iii) and the refusal of a push carrying a listed literal (a /push of a new branch, a plain
  `git push`, the opt-in checkpoint push). B's form: keeps the checkpoint push and the existing citation.
- **R50** PLAN-v2.md:848-849. A STANDS, B STANDS. **Stands, applied.** Same stale "prompts/P11.md:76-80" as R6. Edit:
  "(quoted in prompts/P11.md, the D16 and D1 bullets)", keeping the line break; covers R6.
- **R51** PLAN-v2.md:534, :1051. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** Row 2.45 asked to mark
  the escalation-record deny as temporary; PLAN-v2 only made it conditional. Edit: the D8 row and TC-20 add
  "temporary, retired with the stores". B's form (minimal).
- **R52** PLAN-v2.md:540, :1042 (TC-11). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** PLAN-v2 said
  the launcher keeps inline copies of the human-record and window rules checked against stop_contract, while P5 row 10
  imports lib/overnight.window_open by path unless a replay forces a copy. Edit: five replacements in PLAN-v2 (launcher
  row, TC-11, drift test, acceptance "The launcher's drift test (TC-11) passes."). A's form, which also fixes the
  acceptance line.
- **R53** PLAN-v2.md:781 (CLAUDE.md row). A STANDS, B STANDS. **Stands, applied.** The cell opened "A proposed diff
  attached to the PR" but ended "P9 applies it in its PR (D19)". Edit: it opens "The edit, made in P9's PR (P9 row
  16):". A's fix (the same in both).
- **R54** PLAN-v2.md:66, :778, :1099. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** Three lines stated
  [INFERRED] mechanisms under owner ids without the tag. Edit: :66 in R54-B's form (D19: no owner machine step; the
  guard [INFERRED; prove with P11's acceptance 14 ...]); the TC-45 scope at :778, :1099 and a fourth site A found
  ("lifts the TC-45 deny (D20)") tagged "[INFERRED scope from D20; decided by the P2 TC-45 deny replay]" in R54-A's
  form. Covers R11.
- **R55** PLAN-v2.md:1108. A STANDS, B STANDS. **Stands, applied.** The new section-10 bullet rested D15's yielding on
  one owner quote where UD5 and P9's E2 rest it on two. Edit: the second quote (register CC7, verbatim) added. A's
  fix (the same in both).
- **R56** P2.md:52, :116, :118. A STANDS, B STANDS. **Stands, applied.** G2's failing-stop path and the ESCALATION_ACK
  admission were two lines off on the refreshed base. Edit: :747-830 and :793-804 in P2.md (three places), plus the
  same numbers in PLAN-v2's P2 goal and P3 row. A's fix, which adds the two PLAN-v2 syncs.
- **R57** P2.md:344-345. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** The coordinator paragraph still
  said "inside the window only /stop and off release", which the row had removed from the D4/S1 bullet. Edit: "(inside
  the window only /stop releases, D4; P2 relies on no other exit)". A's shorter form, with no new claim about off.
- **R58** P3.md:48-50. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** The "Files you share with P2"
  bullet called the G2 hook "not P2's" although P2 Goal 7 may take its failing-stop hunk. Edit: the bullet adds that
  exception (P2 may take the hunk as P3 wrote it before its arming commit; if P2 merged it first, build on it). B's
  form: the bullet only; row 6 unchanged.
- **R59** P3.md:274-275, acceptance 18. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** As R18. Edit:
  acceptance 18's L14 clause says BA's write permission at policies/tool-policy.v1.json:129 is P1b's to drop
  (prompts/P1b.md row 4), else P5-a's (prompts/P5.md row 1), and that P3 does not edit the policy file. A's form;
  covers R18. The item's scope-paragraph append and R18's scope row were not applied.
- **R60** P3.md:130-131. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** The D20-D24 bullet header said
  the quotes are "quoted in full" in DECISIONS.md, which elides with "…". Edit: "quoted in DECISIONS.md" in all eight
  prompt headers (P2-P6, P9-P11). A's form (keeps the line break).
- **R61** P4.md:81-87 (Goal 2). A STANDS, B STANDS. **Stands, applied.** The canonical-todo-step sentence followed the
  close-stage branch and named an experiment that never reaches it. Edit: the sentence moves into the dev-stage branch
  and names a sandbox /commit over a task whose lane QA was never dispatched. A's form (same text as B, shorter OLD).
- **R62** P4.md:576-594 (acceptance 4). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** No acceptance ran
  the never-dispatched case that decides the canonical-todo-step branch. Edit: acceptance 4 adds "a task whose lane QA
  was never dispatched, under /close and under /commit". B's form: names the lane-QA step of the task's own pipeline;
  the optional :54-55 pointer left out (it would clash with sync P3-5, which moves the reader's proof to P1b).
- **R63** P4.md:59-60. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** P2's step 2-4 derivation without a
  seed file was cited without its [INFERRED] tag. Edit: the tag added, naming P2's acceptance 11 replay. B's form
  (names the deciding experiment precisely).
- **R64** P5.md:181-182. A STANDS, B STANDS. **Stands, applied.** One pair of quote marks held both the plan line and
  the owner's reply (register QP2). Edit: "Answering the plan line ..., the owner wrote: ...", both strings verbatim
  from register.md. A's fix (the same in both).
- **R65** P5.md:463-465. A STANDS, B STANDS. **Covered by R33.** The same stale push bullet; deleted once under R33.
- **R66** P5.md:297 (row 1). A REFUTED, B REFUTED. **Refuted.** As R29: the dropped comparison and tie-break follow
  D8 and D21. Same record note as R29. Edit: none.
- **R67** P5.md:298, :775-776, :802-803. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** "Retired with the
  stores" named no retirer. Edit: row 2 and the scheduled-retirement bullet name P10 row 19 (L25); "(P3/P6)" not
  restored (P6 retires nothing). A's form (names only P10 row 19).
- **R68** P5.md:91, :307. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** Goal 1 and row 10's File column
  stated the window_open import unconditionally. Edit: "unless row 10's replay makes you copy the rule" / "unless the
  replay makes you copy it", plus the same condition at P5.md:62. A's fix (the same in both).
- **R69** P5.md:310 (row 13). A STANDS, B STANDS. **Stands, applied.** The deny's lift was restated under D20 without
  its [INFERRED] tag. Edit: "[INFERRED scope from D20; P2's acceptances 7 and 14 prove it]". A's fix (same text).
- **R70** P5.md:108-109 (Goal 5). A STANDS-CORRECTED, B STANDS. **Stands, applied.** "every caller other than the
  dispatch whose obligation declares" treats a dispatch as a caller. Edit: "the agent whose dispatch obligation
  declares". A's fix (same text).
- **R71** P6.md:496-501. A STANDS-CORRECTED, B STANDS-CORRECTED. **Covered by R34.** The problem stands; it is resolved
  by R34's option (a), not R71's option (b) (see "Conflicts and choices").
- **R72** P6.md:502-505. A REFUTED, B REFUTED. **Refuted.** The three passages are references to the deleted filter,
  which the row's "delete the filter" covers; deleting the sentence would leave stale instructions. Edit: none.
- **R73** P6.md:693-694 (acceptance 14). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** A `--stat` list
  cannot show which lines a deletion removes, and the in-line deletions in changelog-analyst.md make "(deletions only)"
  false for a compliant P6. Edit: acceptance 14 keeps the file list and adds that each hunk's `+` lines are its `-`
  lines with words deleted and none added. B's form, which holds under R34's chosen option.
- **R74** P9.md:149-150. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** The D20 sub-bullet's "parks
  nothing" would fail P9's acceptance 10 and P2's acceptance 12. Edit: "asks nobody and lets nothing wait for the owner".
  B's two-word change, keeping "the session" as subject.
- **R75** P9.md:545-551 (acceptance 10). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** As R38. Edit:
  the regex uses `\bblocked\b` (row 8's bare word); the exception keeps "not a cycle terminal" and names a hook's block
  or deny wording; the hooks/ pass keeps `"blocked"`. A's form; covers R38.
- **R76** P9.md:444 (row 16). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** Row 16 fixed the subagent
  path as "reports it ... and the orchestrator asks" although row 14 makes it depend on an experiment. Edit: "a subagent
  asks directly if P3's acceptance-19 experiment and P1's capability facts show it can, as in row 14; otherwise ..."
  and "#5 ... is asked or relayed in-turn as row 14 documents it". B's form (row 14's condition).
- **R77** P9.md:82. A STANDS, B STANDS. **Stands, applied.** A bare "(acceptance 19)" read as P9's own. Edit: "(P3's
  acceptance 19)". A's fix (the same in both).
- **R78** P9.md:137-138 (release note). A STANDS-CORRECTED, B REFUTED. **Stands, applied.** A could not refute it: the
  note credited CLAUDE.md with the human exits and left out the D23 pause line. B held the three-file note true as a
  whole. Edit: "the Stop gate's human exits (README, ARCHITECTURE), the gated commands' in-turn AskUserQuestion pause
  outside /dev-overnight (CLAUDE.md's added line)". A's form, with D20's scope.
- **R79** P10.md:294-297 (correction 3). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** Correction 3
  described PLAN-v2 text that the batch removed (the doctor runs), contradicting P10.md:25. Edit: correction 3 names
  TC-37 (section 9), the P10 rows "Commit 1, TC-37" and "Commit 2, TC-37" and section 4, and says PLAN-v2 now keeps
  the stubs and marks the doctor step withdrawn. A's form: rows and sections instead of line numbers the sync's inserts
  would move.
- **R80** P10.md:147-148 (D18/D19 bullet). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** The bullet
  still credited "doctor on each home" to TC-37. Edit: "the withdrawn "doctor on each home" step (PLAN-v2 section 14;
  correction 3)". A's fix (the same in both).
- **R81** P10.md:204-205. A STANDS-CORRECTED, B STANDS-CORRECTED. **Covered by R41.** The same range correction,
  applied once under R41.
- **R82** P10.md:354 (row 19). A STANDS, B STANDS. **Stands, applied.** Row 19's seed left out L48, the overnight
  continuation sentinel, which the ledger marks DEAD. Edit: L48 added to row 19 with its deleting phase. A's fix (the
  same in both). The sync's P10-4 later replaced row 19's phase attributions with P1b's and kept L48.
- **R83** P10.md:339, :519-520, :600. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, no text change.** The same
  finding as R43; B's "keep" taken over A's deletion of the conditional stub branch (see "Conflicts and choices").
- **R84** P11.md:647-649 (acceptance 17). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** The sentence had
  no verb and did not say how the guard's own tests are counted (the item's "numstat does not see test files" was
  false for hooks/tests). Edit: one merged acceptance-17 text: counted as "Net code cap" says (the pre-push guard's own
  tests in, wherever they sit; every other test out), its one total reported against its target (<= 0). B's form;
  covers R45.
- **R85** P11.md:317-318 (A6). A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** A6 described the
  pre-batch PLAN-v2 step 3. Edit: "PLAN-v2's goal and step 3 ("Count, do not print") count the secret-bearing keys ...
  without printing any value". A's form (keeps the line breaks).
- **R86** P11.md:106, :108, :114, :484. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.** The D16 and D1
  bullets kept the old "explicit go-ahead at execution time" model. Edit: four replacements: the go-ahead on record plus
  one AskUserQuestion confirmation, and D1 "with D16's single confirmation at that time". B's form (shorter second edit,
  corrected anchor); covers R2.
- **R87** HANDOVER.md:19, :20. A STANDS, B STANDS. **Stands, applied.** The owner-facing table still described parking,
  the after-window question, an owner per gap, a continuation include and the /redev binding, all withdrawn (D20-D22).
  Edit: both cells now state the D20 and D21/D22 designs. A's text with HANDOVER.md's own double-quote style.
- **R88** HANDOVER.md:70-72 (question 12). A STANDS, B STANDS-CORRECTED. **Stands, applied.** Question 12 still listed
  D4b's refinement and /redev's gating as open. Edit: a dated note on the same line (D20 withdrew parking and the
  morning question; /redev is /dev under the same gates, D22; the two extra exits are planner proposals). B's form: same
  line, so no HANDOVER line moved; double-quote style as R87.
- **R89** COVERAGE.md:27, :29, :34, :35, :61, :81, :164. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands,
  applied.** The coverage matrix still mapped decisions onto withdrawn mechanisms. Edit: a status prefix on line 3
  (the file yields to DECISIONS.md; the named rows name withdrawn designs) and "D4b overnight parking: SUPERSEDED by
  D20". B's in-place form (no line moves), with A's missing design (the question asked when a round changes nothing)
  added to the list.
- **R90** COVERAGE-P9-P11.md:35, :98, :174, :67, :170. A STANDS-CORRECTED, B STANDS-CORRECTED. **Stands, applied.**
  The file still listed the continue-cycle.md check, pointed loops at the include, filed D4b as "implemented as
  planned" and kept "R-a..R-i". Edit: seven replacements (check removed; one re-dispatch sentence, no include, D21;
  "superseded by D20"; P10 row 3 with option (a) and R-e; "R-e" in place of "R-a..R-i"; P11 B2 handles S4). B's form:
  :67 and :170 unchanged (they point at the live P10 section), R-e kept.
- **R91** PLAN-v1.md:313, :324 (D-A2-2). A REFUTED, B STANDS-CORRECTED. **Stands, applied.** B could not refute it:
  PLAN-v1 still prescribes the withdrawn /redev resume route and DECISIONS.md:5's override list did not name it. A held
  the frozen, lowest-precedence file already overridden. Edit: DECISIONS.md:5's list gains "/redev <task>"; PLAN-v1
  unchanged (frozen; its line citations hold). B's fix.

## Conflicts and choices

- **R34 and R71 (changelog-analyst carve-out).** Row 3.5 applied as written (R34's option (a), B's form). The ruling:
  DECISIONS.md "Architecture is producer-side", "Never add consumer-side checks: nothing new in /close, /commit or the
  changelog-analyst (no scan, no cleanup class, no filter)" (DECISIONS.md:92-95), and P6's own goal that QA and the
  changelog-analyst no longer re-check the lists against git (P6.md:106-107). R71's option (b) would keep a git re-check
  in the changelog-analyst and needs an amendment to the audit's corrections.md; it was not taken and no audit file was
  edited. The adoption outcome is kept: Phase 5's adoption branch stays but is never taken, and a pre-existing
  untracked path dev modified is staged whole-file by the attribution-and-staging decision, as when the adoption route
  fails today; P6 says so in its PR. Row 6's consumer list now names scripts/check-late-repair-provenance.py and
  scripts/stage-owned-hunks.py. R73's check was chosen to hold under this option; R72 stays refuted.
- **R30 (push and merge predicates).** Push: B's typed-remote-tip predicate, "HEAD equals the tip of
  `refs/remotes/<remote>/<BRANCH>` for the typed remote (with none typed, the upstream tip)". It never releases a /push
  whose typed remote lacks HEAD, as D4/TC-25 require for /merge ("a merge the command did not select must not release
  the span"); A's "no push updated the upstream after the opener" variant was not taken. Merge: B's text, "git- and
  hook-written facts only", with the bare-/merge source tip read from an existing git- or hook-written fact that names
  merge.md Step 0's pick and outlives merge.sh's cleanup, plus A's "an existing ... (no new state file)" so the
  predicate adds no state file. Acceptance 6 no longer carries fallbacks that release the span: a merge of another
  branch, and a --no-commit MERGE_HEAD from another branch, give rc 2; a typed remote that is the upstream and already
  has HEAD gives rc 0. PLAN-v2's P5 gate row and TC-25 carry the same predicates; the stale "Corrections to PLAN-v2"
  push bullet is deleted (R33/R65).
- **R37, R38 and R75 (the `blocked` grep).** Row 3.6 row 8 says acceptance 10's grep adds `blocked`; the batch had
  narrowed it to `"blocked"`, which misses unquoted honest-terminal prose (D2). R75-A's `\bblocked\b` was applied once
  and also fixes R38's text; R38's separate backtick or bare-word check was not taken (two checks for one row); the
  exception stays "not a cycle terminal" (R75-B's widening to "cycle, pipeline or lane terminal" not taken). R37's
  Correction 8 uses the bare `blocked` (B's wording modified) to match. The word-boundary form's known gap is under
  "Left for the reviewer".
- **Duplicates applied once.** R6/R50 (R50's form, keeps the line break); R11/R54 (R54-B's form at :66); R18/R59
  (R59-A's form: P1b row 4, else P5-a row 1; P3 does not edit the policy file); R33/R65 (the deletion, under R33); R41/R81
  (R41); R45/R84 (R84-B's merged text); R2/R86 (R86-B's :114 edit); R38/R75 (above).
- **R43 and R83 (P10 row 4's stub-or-residual rule).** Kept, no text change: both R43 refuters and R83-B keep it; R83-A's
  deletion of the conditional stub branch would drop the plan's only statement of the running-session hazard (D25(3),
  D15). The strict-minimum alternative was rejected for the same reason. Record note the items ask for: row 4's
  stub-or-residual rule, its release-note clause and acceptance 1's "plus any row 4 file experiment 1 made a stub" are
  an editor addition beyond corrections 3.7; they give a consequence to the personal-overlay registration hazard for
  running sessions that the removed stand-ins (R-c(i), R-f) covered; the stub branch cannot fire under experiment 1 as
  written (fe7700c8's tracked settings name none of row 4's files), so in practice the release-note residual is what
  happens.
- **R44 (P10 line width).** No re-wrap: no rule or check sets a width (R44-B), the minimum edit is none, and re-wrapping
  P10 lines would move text that the sync's anchors P10-1 to P10-6 match.
- **R19 (P3's L21 clause).** B's ownership-neutral fallback, not A's "listed as P4's": P1b row 6 deletes part of the
  private terminal sets before P3, so naming P4 could be wrong.
- **R29 and R66 (P5 row 1's tie-break).** Both refuted; the tie-break stays out on purpose under D8 ("never from a
  table") and D21. Record note in R29.
- **Other recorded choices.** R14: change row 15's wording, not acceptance 12 (P9's acceptance 10 would fail). R17:
  delete the notice write rather than narrow the Retired claims (D24, PLAN-v2's P3 rows). R59: correct acceptance 18
  rather than widen P3's scope (D24: P1b owns the requirement). R62: the optional P4.md:54-55 pointer left out
  because sync P3-5 moves the reader's proof to P1b. R79: anchors by name, not line numbers the sync would move. R88
  and R89: in-place edits so that no HANDOVER.md or COVERAGE.md line moved (DECISIONS.md and P1c.md cite their lines).
  R91: extend DECISIONS.md:5 rather than edit the frozen PLAN-v1.
- **Residual text the sync later changed.** P3-5 names R17's notice write as delivered by P1b row 3 and P1c row 7. K-4
  edits R89's status line (O17/O18 and "the OPERATION_STALLED question" leave its list). P9-8 replaces row 16's #5
  sentence and keeps R76's "asked or relayed in-turn as row 14 documents it". P10-4 replaces R82's "(P2 rows 4 and 9)"
  attribution with P1b's and keeps L48. The sync anchor of D-1 (DECISIONS.md:5) had been rewritten by R91.
- **D25's rank (round 1).** D25 and D20-D24 do not override one another (DECISIONS.md:7, :68, as the D-1 override set
  the headings): the eight prompt headers and PLAN-v2's precedence lines rank D25 with D20-D24, neither above nor below
  them.
- **Push predicate (round 4).** The /push predicate also holds when HEAD "is an ancestor of" the typed remote's tip
  (prompts/P5.md:433, PLAN-v2.md:563): that remote already has HEAD and push.sh pushes nothing, so a branch behind its
  remote is no dead end (D25 (3)). This settles R30-A's strictly-behind case; round 1 had already moved the typed-remote
  case to its producer (push.sh counts against the typed remote).
- **The P10 and P11 tail sentence (round 5).** Changed on purpose to "The owner's rulings of 2026-10-23 and 2026-10-24
  (DECISIONS.md D20-D25, which do not override one another) outrank every other decision and S#."
  (prompts/P10.md:819-820, prompts/P11.md:795-796): "D20-D24 outrank every other decision" contradicted DECISIONS.md:7
  and :68, and two verifiers found it independently. The sentence sits in P10's and P11's own tail variant, not in
  _common.md's shared tail (which ends at "before editing."); P2-P6 and P9 still end byte for byte with
  prompts/_common.md.
- **No class H for a lost /do sidecar (round 5; refuter r5x-sidecar).** This reverses round 3's r3-structure-1. P1c X6's
  class H is a closed list (P1c.md:360-363), and a lost sidecar is D25 (2)'s missing-artifact fault, so P5's do
  predicate reads the hook's `[/do] task-id minted: <id>` transcript record (prompts/P5.md:400-401; TC-26 as corrected),
  the sidecar stays only for the agent deny and TC-18, and a lost sidecar blocks nothing (P5.md:123-125). P5 still
  extends class H to its gate's and launcher's instrument-failure block (P5.md:119-122), as P1c's class H holds the
  time-lock's.
- **G1 and G3 reach running sessions (rounds 5-6; refuter r5x-arming).** Unless P2's Arming-timing probe shows a
  settings change reaching a running session, G1 and G3 take their switch at run time from the harness home's
  settings.json when their process env lacks the key, as P1b E4 has G2 do since eef8a5c: through P7b's function, not a
  second reader (prompts/P2.md:118). Round 6 placed that read: one hunk at each switch read (`_run_obligation_barrier`,
  `main`), in files P3 otherwise owns, in a commit before P2's arming commit (P2.md:52, P3.md:50, PLAN-v2.md:180).
- **No per-role prefix-row fallback (rounds 5-6).** A tool-policy allow prefix that names a file maps that file to a
  role (D21; P1b E3 and row 19 rule 7), so P5 row 1, P3, P6 and TC-20 offer no prefix-row fallback (prompts/P5.md:111,
  :341; PLAN-v2.md:1086).
- **The Stop launcher (rounds 8-9; refuter r8x-launcher).** P5's launcher loads P1b row 18's transcript reader, with the
  human-record rule, and lib/overnight.window_open by path, never a copy and with no drift test; P5 moves span_opener,
  the human-record rule and timelock_released into the reader's module. Stated loss: a broken module the launcher loads
  leaves the checks that need it not holding, as before P5-b (prompts/P5.md:351; PLAN-v2.md:44, :566, :1077; at :44 a
  carve-out from S1, since D24 outranks S1).
- **Verifier findings not applied.** Round 7: r7-sync-p-8 (P3.md:692's tool-policy ":129" to ":127"): :129 is right for
  P3's refreshed base, where P8's 352e28c moved the ba-qa-report prefix down from :127, the line P1b row 4, P5 and
  PLAN-v2 cite at d625284; r7-sync-V-7 ("(row 19 rule 7)" to E3): rule 7 also covers a tool-policy allow prefix that
  names a derived artifact's file, so the citation is right. Round 9: r9-sync-V-3 (the tracked GATED/CONTROL JSON's
  readers made one function): under P1b row 19 rule 1 a tracked file that no code writes is an input, not an artifact,
  so rule 4's one-decider test does not reach those reads; the decisions they feed are on the transcripts, through the
  reader's span_opener.

## Part 2: the P1b sync list

- **V-1** (section 3, a "never fail" principle): adapted. Anchor unchanged, PLAN-v2.md:96 ("- **One terminal (D2).**
  A dev cycle ends only complete:"). "as important as D24" dropped (DECISIONS.md and register.md record no ranking;
  owner-R5); the quote is D25's whole sentence as DECISIONS.md:70 records it (format-FH-6); id D25 kept.
- **V-2** (section 5, P1b and P1c rows): applied as written, after the P8 row (PLAN-v2.md:131).
- **V-3** (section 5, P2 row dependencies): applied as written (PLAN-v2.md:132).
- **V-4** (section 5, P3 row dependencies): applied as written (PLAN-v2.md:133).
- **V-5** (section 5, note on waves and caps): adapted. New anchor PLAN-v2.md:139, the P11 row as the batch rewrote it
  ("| P11 | History rewrite, remote ref deletion, GitHub purge, pre-push guard (last) |"). The note names P1c's
  deliveries for P2, P3, P4, P5, P9 and P10 (P1c X5) and cites its source; rewrapped. Adding P1c to the cap list
  (format-FH-2, plan-FIT-11) not taken; P1c's estimate goes to "For the P1b/P1c session". Same anchor as format-FH-5,
  plan-FIT-07.
- **V-6** (section 6, waves 2b and 2c): applied as written, after PLAN-v2.md:160.
- **V-7** (section 6, wave 3 dependencies): adapted. New anchor PLAN-v2.md:163, the end of wave 3's "- Must be merged
  first: P1 (...) and P8 (...)" bullet ("the aggregate-dev-report.py main exit change that P3 rewrites around, :697-788
  and :1508-1560)."), so that "Must also be merged first" follows the bullet it extends; text unchanged.
- **V-8** (section 6, wave 9): adapted. New anchor PLAN-v2.md:178 ("**Wave 9: P11 (last).** Must be merged first: every
  phase PR,"); the batch removed "human-run", which the sync text would bring back against D16/D18. Only "(P7b, P1b and
  P1c included; the P1c replay suite green on master)" is added (plan-FIT-07).
- **V-9** (P2 section, dependencies and P1b's map): adapted. The paragraph applied as written at PLAN-v2.md:340; an added
  replacement at PLAN-v2.md:352 ("Either P2 takes that G2 hunk (hooks/subagentstop-artifact-contract-enforce.py
  failing-stop path :747-830, ...") turns the batch's either/or into a pointer to the P1b/P1c delivery, which V-9 says
  lands before P2. plan-FIT-16 verified; its fix belongs to P2-4.
- **V-10** (P2 section, acceptance): applied as written, after PLAN-v2.md:388.
- **V-11** (P3 section, dependencies and P1b's map): adapted. The paragraph at PLAN-v2.md:403 gains V-9's "verified on
  the base, not redone" rule and says a row that still builds a delivered item only verifies it; an added replacement at
  PLAN-v2.md:412 ("P3's declaring-dispatch reader must exist before /close and /commit use it") keeps the stages P3's and
  names the reader as P1b's (E3). plan-FIT-06.
- **V-12** (P3 section, acceptance): applied as written, after PLAN-v2.md:441.
- **V-13** (P4 section, P1b's map): adapted. Insertion anchor unchanged (PLAN-v2.md:451, "Wave 4. Needs P2 and P3
  merged."); an added replacement narrows the batch's goal at PLAN-v2.md:460 ("- D24 table for every artifact /close and
  /commit read or write (L17, L18, ...") to the artifacts P4's rows still change, as the edit's overlap note intends
  (plan-FIT-06 (2)); "steps a hook refused" becomes the steps P1c row 18 lists; "(D23)" added after the in-turn waits.
- **V-14** (P4 section, acceptance): applied as written, after PLAN-v2.md:497.
- **V-15** (P5 section, P1b's map): adapted. Anchor unchanged (PLAN-v2.md:510). "P5-a arms and extends that mechanism"
  becomes: P5-a verifies it, arms it only where P1b left it unenforced and adds only the release-input denies
  (plan-FIT-12); the escalation-record deny "is dropped" becomes: normally it has nothing to deny and is not added (the
  batch and R51 made it conditional); "only the instrument-failure block waits for /stop" is replaced, because the /do
  missing-sidecar gap (PLAN-v2.md:548, :602) is also cleared only by a human: a site fitting no X6 class fails the
  check, and that gap is named.
- **V-16** (P5 section, acceptance): applied as written, after PLAN-v2.md:588.
- **V-17** (P6 section, P1b's map): adapted. Anchor unchanged (PLAN-v2.md:608). "A3.a builds on the producer E6 kept"
  becomes: A3.a builds on E6's outcome and keeps the CLI transcript write set (TC-46), with P6-4's clause for a dev
  report left without a self-reported list (plan-FIT-05); "A4.a changes only the role input" names the sources the
  batch's A4.a row changes; "as P5 armed it" becomes "as P5-a left it" (plan-FIT-12).
- **V-18** (P6 section, acceptance): applied as written, after PLAN-v2.md:637.
- **V-19** (P9 section, runtime artifacts moved to P1b): applied as written, after PLAN-v2.md:752.
- **V-20** (P9 section, goal "one producer per fact"): applied as written (PLAN-v2.md:755).
- **V-21** (P9 section, CLAUDE.md row, Hook Discipline #5): adapted. Anchor unchanged (PLAN-v2.md:781); the quoted
  CLAUDE.md text gets back its backticks ("Ordinary `/dev` recovery has an honest terminal branch") to match CLAUDE.md:98
  at d625284.
- **V-22** (P9 section, acceptance): applied as written, after PLAN-v2.md:793.
- **V-23** (P10 section, dead-code row): applied as written (PLAN-v2.md:825).
- **V-24** (P10 section, artifact-level goal): adapted. The batch had already added corrections 2.61's goal at
  PLAN-v2.md:811 ("- Artifact-level D17 (D24): every artifact the harness writes has a reader ..."); the edit's own
  overlap note says this bullet replaces it, so the operation became a replacement there instead of an insertion after
  "- BA can propose a rule's retirement." (:809); text byte for byte (plan-FIT-06).
- **V-25** (P10 section, acceptance): adapted. Anchor unchanged (PLAN-v2.md:838). "the stub retirement" (the dac09ec9
  design) becomes the stub registrations (render-settings check, the migration) while the stubs stay tracked (D19,
  experiment 3 option (a)).
- **V-26** (P11 section, dependencies): applied as written (PLAN-v2.md:846).
- **V-27** (P11 section, acceptance): adapted. Anchor unchanged (PLAN-v2.md:880). The hint drops "if corrections 2.65
  applies" (applied) and names the landing's one new step, the pre-push guard install at the next Stop on a pulled and an
  unpulled home, and the guard's refusal; R-N1, R-V1 and the held index.lock stay.
- **V-28** (section 11, net-code metric): applied as written (PLAN-v2.md:1161).
- **V-29** (section 11, three metrics): adapted. Anchor unchanged (PLAN-v2.md:1138). Rows 1 and 3 as written. Row 2:
  the F6 aside names /dev-overnight explicitly and cites D22 and RD4 (the human /restart resumes an interrupted
  interactive session; F6o has no human event, X8), and F2g is marked as measured armed. plan-FIT-10 is left to the
  DECISIONS.md side.
- **V-30** (section 14, wave list superseded): applied as written, after PLAN-v2.md:1249.
- **V-31** (new section 15): adapted. Anchor unchanged (PLAN-v2.md:1260, the last line). The ranking "with 'one
  producer, one consumer'" is dropped and the "之后…" quote loses its quotation marks: the merge rule is credited to D25
  and P1c's merge rule, and the owner quote is D25's full text (owner-R5, format-FH-6); D25's earlier words are CC4,
  CC8, DT3, DT4 and HC2, not DT2; "N1 and V1-1/NV-1 have no record" is corrected from reviews/P7b-PR-record.md
  (plan-FIT-04); the merge rule's scope matches the sync header (P7, P7b and P8 carry no item); "its E9" becomes P1b's
  E9 and TC-20 cites P1b's E3; the path rule covers both directions (P1b item 4). format-FH-11's shortening not taken.
- **D-1** (the 2026-10-24 ruling as D25): adapted, by the orchestrator's override of the evaluator. The sync anchor
  (DECISIONS.md:5) had been rewritten by R91, and DECISIONS.md already records D25 at :68-84. The evaluator's merged
  rewrite of that block was not applied: its insert would be a second D25, the rest is already there, and it would add
  a source line and provenance claims no record supports and a "ranks with D24" label that neither DECISIONS.md nor
  register.md records. Only the heading fix D-1's own note asks for was applied (plan-FIT-09): DECISIONS.md:7 ("## Owner
  rulings of 2026-10-23 (latest; they override every decision below, PLAN-v1, PLAN-v2 and every prompt)") now reads
  "(they override every decision below except D25, ...)", and DECISIONS.md:68 ("## Owner ruling of 2026-10-24") now
  says D25 is the latest ruling and, like D20-D24, overrides every other decision, PLAN-v1, PLAN-v2 and every prompt.
- **D-2** (Execution, the inserted phases): applied as written, after DECISIONS.md:205.
- **D-3** (Execution, the merge rule): adapted. New anchor DECISIONS.md:208 ("- Every phase PR carries the D24 artifact
  table, measured, before review.", the batch's corrections 1.10 bullet), so the new bullet follows it as its overlap
  note asks; text byte for byte.
- **H-1** (table rows for P1b and P1c): applied as written, after HANDOVER.md:18.
- **H-2** (P2 row dependencies): applied as written (HANDOVER.md:19).
- **H-3** (P3 row dependencies): applied as written (HANDOVER.md:20).
- **H-4** (P4 row dependencies): applied as written (HANDOVER.md:21).
- **H-5** (P5 row dependencies): applied as written (HANDOVER.md:22).
- **H-6** (P6 row dependencies): applied as written (HANDOVER.md:23).
- **H-7** (P9-P11 row): applied as written (HANDOVER.md:24).
- **H-8** (duration): adapted. The anchor extended to HANDOVER.md:26-27 ("按每波最长的算：第 2 波约 3.5 天，..." and the next
  line) so the 134-column line could be rewrapped; every character kept (31 days = 18 + 13).
- **H-9** (waves told to the owner): applied as written, after HANDOVER.md:29.
- **H-10** (new section "2026-10-24 更新"): adapted. Anchor unchanged (HANDOVER.md:104, the last line). The owner
  ranking "同等重要" is dropped and the quote is D25's full text (owner-R5); "记进" becomes "已记进" and DT2 leaves the list;
  the "no record" sentence on N1, V1-1 and NV-1 is corrected (plan-FIT-04); "每个提示词" names P2-P6 and P9-P11; "(D24)"
  added to the P1b line; rewrapped.
- **K-1** (decisions table, D24 and D25): adapted. Anchor unchanged (COVERAGE.md:46). In the D24 row the note cites
  R89's status line instead of corrections.md, "no D20-D23 rows yet" becomes "no D18-D23 rows", and "one producer, one
  consumer" becomes "at least one consumer" (D24). The D25 row as written.
- **K-2** (owner statements, O4/O6): applied as written (COVERAGE.md:55).
- **K-3** (owner statements, O10/O12): applied as written (COVERAGE.md:59).
- **K-4** (owner statements, O17/O18): adapted. Row anchor unchanged (COVERAGE.md:61); "P3 (include step 6)" and "P4
  (OPERATION_STALLED question)", withdrawn designs (D21, D22, D23), give way to what P3 and P4 now deliver, with P1c and
  P9 (Hook Discipline #5, C12) added. An added replacement in R89's status line (COVERAGE.md:3, "Rows D3, D4b, D7, D8
  and O17/O18, ...") takes O17/O18 and "the OPERATION_STALLED question" out of its list, which would otherwise be false.
- **K-5** (owner statements, O45 waves): applied as written (COVERAGE.md:70).
- **K-6** (owner statements, the 2026-10-24 rule): adapted. Anchor unchanged (COVERAGE.md:70). "as important as D24"
  dropped (owner-R5); the suite and the merge rule are worded after D25's own text, not as the owner's words.
- **K-7** (contradictions, C12): applied as written, after COVERAGE.md:132.
- **K-8** (dependencies table, P1b and P1c): adapted. The rows applied as written after COVERAGE.md:179; an added
  replacement of the paragraph under the table (COVERAGE.md:187-189, "Merge order inside waves matches PLAN ... P7b is a
  dependency of no prompt, ...") dates that clause and states the current facts, since the new rows list P7b as a
  dependency.
- **K-9** (dependencies, P2): applied as written (COVERAGE.md:180).
- **K-10** (dependencies, P3): applied as written (COVERAGE.md:181).
- **K-11** (dependencies, P9-P11): applied as written (COVERAGE.md:185).
- **K-12** (new section (e)): adapted. Anchor unchanged (COVERAGE.md:286, the last line). The N1/V1-1/NV-1 "no record"
  bullet is rewritten from reviews/P7b-PR-record.md (plan-FIT-04); the D25 (2) row's Test cell says P1c's acceptance 4
  allows the human /restart of F5, F5f and F6 (D22, RD4).
- **P2-1** ("Before you start"): applied as written (prompts/P2.md:68).
- **P2-2** (merge titles and P1c's suite): applied as written (P2.md:72).
- **P2-3** (stop message): applied as written (P2.md:77).
- **P2-4** (the P1b and P1c block): adapted. Anchor unchanged (P2.md:84, "## Goal"). The merge rule cites acceptance 20
  (plan-FIT-08); "Already done" names rows 4 and 9, where the batch put P1b's work, and says the named rows keep only
  what is left; added the write-qa-mode.sh creation and qa_mode switch (P1b row 1, E7), the extra overnight-state
  writers (E13), P1c's "Delivered for later phases" (X5), Goal 7's STOPGATE condition already holding (P1c row 7) and
  acceptance 13's two env lines if X3 armed STOPGATE (plan-FIT-16); D25 quoted on one line, verbatim; "P1c's X3" kept
  (plan-FIT-02 not adopted: P1b.md:683 forbids P1b arming).
- **P2-5** (the never-fail acceptance): adapted. New anchor P2.md:827 ("    harness-report.json, continuation sentinel,
  aggregate-pending and terminal receipts.", the last line of the batch's acceptance 19); numbered 20.
- **P3-1** ("Before you start"): applied as written (prompts/P3.md:65).
- **P3-2** (merge titles and P1c's suite): applied as written (P3.md:69).
- **P3-3** (stop message): applied as written (P3.md:77).
- **P3-4** ("Branch and pull request" dependencies): adapted. New anchor P3.md:718 ("- Dependencies: start only after P1,
  P8 and P7b are merged"; the refreshed P3 already added P7b); text byte for byte (plan-FIT-07).
- **P3-5** (the P1b and P1c block): adapted. Anchor unchanged (P3.md:84, "## Goal"). The merge rule cites acceptance 20
  (plan-FIT-08); row 1 is already the corrected text and the batch tied its proof to acceptance 8, so the block says P1b's
  acceptance 7 is the proof and acceptance 8 runs the reader over P3's own gaps (D8's [INFERRED] experiment stays
  cited); "corrections.md's D24 acceptance" becomes acceptance 18; R17's notice write in row 7 is named as delivered (P1b
  row 3, P1c row 7).
- **P3-6** (the never-fail acceptance): adapted. New anchor P3.md:667 (" a subagent's only question path).", the last
  line of acceptance 19); numbered 20 (plan-FIT-08).
- **P4-1** ("Before you start"): applied as written (prompts/P4.md:30).
- **P4-2** (merge titles and P1c's suite): applied as written (P4.md:34).
- **P4-3** (stop message): applied as written (P4.md:44).
- **P4-4** (the P1b and P1c block): adapted. Anchor unchanged (P4.md:70, "## Goal"). The merge rule cites acceptance 22
  (plan-FIT-08); added replacements narrow the batch's Goal 8 (P4.md:105-111, "8. **One producer and one deciding consumer
  per artifact (D24).** Per artifact /close and /commit read or write ...") and lines 2-5 of acceptance 21 (P4.md:685-688)
  to the artifacts P4's rows still change, with P1b's table as the before (plan-FIT-06 (4)); acceptance 21's last line is
  kept for P4-5's anchor; the sentence on P1c row 18 names hook refusals and repo-relative paths. plan-FIT-05's E6
  addition not taken.
- **P4-5** (the never-fail acceptance): adapted. New anchor P4.md:689 (" channel kept.", the last line of acceptance 21);
  numbered 22; the hint points to Goals 1-2 and acceptance 4's three cases, which R61 and R62 changed.
- **P5-1** (merge titles): applied as written (prompts/P5.md:43-44).
- **P5-2** (stop message): applied as written (P5.md:58).
- **P5-3** ("Branch and pull request" dependencies): applied as written (P5.md:830).
- **P5-4** (the P1b and P1c block): adapted. Anchor unchanged (P5.md:86, "## Goal"). The merge rule cites acceptance 26;
  the escalation-record deny is neither added nor counted (the batch's row 2 is already conditional); "arms" dropped
  (P1b E3 replaces the per-role prefixes; plan-FIT-12); added replacements in the batch's Goal 9 (P5.md:127-130, "
  edits: prompt-workflow.py:1781 _DEV_REPORT_TERMINAL_STATUSES ...") and its Rules-retired bullet (P5.md:797-799, "- the
  second deciders of gate facts (Goal 9, D24): ...") say to retire only what P1b's PR left (P1b rows 2, 9 and 12; E7,
  E8, E11).
- **P5-5** (the never-fail acceptance): adapted. New anchor P5.md:766 (" deciding consumers before -> after / proof (a
  grep for writers and readers, plus a sandbox write trace).", the last line of the batch's acceptance 25); numbered 26.
- **P6-1** ("Before you start"): applied as written (prompts/P6.md:30).
- **P6-2** (merge titles and P1c's suite): applied as written (P6.md:34).
- **P6-3** (stop message): applied as written (P6.md:47).
- **P6-4** (the P1b and P1c block): adapted. Anchor unchanged (P6.md:78, "## Goal"). The merge rule cites acceptance 20;
  a precedence sentence says E6's outcome wins over the batch texts that name another producer or keep what E6 removes,
  and A3.a keeps the transcript (plan-FIT-05); the agent-index sentence is merged with the batch's option one (as V-17);
  "as P5 armed it" becomes "as P5-a left it" (plan-FIT-12); the declaring-dispatch reader is named as P1b's.
- **P6-5** (the never-fail acceptance): adapted. New anchor P6.md:723 (" changes, with this row first.", the last line of
  acceptance 19; the batch extended acceptance 18, the sync's anchor); numbered 20; "(F3.a)" becomes "(F3.a, Goal 4)",
  apart from P1c's F3a (plan-FIT-07, plan-FIT-08, plan-FIT-19).
- **P9-1** ("Before you start"): applied as written (prompts/P9.md:45).
- **P9-2** (merge titles and P1c's suite): applied as written (P9.md:49).
- **P9-3** (stop message): applied as written (P9.md:59).
- **P9-4** ("Branch and pull request" dependencies): applied as written (P9.md:676).
- **P9-5** (Goal 1, one producer per fact): adapted. New anchor P9.md:107-110, Goal 1 as the batch rewrote it ("1. **One
  producer per fact.** spec_path (prompt-workflow, from the session transcript), ..."); the batch's E4 qualifier kept,
  the roster worded as P1b row 18 words it, rewrapped (format-FH-5, plan-FIT-07).
- **P9-6** (scope, rows 1, 2, 4 and 5 after P1b): adapted. Anchor unchanged (P9.md:427, "Locations are at f8c18c2 with
  an anchor. ..."). Row 5 already computes the roster, so "replaces row 5's literal constant" becomes "the function row 5
  describes"; the one-writer proofs are "what acceptance 23 asks for", with P1b's text winning where acceptance 23
  differs (L42, L24, L44); "Rows 6 and 7 and the prose rows stay yours" becomes "The other rows stay yours". plan-FIT-20
  not added.
- **P9-7** (D2 bullet, Hook Discipline #5): adapted. Anchor unchanged (P9.md:187). The quotation marks around the D25 (3)
  paraphrase are removed (not verbatim in DECISIONS.md or register.md), the teachings file is named in full and the
  locations are given at f8c18c2.
- **P9-8** (row 16, the #5 rewrite): adapted. New anchor P9.md:446, row 16's sentence "#5 rewritten: one terminal,
  complete; a producer question is asked or relayed in-turn as row 14 documents it (outside /dev-overnight; ..." (the
  batch added the overnight clause, R76 changed "relayed"). The sync text replaces the overnight parenthetical; R76's
  "asked or relayed ... as row 14 documents it" and D3 are merged in.
- **P9-9** (acceptance 16 grep): adapted. The anchor extended to the whole of P9.md:579 so the line could be rewrapped;
  the sync text byte for byte; the unchanged tail ("`grep -c 'this turn' CLAUDE.md` -> at least 1;") moves to its own
  line.
- **P9-10** (the never-fail acceptance): adapted. New anchor P9.md:622 (" table" claims (close.md:278, commit.md:83-84) if
  P4 left them.", the last line of the batch's acceptance 23); numbered 24; the code list gains E4's cp-enforce fixes and
  arming and drops "if any" for E2; "Prose-only changes need no fault replay" is replaced by P1c's own merge rule for
  extracted command and agent files (plan-FIT-08).
- **P10-1** (merge titles and P1c's suite): applied as written (prompts/P10.md:38).
- **P10-2** (stop message): applied as written (P10.md:46).
- **P10-3** ("Branch and pull request" dependencies): applied as written (P10.md:745).
- **P10-4** ("What earlier phases left to you", P1b and P1c): adapted. Insertion anchor unchanged (P10.md:54, "- P2:
  `--cycle-reset` as a loop-gate bypass (V9c);"). Added replacements in the batch's D24 Goal bullet (P10.md:99-104), the
  D24 sub-bullet (:130-132) and row 19's first cells (:357): the artifact-level goal rests on P1b's CI check and D24's
  per-PR table stays for the artifacts P10 changes; L48 is added (P1b row 13 deletes the sentinel); the P1c bullet gains
  X5's rows for P10 and cites acceptance 25. plan-FIT-06 item 3 used in substance, not verbatim.
- **P10-5** ("Dead code (D17)", leave out P1b's deletions): applied as written, after P10.md:476.
- **P10-6** (the never-fail acceptance): adapted. Anchor unchanged (P10.md:711); "the stub retirement" becomes the
  stub-registration class, as in V-25; numbered 25.
- **P11-1** (merge titles): applied as written (prompts/P11.md:46-47).
- **P11-2** (dependencies, P1c's suite): applied as written, after P11.md:51; it cites acceptance 19.
- **P11-3** (the never-fail acceptance): adapted. Anchor unchanged (P11.md:661); numbered 19; the hint names the
  guard's refusal without the old condition and the guard install on a pulled and an unpulled home.

**Decision ids.** The sync list's "D25" is the ruling DECISIONS.md already records as D25 (the batch's block at
DECISIONS.md:68-84), so no decision id was introduced and nothing was renumbered; D26 and above are unused. Every
evaluator reported no new id.

**Acceptance numbers.** Each never-fail item takes the next free number after the batch's last item (the D24 items, and
in P3 the subagent question experiment): P2 20, P3 20, P4 22, P5 26, P6 20, P9 24, P10 25, P11 19. Each prompt's "P1b
and P1c" block cites the same number (P2-4, P3-5, P4-4, P5-4, P6-4; in P10 the P1c bullet of P10-4); P9 has no such
block, and P11 cites its number in "Before you start" (P11-2). The batch's own acceptance numbers are unchanged.

**Quote rule.** The sync list's quote "之后每个阶段合并的条件之一是…" (reviews/P1b-plan-sync.md, "Sources" and the
V-31 and D-1 texts) is in neither register.md nor DECISIONS.md, so no applied edit presents it as the owner's words; the
rule it states is kept as P1c's merge rule (DECISIONS.md Execution bullet from D-3, PLAN-v2 section 15, each prompt's
never-fail acceptance). The "ranked with D24" wording ("as important as D24", "ranks with D24", "同等重要") was dropped
for the same reason (V-1, V-31, H-10, K-6 and D-1's heading). Owner words that the edits do quote are verbatim runs of D25's
sentence as DECISIONS.md:70 records it (in full in V-1, V-31 and H-10; without its leading words in P2-4 to P6-4, reviewer item 26) and register rows quoted verbatim.

## Verification rounds

The method is under "Method"; the choices the rounds made are under "Conflicts and choices". Findings are the DEFECTS
lines summed over the verifiers; "distinct" counts the same defect reported by several verifiers once. Each round's
baseline is named in its addendum to the verifier brief.

| round | baseline | defects by verifier (res-a, res-b, sync-V, sync-dhk, sync-p, quotes, structure) | total | outcome | edits | commit |
|---|---|---|---|---|---|---|
| 1 | c728380 | 6, 3, 9, 10, 7, 4, 3 | 42 | all applied | 73 | fa5659d |
| 2 | 686b375 | 3, 2, 16, 5, 18, 3, 12 | 59 | all applied | 99 | f65290d |
| 3 | 3f01eea | 1, 2, 8, 1, 4, 1, 1 | 18 | all applied | 27 | f732f26 |
| 4 | 4ab7cf1 | 1, 1, 2, 0, 4, 0, 4 | 12 | 9 applied, 2 merged as duplicates, 1 moot | 18 | 9380922 |
| 5 | ad5674b | 2, 3, 12, 2, 14, 2, 15 | 50 | merged by one integration step; two reversals checked by refuters (both held) | 91 | b335a0e |
| 6 | 2b4ea19 | 3, 4, 3, 2, 6, 0, 2 | 20 (+1 after its baseline) | 13 distinct + 1 applied | 23 | 7beb706 |
| 7 | 3ef1eca | 1, 2, 7, 3, 8, 1, 6 | 28 | 9 distinct applied, 2 rejected | 28 | e428c5b |
| 8 | a085da8 | 0, 1, 2, 0, 1, 0, 0 | 4 | 4 distinct applied (one checked by a refuter, held) | 24 | bb56fe5 |
| 9 | d16129f | 0, 2, 3, 0, 3, 0, 2 | 10 | 4 distinct applied, 1 rejected | 20 | 32fe0e0 |
| 10 | e712310 | final confirmation round, higher bar; four verifiers (res, plan, prompts, quotes-structure): 0, 1, 2, 0 | 3 | 2 distinct applied; a check of those edits found 1 more, applied | 7 + 1 | 5a4e0a3, d347b2f |

### Round 1

Baseline c728380. 42 findings, all applied once duplicates were merged; 73 edits in fa5659d.
- D25 ranked with D20-D24 in the eight prompt headers, PLAN-v2's precedence lines and DECISIONS.md's headings.
- DECISIONS.md cites HANDOVER.md and COVERAGE.md lines by name (the sync's inserts had moved them).
- PLAN-v2's older text follows what the sync made P1b and P1c own (reader credits, P4's advisory sinks, the G2-hunk
  clause, TC-56 and TC-57, the launcher at :44 and :539, V-29's /restart exception); the residual texts name P1b's E3
  and acceptance 7.
- The push dead end for a typed remote that is not the upstream is fixed at its producer (push.sh counts against the
  typed remote).

Rejected: none. Then 686b375 merged the P1b/P1c session's 2e7d4c0..0cbfbd3 (6 commits, rewriting both prompts and
inventory/).

### Round 2

Baseline 686b375; before the fixes, 32a6967 (this record's draft) and 3f01eea (that session's P1c fixes
8ad26bc..1715fdd) came in, and the fixes align to P1b and P1c as merged at 3f01eea. 59 findings, all applied; 99 edits
in f65290d.
- PLAN-v2 and the prompts follow the revised P1b and P1c: P1b's E4 arms G2 (P1c's X3 only if P1b did not); P1c's
  net-code cap <= +150; 21 faults, with the human /close or /commit of the F8 faults beside /restart; P1b corrections 4,
  7 and 8; E8 without `pending`; row 10's routing loop; E6's candidates; X8's hand-off to P9.
- D25 (2)'s "no human action" names the owner's own commands (DECISIONS.md, HANDOVER.md, COVERAGE.md).
- P4 cites P1b's acceptance 7, not P3's acceptance 8, as the reader's proof; P4's wave paragraph, PLAN-v2's UD-CM row
  and V-22's merge-rule sentence.

Rejected: none.

### Round 3

Baseline 3f01eea (head f65290d). 18 findings, all applied; 27 edits in f732f26.
- PLAN-v2:96's D25 bullet gets the owner's-own-commands exception; HANDOVER question 5's heading follows P2's arming.
- R15's and R58's parentheticals follow P1b's rows; R46's names pull.sh's own success line.
- PLAN-v2 follows through on G2's arming, P1c's merge rule, ESCALATION_ACK, row 18, E3, E6 and E8.
- r3-structure-1 had P5 extend P1c's class H to the /do missing-sidecar gap (withdrawn in round 5).

Rejected: none. Then 4ab7cf1 merged that session's 9f214f3 (P1c: the merge rule's coverage step leaves the test
directories out; X3's and X4's probes; D8 wording).

### Round 4

Baseline 4ab7cf1. 12 findings: 9 applied, 2 merged as duplicates (r4-sync-p-1 = r4-res-b-1, r4-structure-3 =
r4-sync-V-1) and 1 moot once r4-res-b-1 landed (r4-structure-2), as round4-notes.md records; 18 edits in 9380922.
- The push predicate also holds when HEAD is an ancestor of the typed remote's tip ("Conflicts and choices").
- P2's three take-the-hunk or merge-after-P3 sites follow round 3: no hunk, P2 first.
- P3 quotes TC-40 as round 3 rewrote it; PLAN-v2 and P4 map rows to lines as P1c's "Delivered by P1b" does; P1c row 10
  is credited for the QA latest-report guess; P2-P4's in-flight and legacy cases and P9's L18 item follow what P1b's and
  P1c's PRs leave.

Rejected: none (r4-structure-2 became moot). Then 92b4d9b and ad5674b merged 18 commits of the P1b/P1c and reviewer
sessions, up to c6e3942, among them reviews/D20-D25-reviewer-findings-on-A.md (4cc52aa). The structure verifier had read
nine claims A1-A9 from them early ("AFTER 4ab7cf1"); the claims and the reviewer findings went to round 5.

### Round 5

Baseline ad5674b; the fixes were applied on eef8a5c, a fast-forward to 5 commits of that session. 50 findings, merged by
one integration step into 91 edits that keep every line count (b335a0e).
- Two reversals, each held by a refuter ("Conflicts and choices"): the /do sidecar leaves class H, and G1 and G3 read
  their switch at run time.
- D20-D25 in the eight preambles, P9 and the P10 and P11 tail sentence; no per-role prefix-row fallback (D21).
- HANDOVER's 会问你 cells, :7 and :37 follow D18; the overnight subagent's decision rule follows D20; D8's deny half; P4
  fails the never-dispatched case instead of recording a /close or /commit dead end.
- The A1-A9 claims that held: P1b row 7 keeps /commit's chain call, E14 keeps Step 8's selection, row 10's main-agent
  route, E7's script stubs, P1b's arming commit, the content pairing of P1c row 17.

Not applied: r5-structure-15, a line number in P1b.md (sent to that session). Then 2b4ea19 merged 787167e..e8e5817.

### Round 6

Baseline 2b4ea19; the fixes were applied on ec2681d, a fast-forward to P1c 88b240c, P1b 5922f1f and that session's merge
of 2b4ea19. 20 findings and 1 after the baseline; 13 distinct and the 1 applied; 23 edits in 7beb706.
- P3's do-report branch opens for a hook-minted /do task with no do-report (round 5's open item).
- Round 5's switch-read hunks are named in P2's and P3's shared-file lists and PLAN-v2:180 and :357; P2's Arming-timing
  step decides only P5's question.
- P3's Out of scope drops TC-20's prefix-row fallback and P5 row 1 its "or keep it and say why"; P4's new routes get
  acceptance replays; HANDOVER question 5's heading and COVERAGE.md's status line; PLAN-v2's dated TC-26 note bracketed
  and :576's numbers back to 09ab15b.
- After the baseline: P9:458-460 follows 88b240c (the wake's SendMessage widening is issued by
  userprompt-restart-authorize.py).

Rejected: none. Then 3ef1eca merged 49 commits of that session (db16126..fb8f42c), large revisions of P1b, P1c and
inventory/.

### Round 7

Baseline 3ef1eca; the fixes were applied on d6409c2, a fast-forward to a12fb1d, 976adef, 59b483a, a9a9b98 and d6409c2
(inventory round 13). 28 findings; 9 distinct applied, 2 rejected; 28 edits in e428c5b. All but three follow that
session's commits since ec2681d:
- A close-QA or commit-QA finding on a product file no dispatch of the task wrote goes back to that round's own QA
  dispatch, with no default role (P4, PLAN-v2).
- P1c X8's wake rule (a recurring CronCreate of the wake's text) and the time-lock's wake check (PLAN-v2:536, P2, P5);
  P1b row 15's terminal receipt call kept (P2, P5); P1b row 13's one overnight-state decider and row 11's early
  commit-landing exemption (P2, P3); X8's third case (P9, PLAN-v2).
- Inventory counts 43 / 52 / 26 / 24 of 120; COVERAGE.md's status line and fix 3, HANDOVER:83.

Rejected: r7-sync-p-8 and r7-sync-V-7 ("Conflicts and choices"). Then a085da8 merged 5b2b3d9 (P1b E9 and rows aligned
with inventory round 13).

### Round 8

Baseline a085da8. 4 findings, 4 distinct, all applied; 24 edits in bb56fe5.
- P1b row 18 (5b2b3d9) made one transcript reader: P2, P3, P5 and P6 read transcripts and agent meta through it, and
  P5's launcher loads it by path instead of copying the human-record rule under a drift test (refuter r8x-launcher held;
  its fix replaced the verifier's).
- P4's acceptances replay the no-artifact close-QA route; PLAN-v2:357 lists the terminal receipt call.

Rejected: none. Then d16129f merged abb33b2, 9e796b8, 5530a7e and 7284365 (inventory A108 and A120; P1c's faults
paragraph and Rollback).

### Round 9

Baseline d16129f. 10 findings; 4 distinct applied, 1 rejected; 20 edits in 32fe0e0.
- window_open calls stop_contract.timelock_released, so P5 moves timelock_released, with span_opener and the
  human-record rule, into the reader's module and states the loss per broken module; P2 no longer allows a copy of the
  window rule.
- P4 replays a commit-QA REJECT whose finding cites no artifact or names only an undeclared product file.
- PLAN-v2's and P5's "a crash in a gated span blocks" lines name TC-11's stated loss (D24 outranks S1).

Rejected: r9-sync-V-3 ("Conflicts and choices"). Then e712310 merged that session's 0381276..facc385 (17 commits: P1b,
P1c, inventory/ and their own record reviews/P1b-P1c-findings-record.md).

### Round 10

Baseline e712310 for everything, under the round 10 addendum's higher bar. Four verifiers: res 0, plan 1, prompts 2,
quotes-structure 0 DEFECTs, 3 reported and 2 distinct, both caused by P1b commits merged in e712310; 7 edits in 5a4e0a3.
- P1b row 8 and correction 9 move the /spec coverage rule to G2 at the spec subagent's stop and leave
  stop-spec-coverage-enforce.py an exit-0 stub: P5 acceptance 13 and PLAN-v2:1158 and :1353 follow.
- P1b row 6 moves the gitignore preflight's dev-report rule into G3, next to row 11's commit-landing admission: P3 row
  13, P3.md:102 and acceptance 11, and PLAN-v2:423 add P3's three other profile exemptions to G3's admission.

A further independent check of those 7 edits found 1 defect: P5 acceptance 13's new sentence could be read as exempting
/spec from the time-lock (against acceptances 9, 10 and 12, D20); it now says "with no open overnight window" (1 edit,
d347b2f). Rejected: none. No merge followed: P1b, P1c and inventory/ are unchanged since e712310. Verification ends
here; every remaining item is MINOR, listed under "Left for the reviewer".

### What the rounds checked

Across the rounds, round 10 last at e712310, the verifiers checked that every standing R item and every sync edit landed
as recorded, each NEW present at the head or traced to the later entry that replaced it on purpose; that no rejected
idea came back; that every owner quote is verbatim in register.md or DECISIONS.md and no planner text is credited to the
owner; that no personal data or model identifier was added; that every prompt keeps its first line, P2-P6 and P9 end
byte for byte with prompts/_common.md and P10 and P11 keep their own tails but for round 5's sentence; and that
cross-references, decision ids and acceptance numbers hold, including every reference into prompts/P1b.md,
prompts/P1c.md and inventory/ at the round's baseline. The counts fell from 42 and 59 in rounds 1-2 to 4 and 10 in
rounds 8-9 and 3 in round 10.

## For the P1b/P1c session

Neither the residuals, the sync nor any verification round changed prompts/P1b.md, prompts/P1c.md or inventory/. The
first eighteen items come from the sync evaluators' FOR-P1B-P1C fields (no refuter result asks for a change to these
files); line numbers in their first part are at the sync commit (c728380), the version the evaluators read. The P1b/P1c
session's commits merged since (686b375 to e712310) rewrote both prompts, so each item ends with where the point stands
at e712310, re-read there; nothing changed those files after e712310, so each status holds at d347b2f. The last four
items are what the verification rounds sent to that session. That session's own record is
reviews/P1b-P1c-findings-record.md (facc385).

- prompts/P1b.md:13, :161-164 and prompts/P1c.md:138-143 call the ruling "the owner's rule of 2026-10-24", quote it from
  永远 without its opening, rank it with "one producer, one consumer" (P1b.md:163, P1c.md:138) and credit the suite design
  and merge rule to the owner (P1c.md:141-143); DECISIONS.md D25 records neither the ranking nor the design as the
  owner's words. Proposed: name it D25, quote DECISIONS.md D25 in full, drop the ranking, and credit the suite and the
  merge rule to D25's recorded measure and P1c. Sources: V-1, V-31, D-1, H-10, K-6 (owner-R5, format-FH-6). At e712310:
  settled (P1b.md:201-208, P1c.md:162-169).
- prompts/P1b.md:102 and prompts/P1c.md:134-136 rank planner text below "D20-D24". Proposed: D20-D25. Source: D-1. At
  e712310: settled in both (P1b.md:141-142, P1c.md:156-157).
- prompts/P1c.md:16-17, X9 (:357-372) and R-V1 (:544-547) say N1, V1-1 and NV-1 have no record, while
  reviews/P7b-PR-record.md records them (:220 N1, :242 V1-1, :253 NV-1). Proposed: cite that record; take R-N1's
  "before" from its N1 (after P7's manual init and a CLI `model` write, pull.sh rc=1 "cannot pull with rebase: You have
  unstaged changes") and R-V1's from its V1-1/NV-1 scenarios (landedlock.sh, v11doc.sh); give an owner to N1's remaining
  window (record :1334-1342) and to its Fact 1, safe_pull's tee without pipefail (:1300-1304). Sources: V-27, V-31,
  H-10, K-12, P11-3 (plan-FIT-04). At e712310: settled (X9, P1c.md:470-481, and R-V1, :738-744, cite the record; row 20,
  :554, takes Fact 1 and, if X9 takes it, N1's window).
- prompts/P1b.md E13 (:365): "one writer (the orchestrator at Step 4)" for the cycle contract contradicts TC-43
  (PLAN-v2.md:1074 at 86b7cbc) and P2's PM TRIAGE handler as the only writer (P2.md:386-388 at 86b7cbc); its decision
  rule (:369-371) has no /stop replay although P2 row 14 keeps break-overnight-lock.py's current_phase=completed write.
  Proposed: name the PM TRIAGE handler and add the /stop case. Source: P2-4 (plan-FIT-03). At e712310: settled (E13,
  P1b.md:589-619: a PM TRIAGE handler is the contract's only writer, and the replay includes a human /stop inside cycle
  1's window).
- prompts/P1b.md:683 forbade P1b to arm any switch; if P1b were changed to arm G2 under E4 (plan-FIT-02), P2's "P1b and
  P1c" block would have to read "if P1b or P1c already set". Source: P2-4. At e712310: settled (P1b arms G2 under E4,
  P1b.md:98, :368, :705; P2.md and PLAN-v2.md say so since round 2, P2.md:113 and PLAN-v2.md:104, :174, :181).
- prompts/P1b.md "Corrections to PLAN-v2" item 2 (:395) takes "the escalation stores and the arbitration path (Goal 3)"
  from P3, but no P1b scope row names progress_measure.py's arbitration and awaiting_input phases or
  declare_awaiting_input (row 3 :459 names only G2's arbitration comment; P1c row 7 :405 only the progress/ store and
  its G2 helpers), and P3 row 6 keeps them. Proposed: list them in row 3, or narrow item 2 to "the G2 escalation stores,
  their admission and G2's arbitration comment". Source: P3-5. At e712310: still open (item 2 is P1b.md:661; row 3,
  :758, names G2's escalation stores, their admission and the arbitration comment, and no progress_measure piece).
- prompts/P1b.md E6 (:271-284): its candidates were the journal and dev's owned_edits/pre_edit_snapshots, while PLAN-v2
  TC-46 and P6 take the CLI transcript write set as the one source; it did not say whether `_wire_ledger_judgment`'s
  ENTANGLED check, the owned-edits ledger and dev's files_created/files_modified stay (P6 rows 5 and 6 keep them).
  Proposed: name the transcript reader as a candidate (or say A3.a's check is G2's check of dev's own report) and settle
  the three. Sources: V-17, P6-4 (plan-FIT-05). At e712310: settled (E6, P1b.md:438-461, takes the CLI's transcript
  record as candidate (c) and keeps the ENTANGLED check and dev's declared file lists).
- prompts/P1b.md E3 (:220-242) did not say whether the derived write permission ships enforcing when it deletes the
  per-role prefixes, or which callers it denies; its Out of scope (:506) gave P5 "the D8 deny for paths no obligation
  declares", which P5 row 1 does not plan. Sources: V-15, V-17, P5-4, P6-4 (plan-FIT-12). At e712310: settled (E3,
  P1b.md:341-345: enforcing, every caller, the main agent included; the main agent's half goes to P5 row 1 only under
  acceptance 17's condition).
- prompts/P1b.md E8 (:303-304) prefers (a), no skeleton, on a tie, while P5's TC-18 continuation and its rows 15 and 21
  read the pending do-report skeleton (PLAN-v2.md:548 at 86b7cbc). Proposed: E8's rule covers that case. Sources: V-15,
  P5-4 (plan-FIT-13). At e712310: addressed (E8, P1b.md:494-516, still prefers (a) on a tie and ties its outcome to P5
  row 21 and to its correction 8).
- prompts/P1b.md Goal 3 (:72-75) and acceptance 13 allow deciding checks only at the producer's stop, G1 and G3; P5's
  Stop gate was not named. Proposed: count the command's Stop gate as an allowed position. Source: P5-4 (owner-R10). At
  e712310: settled (P1b.md:92-96).
- prompts/P1b.md row 19 (:475) and acceptance 3 do not say how the CI check derives producers and deciding consumers for
  artifacts that are not files (the obligation record, the task-id rule, the terminal vocabulary, the resolver's stdout,
  the COMMIT response line, the changelog-status block; E1 counted 32 "row not a file" misses). Proposed: state the
  derivation and add a mutation such as a second parser of the changelog-status block. Sources: V-24, P10-4
  (plan-FIT-15). At e712310: addressed (P1b.md:846 adds a second parser of a declared response block as a mutation).
- prompts/P1b.md:37: the "latest baseline CI run on origin/master is green" check names no command. Source: K-8 (review
  note). At e712310: settled (P1b.md:39-46 give the gh query and the REST call).
- prompts/P1c.md X6 (:302-304): class H names only the time-lock block and its instrument-failure block, so P5's
  command-gate and launcher instrument-failure blocks (released by /stop) fit no class, and a lost hook-written input
  (the /do sidecar, PLAN-v2.md:548 at 86b7cbc) is not classed. Proposed: count them in H and class the lost input.
  Source: V-15. At e712310: still open in P1c, covered in P5: class H (P1c.md:360-363) still names only the time-lock's
  two blocks, and P5 extends it to its own instrument-failure block (prompts/P5.md:119-122); the lost sidecar needs no
  class since round 5, as it blocks nothing ("Conflicts and choices").
- prompts/P1c.md "Net code cap" (:687-690): the -150 estimate counted code P1b removes first. Proposed: count against
  the master P1b leaves and re-derive. Source: V-5 (format-FH-2, plan-FIT-11). At e712310: settled (P1c.md:974-980, <=
  +150).
- prompts/P1c.md "Merge rule from P1c on" (:557-562): a fault replay's path left out settings.json (P5 changes the Stop
  group and adds `Skill(codex:*)`) and any CI-only script (P10's scripts/size-ratchet.py, run only by baseline.yml), so
  P5's and P10's never-fail acceptances would fail on their own diffs. Proposed: count the settings.json keys a replay
  uses, and let a file no hook or template reaches pass with the CI job that runs it, or an equivalent rule. Sources:
  P5-5, P10-6 (plan-FIT-17). At e712310: settled (P1c.md:749-780: keys compared one by one; a CI-only file, such as
  P10's size ratchet, printed as a fact).
- prompts/P1c.md X8 option (B) (:351-352) kept the human /restart for F6o against the fault acceptance (:525) and the DO
  NOT list (:750-751, D20). Source: V-29. At e712310: settled (X8, P1c.md:406 on, offers no option (B)).
- prompts/P1c.md X8 option (A) (:345-347) widens the SendMessage exception to the overnight session's own wake, which
  makes CLAUDE.md:62 at d625284 and Lesson 16 false, and P1c's "Hand-offs for the sync list" (:730-739) named only Hook
  Discipline #5. Source: P9-8 (plan-FIT-18). At e712310: settled (P1c.md:1059-1063 hand off CLAUDE.md:62 and Lesson 16).
- prompts/P1c.md:8 stated the wave without the id 2c, and P1c.md:14-15 said P8 and P7b merge "before wave 3" while
  "Before you start" (:33-36) required them before P1c (format-FH-10 (1)). Sources: V-6, K-8. At e712310: settled
  (P1c.md:8 "Wave 2c", :14-15 "merge before P1b").
- inventory/artifact-map-d625284.tsv row A51 cites "PLAN-v2:773 says 12"; PLAN-v2's "12 consent readers" row was :773
  only at the planning commit 3ce5882, :771 at aaf072c and is :803 now. Proposed: cite it by name, as P1b row 9 does.
  Raised by round 3's structure verifier and repeated through round 10. At e712310: still open (the TSV's line 50).
- r5-structure-15: P1b.md cited P5.md:839 for the `blocked` rewrite in P5's retired list, which is P5.md:841. This work
  left P1b.md alone. At e712310: settled by that session in 787167e (P1b.md:714 cites P5.md:841).
- The settings_env/CLAUDE_HOME trap for G2, raised in round 5 (refuter r5x-arming): claude_home's `settings_env` returns
  nothing on a landed home whose overlay sets CLAUDE_HOME, so a run-time switch read through it misses G2's key there.
  At e712310: settled; P1b E4 at eef8a5c already took that case through P7b's function (now P1b.md:392-397), and round 5
  worded P2's G1/G3 read to match.
- Commits of that session newer than a round's baseline ("AFTER <baseline>"): the references they broke were fixed by
  this work in rounds 5-7, and the later ones broke none. At d347b2f P1b's citations into this work's files still land
  on their subjects (round 10's check re-read the ones its edits touched): P1b.md:286 (P4.md:697), :485 (P2.md:519),
  :487 (P2.md:322), :655-656 (PLAN-v2.md:133-134, :172, :174, :1199, :1311, :1329), :714 (P5.md:841), :715-716
  (PLAN-v2.md:1158; P5.md:265, :607, :753), :762 (P2.md:756) and :878 (P6.md:413-416); P1c's `plan:` citations are
  pinned to 3ce5882. Nothing else the rounds listed for that session is open.

## Left for the reviewer

Observations the sources report outside both lists that are still open at d347b2f; line numbers are at e712310, re-read
there, and hold at d347b2f (5a4e0a3 and d347b2f changed only PLAN-v2.md:423, :1158, :1353, prompts/P3.md:102, :299, :639
and prompts/P5.md:753). Not listed because they are fixed: what round 1 (fa5659d) fixed (D25 in PLAN-v2's precedence
lines and in the prompts' D20-D24 bullets, the P5 and P10 wave paragraphs, the HANDOVER.md and COVERAGE.md citations in
DECISIONS.md, the P3 reader credits in PLAN-v2 and P4's advisory sinks, the G2-hunk clause of PLAN-v2's P3 row, the
CLAUDE.md row's #1/#3, PLAN-v2's P3 arbitration grep, TC-56 and TC-57, the launcher wording at PLAN-v2.md:44 and :539,
the push dead end for a typed remote that is not the upstream, COVERAGE.md's waves sentence and P9's L-attributions),
and what later rounds fixed from this list as it stood at 686b375: STOPGATE's arming credited to P1c's X3, P4's wave
paragraph, PLAN-v2's UD-CM row, V-22's "prose-only changes need none" and DECISIONS.md D25 (2)'s "no human action"
beside the owner's /restart (round 2); the G2 failing-stop either/or in P2, P3 and PLAN-v2 (rounds 3-4); the push
predicate for HEAD strictly behind the tip (round 4); the P10 and P11 tail sentence, HANDOVER's 会问你 cells and the
corrections 2.82 prefix-row fallback for P5 row 1 (rounds 5-6); COVERAGE.md gap 7 (COVERAGE.md:3, round 7); and
PLAN-v2.md:1158 with P5's acceptance 13, which kept the /spec coverage phase's block after P1b correction 9 moved its
rule (round 10, 5a4e0a3 and d347b2f). P1b now settles one more: its row 7 respells commit.md :459, :486, :570 and :821's
`source venv/bin/activate` calls (P1b.md:762), which no P2 acceptance ran (R15-B).

- HANDOVER.md:1, :3 and :80 still say "8 个提示词". (H-1)
- COVERAGE-P9-P11.md:35-37 (P9, P10 and P11 dependency rows, a dated 2026-10-19 table) do not list P1b and P1c, and :35
  still credits `"CLAUDE_OBLIGATION_STOPGATE": "block"` to "P2 row 17" (P1b's E4 arms it). (R90-B, K-11; reviewer item
  25)
- COVERAGE-P9-P11.md:63 ("O4/O6 one producer per fact | P9 rows 1-6") names no P1b. (K-2)
- COVERAGE-P9-P11.md:76 ("B1-B9 (step 9 as in-place re-sync, D19)") is false now (P11 does no re-sync; B3, B6 and B7 are
  deleted), and "B1-B9" stands at :108 and :127. (R90-A)
- prompts/P5.md:342 (row 2) says "P3 row 6 removes their writer"; after R17 the writers sit in P3 rows 6 and 7, and P1b
  row 3 and P1c row 7 remove them first. Its check `git grep -n -e escalations/ -e escalation-admissions/ --
  hooks/subagentstop-artifact-contract-enforce.py` does not match the code's `cycle_dir / "escalations"` form. (R17-B,
  R67-B, P5-4)
- PLAN-v2.md:51 and :364 state the TC-45 deny's lift "on any human-typed prompt" without the [INFERRED scope] tag that
  R54 and R69 added elsewhere (:569 has it). (R69-A)
- PLAN-v2.md:892 (P11 goal tag) and prompts/P11.md:74-75 still say "acceptance 14 extended to" / "extending acceptance
  14", while DECISIONS.md D16 names acceptance 14's cases directly. (R5)
- PLAN-v2.md:1255 (section 13, P5 carry-over row) says "`/do <task-id>` re-grants it" without the TC-18 condition that
  :84, :350 and prompts/P5.md:556 carry. (R9)
- PLAN-v2.md:392 (P2 scratch-repo run still lists close.md Step 0, the QA-arming block and commit.md Step 5; P2.md
  records its deviation) and :453 ("after the re-dispatched BA writes a newer ticket and context", which R22 reverted in
  P3.md) differ from the prompts after the residual edits. (R15, R22-B)
- PLAN-v2.md:501 (P4 overnight-loop row) computes session_families() and runs the per-family disposition, and :1254
  (section 13, P4 row) lists "TC-13's `session_families()`", both unconditionally; P4.md makes the loop's print
  conditional. (R27)
- PLAN-v2.md:101, :348, :1067, :1077 (TC-11 rationale) and :1215 (Decision 10) still say "import-free launcher", while
  since round 8 the launcher loads lib/overnight.window_open and P1b row 18's reader module by path (P5 row 10,
  PLAN-v2.md:566). (R52, R68)
- PLAN-v2.md:841 ("CI enforces a size budget that only goes down."), :846 ("The size budget is measured after this
  cleanup.") and :861 (policies/size-budget.v1.json (new)) assume the budget file that P10's experiment 12 may drop.
  (R42)
- PLAN-v2.md:383 (P2 row) ends "(inside the window only /stop and off release, section 4)", and prompts/P5.md:240 says
  "only /stop and off release it" inside the D20 bullet, without the planner-proposal tag PLAN-v2.md:112 gives the off
  exit. (R57)
- DECISIONS.md:93-94 (D15: a registered hook file "becomes an exit-0 stub for one phase") against D19 and TC-37, where
  the stubs stay tracked. (R10-A)
- Pre-batch PLAN-v2 line numbers, already off at aaf072c: prompts/P10.md:291 ("PLAN-v2.md:947", U-E3b, now :984), :298
  (":825", P10's TC-35 row, now :857), :299 (":729", the D17 candidates row, now :757) and :307 (":1082", TC-53, now
  :1119); prompts/P11.md:499 ("PLAN-v2 :882", now :920), :684 ("section 5 :141", now :142; "section 11 :1158", now
  :1199) and :687 (":1158"). (R79-A, R45-A, R84-B; round 3's structure verifier)
- `\bblocked\b` in P9's acceptance 10 (prompts/P9.md:585) misses identifiers such as pipeline_blocked (expected tree
  agents/pm.md:659, :665; commands/dev-overnight.md:813, :815) and blocked_app_unavailable (agents/qa.md:811, :826).
  (R38-A, R38-B)
- P10 row 4's release-note residual (prompts/P10.md:357, :539) covers python files only, while R-f also stood in for
  shell files (bash on a missing file exits 127, a non-blocking hook error under D25(1)); whether a release-note
  residual meets D25(3) for a running session whose personal overlay names a deleted python PreToolUse hook is a design
  question. (R43-B)
- After P6 deletes the dev-registry FIRST ACTION lines, the kept SECOND ACTION prose that places its line "immediately
  after the dev-registry FIRST ACTION" (expected tree commands/dev-command.md:183, commands/dev-overnight.md:353) points
  at a deleted line. (R35-B)
- prompts/P8.md:494 still says P10 deletes such files "after doctor's per-home check (TC-37)" (P8 has run), and
  prompts/P7.md:267 keeps "Deleting hooks, stubs or dead installers" (P7's historical prompt). (R7-A, R8-B)
- prompts/P1.md:512 lists redev.md as P3's work, while P3 leaves it unchanged (R40-A); prompts/P1.md:307 still says
  "P5's import-free launcher will copy its tuples under a drift test", stale since round 8 (round 9's res-b verifier).
  P1 is a merged phase's prompt.
- Expected tree commands/redev.md:15 ("abort and ask the user to run `/dev` instead") is a text exit that only P9 row
  8's general rule covers; docs/reference/close-commit-zero-failure-mechanism-20260928.md:266 still names the withdrawn
  /redev resume route (register.md section 1.2 records it as superseded by D22). (R40-A, R40-B)
- PLAN-v1.md:202 and :285, landscape/00-INDEX.md:146 and landscape/A-gates-terminal.md:370 still carry the withdrawn
  D-A2-2 /redev resume text; PLAN-v1 is frozen and DECISIONS.md:3 and the prompts override them. (R91-A, R91-B)
- O19 is quoted with inner double quotes at prompts/P3.md:172 and prompts/P5.md:214, as register.md:111 has it, and with
  single inner quotes at DECISIONS.md:51. (R60-A)

NOT COUNTED items the round results list (rounds 3-9) that are still open at d347b2f, one line each. Each is older text
this work did not add, overridden by the prompt's "P1b and P1c" block, PLAN-v2's "After P1b and P1c" paragraph or
COVERAGE.md:3 unless the line says otherwise. Items the verifiers judged accurate as written, and items already listed
above, are not repeated.

- PLAN-v2.md:
  - :54 credits "ESCALATION_ACK ... releases nothing" to P3; P1b row 3 delivers it.
  - :106, :1144 and :1199 leave out P7b's net +60 lines (section 14, :1279).
  - :135, :353 and :368 have P2 arm "G1-G3"; P2 arms G1 and G3, and G2 is armed by P1b's E4 (else P1c's X3).
  - :272 and :1101 keep the TERMINAL_VOCABULARY/schema drift test that P1b rows 6 and 18 delete.
  - :442 says "The G2 escalation-record stores are removed here"; the P3 paragraph at :423 makes that verify-only.
  - :566 and :1077 size the launcher at "about 40 lines", P5 row 10 at "about 50 lines".
  - :571's "after step i went in_progress" (P5 row) is governed by :536.
  - :589 and :1070 grep for D4c only in command_span.py and stop_contract.py, not in the reader's module (round 8).
  - :803 "the 12 consent readers"; P1b row 9 counts eleven hooks with thirteen read sites.
  - :1042 and :1049 have P9 delete lifecycle-baseline-import.sh among "the four scripts"; P1b row 15 deletes it.
  - :1092 cites prompt-workflow.py:1427 (PLAN-v2's base 54393f8); it is :1425 at f8c18c2 and d625284.
  - :1144's list of new files leaves out the tracked GATED/CONTROL JSON of P5 row 10.
  - Section 13 rows :1237, :1252-1254, :1256 and :1264 send P1b/P1c deliveries to P2-P5 (dated PR records; item 24).
  - :1276, like the X8 quotes in prompts P2-P6, P7b and P9-P11, ends with "。", which register X8 does not have.
- prompts/P2.md and P3.md:
  - P2's title, :5, :15 and Goal 7 (:157), and P3.md:7 and :15-16 say P2 arms "G1-G3".
  - P2.md:494 lists close.md :246-251 among the respelling sites; P1b row 1 deletes that block first.
  - P2.md:186 (D24 bullet), row 4 and acceptance 5 make the lane hook the aggregate's only producer; E5 may take (b).
  - P2 acceptance 19 (:872) lists artifacts P1b already removed (harness-report.json, continuation sentinel, ...).
  - P2 row 14 (:332) leaves `_complete_todos` to P5; P1b row 2 (E7) deletes break-overnight-lock.py's todos write.
  - P2.md:449 ("A contract the old prose already wrote ...") describes the cycle contract P1b E13 now delivers.
  - P3.md:296-297 (row 11) cites ENFORCED_AGENT_TYPES :31, which P1b row 18 deletes (reviewer item 6).
  - P3's retired list (:365-367) counts G2's escalation stores and the ESCALATION_ACK admission P1b row 3 retires.
- prompts/P4.md:
  - :524 (Out of scope) still calls the declaring-dispatch reader P3's work (P1b E3's).
  - Row 9 (:304) keeps sinks whose writes P1b row 3 and E12 deleted; "Net code cap" (:766) credits them.
  - Row 3 (:298) deletes "the 1b still-missing finding", which P1b row 10 deletes too.
  - Row 4 (:299) and :211 keep two audit-line writes that inventory A98 lists as written and never read.
  - :379-383 `append_rating` reads the score log beside P1b row 15's one reading function for it.
- prompts/P5.md:
  - Row 11 (:352): "use the name P3 merged" for the reader (the block names P1b's E3).
  - Row 13 (:354) and the retired list (:845): "/stop's todo force-complete", which P1b row 2 (E7) deletes.
  - Row 14 (:355): push.md Step 1's "no push-gate token" abort, a scan P1b row 11 removed.
  - Retired list (:840): "stop-obligation-gate (G4's terminal re-check)", which P1b row 3 stubbed.
  - S9 (:274) "[pending, completed]", :292 and acceptance 21 (:795) "a pending skeleton", row 15 (:356).
- prompts/P6.md:
  - :118 says journal-view "was deleted by P3 row 7" (P1b row 6).
  - Row 9 (:356), :321-329, :428 and :636 keep /tmp/agentic-commit/ paths that P1b row 12 moves.
  - Row 3 (:350) cites obligation.ROLES and ENFORCED_AGENT_TYPES, which P1b row 18 deletes (reviewer item 6).
  - :66 "any G2 escalation records P3 left" (P1b row 3, P1c row 7 remove them).
  - Row 1 (:348) cites `_metadata_by_tool_use` as :525-548; it ends at :549 (inventory A120).
- prompts/P9.md:
  - Row 8 (:476): overnight-status.sh "prints the state with no time computation"; P1b row 13 adds the window verdict.
  - Row 5 (:473) and :425 locate CP_AGENTS readers that P1b rows 1 and 18 delete.
  - Acceptance 11 (:598) holds only if P1b row 15's score-log reader does not name lifecycle.jsonl.
- prompts/P10.md:
  - Row 7 (:360) keeps the drift test P1b deletes; row 3 (:356) cites the timelock phase P5 deletes.
  - Row 19 (:372): "the bulk-commit chain once P4 removes --bulk's entry", while P4 keeps /commit --bulk (D15).
  - Row 6 (:359) lists scripts/session-resources.py as a D17 candidate; P1b row 15 runs it.
- Start checks (reviewer item 17): the prompts' merge-title checks expect `P8: …`-style titles, while 2acc29b and
  301d696 read "P8, …" and "P7b, …" (P1c.md:31-37 spells out both forms); P2.md:82, P3.md:82, P4.md:46, P5.md:59,
  P6.md:49 and P10.md:48 "stop and tell the owner" when a check fails (P1c tells the reviewer).
- HANDOVER.md:
  - :11 "没合并它就停下来告诉你" (the prompts tell the reviewer).
  - :16 and :18: the P7b and P8 rows' 会问你 cells still read 问题 1 and 问题 2, answered on 2026-10-19 (:37).
  - :71 (question 11) still offers a veto ("你可以否决") that D18 replaced.
  - :106 and :108 (the 2026-10-22 section): P8 under review and /pull unsafe; P8 and P7b have merged.
- COVERAGE.md:
  - C4 (:128) and fix 3 (:213-220): P4 deletes the three advisory sinks; P1b row 3 and E12 delete their writes first.
  - :247 (fix 9): "the coordinator's timelock-fallback rule the launcher copies"; since round 8 it is never copied.
  - :71 (O44): the live-landing acceptances listed name none of P1b's or P1c's.
- Dated inputs (by design): COVERAGE.md sections (b)-(d) cite the prompts of 2026-10-18; COVERAGE-P9-P11.md those of
  2026-10-19 (its :3-5 `cmp` claim and "D1-D19" included); audit/2026-10-23/ and P1c's `plan:` citations cite 3ce5882.

MINOR items of round 10 (r10-res, r10-plan, r10-prompts, r10-quotes-structure and the check of round 10's edits), one
line each: recorded for the reviewer, not fixed (round 10's bar, "Method"). Those 5a4e0a3 or d347b2f fixed, and those
already listed above, are left out; most follow P1b commits merged in e712310.

- PLAN-v2.md:
  - :1176 counts "43 / 52 / 26 / 24 of 120"; inventory/README.md now gives 43 / 56 / 29 / 24 of 121 (A125).
  - :357's "Delivered before P2" list does not name P1b row 13's deletion of closeout's pending-required-calls block.
  - :446 and :458 still credit the four profile exemptions to gitignore-preflight; :423 now puts them in G3's admission.
  - TC-41 (:1107) lists "/spec exempt"; P1b row 18 reads it from the declaration and row 8 gives /spec an obligation.
  - :536 says P1c row 17 pairs each todo in the subagent-call recorder; P1b row 2 now deletes that pairing.
- prompts/P2.md:
  - Row 9 (:327) "drop it or keep it (D10)" and :585: P1b row 13 already deletes the pending-required-calls block.
  - Row 14 (:332, `IMMUTABLE_FIELDS`): P1b E13 says nothing runs update-overnight-state.sh ("Already done" covers it).
  - :42-68 ("Files you share with P3") omit hooks/pretool-gitignore-preflight.py; the second-to-merge rule covers it.
- prompts/P3.md:
  - Goal 5 (:148) still says the four profiles are exempt "by gitignore preflight"; row 13 now puts them in G3.
  - :640: the sentence after acceptance 11's cases describes only the preflight's run, not G3's.
  - :490 keeps scripts/close-commit-repair-orchestrate.py, which P1b E3 now deletes.
- prompts/P4.md:
  - :348-350: commit.md:249's "bulk capability absent" wait is gone at P4's base (P1b row 11).
  - :334-337: the late-repair route re-runs verify-disclosure; P1b row 6 moves that rule into finalize.
- prompts/P5.md:
  - :115: row 20's step lookups in posttool-subagent-track; P1b row 2 removes that step pairing.
  - :265 ("the coverage phase for /spec ... keep working") and :607 ("unchanged"): since P1b row 8 the phase is a stub.
- prompts/P10.md:
  - :57's list of P1b's stubs omits stop-spec-coverage-enforce.py; its general rule still finds it.
  - Row 6 (:359) lists the repair-map scripts and schema P1b E3 deletes, and update-overnight-state.sh's options.

- reviews/D20-D25-reviewer-findings-on-A.md (4cc52aa): the reviewer session's review of 86b7cbc and c728380, written at
  c728380, 43 findings its refuters kept, grouped as items 1-26, checked as claims in rounds 5-9 (round 10 found none
  reopened). At d347b2f:
  - Fixed: 1-5, 7-11, 13, 14, 16, 18 and 20-23, and the parts of 6, 12, 24 and 25 not named below. Rounds 1-4 had fixed
    many of them before the file arrived, often in other words; rounds 5-9 fixed 2 (P4's /close or /commit dead end), 3
    (P4's and P3's pending do-report), 7 (the /do sidecar dead end), 8 (the D8 bracket's deny half, the start checks),
    11 (the prefix-row fallback), 12 (HANDOVER's 会问你 cells, :7, :37), 13's P2 and P6 parts, 18 (preambles, P9, the P10
    and P11 tails), 20 (the route in round 7, its replays in rounds 8-9), 21 and 22, and fixed 16 and 23 again after P1c
    changed X8.
  - Judged wrong: 15 (P1b E14 keeps /commit Step 8's selection and continuation, prompts/P4.md:86-87; the opposite
    defect was fixed in round 5); 19 (the Stop gate is the main agent's own stop and carries no rule of its own, P1b
    goal 3); 26 (the five prompt quotes are one contiguous verbatim run of DECISIONS.md:70 without its leading words, as
    DECISIONS.md itself quotes at :51 and :74); and item 20's proposed "dev when none" route (P1b E3 and row 10 forbid a
    default role).
  - Open as older text (listed above): 6's P6 row 3 and P3.md:297; 12's HANDOVER.md:1, :3, :106 and :108; 17 (its
    byte-identity note was judged not needed); 24's other section-13 rows; 25's optional COVERAGE-P9-P11.md:35-37.
- 686b375 (the merge of the P1b/P1c session's 2e7d4c0..0cbfbd3) has git's default merge message without the attribution
  lines this work's other commits carry; it was already pushed when noticed and was not amended (no history rewrite).
- Commit trailers: every other commit of this work ends with the attribution lines the task requires; their
  Co-Authored-By line names an AI model (rounds 6-9's quotes verifiers noted it). It is commit metadata, not a line in
  harness-repair-plan/.
