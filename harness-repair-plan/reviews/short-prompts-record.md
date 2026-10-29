# Short prompts: record

The phase prompts P2, P3, P4, P5, P6, P9, P10 and P11 (870 to 1,044 lines each, plus the shared tail) were condensed
into `prompts/short/<phase>.md`: at most 300 lines (P11 350), every row and every acceptance test kept as what changes
and in which files, the paperwork and the citations dropped, and the statements that depend on what P1b delivers
marked `[after P1b: re-check]` (not resolved). This record proves that nothing was dropped: one coverage table per
phase, then the verification round and what it left.

- Branch `claude/vibrant-hopper-bazrn8`, started at 636303e. No existing file changed; added only
  `prompts/short/*.md` and this record.
- Commits, one per short prompt: 0a22380 (P3), 7cf10f8 (P4), 0319481 (P2), 54205eb (P6), 86746ee (P5), 017f9c2 (P9),
  885bc08 (P11), 6d9f10d (P10). Then the verification round's medium fixes, one commit per fixed prompt: 63cc6b1 (P2),
  e889a21 (P9), ebaec1b (P5), 578146c (P4), 6601b1f (P3), a86128b (P11), e06edc0 (P10). Then this record.
- Sources: the long prompts at 636303e; DECISIONS.md; `reviews/plan-pass-1-record.md`, section "After P1b: the list for
  the second pass" (its subsections "prompts/<phase>.md", and the PLAN-v2.md, P1b-plan-sync.md, COVERAGE.md and
  COVERAGE-P9-P11.md entries that name a phase).

## Summary

| Phase | Long (lines / body bytes) | Short (lines / bytes) | Rows: kept / kept, marked / dropped as moved | Acceptance: kept / kept, marked / dropped as moved | Marks | Medium fixed | Low left |
|---|---|---|---|---|---|---|---|
| P2 | 1,044 / 109,570 | 300 / 33,715 | 9 / 9 / 0 | 16 / 4 / 0 | 31 | 2 | 10 |
| P3 | 872 / 84,480 | 300 / 31,371 | 12 / 3 / 0 (rows 8, 9 absent) | 17 / 2 / 0 (A10 a deleted placeholder) | 7 | 1 | 8 |
| P4 | 902 / 95,165 | 300 / 34,544 | 6 / 8 / 0 | 21 / 1 / 0 | 14 | 2 | 6 |
| P5 | 1,006 / 114,017 | 300 / 35,515 | 13 / 9 / 0 | 22 / 4 / 0 | 17 | 14 | 9 |
| P6 | 920 / 85,292 | 300 / 31,892 | 6 / 5 / 0 | 18 / 2 / 0 | 10 | 0 | 3 |
| P9 | 872 / 104,065 | 300 / 34,977 | 12 / 5 / 0 | 22 / 2 / 0 | 14 | 7 | 7 |
| P10 | 898 / 93,177 | 300 / 33,571 | 16 / 3 / 0 | 22 / 0 / 0 (A5-A7 deleted placeholders) | 6 | 5 | 14 |
| P11 | 873 / 70,668 | 350 / 35,008 | 40 / 0 / 0 (B3, B6, B7 replaced) | 14 / 0 / 0 (7, 9-13 replaced) | 0 | 1 | 9 |
| Total | | | 114 / 42 / 0 | 152 / 15 / 0 | 99 | 32 | 66 |

- "Body bytes": the long prompt before its shared tail ("## Context (read once)" to the end). The short prompts are 31%
  to 37% of that, P11 50%.
- Dropped as moved: none. No long prompt marks a row or an acceptance test as moved to another phase.
- Absent or replaced, and so not counted above: P3 rows 8 and 9 (withdrawn in the long prompt, no destination);
  P3 acceptance 10 and P10 acceptance 5-7 (deleted placeholders in the long prompt; the short prompts keep the labels);
  P11 B3, B6 and B7 (marked deleted in the long prompt and replaced by the pre-push guard, to which they map) and P11
  acceptance 7 and 9-13 (replaced in the long prompt by its cases (i)-(iii)).
- P11 has no After-P1b entry about a statement it carries (its only mentions, S38 and R2-02b, concern
  reviews/P1b-plan-sync.md and COVERAGE-P9-P11.md), so it carries no mark.

## How the short prompts were written

- One writer subagent per phase, at most three at a time, each from one written specification; three verifier
  subagents that wrote no prompt; one fixer subagent per prompt with a medium finding. The orchestrator committed.
- The specification fixed the sections in the order the task gives (first line `Owner steps: none.`, then the title;
  Dependencies; Goal; Owner rulings; Rows; Acceptance tests; DO NOT; Pull request; last line `Read prompts/_common.md;
  this file overrides it where they differ`). Choices made for it, each applied to every phase:
  - Rows and tests keep the long prompt's own numbers (R7, A14, A5b), so a coverage line maps one id to one label. P11
    labels its acceptance tests Acc<n>, because A1-A9 are its Part A requirements.
  - Prose was wrapped at 120 characters (raised to 140 in the fix round where a restored requirement needed room); a
    line holding one command may run longer, never past 200. Without a width rule the line limit would not bound the
    size. No markdown tables in the prompts.
  - Work stated outside the scope table (Goal bullets, owner-decision bullets, the Scope subsections, "Before you start",
    arming and live-landing notes, "Already done by P1b: verify, do not redo" lists, "Interfaces you consume") was folded
    into the row it concerns or listed after the rows. "Technical choices you make" and the experiments became the
    "Choices to decide by experiment" list, one line each.
  - "Corrections to PLAN-v2" was dropped as such; an instruction found only there (P5, P6, P9, P10) was carried into its
    row. "Background", "Out of scope", "Rules added / retired", "Rollback" and "Effort" were not carried.
  - The net code cap stays as one line of the DO NOT list (a limit on the work, not PR paperwork).
  - Evidence the long prompts put in the PR beyond the five allowed items (reachability proofs, fact outputs, the size
    budget) travels with the output of the acceptance test that shows it. The D24 table is carried by the acceptance
    test that requires it (P2-P9), by row 19 (P10), and by the D24 ruling line and the PR section (P11; see "Found, not
    fixed").
  - PR-body hand-off sections for later phases ("Hand-off to P4 and P5", "Hand-off to P6", "Hand-off to P11") were
    dropped with the other PR sections; where a later prompt read a fact from one, it names the fact itself (function,
    file, rule) to read on the merged base. P11's stage-2 hand-off comment on its merged PR is a deliverable and is kept.
  - A title line stays unchanged even where an After-P1b entry concerns it (P2's "arm G1-G3", F-P2-01); the same claim
    is marked in the Goal and the PR title line.
  - Marks follow the After-P1b list only: a statement gets `[after P1b: re-check]` when an entry concerns it, keeps the
    long prompt's wording, and an entry whose statement was dropped (as citation, history, background or paperwork) is
    listed as not carried.

## Coverage, per phase

Each section below is that phase's coverage file. "Long place" citations are lines of the long prompt at 636303e;
"Short place" is a label of the short prompt. Line counts and byte counts are the final ones, after the fix round.

## P2

Short prompt: harness-repair-plan/prompts/short/P2.md, 300 lines, 33,715 bytes (long prompt body before the shared
tail: 939 lines, 109,570 bytes; ratio 0.31). Prose lines run to at most 140 characters in the Dependencies failure
paragraph, R4, R7, R9-R15, R17 and the bwrap choice line (rewrapped to make room for the fixer's two fixes); every
other line keeps the 120 wrap, and the one longer line is a command.

### Rows and acceptance tests

| Long item | Short place | Status |
|---|---|---|
| Row 1 (prompt-workflow.py roots, continuation reader) | R1 | kept |
| Row 2 (run_todo_script project candidate) | R2 | kept |
| Row 3 (five project-first resolvers) | R3 | kept |
| Row 4 (aggregator, specialist_yield, write-qa-mode, break-overnight-lock, aggregate-pending) | R4 (opens with its "Done by P1b" credits: E5's one producer and aggregate-pending removal; P1b row 1 and E7's write-qa-mode.sh creation and switch, so R4 and R15 change the script and its calls only where still there) | kept, marked after P1b |
| Row 5 (doc-sync CACHE_FILE / hook_dir) | R5 | kept |
| Row 6 (commands/agents/skills substitution) | R6 | kept, marked after P1b |
| Row 7 (hooks/lib/overnight.py) | R7 | kept |
| Row 8 (stop_contract.timelock_released) | R8 | kept |
| Row 9 (time-lock thinning, closeout.py writer) | R9 (opens with its "Done by P1b" credit: harness-report.json writer, /tmp continuation sentinel) | kept, marked after P1b |
| Row 10 (AskUserQuestion deny in the guard) | R10 | kept |
| Row 11 (posttool-overnight-loop.py) | R11 (opens with its "Done by P1b E13" credit: the state's extra writers, R13's contract items) | kept, marked after P1b |
| Row 12 (file-check, closeout, subagent-enforce, contract_runtime) | R12 (opens with its "Done by P1b E13" credit: one path, "or escalate" gone, R13's other items) | kept, marked after P1b |
| Row 13 (launcher, PM TRIAGE renderer, schema) | R13 (opens with the full "Done by P1b E13, P1c rows 13 and 19" contract credit for R11-R13 and R15) | kept, marked after P1b |
| Row 14 (IMMUTABLE_FIELDS, break-overnight-lock, stop.sh, stop.md) | R14 (opens with its "Done by P1b E13" credit: the state's extra writers) | kept, marked after P1b |
| Row 15 (dev-overnight.md) | R15 (opens with its "Done by P1b" credit: R13's contract items, R4's write-qa-mode.sh items) | kept, marked after P1b |
| Row 16 (docs lines made false) | R16 | kept |
| Row 17 (settings.json arming, allow respelling) | R17 | kept, marked after P1b |
| Row 18 (tests) | R18 | kept |
| Acceptance "Sandbox" note | Acceptance tests, Sandbox paragraph and the two "before" sandbox command lines | kept |
| Acceptance 1 | A1 | kept |
| Acceptance 2 | A2 | kept |
| Acceptance 3 | A3 | kept |
| Acceptance 4 | A4 | kept |
| Acceptance 5 | A5 | kept, marked after P1b |
| Acceptance 6 | A6 | kept, marked after P1b |
| Acceptance 7 | A7 | kept |
| Acceptance 8 | A8 | kept, marked after P1b |
| Acceptance 9 | A9 | kept |
| Acceptance 10 | A10 | kept |
| Acceptance 11 | A11 | kept |
| Acceptance 12 | A12 | kept |
| Acceptance 13 | A13 | kept |
| Acceptance 14 | A14 | kept |
| Acceptance 15 | A15 | kept |
| Acceptance 16 | A16 | kept |
| Acceptance 17 | A17 | kept |
| Acceptance 18 | A18 | kept |
| Acceptance 19 | A19 | kept, marked after P1b |
| Acceptance 20 | A20 (with the merge rule's D20 overnight fault replay and D/H site notes) | kept |
| Scope: "One locator, one parser, window_open (TC-12, TC-36)" (incl. the coordinator's timelock fallback paragraph) | R7 (parser, locator, session_state, cycle_index, window_open, closeout_gaps, deciders, coordinator fallback, prompt-purity parser), R1 (continuation reader), R10 (guard's parser) | kept |
| Scope: "The overnight AskUserQuestion deny (TC-45)" | R10 (A7 covers the FIRST ACTION and runhook.py proofs) | kept |
| Scope: "The cycle contract (TC-35, TC-43, B2.e)" | R13 (seedless steps 2-4, renderer, re-dispatch entries, one declaration, atomic write), R12 (one contract path, mirror and symlink dropped), R15 (Manifest) | kept, marked after P1b |
| Scope: "The D6 landing route and the summary (D6, D6a, D20)" | R15 | kept, marked after P1b |
| Scope: "The harness-home channel in prompts and permissions (TC-44)" | R6 (substitution rules, file scope, P4 lines, operand scan, wrapper test), R17 (constraint 1, permissions), A2 (constraint 3, literal-path runs) | kept |
| Scope: "Arming (A1.a) and live landing (owner, 2026-10-18)" | R17 (arming commit, copy deletions, run-time switch read, permissions across the pull), A15 | kept, marked after P1b |
| Scope: "Technical choices you make (list each in the PR)" | Rows, "Choices to decide by experiment", lines 3-12 | kept, marked after P1b |
| Choice: the names and form of the two printed roots | Choices, line 3 | kept |
| Choice: the locator's rule per isolation kind and for a worktree project dir | Choices, line 4 (with the overridden fresh-clone root from R7's subsection) | kept |
| Choice: how timelock_released and window_open read the transcript and the state | Choices, line 5 | kept |
| Choice: where the deny runs and the payload field tying a subagent to its session | Choices, line 6 | kept |
| Choice: steps 2-4 without a seed, re-dispatch entries, renderer place, schema max_retries | Choices, line 7 | kept |
| Choice: closeout_gaps freshness comparison and clock allowance | Choices, line 8 | kept |
| Choice: write-qa-mode.sh fallback root, and the dead pending-required-calls branch | Choices, line 9 | kept, marked after P1b |
| Choice: channel form in Bash and Read paths, allow respelling, old spellings kept, guard's operand handling | Choices, line 10 (with doc-sync's CLAUDE_CONFIG_DIR reading from row 5) | kept |
| Choice: what stop.md and stop.sh say, other sessions' state in break-overnight-lock.py | Choices, line 11 | kept |
| Choice: anything else you decide | Choices, line 12 (with the G1/G3 switch-read option from "P1b and P1c", Arming) | kept |
| Decided by experiment (D18): bwrap | Choices, line 1 (options and decision rule; the limit in README and in dev-overnight.md's isolation note); procedure and the launcher's in_place refusal in R13 | kept |
| Decided by experiment (D18): Arming timing | Choices, line 2; probe and P5 options in R17 | kept |

Other instruction-bearing parts folded in: "Before you start" -> Dependencies checks; wave paragraph's P3-first rule ->
Dependencies; "Files you share with P3" -> Dependencies (merge rule), R6 (P3's new lines), R17 (switch-read hunks), R18
(path pins only); "P1b and P1c" -> Dependencies (verify, never redo, change only what is left, X5, single producer and
deciding consumer), its "Already done" list -> R4, R9, R11-R15 (each row opens with a "Done by P1b" credit), R7 (P1b row
13, E13), R8 and R10 (P1b row 18 reader), R9 (X8 wake, P1b row 15 receipt call), R14 and R15 (wake lines), R17 (E4, X3,
copy deletions, run-time switch read), A20 (merge rule); Goals 1-8 -> Goal and rows; decided TCs (TC-11 R7, TC-12 R7,
TC-15 A14, TC-35 R13, TC-36 R7, TC-40 A14, TC-43 R13, TC-44 R6, TC-45 R10); "Carry-overs from P1" -> R6
(repository-relative harness scripts incl. resolve-dev-artifact-chain.py, `$TASK_ID`) and R15 (retry caps, stale ":1047
site" references); commit order -> R17 (allow respelling and matcher in earlier commits, arming last) and R18 (Python
3.10).

### After-P1b entries

| Entry | Long place | Short place or reason not carried |
|---|---|---|
| F-P2-01 | P2.md:1, title "arm G1-G3" | Title heading carried unchanged on line 3, as the brief requires; no inline mark there (it would change the heading). The same claim is marked at the Goal (line 20) and the PR title (line 297). |
| F-P2-02 | P2.md:5, PR title example | Pull request, Title line, marked (line 297) |
| F-P2-03 | P2.md:15, wave paragraph "your last commit arms G1-G3" | Not carried: wave history and merge-order rationale; the arming claim itself is marked at Goal and R17 |
| F-P2-07 | P2.md:112, "complete each in the same mechanism and do not rebuild it" | Dependencies, X5 sentence, marked (line 15); its note's row 14 and acceptance 8 cites (update-overnight-state.sh) are marked at R14 (line 131) and A8 (line 225); its new text (rows 4, 11, 14 and 15 act only on what P1b left) concerns the "Done by P1b" credits, marked at R4 (lines 54, 56), R11 (line 111), R14 (line 130) and R15 (line 135) |
| F-P2-10 | P2.md:157-158, Goal 7 | Goal, "the last commit arms G1-G3", marked (line 20); the key list is R17 (F-P2-20) |
| F-P2-12 | P2.md:186-187, D24 bullet | Not carried in the D24 ruling line, which states DECISIONS.md's rule only; the claim (lane hook is the only producer, unread writers go) is carried and marked in R4 (F-P2-16); the "Already done" credit its new text restates (E5's one producer, the aggregate-pending writer's removal) is R4's "Done by P1b" credit, marked (line 54) |
| F-P2-14 | P2.md:322, row 4 location `_invoke_aggregator` | R4, marked after `_invoke_aggregator` (line 56) |
| F-P2-15 | P2.md:322, "The aggregator resolves relative to the hook's own file ..." | R4, marked (line 57) |
| F-P2-16 | P2.md:322, "The lane-completeness hook is the canonical aggregate's only producer. Delete ..." | R4, marked (line 59); also R4's "Done by P1b" E5 credit, marked (line 54) |
| L-P2-03 | P2.md:327, row 9 `_invoke_closeout` parenthetical | R9, marked (line 99) |
| L-P2-04 | P2.md:327, row 9 "drop it or keep it (D10)" | Moved with the choice it states: Choices line 9, marked (line 180) |
| F-P2-18 | P2.md:332, row 14 "It may still record terminal_status ... current_phase ..." | R14, marked (line 132) |
| F-P2-20 | P2.md:335, row 17 three env keys | R17, marked (line 151) |
| L-P2-02 | P2.md:380-383, TIME CHECK paragraph listed under "Out of scope, found" | Not carried: PR paperwork (an "Out of scope, found" listing); R15 keeps the TIME CHECK paragraph |
| F-P2-21 | P2.md:472-474, "After end_time nobody is asked ..." | R15, marked (line 143) |
| F-P2-22 | P2.md:558-559, arming commit is the last commit and holds only the env keys | R17, marked (line 150) |
| L-P2-05 | P2.md:585, technical choice write-qa-mode root and dead branch | Choices line 9, marked (line 180) |
| F-P2-23 | P2.md:775-776, A5 canonical aggregate written | A5, marked (line 211) |
| F-P2-24 | P2.md:777-778, A5 write-qa-mode.sh if P1b's PR left it | A5, marked (line 213); also the write-qa-mode.sh "Done by P1b" credit, marked in R4 (line 56) and R15 (line 135) |
| F-P2-25 | P2.md:785, A6 after end_time closeout_gaps | A6, marked (line 216) |
| F-P2-26 | P2.md:802-804, A8 /stop release | A8, marked (line 228) |
| F-P2-27 | P2.md:871-872, A19 artifact list | A19, marked (line 279) |
| NC-15 | P2.md title, :5, :15, Goal 7 | As F-P2-01, F-P2-02, F-P2-03, F-P2-10 |
| NC-16 | P2.md:494, close.md :246-251 among respelling sites | Not carried: the PLAN-v2 site list is citations; R6 states the substitution by pattern |
| NC-17 | P2.md:186, row 4, acceptance 5 | R4 marks (lines 54, 56, 57, 59) and A5 (line 211); D24 bullet as in F-P2-12 |
| NC-18 | P2.md:872, acceptance 19 list | A19, marked (line 279); the artifacts it names as P1b's removals (harness-report.json, continuation sentinel) are R9's "Done by P1b" credit, marked (line 92) |
| NC-19 | P2.md:332, row 14 `_complete_todos` left to P5 | R14, marked (line 134) |
| NC-20 | P2.md:449, "A contract the old prose already wrote ..." | R13, marked (line 127); the cycle contract it says P1b E13 delivers is the "Done by P1b E13" credit, marked at R13 (line 121) and at its pointers in R11 (line 111), R12 (line 114) and R15 (line 135) |
| MN-06 | P2.md:327 (row 9) and :585 | R9 (line 99) and Choices line 9 (line 180), marked |
| MN-07 | P2.md:332, row 14 IMMUTABLE_FIELDS | R14, marked (line 131); the "Already done" item it cites (the overnight state's extra writers, P1b E13) is the credit marked in R14 (line 130) and R11 (line 111) |
| MN-08 | P2.md:42-68, files shared with P3 | Dependencies, P3-first merge sentence, marked (line 17) |
| PV-1 | PLAN-v2.md:135, section 5 P2 row | PLAN-v2 text not carried; the same claim in P2's own words is marked at Goal, R17 and the PR title |
| PV-2 | PLAN-v2.md:353, P2 heading | PLAN-v2 text not carried; P2's own title is F-P2-01 |
| PV-3 | PLAN-v2.md:368, "The last commit arms G1-G3." | Goal, same mark as F-P2-10 (line 20) |
| PV-16 | PLAN-v2.md:1250 (repeated in P2.md:605 carry-overs) | R6, "resolve-dev-artifact-chain.py", marked (line 66) |
| NC-03 | PLAN-v2.md :135, :353, :368 | As PV-1, PV-2, PV-3 |
| R2-09a | PLAN-v2.md:392 (P2 scratch-repo run) | Not carried: PLAN-v2 text; R6 already leaves the close.md and commit.md lines P1b left |
| MN-02 | PLAN-v2.md:357 ("Delivered before P2" list) | Not carried: PLAN-v2 text |
| NC-13 | PLAN-v2.md section 13 rows | Not carried: PLAN-v2 text (the P2 carry-over that survives is PV-16's) |
| R2-02b | COVERAGE-P9-P11.md:35 ("P2 row 17" credited with STOPGATE) | Not carried: COVERAGE-P9-P11 text; R17's arming is marked under F-P2-20 |

No entry in "### reviews/P1b-plan-sync.md" or "### COVERAGE.md" concerns P2.md.

### DO NOT bullets dropped as repeats of _common.md

- "Do not touch P3's, P4's or P5's files beyond what the rows name" (repeats "Do not edit files outside your phase's
  scope").
- The clause "or start a nested `claude`" of the hook-registration bullet (repeats "Do not run nested `claude` CLI
  sessions"); the rest of that bullet is kept.

### Sections not carried

- Opening paragraph (phase id for the PR title): kept only as the PR title line; the rest is paperwork.
- "Wave 3" paragraph (merge hashes, refreshed base tree, planned merge order): history and commit hashes.
- "No owner step (owner, 2026-10-18)" paragraph: owner quote; its rules are in D18, R17 and A15.
- "P7b" paragraph (files P7b changed): history.
- "Files you share with P3" location lists: citations; the rules are kept (see above).
- "Before you start" base-tree check (a39ecc...) and "say in the PR which base": citations and paperwork.
- "P1b and P1c" paragraph's dates and quotes: history and owner quote; its rules are kept.
- Owner-decision bullets' quotes, O-numbers and S-numbers: owner quotes and plan cross-reference codes.
- Scope preamble ("Locations are on the refreshed base", "What changed after f8c18c2"): history and citations.
- "One suggested commit order": a suggestion, not a requirement (its binding parts are in R17 and R18).
- "Background (in the extracted planning documents)": background reading list (the carry-overs are folded in).
- "Where this prompt corrects or extends PLAN-v2.md's P2 section": corrections to PLAN-v2.
- "Out of scope": out of scope.
- "Rules added / retired (expected)": rules added / retired.
- "Net code cap" prose: carried only as the DO NOT cap line and A18; "Effort": effort.
- "Rollback": rollback.
- "Branch and pull request" (PR headings Decided by experiment, Corrections to PLAN-v2, Subagent session evidence,
  Live landing, Hand-off to P4 and P5, Release notes; subscribe-and-drive): PR paperwork, hand-off section, and text
  repeated from _common.md.
- "Context (read once)" to the end: the shared tail, repeated from _common.md.

Inside kept items, these "list it under Out of scope, found" instructions were left out as PR paperwork: row 5's
lane-completeness advisory log and hooks/install-auto-sync.sh; row 7's pretool-git-privilege-guard.py and
notification-idle-overnight.py parsers and the TIME CHECK claim (L-P2-02); row 9's metrics helpers (the "leave for P10"
part is kept); row 14's find_state_file fallback; row 16's three P9 doc lines. Row 7's optional switch of
notification-idle-overnight.py ("may switch if one line") was left out as a permission, not a requirement. Row 16's
note that the inspector re-dispatch around the close.md clause is P4's was left out as scope rationale.

### Totals

- Rows: 9 kept, 9 kept and marked after P1b, 0 dropped as moved (18 of 18).
- Acceptance tests: 16 kept, 4 kept and marked after P1b, 0 dropped as moved (20 of 20).
- After-P1b marks in the short prompt: 31 (23 from the writer, 8 on the fixer's "Done by P1b" credits: R4 two, R9, R11,
  R12, R13, R14, R15).

## P3

Short prompt: harness-repair-plan/prompts/short/P3.md, 300 lines, 31,371 bytes (long prompt: 872 lines, 92,030 bytes).

### Rows and acceptance tests

| Long item | Short place | Status |
|---|---|---|
| Row 1 (hooks/lib/obligation.py, declaring-dispatch reader) | R1 | kept, marked after P1b |
| Row 2 (resolver: deletions, strict status) | R2 (main text) | kept |
| Row 3 (aggregate-dev-report.py) | R3 | kept |
| Row 4 (dev-lifecycle.py, close-route-select.py, agents/qa.md close gate) | R4 | kept |
| Row 5 (schemas/dev-report.v2.json description) | R5 | kept |
| Row 6 (progress_measure.py, G2 failing stop) | R6 | kept, marked after P1b |
| Row 7 (G2: three writes deleted) | R7 | kept |
| Row 8 | none | absent in the long prompt (withdrawn under D21/D22; the long prompt names no destination phase) |
| Row 9 | none | absent in the long prompt (withdrawn under D21/D22; the long prompt names no destination phase) |
| Row 10 (prompt-workflow.py replay window) | R10 | kept |
| Row 11 (codex-enforce skip for close/commit) | R11 | kept, marked after P1b |
| Row 12 (aggregate-check scoping and canonical check) | R12 | kept |
| Row 13 (gitignore-preflight / G3 profile exemptions) | R13 | kept |
| Row 14 (G2 freshness and lane echo) | R14 | kept |
| Row 15 (agents/dev.md, agents/qa.md echo lines) | R15 | kept |
| Row 16 (tests) | R16 | kept |
| Row 17 (G1 staleness preconditions) | R17 | kept |
| Acceptance "Sandbox and arming" note (precedes the tests, with the "before" sandbox note) | Acceptance tests, "Sandbox" paragraph | kept |
| Acceptance 1 (unit suites) | A1 | kept |
| Acceptance 2 (dev stage cases) | A2 | kept |
| Acceptance 3 (ordering, questions, G1 staleness replay) | A3 | kept |
| Acceptance 4 (escalation) | A4 | kept |
| Acceptance 5 (close stage) | A5 | kept |
| Acceptance 6 (commit stage) | A6 | kept |
| Acceptance 7 (strict status and greps) | A7 | kept |
| Acceptance 8 (declaring-dispatch reader) | A8 | kept |
| Acceptance 9 (/redev) | A9 | kept |
| Acceptance 10 | A10 ("No test") | absent in the long prompt (its item 10 is a deleted placeholder kept only for numbering; the short prompt keeps the label) |
| Acceptance 11 (S7 and S8 fixes) | A11 | kept, marked after P1b |
| Acceptance 12 (warning, then promotion) | A12 | kept |
| Acceptance 13 (allow-list coverage) | A13 | kept |
| Acceptance 14 (static) | A14 | kept |
| Acceptance 15 (no regression) | A15 | kept |
| Acceptance 16 (live landing) | A16 | kept |
| Acceptance 17 (net code) | A17 | kept |
| Acceptance 18 (D24 table) | A18 | kept, marked after P1b |
| Acceptance 19 (subagent question experiment) | A19 | kept |
| Acceptance 20 (never fail) | A20 | kept |
| Scope subsection "The disposition (TC-7, TC-8, TC-22)" | R2, the five sub-bullets (CLI/output/exit/root; dev; do branch; spec clause; close and commit) | kept |
| Scope subsection "Test dispositions" | Rows, extra item "Test dispositions" (plus R16) | kept, marked after P1b |
| Scope subsection "Technical choices you make" | Choices, lines 1-8 and 11 | kept |
| Scope intro paragraph (re-measured locations, "re-verify every location") | none: the short prompt names sites by file and function only | not carried: history and citations |
| Scope "One suggested commit order" | Rows, extra item "Warning and promotion" (warning commit, promotion after the five-sandbox replay, Python 3.10) | kept as far as it states requirements; the suggested order of commits 1-6 dropped (not a requirement) |
| Scope note "Rows 8 and 9 ... are withdrawn" | rows 8 and 9 above | absent in the long prompt |
| Technical choice: gap-line quoting rule, importable function's signature, instrument-failure exit code | Choices, line 1 | kept |
| Technical choice: how --disposition finds the project root when the flag is absent | Choices, line 2 | kept |
| Technical choice: staleness ordering rule and any clock allowance | Choices, line 3 (with R17, decided by A3) | kept |
| Technical choice: which aggregator helpers survive; exit and stderr shape on a mismatch | Choices, line 4 | kept |
| Technical choice: how dev-lifecycle loses the provider | Choices, line 5 | kept |
| Technical choice: how codex-enforce resolves the stopping agent's obligation | Choices, line 6 | kept |
| Technical choice: aggregate-check roster comparison; where the canonical schema check lives | Choices, line 7 | kept |
| Technical choice: freshness clock source and echo comparison | Choices, line 8 | kept |
| Technical choice: anything else you decide | Choices, line 11 | kept |
| Other item decided by experiment: how the do branch reaches the hook's minted record (Disposition, do-report branch) | Choices, line 9 | kept |
| Other items decided by experiment: R1's reader proved by replay (acceptance 8); acceptance 19's subagent question | Choices, line 10 | kept |
| Other item decided by experiment: a product decision DECISIONS.md and the prompt leave open ("OPEN owner decisions") | Choices, line 11; Owner rulings D18 | kept |

### After-P1b entries

| Entry | Long place | Short place or reason not carried |
|---|---|---|
| F-P3-04 | Row 1, "for a never-dispatched artifact, return the command's canonical todo step" (P3.md:288) | R1, marked |
| L-P3-01 | Out of scope, "scripts/close-commit-repair-orchestrate.py and the late-repair route (D15): kept" (P3.md:490) | not carried: the "Out of scope" section is dropped (drop category "Out of scope"); D15's late-repair rule is carried from the Owner-decisions section, which the entry does not concern |
| F-P3-07 | Acceptance 18, the D24 table's artifact list (P3.md:691-695) | A18, marked |
| NC-15 | P3.md:7 (Wave 3 header, "arm G1-G3") and P3.md:15-16 (merge order: "its last commit arms G1-G3", "armed replay with G1-G3 armed") | :15-16 carried in Dependencies (merge-order sentence), marked; :7 not carried (wave history, dropped) |
| NC-21 | Row 11, `ENFORCED_AGENT_TYPES` (P3.md:296-297) | R11, marked |
| NC-22 | Test dispositions, deleted-test list naming "the ESCALATION_ACK admission and G2's escalation stores" (P3.md:365-367) | Rows, extra item "Test dispositions", marked; the same items in "Rules added / retired" (P3.md:727-728) are not carried (section dropped) |
| MN-09 | Goal 5 / its release note, the four profiles exempt "by gitignore preflight" (P3.md:130 and :147-148) | not carried: the release notes are PR paperwork (dropped) and the Goal was compressed without Goal 5's wording; R13 carries row 13's G3 wording, which the entry does not concern |
| MN-10 | Acceptance 11, the sentence after the gitignore cases ("The hook reads the report and `git check-ignore` relative to its own install location ...", P3.md:639-643) | A11, marked |
| MN-11 | Out of scope, close-commit-repair-orchestrate.py kept (P3.md:490) | not carried: same statement as L-P3-01, in the dropped "Out of scope" section |
| NC-01 (PLAN-v2.md) | PLAN-v2:54 credits "ESCALATION_ACK ... releases nothing" to P3; P3's own statements: Goal 3 (P3.md:124-126) and row 6 (P3.md:293) | R6's ESCALATION_ACK clause, marked (one mark shared with NC-05); Goal 3's sentence not carried (Goal compressed) |
| NC-05 (PLAN-v2.md) | PLAN-v2:442 "The G2 escalation-record stores are removed here"; P3's own statement: row 6 (P3.md:293) | R6, marked |
| MN-03 (PLAN-v2.md) | PLAN-v2:446 and :458 credit the four profile exemptions to gitignore-preflight; P3's own statement: Goal 5 (P3.md:130, :147-148) | not carried: as MN-09 |
| R2-09a (PLAN-v2.md) | PLAN-v2:453, "after the re-dispatched BA writes a newer ticket and context" | not carried: the entry concerns PLAN-v2's own wording; P3 already uses the reverted wording (the re-dispatched BA's SubagentStop), carried unmarked in R17, A3 and A12 |
| PV-18 (PLAN-v2.md) | PLAN-v2:1318-1328, section 15 takeover list naming P3's share | not carried: the entry replaces PLAN-v2's own list with a pointer; P3's already-done list is carried from the long prompt in the "P1b/P1c" extra item and rows R1, R3, R6, R7, R13, unmarked |
| PV-1, PV-2, PV-3, NC-03 (PLAN-v2.md) | PLAN-v2:135, :353, :368, P2's "arm G1-G3" | not carried: they concern PLAN-v2's P2 lines, not a P3 statement; P3's own counterpart is NC-15 |
| reviews/P1b-plan-sync.md, COVERAGE.md, COVERAGE-P9-P11.md subsections | scanned | no entry concerns a P3 statement (NC-52 concerns COVERAGE.md's own list of live-landing acceptances) |

### DO NOT bullets dropped as repeats of _common.md

- "Do not delete a test outside the rule in 'Test dispositions', and do not skip, xfail or quarantine one." Repeats
  _common.md's "Do not skip, disable, xfail, quarantine or delete tests to get green, except deletions your prompt names
  explicitly" (the rule itself is in Rows, extra item "Test dispositions").
- "Do not register harness hooks in your own session, run init (scripts/bootstrap) or a render against your container's
  `~/.claude`, or start a nested `claude`; hooks run only in the sandbox namespace." Repeats _common.md's Context ("never
  install it into your own `~/.claude`, never point your own session at its hooks, never edit your container's
  `~/.claude`") and "Do not run nested `claude` CLI sessions"; the sandbox-only rule is in the Acceptance "Sandbox" note.

### Sections not carried

- Top paragraph "Wave 3 ... in parallel with P2" (merge history, merge commit hashes): history; its merge-order instruction is kept in Dependencies.
- "No owner step (owner, 2026-10-18)": owner quote; its rules are kept as D19, D15, the Goal and A16.
- "P7b" paragraph (P7b's files, none of them P3's): background/history.
- "Files you share with P2": line citations and P2's own changes dropped (background); P3's instructions folded into R2 (commit stage: `commit_detection` unedited), R4, R10 ("change nothing else here") and the "Shared with P2" extra item (switch-read hunks, advisory-log constants, spelling, second PR keeps both sides).
- "Before you start": kept as Dependencies; "say in the PR which base you measured against" dropped as PR paperwork.
- "P1b and P1c (merged before you, 2026-10-24)": owner quote (D25) and dates dropped; instructions folded into the "P1b/P1c" extra item, R1, R2, R3, R6, R7, R10, R13, A11, A18, A20; "listed under Corrections to PLAN-v2" dropped (corrections).
- "Goal" release notes ("Put these release notes in the PR"): PR paperwork (release notes).
- "Owner decisions that govern this phase": owner quotes dropped; rules kept as Owner rulings; the TC rows folded into rows (TC-4 commit stage, TC-5 problem=unanswered, TC-7/TC-8 strict binary, TC-16 in D7 and DO NOT, TC-21 R6, TC-22 R2, TC-40 "Warning and promotion", TC-54 "Test dispositions"); "repeat each row in the PR" and "flag this reading for the reviewer in the PR" (TC-16) dropped as PR paperwork; S#/O# codes dropped (plan cross-reference codes).
- "Background (in the extracted planning documents)": background reading list; its two carry-over lists are folded (P1's T4 into R16, `finding_key` into R6; P8's comment and completeness channel into R3).
- "Corrections to PLAN-v2": corrections to PLAN-v2 and the instruction to list them; the requirements they restate are in R2, R4, R5, R12, R15, R17 and A16.
- "Out of scope": Out of scope.
- "Rules added / retired (expected)": Rules added / retired.
- "Net code cap": kept as the DO NOT cap line and A17; rationale dropped.
- "Effort": Effort.
- "Rollback": Rollback.
- "Branch and pull request": branch, push, one-PR and drive-until-merged rules repeat _common.md; "check `git log --oneline origin/master` again before you ask for review" kept in Dependencies; the PR-body headings (Corrections to PLAN-v2, TC-16 reading, Test-disposition ledger, Live landing, Release notes, Hand-off to P4 and P5) dropped as PR paperwork; the PR title form kept.
- Shared tail "## Context (read once)" to the end: repeats _common.md.

### Totals

- Rows: 15 rows in the long prompt (1-7, 10-17); kept 12, kept-marked 3 (R1, R6, R11), dropped-as-moved 0; rows 8 and 9 absent.
- Acceptance tests: 20 numbers; kept 17, kept-marked 2 (A11, A18), dropped-as-moved 0; A10 absent (deleted placeholder).
- Marks in the short prompt: 7 (Dependencies, R1, R6, R11, "Test dispositions", A11, A18).

## P4

Short prompt: prompts/short/P4.md, 300 lines, 34,544 bytes (long prompt without the shared tail: 797 lines, 95,165 bytes).

### Rows and acceptance tests

| Long item | Short place | Status |
|---|---|---|
| Row 1 (close.md Step 0 and the preflights) | R1 | kept, marked after P1b |
| Row 2 (close.md routing machinery) | R2 | kept, marked after P1b |
| Row 3 (close.md Step 1 and Step 2) | R3 | kept, marked after P1b |
| Row 4 (close.md --force, FORCED, Edge Case 8, rating, scoring, --auto, header) | R4 | kept, marked after P1b |
| Row 5 (commands/commit.md) | R5 | kept, marked after P1b |
| Row 6 (changelog-analyst.md; step7-spec-update.py) | R6 | kept |
| Row 7 (close_rating.py, posttool-close-rating.py, settings.json, test, ledger) | R7 | kept, marked after P1b |
| Row 8 (G2 legacy path, e2e, prompt-workflow.py, dev.md, dev-command.md) | R8 | kept |
| Row 9 (advisory JSONL sinks of G1, G2, G3 and the loop) | R9 | kept, marked after P1b |
| Row 10 (posttool-overnight-loop.py terminal checks) | R10 | kept |
| Row 11 (scripts/todo/close.py) | R11 | kept, marked after P1b |
| Row 12 (hooks/lib/command_span.py) | R12 | kept |
| Row 13 (tests) | R13 | kept |
| Row 14 (README.md, ARCHITECTURE.md, ledger, commit.md Related) | R14 | kept |
| Acceptance "Sandbox" note | Acceptance tests, "Sandbox" paragraph (line 169) | kept |
| Acceptance 1 (unit suite) | A1 | kept |
| Acceptance 2 (greps) | A2 (the long grep -nE split into two greps whose union is the same pattern set) | kept |
| Acceptance 3 (todo list) | A3 | kept |
| Acceptance 4 (/close and /commit complete the cycle) | A4, cases (a)-(k) | kept, marked after P1b |
| Acceptance 5 (waits) | A5 | kept |
| Acceptance 6 (rating question) | A6 | kept |
| Acceptance 7 (rating producer) | A7 | kept |
| Acceptance 8 (predicates) | A8 | kept |
| Acceptance 9 (--auto rating) | A9 | kept |
| Acceptance 10 (capability facts) | A10 | kept |
| Acceptance 11 (overnight loop) | A11 | kept |
| Acceptance 12 (legacy deletions) | A12 | kept |
| Acceptance 13 (advisory sinks) | A13 | kept |
| Acceptance 14 (changelog-analyst and Step 8) | A14 | kept |
| Acceptance 15 (settings and claims) | A15 | kept |
| Acceptance 16 (armed replay) | A16 | kept |
| Acceptance 17 (H-Q5 and H-Q3) | A17 | kept |
| Acceptance 18 (no regression) | A18 | kept |
| Acceptance 19 (live landing) | A19 | kept |
| Acceptance 20 (net code) | A20 | kept |
| Acceptance 21 (D24 table) | A21 | kept |
| Acceptance 22 (never fail) | A22 | kept |
| Scope "### Step 0, the re-dispatch and the waits": Step 0 bullet | R1 (call, retry, OPERATION_STALLED rule, rule stated in Step 0) | kept |
| Scope "### Step 0, ...": data fields bullet | R3 (fields, one run, added in the resolver); A2 (grep count 1 per file) | kept |
| Scope "### Step 0, ...": Close-QA findings bullet | Rows, extra item "Routes" (journal writer, round's own QA dispatch, re-run, fresh round); Choices, line 162 (experiment) | kept |
| Scope "### Step 0, ...": task with no cycle artifacts | Rows, extra item "Routes" | kept |
| Scope "### Step 0, ...": late-repair route | Rows, extra item "Late-repair" | kept, marked after P1b |
| Scope "### Step 0, ...": the waits | Rows, extra item "Waits" | kept, marked after P1b |
| Scope "### Step 0, ...": /commit --dry-run | R5 (stays a preview); Choices, line 165 (incomplete close stage) | kept |
| Scope "### The native rating (D9, D9a, D9b)" | R7 (Step 4, close_rating.py, hook, no consumer) | kept, marked after P1b |
| Scope "### Capability facts the rating needs (no owner step)" | Rows, extra item "Capability facts" (fallback and conservative branches); A10 (sources, quotes, redacted shapes) | kept |
| Scope "### The overnight loop reset (TC-13)" | R10 | kept |
| Scope "### Live landing (owner, 2026-10-18)" | A19 (every case); DO NOT "delete an orphaned script"; D15 | kept |
| Scope "### Technical choices you make" | Rows, "Choices to decide by experiment" (lines 155-167) | kept |
| Technical choice: where Steps 1-3 and commit.md get the data fields | Choices, line 165 ("data fields' source") | kept |
| Technical choice: OPERATION_STALLED retry rule, wording and options of each wait | Choices, line 165 ("stall retry; waits") | kept |
| Technical choice: how close-QA findings reach the writer (journal experiment) | Choices, line 162 ("Journal route") | kept |
| Technical choice: late-repair entry; whether the analyst's R4 exception stays | Choices, line 165; Rows "Late-repair" and R6 carry the D10 marks | kept |
| Technical choice: --dry-run under an incomplete close stage | Choices, line 165 | kept |
| Technical choice: rating source channel, row shape and lock, dedup read, TC-27/29/30 branches | Choices, line 165 ("rating channel, row, lock, dedup, capability branches") | kept |
| Technical choice: obligations() and session_families() semantics | Choices, line 165 ("command_span methods") | kept |
| Technical choice: whether the loop prints gaps; format, time bound, exit-2 continuation | Choices, line 164 ("loop print") | kept |
| Technical choice: outcome of G2's M4 handler and the e2e flag gate | Choices, line 165; R8 carries the D10 marks | kept |
| Technical choice: the advisory branches' stderr line | Choices, line 165 | kept |
| Technical choice: STEP7_* replacement names (and trace variable) | Choices, line 165 | kept |
| Technical choice: whether the loop keeps the terminal_gate_blocked_reason pop | Choices, line 165 ("the pop"); R10 | kept |
| Technical choice: anything else you decide | Owner rulings, D10 line (every pure technical choice, a regression test each) | kept |
| Decided by experiment H-Q5 | Choices, line 156; A8, A9, A17 | kept |
| Decided by experiment H-Q3 | Choices, line 158; A17 | kept |
| Default Q7 (decided by sandbox experiment) | Choices, line 160; A4 (g) | kept |
| [INFERRED] reader returns the lane-QA todo step (Goals 1-2, acceptance 4) | Choices, line 164; A4 (c) | kept |
| "If the experiment cannot be run: the default" (H-Q5, H-Q3) | Choices header, line 155 | kept |

Other long-prompt sources folded into the short prompt (not required as table lines, listed for traceability):
- "Before you start" checks: Dependencies list; "find each site on that base": Dependencies last line; "say in the PR which base": dropped (PR paperwork).
- "Interfaces you consume": Rows, extra item "Interfaces you consume" (read each on the base, use it as merged, build no second one; the interfaces named: P3's disposition call with arbitration and `pass_with_exceptions` retired, P1b E3's reader, P2's overnight.py parts, loop reset, seedless steps 2-4, harness-home channel and printed roots, P1's command_span.py, stop_contract.py, producer-question artifact, `# STUB:` markers); the output forms are folded where used (R1 the call and "use the flags P3 shipped", R5 `--stage close` meaning, Routes the reader's two returns, R10 P2's loop parts, R12 command_span); "say so in the PR" dropped (PR paperwork).
- "P1b and P1c (merged before you)": the routes P1b row 10 made (Routes item and A4 cases), the kept no-obligation paths (R8), "only what P1b's PR left" (R8, R9), P1b row 7's Step 5 call (R5), P1c's X5 (R1), "P1b's map governs ... CI check stays green" (Rows item "Before you start"), merge rule (D25, A22). The "Already done by P1b (verify each on your base and do not redo it)" list: Rows, extra item "Already done by P1b" (class-b/c re-checks with their parts, both routing tables and their "no code table" claims, marked for PV-5, close-force flag readers, /close's QA re-arming, the spec-update temp note, the loop's terminal lanes, advisory sinks, one channel per verdict, Step 8's continuation write and `artifact_role`, E14's kept selection, and "keep the close.md, commit.md and changelog-analyst.md fixes P1c's row 18 lists"); its consequences: STEP7_* rename and Step 8's stage 4 only "where P1b's PR left them" (R5, R6, A14), the rating after the session summary if P1b deleted the temp note (R7, A6); the reader and the D24 table (your before) are in Dependencies and A21.
- Goal 1-8: folded into R1, R5, Routes, Waits, R7, R10, R8/R9, A19, A21; the Goal section is one line.
- Owner decisions section: one ruling bullet per decision id (D2, D3, D4/D4c, D6a, D7, D8, D9/D9a/D9b, D10, D11/D14, D12, D15, D17, D18/D19, D20, D21, D22, D23, D24, D25); quotes, S/O codes and history dropped. Producer-side (O10, O12) folded into DO NOT bullet 1; the changelog-analyst cleanliness bullet (O3, O4) folded into R6 (keep staging, cleanliness and attribution rules).
- "Defaults applied without asking": H-Q6 (AFK is "asked, no rating"; no code) covered by A7 (AFK, 0 rows) and A8 (rating_asked true on AFK), its "no code" sentence dropped; H-Q7 (free text not stored) by A7 and DO NOT bullet 5; Q7 by Choices line 160 and A4 (g); Q-D7b by R5; H-Q8 by R7 (first rating wins); H-Q9 by the D9 ruling; "rating required only in /close spans" by R7. The "list them under Decided without asking" instruction dropped (PR paperwork).
- TC list (TC-13, 16, 21, 22, 24, 27-31, 37, 54): folded into R10, Routes/R2, R1/R5, R5, R7, Capability facts, DO NOT (no unregistering), R13; "repeat each in the PR" dropped (PR paperwork); TC-21's "the disposition does not read escalation records" dropped (P3's merged behaviour, interface description).
- Scope intro: location bases (citations, history) and the suggested commit order (a suggestion, not a requirement) dropped; "Python 3.10, standard library only" kept in Rows item "Before you start".
- Header: wave history, merge commit history beyond the start check, P5's dependency on P4, the owner quote of 2026-10-18 dropped; P7b's files fence kept in "Before you start"; "rollback is a revert by the reviewer" kept in D18/D19.
- Row 8 "close-QA's stop no longer re-checks the cycle's qa-report ... say so in the PR" dropped as explanation plus PR paperwork; R10 "the Stop after end_time is P5's; stop-obligation-gate.py reads CLAUDE_OBLIGATION_TERMINAL until P5" dropped as scope note covered by DO NOT (hooks/stop-*.py are P5's); row 5 "commit.md keeps jq in the late-repair guard and attribution slice" dropped (a correction to PLAN-v2); row 12's P1 carry-over fact ("command_span.py ships only active_span() and Span") dropped as P1 history, "add if missing" kept.

### After-P1b entries

| Entry | Long place | Short place or reason not carried |
|---|---|---|
| F-P4-11 | P4.md:296, row 1 (aggregate producer parenthetical) | R1, marked |
| F-P4-12 | P4.md:297, row 2 (mapping rows, source_check list and closed cause set) | R2, marked |
| F-P4-13 | P4.md:300, row 5 (artifact-to-role routing, artifact_role) | R5, marked after "artifact_role" |
| L-P4-04 | P4.md:306, row 11 ("Delete the forced list and `_is_forced`") | R11, marked |
| L-P4-03 | P4.md:337, Step 0 subsection, late-repair bullet (re-run `verify-disclosure`) | Rows item "Late-repair", marked |
| MN-13 | P4.md:334-337, same late-repair statement | Rows item "Late-repair", same mark as L-P4-03 |
| MN-12 | P4.md:348-350, waits (commit.md bulk-capability-absent wait) | Rows item "Waits", marked |
| NC-24 | P4.md:304, row 9 (sinks P1b row 3 and E12 already removed); :766 Net code cap credit | R9, marked; the Net code cap's crediting sentence is not carried (rationale), the DO NOT cap line has only the number and scope |
| NC-25 | P4.md:298, row 3 ("the 1b still-missing finding") | R3, marked |
| NC-26 | P4.md:299, row 4 (audit-log append may stay); P4.md:211, D15 bullet (commit.md Step 4's audit line stays) | R4, marked; the :211 statement is carried in R5 ("Step 4's audit line"), marked |
| NC-27 | P4.md:379-383, "The native rating" (append_rating's read of the log) | R7, marked after "first rating per task wins (read under the lock)" |
| F-P4-15 | P4.md:623, acceptance 4 (deleted qa-report case) | A4 (b), marked |
| F-P4-17 | P4.md:639, acceptance 4 (close-QA finding on a dev file) | A4 (h), marked |
| F-P4-14 | P4.md:530-532, "Out of scope" (P9's work list) | not carried: "Out of scope" section dropped (brief drop category) |
| NC-23 | P4.md:524, "Out of scope" (reader called P3's work) | not carried: "Out of scope" section dropped |
| PV-5 | PLAN-v2.md:474; the same wording at P4.md:81 ("both routing tables and their "no code table" claims", "Already done by P1b") | Rows item "Already done by P1b", marked after "both routing tables and their "no code table" claims" |
| NC-50 | COVERAGE.md C4 (:128) and fix 3 (:213-220) | targets COVERAGE.md, not the long prompt; the P4 statement it touches (row 9's sink deletion) carries NC-24's mark in R9 |
| NC-52 | COVERAGE.md :71 (live-landing acceptances) | targets COVERAGE.md; no statement of the long prompt concerned; no mark |

Scanned with no P4 entry: "### reviews/P1b-plan-sync.md" (S1, S13, S35, S37, S38), "### COVERAGE-P9-P11.md" (R2-02b, R2-03), and the other "### PLAN-v2.md" entries (PV-18 names P4's share of P1b's takeover in PLAN-v2 section 15; it rewrites PLAN-v2.md text only, not the long prompt's "Already done by P1b" statements, so no mark).

### DO NOT bullets dropped as repeats of _common.md

- "Do not register harness hooks in your own session, run init (scripts/bootstrap), a render or any hook against your container's `~/.claude`, or start a nested `claude`. Hooks run only in the sandbox namespace." Repeats _common.md "Context" (never install the harness into your own `~/.claude`, never point your session at its hooks, never edit your container's `~/.claude`) and "DO NOT" (no nested `claude` sessions); "hooks run only in the sandbox" is also kept in the short prompt's Sandbox paragraph.

### Sections not carried

- Header wave history, merge commit history and the 2026-10-18 owner quote: history, owner quote (the start checks and the no-owner-step rule are kept).
- "Owner decisions that govern this phase", quoted owner words and planning-note codes (O#, S#): owner quotes, cross-reference codes (rulings kept as D lines).
- Scope intro (location bases, "Locations are at f8c18c2", suggested commit order): citations, history; the commit order is a suggestion, not a requirement.
- Scope table "Location (f8c18c2)" column: file:line citations.
- "## Background (in the extracted planning documents)", including "Carry-overs from P1" and "Problem ids covered": background reading list, history, cross-reference codes (the carry-over's instruction, add what you consume, is in R12).
- "Corrections to PLAN-v2" list: corrections to PLAN-v2 and the instruction to list them.
- "## Out of scope": Out of scope.
- "## Rules added / retired (expected)": Rules added / retired.
- "Effort: L (about 3.5 days)": Effort.
- "## Rollback": Rollback.
- "## Branch and pull request": branch rules repeat _common.md; extra PR headings (Decided without asking, Corrections to PLAN-v2, Capability facts for P5, Now unreferenced, Live landing, Release notes) are PR paperwork and hand-off sections; the PR title form is kept.
- "## Context (read once)" to the end: the shared tail, repeats _common.md.

### Totals

Rows: 6 kept, 8 kept-marked, 0 dropped-as-moved (14 of 14). Acceptance tests: 21 kept, 1 kept-marked (A4), 0 dropped-as-moved (22 of 22). Marks in the short prompt: 14.

## P5

Short prompt `harness-repair-plan/prompts/short/P5.md`: 300 lines, 35,515 bytes (long prompt without the shared tail:
901 lines, 114,017 bytes; 31 %). After the fixer pass (verify-P5-P6-P9.md, P5 findings 1-14), the Rows and Acceptance
tests sections are wrapped at 140 characters (the fixer brief's allowance); the other sections stay at 120.

### Rows and acceptance tests

| Long item | Short place | Status |
|---|---|---|
| Row 1 | R1 | kept |
| Row 2 | R2 | kept, marked after P1b |
| Row 3 | R3 | kept |
| Row 4 | R4 | kept |
| Row 5 | R5 | kept |
| Row 6 | R6 | kept |
| Row 7 | R7 (with "The gate" folded in) | kept |
| Row 8 | R8 | kept, marked after P1b |
| Row 9 | R9 | kept, marked after P1b |
| Row 10 | R10 | kept |
| Row 11 | R11 | kept, marked after P1b |
| Row 12 | R12 | kept |
| Row 13 | R13 | kept, marked after P1b |
| Row 14 | R14 | kept, marked after P1b |
| Row 15 | R15 | kept, marked after P1b |
| Row 16 | R16 | kept |
| Row 17 | R17 | kept |
| Row 18 | R18 (two marks) | kept, marked after P1b |
| Row 19 | R19 | kept |
| Row 20 | R20 | kept |
| Row 21 | R21 | kept, marked after P1b |
| Row 22 | R22 | kept |
| Acceptance 1 | A1 | kept |
| Acceptance 2 | A2 | kept, marked after P1b |
| Acceptance 3 | A3 | kept |
| Acceptance 4 | A4 | kept |
| Acceptance 5 | A5 | kept |
| Acceptance 6 | A6 | kept |
| Acceptance 7 | A7 | kept |
| Acceptance 8 | A8 | kept |
| Acceptance 9 | A9 | kept |
| Acceptance 10 | A10 | kept |
| Acceptance 11 | A11 | kept |
| Acceptance 12 | A12 | kept, marked after P1b |
| Acceptance 13 | A13 | kept, marked after P1b |
| Acceptance 14 | A14 | kept |
| Acceptance 15 | A15 | kept |
| Acceptance 16 | A16 | kept |
| Acceptance 17 | A17 | kept |
| Acceptance 18 | A18 | kept |
| Acceptance 19 | A19 (with row 16 (b)'s report wording) | kept |
| Acceptance 20 | A20 | kept |
| Acceptance 21 | A21 | kept, marked after P1b |
| Acceptance 22 | A22 | kept |
| Acceptance 23 | A23 | kept |
| Acceptance 24 | A24 | kept |
| Acceptance 25 | A25 (carries the D24 table) | kept |
| Acceptance 26 | A26 | kept |
| Sandbox note before the tests | Acceptance tests, "Sandbox" paragraph | kept |
| Scope: The gate (hooks/stop-command-gate.py) | R7: order (1)-(7), "Todo half", "Predicates" bullets, "Block text"; the seven do-not-port items in R7's first sentence | kept |
| Scope: Arming and live landing (owner, 2026-10-18; D15) | Rows, extra item "Arming"; R21 (mode per arming option); A21 | kept |
| Scope: Test dispositions | Rows, extra item "Test dispositions"; R22 (stub-subject files) | kept |
| Scope: Technical choices you make | Rows, "Choices to decide by experiment", lines 1-6 | kept |
| Scope: Corrections to PLAN-v2 | dropped as a section; items below | kept (instructions only) |
| Decided by experiment: Arming timing | Rows, extra item "Arming"; Choices, line 1 | kept, marked after P1b |
| Decided by experiment: Q1 (todo scripts) | Rows, extra item "Todo scripts"; Choices, line 1 | kept |
| Goal 6 replay (`/do <task-id>` kept or not) | R15; A5 (with P1's mid-turn UserPromptSubmit carry-over); Choices, line 1 | kept |
| Goal 9 (D24): deciders P1b retired, to verify | Rows, extra item "D24 deciders"; D24 ruling; A25 | kept |
| Commit order paragraph | Rows, extra item "Commit order" | kept |
| Technical choice: deny's path reading, unresolved subagent, removed allow prefixes | Choices, line 2 | kept |
| Technical choice: deletion and rename detection (row 2) | Choices, line 3 | kept |
| Technical choice: engine deny location, harness-home resolution (row 3) | Choices, line 3 | kept |
| Technical choice: trailer message reading (row 4) | Choices, line 1 | kept |
| Technical choice: scheduled-prompt rule needed, with evidence (row 5) | Choices, line 2 | kept |
| Technical choice: each commit-guard precision fix (row 6) | Choices, line 1 | kept |
| Technical choice: minted task id read, /merge and /push stable facts | Choices, line 4 | kept |
| Technical choice: mode hand-over, launcher flag, fixed failure codes | Choices, line 5 | kept |
| Technical choice: write-set normalisation, do-branch transcript argument | Choices, line 4 | kept |
| Technical choice: lowered-timeout testing with no agent knob | Choices, line 5 | kept |
| Technical choice: what the Codex path keeps (row 20) | Choices, line 2 | kept |
| Technical choice: prototype port kept, dropped, added | Choices, line 2 ("port (A1)") | kept |
| Technical choice: anything else | Choices, line 4 ("the rest (its test)") | kept |
| Other D10 choices named in rows (transcript neighbour files, GATED/CONTROL path and module, bare /merge Step 0 fact, terminal hand-over) | Choices, lines 3, 4, 5 | kept |

### Corrections to PLAN-v2 items (where each instruction went)

| Item | Where its instruction went |
|---|---|
| 1. G2 records live in `escalations/`, `escalation-admissions/` | nothing beyond row 2 (R2 names the subdirectories) |
| 2. `extract_bash_write_paths` reports no `rm`; deletion coverage added | nothing beyond row 2 (R2 denies deletes and renames) |
| 3. G4-only remainder deletion can orphan `_validate_artifact_status`, `_DEV_REGISTRY_TOKEN_RE` | nothing beyond row 11 |
| 4. The launcher relays stdout as well as stderr | nothing beyond row 10 |
| 5. The Codex path keeps its bookmark state | nothing beyond row 20 |
| 6. No bulk grants with null task_id; the bulk route is the sentinel | nothing beyond row 4 |
| 7. `test_todo_validate*.py`, `test_git_privilege_guard*.py` do not exist | R22 names the guard's real test files (and the rest of A1's set); PLAN-v2's names are not used |
| 8. The write set covers every /do span of the task; MultiEdit counts | nothing beyond row 8 |
| 9. The dev predicate requires the span's own minted task | nothing beyond row 7 (R7 dev predicate) |
| 10. Q5 answered; Arming timing decided again by experiment | D4c ruling (no API-error code); Rows extra item "Arming"; the instruction to record Q5 in the PR is paperwork, not carried |
| 11. Section 13's coordinator row is P1's delivery, kept here | nothing beyond row 9 and acceptance 13 |
| 12. README limits lines row 6 makes false go to "Out of scope, found" for P9 | carried into R6 ("README limits it falsifies: OOS") |
| 13. "merge anyway" does not exist | nothing beyond row 14 (R14: no "merge anyway") |
| 14. Dev-overnight families come from dispatches; report planned pipelines | carried into R7's dev-overnight predicate ("planned, undispatched pipelines: OOS") |

### After-P1b entries

| Entry | Long place | Short place or reason not carried |
|---|---|---|
| L-P5-01 | P5.md:265, D15 bullet ("the coverage phase for /spec ... keep working") | Owner rulings, D15, marked |
| L-P5-02 | P5.md:350, row 9 ("only coverage and completion may block") | R9, marked |
| F-P5-11 | P5.md:362, row 21 location (do.md `blocked` bullet, the skeleton message) | R21 ("`blocked` leaves do.md and the skeleton message"), marked |
| L-P5-03 | P5.md:607, "Out of scope" (/spec coverage phase unchanged) | not carried: "Out of scope" is dropped |
| F-P5-15 | P5.md:747-749, acceptance 12 after-end_time cases | A12, marked (wording kept; the wake case the entry adds is not applied) |
| L-P5-04 | P5.md:753, acceptance 13 /spec coverage case (old text no longer occurs) | A13, marked |
| R2-05 | P5.md:342, row 2 ("P3 row 6 removes their writer" and its `git grep` check) | R2, the check, marked; the "P3 row 6 removes" clause is history, not carried |
| NC-28 | P5.md:352, row 11 ("use the name P3 merged") | R11, marked |
| NC-29 | P5.md:354, row 13 (todo force-complete); P5.md:845, retired list | R13, marked; the retired list is not carried ("Rules added / retired" dropped) |
| NC-30 | P5.md:355, row 14 ("no push-gate token" abort) | R14, marked |
| NC-31 | P5.md:840, retired list (stop-obligation-gate) | not carried: "Rules added / retired" dropped |
| NC-32 | P5.md:274 (S9 [pending, completed]) | Owner rulings, S9, marked |
| NC-32 | P5.md:292 (Arming experiment, pending skeleton) | Rows, extra item "Arming", marked |
| NC-32 | P5.md:795 (acceptance 21, pending skeleton) | A21, marked |
| NC-32 | P5.md:356 (row 15, `do.status` pending) | R15, marked |
| MN-14 | P5.md:115 (row 20's step lookups in posttool-subagent-track) | R18 ("Gate 4, the wake rule, R20's lookups use it"), marked; the restored whole-list clause of the pairing rule sits in the same marked sentence (no new mark) |
| MN-15 | P5.md:265 and :607 | D15 marked (same statement as L-P5-01); :607 not carried ("Out of scope" dropped) |
| NC-07 (PLAN-v2.md) | PLAN-v2.md:571, P5 row: Gate 4 "after step i went in_progress" | R18 (same statement), marked |
| NC-08 (PLAN-v2.md) | PLAN-v2.md:589, P5 grep for D4c misses the reader's module | A2's grep (same statement), marked |
| MN-05 (PLAN-v2.md) | PLAN-v2.md:536, P5 "After P1b and P1c": P1c row 17 pairing in the subagent-call recorder | R18, same mark as MN-14 |
| NC-13 (PLAN-v2.md) | PLAN-v2.md:1256, section 13 P5 row: add back what command_span lacks unless P4 did | R8 ("If command_span lacks ...  unless P4 did"), marked; the entry's other rows (:1237, :1252-1254, :1264) are other phases |
| NC-04 (PLAN-v2.md) | PLAN-v2.md:272, :1101, drift test (P1 row, TC-35) | not about a P5 statement; no mark |
| NC-11, PV-13 (PLAN-v2.md) | PLAN-v2.md:1092, TC-26 cites prompt-workflow.py:1427 | not carried: TC rows and citations are dropped |
| PV-15 (PLAN-v2.md) | PLAN-v2.md:1192, metrics V7a row ("after P5") | not carried: a PLAN-v2 metric row; no P5.md statement carried |
| PV-21 (PLAN-v2.md) | PLAN-v2.md:1158, not-doing bullet on the /spec coverage phase | not carried (P5.md's counterpart is "Out of scope" :607) |
| PV-9, PV-20 (PLAN-v2.md) | PLAN-v2.md:704 (P7 not-doing), :1350-1353 (section 15 restating P1b's corrections) | not about a P5 statement; no mark |

Subsections "### reviews/P1b-plan-sync.md", "### COVERAGE.md" and "### COVERAGE-P9-P11.md": no entry about P5.

### DO NOT bullets dropped as repeats of _common.md

- "Do not register harness hooks in your own session, run init (scripts/bootstrap) or a render against your container's
  `~/.claude`, or start a nested `claude`; hooks run only in the sandbox namespace." (_common Context and DO NOT; the
  sandbox note keeps "not your `~/.claude`").
- Parts of kept bullets: "add a check, scan or routing table to /close, /commit or the changelog-analyst" (_common
  principle 1); "a hook file settings.json registers" (_common principle 5; "a running session may have registered" kept);
  "(TC-32; code, tests and docs name the switch)".

### Sections not carried

- Shared tail, "Context (read once)" to the end: repeats `prompts/_common.md`.
- Opening paragraphs (wave history, base commit, files earlier phases changed): history and citations; the merge base
  stays in the start checks, untouched files are in R16 and DO NOT; the move of stop_contract's GATED_COMMANDS and
  CONTROL_COMMANDS to the tracked JSON file is in R10.
- "No owner step (owner, 2026-10-18)": owner quote; its rules are in D18/D19, R16 and "Arming".
- "Before you start": start checks become "Dependencies"; the instruction to read P1-P4 PR bodies is replaced by the
  facts named in the rows (window_open, closeout_gaps, timelock_released, P2's locator, P3's disposition function and do
  branch, the DDR, rating_required, rating_asked, P4's headless fact).
- "P1b and P1c (merged before you)": folded into R1, R2, R4 (the quoted `-F` read), R5, R7, R8, R9, R10, R13, R18, R20,
  D25, A26 and the extra items "Pending", "Block classes", "D24 deciders"; dates and history dropped.
- Goal bullets 1-9: folded into Goal, rulings and rows; Goal 9's verification list is the extra item "D24 deciders"
  (the D24 ruling stays one line).
- Release notes: paperwork (brief: no release notes).
- Owner decisions section: owner quotes and O-codes dropped; rules kept as "Owner rulings".
- "Decided technical choices this phase implements" (TC list, "repeat each row in the PR"): cross-reference codes and
  paperwork; the rules are in the rows.
- "Scope" intro (location shifts at f8c18c2): citations and history; the commit order kept.
- "Corrections to PLAN-v2": corrections to PLAN-v2 (items mapped above).
- "Background": reading list; its P1 carry-overs folded into R1, R5 (the measured CronCreate record shape and its
  corrected source, reviews/P1-PR5-review-followup.md), R8, R11, R18 and A5 (the mid-turn UserPromptSubmit question).
- "Out of scope": dropped; its instructions are in R1 (arming blockers), R6 and R17 (P9 prose); the A4.c identity-files
  note ("note what you see") is not carried.
- "Rules added / retired (expected)": dropped (brief's list).
- "Net code cap": kept as the last DO NOT bullet; "Effort": dropped.
- "Rollback": dropped; "rollback is the reviewer's revert" stays in D18/D19.
- "Branch and pull request": title form kept; PR body headings (Arming, corrections, test-disposition ledger, live
  landing, release notes, capability facts, carry-over for P10, hand-off to P6) dropped as paperwork; the reachability
  proofs travel with A1 and A22, the D24 table with A25, "what a running session must finish" with A21.

### Totals

Rows: 22 kept (13 kept, 9 kept and marked), 0 dropped as moved. Acceptance tests: 26 kept (22 kept, 4 kept and marked),
0 dropped as moved. After-P1b marks in the short prompt: 17.

### Details condensed to meet the 300-line limit (judgment calls, for review)

Items the fixer pass restored (verify-P5-P6-P9.md, P5 findings 1-14) are no longer listed here. Still condensed:

- R1: the name `resolve_own_obligation`; "(P6 tightens it to agent_type)"; "the deny overrides directory and wildcard
  prefixes on declared paths"; dev.md's example writes (spec_path patch, refined/iter context, spec edits).
- R2: the graphify sidecar path; "a deny you add retires with the stores"; "reads stay allowed"; "add `rm` and
  rename-source coverage (extractor or hook)" (the deny of deletes and renames stays).
- R4: commit_pipeline.py if needed. R5: "where the rule lives: your choice".
- R7: lazy imports; "P1b's CI check stays green" (A10 keeps it); dev: "never the bookmark", "no such record: say so and
  choose a hook-written fact"; do: "a missing sidecar blocks nothing" (A4 keeps it); dev-overnight: "problem=unanswered",
  `state.worktree_path`; merge: "an analyst prompt naming another tip changes nothing" (A6 keeps it); block text: "a
  decision the request, the code or a sensible default cannot settle".
- R8: "normalised repo-relative paths" (in Choices); "ships advisory, arms with the gate".
- R9: "P7's refused-snapshot notice keeps reaching the user"; "P1's auto_commit phase and first-failure cleanup skip
  stay" (A13 keeps the auto_commit-failure case).
- R11: "verify P1b's stub, do not redo". R12: "P7's clean form".
- R13: "break-overnight-lock.py may record cancelled_by_user, which no gate reads" (R7 now excludes the
  `cancelled_by_user` release).
- R14: push.md's "nothing ahead" site and "nothing ahead of upstream already meets the push predicate"; "the human types
  it"; "a question ends no turn" (D3/D23 keep the rule).
- R16: "page unreachable: say so". R17: the flags of check-enforcement-evidence.py and the ledger truths listed.
- R20: prompt-workflow.py's function names in the deletion scope. R21: "a /do that cannot proceed asks with
  AskUserQuestion".
- R22: "pretool-todo-validate has no test file" and PLAN-v2's non-existent test names (a correction to PLAN-v2).
- D24 deciders: "on your base" after "verify each is gone".
- Block classes: the definitions of G and D. Arming: "option 2 needs no shim", "ungated sessions are never blocked" (A21
  keeps it).
- Rulings: D4's list of exits and Esc; D20's "in the window only /stop and off release"; D18/D19's "/stop and off are no
  step of this phase". Dependencies: "no older base"; "re-check git log before review"; checks restated as what must
  hold rather than as commands.

Wording tightened in the fixer pass to make room (no requirement dropped): R1 ("declarer, role from the DDR"; message
"path, `role`"), R5 ("P1's facts"), R10, R22 (file names relative to hooks/tests/ unless under tests/), Arming, the
Sandbox paragraph ("a sandbox of origin/master"), A2 (the `agent_id` case moved after the grep line), A4, A8, A26 ("green
on the PR head" for "on your branch"), the PR paragraph (`Owner steps: none.` first, as in the sibling short prompts),
the Choices regrouped into five lines (every item kept), and the blank line before the last line removed (as in the
sibling short prompts).

## P6

Short prompt `harness-repair-plan/prompts/short/P6.md`: 300 lines, 31,892 bytes (long prompt body before the shared
tail: 815 lines, 85,292 bytes; about 37 %).

### Rows and acceptance tests

| Long item | Short place | Status |
|---|---|---|
| Row 1 (agent_resolver.py, role order) | R1 | kept, marked after P1b |
| Row 2 (pretool-cp-checkin.py, no index write) | R2 | kept, marked after P1b |
| Row 3 (artifact-contract-enforce `main`, `expected_role`) | R3 | kept, marked after P1b |
| Row 4 (e2e, codex-enforce, skill ledger, hook_ledger, overnight guard) | R4 | kept |
| Row 5 (`_run_downstream_wires`, ENTANGLED, journal-view sidecar) | R5 | kept, marked after P1b |
| Row 6 (agents/dev.md rule) | R6 | kept |
| Row 7 (agents/qa.md Step 5 deletion) | R7 | kept |
| Row 8 (commit grant binding) | R8 | kept |
| Row 9 (push and merge grant binding, tool-policy) | R9 | kept, marked after P1b |
| Row 10 (payload builders with top-level `subagent_type`) | R10 | kept |
| Row 11 (new and changed tests) | R11 | kept |
| Acceptance 1 (unit suite) | A1 | kept |
| Acceptance 2 (role order, unit) | A2 | kept |
| Acceptance 3 (sentinel spoof T2) | A3 | kept |
| Acceptance 4 (QA without registration T1a) | A4 | kept |
| Acceptance 5 (unlisted types, never-registered agents) | A5 | kept, marked after P1b |
| Acceptance 6 (index readers keep their cycle) | A6 | kept |
| Acceptance 7 (G2 role binding) | A7 | kept |
| Acceptance 8 (grants) | A8 | kept |
| Acceptance 9 (T6 replay, warning commit) | A9 | kept |
| Acceptance 10 (promotion commit and variants) | A10 | kept |
| Acceptance 11 (prose greps) | A11 | kept |
| Acceptance 12 (F3.a) | A12 | kept |
| Acceptance 13 (warning, then promotion; five-sandbox replay) | A13 | kept |
| Acceptance 14 (static diff) | A14 | kept |
| Acceptance 15 (personal values) | A15 | kept |
| Acceptance 16 (no regression) | A16 | kept |
| Acceptance 17 (live landing) | A17 | kept |
| Acceptance 18 (net code) | A18 | kept |
| Acceptance 19 (one producer per artifact, D24 table) | A19 | kept |
| Acceptance 20 (never fail, P1c suite and fault replays) | A20 | kept, marked after P1b |
| "Sandbox" note before the tests | Acceptance tests, "Sandbox" paragraph | kept |
| Scope subsection "File-list authorship (A3.a, TC-46, TC-40)" | Rows, extra item "File-list authorship (A3.a)" (Where, W/N, Inheritance, D and rules, message and commits, not covered) | kept |
| Scope subsection "Role identity (A4.a)" | R1 (only role reader, fixed order, older-CLI fallback, leave cp-enforce, cp-state-write-guard and G1); R2 (index no longer a role source, FIRST ACTION deletion, old-CLI statement); R9 (unlisted roles, never-registered roles and the replay of their documented writes) | kept |
| Scope subsection "Grant binding (A4.d)" | R8 (commit); R9 (push and merge, removal, Chain-B sentinel) | kept |
| Scope subsection "Harness syntax predicate (F3.a)" | Rows, extra item "Harness syntax predicate (F3.a)" | kept |
| Scope subsection "Live landing" | D15 (no crash, block only by promoted checks, via A17); R2 (old index files never beat a CLI role); R4 (pre-pull cycles still resolve); R9 (unlisted roles; analysts keep documented steps); A17 | kept |
| Scope subsection "Technical choices you make" | Choices, lines 161-171 (one line per item) | kept |
| Technical choice: correction 1's code cost and any cap raise | Choices, line 161 | kept |
| Technical choice: identity helper's signature and where the meta lookup lives | Choices, line 162 | kept |
| Technical choice: dormant general-purpose row under the chosen option | Choices, line 163 | kept |
| Technical choice: generalised write-set reader's signature | Choices, line 164 | kept |
| Technical choice: inheritance search (where, bound, stderr line) | Choices, line 165 | kept |
| Technical choice: path canonicalisation, excluded namespaces, edge cases | Choices, line 166 | kept |
| Technical choice: which MCP or browser tools count as named | Choices, line 167 | kept |
| Technical choice: A3.a message format and warning line | Choices, line 168 | kept |
| Technical choice: F3.a file selection, bash timeout, warning line | Choices, line 169 | kept |
| Technical choice: push and merge grant binding beside P5-a's deny | Choices, line 170 | kept |
| Technical choice: rows correction 11 corrects and their replay | Choices, line 171 | kept |
| Technical choice: anything else you decide | Owner rulings, D10 | kept |
| "Decided by experiment" item 1 (general-purpose subagents) | Choices, lines 155-160 | kept |

### Corrections to PLAN-v2 (section dropped as such; where each instruction went)

| Correction | Where its instruction went |
|---|---|
| 1 (index readers take their cycle from the obligation; no index write when `agent_type` present; pre-pull entries only for payloads with no obligation; cap rises by the measured amount) | R4, R2; cap in DO NOT and A18; Choices line 161 |
| 2 (a role the policy does not list keeps today's behaviour) | R9 (unlisted-role sentence); nothing beyond A5 otherwise |
| 3 (the general-purpose row exists, never applied) | Choices, lines 155-160 (the experiment); nothing beyond that |
| 4 (`agent_type` without `agent_id` is the main agent) | nothing beyond R1 and A2/A5; "quote the hooks reference with the date read" dropped as PR paperwork |
| 5 (the T6 generated file must be named; dev.md tells dev to name it; unnamed variant) | nothing beyond R6, A9 and A10 |
| 6 (re-dispatched dev: union over the task's and lane's dev dispatches; /redev inherits nothing) | nothing beyond the File-list "Inheritance" bullet, D22 and A10 |
| 7 (push and merge grants are spent by the main agent's scripts; binding where the grant is written; grant guard unchanged) | nothing beyond R9 |
| 8 (live canary capture unavailable; fields documented; fallback covers) | R1 ("Payload fields: as P1 measured"; fallback order) and D19 |
| 9 (`py_compile` writes `__pycache__`; use built-in `compile()`) | nothing beyond the F3.a extra item, A12 and DO NOT |
| 10 (the T6 driver is spelled out in acceptance 9) | nothing beyond A9 |
| 11 (newly applied rows of never-registering roles: correct each row to its documented paths, replay every documented write, no exempted-role list) | R9 (instruction carried there, marked) |
| 12 (the main agent removes merge grants; the binding covers create and overwrite, not removal) | nothing beyond R9 ("Removal stays") and A8 |

### Instructions outside the table (where they went)

| Long place | Short place |
|---|---|
| "Before you start" checks | Dependencies (checks); "say in the PR which base you measured against" dropped (PR paperwork); "find each site again" dropped (repeats `_common.md`) |
| "Interfaces you consume" | Dependencies, last paragraph (use as merged, no second one; P5-a's release-input denies, marked); P5-b reader generalisation in Choices line 164 and the E6 bullet; P1 helpers in R4; G1 binding in R1; measured payload fields in R1. The descriptions of P4's e2e, P3's freshness and lane echo, P2's harness-home channel and P8's CI and fixture are not carried (background on merged interfaces) |
| "P1b and P1c (merged before you)" list | Map and CI check: D24; one CLI reader: R1; E6: File-list extra item, first bullet (compressed; "and of the baseline" and "the aggregator union once unread" not carried); agent-index consumers: R1; D8 deny and declaring-dispatch reader: D21; no prefix rows: D21; sidecar deleted by P1b: R5; merge rule: D25, A20 |
| Goal bullets 1-5 | Goal (short) and R1-R9; Goal 5 (live landing) in D15, A17 |
| Goal's release-notes list | not carried (PR paperwork) |
| Owner-decision bullets D2, D3/D23, D4, D7, D8, D10, D11, D12, D15, D17, D18, D19, D20, D21, D22, D24, D25 | Owner rulings, one bullet per id (D3 and D23 split into two bullets) |
| Owner-decision bullets O3/O4, O10/O12, O5/O7, A3 ledger | R6, R7, changelog-analyst extra item; D15 and DO NOT bullet 1; File-list "Not covered" (speed bump, no forgery-grade isolation); D18 |
| "Decided technical choices" TC-46, TC-40, TC-38, TC-20, TC-42, TC-54 | TC-46: R5, R7, File-list; TC-40: File-list, F3.a, DO NOT; TC-38: R1, D19; TC-20: D21; TC-42: R1 (leave P1's G1 hook); TC-54: R2, R7. "Repeat each in the PR" dropped (PR paperwork) |
| Scope preamble (suggested commit order; dev.md and qa.md in one commit; Python 3.10) | Suggested order not carried (it is a suggestion); its binding parts: R7 (same commit as R6, with tests), R2 (FIRST ACTION deletion with its tests), changelog-analyst extra item (in the A3.a promotion commit), File-list and F3.a (warning before promotion); Python 3.10 in R11 |
| Background "Carry-overs from P1" | R1, last sentence (marked) |
| "Out of scope" in-scope deletions (changelog-analyst provenance filter, stale sentence, three references; Phase 5 adoption branch stays) and "resolve-commit-repos and the aggregator stay unchanged" | Rows, extra item "Changelog-analyst deletions" |
| "Net code cap" | DO NOT, last bullet; A18 |
| PR body headings "Decided by experiment" | Pull request (experiment-decided choices) |

### After-P1b entries

| Entry | Long place | Short place or reason not carried |
|---|---|---|
| F-P6-02 | `prompts/P6.md`:66-68 (Interfaces you consume, P5-a release-input denies) | Dependencies, last paragraph, "any G2 escalation records P3 left ... [after P1b: re-check]" |
| F-P6-05 | :350 (row 3, "(not only when it is in `obligation.ROLES`)") | R3, marked |
| L-P6-01 | :417-418 (Role identity, CLI without `agent_type` or meta: role only from a cp-state Read) | R2, marked |
| F-P6-06 | :510-512 (Background, Carry-overs from P1) | R1, last sentence, marked |
| F-P6-07a | :760 (acceptance 20, "a syntax-broken harness hook (F3.a, Goal 4)") | A20, marked ("Goal 4" not carried: the short Goal is not numbered) |
| R2-18 | Role identity :413-415 (deletion of the dev-registry FIRST ACTION lines) | R2, marked after the deletion sentence |
| NC-33 | :118 (Goal 1, sidecar "deleted by P3 row 7") | Goal 1's history sentence not carried (history); the same claim in row 5 ("delete it here only if P3 left it") is carried in R5, marked |
| NC-34 | row 9 :356, correction 11 :321-329, Grant binding :428, acceptance 5 :636 (`/tmp/agentic-commit/` paths) | R9 grant-directory path (row 9 and :428), marked; R9 changelog-analyst paths (correction 11), marked; A5 push-gate token path, marked |
| NC-35 | row 3 :350 (`obligation.ROLES`; `ENFORCED_AGENT_TYPES` of row 4) | R3 `obligation.ROLES`, marked; `ENFORCED_AGENT_TYPES` not carried (citation dropped; R4 names the roles ba, dev, qa) |
| NC-36 | :66 ("any G2 escalation records P3 left") | same statement as F-P6-02; Dependencies, last paragraph, marked (one mark) |
| NC-37 | row 1 :348 (`_metadata_by_tool_use` line range) | not carried: the precedent and its line range are a citation; R1 routes the meta read through P1b's reader |
| PV-17 | `PLAN-v2.md`:1260 (section 13, P6 row; restated in P6's Carry-overs from P1) | R1, last sentence, same mark as F-P6-06 |

No entry in the subsections "### reviews/P1b-plan-sync.md", "### COVERAGE.md" or "### COVERAGE-P9-P11.md" concerns P6.

### DO NOT bullets dropped as repeats of `_common.md`

None dropped whole. All 15 bullets of "DO NOT (this phase)" are carried. In the bullet "Do not register harness hooks
in your own session ...", the parts "read your container's `.claude.json`" (kept as "credentials"), "start a nested
`claude`" (`_common.md` DO NOT) and "Hooks run only in the sandbox namespace" (kept in the Sandbox paragraph) were
trimmed. The bullet "Do not edit a hook to get a replay through ..." now says "the driver stays compliant, not adapted"
for "compliant with agents/*.md and the command text and is never adapted to the hook". The net code cap line is added.

### Sections not carried

- "Corrections to PLAN-v2": corrections to PLAN-v2 (instructions mapped in the table above).
- "Rules added / retired (expected)": rules added / retired.
- "Rollback": rollback.
- "Effort" line: effort.
- "Out of scope": out of scope (its two in-scope deletions and the unchanged consumers are carried, see above).
- "Background (in the extracted planning documents)": background reading list (its "Carry-overs from P1" is carried in R1).
- "Branch and pull request": repeats `_common.md` (branch, driving the PR) and PR paperwork (headings Corrections to
  PLAN-v2, Capability facts used, Now unreferenced, Live landing, Release notes); the PR title form is kept.
- Goal's "Put these release notes in the PR" list: PR paperwork.
- Owner quotes and O-message history in "Owner decisions that govern this phase": owner quotes and history.
- "Context (read once)" to the end: the shared tail (repeats `_common.md`).
- "Now unreferenced" listing of scripts/lib/attribution_aggregate_view.py for P10 (row 5, D17): hand-off section for a
  later phase; R5 keeps "leave it".

### Totals

- Rows: 11 kept (6 kept, 5 kept-marked), 0 dropped as moved.
- Acceptance tests: 20 kept (18 kept, 2 kept-marked), 0 dropped as moved.
- After-P1b marks in the short prompt: 10.

## P9

Short prompt `harness-repair-plan/prompts/short/P9.md`: 300 lines, 34,977 bytes (long prompt `prompts/P9.md`: 872 lines,
111,615 bytes). Counts after the fixer round for the verifier's seven medium P9 findings (see "Fixer round" at the end).

### Rows and acceptance tests

| Long item | Short place | Status |
|---|---|---|
| Row 1 (spec_path producer) | R1 | kept, marked after P1b |
| Row 2 (doc-sync update-only) | R2 | kept |
| Row 3 (settings.json) | R3 | kept, marked after P1b |
| Row 4 (has_do_consent) | R4 | kept |
| Row 5 (roster) | R5 | kept, marked after P1b |
| Row 6 (git normaliser, option table) | R6 | kept |
| Row 7 (prompt includes, QA-fail loops, iterate-failed-pipelines.py) | R7 | kept |
| Row 8 (commands prose pass) | R8 | kept, marked after P1b |
| Row 9 (agents prose, dangling references) | R9 | kept |
| Row 10 (D9a retirement commit) | R10 | kept, marked after P1b |
| Row 11 (score injection, echo contracts) | R11 | kept |
| Row 12 (OPTIONS_XML, overnight AskUserQuestion deny) | R12 | kept |
| Row 13 (residue allowlist, tracked comments, neutral key) | R13 | kept |
| Row 14 (README, ARCHITECTURE) | R14 | kept |
| Row 15 (docstrings, messages) | R15 | kept |
| Row 16 (CLAUDE.md) | R16 | kept |
| Row 17 (tests) | R17 | kept |
| Acceptance 1 (Base) | A1 | kept |
| Acceptance 2 (CI baseline) | A2 | kept |
| Acceptance 3 (spec hand-off) | A3 | kept |
| Acceptance 4 (doc-sync) | A4 | kept |
| Acceptance 5 (consent) | A5 | kept |
| Acceptance 6 (git normaliser) | A6 | kept |
| Acceptance 7 (roster) | A7 | kept |
| Acceptance 8 (includes) | A8 | kept |
| Acceptance 9 (dispatch templates) | A9 | kept |
| Acceptance 10 (no honest-fail, text-pause or parking prose) | A10 | kept |
| Acceptance 11 (D9a) | A11 | kept, marked after P1b |
| Acceptance 12 (E1 output) | A12 (E1's setup and measurements (a)-(f) folded in) | kept |
| Acceptance 13 (settings) | A13 | kept |
| Acceptance 14 (stamps and tutorials) | A14 | kept |
| Acceptance 15 (README and ARCHITECTURE) | A15 | kept |
| Acceptance 16 (CLAUDE.md) | A16 (E3's replay list folded in) | kept |
| Acceptance 17 (E2 output) | A17 (E2's setup folded in) | kept |
| Acceptance 18 (agents) | A18 | kept |
| Acceptance 19 (live landing) | A19 | kept |
| Acceptance 20 (personal values) | A20 | kept |
| Acceptance 21 (full suite) | A21 | kept |
| Acceptance 22 (net code) | A22 (plus the Net code cap section's byte-change report) | kept |
| Acceptance 23 (one producer, one consumer, D24) | A23 | kept, marked after P1b |
| Acceptance 24 (never fail, D25) | A24 | kept |
| Scope subsection "Rows 1, 2, 4 and 5 after P1b (2026-10-24)" | Rows, first paragraph ("P1b/P1c delivered: verify only ...") | kept, marked after P1b |
| Scope subsection "P1c's widened SendMessage exception (X8 ...)" | R16 (Lesson 16 and "sole SendMessage exception" lines, with the four replay cases), R14 ("/restart (R16)"), A16 ("/restart") | kept |
| Scope preamble ("Locations are at f8c18c2 ...") | none (citations) | not carried: citation note |
| Goal 1 (one producer per fact) | Goal; R1, R2, R4, R5, R6, R7 | kept |
| Goal 2 (one prose pass; replay-backed sentences; run_in_background; stamps) | Goal; R8, R14, R15, R16; A9, A16 | kept |
| Goal 3 (scoring shrinks to the rating log) | Goal (marked); R10-R13 | kept, marked after P1b |
| Goal 4 (live landing) | E9 line; A19 | kept |
| "Before you start" checks | Dependencies, run-order line and four check bullets | kept |
| "Interfaces you consume" (P4, P5, P6, P3, P2, P1, P8, P7b, everything else) | Dependencies, paragraph "Use what P1-P8, P7b merged ..."; facts in R1 (P3 disposition), R4 (P1 clearer), R6 (P5-a, P6, P5 row 6), R7 (P2 channel), R8 (P2 advisory-default lines, TIME CHECK, P6 FIRST ACTION), R12 (P2 deny), R13 (P8 allowlist), R14 (P5 stubs, P3 acceptance 19, P1), A19 (P7b scripts), DO NOT 4 (P4 rating code) | kept |
| Owner-decision bullets D20, D21, D22, D23, D24, D19/D18, D9a, D9/D9b, D2, D3/S1, D4/D4c, D5, D7/D8, D20, D12/S6, D15, D17, D10 | Owner rulings, one line per id | kept |
| Owner-decision bullets "Clean, self-consistent, public (O2, O4)" and "Producer-side, one conclusion (O10, O12)" | Goal; DO NOT 6 (nothing added to /close, /commit, changelog-analyst, QA) | kept (no decision id; quotes dropped) |
| "Decided technical choices this phase implements": TC-49 | R10, DO NOT 9 | kept |
| TC-51 | R9 (spec.md), A18 | kept |
| TC-52 | R8 (clean.md prefixes), R9 (inspectors' paths), A18 | kept |
| TC-54 | R17, A21 | kept |
| TC-28, TC-31 | DO NOT 4 (rating producer untouched) | kept |
| TC-37 | D15 line (no hook deleted or unregistered) | kept |
| "Decided by experiment" preamble (kit only, scripts in `$SB/payloads/`, rule fixed first, results in the PR) | Kit paragraph; D18, D10 lines; DO NOT 10, 11; PR section "experiment choices" | kept |
| E1 (H-Q10, score stores) | Choices, line E1; A12 | kept |
| E2 (UD5, /do and a push) | Choices, line E2; R4 (guard change, tests); A5; A17 | kept |
| E3 (hook claims) | Choices, line E3; A16 (replay list); R14, R15, R16 | kept |
| E4 (UD1, cp-enforce) | Choices, line E4; R3 (CP_ENFORCE_MODE), R7, R8, R9; A24 | kept |
| E5 (UD4, Codex default) | Choices, line E5; R7 ("E5's default stated") | kept |
| E6 (U-F3c, Hook Discipline #2) | Choices, line E6; R16 | kept |
| E7 (U2/U6/U7, dangling references) | Choices, line E7; R9, R16 (deep-search line); A18; DO NOT 7 | kept |
| E8 (U-E3b, trimming CLAUDE.md) | Choices, line E8; R16 (added line); A16 (`wc -c`) | kept |
| E9 (live landing) | Choices, line E9; R2, R16 (date block); A19 | kept |
| E10 (D2.a, dead Skill denies) | Choices, line E10; R3; A13; DO NOT 5 | kept |
| Technical choice: transcript reader for spec_path and the printed forms | Choices, line "Also" ("spec_path reader, forms") | kept |
| Technical choice: UserPromptSubmit block for an unresolved explicit spec | Choices, line "Also" ("block"); R1 | kept |
| Technical choice: doc-sync's update-only checks | Choices, line "Also" | kept |
| Technical choice: has_do_consent's signature, shell entry point, measured latency | Choices, line "Also"; R4 | kept |
| Technical choice: roster function's home and per-site subsets | Choices, line "Also"; R5 | kept |
| Technical choice: option table's home module and each correction | Choices, line "Also" ("option table"); R6 | kept |
| Technical choice: row 7's hook delivery experiment; include file names, path form, pointer text | Choices, line "Also" ("R7's delivery, include names, pointers"); R7 | kept |
| Technical choice: how the trace contract moves | Choices, line "Also"; R8 | kept |
| Technical choice: how each prose pin was updated or replaced | Choices, line "Also" ("pins (A21)"); R17 | kept |
| Technical choice: "anything else you decide"; least code, fewest rules, a test or replay each | D10 line | kept |

### Corrections to PLAN-v2 (section dropped; where each instruction went)

| Correction | Short place |
|---|---|
| 1 (score allows incl. lifecycle-baseline-import.sh's; delete all three with their scripts) | R3 (marked after P1b) |
| 2 (false "tracked" comment; agent-scores ignore lines) | nothing beyond R13 and E1 |
| 3 (residue-allowlist entries; P8 may have reshaped the file) | R13 ("any shape P8 left") |
| 4 (P8's deletions; what remains: two shell tests, their index files, TESTING.md S5, index rows) | R10; Dependencies check (tests/generated/INDEX.md absent) |
| 5 (D9a grep filter `=<options>]`) | A11 |
| 6 (neutral key in test_ac_deviation_record_chain.py) | nothing beyond R13 |
| 7 (overnight-init.sh comment naming score-inject.sh) | nothing beyond R13 |
| 8 (honest-fail grep over hooks/: refusal tests, P10 files) | nothing beyond A10 |
| 9 (section 13's P9 row half superseded by P5 row 6; keep what the replay shows) | R14 ("Limits: ... P5-fixed ones leave") |
| 10 (UD-CM, H-Q10 no longer human steps) | D19 line; R16; E1 |
| 11 (P4's enforce-flag lines: skip; if present, list under "Out of scope, found") | DO NOT 7 ("edit P4's artifact-contract enforce-flag lines"); the listing instruction was treated as PR paperwork and not carried |
| 12 (/do consent readers moved; P1's clearers; stubs) | nothing beyond R4 (locations dropped) |
| 13 (git option sites moved; `-C` grammar comment is right) | nothing beyond R6 |
| 14 (README/ARCHITECTURE line moves) | nothing beyond R14 (locations dropped) |
| 15 (PLAN-v2's "No agent edit of CLAUDE.md" replaced by D19) | R16; D19 line |
| 16 (P3's deferred spec clause at its producer) | nothing beyond R1 |
| 17 (roster: neither ROLES nor a copied list; P1b row 18 deleted ROLES) | nothing beyond R5 |
| 18 (the echo "tip; git commit" false block; plain echo exits 0) | nothing beyond A6 |

### After-P1b entries

| Entry | Long place | Short place or reason not carried |
|---|---|---|
| F-P9-02 | Goal 3, "the four scripts" | Goal, marked |
| F-P9-03 | D17 bullet, "the four D9a scripts" | Owner rulings, D17 line, marked |
| F-P9-04 | E1 setup, "lifecycle-baseline-import.sh you delete" | not carried: E1's background description of the stores was dropped (A12 and the E1 line keep the setup and rule) |
| F-P9-05 | Correction 1, "delete all three with their scripts" | R3 ("three score allows (lifecycle-baseline-import.sh's too) with their scripts"), marked |
| L-P9-01 | Scope "Rows 1, 2, 4 and 5 after P1b", "Goal 3, E1 and rows 3 and 10 retire the three other D9a scripts ..." | Rows, first paragraph, marked |
| F-P9-10 | Row 1, "last Write or Edit to `docs/dev/specs/*.md` (INDEX.md and README.md excluded)" | R1, marked |
| F-P9-11 | Row 3 locations, "score allows :40, :50-51" | not carried: locations column (citations); the carried statement is F-P9-12's |
| F-P9-12 | Row 3, "and the three score allows" | R3, marked |
| L-P9-02 | Row 5 locations, agent_types cite range | not carried: citation |
| F-P9-13 | Row 5, "The prose fallback loops become "re-run the command"" | R5 ("Fallback loops: "re-run the command""), marked |
| F-P9-14 | Row 8 locations, "dev.md Step 15 :1106-1178 (self-edits settings)" | not carried: locations column; the Step 15 statement itself is marked in R8 under F-P9-15 |
| F-P9-15 | Row 8, "Step 15 reports suggested permissions instead of editing settings" | R8 ("dev.md Step 15 reports suggested permissions"), marked |
| F-P9-16 | Row 8, "The whole fallback block ... becomes "re-run the command"" | R8 ("fallback block -> "re-run the command""), marked |
| F-P9-17 | Row 8, "dev-overnight.md reports suggested permissions instead of writing them" | R8 ("permissions suggested, not written"), marked |
| F-P9-18 | Row 10, "Delete the four scripts and the two shell tests ..." | R10, marked |
| F-P9-19 | Out of scope, "except the four D9a scripts" | not carried: "Out of scope" section dropped |
| F-P9-22 | Acceptance 23, "(close.md:278, commit.md:83-84)" | A23 ("(close.md, commit.md)", line numbers dropped), covered by the mark at the end of that sentence |
| F-P9-23 | Acceptance 23, "if P4 left them" | A23, marked |
| F-P9-25 | Net code cap, "The four D9a scripts are -1,033 lines ..." | not carried: rationale figures; the cap line keeps only "-900" and its scope, which the entry does not change |
| NC-38 | Row 8, overnight-status.sh "prints the state with no time computation" | R8 (TIME CHECK clause), marked |
| NC-39 | Row 5 and Correction 17, CP_AGENTS readers P1b rows 1 and 18 delete | R5 ("CP_AGENTS AST readers of overnight-init.sh, create-overnight-state.sh"), marked; Correction 17 itself not carried |
| NC-40 | Acceptance 11, `lifecycle.jsonl` grep holds only if P1b row 15's reader does not name it | A11 ("-> close_rating.py only (+ kept skips)"), marked |
| PV-10 | PLAN-v2.md P9 section, spec_path rule (P1b E14 writer call) | same statement as F-P9-10: R1, marked |
| PV-11 | PLAN-v2.md P9 table, spec_path row | same statement as F-P9-10: R1, marked |
| S13 | reviews/P1b-plan-sync.md V-19, spec_path rule | same statement as F-P9-10: R1, marked |
| S1 | reviews/P1b-plan-sync.md status line announcing P9-11 to P9-14 | bookkeeping in another file; the statements P9-11 to P9-14 touch are covered by F-P9-03 (D17, marked), F-P9-05 (R3, marked), F-P9-25 and F-P9-19 (not carried) |
| S35 | reviews/P1b-plan-sync.md P9 file heading (edit count) | bookkeeping in another file; no P9 statement |
| S37 | reviews/P1b-plan-sync.md P9-11 to P9-14 | P9-11 = D17 (marked); P9-12 = Correction 1 -> R3 (marked); P9-13 = Net code cap rationale (not carried); P9-14 = Out of scope (not carried) |
| S38 | reviews/P1b-plan-sync.md counts table and "Anchors not placed" | bookkeeping in another file; no P9 statement |
| R2-02b (COVERAGE-P9-P11.md subsection) | COVERAGE-P9-P11.md dependency rows | concerns COVERAGE-P9-P11.md, not a P9.md statement; the short Dependencies list names P1b and P1c |
| R2-03 (COVERAGE-P9-P11.md subsection) | COVERAGE-P9-P11.md "P9 rows 1-6" | concerns COVERAGE-P9-P11.md; not carried |

### DO NOT bullets dropped as repeats of _common.md

- none dropped whole. Inside the bullet on running hooks against the real home, "Do not start a nested `claude`" was dropped
  as a repeat of _common.md ("Do not run nested `claude` CLI sessions"). The long bullets on P4's enforce-flag lines,
  security hook outcomes and publishing a gitignored file were merged into one short bullet (DO NOT 7).

### Sections not carried

- Opening paragraphs ("Wave 7", the owner-quote block, "CLAUDE.md: the one exception to the tail"): history and owner
  quotes. Their instructions are in Dependencies, the D18/D19 lines, R16 and DO NOT 1-2.
- Release notes under "Goal": PR paperwork (release notes are not a PR-body item).
- Owner-decision preamble (D#/S#/O# ranking) and the owner quotes in every decision bullet: rationale and owner quotes.
- "Decided technical choices this phase implements" (TC-xx list): inventory codes; contents mapped to rows above.
- "Corrections to PLAN-v2": corrections to PLAN-v2; instructions mapped above.
- "Background": background reading list.
- "Out of scope": dropped category.
- "Rules added / retired (expected)": dropped category.
- "Net code cap": the number and its scope are the DO NOT cap line; the byte-change report travels with A22; the figures
  and "Effort" are rationale/effort.
- "Rollback" (including the commit order): dropped category. R10 keeps "D9a retirement commit" and R17 "in its commit".
- "Branch and pull request": branch and PR-driving rules repeat _common.md; the PR-body headings are replaced by the
  fixed list; the title form is kept in the Pull request section.
- "Context (read once)" to the end: shared tail.

### Details compressed or dropped to meet the 300-line limit (concrete, not paperwork)

- R14: "No generated hook tables" moved to DO NOT 6. (The 13 hook names, the team/CI FAQ claim and the README
  install/private-literal rule are carried again: see "Fixer round".)
- R12: "the hook stays warn-only for the other categories"; the second [INFERRED in D20] marker; the deny message text
  ("as P2 merged it" is kept).
- R4: the list of the 13 /do consent readers is compressed to "privilege guard, bash-safety x3, other pretool hooks"
  ("every /do consent reader" is kept).
- R7: the pathspec of the iterate-failed-pipelines grep (`-- commands agents hooks scripts settings.json`).
- R8: "in one message" for clean.md's synchronous calls; "(advisory hook, E3)" on the purity rule; todo/dev.py's Step 15
  label and its "optional" specialists are folded into "follow dev.md's step model".
- R15: the orchestrator gate's `block_streak` docstring is not named.
- E3: "No hook behaviour changes under E3" is carried only through R15's "no behaviour change".
- E7: the deep-search existence check (`ls commands/deep-search.md agents/deep-search.md skills/deep-search` plus the
  Skill denies).
- E9: "(P10 reuses it)" and "Record both runs".
- E10: the 16 candidate deny names measured at f8c18c2 and "record the source and date" (the source is kept).
- A23: the writer/reader notes of the P1b-deleted artifacts (G2's _write_journal_view_sidecar,
  posttool-lane-completeness-watch.py, "read, never written"); "under Now unreferenced" became "for P10".
- D24 line: the table's columns are shortened to "producers, consumers, proofs".
- Dependencies: "say in the PR which base you measured against", "find each site again on your base", PLAN-v2 section
  13's P9 rows (copies of the PR lists), "run independent experiments and test runs in parallel".

### Totals

Rows: 12 kept, 5 kept and marked after P1b, 0 dropped as moved. Acceptance tests: 22 kept, 2 kept and marked after P1b,
0 dropped as moved.

### Fixer round (verifier's seven medium P9 findings)

Mappings and statuses above are unchanged (every row and test keeps its label and status); these statements were
restored in place:

- Rows, first paragraph: the creation-paths condition now reads "P1b E9; if E9 deleted creation, R2 keeps the CLAUDE.md
  date block (this phase's E9) and /test's copies; P1c X5's doc-sync writes into docs/dev/ are done: verify, do not
  redo" (finding 1); it adds P1b's D24 table (its acceptance 6) as the answer to A23's proofs, "where an A23
  parenthesis names another producer or validator than P1b chose (spec monolith: E14; push-gate token: row 11 ...;
  merge-analyst grant: E11), P1b's choice stands and your proof shows it", and "P1b's artifact map and CI check govern
  every row that adds or keeps a check on an artifact" (finding 2).
- R7: the charter is named: the "Requirement Baseline and Scope Authority" block, all 23 agents, variants included;
  ba.md's "### Critical-Thinking Charter" below it is not part of it and stays (finding 3).
- R9: each D2.c dangling-reference site is named by file and phrase: ui-specialist.md (DESIGN_MODE template line,
  report-schema path), ui-axe-injector SKILL.md, dev-command.md ("The full tutorial"), dev-overnight.md (Hard Rule 6's
  state-file-write-policy.md, DESIGN_MODE template line), ba.md (trigger-word rule, both copies), qa.md (trigger-word
  rule, frozen spec line), paseo-daemon.md, commit.md ("Continuation spec"), commands/dev.md ("INDEX-edit clarifier"),
  plus A18's hits and CLAUDE.md's deep-search line (finding 4).
- R14: the 13 exit-0-stderr hooks by name (posttool-git-warn.sh's matcher noted), the team/CI FAQ's `$HOME`-relative
  paths claim (state whether it holds on the base), and "README's install and private-literal sections (P7b's text)
  change only where a sentence is false on your base" (finding 5).
- E1 line: "Landing step" is one idempotent step added to P7b's landing, moving agent-scores.json + lock into
  `<home>/logs/` (ignored), under the landing's lock, exit 0 always, counts-only log; its "landed" test gains one file
  check (overhead re-measured within P7b's 50 ms budget); a pytest (A12 keeps the P7b acceptance re-run) (finding 6).
- A16: the replay cases as the long E3 states them: six Bash calls with a Read between the third and fourth;
  hooks/push.sh on a dirty tree with a valid push grant; `git branch -d x`, `-m a b`, `-D x` through the branch firewall
  and the privilege guard; where userprompt-consent-allowlist.sh writes an /allow sentinel with CLAUDE_STATE_DIR set, and
  whether the coordinator's cleanup phase reaps an expired sentinel on an allowed Stop; prompt-purity on a HOW-laden
  Agent prompt; subagentstop-cp-enforce with a pending cp-state under the shipped settings (expected: exit 0, advisory
  record) (finding 7).

After-P1b marks: none added. No entry of the After-P1b list concerns the restored statements (the entries for this
long prompt concern its :124, :212-214, :242 (E1's setup, not the Landing step), :385, :448 (the D9a sentence of the
rows' first paragraph, already marked), :469-478 (rows 1, 3, 5, 8, 10), :509-510, :661, acceptance 11 and the
net-code rationale).

Room made without dropping a requirement: R5, R7, R8, R9, R14, R16, the rows' first paragraph, E1, A10's prose part,
A16, A18, A19 and A24 rewrapped at up to 140 characters (no new line over 140); R9 no longer repeats "codex command
list" (R7 carries it: "the codex include's codex_required command list fixed"); R4 states E2's guard change by
reference ("E2's privilege-guard change (Choices) with tests: ...", the three regression tests kept) and the Choices
E2 line now names "the privilege guard"; A19 and A24 reworded (order and punctuation only, every case and expected
result kept).

## P10

Short prompt: 300 lines, 33,571 bytes (long prompt before the shared tail: 792 lines, 93,177 bytes; about 36%).
Rows R2, R6, R11, R19 and acceptance A14 are wrapped at up to 140 characters (fixer brief allowance); A1's grep line is
one command of 181 characters.

### Rows and acceptance tests

| Long item | Short place | Status |
|---|---|---|
| Row 1 | R1 | kept |
| Row 2 | R2 | kept |
| Row 3 | R3 | kept, marked after P1b |
| Row 4 | R4 | kept |
| Row 5 | R5 | kept |
| Row 6 | R6 | kept, marked after P1b |
| Row 7 | R7 | kept, marked after P1b |
| Row 8 | R8 | kept |
| Row 9 | R9 | kept |
| Row 10 | R10 | kept |
| Row 11 | R11 | kept |
| Row 12 | R12 | kept |
| Row 13 | R13 | kept |
| Row 14 | R14 | kept |
| Row 15 | R15 | kept |
| Row 16 | R16 (one bullet per residual: read_command_spec, B4, B5, L1, L2, L3) | kept |
| Row 17 | R17 | kept |
| Row 18 | R18 | kept |
| Row 19 | R19 (with the PR's D24 table) | kept |
| Acceptance 1 | A1 (grep regex grouped to fit 200 columns; matches the same six names) | kept |
| Acceptance 2 | A2 | kept |
| Acceptance 3 | A3 | kept |
| Acceptance 4 | A4 | kept |
| Acceptance 5 | A5 ("Deleted in the long prompt") | absent in the long prompt (the long prompt keeps the number, deleted with the stand-in design) |
| Acceptance 6 | A6 ("Deleted in the long prompt") | absent in the long prompt (same) |
| Acceptance 7 | A7 ("Deleted in the long prompt") | absent in the long prompt (same) |
| Acceptance 8 | A8 | kept |
| Acceptance 9 | A9 (reachability table travels with the test) | kept |
| Acceptance 10 | A10 | kept |
| Acceptance 11 | A11 | kept |
| Acceptance 12 | A12 | kept |
| Acceptance 13 | A13 | kept |
| Acceptance 14 | A14 | kept |
| Acceptance 15 | A15 | kept |
| Acceptance 16 | A16 | kept |
| Acceptance 17 | A17 | kept |
| Acceptance 18 | A18 | kept |
| Acceptance 19 | A19 | kept |
| Acceptance 20 | A20 | kept |
| Acceptance 21 | A21 | kept |
| Acceptance 22 | A22 | kept |
| Acceptance 23 | A23 | kept |
| Acceptance 24 | A24 | kept |
| Acceptance 25 | A25 | kept |
| Acceptance "Sandbox" note | Acceptance tests, "Sandbox:" lines | kept |
| Scope: Per-home retirement | R2 (R-e: migration fix, overlay repair through the same function, Exp 1-2), R3 (option (a)); facts 1-4 not carried (rationale) | kept |
| Scope: Product repositories stay clean | R8 (three rules, info/exclude, worktrees); DO NOT bullet 3 (no tracked file from a hook) | kept |
| Scope: Size ratchet | R15 | kept |
| Scope: Recoverable removal | R13 (R14 for cleaner and /clean) | kept |
| Scope: Dead code | Rows, extra item "Dead code" | kept |
| Scope: P0b residuals | R16, one line each | kept |
| Scope: Live landing | Rows, extra item "Dead code ... Commits" ("Changed hooks accept origin/master's state (Exp 5-7 ...)"); R5 Exp 10; R9 last sentence; release-notes list not carried (PR paperwork) | kept |
| Scope: Technical choices you make (closing rule: design doc, less code and fewer rules, a test each) | Choices, header line | kept |
| Choice: experiment 3's option for the stubs | Choices, line 1 | kept |
| Choice: experiment 10's edit shapes and landing step | Choices, line 3 | kept |
| Choice: overlay repair's form and the migration rule | Choices, line 1 | kept |
| Choice: each deletion's verdict where reachability is not plain | Choices, line 5 | kept |
| Choice: harness-owned .claude/ subdirectories with an exclude line | Choices, line 3 | kept |
| Choice: which .gitignore rules go and how the rest are anchored | Choices, line 5 | kept |
| Choice: the seal store's new default | Choices, line 5 | kept |
| Choice: git rm classification details and the protected set | Choices, line 5 | kept |
| Choice: ratchet metric definitions and CI budget ref | Choices, line 4 | kept |
| Choice: L2's bound | Choices, line 4 | kept |
| Choice: B4's wording | Choices, line 4 | kept |
| Choice: each experiment's option | Choices, lines 1-4 | kept |
| Experiment 1 | R2 (real P7b landing, home at fe7700c8; counts overlay hook commands whose file is a stub or missing at HEAD, and those HEAD's clean form runs through another registered command) | kept |
| Experiment 2 | R2 | kept |
| Experiment 3 | R3, A3 | kept |
| Experiment 4 | none | absent in the long prompt (deleted with the stand-in design) |
| Experiment 5 | R3 | kept |
| Experiment 6 | R17 | kept |
| Experiment 7 | R6 | kept |
| Experiment 8 | R7 | kept |
| Experiment 9 | R8 (= A11's origin/master run) | kept |
| Experiment 10 | R5, A24 | kept |
| Experiment 11 | R14, A10 | kept |
| Experiment 12 | R15, A15 | kept |
| Decided TC-37, TC-35 | R3, R2; R7 | kept |
| Decided TC-53 | R6 KEEP (repair-venv.sh, venv-repair.md) | kept |
| Decided TC-54 | Rows, extra item "Commits" (prose-pinning tests) | kept |
| Decided TC-55 | R10 | kept |
| Decided TC-56 | R15 (`docs_reference_bytes`, backlog included); A18 (backlog exists) | kept |
| Decided TC-57 | R12 (record-only rule) | kept |
| Ledger U-F1a | R13, A13 | kept |
| Ledger U-F2a | R15 (own commit, self-raise -> fix design), A15 | kept |
| Ledger U-E2a | R8, A11 | kept |
| Ledger U-E1b | R5 (commands/ pair, agents/ pair rule), A9 | kept |
| Ledger U-E1c | Rows, extra item ("Product docs stay (redacted); record git grep -c counts ...; rename nothing") | kept |
| Ledger U-E3b | nothing here (CLAUDE.md untouched: DO NOT, A21) | kept |
| Ledger E2.b | R6 KEEP (prune-orphaned-workflow-bookmarks.sh) | kept |
| Owner decisions D1, D3, D4, D11-D25 | Owner rulings, one bullet per id | kept |
| Owner decision "Producer-side only" | DO NOT bullet 7 (consumer side, commit.md/close.md/changelog-analyst), R15 (no hook, G2, Review-by, stamp hook), DO NOT bullet 5 (snapshot-then-rm) | kept |
| Owner decision "No new mutable state (C1)" | DO NOT bullet 3; R2 (logging only to the landing log) | kept |
| Correction 1 (TC-35 sites and readers) | R7 (sites, laneb-integration-gate rule, G2 and posttool-overnight-file-check readers) | kept |
| Correction 2 (TC-53 revert) | nothing beyond R6 (repair-venv KEEP) | not carried (history) |
| Correction 3 (doctor on each home withdrawn) | nothing beyond R2/R3 and D19 | not carried (history) |
| Correction 4 (net code cap) | DO NOT, cap line; A22 (against -40000 and about 11,400) | kept |
| Correction 5 (git rm locations) | R13 (files named; sites re-found per Dependencies) | kept |
| Correction 6 (pre-commit trio live) | R6 KEEP | kept |
| Correction 7 (`registered_hooks` from clean settings.json) | R15 | kept |
| Correction 8 (CLAUDE.md-named files stay) | R6 KEEP ("Out of scope, found" if unrun), DO NOT bullet 2, A9 | kept |
| Correction 9 (timelock stub registered) | nothing beyond R3 (six stubs) and A3 | not carried (history) |
| Correction 10 (migration carries harness registrations) | nothing beyond R2 | not carried (rationale) |
| Before you start (checks) | Dependencies | kept |
| Earlier phases: P1 | R6 (close-commit-repair-orchestrate, failed_attempts filter, `--inc-fail`); Dependencies (stub grep) | kept |
| Earlier phases: P1b | R3 (kept stubs, marked after P1b: MN-16), R19, D24 bullet, Dependencies (delete nothing P1b deleted; out-of-scope defects) | kept |
| Earlier phases: P1c | A25, R8 (X5 verify, not redo), D25 | kept |
| Earlier phases: P2 | R6 (`--cycle-reset`), R17 (old spellings) | kept |
| Earlier phases: P3 | R4 (sessionstart-artifact-census.py) | kept |
| Earlier phases: P4 | R6 (every "Now unreferenced" item of P4's, P6's, P9's PRs: any script that lost its last caller); R6 Exp 7 (close-route-select.py, `artifact-contract`) | kept |
| Earlier phases: P5 | R3 (stubs, one-case tests, Exp 5 shim) | kept |
| Earlier phases: P6 | R6 (attribution aggregate files; every "Now unreferenced" item), R8 (`.claude/dev-registry/`) | kept |
| Earlier phases: P8 | R4 (overwrite-guard), R6 (P8's leftover dead code), R9 | kept |
| Earlier phases: P9 | R6 (every "Now unreferenced" item), R17 (allow entries), R18 (INDEX/README lines), R11 (qa-status-gate record KEEP), R5 (E9 landing step), R9 (E1 score-store lines) | kept |
| Earlier phases: PLAN-v2 section 13 rows | Dependencies (last line) | kept |
| Earlier phases: P7b | R2 (landing extended, S4 rule) | kept |

### After-P1b entries

| Entry | Long place | Short place or reason not carried |
|---|---|---|
| L-P10-01 | Row 6 (repair-map engine sentence) | R6, mark after "The proof decides close-commit-repair-orchestrate.py and the repair-map engine" |
| F-P10-03 | Row 7 (drift test) | R7, mark after "The drift test between TERMINAL_VOCABULARY and the schemas stays green" |
| NC-41a (row 7 part) | Row 7 (drift test) | R7, same mark as F-P10-03 |
| NC-41a (row 3 part) | Row 3 (coordinator's timelock phase as a reference example) | not carried: the timelock-phase example is an f8c18c2 site citation; R3 keeps only "references kept" |
| NC-43 | Row 6 (scripts/session-resources.py) | R6, mark after "session-resources.py" |
| MN-16 | Earlier phases, P1b's stub list | R3, mark after the P1b stub list (`git grep -l '^# STUB:' -- scripts`) |
| MN-17 | Row 6 (repair-map scripts and schema; update-overnight-state.sh options) | R6, marks after "schemas/repair-map.v1.json", after "`--cycle-reset` bypass"; the repair-map scripts share L-P10-01's mark |
| NC-04 | PLAN-v2.md (TERMINAL_VOCABULARY drift test) | concerns PLAN-v2, not the long prompt; the same statement in R7 is already marked (F-P10-03) |
| PV-18 | PLAN-v2.md section 15 takeover list | concerns PLAN-v2 only; no statement of it in the short prompt |
| R2-02b | COVERAGE-P9-P11.md dependency rows | concerns the coverage record; Dependencies lists P1b and P1c from the long prompt, no mark |
| R2-03 | COVERAGE-P9-P11.md O4/O6 row | concerns the coverage record; not carried |

R19's pointer to P1b's PR's dead-artifact list (P1b acceptance 10), restored by the fixer, is concerned by no entry:
no mark.

### DO NOT bullets dropped as repeats of _common.md

- "Do not delete remote refs, branches or tags, rewrite history, or push anywhere but your branch." (D16 bullet keeps
  no history rewrite and no remote ref or branch deletion.)

### Sections not carried

- Corrections to PLAN-v2: corrections list (instructions found nowhere else carried into their rows, table above).
- Background: background reading list.
- Out of scope: "Out of scope" section.
- Rules added / retired (expected): rules lists.
- Net code cap prose beyond the cap line: rationale (report items travel with A22).
- Effort: effort.
- Rollback: rollback (each-commit-reverts-alone rule kept under "Commits").
- Branch and pull request beyond title and body: Notes-for-reviewers headings (Corrections, Per-home retirement,
  Records, Hand-off to P11, Live landing, Release notes) are PR paperwork; the work they report stays in rows and tests.
- Hand-off to P11: hand-off section (kept shims and spellings stay R3/R17 work; budget file stays R15).
- Live landing release-notes list and "say so" statements: PR paperwork.
- Owner quotes and "What the owner asked for": owner quotes.
- Per-home retirement facts 1-4: rationale and background.
- Context tail from line 793: replaced by the last line pointing to prompts/_common.md.

### Compression notes (kept in substance, detail dropped)

- R3: P5's three test file names and the at-f8c18c2 reference examples dropped (re-found by grep on the base).
- R4: test file names folded into "with tests"; reference hints dropped.
- R5, R6: CLAUDE.md stem and file examples dropped; rule kept.
- R9: exact score-store ignore lines dropped (P9's E1 lines named).
- R11: "grep-only archive" wording dropped (the list of files whose citing lines are trimmed is kept).
- R13: function names, test file list and measured counts dropped; classification, limits and set check kept.
- R19: Lnn audit labels dropped; artifact names, the sentinel path, the close-force readers' and advisory writers'
  file names and the pointer to P1b's dead-artifact list (P1b acceptance 10) kept.
- Dead code: example loaders (spec_from_file_location, subprocess) and QUICKSTART/.env.example examples dropped.
- Sandbox: "(full history)", drivers path, "(not a worktree)" and the runhook sequence note dropped.

### Totals

Rows: 19 kept (16 kept, 3 kept-marked), 0 dropped-as-moved. Acceptance tests: 22 kept, 0 kept-marked,
0 dropped-as-moved (A5-A7 absent in the long prompt).

## P11

Short prompt `harness-repair-plan/prompts/short/P11.md`: 350 lines, 35,008 bytes (long prompt body before the shared
tail: 767 lines, 70,668 bytes).

Labels used in the short prompt: rows keep the long prompt's ids (Stage 1-3, Fact 1-11, A1-A9, B1-B9, C, H1-H10, where
Hn is hand-off item n). Acceptance tests are labelled `Acc<n>` (Acc1, Acc5b, ...), not `A<n>`, because Part A's rows
already use A1-A9; the short prompt states "Acc<n> is the long prompt's acceptance n".

### Rows and acceptance tests

| Long item | Short place | Status |
|---|---|---|
| What you deliver 1 (stage 1, the PR) | Stage 1 | kept |
| What you deliver 2 (stage 2, after the merge; overrides "stop when merged") | Stage 2 | kept |
| What you deliver 3 (never publish against origin; reviewer asks and runs) | Stage 3; DO NOT bullet 2 | kept |
| Fact 1 | Fact 1 | kept |
| Fact 2 | Fact 2 | kept |
| Fact 3 | Fact 3 | kept |
| Fact 4 | Fact 4 | kept |
| Fact 5 | Fact 5 | kept |
| Fact 6 | Fact 6 | kept (as "planning measurement; do not re-run") |
| Fact 7 | Fact 7 | kept |
| Fact 8 | Fact 8 | kept |
| Fact 9 | Fact 9 | kept |
| Fact 10 | Fact 10 | kept |
| Fact 11 | Fact 11 | kept |
| A1 | A1 | kept |
| A2 | A2 (with its coverage experiment and build paragraph) | kept |
| A3 | A3 | kept |
| A4 | A4 | kept |
| A5 | A5 | kept |
| A6 | A6 | kept |
| A7 (eleven verification lines and scan rules) | A7 (code block verbatim) and the "Scans:" paragraph | kept |
| A8 (steps 1-6, every preflight condition) | A8 steps 1-6 | kept |
| A9 | A9 | kept |
| B1 | B1 | kept |
| B2 | B2 | kept |
| B3 | B3 | replaced in the long prompt by goal bullet 4's pre-push guard |
| B4 | B4 | kept |
| B5 | B5 | kept |
| B6 | B6 | replaced in the long prompt by goal bullet 4's pre-push guard |
| B7 | B7 | replaced in the long prompt by goal bullet 4's pre-push guard |
| B8 | B8 | kept |
| B9 | B9 | kept |
| Part C | C | kept |
| Hand-off item 1 | H1 | kept |
| Hand-off item 2 | H2 | kept |
| Hand-off item 3 | H3 | kept |
| Hand-off item 4 | H4 | kept |
| Hand-off item 5 | H5 | kept |
| Hand-off item 6 (the owner question) | H6 | kept (the go-ahead on record is named via DECISIONS.md D16, not quoted) |
| Hand-off item 7 | H7 | kept |
| Hand-off item 8 | H8 | kept |
| Hand-off item 9 | H9 | kept |
| Hand-off item 10 | H10 | kept |
| Hand-off preamble (post after the stage-2 runs; no private value) | Hand-off, first line | kept |
| Hand-off closing (answer comments, corrected hand-off, no new PR, stop) | Hand-off, last line | kept |
| Goal bullet 4 (the pre-push guard's definition) | Rows, Part B, extra item "Pre-push guard (goal bullet 4)" | kept |
| Part B preamble (placement) and the "Producer-side, no new mutable state" bullet | Rows, Part B, first paragraph | kept |
| "Before you start" checks | Dependencies | kept |
| Earlier phases' deliverables to find on the base (Background list, Out-of-scope P10 items, P9/P10 landing steps) | Rows, extra item "Find on the merged base" | kept |
| Net code cap section, size budget paragraph | Rows, extra item "Size budget (P10)" | kept |
| Net code cap (target <= 0 and what it counts) | DO NOT, last bullet | kept |
| Background: PLAN-v2 section 13 rows for P11 | H10 | kept |
| Out of scope: copies of a home named in "Out of scope, found" | Pull request | kept |
| Scope subsection "What happens today" (re-run each fact, output in the PR) | Rows, "What happens today", first line | kept |
| Scope subsection "Part A: the rewrite" | Rows, Part A | kept |
| Scope subsection "Part B: the landing installs the pre-push guard" | Rows, Part B | kept |
| Scope subsection "Part C: docs" | Rows, Part C | kept |
| Scope subsection "Technical choices you make" | Rows, "Choices to decide by experiment" | kept |
| Technical choice: the mailmap target | Choices, line 1 | kept |
| Technical choice: each literal's rule form | Choices, line 2 | kept |
| Technical choice: the placeholders | Choices, line 3 | kept |
| Technical choice: the removed paths | Choices, line 4 | kept |
| Technical choice: the root-change mechanism | Choices, line 5 | kept |
| Technical choice: use of `--sensitive-data-removal` | Choices, line 6 | kept |
| Decision rule (other item decided by rule): A6's rotation line | Choices, line 7 | kept |
| Decision rule (other item decided by rule): who files the A9 request | Choices, line 8 | kept |
| Technical choice: the merged-branch rule | Choices, line 9 | kept |
| Technical choice: the notice derivation and its cost (B1) | Choices, line 10 | kept |
| Technical choice: B4's matcher | Choices, line 11 | kept |
| Technical choice: B5's new-chain rule | Choices, line 12 | kept |
| Technical choice: B2's fork-point rule | Choices, line 13 | kept |
| Technical choice: the pull producer's restore of a stopped rebase | Choices, line 14 | kept |
| Technical choice: where the pre-push guard's code lives | Choices, line 15 | kept |
| Technical choice: the notice wording | Choices, line 16 | kept |
| Technical choice: the push batching and leases | Choices, line 17 | kept |
| Acceptance 1 | Acc1 | kept |
| Acceptance 2 | Acc2 | kept |
| Sandbox setup (before the scenarios) | Acceptance tests, "Sandbox setup", `home.sh` and "Publish =" paragraphs | kept (compressed) |
| Pull scenarios expectation (iii) | Acceptance tests, "(iii)" paragraph | kept |
| Acceptance 3 | Acc3 | kept |
| Acceptance 4 | Acc4 | kept |
| Acceptance 5 | Acc5 | kept |
| Acceptance 5b | Acc5b | kept |
| Acceptance 6 | Acc6 | kept |
| Acceptance 7 | Acc7 | replaced in the long prompt by (i)-(iii) (Acc14 (i) and (ii), and the (iii) expectation) |
| Acceptance 8 | Acc8 | kept |
| Acceptance 9 | Acc9-13 | replaced in the long prompt by (i)-(iii) |
| Acceptance 10 | Acc9-13 | replaced in the long prompt by (i)-(iii) |
| Acceptance 11 | Acc9-13 | replaced in the long prompt by (i)-(iii) |
| Acceptance 12 | Acc9-13 | replaced in the long prompt by (i)-(iii) |
| Acceptance 13 | Acc9-13 | replaced in the long prompt by (i)-(iii) |
| Acceptance 14 | Acc14 | kept |
| Acceptance 15 | Acc15 | kept |
| Acceptance 16 | Acc16 | kept |
| Acceptance 17 | Acc17 | kept |
| Acceptance 18 | Acc18 | kept |
| Acceptance 19 | Acc19 | kept |

### After-P1b entries

The After-P1b list (reviews/plan-pass-1-record.md from line 296) has no subsection for prompts/P11.md. The whole list,
including "### PLAN-v2.md", "### reviews/P1b-plan-sync.md", "### COVERAGE.md" and "### COVERAGE-P9-P11.md", was scanned
for P11 (by name, by its PLAN-v2 section lines :845-887, :142, :1199, and by its subject terms: pre-push, filter-repo,
rewrite, refs/backups, wave 9). Two entries mention P11; neither concerns a statement of prompts/P11.md, so the short
prompt carries no `[after P1b: re-check]` mark.

| Entry | Long place | Short place or reason not carried |
|---|---|---|
| S38 (reviews/P1b-plan-sync.md counts table, row `prompts/P11.md \| 3`) | none in prompts/P11.md (the statement is the sync record's edit count) | not carried: concerns reviews/P1b-plan-sync.md, not the long prompt |
| R2-02b (COVERAGE-P9-P11.md:35-37 dependency rows for P9, P10 and P11 omit P1b and P1c) | none in prompts/P11.md (its "Before you start" already lists the `P1b: …` and `P1c: …` merges) | not carried: concerns COVERAGE-P9-P11.md; the short prompt's Dependencies carry the long prompt's own check unchanged, unmarked |

### DO NOT bullets dropped as repeats of _common.md

- "Do not push to anything but your branch on origin." (repeats _common.md's "Do not ... push to `master` or to any
  branch other than yours").

### Sections not carried

- "## Context (read once)" to the end (shared tail): repeats prompts/_common.md.
- Opening paragraph (PLAN-v2 section citation, wave 9, base commit and line-number note): citations and history; "re-find
  every site on current origin/master" kept in Dependencies.
- "Owner decisions": owner quotes, [INFERRED] notes, rank and supersession notes (S2 superseded by D20, S1's extra exits
  and S9 without owner quote): owner quotes and rationale; S2 and S9 govern nothing in this phase.
- "PLAN-v2's decision ledger" paragraph (C3.b, "GitHub purge" OPEN row): plan cross-reference codes; its instruction
  (the rewrite does not depend on the purge request) is in A9.
- "What happens today" intro ("measured on f8c18c2 ... git 2.43") and the facts' file:line positions, commit hashes,
  dates, the prototype steps of Fact 6 and its gc warning: citations and history.
- "## Background": background reading list; its instructions are folded into "Find on the merged base" and H10.
- "## Out of scope": out-of-scope category; its instructions are folded (copies of a home -> Pull request; P10's kept
  items -> Find on the merged base and H10; no-edit files -> DO NOT).
- "## Rules added / retired (expected)": rules added / retired category.
- "## Net code cap" rationale (PLAN-v2 citations, "set when P11 was human-run") and "Justify every block in the PR": history
  and PR paperwork; the cap itself is the last DO NOT bullet.
- "Effort" line: effort category.
- "## Branch, pull request, hand-off": branch creation and "subscribe and drive" text (repeats _common.md); the "Notes for
  reviewers" headings (Pull paths after a rewrite, What the pre-push guard refused, Dry run, Experiments, Size budget):
  PR paperwork beyond the allowed body items (their content is acceptance output, choices or Acc17's output). The D24
  table and the summary's first-line content are kept in the Pull request section.

### Totals

Rows: 40 kept, 0 kept-marked, 0 dropped-as-moved, 3 replaced in the long prompt (B3, B6, B7 -> the pre-push guard).
Acceptance tests: 14 kept, 0 kept-marked, 0 dropped-as-moved, 6 replaced in the long prompt (7, 9, 10, 11, 12, 13 ->
(i)-(iii)).

## Verification round

One round, by three subagents that wrote no prompt: one for P2-P4, one for P5, P6 and P9, one for P10 and P11. Each
checked, per phase: (1) the coverage table complete against the long prompt, and every row requirement and every
acceptance pass condition present at full strength, no two tests merged; (2) no rejected idea back; (3) the rulings
agree with DECISIONS.md and none is presented as the owner's words; (4) the line limit, the first and last lines, the
section order, the PR items, no citation and no personal data; (5) the After-P1b marks. Severity: high (a row or test
missing, tests merged, a pass condition weakened, a rejected idea back, a ruling wrong, a limit exceeded), medium (a
concrete row requirement lost or changed, a coverage line wrong, a missing mark, a citation or personal value left),
low (wording, or compression that loses no requirement).

| Phase | High | Medium | Low |
|---|---|---|---|
| P2 | 0 | 2 | 10 |
| P3 | 0 | 1 | 8 |
| P4 | 0 | 2 | 6 |
| P5 | 0 | 14 | 9 |
| P6 | 0 | 0 | 3 |
| P9 | 0 | 7 | 7 |
| P10 | 0 | 5 | 14 |
| P11 | 0 | 1 | 9 |
| Total | 0 | 32 | 66 |

- No high finding, so no second round. Checks 2 and 4 passed in every phase apart from low findings; check 3 found only
  low findings (rulings incomplete, none wrong); check 5 found only low findings.
- Every medium finding was fixed, by one fixer subagent per prompt, each fix in its own commit:
  - P2 (63cc6b1): rows 4, 9 and 11-15 name the P1b delivery each builds on ("Done by P1b ...: verify, change only what
    is left"), 8 new marks; the bwrap limit names both places, README and dev-overnight.md's isolation note.
  - P3 (6601b1f): the DO NOT list names commands/redev.md among the files P3 leaves unchanged.
  - P4 (578146c): the "Already done by P1b: verify, do not redo" list (PV-5 marked) and "Interfaces you consume: use as
    merged, build no second" restored as row items; the STEP7_* rename and Step 8's stage 4 apply where P1b's PR left
    them; row 1 uses the flags P3 shipped; the rating goes after the session summary when P1b deleted the temp note
    (row 7, A6).
  - P5 (ebaec1b): row 1 (no second lookup, the policy-row role as today, fix each count at its source and re-run, no
    workaround in the message), row 3 (git config writes stay with the commit guard), row 4 (P1b's quoted -F read),
    row 5 (the measured CronCreate record and its source; an unmeasured shape takes the rule), row 7 (the do-not-port
    list with `cancelled_by_user`; the merge and push predicates' facts), row 10 (five items), row 15 (the mint
    function's comment), A5 (the mid-turn UserPromptSubmit carry-over), row 18 (the pairing rule), row 20 (Path A and
    pretool-subagent-enforce read `command_span`; which `build_sequence_fix_call` stays), row 22 and A1 (the test files
    named), the arming rule's time-lock exclusion, and the D24 deciders to verify and retire.
  - P9 (e889a21): the E9 condition the right way round; P1b's choice stands for acceptance 23's parentheses, and P1b's
    artifact map governs every row that adds or keeps a check; the charter named; row 9's dangling-reference sites;
    row 14's three items; E1's landing step; E3's replay cases in A16.
  - P10 (e06edc0): experiment 1's full count and the overlay repair's one function (row 2); the earlier phases' "Now
    unreferenced" items as row 6 candidates; row 11's citing files; row 19's three named leftovers and P1b's
    dead-artifact list.
  - P11 (a86128b): the hand-off's owner question quotes verbatim, with their date, the three statements DECISIONS.md D16
    quotes (the short prompt itself quotes none).
- After the fixes every short prompt is within its limit (300; P11 350), the fixers updated their phases' coverage
  sections, and a scan of all eight prompts finds no owner quote, no e-mail address, no home path but the stand-in
  /home/alice, no rejected idea except as a negative statement, and one file:line form (P3 A7's expected grep output,
  a low finding below).

## Found, not fixed

Notes from this pass (not verifier findings):

- Statements that name a P1b deliverable but that no After-P1b entry concerns carry no mark (for example P10 row 19's
  "P1b deletes all of them but L39", and most items of P4's restored "Already done by P1b" list beyond PV-5). The marks
  follow the After-P1b list, as the task asks; the second pass should also re-read every mention of P1b and P1c in the
  short prompts.
- The PR-body hand-off sections for later phases are dropped (the task's PR list); the later short prompts name the
  facts to read on the merged base instead. If the reviewer wants them back, it is one PR item each in P2, P3, P5 and
  P10.
- P11's PR section lists the D24 table beyond the five allowed PR items (verifier low P11-10). Kept: DECISIONS.md
  (Execution) requires every phase PR to carry it and no P11 acceptance test does.
- The rows' instructions to list an item under "Out of scope, found" (P2 rows 5, 7, 9, 14, 16 and similar) were dropped
  as PR paperwork; the PR list keeps "Out of scope, found", and _common.md says what goes there.
- After the fix round, prose lines of 121 to 140 characters occur in P2, P4, P5, P9 and P10 (the fixers' allowance);
  the writers kept 120.

The verifiers' low findings, as they reported them (66). "l.N" are lines of the short prompts as verified, before the
fix commits moved some of them; "coverage-<phase>.md" is that phase's section above.

### P2 (10 low)

- low | 1 | R10 (l.104-106) | The evidence the subagent-session key must come from is gone. Long: settle it from "P1's PR section 'Capability facts for P5' (it also says whether a subagent can call AskUserQuestion at all), the CLI's hooks reference (whether PreToolUse runs for AskUserQuestion, and the session_id, agent_id and transcript_path a subagent's payload carries), and the `sessionId` ... of a subagent transcript in your own session's store (read-only, keys only)"; "If payload.session_id is the parent's, key on it." Short keeps only "a field evidence proves (not baseline.py), ideally CLI-written (transcript path)".
- low | 1 | R17 (l.160-162), Choices l.174 | Arming-timing probe outcomes compressed. Missing: "If the probe cannot be run ..., take (2) and record the probe as unmeasured", and outcome (3)'s "your own arming applies to them at once and is never 'Only sessions started after the update'". "probe absent" in Choices l.174 can be read as "key absent" or "probe not run".
- low | 1 | Acceptance sandbox note (l.185-190) | Driver requirements dropped from the long sandbox note: "FIRST ACTION registrations, the canonical TodoWrite list and `run_in_background: false`", and "subagent transcript under `<sid>/subagents/agent-<id>.jsonl`, `.meta.json`, SubagentStop payload" (the short keeps only "P1's dispatch model").
- low | 1 | A5 (l.211-213), A15 (l.266-267) | "Before" states dropped: specialist_yield "(before: the fallback)", doc-sync "(before: under `$HOME/.claude`)"; A15's pre-P1b overnight lost "make it with d625284's code".
- low | 1 | R6 (l.66-68), R17 (l.156-157) | R6 dropped "in overnight dispatches the registry is under `<MAIN_ROOT>`, as today". R17's "(CLI matching)" compresses "read the CLI's permissions reference ... for how a command that contains a parameter expansion or a quoted first word is matched; if a literal `${…}` rule would not match, pick a form the CLI does match".
- low | 1 | R8 (l.90), R10 (l.103) | The general rule is narrowed to two rows. Long: "row 8's `timelock_released`, and any other transcript read your rows add or move, reads through [P1b row 18's reader]".
- low | 1 | DO NOT l.285 | Narrowed. Long: "Do not read `status`, `terminal_status` or the helper-auth token as a release anywhere." Short limits it to releasing "the lock or deny".
- low | 1 | DO NOT l.295 | Net code cap line lost "the prose should not grow beyond the summary section and the landing route" (commands/, agents/, settings.json outside the cap).
- low | 3 | Owner rulings l.24, l.31, l.38 | Incomplete, not wrong: D10 omits criterion (1) "follows the producer-side design doc"; D18 carries D19's rule ("has no step") and no D19 line exists; D3/D23 say asking releases no Stop but not that answering releases nothing either (D23: "Neither asking nor answering releases a gate").
- low | 5 | coverage-P2.md, After-P1b table | PV-18 and PV-20 (### PLAN-v2.md entries that name P2's share and P2's arming of G1 and G3) are not listed. Both concern PLAN-v2 text only, so no mark is needed; add them as "not carried".

### P3 (8 low)

- low | 1 | Owner rulings D3/D23 (l.26, l.43) | The D3 bullet's "Do not write 'nothing pauses' anywhere." is dropped.
- low | 1 | DO NOT l.286-287, D2 l.25 | The D2 bullet's vocabulary ban lost "or 'accept with known issues'" and "Never word any of this as ... an 'honest' outcome in code comments, gap text, prose or the PR" (short keeps "never worded as failure").
- low | 1 | Rows item "P1b/P1c" (l.146-148) | Dropped from the long "P1b and P1c" bullet: "nothing you add re-derives part of it [the disposition]" and "the lane roster is checked at G3 (P1b row 6)".
- low | 1 | R2 l.67, R10 l.107-108 | Two P1b deliveries are not credited, so "verify each delivery, never redo it" does not reach them: "the completion report leaving the resolver's required chain" and "consumers importing obligation.TERMINAL_VOCABULARY, the replay window's private terminal set included (your replay-window row keeps the 60 s window, S8)".
- low | 1 | Dependencies l.10-11 | Start check weakened. Long: `git show origin/master:hooks/lib/obligation.py | grep -cE '^def (canonical_task_id|registry_dir_for)\('` prints 2. Short: obligation.py "has `canonical_task_id` and `registry_dir_for`" (the top-level def and the count are lost).
- low | 3 | Owner rulings D7 (l.29) | Incomplete, not wrong: DECISIONS D7 and the long TC-16 reading have "the same subagent_type, task_id, lane (lane_set, pipeline, profile) and obligation template and a fresh dispatched_at"; the short says only "same subagent_type and obligation".
- low | 4 | A7 l.219 | "hooks/sessionstart-artifact-census.py:147" has file:line form. It is the exact expected grep output of long acceptance 7, so it may stay; if removed, keep the strength ("only the one line in hooks/sessionstart-artifact-census.py, unregistered, P10's").
- low | 1 | coverage-P3.md, A10 line | The status is "absent in the long prompt", but the long prompt keeps item 10 as a placeholder and the short labels it A10. The status should be "kept (placeholder)".

### P4 (6 low)

- low | 1 | Rows item "Capability facts" (l.134-136), A10 (l.226-227) | The three fact sources and their rules are dropped: (1) your own AskUserQuestion tool definition and the SDK types (sdk-tools.d.ts: `metadata`/`source`, an `answers` field, the output shape with afkTimeoutMs); (2) your own transcript, read-only, keys only, values replaced by `<text>`; (3) the CLI documentation (hooks reference, settings reference for askUserQuestionTimeout and classifyAskUserQuestion, headless or print mode) "quoted with the date you read it. Do not substitute memory."
- low | 1 | R5 l.68 | "(...; no --bulk)" can be read as dropping --bulk, against "Keep ... `--bulk`" (l.73). Long: "Step 3 becomes one `--stage close` call (skipped under --bulk, as today)".
- low | 1 | R10 l.113-114 | "instrument failure (resolver load, timeout): one line, reset stands, exit 2" reads as unconditional. Long: "The two bullets below that exit 2 apply only to a print the replay keeps." (A11 conditions it.)
- low | 1 | Dependencies l.15 | The STOPGATE check lost "you delete consumer checks that the armed G2 now covers, never before the producer gate is live".
- low | 1 | Waits (l.149-150), Choices l.153 | Minor details dropped: for a hook rejection, "if he declines, #4 applies" (CLAUDE.md Subagent Hook Discipline); H-Q5's experiment runs "in the arm-close-commit-producers sandbox".
- low | 3 | Owner rulings D10 (l.27) | Incomplete, not wrong: criterion (1) "follows the producer-side design doc" is omitted.

### P5 (9 low)

- low | 1 | R2 (lines 48-52) | Dropped "Reading stays allowed." and "a deny you do add is temporary, retired with the stores".
- low | 1 | R7 (lines 67-98) | Dropped details: "Heavy modules load lazily here, inside gated spans only" (A9's obligation.py case still tests it); the canonical todo script is "run with the span's arguments in CLAUDE_TODO_PROMPT" and "a later unrelated list is ignored"; dev predicate "never from the workflow bookmark, which agents can write. If the transcript carries no such record, say so and choose the hook-written fact you use instead (D10)"; step 3 "CONTROL, built-in and plugin commands ... never change it".
- low | 1 | R9 (lines 106-113) | Dropped "P7's refused-snapshot notice keeps reaching the user", "`<reason>` a fixed code; otherwise allow and record it", and "Section 13's P5 row ... is delivered by P1: check that it holds on your base and keep it".
- low | 1 | R14 (lines 128-132) | Dropped ""Nothing ahead of upstream" already satisfies the push predicate" (so push.md's nothing-ahead site gets no question) and "(the human types it)" for "run /commit first".
- low | 1 | R17 (lines 140-142) | "make ... true" lost its content: "the launcher registered, the coordinator a phase runner with the completion phase, the obligation, do-report and two todo hooks unregistered (retire their ids, as H-060 – H-063 were), S-004 retired and the completion phase recorded".
- low | 1 | R1 (lines 46-47) | The arming-blocker writes are no longer named: dev.md's spec_path patch, refined/iter context and spec edits, and close.md's "ensures the report file exists" (names suffice, without line numbers).
- low | 1 | R3 (line 55) | The README sentence to rewrite is not identified: "an agent can make such an edit today (denying it is planned, P5-a)".
- low | 1 | R21 (lines 155-158), R15 | Dropped "a /do that cannot proceed asks with AskUserQuestion" (the text that replaces the `blocked` bullet) and do.md's "if kept, this continuation".
- low | 1 | Dependencies (lines 4-13) | Dropped "Do not start from an older base." and "hooks/stop-cleanup-allowlist.sh, which you do not edit".

### P6 (3 low)

- low | 1 | Rows, "File-list authorship", Inheritance bullet (lines 122-127) | It does not say which reader the inheritance search uses. | Long "P1b and P1c": "row 1's `agentType` read from the agent's `.meta.json` and the inheritance search's transcript reads and meta `toolUseId` mapping go through it" (P1b row 18's one reader). R1 says this only for the role read. Fix: add "through P1b's reader" to the Inheritance bullet. (P1b's CI check would catch a second parse, hence low.)
- low | 1 | R1 (line 44) | Correction 4's evidence step was dropped as paperwork. | Long: "Quote the reference with the date you read it" (the CLI hooks reference on `agent_type` without `agent_id`). It can go in the PR summary.
- low | 1 | coverage-P6.md, "Live landing" line | The coverage table says D15 carries "no crash, block only by promoted checks", but the short D15 line (line 30) carries only feature retention and no unregistration. The rule "Every hook you change must accept the transcripts, registries and reports origin/master's code wrote, must not crash on them, and must not block a compliant in-flight subagent except through the promoted checks" is carried only by A17's expected results. Fix: correct the coverage line to "A17", or add the rule to D15.

### P9 (7 low)

- low | 1 | R8 (line 89) | "Hard Rules 5, 7 ... go" goes beyond the long prompt. Long row 8 lists Hard Rule 5 (skip unfixable) and Hard Rule 7 (the Stop hook blocks until end-time) as places for the D20 change ("the session cannot end until every family passes, even past end_time; ... drops the "skipped" and "parked" counters and paths"); it does not say to delete Rule 7. Fix: "Hard Rule 5, the skipped/parked paths and counters go; Hard Rule 7 states that the session cannot end until every family passes, even past end_time".
- low | 1 | Choices E6, E7, E9, E10 (lines 166-174) | Dropped: E9 "Record both runs"; E10 "record the source and date" of the built-in skill list; E7's deep-search check (`ls commands/deep-search.md agents/deep-search.md skills/deep-search` plus the Skill denies); E6 "(record which hooks act)".
- low | 1 | R8 (lines 93, 98) | Dropped: Correction 11 / row 8 "Correction 11's lines inside it, if still there, stay and are listed" (under "Out of scope, found"); "(in one message)" for clean.md's N synchronous calls.
- low | 1 | R4, R12, R15 | Dropped: R12 "the hook stays warn-only for the other categories"; R4's 13 consent readers compressed to "other pretool hooks" (A5's grep partly guards it); R15's `block_streak` docstring not named.
- low | 1 | Owner rulings D24 (line 41) | The table's columns are shortened to "(producers, consumers, proofs)", and no P9 acceptance test carries the table. DECISIONS.md: "artifact / producers before → after / deciding consumers before → after / proof (a grep for writers and readers, plus a sandbox write trace)". Fix: spell out the columns.
- low | 1 | Dependencies (lines 4-13) | Dropped "Do not start from an older base."
- low | 4 | lines 187, 209, 217, 222 | These lines run over 120 characters (141, 128, 135, 152) and carry a label ("- A10:", "- A11 (R10):") or an arrow ("-> nothing.", "-> passed.") beside the command. The writer brief allows a longer line only when it holds one command. Fix: move the label or arrow to its own line.

### P10 (14 low)

- low | 1 | R2, line 45 ("(atomic, 0600, rest byte-identical)") | Exp 2 option (a) dropped "after canonical re-serialisation", so the short asks for more than the long does. | Long: "everything else byte-identical after canonical re-serialisation".
- low | 1 | R5, line 67 (Exp 10) | "each pull path ... from the base's code" dropped (implied by "a live home at your base"). | Long, experiment 10: "each pull path (fswatch `safe_pull`, /pull, a merge pull) from the base's code".
- low | 1 | R4 and R5 | Names of the files that refer to deleted files were dropped (A9's grep still finds them). | Long: "tests/test_bash_write_targets_verb_narrowing.py and hooks/lib/bash_write_targets.py name it" [pretool-overwrite-guard]; "post-commit-warn.sh (named by hooks/posttool-git-warn.sh)"; "scripts/aggregate-dev-report.py names it" [regen-index-dirs.py]; R4's test files test_overwrite_guard.py, test_sessionstart_artifact_census.py, test_baseline_snapshot_preflight.py folded into "with tests".
- low | 1 | R3 | P5's three one-case test-file names and the reference examples were dropped. Option (a) deletes none of them, so no requirement is lost.
- low | 1 | R13 | The planning measurements (AC-R02-10 then 9 unledgered; base may already fail with `member counts 1264 != |L| 1256`; 17 failing tests, 6 matrix rows) and the test-file names (test_bash_safety_context_rules.py, test_bash_execution_boundary.py, pol_iteration5_qa_matrix.v1.json, test_pol_generative_sweeps.py, pol_primary_laxity_ledger.json) were dropped. They are expectations, not pass conditions; "run it on your base first" is kept.
- low | 1 | Acceptance tests, "Sandbox:" lines 195-198 | Setup notes were dropped. | Long: "Keep your drivers under `$SB/drivers` and run them as `/mnt/sb/drivers/…` (sb-setup.sh recreates `$SB/tools`)"; "tools are at /mnt/sb/tools"; "the kit copies `.git`" (full history, needed by A3); "(a clone, not a worktree)"; "tools/runhook.py runs a group's hooks one after another unless `RV_PARALLEL=1` ...".
- low | 1 | A11, A16 | Small details dropped. | A11: "(drivers built on tools/baseline.py)". A16 t_hook_cmd_override: "a hook command in settings.json prefixed `GIT_AUTO_PUSH=1`".
- low | 1 | Dead-code paragraph, lines 179-184 | The search scope is compressed. | Long: "search each subject's path, basename and module name"; loaders "spec_from_file_location, subprocess"; "a test file goes whole only when every test in it exercises only unreachable code".
- low | 1 | R9, line 105 ("delete dead and duplicate rules (doc-sync guards, tests/generated block included)") | This reads as if the doc-sync guards and the tests/generated block are to be deleted. The long lists them as locations to review, and that block is collapsed, not deleted. | Fix: "review every rule (doc-sync guards and the tests/generated block included); delete dead and duplicate ones".
- low | 1 | DO NOT bullets 1 and 4 (lines 287, 290) | Slightly narrowed. | Long: "against your container's real `~/.claude` or real HOME"; "do not print or log an overlay value or a private-literal line" (short: "log a private value").
- low | 1 | Dependencies, line 8 | The `#6: P8, …` subject form and "the body's first line" were reduced to "(subject or body)".
- low | 3 | Owner rulings, D24 (line 34) | "one producer, at least one trusted consumer" weakens DECISIONS.md D24: "exactly one producer and at least one consumer, and its consumers trust one conclusion".
- low | 4 | Owner rulings D24 line and Pull request (lines 34, 297-299) | The writer brief asks the D24 line to say that the PR carries the D24 table when no acceptance test carries it. Here only R19 says so, and the PR section's "Body only" list omits it, which conflicts on its face with R19. | Fix: D24 line add "the PR carries the D24 table (R19)".
- low | 5 | R6, lines 75-81 | The MN-17 statement (row 6 lists the repair-map scripts, schema and tests) is marked on the schema and on `--cycle-reset`. The script names close-commit-repair-orchestrate.py and generate-repair-map.py, and the three repair-map tests, rely on a later sentence's mark (L-P10-01). Acceptable, but imprecise.

### P11 (9 low)

- low | 1 | Fact 4, lines 67-69 | The re-run's setup and part of its expected results were dropped. | Long: setup "a 5-commit repository whose third commit had a private author; a home holding one local-only commit, one stash entry, a checkpoint-style ref, a backup-style ref, a modified tracked file and an untracked file"; results "in every case the modified file and the untracked file survive (pull.sh's stash and pop), and the replayed local commit keeps its author and gets the home's committer identity"; "a clone writes no reflog for `refs/remotes/origin/master` but writes one for the symref `refs/remotes/origin/HEAD`".
- low | 1 | Facts 2, 7 and 8 (lines 64, 72-74) | Details were dropped. | Fact 2: "an identity mapping alone does not change the root; whether a text replacement does depends on the list". Fact 7: the error texts "fatal: --mirror can't be combined with refspecs", "deny deleting a hidden ref" / "deny updating a hidden ref". Fact 8: "writers serialise on `<git dir>/checkpoint-core.lock` (`flock -x 9`) and update the ref with a compare-and-swap"; checkpoint bodies carry `_checkpoint_commit_body`'s marker text.
- low | 1 | A2, lines 90 and 100 | P7b's seeding sources and filters are compressed to "its sources and filters", and "per class" is dropped from what may be printed. | Long: "the overlay's personal env values after migration, the overlay's permission entries naming absolute paths outside the home, the home's git `user.email`, and the marker values of `rev`'s scripts/check-public-core.sh; ... split, trim, drop values shorter than 4 characters, drop shipped defaults, never the bare owner name of the origin URL, de-duplicate"; "Print only counts per class and the sha256 of each file."
- low | 1 | Sandbox `conflict` profile, lines 258-259 | The upstream commit's identity condition was dropped. | Long: "an upstream commit on master editing the same line differently (sandbox identity)".
- low | 1 | Goal, line 21 | The unpulled home's state was dropped (Fact 9 still carries the mechanism). | Long: "a home that has not pulled yet keeps working on the old history and cannot publish it".
- low | 1 | DO NOT bullet 1, line 320 | Under the "DO NOT" heading, "Force-push, delete or create refs, or rewrite history only in a throwaway scratch mirror ..." can be read inverted. | Fix: "Force-push, ref changes and history rewrites happen only in ...".
- low | 3 | Owner rulings D18, line 32 ("the one exception is D23") | The wording is imprecise. The exception is the reviewer's single AskUserQuestion confirmation right before the irreversible publish (DECISIONS.md D18, citing D16 and D23), not D23 as a whole. | Fix: "the one exception is the reviewer's confirmation (D16, D23)".
- low | 3 | Owner rulings D24, line 39 | "one producer, at least one consumer" omits DECISIONS.md D24's "exactly one producer" and "its consumers trust one conclusion".
- low | 4 | Pull request, line 348 ("...; the D24 table.") | The D24 table is listed in the body beyond the allowed items. It adds no work: the D24 ruling line, the long prompt and DECISIONS.md ("Every phase PR carries the D24 artifact table") already require it. It is a form deviation only, and either placement is harmless.
