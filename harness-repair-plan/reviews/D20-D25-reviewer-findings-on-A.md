# Reviewer findings on session A's commits 86b7cbc and c728380

Independent review by the reviewer session (four lenses: owner conformance, residual faithfulness, plan-sync application, cross-file consistency; two refuters per finding; 43 kept, 7 dropped). Scope: the plan files outside P1b.md, P1c.md and inventory/, at c728380 (byte-identical at 0cbfbd3). "Origin: drift" marks findings caused by session B's later changes to P1b/P1c. These are claims to re-check against the branch head before applying.


**Review of A's commits 86b7cbc and c728380 (scope: aaf072c..c728380, excluding P1b.md, P1c.md and inventory/)**

The in-scope files are byte-identical at c728380 and 0cbfbd3, so the line numbers below hold at both. "Origin" says whether A's own text caused the problem, or whether B's later commits (2e7d4c0, d22c669 and after) moved P1b or P1c out from under text that matched them at c728380.

## HIGH

**1. Who arms G2, the consumer-side copies left for P2, and P2's G2-hunk fork** (SYNC-1, X1, SYNC-2)
- **Files:** prompts/P2.md, PLAN-v2.md, prompts/P3.md, prompts/P4.md, prompts/P6.md, prompts/P9.md, HANDOVER.md
- **Location:**
  - P2.md: :15, :51-52, :108-111, :147-155 (Goal 7), :223-224, :325 (row 17), :495-498, :547, :661-662, :684-685, acceptance 13 and 14
  - PLAN-v2.md: :104, :172, :174, :181, :357, :368, :442, :1177, :1352
  - P3.md: :49-51, :291 (row 6)
  - P4.md: :43-44, :77
  - P6.md: :39; P9.md: :56; HANDOVER.md: :21
- **Problem:**
  - A's text says P2 arms G1-G3 unless P1c's X3 armed G2, and that P2 may take G2's failing-stop hunk or else merge after P3.
  - At B's head, P1b arms G2 in its last commit (E4, correction 7). It keeps the consumer-side copies whose faults only G1 or G3 stop, and P2's arming commit must delete them. P1b row 19 rule 6 fails CI otherwise. G2's failing stop is already a plain exit 2 (P1b row 3, P1c row 7).
  - Consequence 1: no phase deletes the kept copies (P4 lists them as "Already done by P1b"). Re-checks survive at /close and /commit, against D24 and C2, and P1b's CI check goes red on P2's arming commit.
  - Consequence 2: P2 now never takes a G2 hunk, so Goal 7's literal condition "you do not take the hunk" is always true. P2 would merge after P3, which reverses wave 3 ("P2 first", PLAN-v2:181).
- **Fix:**
  - PLAN-v2.md:174: `It may arm CLAUDE_OBLIGATION_STOPGATE (its X3).` → `P1b arms CLAUDE_OBLIGATION_STOPGATE in its last commit (E4); P1c's X3 arms it only if P1b's merged settings.json left it advisory.`
  - PLAN-v2.md:172: after `...it hands to P1c.` insert `Its last commit arms G2 (CLAUDE_OBLIGATION_STOPGATE=block, E4) and deletes the consumer-side copies whose faults only armed G2 stops; copies whose faults only G1 or G3 stop stay, listed in its PR with their gate, until P2's arming commit deletes them (P1b correction 7).`
  - PLAN-v2.md:104: `G1-G3 arm in P2.` → `G2 arms in P1b's last commit (E4); G1 and G3 arm in P2.`
  - PLAN-v2.md:181: `(its last commit arms G1-G3)` → `(its last commit arms G1 and G3; P1b armed G2)`
  - PLAN-v2.md:357: `If P1c's X3 already set CLAUDE_OBLIGATION_STOPGATE to block, the arming commit adds CLAUDE_OBLIGATION_GATE and _BARRIER only.` → `P1b's E4 (or, if P1b left it, P1c's X3) already set CLAUDE_OBLIGATION_STOPGATE to block, so the arming commit adds CLAUDE_OBLIGATION_GATE and _BARRIER only and, in the same commit, deletes the consumer-side copies P1b's PR lists as kept for faults only G1 or G3 stop.`
  - PLAN-v2.md:368: `The last commit arms G1-G3.` → `The last commit arms G1 and G3 (G2 is armed since P1b's E4, or P1c's X3) and deletes the consumer-side copies P1b's PR lists as kept for them.`
  - PLAN-v2.md:442: `(C5; unless P2 already took this hunk before its arming commit, P2 goal)` → `(C5; delivered by P1b row 3 and P1c row 7; P3 verifies it, and neither P2 nor P3 takes a G2 hunk)`
  - PLAN-v2.md:1352: `P2 keeps arming G1-G3, with P1b's E4 shipped-mode list as its input (G1 and G3 only, if P1c armed G2).` → `P1b arms G2 (E4); P2 arms G1 and G3, with P1b's E4 list as its input, and its arming commit deletes the consumer-side copies E4 kept for them.`
  - PLAN-v2.md:1177: `3 of 3 after P2,` → `1 of 3 after P1b (G2, E4), 3 of 3 after P2,`
  - P2.md:15: `(unless you do not take G2's failing-stop hunk; then you merge after P3 and arm last, Goal 7)` → `(G2's failing-stop path is already a plain exit 2 on your base, P1b row 3 and P1c row 7, so no G2 hunk changes this order)`
  - P2.md:52: `Goal 7 lets you take it, exactly as P3 wrote it, before your arming commit.` → `P1b row 3 and P1c row 7 already made it a plain exit 2; verify it on your base and do not edit it.`
  - P2.md:108: `- Arming: if P1c's X3 already set \`CLAUDE_OBLIGATION_STOPGATE\` to block, your arming commit (row 17) adds only` → `- Arming: P1b's E4 sets \`CLAUDE_OBLIGATION_STOPGATE\` to block in P1b's last commit (P1c's X3 sets it only if P1b left it advisory), so your arming commit (row 17) adds only`
  - P2.md, end of the same bullet, after `is an input of your armed replay (acceptance 14).`: append `The same commit deletes every consumer-side copy P1b's PR lists under "Faults" with G1 or G3 as its gate, close.md and commit.md copies included (P1b E4, correction 7); P1b's CI check (row 19 rule 6) fails on a copy left once its gate blocks, so the deletions and the switches go in one commit and revert as one unit.`
  - P2.md:151-153 (Goal 7): replace `Either take that hunk before the arming commit, or,\n   if you do not take the hunk, merge after P3: merge \`origin/master\` (with P3's G2 change) into your branch, then make\n   the arming commit with all three switches` with `P1b row 3 and P1c row 7 delivered that path and P1b's E4 (else P1c's X3) set STOPGATE to block: verify both on your base and take no G2 hunk; your arming commit adds GATE and BARRIER (STOPGATE only if your base lacks it) and deletes the copies P1b kept for G1 and G3, and the tracked settings.json then holds all three switches`. Keep the trailing reference list.
  - P2.md:325 (row 17): replace the text from `STOPGATE is armed only once` through `(acceptance 13 expects 3).` with `G2's failing-stop path is already a plain exit 2 (P1b row 3, P1c row 7) and STOPGATE is already block on your base (P1b E4 or P1c X3); add it only if your base lacks it. The same commit deletes, in close.md and commit.md, each consumer-side copy P1b's PR lists as kept for G1 or G3 (P1b correction 7). Acceptance 13 expects 3 either way.` In the same cell, make the opening "add GATE, STOPGATE, BARRIER" read "add those of GATE, STOPGATE and BARRIER that your base does not already set".
  - P2.md:495-498: after `list them for P4 under "Out of scope, found"` insert `; a line among them that P1b's PR lists as a copy kept for G1 or G3 is not left: your arming commit deletes it (Arming bullet)`
  - P2.md:547: `holds only the three env keys (row 17)` → `holds the env keys still advisory on your base (row 17) and the deletion of each consumer-side copy P1b's E4 kept for G1 and G3`
  - P2.md:661-662: `every\n  consumer-side check in close.md and commit.md,` → `every\n  consumer-side check in close.md and commit.md except the copies P1b kept for G1 and G3 (your arming commit deletes them),`
  - P2.md:684-685 (DO NOT): after `change paths and the one sentence only` insert `, except that your arming commit deletes each consumer-side copy P1b's PR lists as kept for a fault only G1 or G3 stops (P1b E4, correction 7)`. Insert the same exception at P2.md:223-224, after `fix one sentence arming makes false`.
  - P2 acceptance 13/14: add `On the arming commit P1b's CI check is green, no copy P1b's PR lists for G1 or G3 is left, and a fault replay for each deleted copy shows armed G1 or G3 stopping it and returning it to its producer.`
  - P3.md:49-51: `except G2's\n  failing-stop hunk (row 6), which P2 Goal 7 may take, exactly as you wrote it, before its arming commit; if P2\n  merged first with that hunk, keep master's version of it and build on it.` → `G2's failing-stop path (row 6) included: P1b row 3 and P1c row 7 delivered it; keep master's version and build on it.`
  - P3.md:291 (row 6): replace the text from `G2's failing stop (\`_gate_decide\` :747-830) becomes a plain exit 2` through `(P2 Goal 7; D4, design ruling 3, ledger L25).` with `G2's failing stop (\`_gate_decide\` :747-830) is already a plain exit 2 naming the failing artifacts to their producer, with no escalation record, admission or progress file and no ESCALATION_ACK admission (P1b row 3, P1c row 7): verify it on your base and keep master's version; STOPGATE is armed since P1b E4, or P1c X3 (D4, design ruling 3, ledger L25).`
  - P4.md:77: after `Already done by P1b` insert `(the copies P1b kept for G1 and G3 are deleted by P2's arming commit)`. P4.md:43-44: the parenthetical becomes `(P1b armed G2, P2 armed G1 and G3; ...)`.
  - P6.md:39: `(G2 armed since P2)` → `(G2 armed since P1b, E4)`
  - P9.md:56: the trailing label `(P2)` on the STOPGATE check → `(P1b E4 or P1c X3)`
  - HANDOVER.md:21: `最后一个提交把 G1–G3 从"提醒"改成"拦截"` → `最后一个提交把 G1、G3 从"提醒"改成"拦截"（G2 已由 P1b 的最后一个提交改成拦截），并删掉 P1b 为它们暂留的消费端检查`
- **Confirmations:** 2 for each source finding.
- **Origin:** mostly drift: P1b correction 7 is not in P1b at c728380. The G2-hunk fork (SYNC-2) is A's: c728380's own PLAN-v2:368 already forbids it.

**2. P4 accepts a known /close and /commit dead end** (F1)
- **File:** prompts/P4.md
- **Location:** :609-611 (acceptance 4, the never-dispatched lane-QA case)
- **Problem:**
  - If the reader does not return the lane-QA step, P4 only records the miss under "Out of scope, found" and still merges.
  - That ships a task /close and /commit cannot complete, against D7 (O19 "用户想close一定close完成"), D25 (3) and the P1c merge rule.
  - P1b acceptance 7 already replays this exact /close case as passing, so a miss here is a regression, not something to record.
- **Fix:** replace `if it did not, record the miss under "Out of\n     scope, found" for the declaring-dispatch reader and add no table (D21);` with `if it did not, the case fails and P4 does not merge while /close or /commit cannot complete this task (D7, D25 (3), acceptance 22, the P1c merge rule). If the miss comes from this PR's own changes (close.md, commit.md, scripts/todo/close.py), fix it here and rerun the case. If the reader on your base misses it (P1b E3, P1b acceptance 7; hooks/lib/obligation.py is not in your scope), stop and report the case and the reader's output to the reviewer as a blocker, and rerun the case once the fix is merged at the reader. Add no table and no local workaround (D21);`
- **Confirmations:** 1.
- **Disagreement:** the original fix had P4 edit hooks/lib/obligation.py. The refiner kept P4 inside its own scope (blocker report instead). The refined text is adopted.
- **Origin:** A. The stale reader attribution at P4.md:41/:55/:146/:164/:504 is handled in item 8.

**3. The do-report enum still has `pending`; TC-18 looks up a pending do-report** (X2, SYNC-9)
- **Files:** prompts/P5.md, PLAN-v2.md, prompts/P3.md, prompts/P4.md
- **Location:**
  - P5.md: :96-97, :141, :256, :274, :338 (row 15), :344 (row 21), :660, :670, :770
  - PLAN-v2.md: :55, :84, :574, :576, :591, :952, :957, :1084, :1152, :1182
  - P3.md: :232-233, :339-341, :571-572
  - P4.md: :231, :614
- **Problem:**
  - P1b E8 removes `pending` from schemas/do-report.v1.json. Correction 8 tells P5 to find the unfinished /do task from a hook-written record with no completed do-report.
  - Consequence 1: P5-d would re-add `pending`, a second decider P1b removed.
  - Consequence 2: under E8 (a) no pending do-report ever exists, so `/do <task-id>` (TC-18) never matches.
- **Fix:**
  - P5.md:256: `do-report's enum becomes [pending, completed] (P5-d).` → `do-report's enum becomes [completed] (P5-d drops \`blocked\`; P1b E8 already removed \`pending\`, P1b correction 8).`
  - P5.md:344: replace `S9: the enum becomes \`["pending", "completed"]\`, TERMINAL_VOCABULARY likewise (its drift test keeps them equal)` with `S9: the enum becomes \`["completed"]\` (P1b E8 removed \`pending\`); TERMINAL_VOCABULARY follows because it reads the schema (P1b rows 6 and 18)`. In the same row, `the skeleton message :1434-1437` → `the skeleton message :1434-1437, if E8 (b) kept it`.
  - P5.md:338: `\`docs/dev/do-report-<id>.json\` exists with \`source: "do"\` and \`do.status\` pending` → `the hook-written record P1b's PR names for it (the \`[/do] task-id minted\` line, the sidecar, or under E8 (b) the skeleton) names that task and no do-report of it has \`do.status\` completed (P1b correction 8)`
  - P5.md:660: `Pending report -> rc 2` → `No completed do-report (none written under E8 (a), or under (b) the skeleton with do.status unset) -> rc 2`
  - P5.md:670: `names no pending do-report` → `names no task that the record P1b's PR names shows without a completed do-report`
  - P5.md:96-97: after `(P1b E8;\n  rows 15 and 21 build on it)` insert `; E8 removed \`pending\`, so row 15 and acceptance 5 find an unfinished /do task from the hook-written record P1b's PR names (P1b correction 8)`
  - P5.md:141 `a pending /do task` → `an unfinished /do task`
  - P5.md:274 and :770 `a pending skeleton` → `no completed do-report (under P1b E8 (b), its skeleton)`
  - PLAN-v2.md:55 and :952 `[pending, completed]` → `[completed] (P1b E8 removed pending)`
  - PLAN-v2.md:576: `do.status enum becomes ["pending","completed"]` → `do.status enum becomes ["completed"] (P1b E8 removed pending)`. Reword the "rewrote pending to blocked" rationale so it applies to `blocked` only.
  - PLAN-v2.md:1152: `do-report to "pending"/"completed"` → `do-report to "completed"`
  - PLAN-v2.md:574: `docs/dev/do-report-<id>.json exists with do.status pending` → `a hook-written record names the task and no completed do-report of it exists (P1b correction 8)`
  - PLAN-v2.md:591: `/do pending -> rc 2` → `/do with no completed do-report -> rc 2`
  - PLAN-v2.md:1084 (TC-18): `and the do-report is pending` → `and a hook-written record names that task with no completed do-report of it`; `with no new id or skeleton` → `with no new id (and, under P1b E8 (b), no new skeleton)`
  - PLAN-v2.md:84 and :1182: `a pending task` → `an unfinished task`
  - P3.md:232-233, :339-341, :571-572 and P4.md:231, :614, PLAN-v2.md:957 (Q7): `pending do-report` / `whose do-report is pending` → `no completed do-report`. In P3's fixture, use `no do-report for a hook-minted /do task -> artifact=docs/dev/do-report-<task>.json problem=missing` and keep the `blocked` fixture.
- **Confirmations:** 2.
- **Origin:** drift (P1b correction 8, 2e7d4c0).

**4. P9 row 8 makes permissions "reported" instead of written** (X3)
- **File:** prompts/P9.md
- **Location:** :457 (row 8)
- **Problem:** P1b row 16 now keeps scripts/apply-permissions.sh as the one writer of .claude/settings.json, called by /dev, /dev-command and /dev-overnight, and says no step only reports permissions. P9 would remove that writer and leave the owner a manual step. An unattended overnight session cannot answer the permission prompts that follow (D19, D20).
- **Fix:**
  - Locations column: `dev.md Step 15 :1106-1178 (self-edits settings)` → `dev.md Step 15 :1106-1178 and dev-command.md Step 14 :704-776 (after P1b row 16 they call scripts/apply-permissions.sh; prose only)`
  - Change column: `Step 15 reports suggested permissions instead of editing settings;` → `Step 15 and dev-command.md's Step 14 call scripts/apply-permissions.sh with QA's validated permissions, the one harness writer of \`.claude/settings.json\` P1b row 16 kept: verify that change is on your base and change only prose that says otherwise;`
  - Change column: `dev-overnight.md reports suggested permissions instead of writing them (:1518-1519, L55 settings-derived files).` → `dev-overnight.md keeps its scripts/apply-permissions.sh call (:1518-1519, L55; P1b row 16); no step only reports permissions (D19, D20).`
- **Confirmations:** 2.
- **Origin:** drift (d22c669; at c728380 P1b row 7 said "permissions are reported, not written").

**5. P9 turns the /dev fallback block into "re-run the command"** (X4)
- **File:** prompts/P9.md
- **Location:** :457 (row 8), :454 (row 5)
- **Problem:** P1b row 1 replaced these blocks: the orchestrator uses the task_id the hook recorded, or else calls the hook's start function, and never has the owner type the command again (P1b acceptance 14). P9 would bring back a human step that D19 and D25 (2) forbid.
- **Fix:**
  - P9.md:457: `The whole fallback block (dev.md:196-218, dev-command.md:142-150) becomes "re-run the command"` → `The fallback block (dev.md:196-218, dev-command.md:141-163) is what P1b row 1 left: the orchestrator uses the task_id the hook recorded at this command's start (the session-keyed bookmark, or the record P1b's E7 moved that field to), else it calls the hook's own start function; never a registry picked by name or age and never the owner typing the command again. Verify it against P1b acceptance 14 and change only prose that still says otherwise`. Keep the rest of the sentence.
  - P9.md:454: `The prose fallback loops become "re-run the command" (or go, if P6's option made the registry sentinels inert).` → `The prose fallback loops follow P1b row 1 (the recorded id, else the hook's start function; no re-typed command and no human action), or go if P6's option made the registry sentinels inert.`
- **Confirmations:** 2.
- **Origin:** drift (at c728380, P1b row 1 itself said "re-run the command").

**6. P9 keeps obligation.ROLES, PRODUCER_ROLES and ENFORCED_AGENT_TYPES and adds a test on ROLES** (X5)
- **Files:** prompts/P9.md, prompts/P6.md, prompts/P3.md
- **Location:** P9.md:427, :454 (row 5), :548-549 (acceptance 7); P6.md:343-344; P3.md:295
- **Problem:** P1b row 18 deletes all three lists, and P1b row 19 rule 7 fails on any literal that names two or more roster entries. P9's acceptance 7 targets a name that no longer exists, or re-adds a hand-written role list (D21), which turns P1b's check red.
- **Fix:**
  - P9.md:454: replace `obligation.ROLES and PRODUCER_ROLES (the obligation producers), codex ENFORCED_AGENT_TYPES and the tool-policy roles are different facts and stay; a test asserts ROLES is a subset of the roster.` with `P1b row 18 deleted obligation.ROLES, PIPELINES, PRODUCER_ROLES and codex ENFORCED_AGENT_TYPES (roles validate against the roster function, pipelines against the command files, and the active command's declaration says which dispatches carry a block): verify each is gone and re-add none (D21; P1b's CI check, row 19 rule 7). The role keys of policies/tool-policy.v1.json are a different fact and stay.`
  - P9.md:454, same row: `keep that site's set as a named subset derived from the roster and record why` → `keep that site's set as a subset derived from the declarations (never a literal naming two or more roster entries, P1b row 19 rule 7) and record why`
  - P9.md:548-549: `a test\n   asserts obligation.ROLES is a subset of the roster;` → `` `git grep -nE '^(ROLES|PIPELINES|PRODUCER_ROLES|ENFORCED_AGENT_TYPES) *=' -- hooks scripts` prints nothing (P1b row 18), and P1b's CI check is green; ``
  - P9.md:427: `ROLES stays the producer subset.` → `P1b row 18 removed ROLES and PRODUCER_ROLES as well (D21).`
  - P6.md:343: `(not only when it is in \`obligation.ROLES\`)` → `(not only when the active command's declaration names that role, the condition P1b row 18 put in place of the deleted \`obligation.ROLES\`)`
  - P6.md:344 and P3.md:295: `ENFORCED_AGENT_TYPES` :31 → `read from the declaration since P1b row 18 deleted \`ENFORCED_AGENT_TYPES\``
- **Confirmations:** 2.
- **Origin:** drift (at c728380, P1b said "ROLES stays the producer subset").

## MEDIUM

**7. The /do "sidecar missing" gap is a dead end that only a human clears** (F4, X9, SYNC-12)
- **Files:** prompts/P5.md, PLAN-v2.md
- **Location:**
  - P5.md: :104-107, :297, :338 (row 15), :382-385, :662-663 (acceptance 4), :856-857
  - PLAN-v2.md: :536, :563, :574, :591, :629, :1092 (TC-26), :1172, :1217
- **Problem:**
  - A's X6 bullet tells P5 that every block site must fit class G, D or H, and that a site fitting none is fixed before merge.
  - P5 still prescribes `do task sidecar missing`, which only /stop or a human `/do <task-id>` clears, and which tmp cleanup can reach. That breaks D25 (3) and P1c X6.
  - PLAN-v2:536 leaves the case open, and the metric at :1172 accepts it. P5 is told both to build the site and that it cannot merge with it.
- **Fix:**
  - P5.md:382-385: replace `the task named by the hook-minted sidecar only (TC-26)` and the sentence `A missing sidecar is the gap \`do task sidecar missing\`, cleared only by /stop or, if Goal 6 keeps TC-18, a\n  human \`/do <task-id>\`.` with `the task named in the hook-output record the CLI wrote for the human-typed /do opener of the span (\`[/do] task-id minted: <id>\`, prompt-workflow.py :1425 at f8c18c2), or the id typed in a human \`/do <task-id>\` opener if Goal 6 keeps TC-18. Read it with the same record shape as the dev predicate's minted id (:376-379), never from assistant text, a tool result, the /tmp sidecar or a do-report. Tmp cleanup of the sidecar then leaves no gap only a human clears (D25 (3), P1c X6 class G). If P1's capability facts show the CLI writes no such record, keep the sidecar under a root tmp cleanup does not touch and every agent is denied (D10), and the PR names the site until X6 classes it (TC-26, decided by experiment, D18).`
  - P5.md:338 (row 15): `a missing sidecar is a gap that only a human /stop clears (or, if Goal 6 keeps TC-18, a human-typed \`/do <task-id>\`)` → `the gate reads the task id from the opener's hook-output record, not from the sidecar (TC-26 as corrected); prompt-workflow emits the minted id in its opener output whether or not the sidecar write succeeds (at f8c18c2 the print at :1425 is skipped when the write at :1419-1424 fails); a /do opener whose hook recorded no id is the hook's instrument failure (H, like the gate's), or P5 proves it unreachable`
  - P5.md:297: `TC-26 (/do identity from the sidecar only)` → `TC-26 (/do identity from the opener's hook-output record)`
  - P5.md:662-663: `the sidecar deleted -> rc 2 \`do task sidecar missing\`, cleared by a human /stop (and, only if Goal 6 keeps TC-18, by a human \`/do <task-id>\`)` → `the sidecar deleted mid-span -> the gate names the same task from the opener's record: no completed do-report -> rc 2 naming the do-report; completed with file lists equal to the write set -> rc 0, with no human action; an agent Bash command echoing \`[/do] task-id minted: <other id>\` changes nothing`
  - P5.md:856-857: delete the sentence `A /do sidecar removed by tmp cleanup blocks the /do span until the human types /stop` together with its remainder.
  - P5.md:104-107: after `(H, like the\n  time-lock's).` append ` The /do identity carries no sidecar-missing gap: it would fit no class (row 15, the do predicate).`
  - PLAN-v2.md:536: `the /do span's missing-sidecar gap below, which no agent step clears, is checked against these classes.` → `the /do predicate reads its task id from the opener's hook-output record (TC-26 as corrected), so a missing sidecar blocks nothing and no /do site waits for a human.`
  - PLAN-v2.md:563, :574, :591 (S3): mirror the P5 predicate, row 15 and acceptance 4 text. Delete the residual at :629.
  - PLAN-v2.md:1092 (TC-26): the decided column becomes the opener-record read, tested by "sidecar deleted -> task still named; completed -> rc 0". The revert column becomes "the sidecar, with the missing-sidecar gap classed by P1c X6".
  - PLAN-v2.md:1172: `a missing /do sidecar is cleared by a human "/do <task-id>" (TC-26; only if TC-18 is kept by P5's replay), and any residual is released by /stop` → `a missing /do sidecar no longer blocks (TC-26)`. Adjust the revert note at :1217 to match.
  - TC-18's `/do <task-id>` stays only as the consent-loss continuation.
- **Confirmations:** 2.
- **Disagreement:** three mechanisms were proposed:
  - (a) the transcript record alone, with the sidecar not read for identity (D24: one source);
  - (b) the sidecar moved under a non-tmp, agent-denied root;
  - (c) the sidecar, falling back to the transcript.
  
  I adopted (a) as primary and (b) as the D10 fallback. One refiner noted a text match would accept an agent-echoed line, so the read is of the hook-output record. X20's second refiner put this gap into class H; that is rejected (see item 23).
- **Origin:** A. The gap predates A, but A's X6 bullet and PLAN-v2:536 made the plan contradict itself.

**8. The D8 proof bracket, and the declaring-dispatch reader still credited to P3** (F6, SYNC-5, X8, the reader part of SYNC-13, the second part of F1)
- **Files:** DECISIONS.md, PLAN-v2.md, prompts/P3.md, P4.md, P5.md, P6.md
- **Location:**
  - DECISIONS.md: :131-132
  - PLAN-v2.md: :87, :183, :485, :536, :567, :1086, :1258
  - P3.md: :199-200, :206, :275, :286, :476-478
  - P4.md: :41-42, :55-58, :99, :146, :164-165, :504
  - P5.md: :53-55, :133-134, :190-191, :226-228, :295-296, :323, :334, :424-426, :467, :494
  - P6.md: :70-71, :154-155
- **Problem:**
  - D8 (top precedence) gates this INFERRED mechanism on P3 acceptance 8 and the P5-a arm-* replay. But P1b E3 builds and ships the reader and the derived deny (enforcing), and A's own P3 block says "consumed, not built".
  - Following DECISIONS, a reviewer would have to block P1b E3, or accept use before proof.
  - The P4 and P5 start checks look for "P3's declaring-dispatch reader (P3 row 1; use the name P3 merged)", a name P3's PR never gives. Failing a start check means stop.
  - PLAN-v2:536 ("adds to it only the release-input denies") drops the main agent's half that P1b E3 may leave to P5 row 1.
- **Fix:**
  - DECISIONS.md:131-132: replace the bracket `[INFERRED mechanism; prove before use by P3's acceptance 8 replay (the declaring-dispatch reader) and, for the deny,\n  by the P5-a arm-* sandbox replay (TC-20 revised: 0 compliant writes denied, 0 V7a writes allowed).]` with `[INFERRED mechanism; prove before use by P1b's E3 replays: the declaring-dispatch reader by P1b acceptance 7 (its never-dispatched /close case included), the write permission derived from dispatch records by E3's decision rule (TC-20 as corrected: 0 compliant writes denied, 0 writes of a path another dispatch's obligation declares allowed), after which P1b ships the deny enforcing. Any part P1b's PR leaves to P5 row 1 (the main agent's half, an unresolved subagent role, a Bash write target the extractor does not see) is proved before it is armed by the P5-a arm-* sandbox replay. P3's acceptance 8 and P5-a re-run the replays on their bases.]`
  - PLAN-v2.md:536: `(it arms it only where P1b's PR left it unenforced; where E3 took the other outcome, P1b's PR rules), adds to it only the release-input denies, and builds no table.` → `(P1b ships it enforcing, with no switch; where E3 took the other outcome, P1b's PR rules), extends it to what P1b's PR left to P5 row 1 (the main agent's half, an unresolved subagent role, a Bash write target the hook does not extract), adds the release-input denies, and builds no table.`
  - PLAN-v2.md:87: `(D21; P5-a proves the mechanism by sandbox experiment, TC-20)` → `(D21; P1b E3 proves the mechanism by sandbox replay and ships it enforcing; P5-a re-runs it and proves what it adds for callers P1b left, TC-20)`
  - PLAN-v2.md:1086, TC-20 decided cell: → `[INFERRED; decided by P1b E3's replay (0 compliant writes denied, 0 writes of another obligation's declared path allowed), re-run by the P5-a arm-* sandbox replay for the callers P5 row 1 adds]`. For the Revert cell, see item 11.
  - PLAN-v2.md:183: `and P3 (stages and the declaring-dispatch reader)` → `and P3 (stages; the declaring-dispatch reader they read is P1b's, E3)`
  - PLAN-v2.md:485: `It needs P3's stages and the declaring-dispatch reader,` → `It needs P3's stages (the declaring-dispatch reader is P1b's, E3),`
  - PLAN-v2.md:567: `Keep the declaring-dispatch reader P3 exposed from find_unresolved_dispatch_obligations (D21)` → `Keep the declaring-dispatch reader P1b's E3 left in find_unresolved_dispatch_obligations (D21)`
  - PLAN-v2.md:1258: `keeping the declaring-dispatch reader P3 exposed from it` → `keeping the declaring-dispatch reader P1b's E3 added to it`
  - P4.md:41-42 and P5.md:53-55: `contains P3's declaring-dispatch reader (P3 row 1; use the name P3\n  merged)` → `contains the declaring-dispatch reader (P1b E3; use the name P1b's PR gives)`
  - P4.md:55-58: `(P3 row 1; an [INFERRED] mechanism of D21 that P3's acceptance 8 replay\n  proves` → `(P1b E3; an [INFERRED] mechanism of D21 that P1b's acceptance 7 replay proves`
  - P4.md:99 and P5.md:424-426: "decided by P3's acceptance 8 replay ..." → "decided by P1b's acceptance 7 replay (its /close whose lane QA was never dispatched), re-run here by acceptance 4's never-dispatched case" (in P5: "by acceptance 2").
  - P4.md:146 and :164-165: "P1b's acceptance 7 replay proves the reader".
  - P4.md:504: remove "and the declaring-dispatch reader" from P3's work and add "(the declaring-dispatch reader is P1b's, E3)".
  - P5.md:323, :334, :467, :494, and the proof tags at :133-134, :190-191, :226-228, :295-296: make the same substitution.
  - P3.md:199-200: `You build the stages and the declaring-dispatch reader; P4 wires /close and /commit to them.` → `You build the stages and consume P1b's declaring-dispatch reader (E3); P4 wires /close and /commit to them.`
  - P3.md:206: → `[INFERRED; proved by P1b's E3 replay (P1b acceptance 7); your acceptance 8 re-runs it over your gaps]`
  - P3.md:275: `(1) the declaring-dispatch reader with its test;` → `(1) your acceptance 8 test of P1b's reader on your base (no second reader);`
  - P3.md:286 (row 1): consume, do not build.
  - P3.md:476-478: the D8 deny becomes "P1b E3's derived write permission, which P5-a extends and whose extension P5-a's arm-* replay proves".
  - P6.md:70-71: `the declaring-dispatch reader (P3 row 1; [INFERRED] under D21, proved by P3's sandbox replay)` → `the declaring-dispatch reader (P1b E3; [INFERRED] under D21, proved by P1b's acceptance 7 replay)`
  - P6.md:154-155: → `[INFERRED in D21; P1b's E3 replays prove the reader (acceptance 7) and the derived deny; P5-a's arm-* replay decides only the callers P1b left to P5 row 1]`
- **Confirmations:** 2.
- **Disagreement:** wording only ("prove" vs "proved"; whether every stale tag goes in the same change). Do them all together.
- **Origin:** A. 86b7cbc wrote the bracket, and c728380 moved the reader to P1b without updating it.

**9. D25 (2) "zero human action" conflicts with the /restart and F8 exceptions; fault count is stale** (F5, SYNC-7, X16)
- **Files:** HANDOVER.md, PLAN-v2.md, DECISIONS.md, COVERAGE.md
- **Location:** HANDOVER.md:119-121; PLAN-v2.md:96, :174, :1175, :1330-1334; DECISIONS.md:77-79; COVERAGE.md:306
- **Problem:**
  - PLAN-v2:1175 and COVERAGE:306 exempt the human /restart of F5, F5f and F6, as P1c does. But PLAN-v2:96, :1334, D25 (2) and the owner-facing HANDOVER:121 say these faults pass with "zero human action" / "零人工".
  - P1c now has 21 faults. The four F8 faults (CC4) each start with a human /close or /commit, which P1c exempts. PLAN-v2:174 still says 17.
  - Consequences: the owner is told he does nothing where the plan needs his /restart; a reviewer applying D25 (2) literally would fail P1c's F5/F6/F8 acceptance; the CC4 replays are hidden.
- **Fix:**
  - HANDOVER.md:121: `生产者，下一轮通过，零人工；` → `生产者，下一轮通过，零人工（例外：会话被你自己中断，或在 /dev-overnight 之外因额度用完被截断，仍由你敲 /restart 接上，这是你定的"恢复一个session被截断应该用restart command"（D22）；接上之后零人工。/dev-overnight 里额度用完由会话自己的定时唤醒接上，不用你（P1c X8））；`
  - PLAN-v2.md:1330-1334: rewrite the (2) sentence as `(2) Faults (a missing, malformed or old-version artifact including E1's v1/v2 conflict, a held git index.lock, an interrupted session, a usage limit and resume, a fan-out lane leaving an old report, and an unfinished cycle met by the human's /close or /commit, F8-F8c, CC4) are each blocked (the F8 faults: a gap found by /close's or /commit's one chain-function call, no hook block), with the artifact and the failing check named, returned to the producer of the declaring dispatch, and pass on the next round with zero human action apart from the human /restart that resumes a session the owner interrupted or one a usage limit cut outside /dev-overnight (F5, F5f, F6; D22, register RD4) and the human /close or /commit that starts each F8 fault (CC4); inside /dev-overnight a usage-limit cut resumes with none (F6o, P1c X8, D20).`
  - PLAN-v2.md:96: after `that producer's next round passes with no human action` insert ` (apart from the human /restart that resumes a session he interrupted, or one a usage limit cut outside /dev-overnight: D22, RD4; P1c X8 resumes a usage-limit cut inside /dev-overnight)`
  - DECISIONS.md:79: after `repaired at the next round with no human action;` insert ` [planner reading of (2) with D22, not new owner words: a session the owner interrupted is his exit (D23) and resumes when he types /restart, as does one a usage limit cut outside /dev-overnight (D22; register RD4 "恢复一个session被截断应该用restart command", SG6 "之后用restart自动接"); no human action is needed after that /restart; inside /dev-overnight a usage-limit cut resumes with none (D20; P1c X8)]`
  - PLAN-v2.md:174: `17 faults;` → `21 faults, the four F8 faults (F8, F8q, F8p, F8c) replaying CC4's unfinished cycle met by the human's /close or /commit;`
  - PLAN-v2.md:1175 (target cell): `(outside /dev-overnight, the human /restart that resumes F5, F5f and F6 aside: D22, register RD4; inside it none: F6o, P1c X8, D20)` → `(outside /dev-overnight, the human /restart that resumes F5, F5f and F6 (D22, register RD4) and the human /close or /commit that starts each F8 fault (CC4, D7) aside; inside it none: F6o, P1c X8, D20)`. Leave the baseline column as it is.
  - COVERAGE.md:306: after `F7, F7b (fan-out lane),` insert `F8, F8q, F8p, F8c (an unfinished cycle met by the human's /close or /commit, CC4; routed by P1b row 10),`. Replace `P1c acceptance 4 (the human /restart of F5, F5f and F6 aside: D22, register RD4)` with `P1c acceptance 4 (the human /restart of F5, F5f and F6 and the human /close or /commit of each F8 fault aside: D22, register RD4, CC4); P1b acceptance 7`.
- **Confirmations:** 2.
- **Disagreement:**
  - One refiner proposed adding "unless X8 records the CLI limit" to :1175. Two rejected it: P1c says a CLI limit is reported, "never as D20 met". Not adopted.
  - The split between a session the owner interrupted (his exit, D23) and a usage-limit cut is adopted from the refiners.
- **Origin:** the "zero human action" text is A's (F5). The fault count and F8 are drift (P1c went from 17 to 21 faults after c728380).

**10. P6 and PLAN-v2 misstate what P1b E6 removed** (X10, SYNC-4)
- **Files:** prompts/P6.md, PLAN-v2.md, prompts/P5.md
- **Location:** P6.md:84-86, :90-92; PLAN-v2.md:536 (the "Delivered before P5" list), :564, :637; P5.md:97, :331
- **Problem:**
  - A's text says E6 removed G2's `_wire_ledger_judgment` and the adjudicator comparison, and that E6 wins over row 5's ENTANGLED check.
  - B's E6 keeps both, and also delivers TC-46's write-set reader to command_span.
  - Consequences: P6 may delete the ENTANGLED check, or skip retiring the losing producer's readers, so two producers of "which files this dev wrote" survive (D24). P5 row 8 would build a second write-set reader.
- **Fix:**
  - P6.md:84-86: replace `and removed the other\n  producer and every rule that compared the two (the G2 ledger wire, the aggregator union, the adjudicator's\n  comparison).` with `; it kept G2's \`_wire_ledger_judgment\` with the attribution_adjudicator functions it calls (its ENTANGLED check, row 5) and dev's declared \`files_created\` / \`files_modified\` (A3.a checks them), deleted verify-attribution-chain at /commit Step 5 if it only re-checked and the aggregator union once no reader of it was left, and its PR lists each losing candidate with its remaining readers and the phase that retires it: retire those it assigns to you (acceptance 19). If E6 took the CLI record, it added TC-46's write-set reader to hooks/lib/command_span.py, which A3.a reuses.`
  - P6.md:91-92: delete `row 5 keeps\n  \`_wire_ledger_judgment\`'s ENTANGLED check; `
  - PLAN-v2.md:637: `and removed the other producer and every rule that compared the two: A3.a builds on E6's outcome.` → `; it kept G2's \`_wire_ledger_judgment\` (ENTANGLED, P6 row 5) and dev's declared file lists, listed each losing candidate with its remaining readers and the phase that retires it, and, if it took the CLI record, delivered TC-46's write-set reader in hooks/lib/command_span.py early: A3.a builds on E6's outcome and reuses that reader.`
  - P5.md:97: after `rows 15 and 21 build on it);` insert ` TC-46's transcript write-set reader in hooks/lib/command_span.py, if P1b's E6 took the CLI record (row 8's \`write_set()\` extends that reader for the main agent's /do span and writes no second one);`
  - PLAN-v2.md:536: add the same reader to the "Delivered before P5" list.
  - PLAN-v2.md:564 and P5.md:331: `new Span.write_set()` → `Span.write_set() (new unless P1b E6 delivered the reader; then extend it)`
- **Confirmations:** 2.
- **Disagreement:** one refiner also deletes "row 6 and \"Out of scope\" keep the owned-edits ledger" from P6:91-92; the other keeps it. Keep it: the ledger survives as a losing candidate, with readers, until the phase that retires it (acceptance 19).
- **Origin:** drift (at c728380, P1b E6 did delete the wire).

**11. P5 and TC-20 fall back to per-role prefix rows that P1b E3 forbids** (X11)
- **Files:** prompts/P5.md, PLAN-v2.md, prompts/P6.md
- **Location:** P5.md:100, :323 (row 1); PLAN-v2.md:1086 (TC-20, Revert column); P6.md:99, :152-155
- **Problem:** P1b E3 forbids an allow prefix that names a derived artifact's file, and its CI check fails on one. A count above 0 is fixed where it arises. Taking P5's fallback re-adds a filename-to-role table (D21) and turns P1b's check red.
- **Fix:**
  - P5.md:323: `If the declared-path variant misses it, fall back to PLAN-v2 TC-20's alternative (per-role prefix rows in tool-policy.v1.json, which exist today) and record the counts; no variant adds a table that maps file names to roles (D21).` → `A count above 0 is fixed where it arises, as P1b's E3 rule says (the producer's obligation declares the path, a write by a non-producer goes, or the Bash write extractor gains the target), never by a prefix row that names a file: P1b's CI check (row 19 rule 7) fails on one (D21).`
  - P5.md:323, same cell: `delete each allow prefix the derived deny now always overrides for that role, or keep it and say why (D10)` → `verify P1b deleted each allow prefix that names a derived artifact's file (P1b E3, row 19 rule 7); directory and wildcard prefixes stay and the derived deny overrides them`
  - P5.md:100: `can fall back only to the per-role prefix rows P1b kept` → `has no prefix-row fallback (P1b E3)`
  - PLAN-v2.md:1086 (Revert cell): `A per-role prefix list in tool-policy.v1.json, if the experiment fails.` → `None (D21): a per-role prefix row that names a file is a filename-to-role table, and P1b's CI check fails on it; a count above 0 is fixed where it arises (P1b E3).`
  - P6.md:153-154: `or from P5's existing per-role prefix rows if its arm-* replay chose that fallback` → `with no prefix-row fallback (P1b E3)`
  - P6.md:99: → `P1b E3 deleted every tool-policy allow prefix that names a derived artifact's file; correction 11 applies to the rows left (deny, directory and wildcard prefixes).`
- **Confirmations:** 2.
- **Origin:** A (A's own P5 block names P1b E3).

**12. The owner-facing HANDOVER is stale** (F2, X13, SYNC-15)
- **File:** HANDOVER.md
- **Location:** :1, :3, :7, :21, :23, :24, :25, :26, :37, :106, :108, and a new section after "## 2026-10-24 更新" (:110)
- **Problem:**
  - A rewrote rows 21, 23, 24 and 25 but kept "问题 3/4/5/6" in the 会问你 column. That tells the owner he will be asked, against D18/D19 and the prompts ("The owner is asked nothing"). The new P1b and P1c rows say 不问, so the table disagrees with itself.
  - Row 26 says P9-P11 are 还没写 (not written); they were written on 2026-10-19.
  - :106 and :108 say P8 is under review and /pull is unsafe until P7b merges. Both merged on 2026-10-25, before A's commits.
  - :1 and :3 list only 8 prompts.
- **Fix:**
  - Last cell of :21 → `不问（D18：由实验决定）`; :23 → `不问（D18：由实验决定）`; :24 → `不问（D18、D19：由实验决定）`; :25 → `不问（D18：由实验决定）`
  - :26: `还没写。P9 在 P6 之后` → `已写好（2026-10-19，2026-10-24 加上了 P1b、P1c；见 COVERAGE-P9-P11.md）。P9 在 P6 之后`; and `见问题 8` → `不问（问题 8 已按 D18、D19 定下）`
  - :1 → `# 交接：修复计划的提示词（P7b、P1、P8、P1b、P1c、P2–P6、P9–P11）`
  - :3: replace `8 个提示词都在这个文件夹里：P7b.md、P1.md、P8.md、P2.md、P3.md、P4.md、P5.md、P6.md。每个末尾都原样附上了\nprompts/_common.md（已逐字节核对）。` with `提示词都在这个文件夹里：P7b.md、P1.md、P8.md、P1b.md、P1c.md、P2.md–P6.md、P9.md–P11.md。每个末尾都附上了 prompts/_common.md：P10、P11 的副本在 Context 那段多一句 owner 裁决优先的话，其余逐字节相同。`
  - :7: `你只需要回答下面"要你回答的问题"。可以一次答完；不答的就用默认值。` → `提示词不再问你（D18、D19）；下面的问题只作记录。`
  - :37: → `### 提示词里原来会问的 6 个（1、2 已于 2026-10-19 回答；3–6 不再问你，由 P2、P4、P5、P6 各自做实验决定，D18、D19）`
  - Add a new section:
    ```
    ## 2026-10-26 更新
    - P7b（PR #7，合并提交 301d696）和 P8（PR #6，合并提交 2acc29b）都已在 2026-10-25 合并，CI 绿；10-22 那节"P8 正在审阅""P7b 合并之前 /pull 仍然不安全"已不再适用：/pull 拉到的代码由 P7b 自己落地。
    - P1b 的前置（P1、P8、P7b）都已合并；P1b 提示词审阅完成后就开。
    - 表里 P2、P4、P5、P6 的"会问你"已改为"不问"：问题 3–6 按 D18、D19 由各阶段做实验决定，写进它 PR 的 technical-choices 表。
    - 你不用做任何事。
    ```
- **Confirmations:** 2.
- **Disagreement:**
  - (a) Should HANDOVER say "P1b 现在就能开"? One refiner said yes. The other said no, because the P1b prompt is still under B's review ("AB我都在推进"). Adopted: "审阅完成后就开".
  - (b) "/pull 现在安全": rejected as unconditional; adopted "the 10-22 caveat no longer applies".
  - (c) SYNC-15 also wanted each prompt's "Wave N" intro to list P1b and P1c (P5.md:14 `P1, P8, P7b, P2, P3 and P4 must be merged` → `P1, P8, P7b, P1b, P1c, P2, P3 and P4 must be merged`, and likewise at P2:10, P3:9, P4:8-12, P6:8, P9:9, P10:8). The other refiner said leave them, since each prompt states the requirement in "Before you start". Recommendation: fix only P5.md:14, the one closed "must be merged" list.
- **Origin:** A.

**13. P1c's net-code cap differs between PLAN-v2 and the prompts** (X7, SYNC-6)
- **Files:** PLAN-v2.md, prompts/P2.md, prompts/P6.md
- **Location:** PLAN-v2.md:106, :134, :1199, :1329; P2.md:893-894; P6.md:777-778
- **Problem:** PLAN-v2 gives P1c `<= 0`, while P1c.md:863 and P1b correction 1 say `<= +150`. PLAN-v2's principle allows only P2, P6 and P7 to be positive. The reviewer and P1c read different merge caps.
- **Fix** (align PLAN-v2 to B; if the reviewer rejects +150, revert P1c.md :832/:863 and P1b correction 1 instead; either way they must match):
  - PLAN-v2.md:134: `| 2c | P1b (so P1, P8, P7b) | XL | <= 0 |` → `| 2c | P1b (so P1, P8, P7b) | XL | <= +150 |`
  - PLAN-v2.md:1199: `P1c <= 0;` → `P1c <= +150;`
  - PLAN-v2.md:1329: `net code <= 0; prompts/P1c.md` → `net code <= +150, measured against P1c's base (C3 measured by the suite); prompts/P1c.md`
  - PLAN-v2.md:106: `Only P2, P6 and P7's init/install code may be positive.` → `Only P1c (<= +150), P2, P6 and P7's init/install code may be positive.`
  - P2.md:893-894: `three phases allowed a positive budget` → `four phases allowed a positive budget`
  - P6.md:777-778: `three phases allowed to be positive` → `four phases allowed to be positive`
- **Confirmations:** 2.
- **Origin:** drift (2e7d4c0).

**14. P9 lets a PR-body reason excuse a missing fault replay** (X6, SYNC-10)
- **Files:** prompts/P9.md, PLAN-v2.md
- **Location:** P9.md:645-647 (acceptance 24); PLAN-v2.md:826
- **Problem:** P1c's merge rule now reads no PR-body reason. A changed command or agent definition that a replayed pipeline reaches must be read by a replay, or the step fails. P9, the largest commands/agents edit, plans around an excuse that CI ignores, so its merge fails late.
- **Fix:**
  - P9.md:647: `and for any other changed commands/ or agents/ file the PR body says why no fault replay applies.` → `and any other changed command or agent definition (YAML frontmatter on base or head) that a replayed pipeline reaches is read by a replay of P1c's (1), (2) or (4), or the PR adds the scenario that reads it; other changed files there (a definition no replayed pipeline reaches, or a file with no frontmatter on either side) are printed as facts and do not fail the step, and the step reads no PR-body reason.`
  - PLAN-v2.md:826: `prose-only changes need none, and every command or agent template a driver extracts keeps its scenarios green.` → `prose-only changes need no fault replay, but every changed command or agent definition a replayed pipeline reaches is read by a replay, and every template a driver extracts keeps its scenarios green.`
- **Confirmations:** 2.
- **Disagreement:** severity only (X6 said high, SYNC-10 said low). Rated medium: the failure is caught by CI, late.
- **Origin:** drift (d22c669 and later).

**15. P4 does not know P1b E14 deleted /commit Step 8** (X14)
- **File:** prompts/P4.md
- **Location:** :77-87 ("Already done by P1b" block), :270, :280 (row 5), :281 (row 6), :288 (row 13), :442, :677-678 (acceptance 14), :735
- **Problem:** P1b E14 deletes /commit Step 8's spec selection, its STEP7_* markers and scripts/step7-spec-update.py. P4 still renames those markers and requires them to be emitted through that script. Acceptance 14 cannot be met, and P4 may rebuild what P1b deleted.
- **Fix:**
  - Block :77-87: after `one channel per verdict (P1b E11);` insert `/commit Step 8 (P1b E14: its spec selection, stage 4's routing to ba, the continuation dispatch, the STEP7_* markers and COMMIT_STEP7_TRACE, scripts/step7-spec-update.py and the tests that pin those markers), so the Step 8 items of rows 5, 6 and 13, acceptance 14 and the PR list below are already met: do not rename or rebuild them, and name each one in the PR as delivered by P1b;`
  - Row 5: delete `Step 8 trace markers :866-876 and stage-4 routing :908-911;` and `Step 8 becomes advisory: stage 4 prints and dispatches nothing. Rename the STEP7_* markers (Step 8 emits them).`
  - Row 6: drop `scripts/step7-spec-update.py`, `step7-spec-update.py marker docs :23, :31-37 and emitters :182-240` and `Rename the markers in step7-spec-update.py to match commit.md.`
  - Row 13: drop `hooks/tests/test_final_sweep.sh and hooks/tests/test_ac5_verify.sh (STEP7 markers)`.
  - :270: `(3) commit.md, step7-spec-update.py and the changelog-analyst` → `(3) commit.md and the changelog-analyst`
  - :442: delete `- the STEP7_* replacement names (and the trace variable);`
  - :677-678: replace `Step 8's stage 4 prints and dispatches nothing; \`COMMIT_STEP7_TRACE\` (or its renamed variable) emits the renamed markers through scripts/step7-spec-update.py.` with `commit.md has no Step 8 spec selection, scripts/step7-spec-update.py does not exist on your base and no STEP7_* marker remains (P1b E14; acceptance 2's grep).`
  - :735: drop `Step 8's routing to ba,`
- **Confirmations:** 2.
- **Origin:** drift (new E14 text after c728380).

**16. P9 has no row for the /restart lines that P1c's X8 changes** (X12, SYNC-11)
- **File:** prompts/P9.md
- **Location:** :463 (row 14), :465 (row 16), :294-308 (E3's "At least" list)
- **Problem:** P1c hands P9 four lines (CLAUDE.md:41 and :62, README.md:477, ARCHITECTURE.md:178) that name only the typed /restart as the SendMessage exception. X8 widens that exception, and P9 carries no row for these lines. CLAUDE.md, README and ARCHITECTURE would then state a false rule about the hook.
- **Fix:**
  - Row 16, Locations: after `:43 (Lesson 16's reference to Hook Discipline #4/#5);` insert `:41 (Lesson 16: "the human-only \`/restart\` command must enumerate every recoverable child");`. Change `:62 (run_in_background on every dispatch)` to `:62 (run_in_background on every dispatch; "The sole \`SendMessage\` exception is the supported human-only \`/restart\` path")`.
  - Row 16, Change: after `:102 per E3 (the sentinel lives under the hook state directory; the cleanup phase runs on an allowed Stop).` insert ` :62's SendMessage sentence and Lesson 16 (:41) per E3 and P1c's X8: if X8 widened the exception of hooks/pretool-block-background-tasks.py on your base, state it as the merged hook does (typed /restart, or the overnight session's own wake inside its open /dev-overnight span, with the same fixed message and transcript-discovered pending-id rule; D20); /restart itself stays human-only; every other message and id stays refused.`
  - Row 14: add to Locations `README.md "No background dispatch" row :477; ARCHITECTURE.md §5.1 :178 ("The exception is deliberately narrow")`, and to Change `both state the SendMessage exception as row 16 words it (P1c X8, E3).`
  - E3 list: after the run_in_background item insert `hooks/pretool-block-background-tasks.py's SendMessage exception: the fixed recovery message to a pending transcript-discovered id from a typed /restart and, if X8 widened it, from the overnight wake inside an open span (each accepted), another message and another id (each refused);`
- **Confirmations:** 2.
- **Disagreement:** one refiner relied on P1c's replay; both final versions add P9's own E3 replay, which is adopted.
- **Origin:** drift (a new hand-off in B's head).

**17. Merge-title start checks fail on a correct base, and failures go to the owner** (SYNC-8, X21)
- **Files:** prompts/P2.md, P3.md, P4.md, P5.md, P6.md, P9.md, P10.md, P11.md
- **Location:**
  - The "Before you start" title bullets: P2:71-72, P3:68-69, P4:33-35, P5:42-44, P6:33-34, P9:48-49, P10:37-38, P11:45-47.
  - The failure lines: P2:80-81, P3:79-80, P4:45, P5:58, P6:48, P10:47.
- **Problem:**
  - The checks require merges "titled `P8: …`" and "`P7b: …`". Master's merges carry `P8, …` and `P7b, …` in the subject (2acc29b, 301d696). A literal check fails on a correct base and the session stops: a false dead end.
  - The failure lines say "stop and tell the owner", which goes against D18/D19 and against P1b, P1c and P9.
- **Fix:**
  - In all eight prompts, drop P5's `(a GitHub merge commit carries the title in its subject or its body)` and P11's `(a merge GitHub makes keeps the pull request title in the body, not the subject: fe7700c8, 3dfb66a3)`. After the list of titles, add: `git log prints each merge commit's message, not the pull request's title. A merge takes one of two forms: the subject \`Merge pull request #<n>: <phase>, …\` (P8: 2acc29b, P7b: 301d696), or the subject \`Merge pull request #<n> from <owner>/<branch>\` with \`<phase>: …\` as the body's first line (P1: d625284). Each later phase's merge counts in either form (prompts/P1c.md, "Before you start").`
  - On the failure lines: `stop and tell the owner that` → `stop and tell the reviewer in your session output (never the owner; D18, D19) that`
- **Confirmations:** 2 for the title check; 1 for the "tell the owner" part.
- **Disagreement:** whether to change the shared _common.md tail ("stop and tell the owner instead of guessing") in all 13 copies. That edit is optional and needs the byte-identity note in HANDOVER (item 12) updated with it.
- **Origin:** A.

**18. D25's precedence is missing from PLAN-v2 and the prompts** (SYNC-3, F9)
- **Files:** PLAN-v2.md, prompts/P2.md-P6.md, P9.md, P10.md, P11.md, DECISIONS.md
- **Location:**
  - PLAN-v2.md: :7, :10, :25, :107
  - The preamble lines: P2:161, P3:153, P4:137, P5:181, P6:144, P9:148, P10:123, P11:82
  - The D20-D24 bullets: P2:164, P3:159, P4:140, P5:184, P6:147, P9:151, P10:126, P11:85
  - P9:486; P10:818-819; P11:795-796; DECISIONS.md:68
- **Problem:** every precedence statement outside DECISIONS still calls D20-D24 the latest and top rulings. P10 and P11 never mention D25.
- **Fix:**
  - Preambles: `DECISIONS.md D20-D24 (owner, 2026-10-23). S2 is superseded` → `DECISIONS.md D20-D25 (owner, 2026-10-23 and 2026-10-24). S2 is superseded`
  - Bullets: `(owner, 2026-10-23; latest, they outrank every bullet below and every plan; quoted in` → `(owner, 2026-10-23; with D25 (owner, 2026-10-24, same rank; DECISIONS.md) they outrank every bullet below and every plan; quoted in`
  - P10.md:818-819 and P11.md:795-796: `The owner's rulings of 2026-10-23 (DECISIONS.md\nD20-D24) outrank` → `The owner's rulings of 2026-10-23 and 2026-10-24 (DECISIONS.md\nD20-D25) outrank`
  - P9.md:486: `(D20-D24 first)` → `(D20-D25 first)`
  - PLAN-v2.md:7: `its owner rulings of 2026-10-23, D20-D24, come first` → `its owner rulings D20-D24 (2026-10-23) and D25 (2026-10-24) come first`
  - PLAN-v2.md:10 and :25: `DECISIONS.md D20-D24` → `DECISIONS.md D20-D25`
  - PLAN-v2.md:107: `D1-D24 are binding, S1-S9 bind below quoted owner words and D20-D24` → `D1-D25 are binding, S1-S9 bind below quoted owner words and D20-D25`
  - Optional, DECISIONS.md:68: `(latest; like D20-D24 it overrides every other decision, PLAN-v1, PLAN-v2 and every prompt)` → `(latest; it ranks with D20-D24 and agrees with them; like them it overrides every earlier decision, PLAN-v1, PLAN-v2 and every prompt)`
- **Confirmations:** 1 each from two independent lenses.
- **Disagreement:**
  - F9's original fix had D25 outranking D20-D24. The refiner, and the sync list's D-1 ("D25 overrides nothing in D20-D24 and agrees with them"), rank it with them. Same rank is adopted.
  - SYNC-3's rewrite of the DECISIONS.md:7 heading is not adopted: owner-F3 raised the same point and two refuters dropped it (the "except" clause cannot be read the inverted way, and :68 states the order).
- **Note for B:** prompts/P1b.md:124 still says "D20-D24".
- **Origin:** A.

## LOW

**19. PLAN-v2:96 leaves the Stop gate out of the allowed stop positions** (F8)
- **File:** PLAN-v2.md
- **Location:** :96
- **Problem:** the D25 bullet lists only the producer's stop, G1 and G3. D4 and D21 name the Stop gate too, so every P5 Stop-gate block would read as a block at a non-allowed position.
- **Fix:** `(the producer's stop, G1 at dispatch, G3 at collection)` → `(the producer's stop, G1 at dispatch, G3 at collection, or at the end the command's Stop gate (D4, D21; P5), which decides completion only from the one chain function's conclusion, git and the stopping main agent's own artifacts and re-validates no subagent's artifact; prompts/P1b.md goal 3)`. Do not add the time-lock: it is class H, not a fault stop (PLAN-v2:100).
- **Optional:** where the text says "checks only at the producer's stop, G1 and G3" (PLAN-v2:1313, P2:88, P3:88, P4:75, P6:83), append `plus P1b goal 3's two completion reads (the single chain-function call at /dev's end, /close and /commit, used verbatim, and the command's Stop gate), neither carrying a rule of its own`.
- **Confirmations:** 2.
- **Origin:** A.

**20. No route for a commit-QA REJECT that names an undeclared file** (A86-2)
- **File:** prompts/P4.md
- **Location:** row 5 (:280; :259 at 86b7cbc)
- **Problem:** "Keep Step 6's REJECT." leaves no route for a REJECT naming a code or doc file that no dispatch declared. The "dev when none" default exists only for close-QA findings. An implementer must either guess a role from the file kind (D21) or leave the REJECT unroutable.
- **Fix:**
  - `Keep Step 6's REJECT.` → `Keep Step 6's REJECT; a file it names that no dispatch declared goes to the subagent the attribution journal records as its writer, dev when none (the "Close-QA findings" route and its experiment), and item 1's file-kind mapping goes with artifact_role (D21).`
  - Required second edit: `each name an artifact: dispatch again the declaring dispatch under the same task id` → `each name a file: dispatch again its declaring dispatch under the same task id, or, for an undeclared file, the Step 6 route above`
  - Optional: add an acceptance 4 bullet: a commit-QA `COMMIT: REJECT` naming a dev file is routed to its writer (dev when none) under the same task id, a fresh commit-QA round approves, and the commit lands.
- **Confirmations:** 2.
- **Origin:** A (86b7cbc, R23).

**21. The overnight subagent's decision rule differs from D20** (X18)
- **Files:** prompts/P2.md, PLAN-v2.md
- **Location:** P2.md:409-410, :458-459; PLAN-v2.md:46, :281, :295, :384, :1111 (TC-45)
- **Problem:** the subagent deny message says "take the option your evidence supports ... as an assumption", which is not D20's rule (experiment, else the question's default). Nothing carries a subagent's decision into "Decisions made without the owner".
- **Fix:**
  - P2.md:409-410, PLAN-v2.md:384 and :1111: `Take the option your evidence supports, record it as an assumption in your report, and write your report.` → `Decide by experiment if one can be run, else take the question's default; record the decision, its options and the evidence or experiment in your report, and write your report.`
  - Use the same wording at PLAN-v2.md:46 and :295 ("takes the option its evidence supports and records it as an assumption") and in the :281 bracketed note.
  - P2.md:458-459: after `written as each decision is made` add `; a decision a subagent records in its report is copied into this section by the orchestrator when it collects that report`.
  - Keep the [INFERRED; acceptance 14] tag. Leave prompts/P1.md and audit/ unchanged. Afterwards, `grep -rn "evidence supports"` outside audit/ and reviews/ should print nothing.
- **Confirmations:** 2.
- **Origin:** A.

**22. P3, P4 and P9 are not told to read P1c's "Delivered for later phases" list** (X19)
- **Files:** prompts/P3.md, P4.md, P9.md (P5 optional)
- **Location:** P3.md:~98-104; P4.md:83-85; P9.md:436-447; P5.md:86-110
- **Problem:** only P2 and P10 tell their phase to read P1c's X5 list. P3, P4 and P9 may rebuild, or conflict with, parts P1c already delivered.
- **Fix:**
  - P3, after the "Already done" bullet: `- What P1c's PR lists for P3 under "Delivered for later phases" (X5: the resolver lines its compliant scenarios needed) is the smallest part its suite needed: verify each on your base, complete it inside the disposition and do not rebuild it.`
  - P4.md:83-85: append `; what P1c's PR lists for P4 under "Delivered for later phases" (X5: close.md Step 0) is done in your row's mechanism: verify each on your base, complete it and do not rebuild it.`
  - P9.md, at the end of the "Rows 1, 2, 4 and 5 after P1b" paragraph: `P1c's PR lists under "Delivered for later phases" (X5) what it did of row 2 (docs/dev/ in doc-sync's EXCLUDED_PATTERNS): verify it on your base and do not redo it.`
  - P5 (optional): the generic form of the same bullet.
- **Confirmations:** 2.
- **Origin:** A.

**23. P5 misses P1c's wake rule; P2 misses P1b's cycle_index** (X20)
- **Files:** prompts/P5.md, prompts/P2.md
- **Location:** P5.md, the Gate 4 sentence of the "P1b and P1c" block (~:102-110) and the PR-reading list :59-64; P2.md, the "Already done" list (~:96-108)
- **Problem:**
  - P1c row 17 adds the /dev-overnight wake step's completion rule to pretool-todo-validate, which P5 row 18 rewrites. P5 names only Gate 4's rule, so F6o goes red late.
  - P1b E13 delivers `cycle_index(state)` early, so P2 may build a second cycle index.
- **Fix:**
  - P5: `Gate 4 accepts a recovery resume (P1c row 16): row 18's rewrite keeps that rule.` → `Gate 4 accepts a recovery resume (P1c row 16), and /dev-overnight's first canonical step, the wake, completes only after a CronCreate or ScheduleWakeup call in the span (P1c row 17, X8; F6o replays it): row 18's rewrite keeps both rules.`
  - P5.md:59-64: add `P1c's "Delivered for later phases" and its X8 record` to the PR-reading list.
  - P2, after `the overnight state's extra writers (P1b E13; rows 11 and 14)`: add `the one cycle index, \`cycle_index(state)\` in hooks/lib/overnight.py, which every reader of the cycle number calls (P1b E13, replayed by P1c); rows 7, 11 and 12 keep only what is left of it`.
- **Confirmations:** 2.
- **Disagreement:** the original also added a class-H extension sentence. One refiner drops it (P5.md:104-107 and acceptance 26 already cover it; owner-F7 was dropped on the same ground). The other refiner's H list includes the `/do task sidecar missing` gap, which contradicts item 7. Adopted: no class-H sentence.
- **Origin:** mixed (the cycle_index part is A's; the wake rule is P1c content).

**24. Section 13 carry-over rows still send P1b/P1c deliveries to P2-P5** (SYNC-13, routing part)
- **File:** PLAN-v2.md
- **Location:** section 13 header (after `The PR #5 (P1) rows cite lines at its merge commit d625284.`), rows :1237, :1252, :1254, :1256, :1258, :1259
- **Problem:** the rows still route to later phases items that P1b or P1c deliver (the advisory sink writer, the T4 escalation key, calls()/last_todos()/write-set, the D8 prefixes), so later phases may rebuild them. The reader attribution part of this finding is in item 8.
- **Fix:** insert:
  ```
  Since 2026-10-24 (section 15), P1b and P1c merge before P2. A phase verifies on its base each part of a row below that they deliver and does only the rest:
  - the P2 Path.home row: P1b E12 deletes the artifact-contract-advisory.jsonl writer (doc-sync's cache stays P2's);
  - the P2 template-path row: P1b row 7 and P1c row 18 respell the resolver, late-repair, aggregate and session-index calls they list; TC-44's substitution and the unassigned $TASK_ID stay P2's;
  - the P3 T4 row: P1b row 3 and P1c row 7 delete the escalation records;
  - the P4 and P5 command_span rows: P1b E7 adds calls() and last_todos(), and E6 adds TC-46's write-set reader if it took (c); P4 still adds obligations() and session_families();
  - the P5 G4 row: the reader is P1b's (E3);
  - the P5-a D8 prefix row: P1b E3 removes the prefixes that name a declared artifact's file; the wildcard and directory prefixes stay, and the derived deny overrides them.
  ```
- **Confirmations:** 2.
- **Origin:** A.

**25. COVERAGE: N1 ownership and the R-V1 mapping are stale** (SYNC-14, the COVERAGE part of X16)
- **Files:** COVERAGE.md, COVERAGE-P9-P11.md
- **Location:** COVERAGE.md:308, :316-322; COVERAGE-P9-P11.md:35-37
- **Problem:** COVERAGE says P1c's X9 and R-V1 "predate that record" and that "no phase owns" N1's remaining window and Fact 1. P1c now cites the records and owns both (X9, row 20). It also maps R-V1 to X7/row 14.
- **Fix:**
  - COVERAGE.md:316-322: replace from `P1c's X9 and R-V1 predate that record:` through `no phase owns them yet.` with `P1c cites it: X9 names commits 8ab874b and 98d153a and takes N1's "before" on 1d10ae0; R-V1 names 96bcb8f and 921b512 and their tests in tests/test_landing.py. P1c row 20 owns safe_pull's tee without pipefail (Fact 1) in every case, and N1's remaining window if X9 (ii) refuses (otherwise R-N1 replays it).`
  - COVERAGE.md:308: `R-V1 (X7, row 14)` → `R-V1 (replay only: fixed in P7b by 96bcb8f and 921b512; F4c, not V1-1, is X7 and row 14)`
  - COVERAGE-P9-P11.md:35-37 (optional): one substitution per cell, `P7b, P1, P8, P2` → `P7b, P1, P8, P1b, P1c, P2`. This also covers the P11 parenthesis. The STOPGATE label is handled in item 1 (P9.md:56).
- **Confirmations:** 2.
- **Disagreement:** one refiner says leave the dated COVERAGE-P9-P11 table alone (the convention at COVERAGE.md:191-197), so that part is optional.
- **Origin:** A, partly drift.

**26. The D25 quote is shortened without an elision mark** (F10)
- **Files:** prompts/P2.md, P3.md, P4.md, P5.md, P6.md
- **Location:** P2:90, P3:90, P4:73, P5:88, P6:81
- **Problem:** the opening "还有一件我关心的！就是" is dropped without "…", against DECISIONS' verbatim-quote rule (DECISIONS.md:10).
- **Fix:** `"永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"` → `"还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"` (matches DECISIONS.md:70, PLAN-v2.md:96 and :1303, HANDOVER.md:113, P1b.md:184, P1c.md:153). Re-wrap the lines.
- **Confirmations:** 1.
- **Disagreement:** "…" prefix vs full sentence. The full sentence is adopted.
- **Origin:** A.

**Not reported (dropped by both refuters):**
- owner-F3: the DECISIONS:7 "except" parse.
- owner-F7: P5's instrument-failure block in class H.
- owner-F11: the D20 decision rule written into CLAUDE.md.
- residuals-A86-1: the stage-owned-hunks consumer claim.

## VERDICT

**Acceptable after the listed fixes** (not as is; no rework needed).

- **86b7cbc** (D20-D25 batch residuals) is sound apart from the D8 proof bracket (item 8) and the commit-REJECT route (item 20). No rejected idea was introduced.
- **c728380** (P1b plan-sync) applied the sync list faithfully, with no rejected idea, but:
  - Its own errors are items 2, 7, 8, 9 (the "zero human action" text), 11, 12, 17, 18 and 19-26.
  - Items 1 (in part), 3-6, 10, 13-16 and the fault-count half of 9 are drift: B changed P1b and P1c after c728380 (corrections 7 and 8, 21 faults, the +150 cap, E6, E14, row 1/16/18, X8's hand-off).

Every fix is a local text replacement. Two conditions:
1. Apply the drift items as a re-sync pass after B's P1b.md and P1c.md settle, so they are not hit by B again.
2. Push A's per-item record (reviews/D20-D25-residuals-and-sync-record.md) with those fixes, so the reviewer can audit which R-items and sync items were applied or rejected.