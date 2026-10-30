# Short prompt P1c: record

`prompts/P1c.md` (1,219 lines, 130,505 bytes; the body before its shared tail "## Context (read once)" is 1,114 lines)
was condensed into `prompts/short/P1c.md`: 350 lines, 42,459 bytes, every line at most 140 characters (counted in
characters; the `…` in two command lines is one character). The method is the one `reviews/short-prompts-record.md`
gives, applied to the task's own keep and drop lists. This record maps every experiment, scope row, suite requirement,
merge-rule item and acceptance test of the long prompt to its place in the short one, then gives the verification round.

- Branch `claude/vibrant-hopper-bazrn8`. No existing file changed; added only `prompts/short/P1c.md` and this record.
- Source: `prompts/P1c.md` as last changed by 92bff83. "Long place" below is a line of that file; "Short place" is a
  label of the short prompt (X1-X10, R1-R21, A1-A17, R-P1 to R-V1, or a section heading).
- Commits: the short prompt, the merge of the branch's new D26 commit (6d12486), this record, then the fix round.

## How the short prompt was written

- One writer (the orchestrating session), from the long prompt and DECISIONS.md; three verifier subagents that wrote
  nothing (below).
- Sections in the task's order: `Owner steps: none.` and the title; "Dependencies and start checks" (with the interfaces
  P1b and earlier phases deliver); Goal; Owner rulings; "Decided by experiment"; "Scope rows"; "The suite"; "Merge rule
  from P1c on"; "Acceptance tests"; "Net code cap and DO NOT"; "Pull request"; last line `Read prompts/_common.md; this
  file overrides it where they differ`.
- Labels: experiments keep X1-X10; scope rows become R1-R21 (row N -> RN); acceptance tests become A1-A17 (N -> AN);
  regressions keep R-P1, R-E1, R-N1, R-V1. The requirement (2) exceptions that the long prompt states three times
  (Goal 1 (2), suite (2) fourth assertion, acceptance 4) are stated once as "HX" in "The suite" and named from the
  other two places, word for word as the long prompt's text.
- P1b's deliverables keep their names and say "as P1b merged it" (the runner, the ten drivers, the D24 table format and
  check, E1, "Out of scope, found", "Hand-off to P1c", "Live landing" stubs, the transcript reader, the "Delivered by
  P1b" rows, the routing loops). Nothing about them is resolved.
- Prose wrapped at 140 characters, list continuation lines indented. No markdown tables.
- Dropped as the task lists: file:line citations (the d625284 line numbers; function names and quoted texts stay where a
  row needs them to find its site), history and rationale, the Background section, the shared tail, and PR-body
  sections beyond the six the task allows.
- Dropped and pointed to instead: the pilot's measurements ("What the pilot measured", its fault table and timings). A4
  compares with that table and X10 takes its timings as input, so the short prompt names the section in
  `prompts/P1c.md` (in the planning documents every session extracts) instead of copying it.
- Folded: "Before you start" and "Interfaces you consume" into "Dependencies and start checks"; the "Rules added /
  retired (expected)" lists into A14; "Technical choices you make" into the PR's experiment line; the Rollback commit
  order into "R9 in the last commit", "each commit keeps the suite green; a fix and its replay revert together" and A17
  ("at every commit"); "Out of scope" into the DO NOT list ("Not here: ...") and the PR's "Out of scope, found" item; the
  "Branch and pull request" rules that differ from `_common.md` (title, CI means green, the 60,000-byte limit) into the
  PR section.
- Not carried (PR-body paperwork or text the task drops): the release notes; the PR headings "Suite", "C1-C5",
  "Delivered for later phases" (X5's record of phase, row, done, remaining is kept and goes in the PR's experiment line)
  and "Hand-offs for the sync list" (instructions to the reviewer about other prompts; R17 keeps "typed-/restart-only
  prose goes to P9" only as the X8/R17 rule that the widened exception is P1c's own decision); "Effort: XL"; the
  per-phase CLAUDE.md branch waiver and planning-document instructions (in `_common.md`).

## Coverage

### Decided by experiment (10 of 10 kept)

| Long item | Long place | Short place | Status |
|---|---|---|---|
| Preamble (where experiments run, rule fixed first, recorded, followed) | 241-247 | "Decided by experiment" lead | kept |
| X1 runner source (import P1b's runner and drivers, extend, port missing pieces; strace rule) | 249-260 | X1 | kept |
| X2 hermetic fixture (layout, landed harness home, experiment, rule, write-audit fixes) | 262-286 | X2 | kept |
| X3 G2 armed (base already armed; experiment; rule; copies deleted; run-time switch; false blocks; F1/F1q/F2) | 288-311 | X3, R9 | kept |
| X4 literal-prose conflicts, options (a)-(d), merge.md sub-measure | 313-332 | X4 | kept |
| X5 later phases' lines, corrections 2.21/2.85, smallest-part rule, record | 334-344 | X5 | kept |
| X6 no dead end: (i) enumeration, (ii) classes G/D/H/U, (iii) two replays, recall rule, outside refusals | 346-378 | X6 | kept |
| X7 held git lock: options (A)/(B), experiment, rule with and without /proc, worktree unit test | 380-404 | X7 | kept |
| X8 autonomous resume: facts and sources, the wake, the capability question and its two outcomes, deletion and time-lock, rule, reporting | 406-469 | X8 (question, options, rule), R17 (the change) | kept |
| X9 N1: record, before, (i), (ii), rule, `safe_pull` exit status | 471-489 | X9, R20, R-N1 | kept |
| X10 CI time: estimate, (a), (b), (c), rule, split, full set before merge, P1b's check outside | 491-511 | X10 | kept (the last clause shortened to "no scenario in neither set"; P1b's own schedule not restated) |

### Scope rows (21 of 21 kept, plus the three row lists)

| Long item | Long place | Short place | Status |
|---|---|---|---|
| "Delivered by P1b" paragraph | 518-531 | "Scope rows" lead | kept, "as P1b merged it" |
| Row 1 tests/replay/ fixture, drivers, modes | 535 | R1 | kept |
| Row 2 test_pipelines.py | 536 | R1 (R2-R5) | kept |
| Row 3 test_faults.py | 537 | R1 (R2-R5) | kept |
| Row 4 test_no_dead_end.py | 538 | R1 (R2-R5) | kept |
| Row 5 test_regressions.py | 539 | R1 (R2-R5) | kept |
| Row 6 baseline.yml, TESTING.md, coverage step, network guard | 540 | R6 | kept |
| Row 7 G2 plain exit 2, hand-off and stores deleted, GATE_FAULT | 541 | R7 | kept |
| Row 8 G2 legacy correlation (F7b) | 542 | R7 (R8) | kept |
| Row 9 settings.json STOPGATE | 543 | R9 | kept |
| Row 10 e2e gate report resolution | 544 | R10 | kept |
| Row 11 aggregate script: no blocked canonical, v2 statuses | 545 | R11 | kept |
| Row 12 resolver fan-out optional-parent read | 546 | R11 (R12) | kept |
| Row 13 overnight file check schema from obligation | 547 | R13 | kept |
| Row 14 session index sync | 548 | R13 (R14) | kept |
| Row 15 restart.md command spelling | 549 | R15 | kept |
| Row 16 Gate 4 after a recovery resume | 550 | R15 (R16) | kept |
| Row 17 the wake, capability, deletion, time-lock, one todo-comparison rule | 551 | R17 | kept |
| Row 18 literal-prose conflicts (X4) | 552 | R18 | kept |
| Row 19 /dev-overnight compliant cycle (X5) | 553 | R18 (R19) | kept |
| Row 20 pull.sh, git-fswatch.sh (X9) | 554 | R20 | kept |
| Row 21 tests pinning the changes; claims lines | 555 | R20 (R21) | kept |
| "Rows 18 and 19, P1b's kept base blocks" | 557-565 | R18 lead | kept |
| Row 18 list, 9 items (graphify; 5-Bash streak; spec-update; `rm -f`; do.md template; close.md blocks; merge.md and merge.sh; push.md `find`; /dev-command three refusals and the X4 (b) fix; repository-relative paths) | 567-603 | R18 (pilot), R18 /dev-command | kept (the last two items share the /dev-command sub-bullet) |
| Row 19 list, 7 items (empty contract; Step 1 block; subprocess git block; bwrap; E1 and e2e; closeout gate and cycle id; launch prerequisites, no producer question) | 605-628 | R19 sub-bullet | kept ("never in place on a protected branch" and "no producer question; P2 adds D20's replay" not carried: the launcher refuses the first by design, the second states what P2 does) |

### The suite (every requirement kept)

| Long item | Long place | Short place | Status |
|---|---|---|---|
| Gate block | 633 | "The suite": Gate block | kept |
| Hook error | 634-635 | "The suite": Hook error | kept |
| Expected producer (incl. the d625284 /merge, /push gap and the scope-row rule) | 636-641 | "The suite": Expected producer | kept |
| Next round (four cases) | 642-645 | "The suite": Next round | kept |
| Human event (incl. X8's wake) | 646-650 | "The suite": Human event | kept |
| Terminal, per pipeline (ten) | 651-659 | "The suite": Terminal | kept |
| (1) 16 scenarios, the overnight end_time rule, the CLOSE_REPORT_APPEND_ERROR cause, asserts, table | 661-673 | (1) | kept |
| (2) 21 faults (F1, F1q, F2, F2j, F2g, F3a, F3q, F3b, F4, F4c, F4s, F5, F5f, F6, F6o, F7, F7b, F8, F8q, F8p, F8c) | 675-696 | (2) | kept, 21 of 21 (P1b's acceptance 7 note not carried: it describes P1b) |
| (2) assertion 1: block names path and check | 697-698 | (2) first bullet | kept |
| (2) assertion 2: receiving actor = expected producer, repair by same agent | 699-701 | (2) second bullet | kept |
| (2) assertion 3: next round passes, terminal reached | 702 | (2) second bullet | kept |
| (2) assertion 4: 0 human events except the human's own commands | 703-708 | (2) second bullet, "HX" | kept, wording in HX |
| (2) assertion 5: F4, F4c/F4s, F2g | 709-710 | (2) third bullet | kept |
| (2) assertion 6: F8 faults routing | 711-719 | (2) fourth bullet | kept |
| (2) assertion 7: no hook error | 720 | (2) first bullet | kept |
| (2) table | 721-722 | (2) "Table" | kept |
| (3) No dead end: X6 | 724 | (3) | kept |
| (4) R-P1 | 727-731 | R-P1 | kept |
| (4) R-E1 | 732-734 | R-E1 | kept |
| (4) R-N1 | 735-737 | R-N1 | kept |
| (4) R-V1 | 738-747 | R-V1 | kept |

### Merge rule from P1c on (every item kept)

| Long item | Long place | Short place | Status |
|---|---|---|---|
| Full set green on the head; PR body pastes the (1)-(4) summary tables | 751-752 | Merge rule, bullet 1 | kept |
| Fault replay per process class, derived from traces; the files and keys on each replay's path | 753-760 | bullet 2 | kept |
| Files sorted outside settings.json, commands/, agents/, at test time; tests; the runtime set's four kinds | 760-769 | bullet 3 | kept (the test directories hooks/tests/ and scripts/install/tests/ are covered by "a directory named tests") |
| Comment-only definition (Python, shell) | 769-771 | bullet 3 | kept |
| Fail condition (runtime-set file or settings key on no replay's path) | 771-773 | bullet 4 | kept |
| CLI-only key printed as a fact | 773-774 | bullet 4 | kept |
| Facts printed: comment-only changes; test, CI-only, used-by-no-process classes | 774-778 | bullet 4 | kept (the example list cut to "e.g. INDEX.md") |
| commands/ and agents/ definitions must be read by a replay, else fail and add the scenario | 778-782 | bullet 5 | kept |
| What "reached" means, read at test time, skipped-branch agents count | 782-786 | bullet 5 | kept |
| Other commands/agents files printed as facts; no PR-body reason; deletions exempt | 786-787 | bullet 5 | kept |
| A pipeline-shape change updates its scenarios in the same commit, keeps every assertion | 788-789 | bullet 6 | kept |

### Acceptance tests (17 of 17 kept, none merged)

| Long | Long place | Short | Status |
|---|---|---|---|
| Setup (kit for "before" trees; suite in the 3.12 venv; never the real home) | 839-843 | "Acceptance tests" lead | kept |
| 1 Base | 845 | A1 | kept |
| 2 CI baseline, (a) and (b), root and shallow-clone verdicts | 846-857 | A2 | kept |
| 3 Requirement (1), wakes, "before" refusals, no DEVIATION, D24 check | 858-865 | A3 | kept |
| 4 Requirement (2), fault table, "before" vs pilot | 866-874 | A4 | kept |
| 5 Requirement (3), counts, recall, classes, two replays, "before" | 875-879 | A5 | kept |
| 6 Requirement (4), each "before" | 880-883 | A6 | kept |
| 7 Hermetic and network-free | 884-888 | A7 | kept |
| 8 Fault coverage | 889-894 | A8 | kept (the expected classes of tests/replay/, TESTING.md, baseline.yml not restated) |
| 9 Run time | 895-896 | A9 | kept |
| 10 Unit tests for rows 7, 8, 10-14, 16-20 | 897-901 | A10 | kept (examples shortened, marked "e.g.") |
| 11 Live landing | 902-924 | A11 | kept |
| 12 D24 table | 925-934 | A12 | kept |
| 13 C1-C5 | 935-940 | A13 | kept |
| 14 Rules added / retired | 941, 952-972 | A14 | kept, with the expected counts and lists |
| 15 Net code | 942-943 | A15 | kept |
| 16 Personal values | 944-946 | A16 | kept (the e-mail-shaped placeholder named as "a stand-in .invalid address") |
| 17 Full suite | 947-950 | A17 | kept |

### Goal, rulings, cap, DO NOT, PR

| Long item | Long place | Short place | Status |
|---|---|---|---|
| Goal 1-4 | 115-140 | Goal 1-4 | kept |
| Owner decisions (D25; CC4, CC8, DT2, DT3, DT4, HC2; the 2026-09-28 ruling and C1-C5; D18, D19, D20, D21, D22, D23, D24, D15, D17, D4c/SG6, T0, D2, D8; producer-side; no OPEN decision) | 154-239 | Owner rulings | kept, one clause each, no quotes ("no OPEN decision" in D18's clause) |
| Net code cap | 974-983 | "Net code cap and DO NOT", bullet 1; A15 | kept |
| DO NOT (this phase), 13 items | 1084-1113 | "Net code cap and DO NOT", bullets 2-5 | kept |
| PR: `Owner steps: none.`, summary, acceptance outputs (60,000 bytes), experiment choices, D24 table, "Out of scope, found" | 1039-1079 | "Pull request" | kept, reduced to the task's list |

### Totals

| | Long | Kept in the short prompt | Dropped |
|---|---|---|---|
| Experiments | 10 | 10 | 0 |
| Scope rows | 21 (+ 3 lists, 16 list items) | 21 (+ 3 lists, 16 list items) | 0 |
| Suite requirements (definitions, (1), the 21 faults and 7 assertions, table, (3), 4 regressions) | 6 + 1 + 21 + 7 + 1 + 1 + 4 = 41 | 41 | 0 |
| Merge-rule items | 11 | 11 | 0 |
| Acceptance tests | 17 | 17 | 0 |
