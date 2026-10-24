# P1b and P1c: plan-sync edits for the reviewer

Status: written 2026-10-24 against the planning branch at dac09ec9, for the reviewer to apply on top of its own
D20-D24 batch (audit/2026-10-23/corrections.md). This file changes nothing by itself; it lists the exact edits that
make the rest of the plan agree with prompts/P1b.md and prompts/P1c.md. New file; no other file was touched.

## How to apply

- **Order.** Apply corrections.md sections 1, 2 and 3 first, then the edits below, file by file, in the order given.
- **Anchors.** Every anchor is quoted verbatim from the file as it is at dac09ec9 (part of one line, or several whole
  lines) and occurs exactly once in that file (checked; see "Verification"). Line numbers are dac09ec9's and only help
  orientation: find each anchor by its text.
- **Actions.** REPLACE: the anchor text is replaced by the new text. INSERT AFTER / INSERT BEFORE: the anchor stays,
  and the new text goes on its own lines right after the line that contains the end of the anchor (or right before the
  line that contains its start). A new text that starts with an empty line is a new paragraph.
- **Overlap.** Where corrections.md edits the same line or the line next to it, the edit says "Overlap" and how to
  merge. Where a corrections.md text would rebuild what P1b or P1c delivers, the edit says which text wins: always the
  P1b/P1c one, because corrections.md predates both phases and both apply D24 (and D25) to the same items in more
  detail (prompts/P1b.md, "Corrections to PLAN-v2", item 2; prompts/P1c.md, "Hand-offs for the sync list").
- **P2 and P3.** corrections.md section 0 says its P2 and P3 edits go to refreshed copies (p23) that are not on the
  planning branch. The anchors below are from the dac09ec9 copies (UNVERIFIED against p23). If an anchor is not found
  there, find the same sentence by its distinctive words; the new text applies unchanged.
- **Acceptance numbers** assume dac09ec9. Where corrections.md adds or removes acceptances (it adds one at the end of
  P2, P3, P4, P5, P6, P9 and P10, deletes P3's acceptance 10, and replaces P11's acceptances 3-13), give the
  never-fail item the next free number and fix the cross-reference in that prompt's "P1b and P1c" block or
  "Before you start" line.
- **Anchors after corrections.md.** corrections.md changes the text of one anchor below: P9-5 (its section 3.6 item
  ":109"). Every other anchor is untouched by corrections.md (checked by matching every quoted fragment of
  corrections.md against the anchors; corrections.md itself is not yet applied, so this is a text comparison, not a
  run).
- **Decision id.** This file records the owner's rule of 2026-10-24 as **D25** (DECISIONS.md edit D-1).
  prompts/P1b.md and P1c.md call it "the owner's rule of 2026-10-24"; both names mean the same ruling.

## Sources

- The owner, 2026-10-24, relayed verbatim in the request that commissioned P1b and P1c: "永远不能失败！每一次开发一定不会在
  流程上出现任何错误！出现了错误也可以立刻被修复！" ("It must never fail! No development run may ever hit an error in the process!
  And if an error does occur, it can be fixed at once!"), ranked with "one producer, one consumer". The same request
  asks for a CI replay suite on the runtime trace with parts (1)-(4), and: "之后每个阶段合并的条件之一是这套测试保持全绿，
  并补上它改动那类流程的故障回放。同步清单里请给 P2–P11 每个阶段加上这一条验收。" It also asks for the sync-list entry on
  CLAUDE.md Hook Discipline #5 (below).
- Earlier owner words (audit/2026-10-23/register.md): CC4, CC8, DT2, DT3, DT4, HC2, quoted with their sources in
  prompts/P1c.md, "Owner decisions that govern this phase".
- prompts/P1b.md: "Corrections to PLAN-v2" items 1-7, scope rows 0-20, E1-E14. prompts/P1c.md: Goal, scope rows 1-21,
  X1-X10, "Merge rule from P1c on", "Hand-offs for the sync list".

## Sync-list entry for P9: CLAUDE.md Hook Discipline #5

Master CLAUDE.md, Hook Discipline item 5 (CLAUDE.md:98 at d625284; find it by its text "Ordinary `/dev` recovery has
an honest terminal branch"), lets an ordinary /dev "record the lane or cycle as blocked/incomplete ... and terminate
honestly". That conflicts with the owner's "诚实终态永远不允许" ("an honest terminal state is never allowed"; register
DT4, docs/reference/paseo-daemon-teachings-20260910.md:103 at d625284) and with D25's requirement (3) (no dead end apart
from the owner's /stop). P9 rewrites it in line with D20 (overnight asks nobody; it decides by experiment, else by the
question's preset default, and records the decision) and D23 (outside overnight the pause is one specific in-turn
AskUserQuestion that releases no gate), and keeps Lesson 16's reference to #4/#5 (CLAUDE.md:43) consistent. P1b and
P1c do not edit CLAUDE.md. The edits that carry this entry: PLAN-v2 V-21, prompts/P9.md P9-7, P9-8 and P9-9,
COVERAGE.md K-7, DECISIONS.md D-1 (last sentence), HANDOVER.md H-10.

## The acceptance item every phase P2-P11 gains

The lead sentence is the same everywhere: "The P1c replay suite stays green on this PR's head, and this PR adds the
fault replay for each process class it changes." Each prompt edit below writes it out with that phase's number and a
short "Expected here" list (a hint, not a table: P1c's fault-coverage step derives the class from the suite's traces).
PLAN-v2 gets the same sentence as a bullet in each phase's acceptance list.

P7, P7b and P8 lie inside "P2-P11" by number but carry no such item: P7 is merged (f8c18c2), and P8 and P7b merge
before P1b starts, so before the suite exists (PLAN-v2 V-6). A later PR that reopens any of them is a phase PR and falls
under the merge rule of PLAN-v2 section 15 (V-31's bullet) like every other.

---

## File: PLAN-v2.md (31 edits)

#### V-1. Section 3, a "never fail" principle (:94)

INSERT BEFORE. Overlap: corrections.md 2.11 inserts the D24 principle after :93; this bullet goes after that one,
directly before "One terminal (D2)".

~~~anchor
- **One terminal (D2).** A dev cycle ends only complete:
~~~
~~~new
- **Never fail (owner, 2026-10-24; D25, as important as D24).** "永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！" A compliant run of any of the ten pipelines (/spec /dev /redev /dev-command /dev-overnight /do /close /commit /merge /push) meets no gate block and no hook error. A fault is stopped at an allowed position (the producer's stop, G1 at dispatch, G3 at collection), its block names the artifact and the failing check, it goes back to that artifact's own producer (read from the dispatch record that declared it, D21), and that producer's next round passes with no human action. Apart from the human /stop there is no state in which an agent cannot satisfy a gate. P1c proves this with a CI replay suite on P1b's trace runner; from P1c on every phase merges only with the suite green and adds the fault replay for each process class it changes (section 15).
~~~

#### V-2. Section 5, rows for P1b and P1c (:133)

INSERT AFTER (after the P8 row). No overlap.

~~~anchor
| P8 | Private tree, one privacy engine, hermetic green CI | 2 | P0, P7 | L | < 0 |
~~~
~~~new
| P1b | One producer and at least one consumer per artifact (D24): consumer-side re-checks, second producers, written-never-read and read-never-written artifacts and filename-to-role tables removed; a CI check derives the artifact graph at test time; trace runner and ten compliant pipeline drivers | 2b | P1, P8, P7b | XL | <= -1200 |
| P1c | Never fail (D25): CI replay suite (ten compliant pipelines, fault injection, no dead end, regression replays) and the producer-side fixes it needs; merge rule for every later phase | 2c | P1b (so P1, P8, P7b) | XL | <= 0 |
~~~

#### V-3. Section 5, P2 row dependencies (:134)

REPLACE. Overlap: corrections.md 2.17 edits the Goal cell of the same row ("S2 parking"); apply both.

~~~anchor
| 3 | P1, P8 | L | <= +210 |
~~~
~~~new
| 3 | P1, P8, P7b, P1b, P1c | L | <= +210 |
~~~

#### V-4. Section 5, P3 row dependencies (:135)

REPLACE. Overlap: corrections.md 2.17 edits the Goal cell of the same row; apply both.

~~~anchor
| 3 | P1, P8 | L | <= -50 |
~~~
~~~new
| 3 | P1, P8, P7b, P1b, P1c | L | <= -50 |
~~~

#### V-5. Section 5, note under the table on waves and caps (:141)

INSERT AFTER (after the P11 row, before the empty line and "## 6. Waves"). No overlap.

~~~anchor
| P11 | History rewrite, remote ref deletion, GitHub purge (human-run) | 9 | every phase PR | S (human) | 0 |
~~~
~~~new

P7b (wave 2) is described in section 14; P1b and P1c (waves 2b and 2c) in section 15. P2-P11 also require P1b and P1c merged. P1b takes over per-artifact work this table's caps assumed for P2, P3, P4, P5, P9 and P10 (prompts/P1b.md, "Corrections to PLAN-v2", item 2), and P1c some fixes planned for P2, P3 and P5. Before each of those phases starts, the reviewer writes into its prompt an adjusted cap: the cap above plus the lines P1b and P1c already deleted from that phase's planned rows (from their PRs: P1b's "Corrections to PLAN-v2", P1c's "Delivered for later phases"), never above 0 for a phase planned net-negative.
~~~

#### V-6. Section 6, waves 2b and 2c (:162)

INSERT AFTER (after the last bullet of wave 2). No overlap.

~~~anchor
- Merge order: either. P8 first gives P1 a green CI baseline.
~~~
~~~new

**Wave 2b: P1b (alone; 2026-10-24).** Must be merged first: P1, P8 (hermetic conftest, green CI, one privacy engine, its D17 deletions) and P7b (the landing; its overlay, marker, log, seeded list and pre-commit hook enter P1b's map). P1b applies D24 to every harness artifact: one producer, at least one consumer and one deciding rule each; checks only at the producer's stop, G1 and G3; no filename-to-role table (D21); a CI check that derives the artifact graph at test time; the trace runner and the ten compliant pipeline drivers it hands to P1c. It edits most hooks, scripts and command files, so no phase shares its wave.

**Wave 2c: P1c (alone; 2026-10-24).** Must be merged first: P1b, P8 and P7b. P1c builds D25's replay suite on P1b's runner (tests/replay/: the ten pipelines in shipped and armed settings; 17 faults; the no-dead-end enumeration of every block site; regression replays of P1's fan-out wedge, E1, N1 and V1-1/NV-1) and fixes at the producer side every dead end and unreturned block the suite finds. It may arm CLAUDE_OBLIGATION_STOPGATE (its X3). From its merge on, every phase PR merges only with the suite green on its head and adds the fault replay for each process class it changes (P1c's fault-coverage CI step).
~~~

#### V-7. Section 6, wave 3 dependencies (:164)

INSERT AFTER. No overlap.

~~~anchor
**Wave 3: P2 + P3.**
~~~
~~~new
- Must also be merged first (2026-10-24): P7b, P1b and P1c (waves 2, 2b, 2c). P1b and P1c deliver parts of both phases' planned rows (section 15); each phase verifies them on its base and does not redo them.
~~~

#### V-8. Section 6, wave 9 (:180)

REPLACE. No overlap (corrections.md 2.62 renames the P11 section heading, not this line).

~~~anchor
**Wave 9: P11 (human-run, last).** Must be merged first: every phase PR,
~~~
~~~new
**Wave 9: P11 (human-run, last).** Must be merged first: every phase PR (P7b, P1b and P1c included; the P1c replay suite green on master),
~~~

#### V-9. P2 section, dependencies and P1b's map (:342)

REPLACE. Overlap: corrections.md 2.18 replaces the heading on :340 (two lines up); no textual overlap. Where
corrections.md 2.21 and 2.85 word the cycle-contract rows, P1b E13 and P1c rows 13 and 19 deliver them; P2 keeps what
is left.

~~~anchor
Wave 3, with P3. Needs P1 and P8 merged. Merges before P3 (section 6).
~~~
~~~new
Wave 3, with P3. Needs P1, P8, P7b, P1b and P1c merged. Merges before P3 (section 6).

**After P1b and P1c (2026-10-24).** P1b's artifact map governs every row below that adds or keeps a check on an artifact: the check sits at that artifact's producer stop, at G1 or at G3, and the artifact keeps one producer and one deciding consumer; a row that would add a second producer, a second deciding consumer or a consumer-side re-check is dropped. Delivered before P2 (verified on the base, not redone; where a P1b experiment took the other outcome, its PR rules): the canonical aggregate's one producer (P1b E5) and the aggregate-pending writer's removal; closeout's harness-report.json writer; the /tmp continuation sentinel; the cycle contract's one writer and one path, no launcher seed, no in-place mutation, and the schema of obligation-bearing entries read from the dispatch obligation (P1b E13, P1c rows 13 and 19; TC-35 as corrected); G2's failing stop as a plain exit 2 with no ESCALATION_ACK admission (corrections 2.27; P1b row 3, P1c row 7). If P1c's X3 already set CLAUDE_OBLIGATION_STOPGATE to block, the arming commit adds CLAUDE_OBLIGATION_GATE and _BARRIER only. P1b's E4 list (the faults the deleted consumer-side checks used to stop, with the gate that stops each once armed) is an input of P2's armed replay.
~~~

#### V-10. P2 section, acceptance (:389)

INSERT AFTER. No overlap.

~~~anchor
- `git diff --numstat -- hooks scripts schemas` -> net code lines <= +210.
~~~
~~~new
- The P1c replay suite stays green on this PR's head, and this PR adds the fault replay for each process class it changes (P1c's fault-coverage step passes): at least the D20 unattended-decision replay, the time-lock, the AskUserQuestion deny, the cycle contract and the armed settings.
~~~

#### V-11. P3 section, dependencies and P1b's map (:404)

REPLACE. Overlap: corrections.md 2.28 replaces the heading on :402; 2.30, 2.33 and 2.35 rewrite rows whose content P1b
and P1c deliver (the declaring-dispatch reader, the escalation stores); P3 consumes the result.

~~~anchor
Wave 3, with P2. Needs P1 and P8 merged. Merges after P2 (section 6).
~~~
~~~new
Wave 3, with P2. Needs P1, P8, P7b, P1b and P1c merged. Merges after P2 (section 6).

**After P1b and P1c (2026-10-24).** P1b's artifact map governs every row below that adds or keeps a check on an artifact (as in P2). Delivered before P3: the declaring-dispatch reader in hooks/lib/obligation.py (P1b E3; the row corrections 2.33 writes is consumed, not built); the G2 escalation stores, their admission and the arbitration path (P1b row 3, P1c row 7; ESCALATION_ACK releases nothing, corrections 2.30); journal-view and G2's deferred-checks write; the completion report leaving the resolver's required chain; consumers importing obligation.TERMINAL_VOCABULARY, the replay window's private set included; BA's write permission on ba-qa-report; the aggregate's blocked canonical and its third status vocabulary (P1c row 11); the resolver's fan-out optional-parent read (P1c row 12). The disposition is the one chain function P1b left (P1b row 7): every consumer calls it and nothing re-derives part of it; the lane roster is checked at G3 (P1b row 6).
~~~

#### V-12. P3 section, acceptance (:443)

INSERT AFTER. No overlap.

~~~anchor
- `git diff --numstat -- hooks scripts schemas` -> net code lines <= -50.
~~~
~~~new
- The P1c replay suite stays green on this PR's head, and this PR adds the fault replay for each process class it changes (P1c's fault-coverage step passes): at least one per disposition stage (dev, close, commit), each gap naming the artifact and the failing check and cleared by the next round of its declaring dispatch.
~~~

#### V-13. P4 section, P1b's map (:454)

INSERT AFTER. Overlap: corrections.md 2.42 adds a P4 goal "D24 table for every artifact /close and /commit read or
write (L17, ...)": P1b delivers that table (its acceptance 6); do not add 2.42's goal, and P4's PR lists only the
artifacts its rows still change.

~~~anchor
Wave 4. Needs P2 and P3 merged.
~~~
~~~new

**After P1b and P1c (2026-10-24).** P1b's artifact map governs every row below that adds or keeps a check on an artifact (as in P2). Delivered before P4: the class-b/c re-checks of /close and /commit (the aggregator re-runs at /close Step 0 and /commit row 1, /close's schema gate and Step 0 verdict layer, /commit Step 3's accepted-line list, Step 5's second resolver run, the commit-QA cross-check and the status re-parse), both routing tables and their "no code table" claims, the close-force flag readers, /close's QA re-arming of the enforce flags, the overnight loop's terminal lanes (the deletion half of TC-13), the advisory jsonl sinks (P1b E12; the D1.e row), one channel per verdict (P1b E11), and the D24 table for L17, L18, L22, L23, L28, L31, L32, L40, L41, L42 and L53. P1c fixed the close.md and commit.md steps a hook refused (its row 18). The rows below keep what is left: one disposition call per consumer, dispatching again each gap's declaring dispatch (D7, D21), the waits as in-turn questions, the native rating and the reset's print rule.
~~~

#### V-14. P4 section, acceptance (:499)

INSERT AFTER. No overlap.

~~~anchor
- `git diff --numstat -- hooks scripts schemas` -> net code lines <= -150.
~~~
~~~new
- The P1c replay suite stays green on this PR's head, and this PR adds the fault replay for each process class it changes (P1c's fault-coverage step passes): at least /close and /commit completing an incomplete cycle by dispatching again the declaring dispatch, the rating question, and the overnight reset that never blocks.
~~~

#### V-15. P5 section, P1b's map (:512)

INSERT AFTER. Overlap: corrections.md 2.45 rewrites the D8 row as a deny derived from dispatch records and marks the
escalation-record deny temporary: P1b E3 ships that derivation, and the escalation records no longer exist (P1b row 3,
P1c row 7), so that deny is dropped (P1c hand-off), not kept as temporary.

~~~anchor
Wave 5. Needs P4 merged.
~~~
~~~new

**After P1b and P1c (2026-10-24).** P1b's artifact map governs every row below that adds or keeps a check on an artifact (as in P2); the gate's predicates call the one chain function and read git, and decide nothing a producer-side gate already decided. Delivered before P5: G4's re-validation (stop-obligation-gate.py is already an exit-0 stub; what is left of find_unresolved_dispatch_obligations is what the declaring-dispatch reader needs), the todo-file writers and bookmark mutations (P1b E7; command_span calls() and last_todos() exist if E7 shipped them), the separate do.status deciders and the do-report's one writer (P1b E8), merge.md's validate-and-unlink (P1b E11), and the D8 write permission derived from the session's dispatch records (P1b E3, TC-20 as corrected): P5-a arms and extends that mechanism and builds no table. The escalation-record deny has nothing left to deny and is dropped. Gate 4 accepts a recovery resume (P1c row 16); the todo fold keeps that rule. Every block site P5 adds fits a class of P1c's no-dead-end check (its X6): a gap block is cleared by the actor's next compliant step (G), a deny names the forbidden operation (D), and only the gate's and the launcher's instrument-failure block waits for the human /stop (H, like the time-lock's).
~~~

#### V-16. P5 section, acceptance (:590)

INSERT AFTER. No overlap.

~~~anchor
- `git diff --numstat -- hooks scripts schemas` -> net code lines <= -700.
~~~
~~~new
- The P1c replay suite stays green on this PR's head, and this PR adds the fault replay for each process class it changes (P1c's fault-coverage step passes): at least a gap block per gated command cleared by the next compliant step, the instrument-failure block released by /stop, the D8 deny of a foreign write, and the /do file-list check.
~~~

#### V-17. P6 section, P1b's map (:610)

INSERT AFTER. Overlap: corrections.md 2.51 rewrites the agent-index row (:626); consistent with P1b correction 3.

~~~anchor
Wave 6. Needs P5 merged.
~~~
~~~new

**After P1b and P1c (2026-10-24).** P1b's artifact map governs every row below (as in P2). P1b's E6 chose the one producer of "which files this dev wrote" and of the baseline, and removed the other producer and every rule that compared the two: A3.a builds on the producer E6 kept, with G2 at dev's stop as the one deciding consumer, and adds no second comparison. All agent-index consumers already take agent_resolver's one conclusion (P1b correction 3), so A4.a changes only the role input. The D8 deny is P1b E3's mechanism as P5 armed it.
~~~

#### V-18. P6 section, acceptance (:639)

INSERT AFTER. No overlap.

~~~anchor
- `git diff --numstat -- hooks scripts schemas` -> net code lines <= +100.
~~~
~~~new
- The P1c replay suite stays green on this PR's head, and this PR adds the fault replay for each process class it changes (P1c's fault-coverage step passes): at least a dev report that lists a file it did not write or omits one it wrote, a syntax-broken harness hook (F3.a), and a grant claimed by the wrong role, each returned to its own producer.
~~~

#### V-19. P9 section, runtime artifacts moved to P1b (:754)

INSERT AFTER. Overlap: corrections.md 2.56 appends to the spec_path row (:770); consistent (prompt-workflow decides the
spec once; no spec rule enters the disposition).

~~~anchor
Wave 7. Needs P6 and P8 merged.
~~~
~~~new

**After P1b and P1c (2026-10-24).** Runtime artifacts moved to P1b (D24): the spec_path producer (P1b row 8, E14: the explicit --spec, else the session's last Write or Edit to docs/dev/specs/*.md), doc-sync's creation in product directories (P1b E9, if it deleted creation), one has_do_consent reader (P1b row 9), the roster computed from the stems of agents/*.md (P1b row 18), the orchestrator's context patches and QA-content writes (E10, E14), and the one-writer proofs for L01, L24, L42, L44 and L51. For those rows P9 re-runs its acceptance tests against P1b's result, fixes only what fails, and does the prose pass. Facts that are not runtime artifacts stay P9's: the git option table and normaliser, the shared prompt blocks, and the prose pass itself.
~~~

#### V-20. P9 section, goal "one producer per fact" (:757)

REPLACE. Overlap: corrections.md 2.54 replaces the next line (:758); no textual overlap.

~~~anchor
- Each fact gets one producer: spec_path, doc-sync output, the consent check, the roster, the git option table, and the shared prompt blocks (includes).
~~~
~~~new
- Each fact gets one producer. Runtime artifacts (spec_path, doc-sync output, the consent check, the roster) got theirs in P1b and are verified here; the git option table and the shared prompt blocks (includes) get theirs here.
~~~

#### V-21. P9 section, CLAUDE.md row: Hook Discipline #5 (:783)

REPLACE (part of the CLAUDE.md row's Change cell). No corrections.md edit touches :783. This is the PLAN half of the
sync-list entry for P9.

~~~anchor
#5 rewritten: one terminal (complete), a producer question is relayed in-turn, the cycle stays incomplete and the same role resumes after the answer (D2, D3);
~~~
~~~new
#5 rewritten under D20 and D23, because "Ordinary /dev recovery has an honest terminal branch" (CLAUDE.md:98 at d625284) conflicts with the owner's "诚实终态永远不允许" (register DT4, teachings:103) and with D25: no honest, blocked or incomplete terminal; one terminal (complete); outside /dev-overnight a needed owner decision is one specific in-turn AskUserQuestion (the pause), which releases no gate, and the same role resumes after the answer; inside /dev-overnight nobody is asked and the decision is made by experiment, else by the question's preset default, and recorded in "Decisions made without the owner"; Lesson 16's reference to #4/#5 (:43) stays consistent (D2, D3, D20, D23, D25);
~~~

#### V-22. P9 section, acceptance (:795)

INSERT AFTER. No overlap.

~~~anchor
- `git diff --numstat -- hooks scripts schemas` -> net code lines <= -900.
~~~
~~~new
- The P1c replay suite stays green on this PR's head, and this PR adds the fault replay for each process class it changes (P1c's fault-coverage step passes); prose-only changes need none, and every command or agent template a driver extracts keeps its scenarios green.
~~~

#### V-23. P10 section, the dead-code row excludes P1b's deletions (:826)

REPLACE. No overlap.

~~~anchor
| the I5/I6 list: every item still unreachable after P8 (D17) |
~~~
~~~new
| the I5/I6 list: every item still unreachable after P8 and not already deleted by P1b or P1c (D17; their PRs list each deletion with its reachability proof) |
~~~

#### V-24. P10 section, goals: the artifact-level goal is P1b's CI check (:811)

INSERT AFTER. Overlap: corrections.md 2.61 adds the P10 goal "Artifact-level D17 (D24): every artifact the harness
writes has a reader ... experiment-9 trace over all ten pipeline commands; ledger DEAD rows first". Do not add 2.61's
text; this bullet replaces it (prompts/P1b.md, "Corrections to PLAN-v2", item 2: the CI check replaces it, and P10
keeps file-level D17).

~~~anchor
- BA can propose a rule's retirement.
~~~
~~~new
- Artifact-level D24 (every artifact written has a reader, every artifact read has a writer, one producer and one deciding rule each) is P1b's CI check, which stays green; P10 keeps file-level D17 and adds no second artifact inventory.
~~~

#### V-25. P10 section, acceptance (:839)

INSERT AFTER. No overlap.

~~~anchor
- `git diff --numstat -- hooks scripts schemas` -> net code lines <= -40000.
~~~
~~~new
- The P1c replay suite stays green on this PR's head, and this PR adds the fault replay for each process class it changes (P1c's fault-coverage step passes): at least the stub retirement and the recoverable removal.
~~~

#### V-26. P11 section, dependencies (:847)

REPLACE. Overlap: corrections.md 2.63 replaces the sentences that follow in the same paragraph (:847-848, "An agent
may prepare the commands ..."); apply both.

~~~anchor
Wave 9. Needs every phase PR merged and no phase PR open.
~~~
~~~new
Wave 9. Needs every phase PR merged (P7b, P1b and P1c included) and no phase PR open.
~~~

#### V-27. P11 section, acceptance (:877)

INSERT AFTER. No overlap.

~~~anchor
- The P0 acceptance test still passes: a dirty Stop with GIT_AUTO_PUSH unset creates no remote ref.
~~~
~~~new
- The P1c replay suite stays green on this PR's head, and this PR adds the fault replay for each process class it changes (P1c's fault-coverage step passes): the landing's new step on a pull of rewritten history, also under a held index.lock (and the pre-push guard, if corrections 2.65 applies); R-N1 and R-V1 stay green.
~~~

#### V-28. Section 11, net-code metric (:1158)

REPLACE (part of the row). No overlap.

~~~anchor
P0 <= 0; P1 <= -250; P2 <= +210;
~~~
~~~new
P0 <= 0; P1 <= -250; P1b <= -1200; P1c <= 0; P2 <= +210;
~~~

#### V-29. Section 11, three metrics (:1135)

INSERT AFTER. No overlap (corrections.md 2.88 edits the overnight-questions row, :1142).

~~~anchor
| Compliant pipelines that complete with G1-G3 and the command gate armed, under T1 | 1 of 6 | 6 of 6 (G1-G3 after P2; the command gate after P5) |
~~~
~~~new
| Compliant replays of the ten pipelines (shipped and armed settings) with a gate block or a hook error | trace B: 9 refusals on the compliant replay and a dead-end first overnight cycle; trace A and the 2-lane /dev: 0 (P1c pilot, d625284) | 0 in CI on every PR from P1c on |
| Injected faults not returned to the artifact's own producer, needing a human action, or ending in a dead end | F1, F1q, F2, F2j, F2g, F3a, F3b, F4c, F5, F6, F7b (shipped settings; P1c pilot, d625284) | 0 from P1c on (the human /restart of F5, F5f and F6 aside), held by the merge rule |
| Artifacts with more than one producer / more than one deciding consumer / written never read / read never written | 35 / 37 / 29 / 18 of 122 (d625284 map, inventory/README.md) | 0 after P1b, held by its CI check |
~~~

#### V-30. Section 14, its wave list is superseded (:1246)

INSERT AFTER. No overlap.

~~~anchor
- Sections 5 and 6: P2-P6 also require P7b merged. Waves: P7b + P1 + P8; P2 + P3; P4; P5; P6; P9; P10; P11.
~~~
~~~new
  (Superseded by section 15: P1b and P1c run between wave 2 and wave 3.)
~~~

#### V-31. New section 15 at the end of the file (:1257)

INSERT AFTER (the last line of the file). No overlap.

~~~anchor
against master f8c18c27, cross-checked in COVERAGE.md). HANDOVER.md is the owner's table of when to open each.
~~~
~~~new

## 15. Revision 2026-10-24: P1b, P1c and the never-fail rule

The owner, 2026-10-24, ranked with "one producer, one consumer" (D24): "永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以
立刻被修复！" ("It must never fail! No development run may ever hit an error in the process! And if an error does occur, it
can be fixed at once!") DECISIONS.md records it as D25 with the earlier words it restates (audit/2026-10-23/register.md
rows CC4, CC8, DT2, DT3, DT4, HC2). The request that relayed it asked for a CI replay suite that reuses the runtime trace,
and: "之后每个阶段合并的条件之一是这套测试保持全绿，并补上它改动那类流程的故障回放".

- New phase **P1b** (wave 2b, alone; needs P1, P8 and P7b; net code <= -1200; prompts/P1b.md; planning evidence in
  inventory/): D24 applied to every harness artifact. Re-checks and re-derivations at consumers go (/close, /commit,
  scripts consumers run, other hooks, prose steps); checks stay only at the producer's stop, G1 and G3; every second
  producer and second deciding consumer goes; a written-never-read artifact is deleted at its producer and a
  read-never-written one loses its reading branch; filename-to-role tables give way to the declaring-dispatch reader
  (D21). A CI check derives the artifact graph at test time, with no exception list. P1b ships the trace runner and the
  ten compliant drivers P1c builds on.
- P1b takes over these rows (prompts/P1b.md, "Corrections to PLAN-v2", item 2): from P2, the canonical aggregate's
  producer, closeout's harness-report writer, the cycle contract's single writer, path, no seed and obligation-sourced
  schema (TC-35 as corrected), the aggregate-pending and continuation-sentinel writers; from P3, the declaring-dispatch
  reader, the escalation stores and the arbitration path, journal-view, the completion report leaving the required
  chain, the TERMINAL_VOCABULARY imports, BA's ba-qa-report permission; from P4, the class-b/c re-checks, both routing
  tables, the close-force readers and the D24 table for L17, L18, L22, L23, L28, L31, L32, L40, L41, L42 and L53; from
  P5, G4's re-validation, the todo-file writers, the do.status deciders, merge.md's validate-and-unlink and the write
  permission derived from dispatch records (TC-20 as corrected); from P9, the spec_path producer, doc-sync update-only
  (if its E9 deletes creation), the one /do consent reader, the roster from agents/*.md stems and the one-writer proofs
  for L01, L24, L42, L44 and L51; from P10, the artifact-level goal of corrections.md 2.61, replaced by the CI check
  (P10 keeps file-level D17).
- New phase **P1c** (wave 2c, alone; needs P1b, P8 and P7b; net code <= 0; prompts/P1c.md): D25's suite under
  tests/replay/. (1) The ten pipelines run compliantly in shipped and armed settings with 0 gate blocks and 0 hook
  errors. (2) Faults (a missing, malformed or old-version artifact including E1's v1/v2 conflict, a held git
  index.lock, an interrupted session, a usage limit and resume, a fan-out lane leaving an old report) are each blocked
  with the artifact and the failing check named, returned to the producer of the declaring dispatch, and pass on the
  next round with zero human action. (3) No dead end, proven by enumerating every block site at test time and
  replaying each (P1c X6). (4) Regression replays of P1's fan-out wedge, E1, N1 and V1-1/NV-1 (N1 and V1-1/NV-1 have no
  record in the repository or the planning branch; P1c reproduces them from their descriptions). P1c fixes at the
  producer side every dead end and unreturned block the suite finds (G2's no-progress hand-off and ESCALATION_ACK
  admission, the e2e gate's newest-file correlation, the aggregate's blocked canonical, E1, the shared-index sync under
  a held lock, /restart's refused commands, Gate 4 after a recovery resume, the literal-prose conflicts, the overnight
  first cycle).
- **Merge rule from P1c on.** Every phase PR (P2-P11) merges only when the suite's full set is green on its head and it
  adds the fault replay for each process class it changes; P1c's fault-coverage CI step derives the class from the
  suite's traces. Each of P2-P11 carries this as an acceptance test.
- **Waves.** P0 + P7; P1 + P8 + P7b; P1b; P1c; P2 + P3; P4; P5; P6; P9; P10; P11.
- **Caps.** See the note under section 5.
- **CLAUDE.md.** Hook Discipline #5 ("Ordinary /dev recovery has an honest terminal branch", master CLAUDE.md:98 at
  d625284) conflicts with the owner's "诚实终态永远不允许" (DT4) and with D25's requirement (3). P9 rewrites it under D20 and
  D23 (the CLAUDE.md row of P9). P1b and P1c do not edit CLAUDE.md.
- **Corrections P1b records in its PR:** the audit ledger's counts are superseded by the d625284 map (inventory/README.md;
  L04's MC label withdrawn); the hook-state path rule (state written under harness_state_dir() but read at a fixed /tmp
  path in four places); the privilege guard's quoted `-F` read; G4 left as an exit-0 stub for P5; P2 keeps arming G1-G3,
  with P1b's E4 shipped-mode list as its input (G1 and G3 only, if P1c armed G2).
~~~

---

## File: DECISIONS.md (3 edits)

#### D-1. The owner's ruling of 2026-10-24 as D25 (after :5)

INSERT AFTER. Overlap: corrections.md 1.1 also inserts after line 5 (the 2026-10-23 block, headed "(latest; they
override every decision below ...)"). Put this block first, directly after line 5, so the 2026-10-23 block follows it;
when both are applied, change "(latest; they override" in 1.1's heading to "(they override". D25 overrides nothing in
D20-D24 and agrees with them.

~~~anchor
"ask for curl/wget/docker" or "per-cycle commit", read the decision below instead.
~~~
~~~new

## Owner ruling of 2026-10-24 (latest; ranks with D24)

- **D25 Never fail.** The owner, 2026-10-24, to the reviewing session (relayed verbatim in the request that
  commissioned P1c): "永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！" [It must never fail! No
  development run may ever hit an error in the process! And if an error does occur, it can be fixed at once!] He ranks
  it with D24. The same request asked for it as a CI replay suite that reuses the runtime trace: (1) the ten pipelines
  run compliantly with 0 gate blocks and 0 hook errors; (2) injected faults (a missing, malformed or old-version
  artifact, a held git index.lock, an interrupted session, a usage limit and resume, a fan-out lane leaving an old
  report) are each blocked with the artifact and the failing check named, go back to that artifact's own producer, and
  pass on the next round with zero human action; (3) apart from the owner's /stop, no state exists in which an agent
  cannot satisfy a gate; (4) every process defect already fixed has a regression replay. And: "之后每个阶段合并的条件之一是
  这套测试保持全绿，并补上它改动那类流程的故障回放" [from then on, one condition for merging each phase is that this suite stays
  green and the phase adds the fault replay for the kind of process it changes]. Earlier words it restates
  (audit/2026-10-23/register.md; "teachings" is docs/reference/paseo-daemon-teachings-20260910.md at d625284): CC4
  (D7, O19: "dev永远都会完成…只要用户想dev一定dev完成，用户想close一定close完成", plan prompts/P4.md:100-102); CC8 ("永远不允许
  force，永远一致的规则就是agent哪里犯错了自己就补哪里", teachings:108); DT2 (O17/O18: "…dev走完只会有一个结果：彻底开发完成，不存在任何
  gap", plan prompts/P3.md:144-146); DT3 (O17: "不要给我说失败"); DT4 ("诚实终态永远不允许", teachings:103); HC2 ("如果发现了
  问题就通过harness解决，永远不要通过ai的自觉性！", teachings:124). P1c delivers the suite; from P1c on it is a merge condition of
  every phase (Execution, below). CLAUDE.md Hook Discipline #5 ("honest terminal branch") contradicts DT4 and D25; P9
  rewrites it under D20 and D23.
~~~

#### D-2. Execution: the inserted phases (:114)

INSERT AFTER. No overlap.

~~~anchor
  P11 = remote refs and history cleanup). Wave 1 = P0 + P7. The later waves are in PLAN-v2.md.
~~~
~~~new
- Inserted phases: P7b (2026-10-18, zero-touch landing), P1b (2026-10-24, D24 applied to every artifact) and P1c
  (2026-10-24, D25's replay suite). After wave 2 the order is P1b, then P1c, then P2 + P3 (PLAN-v2.md sections 14
  and 15).
~~~

#### D-3. Execution: the merge rule (:116)

INSERT AFTER. Overlap: corrections.md 1.10 inserts "- Every phase PR carries the D24 artifact table, measured, before
review." after the same line; put this bullet after 1.10's.

~~~anchor
  experiment under D18 when their phase reaches them.
~~~
~~~new
- From P1c on, the reviewing session merges a phase PR only when the P1c replay suite (its full set) is green on the
  PR head and the PR adds the fault replay for each process class it changes (D25; P1c's fault-coverage CI step).
~~~

---

## File: HANDOVER.md (10 edits)

#### H-1. The table: rows for P1b and P1c (:18)

INSERT AFTER (after the P8 row). No overlap (corrections.md does not edit HANDOVER.md).

~~~anchor
| 第 2 波 | P8.md | 把私人内容清出仓库；只留一个隐私检查引擎；CI 变绿 | 同上，现在就能开 | 能，和 P7b、P1 同时跑；比 P1 先合并更好（P1 就能在绿的 CI 上收尾） | 约 3 天 | 问题 2 |
~~~
~~~new
| 第 2b 波 | P1b.md | 每个产物只有一个生产者、至少一个消费者，消费者只信一个结论（D24）：删掉 /close、/commit 等消费端的重复检查、多余的生产者、写了没人读和读了没人写的文件、"文件名对应角色"的表；CI 里加一个每次重新推导产物关系的检查，并交给 P1c 一个能回放全部 10 条流水线的运行时追踪工具 | P1、P8、P7b | 不能，单独跑 | 约 7 天 | 不问 |
| 第 2c 波 | P1c.md | "永远不能失败"：CI 里的回放测试套件（10 条流水线合规运行、故障注入、没有死路、已修流程错误的回放），测出来的死路都在生产端修好；之后每个阶段合并都要它全绿，并补上自己改的那类流程的故障回放 | P1b（因此也要 P1、P8、P7b） | 不能，单独跑 | 约 6 天 | 不问 |
~~~

#### H-2. P2 row dependencies (:19)

REPLACE. No overlap.

~~~anchor
| P1、P8、P7b | 能，和 P3 同时跑；P2 先合并 |
~~~
~~~new
| P1、P8、P7b、P1b、P1c | 能，和 P3 同时跑；P2 先合并 |
~~~

#### H-3. P3 row dependencies (:20)

REPLACE. No overlap.

~~~anchor
| P1、P8、P7b | 能，和 P2 同时跑；P3 后合并 |
~~~
~~~new
| P1、P8、P7b、P1b、P1c | 能，和 P2 同时跑；P3 后合并 |
~~~

#### H-4. P4 row dependencies (:21)

REPLACE. No overlap.

~~~anchor
| P1、P8、P7b、P2、P3 | 不能，单独跑 | 约 3.5 天 | 问题 4 |
~~~
~~~new
| P1、P8、P7b、P1b、P1c、P2、P3 | 不能，单独跑 | 约 3.5 天 | 问题 4 |
~~~

#### H-5. P5 row dependencies (:22)

REPLACE. No overlap.

~~~anchor
| P1、P8、P7b、P2、P3、P4 | 不能，单独跑 |
~~~
~~~new
| P1、P8、P7b、P1b、P1c、P2、P3、P4 | 不能，单独跑 |
~~~

#### H-6. P6 row dependencies (:23)

REPLACE. No overlap.

~~~anchor
| P1、P8、P7b、P2、P3、P4、P5 | 不能，单独跑 |
~~~
~~~new
| P1、P8、P7b、P1b、P1c、P2、P3、P4、P5 | 不能，单独跑 |
~~~

#### H-7. P9-P11 row: P11 after every PR, P1b and P1c included (:24)

REPLACE (part of the row). No overlap.

~~~anchor
P11 在所有 PR 都合并之后 |
~~~
~~~new
P11 在所有 PR（含 P1b、P1c）都合并之后 |
~~~

#### H-8. Duration (:26)

REPLACE. No overlap. (3.5 + 7 + 6 + 3.5 + 3.5 + 5 + 2.5 = 31.)

~~~anchor
按每波最长的算：第 2 波约 3.5 天，第 3 波约 3.5 天，再加 P4 3.5 天、P5 5 天、P6 2.5 天，合计约 18 个工作日，
~~~
~~~new
按每波最长的算：第 2 波约 3.5 天，P1b 约 7 天，P1c 约 6 天，第 3 波约 3.5 天，再加 P4 3.5 天、P5 5 天、P6 2.5 天，合计约 31 个工作日，
~~~

#### H-9. Waves told to the owner (:29)

INSERT AFTER. No overlap.

~~~anchor
和你 10-18 听到的波次一致：P7b + P1 + P8，然后 P2 + P3，然后 P4、P5、P6 依次。这次把 P7b 也写进了 P2–P6 的前置条件。
~~~
~~~new

2026-10-24 起：第 2 波之后先单独跑 P1b，再单独跑 P1c，然后才是 P2 + P3；P2–P11 的前置条件都加上了 P1b 和 P1c。
~~~

#### H-10. New section "2026-10-24 更新" at the end (:104)

INSERT AFTER (the last line of the file). No overlap.

~~~anchor
- 你不用做任何事。P7b 合并之前，/pull 仍然不安全。
~~~
~~~new

## 2026-10-24 更新

- 你新加的一条，和"一生产者一消费者"（D24）同等重要，原话："永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"
  记进 DECISIONS.md，编号 D25；你以前说过的同类的话（register.md 的 CC4、CC8、DT2、DT3、DT4、HC2）一并引在那里。
- 新增两个阶段，都排在 P8、P7b 之后、P2 + P3 之前，各自单独跑，都不问你、不要你动手：
  - P1b（prompts/P1b.md）：每个产物只留一个生产者、至少一个消费者，消费者只信一个结论；/close、/commit 等消费端的重复检查、多余的
    生产者、没人读的文件、"文件名对应角色"的表都删掉；CI 里加一个每次重新推导产物关系的检查。约 7 天。
  - P1c（prompts/P1c.md）：把"永远不能失败"做成 CI 里的回放测试套件，复用 P1b 的运行时追踪：(1) 10 条流水线合规运行，门禁拦截 0、
    hook 报错 0；(2) 故障注入：缺产物、格式错、旧版本报告（E1 的 v1/v2 冲突）、git index.lock 被占、会话中断、额度用完后恢复、并行
    lane 留旧报告（P1 那个严重问题），每个拦截都点名产物和没过的检查，退回给它自己的生产者，下一轮通过，零人工；(3) 没有死路：除了
    你的 /stop，不存在 agent 无法满足门禁的状态；(4) 已修过的流程错误各一个回放：P1 并行、E1、N1、V1-1/NV-1（后两个在仓库和规划
    分支里都没有记录，按描述复现）。测出来的死路都在生产端修好。约 6 天。
- 从 P1c 起，P2–P11 每个阶段合并的条件之一是这套测试在它的 PR 上保持全绿，并补上它改动那类流程的故障回放；每个提示词都加了这一条
  验收。
- P2–P5、P9、P10 原计划里的一部分逐产物工作改由 P1b 先做（P1b.md 的"Corrections to PLAN-v2"第 2 条）；这些阶段的净代码上限由
  审阅者按 P1b、P1c 的 PR 重新折算后写进提示词。
- master 的 CLAUDE.md Hook Discipline 第 5 条（"honest terminal branch"，d625284 第 98 行）和你的"诚实终态永远不允许"冲突，交给
  P9 按 D20、D23 改写。
- 波次：P8、P7b 合并后 → P1b → P1c → P2 + P3 → P4 → P5 → P6 → P9 → P10 → P11。P1b、P1c 让总工期多出约 13 个工作日。
- 你不用做任何事。
~~~

---

## File: COVERAGE.md (12 edits)

#### K-1. Decisions table: D24 and D25 (:46)

INSERT AFTER (after the D17 row). No overlap.

~~~anchor
| D17 dead code deleted | P8 (candidate list), P3 and P5 (code their change orphans), P4/P6 ("Now unreferenced") | P10 (rest of I5/I6, unregistered hook files) | |
~~~
~~~new
| D24 one producer, one consumer per artifact (2026-10-23) | P1b (every artifact: map, deletions, declaring-dispatch reader, CI check); every later PR carries the D24 table | P10 file-level D17 only (the artifact-level goal is P1b's CI check) | added 2026-10-24; this table has no D20-D23 rows yet (corrections.md does not edit COVERAGE.md) |
| D25 never fail (2026-10-24) | P1c (replay suite, producer-side fixes, merge rule); P2-P11 (acceptance: suite green on the PR head, fault replay per changed process class) | - | P9 rewrites CLAUDE.md Hook Discipline #5 (C12) |
~~~

#### K-2. Owner statements: O4/O6 (:55)

REPLACE. No overlap.

~~~anchor
| O4/O6 three axes; one producer and one consumer per artifact | P3, P5 (quoted); P8 goal 4; P4 row 8 (flag writers lose their reader) | P9 (one producer per fact) |
~~~
~~~new
| O4/O6 three axes; one producer and one consumer per artifact | P1b (every artifact, CI check); P3, P5 (quoted); P8 goal 4; P4 row 8 (flag writers lose their reader) | P9 (facts that are not runtime artifacts: git option table, includes) |
~~~

#### K-3. Owner statements: O10/O12 (:59)

REPLACE. No overlap.

~~~anchor
| O10/O12 producer-side only, consumers trust one conclusion | every prompt; P4 removes consumer checks | - |
~~~
~~~new
| O10/O12 producer-side only, consumers trust one conclusion | every prompt; P1b removes consumer-side re-checks and second deciding consumers of every artifact; P4 removes what P1b left in /close and /commit | - |
~~~

#### K-4. Owner statements: O17/O18 (:61)

REPLACE. No overlap.

~~~anchor
| O17/O18 no "failure" framing; dev ends complete; user may join mid-way | P1, P3 (include step 6), P4 (OPERATION_STALLED question) | P9 |
~~~
~~~new
| O17/O18 no "failure" framing; dev ends complete; user may join mid-way | P1, P1c (no dead end; every fault returns to its producer), P3 (include step 6), P4 (OPERATION_STALLED question) | P9 (Hook Discipline #5, C12) |
~~~

#### K-5. Owner statements: O45 waves (:70)

REPLACE. No overlap.

~~~anchor
| O45 waves and parallelism | P7b + P1 + P8, P2 + P3, P4, P5, P6 as the prompts state (section d) | P9 -> P10 -> P11 |
~~~
~~~new
| O45 waves and parallelism | P7b + P1 + P8, then P1b, then P1c (2026-10-24), then P2 + P3, P4, P5, P6 as the prompts state (section d) | P9 -> P10 -> P11 |
~~~

#### K-6. Owner statements: the 2026-10-24 rule (after :70)

INSERT AFTER the O45 row as K-5 left it (the anchor is the row's first cell, which K-5 does not change). No overlap.

~~~anchor
| O45 waves and parallelism |
~~~
~~~new
| 2026-10-24 never fail (D25), as important as D24: CI replay suite (1)-(4); every later phase merges with it green and adds its fault replay | P1c; P2-P11 acceptance (this sync) | - |
~~~

#### K-7. Contradictions: C12, Hook Discipline #5 against DT4 (:132)

INSERT AFTER (after the C11 row). No overlap.

~~~anchor
| C11 | DECISIONS D4 vs PLAN S1/P5 |
~~~
~~~new
| C12 | CLAUDE.md:98 at d625284 (Hook Discipline #5) vs register DT4, D25 | #5 lets ordinary /dev recovery record a lane or cycle as blocked/incomplete and "terminate honestly"; the owner: "诚实终态永远不允许" (teachings:103); P1c requirement (3), no dead end | P9 rewrites #5 under D20 and D23 (P9 D2 bullet, row 16, acceptance 16); Lesson 16 (:43) stays consistent; P1b and P1c do not edit CLAUDE.md |
~~~

#### K-8. Dependencies table: P1b and P1c (:179)

INSERT AFTER (after the P8 row). No overlap.

~~~anchor
| P8 | 2 with P1 | P0, P7 | W2, P0+P7 | yes |
~~~
~~~new
| P1b | 2b alone (2026-10-24) | P1, P8, P7b (merge titles; P7b's land script; P8's deletions; green CI) | section 15 after this sync | yes |
| P1c | 2c alone (2026-10-24) | P1b, P8, P7b (merge titles; P8's hermetic conftest) | section 15 after this sync | yes |
~~~

#### K-9. Dependencies table: P2 (:180)

REPLACE. No overlap.

~~~anchor
| P2 | 3 with P3, merges first | P1, P8 (merge titles, P1 files, stop-completion-gate gone) | W3, P1+P8 | yes |
~~~
~~~new
| P2 | 3 with P3, merges first | P1, P8, P7b, P1b, P1c (merge titles, P1 files, stop-completion-gate gone, P1c's suite) | W3, P1+P8+P7b+P1b+P1c | yes after this sync |
~~~

#### K-10. Dependencies table: P3 (:181)

REPLACE. No overlap.

~~~anchor
| P3 | 3 with P2, merges second | P1, P8 (+ ba-qa schema, canonical_task_id, STUB) | W3 | yes |
~~~
~~~new
| P3 | 3 with P2, merges second | P1, P8, P7b, P1b, P1c (+ ba-qa schema, canonical_task_id, STUB, P1c's suite) | W3 | yes after this sync |
~~~

#### K-11. Dependencies table: P9-P11 (:185)

REPLACE. No overlap.

~~~anchor
| P9, P10, P11 | not written | P9: P6+P8; P10: P9; P11: every PR merged | W7-W9 | P6 states P9 waits for it |
~~~
~~~new
| P9, P10, P11 | written 2026-10-19 (COVERAGE-P9-P11.md) | P9: P6+P8; P10: P9; P11: every PR merged; each also lists P1b and P1c after this sync | W7-W9 | P6 states P9 waits for it |
~~~

#### K-12. New section (e) at the end of the file (:286)

INSERT AFTER (the last line of the file). No overlap.

~~~anchor
   is written for a separate session that never merges its own PR.
~~~
~~~new

## (e) Addendum 2026-10-24: P1b and P1c

Inputs: prompts/P1b.md and prompts/P1c.md (each ends with prompts/_common.md byte for byte), inventory/ (the d625284
map), audit/2026-10-23/, reviews/P1b-plan-sync.md.

| Owner requirement | Delivered by | Test |
|---|---|---|
| D24: one producer, at least one consumer, consumers trust one conclusion | P1b Goals 1-4, scope rows 0-18, E1-E14 | P1b acceptance 3, 6, 10-13 |
| D24: proved every time, no hand list | P1b Goal 5, row 19 (CI check, trace runner, ten compliant drivers) | P1b acceptance 2, 3 |
| D25 (1) ten pipelines compliant, 0 blocks, 0 hook errors | P1c Goal 1, row 2, "The suite" (1): 16 scenarios in 2 settings modes | P1c acceptance 3 |
| D25 (2) faults return to their producer, next round passes, zero human action | P1c rows 3 and 7-17; F1, F1q (missing), F2, F2j, F2g (malformed), F3a, F3q, F3b (old version, E1), F4, F4c, F4s (index.lock), F5, F5f (interrupted), F6, F6o (usage limit, X8), F7, F7b (fan-out lane), each in 2 modes | P1c acceptance 4 |
| D25 (3) no dead end apart from /stop | P1c X6, row 4 (block sites enumerated at test time; classes G, D, H, U) | P1c acceptance 5 |
| D25 (4) a regression replay per fixed defect | P1c row 5: R-P1, R-E1, R-N1 (X9, row 20), R-V1 (X7, row 14) | P1c acceptance 6 |
| D25 merge rule | P1c "Merge rule from P1c on", row 6 (fault-coverage step); P2-P11 acceptance items (this sync) | P1c acceptance 8; each later PR |
| Earlier words CC4, CC8, DT2, DT3, DT4, HC2 | P1c "Owner decisions" (quoted with sources); DT4 against CLAUDE.md #5: P9 (C12) | P9 acceptance 16 |

What moved from later phases into P1b and P1c: PLAN-v2 section 15; each later prompt's "P1b and P1c" block names its
share.

Found while syncing:
- N1, V1-1 and NV-1 have no record in the repository at d625284 or under harness-repair-plan/ at dac09ec9; P1c
  reproduces them from their descriptions (X9, R-V1).
- docs/reference/paseo-daemon-teachings-20260910.md, the source of CC8, DT4 and HC2, is deleted on P8's branch; P1c reads
  it with `git show d625284:`.
- audit/2026-10-23/report-zh.md section 4 item 5 suggests giving the 13 artifacts with no owning phase to P9 or P10; P1b's
  rows own them now. report-zh.md is a dated audit record and is not edited.
- P1b and P1c both name the obligation-sourced overnight schema (P1b rows 6 and 13 through E13; P1c row 13) and G2's
  plain exit 2 (P1b row 3; P1c row 7). P1b lands first; P1c re-verifies on its base and adds only the replay ("A defect
  P1b or P8 already closed needs only its replay", P1c "Before you start").
~~~

---

## File: prompts/P2.md (5 edits)

#### P2-1. "Before you start" (:62)

REPLACE. No overlap.

~~~anchor
**Before you start.** Start only after P1, P8 and P7b are merged.
~~~
~~~new
**Before you start.** Start only after P1, P8, P7b, P1b and P1c are merged.
~~~

#### P2-2. Merge titles and P1c's suite (:66)

REPLACE. No overlap.

~~~anchor
  `P8: …` and `P7b: …`.
~~~
~~~new
  `P8: …`, `P7b: …`, `P1b: …` and `P1c: …`.
- P1c's replay suite is in the tree and green: `git ls-tree -r --name-only origin/master -- tests/replay` lists
  test_pipelines.py, test_faults.py, test_no_dead_end.py and test_regressions.py (or the names P1c's PR gives), and the
  latest CI run on origin/master is green.
~~~

#### P2-3. The stop message (:71)

REPLACE. No overlap.

~~~anchor
wave 3 starts only after P1, P8 and P7b are merged
~~~
~~~new
wave 3 starts only after P1, P8, P7b, P1b and P1c are merged
~~~

#### P2-4. The P1b and P1c block (before :76)

INSERT BEFORE. Overlap: corrections.md 3.1's row-4 text ("The lane-completeness hook is the canonical aggregate's only
producer ...") is superseded by P1b E5's result; its row 9, row 11 and new D24 acceptance items are delivered by P1b
and P1c as the block says. corrections.md 3.1's Goal 7 / row 17 arming condition is met by P1b row 3 and P1c row 7.

~~~anchor
## Goal
~~~
~~~new
**P1b and P1c (merged before you, 2026-10-24).** P1b applied D24 to every harness artifact (one producer, at least one
consumer and one deciding rule each; checks only at the producer's stop, G1 and G3; no filename-to-role table) and added
a CI check that derives the artifact graph at test time. P1c turned the owner's rule of 2026-10-24 (D25: "永远不能失败！
每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！") into the CI replay suite under tests/replay/. For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact: the check sits at that artifact's
  producer stop, at dispatch (G1) or at collection (G3), and the artifact keeps one producer and one deciding consumer.
  A row that would add a second producer, a second deciding consumer or a consumer-side re-check is dropped and listed
  under "Corrections to PLAN-v2". P1b's CI check stays green.
- Already done (verify each on your base and do not redo it; where a P1b experiment took the other outcome, follow
  P1b's PR): the canonical aggregate's one producer (P1b E5) and the aggregate-pending writer's removal; closeout's
  harness-report.json writer; the /tmp continuation sentinel (row 9); the cycle contract's one writer and one path, no
  launcher seed, no in-place mutation, and the schema of obligation-bearing entries read from the dispatch obligation,
  with the file check's "or escalate" text gone (P1b E13, P1c rows 13 and 19; rows 11-13 and 15 keep what is left;
  TC-35 as corrected); G2's failing stop is a plain exit 2 with no ESCALATION_ACK admission (P1b row 3, P1c row 7).
- Arming: if P1c's X3 already set `CLAUDE_OBLIGATION_STOPGATE` to block, your arming commit (row 17) adds only
  `CLAUDE_OBLIGATION_GATE` and `CLAUDE_OBLIGATION_BARRIER`, and acceptance 13's count of 3 still holds. P1b's E4 list
  (the faults the consumer-side checks it deleted used to stop, with the gate that stops each once armed) is an input of
  your armed replay (acceptance 14).
- Merge rule: your PR merges only with P1c's suite green and with a fault replay for each process class you change
  (acceptance 19). The D20 unattended-decision replay is your overnight fault replay (P1c's compliant overnight scenario
  carries no producer question). In P1c's no-dead-end check the AskUserQuestion deny is a D site (the pipeline completes
  without the call) and the time-lock an H site.

~~~

#### P2-5. Acceptance 19 (after :748)

INSERT AFTER. Overlap: corrections.md 3.1 adds a "New acceptance" (the D24 table) at the end; if it is applied first,
this item takes the next number and P2-4's "(acceptance 19)" follows it.

~~~anchor
    net lines (added minus deleted) <= +210.
~~~
~~~new
19. **Never fail (D25; P1c merge rule).** The P1c replay suite stays green on this PR's head, and this PR adds the
    fault replay for each process class it changes. Run the suite's full set and P1c's fault-coverage step on your
    branch and paste the four summary tables and the step's output. Expected here: the D20 unattended-decision replay,
    the overnight launch and time-lock in every timezone, the cycle contract, the AskUserQuestion deny, the landing
    route's summary and the armed settings each lie on a fault replay's path; a pipeline whose shape you change has its
    scenarios updated in the same commit (TC-54).
~~~

---

## File: prompts/P3.md (6 edits)

#### P3-1. "Before you start" (:65)

REPLACE. No overlap.

~~~anchor
**Before you start.** Start only after P1, P8 and P7b are merged.
~~~
~~~new
**Before you start.** Start only after P1, P8, P7b, P1b and P1c are merged.
~~~

#### P3-2. Merge titles and P1c's suite (:69)

REPLACE. No overlap.

~~~anchor
  `P8: …` and `P7b: …`.
~~~
~~~new
  `P8: …`, `P7b: …`, `P1b: …` and `P1c: …`.
- P1c's replay suite is in the tree and green: `git ls-tree -r --name-only origin/master -- tests/replay` lists
  test_pipelines.py, test_faults.py, test_no_dead_end.py and test_regressions.py (or the names P1c's PR gives), and the
  latest CI run on origin/master is green.
~~~

#### P3-3. The stop message (:77)

REPLACE. No overlap.

~~~anchor
wave 3 starts only after P1, P8 and P7b are merged
~~~
~~~new
wave 3 starts only after P1, P8, P7b, P1b and P1c are merged
~~~

#### P3-4. "Branch and pull request" dependencies (:738)

REPLACE. No overlap.

~~~anchor
- Dependencies: start only after P1 and P8 are merged
~~~
~~~new
- Dependencies: start only after P1, P8, P7b, P1b and P1c are merged
~~~

#### P3-5. The P1b and P1c block (before :84)

INSERT BEFORE. Overlap: corrections.md 3.2 rewrites row 1 as the declaring-dispatch reader, deletes rows 7-9 and the
escalation-gap acceptances, and adds a D24 acceptance and an AskUserQuestion experiment; P1b delivers the reader and the
D24 table, and P1b row 3 / P1c row 7 delete the escalation stores. Where a corrections.md row would build what P1b
built, P1b's result wins and the row consumes it.

~~~anchor
## Goal
~~~
~~~new
**P1b and P1c (merged before you, 2026-10-24).** P1b applied D24 to every harness artifact (one producer, at least one
consumer and one deciding rule each; checks only at the producer's stop, G1 and G3; no filename-to-role table) and added
a CI check that derives the artifact graph at test time. P1c turned the owner's rule of 2026-10-24 (D25: "永远不能失败！
每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！") into the CI replay suite under tests/replay/. For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact: the check sits at that artifact's
  producer stop, at dispatch (G1) or at collection (G3), and the artifact keeps one producer and one deciding consumer.
  A row that would add a second producer, a second deciding consumer or a consumer-side re-check is dropped and listed
  under "Corrections to PLAN-v2". P1b's CI check stays green.
- Already done (verify each on your base and do not redo it; where a P1b experiment took the other outcome, follow
  P1b's PR): the declaring-dispatch reader in hooks/lib/obligation.py (P1b E3; your row 1 as corrections.md rewrites it
  is consumed, not built, and its replay proof is P1b's acceptance 7); the G2 escalation stores, their admission and the
  arbitration path (P1b row 3, P1c row 7: G2's failing stop is a plain exit 2 naming the artifacts, and ESCALATION_ACK
  releases nothing); journal-view and G2's deferred-checks write; the completion report leaving the resolver's required
  chain; consumers importing obligation.TERMINAL_VOCABULARY, the replay window's private terminal set included (your
  replay-window row keeps the 60 s window, S8); BA's write permission on ba-qa-report; the aggregate's blocked
  canonical and its third status vocabulary (P1c row 11); the resolver's fan-out optional-parent read (P1c row 12,
  which the disposition keeps). corrections.md's D24 acceptance for P3 is answered by P1b's D24 table: your PR lists
  only the artifacts your rows still change.
- The disposition is the one chain function P1b left (scripts/resolve-dev-artifact-chain.py, P1b row 7): every consumer
  calls it and nothing you add re-derives part of it; the lane roster is checked at G3 (P1b row 6).
- Merge rule: your PR merges only with P1c's suite green and with a fault replay for each process class you change
  (acceptance 18).

~~~

#### P3-6. Acceptance 18 (after :689)

INSERT AFTER. Overlap: corrections.md 3.2 deletes acceptance 10 and adds a D24 acceptance at the end; renumber this
item to the next free number and follow it in P3-5's "(acceptance 18)".

~~~anchor
    deleted) <= -50.
~~~
~~~new
18. **Never fail (D25; P1c merge rule).** The P1c replay suite stays green on this PR's head, and this PR adds the
    fault replay for each process class it changes. Run the suite's full set and P1c's fault-coverage step on your
    branch and paste the four summary tables and the step's output. Expected here: one fault replay per disposition
    stage (dev, close, commit) whose gap names the artifact and the failing check and is cleared by the next round of
    the dispatch the declaring-dispatch reader returns, and the S7 collection checks you promote.
~~~

---

## File: prompts/P4.md (5 edits)

#### P4-1. "Before you start" (:30)

REPLACE. Overlap: corrections.md 3.3 (:35-41) deletes the continue-cycle.md and ROLE_BY_ARTIFACT checks a few lines
below; no textual overlap.

~~~anchor
**Before you start.** Start only after P1, P8, P7b, P2 and P3 are merged.
~~~
~~~new
**Before you start.** Start only after P1, P8, P7b, P1b, P1c, P2 and P3 are merged.
~~~

#### P4-2. Merge titles and P1c's suite (:34)

REPLACE. No overlap.

~~~anchor
  `P8: …`, `P7b: …`, `P2: …` and `P3: …`.
~~~
~~~new
  `P8: …`, `P7b: …`, `P1b: …`, `P1c: …`, `P2: …` and `P3: …`; P1c's replay suite (tests/replay/) is green in the latest
  CI run on origin/master.
~~~

#### P4-3. The stop message (:43)

REPLACE. No overlap.

~~~anchor
P4 starts only after P1, P8, P7b, P2 and P3 are merged
~~~
~~~new
P4 starts only after P1, P8, P7b, P1b, P1c, P2 and P3 are merged
~~~

#### P4-4. The P1b and P1c block (before :68)

INSERT BEFORE. Overlap: corrections.md 3.3's "New goal and acceptance (D24)" (L17, L18, L22, L23, L28, L31, L32, L40,
L41, L42, L53) is delivered by P1b's D24 table; do not add it as written. Its row 2 and row 5 items (registry name from
the disposition; no successor table) agree with P1b rows 1 and 10.

~~~anchor
## Goal
~~~
~~~new
**P1b and P1c (merged before you, 2026-10-24).** P1b applied D24 to every harness artifact and added a CI check that
derives the artifact graph at test time; P1c's CI replay suite (tests/replay/) enforces the owner's rule of 2026-10-24
(D25: "永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"). For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact (one producer, one deciding consumer,
  checks only at the producer's stop, G1 and G3); a row that would add a second decider or a consumer-side re-check is
  dropped and listed under "Corrections to PLAN-v2". P1b's CI check stays green.
- Already done by P1b (verify each on your base and do not redo it): /close's and /commit's class-b/c re-checks (the
  aggregator re-runs at /close Step 0 and /commit row 1, /close's schema gate and Step 0 verdict layer, /commit Step 3's
  accepted-line list, Step 5's second resolver run, the commit-QA cross-check and the status re-parse); both routing
  tables and their "no code table" claims; the close-force flag readers; /close's QA re-arming of the enforce flags;
  the overnight loop's terminal lanes (the deletion half of TC-13); the advisory jsonl sinks (P1b E12; your row 9); one
  channel per verdict (P1b E11); the D24 table for L17, L18, L22, L23, L28, L31, L32, L40, L41, L42 and L53 (your PR
  lists only the artifacts your rows still change). P1c fixed the close.md and commit.md lines a hook refused (its
  row 18): keep those fixes. Your rows keep what is left: one disposition call per consumer, dispatching again each
  gap's declaring dispatch (D7, D21), the waits as in-turn questions (D23), the native rating and the reset's print
  rule.
- Merge rule: your PR merges only with P1c's suite green and with a fault replay for each process class you change
  (acceptance 21).

~~~

#### P4-5. Acceptance 21 (after :617)

INSERT AFTER. Overlap: corrections.md 3.3 adds a D24 acceptance; if applied, renumber and follow it in P4-4.

~~~anchor
    deleted) <= -150.
~~~
~~~new
21. **Never fail (D25; P1c merge rule).** The P1c replay suite stays green on this PR's head, and this PR adds the
    fault replay for each process class it changes. Run the suite's full set and P1c's fault-coverage step on your
    branch and paste the four summary tables and the step's output. Expected here: /close and /commit completing an
    incomplete cycle (a deleted qa-report; a dev-complete but unclosed task under /commit) by dispatching again the
    declaring dispatch, the rating question (Skip records nothing and blocks nothing), and the overnight reset that
    never blocks.
~~~

---

## File: prompts/P5.md (5 edits)

#### P5-1. Merge titles (:43-44)

REPLACE. Overlap: corrections.md 3.4 (:48, :53-54, :64) deletes the continue-cycle.md and ROLE_BY_ARTIFACT checks a
few lines below; no textual overlap.

~~~anchor
  `P8: …`, `P7b: …`, `P2: …`, `P3: …` and `P4: …` (a GitHub merge commit carries the title in its subject or its
  body).
~~~
~~~new
  `P8: …`, `P7b: …`, `P1b: …`, `P1c: …`, `P2: …`, `P3: …` and `P4: …` (a GitHub merge commit carries the title in its
  subject or its body). P1c's replay suite (tests/replay/) is green in the latest CI run on origin/master.
~~~

#### P5-2. The stop message (:58)

REPLACE. No overlap.

~~~anchor
P5 starts only after P1, P8, P7b, P2, P3 and P4 are merged
~~~
~~~new
P5 starts only after P1, P8, P7b, P1b, P1c, P2, P3 and P4 are merged
~~~

#### P5-3. "Branch and pull request" dependencies (:740)

REPLACE. No overlap.

~~~anchor
- Dependencies: start only after P4 (and so P1, P8, P2 and P3) is merged
~~~
~~~new
- Dependencies: start only after P4 (and so P1, P8, P7b, P1b, P1c, P2 and P3) is merged
~~~

#### P5-4. The P1b and P1c block (before :85)

INSERT BEFORE. Overlap: corrections.md 3.4 row 1 (the deny from dispatch records) is P1b E3's mechanism, which P5-a
arms and extends; 3.4 row 2 ("Label the escalation-record deny temporary ...") is superseded: drop that deny (P1c
hand-off). 3.4's new D24 goal (the replay-window terminal set, the todo-file writers L08, the do.status deciders L30,
merge.md's validate-and-unlink L44) is delivered by P1b rows 2, 9, 12 and E7, E8, E11.

~~~anchor
## Goal
~~~
~~~new
**P1b and P1c (merged before you, 2026-10-24).** P1b applied D24 to every harness artifact and added a CI check that
derives the artifact graph at test time; P1c's CI replay suite (tests/replay/) enforces the owner's rule of 2026-10-24
(D25: "永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"). For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact: the gate's predicates call the one chain
  function and read git, and decide nothing a producer-side gate already decided. P1b's CI check stays green.
- Already done (verify each on your base and do not redo it; where a P1b experiment took the other outcome, follow
  P1b's PR): G4's re-validation (stop-obligation-gate.py is already an exit-0 `# STUB:` file, and what is left of
  `find_unresolved_dispatch_obligations` is what the declaring-dispatch reader needs; row 11 deletes the rest); the
  todo-file writers and the bookmark mutations (P1b E7; if it shipped `command_span.calls()` and `last_todos()`, rows 18
  and 20 consume them); the separate do.status deciders and the do-report's one writer (P1b E8; rows 15 and 21 build on
  it); merge.md Step 3's validate-and-unlink (P1b E11); the D8 write permission derived from the session's dispatch
  records (P1b E3, TC-20 as corrected): row 1 arms and extends that mechanism and builds no table; the guard's quoted
  `-F` read (P1b correction 5; row 4 keeps the fix). Row 2's deny of the G2 escalation records has nothing left to deny
  (P1b row 3, P1c row 7): drop it and count it among the retired rules. Gate 4 accepts a recovery resume (P1c row 16):
  row 18's rewrite keeps that rule.
- Every block site you add fits a class of P1c's no-dead-end check (its X6, enumerated at test time): a gap block is
  cleared by the actor's next compliant step (G); a deny names the forbidden operation and the pipeline completes
  without it (D); only the gate's and the launcher's instrument-failure block waits for the human /stop (H, like the
  time-lock's).
- Merge rule: your PR merges only with P1c's suite green and with a fault replay for each process class you change
  (acceptance 25).

~~~

#### P5-5. Acceptance 25 (after :686)

INSERT AFTER. Overlap: corrections.md 3.4 adds a D24 goal with its acceptance; if applied, renumber and follow it in
P5-4.

~~~anchor
    deleted) <= -700.
~~~
~~~new
25. **Never fail (D25; P1c merge rule).** The P1c replay suite stays green on this PR's head, and this PR adds the
    fault replay for each process class it changes. Run the suite's full set and P1c's fault-coverage step on your
    branch and paste the four summary tables and the step's output. Expected here: per gated command, a Stop blocked
    with its gaps named and released by the next compliant step; the instrument-failure block released by /stop; a
    foreign write denied by the D8 deny; a /do whose file lists differ from its write set; P5-c's todo fold.
~~~

---

## File: prompts/P6.md (5 edits)

#### P6-1. "Before you start" (:30)

REPLACE. Overlap: corrections.md 3.5 (:41-46) rewrites the table-derived-deny prerequisite a few lines below; no
textual overlap.

~~~anchor
**Before you start.** Start only after P1, P8, P7b, P2, P3, P4 and P5 are merged.
~~~
~~~new
**Before you start.** Start only after P1, P8, P7b, P1b, P1c, P2, P3, P4 and P5 are merged.
~~~

#### P6-2. Merge titles and P1c's suite (:34)

REPLACE. No overlap.

~~~anchor
  `P8: …`, `P7b: …`, `P2: …`, `P3: …`, `P4: …` and `P5: …`.
~~~
~~~new
  `P8: …`, `P7b: …`, `P1b: …`, `P1c: …`, `P2: …`, `P3: …`, `P4: …` and `P5: …`; P1c's replay suite (tests/replay/) is
  green in the latest CI run on origin/master.
~~~

#### P6-3. The stop message (:46)

REPLACE. No overlap.

~~~anchor
P6 starts only after P1, P8, P7b, P2, P3, P4 and P5 are merged
~~~
~~~new
P6 starts only after P1, P8, P7b, P1b, P1c, P2, P3, P4 and P5 are merged
~~~

#### P6-4. The P1b and P1c block (before :77)

INSERT BEFORE. Overlap: corrections.md 3.5 "correction 1" (agent-index readers take the cycle from the agent's own
obligation) and its new D24 acceptance ("which files this dev wrote") meet P1b correction 3 and E6: P1b's result wins,
and P6's PR records what E6 left.

~~~anchor
## Goal
~~~
~~~new
**P1b and P1c (merged before you, 2026-10-24).** P1b applied D24 to every harness artifact and added a CI check that
derives the artifact graph at test time; P1c's CI replay suite (tests/replay/) enforces the owner's rule of 2026-10-24
(D25: "永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"). For this phase:
- P1b's map governs every row below that adds or keeps a check on an artifact (one producer, one deciding consumer,
  checks only at the producer's stop, G1 and G3). P1b's CI check stays green.
- P1b's E6 already chose the one producer of "which files this dev wrote" and of the baseline, and removed the other
  producer and every rule that compared the two (the G2 ledger wire, the aggregator union, the adjudicator's
  comparison). A3.a builds on E6's outcome: G2 at dev's stop is the one deciding consumer, and you add no second
  producer and no second comparison; if E6 left the dev report without a self-reported file list, A3.a's "declared
  versus written" check shrinks to what E6 left, and the PR says so.
- All agent-index consumers already take agent_resolver's one conclusion (P1b correction 3), so A4.a changes only the
  role input. The D8 deny is P1b E3's mechanism as P5 armed it; per-role tool-policy prefixes that named declared
  artifacts may be gone (E3), and correction 11 applies to the rows left.
- Merge rule: your PR merges only with P1c's suite green and with a fault replay for each process class you change
  (acceptance 19).

~~~

#### P6-5. Acceptance 19 (after :659)

INSERT AFTER. Overlap: corrections.md 3.5 adds two acceptances (/redev, D24); if applied, renumber and follow it in
P6-4.

~~~anchor
    deleted) <= +100.
~~~
~~~new
19. **Never fail (D25; P1c merge rule).** The P1c replay suite stays green on this PR's head, and this PR adds the
    fault replay for each process class it changes. Run the suite's full set and P1c's fault-coverage step on your
    branch and paste the four summary tables and the step's output. Expected here: a dev report that lists a file it
    did not write and one that omits a file it wrote (blocked at dev's stop after the promotion commit, cleared by that
    dev's rewrite), a syntax-broken harness hook (F3.a), and a grant claimed by the wrong role.
~~~

---

## File: prompts/P9.md (10 edits)

#### P9-1. "Before you start" (:45)

REPLACE. Overlap: corrections.md 3.6 (:52) deletes the continue-cycle.md check a few lines below; no textual overlap.

~~~anchor
**Before you start.** Start only after P7b, P1, P8, P2, P3, P4, P5 and P6 are merged.
~~~
~~~new
**Before you start.** Start only after P7b, P1, P8, P1b, P1c, P2, P3, P4, P5 and P6 are merged.
~~~

#### P9-2. Merge titles and P1c's suite (:49)

REPLACE. No overlap.

~~~anchor
  `P1: …`, `P8: …`, `P2: …`, `P3: …`, `P4: …`, `P5: …` and `P6: …`.
~~~
~~~new
  `P1: …`, `P8: …`, `P1b: …`, `P1c: …`, `P2: …`, `P3: …`, `P4: …`, `P5: …` and `P6: …`; P1c's replay suite
  (tests/replay/) is green in the latest CI run on origin/master.
~~~

#### P9-3. The stop message (:59)

REPLACE. No overlap.

~~~anchor
after those eight PRs are merged.
~~~
~~~new
after those ten PRs are merged.
~~~

#### P9-4. "Branch and pull request" dependencies (:602)

REPLACE. No overlap.

~~~anchor
- Dependencies: start only after the PRs titled `P7b: …`, `P1: …`, `P8: …`, `P2: …`,
~~~
~~~new
- Dependencies: start only after the PRs titled `P7b: …`, `P1: …`, `P8: …`, `P1b: …`, `P1c: …`, `P2: …`,
~~~

#### P9-5. Goal 1, one producer per fact (:106-108)

REPLACE. Overlap: corrections.md 3.6 (:109) replaces "beside P3's continue-cycle.md" with "under
templates/prompt-includes/" in this same sentence; this replacement already carries that change, so skip 3.6's :109
item. If 3.6's :109 item was applied already, the anchor's last line reads "... (five include files under
templates/prompt-includes/)." instead; replace that text the same way.

~~~anchor
1. **One producer per fact.** spec_path (prompt-workflow, from the session transcript), doc-sync output (update-only),
   the /do consent check (one reader), the agent roster (one constant), the git global-option table (one table and a
   normaliser), and the shared prompt blocks (five include files beside P3's continue-cycle.md).
~~~
~~~new
1. **One producer per fact.** The runtime artifacts got their one producer in P1b (D24): spec_path, doc-sync output
   (update-only, P1b E9), the /do consent check (one reader) and the agent roster (computed from the stems of
   agents/*.md). You verify them (rows 1, 2, 4, 5) and change code there only where a test fails. You give one producer
   to the facts that are not runtime artifacts: the git global-option table (one table and a normaliser) and the shared
   prompt blocks (five include files under templates/prompt-includes/).
~~~

#### P9-6. Scope: rows 1, 2, 4 and 5 after P1b (:389)

INSERT AFTER. Overlap: corrections.md 3.6 rewrites row 1 (:376, :393: spec blocked at UserPromptSubmit; BA records
spec_path; orchestrator patch and jq builds deleted), row 5 (:397: roster from agents/*.md stems) and adds a D24
acceptance (L01, L24, L51, L44, L42); all agree with what P1b delivered, so they become checks of P1b's result rather
than work.

~~~anchor
Locations are at f8c18c2 with an anchor. "Lines your change makes false" means: find them with grep on your base.
~~~
~~~new

**Rows 1, 2, 4 and 5 after P1b (2026-10-24).** P1b applied D24 to every runtime artifact before you and took this
phase's runtime half: row 1's spec path (decided once at UserPromptSubmit, P1b row 8 and E14; BA records spec_path from
its dispatch line, and the orchestrator's context patches and QA-content writes are gone, E10 and E14), row 2's
creation paths (P1b E9; if E9 deleted creation, row 2 keeps the CLAUDE.md date block, your E9, and /test's copies),
row 4 (one `has_do_consent`, P1b row 9), row 5's roster (computed from the stems of agents/*.md in one hooks/lib
function, P1b row 18; this replaces row 5's literal constant), and the one-writer proofs for L01, L24, L42, L44 and L51
that corrections.md adds as a P9 acceptance (answered by P1b's D24 table). For these rows run acceptances 3, 4, 5 and 7
against P1b's result, change code only where one fails, and do the prose pass. Rows 6 and 7 and the prose rows stay
yours. P1b's artifact map and CI check govern every row that adds or keeps a check on an artifact.
~~~

#### P9-7. Owner decisions, D2 bullet: Hook Discipline #5 (:163)

REPLACE. Overlap: corrections.md 3.6 (:165-166) appends to the D3/S1 bullet two lines below; no textual overlap. This
carries the sync-list entry for P9.

~~~anchor
  needs_clarification and a hook rejection are process steps. Hook Discipline #5 is rewritten accordingly.
~~~
~~~new
  needs_clarification and a hook rejection are process steps. Hook Discipline #5 ("Ordinary `/dev` recovery has an
  honest terminal branch", CLAUDE.md:98 at d625284; find it by that text) conflicts with the owner's "诚实终态永远不允许"
  ("an honest terminal state is never allowed"; register DT4, teachings:103) and with D25's "no dead end apart from the
  owner's /stop" (the owner's rule of 2026-10-24, P1c's requirement (3)): rewrite it under D20 and D23 (row 16).
~~~

#### P9-8. Row 16 (CLAUDE.md): the #5 rewrite (:408)

REPLACE (part of row 16's Change cell). Overlap: corrections.md 3.6 (:408, row 16) replaces the row's "added CLAUDE.md
line" and adjusts :60; different sentences of the same cell; apply both.

~~~anchor
#5 rewritten: one terminal, complete; a producer question is relayed in-turn; the cycle stays incomplete and the same role resumes after the answer (D2, D3); Lesson 16's wording stays consistent with it.
~~~
~~~new
#5 rewritten under D20 and D23 (DT4: "诚实终态永远不允许"; D25): no honest, blocked or incomplete terminal branch and no "terminate honestly"; one terminal, complete; outside /dev-overnight a needed owner decision is one specific in-turn AskUserQuestion (the pause, D23), which releases no gate, and the same role resumes after the answer; inside /dev-overnight nobody is asked: the decision is made by experiment, else by the question's preset default, and recorded in "Decisions made without the owner" (D20); a recovery that cannot resume re-dispatches the lane through the ordinary pipeline and never ends it (D2); Lesson 16's "Scope & terminal branch" paragraph (:43) and its #4/#5 reference stay consistent with it.
~~~

#### P9-9. Acceptance 16: grep for the old #5 wording (:526)

REPLACE. Overlap: corrections.md 3.6 (:527, acceptance 16) replaces the CLAUDE_COMMAND_GATE grep in the same item;
apply both.

~~~anchor
    terminal|output a \*\*REQUEST\*\*' CLAUDE.md` -> nothing;
~~~
~~~new
    terminal|terminate honestly|blocked/incomplete|output a \*\*REQUEST\*\*' CLAUDE.md` -> nothing;
~~~

#### P9-10. Acceptance 23 (after :555)

INSERT AFTER. Overlap: corrections.md 3.6 adds a D24 acceptance; if applied, renumber.

~~~anchor
    deleted) <= -900.
~~~
~~~new
23. **Never fail (D25; P1c merge rule).** The P1c replay suite stays green on this PR's head, and this PR adds the
    fault replay for each process class it changes. Run the suite's full set and P1c's fault-coverage step on your
    branch and paste the four summary tables and the step's output. Prose-only changes need no fault replay, but every
    command or agent template a driver extracts keeps its scenarios green; code changes (the normaliser and option
    table, the scoring retirement, the E2 change if any) each lie on a fault replay's path.
~~~

---

## File: prompts/P10.md (6 edits)

#### P10-1. Merge titles and P1c's suite (:38)

REPLACE. Overlap: corrections.md 3.7 (":11-12, :37-38") asks to re-check this bullet's merge-title checks against the
rewritten P3; apply both.

~~~anchor
  `P1: …`, `P8: …`, `P2: …`, `P3: …`, `P4: …`, `P5: …`, `P6: …` and `P9: …`.
~~~
~~~new
  `P1: …`, `P8: …`, `P1b: …`, `P1c: …`, `P2: …`, `P3: …`, `P4: …`, `P5: …`, `P6: …` and `P9: …`; P1c's replay suite
  (tests/replay/) is green in the latest CI run on origin/master.
~~~

#### P10-2. The stop message (:46)

REPLACE. No overlap.

~~~anchor
P10 starts only after P7b, P1, P8, P2, P3, P4, P5, P6 and P9 are
~~~
~~~new
P10 starts only after P7b, P1, P8, P1b, P1c, P2, P3, P4, P5, P6 and P9 are
~~~

#### P10-3. "Branch and pull request" dependencies (:753)

REPLACE. No overlap.

~~~anchor
- Dependencies: start only after P7b, P1, P8, P2, P3, P4, P5, P6 and P9 are merged
~~~
~~~new
- Dependencies: start only after P7b, P1, P8, P1b, P1c, P2, P3, P4, P5, P6 and P9 are merged
~~~

#### P10-4. "What earlier phases left to you": P1b and P1c (before :54)

INSERT BEFORE. Overlap: corrections.md 3.7 adds an artifact-level goal (":84-96 (Goal)", experiment 9 for all ten
pipelines) and "New gap rows" (L26, L27, L06, L36, L18, L21, L56, L25, L54, plus L39). Do not add the goal as written:
P1b's CI check replaces it (prompts/P1b.md, "Corrections to PLAN-v2", item 2). Of the gap rows, all but L39 (the
bulk-commit chain, which waits for P4) are P1b's and P1c's; this bullet turns them into checks.

~~~anchor
- P2: `--cycle-reset` as a loop-gate bypass (V9c);
~~~
~~~new
- P1b (D24): its PR's dead-artifact list (acceptance 10) with reachability proofs, its "Out of scope, found" items, and
  the registered hook files it emptied to `# STUB:` stubs (if any). What P1b deleted is not yours to delete again. Its
  CI check (one producer, at least one consumer and one deciding rule per artifact, derived at test time) stays green
  and is the artifact-level goal: corrections.md's artifact-level goal and its experiment-9 table for this phase are
  replaced by it, and you keep file-level D17. corrections.md's new gap rows for this phase that P1b's rows cover
  (journal-view L26, aggregate-pending L27, workflow-history L06, the close-force readers L36, the superseded-<task>/
  branch L18, the dead terminal-vocabulary branches L21, the qa-input reader L56, the G2 escalation stores L25, the
  advisory writers L54): check each is gone on your base; one still there is deleted with its proof, and the PR names
  the phase that left it. The bulk-commit chain (L39) stays your row.
- P1c: the replay suite with its fault-coverage step (it stays green; acceptance 25) and P1c's "Out of scope, found".
~~~

#### P10-5. "Dead code (D17)": leave out P1b's deletions (:475)

INSERT AFTER. No overlap.

~~~anchor
users to run a file makes it live (installers, hooks/QUICKSTART.md and hooks/.env.example for hooks/install.sh).
~~~
~~~new
Leave out every subject P1b's or P1c's PR already deleted with its reachability proof. For a file P1b kept as the one
producer or consumer of an artifact, P1b's map names its reader, and the file is unreachable only if that reader is.
~~~

#### P10-6. Acceptance 25 (after :718)

INSERT AFTER. No overlap.

~~~anchor
    any, its log line and the stash list before and after.
~~~
~~~new
25. **Never fail (D25; P1c merge rule).** The P1c replay suite stays green on this PR's head, and this PR adds the
    fault replay for each process class it changes. Run the suite's full set and P1c's fault-coverage step on your
    branch and paste the four summary tables and the step's output. Expected here: the stub retirement (a session whose
    loaded hook list still names a retired path), a recoverable `git rm` and a refused forced one, and a product
    repository left clean after the pipelines. Deletions are exempt from the coverage step; every scenario stays green
    after them.
~~~

---

## File: prompts/P11.md (3 edits)

#### P11-1. Merge titles (:39)

REPLACE. No overlap.

~~~anchor
  `P1: …`, `P8: …`, `P2: …`, `P3: …`, `P4: …`, `P5: …`, `P6: …`, `P9: …` and `P10: …` (a merge GitHub makes keeps
  the pull request title in the body, not the subject: fe7700c8, 3dfb66a3).
~~~
~~~new
  `P1: …`, `P8: …`, `P1b: …`, `P1c: …`, `P2: …`, `P3: …`, `P4: …`, `P5: …`, `P6: …`, `P9: …` and `P10: …` (a merge
  GitHub makes keeps the pull request title in the body, not the subject: fe7700c8, 3dfb66a3).
~~~

#### P11-2. Dependencies: P1c's suite (:44)

INSERT AFTER. No overlap.

~~~anchor
  exists (`git cat-file -e origin/master:scripts/size-ratchet.py`, or the name P10's PR gives).
~~~
~~~new
- P1c's replay suite (tests/replay/) is green in the latest CI run on origin/master; your PR keeps it green and adds the
  fault replay for the process it changes (acceptance 19).
~~~

#### P11-3. Acceptance 19 (after :730)

INSERT AFTER. Overlap: corrections.md 3.8 replaces acceptances 3-13 with three items; this item still goes after the
last one, with the next free number (follow it in P11-2).

~~~anchor
    agents/changelog-analyst.md` is empty.
~~~
~~~new
19. **Never fail (D25; P1c merge rule).** The P1c replay suite stays green on this PR's head, and this PR adds the
    fault replay for each process class it changes. Run the suite's full set and P1c's fault-coverage step on your
    branch and paste the four summary tables and the step's output. Expected here: the landing's new step on a home
    that pulls rewritten history, also under a held index.lock and after a pull that stops, completing at a later turn
    end with no human action (and the pre-push guard's refusal, if corrections.md's P11 rewrite applies); R-N1 and R-V1
    stay green. The rewrite script outside the repository is not part of the suite.
~~~

---

## Counts

| File | Edits |
|---|---|
| PLAN-v2.md | 31 |
| DECISIONS.md | 3 |
| HANDOVER.md | 10 |
| COVERAGE.md | 12 |
| prompts/P2.md | 5 |
| prompts/P3.md | 6 |
| prompts/P4.md | 5 |
| prompts/P5.md | 5 |
| prompts/P6.md | 5 |
| prompts/P9.md | 10 |
| prompts/P10.md | 6 |
| prompts/P11.md | 3 |
| total | 101 |

Anchors not placed: none at dac09ec9 (101 of 101 found exactly once, and the edits applied in order to a scratch copy
leave every later anchor unique). Not verified: the P2 and P3 anchors against the refreshed p23 copies, which are not on
the planning branch (see "How to apply"). One anchor changes if corrections.md is applied first: P9-5 (its overlap note
gives the alternative text).

Not in this sync (outside its file list): audit/2026-10-23/report-zh.md section 4 item 5 (the 13 artifacts with no
owning phase, now P1b's), prompts/P7b.md, P8.md and P1.md, README.md. P7b is still absent from PLAN-v2 section 5's table
(section 14 asked for it; COVERAGE fix 13); V-5 points to section 14 instead of adding the row.

## Verification

Run from the planning clone's root at dac09ec9, before any edit is applied. The script reads this file, takes every
`~~~anchor` block under its "## File:" heading and counts its occurrences in that file; every count must be 1.

    python3 -I - harness-repair-plan <<'EOF'
    import re, sys, pathlib
    root = pathlib.Path(sys.argv[1])
    text = (root / "reviews/P1b-plan-sync.md").read_text(encoding="utf-8")
    bad = 0
    for sec in re.split(r"^## File: ", text, flags=re.M)[1:]:
        name = sec.split(" (", 1)[0].strip()
        body = (root / name).read_text(encoding="utf-8")
        for a in re.findall(r"^~~~anchor\n(.*?)\n~~~$", sec, flags=re.M | re.S):
            n = body.count(a)
            if n != 1:
                bad += 1
                print(name, n, repr(a[:70]))
    print("anchors not unique or missing:", bad)
    EOF
