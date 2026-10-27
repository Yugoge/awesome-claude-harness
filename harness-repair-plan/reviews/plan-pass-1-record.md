# Plan pass 1: record

First pass over the items two earlier sessions left for the plan files: it applies every item whose fix is right
whatever P1b's pull request ends up doing, and hands the rest to the second pass, which runs after P1b merges.

- Branch `claude/vibrant-hopper-bazrn8`, started at 3b5c825. Commits of this pass: 1740054 (PLAN-v2.md and the sync
  file), 92bff83 (the shared tail), 22fc8f0 (the bodies of prompts P2-P6 and P9-P11), d4a4e88 (DECISIONS.md,
  HANDOVER.md, COVERAGE.md, COVERAGE-P9-P11.md, README.md), then this record.
- Source 1: reviews/P1b-P1c-findings-record.md, section "For the plan files" (:1356-4977 at 3b5c825): 119 pending items
  with exact old and new texts, anchored at ef34dbc. Its applied, superseded and not-carried items are left alone.
- Source 2: reviews/D20-D25-residuals-and-sync-record.md, section "Left for the reviewer" (:1007 to the end): the open
  list, the "NOT COUNTED" list and the "MINOR" list, one line each, with no fix text. Ids below: R2-01 to R2-23 are
  the open list in order (:1025-1084), R2-24 to R2-26 the three closing notes (:1184-1204), NC-01 to NC-53 the NOT
  COUNTED bullets in order (:1092-1154; the start-checks bullet carries NC-44, merge titles, and NC-45, "tell the
  owner"), MN-01 to MN-17 the MINOR bullets in order (:1161-1182). R2-02, R2-09 and NC-41 name two defects each and
  are split into a and b. The section's opening paragraph lists what earlier rounds fixed and one more item P1b
  settles (commit.md's `source venv/bin/activate` calls); neither is an item.

## Summary

| Source | Entries | Now, applied | Now, already applied | Now, not applied | After P1b |
|---|---|---|---|---|---|
| Source 1 (findings record) | 119 | 31 | 0 | 3 | 85 |
| Source 2 (residuals record) | 99 | 30 | 0 | 8 | 61 |
| Total | 218 | 61 | 0 | 11 | 146 |

- Now, applied: every Now item's defect was still present, so none counts as already applied. MN-01 and NC-45 are the
  same edits as PV-14 and the six "tell the reviewer" items of Source 1; NC-14 and NC-44 each edit several files.
- Now, not applied (with reason): the prompts of merged phases (F-P7b-01, F-P8-01, R2-19, R2-20), audit/ (FD-17),
  PLAN-v1.md and landscape/ (R2-22), an owner ruling's text (R2-14, D15), a dated input kept by design (NC-53), and
  three notes with nothing to edit in the plan files (R2-24 to R2-26).
- After P1b: 146 entries, 85 with the findings record's fix texts and 61 with the residuals record's defect lines (no
  fix text exists for them); 13 of the 61 repeat a Source 1 entry and say so. Three Source 1 entries have lost their
  old text to commits made after ef34dbc: PV-21 (PLAN-v2.md:1158) and L-P5-04 (P5.md:753) are carried in substance
  since 5a4e0a3/d347b2f, and PV-20's bullet (now PLAN-v2.md:1347-1350) gained P1b's correction 9 in d347b2f. The second
  pass checks those three against P1b as merged.

## How the items were sorted and applied

- **Now**: the fix is right whatever P1b's PR does: a stale count or line number, a "tell the owner" where the prompts
  now tell the reviewer, an owner quote made verbatim, a dated row that no longer holds for a reason other than P1b, a
  HANDOVER cell answered long ago, a P5, P10 or P11 rule unrelated to P1b's work. **After P1b**: the fix states what
  P1b or P1c delivers, deletes, moves, keeps or arms, depends on a choice inside P1b (E4's arming with P1c's X3
  fallback, E5's candidates, E8, E13, E14), or cites code lines P1b changes; when unsure, After P1b. A prompt's mere
  mention of P1b and P1c among the merges it waits for does not make an item After P1b.
- Source 1 items were found by their old text (each occurred exactly once) and replaced by the record's new text,
  taken from the record file itself, not retyped. Four D25-quote items (F-P3-02, F-P4-03, F-P5-03, F-P6-03) keep the
  record's words but stay on one line (at most 117 characters; the record's new text wraps them onto two), so that no
  line after them moves: P1b.md cites P4.md:697, P5.md:265, :607, :753, :841 and P6.md:413-416.
- Source 2 items got the smallest edit that fixes the stated defect. Table rows and one-line bullets stay one line;
  wrapped bullets were re-wrapped within their own line count, except P10's start check, which gained one line (no
  plan file cites a P10 line number).
- Shared tail: `prompts/_common.md` took F-C-01 to F-C-05; the new tail was copied byte for byte into P1c.md (its tail
  only), P2-P6 and P9. P10 and P11 took the same five changes by hand: their tails carry one more sentence (the
  D20-D25 precedence, fixed there in rounds 5-6 of the residuals work), which a byte-for-byte copy would have
  deleted; their tails now equal the new `_common.md` plus that sentence, as before. The prompts of started or merged
  phases keep older tails: P0 and P7 (older forms), P1, P1b, P7b and P8 (the previous `_common.md`).
- First lines: P1b.md and P1c.md start with "Owner steps: none."; P1c.md keeps it. P2-P6 and P9-P11 have never started
  with it (their first line is the phase heading, and they place "Owner steps: none." in the PR body); no item adds
  it, and their first lines are unchanged.

## Items, one line each

### Source 1 (reviews/P1b-P1c-findings-record.md, "For the plan files")

Line numbers in the last column are at this pass's HEAD.

| Id | Set | Reason | Edit or state |
|---|---|---|---|
| PV-1 | After P1b | G2's arming is P1b's E4, else P1c's X3 (an arming choice inside P1b with P1c's fallback) | handed on; old text at PLAN-v2.md:135 |
| PV-2 | After P1b | G2's arming is P1b's E4, else P1c's X3 (an arming choice inside P1b with P1c's fallback) | handed on; old text at PLAN-v2.md:353 |
| PV-3 | After P1b | G2's arming is P1b's E4, else P1c's X3 (an arming choice inside P1b with P1c's fallback); P1b's kept consumer-side copies | handed on; old text at PLAN-v2.md:368 |
| PV-5 | After P1b | P1b E3 deletes the routing tables' prose copies | handed on; old text at PLAN-v2.md:474 |
| PV-9 | After P1b | G2's arming is P1b's E4, else P1c's X3 (an arming choice inside P1b with P1c's fallback) | handed on; old text at PLAN-v2.md:704 |
| PV-10 | After P1b | P1b E14 (the spec monolith's one writer) | handed on; old text at PLAN-v2.md:784 |
| PV-11 | After P1b | P1b E14 | handed on; old text at PLAN-v2.md:800 |
| PV-13 | After P1b | P1b correction 8 records it; at PLAN-v2's stated base 09ab15b (README.md:9) the print is at :1427, at f8c18c2 and d625284 at :1425 | handed on; old text at PLAN-v2.md:1092 |
| PV-21 | After P1b | P1b row 8 | handed on; old text gone: 5a4e0a3/d347b2f rewrote PLAN-v2.md:1158, which carries the item in substance |
| PV-14 | Now, applied | stale count: the figure is the committed inventory/README.md:17-24, whatever P1b's PR does | applied as recorded, PLAN-v2.md:1176 |
| PV-15 | After P1b | P1b E3 ships the deny (P5-a's share is P1b's PR's call) | handed on; old text at PLAN-v2.md:1192 |
| PV-16 | After P1b | P1b row 7 respells the resolver calls it keeps | handed on; old text at PLAN-v2.md:1250 |
| PV-17 | After P1b | P1b row 1 deletes /close's QA arming | handed on; old text at PLAN-v2.md:1260 |
| PV-18 | After P1b | restates P1b's "Corrections to PLAN-v2" item 2; coupled with P1b.md:655's :1329 | handed on; old text at PLAN-v2.md:1318-1328 |
| PV-19 | Now, applied | section 15 repeats what P9's CLAUDE.md row (PLAN-v2.md:813) carries; no P1b dependency | applied as recorded: PLAN-v2.md:1347-1349 deleted (3 lines; nothing cites the lines after them) |
| PV-20 | After P1b | restates P1b's own corrections 3-9 | handed on; old text gone: d347b2f appended correction 9 to the bullet, now PLAN-v2.md:1347-1350 |
| S1 | After P1b | announces P9-11 to P9-14, which S37 adds (P1b row 15) | handed on; old text at reviews/P1b-plan-sync.md:5 |
| S2 | Now, applied | prompts/P1b.md and P1c.md already say D25 (7 times each) | applied as recorded, sync :31-32 |
| S3 | Now, applied | quote: D25's full sentence; the forwarded reply is the reviewer's | applied as recorded, sync :36-41 (4 lines -> 6) |
| S4 | Now, applied | DECISIONS.md:86-87 states it | applied as recorded, sync :59 |
| S13 | After P1b | P1b E14 (as PV-10) | handed on; old text at reviews/P1b-plan-sync.md:304 |
| S16 | Now, applied | stale count (as PV-14) | applied as recorded, sync :421 |
| S25 | Now, applied | quote: D25's full sentence | applied as recorded, sync :915-923 |
| S28 | Now, applied | quote: D25's full sentence | applied as recorded, sync :1020-1028 |
| S29 | Now, applied | quote: D25's full sentence | applied as recorded, sync :1111-1114 |
| S31 | Now, applied | quote: D25's full sentence | applied as recorded, sync :1200-1202 |
| S33 | Now, applied | quote: D25's full sentence | applied as recorded, sync :1290-1293 |
| S35 | After P1b | P1b row 15 | handed on; old text at reviews/P1b-plan-sync.md:1325 |
| S37 | After P1b | P1b row 15 | handed on; old text at reviews/P1b-plan-sync.md:1466-1467 |
| S38 | After P1b | P1b row 15 | handed on; old text at reviews/P1b-plan-sync.md:1620-1628 |
| F-C-01 | Now, applied | "tell the owner" where the prompts now tell the reviewer | applied as recorded to _common.md; tail copied |
| F-C-02 | Now, applied | the attribution trailers; no P1b dependency | applied as recorded; tail copied |
| F-C-03 | Now, applied | dated CI paragraph that no longer holds: P8 merged (2acc29b, green CI) | applied as recorded; tail copied |
| F-C-04 | Now, applied | GitHub's body limit; no P1b dependency (optional) | applied as recorded; tail copied |
| F-C-05 | Now, applied | CI is green since P8 | applied as recorded; tail copied |
| F-P2-01 | After P1b | G2's arming is P1b's E4, else P1c's X3 (an arming choice inside P1b with P1c's fallback) | handed on; old text at prompts/P2.md:1 |
| F-P2-02 | After P1b | G2's arming is P1b's E4, else P1c's X3 (an arming choice inside P1b with P1c's fallback) | handed on; old text at prompts/P2.md:5 |
| F-P2-03 | After P1b | G2's arming is P1b's E4, else P1c's X3 (an arming choice inside P1b with P1c's fallback) | handed on; old text at prompts/P2.md:15 |
| F-P2-04 | Now, applied | "tell the owner" -> the reviewer | applied as recorded, P2.md:82-83 |
| F-P2-05 | Now, applied | quote: D25's full sentence | applied as recorded, P2.md:92-93 |
| F-P2-07 | After P1b | P1b E13's deletions and /stop's write path | handed on; old text at prompts/P2.md:112 |
| F-P2-10 | After P1b | G2's arming is P1b's E4, else P1c's X3 (an arming choice inside P1b with P1c's fallback) | handed on; old text at prompts/P2.md:157-158 |
| F-P2-12 | After P1b | P1b E5's one aggregate producer | handed on; old text at prompts/P2.md:186-187 |
| F-P2-14 | After P1b | P1b E5's candidates | handed on; old text at prompts/P2.md:322 |
| F-P2-15 | After P1b | P1b E5's candidates | handed on; old text at prompts/P2.md:322 |
| F-P2-16 | After P1b | P1b E5's candidates | handed on; old text at prompts/P2.md:322 |
| L-P2-03 | After P1b | P1b row 13 | handed on; old text at prompts/P2.md:327 |
| L-P2-04 | After P1b | P1b row 13 | handed on; old text at prompts/P2.md:327 |
| F-P2-18 | After P1b | P1b E13's write path | handed on; old text at prompts/P2.md:332 |
| F-P2-20 | After P1b | G2's arming is P1b's E4, else P1c's X3 (an arming choice inside P1b with P1c's fallback) | handed on; old text at prompts/P2.md:335 |
| L-P2-02 | After P1b | P1b row 13 | handed on; old text at prompts/P2.md:380-383 |
| F-P2-21 | After P1b | P1c X8's wake | handed on; old text at prompts/P2.md:472-474 |
| F-P2-22 | After P1b | G2's arming is P1b's E4, else P1c's X3 (an arming choice inside P1b with P1c's fallback); P1b's kept copies | handed on; old text at prompts/P2.md:558-559 |
| L-P2-05 | After P1b | P1b row 13 | handed on; old text at prompts/P2.md:585 |
| F-P2-23 | After P1b | P1b E5's candidates | handed on; old text at prompts/P2.md:775-776 |
| F-P2-24 | After P1b | P1b row 1, E7 and acceptance 17 | handed on; old text at prompts/P2.md:777-778 |
| F-P2-25 | After P1b | P1c X8's wake | handed on; old text at prompts/P2.md:785 |
| F-P2-26 | After P1b | P1c X8's wake | handed on; old text at prompts/P2.md:802-804 |
| F-P2-27 | After P1b | P1b's D24 table | handed on; old text at prompts/P2.md:871-872 |
| F-P3-01 | Now, applied | "tell the owner" -> the reviewer | applied as recorded, P3.md:82-83 |
| F-P3-02 | Now, applied | quote: D25's full sentence | applied with the record's words on one line (117 characters), P3.md:92: the record's new wraps it onto two |
| F-P3-04 | After P1b | P1b E3's reader | handed on; old text at prompts/P3.md:288 |
| L-P3-01 | After P1b | P1b E3 deletes the script | handed on; old text at prompts/P3.md:490 |
| F-P3-07 | After P1b | P1b's D24 table | handed on; old text at prompts/P3.md:691-695 |
| F-P4-02 | Now, applied | "tell the owner" -> the reviewer | applied as recorded, P4.md:46-47 |
| F-P4-03 | Now, applied | quote: D25's full sentence | applied with the record's words on one line, P4.md:74, so P1b.md's cite P4.md:697 keeps its line |
| F-P4-11 | After P1b | P1b E5's candidates | handed on; old text at prompts/P4.md:296 |
| F-P4-12 | After P1b | what P1b E3 leaves | handed on; old text at prompts/P4.md:297 |
| F-P4-13 | After P1b | what P1b E3 leaves | handed on; old text at prompts/P4.md:300 |
| L-P4-04 | After P1b | P1b row 6 | handed on; old text at prompts/P4.md:306 |
| L-P4-03 | After P1b | P1b row 6 | handed on; old text at prompts/P4.md:337 |
| F-P4-14 | After P1b | P1b row 15 | handed on; old text at prompts/P4.md:530-532 |
| F-P4-15 | After P1b | P1c's F8 replays | handed on; old text at prompts/P4.md:623 |
| F-P4-17 | After P1b | P1c's F8p | handed on; old text at prompts/P4.md:639 |
| F-P5-02 | Now, applied | "tell the owner" -> the reviewer | applied as recorded, P5.md:59-60 |
| F-P5-03 | Now, applied | quote: D25's full sentence | applied with the record's words on one line, P5.md:89, so P1b.md's cites P5.md:265, :607, :753 and :841 keep their lines |
| L-P5-01 | After P1b | P1b row 8's stub | handed on; old text at prompts/P5.md:265 |
| L-P5-02 | After P1b | P1b row 8's stub | handed on; old text at prompts/P5.md:350 |
| F-P5-11 | After P1b | P1b E8 candidate (b) | handed on; old text at prompts/P5.md:362 |
| L-P5-03 | After P1b | P1b row 8's stub | handed on; old text at prompts/P5.md:607 |
| F-P5-15 | After P1b | P1c X8's wake | handed on; old text at prompts/P5.md:747-749 |
| L-P5-04 | After P1b | P1b row 8's stub | handed on; old text gone: d347b2f rewrote P5.md:753, which carries the item in substance |
| F-P6-01 | Now, applied | "tell the owner" -> the reviewer | applied as recorded, P6.md:49-50 |
| F-P6-02 | After P1b | P1b row 3 and P1c row 7 remove the stores | handed on; old text at prompts/P6.md:66-68 |
| F-P6-03 | Now, applied | quote: D25's full sentence | applied with the record's words on one line, P6.md:83, so P1b.md's cite P6.md:413-416 keeps its lines |
| F-P6-05 | After P1b | P1b row 18 | handed on; old text at prompts/P6.md:350 |
| L-P6-01 | After P1b | P1b row 8's cp-state choice (the item is conditional on it) | handed on; old text at prompts/P6.md:417-418 |
| F-P6-06 | After P1b | P1b row 1 deletes /close's QA arming | handed on; old text at prompts/P6.md:510-512 |
| F-P6-07a | After P1b | names P1c's fault id F3a, which P1c's PR fixes | handed on; old text at prompts/P6.md:760 |
| F-P7b-01 | Now, not applied | "tell the owner" -> the reviewer | not applied: P7b is a merged phase, whose prompt this pass may not edit |
| F-P8-01 | Now, not applied | "tell the owner" -> the reviewer | not applied: P8 is a merged phase, whose prompt this pass may not edit |
| F-P9-01 | Now, applied | an unquoted owner claim; no P1b dependency | applied as recorded, P9.md:18-19 |
| F-P9-02 | After P1b | P1b row 15 | handed on; old text at prompts/P9.md:124 |
| F-P9-03 | After P1b | P1b row 15 | handed on; old text at prompts/P9.md:212-214 |
| F-P9-04 | After P1b | P1b row 15 | handed on; old text at prompts/P9.md:242 |
| F-P9-05 | After P1b | P1b row 15 | handed on; old text at prompts/P9.md:385 |
| L-P9-01 | After P1b | P1b row 15's score-log function | handed on; old text at prompts/P9.md:448 |
| F-P9-10 | After P1b | P1b E14 | handed on; old text at prompts/P9.md:469 |
| F-P9-11 | After P1b | P1b row 15 | handed on; old text at prompts/P9.md:471 |
| F-P9-12 | After P1b | P1b row 15 | handed on; old text at prompts/P9.md:471 |
| L-P9-02 | After P1b | a code cite into `_init_dev_registry`, whose roster P1b rows 1 and 18 change | handed on; old text at prompts/P9.md:473 |
| F-P9-13 | After P1b | P1b row 1 | handed on; old text at prompts/P9.md:473 |
| F-P9-14 | After P1b | P1b row 16 (coupled with F-P9-15) | handed on; old text at prompts/P9.md:476 |
| F-P9-15 | After P1b | P1b row 16 | handed on; old text at prompts/P9.md:476 |
| F-P9-16 | After P1b | P1b row 1 | handed on; old text at prompts/P9.md:476 |
| F-P9-17 | After P1b | P1b row 16 | handed on; old text at prompts/P9.md:476 |
| F-P9-18 | After P1b | P1b row 15 | handed on; old text at prompts/P9.md:478 |
| F-P9-19 | After P1b | P1b row 15 | handed on; old text at prompts/P9.md:509-510 |
| F-P9-22 | After P1b | P1b E3 deletes the tables' prose copies | handed on; old text at prompts/P9.md:661 |
| F-P9-23 | After P1b | P1b E3 deletes the tables' prose copies | handed on; old text at prompts/P9.md:661 |
| F-P9-25 | After P1b | P1b row 15 | handed on; old text at prompts/P9.md:699-701 |
| F-P10-01 | Now, applied | "tell the owner" -> the reviewer | applied as recorded, P10.md:48-49 (now :49-50) |
| L-P10-01 | After P1b | P1b E3 | handed on; old text at prompts/P10.md:360 |
| F-P10-03 | After P1b | P1b's TERMINAL_VOCABULARY | handed on; old text at prompts/P10.md:361 |
| FD-7 | Now, applied | records a fact nobody is asked about (D18, D19); no P1b dependency | applied as recorded, COVERAGE.md:282-284 |
| FD-11 | After P1b | credits P1c's F8 faults | handed on; old text at COVERAGE.md:312 |
| FD-15 | Now, applied | index row; no P1b dependency | applied as recorded, README.md:9 |
| FD-16 | Now, applied | index rows; no P1b dependency | applied as recorded, README.md:14-17 |
| FD-17 | Now, not applied | pins the register's `plan:` citations | not applied: audit/ is outside the files this pass may edit |

### Source 2 (reviews/D20-D25-residuals-and-sync-record.md, "Left for the reviewer")

Line numbers in the last column are at this pass's HEAD.

| Id | Set | Reason | Edit or state |
|---|---|---|---|
| R2-01 | Now, applied | stale count | HANDOVER.md:1 and :80; :3-5 re-wrapped on three lines, naming the 13 prompts and which tails are byte-identical |
| R2-02a | Now, applied | merge order fixed by DECISIONS.md (Execution) and the prompts' start checks | COVERAGE-P9-P11.md:35-37: P1b and P1c added to "Must be merged first" |
| R2-02b | After P1b | :35's STOPGATE credit is P1b's E4, else P1c's X3 | handed on |
| R2-03 | After P1b | credits P1b's D24 work (K-2) | handed on |
| R2-04 | Now, applied | P11 only | COVERAGE-P9-P11.md:76 (steps 1-8 and the pre-push guard; B3, B6, B7 deleted, no re-sync), :108, :127 |
| R2-05 | After P1b | P1b row 3 and P1c row 7 remove the writers first | handed on |
| R2-06 | Now, applied | the tag :569 carries | PLAN-v2.md:51 and :364 carry "[INFERRED scope from D20; decided by the P2 TC-45 deny replay]" |
| R2-07 | Now, applied | P11 only; DECISIONS.md D16 names the cases | PLAN-v2.md:892 and prompts/P11.md:74-75 name acceptance 14's cases |
| R2-08 | Now, applied | the TC-18 condition :84 and :350 carry | PLAN-v2.md:1255 |
| R2-09a | After P1b | :392's list depends on what P1b's PR leaves of close.md Step 0, the QA-arming block and commit.md Step 5 (P2.md:505-507) | handed on |
| R2-09b | Now, applied | P3's own text (R22) | PLAN-v2.md:453: "after a newer ticket and context" |
| R2-10 | Now, applied | P4's own condition | PLAN-v2.md:501 (the per-family run happens only for the print) and :1254 |
| R2-11 | Now, applied | the launcher loads lib/overnight.window_open by path whatever P1b does | PLAN-v2.md:101, :348, :1067, :1077, :1215: "import-free" replaced by what the launcher imports; no P1b row named |
| R2-12 | Now, applied | P10's experiment 12 | PLAN-v2.md:841, :846, :861 |
| R2-13 | Now, applied | the planner-proposal tag of PLAN-v2.md:112 | PLAN-v2.md:383; prompts/P5.md:240 (lines 240-243 re-wrapped, same count) |
| R2-14 | Now, not applied | D15 is the owner's recorded decision | not applied: an owner ruling's text; the findings record's "Not carried" item 3 keeps it; P10 (TC-37, D19) states the stubs' fate |
| R2-15 | Now, applied | stale plan-file line numbers | P10.md:292, :299, :300, :308 (numbers at HEAD) -> :984, :857, :757, :1119; P11.md:499, :684, :687 -> :920, :142 and :1199, :1199 |
| R2-16 | Now, applied | regex gap; no P1b dependency | prompts/P9.md:585 and :589: `(\b\|_)blocked` in place of `\bblocked\b` |
| R2-17 | Now, applied | shell hooks are deleted by row 4 too | P10.md:358 (row 4) and :540-541 (bullet :538-541 re-wrapped): "python or shell hook", bash exits 127; the D25(3) design question is under "Found, not fixed" |
| R2-18 | After P1b | depends on P1b row 1's registry sentinels and P6's options (unsure) | handed on |
| R2-19 | Now, not applied | merged phases | not applied: prompts/P8.md and P7.md |
| R2-20 | Now, not applied | merged phase | not applied: prompts/P1.md |
| R2-21 | Now, applied | D22; no P1b dependency | prompts/P9.md:476 (row 8): redev.md :15 named as a text exit; the design doc's :266 (the withdrawn /redev route) named; "(two lines)" -> "(three lines)" |
| R2-22 | Now, not applied | frozen records | not applied: PLAN-v1.md and landscape/ are outside the files this pass may edit |
| R2-23 | Now, applied | quote punctuation | DECISIONS.md:51 uses the register's inner double quotes |
| R2-24 | Now, not applied | status of the 4cc52aa review | no edit of its own: its open parts are R2-01 (item 12), NC-21 and NC-35 (item 6), NC-44 (item 17), NC-13 (item 24), R2-02 (item 25) |
| R2-25 | Now, not applied | a pushed merge message | not applied: no history rewrite |
| R2-26 | Now, not applied | commit metadata | not applied: not a line in harness-repair-plan/ |
| NC-01 | After P1b | P1b row 3 | handed on |
| NC-02 | Now, applied | P7b's merged cap (prompts/P7b.md:623) | PLAN-v2.md:106, :1144, :1199 |
| NC-03 | After P1b | G2's arming is P1b's E4, else P1c's X3 (an arming choice inside P1b with P1c's fallback) | handed on (same defect as PV-1 to PV-3) |
| NC-04 | After P1b | P1b rows 6 and 18 | handed on |
| NC-05 | After P1b | P1b row 3 | handed on |
| NC-06 | Now, applied | P5 row 10's size | PLAN-v2.md:566 and :1077: about 50 lines |
| NC-07 | After P1b | governed by :536's P1c row 17 paragraph | handed on |
| NC-08 | After P1b | the reader's module is P1b row 18's | handed on |
| NC-09 | After P1b | P1b row 9 | handed on |
| NC-10 | After P1b | P1b row 15 | handed on |
| NC-11 | After P1b | P1b correction 8 | handed on (same as PV-13) |
| NC-12 | Now, applied | P5 row 10 | PLAN-v2.md:1144 |
| NC-13 | After P1b | P1b/P1c deliveries | handed on |
| NC-14 | Now, applied | quote punctuation | PLAN-v2.md:1276 (and a period after the quote), P2.md:21, P3.md:20, P4.md:21, P5.md:23, P6.md:20, P9.md:22, P10.md:20, P11.md:128; P7b.md:87 not edited (merged) |
| NC-15 | After P1b | G2's arming is P1b's E4, else P1c's X3 (an arming choice inside P1b with P1c's fallback) | handed on (P2 part = F-P2-01 to -03, -10; P3.md:7 and :15-16 have no Source 1 text) |
| NC-16 | After P1b | P1b row 1 | handed on |
| NC-17 | After P1b | P1b E5's candidates | handed on (same as F-P2-12, -14 to -16, -23) |
| NC-18 | After P1b | P1b's removals | handed on (same as F-P2-27) |
| NC-19 | After P1b | P1b row 2 (E7) | handed on |
| NC-20 | After P1b | P1b E13 | handed on |
| NC-21 | After P1b | P1b row 18 | handed on |
| NC-22 | After P1b | P1b row 3 | handed on |
| NC-23 | After P1b | P1b E3 | handed on |
| NC-24 | After P1b | P1b row 3 and E12 | handed on |
| NC-25 | After P1b | P1b row 10 | handed on |
| NC-26 | After P1b | D24 relation P1b owns and may delete | handed on |
| NC-27 | After P1b | P1b row 15 | handed on |
| NC-28 | After P1b | P1b E3 | handed on |
| NC-29 | After P1b | P1b row 2 (E7) | handed on |
| NC-30 | After P1b | P1b row 11 | handed on |
| NC-31 | After P1b | P1b row 3 | handed on |
| NC-32 | After P1b | P1b E8 | handed on |
| NC-33 | After P1b | P1b row 6 | handed on |
| NC-34 | After P1b | P1b row 12 | handed on |
| NC-35 | After P1b | P1b row 18 | handed on (same as F-P6-05) |
| NC-36 | After P1b | P1b row 3, P1c row 7 | handed on (same as F-P6-02) |
| NC-37 | After P1b | a code cite into the agent-meta reader P1b row 18 changes | handed on |
| NC-38 | After P1b | P1b row 13 | handed on |
| NC-39 | After P1b | P1b rows 1 and 18 | handed on |
| NC-40 | After P1b | P1b row 15 | handed on |
| NC-41a | After P1b | row 7's drift test: P1b | handed on (same as F-P10-03) |
| NC-41b | Now, applied | row 3's timelock phase: P5 deletes it | P10.md:357 (row 3): "P5 deletes that phase, so take the references from your base" |
| NC-42 | Now, applied | P4 keeps /commit --bulk (D15) | P10.md:373 (row 19): the bulk-commit chain (L39) stays live |
| NC-43 | After P1b | P1b row 15 | handed on |
| NC-44 | Now, applied | merge-title format in the start checks | P2.md:74, P3.md:71, P4.md:35-36, P5.md:44-45, P6.md:35-36, P9.md:50-51, P10.md:39-41 (one line added), P11.md:46-47: both forms master's merges take |
| NC-45 | Now, applied | "tell the owner" -> the reviewer | same edits as F-P2-04, F-P3-01, F-P4-02, F-P5-02, F-P6-01, F-P10-01 |
| NC-46 | Now, applied | the prompts tell the reviewer | HANDOVER.md:11 |
| NC-47 | Now, applied | questions answered on 2026-10-19 | HANDOVER.md:16 and :18 |
| NC-48 | Now, applied | D18 replaced the veto | HANDOVER.md:71 |
| NC-49 | Now, applied | dated rows that no longer hold: P8 and P7b merged | HANDOVER.md:106 and :108 note the merges (2acc29b, 301d696) |
| NC-50 | After P1b | P1b row 3 and E12 | handed on |
| NC-51 | Now, applied | the launcher never copies the rule (P2.md:930-931) | COVERAGE.md:247-248 (re-wrapped, same count) |
| NC-52 | After P1b | names P1b's and P1c's acceptances | handed on |
| NC-53 | Now, not applied | dated inputs, by design | not applied: no edit, by design |
| MN-01 | Now, applied | stale count | same edit as PV-14 |
| MN-02 | After P1b | P1b row 13 | handed on |
| MN-03 | After P1b | P1b row 6 moved the rule into G3 | handed on |
| MN-04 | After P1b | P1b rows 8 and 18 | handed on |
| MN-05 | After P1b | P1b row 2 | handed on |
| MN-06 | After P1b | P1b row 13 | handed on (same as L-P2-04, L-P2-05) |
| MN-07 | After P1b | P1b E13 | handed on |
| MN-08 | After P1b | P2's preflight edit is the arming commit's deletion of P1b's kept copy | handed on |
| MN-09 | After P1b | P1b row 6 | handed on |
| MN-10 | After P1b | P1b row 6 | handed on |
| MN-11 | After P1b | P1b E3 | handed on (same as L-P3-01) |
| MN-12 | After P1b | P1b row 11 | handed on |
| MN-13 | After P1b | P1b row 6 | handed on (same as L-P4-03) |
| MN-14 | After P1b | P1b row 2 | handed on |
| MN-15 | After P1b | P1b row 8 | handed on (same as L-P5-01, L-P5-03) |
| MN-16 | After P1b | P1b row 8 | handed on |
| MN-17 | After P1b | P1b E3 | handed on (same as L-P10-01) |

## After P1b: the list for the second pass

Grouped by target file. Each Source 1 entry is the findings record's entry copied as it stands (heading, state, source,
grade and notes, old and new texts; anchored at ef34dbc), preceded by one line that gives where its old text occurs at
this pass's HEAD. Each Source 2 entry is the residuals record's bullet copied as it stands (its line numbers are at
e712310; at this pass's HEAD they still hold, except in prompts/P10.md, whose lines from :41 on moved down by one).
Source 2 has no fix text: the second pass writes the smallest edit against P1b as merged. Source 1's "Conventions"
(:2305-2341) and "Base and conventions" (:1371-1399) still describe how its texts are written.

### PLAN-v2.md

At HEAD: the old text occurs once, at `PLAN-v2.md`:135.

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

At HEAD: the old text occurs once, at `PLAN-v2.md`:353.

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

At HEAD: the old text occurs once, at `PLAN-v2.md`:368.

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

At HEAD: the old text occurs once, at `PLAN-v2.md`:474.

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

At HEAD: the old text occurs once, at `PLAN-v2.md`:704.

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

At HEAD: the old text occurs once, at `PLAN-v2.md`:784.

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

At HEAD: the old text occurs once, at `PLAN-v2.md`:800.

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

At HEAD: the old text occurs once, at `PLAN-v2.md`:1092.

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

At HEAD: the old text occurs 0 times in `PLAN-v2.md`; see the item's row in the table above.

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

At HEAD: the old text occurs once, at `PLAN-v2.md`:1192.

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

At HEAD: the old text occurs once, at `PLAN-v2.md`:1250.

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

At HEAD: the old text occurs once, at `PLAN-v2.md`:1260.

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

At HEAD: the old text occurs once, at `PLAN-v2.md`:1318-1328.

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

At HEAD: the old text occurs 0 times in `PLAN-v2.md`; see the item's row in the table above.

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

**R2-09a** (reviews/D20-D25-residuals-and-sync-record.md:1042-1044 (the part this id names; the bullet is shared)):

~~~
- PLAN-v2.md:392 (P2 scratch-repo run still lists close.md Step 0, the QA-arming block and commit.md Step 5; P2.md
  records its deviation) and :453 ("after the re-dispatched BA writes a newer ticket and context", which R22 reverted in
  P3.md) differ from the prompts after the residual edits. (R15, R22-B)
~~~

**NC-01** (reviews/D20-D25-residuals-and-sync-record.md:1092):

~~~
  - :54 credits "ESCALATION_ACK ... releases nothing" to P3; P1b row 3 delivers it.
~~~

**NC-03** (reviews/D20-D25-residuals-and-sync-record.md:1094):

~~~
  - :135, :353 and :368 have P2 arm "G1-G3"; P2 arms G1 and G3, and G2 is armed by P1b's E4 (else P1c's X3).
~~~

**NC-04** (reviews/D20-D25-residuals-and-sync-record.md:1095):

~~~
  - :272 and :1101 keep the TERMINAL_VOCABULARY/schema drift test that P1b rows 6 and 18 delete.
~~~

**NC-05** (reviews/D20-D25-residuals-and-sync-record.md:1096):

~~~
  - :442 says "The G2 escalation-record stores are removed here"; the P3 paragraph at :423 makes that verify-only.
~~~

**NC-07** (reviews/D20-D25-residuals-and-sync-record.md:1098):

~~~
  - :571's "after step i went in_progress" (P5 row) is governed by :536.
~~~

**NC-08** (reviews/D20-D25-residuals-and-sync-record.md:1099):

~~~
  - :589 and :1070 grep for D4c only in command_span.py and stop_contract.py, not in the reader's module (round 8).
~~~

**NC-09** (reviews/D20-D25-residuals-and-sync-record.md:1100):

~~~
  - :803 "the 12 consent readers"; P1b row 9 counts eleven hooks with thirteen read sites.
~~~

**NC-10** (reviews/D20-D25-residuals-and-sync-record.md:1101):

~~~
  - :1042 and :1049 have P9 delete lifecycle-baseline-import.sh among "the four scripts"; P1b row 15 deletes it.
~~~

**NC-11** (reviews/D20-D25-residuals-and-sync-record.md:1102):

~~~
  - :1092 cites prompt-workflow.py:1427 (PLAN-v2's base 54393f8); it is :1425 at f8c18c2 and d625284.
~~~

**NC-13** (reviews/D20-D25-residuals-and-sync-record.md:1104):

~~~
  - Section 13 rows :1237, :1252-1254, :1256 and :1264 send P1b/P1c deliveries to P2-P5 (dated PR records; item 24).
~~~

**MN-02** (reviews/D20-D25-residuals-and-sync-record.md:1162):

~~~
  - :357's "Delivered before P2" list does not name P1b row 13's deletion of closeout's pending-required-calls block.
~~~

**MN-03** (reviews/D20-D25-residuals-and-sync-record.md:1163):

~~~
  - :446 and :458 still credit the four profile exemptions to gitignore-preflight; :423 now puts them in G3's admission.
~~~

**MN-04** (reviews/D20-D25-residuals-and-sync-record.md:1164):

~~~
  - TC-41 (:1107) lists "/spec exempt"; P1b row 18 reads it from the declaration and row 8 gives /spec an obligation.
~~~

**MN-05** (reviews/D20-D25-residuals-and-sync-record.md:1165):

~~~
  - :536 says P1c row 17 pairs each todo in the subagent-call recorder; P1b row 2 now deletes that pairing.
~~~

### reviews/P1b-plan-sync.md

At HEAD: the old text occurs once, at `reviews/P1b-plan-sync.md`:5.

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

At HEAD: the old text occurs once, at `reviews/P1b-plan-sync.md`:304.

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

At HEAD: the old text occurs once, at `reviews/P1b-plan-sync.md`:1325.

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

At HEAD: the old text occurs once, at `reviews/P1b-plan-sync.md`:1466-1467.

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

At HEAD: the old text occurs once, at `reviews/P1b-plan-sync.md`:1620-1628.

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

### prompts/P2.md

At HEAD: the old text occurs once, at `prompts/P2.md`:1.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:5.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:15.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:112.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:157-158.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:186-187.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:322.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:322.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:322.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:327.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:327.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:332.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:335.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:380-383.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:472-474.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:558-559.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:585.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:775-776.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:777-778.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:785.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:802-804.

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

At HEAD: the old text occurs once, at `prompts/P2.md`:871-872.

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

**NC-15** (reviews/D20-D25-residuals-and-sync-record.md:1107):

~~~
  - P2's title, :5, :15 and Goal 7 (:157), and P3.md:7 and :15-16 say P2 arms "G1-G3".
~~~

**NC-16** (reviews/D20-D25-residuals-and-sync-record.md:1108):

~~~
  - P2.md:494 lists close.md :246-251 among the respelling sites; P1b row 1 deletes that block first.
~~~

**NC-17** (reviews/D20-D25-residuals-and-sync-record.md:1109):

~~~
  - P2.md:186 (D24 bullet), row 4 and acceptance 5 make the lane hook the aggregate's only producer; E5 may take (b).
~~~

**NC-18** (reviews/D20-D25-residuals-and-sync-record.md:1110):

~~~
  - P2 acceptance 19 (:872) lists artifacts P1b already removed (harness-report.json, continuation sentinel, ...).
~~~

**NC-19** (reviews/D20-D25-residuals-and-sync-record.md:1111):

~~~
  - P2 row 14 (:332) leaves `_complete_todos` to P5; P1b row 2 (E7) deletes break-overnight-lock.py's todos write.
~~~

**NC-20** (reviews/D20-D25-residuals-and-sync-record.md:1112):

~~~
  - P2.md:449 ("A contract the old prose already wrote ...") describes the cycle contract P1b E13 now delivers.
~~~

**MN-06** (reviews/D20-D25-residuals-and-sync-record.md:1167):

~~~
  - Row 9 (:327) "drop it or keep it (D10)" and :585: P1b row 13 already deletes the pending-required-calls block.
~~~

**MN-07** (reviews/D20-D25-residuals-and-sync-record.md:1168):

~~~
  - Row 14 (:332, `IMMUTABLE_FIELDS`): P1b E13 says nothing runs update-overnight-state.sh ("Already done" covers it).
~~~

**MN-08** (reviews/D20-D25-residuals-and-sync-record.md:1169):

~~~
  - :42-68 ("Files you share with P3") omit hooks/pretool-gitignore-preflight.py; the second-to-merge rule covers it.
~~~

### prompts/P3.md

At HEAD: the old text occurs once, at `prompts/P3.md`:288.

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

At HEAD: the old text occurs once, at `prompts/P3.md`:490.

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

At HEAD: the old text occurs once, at `prompts/P3.md`:691-695.

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

**NC-15** (reviews/D20-D25-residuals-and-sync-record.md:1107):

~~~
  - P2's title, :5, :15 and Goal 7 (:157), and P3.md:7 and :15-16 say P2 arms "G1-G3".
~~~

**NC-21** (reviews/D20-D25-residuals-and-sync-record.md:1113):

~~~
  - P3.md:296-297 (row 11) cites ENFORCED_AGENT_TYPES :31, which P1b row 18 deletes (reviewer item 6).
~~~

**NC-22** (reviews/D20-D25-residuals-and-sync-record.md:1114):

~~~
  - P3's retired list (:365-367) counts G2's escalation stores and the ESCALATION_ACK admission P1b row 3 retires.
~~~

**MN-09** (reviews/D20-D25-residuals-and-sync-record.md:1171):

~~~
  - Goal 5 (:148) still says the four profiles are exempt "by gitignore preflight"; row 13 now puts them in G3.
~~~

**MN-10** (reviews/D20-D25-residuals-and-sync-record.md:1172):

~~~
  - :640: the sentence after acceptance 11's cases describes only the preflight's run, not G3's.
~~~

**MN-11** (reviews/D20-D25-residuals-and-sync-record.md:1173):

~~~
  - :490 keeps scripts/close-commit-repair-orchestrate.py, which P1b E3 now deletes.
~~~

### prompts/P4.md

At HEAD: the old text occurs once, at `prompts/P4.md`:296.

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

At HEAD: the old text occurs once, at `prompts/P4.md`:297.

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

At HEAD: the old text occurs once, at `prompts/P4.md`:300.

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

At HEAD: the old text occurs once, at `prompts/P4.md`:306.

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

At HEAD: the old text occurs once, at `prompts/P4.md`:337.

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

At HEAD: the old text occurs once, at `prompts/P4.md`:530-532.

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

At HEAD: the old text occurs once, at `prompts/P4.md`:623.

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

At HEAD: the old text occurs once, at `prompts/P4.md`:639.

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

**NC-23** (reviews/D20-D25-residuals-and-sync-record.md:1116):

~~~
  - :524 (Out of scope) still calls the declaring-dispatch reader P3's work (P1b E3's).
~~~

**NC-24** (reviews/D20-D25-residuals-and-sync-record.md:1117):

~~~
  - Row 9 (:304) keeps sinks whose writes P1b row 3 and E12 deleted; "Net code cap" (:766) credits them.
~~~

**NC-25** (reviews/D20-D25-residuals-and-sync-record.md:1118):

~~~
  - Row 3 (:298) deletes "the 1b still-missing finding", which P1b row 10 deletes too.
~~~

**NC-26** (reviews/D20-D25-residuals-and-sync-record.md:1119):

~~~
  - Row 4 (:299) and :211 keep two audit-line writes that inventory A98 lists as written and never read.
~~~

**NC-27** (reviews/D20-D25-residuals-and-sync-record.md:1120):

~~~
  - :379-383 `append_rating` reads the score log beside P1b row 15's one reading function for it.
~~~

**MN-12** (reviews/D20-D25-residuals-and-sync-record.md:1175):

~~~
  - :348-350: commit.md:249's "bulk capability absent" wait is gone at P4's base (P1b row 11).
~~~

**MN-13** (reviews/D20-D25-residuals-and-sync-record.md:1176):

~~~
  - :334-337: the late-repair route re-runs verify-disclosure; P1b row 6 moves that rule into finalize.
~~~

### prompts/P5.md

At HEAD: the old text occurs once, at `prompts/P5.md`:265.

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

At HEAD: the old text occurs once, at `prompts/P5.md`:350.

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

At HEAD: the old text occurs once, at `prompts/P5.md`:362.

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

At HEAD: the old text occurs once, at `prompts/P5.md`:607.

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

At HEAD: the old text occurs once, at `prompts/P5.md`:747-749.

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

At HEAD: the old text occurs 0 times in `prompts/P5.md`; see the item's row in the table above.

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

**R2-05** (reviews/D20-D25-residuals-and-sync-record.md:1032-1035):

~~~
- prompts/P5.md:342 (row 2) says "P3 row 6 removes their writer"; after R17 the writers sit in P3 rows 6 and 7, and P1b
  row 3 and P1c row 7 remove them first. Its check `git grep -n -e escalations/ -e escalation-admissions/ --
  hooks/subagentstop-artifact-contract-enforce.py` does not match the code's `cycle_dir / "escalations"` form. (R17-B,
  R67-B, P5-4)
~~~

**NC-28** (reviews/D20-D25-residuals-and-sync-record.md:1122):

~~~
  - Row 11 (:352): "use the name P3 merged" for the reader (the block names P1b's E3).
~~~

**NC-29** (reviews/D20-D25-residuals-and-sync-record.md:1123):

~~~
  - Row 13 (:354) and the retired list (:845): "/stop's todo force-complete", which P1b row 2 (E7) deletes.
~~~

**NC-30** (reviews/D20-D25-residuals-and-sync-record.md:1124):

~~~
  - Row 14 (:355): push.md Step 1's "no push-gate token" abort, a scan P1b row 11 removed.
~~~

**NC-31** (reviews/D20-D25-residuals-and-sync-record.md:1125):

~~~
  - Retired list (:840): "stop-obligation-gate (G4's terminal re-check)", which P1b row 3 stubbed.
~~~

**NC-32** (reviews/D20-D25-residuals-and-sync-record.md:1126):

~~~
  - S9 (:274) "[pending, completed]", :292 and acceptance 21 (:795) "a pending skeleton", row 15 (:356).
~~~

**MN-14** (reviews/D20-D25-residuals-and-sync-record.md:1178):

~~~
  - :115: row 20's step lookups in posttool-subagent-track; P1b row 2 removes that step pairing.
~~~

**MN-15** (reviews/D20-D25-residuals-and-sync-record.md:1179):

~~~
  - :265 ("the coverage phase for /spec ... keep working") and :607 ("unchanged"): since P1b row 8 the phase is a stub.
~~~

### prompts/P6.md

At HEAD: the old text occurs once, at `prompts/P6.md`:66-68.

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

At HEAD: the old text occurs once, at `prompts/P6.md`:350.

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

At HEAD: the old text occurs once, at `prompts/P6.md`:417-418.

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

At HEAD: the old text occurs once, at `prompts/P6.md`:510-512.

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

At HEAD: the old text occurs once, at `prompts/P6.md`:760.

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

**R2-18** (reviews/D20-D25-residuals-and-sync-record.md:1070-1072):

~~~
- After P6 deletes the dev-registry FIRST ACTION lines, the kept SECOND ACTION prose that places its line "immediately
  after the dev-registry FIRST ACTION" (expected tree commands/dev-command.md:183, commands/dev-overnight.md:353) points
  at a deleted line. (R35-B)
~~~

**NC-33** (reviews/D20-D25-residuals-and-sync-record.md:1128):

~~~
  - :118 says journal-view "was deleted by P3 row 7" (P1b row 6).
~~~

**NC-34** (reviews/D20-D25-residuals-and-sync-record.md:1129):

~~~
  - Row 9 (:356), :321-329, :428 and :636 keep /tmp/agentic-commit/ paths that P1b row 12 moves.
~~~

**NC-35** (reviews/D20-D25-residuals-and-sync-record.md:1130):

~~~
  - Row 3 (:350) cites obligation.ROLES and ENFORCED_AGENT_TYPES, which P1b row 18 deletes (reviewer item 6).
~~~

**NC-36** (reviews/D20-D25-residuals-and-sync-record.md:1131):

~~~
  - :66 "any G2 escalation records P3 left" (P1b row 3, P1c row 7 remove them).
~~~

**NC-37** (reviews/D20-D25-residuals-and-sync-record.md:1132):

~~~
  - Row 1 (:348) cites `_metadata_by_tool_use` as :525-548; it ends at :549 (inventory A120).
~~~

### prompts/P9.md

At HEAD: the old text occurs once, at `prompts/P9.md`:124.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:212-214.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:242.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:385.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:448.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:469.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:471.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:471.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:473.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:473.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:476.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:476.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:476.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:476.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:478.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:509-510.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:661.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:661.

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

At HEAD: the old text occurs once, at `prompts/P9.md`:699-701.

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

**NC-38** (reviews/D20-D25-residuals-and-sync-record.md:1134):

~~~
  - Row 8 (:476): overnight-status.sh "prints the state with no time computation"; P1b row 13 adds the window verdict.
~~~

**NC-39** (reviews/D20-D25-residuals-and-sync-record.md:1135):

~~~
  - Row 5 (:473) and :425 locate CP_AGENTS readers that P1b rows 1 and 18 delete.
~~~

**NC-40** (reviews/D20-D25-residuals-and-sync-record.md:1136):

~~~
  - Acceptance 11 (:598) holds only if P1b row 15's score-log reader does not name lifecycle.jsonl.
~~~

### prompts/P10.md

At HEAD: the old text occurs once, at `prompts/P10.md`:360.

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

At HEAD: the old text occurs once, at `prompts/P10.md`:361.

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

**NC-41a** (reviews/D20-D25-residuals-and-sync-record.md:1138 (the part this id names; the bullet is shared)):

~~~
  - Row 7 (:360) keeps the drift test P1b deletes; row 3 (:356) cites the timelock phase P5 deletes.
~~~

**NC-43** (reviews/D20-D25-residuals-and-sync-record.md:1140):

~~~
  - Row 6 (:359) lists scripts/session-resources.py as a D17 candidate; P1b row 15 runs it.
~~~

**MN-16** (reviews/D20-D25-residuals-and-sync-record.md:1181):

~~~
  - :57's list of P1b's stubs omits stop-spec-coverage-enforce.py; its general rule still finds it.
~~~

**MN-17** (reviews/D20-D25-residuals-and-sync-record.md:1182):

~~~
  - Row 6 (:359) lists the repair-map scripts and schema P1b E3 deletes, and update-overnight-state.sh's options.
~~~

### COVERAGE.md

At HEAD: the old text occurs once, at `COVERAGE.md`:312.

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

**NC-50** (reviews/D20-D25-residuals-and-sync-record.md:1150):

~~~
  - C4 (:128) and fix 3 (:213-220): P4 deletes the three advisory sinks; P1b row 3 and E12 delete their writes first.
~~~

**NC-52** (reviews/D20-D25-residuals-and-sync-record.md:1152):

~~~
  - :71 (O44): the live-landing acceptances listed name none of P1b's or P1c's.
~~~

### COVERAGE-P9-P11.md

**R2-02b** (reviews/D20-D25-residuals-and-sync-record.md:1026-1028 (the part this id names; the bullet is shared)):

~~~
- COVERAGE-P9-P11.md:35-37 (P9, P10 and P11 dependency rows, a dated 2026-10-19 table) do not list P1b and P1c, and :35
  still credits `"CLAUDE_OBLIGATION_STOPGATE": "block"` to "P2 row 17" (P1b's E4 arms it). (R90-B, K-11; reviewer item
  25)
~~~

**R2-03** (reviews/D20-D25-residuals-and-sync-record.md:1029):

~~~
- COVERAGE-P9-P11.md:63 ("O4/O6 one producer per fact | P9 rows 1-6") names no P1b. (K-2)
~~~

## References in prompts/P1b.md and prompts/P1c.md (step 4)

Every `file:line` reference to a plan file in P1b.md and P1c.md was read at 3b5c825 and at this pass's HEAD.

- P1b.md: P4.md:697 (:286), P2.md:519 (:485), P2.md:322 (:487), PLAN-v2.md:133-134, :1199, :1311, :1329, :172, :174
  (:655-656), P5.md:841 (:714), PLAN-v2.md:1158 and P5.md:265, :607, :753 (:715-716), P2.md:756 (:762) and
  P6.md:413-416 (:878): each line holds the same text as before, except PLAN-v2.md:1199, which this pass edited in
  place (the caps row gained P7b's cap, NC-02) and which is still the caps row the reference means.
- P1c.md: its `plan:` references (P4.md:100-102, P3.md:154-155, :144-146, P9.md:161, COVERAGE.md:26, P5.md:152-156) are
  pinned to 3ce5882 by P1c.md:158 and do not move.
- Moved: none. Coupled, for the second pass: PV-18 moves the P1c bullet of PLAN-v2.md section 15 from :1329 to :1321,
  and P1b.md:655 then cites ":1329" (the findings record's PV-18 note).

## Verification round

Running: five verifiers that did not make the edits check the Now items of each source, the rejected ideas, the owner
quotes, and the prompts' first lines, tails and scope. Their findings and the fixes follow in the next commit.

## Found, not fixed

- **R2-17's design question (open; no text).** Whether a release-note residual meets D25 (3) for a running session
  whose personal overlay names a hook P10 deletes is a design question, not a wording defect. P10's experiment 1
  already counts such registrations and its rule makes a counted file an exit-0 stub; P10 decides it by that
  experiment (D18). This pass only widened the residual to shell hooks.
- **Older tails.** The prompts of started or merged phases keep the previous shared tail: P1, P1b, P7b and P8 (the
  `_common.md` before F-C-01 to F-C-05), P0 and P7 (older forms). HANDOVER.md:4 now says so. No later reader depends on
  their tails.
- **"Owner steps: none." as a first line.** Only P1b.md and P1c.md start with it; P2-P6 and P9-P11 start with their
  phase heading and require the line in the PR body. The findings record refuted format-FH-7 and gives no item, so no
  line was added.
- **DECISIONS.md D10** still says the technical-choices table lets "the reviewer or owner" veto a choice; D18 absorbed
  D10 (register X12) and NC-48 removed HANDOVER's veto offer. D10's text is an owner decision record; left as is.
- **PLAN-v2.md:1092 (PV-13, NC-11).** The cite :1427 is right at PLAN-v2's stated base 09ab15b (README.md:9) and
  :1425 at f8c18c2 and d625284; the second pass follows P1b's correction 8 as merged.
