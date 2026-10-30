# Short prompt P1c: record

`prompts/P1c.md` (1,219 lines, 130,505 bytes; the body before its shared tail "## Context (read once)" is 1,114 lines)
was condensed into `prompts/short/P1c.md`: 350 lines, 43,525 bytes, every line at most 140 characters (counted in
characters; the `…` in two command lines is one character). The method is the one `reviews/short-prompts-record.md`
gives, applied to the task's own keep and drop lists. This record maps every experiment, scope row, suite requirement,
merge-rule item and acceptance test of the long prompt to its place in the short one, then gives the verification round.

- Branch `claude/vibrant-hopper-bazrn8`. No existing file changed; added only `prompts/short/P1c.md` and this record.
- Source: `prompts/P1c.md` as last changed by 92bff83. "Long place" below is a line of that file; "Short place" is a
  label of the short prompt (X1-X10, R1-R21, A1-A17, R-P1 to R-V1, or a section heading).
- Commits: 2ee103a (the short prompt), 6dd25fe (merge of the branch's new D26 commit 6d12486; its message has no
  attribution lines, see "Found, not fixed"), bc20145 (this record), then e57b5bb (round 1 fixes, prompt and record)
  and one commit for round 2's fixes.

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
  other two places, with the long text's meaning ("their" for "his"; the restart.md name and the RD4 citation dropped).
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
  retired (expected)" lists into A14; "Technical choices you make" into the PR's experiment line; of the Rollback section only "R9 in the last commit", "each commit keeps the suite green; a fix and its replay revert
  together" and A17 ("at every commit") (its commit-order steps 1-6 and "say in the PR what each revert restores" are
  dropped); "Out of scope" into the DO NOT list ("Not here: ...") and the PR's "Out of scope, found" item; the
  "Branch and pull request" rules that differ from `_common.md` (title, CI means green, the 60,000-byte limit) into the
  PR section.
- Not carried (PR-body paperwork or text the task drops): the release notes; the PR headings "Suite", "C1-C5",
  "Delivered for later phases" (X5's record of phase, row, done, remaining is kept and goes in the PR's experiment line)
  and "Hand-offs for the sync list" (instructions to the reviewer about other prompts); the commit-subject format
  (`P1c: <what changed>`, `P1c (<item ids>): ...`); "sandbox output" in the DO NOT item on committed captures; the
  per-phase CLAUDE.md branch waiver and planning-document instructions (in `_common.md`). "Effort: XL" was first dropped
  and is kept since the fix round, with D26's consequence (see the verification round).

## Coverage

### Decided by experiment (10 of 10 kept)

| Long item | Long place | Short place | Status |
|---|---|---|---|
| Preamble (where experiments run, rule fixed first, recorded, followed) | 241-247 | "Decided by experiment" lead | kept |
| X1 runner source (import P1b's runner and drivers, extend, port missing pieces; strace rule) | 249-260 | X1 | kept |
| X2 hermetic fixture (layout, landed harness home, experiment, rule, write-audit fixes) | 262-286 | X2 | kept (overlay contents, venv place, "devices aside" and the fix order restored in the fix round) |
| X3 G2 armed (base already armed; experiment; rule; copies deleted; run-time switch; false blocks; F1/F1q/F2) | 288-311 | X3, R9 | kept (the armed-base rule and the clean-form check restored in the fix round) |
| X4 literal-prose conflicts, options (a)-(d), merge.md sub-measure | 313-332 | X4 | kept |
| X5 later phases' lines, corrections 2.21/2.85, smallest-part rule, record | 334-344 | X5 | kept |
| X6 no dead end: (i) enumeration, (ii) classes G/D/H/U, (iii) two replays, recall rule, outside refusals | 346-378 | X6 | kept |
| X7 held git lock: options (A)/(B), experiment, rule with and without /proc, worktree unit test | 380-404 | X7 | kept |
| X8 autonomous resume: facts and sources, the wake, the capability question and its two outcomes, deletion and time-lock, rule, reporting | 406-469 | X8 (question, options, rule), R17 (the change) | kept (the dev-overnight.md wake-step line, the /stop replay and "any later span" restored in the fix round) |
| X9 N1: record, before, (i), (ii), rule, `safe_pull` exit status | 471-489 | X9, R20, R-N1 | kept |
| X10 CI time: estimate, (a), (b), (c), rule, split, full set before merge, P1b's check outside | 491-511 | X10 | kept ("to master" and the cancel clause restored in the fix round; P1b's own schedule not restated; "no repository setting changed" kept in R6 since round 2) |

### Scope rows (21 of 21 kept, plus the kept-base-blocks paragraph and the two row lists)

| Long item | Long place | Short place | Status |
|---|---|---|---|
| "Delivered by P1b" paragraph | 518-531 | "Scope rows" lead | kept, "as P1b merged it" (the agent calls restored in the fix round) |
| Row 1 tests/replay/ fixture, drivers, modes | 535 | R1 | kept |
| Row 2 test_pipelines.py | 536 | R1 (R2-R5) | kept ("both modes" now on rows 2, 3, 5 only, not on X6's test: fix round) |
| Row 3 test_faults.py | 537 | R1 (R2-R5) | kept |
| Row 4 test_no_dead_end.py | 538 | R1 (R2-R5) | kept |
| Row 5 test_regressions.py | 539 | R1 (R2-R5) | kept |
| Row 6 baseline.yml, TESTING.md, coverage step, network guard | 540 | R6 | kept (the coverage step's place restored in the fix round) |
| Row 7 G2 plain exit 2, hand-off and stores deleted, GATE_FAULT | 541 | R7 | kept |
| Row 8 G2 legacy correlation (F7b) | 542 | R7 (R8) | kept |
| Row 9 settings.json STOPGATE | 543 | R9 | kept ("nothing else in settings.json" restored in the fix round) |
| Row 10 e2e gate report resolution | 544 | R10 | kept (the G2/e2e decider split restored in the fix round) |
| Row 11 aggregate script: no blocked canonical, v2 statuses | 545 | R11 | kept |
| Row 12 resolver fan-out optional-parent read | 546 | R11 (R12) | kept |
| Row 13 overnight file check schema from obligation | 547 | R13 | kept |
| Row 14 session index sync | 548 | R13 (R14) | kept ("no analyst prose" restored in the fix round) |
| Row 15 restart.md command spelling | 549 | R15 | kept |
| Row 16 Gate 4 after a recovery resume | 550 | R15 (R16) | kept |
| Row 17 the wake, capability, deletion, time-lock, one todo-comparison rule | 551 | R17 | kept |
| Row 18 literal-prose conflicts (X4) | 552 | R18 | kept |
| Row 19 /dev-overnight compliant cycle (X5) | 553 | R18 (R19) | kept |
| Row 20 pull.sh, git-fswatch.sh (X9) | 554 | R20 | kept |
| Row 21 tests pinning the changes; claims lines | 555 | R20 (R21) | kept |
| "Rows 18 and 19, P1b's kept base blocks" | 557-565 | R18 lead | kept |
| Row 18 list, 10 items (graphify; 5-Bash streak; spec-update; `rm -f`; do.md template; close.md blocks; merge.md and merge.sh; push.md `find`; /dev-command three refusals and the X4 (b) fix; repository-relative paths) | 567-603 | R18 (pilot), R18 /dev-command | kept (the last two items share the /dev-command sub-bullet) |
| Row 19 list, 7 items (empty contract; Step 1 block; subprocess git block; bwrap; E1 and e2e; closeout gate and cycle id; launch prerequisites, no producer question) | 605-628 | R19 sub-bullet | kept, except "never in place on a protected branch" (the launcher refuses it by design) and "the compliant overnight scenario carries no producer question" (a scenario constraint; see "Found, not fixed") |

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
| Setup (kit for "before" trees; suite in the 3.12 venv; never the real home) | 839-843 | "Acceptance tests" lead | kept (the per-tree empty SB and the detached checkout not restated: low) |
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
| 11 Live landing | 902-924 | A11 | kept (the switch-over point, the cycle's own escalation records, the branch-env condition and "with hook text" restored in the fix round) |
| 12 D24 table | 925-934 | A12 | kept (e2e correlation, bookmark and todo file, agent meta restored in the fix round) |
| 13 C1-C5 | 935-940 | A13 | kept |
| 14 Rules added / retired | 941, 952-972 | A14 | kept, with the expected counts; the expected lists given by row (R7, R8, R10-R13, R16, R19's empty contract, each refused prose step; fix round) |
| 15 Net code | 942-943 | A15 | kept |
| 16 Personal values | 944-946 | A16 | kept (the e-mail-shaped placeholder named as "a stand-in .invalid address") |
| 17 Full suite | 947-950 | A17 | kept |

### Goal, rulings, cap, DO NOT, PR

| Long item | Long place | Short place | Status |
|---|---|---|---|
| Goal 1-4 | 115-140 | Goal 1-4 | kept |
| Owner decisions (D25; CC4, CC8, DT2, DT3, DT4, HC2; the 2026-09-28 ruling and C1-C5; D18, D19, D20, D21, D22, D23, D24, D15, D17, D4c/SG6, T0, D2, D8; producer-side; no OPEN decision) | 154-239 | Owner rulings | kept, one clause each, no quotes ("no OPEN decision" in D18's clause) |
| Net code cap | 974-983 | "Net code cap and DO NOT", bullet 1; A15 | kept |
| DO NOT (this phase), 13 items | 1084-1113 | "Net code cap and DO NOT", bullets 2-5 | kept ("sandbox output" not restated: low; "Not here" corrected in the fix round so it no longer forbids X3's deletions, the routing loops or X4/X5 prose) |
| PR: `Owner steps: none.`, summary, acceptance outputs (60,000 bytes), experiment choices, D24 table, "Out of scope, found" | 1039-1079 | "Pull request" | kept, reduced to the task's list |

### Totals

| | Long | Kept in the short prompt | Dropped |
|---|---|---|---|
| Experiments | 10 | 10 | 0 |
| Scope rows | 21 (+ the kept-base-blocks paragraph and 2 lists, 17 list items) | 21 (+ the paragraph and 2 lists, 17 list items) | 0 |
| Suite requirements (definitions, (1), the 21 faults and 7 assertions, table, (3), 4 regressions) | 6 + 1 + 21 + 7 + 1 + 1 + 4 = 41 | 41 | 0 |
| Merge-rule items | 11 | 11 | 0 |
| Acceptance tests | 17 | 17 | 0 |

## Verification round 1

Three subagents that wrote nothing, one area each, read only: (A) X1-X10 and the scope rows; (B) the suite, the merge
rule and A1-A17; (C) the owner rulings against DECISIONS.md and register.md, the rejected ideas, the PR section, the DO
NOT list and the limits. Findings: 4 high, 21 medium (prompt), 31 low, and record inaccuracies.

Checked and clean: the counts (10 experiments, 21 rows, 16 scenarios, 21 faults, 11 merge-rule items, 17 acceptance
tests); no acceptance test merged; no rejected idea reintroduced (parking, after-window or stale-lock questions,
filename-to-role tables and owner/fix fields, continue-cycle.md or a /redev binding, "nothing pauses", answers that end
a command, an honest terminal, checks at /close or /commit, new state files, committed lists read by CI); every ruling
the long prompt names is present, none quoted, none contradicting DECISIONS.md; first and last lines; no personal data.

Fixed (one commit, prompt and record):

| Finding | Severity | Fix in the short prompt |
|---|---|---|
| D26 (merged on the branch during this session): no effort and no split stated | high (C) | Dependencies: "Effort XL: per D26 the reviewer hands P1c out only as sub-phases; push after each commit." The split itself is not made here (new work; see below) |
| R17: the dev-overnight.md wake-step line lost | high (A) | "dev-overnight.md gains the wake step" |
| X8's /stop replay used in A3 but not defined; "drives no Stop after it" lost | high (A) | R17 defines it |
| "R2-R5 (new, both modes)" put X6's test in both modes | high (A) | "both modes" on test_pipelines, test_faults, test_regressions only |
| X2: "device files aside", the fix order, "before merge", the overlay contents, the venv's place | medium (A) | restored |
| X3: replays held to the rule when base is armed; clean form and `render-settings check --staged`; "and re-run" | medium (A) | restored |
| X6: "P1c.md quotes" ambiguous | medium (A) | "prompts/P1c.md" |
| X8/R17: the time-lock reads the whole transcript, "any later span" | medium (A) | restored |
| X10: "to master", "a newer push cancels the older run" | medium (A) | restored |
| "Delivered by P1b": changelog-analyst.md's and qa.md's agent calls | medium (A) | restored |
| R6 coverage step's code location; R9 "nothing else in settings.json"; R10 decider split; R14 "no analyst prose" | medium (A) | restored |
| A11: switch-over point; the cycle's own escalation records; the branch-env condition; "with hook text" (low) | medium (B) | restored |
| A12: e2e correlation, bookmark and todo file, agent meta | medium (B) | restored |
| A14: expected retired list partial | medium (B) | given by row: R7, R8, R10-R13, R16, R19's empty contract, each refused prose step |
| "Not here" forbade X3's deletions, the routing loops and X4/X5 prose | medium (C) | "/close and /commit beyond R14, R18, X3's deletions, the routing loops (P4); ... prose (P9) and hygiene (P10) beyond X4, X5"; producer-side clause "routing loops only re-dispatch" |
| Where experiment results go (D10, D18 technical-choices table) | medium (C) | "setup, counts or exit codes, option, why and revert recorded in the PR (comments if long)"; PR item "details in comments" |
| "use a differing name" readable backwards | medium (C) | "use the merged name" |
| Record: statuses that said "kept" for lost content; Row 18 list count; HX "word for word"; Rollback "folded"; "Effort: XL" as paperwork | medium/low (A, B, C) | corrected in the tables above |

To make room within 350 lines, wording without a condition was shortened (for example X1's "from the kit", X5's list of
phases, X10's "untraced", R8's "per its transcript, not a sibling's", "held to the same" in X7's rule).

## Found, not fixed

- D26 requires P1c (XL) to be split into sub-phases of at most M before hand-out, each with its own branch, PR and
  acceptance tests. Neither prompts/P1c.md nor this short prompt is split; splitting is new work and the task forbids
  it. The short prompt says the reviewer hands P1c out only as sub-phases.
- The merge commit 6dd25fe (merging the branch's new D26 commit) has git's default message without the attribution
  lines. It is pushed; history is not rewritten.
- Low findings left as they are (each judged harmless brevity or covered elsewhere): X1's "exactly", the strace syscall
  list and "record each piece"; X2's five proxy names, "fails fast", origin/HEAD, other home states from the same
  origin; X3's "through P7b's function"; X4's `run_in_background: false`; X5's 2.21 quote on steps 2-4; X6's
  "hook-level" and "the agent keeps working"; X7's "fixed interval" and "no option asks the orchestrator"; X8's 0-candidate wake, "after the summary is written", "where the session scheduled the wake" and "no
  second issuer"; X9's GIT_CONFIG_GLOBAL in scratch; X10's inputs, ubuntu-latest and P1b's own check schedule; R6 "(not a skip)"; R7's "a store another reader uses stays, in the D24 table" and GATE_FAULT's
  classing; R12 "singular cycles unchanged"; R13's obligation qualifier; R16 "where declared"; R21's claims-check
  names; merge.sh's file list; R19's "carries no producer question" (a scenario constraint) and "never in place on a
  protected branch"; F4c "removed by that process"; A2's "say so" on a failed unshallow; the acceptance setup's per-tree
  SB and detached checkout; "commit.py" in the expected-producer gap; `isMeta` and "is_human_prompt rejects it" for
  the wake; restart.md's name in HX; A8's expected classes; A10's examples; the merge rule's example lists; the rulings'
  INFERRED marks for D20's preset default and D21's mechanism, D24's "trust one conclusion", D23's "specific decision";
  "sandbox output" in the captures item; the commit-subject format.

## Verification round 2

Round 1 found high-severity defects, so a second round ran: one subagent that wrote nothing reviewed e57b5bb's diff
against prompts/P1c.md and DECISIONS.md. It confirmed every fix in the round-1 table, the D26 line (agrees with D26,
invents no split), the limits (350 lines, at most 140 characters, first and last lines, no e-mail) and no rejected idea
reintroduced. It found that the room-making shortenings of e57b5bb had dropped two conditions:

| Finding | Severity | Fix |
|---|---|---|
| X10/row 6 "the PR changes no repository setting" removed by e57b5bb | high | R6: "no repo setting changed" |
| A3 "those ... your base still shows" lost "still shown", widening the pass condition to all hand-off items | medium | "P1b's hand-off items (both) still shown among them" |

Not fixed (low; a round fixes only medium or higher): e57b5bb also shortened X7's (B) rule from "same conditions before
merge" to "held to the same", dropping "before merge"; and X5's list now says "P3" where the long prompt says "the
resolver (P3)", which reads wider beside "Not here: disposition and gaps (P3)" (X5's own rule still limits the work to
the smallest part of the later row that clears a block).
