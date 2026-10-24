# Review findings on P1b, P1c, the inventory and the P1b plan-sync list (unverified)

Five independent review lenses read the files at commit c1bdc15: owner conformance, factual accuracy against the code, implementability, fit with the rest of the plan (including the D20-D25 batch), format and hygiene. These are claims to verify, not orders: each gets two independent refuters before it is applied (see the session prompt).


## Lens summary: owner

Conformance review of P1b.md and P1c.md (plan-push at c1bdc15) against register.md, D20-D25, the 2026-09-28 rulings with C1-C5, and the reviewer's points (a)-(d). Most of the rules are carried into both prompts correctly: the "Owner steps: none." first line, no owner questions, experiments instead of arbitration (D18), the D21/D22/D23 bullets, a CI check derived at test time with no TSV, the inventory regenerated on the base, G1-G3 kept as allowed positions, and DO NOT lists with no parking or new state file.

The defects are in how deletions are sequenced and in the never-fail suite:
1. P1b turns the incomplete-cycle routing in /close and /commit into report-only. The owner rejected exactly that (CC4, CC5, D7).
2. P1b deletes consumer-side checks and the advisory records while G1-G3 stay advisory. That opens a window on the live home in which faults are not detected (against ruling 4, C3 and D25).
3. P1c's stale-lock fallback X7 (B) asks the owner, also inside overnight. If the experiment picks it, P1c's own zero-human assertion on F4s fails.
4. P1c's suite has no replay of /close or /commit completing an incomplete cycle (CC4).

Further findings: reviewer proposals presented as owner words (the ranking, and the suite with its merge rule, in P1b, P1c and the draft D25); several new human steps or waits (the "re-run the command" fallback, permissions reported instead of applied, X8 (B) in overnight, overnight parking left untested); contradictions in the zero-exception check (obligation.ROLES and PIPELINES, the leftover tool-policy prefixes, an allowed-position set without the Stop gate and the chain function); P1b acceptance tests that allow new blocks or that cannot be met inside P1b's scope; never-fail checks resting on agent discipline (merge rule) or on weak proofs (class D in X6).

I opened the owner's transcript read-only to check the source of the 2026-10-24 quote (record 2593 against the reviewer's reply at record 2603). No file was edited.


## Lens summary: facts

I checked P1b.md, P1c.md and inventory/README.md against the code at master d625284, at P8 (0d26692) and in P7b's working clone (760f06e).

What I covered:
- About 130 file:line claims in P1b's Goal, E1-E14, Corrections, Scope rows 0-20 and Acceptance.
- P1c's Before-you-start, pilot table, scope rows 7-20 and the row 18/19 lists.
- Every count in the README, recomputed from the TSV. All of them match: 122 rows, the group sizes, 40 rows outside the ledger, the violation tallies 35/37/29/29/18/27/21, evidence 86/33/3, positions 30/13/18/67.
- The TSV's 593 file:line references. All resolve to real files and 588 fall in range; the other 5 are my resolver confusing commands/dev.md with agents/dev.md and hooks/push.sh with the root push.sh. I read the cited lines for more than 60 rows (A01-A24, A26-A57, A58-A75, A76-A107, A108-A124).

Most claims hold: the obligation.py constants and lines, the routing tables, the E3 tables, the 11 hooks / 13 /do consent read sites, the G2 escalation stores and lines, the contract_runtime mutation, the launcher's seed contract, the v1/v2 schema-name conflict at dev-overnight.md:837/:838 against :1288/:1390, the net-code block sizes (230, 155, 150, 262, 640, 146, 92), the design-doc rulings at :13-23 and C1-C5 at :26-35, the register and teachings quotes, P8's conftest/workflow/deletions, and P1c's X9 grep results.

Commands I ran:
- Acceptance 7, 8 and 9 greps on the base.
- P1c's N1 and V1-1/NV-1 greps.
- P1c's conftest grep: 0 lines on the base, 1 on P8.
- scripts/check-public-core.sh: fails on d625284 (expected), passes on P8.

18 findings, worst first:
- Row 18 would delete the reads of three files that are written: the runtime guard's protected-runtime.json, the tracked .awesome-claude-harness, and the human-made .hook-refactor-allow.
- Acceptance 9's grep cannot match the guard's single-quoted /tmp paths and skips the prose /tmp writers in commands/ and agents/.
- The path rule cites :2093, which is only the block message (the read is _find_grant :328). It also misses the /do sidecar, and moving execute-push.py's base alone would break /push when CLAUDE_STATE_DIR is set.
- TERMINAL_VOCABULARY's do-report entry includes "pending", so it is not a terminal set.
- Acceptance 8 conflicts with P1c rows 8 and 10.
- The prose copies of the routing table are missed.
- P7b's description is stale against 760f06e.
- The pull-analyst grant does not exist.
- E5's candidate (a) never runs in a product repository.
- The TSV misclassifies the doc-sync notices, the append-error markers and the spec-update temp note.
- P1c's "no record of N1 or V1-1" is out of date once P7b merges.
- Several lines are stale or misattributed.

Supporting notes are in <reviewer scratch>/p1b-review/notes.


## Lens summary: feasible

Verdict on implementability: neither prompt can go to an implementation session as written.

P1b cannot be delivered as one PR that meets its own acceptance. Its acceptance 4 requires 0 blocks in all ten pipelines, in both settings modes. The pilot's blocks on /commit, /merge, /dev-command, /dev-overnight and /dev (P1c rows 18-19) sit outside every P1b scope row. P1b has no rule for deciding which side changes, and its DO NOT forbids hook changes made to suit a driver.

The zero-exception end state contradicts itself in four places:
- Row 18 keeps obligation.ROLES, and row 6 keeps TERMINAL_VOCABULARY, while Goal 4 and mutation test 5 make any role list or vocabulary fail the check.
- Row 18 deletes PIPELINES while E3 extends it.
- The tool-policy rows for undeclared paths stay until P5.
- The e2e gate and G2 both decide on the qa-report.

The allowed positions also leave out D21's "Stop gate", so P5's planned Stop gate would fail P1b's check.

The check's derivation is not defined well enough to be derived without exceptions: what counts as an artifact, a reader, the same rule, or a re-check; prose consumers; a coverage floor. E2 has no real CI cost bound (unlimited shards, differential runs not counted), and it conflicts with P1c's X10 split. E5 cannot run in the sandbox: both the hook and the prose call the aggregator by a path inside the product repository, and the toy repository has no scripts/ or venv/.

P1c was written as if P1b had not run, and it rests on a false premise:
- It claims no record of N1 or V1-1/NV-1 exists, but P7b at 760f06e carries both in its tests and commit messages. Its rebuilt descriptions do not match those defects.
- Rows 7, 10 and 13, row 19's seed, row 18's items, its "before" trees and its net-code funding repeat or depend on P1b deletions.
- X8 (A) breaks P1c's own DO NOT, because CLAUDE.md states the SendMessage exception as "the sole" one for the human-only /restart.
- X6 has no rule for when recall falls short of 100%. It would also class F5's known dead end as clearable.
- X2's `git archive` harness home is not a git repository, which the landing and /pull replays need.

Lower-severity items: the PR-body evidence exceeds GitHub's 65,536-character limit; the shared CI and "tell the owner" paragraphs are stale; the commit trailers the reviewer asked for are missing.

Dependencies are stated and mostly checkable. P1b's start check names `scripts/install/land`, which exists at 760f06e. P8's deletions of dev-fix.py and spec-update-contract.py are confirmed at 0d26692. P1c's conftest grep for CLAUDE_STATE_DIR prints 1 on P8's head. The one gap is "the latest baseline CI run is green", which has no command.

Line references in P1b and P1c were spot-checked against d625284 and are accurate. Recommended scoping:
1. P1b acceptance 4 becomes "no new block versus the base", with marked deviations handed to P1c.
2. P1b takes over P1c rows 8, 10 and 12 so its D24 goals hold, and P1c gets a "Delivered by P1b" section with re-based "before" trees and net-code cap.
3. P1b is split into P1b-1 (runner and derivation) and P1b-2 (the deletions and the real-tree check with zero exceptions).


## Lens summary: plan

The reviewer's batch was committed while I worked: 06794d9 (D20-D25 applied), merged in be06811, working tree clean at about 16:57Z. So "the batch" below means be06811's tree; D25 is already in DECISIONS.md:68-82.

**Sync list, 101 edits.** My script checked every ~~~anchor in the branch at c1bdc15, in p23 HEAD before the batch, and in be06811.
- All 101 anchors are found exactly once at c1bdc15.
- 95 anchors are still found exactly once in be06811. Six changed: V-5, V-8, P3-4, P6-5, P9-5, P9-8. FIT-07 gives each one's new text. P3-4 changed in p23's own P3 refresh (174dbb4). V-8's new text also brings back "human-run", which the batch removed.
- Applies cleanly, with no meaning conflict: V-1–V-4, V-6, V-7, V-9–V-12, V-14, V-16, V-18–V-23, V-25, V-26, V-28–V-30; D-2, D-3; H-1–H-9; K-1–K-11; P2-1–P2-3; P3-1–P3-3; P4-1–P4-3; P5-1–P5-3; P6-1–P6-3; P9-1–P9-4, P9-6, P9-7, P9-9; P10-1–P10-3, P10-5, P10-6; P11-1, P11-2.
- Anchor still found, but the edit is wrong on top of the batch:
  - D-1 would create a second D25. The batch also left D20-D24's heading saying they override D25 (FIT-09).
  - V-13, V-24, P4-4 and P10-4 say "do not add corrections.md's D24 goal", but the batch already added those goals. Inserting them leaves contradictory instructions; they must become REPLACE edits (FIT-06).
  - P2-5, P3-6, P4-5, P5-5, P6-5 and P9-10 collide with the batch's new D24 acceptance numbers. The right numbers are 20, 20, 22, 26, 20 and 24 (FIT-08).
  - V-31, H-10 and K-12 say N1 and V1-1/NV-1 have no record. That is false since 4a9256a added reviews/P7b-PR-record.md (FIT-04).
  - V-15/P5-4 say P5 "arms" a mechanism P1b already ships (FIT-12). V-17/P6-4 conflict with the batch's P6 acceptance 19 and with TC-46 (FIT-05).
  - P2-4 leaves out several P1b/P1c deliveries that P2's rows still edit (FIT-16).
  - V-27/P11-3 are only slightly off: they say "landing's new step on a pull of rewritten history", while the batch's P11 landing step is the pre-push guard install, and their "(if 2.65 applies)" is stale.
- None of the 101 edits conflicts in meaning with D20-D24 except V-8 (P11's run by the reviewer under D16/D18) and D-1 (a second D25).

**Decision ids.** The sync adds only D25, the same ruling the batch records as D25, so no D-number clashes. Experiment and probe ids do clash: X1/X2 have three meanings, E1 two, and F3.a/F3a (FIT-19).

**Fit of P1b/P1c with the rest of the plan, most severe first:**
- **FIT-01 (blocker).** P1b's acceptance 4 (0 blocks in all ten compliant pipelines) is P1c's requirement (1). It cannot pass without P1c's rows 18-19.
- **FIT-02.** P1b deletes consumer-side checks while G1-G3 are still advisory. That opens a no-check window on the owner's live home (D25).
- **FIT-03.** P1b E13 makes the orchestrator the cycle contract's writer, which is the revert of decided TC-43. It also drops /stop's state write, which P2 row 14 keeps.
- **FIT-04.** P1c's R-N1/R-V1 replay the wrong defects. N1's remaining window and the fswatch pipefail defect are unowned.
- **FIT-05.** P1b E6 contradicts P6's transcript write set, TC-46 and P4's journal routing.
- **FIT-06.** The duplicated D24 goals described above.
- **Medium:** acceptance numbering (FIT-08); D25's position and wording (FIT-09, FIT-10); P1c redoing P1b's rows, so P1c's ≤ 0 net-code cap cannot be met (FIT-11); E3 duplicating P5 row 1 (FIT-12); E8 versus P5's TC-18 skeleton (FIT-13); landing.log versus P10/P11 (FIT-14); non-file artifacts that the CI check cannot see once P10's artifact-level goal goes (FIT-15).
- **Low:** FIT-16 to FIT-22.

**Ledger gaps.** All 56 ledger rows appear in the 122-row d625284 map, and P1b's scope rows 1-18 name every group. Two gaps remain:
- the non-file artifacts no CI check holds after P1b (FIT-15);
- the process errors that the P7b record leaves "for the reviewer" with no phase: N1's window, fswatch Fact 1, and Fact 9 homes stuck in S3/S4 (FIT-04).

Evidence trees and scripts are in <reviewer scratch>/p1b-review/fit:
- B = branch c1bdc15
- H = p23 HEAD before the batch
- W2 = snapshot of be06811
- anchor3.py and acc.py = the checkers


## Lens summary: format

Format and hygiene review of the five new files (P1b.md, P1c.md, inventory/README.md, inventory/artifact-map-d625284.tsv, reviews/P1b-plan-sync.md) at plan-push c1bdc15.

Passes:
- Shared tail. In both P1b.md and P1c.md, everything from "## Context (read once)" to the end of the file is byte-identical to prompts/_common.md. It also matches P2.md (the branch copy and the p23 copy), the p23 copies of P3-P6 and P9, P7b.md and P8.md. Only the p23 copies of P10 and P11 differ, by one added sentence about D20-D24.
- Format items that are right: the PR title form is `<phase-id>: <short goal>`; the "Branch and pull request" sections have the same four bullets as P2; the acceptance headings say "paste the command and its output"; the technical-choices table has the columns choice / experiment or test / result / why / revert, which is Principle 7 written out in full.
- Privacy (counts only):
  - personal values from values.txt (25 lines, no empty line), grep -cFf: 0 in each of the five files, and 0 case-insensitive;
  - e-mail-shaped strings: 1, at P1c.md:661, which is the reserved placeholder at example.invalid;
  - session ids, claude.ai links, github.com links: 0;
  - home paths: only /root/toyproj, the sandbox's own path, at inventory/README.md:159-160.
- Model identifiers: none in the five files.
- Inventory TSV: 123 lines, 16 columns on every line, 122 unique ids. Every count in inventory/README.md's counts table matches a recount from the TSV.
- Size: P1b (96 KB) and P1c (85 KB) are about the size of the p23 copies of P2-P10 (82-108 KB). The cuts I name are restated text, not unusual length.

Defects, in order:
1. P1b asks for both full artifact maps and a full D24 table in the PR body. These cannot fit GitHub's 65,536-character limit: the d625284 map alone is 79,334 characters.
2. P1c is written against d625284 as if P1b had not run. It repeats about eight of P1b's deletions. Its net-code estimate and retired-rules list count deletions that P1b makes. It sends findings "for P1b's table" after P1b has merged. It also leaves `-F` to P5 while P1b's Correction 5 fixes it.
3. P1c rebuilds the compliant drivers that P1b hands to it, which leaves two driver sets.
4. Neither prompt states the commit format or the standard trailers. The shared DO NOT line "Do not put model identifiers in commits or the PR" contradicts the trailer every P1 and P8 commit carries.
5. Checked against the reviewer's p23 tree, 6 of the sync list's 101 anchors match nothing (the file says only 1 would). Edit V-8 would put back "(human-run, last)".
6. The never-fail rule (D25):
   - Quotes and names: every copy drops the owner's opening words, which are the basis for ranking the rule with D24. P1b and P1c never call it D25, while P2-P11 will. P1b cites a source the implementer cannot open.
   - Who said what: P1c says the suite design came from the owner, and the sync list's D-1 puts it under the owner-ruling heading without a marker, but no planning document records owner words for it.
7. Low:
   - "Owner steps: none." is the first line of the file in P1b and P1c only.
   - inventory/README.md has a recipe that runs unpublished scripts, and its "16 to 18" figure does not match the 18 that P1b records.
   - Concrete cuts in P1b, P1c and the sync list (restated retired list, trace coverage stated three times, CLAUDE.md #5 note repeated, timings, V-31 summary).

Not raised: the CI paragraph of the shared tail ("red since 2026-07-26 … P8 makes CI green") is stale for every phase after P8. P2 has the same problem, and P1b and P1c both require green CI anyway, so it is a _common.md matter, not a defect in these files.

Scripts and notes are in <reviewer scratch>/p1b-review/notes/ (anchors.py checks the sync anchors against a tree).


## Findings (by severity)


### feasible-B1 [blocker] harness-repair-plan/prompts/P1b.md
- Location: Acceptance 4 (:531-537); also E5 (:265-266 "once E13 lets it run"), row 13 (:469 "Plans: ... (once E13 lets them run)"), Out of scope (:501-502), DO NOT (:689)
- Claim: Acceptance 4 (0 blocks from any hook, ten pipelines, shipped and armed) cannot be met inside P1b's scope. P1b's own rules forbid the hook changes that would be needed, and give no rule for deciding which side (hook or prose) changes.
- Evidence: P1c.md:421-473 (rows 18-19) list the blocks a literal compliant replay meets at d625284 that no P1b row touches:
- /commit: changelog-analyst.md :93/:1123/:1456 `rm -f "${MSGFILE}"` refused by bash-safety.
- /merge: merge.md:87 SESSION_ID; merge.sh :181-183 refuses on the untracked files the pipeline left.
- /push: push.md:83 `find`.
- /dev-command: pretool-claude-config-guard refuses the dev's command-file write.
- /dev: dev.md:757-759 graphify against Gate 4; the 5-Bash streak on Steps 14-17; repo-relative `scripts/...` paths (dev.md:1322).
- /dev-overnight: Step 1 refused by bash-safety (census_fatal) and by OVERNIGHT MAIN-ROOT BLOCK; OVERNIGHT SUBPROCESS GIT BLOCK (:1637) on every overnight python script; CLOSEOUT GATE; the cycle-id disagreement.
P1b's Out of scope (:501) leaves the overnight time-lock/window to P2, and E13 changes only the state and contract hooks. So the overnight plans never run, contrary to row 13's "once E13 lets them run". DO NOT :689 forbids changing a hook to suit a driver, and P1b has no equivalent of P1c's X4 (which side changes). Doing all of this would mean doing P1c rows 18-19 inside P1b.
- Proposed fix: Replace the "Expected:" sentence of acceptance 4 ("Expected: 0 blocks from any hook and 0 hook errors (exit other than 0 or 2) in every compliant run." through "never a hook change to suit a driver.") with:
"Expected: 0 hook errors in every run, and 0 new blocks: every block on your branch is also met on the base at the same hook, step and text. Where a base block stops a pipeline, the driver goes past it by the step the pilot used, marked in the driver source with a `DEVIATION:` comment quoting the hook text, so every step is traced. Every base block and DEVIATION goes under 'Hand-off to P1c' (P1c rows 18-19 remove them). A block that your branch adds, or that the base lacks, is a defect you fix; never change a hook to suit a driver."
In E5 and row 13, replace "(once E13 lets it run)" and "(once E13 lets them run)" with "(through the marked deviations)".
In P1c.md "Interfaces you consume", P1b bullet, append: "and its 'Hand-off to P1c' list: your drivers drop every DEVIATION (X4)."


### owner-R1 [blocker] harness-repair-plan/prompts/P1b.md
- Location: release notes :87-89; Scope row 10 (:466, Deleted column); Out of scope :505; acceptance 4 (:531-536) and 7
- Claim: P1b deletes the routing in /close and /commit (finding -> role -> re-dispatch of that role) and replaces it with reporting. On the live home, from P1b's merge until P4, /close and /commit then cannot complete an unfinished cycle. That is the alternative the owner rejected.
- Evidence: At d625284, close.md :162-321 routes every finding through close_artifact_role to one Agent dispatch of the producing role (the 'Routing loop', step 1-2). P1b row 10 deletes the tables and says 'an incomplete cycle is reported as the artifact, its failing check and the dispatch E3's reader returns'. The release note says 'when a cycle is incomplete they name the missing artifact and the dispatch that declared it'. Out of scope moves '/close and /commit completing an incomplete cycle by re-dispatching (D7, P4)' to P4. Owner: CC4 'dev永远都会完成，所以如果遇到close和commit自己派发相关的dev使用过的subagent补全…用户想close一定close完成', and CC5 (plan P4.md:103-104: the owner rejected having /close and /commit only report). D25 'never fail'. P1b acceptance 4 still expects '/close … with a routing round', which report-only cannot produce. E3's own rule ('every table above is deleted and its callers read the reader') points to a swap, not a removal.
- Proposed fix: (1) Replace :88-89 'when a cycle is incomplete they name the missing artifact and the dispatch that declared it.' with 'when a cycle is incomplete, each gap's declaring dispatch (E3's reader) is dispatched again with the same subagent_type, task_id, lane and obligation template and a fresh dispatched_at, until the cycle completes (D7, CC4); the gap itself reports facts only (D21).' (2) In row 10's Deleted column, replace 'an incomplete cycle is reported as the artifact, its failing check and the dispatch E3's reader returns' with 'the routing loop takes each finding's producer from E3's reader instead of the table and dispatches that declaring dispatch again (same subagent_type, task_id, lane, obligation template; fresh dispatched_at); the rest of the loop stays for P4'. (3) Replace Out of scope :505 '/close and /commit completing an incomplete cycle by re-dispatching (D7, P4)' with 'the rest of /close's and /commit's completion machinery (Step 0 as one disposition call, R15, arbitration, the waits; P4); the re-dispatch itself keeps working through E3's reader from this phase on'. (4) Add to acceptance 7: '/close after a /dev cycle whose lane QA report was removed after QA's stop: the reader names that QA dispatch, /close dispatches it again, the report is written, /close lands CLOSE: YES with 0 human events; the same at /commit for a dev-stage gap.'


### plan-FIT-01 [blocker] harness-repair-plan/prompts/P1b.md
- Location: Acceptance 4 (:531-537); E13 decision rule (:368-373); E5 (:265-266); 'What you hand to P1c' (:59-61); against prompts/P1c.md rows 18-19 (:416-474) and X5 (:279-289)
- Claim: P1b's acceptance 4 requires 0 blocks in compliant replays of all ten pipelines. That is P1c's requirement (1), and the replays are blocked today by refusals that only P1c's rows 18-19 and X5 fix. P1b cannot pass its own acceptance, or run E13 and E5, without doing P1c's work. That work is outside P1b's scope, and P1b's own DO NOT and Out of scope forbid parts of it.
- Evidence: P1b :531-537 sets the expectation '0 blocks from any hook and 0 hook errors ... in every compliant run'. It includes '/dev-overnight (two cycles of a 2-pipeline session, E13)', /dev-command and /merge, and says 'Any block is either a driver ... or a defect you fix'. P1b's own trace table (:427-438) lists blocks that exist today: dev's command-file write refused, Step 0 refused by bash-safety, `rm -f "$MSGFILE"` refused, merge.sh refused on the dirty tree, and the overnight first cycle a dead end. P1c :74-77 counts 9 refusals on trace B and the overnight dead end. P1c row 19 (:454-470) lists further overnight blocks that P1b's E13 does not remove: bash-safety census_fatal on the dev-overnight.md Step 1 apostrophes, OVERNIGHT MAIN-ROOT BLOCK, SUBPROCESS GIT BLOCK on every harness python3 script, WRITE-BOUNDARY FAIL-CLOSED without bwrap, and the time-lock CLOSEOUT GATE. P1b's Out of scope (:501-502) gives the overnight time-lock and window to P2. P1b DO NOT :689 forbids changing a hook to suit a replay driver. P1b's acceptance 14 (:568-570) already accepts base dead ends 'for P1c', which contradicts acceptance 4. E5 (:266) and E13 (:368) need two overnight cycles to run.
- Proposed fix: In P1b.md acceptance 4, replace "Expected: 0 blocks from any hook and 0 hook errors (exit other than 0 or 2) in every compliant run." with "Expected: 0 hook errors (exit other than 0 or 2) in every compliant run, and no block on your branch that the base does not show at the same step. List each base block with its hook text for P1c (its rows 18-19 fix them). Where a base block stops a pipeline, the driver passes it with a marked deviation (as the planning pilot's overnight what-if did), and each deviation is listed, so the trace still reaches every later step." In E13's decision rule, after "both cycles run with 0 blocks from the contract and state hooks", add "(blocks of other hooks that the base also shows are passed by listed driver deviations)". In 'What you hand to P1c', append "; the drivers carry the marked deviations, and P1c removes each one as its rows 18-19 fix the block". In P1c X1, add "Remove each of P1b's marked driver deviations in the commit that fixes its block."


### facts-F1 [high] harness-repair-plan/prompts/P1b.md (also inventory/artifact-map-d625284.tsv row A117)
- Location: Scope row 18, column Deleted (P1b.md:474, 'The reading branches of files nothing writes: ...'); TSV A117 columns paths/resolution
- Claim: Row 18 says these files have no writer and their reading branches go: `.claude/.hook-refactor-allow`, `~/.config/claude/protected-runtime.json`, the generic `claude-*-grant-*.json` probe, `<proj>/.claude/CLAUDE.md` and `.claude/.awesome-claude-harness`. TSV A117 says 'all sources agree: no writer in hooks, scripts, commands or agents'. At least four of the five are written, and the fifth is an uncalled function.
- Evidence: (1) protected-runtime.json is created by scripts/bootstrap:362-386 ('bootstrap: created protected-runtime file', init step 4) and documented at README.md:99 and :115. Without it, hooks/lib/runtime_guard/config.py:60-66 returns None, so the guard fails closed on npm, node and kill (README.md:805). (2) `.claude/.awesome-claude-harness` is a tracked file at d625284 and at 0d26692 (git ls-tree; PUBLIC-CORE.md:158). session-gitignore-propagate.sh:22 reads it in the harness repository itself. (3) `.hook-refactor-allow` is the human's sentinel by design: pretool-claude-config-guard.py:1-12, .gitignore:129, docs/THREAT-MODEL.md:374 ('touch .claude/.hook-refactor-allow'). P1c row 18 keeps that guard and adds a narrow allowance. Deleting the read leaves /dev-command no route to write a command file (C5). (4) The pattern at pretool-git-privilege-guard.py:372-374 belongs to `_find_grant_any` (:365-386), which has no caller. Its glob '/tmp/claude-%s-grant-*-*.json' also matches the commit grants that write-commit-grant.py writes under /tmp. (5) `<proj>/.claude/CLAUDE.md` is the user's Claude Code project file. session_start.sh:28 is not registered in settings.json at d625284. The static extractor skipped scripts/bootstrap because the file has no extension.
- Proposed fix: In P1b.md row 18, replace "The reading branches of files nothing writes: `.claude/.hook-refactor-allow` (pretool-claude-config-guard.py:77), `~/.config/claude/protected-runtime.json` (runtime_guard/config.py:63), the generic `claude-*-grant-*.json` probe (pretool-git-privilege-guard.py:374), `<proj>/.claude/CLAUDE.md` (session-info.sh:26, session_start.sh:28), `.claude/agent-bookmark-*.json` (posttool-overnight-trace.py:394), `.claude/.awesome-claude-harness` (session-gitignore-propagate.sh:22) unless a command or init creates it;" with "The reading branch of `.claude/agent-bookmark-*.json` (posttool-overnight-trace.py:394; nothing writes it) and the uncalled `_find_grant_any` (pretool-git-privilege-guard.py:365-386; D17 reachability proof). These stay because something writes them: `~/.config/claude/protected-runtime.json` (scripts/bootstrap:362-386, README.md:99), `.claude/.awesome-claude-harness` (tracked in the repository), `.claude/.hook-refactor-allow` (the human's sentinel; P1c row 18 narrows its guard), `<proj>/.claude/CLAUDE.md` (the user's project file);". In TSV A117, drop those four paths from `paths`, set `violations` to 'read never written (agent-bookmark only)', and change `resolution` to 'agent-bookmark-*: no writer; protected-runtime.json: scripts/bootstrap:362-386 (missed by the extractor: no file extension); .awesome-claude-harness: tracked; .hook-refactor-allow: written by the human by design; .claude/CLAUDE.md: user-owned; claude-*-grant-* probe: _find_grant_any has no caller'.


### facts-F2 [high] harness-repair-plan/prompts/P1b.md
- Location: Acceptance 9, last sentence (P1b.md:554-555)
- Claim: `git grep -nE '"/tmp/claude-|/tmp/agentic-commit' -- hooks scripts ':!hooks/tests'` 'lists only defaults inside the state-dir helper' is supposed to prove the path rule. As written, the grep cannot see the defect it targets.
- Evidence: Run on d625284, it prints 18 lines, and none of them is pretool-git-privilege-guard.py:274 (f'/tmp/claude-orchestrator-consent-{sid}.flag'), :328 ('/tmp/claude-%s-grant-%s-*.json', the push grant read) or :2093. These are single-quoted strings, and the pattern requires a double quote before /tmp/claude-. The same applies to :372, :406, :636, :1358-1360, :1406-1407 and :2237, and to pretool-bash-safety.sh:1722 (96 hits in total without the quote). The pathspec also leaves out commands/ and agents/, which hold the prose writers Correction 4 itself names: commit.md:666, do.md:55-58, agents/changelog-analyst.md:1221 and :1247, agents/push-analyst.md:155, agents/merge-analyst.md:164, merge.md:139 and :165, push.md:144. The command would pass while the defect is still there.
- Proposed fix: Replace "`git grep -nE '"/tmp/claude-|/tmp/agentic-commit' -- hooks scripts ':!hooks/tests'` lists only defaults inside the state-dir helper." with "`git grep -nE '/tmp/(claude-|agentic-commit|overnight-)' -- hooks scripts commands agents ':!hooks/tests' ':!scripts/install/tests'` lists only the helper's default (hooks/lib/harness_state_dir.py, harness_state_dir.sh), comments, and paths whose every writer and reader use the same fixed root, each named in the PR. On the base it lists, among others, pretool-git-privilege-guard.py:274 and :328, scripts/execute-push.py:35, commands/do.md:57-58, commands/commit.md:666, agents/changelog-analyst.md:1221 and :1247, and agents/push-analyst.md:155."


### facts-F3 [high] harness-repair-plan/prompts/P1b.md (also TSV rows A52, A71, A73)
- Location: Corrections to PLAN-v2 item 4 (P1b.md:408-412); Scope row 12 'Deleted' (P1b.md:468); Goal release note on the path rule (P1b.md:91-92)
- Claim: The path rule lists four mismatches: /do consent at guard :274, the push grant at guard :2093, the chain-B sentinel at execute-push.py:35, and the push-gate token at commit.md:666. Row 12 says execute-push.py:35 and guard :2093 should read and write under harness_state_dir(). One location is wrong, two mismatches are missing, and following row 12 literally creates a new mismatch.
- Evidence: (a) guard :2093 is in `_block_missing_push_grant`, which only formats the block message. The push grant is read by `_find_grant` at :328, called from :2135. Changing :2093 changes only the message. (b) execute-push.py:35 `_SENTINEL_BASE = "/tmp/agentic-commit/push-analyst"` is both the chain-B sentinel's write root and the push-analyst grant's read root (grant_path at :117). The push-analyst writes its grant under /tmp (agents/push-analyst.md:155; its rules at :33-35 forbid any other path). pretool-push-analyst-grant-guard.py:73 already reads it under harness_state_dir(). So with CLAUDE_STATE_DIR set, the guard reads a path nothing writes today (TSV A71 lists no such violation). Moving :35 alone makes execute-push.py miss the grant and /push fails. (c) The /do task sidecar is written under the state dir (prompt-workflow.py:1419), but do.md:57 tells the agent to read /tmp/claude-do-task-$SID.json. do.md:58's fallback reservation writes /tmp while the hook's reservations are under the state dir (prompt-workflow.py:1337, :1348). TSV A52 says 'none found'. (d) The token's writer prose is agents/changelog-analyst.md:1221 and :1247 (commit.md:666 is the dispatch text). posttool-push-gate-token-verify.py:44 also matches the state dir.
- Proposed fix: Replace Correction 4's text from "read at a fixed /tmp path in pretool-git-privilege-guard.py (/do consent :274, push grant :2093; probes X11a and X11b2 on d625284), execute-push.py writes the chain-B sentinel under /tmp (:35) for push.sh to read under the state dir (:106), and the push-gate token is written under /tmp by prose (commit.md:666) and read under the state dir (push.sh:212)." with: "read at a fixed /tmp path in pretool-git-privilege-guard.py (/do consent :274; push grant `_find_grant` :328, reached from :2135, whose block message :2093 names the same pattern; probes X11a and X11b2). The /do agent reads the task sidecar at /tmp (commands/do.md:57) and writes its fallback reservation there (:58), while prompt-workflow.py:1348 and :1419 use the state dir. execute-push.py's `_SENTINEL_BASE` (:35) is both the chain-B sentinel's write root and the push-analyst grant's read root (:117): push.sh:106 reads the sentinel and pretool-push-analyst-grant-guard.py:73 reads the grant under the state dir, while agents/push-analyst.md:155 writes the grant under /tmp. The push-gate token is written under /tmp by the analyst's prose (agents/changelog-analyst.md:1221, :1247, dispatched with commit.md:666) and read under the state dir (push.sh:212, posttool-push-gate-token-verify.py:44). Each writer and its prose move together: execute-push.py:35 moves only with push-analyst.md:155." In row 12, replace "execute-push.py:35 and pretool-git-privilege-guard.py:2093 read and write under `harness_state_dir()`" with "execute-push.py:35 together with agents/push-analyst.md:155, and pretool-git-privilege-guard.py:328 (and its message :2093), read and write under `harness_state_dir()`". Add the /do sidecar and the push-analyst grant to the release note's list. TSV: A52 violations -> 'read never written (do.md:57 reads /tmp; the hook writes the state dir)'; A71 add 'read never written (grant guard :73 reads the state dir; the analyst writes /tmp)'; A73 readers -> 'pretool-git-privilege-guard.py:328 _find_grant via :2135 (:2093 is the block message)'.


### facts-F4 [high] harness-repair-plan/prompts/P1b.md
- Location: E8 decision rule (P1b.md:304-306, 'Every reader then decides `do.status` through one function on obligation.TERMINAL_VOCABULARY'); Scope row 9 'Deciding consumer kept' (P1b.md:465); E8 Fallback (P1b.md:306-307)
- Claim: Every do.status reader is to decide through one function built on obligation.TERMINAL_VOCABULARY, and the fallback has the e2e gate read `expected_absent` 'from the /do dispatch record'.
- Evidence: obligation.py:138 sets TERMINAL_VOCABULARY['do-report.v1']['do.status'] = {pending, completed, blocked}. That is the schema's enum (schemas/do-report.v1.json /properties/do/properties/status), not a terminal set: the comment at obligation.py:129-131 says 'Equal to each registered schema's enum'. Today's deciders use {completed, blocked} (stop-do-report-gate.py:59) and {completed} (close.md:414). A function built on the constant would accept the pending skeleton that prompt-workflow.py:1363-1397 writes, so the /do Stop and /close would pass an unfinished /do. No code imports TERMINAL_VOCABULARY at d625284. Separately, there is no '/do dispatch record': pretool-do-block-subagents.py blocks Agent dispatch during /do, and commands/do.md has no obligation block.
- Proposed fix: In E8, replace "Every reader then decides `do.status` through one function on obligation.TERMINAL_VOCABULARY (stop-do-report-gate.py, /close preflight, resolve-commit-repos.py, dev-lifecycle.py, the e2e gate)." with "Every reader then decides `do.status` through one function whose terminal set is named once and drift-tested against the schema. obligation.TERMINAL_VOCABULARY['do-report.v1'] (obligation.py:138) is the schema enum {pending, completed, blocked}, not a terminal set, so the function must not treat 'pending' as terminal (stop-do-report-gate.py, /close preflight, resolve-commit-repos.py, dev-lifecycle.py, the e2e gate)." Make the same change in row 9's "`do.status` through one function on obligation.TERMINAL_VOCABULARY". In the fallback, replace "the e2e gate reads `expected_absent` from the /do dispatch record instead of from the report" with "the e2e gate derives `expected_absent` from the do-report's own `source == \"do\"` (the fixed set prompt-workflow.py:1386 writes); /do has no dispatch record (pretool-do-block-subagents.py)."


### feasible-H1 [high] harness-repair-plan/prompts/P1b.md
- Location: Goal 3 (:72-75), Goal 4 (:76-79), E3 (:231-233 "which then extends both sets"), row 6 (:462 "obligation.TERMINAL_VOCABULARY as its one code mirror"), row 7 (:463), row 18 (:474), acceptance 3 (:527)
- Claim: The zero-exception end state contradicts the prompt's own kept items, so P1b's check either fails on the tree P1b leaves or needs an unstated exemption. The kept items are: literal role, pipeline and vocabulary sets; tool-policy role-to-prefix rows; two deciders at QA's stop; and the Stop gate that D21 and P5 rely on.
- Evidence: 1. Row 18 keeps obligation.ROLES, a literal frozenset at hooks/lib/obligation.py:74-80 that does not even equal the schema: schemas/obligation.v1.json role enum has 7 roles, the code has 10 with the inspectors. Yet acceptance 3 requires "a hand-written ... role list in a hook" to fail the check.
2. Row 18 deletes "command lists (obligation.py:81-83 ...)", which is PIPELINES (used by validate_obligation :447). E3's fallback extends ROLES and PIPELINES.
3. Row 6 keeps TERMINAL_VOCABULARY (obligation.py:132-139, a literal mirror of six schemas). Goal 4 deletes vocabularies "that repeat a declaration".
4. E3 :241 keeps the tool-policy write prefixes for undeclared paths until P5, which is a role-to-filename table under D21.
5. Row 7 keeps G2 and the e2e gate both deciding on the qa-report with different rules. P1c.md:408 calls this "P1b's D24 question", but P1b never answers it.
6. D21 (p23 DECISIONS.md, D21 entry) names three enforcement positions: producer (G2), dispatch (G1) and "at the end (the Stop gate)". p23 P5.md:88 makes stop-command-gate.py the gate that blocks a Stop until artifacts are complete. P1b Goal 3 allows only the producer stop, G1 and G3, so P5's gate would fail P1b's CI check.
- Proposed fix: Row 18: replace "obligation.ROLES stays the producer subset, tested as a subset" with "obligation.ROLES, PIPELINES, PROFILES and TERMINAL_VOCABULARY are read at import from schemas/obligation.v1.json and the report schemas (the schema is the one declaration; the inspectors join the schema's role enum; the drift test goes)".
E3: replace "(which then extends both sets)" with "(which then extends the schema enums)".
Goal 3: after "(G3)" insert "and, for a command's own completion, the command's Stop gate (D21 'at the end', P5), which reads the one chain function's conclusion".
Add to Goal 5: "Definitions the check uses: checks at the producer's stop, G1, G3 and the Stop gate are the producer side, not consumers; among them each property of an artifact is checked by exactly one rule. A D21 table is a literal that maps a path some obligation declares to a role, or a literal collection of two or more agents/*.md stems or schema enum values outside schemas/ and agents/. Tool-policy rows for paths no obligation declares are not such a table until P5."
Row 7: add "the e2e gate's checks become properties of the qa-report obligation checked once (in G2 or in the e2e gate, technical choice); the other copy goes".


### feasible-H2 [high] harness-repair-plan/prompts/P1b.md
- Location: Goal 5 (:80-83), E1 (:189-202), row 19 (:475), acceptance 3 (:524-530)
- Claim: The check's derivation rules are left open, so "zero exceptions" can be reached by narrowing the check, and some invariants cannot be detected at all. Undefined: what an artifact is, what a reader is, when two deciders are "one rule", and what a re-check is. There is no coverage floor, the union's static half has no determinism requirement, and drivers are not required to extract the command text.
- Evidence: 1. The d625284 map's exclusions were made by hand (inventory/README.md "Excluded": 123 trace patterns, 84 static families, snapshot scanners and target guards left out as readers). Row 19 forbids any list in the check's source, but gives no rule that reproduces those exclusions. Without one, auto-commit.sh and pretool-read-size-guard.py read every file, so "written never read" can never fire.
2. E1's union adds static edges at about 82% precision, so false second writers or readers show up as violations. The only remedy left to the session is to drop edges, and nothing bounds how many.
3. Determinism is required only for the static-alone option. The pilot's extractor differed in 108 of 8,962 records between reruns.
4. Acceptance 3's mutation "a resolver run added to a /close step" is detectable only if drivers extract close.md's fenced blocks at test time. P1c.md:560 assumes that ("templates the drivers extracted"); P1b never requires it.
5. Natural-language prose checks (dev.md Step 12, dev-overnight.md "Validate test plan") cannot be derived by any test.
6. Acceptance 3's /tmp-versus-CLAUDE_STATE_DIR mutation needs replays run with CLAUDE_STATE_DIR set, which acceptance 4 does not require.
- Proposed fix: Append to row 19's description:
"Derivation rules (in the check's code, no lists):
(1) An artifact is a normalized path pattern. The replay's own session ids, timestamps, lanes and task ids are replaced by their roles, taken by value from the replay. Excluded: files tracked at replay start; files a process creates and removes within one hook run; `<artifact>.lock`; directories.
(2) A reader opens the path by name. Reads that follow a listing of the parent directory, and reads by a process whose read set equals the paths in the triggering event's tool_input, are not content reads.
(3) Two deciders are one rule when both reach the same function definition (static call graph) or the same script entry (trace).
(4) A re-check is a deciding read outside the producer side whose decision flips on a mutation the producer-side gate also rejects.
(5) Every replay runs with CLAUDE_STATE_DIR set to a directory that is not under /tmp.
(6) Drivers take each step's Bash blocks and templates from commands/*.md and agents/*.md at test time.
(7) The union's static half is sorted, and a test asserts two runs give byte-identical output.
The check covers code and extracted command blocks; natural-language prose checks are deleted by the PR and listed, and are not claimed as detected."
Add acceptance 6b: "Coverage floor: once, in the PR (not in a test), compare the check's artifact set on your base with the 122 rows of inventory/artifact-map-d625284.tsv; every map row whose path still exists on your base and that the check does not find is explained."


### feasible-H3 [high] harness-repair-plan/prompts/P1b.md
- Location: E5 (:261-269); row 7 (:463 "/dev's end, /close and /commit each call the one chain function once")
- Claim: E5's two candidates cannot be replayed in the kit's toy product repository: both reach the aggregator by a path inside the product repo, which has no scripts/ and no venv/. E5 then has no passing option and no fallback, and the same applies to every chain-function call row 7 keeps.
- Evidence: hooks/posttool-lane-completeness-watch.py:216-218 at d625284: `script = Path(project_dir) / "scripts" / "aggregate-dev-report.py"; if not script.exists(): return`, so candidate (a) silently never aggregates in a product repo. Candidate (b), commands/dev.md:885, runs `source venv/bin/activate && python3 scripts/aggregate-dev-report.py`. close.md:338 and dev.md:1322 (`python3 scripts/resolve-dev-artifact-chain.py`) use the same form. The toy repo sb-setup.sh builds (make_toy) has neither directory. P1c.md:449-452 records these as "Repo-relative script paths a product repo does not have (X5, P2's channel)", so the pilot's compliant drivers must have stepped around them.
- Proposed fix: Append to E5, before "Decision rule": "In the sandbox the product repository has no scripts/ or venv/. Candidate (a) resolves the script from the hook's own location (`Path(__file__).resolve().parents[1] / 'scripts'`; one line, the producer's fix). Candidate (b), and every chain-function call row 7 keeps (dev.md:1322, close.md Step 0, commit.md :313 and :334), uses the harness-home form of P2's channel row (TC-44), only the smallest part needed (as P1c X5 words it), in a form bash-safety accepts by design (`python3 ~/.claude/scripts/<name>`, never a `$HOME`-headed command). Record in the PR which lines you changed and leave the rest of TC-44 to P2."


### feasible-H4 [high] harness-repair-plan/prompts/P1b.md
- Location: E2 decision rule and fallback (:213-218); E1 fallback (:200-202); P1c.md X10 (:385-390)
- Claim: E2 sets no effective CI cost bound, the differential runs E1 needs are never counted, and P1c's X10 can move the traced D24 run off pull_request, against E2's "never nightly-only, per PR".
- Evidence: 1. E2 option (a) is taken whenever the traced replay fits "25 minutes wall per CI job (shard by pipeline with a matrix if one job does not)". The shard count is unlimited, so (a) always fits and the fallback "if no variant fits the budget" can never fire.
2. E1's fallback triggers "if the differential runs exceed E2's time budget", but that budget is per job and unbounded. The differential count, roughly reader invocations times artifacts read times 2 (trace-a alone has 5782 hook runs), is never measured.
3. Acceptance 4 needs both settings modes, but neither E1 nor E2 says which mode the check's trace uses.
4. P1c.md:386-389's split runs "the traced run that feeds the D24 table" only on the PR head before merge, plus weekly.
- Proposed fix: In E2 replace "fits 25 minutes wall per CI job (shard by pipeline with a matrix if one job does not)" with "fits at most 10 matrix jobs of at most 25 minutes wall each, setup included, with E1's differential runs counted (record their number and time)".
Replace E2's fallback with "Fallback: drop the differential runs to readers outside the producer side first (E1's fallback); if it still does not fit, the traced job runs on pull_request when hooks/, scripts/, schemas/, commands/, agents/ or settings.json change, and always on the PR head before merge."
Add: "The check traces the shipped settings; armed settings are replayed by acceptance 4 only."
In P1c.md X10 append: "P1b's D24 check job keeps P1b's E2 schedule and is outside this split."


### feasible-H5 [high] harness-repair-plan/prompts/P1c.md
- Location: X9 (:357-372), R-N1 and R-V1 (:542-551), acceptance 6 (:627-629)
- Claim: P1c says no record of N1 or V1-1/NV-1 exists and rebuilds both from guesses. P7b, which merges before P1c, contains both records, and the rebuilt descriptions are different defects, so the regression replays would not guard the ones that were fixed.
- Evidence: At P7b's head 760f06e:
- tests/test_landing.py:729 "Review V1-1: while a git lock refused a landed home's repair, settings.json kept ..."
- :770 "Review NV-1: while a git lock refused a landed home's repair of CLAUDE.md (doc-sync's date ...)"
- :1060 and :1096 "Review N1 ..."
- scripts/install/land:17 and :190 "(review N1)"
- commits 8ab874b "Review N1 (round 3)", 96bcb8f "Review V1-1", 921b512 "Review NV-1".
The actual N1: the CLI writes `model` (a key the clean form leaves out); git trusts the stat; /pull does not stash and `git pull --rebase` refuses, so hooks/pull.sh exits 1 and safe_pull returns 0 without pulling at every later Stop. P1c instead rebuilds it as P7b fact 2/9 (`UU settings.json` at the pop).
The actual V1-1/NV-1: a lock refuses the landing's repair of a conflicted pop; the Stop gave no notice and landing.log said repaired. P1c merges this with F4c, the /commit session-index sync.
P1c.md:357-361 and :544-546 assert `git grep` finds nothing, which is false on P1c's base.
- Proposed fix: Replace X9's opening ("No record of this defect exists ..." through "Reproduce it from its description: ... pop path.") with:
"The record is P7b's merged PR: commit 8ab874b ('Review N1 (round 3)') and tests/test_landing.py's tests whose docstrings begin 'Review N1'. N1: on a landed home the CLI writes `model`, settings.json's size changes, git trusts the stat, /pull does not stash, `git pull --rebase` refuses, and hooks/pull.sh exits 1 while safe_pull returns 0 at every later Stop."
Rebuild (i)/(ii) from that shape. The "before" tree is the first parent of 8ab874b, or f8c18c2 after P7's init (P7b says P7's manual init leaves a home the same way).
In R-V1 replace "no record with these ids exists ... so reproduce from the description" with "the records are commits 96bcb8f (V1-1) and 921b512 (NV-1) and their tests in tests/test_landing.py: a git lock refuses the landing's repair of a conflicted pop (settings.json; NV-1: doc-sync's CLAUDE.md or INDEX.md alone); assert the notice names the refused path and landing.log says result=repair-refused, then the next Stop after release repairs it. Before: the first parent of 96bcb8f."
Keep F4c (the sync) as its own fault, not as V1-1.


### feasible-H6 [high] harness-repair-plan/prompts/P1c.md
- Location: rows 7, 10, 13, 18 (bullets on do.md, spec-update, merge.md:165, close.md :337/:507, /dev-command auto-detect), row 19 bullet 1; row 1 (:399 "the one exception"); row 10 (:408); Out of scope (:588-590, :593-595); acceptance 6 (:627-629); P1b.md rows 3, 6, 8, 12, 13, 17, E8, E9, E13, E14, Correction 5
- Claim: P1c's scope and evidence were written as if P1b had not run. About ten P1c rows target sites P1b's rows already remove. P1c's "before" reproductions are taken on its own base, where those defects are already gone. Several P1c hand-offs go to P1b, which merges first. The implementation session cannot tell which instruction governs.
- Evidence: - P1c row 7 (G2 hand-off and stores, :614/:637/:659/:747) = P1b row 3 (:459, the same lines).
- P1c row 10 (e2e reads the declared path) = P1b row 3's Moves column.
- P1c row 13 (file check reads the obligation's schema) = P1b row 6's Moves column and E13.
- P1c row 19's seed (create-overnight-state.sh :1026-1056) = P1b E13 ("no seed file").
- P1c row 18: the do.md template = P1b E8; spec-update mktemp = P1b row 17; merge.md:165 unlink = P1b row 12/E11; close.md :337/:507 = P1b rows 7 and 8 (close.md:334-398, :504-519); /dev-command INDEX.md auto-detect = P1b E9/E14.
- P1c.md:593-595 lists the guard's `-F` quoting for P5, but P1b Correction 5 fixes it.
- P1c.md:408 and :588-590 hand items to "P1b's D24 question" / "P1b's table".
- Acceptance 6 asks for R-E1 "before row 13" and R-P1 "before row 8" on P1c's base, where P1b may already have fixed them.
- P1c row 1 calls its committed drivers "the one exception", although P1b row 19 already commits drivers.
- Proposed fix: Insert in P1c.md after "Interfaces you consume" a section "Delivered by P1b (verify on your base; replay only)": "For each of rows 7, 10, 13 and 19's seed, and the row 18 bullets on do.md Step 5, spec-update.md:115, merge.md:165 and close.md :337/:507, read P1b's merged PR. Where P1b did the change, your row is its replay and unit test only, and the 'before' tree for its regression or fault table is the first parent of P1b's merge commit on master."
Replace row 10's "Whether this gate should stay a second decider next to G2 on the same artifact is P1b's D24 question: list it, do not merge them here." with "P1b's check decided whether the e2e gate stays a second decider; keep what P1b merged."
Replace Out of scope :588-590's "list them for P1b's table; do not merge them here" with "a second deciding consumer the suite shows on your base is a defect in P1b's check: report it under 'Out of scope, found' with the trace event".
Replace :593-595's privilege-guard item with "fixed by P1b (Correction 5): its test passes on your base".
In row 1 replace "This phase commits its scenario drivers as test code: the one exception to P1's 'do not commit scenario drivers'." with "Extend the drivers P1b committed; do not build a second set."


### feasible-H7 [high] harness-repair-plan/prompts/P1c.md
- Location: Net code cap (:685-690); acceptance 15 (:657-658)
- Claim: P1c's net-code cap (<= 0) is paid for mainly by deletions that P1b makes first. On P1c's real base the cap is likely unreachable, and it would push X7 and X8 towards their no-code options for line-count reasons rather than on experiment results.
- Evidence: P1c.md:688-690 funds the cap with "The G2 hand-off and its record code (about :304-:831 ...), `_write_blocked_aggregate` (about 80 lines) and the launcher's empty-contract block (about 35 lines)", expecting about -150. P1b row 3 (:459) deletes the G2 hand-off and stores (:614-829), and P1b E13 removes the seed (create-overnight-state.sh :1026-1056). What remains to pay for P1c's additions is about 80 lines. The additions are: X7 (A)'s /proc lock wait; X8 (A) in four files; row 16's Gate 4 recovery rule; row 18's config-guard allowance; row 8's own-transcript correlation; and any X6 site fixes.
- Proposed fix: Replace the cap paragraph's first two sentences with:
"Net lines in hooks/, scripts/ and schemas/ (tests excluded), measured against your base, must be <= the lines rows 7-20 delete on your base plus 150; the PR lists every added line by row. P1b already removed G2's hand-off (its row 3) and the launcher seed (its E13), so those lines do not count here. X7 and X8 are decided by their rules, never by this cap; C3 is measured by the suite (acceptance 13)."
Adjust acceptance 15 to the same bound.


### format-FH-1 [high] harness-repair-plan/prompts/P1b.md
- Location: :456 (scope row 0, last sentence); :542-544 (acceptance 6); :574 (acceptance 16); :660-661 (PR heading Inventory)
- Claim: P1b requires the before and after artifact maps (heading Inventory) and a D24 table with one row per artifact in the PR body. A GitHub PR body holds at most 65,536 characters, so the session cannot meet scope row 0 and acceptance 6 as written. It will either fail to post the body or cut down the D24 proof the owner asked for.
- Evidence: inventory/artifact-map-d625284.tsv is 79,334 characters for 122 rows, so one map alone is over the limit. Its artifact, producers and deciding_consumers columns alone add up to 27,018 characters, so a before-to-after D24 table with a proof column is about 55k characters before the 19 other acceptance outputs, the E1-E14 results and the release notes. Acceptance 16 also asks for each experiment's "raw output", while :174 says "raw counts or exit codes". E2's raw strace is 57 MB per replay (:207).
- Proposed fix: (1) :456 replace "in the PR, never in the repository." with "in PR comments of at most 60,000 characters each, linked from the PR body, never in the repository."
(2) :660-661 replace "**Inventory** (the regenerated map before and after, from the check's own derivation, and what differs from inventory/artifact-map-d625284.tsv);" with "**Inventory** (inventory/README.md's counts table before and after, the rows that differ from inventory/artifact-map-d625284.tsv, and links to the PR comments that hold both full maps);"
(3) :542 replace "**D24 table** in the PR body:" with "**D24 table**, in PR comments of at most 60,000 characters each, linked from the body (the body lists the rows whose producers or deciding consumers change):"
(4) :574 replace "Each experiment's setup, raw output and option taken, E1-E14." with "Each experiment's setup, raw counts or exit codes and option taken, E1-E14 (no trace files)."


### format-FH-2 [high] harness-repair-plan/prompts/P1c.md
- Location: Scope intro :394-395; rows 7 (:405), 10 (:408), 13 (:411), row 18 bullets do.md (:431-433), merge.md:165 (:436-437), /dev-command auto-detect (:440-441), row 19 first bullet (:455-459); X2 :245; Out of scope :588-590 and :593-595; Retired :673-682; Net code cap :687-690
- Claim: P1c starts only after P1b merges, but it is written against d625284 as if P1b had not run. It repeats P1b's deletions. It counts P1b's deletions toward its own net-code cap (<= 0, estimate -150) and its own retired rules (at least 8). It sends findings "for P1b's table" when P1b is already merged and its CI check has no exceptions. It leaves `-F` to P5 when P1b fixes it. On the post-P1b base, the cap and the retired count lose what pays for them, and the session either redoes P1b's work or claims credit for it.
- Evidence: Pairs, each P1c location first and the P1b counterpart second:
- G2's hand-off, ESCALATION_ACK admission and stores: P1c row 7 :405 (:304-:831); P1b row 3 :459 (:614-635, :637-656, :659-713, :747-829).
- e2e gate reads the obligation's declared path: P1c row 10 :408; P1b row 3 Moves :459.
- overnight file-check reads the obligation's schema: P1c row 13 :411; P1b row 6 Moves :462 and E13.
- no launcher seed: P1c row 19 :455-459; P1b E13 :356-372.
- do.md expected_absent: P1c row 18 :431-433; P1b E8 :299-307.
- merge.md grant unlink: P1c :436-437; P1b row 12 :468 and E11.
- /dev-command spec auto-detect: P1c :440; P1b row 8 :464 and E14.
- guard `-F` read: P1c out of scope :593-595 ("P5's commit-guard precision row"); P1b Correction 5 :413-415 fixes it.
- Net code: P1c's -150 relies on the G2 code at :304-:831 and on the launcher's empty contract; both deletions are also counted in P1b's own estimate (:620-621, "G2's escalation and journal-view code about 230").
- Retired: P1c items 1, 3, 6 and 8 (:674-681) repeat P1b's retired list (:599-613).
- Caps: P1b Correction 2 (:403-404) and the sync's V-5 re-measure the caps of P2, P3, P4, P5, P9 and P10, but not P1c's.
P1c's own hedge at :40 ("A defect P1b or P8 already closed needs only its replay") does not fix the cap, the retired count or the out-of-scope text.
- Proposed fix: (1) Insert after :395 ("... New code runs on Python 3.10, the CI floor."): "Rows 7, 10, 13 and 19 (first bullet), and row 18's do.md, merge.md:165 and /dev-command auto-detect bullets, restate P1b's row 3, row 3, row 6 with E13, E13, E8, E11 with row 12, and E14. P1b delivered them: on your base each needs only its fault or scenario replay, and code changes only where that replay still fails."
(2) :245 replace "and the PR lists them for P1b's D24 table." with "and the PR lists them in its D24 table (acceptance 12)."
(3) :408 delete "Whether this gate should stay a second decider next to G2 on the same artifact is P1b's D24 question: list it, do not merge them here."
(4) :588-590 replace "Where the suite shows several deciding consumers of one artifact (e2e and G2 on the qa-report, the four producers of the canonical aggregate, ledger L18), list them for P1b's table; do not merge them here." with "P1b's CI check (no exceptions) already holds one producer and one deciding rule per artifact; a violation the suite shows is a P1b defect: fix it at its producer and name it in the PR."
(5) :593-595 delete the clause from "pretool-git-privilege-guard.py :1254-1260 opens" through "(P5's commit-guard precision row);" (P1b Correction 5).
(6) :688-690 replace "The G2 hand-off and its record code (about :304-:831, of which `_gate_decide`'s plain block stays), `_write_blocked_aggregate` (about 80 lines) and the launcher's empty-contract block (about 35 lines) pay for the additions; expect about -150 (an estimate, UNVERIFIED)." with "P1b deleted the G2 hand-off and its records (P1b row 3) and the launcher's empty contract (P1b E13); they count in P1b's cap, not here. The reviewer re-derives this cap from P1b's merged diff before dispatch; report net lines and what pays for them." Also add P1c to the phase list in sync edit V-5 ("P2, P3, P4, P5, P9 and P10").
(7) :673 change "Retired (at least 8):" to "Retired (at least 4, not counting what P1b retired):" and drop items 1, 3 and 8, plus the second-schema half of item 6, unless your base still has them.


### owner-R2 [high] harness-repair-plan/prompts/P1b.md
- Location: E4 :244-260 (the 'Shipped, list …' clause :256-258); release note :96-97; E12 :351-352; DO NOT :683
- Claim: P1b knowingly ships a window on the live home in which faults go undetected. It deletes consumer-side checks while G1-G3 stay advisory in shipped settings, and E12 also deletes the advisory records that E4 says will be 'the only' trace of those faults.
- Evidence: E4 pilot (shipped): 'a missing or malformed dev report is blocked by no hook; only the dev.md Step 12 prose and the Step 17 resolver run by prose catch it'. E4 then says: 'Shipped, list every fault that a deleted check used to stop and that now only an advisory record notes … into P2's hand-off'. The release note reads 'G1-G3 stay advisory until P2 arms them'. E12 says 'for the advisory logs: the gate writes nothing in advisory mode until P2 arms it', so even the advisory record is gone. The DO NOT forbids arming any gate. The owner's /pull lands P1b on his live home (D15/D19). Ruling 4 (design :21-23) 'no new bugs are acceptable'; C3 'strict failure-surface decrease'; D25 '出现了错误也可以立刻被修复'. P1c X3 already shows that arming G2 alone returns F1, F1q and F2 to their producers.
- Proposed fix: (1) Replace E4 :256-258 ('Shipped, list every fault … into P2's hand-off.') with 'Shipped: the escape list is empty at every commit. A consumer-side copy is deleted only in the commit that arms, in settings.json env, the allowed-position gate E4 names for its faults, under P1c X3's rule (0 blocks of that gate on every compliant replay and on acceptance 17's live-landing replay). A copy whose faults only G1 or G3 stop stays until P2's arming commit and is listed for P2.' (2) Replace release note :96-97 with 'G2 is armed where E4 needed it (X3's rule); G1 and G3 stay advisory until P2, and no consumer-side check whose faults only they stop is deleted here.' (3) DO NOT :683: 'Do not arm G1-G3 or any other switch in a tracked file (P2)' -> 'Do not arm G1, G3 or any other switch in a tracked file (P2); arm G2 only under E4's rule.' (4) E12 :351-352: replace '(for the advisory logs: the gate writes nothing in advisory mode until P2 arms it)' with '(an advisory gate's record stays until that gate is armed and goes in the arming commit)'. (5) Sync: P1c X3 and row 9 become 'replay only' where P1b armed G2.


### owner-R3 [high] harness-repair-plan/prompts/P1c.md
- Location: X7 option (B) :324-325 and its rule; Scope row 14 (:410); faults assertion :522-525 (F4s)
- Claim: X7's fallback (B) sends a stale git lock to the owner ('the orchestrator asks in-turn'), with no carve-out for /dev-overnight or /commit --auto. If the experiment picks (B), P1c's own F4s assertion (0 human events) cannot pass and the suite cannot go green.
- Evidence: :324-325 '(B) it waits only and never removes; a stale lock is reported in the analyst's response block, and the orchestrator asks in-turn (D23).' The rule says 'take (A) if … otherwise (B)'. (2) lists F4s 'a stale index.lock at /commit' and asserts '0 human events between the injection and the terminal, except … F5, F5f and F6'. D20 says overnight never asks (P2 adds the AskUserQuestion deny, so an ask there is also refused). C5 'no new human-in-the-loop steps'. D25 'any error can be repaired immediately'. CC8 'agent哪里犯错了自己就补哪里'.
- Proposed fix: Replace (B) with an automatic variant: '(B) where /proc is unavailable, the sync treats the lock as stale when no git process of this repository runs (from ps, or fuser/lsof where present) and the lock is older than the sync's own start; it removes it with one unlink, says so on stdout and continues; it never asks.' Rule: 'take (A) if …; otherwise (B); no branch asks the owner or the orchestrator, inside or outside /dev-overnight.' In row 14, delete 'The prose changes only if X7 picks (B) (the stale-lock line in the response block)'.


### owner-R4 [high] harness-repair-plan/prompts/P1c.md
- Location: 'The suite' (2) Faults :508-528 and (4) Regressions
- Claim: The never-fail suite has no replay of /close or /commit meeting an incomplete cycle and completing it. CC4, which P1c itself cites, is therefore never proven, and nothing catches R1's regression.
- Evidence: P1c cites CC4 ('只要用户想dev一定dev完成，用户想close一定close完成') among the words D25 restates (:146-149). All 17 faults inject inside /dev, /commit's index or /restart. None injects a gap that /close or /commit has to complete. The terminal for /close is 'CLOSE: YES'; scenario (1) covers only compliant /close.
- Proposed fix: Add to (2): 'F8: /close after a /dev cycle whose lane QA report is missing (removed after QA's stop); F8c: /commit after a /close of a cycle with a dev-stage gap. Assert: the gap names the artifact and check; the dispatch that declared it (E3's reader) is dispatched again by /close (/commit) with the same obligation template; the cycle completes; CLOSE: YES and the commit lands; 0 human events (CC4, D7).' Add 'R-CC4' to (4), with its 'before' on the base.


### plan-FIT-02 [high] harness-repair-plan/prompts/P1b.md
- Location: E4 (:244-259); DO NOT :683; against prompts/P1c.md X3 (:248-259) and W PLAN-v2.md:352
- Claim: P1b deletes consumer-side checks while G1-G3 are still advisory, and E4 ships an 'escape list' of faults that nothing stops in shipped settings. Master is the owner's live ~/.claude, which lands on /pull. From P1b's merge until P1c's X3 arms G2 (P1c is about 6 days) and P2 arms G1 and G3, those faults pass with no check at all. That contradicts D25 ('出现了错误也可以立刻被修复') on the owner's live home.
- Evidence: P1b :256-257: 'Shipped, list every fault that a deleted check used to stop and that now only an advisory record notes, with the gate that stops it once P2 arms; this list goes in the PR'. P1b :683: 'Do not arm G1-G3 or any other switch in a tracked file (P2)'. P1c :82-84 (pilot): in shipped settings, F1 and F2 are blocked by no hook. Arming G2 alone returns F1, F1q and F2 to their producers (P1c X3 :248-249). P1b rows 7 and 10 delete /close's schema gate, Step 0's verdict layer and /commit Step 5's second resolver run. D19: merged code reaches the owner's homes by /pull while his sessions keep running.
- Proposed fix: Add to E4's decision rule: "A fault that a deleted consumer-side check stopped, and that no gate stops in shipped settings, may not be left open on master. For a fault G2 stops: your last commit sets `\"CLAUDE_OBLIGATION_STOPGATE\": \"block\"` in settings.json env, after the false-block replay of prompts/P1c.md X3 (acceptance 4 and 17 with it set: 0 G2 blocks on compliant stops). For a fault only G1 or G3 stops: keep that consumer-side check, list it, and P2's arming commit deletes it." Change P1b :683 to "Do not arm G1 or G3, or any switch other than CLAUDE_OBLIGATION_STOPGATE under E4, in a tracked file." In P1c X3, prepend: "If P1b's merge already set CLAUDE_OBLIGATION_STOPGATE, replay only and say so." Sync P2-4's 'Arming' bullet then reads "if P1b or P1c already set ...".


### plan-FIT-03 [high] harness-repair-plan/prompts/P1b.md
- Location: E13 (:356-373); row 13 (:469)
- Claim: E13's main variant makes the orchestrator the cycle contract's only writer at Step 4. That is the revert of decided TC-43, and it brings back the ledger's L46 problem (the orchestrator writes its own contract). E13 also removes break-overnight-lock.py's state write without replaying /stop, and it fixes the cycle-index source that P2 row 12 defines.
- Evidence: P1b :366: 'one writer (the orchestrator at Step 4)'; :372 gives the PM TRIAGE handler only as the fallback. W PLAN-v2.md:1074 (TC-43): 'The PM TRIAGE handler in posttool-subagent-track renders steps 8/10/11g/12/15/20 ... the orchestrator no longer writes the contract'; its revert is 'Restore the orchestrator-written contract prose'. W P2.md:386-387: '...it is the contract's only writer'. P1c X5 :286 quotes corrections 2.21: 'The PM TRIAGE handler is the contract's only writer'. report-zh.md L46 row: '自己给自己出合同'. E13 :368: 'the state is written once by the launcher'. W P2.md row 14 keeps break-overnight-lock.py writing terminal_status=cancelled_by_user and current_phase=completed, which 'keeps closing lib/overnight's session-agnostic exemption, _state_file_is_live :46-60'. E13's decision rule (:369-371) contains no /stop replay.
- Proposed fix: In E13, replace "one writer (the orchestrator at Step 4)" with "one writer: the PM TRIAGE handler in hooks/posttool-subagent-track.py, which renders steps 8/10/11g/12/15/20 from scripts/todo/dev-overnight.py _STEPS (TC-43, P2 row 13; delivered early: say so for P2)". Replace the fallback with "Fallback: the launcher stays the state's only writer apart from /stop's record; the orchestrator never writes the contract (that is TC-43's revert); never three copies or a seed." Append to the decision rule: ", and /stop inside the window still releases the time-lock and closes the session (lib/overnight _state_file_is_live false afterwards), as on the base; break-overnight-lock.py's terminal_status/current_phase write stays unless that replay passes without it (P2 row 14). The cycle index is one function, P2 row 12's cycle_index(): if you remove posttool-overnight-loop.py's cycle_count write, cycle_index() reads the cycle directories, and you say so for P2."


### plan-FIT-04 [high] harness-repair-plan/prompts/P1c.md
- Location: X9 (:357-372); R-N1 and R-V1 (:542-551); row 20 (:418); also reviews/P1b-plan-sync.md V-31 (:474-475), H-10 (:682-683), K-12 (:850-851)
- Claim: R-N1 and R-V1 replay the wrong defects. P1c and the sync say that N1, V1-1 and NV-1 have no record, but at the branch head that P1c's session extracts, reviews/P7b-PR-record.md (commit 4a9256a) records all three with their before/after evidence. X9's 'N1' is P7b.md facts 2 and 9 (a stash-pop UU at f8c18c2). P7b's record says no pull path can repair that state, so R-N1(i) as written tests an unreachable state. The real N1's remaining window and the fswatch pipefail defect are left 'for the reviewer', and no phase owns them, although they are D25 process errors.
- Evidence: P7b-PR-record.md:207 (N1): on a landed home, once the CLI wrote `model`, /pull exits 1 ('cannot pull with rebase: You have unstaged changes') and safe_pull returns 0 without pulling. It was fixed by re-recording the stat at the next Stop; the before is n1-before.txt (d625284 after P7's manual init). :229 (V1-1) and :240 (NV-1): a landing under a git lock gave no notice and logged result=repaired. Out of scope :1305-1316: 'a /pull run after a CLI write ... and before the next Stop still meets git's refusal once ... (for the reviewer)'. :1264-1268, Fact 1: safe_pull's tee without pipefail logs failures as success; 'no phase in PLAN-v2 owns the rest'. P7b.md:224-229 (fact 9): a home left in S3 or S4 'receives nothing more by any pull path'. P1c :357-361 and :544-546 say the greps find nothing under harness-repair-plan/; the sync says the same at V-31 :474-475, H-10 :682-683 and K-12 :850-851. P1b row 0 says 'claude-settings.applied ... or a claude-settings.checked marker'; the record has both (:401 the render record, :217/:643 the marker).
- Proposed fix: Rewrite X9's facts as: "N1 is review N1 of PR P7b (reviews/P7b-PR-record.md:207). Before: d625284 after P7's manual init, a CLI `model` write, then pull.sh rc=1 and safe_pull rc=0 with HEAD behind. After: one Stop, then /pull and safe_pull pull. Its remaining window (record :1305-1316, a pull before that Stop still fails once) is a D25 process error: fix it at the pull producers (hooks/pull.sh HAS_CHANGES and git-fswatch.sh has_changes call the landing's existing stat re-record), and replay both pulls." Rewrite R-V1 as: "reviews/P7b-PR-record.md:229 and :240 (landedlock.sh and v11doc.sh scenarios): with index.lock held, the Stop's notice names each refused path ('still conflicted: git refused its repair, tried again at the next turn end'); after release the next Stop repairs. F4c/X7 stays its own fault, not labelled V1-1." Widen row 20 to "hooks/pull.sh; hooks/git-fswatch.sh safe_pull/has_changes: N1's window (always) and Fact 1's pipefail (record :1264-1268)". In the sync, replace V-31's "(N1 and V1-1/NV-1 have no record in the repository or the planning branch; P1c reproduces them from their descriptions)" with "(recorded in reviews/P7b-PR-record.md rows N1, V1-1 and NV-1)". Fix H-10 :682-683 and K-12 :850-851 the same way. In P1b row 0, name both `<git dir>/claude-settings.applied` and `<git common dir>/claude-settings.checked`. Fact 9 (homes stuck in S3 or S4) is still unowned, and P7b says 'the reviewer takes it up with the owner', which D18/D19 forbid; give it to P1c or P11 explicitly.


### plan-FIT-05 [high] harness-repair-plan/prompts/P1b.md
- Location: E6 (:271-284); against W prompts/P6.md acceptance 19 (:716-719), row 5 (:320), D4 bullet (:170-171); W prompts/P4.md:78 and :282; W PLAN-v2.md TC-46 (:53); sync P6-4 (:1287-1291) and V-17 (:278)
- Claim: E6 picks the hook-written attribution journal (never the agent's self-report) as the one producer of 'which files this dev wrote', and it deletes `_wire_ledger_judgment`. The batch's P6 names the CLI transcript write set as that producer and keeps `_wire_ledger_judgment`'s ENTANGLED check, and TC-46 checks dev's declared lists against the transcript. P4 routes close-QA findings by the journal. The three phases contradict each other. The sync's P6-4 ('A3.a builds on E6's outcome') contradicts W P6's acceptance 19.
- Evidence: P1b :277-280: 'keep the producer that is hook-written and equals the transcript set ... (HC2: never the agent's self-report); the other producer and every consumer rule that compares the two go (the G2 wire `_wire_ledger_judgment`, ...)'. W P6.md:716-718: 'the one producer (the transcript write set) and lists the other two (the attribution journal, dev's owned_edits) with the phase that retires each'. W P6.md:320: '`_wire_ledger_judgment`'s ENTANGLED check stays'. W P6.md:171: 'The write set comes from the CLI transcript ... never from git state, the journal'. W P4.md:78: 'Close-QA findings go to the subagent the attribution journal records as the file's writer'. report-zh.md P6 bullet: 'dev 交的文件清单在 dev 自己结束时，用 CLI 记录核对（你说过"是dev的问题"）'.
- Proposed fix: Rewrite E6's candidates and rule: "Candidates for 'which files this dev wrote': (a) the attribution journal, (b) dev's self-reported owned_edits/pre_edit_snapshots, (c) the CLI transcript's Write/Edit set of that dev, read through one function (command_span `write_set()`, the reader P5-b's A3.c and P6's A3.a use). The transcript is a record like E7's todo list, so prefer (c) if it equals every replay's actual writes. Then delete the aggregator union and attribution_adjudicator's comparison. Keep `_wire_ledger_judgment`'s ENTANGLED check and dev's declared files_created/files_modified, which P6 A3.a checks at dev's stop (TC-46). List the journal's remaining readers (P4's close-QA routing, /commit staging) for P4 and P6." Change the sync's P6-4 bullet to "P1b E6 settled the record (see its PR); W acceptance 19 holds if E6 took (c); otherwise the PR names E6's producer and the phase that retires the rest". Add to P4-4: "close-QA routing reads E6's record, not the journal, if E6 took (c)".


### plan-FIT-06 [high] harness-repair-plan/reviews/P1b-plan-sync.md
- Location: V-24 (:350-362), V-13 (:219-231), P10-4 (:1501-1522), P4-4 (:1095-1124), plus the batch texts W PLAN-v2.md:460 and :811, P10.md:99-104 and :130-132 and :354, P4.md:104 and :675-680, P9.md:605-618, P2.md:824-826
- Claim: The sync assumes corrections.md is not yet applied, so its overlap notes say 'do not add corrections.md's D24/artifact-level goal'. The reviewer's batch (now committed as 06794d9, merged in be06811) already added those goals. The sync's INSERTs would put 'P1b's CI check replaces it, add no second inventory' next to instructions that still order a second inventory or a full D24 table for artifacts P1b already settled. Several batch texts also name P2, P3 or P4 as the deleters of artifacts that P1b deletes.
- Evidence: W PLAN-v2.md:811: 'Artifact-level D17 (D24): ... proven by an experiment-9 trace over all ten pipeline commands'. V-24 inserts after :809 and says 'Do not add 2.61's text'. W P10.md:99-104: 'Run experiment 9 for all ten pipeline commands ... list every path written ... A write with no reader is deleted'. P10-4 says 'Do not add the goal as written'. W PLAN-v2.md:460 and W P4.md:104 and :675-680 ask for a 'D24 table ... one row per artifact /close and /commit read or write (L17 ... L53)', and the L40 clause duplicates P1b E11. V-13 and P4-4 say 'do not add'. W P9.md:614-615: 'which P3 row 7 (L26, L25), P2 rows 4 (L27) and 9 (L48) and P4 row 8 (L36) delete'. W P10.md:354: 'earlier phases delete L26 and L25 (P3), L27 (P2) and the L36 readers (P4)'. W P2.md:824-826: the D24 table for 'overnight state, cycle contract, ... canonical aggregate, advisory logs, harness-report.json, continuation sentinel, aggregate-pending', all of which P1b delivers.
- Proposed fix: Turn these into REPLACE edits against 06794d9. (1) V-24: REPLACE the PLAN-v2.md:811 bullet ('- Artifact-level D17 (D24): every artifact the harness writes has a reader ... ledger DEAD rows first.') with V-24's bullet. (2) V-13: add REPLACE of PLAN-v2.md:460 with '- D24 table for the artifacts P4's rows still change; P1b's table is the before for L17, L18, L22, L23, L28, L31, L32, L40, L41, L42 and L53.' (3) P10-4: REPLACE the P10.md:99-104 goal bullet with '- **Producer and consumer per artifact (D24).** P1b's CI check holds it (one producer, at least one consumer, one deciding rule per artifact, derived at test time) and stays green; this phase adds no second inventory, and row 19 deletes only what P1b's PR left, each with its proof.' At P10.md:130-132 change 'deletes writes with no reader ... seeded by row 19' to 'deletes only the leftovers P1b's PR names (row 19)'. At P10.md:354 replace 'earlier phases delete L26 and L25 (P3), L27 (P2) and the L36 readers (P4)' with 'P1b deleted L26, L25, L27, L36's readers, L06's workflow-history, L56's reader and the L54 writers (its rows 2, 3, 6, 10 and E12)'. (4) P4-4: REPLACE P4.md Goal 8 (:104) and acceptance 21's 'with one row per artifact /close and /commit read or write (L17, ... L53)' with 'for the artifacts your rows still change (P1b's table is the before)'; replace the L40 clause with 'L40: P1b E11 kept one channel; verify it'. (5) Add REPLACE of P9.md:614-615 'which P3 row 7 (L26, L25), P2 rows 4 (L27) and 9 (L48) and P4 row 8 (L36) delete' with 'which P1b deleted'. (6) Add REPLACE of P2.md:825-826's list with 'for the retro report, the summary, the terminal receipts and every artifact your rows change (P1b's table covers the overnight state, cycle contract, canonical aggregate, advisory logs, harness-report.json, continuation sentinel and aggregate-pending)'.


### facts-F5 [medium] harness-repair-plan/prompts/P1b.md
- Location: Acceptance 8 (P1b.md:548-549)
- Claim: `git grep -nE 'session_ts|TASK_ID_REF_PATTERNS|SESSION_ID="dev-\$\{TASK_ID\}"' -- hooks scripts commands ':!hooks/tests'` is to print nothing after P1b. The grep overlaps work P1c owns, and it misses one of P1b's own targets.
- Evidence: On d625284 it prints 18 lines. They include subagentstop-e2e-enforce.py:77-148, the session_ts correlation for QA dispatches without an obligation, which P1c row 10 rewrites after P1b and still cites as present ('report resolution :120-137'). They also include subagentstop-artifact-contract-enforce.py:45 and :209-234 in `_find_correlated_reports`, the legacy path that P1c row 8 replaces (F7b). P1b's own rows change only the obligation-bearing e2e rule (row 3) and the G2 regex block :220-232 (row 1). So acceptance 8 either fails or forces P1b to do P1c rows 8 and 10. Separately, dev.md:128 `SESSION_TS="${DEV_SESSION_ID#dev-}"`, which row 1 deletes, is upper-case, and the grep is case-sensitive, so it never checks that deletion.
- Proposed fix: Replace acceptance 8's sentence with: "`git grep -niE 'session_ts|TASK_ID_REF_PATTERNS|SESSION_ID=\"dev-\$\{TASK_ID\}\"' -- hooks scripts commands ':!hooks/tests'` prints only subagentstop-e2e-enforce.py's resolution for QA dispatches without an obligation (P1c row 10) and subagentstop-artifact-contract-enforce.py's `_find_correlated_reports` for dispatches without an obligation (P1c row 8), each listed in the PR's hand-off to P1c; every other task-id-to-name derivation in hooks/ and scripts/ is a call into obligation.py (list them)." Alternatively, move P1c rows 8 and 10 into P1b and say so in P1c.


### facts-F6 [medium] harness-repair-plan/prompts/P1b.md
- Location: E3 table list (P1b.md:221-226); Scope row 10 'Deleted' (P1b.md:466, 'the "no code table" claims (close.md:288, commit.md:83-84)'); Acceptance 7 (P1b.md:545-547)
- Claim: The filename-to-role tables in close.md and commit.md are close.md:162-181 and commit.md:99-116, and the 'no code table' claims are close.md:288 and commit.md:83-84. Acceptance 7's grep for `close_artifact_role|artifact_role\(` is meant to prove they are gone.
- Evidence: close.md:276 holds a third copy of the table in prose ('Mapping rows: `dev-report*` -> dev; `*qa-report*` -> qa; `ticket*|ba-spec*|context*|acceptance-criteria*` -> ba; ... changelog status -> changelog-analyst; everything else -> orchestrator'). close.md:278 holds a third 'no code table' claim ('there is no engine output and no code table'). commit.md:88-97 describes the 'Eight-row mapping' in prose. D21 forbids a filename-to-role table 'in code or in prose'. Acceptance 7's grep cannot see any of these, so it passes with the prose table still in place.
- Proposed fix: In E3's table list, after "commands/close.md:162-181 and commands/commit.md:99-116 (filename to role; their changelog-status* row matches no file)" add "and their prose copies close.md:276 ('Mapping rows: ...') and commit.md:88-97 ('Eight-row mapping, first match wins')". In row 10, change "the \"no code table\" claims (close.md:288, commit.md:83-84)" to "the \"no code table\" claims (close.md:278, :288, commit.md:83-84)". Change acceptance 7's grep to "`grep -nE 'close_artifact_role|artifact_role\(|Mapping rows|Eight-row mapping|no code table|no code, table' commands/close.md commands/commit.md` prints nothing".


### facts-F7 [medium] harness-repair-plan/prompts/P1b.md; harness-repair-plan/inventory/README.md; TSV rows A88, A105, A106
- Location: P1b.md:52-55 (Interfaces you consume, P7b bullet); Scope row 0 (P1b.md:456); Scope row 16 (P1b.md:472, 'render-settings :1193 in the reviewer's P7b copy'); README.md:59 (`p7b_p8_effect` column definition); TSV A88, A105, A106 column p7b_p8_effect/producers
- Claim: P7b's products are 'the overlay `settings.machine.json`' plus 'the marker or record the landing keeps in the git directory (`claude-settings.applied` in the reviewing session's copy; an earlier planning note calls it a `claude-settings.checked` marker in the git common dir: use what merged)'. Row 16 cites logs/landing.log at render-settings :1193 with one writer. README and the TSV say the P7b copy is based on f8c18c2 (A105: 'reviewer copy 98096fc9'), and A88 says P7b adds 5 lines near :377 of pretool-bash-safety.sh.
- Evidence: At P7b head 760f06e, which is based directly on d625284 (merge-base d625284; first commit ef5867b's parent is d625284), and no object 98096fc9 exists:
- `claude-settings.applied` is P7's render record, already at d625284 (render-settings:29 and :56 there). P7b's land:31 only reads it.
- P7b adds two files of its own in the git common dir: `claude-settings.checked` (land:195; kept as a recorded departure, P7b PR body NF-1) and `claude-landing.lock` (land:206). These are alternatives to nothing: both exist, and they are new state files that matter for C1.
- settings.machine.json is P7's overlay (A105); P7b's landing writes it on live homes.
- logs/landing.log is declared at render-settings:1208 ('append-only; no code reads it') and written by two programs: render-settings cmd_land :1503 and scripts/install/land (log() :50, the redirects at :226 and :245). That makes it 'several producers'.
- The bash-safety change is 7 lines at :8-14, which read guard keys from settings.json through hooks/lib/claude_home.py settings_env (:189). P7b also adds the same read to hooks/lib/subagent_restart.py:826-832. These are new runtime readers of settings.json, absent from A105.
- Proposed fix: In P1b.md:52-55, replace "the overlay `settings.machine.json`, the marker or record the landing keeps in the git directory (`claude-settings.applied` in the reviewing session's copy; an earlier planning note calls it a `claude-settings.checked` marker in the git common dir: use what merged), `logs/landing.log`" with "the landing's writes of P7's overlay `settings.machine.json` and P7's render record `<git dir>/claude-settings.applied`, its own `<git common dir>/claude-settings.checked` marker (land:195 at 760f06e) and `<git common dir>/claude-landing.lock` (land:206), `logs/landing.log` (written by scripts/install/land :50, :226, :245 and render-settings cmd_land :1503), the hooks' new reads of settings.json env (hooks/lib/claude_home.py settings_env, pretool-bash-safety.sh:8-14, subagent_restart.py:826-832)". In row 0, replace "(`claude-settings.applied` in the reviewer's copy, or a `claude-settings.checked` marker in the git common dir)" with "(`claude-settings.checked` and `claude-landing.lock` in the git common dir; `claude-settings.applied` is P7's)". In row 16, replace "read by no code, render-settings :1193 in the reviewer's P7b copy" with "read by no code, written by two programs: scripts/install/land :50, :226, :245 and render-settings :1503 (LANDING_LOG :1208) at 760f06e". In README.md:59, replace "(the reviewing session's copy, base f8c18c2, not in the repository, so UNVERIFIED against the P7b that merges)" with "(the reviewing session's clone at 760f06e, based on d625284, not yet pushed; UNVERIFIED against the P7b that merges)". Correct A105 (760f06e; `land` subparser :1532, cmd_land :1493), A106 (producers: land and render-settings), and A88 (7 lines at :8-14).


### facts-F8 [medium] harness-repair-plan/inventory/artifact-map-d625284.tsv (row A123); harness-repair-plan/prompts/P1b.md
- Location: TSV A123; P1b.md E3 (P1b.md:232-234, 'name neither command nor the push-, merge- and pull-analysts: those analysts' artifacts get no answer ... take the fallback'); Scope row 12 (P1b.md:468, 'the pull-analyst grant if the regenerated map confirms no consumer')
- Claim: A123 lists a 'Pull-analyst grant' at /tmp/agentic-commit/pull-analyst/... produced by agent:pull-analyst and 'written never read'. E3 sends the pull-analyst's artifacts to the fallback, which declares them in its dispatch template.
- Evidence: agents/pull-analyst.md:33 says 'Never write any grant token — pull-analyst is purely advisory; no token is written, ever'. :34 says 'Never write any file — this agent has no Write tool access; all output goes to stdout only', and :158 says 'No files written'. The path appears only in the other analysts' 'never write grants for other agents' rules (merge-analyst.md:34, push-analyst.md:33), which is where A123 took it ('named in'). There is no artifact. E3's fallback would make the implementer declare a non-existent artifact in a read-only agent's dispatch. The README count 'written never read 29' includes this row.
- Proposed fix: Delete TSV row A123 and move it to README 'Excluded' as "A123 (`/tmp/agentic-commit/pull-analyst/...`: named only in merge-analyst.md:34 and push-analyst.md:33's prohibitions; pull-analyst writes no file, agents/pull-analyst.md:33-34, :158)". Decrement 'written never read' to 28 and the row count to 121. In P1b E3, replace "the push-, merge- and pull-analysts: those analysts' artifacts" with "the push- and merge-analysts (the pull-analyst writes no file): those analysts' artifacts". In row 12, delete "; the pull-analyst grant if the regenerated map confirms no consumer".


### facts-F9 [medium] harness-repair-plan/prompts/P1b.md
- Location: E5, candidates and experiment (P1b.md:261-268)
- Claim: Candidate (a), 'the lane-completeness hook when the last lane report lands', is an existing producer of the canonical aggregate (posttool-lane-completeness-watch.py:216-220), and the experiment compares replays 'with only (a), then with only (b)'.
- Evidence: posttool-lane-completeness-watch.py:90-91 resolves project_dir as CLAUDE_PROJECT_DIR or cwd. :216-218 runs `Path(project_dir) / "scripts" / "aggregate-dev-report.py"` and returns silently when it does not exist. That script exists only in the harness repository, not in a product repository such as the kit's toyproj. In every product-repo replay, (a) never writes the canonical, so the decision rule picks (b) because of a path defect, not on the merits. dev.md:885 and close.md:338 have the same repo-relative path (P1c row 18 lists them as 'Repo-relative script paths a product repo does not have').
- Proposed fix: After "and by hooks/posttool-lane-completeness-watch.py:216-220 itself." add: "At d625284 the hook resolves the aggregator under CLAUDE_PROJECT_DIR (:91, :216-218) and returns when it is absent, which it is in every product repository, so (a) produces nothing there. Before the experiment, resolve the script from the harness home (the hook's own `Path(__file__).resolve().parent.parent / 'scripts'`, as prompt-workflow.py:1576 does), or record that (a) was unreachable and why."


### facts-F10 [medium] harness-repair-plan/prompts/P1b.md (also TSV row A109)
- Location: Scope row 17 'Deleted' (P1b.md:473, 'doc-sync notices (`/var/tmp/claude-scratch/<sid>/doc-sync-notices-agent-<hex>.json`, deleted unread at SessionEnd)'); 'Rules retired' list ('doc-sync notices'); TSV A109
- Claim: The doc-sync notices file is written and never read, and is deleted at its producer.
- Evidence: hooks/doc_sync/notice.py:469-470 (`state_path = state_path_for(payload)`; `state = read_state(state_path)`) reads the file back, and :511 (`write_state`) writes it: it is the per-audience dedupe state ('Notices for skipped regeneration: text, per-audience dedupe state', notice.py:2). By README.md:76-78's own definition, a writer that reads its file back to decide later (a cache or throttle) counts as a consumer. Deleting it makes doc-sync repeat every notice on every PostToolUse.
- Proposed fix: In row 17, replace "doc-sync notices (`/var/tmp/claude-scratch/<sid>/doc-sync-notices-agent-<hex>.json`, deleted unread at SessionEnd);" with "doc-sync's notice dedupe state (`doc-sync-notices-<audience>.json`) stays while doc-sync emits notices (notice.py:469-470 reads it back, a cache); it goes only if E9 removes every notice source;". Remove 'doc-sync notices' from 'Retired'. In TSV A109, set readers to 'hooks/doc_sync/notice.py:469-470 (self, dedupe){c}' and violations to 'none in D24 terms (dedupe state read by its writer)'.


### facts-F12 [medium] harness-repair-plan/prompts/P1b.md (also TSV row A112)
- Location: Scope row 17 'Deleted' (P1b.md:473, 'the spec-update temp notes (`update-<rand>.md`, written and never read; ...)'); 'Rules retired' ('the spec-update temp note')
- Claim: The spec-update temp note is written and never read, and is deleted outright.
- Evidence: commands/spec-update.md:113-130: `/spec-update --temp` is a user-invoked mode whose note carries a '## Resume prompt' of '3-8 sentences the next agent can paste/read to resume' plus an artifact map. People read it, so no code reader is expected. Deleting it removes a mode of a published command (Principle 6: no feature retirement), and it skips P1b's own E12 rule, which decides owner-read files by whether a command's output names the path.
- Proposed fix: In row 17, replace "the spec-update temp notes (`update-<rand>.md`, written and never read; spec-update.md's mktemp-then-Write sequence is also refused by pretool-write-guard.sh);" with "the spec-update temp note (`update-<rand>.md`, read by people: spec-update.md:113-130) goes through E12's owner-read test like the other logs. Its mktemp-then-Write sequence, which pretool-write-guard.sh refuses, is fixed in the prose (P1c row 18);". Remove 'the spec-update temp note' from 'Retired' unless E12 deletes it.


### facts-F13 [medium] harness-repair-plan/prompts/P1c.md
- Location: X9 (P1c.md:357-361, 'No record of this defect exists in the repository or the planning branch'); The suite (4) R-V1 (P1c.md:544-546); R-N1 before-tree (P1c.md:542-543)
- Claim: No record of N1 or V1-1/NV-1 exists 'in the repository or the planning branch', so both must be reproduced from a description, with 'before' trees at f8c18c2.
- Evidence: P1c starts only after P7b merges. P7b at 760f06e carries both as named review findings, with fixes: scripts/install/land:17 ('a CLI write left stat-dirty gets its index stat re-recorded (review N1)') and :190-201 ('Review N1: ... `git pull --rebase` refused'), plus commit 921b512 'P7b (R2, R9): every repair git refused is named and logged apart (NV-1)'. P7b's PR body (p7b/PR-BODY.md:205, :227) defines N1 as '/pull exited 1 (cannot pull with rebase: You have unstaged changes) and fswatch's safe_pull returned 0 without pulling' and V1-1 as a repair the landing refused under a git lock with no notice. The greps P1c quotes are true only at d625284 and dac09ec9, not on P1c's base.
- Proposed fix: In X9, replace "No record of this defect exists in the repository or the planning branch: ... finds nothing. Reproduce it from its description:" with "N1, NF-1, V1-1 and NV-1 are P7b review findings. Their definitions and reproductions are in P7b's merged PR body (rows N1, NF-1, V1-1, NV-1) and its commits (scripts/install/land:17, :190-201 at 760f06e; 921b512). Reproduce each from there:". Make the 'before' trees P7b's pre-fix heads named in that PR (not only f8c18c2). In R-V1, replace "no record with these ids exists in the repository or the planning branch (...), so reproduce from the description" with "take V1-1 and NV-1 from P7b's PR body; R-V1 adds /commit's shared-index sync (F4c) as the second repair path under a held lock".


### feasible-M1 [medium] harness-repair-plan/prompts/P1b.md
- Location: Acceptance 8 (:548-549) against row 1 (:457, "the regex copies (subagentstop-artifact-contract-enforce.py:220-232 ...") and row 6 (:462, "the legacy correlation path only for a dispatch without an obligation")
- Claim: Acceptance 8 contradicts rows 1 and 6. It requires `session_ts` to disappear from every hook. Row 6 keeps the legacy correlation path, which is built on session_ts. No row names the e2e gate's session_ts branches, and no row says what replaces the legacy correlation once its regex goes.
- Evidence: `git grep -nE 'session_ts|TASK_ID_REF_PATTERNS' d625284 -- hooks scripts commands ':!hooks/tests'` gives 18 lines: subagentstop-e2e-enforce.py :77-148 (8 lines, the session_ts filename and content match), subagentstop-artifact-contract-enforce.py :209-234 (the legacy `_find_correlated_reports`), and pretool-aggregate-check.py :95-226. P1b row 3 changes only the obligation-bearing QA path of the e2e gate. The replacement for dispatches without an obligation (judge only reports the stopping agent wrote, read from its own transcript's Write/Edit tool uses) is described only in P1c rows 8 and 10.
- Proposed fix: Row 6, column 3: replace "(the obligation path; the legacy correlation path only for a dispatch without an obligation)" with "(the obligation path; for a dispatch without an obligation, only the reports the stopping agent wrote itself, read from its own transcript's Write and Edit tool uses, never a sibling's)".
Row 3, Moves column: append "; without an obligation, only a qa-report the stopping QA wrote itself (subagentstop-e2e-enforce.py :103-148's session_ts branches go)".
In P1c.md rows 8 and 10 add "(delivered by P1b: replay and unit test only)".


### feasible-M2 [medium] harness-repair-plan/prompts/P1b.md
- Location: Acceptance 5 (:538-541), E4 decision rule (:252-256), acceptance 14 (:568-570), row 7 (:463)
- Claim: Acceptance 5 requires every stale-artifact fault to pass armed on P1b's branch. The stale v1 qa-report dead end comes from the resolver's fan-out optional-parent read, not from any check P1b deletes, so E4's rule ("move the deleted check's rule") cannot fix it, and acceptance 14 meanwhile lets base dead ends pass to P1c.
- Evidence: P1c.md:87 (F3b), armed column "same": the Step 17 resolver fails on the stale unsuffixed file; `rm` is refused; QA and the orchestrator may not write it. P1c.md:410 (row 12) removes the resolver's fan-out optional-parent branch (read-never-written: no dispatch declares the unsuffixed parents). No P1b row touches that branch, but E4's fault set includes "a stale earlier-version artifact beside the new one".
- Proposed fix: Add to row 7's Deleted column: "the resolver's fan-out optional-parent read (resolve-dev-artifact-chain.py; commands/dev.md :1338-1344 and dev-command.md's copy): no dispatch declares the unsuffixed parent ticket, context or qa-report in a fan-out cycle, so it is read-never-written (D24); singular cycles unchanged".
In P1c.md row 12 add "(delivered by P1b: replay only)".
Alternatively, append to acceptance 5: "except a fault that ends in a dead end also present on the base and on lines no row of yours touches; list it under acceptance 14 for P1c".


### feasible-M3 [medium] harness-repair-plan/prompts/P1b.md
- Location: Branch and pull request (:659-665), row 0 (:456 "Put the regenerated map (before) and the after-map ... in the PR"), acceptance 6 (:542-544); P1c.md:724-740
- Claim: The PR body P1b requires cannot be posted: GitHub caps a PR body at 65,536 characters, and the required content is several times that. The before and after maps alone are each around the size of the 79 KB planning TSV.
- Evidence: `wc -c inventory/artifact-map-d625284.tsv` gives 79,334 bytes for 122 rows. Its four key columns alone are 26,717 bytes. P1b requires in the body: both maps ("Inventory"), a D24 row per artifact, "setup, raw output and option taken" for E1-E14, and "paste the command and its output" for all 20 acceptance tests. P1c adds four tables over 16x2 scenarios and 17x2 faults, the X6 site counts per hook, and X1-X10 raw results.
- Proposed fix: In both prompts' "Branch and pull request", add: "The PR body stays under GitHub's 65,536-character limit. It carries the summary tables (counts per invariant before and after, one line per experiment with the option taken, one pass line per acceptance test). The full maps, the D24 table and the raw outputs are written by the check and the suite to their CI job's uploaded artifact, and posted as PR comments where a reviewer must read them inline; each body heading links its comment or the run."
In row 0 replace "in the PR, never in the repository" with "in the check's CI artifact and a PR comment, never in the repository".


### feasible-M4 [medium] harness-repair-plan/prompts/P1b.md
- Location: E12 decision rule (:348-351), row 16 (:472, "P7b's `logs/landing.log` write ... E12: unless a command output names it), keeping the notice line")
- Claim: E12 counts a file as read by the owner only if a command file names it. The landing's own notice, which reaches the owner's session, points him at logs/landing.log, so E12 would delete that log while row 16 keeps the notice that points to it.
- Evidence: At 760f06e scripts/install/land prints "... (see logs/landing.log); it runs again at the next turn end" at :230 and :239, the same at :247, and "... see logs/landing.log." at :249. Each line is the session notice the Stop relays. The P7b fixes for V1-1/NV-1 (96bcb8f, 921b512) make that log record `result=repair-refused`. E12 says "the CI check derives this from the command files at test time", and the landing is not a command file.
- Proposed fix: E12: replace "a file counts as read by the owner only if a command's own output tells him its path (the command text prints or links it, as dev-overnight.md's final summary does); the CI check derives this from the command files at test time" with "a file counts as read by the owner only if an output that reaches him names its path: a command's text, or a string a hook or script emits as its session notice or systemMessage; the CI check derives both at test time (commands/*.md, and literals passed to the notice channel)".
Row 16: delete "P7b's `logs/landing.log` write (read by no code, render-settings :1193 in the reviewer's P7b copy; E12: unless a command output names it), keeping the notice line;".


### feasible-M5 [medium] harness-repair-plan/prompts/P1c.md
- Location: X8 option (A) (:340-350) and rule (:353-355); DO NOT (:757-759)
- Claim: X8 (A) cannot legally be taken: it widens a denial that CLAUDE.md states as a written rule, which P1c's own DO NOT forbids. X8's rule also gives no outcome when neither the documentation nor a capture settles the platform fact, which the prompt itself says is UNVERIFIED.
- Evidence: CLAUDE.md's Orchestrator-Only Rule: "The sole `SendMessage` exception is the supported human-only `/restart` path". Lesson 16: "the human-only `/restart` command must ...". P1c.md:757-759: "Do not weaken a security denial to make a replay pass ... A hook changes only under X4 (b), a refusal no written rule backs". X8 (A) widens hooks/pretool-block-background-tasks.py :157-161 to "the overnight session's own wake". X8's rule allows (A) only on a "documented or captured record shape" and (B) only if documentation or a capture "shows that a scheduled prompt cannot fire there", while :335-337 says those facts are UNVERIFIED.
- Proposed fix: Append to X8 (A): "This widening is decided under D20 and T0 (owner, 2026-10-22/23), which rank above CLAUDE.md's 'The sole SendMessage exception is the supported human-only /restart path' and Lesson 16's 'human-only /restart'. The DO NOT on weakening security denials does not apply to this one exception, and the PR lists both CLAUDE.md sentences under the sync-list hand-offs for P9."
Append to X8's rule: "If neither the documentation nor P1's capture settles whether a scheduled prompt fires after a usage-limit end, run (A)'s replay with the scheduled-prompt record shape P1 captured for CronCreate or ScheduleWakeup in any session; take (A) if that drives the replay to a completed cycle with 0 blocks, otherwise (B), recording the fact as UNVERIFIED for P5."


### feasible-M6 [medium] harness-repair-plan/prompts/P1c.md
- Location: X6 (:291-315), class G (:299), rule (:309-311); DO NOT last bullet (:768)
- Claim: X6 cannot prove requirement (3) as written:
- it has no rule for when the enumerator's recall falls short of 100%;
- class G accepts any next action a hook permits, even one a written rule forbids, so F5's known dead end would pass;
- the dead-end sites X6 orders fixed before merge may sit in code the DO NOT forbids P1c to touch.
- Evidence: X6's rule: "adopt the method if ... recall 100%", with no else branch. F5 (P1c.md:90): Gate 4 refuses the dev step after a /restart resume unless a new dev Agent call is made. That call is one every hook allows, so a per-site replay classes the site G, although CLAUDE.md Lesson 16 forbids it. X6 :310-311: "A site that fits no class is a dead end and becomes a scope row fixed at its producer before merge." DO NOT :768: "Do not change resolver, aggregator or overnight-loop code beyond rows 11, 12 and 19."
- Proposed fix: Replace X6's "Rule fixed: adopt the method if, on your base, the enumerator finds the site of every block the pilot observed ... recall 100%)." with "Rule fixed: the method is required; if on your base the enumerator misses the site of a block the pilot observed, extend it (helper functions that exit 2 or print a deny, non-literal exit codes) until recall is 100%."
In class G append: "the clearing action must be allowed by every registered hook and by every written rule (CLAUDE.md, the command and agent prose); a site whose only clearing action a written rule forbids (Gate 4 after a /restart resume: a replacement Agent call, Lesson 16) is a dead end."
In the last DO NOT bullet append: "except a U or dead-end site X6 finds there".


### feasible-M7 [medium] harness-repair-plan/prompts/P1c.md
- Location: X2 (:234-235, "the harness copy from `git archive HEAD` of your checkout, no worktree"; :243-246, the writes outside tmp_path)
- Claim: X2's fixture builds the harness home with `git archive`, which gives a directory that is not a git repository. Checkpoints, P7b's landing, /pull (R-N1) and acceptance 11's harness-home Stop all run git in that home. The fixture also tolerates fixed /tmp writes that P1b's path rule removes, so a regression of that rule would not be caught.
- Evidence: R-N1 (:542) runs hooks/pull.sh and safe_pull on the home. R-V1 (:547-550) runs the landing on a busy harness home. Acceptance 11 (:643) runs "one in the harness home". F4 (:526) asserts "the checkpoint ref advances". The landing refuses a clone made at a filter revision and reads `git rev-parse --git-path claude-settings.applied` (land:31 at 760f06e). The kit's sb-setup.sh keeps .git and commits a snapshot for this reason. X2 :244 allows writes outside tmp_path for "the fixed `/tmp` paths some hooks still use: ledger L29, L42, L43", which P1b's acceptance 9 removes.
- Proposed fix: Replace "`tmp_path/home/.claude` (CLAUDE_CONFIG_DIR; the harness copy from `git archive HEAD` of your checkout, no worktree)" with "`tmp_path/home/.claude` (CLAUDE_CONFIG_DIR): a clone of your checkout's HEAD with a local bare origin (so pull, checkpoint and landing run against a real repository), set up with the init steps P7b's landing expects; no worktree".
Replace "writes outside tmp_path only paths that carry the scenario's own session id (the fixed `/tmp` paths some hooks still use: ledger L29, L42, L43)" with "writes nothing outside tmp_path (P1b's path rule moved the fixed /tmp state paths; any such write is a defect at its writer, fixed here and listed in the D24 table)".


### feasible-M8 [medium] harness-repair-plan/prompts/P1b.md
- Location: Effort (:630 "Effort: XL (about 7 days)"), Scope table (:454-476), Corrections item 2 (:391-404), Rollback (:645-650)
- Claim: Even after B1 and H1-H3 are fixed, P1b is beyond one reviewable PR from one session. It holds about 213 file:line sites in about 120 files, 14 experiments, ten new pipeline drivers, and work taken from P2, P3, P4, P5, P9 and P10. P1c's X6 corpus is open-ended in the same way.
- Evidence: The scope rows cite 213 file:line locations across 120 distinct files (grep over :456-476). The pilot's drivers are unpublished (P1c.md:63-64; inventory/README.md "How it was produced": workflow scratch only), so P1b builds all ten from the kit's 717 lines. Correction 2 moves work from P2, P3, P4, P5, P9 and P10. Effort estimates in the reviewer's copies: P3 L about 3 d, P4 L 3.5 d, P5 L 5 d (and P5 is split into P5-a to P5-d). The zero-exception check can only land after every deletion. X6 (P1c.md:312-315) expects a per-site replay for 136-442 block-like lines in 31-44 hook files.
- Proposed fix: Split P1b into two PRs, with the check over the real tree landing last:
P1b-1 (wave 2b): row 0; row 19's runner, drivers and derivation, committed with tests that assert only determinism, that each pipeline reaches its terminal or a listed base block, and acceptance 3's mutation detections on scratch copies; Corrections 4-5; Rollback commits (1)-(2).
P1b-2 (wave 2b'): Rollback commits (3)-(5), plus the test that runs the check's invariants over the real tree with zero exceptions; the cap of <= -1200 is counted over both PRs.
P1c starts after P1b-2.
In P1c, set Effort to say X6's per-site corpus is the largest item, and give it its own commit group (Rollback step 4 already does).


### format-FH-3 [medium] harness-repair-plan/prompts/P1c.md
- Location: :44-46 (Interfaces you consume, P1b bullet); X1 :222-225; row 1 :399
- Claim: P1b hands P1c the runner and ten compliant drivers, but P1c builds a second scenario library. The result is two driver sets that model the same command text. The merge rule makes later phases "update that pipeline's scenarios" (:563), so one set drifts or every phase edits both.
- Evidence: - P1b :59-61 and :475 ship the trace runner and "the ten compliant drivers ... so P1c can add faults to them" under tests/, in every E1 outcome (acceptance 4).
- P1c :44-46 lists only P1b's trace runner, its D24 table format and its E1 choice, not the drivers.
- X1 :223-225: "If P1b chose static derivation only, ship the runner under tests/replay/". That case cannot happen, because P1b always ships the runner.
- Row 1 :399: "One scenario library builds every pipeline ... This phase commits its scenario drivers as test code: the one exception to P1's 'do not commit scenario drivers'". That is false once P1b has committed its drivers (P1b DO NOT :692).
- Proposed fix: (1) :44 replace "- P1b: its trace runner (the committed module that replays a pipeline in T1 order and records which actor wrote, read, probed or deleted which path), its D24 table format," with "- P1b: its trace runner (the committed module that replays a pipeline in T1 order and records which actor wrote, read, probed or deleted which path) and its ten compliant pipeline drivers (P1b acceptance 4; you extend them, never a second set), its D24 table format,"
(2) :222-225 replace "If P1b ships a runtime trace runner, import it and add only the scenario library, the assertions and the fixture (rows 1-5). If P1b chose static derivation only, ship the runner under tests/replay/, ported from the planning kit (baseline.py's Session, ev and tool; runhook.py) and the pilot design:" with "P1b ships the runner and the ten drivers whatever its E1 decided. Import both and add only the missing scenarios, the fault injection, the assertions and the fixture (rows 1-5). A piece the runner lacks goes into P1b's module, ported from the planning kit (baseline.py's Session, ev and tool; runhook.py) and the pilot design:"
(3) In row 1 :399, replace "One scenario library builds every pipeline" with "P1b's drivers, extended to the 16 scenarios, build every pipeline", and delete "This phase commits its scenario drivers as test code: the one exception to P1's \"do not commit scenario drivers\"."


### format-FH-4 [medium] harness-repair-plan/prompts/P1b.md
- Location: "Branch and pull request" :656-658 (and P1c.md :721-723); shared tail P1b.md:765, P1c.md:840
- Claim: Neither prompt states the commit format or the standard trailers, which the reviewer's item (d) requires. The only rule both carry is the shared "Do not put model identifiers in commits or the PR", which contradicts the attribution trailer every merged phase commit has. The session must either drop or edit the trailer its system prompt gives (prompt instructions about these lines take precedence over that reminder) or break the literal DO NOT. Either way its commits may differ from the P1 and P8 form.
- Evidence: - origin/master 3a18cb18, 7ef1835b and b9699dc5 (P1), and origin/repair/P8 0d266922 and d1b644f4, each have the subject "P1: …" or "P8: …" and end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" and "Claude-Session: …".
- Grepping P1b.md, P1c.md, the sync file and the p23 prompts for trailer, Co-Authored and Claude-Session finds no rule for phase commits.
- Proposed fix: In P1b.md after :658 ("  branch. One branch, one pull request to `master`.") insert:
"- Commits: subject `P1b: <what changed>`, a body that says why and what you ran, and, last, the attribution trailer lines your session's system prompt gives (Co-Authored-By, Claude-Session), unchanged. Those trailer lines are the only place a model name may appear; everywhere else \"Do not put model identifiers in commits or the PR\" holds."
Insert the same bullet in P1c.md after :723 with `P1c: <what changed>`.


### format-FH-5 [medium] harness-repair-plan/reviews/P1b-plan-sync.md
- Location: V-5 (:120-130), V-8 (:157-166), P3-4 (:993-1002), P6-5, P9-5 (:1365-1380), P9-8; "How to apply" :27-30; "Counts" :1617-1620
- Claim: The reviewer applies the sync list on top of the p23 tree, but 6 of its 101 anchors are not found there. The file says only P9-5 would move. Two of the replacement texts would also undo p23 corrections if applied with the file's "find it by its words" fallback.
- Evidence: anchors.py (in p1b-review/notes) finds 101 of 101 anchors exactly once at dac09ec9, and 95 of 101 in p23. The 6 misses are V-5, V-8, P3-4, P6-5, P9-5 and P9-8. Two replacement texts regress p23:
- V-8's new text (:165) is "**Wave 9: P11 (human-run, last).** ...", while p23 PLAN-v2.md:178 reads "**Wave 9: P11 (last).**" (P11 is reviewer-run, D19; p23:139 "S (reviewer)").
- P9-5's new text says "five include files under templates/prompt-includes/" and drops p23 P9.md:109-110 "(four if E4 drops the Checkpoint Marking Contract)".
- Proposed fix: Swap in these p23 anchors; each was checked to occur exactly once:
- V-5: "| P11 | History rewrite, remote ref deletion, GitHub purge, pre-push guard (last) | 9 | every phase PR | S (reviewer) | 0 |"
- V-8 anchor: "**Wave 9: P11 (last).** Must be merged first: every phase PR,"; new text: "**Wave 9: P11 (last).** Must be merged first: every phase PR (P7b, P1b and P1c included; the P1c replay suite green on master),"
- P3-4 anchor: "- Dependencies: start only after P1, P8 and P7b are merged" (new text unchanged).
- P6-5 anchor: "    deleted) <= +100, or the cap as raised by the measured amount under correction 1."
- P9-5 anchor: p23 P9.md:107-110 ("... the agent roster (one function over the agent files), the git global-option table (one table and a normaliser), and the shared prompt blocks (five include files (four if E4 drops the Checkpoint Marking Contract) under templates/prompt-includes/)."); in the new text keep "(four if E4 drops the Checkpoint Marking Contract)".
- P9-8 anchor: "#5 rewritten: one terminal, complete; a producer question is relayed in-turn (outside /dev-overnight; inside it the question is decided without the owner and recorded, D20); the cycle stays incomplete and the same role resumes after the answer (D2, D3); Lesson 16's wording stays consistent with it."
Then change "How to apply" and "Counts" to say the anchors are verified against p23, and run the "Verification" script there.


### format-FH-6 [medium] harness-repair-plan/prompts/P1b.md
- Location: P1b.md:161-164 and :13-14; P1c.md:138-143; P1b-plan-sync.md D-1 (:510-530), H-10 (:675), V-1, V-31 (:444-448), "Decision id" :31-32
- Claim: The never-fail rule appears under two names ("the owner's rule of 2026-10-24" in P1b and P1c, D25 in P2-P11 after the sync). Its quote is cut without the "…" mark DECISIONS.md uses for elisions. P1b cites a source the implementer cannot open. P1c says the suite design came from the owner, though the quoted words contain none of it.
- Evidence: - The owner's message, per the task, begins "还有一件我关心的！就是永远不能失败！…". That opening ("one more thing I care about") is the basis for "ranks with D24". Every copy that calls itself verbatim (P1b:161, P1c:138, sync D-1, V-1, V-31, H-10 "原话") starts at 永远 with no "…".
- P1b:161 says "(relayed in this workflow's task; P1c's)". No planning document has that task, and register.md and report-zh.md have no 2026-10-24 row.
- P1c:141 says "He asked for it as a CI replay suite that reuses the runtime trace, with parts (1)-(4) ...". D-1 puts the same design under the owner-ruling heading as "The same request asked ..." with no [INFERRED] or reviewer marker, unlike D20 and D21.
- P1b's English rendering differs from P1c's and the sync's.
- Proposed fix: (1) P1b.md:161-163 replace "- **The owner's rule of 2026-10-24** (relayed in this workflow's task; P1c's): \"永远不能失败！每一次开发一定不会在流程上\n  出现任何错误！出现了错误也可以立刻被修复！\" (\"It must never fail. No development run may hit any process error, and an\n  error that does occur must be repairable at once.\")" with "- **D25 Never fail** (owner, 2026-10-24; DECISIONS.md D25): \"还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！\" (\"One more thing I care about: it must never fail! No development run may ever hit an error in the process! And if an error does occur, it can be fixed at once!\")". At :13 replace "the owner's rule of 2026-10-24" with "D25".
(2) P1c.md:138-141: same heading and quote. Replace "He asked for it as a CI replay suite that reuses the runtime trace, with parts (1)-(4) of the Goal, with every later phase merging only with it green and adding the fault replay for the process it changes." with "The suite's parts (1)-(4) and the merge rule come from the request that relayed it (DECISIONS.md D25 marks which words are the owner's)."
(3) Sync D-1, V-1, V-31 and H-10: quote from "还有一件我关心的！就是". In D-1, wrap "The same request asked for it as a CI replay suite ... 故障回放\" [...]" in "[Reviewer's request, no owner words: ...]", unless the reviewer has the owner's own words for the design. Delete the "both names mean the same ruling" sentence at :31-32.


### owner-R5 [medium] harness-repair-plan/prompts/P1c.md
- Location: P1c :138-143; P1b.md :161-163; reviews/P1b-plan-sync.md :36-38, :83 (V-1), :510-524 (D-1), :762
- Claim: Reviewer proposals are written as the owner's words: the ranking 'as important as / ranks with D24', the CI replay suite with parts (1)-(4), and the merge rule. The draft D25 would give them the rank of an owner decision in DECISIONS.md.
- Evidence: The owner's only message (reviewer transcript, record 2593, 2026-10-24T10:45:36Z) is exactly '还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！'. 'Same importance as one producer, one consumer' ('和"一生产者一消费者"同等重要'), the four testable criteria, the CI suite and the line '之后每个阶段合并的条件之一是这套测试保持全绿…' all come from the reviewer's reply (record 2603, 10:46:39Z), which the owner forwarded. Yet P1c :141 says 'He asked for it as a CI replay suite …', P1b :163 says 'The owner ranks it with …', and sync D-1 says 'He ranks it with D24. The same request asked for it as a CI replay suite …'. All of them also drop the opening '还有一件我关心的！就是'.
- Proposed fix: In all three files, quote the full sentence '还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！' with its source (owner to the reviewing session, 2026-10-24T10:45:36Z). Delete 'The owner ranks it with …' (P1b :163), '(latest; as important as one producer and one consumer, D24)' (P1c :138 -> '(latest)'), 'He ranks it with D24.' and the heading '(latest; ranks with D24)' (sync :510, :512), and 'as important as D24' (sync :83, :762). Replace 'He asked for it as a CI replay suite …' (P1c :141-143) and 'The same request asked for it as …' (sync D-1) with '[INFERRED: the reviewer's proposal of 2026-10-24T10:46:39Z, forwarded by the owner: a CI replay suite with parts (1)-(4) and a merge rule for later phases; not owner words.]'


### owner-R6 [medium] harness-repair-plan/prompts/P1b.md
- Location: Scope row 1 (:457), Deleted column: 'they become "re-run the command"'
- Claim: Replacing the orchestrator's fallback mint with 're-run the command' turns a process fault (hook output missing from context, e.g. after a resume or compaction) into a step for the human.
- Evidence: dev.md :196 at d625284: 'Fallback (if hook output is absent — e.g., session resumed without re-running the command)'. P1b row 1: 'The orchestrator fallback mint and fallback blocks (commands/dev.md:196-218, dev-command.md:142-160: they become "re-run the command")'. The id and registry already exist on disk and in the transcript, so a re-type is not needed. Against D19 ('我不做，没空'), C5 (no new human-in-the-loop step) and D25.
- Proposed fix: Replace 'they become "re-run the command"' with 'they become: read the id the mint already recorded (the UserPromptSubmit hook output in the transcript, else the registry sentinel through obligation.registry_dir_for / canonical_task_id); never mint, never ask the human to retype'. Add to acceptance 4: 'a /dev whose hook output is no longer in context (after a compaction) continues with the recorded id, 0 human events'.


### owner-R7 [medium] harness-repair-plan/prompts/P1b.md
- Location: Scope row 16 (:472) 'harness writers report suggested permissions instead of writing'; row 7 '(permissions are reported, not written)'
- Claim: Switching the QA-validated permission write to 'report suggested permissions' gives the owner a manual settings step, or lets later unattended cycles hit permission prompts. It also retires a feature.
- Evidence: dev-overnight.md Step 18 (:1510-1519 at d625284) aggregates the QA-validated permissions of all pipelines and applies them with scripts/apply-permissions.sh, so the next cycle does not stall. Row 16 deletes the write in favour of a report. The plan's D19 forbids owner machine steps; D20 overnight is unattended; principle 6 (_common) 'No feature retirement'.
- Proposed fix: Replace row 16's 'harness writers report suggested permissions instead of writing' and the Deleted text '…: both report suggested permissions' with: 'one harness writer stays, scripts/apply-permissions.sh (the single function /dev and /dev-overnight both call); the orchestrator's jq edit (dev.md:1081-1110) goes (D8). Decided by experiment: replay overnight cycle 2 and a second /dev in the same product with and without the write; if no prompt or denial differs, the write goes too; "report" is never an option (D19, D20).' In row 7, delete '(permissions are reported, not written)'.


### owner-R8 [medium] harness-repair-plan/prompts/P1b.md
- Location: Acceptance 17 (:575-581): 'Expected: no hook exits 2 except a block your rows make correct (name each)'
- Claim: The live-landing acceptance allows new blocks on an in-flight compliant cycle. That is a process error in a live development run, and it is weaker than P1c's equivalent acceptance.
- Evidence: D15: live sessions keep their hook list and the base's command text. D25 says no process error in any development run. C5 says legitimate output always keeps a route. P1c acceptance 11 requires 'no hook exits 2 on a compliant stop' for the same kind of in-flight cycle.
- Proposed fix: Replace 'Expected: no hook exits 2 except a block your rows make correct (name each)' with 'Expected: no hook exits 2 on any event of the compliant in-flight cycle (D15, D25); a row that would block one is changed until it does not'.


### owner-R9 [medium] harness-repair-plan/prompts/P1b.md
- Location: Acceptance 4 (:531-541); E13 decision rule; Out of scope (the /dev-overnight time-lock, window and landing are P2's); DO NOT 'Do not change a hook to suit a replay driver'
- Claim: Acceptance 4 requires 0 blocks on all ten pipelines, but the refusals that block a literal compliant replay (/dev-overnight cycles, /merge, /dev-command, close.md Step 0) are P1c rows 18-19 and P2 work. As written, the implementation session must either expand into P1c/P2 or let drivers deviate. The runtime-derived D24 check then misses the overnight artifacts after the first dispatch.
- Evidence: P1c :466-472 (row 19): census_fatal on dev-overnight.md Step 1, OVERNIGHT MAIN-ROOT BLOCK, OVERNIGHT SUBPROCESS GIT BLOCK, WRITE-BOUNDARY FAIL-CLOSED without bwrap, CLOSEOUT GATE and the cycle-id disagreement (P2 row 12). P1c row 18 lists merge.sh's untracked-file refusal, the config guard on /dev-command, and close.md :337/:507. P1b E13 only requires '0 blocks from the contract and state hooks'. Pilot trace B had 9 refusals on its compliant replay.
- Proposed fix: In acceptance 4, replace 'Expected: 0 blocks from any hook …' with 'Drivers follow the command text literally (P1c X4's definition). Expected: 0 hook errors, and no block except the refusals P1c rows 18-19 list, each printed with its hook text, re-verified on your base and handed to P1c under "Hand-off to P1c". For relation derivation only, each refused pipeline continues past the refusal in a what-if run whose deviations are marked, so the D24 check derives the artifacts of every later step (overnight cycles 1-2 included).'


### owner-R10 [medium] harness-repair-plan/prompts/P1b.md
- Location: Goal 3 (:72-75); Scope row 19 (:475); acceptance 13; Corrections item 6 (G4)
- Claim: The allowed positions the zero-exception CI check enforces are only the producer stop, G1 and G3. Two deciding positions the plan keeps are missing: the single call of the chain function at /dev's end, /close and /commit (row 7, ruling 1 class a), and the command's Stop gate (SG1/D4; G4 now, P5's unified gate later). The check therefore fails on P1b's own design and on P5, unless someone adds an exception.
- Evidence: Goal 3: 'Every re-check and re-derivation elsewhere goes: in /close and /commit, in scripts consumers run, in other hooks'. Row 7 keeps '/dev's end, /close and /commit each call the one chain function once'. Owner SG1 (O20): 'do dev … push这些全部加入stop gate，在没有跑完todo list以及没有完成相关artifact之前是不允许stop的'. Acceptance 13 requires 'deciding checks outside the allowed positions … 0 on your branch'. Row 19 forbids exception lists.
- Proposed fix: Rewrite goal 3's last two sentences as: 'Allowed deciding positions: the producer's own stop (G2), G1 at dispatch, G3 at collection, the command's Stop gate (SG1, D4: G4 now, P5's unified gate later), and the single call of the one chain function at /dev's end, /close and /commit (ruling 1, class a). Every other deciding read is a re-check and goes. G1-G3 and the Stop position stay; P2 still arms G1-G3.' Add to row 19: 'the check derives each position from settings.json's event and matcher and from call sites of the one chain function, never from a list of hook names'.


### owner-R11 [medium] harness-repair-plan/prompts/P1b.md
- Location: E3 :233 '(which then extends both sets)', :241 'prefixes for undeclared paths stay until P5'; Scope row 18 (:474) 'obligation.ROLES stays the producer subset'
- Claim: P1b keeps, and lets E3 extend, hand-written role and pipeline lists that code reads, while promising a check with zero exceptions that fails on 'a hand-written … role list in a hook'. It also keeps tool-policy prefixes that name file paths for roles. Each of these needs either an exception or a contradiction.
- Evidence: obligation.py :74-83 at d625284: ROLES and PIPELINES frozensets. Row 18 deletes 'command lists (obligation.py:81-83 …)' (that is PIPELINES), while E3's fallback 'extends both sets'. Row 18 keeps ROLES 'tested as a subset'. Acceptance 3 mutation: 'a hand-written filename-to-role mapping or role list in a hook' must fail the check. Row 19: 'no exception list'. D21: no file-name-to-role table in code. policies/tool-policy.v1.json (24 roles, 261 prefixes) stays partly until P5.
- Proposed fix: E3 :233: replace '(which then extends both sets)' with '(their dispatch templates gain an obligation whose role validates against the roster function and whose pipeline validates against the commands/*.md stems)'. Row 18: replace 'obligation.ROLES stays the producer subset, tested as a subset' with 'obligation.ROLES and PIPELINES go; parse_obligation validates role against the roster function (agents/*.md stems) and pipeline against the commands/*.md stems'. E3 :241: after 'prefixes for undeclared paths stay until P5' add '; the CI check asserts that no remaining prefix names a path of any artifact it derived, with no exception for policies/tool-policy.v1.json'.


### owner-R12 [medium] harness-repair-plan/prompts/P1c.md
- Location: X8 option (B) :350-352 and rule :354-355; faults assertion :525 (F6o); DO NOT :750-752
- Claim: Under X8 (B), an unattended overnight session that hits a usage limit waits for the owner's /restart, yet the DO NOT says '(B) adds no wait'. F6o asserts zero human events, so (B) also leaves the suite unable to go green.
- Evidence: :352 '(B) … keep the human /restart, and assert that everything after it is automatic.' :751 'X8 (B) adds no wait: it records a platform limit'. :525 'F6o, inside /dev-overnight, has no human event at all'. The pilot's F6 verdict: 'an unattended overnight session waits for the owner (against D20)'. D20, T0 '总之就是不能停', D25.
- Proposed fix: Replace DO NOT :751-752 'X8 (B) adds no wait: … taken only on that evidence.' with 'X8 (B) does leave the session waiting for the owner; take it only on documented evidence, record that state as an open D20/D25 gap under "Out of scope, found" and in P2's hand-off, and do not claim F6o passes.' Add an option (C) to X8: 'an out-of-session wake the base already ships (a timer or daemon that sends the fixed recovery prompt into the session), decided by the same two replays'. Under (B), the F6o line of (2) reads 'F6o: the waiting state is reported as the named gap, never counted as passed'.


### owner-R13 [medium] harness-repair-plan/prompts/P1c.md
- Location: :473 'The compliant overnight scenario carries no producer question; P2 adds the D20 decide-and-record replay'
- Claim: The suite leaves out the overnight producer-question path, the one path where master's live prose still parks a pipeline and asks the owner after end_time. The suite can be green while the merged harness violates D20.
- Evidence: origin/master commands/dev-overnight.md :12, :115-124 (Clause A-C, Hard Rule 5: 'parks the pipeline … After end_time … asks each parked question with one AskUserQuestion'), :451-452, :1049, :1331, :1509. D20: 'never asks, never parks, also not after end_time'. X5 already tells P1c to deliver the smallest part of a later phase's row with that row's own mechanism.
- Proposed fix: Replace :473-474 with: 'Scenario (1) adds /dev-overnight devquestion: a BA producer question inside the window. Assert 0 AskUserQuestion calls inside and after the window, the decision taken by experiment or by the question's default and recorded in the summary's "Decisions made without the owner", and the pipeline reaching QA pass. Deliver under X5 the smallest part of P2's D20 row that makes it pass (P2's mechanism), listed under "Delivered for later phases".'


### owner-R14 [medium] harness-repair-plan/prompts/P1c.md
- Location: X6 (ii), class D :300-301
- Claim: Class D ('denial of a forbidden operation') counts as proven no-dead-end when the compliant scenario completes without the operation. That says nothing about the fault states where the denial actually traps an agent, so requirement (3) can pass with dead ends still in place.
- Evidence: The pilot's dead ends are D denials met only in fault states: F3b ('`rm` is refused … dead end'), F4c/F4s ('`rm .git/index.lock` is refused by bash-safety … human-only dead end'), and merge.md's `rm -f <grant>`. Each compliant scenario completes without those operations, so each site would be classed D and pass.
- Proposed fix: Replace ':300-301 … and the (1) scenario of that pipeline completes without the operation;' with '… and every replay that reaches the site, compliant or fault, reaches its terminal without the operation and with 0 human events; a site reached only by a fault replay whose pipeline cannot then complete is a dead end;'.


### owner-R15 [medium] harness-repair-plan/prompts/P1c.md
- Location: X10 rule :386-390; 'Merge rule from P1c on' :556-563
- Claim: The merge rule that keeps never-fail green for later phases rests on agent discipline (HC2). The full set runs only on a manual workflow_dispatch or the one-time ready_for_review event, and any commands/ or agents/ change no driver extracts can be exempted by a sentence in the PR body.
- Evidence: :388 '(workflow_dispatch by the reviewer, or the `ready_for_review` event)'. ready_for_review does not fire again on later pushes, so a merged head can lack a full-set run. :562 'otherwise the PR body says why no fault replay applies'. HC2: '永远不要通过ai的自觉性'.
- Proposed fix: :388: replace '(workflow_dispatch by the reviewer, or the `ready_for_review` event)' with '(on every pull_request opened, synchronize, reopened and ready_for_review event of a PR to master, as a required status check; shard further rather than move it to a manual trigger)'. :562: replace 'otherwise the PR body says why no fault replay applies' with 'and the drivers extract every fenced block and template of every changed commands/ or agents/ file, so an unextracted changed file fails the step'. Also name who marks the check required without an owner step (the reviewing session through the repository ruleset).


### owner-R16 [medium] harness-repair-plan/prompts/P1c.md
- Location: Out of scope :587-590; Scope row 10 (:408) last sentence; acceptance list
- Claim: P1c treats P1b as if it came later ('list them for P1b's table; do not merge them here'; 'Removing the re-checks at /close and /commit (P4)'). It never requires P1b's zero-exception D24 check to stay green. Keeping two deciders next to G2 (for example the e2e gate on the qa-report) would then either fail P1b's check or go unchecked.
- Evidence: P1c runs after P1b's merge (:8, :32). P1b goal 2 and row 19 require one deciding rule per artifact with no exceptions, and P1b's rows 3 and 6-7 already decide the e2e/G2 and aggregate cases. Row 10 says 'Whether this gate should stay a second decider next to G2 … is P1b's D24 question: list it, do not merge them here.'
- Proposed fix: Replace the Out-of-scope bullet ':588-590 D24 consolidation … list them for P1b's table; do not merge them here.' with 'P1b's D24 check stays green on your branch with no exception; where the suite shows two deciders on one artifact, P1b's merged choice decides and you add no second one.' Delete row 10's last sentence. Replace ':587 Removing the re-checks at /close and /commit (P4)' with 'the rest of /close and /commit (P4; P1b removed their re-checks)'. Add acceptance: 'P1b's D24 CI check passes on your branch.'


### plan-FIT-07 [medium] harness-repair-plan/reviews/P1b-plan-sync.md
- Location: V-5 (:120-130), V-8 (:157-166), P3-4 (:993-1002), P6-5 (:1300-1314), P9-5 (:1365-1383), P9-8 (:1423-1433)
- Claim: Six anchors no longer exist verbatim in the reviewer's tree (be06811). Each anchor is found once at the branch's c1bdc15, and all other 95 anchors are still found exactly once. V-8's new text also brings back '(human-run, last)', which the batch removed: P11's irreversible step is now run by the reviewer after one AskUserQuestion (W D16, D18).
- Evidence: Checked by script: every ~~~anchor block counted in c1bdc15, in p23 HEAD before the batch, and in be06811. Anchors changed: V-5 at PLAN-v2.md:139, now '| P11 | History rewrite, remote ref deletion, GitHub purge, pre-push guard (last) | 9 | every phase PR | S (reviewer) | 0 |'. V-8 at PLAN-v2.md:178, now '**Wave 9: P11 (last).** Must be merged first: every phase PR, with no phase PR open ...'. P3-4 at P3.md:714, now '- Dependencies: start only after P1, P8 and P7b are merged (the checks under "Before you start"); check'; this changed in p23's own P3 refresh, commit 174dbb4. P6-5 at P6.md:715, now '    deleted) <= +100, or the cap as raised by the measured amount under correction 1.' P9-5 at P9.md:106-109, which now says 'the agent roster (one function over the agent files)' and '(five include files (four if E4 drops the\n   Checkpoint Marking Contract) under templates/prompt-includes/)', so the sync's fallback anchor does not match either. P9-8 at P9.md:444, now '#5 rewritten: one terminal, complete; a producer question is relayed in-turn (outside /dev-overnight; inside it the question is decided without the owner and recorded, D20); the cycle stays incomplete and the same role resumes after the answer (D2, D3); Lesson 16's wording stays consistent with it.' P9-8's new text agrees with D20 and D23 and applies unchanged.
- Proposed fix: V-5: use the new anchor quoted above (INSERT AFTER; new text unchanged). V-8: anchor '**Wave 9: P11 (last).** Must be merged first: every phase PR,'; new text '**Wave 9: P11 (last).** Must be merged first: every phase PR (P7b, P1b and P1c included; the P1c replay suite green on master),'. P3-4: anchor '- Dependencies: start only after P1, P8 and P7b are merged'; new text '- Dependencies: start only after P1, P8, P7b, P1b and P1c are merged'. P6-5: insert after P6.md:719 ('    changes, with this row first.') and number it 20 (see FIT-08). P9-5: anchor P9.md:106-109 as quoted; in the new text keep '(five include files (four if E4 drops the Checkpoint Marking Contract) under templates/prompt-includes/)'. P9-8: anchor the P9.md:444 sentence quoted above; new text unchanged.


### plan-FIT-08 [medium] harness-repair-plan/reviews/P1b-plan-sync.md
- Location: P2-5 (:936-951), P3-6 (:1040-1054), P4-5 (:1126-1140), P5-5 (:1217-1231), P6-5 (:1300-1314), P9-10 (:1447-1460), with the cross-references in P2-4, P3-5, P4-4, P5-4 and P6-4
- Claim: The never-fail acceptance items are inserted after the net-code line, but the batch put its D24 acceptance after that line. Applied as written, each prompt ends up with two items of the same number, and the 'P1b and P1c' block points to the wrong one.
- Evidence: In be06811 the last acceptance items are: P2.md:824 '19. Producer and consumer per artifact (D24)'; P3.md:656 '18. D24 table' and :661 '19. Subagent question experiment'; P4.md:675 '21. D24 table (Goal 8)'; P5.md:765 '25. One producer and one deciding consumer (D24, Goal 9)'; P6.md:716 '19. One producer per artifact (D24)'; P9.md:605 '23. One producer, one consumer (D24)'. The sync inserts '19.', '18.', '21.', '25.', '19.' and '23.' right after the preceding net-code item. P10-6 (25) and P11-3 (19) are correct: P10.md:706 and P11.md:650 are the last items.
- Proposed fix: P2-5: number it 20 and insert it after P2.md:826 ('    harness-report.json, continuation sentinel, aggregate-pending and terminal receipts.'); in P2-4 write '(acceptance 20)'. P3-6: number it 20, after P3.md:663 ('    a subagent's only question path).'); in P3-5 write '(acceptance 20)'. P4-5: number it 22, after P4.md:680 (the last line of acceptance 21, '    channel kept.'); in P4-4 write '(acceptance 22)'. P5-5: number it 26, after P5.md:767; in P5-4 write '(acceptance 26)'. P6-5: number it 20, after P6.md:719; in P6-4 write '(acceptance 20)'. P9-10: number it 24, after P9.md:618 ('    table" claims (close.md:278, commit.md:83-84) if P4 left them.'); update the cross-reference in P9-6.


### plan-FIT-09 [medium] harness-repair-plan/reviews/P1b-plan-sync.md
- Location: D-1 (:498-530); W DECISIONS.md:7 and :68-82
- Claim: D-1 would add a second D25. The batch already records D25 at DECISIONS.md:68-82, and it placed D25 below the 2026-10-23 block, whose heading says those rulings are 'latest' and 'override every decision below'. As written, DECISIONS.md says D20-D24 override D25, while P1b, P1c and the sync rank D25 with D24.
- Evidence: W DECISIONS.md:7: '## Owner rulings of 2026-10-23 (latest; they override every decision below, PLAN-v1, PLAN-v2 and every prompt)'. :68: '## Owner ruling of 2026-10-24'. :70: '- **D25 Never fail.**'. D-1's anchor (:5) is still found, so its INSERT would apply and create a duplicate D25. D-1's own note asks for the heading change ('change "(latest; they override" ... to "(they override"'), but the batch did not make it. D-2 and D-3 apply cleanly. D-3's bullet should follow the batch's '- Every phase PR carries the D24 artifact table' bullet.
- Proposed fix: Drop D-1's insert. Replace DECISIONS.md:7 with '## Owner rulings of 2026-10-23 (they override every decision below except D25, PLAN-v1, PLAN-v2 and every prompt)', and :68 with '## Owner ruling of 2026-10-24 (latest; ranks with D24)'. In P1b.md :101-102 and P1c.md :134-137, change 'D20-D24' to 'D20-D25' where they rank owner rulings.


### plan-FIT-10 [medium] harness-repair-plan/DECISIONS.md (batch 06794d9)
- Location: D25 (2) at :77-79 and D22 at :46; against prompts/P1c.md :522-525, sync V-29 (:418)
- Claim: D25 as recorded says an interrupted session and a resume after a usage limit are 'repaired at the next round with no human action'. P1c's acceptance allows one human /restart for F5, F5f and F6, and D22 in the same file says 'An interrupted session is resumed with /restart', a human-only command. DECISIONS.md overrides prompts, so P1c's fault acceptance violates D25 as written.
- Evidence: DECISIONS.md:77-79: '(2) every injected fault (..., interrupted session, resume after a usage limit, ...) is returned to its own producer ... and repaired at the next round with no human action'. :46: 'An interrupted session is resumed with /restart ("恢复一个session被截断应该用restart command而不是写字" ...)'. P1c :522-525: '0 human events ... except the one human /restart that is part of F5, F5f and F6 (... /restart is human-only by design ...)'. V-29 :418: '(the human /restart of F5, F5f and F6 aside)'.
- Proposed fix: In D25 (2), after 'repaired at the next round with no human action', add '; a session the owner interrupted, or one cut by the usage limit outside /dev-overnight, resumes with the owner's /restart (human-only by design; D22's source line, teachings:295), after which nothing else needs a human; inside /dev-overnight not even that (D20; P1c X8)'.


### plan-FIT-11 [medium] harness-repair-plan/prompts/P1c.md
- Location: rows 7 (:405), 10 (:408), 13 (:411), 19 first bullet (:455-459), row 18 do.md and /dev-command bullets (:431-447); Out of scope (:588-590, :593-595); X2 (:245); net code cap (:685-690)
- Claim: P1c re-does work that P1b, which merges first, already owns at the same line ranges. P1c's net-code budget is paid mostly by lines P1b deletes, so P1c's '<= 0' cap cannot be met. Several P1c texts also hand items 'to P1b's table' after P1b has merged.
- Evidence: P1c row 7 deletes the G2 hand-off, ESCALATION_ACK and the four stores at :614, :637, :659, :691, :704 and :747; P1b row 3 (:459) deletes ':614-635, :637-656, :659-713, :747-829, deferred-checks :691'. P1c row 10 and P1b row 3 both move the e2e gate onto the obligation path. P1c row 13 and P1b row 6, row 13 and E13 both make the file check read the obligation's schema and drop the v1 names. P1c row 19's seed bullet repeats E13's 'no seed file'. The P1c row 18 do.md bullet repeats P1b E8. The /dev-command INDEX.md bullet repeats P1b E9 and E14. P1c :593-595 files the quoted `-F` read under P5, but P1b correction 5 fixes it. P1c :685-690: 'The G2 hand-off ... and the launcher's empty-contract block ... pay for the additions; expect about -150'. P1c :408, :245 and :588-590 say 'P1b's D24 question' and 'list them for P1b's table'. The sync K-12 (:856-858) admits the overlap but changes nothing.
- Proposed fix: In P1c rows 7, 10, 13 and row 19's first bullet, prefix: 'P1b row 3 / E13 / row 6 delivers this; verify it on your base, add the replay, and change code only for what P1b's PR left.' Delete the do.md expected_absent and /dev-command auto-detect bullets of row 18, or prefix them 'if P1b E8 / E9-E14 left it'. Delete the '-F' item from Out of scope. Replace ':408 "... is P1b's D24 question: list it, do not merge them here"' and ':588-590' with 'P1b's CI check already holds one deciding rule per artifact; a second decider the suite shows is a failure of that check: fix it here at the producer side.' Replace X2's 'lists them for P1b's D24 table' with 'lists them; each is a defect of P1b's path rule'. Replace the net-code paragraph with: 'Net lines in hooks/, scripts/ and schemas/ <= 0, counted against the master P1b leaves. If P1b already removed the G2 hand-off and the launcher seed, the reviewer sets the cap from P1b's PR before you start (sync V-5's rule, extended to P1c).' Extend V-5's sentence to read 'P2, P3, P4, P5, P9, P10 and P1c'.


### plan-FIT-12 [medium] harness-repair-plan/prompts/P1b.md
- Location: E3 (:235-242); Corrections item 2 (:400); Out of scope (:506); against W prompts/P5.md row 1 (:297); sync P5-4 (:1203-1205), V-15 (:255), P6-4 (:1293)
- Claim: E3's derived write permission is P5 row 1 word for word (the same rule and the same 0/0 experiment). P1b deletes the per-role prefixes that P5 row 1 names as its fallback, and P1b never says whether its permission ships enforcing. The sync tells P5 it 'arms and extends' the permission. Either master loses a deny between P1b and P5, or P5 has nothing to arm. P1b's Out of scope also gives P5 'the D8 deny for paths no obligation declares', which P5 does not plan.
- Evidence: P1b :236-241: 'a subagent may write the paths its own obligation declares; any other caller writing a declared path is denied; undeclared paths keep the policy rows ... if the derived write permission denies 0 compliant writes and allows 0 writes of a path another agent's obligation declares, the per-role write prefixes that name declared artifacts go'. W P5.md:297: 'A subagent may write the paths its own obligation declares ... Any other caller, the main agent included, that writes a path declared by any obligation of the session is denied ... Undeclared paths keep the policy rows. Decide by experiment ...: the target is 0/0. If the declared-path variant misses it, fall back to ... per-role prefix rows in tool-policy.v1.json'. P1b :506: 'the D8 deny for paths no obligation declares ... (P5)'.
- Proposed fix: Append to E3: 'The derived permission ships enforcing in hooks/pretool-tool-policy.py in the same commit that deletes the prefixes it replaces. Acceptance: every write the base denies by those prefixes is still denied on your branch (replayed), and the deny message names the path and the declaring role. You deliver P5 row 1 (TC-20); say so.' Replace :506's item with 'the protected-path denies of P5 row 2'. In sync P5-4, replace 'row 1 arms and extends that mechanism and builds no table' with 'row 1 is delivered by P1b E3 (enforcing): verify it, and its prefix fallback no longer exists'. In P6-4, replace 'as P5 armed it' with 'as P1b shipped it'.


### plan-FIT-13 [medium] harness-repair-plan/prompts/P1b.md
- Location: E8 (:299-307); against W prompts/P5.md rows 15 (:312) and 21 (:318), PLAN-v2.md TC-18 (:1049)
- Claim: On a tie, E8 prefers (a), 'the main agent writes the whole report (no skeleton)'. P5's TC-18 continuation and the do-report enum need the hook-written pending skeleton, so option (a) silently removes the basis of P5 rows 15 and 21.
- Evidence: P1b :303-304: 'prefer (a) on a tie (fewer state files)'. W P5.md:312: '/do <task-id>, where ... docs/dev/do-report-<id>.json exists with source: "do" and do.status pending, re-grants consent ...: no new id, no new skeleton'. :318: 'the enum becomes ["pending", "completed"] ... the skeleton message :1434-1437'. The pending state is the skeleton written by prompt-workflow.py:1363-1397 (P1b E8).
- Proposed fix: Add to E8's decision rule: '... and P5's TC-18 case (a /do after a consent loss finds its pending task) still resolves; prefer (b) on a tie, because P5 rows 15 and 21 read the hook's pending skeleton. Take (a) only if the replay shows TC-18 resolving from the sidecar alone; then say so for P5.'


### plan-FIT-14 [medium] harness-repair-plan/prompts/P1b.md
- Location: E12 (:345-354); row 16 (:472); against W prompts/P11.md B8 (:430-433) and :101-102, W P10.md:172 and acceptance 23 (:704-705), P1c R-V1 (:547-551)
- Claim: E12 deletes P7b's logs/landing.log write unless a command output names it. P11's landing step appends to that log, P10 scans it, and P7b's V1-1/NV-1 fixes report their result through it. If P1b deletes it, P11 brings back a written-never-read file, which fails P1b's zero-exception CI check, and P10's and R-V1's assertions lose their target.
- Evidence: P1b :347 and row 16: 'P7b's `logs/landing.log` write (read by no code ...; E12: unless a command output names it)'. W P11.md:432-433 (B8): 'One append to the landing log with counts and revision ids'. W P10.md:172: 'The only log is P7b's append-only landing log, which no code reads'; :704-705 scans 'every landing log'. reviews/P7b-PR-record.md:229 and :240: V-1's fix logs result=repair-refused.
- Proposed fix: Add to E12: 'landing.log is decided with its later writers: if it goes, the landing's notice carries what the log carried, and the reviewer's sync edits P11 B8 to "no log write; the notice carries the counts", P10.md:172 to "no landing log remains (P1b E12)" and P10 acceptance 23 to drop the log. If it stays, its owner-facing reader is named.' Add the matching edits to the sync for P10 and P11.


### plan-FIT-15 [medium] harness-repair-plan/prompts/P1b.md
- Location: Goal 5 (:80-83); row 19 (:475); acceptance 3 (:524-530); against sync V-24 (:361) and P10-4 (:1514-1516)
- Claim: The CI check derives relations only from file operations (runtime trace) and literal path sites. Several ledger artifacts are not files: the task-id rule, the obligation record, the terminal vocabulary, the resolver's stdout, the commit-QA response line and the changelog-status block. The sync removes P10's artifact-level goal in favour of this check, so after P1b nothing keeps one producer and one decider for those artifacts. A later second parser of the changelog-status block, or a second decider of the disposition stdout, would pass CI.
- Evidence: inventory/artifact-map-d625284.tsv paths: A01 'dev-<ts> ... in prompts, names, obligations'; A14 '<obligation v="1"> in Agent tool_input.prompt'; A40 'dev.status legal set'; A46 'stdout JSON of scripts/resolve-dev-artifact-chain.py'; A66 'COMMIT: APPROVE|REJECT' response line; A67 'response block changelog-status.v1'. P1b E1 (:184-185): the pilot missed 32 rows as 'row not a file'. Row 19 derives relations from settings.json, obligation records, todo steps, agents/*.md and command files, and gives no rule for stdout or response records. V-24 says P10 'adds no second artifact inventory'.
- Proposed fix: Add to row 19: 'For artifacts that are not files (a record in the transcript, a script's stdout a step consumes, a subagent's response block, a vocabulary, the task-id rule), the check derives the producer from the obligation or the producing function's call sites, and the consumers from the replay transcripts (the tool_result text a later step reads) and from the code call sites of the parsing function.' Add to acceptance 3's mutation tests: 'a second parser of the changelog-status block in a hook; a second derivation of the task id in a script'.


### facts-F11 [low] harness-repair-plan/inventory/artifact-map-d625284.tsv (row A58); harness-repair-plan/inventory/README.md
- Location: TSV A58 columns producers/violations; README.md:23-24 counts
- Claim: A58 says the close-report append-error markers have 'P: none found in code (scripts/close-report-append.py:771 only deletes)' and are 'read never written (deleted, never written)'.
- Evidence: scripts/close-report-append.py writes them: `_write_failure_marker` :250-301 creates `<_DEFAULT_MARKER_DIR>/close-report-<task>-append-error-<ts>.json` with open(marker_path, "x") at :296 (:232 `_DEFAULT_MARKER_DIR = Path("/tmp/claude-close-report-markers")`). :771 is `ok, line = run(...)`, not a delete. git grep finds no reader outside the script. The row is 'written never read', the reverse of what it says.
- Proposed fix: In TSV A58, set producers to 'scripts/close-report-append.py:250-301 (_write_failure_marker, open "x" :296) under a fixed /tmp{c}', readers to 'none{c}', and violations to 'written never read'. In README.md, change the counts to 'written never read | 30' and 'read never written | 17' (29 and 18 before; apply F8's change too).


### facts-F14 [low] harness-repair-plan/prompts/P1b.md (also P1c.md 'Out of scope, found')
- Location: Corrections to PLAN-v2 item 5 (P1b.md:413-415, 'fix the argument parsing (one line) and test it'); P1c.md:593-595
- Claim: The guard's -F check fails only because it opens the argument 'with its quotes attached', so a one-line parsing fix restores the bulk-commit subject check.
- Evidence: pretool-git-privilege-guard.py:1254-1259 matches `-F\s+(\S+)` and opens it. The analyst's prescribed form is `git -C "${GIT_ROOT}" commit -F "${MSGFILE}"` (agents/changelog-analyst.md:1118, :1449; MSGFILE chosen at :1099). PreToolUse sees the unexpanded command text, so after stripping the quotes the guard opens the literal `${MSGFILE}` and still gets ENOENT. The one-line fix works only when the analyst inlines a literal path.
- Proposed fix: Replace "fix the argument parsing (one line) and test it." with "fix the argument parsing and test both forms the analyst uses: a literal quoted path, and `-F \"${MSGFILE}\"` (changelog-analyst.md:1118, :1449). A shell variable cannot be resolved at PreToolUse, so either the analyst's prose names the literal path written by its own Write, or the check reads the message from that Write. Choose by experiment."


### facts-F15 [low] harness-repair-plan/prompts/P1b.md
- Location: E7 (P1b.md:286-288, '`qa.json`'s `qa_mode` is flipped by the orchestrator through scripts/write-qa-mode.sh between dispatches (commands/dev.md:606-611, :975-980)')
- Claim: The qa_mode switch is flipped at commands/dev.md:606-611 and :975-980.
- Evidence: write-qa-mode.sh is also called at commands/dev-command.md:437 and :627, commands/dev-overnight.md:1097 and :1381 (with the note at :1503), and commands/close.md:246-248 (the QA-arming rule, which row 1 deletes separately). If E7 removes the file write, the dev-command and dev-overnight calls are left calling a script that no longer exists, or writing a file nothing reads.
- Proposed fix: Replace "(commands/dev.md:606-611, :975-980)" with "(commands/dev.md:609, :978; commands/dev-command.md:437, :627; commands/dev-overnight.md:1097, :1381; commands/close.md:246-248)", and add to E7's decision rule: "each of these call sites goes with the switch."


### facts-F16 [low] harness-repair-plan/prompts/P1c.md
- Location: X7 (P1c.md:317-318, '(scripts/lib/session_index.py :235 and :256 raise `sync_failed`)'); Scope row 14 (P1c.md:412)
- Claim: sync-shared exits 3 when index.lock is held, at session_index.py :235 and :256.
- Evidence: session_index.py:232-235 raises on a failing `git diff-tree`, which does not take the index lock. The lock-sensitive calls are update-index: :253-256 raises, but the deletion branch :249-250 (`_run(["update-index", "--force-remove", ...])`) ignores its return code, so with the lock held a committed deletion is reported as 'synced' without syncing. X7's experiment (live holder, stale lock, no lock) would miss that silent path.
- Proposed fix: Replace "(scripts/lib/session_index.py :235 and :256 raise `sync_failed`)" with "(scripts/lib/session_index.py :253-256 raises `sync_failed` when `update-index --cacheinfo` cannot take the lock; the deletion branch :249-250 ignores update-index's return code and reports the path synced; :233-235 is diff-tree, not a lock site)". Add to X7's experiment: "each case also commits one deleted path."


### facts-F17 [low] harness-repair-plan/prompts/P1b.md; harness-repair-plan/prompts/P1c.md
- Location: P1b row 9 (P1b.md:465, 'stop-do-report-gate.py:23-24'); P1b row 6 (P1b.md:462, private terminal sets); P1c row 18 (P1c.md:439, 'commands/push.md :83 has the agent `find` the token')
- Claim: Three location claims are stale or point at the wrong lines: the do-report gate's terminal set is at stop-do-report-gate.py:23-24; row 6 lists the private terminal sets as prompt-workflow.py, posttool-overnight-loop.py and dev-lifecycle.py; push.md:83 is where the agent runs `find` on the token.
- Evidence: stop-do-report-gate.py:23-26 is docstring text. The code set is `TERMINAL_STATUSES = {"completed", "blocked"}` at :59, used at :101. aggregate-dev-report.py also has its own sets, which no row names: `_TERMINAL_DEV_STATUSES = frozenset({"completed", "blocked", "needs_review"})` at :2099 and the shard check `("completed", "needs_review")` at :784. push.md:82-84 describes push.sh's READ side ('`push.sh` scans ... (`find <repo-hash-dir> ...`)'). The agent instruction to scan the token directory is push.md:140-149 (Step 1, under a fixed /tmp at :144).
- Proposed fix: P1b row 9: replace "stop-do-report-gate.py:23-24" with "stop-do-report-gate.py:59 (TERMINAL_STATUSES, used at :101)". P1b row 6: after "dev-lifecycle.py:201-252 private terminal sets" add ", aggregate-dev-report.py:784 (shard set) and :2099 (`_TERMINAL_DEV_STATUSES`)". P1c row 18: replace "commands/push.md :83 has the agent `find` the token" with "commands/push.md:140-149 (Step 1) has the agent scan `/tmp/agentic-commit/push/<repo-hash>/` for the token (:83 describes push.sh's own read)".


### facts-F18 [low] harness-repair-plan/inventory/artifact-map-d625284.tsv; harness-repair-plan/prompts/P1b.md
- Location: TSV A63 (reader 'stop-cleanup-allowlist.sh:286'), A98 (producers 'stop-cleanup-allowlist.sh:28', 'audit-slashcommand.sh:39'); P1b row 14 caller list (P1b.md:470, '... stop-cleanup-allowlist.sh'); P1b row 18 ('session_start.sh:28')
- Claim: The TSV and P1b's rows present stop-cleanup-allowlist.sh, audit-slashcommand.sh and session_start.sh as live producers and readers.
- Evidence: settings.json at d625284 registers 81 hook entries, covering 79 files under hooks/ plus scripts/canary-verify.sh. None of the three scripts is registered, and no hook or script invokes them (git grep finds only INDEX.md, README.md and comments; CLAUDE.md also says stop-cleanup-allowlist.sh is not registered). Their reads and writes have no live entry point, so A98's {c,t} evidence for them and A63's reader are not live relations. P1b row 19's check, which derives positions from settings.json, would disagree with this map.
- Proposed fix: In TSV A63 and A98, mark those entries '(unregistered in settings.json at d625284; no live entry point)' and drop them from the counts that depend on them. In P1b row 14, after "stop-cleanup-allowlist.sh" add "(unregistered: its reading branch has no live entry; file-level deletion is P10's, D17)". In row 18, replace "session-info.sh:26, session_start.sh:28" with "session-info.sh:26 (session_start.sh is unregistered)".


### feasible-L1 [low] harness-repair-plan/prompts/P1c.md
- Location: Row 6 (:404 "required on pull_request"), X10 (:386 "as a required check"); P1b.md E2 fallback (:218 "a separate workflow job that the PR must pass")
- Claim: "Required check" is a GitHub branch-protection setting, which no PR can create. Read literally, it is a repository-settings step for whoever administers the repo, which D19 rules out for the owner.
- Evidence: baseline.yml (P8 head) defines triggers and jobs only; making a job required is done in the repository settings, outside any PR. Neither prompt names who makes the job required.
- Proposed fix: Replace "required on pull_request" (row 6) and "as a required check" (X10) with "on every pull_request; the merge condition is the reviewer's: the reviewer merges only with these jobs green on the head; the PR changes no repository setting". Apply the same to P1b E2's "that the PR must pass".


### feasible-L2 [low] harness-repair-plan/prompts/P1b.md
- Location: CI section (:768-773); Planning documents (:728); Branch and pull request (:652-668); the same text in P1c.md (:803, :843-848) and prompts/_common.md
- Claim: Shared text copied into P1b and P1c is stale or conflicts with the D18/D19 rules:
- The CI paragraph says CI is red and "P8 makes CI green", yet both prompts start only after P8 and require green CI.
- "Stop and tell the owner" contradicts "never the owner".
- The commit trailers the reviewer's item (d) asked for are missing, and "no model identifiers in commits" conflicts with the attribution lines the platform adds.
- Evidence: P1b.md:770-773: "has been red on master since 2026-07-26 ... Pre-existing failures outside your scope are not yours to fix (phase P8 makes CI green); list them". This contradicts :37 ("the latest baseline CI run on origin/master is green (P8)") and acceptance 2 and 19. :728 "stop and tell the owner instead of guessing" contradicts :38 "tell the reviewer in your session output (never the owner)". No mention of trailers anywhere in P1b, P1c or _common.md, while P7b's commits on 760f06e end with Co-Authored-By/Claude-Session lines that name a model, against _common's "Do not put model identifiers in commits or the PR".
- Proposed fix: In P1b and P1c replace the CI section's body with: "P8 made baseline.yml green; your base's latest run is green (Before you start). Run its steps locally on python 3.12 on your base and your branch; your PR keeps every job green. A red test on your base is a stop condition: say so in your session output for the reviewer."
Replace "stop and tell the owner instead of guessing" with "stop and say so in your session output for the reviewer (never ask the owner, D18)".
Add under "Branch and pull request": "End every commit message with the attribution lines your session's instructions give (Co-Authored-By, Claude-Session); they are the one exception to 'no model identifiers in commits'."
Make the same edits in prompts/_common.md.


### feasible-L3 [low] harness-repair-plan/prompts/P1b.md
- Location: Acceptance 9 grep (:554-555) against row 12 (:468)
- Claim: Acceptance 9's grep finds 14 sites on P8's head, but row 12 names only three, so the implementation session finds the other eleven only when the acceptance fails. One of them, the merge-analyst grant path, also lives in agent prose.
- Evidence: `git grep -nE '"/tmp/claude-|/tmp/agentic-commit' origin/repair/P8 -- hooks scripts ':!hooks/tests'` gives 14 hits: pretool-git-privilege-guard.py :1957/:1971 (merge-analyst grant glob), close-report-append.py :232/:731, write-git-residual-override.py:39, capture-hero-run.py :52/:377 and verify-hero-provenance.py:242 (/tmp/claude-grants), execute-push.py:35, and docstrings in commit_journal.py, posttool-push-gate-token-verify.py, pretool-push-analyst-grant-guard.py and tmpfiles-claude-scratch.conf:46.
- Proposed fix: Append to row 12's Deleted column: "also every other fixed state path acceptance 9's grep lists on your base (on P8's head: the merge-analyst grant glob at pretool-git-privilege-guard.py :1971 and its writer's prose, close-report-append.py :232, write-git-residual-override.py:39, the /tmp/claude-grants readers in capture-hero-run.py and verify-hero-provenance.py), each through harness_state_dir(); docstrings that name the old path are reworded".


### feasible-L4 [low] harness-repair-plan/prompts/P1b.md
- Location: E2 experiment (:211-212 "in a CI job on your branch")
- Claim: The E2 experiment cannot run "in a CI job on your branch" by pushing alone, because baseline.yml runs on push only for master and main. The prompt does not say how to trigger it, nor where the temporary experiment job goes so that each commit still reverts cleanly.
- Evidence: P8's baseline.yml: `on: push: branches: [master, main]; pull_request; workflow_call; schedule; workflow_dispatch`. P1b's Branch and pull request section has the PR opened after the work, and Rollback requires every commit to keep the suite green and revert on its own.
- Proposed fix: Append to E2's Experiment: "Run it either from a draft PR opened before the experiment, or with `gh workflow run baseline.yml --ref <your branch>`; put the probe in a job you remove again before the first commit the PR keeps, and paste its run URL and output."


### feasible-L5 [low] harness-repair-plan/prompts/P1b.md
- Location: Interfaces, P7b bullet (:53-55); row 0 (:456)
- Claim: The prompt names P7b's git-directory files with an "or", but both exist at 760f06e, so the session may map only one of them.
- Evidence: At 760f06e: scripts/install/render-settings:65 `RECORD = "claude-settings.applied"` (the record) and scripts/install/land:195 `ck="$COMMON/claude-settings.checked"` (the marker; d864104 keeps it as "a decided departure from the no-marker rule").
- Proposed fix: In both places replace "(`claude-settings.applied` in the reviewing session's copy; an earlier planning note calls it a `claude-settings.checked` marker in the git common dir: use what merged)" with "the record `<git dir>/claude-settings.applied` and the marker `<git common dir>/claude-settings.checked` (both at P7b's head; map each)".


### feasible-L6 [low] harness-repair-plan/prompts/P1b.md
- Location: Scope table (:454-476)
- Claim: Several d625284 map rows with D24 violations have no scope row, so the zero-exception check will fail on them without the prompt saying they are in scope.
- Evidence: From artifact-map-d625284.tsv:
- A29 (overnight graphify requirement copy: read never written in the replay);
- A37 (attribution seal logs: written never read outside their writers);
- A58 (close-report append-error markers: read never written; close-report-append.py:771 only deletes);
- A82 (dev-overnight.md:1697-1700 files-generated list: hand-written table);
- A87 (specialist-yield-log: read never written in the replay).
None is named in rows 1-18.
- Proposed fix: Append to the paragraph before the Scope table: "A violation the regenerated map shows with no row here (at d625284: A29, A37, A58, A82, A87) is in scope under the same rules: delete the dead write or read at its producer or reader, or give it its one producer."


### feasible-L7 [low] harness-repair-plan/prompts/P1c.md
- Location: Row 1 settings modes (:399 "`armed` (the same plus CLAUDE_OBLIGATION_GATE and CLAUDE_OBLIGATION_BARRIER = block ...)") against P1b.md E4 (:251-252) and P1c's pilot definition (:66)
- Claim: The same runner gets two definitions of "armed". P1c's leaves out STOPGATE, so before P1c's commit 7 its armed mode does not arm G2. That differs from P1b's armed mode and from the pilot's armed column, which P1c's fault table quotes.
- Evidence: P1b E4: "CLAUDE_OBLIGATION_GATE, _STOPGATE and _BARRIER = block". P1c :66: "armed means P1's sandbox arming (G1-G3 block, G4 advisory)". P1c row 1 arms only GATE and BARRIER.
- Proposed fix: In row 1 replace "the same plus CLAUDE_OBLIGATION_GATE and CLAUDE_OBLIGATION_BARRIER = block, P2's target" with "the same plus CLAUDE_OBLIGATION_GATE, CLAUDE_OBLIGATION_STOPGATE and CLAUDE_OBLIGATION_BARRIER = block (P1's sandbox arming, as P1b's runner uses it; P2's target)".


### feasible-L8 [low] harness-repair-plan/prompts/P1b.md
- Location: Acceptance 11 C1 (:560-561); E4 shipped list (:256-257) against E12 (:352)
- Claim: Two acceptance details fail by construction:
- C1's "subset of the base's" path-pattern test fails whenever the branch's replays reach steps the base never reached.
- E4's shipped escape list is described as "what only an advisory record notes", but E12 stops the advisory gates writing anything.
- Evidence: On the base, pipelines stop at base blocks (the overnight first cycle is a dead end, inventory/README.md), so patterns from later steps exist only on the branch. E12: "for the advisory logs: the gate writes nothing in advisory mode until P2 arms it". E4: "list every fault that a deleted check used to stop and that now only an advisory record notes".
- Proposed fix: Acceptance 11: replace "are a subset of the base's" with "are, on the steps both trees reach, a subset of the base's; every pattern from a step only your branch reaches is listed and must be named by a literal writer site on the base".
E4: replace "that now only an advisory record notes" with "that, shipped, no hook now stops (exit 0 at every hook)".


### format-FH-7 [low] harness-repair-plan/prompts/P1b.md
- Location: P1b.md:1-2 and :26-27; P1c.md:1-2
- Claim: "Owner steps: none." is the first line of the P1b and P1c prompt files. Every other prompt (P0-P11, both the branch and the p23 copies) starts with its H1, and D19's line belongs in the PR body (P7b:641, P10:749). P1b states the PR rule three times (:1, :27, :659) and P1c twice (:1, :724). The series now has two forms, and the sync list does not add the line to P2-P11.
- Evidence: `head -1` of every prompt: only P1b.md and P1c.md begin with "Owner steps: none.". The H1 follows on line 3.
- Proposed fix: Delete lines 1-2 of P1b.md and P1c.md, so the H1 is line 1. In P1b.md:26-27 delete the sentence "The PR body's first line reads\n\"Owner steps: none.\"". The rule stays at P1b.md:659 and P1c.md:724. If the reviewer wants the line at the top of every prompt instead, add it to P2-P11 through the sync list, so the whole series has one form.


### format-FH-8 [low] harness-repair-plan/inventory/README.md
- Location: :139-165 (How it was produced); :90-93 (workflow scratch inv/*.tsv); :41
- Claim: The README gives a recipe of commands that run unpublished scratch scripts ($P1B/static/extract.py, $P1B/lc/tools/build.py, agg_trace.py, join.py, build_map.py) and cites unpublished inputs. An implementer cannot run or read any of them, and _common.md:34 tells a session that cannot read planning documents to stop. P1b regenerates the map with its own runner anyway (row 0). :41's "16 to 18 claims" also disagrees with :90 ("18 ledger errors") and with P1b.md:405 ("removes 18 ... adds 19"), which P1b records in its PR.
- Evidence: Of the README's paths, only tools/build.py fails to resolve inside the planning tree, and it lives under $P1B/lc. The README itself says ":141 ... (not published; the scripts below live there and nowhere else)".
- Proposed fix: (1) Replace :139-165 with "## How it was produced\n\nBy the planning workflow's scratch scripts (static extractor, trace-a and trace-b, the ledger re-check, probes X1-X11b2), which are not published. P1b does not rerun them: its scope row 0 regenerates the map on its own base with its own runner and check. A verification pass corrected six rows by hand from code reads: A31, A51, A86, A88, A94, A117 (see each row's `resolution`)."
(2) :90-93 replace each "(workflow scratch `inv/…tsv`)" with "(not published)".
(3) :41 replace "The ledger's own 16 to 18 claims that the code does not support are removed (column `resolution`)." with "The 18 ledger claims the re-check found unsupported by the code are removed and its 19 omissions added (column `resolution`)."


### format-FH-9 [low] harness-repair-plan/prompts/P1b.md
- Location: :597-614 (Retired list); :421-445 with row 0 :456 and inventory/README.md:128-137; :52-54 and :456 (claude-settings.checked); :480-481; :665
- Claim: Restated text that gives the implementer several lists that must agree:
- The retired list restates the Scope table's Deleted and Moves columns item by item, so two lists must match.
- Trace coverage is stated three times.
- An obsolete second marker name is offered twice.
- "Out of scope, found" is added as a PR heading although the shared format already has it, so the PR gets two sections.
- Evidence: - :597-614 (18 lines) repeats the deletions of rows 1-18.
- Trace coverage: the P1b table at :427-445, row 0 at :456, and inventory/README.md:128-137 say the same thing.
- P7b's landing at its current head (1071ad3) names claude-settings.applied in scripts/install/land and render-settings, so the alternative "claude-settings.checked" is dead text.
- :480-481 lists register row ranges (PC1-PC11 ... X1-X19) that the file itself holds.
- :665 adds "**Out of scope, found**", which the shared Pull request list (:793) already has.
- Proposed fix: (1) Replace :597-615 with "Retired (at least 40): every item of the Scope table's Deleted and Moves columns that you removed, one line each with its file:line on your base."
(2) Replace inventory/README.md:128-137 with "## Not covered\n\nSee prompts/P1b.md, \"What the planning trace replayed\"; 33 rows rest on code reading alone (`evidence` = code)."
(3) :52-54 delete "; an\n  earlier planning note calls it a `claude-settings.checked` marker in the git common dir: use what merged"; in row 0 :456 delete ", or a `claude-settings.checked` marker in the git common dir".
(4) :480-481 replace "(the owner's words with sources; rows PC1-PC11, T0-T5, ON1-ON9, RD1-RD7, QP1-QP9, SG1-SG7, HC1-HC7, SF1-SF5, CC1-CC11, DT1-DT5, X1-X19)" with "(the owner's words with sources)".
(5) :665 replace "**Release notes** (the list under \"Goal\"); **Out of scope, found**." with "**Release notes** (the list under \"Goal\")."; the same in P1c.md:740.


### format-FH-10 [low] harness-repair-plan/prompts/P1c.md
- Location: :8-17 (wave text); X10 :374-380; :159-161 and :591 (CLAUDE.md #5); :174-175
- Claim: Restated and pre-P1b text in P1c:
- The wave paragraph gives the order from before P1b existed, and it does not use the wave id 2c that PLAN-v2 and HANDOVER will use.
- X10 repeats P1b E2's planning timings, which P1b replaces with CI-runner measurements before P1c starts.
- The CLAUDE.md #5 conflict appears three times.
- D18 and D19 are stated twice.
- Evidence: - :13-15: "P8 ... and P7b ... merge before wave 3 (report-zh.md, section 4, item 6)"; P1b requires both before wave 2b.
- :374-376 repeats 637.6 s, 1034.9 s, 451.4 s and 632.6 s from P1b.md:204-207. P1b acceptance 2 and E2 measure the traced replay on the CI runner.
- The #5 note appears at :159-161, :591 and :737-739.
- D18 and D19 appear at :22-27 and :174-175.
- Proposed fix: (1) :8 replace "**Wave: right after P1b, before P2 and P3.**" with "**Wave 2c: right after P1b (wave 2b), before P2 and P3.**". At :14-16 replace "merge before wave 3 (audit/2026-10-23/report-zh.md, section 4, item 6). You\nneed both:" with "merged before P1b. You need both:".
(2) :374-376 replace from "Pilot measurements (4 cores shared" through "strace adds x1.4-1.6." with "Start from P1b's E2 measurements on the CI runner (its PR) and the pilot timings above."
(3) Delete the last two sentences of :159-161 ("It conflicts with CLAUDE.md:98 ... you do not edit CLAUDE.md.") and :591's "(P9; the Hook Discipline #5 conflict with DT4 is P9's)". The hand-off at :737-739 and the DO NOT at :761 carry it.
(4) Delete :174-175 ("- **D18** decide every open choice ... **D19** no owner machine step."); :22-27 says it.


### format-FH-11 [low] harness-repair-plan/reviews/P1b-plan-sync.md
- Location: V-31 (:433-494); D-1 last sentence (:528-529); "Sync-list entry for P9" (:47-57)
- Claim: The sync list adds a new PLAN-v2 section 15 (51 lines, about 5 KB) that restates material placed elsewhere:
- P1b Correction 2's takeover list, which V-9 to V-27 already put into each phase's section;
- P1c's goals, already in D-1;
- the CLAUDE.md #5 note, already in V-21;
- P1b's corrections, already in P1b.md:405-419.
Every future change to P1b's scope then needs edits in three or four places. The #5 note alone appears in 12 lines across 7 edits.
- Evidence: - Inserted text totals 51,257 of the file's 84,178 bytes. The largest blocks are V-31 (4,982 bytes), K-12 (2,557), P2-4 (2,360) and D-1 (1,954).
- "Hook Discipline #5" occurs 12 times in the sync file: the standalone section, V-21, V-31, D-1, K-7, H-10, and P9-7 to P9-9.
- Proposed fix: (1) Shorten V-31's new text to the heading, the "Merge rule from P1c on" bullet, the "Waves" bullet, the "Caps" bullet, and one line: "P1b: prompts/P1b.md (its takeovers are in each phase section above); P1c: prompts/P1c.md; the rule: DECISIONS.md D25." Delete the P1b, P1c, CLAUDE.md and "Corrections P1b records" bullets.
(2) In D-1 delete "CLAUDE.md Hook Discipline #5 (\"honest terminal branch\") contradicts DT4 and D25; P9\n  rewrites it under D20 and D23." (V-21, P9-7 to P9-9 and K-7 carry it).
(3) Shorten the "Sync-list entry for P9" section to its last sentence (the list of edits that carry it).


### owner-R17 [low] harness-repair-plan/prompts/P1b.md
- Location: E12 :345-355 (rule 'only if a command's own output tells him its path'); Scope row 16 (logs/landing.log)
- Claim: E12 counts a file as read by the owner only when a command file names it. The landing's own notice tells the owner 'see logs/landing.log', so the rule deletes that log. The notice then points at nothing, and the only record of why a landing failed on the live home is gone, which weakens 'repairable at once'.
- Evidence: P7b's scripts/install/land :230, :239, :247, :249 (760f06e): 'Harness landing failed at the … step (see logs/landing.log) … it runs again at the next turn end'. render-settings :1208 'no code reads it'. P1b row 16 deletes the write and keeps the notice line. D24 counts the owner as a consumer; D25.
- Proposed fix: Replace E12's 'a file counts as read by the owner only if a command's own output tells him its path (the command text prints or links it, as dev-overnight.md's final summary does); the CI check derives this from the command files at test time' with '… only if an owner-facing output names its path: a command's text, or a hook's notice/systemMessage/stdout that reaches the session; the CI check derives both at test time from the command files and the hook sources'. In row 16, delete the landing.log deletion.


### owner-R18 [low] harness-repair-plan/prompts/P1b.md
- Location: E14 candidates :377-385
- Claim: E14 candidate (a) gives the spec monolith three writers (dev, QA, the spec agent), one per section. That contradicts 'exactly one producer per artifact' (D24), and a file-level write trace cannot see byte ranges, so the CI check would flag the file.
- Evidence: '(a) each section has one producer that writes it (dev its Sections 2/3, QA its own updates, the spec agent the rest)'; the rule takes the variant with 'one writer per byte range'. Goal 1 'Every harness artifact … has exactly one producer'. E2 traces file opens, not byte ranges.
- Proposed fix: Delete candidate (a) and the tie rule. Text: 'The spec agent is the monolith's only writer; dev and QA put their section text in their own reports (the former (b)). Experiment: replay /spec then /dev (singular and 2-lane, QA pass and fail); it ships if the trace shows one writer of the file and 0 blocks.'


### owner-R19 [low] harness-repair-plan/prompts/P1c.md
- Location: Scope row 11 (:409) 'the orchestrator, the step's producer per scripts/todo/dev.py, re-runs the aggregate once the lane is repaired'; row 7 'GATE_FAULT … stays'
- Claim: Row 11 fixes the orchestrator as the aggregate's re-runner, even though P1b's E5 may have made the lane-completeness hook its only producer (D8, HC2). Row 7 keeps GATE_FAULT as a permanent block that fits none of X6's classes, which forces a contradiction with requirement (3).
- Evidence: P1b E5 decision rule: take (a), the hook, when it validates before every QA dispatch with 0 orchestrator aggregation calls. P1c X6: 'A site that fits no class is a dead end'. A deterministic gate crash blocks every round, and its producer cannot clear it.
- Proposed fix: Row 11: replace 'the orchestrator, the step's producer per scripts/todo/dev.py, re-runs the aggregate once the lane is repaired' with 'the canonical's one producer as P1b's E5 chose writes it again when the repaired lane report lands'. X6 (ii): add 'E, an instrument failure (GATE_FAULT, GATE_ERROR): a hook error by the Definitions; the corpus, malformed payloads included, shows that no replay reaches it, and any reach fails the suite'.


### owner-R20 [low] harness-repair-plan/prompts/P1b.md
- Location: Context, 'Planning documents' :728 (same text P1c.md :803); CI section (both files)
- Claim: The shared text tells the implementation session to 'stop and tell the owner', which contradicts D18/D19 and both prompts' own 'tell the reviewer … (never the owner)'. The CI paragraph is also stale: it allows pre-existing failures although P8 makes CI green before P1b.
- Evidence: P1b :728 / P1c :803 'If you cannot fetch or read the planning documents, stop and tell the owner instead of guessing.' P1b's 'Before you start' says 'tell the reviewer in your session output (never the owner)'. The CI section says 'Baseline CI … has been red on master since 2026-07-26 … Pre-existing failures outside your scope are not yours to fix (phase P8 makes CI green)' and 'keep CI no worse than master', while P1b and P1c require P8 merged with green CI.
- Proposed fix: In both prompts, replace 'stop and tell the owner instead of guessing.' with 'stop and tell the reviewer in your session output (never the owner) instead of guessing.' Replace the CI paragraph with 'CI is green on master since P8. Run the baseline workflow's steps on Python 3.12 on your base and on your branch; your PR keeps every job green.' and 'keep CI no worse than master' with 'keep CI green'.


### plan-FIT-16 [low] harness-repair-plan/reviews/P1b-plan-sync.md
- Location: P2-4 'Already done' bullet (:919-924); V-9 (:180)
- Claim: The P2 block leaves out P1b and P1c deliveries that W P2's rows still edit. P2 would edit a script P1b may delete, and a state writer P1b removes.
- Evidence: W P2.md row 4 (:279) and row 15 edit scripts/write-qa-mode.sh, which P1b E7 removes 'if nothing is left' (P1b :295-297). W P2.md row 14 edits update-overnight-state.sh and break-overnight-lock.py, whose state writes P1b E13 removes (:357-358, :368). P1c X5 and row 18 deliver parts of P2's harness-home channel (TC-44: dev.md:1322, dev-command.md:889, commit.md:313/:334, close.md:337, changelog-analyst.md:669), the bwrap decision and P2 row 12's cycle index (P1c :449-452, :465-470). The block does not mention any of these.
- Proposed fix: Append to P2-4's 'Already done' bullet: '; scripts/write-qa-mode.sh's qa_mode switch (P1b E7: rows 4 and 15 edit it only if it still exists); the overnight state's extra writers (P1b E13: rows 7, 11 and 14 keep what is left, with /stop's record); and what P1c's "Delivered for later phases" lists (X5: the harness-home channel for the script paths of P1c row 18, the bwrap decision, P2 row 12's cycle index): verify, extend, do not rebuild.'


### plan-FIT-17 [low] harness-repair-plan/prompts/P1c.md
- Location: X2 (:243-246); X10 (:385-390); 'Merge rule from P1c on' (:557-562) and acceptance 8 (:633-634)
- Claim: Three rules do not fit P1b and the later phases. X2 tolerates writes to fixed /tmp paths that P1b's path rule removes. X10 can move P1b's per-PR D24 trace job into a pre-merge/weekly set. The fault-coverage step defines 'path' without settings.json but requires changed settings.json to lie on one, so P1c's own X3 commit and the settings.json edits of P2, P4, P5, P9 and P10 fail it.
- Evidence: X2 :243-244: 'writes outside tmp_path only paths that carry the scenario's own session id (the fixed /tmp paths some hooks still use: ledger L29, L42, L43)'. P1b correction 4, row 12 and acceptance 9 (:550-555) move those paths under harness_state_dir(). X10 :388: 'the traced run that feeds the D24 table ... runs on the PR head before merge ... and on baseline.yml's weekly schedule'. P1b E2 :217-218: 'still per PR, never nightly-only'. P1c :558-560 counts as a path 'hook files run, scripts they start, schemas they load, command and agent templates'; it then fails when a changed file under hooks/, scripts/, schemas/ or settings.json lies on no path.
- Proposed fix: X2: replace the parenthesis with '(after P1b's path rule there should be none; any write outside tmp_path is a fixture or harness defect, fixed before merge)'. X10: append 'P1b's D24 check job stays in the every-push set; only P1c's own traced run may move.' Merge rule: add 'settings.json counts as on the path of every replay that runs under the key the PR changes; the step diffs keys, not the file'.


### plan-FIT-18 [low] harness-repair-plan/prompts/P1c.md
- Location: X8 (A) (:340-350); 'Hand-offs for the sync list' (:730-739); sync P9-8 (:1423-1433)
- Claim: If X8 takes (A), it widens the SendMessage exception to the overnight session's own wake. CLAUDE.md's 'sole SendMessage exception' sentence and Lesson 16 (the human-only /restart) then become false. The hand-offs and the sync cover only Hook Discipline #5.
- Evidence: d625284 CLAUDE.md:62: 'The sole `SendMessage` exception is the supported human-only `/restart` path ...'. :41: 'the human-only `/restart` command must enumerate every recoverable child ...'. P1c :347-348: 'The SendMessage exception ... widens from "typed /restart" to "typed /restart, or the overnight session's own wake inside its span"'. W P9.md row 16 lists :62 only for 'run_in_background on every dispatch'.
- Proposed fix: Add a hand-off bullet to P1c: 'If X8 took (A): CLAUDE.md:62's "sole SendMessage exception" and Lesson 16 (:41-46) also name the overnight wake (P9 row 16).' Extend sync P9-8's new text with ': if P1c's X8 took (A), :62 and Lesson 16 name the overnight wake's SendMessage exception beside /restart'.


### plan-FIT-19 [low] harness-repair-plan/prompts/P1c.md
- Location: experiments X1-X10 (:220-390); P1b rows 2, 9, 12, 14 and correction 4 (probes X1, X2, X11a, X11b2); P1b row 6 '(fixes E1)'; sync P6-5 '(F3.a)'
- Claim: Experiment and probe ids clash. 'X1' means register row X1 (D15), inventory probe X1 (/allow) and P1c experiment X1 (runner source). 'E1' means P1b's experiment E1 and the ledger's v1/v2 conflict. P6-5's 'F3.a' (landscape: syntax-broken hook) reads like P1c fault F3a (the E1 contract conflict). A session reading P1b's PR could map 'probe X1' or 'fixes E1' to the wrong item.
- Evidence: register.md:274-292 has rows X1-X19. inventory/README.md:100-105 has probes X1, X2, X11a, X11b2. P1b row 14: '(probe X1: it writes both channels today)'. P1c :220: 'the experiments here are X1-X10'. P1b row 6: '(E13; one declaration, fixes E1)'. Sync P6-5 :1313: 'a syntax-broken harness hook (F3.a)'. P1c :86 defines F3a as the E1 contract conflict.
- Proposed fix: In P1b.md and inventory/README.md, rename the probes to 'probe Q1, Q2, Q11a, Q11b2'. In P1b row 6, write '(E13; one declaration, fixes the ledger's E1 v1/v2 conflict)'. In sync P6-5, write 'the landscape's F3.a (a syntax-broken harness hook)'. Optionally rename P1c's experiments to 'Y1-Y10'.


### plan-FIT-20 [low] harness-repair-plan/prompts/P1b.md
- Location: row 10 (:466, score-update.sh and close-scoring-decide.py), row 15 (:471, lifecycle-baseline-import.sh), net-code estimate (:624); against W prompts/P9.md row 10 (:438) and D9a
- Claim: P1b rewrites scoring scripts that P9 deletes whole under the already-decided D9a: close-scoring-decide.py's verdict reading, score-update.sh's precondition, and lifecycle-baseline-import.sh's second write. That is wasted work, and both phases count the same 146 lines in their net-code caps.
- Evidence: P1b :466: 'score-update.sh's precondition re-read ... and close-scoring-decide.py's own verdict reading (they call the classifier; P9 retires scoring)'. :471: 'scripts/lifecycle-baseline-import.sh's second write of the score log'. :624: 'the second score-log writer 146'. W P9.md:438 row 10 deletes scripts/score-inject.sh, close-scoring-decide.py, lifecycle-baseline-import.sh and score-update.sh. DECISIONS D9a: 'their scripts and tests are deleted'.
- Proposed fix: In rows 10 and 15, replace the edits with: 'delete scripts/close-scoring-decide.py and scripts/lifecycle-baseline-import.sh whole (D9a decided; with their allow entries and tests); P9 row 10 verifies they are gone and keeps the rest of scoring'. Add a line to the sync's P9-6 block: 'row 10: close-scoring-decide.py and lifecycle-baseline-import.sh are gone (P1b)'.


### plan-FIT-21 [low] harness-repair-plan/prompts/P1c.md
- Location: X1 (:222-230); row 1 (:399)
- Claim: P1c X1 tells the session to import P1b's runner and 'add only the scenario library', and row 1 calls tests/replay/ new. P1b ships the ten compliant drivers under tests/ (likely tests/replay/) precisely so P1c can extend them, so P1c would build a second driver set.
- Evidence: P1b :59-61: 'The trace runner and the drivers that replay all ten pipeline commands compliantly ... under tests/, so P1c can add fault injection ... without rebuilding them'. P1b row 19 (:475): 'for example tests/replay/'. P1c :223: 'import it and add only the scenario library, the assertions and the fixture'. P1c :399: 'tests/replay/ (new): conftest.py, the runner glue, the scenario library'.
- Proposed fix: Replace in X1 'import it and add only the scenario library, the assertions and the fixture (rows 1-5)' with 'import it and P1b's ten compliant drivers; add the scenarios P1b lacks (clarify, devquestion, the close-QA append-error round), the faults, the assertions and the fixture (rows 1-5)'. In row 1, write 'tests/replay/ (P1b's, extended)'.


### plan-FIT-22 [low] harness-repair-plan/PLAN-v2.md and harness-repair-plan/README.md (batch 06794d9)
- Location: PLAN-v2.md:101, :168, :541, :1051-1052; W P5.md:297 ('P3's declaring-dispatch reader (P3 row 1)'); README.md table
- Claim: After the sync, several lines still name P3 as the builder of the declaring-dispatch reader and the remover of the G2 escalation stores, which P1b and P1c now deliver. The plan's README index also does not list prompts P1b and P1c, inventory/, audit/ or reviews/, although P1b and P1c tell sessions to read README second as 'index'. The sync leaves both out.
- Evidence: PLAN-v2.md:101: 'the G2 escalation stores are removed (P3, ledger L25)'. :168: 'P3 (stages and the declaring-dispatch reader)'. :541: 'Keep the declaring-dispatch reader P3 exposed'. :1051-1052 (TC-20, TC-21): 'P3 removes the G2 escala...'. W P5.md:297: 'from P3's declaring-dispatch reader (P3 row 1)'. README.md table: DECISIONS, PLAN-v2, PLAN-v1, prompts/, landscape/, reports/, tools/ only. Sync 'Not in this sync' (:1621) excludes README.md.
- Proposed fix: Add sync edits. Replace '(P3, ledger L25)' with '(P1b row 3, P1c row 7; ledger L25)'. Replace 'P3 (stages and the declaring-dispatch reader)' with 'P3 (stages; the declaring-dispatch reader is P1b's)'. Replace 'the declaring-dispatch reader P3 exposed' with 'the declaring-dispatch reader P1b exposed'; make the same replacement in TC-20 and TC-21 and in P5.md:297 ('P1b's declaring-dispatch reader (P1b E3)'). Add README rows: 'inventory/ | the d625284 artifact map (P1b planning evidence)', 'audit/ | the 2026-10-23 owner register, ledger, corrections, report-zh', 'reviews/ | review records and plan-sync lists'. In the PLAN-v2 row, write 'phases P0-P11 plus P1b, P1c, P7b'.
