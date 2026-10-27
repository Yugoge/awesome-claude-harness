# Coverage cross-check: prompts P9, P10, P11 against P7b, P1-P8

Inputs: prompts-p9-p11/{P9,P10,P11}.md (each ends with prompts/_common.md byte-for-byte: `cmp` OK for all three, before
and after the fixes below, and `## Context (read once)` occurs once in each); the eight earlier prompts in
harness-repair-plan/prompts/ (P7b, P1, P8, P2, P3, P4, P5, P6; tails also `cmp`-identical); DECISIONS.md (D1-D19);
PLAN-v2.md (sections 4-7, P9, P10, P11, 13, 14); COVERAGE.md (the matrix for P7b, P1-P8, extended here); HANDOVER.md
(owner-gap questions 1-12); the planning STATE (owner messages O1-O45 and the 2026-10-17..19 addendum). File:line claims
were re-read on a `git archive` of master f8c18c276e92e07c14487e9908490aa4bdefbc3a. Status at the time of this check
(relayed owner message): P1 is done, P8 is still running; P7b is being implemented by the reviewing session (branch
repair/P7b, head 1e6c30d8, read-only here); P2-P6 have not started.

Experiments run for this check (scratch only, HOME and git config in scratch):
- X1 doc-sync on a live home: f8c18c2's hooks/posttool-doc-sync.py replayed for one Edit of commands/redev.md in a scratch
  copy of the tree -> `git status`: ` M CLAUDE.md`, ` M commands/INDEX.md` (only the `*Last updated:*` and the
  `> Last updated:` lines change).
- X2 modify/delete on a pull: a home whose commands/INDEX.md is re-dated, upstream deletes it; stash, `pull --rebase`,
  pop -> `DU commands/INDEX.md`; the next pull's stash step -> `commands/INDEX.md: needs merge`; `git pull --rebase` ->
  `fatal: Exiting because of an unresolved conflict.` The home receives no later merge.
- X3 adjacency on a pull (f8c18c2's scripts/INDEX.md): upstream removes one listing row far from the header -> clean
  (` M scripts/INDEX.md`); upstream changes `**Total entries**` (the line after the re-dated date line) -> `UU`.
- X4 reads at f8c18c2: all 23 agent files carry the "Requirement Baseline and Scope Authority" heading; "Critical-Thinking
  Charter" exists only in agents/ba.md (:14-20, inside the :8-21 heading-to-heading span); agents/INDEX.md and
  agents/README.md have no YAML frontmatter; settings.json has no Skill(INDEX:*) or Skill(README:*) deny; commands/commit.md's
  late-repair steps run scripts/late-repair-controller.py and nothing runs scripts/close-commit-repair-orchestrate.py;
  README.md :400, :479, :570 and ARCHITECTURE.md :329 name stop-overnight-timelock.py or posttool-todo-sequence.py as
  live hooks; commands/dev-overnight.md:1574 (TIME CHECK) claims a time computation scripts/overnight-status.sh does not
  do (it prints the state and exits 0); CLAUDE.md names nothing P10 or P11 changes; root README.md has no doc-sync block.
- X5 the in-progress P7b landing: `scripts/install/land --state` prints landed | hooks | removed | upgraded | none;
  `render-settings land` repairs only settings.json among unmerged paths (its `_unmerged` set is skipped), as P7b R2 says.

## (a) Dependencies and order

| Prompt | Stated wave | Must be merged first (how checked) | Products checked, and the prompt that ships each | PLAN-v2 / HANDOVER | Match |
|---|---|---|---|---|---|
| P9 | 7, alone | P7b, P1, P8, P1b, P1c, P2, P3, P4, P5, P6 (merge titles in `git log --merges --format='%H %s%n%b'`) | hooks/lib/close_rating.py, hooks/posttool-close-rating.py (P4 row 7); hooks/stop-launch.py, hooks/stop-command-gate.py (P5 rows 7, 10); do-report.v1 without "blocked" (P5 row 21); agents/dev.md without the git derivation (P6 acceptance 11); `"CLAUDE_OBLIGATION_STOPGATE": "block"` (P2 row 17); tests/generated/INDEX.md absent (P8 row 3b); scripts/score-update.sh present (nobody before P9 deletes it: P4 DO NOT) | W7 after P6 and P8; HANDOVER "P9 after P6" | yes (stricter, transitively implied) |
| P10 | 8, alone | P7b, P1, P8, P1b, P1c, P2-P6, P9 | stop-launch.py and its one registration (P5 rows 10, 12, acceptance 22); a `# STUB:` file incl. stop-completion-gate.py (P1 row 22); score-update.sh absent (P9 row 10); conftest.py without collect_ignore (P8); auto-commit.sh calls the landing (P7b R1; implementation: scripts/install/land) | W8 after P9 | yes |
| P11 | 9, alone, last | every phase PR (P7b, P1, P8, P1b, P1c, P2-P6, P9, P10) and no open PR | landing trigger (P7b R1); engine reads private-literals.txt (P7, kept by P8: f8c18c2 check-public-core.sh :54-61); scripts/size-ratchet.py (P10 row 15) | W9, every PR merged, none open; owner go-ahead at execution (D16, D18) | yes |

Merge order is strictly sequential (P9 -> P10 -> P11), as told to the owner (O45) and in HANDOVER. P0, P0b and P7 are
ancestors of f8c18c2 (the merge-base check). The merge-title check reads the body, which carries the PR title of a
GitHub-made merge; a squash merge would defeat it (the reviewer merges with merge commits, as for PR #4).

## (b) Items deferred to P9, P10, P11 -> exactly one prompt

Legend: "P9 row n", "P10 row n", "P11 An/Bn" = the scope row or requirement; "exp" = experiment; "fixed" = gap closed by
a fix in section (d).

### From COVERAGE.md (decisions and owner statements, "Deferred (later)" column)

| Item | Delivered by | Status |
|---|---|---|
| D1: delete the 255 remote refs | P11 A8 step 4 (script); the reviewer runs it after the go-ahead | ok |
| D2: P9 prose pass; P10 dev-report.v1 projection (TC-35) | P9 rows 8-9, acceptance 10; P10 row 7, exp 8 | ok |
| D3: P9 prose; CLAUDE.md Hook Discipline (UD-CM) | P9 row 16 (CLAUDE.md edited in the PR under D19) | ok |
| D4: P10 stub deletion | P10 row 3 (experiment 3, option (a): the six stubs stay tracked exit-0 files) with the overlay repair (R-e) | ok |
| D5: CLAUDE.md:60 | P9 row 16 | ok |
| D9a: scripts, injection, echo contracts, tests, OPTIONS_XML; H-Q10 | P9 rows 10-13, E1 | ok |
| D12: history | P11 A2-A7 | ok |
| D15: stub deletion | P10 row 3 | ok |
| D16: history at the end | P11 (stage 1 code, scratch script, reviewer's single run) | ok |
| D17: rest of I5/I6, unregistered hook files | P10 rows 4, 6 | ok |
| O2 prose pass, clean tree, ratchet, recoverable removal | P9; P10 rows 13-15 | ok |
| O4/O6 one producer per fact | P9 rows 1-6 | ok |
| O11 / O21 / O19 history and refs | P11 | ok |
| O17/O18, O20 prose and scoring | P9 | ok |
| O35 dead code now | P10 | ok |
| O44 no owner step: UD-CM, H-Q10, doctor on each home, P11 human steps | P9 row 16 and E1; P10 per-home retirement; P11 stage 1/2 and the reviewer's run | ok |
| O45 P9 -> P10 -> P11 | (a) | ok |

### PLAN-v2 rows and ledger

| Source | Delivered by | Status |
|---|---|---|
| P9 table (spec_path, doc-sync, settings, consent, roster and git table, includes, prose, score tests/scripts/prose, OPTIONS_XML, config, README/ARCHITECTURE, CLAUDE.md) | P9 rows 1-16 (one-to-one; sources file maps each) | ok |
| P10 table (doctor, junk, stubs, TC-35, I5/I6, graphify/propagate/sweep/seal/.gitignore, records, ba/backlog/git rm/cleaner/ratchet) | P10 rows 1-18 | ok |
| P11 steps 1-8 and goal bullet 4 (the pre-push guard) | P11 A1-A9 (steps 2-8), B1-B9 (the landing on each home, D19; no re-sync: B3, B6 and B7 deleted 2026-10-23 for the pre-push guard), stage 2 hand-off (step 1's checks become A8 preflight and hand-off item 3) | ok |
| Ledger UD-CM, UD1, UD4, UD5, UD6, UD7, UD8, U-F3c, U2/U6/U7, U-E3b, H-Q10, D-D1e | P9 E1-E10, row 14 | ok (decided by experiment) |
| Ledger U-E1a (D17), U-E1b, U-E1c, E2.b, U-E2a, U-F1a, U-F2a; TC-35, TC-37, TC-53..TC-57 | P10 exps 1-9, acceptance 11-15, rows 6-15 | ok; U-E1b's exception narrowed (fix 9) |
| Ledger C3.b, GitHub purge | P11 (C3.b resolved by S7/D16; purge: A9 text, filed by whoever the docs allow) | ok |
| Section 13 P9 row (refused-snapshot wording; REG-D and `!`/`&` limits) | P9 row 14 + Correction 9 (P5 row 6 fixed the over-blocks) | ok |
| Section 14 P0b residuals | P9 row 8 (commands/checkpoint.md); P10 "P0b residuals" (read_command_spec, B4, B5, L1-L3) | ok |
| Section 14 "skip dev.md:192, :215, dev-command.md:137, :160" | P9 Correction 11, DO NOT | ok |
| STATE 8.11 stale points (TC-53 revert; laneb in TC-35) | P10 corrections 1, 2 | ok |

### Hand-offs written into the earlier prompts

| From | Item | Delivered by | Status |
|---|---|---|---|
| P1 | stop-completion-gate stub, marker | P10 rows 1, 3 | ok |
| P1 | close-commit-repair-orchestrate.py; failed_attempts readers (pm.md :338, :627; build-pipelines-from-triage.py); update-overnight-state.sh `--inc-fail` | P10 row 6 ("every item of What earlier phases left") | ok; P3's "kept (late-repair route)" reconciled (fix 10) |
| P1 | CLAUDE.md, INDEX/README, docs prose | P9 | ok |
| P2 | `--cycle-reset` bypass; kept old permission spellings | P10 row 6; exp 6 | ok |
| P2 | do.md:53; design doc :184, :216 | P9 row 8 | ok |
| P2 | qa-status-gate-gap-...-20261005.md | P10 row 11 | ok |
| P2 | dev-overnight.md:1574 TIME CHECK (false claim) | nobody | fixed (P9 row 8, fix 4) |
| P2 | update-overnight-state.sh `find_state_file` any-session fallback; hooks/install-auto-sync.sh `~/.claude` spellings | nobody (not dead code, not prose) | residual for the reviewer (section (g)) |
| P3 | spec clause | P9 row 1 | ok |
| P3 | Step 16/17 loops -> one re-dispatch sentence, no include (D21) | P9 row 7 | ok |
| P3 | sessionstart-artifact-census.py | P10 row 4 | ok |
| P4 | D9a list (scripts, tests, dev.md scoring, echo contracts, style-inspector :339, OPTIONS_XML, dev-overnight :117/:142, score allows, residue entries, false comments, H-Q10) | P9 rows 10-13, E1 | ok |
| P4 | close-route-select.py, write-enforce-flag `artifact-contract` | P10 exp 7 | ok |
| P4 | dev.md/dev-command.md flag lines | P4 itself; P9 skips | ok |
| P5 | the stubs, their three test files, Arming option-1 shim | P10 row 3, exp 5 | ok |
| P5 | README limits lines (:305-306, :311-314); do.md :2 | P9 row 14, row 8 | ok |
| P5 | README :400, :479, :570, ARCHITECTURE :329 naming stubs as live hooks (P5 row 17) | P9 row 14 named only :536 and ARCHITECTURE :167 | fixed (fix 3) |
| P6 | FIRST ACTION lines; changelog-analyst :253-256; candidate_tree :69-83; U-F3c | P9 rows 8, 9, E6 | ok |
| P6 | attribution_aggregate_view; agent-index.json in product repos | P10 row 6; exp 9 | ok |
| P7b | the landing (trigger, lock, notice, log, "landed" fast path) | extended by P9 (E1/E9, optional), P10 (R-e, exp 10), P11 (B1-B9; B3, B6 and B7 deleted); each keeps the earlier steps | ok |
| P7b | off-site backup out of scope | nobody | fixed (P11 out of scope, D18 rule; fix 13) |
| P8 | unreachable code outside its list; overwrite-guard; gen-test-baseline.py; rest of .gitignore; ratchet | P10 rows 4, 6, 9, 15 | ok |
| P8 | score shell tests; residue entries | P9 rows 10, 13 | ok |
| P8 | history, refs, GitHub purge | P11 | ok |
| P8 | git-clean AC matrix (row 4e, not delivered) | none; P10 out of scope | resolved by D19 (owner data, owner step refused) |
| any PR | "Out of scope, found" / "Now unreferenced" items copied into section 13 after each merge (COVERAGE fix 13) | P10 read section 13; P9 and P11 did not | fixed (fixes 5, 15) |

### Done twice

None after the fixes. Sequential overlaps (each later phase builds on the merged earlier state, no item delivered
twice):

| File or item | P9 | P10 | P11 | Note |
|---|---|---|---|---|
| agents/ba.md | row 7 (shared charter), rows 9, 11 | row 12 (Critical-Thinking Charter, backlog, verdict) | - | was a collision: P9's ":8-21" span held P10's subject (fix 1) |
| agents/INDEX.md, agents/README.md | rows 8-9 edit the doc-sync lines that mirror agent descriptions | row 5 deleted them on an unverified premise | - | P10 now deletes them only if Claude Code loads a frontmatter-less agents/*.md (fix 9) |
| .gitignore | row 13 (false comment), E1 keeps `/agent-scores.json*`, `logs/*` | row 9 minimisation | - | P10 could have deleted E1's lines as "no writer" (fix 8) |
| INDEX.md, scripts/INDEX.md, scripts/README.md, tests/INDEX.md, TESTING.md | row 10 rows | row 18 rows | - | pull-safety rule now in both (fixes 6, 7) |
| P7b's landing | E1/E9 at most one step | R-e, exp 10 | B1-B9 (B3, B6, B7 deleted) | P10, P11 told to keep earlier steps |
| settings.json | row 3 (dead denies, missing/score allows) | row 17 (allows of deleted targets, old spellings), env | none | disjoint |
| hooks/pretool-bash-safety.sh | consent readers | git rm block | none | disjoint |
| hooks/prompt-workflow.py | rows 1, 4, 5 | read_command_spec | none (DO NOT) | disjoint functions |
| commands/do.md :53 | row 8 (after P5 row 15) | row 18 (deleted-path lines only) | - | sequential |
| CLAUDE.md | row 16 | barred | barred | single editor (D19 exception) |

## (c) Contradictions with earlier deliverables, and fixes applied (P9-P11 only; tails unchanged)

| # | Prompt (current lines) | Problem, with evidence | Fix applied |
|---|---|---|---|
| 1 | P9 row 7 (:399) | "the charter (agents/ba.md:8-21 plus 17)" -> "2 identical inline lines": ba.md :8-21 includes BA's "### Critical-Thinking Charter" (:14-20; X4), which P10 row 12 and acceptance 19 edit (grep instead of full read; `verdict: patch \| redesign \| retire`) | charter = the shared block (ba.md :8-12 and its copy in all 23 agents); the Critical-Thinking Charter stays; acceptance 8 checks it is still there |
| 2 | P9 E9 (:304-330), acceptance 19 (:539-544) | E9 replays "a Write in the harness" and checks only that the pull ends clean. X2/X3: a deleted file the home re-dated leaves `DU` and wedges every later pull (P7b's landing repairs only settings.json, X5); a count line next to the date line leaves `UU`. P9 deletes index files (row 10) and edits index rows | Writes in each directory whose index file the branch edits or deletes; measured facts stated; rule checked after one Stop plus a second /pull; edit-shape rule for index files; the one landing step a deletion may need is specified (doc-sync file only, local diff only doc-sync lines, outside S4, stash kept, exit 0) |
| 3 | P9 row 14 (:406), Interfaces P5 (:77-78) | P5 row 17 hands README :400, :479, :570 and ARCHITECTURE :329 (stubs named as live hooks) to P9; P9 named only :536 and ARCHITECTURE :167 | the four lines added; the change column says no line names an unregistered stub as live |
| 4 | P9 row 8 (:400) | P2 kept and listed the false TIME CHECK paragraph (dev-overnight.md:1574; X4); no phase took it | added to row 8 (prose) |
| 5 | P9 Interfaces (:100-103) | P9 consumed only named hand-offs; section 13 rows the reviewer copies after each merge (COVERAGE fix 13) and other "Out of scope, found" items for P9 had no reader (P10 has one) | one bullet: every such item is handled or listed again with the reason |
| 6 | P10 (new exp 10 :187-204; acceptance 24; Live landing; choices; out of scope; rules) | P10 deletes doc-sync files (commands/INDEX.md, README.md, possibly agents/ and .claude/ pairs, every deleted directory's index files) and edits index rows, but had no pull-path check; X1-X3 show the wedge; P11's re-sync would then never arrive | experiment 10 with P9's rule, reusing P7b's or P9's landing step if one exists, else adding the same narrow step; acceptance 24 |
| 7 | P10 "What earlier phases left", P9 bullet (:70-76) | the CLAUDE.md date block went P9 -> P10 -> "list again for the reviewer", a hand-off with no possible executor (P10 and P11 may not edit CLAUDE.md) | terminal: the block stays as P9 left it; P9 E9 says the same; P10 also picks up P9's landing step and E1's ignore lines |
| 8 | P10 row 9 (:302) | ".gitignore: delete rules with no writer" would remove the `/agent-scores.json*` (and `logs/*`) lines P9 E1 keeps because homes still hold the old store; E1 (c)/(d) show it would then enter `git status` and the checkpoint snapshots (`git add -A`, checkpoint-core.sh :537) | keep E1's lines unless E1 moved the file under logs/ |
| 9 | P10 row 5 (:298), U-E1b (:226-229) | "the four generated files inside commands/ and agents/ are loaded ... as a command and agent": agents/INDEX.md and README.md have no frontmatter (X4), acceptance 9 tests only /INDEX; D18 requires the premise to be measured | commands/ pair deleted; agents/ pair only if the CLI's subagent documentation or a measurement shows it loaded; no Skill(INDEX/README) deny exists at f8c18c2 |
| 10 | P10 row 6 (:299) | P3 calls close-commit-repair-orchestrate.py part of "the late-repair route (D15): kept"; the route runs late-repair-controller.py and nothing runs the script (X4) | one clarifying sentence; the reachability proof decides |
| 11 | P10 technical-choices heading (:522) | "choice / why / how to revert" lacks D18's experiment and result columns that P9 and P11 carry | "choice / experiment or test / result / why / how to revert" |
| 12 | P10 acceptance 19 (:702) | "ba.md :18's step" moves after P9 row 7 | anchored to the Critical-Thinking Charter's history step |
| 13 | P11 out of scope (:532-536) | off-site backup: "the reviewer records it" is no D18/D19 resolution; the owner's 2026-10-19 backup answer was ambiguous | decided by acceptance 14's measurement: the only off-site channel is the opt-in checkpoint push to the public origin, so it stays off (D1) and no phase points it elsewhere (a private remote needs the owner's account, D19); recorded in hand-off item 8 |
| 14 | P11 A6 (:280-281), A9 (:344), DO NOT (:552-553) | A6 may add a rotation line to the owner message, but DO NOT allowed only the go-ahead reply and the support form, and A9 called the support form "the only owner action besides the go-ahead" | the exception lists the rotation line; the line names a provider-side revocation, never a machine step (D19) |
| 15 | P11 Background (:513-514) | no reader for section 13 rows routed to P11 | added; out-of-scope ones go to hand-off item 10 |
| 16 | P11 Net code cap (:750-757), PR headings (:773-775); P10 hand-off (:770-771) | P10's ratchet has no headroom and refuses a PR that raises a budget and changes anything else (a raise travels alone); P11's one PR adds files and lines (tracked_files, tracked_lines), so its CI fails, and P11 may open only one PR | P11 runs the check; if it exits 1 it neither raises the budget nor deletes unrelated lines, and reports the six values so the reviewer merges a budget-only PR first; P10's hand-off names this |

Unchanged on purpose: P9's E2 sentence fits CLAUDE.md :60 (a row 16 line); P11 B2's "upgraded" matches the P7b
implementation's state name (X5); P11 B7's concern for P7b's verdict is harmless (a landed home's state does not read the
reflog in the implementation).

## (d) HANDOVER owner-gap items -> D18/D19 resolution

| HANDOVER item | Resolution | Where |
|---|---|---|
| 1 P7b other repositories | owner answered 2026-10-19: also the other repositories | DECISIONS (answers), P7b R6/R8 |
| 2 P8 three tool-policy rules | owner answered 2026-10-19 (TC-47) | DECISIONS, P8 |
| 3 P2 in_place without bwrap | D18 experiment in P2 | P2 |
| 4 P4 rating questions (H-Q5, H-Q3) | D18 experiments in P4 | P4 |
| 5 Arming timing | D18 experiment (P2 if settings reach running sessions, else P5) | P2, P5 |
| 6 P6 general-purpose subagents | D18 experiment in P6 | P6 |
| 7 How merged code arrives; homes stuck after a P7-only pull | D19: only when the owner types /pull, no automatic pull (fswatch's existing `safe_pull` covered by P9 E9 and P11 acceptance 5); the owner was told not to pull before P7b; stuck states: P7b R2 (S3 repaired, S4 reported); each later phase's own pull is kept from wedging by P9 E9 and P10 exp 10 (fixes 2, 6); P11 B2 handles S4 (P10 changes nothing in S4) | P7b, P9, P10, P11 |
| 8 P9-P11 human steps | P9: CLAUDE.md edited in the PR (row 16), H-Q10 by E1; P10: per-home retirement by the landing replaces "doctor on each home"; P11: stage 1 code + scratch script, rehearsals, hand-off; the reviewer runs the publish (including the 255-ref deletion) after the one go-ahead D16/D18 keep | P9, P10, P11 |
| 9 Off-site backup | D18 rule from P11 acceptance 14 (fix 13); P7b and P10 out of scope | P11 |
| 10 git-clean matrix file | D19: owner data, owner step refused; P8 records "not delivered" with the closing sentence; module keeps its pre-existing skip | P8 (P10 out of scope) |
| 11 Defaults applied without asking | D18: final (no veto round) | P4, P5, P8 |
| 12 Confirmations never given (D4b wording (superseded by D20, 2026-10-23); /redev and two extra exits; the reading of "好的") | D18: no arbitration; implemented as planned (nine gated commands, two human exits), documented by P9 row 16 and row 14; "好的": the reviewing session implements and merges P7b itself | P2, P5, P9 |
| PLAN-v2 section 14 open list (same four items) | as 7-10 | - |
| STATE 8.15 who deletes the 255 refs | the reviewer, with P11's script, after the go-ahead | P11 |
| STATE 8.16 docs branch | rewritten and kept (A8 step 4) | P11 |
| STATE 8.21 old remote branches | fully merged ones deleted by the publish (named in the owner message), the rest rewritten | P11 |

Every HANDOVER owner-gap item now has a D18 or D19 resolution; the only owner actions left are P11's go-ahead reply, the
optional GitHub support form, and a rotation line only if A6 counts a credential.

## (e) Changes needed in earlier prompts (not edited here)

| # | Prompt (state) | Change | Why |
|---|---|---|---|
| 1 | P7b (being implemented by the reviewer) | Recommended: extend R2 so the landing resolves an unmerged doc-sync file (an `AUTO:` block or doc-sync's footer) whose local side differs from the merge base only in doc-sync's generated lines, to the upstream side, outside S4, keeping the stash entry, counts-only log, exit 0 | X1-X3: a pull that deletes or count-edits a file the home's doc-sync re-dated wedges every later pull, and today the landing repairs only settings.json (X5). One step in P7b covers every phase's diff, P8's included; P9 E9 and P10 exp 10 then reuse it (they add it only if it is missing) |
| 2 | P8 (running) | Its live-landing acceptance 16 replaces files in place and runs no pull path. Its deletions of doc-sync files (tests/generated/INDEX.md and README.md, row 3b) and any `**Total entries**` change in docs/reference/INDEX.md (records deleted, row 7a) should be checked on one pull path from a home with doc-sync edits, or rely on item 1 | same wedge on the owner's first pull after P8 |
| 3 | P2, P4, P5, P6 (not started) | optional wording: "CLAUDE.md (never edited by an agent, UD-CM)" -> "(P9 edits it under D19)" | stale description only; it constrains those phases correctly |
| 4 | P1 (done), P8 (running) | none: "(P11, human-run)" and P8's "after doctor's per-home check" are stale descriptions superseded by P10/P11 | harmless |
| 5 | Reviewer (not a prompt) | copy each merged PR's "Out of scope, found" / "Now unreferenced" items into PLAN-v2 section 13 (COVERAGE fix 13); P9, P10 and P11 now each read section 13 rows for their phase. When P11's size check exits 1, author and merge a budget-only PR (fix 16) | consumers exist now; the producer step is the reviewer's |

## (f) Residuals assigned to no phase (for the reviewer)

- P2 "Out of scope, found": scripts/update-overnight-state.sh `find_state_file` falls back to the newest state file of
  any session when no session id is given (:124-131 at f8c18c2), unless P2's locator change removes it; and
  hooks/install-auto-sync.sh spells `~/.claude` throughout (an opt-in installer kept under D1; PR #4's list). Neither is
  dead code (P10) or prose (P9). Give each a section 13 row or a fix PR.
- P5 "Corrections": overnight pipelines the state planned but nobody dispatched are not families; whether P2's closeout
  should cover them is the reviewer's decision.
- CLAUDE.md :3-5 (doc-sync's date block): if P9's E9 keeps it, it stays static by design (no later phase edits CLAUDE.md).

## Verdict

P9, P10 and P11 are consistent with the earlier prompts after the 16 fixes above: dependencies and order are right
(P9 after P6 and P8 and everything before them; P10 after P9; P11 after every PR, none open), every deferred item has
exactly one deliverer or an explicit residual, and every HANDOVER owner-gap item has a D18/D19 resolution. The one
material risk found reaches beyond these three prompts: a pull that deletes or count-edits a doc-sync file the home
re-dated wedges that home for every later merge (P11's re-sync included). P9 and P10 now measure and handle it; the
recommended single fix is in P7b's landing (section (e) item 1), and P8's deletions should be checked against it. Ready
to hand over once the reviewer has noted (e) and (f).
