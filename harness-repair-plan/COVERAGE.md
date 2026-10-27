# Coverage cross-check: prompts P7b, P1, P8, P2, P3, P4, P5, P6

Status 2026-10-23: this file yields to DECISIONS.md wherever the two disagree; read DECISIONS.md first, then the current prompts. Rows D3, D4b, D7 and D8, the P3 row of (b) (items 1, 5, 6) and the 'commands/redev.md, continue-cycle.md' row still name withdrawn designs (parking and the after-window question, the continuation include, `/redev <task-id>`, ROLE_BY_ARTIFACT, the question asked when a round changes nothing); gap 7's D4b wording and /redev are settled by D20 and D22. Fix 15's "Word parking" is withdrawn with parking (D20). The owner answers this file asks for (C2, C9, fixes 2 and 8, the "owner input" cells of (b), and "Gaps the owner must decide") were given on 2026-10-19 (DECISIONS.md "Answers recorded 2026-10-19", D19) or are decided by experiment (D18); and fix 2's "Only sessions started after the update", which "holds for G1-G3", no longer does: P2 arms G1 and G3 in sessions started before the pull too (P2's release notes). Inputs: prompts-all/{P7b,P1,P8,P2,P3,P4,P5,P6}.md (each ends with prompts/_common.md byte-for-byte: checked with cmp,
all 8 OK); harness-repair-plan/DECISIONS.md; PLAN-v2.md (docs branch 1efc298e: sections 0-13, section 13 with 13
rows); recall/STATE.md (owner messages O1-O38); the session transcript after STATE.md (owner messages of 2026-10-17
and 2026-10-18, called O39-O45 here). File:line claims about shared lines were re-read on a `git archive` of master
f8c18c276e92e07c14487e9908490aa4bdefbc3a (checkpoint-core.sh, pretool-bash-safety.sh, subagent_restart.py,
README.md, PUBLIC-CORE.md, settings.machine.example.json, prompt-workflow.py, dev-lifecycle.py, the advisory-log
constants and their test readers): all match the prompts.

Owner messages after STATE.md (not in STATE.md section 2; STATE.md should gain them):
- O39-O43 (2026-10-17 03:32-09:09): status and quiz questions; no behaviour asked.
- O44 (2026-10-18 06:12): "我自己在机器上做的是什么意思？我不做，没空，我不能停止claude。现在派出subagent或者workflow阅读之前的聊天记录并撰写完整全面的P1-P6给我…"
- O45 (2026-10-18 06:17): "好的同时现在给我说大概多久可以开发完？那些可以并行开发？" The reviewer read "好的" as consent to implement
  P7b itself and answered the waves: P7b + P1 + P8 now; then P2 + P3; then P4 -> P5 -> P6; then P9 -> P10 -> P11.

## (a) Owner decisions and owner statements -> prompt

Legend: done = merged (P0 PR #2, P0b PR #3, P7 PR #4); later = deferred to P9/P10/P11 (their prompts were written on 2026-10-19, after this table; see COVERAGE-P9-P11.md).

### Decisions

| Id | Implemented by | Deferred (later) | Note |
|---|---|---|---|
| D1 push opt-in | done (P0, P0b); P7b R3 (migrate never seeds `1`, check line), R6 (legacy hooks inert), R7 (pre-landing sessions read rendered settings), R8 (stale fswatch restarted); every prompt: origins are local bare repos | P11: delete the 255 remote refs | P7b's default "harness home only" leaves legacy hooks in the owner's other repos pushing (D1 unmet there); see C9 |
| D2 one dev terminal | P1 (enums, required_values, prose caps, G2), P3 (strict pass, aggregator, resolver), P4 (close/commit lose pass_with_exceptions), P5 (gate accepts chain_pass only), P6 (mismatch is a repair step) | P9 prose pass; P10 dev-report.v1 projection (TC-35) | wording rule "不要给我说失败" stated in P1, P3, P4, P5, P6; missing in P2 (fix 15) |
| D3 in-turn questions | P1 (producer-question artifact; ba/dev cannot call AskUserQuestion, tool policy), P2 (deny + parking), P3 (include relays, asks when a round changes nothing), P4 (close/commit waits), P5 (merge/push/do aborts, block text) | P9 prose; CLAUDE.md Hook Discipline via UD-CM | |
| D4 Stop gates | P1 (coordinator failure rule, stop-completion-gate stub), P2 (time-lock released only by a human /stop record), P4 (loop reset never blocks), P5 (unified gate, launcher, release-input denies, arm) | P10 stub deletion | PLAN adds /redev and two exits (a human-typed harness command, CLAUDE_COMMAND_GATE=off) that DECISIONS D4 does not name (C11) |
| D4b overnight parking: SUPERSEDED by D20 | P1 (prose), P2 (deny, "Parked questions", asked after end_time), P3 (include parks), P4 (loop print), P5 (dev-overnight predicate) | - | owner confirmation of the refined wording UNVERIFIED (STATE 8.18) |
| D4c no error/interrupt code | P1, P2, P3, P5 (Q5 recorded as answered by O26) | - | |
| D5 consent one turn | P1 row 25 (one clearer at UserPromptSubmit), P5 row 15 (`/do <task-id>`) | P9 CLAUDE.md:60 via UD-CM | |
| D6 land once at the end | P2 (per-cycle commit removed, /close added, `--auto` route) | - | |
| D6a owner types 4 commands | P2 (summary prints them and where), P5 (each held by its predicate), P4 (rating per landed parent) | - | |
| D7 close/commit complete dev | P1 (G1 in close/commit spans), P3 (stages, include, `/redev <task-id>`), P4 (wired), P5 (predicates), P6 (re-dispatched dev inherits writes) | - | TC-16 reading flagged to reviewer in P1, P3, P4 |
| D8 producer writes its artifact | P1 (question artifact, BA prefix), P3 (ROLE_BY_ARTIFACT), P4 (rating hook is the writer), P5-a (derived deny), P6 (CLI role, grant binding) | - | |
| D9 native rating | P4 | - | study section: PLAN-v2 section 8 (done in planning) |
| D9a rating log only | P4 (close_* scoring, parse/record removed) | P9 (scripts, injection, echo contracts, tests, OPTIONS_XML), H-Q10 | lifecycle.jsonl has two writers (score-update.sh, close_rating.py) from P4 until P9 |
| D9b asked, not answered | P4 (rating_asked), P5 (gate) | - | |
| D10 technical choices | every prompt (choices section or D10 bullet; P8 via its D10 bullet) | - | |
| D11 settings tracked, filter | done (P7); P7b (landing registers filter, renders, record); all later prompts keep `render-settings check --staged` green | - | |
| D12 no personal values | done (P7 code/settings, R7b); P7b (seeds local list, counts only); P8 (private tree, one engine, markers out of the tracked engine) | P11 history | |
| D13 paseo optional | done (P7); P7b (module carried from previous settings, fresh clone never on); P8 (paseo skips only); P2 (paseo-daemon.md respelling must not fail with module off) | - | |
| D14 permissions | done (P7); P2 (respelling, no grant/withdraw); P3, P5 add no allow entry; P6 policy rows | - | |
| D15 published, no retirement, stubs | every prompt (live landing, stubs with `# STUB:`) | P10 stub deletion | D15 says "stub for one phase"; PLAN TC-37 keeps stubs until P10 |
| D16 history at the end | every prompt: no rewrite | P11 | |
| D17 dead code deleted | P8 (candidate list), P3 and P5 (code their change orphans), P4/P6 ("Now unreferenced") | P10 (rest of I5/I6, unregistered hook files) | |
| D24 one producer, at least one consumer per artifact (2026-10-23) | P1b (every artifact: map, deletions, declaring-dispatch reader, CI check); every later PR carries the D24 table | P10 file-level D17 only (the artifact-level goal is P1b's CI check) | added 2026-10-24; this table has no D18-D23 rows (read them in DECISIONS.md, as the status line at the top says) |
| D25 never fail (2026-10-24) | P1c (replay suite, producer-side fixes, merge rule); P2-P6 and P9-P11 (acceptance: suite green on the PR head, fault replay per changed process class; P7 is merged, P8 and P7b merge before the suite exists) | - | P9 rewrites CLAUDE.md Hook Discipline #5 (C12) |

### Owner statements that ask for behaviour (STATE section 2, plus O44/O45)

| Statement | Implemented by | Later |
|---|---|---|
| O2 clean the repo, harness runs "不多不少"; prompt bloat, /clean useless | P0 done (no re-injection); P4 (close/commit shrink); P8 (junk with privacy residue) | P9 (prose pass, -25 KB scoring prose), P10 (clean tree, size ratchet, recoverable removal) |
| O3 published product; retire nothing; keep live editing | every prompt (D15, live landing) | - |
| O3/O4 changelog-analyst cleanliness -> root cause is dev's files_created | P6 (A3.a); P4 leaves the analyst's rules | - |
| O4/O6 three axes; one producer and one consumer per artifact | P1b (every artifact, CI check); P3, P5 (quoted); P8 goal 4; P4 row 8 (flag writers lose their reader) | P9 (facts that are not runtime artifacts: git option table, includes) |
| O5/O7 runtime proof; disobedient agents forced | armed replays with V2b-V5 in P1, P2, P3, P5; P6 identity from CLI; principle 8 everywhere | - |
| O8 /do needs /close before /commit; overnight close+commit+merge | P4 (Q7, Q-D7b: /commit runs close Steps 1-2); P2 (route); P5 (predicates) | - |
| O9 overnight closes only after the session | P2 | - |
| O10/O12 producer-side only, consumers trust one conclusion | every prompt; P1b removes consumer-side re-checks and second deciding consumers of every artifact; P4 removes what P1b left in /close and /commit | - |
| O11/O12 generic repo, no hardcoded accounts | done (P7); P8 synthetic fixtures; P7b never prints values | P11 |
| O17/O18 no "failure" framing; dev ends complete; user may join mid-way | P1, P1c (no dead end; every fault returns to its producer), P3 (QA and BA-QA fails loop back to their producer; the disposition has no cap; only a producer's own solid question is asked, D23), P1b row 10 and P4 (/close and /commit re-dispatch each gap's declaring dispatch; OPERATION_STALLED asks nothing) | P9 (Hook Discipline #5, C12) |
| O19 QA must-pass removed; dev no-stop gate; /do one turn; overnight `/commit --auto`; close/commit complete dev; no producer writes by orchestrator | P1, P5, P2, P3/P4, P5-a | P11 (255 refs) |
| O20 eight Stop gates; native rating; scoring section | P5; P4; PLAN section 8 | P9 |
| O21 settings tracked/sanitized; local support kept; best permissions; history cleaned; one prompt/branch/PR per phase | done (P7); P7b (local support through seeding); _common branch rules | P11 |
| O22 users make the clone their own; paseo optional; curl/wget/docker safe; questions must be solid; reviewer merges | done (P7); D3 in every prompt; "never merge it yourself" (_common) | - |
| O23 paseo chosen at init | done (P7); P7b keeps the choice | - |
| O28 prompt names the branch | _common (repair/<phase-id>) | - |
| O35 delete dead code now | P8, P3, P5 | P10 |
| O44 no owner step, sessions cannot stop | P7b (whole phase); "No owner step" + live-landing acceptance in P1 (18), P8 (16), P2 (15), P3 (16), P4 (19), P5 (21), P6 (17) | P9 (UD-CM, H-Q10), P10 (doctor on each home), P11 (human-run steps): conflict, see gaps |
| O45 waves and parallelism | P7b + P1 + P8, then P1b, then P1c (2026-10-24), then P2 + P3, P4, P5, P6 as the prompts state (section d) | P9 -> P10 -> P11 |
| 2026-10-24 never fail (D25): measured by the CI replay suite (1)-(4); every later phase merges with it green and adds the fault replay for the flows it changes (P1c's merge rule) | P1c; P2-P6 and P9-P11 acceptance (this sync) | - |

## (b) PLAN-v2 rows P1-P6 and section 13 -> exactly one prompt

PLAN row numbers are table rows in PLAN-v2 order (P1 table :256-273, P2 :363-373, P3 :421-429, P4 :472-483,
P5 :536-552, P6 :626-630). "r" = row of the prompt's scope table.

| Phase | PLAN row -> prompt row(s) | Added by the prompt (not in the PLAN table) | Dropped or replaced |
|---|---|---|---|
| P1 | 1 G2 waiver -> r1-r3; 2 _wire_qa_chain/_cycle_dir -> r4-r5; 3 obligation.py + schemas -> r6-r8; 4 dev-report enums -> r10; 5 stop_contract -> r11; 6 command_span -> r12 (two methods may wait for P4 r12); 7 G3 + do-block -> r13-r14; 8 G1 -> r15; 9 ba-qa-report -> r9; 10 templates identity -> r17; 11 dev/dev-command loops -> r18; 12 overnight prose -> r19; 13 agents -> r20; 14 close.md:606 -> r21; 15 stop-completion-gate -> r22; 16 coordinator -> r23; 17 D5 clearers -> r25; 18 tests -> r26 | r16 BA tool-policy prefix; r24 canary untouched; r27 docs/ledger counts (CI forces them); novelty-check rejection routed to the artifact | TC-38 live 2.1.295 capture -> in-session capture + hooks reference (O44); agents' direct-ask sentence (tool policy denies AskUserQuestion to ba/dev) |
| P2 | 1 prompt-workflow -> r1-r2; 2 todo resolvers -> r3; 3 prose substitution -> r6 + TC-44 section; 4 B1.e sites -> r4; 5 overnight lib/coordinator -> r7-r8 + fallback; 6 deny -> r10; 7 time-lock -> r9; 8 loop/contract -> r11-r13; 9 immutables -> r14; 10 dev-overnight D6 -> r15; 11 arming -> r17 | r5 (section 13 + PR #4 list); r16 docs; r18 tests; continuation reader and prompt-purity parser on window_open/one parser; do.md, merge.md, push.md, skills respelled | "only lines that survive P4" overridden (its own acceptance needs them) |
| P3 | 1 ROLE_BY_ARTIFACT -> r1; 2 resolver -> r2 + disposition; 3 progress_measure/escalation -> r6-r7; 4 aggregator -> r3; 5 include -> r8; 6 /redev -> r9; 7 replay/codex -> r10-r11; 8 S7 -> r12-r14 (+ r15 echo prose); 9 tests -> r16 | r4 dev-lifecycle, close-route-select, qa.md close gate; r5 schema description | "an explicit spec_path must resolve": not built (no producer records it); no later home named (fix 11) |
| P4 | 1 close Step 0/routing -> r1-r4; 2 rating/scoring/--auto -> r4 + rating; 3 commit.md -> r5; 4 analyst/step7 -> r6; 5-7 close_rating, hook, registration -> r7; 8 close.py -> r11; 9 loop TC-13 -> r10; 10 S12 legacy -> r8; 11 D1.e sinks -> r9; 12 tests -> r13 | r12 command_span methods if missing; r14 docs; flag-writer prose dev.md:192,:215, dev-command.md:137,:160 (a PLAN P9 row; moved here, P9 must skip it) | TC-27/29/30 measurements -> conservative branches without owner dialogs |
| P5 | 1 D8 + release inputs -> r1-r2; 2 trailer -> r4; 3 Skill(codex) -> r5; 4 gate -> r7; 5 do branch/write_set -> r8; 6 coordinator -> r9; 7 launcher -> r10; 8 stubs + obligation fns -> r11; 9 Stop group -> r12; 10 break-overnight-lock/stop.md -> r13; 11 merge/push -> r14; 12 todo-validate -> r18; 13 todo hooks -> r19; 14 bookmark copies -> r20; 15 /do -> r15; 16 tests -> r22; 17 P5-d -> r21 | r3, r6, r16 (section 13); r17 ledger/docs; scheduled-prompt rule if unmeasured | live-host systemMessage check -> docs + sandbox (O44) |
| P6 | 1 role source -> r1-r4; 2 written set + dev.md/qa.md -> r5-r7; 3 F3.a -> r5 + F3.a section; 4 grant binding -> r8-r9; 5 tests -> r10-r11 | owner input on general-purpose subagents (O44/D15); analyst policy rows (correction 11) | - |

Section 13 (13 rows):

| Row | Prompt | Status |
|---|---|---|
| P2 Path.home writers (doc-sync :22, G2 :120) | P2 r5 | duplicate in effect: P4 r9 deletes :120 (D1.e) after P2 moves it (fix 3) |
| P5 auto_commit phase is a Stop gate; cleanup skipped | P1 r23 delivers; P5 r9 only verifies | single delivery, stated in both |
| P5-a deny edits of the privacy/settings engines | P5 r3 | ok |
| P8 24 capability_gate tests | P8 r4k | ok |
| P8 installer.py:1804 | P8 r1a | ok |
| P8 fixture secret scan by rule | P8 r1b (+ r10) | ok |
| P8 assignment_target_matrix order dependence | P8 TC-47 (d) + acceptance 15 | ok |
| P8 optional merge/commit-msg privacy steps | P8 r12 (optional) | delivery gap to landed live homes (fix 4) |
| P8 render-settings migrate seeds GIT_AUTO_PUSH=1 | P7b R3 (P8 r11 "moved") | ok; PLAN text still says P8 (fix 13) |
| P5-a commit-guard/hard-ban precision + three P7 limits | P5 r6 | ok |
| P5 systemMessage display; threshold "Checkpoint failed" | P5 r16 | live host replaced by docs + sandbox (O44) |
| P2 in_place without bwrap | P2 owner input | ok |
| P9 README wording (blob unreachable; REG-D fallback, `!`/`&` as limits) | later (P9) | half superseded by P5 r6, which fixes both over-blocks (fix 10) |

Orphans (in no prompt): PLAN P8 C4.e "git-clean AC matrix as a tracked fixture" (P8 r4e: not delivered, owner-only
data); P3's spec_path clause (fix 11); P0b residuals of STATE 8.10 (commands/checkpoint.md prose, dead
`read_command_spec` in prompt-workflow.py, B4, B5, L1-L3) are in no section 13 row; STATE 8.11 stale PLAN points
(TC-53 revert text, P10's laneb row) wait for the P10 prompt; items the prompts send to "Out of scope, found" / "Now
unreferenced" for P10 (P2's kept old allow spellings, P4's close-route-select.py and the write-enforce-flag
`artifact-contract` option, P6's attribution_aggregate_view.py, P1's close-commit-repair-orchestrate.py, P3's
sessionstart-artifact-census.py, P5's Arming option-1 shim) reach P10 only if the reviewer copies them into section 13
after each merge (fix 13).

Other duplicates: tests/test_write_qa_mode.py fixed by P8, then re-pointed by P2 (fix 5). README/ARCHITECTURE count
lines edited by P1 and deleted by P8: both prompts state the rule (P8's deletion wins; the ledger is P1's).

## (c) Contradictions and same-wave file overlaps

### Contradictions between prompts

| # | Where | Conflict | Resolution |
|---|---|---|---|
| C1 | P2.md:176 vs P3.md:228, :624-632 | P2: "if P3 merged first, its new checks are already warning-first; your arming does not promote them". P3 ships its promotion commit in its own PR, so after P3 merges its checks are blocking-ready and P2's arming makes them block (P2.md:13-14 and PLAN wave 3 say P2's replay must include them) | fix 1 |
| C2 | P2.md:164 (+ :19-22) vs P5.md:189-201, :413 | One ledger row "Arming timing": P2 says it is settled by O44; P5 says it needs a new answer and asks it | fix 2; one owner answer for both arming merges |
| C3 | P1.md:20-22 vs P7b.md:15-43 | P1 tells itself to "re-derive row 27's counts from the merged settings.json" after P7b (P7b never edits settings.json) and lists none of P7b's shared lines (README.md :258-268 directly below P1's :253-256; checkpoint-core.sh :319-320/:428 next to P1's :518/:525; the auto-commit.sh notice P1's relay must pass) | fix 5 |
| C4 | P2.md:205 (row 5) vs P4.md:201 (row 9) | P2 moves three advisory sinks (G1 :77, G3 :384-386, G2 :120) that P4 deletes as writers without readers (D1.e); moving them forces edits to hooks/tests/test_artifact_contract_enforce.py:252-254, tests/test_aggregate_dev_report.py:2432/:2450, hooks/tests/test_obligation_gate.py:34 (verified), two of which P3 edits heavily in the same wave, and neither shared-file list says so | fix 3 |
| C5 | P2.md:35-53, P3.md:34-58 | Unlisted P2/P3 overlaps: tests/test_dev_artifact_chain_consumer_contracts.py (P3 :99-131 qa.md close-gate pin; P2 the path pins :57-58, :85-87, :118, e.g. `PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"`); README.md (P2 :562, :570; P3 :619); prompt-workflow.py hunks adjacent at :1900-1930 (P3's `_ordinary_dev_start` print lines vs P2's `handle_phase_a` :1923) | fix 6 |
| C6 | P8.md:329-332 vs P2.md:204 | P8 may change write-qa-mode.sh to match the four failing cases (harness-home registry); P2 then reverses the fallback to the repository root | fix 7 |
| C7 | P8.md:291 (row 12) vs P7b.md:234 (R1 "landed") | Installed git hooks are copies (scripts/bootstrap step 5 `cp`, verified); the landing skips a landed home, so hooks P8 adds after P7b merged, or a changed hooks/git-hooks/pre-commit, never reach the owner's homes, and he runs no init (O44) | fix 4 |
| C8 | Section 13 P9 row vs P5.md:246 (row 6) | Section 13 asks P9 to list the REG-D `# comment`/`$'..'` fallback and the `!`/`&` hard-ban case as README limits; P5 row 6 fixes both | fix 10 |
| C9 | P7b.md:126-132 vs D1 | Default "harness home only" keeps installed legacy push hooks active in the owner's other repositories; P0's REQUEST covered them by a human step that O44 removed; the question text does not tell the owner this | fix 8; owner decides |
| C10 | P5.md:57-61, P4.md:56-59 vs P2.md:752-756 | P4 and P5 read P2's locator, window_open, timelock_released and fallback rule "from P2's PR", but P2's PR body has no hand-off heading (P1 and P3 and P5 have one) | fix 9 |
| C11 | DECISIONS D4 vs PLAN S1/P5 | D4 names eight commands and two human exits; PLAN and P5 gate nine (adds /redev) and add two exits (a human-typed harness command, CLAUDE_COMMAND_GATE=off); never confirmed by the owner (STATE 3.1) | owner gap (low); no prompt change |
| C12 | CLAUDE.md:98 at d625284 (Hook Discipline #5) vs register DT4, D25 | #5 lets ordinary /dev recovery record a lane or cycle as blocked/incomplete and "terminate honestly"; the owner: "诚实终态永远不允许" (teachings:103); P1c requirement (3), no dead end | P9 rewrites #5 under D20 and D23 (P9 D2 bullet, row 16, acceptance 16); Lesson 16 (:43) stays consistent; P1b and P1c do not edit CLAUDE.md |

### Wave 2 overlaps (P7b, P1, P8), verified at f8c18c2

| File | P7b | P1 | P8 | Stated in |
|---|---|---|---|---|
| hooks/lib/checkpoint-core.sh | `_checkpoint_rate_limited_push` :319-320; trailer :428 (optional) | read-tree redirects :518, :525 | :95 (comment :90-94), `_checkpoint_push_gate_pii_signature` :247-314, call :403 | P7b, P8; P1 names only P8 (fix 5) |
| README.md | :74-130, :166-167, :258-268 | :253-256, :423, :821, :869 | :423, :821, :829 deleted; :820 (NESTED-REPO); :325-327 (row 12) | P7b, P8; P1 names only P8 (fix 5) |
| ARCHITECTURE.md | - | :20, :21, :28, :39, :357, :362 | count lines, :396 | P1, P8 |
| PUBLIC-CORE.md | :46-48, :69-71 | - | sections 3 and 5 (:80-123, :174-196), :116, :168 | P7b, P8 |
| hooks/pretool-bash-safety.sh | env test before :8; helper near :377-387, :1816 | - | :1961, :2083-2084, :2168 | P7b, P8 (P8 omits the :8 area, fix 16) |
| hooks/lib/subagent_restart.py | :826 | - | :111, :775-776 | P7b, P8 |
| scripts/bootstrap | steps 2-5 non-interactive, step 5 body kept | - | step 5 body (row 12, optional) | P7b, P8 |
| hooks/auto-commit.sh | trigger + notice (exit-0 paths :23, :29, :51, :57) | tests rely on its output; coordinator relay kept | - | P7b, P1 (relay only) |
| render-settings, doctor, tests/test_settings_filter.py | yours | - | do not edit | P7b, P8 |
| settings.json, stop-workflow-coordinator.py, prompt-workflow.py | not yours | P1 | - | all three |
| conftest.py, baseline.yml, check-public-core.sh | not yours | - | P8 | all three |
| test_artifact_contract_enforce.py, test_obligation.py, test_contract_runtime_version_dispatch.py, test_laneb_stop_coordinator.py, test_aggregate_dev_report.py, test_report_projection_contract.py, policies/tool-policy.v1.json, commands/dev-overnight.md, docs/ENFORCEMENT-LEDGER.md | - | heavy/light as listed | light as listed | P1, P8 (identical lists) |

Resolution rule (stated in P7b.md:45-46, P1.md:56-58 and :21-22, P8.md:101-103 and :32-34): the PR that merges second
merges origin/master (merge commit, no rebase), re-verifies the shared lines, keeps the other side's edits, re-runs its
acceptance tests. Count-line conflicts resolve to P8's deletion; the ledger and per-event tables are P1's.

### Wave 3 overlaps (P2, P3), verified at f8c18c2

| File | P2 | P3 | Stated |
|---|---|---|---|
| hooks/prompt-workflow.py | `resolve_project_dir` :62, `_is_active_state` :105, `find_any_overnight_state` :139, `run_todo_script` :332, `handle_phase_a` :1923, `main` :1999 | `_DEV_REPORT_TERMINAL_STATUSES` :1783, `_dev_report_reached_terminal` :1786, `_ordinary_dev_start` :1831-1921 | both; adjacency at :1900-1930 unstated (fix 6) |
| scripts/dev-lifecycle.py | `_load_close_verdict_module` :109-117 | provider plumbing :82-102, :201-235, :284-354, :331-412, :596 | both |
| hooks/subagentstop-artifact-contract-enforce.py | ADVISORY_LOG :120 | heavy | both (removed by fix 3) |
| hooks/pretool-aggregate-check.py | :384-386 | `main` :674-714, :247-369 | both (removed by fix 3) |
| agents/qa.md, agents/dev.md | path respelling | close gate :206-226; one report-template line each | both |
| commands/redev.md, continue-cycle.md | respell if P3 merged first | P3 | both |
| tests/test_dev_artifact_chain_consumer_contracts.py | path pins | qa.md close-gate pin | neither (fix 6) |
| README.md | :562, :570 | :619 | neither (fix 6) |
| test_artifact_contract_enforce.py, test_aggregate_dev_report.py, test_obligation_gate.py | advisory-log readers if sinks move | escalation/aggregate cases | neither (fix 3 removes it) |
| settings.json, overnight lib/hooks, stop_contract, coordinator | P2 only | none | both |

Resolution rule (P2.md:11-14, :54; P3.md:11-14, :58): P2 merges first; the second merges origin/master and re-runs its
acceptance tests; if P3 merges first, P2's armed replay includes P3's promoted checks.

## (d) Dependencies and waves: prompts vs PLAN-v2

| Prompt | Wave stated | Must be merged first (checked how) | PLAN-v2 | Match |
|---|---|---|---|---|
| P7b | 2a, beside P1/P8, merge first | P0, P0b, P7 (merge-base f8c18c2; settings.machine.example.json) | absent | new phase from O44; PLAN sections 4, 5, 6, 13 not updated (fix 13) |
| P1 | 2 with P8 | P0, P0b, P7 (+ GIT_AUTO_PUSH "0") | W2, P0+P7 | yes |
| P8 | 2 with P1 | P0, P7 | W2, P0+P7 | yes |
| P1b | 2b alone (2026-10-24) | P1, P8, P7b (merge titles; P7b's land script; P8's deletions; green CI) | section 15 after this sync | yes |
| P1c | 2c alone (2026-10-24) | P1b, P8, P7b (merge titles; P8's hermetic conftest) | section 15 after this sync | yes |
| P2 | 3 with P3, merges first | P1, P8, P7b, P1b, P1c (merge titles, P1 files, stop-completion-gate gone, P1c's suite) | W3, P1+P8+P7b+P1b+P1c | yes after this sync |
| P3 | 3 with P2, merges second | P1, P8, P7b, P1b, P1c (+ ba-qa schema, canonical_task_id, STUB, P1c's suite) | W3 | yes after this sync |
| P4 | 4 alone | P1, P8, P2, P3 (+ STOPGATE block) | W4, P2+P3 | yes |
| P5 | 5 alone | P1, P8, P2, P3, P4 | W5, P4 | yes |
| P6 | 6 alone | P1-P5 (+ do-report without "blocked") | W6, P5 | yes |
| P9, P10, P11 | written 2026-10-19 (COVERAGE-P9-P11.md) | P9: P6+P8; P10: P9; P11: every PR merged; each also lists P1b and P1c after this sync | W7-W9 | P6 states P9 waits for it |

Merge order inside waves matches PLAN (wave 2 either order, P8 preferred; wave 3 P2 first). When this table was
written, P7b was a dependency of no prompt, yet P5 row 6 edits the hard-ban block holding P7b's :1816 helper call and
row 16 builds on the auto-commit notice P7b extends (fix 12, recommended). Since then P2-P6 and P9-P11 start only after
P7b, P1b and P1c are merged (their "Before you start"; the P4-P6 cells above list none of the three, the P9-P11 cell
lists P1b and P1c but not P7b), and P1b and P1c need P7b too (rows above, 2026-10-24). The waves told to the owner on
2026-10-18 equaled the prompts' waves of that date; P1b and P1c (waves 2b and 2c) were inserted on 2026-10-24 (row O45
in (a)).

## Fixes

1. **P2.md:176.** Replace the TC-40 bullet with: "TC-40: P3 ships its new G2/G3 checks warning-first and promotes them
   in its own PR after its armed replay. If P3 merged first, its promoted checks start blocking with your arming
   commit: your armed replay (acceptance 14) includes them and shows 0 false blocks. You promote nothing."
2. **P2.md:164 and P5.md:189-201 (Arming timing).** P2.md:164: replace "'Arming timing' is settled by the owner's
   2026-10-18 message (above)." with "'Arming timing' is one ledger row for your arming commit and P5-d. The owner's
   2026-10-18 message voids its 'no cycle in flight' answer; apply P5's recommended option 'Only sessions started
   after the update', which holds for G1-G3 when a running session keeps the env it loaded. If the CLI's settings
   reference says settings env reaches running sessions, ask the owner P5's 'Arming' question (same header and
   options) once before the arming commit and record the answer in the PR for P5." P5.md:189: append "If P2's PR
   recorded an owner answer to 'Arming', apply it and do not ask again."
3. **Advisory sinks (P2 row 5, headers, acceptance; P3 header; P4 interface).** P2.md:205: drop
   hooks/subagentstop-artifact-contract-enforce.py, hooks/pretool-aggregate-check.py, hooks/pretool-obligation-gate.py
   and `ADVISORY_LOG :120; :384-386; :77` from the row; add "G1 :77, G3 :384-386 and G2 :120 write logs no code reads;
   P4 deletes them with their test readers (D1.e), which also delivers section 13's :120 item: do not move them."
   P2.md:45-47 and P3.md:47-50: make both files "P3 only". P2.md:512: "one advisory-log writer added from PR #4's list
   (posttool-lane-completeness-watch.py)". P2.md:628: "the doc-sync cache and the lane-completeness advisory log land
   there". P4.md:58-59: "You delete the three advisory sinks (row 9); this also delivers PLAN-v2 section 13's P2 item
   for hooks/subagentstop-artifact-contract-enforce.py:120: say so in the PR."
4. **Installed git hooks reach landed homes (P7b R1, P8 row 12), from the owner conversation (O44).** P7b.md:234-235:
   extend "landed" with "and the installed pre-commit (and every hook bootstrap step 5 installs) is byte-identical to
   its source under hooks/git-hooks/; when only that differs, re-run step 5 alone (no migration, no seeding)", plus a
   case in acceptance 11 (cost stays under 50 ms) and 9. P8.md:291 row 12: add "On the owner's homes the new hooks
   arrive through P7b's landing, which re-runs step 5 when an installed copy differs from its source; add that case to
   acceptance 16."
5. **P1.md:20-22.** Replace the P7b paragraph's second and third sentences with: "Files P7b also touches: README.md
   :74-130, :166-167 and :258-268 (directly below the :253-256 paragraph your row 27 rewrites: expect a textual
   conflict, keep both sides); hooks/lib/checkpoint-core.sh `_checkpoint_rate_limited_push` :319-320 and possibly the
   trailer :428 (yours: :518, :525); hooks/auto-commit.sh, whose landing notice reaches the user through the relay
   row 23 keeps; hooks/pretool-bash-safety.sh and hooks/lib/subagent_restart.py (not yours). If P7b merges while your
   PR is open, merge origin/master, keep its edits, and re-run acceptance tests 9 and 15-18."
6. **P2.md:35-53 and P3.md:34-58 (shared-file lists).** Add to both: "tests/test_dev_artifact_chain_consumer_contracts.py:
   P3 changes test_close_qa_accepts_one_parent_lane_matrix_without_fake_parents (:99-131); P2 changes only the path
   pins its respelling breaks (:57-58, :85-87, :118); the second to merge keeps both." "README.md: P2 :562, :570; P3
   :619; disjoint." To the prompt-workflow.py bullet: "the hunks meet near :1900-1930 (P3's printed lines in
   `_ordinary_dev_start`, P2's `handle_phase_a`): expect a textual conflict and keep both sides."
7. **P8.md:331-332.** After "...in the script (b)." add: "For the cases with CLAUDE_PROJECT_DIR unset, fix the test,
   never the script: P2 (its row 4) sets the fallback root to the repository root, and a script change here would be
   reversed there."
8. **P7b.md:127-131 (owner input).** Add the consequence to each option: "'harness home only': legacy hooks in your
   other repositories keep pushing on every commit (D1 is then not met there, and nothing else removes them, because
   you run no steps)"; "'also the other repositories': the same reversible rename there, counts only". Keep the
   default as written unless the reviewer obtains the owner's answer first.
9. **P2.md:752-756 (PR body).** Add the heading "**Hand-off to P4 and P5**: the signatures and rules of session_state,
   window_open, closeout_gaps, cycle_index and stop_contract.timelock_released; the locator per isolation kind
   (fresh-clone case included); the coordinator's timelock-fallback rule the launcher copies; the loop's seed
   rendering and continuation print."
10. **P5.md:400-420 (Corrections to PLAN-v2).** Add: "Section 13's P9 row asks README to list the `# comment`/`$'..'`
    REG-D fallback and the `!`/`&` hard-ban case as limits; row 6 fixes both, so they are not limits after this
    phase. List the README limits lines under 'Out of scope, found' for P9, whose row keeps only the refused-snapshot
    wording."
11. **P3.md:441 and :321.** Extend "the spec clause is not implemented: no producer records an explicit spec binding"
    with "; PLAN-v2 P9 (D2.d: prompt-workflow becomes the single producer of spec_path) is the phase that can record
    it: name that in the PR so the clause is not lost."
12. **Recommended: P2.md:56-68, P3.md:60-77, P4.md:28-44, P5.md:37-56, P6.md:30-53.** Add to "Before you start": the
    merges include one titled `P7b: …`; replace each "P7b may merge before or alongside you" paragraph with "P7b is
    merged (wave 2); its files are not yours". Reason: the owner was told P7b runs in the current wave, and P5 row 6
    edits the hard-ban block that holds P7b's :1816 helper call.
13. **PLAN-v2.md (docs branch, reviewer).** Section 4: replace the P0 row ("Remove the installed post-commit push
    hooks..."), the P7 row ("Run init ... migration ... doctor --strict"), "Write the overlay and the private-literal
    list (only init, run by the human...)" and the P2/P5 row ("Tell the reviewer when no /dev cycle is in flight")
    with "P7b's landing (no owner step, O44)" and "none; live landing, Arming per the P5 answer". Sections 5 and 6: add
    P7b (wave 2, needs P0+P7, caps +60 outside bootstrap/install and target +250 inside). Section 7: Arming timing ->
    "re-asked in P5 under O44"; Q5 -> "answered by O26". Section 13: row "P8 ... render-settings migrate" -> P7b; add
    rows for the P0b residuals (P9: commands/checkpoint.md prose; P10: dead `read_command_spec`, B4, B5, L1-L3) and,
    after each merge, the "Out of scope, found" / "Now unreferenced" items listed under (b). P7b.md:95 already promises
    the section 4 update; it is not done at 1efc298e.
14. **Deferred-phase note for the P9 prompt (when written).** Skip dev.md:192, :215 and dev-command.md:137, :160
    (P4 row 8 deletes the flag prose with its writer).
15. **P2.md:129 (low).** Append to the D2 bullet: "Word parking, gaps and deny messages as process steps, never as a
    failure ('不要给我说失败', O17)."
16. **P8.md:26 (low).** "an environment helper near :377-387 and :1816" -> "an environment test before :8 and a helper
    near :377-387 and :1816".

## Gaps the owner must decide

1. The six OPEN inputs the prompts ask (all can go in one AskUserQuestion before wave 2/3): P7b other repositories
   (fix 8); P8 TC-47's three tool-policy rules plus any root/non-root test case; P2 in_place without bwrap; P4 H-Q5 and
   H-Q3; P5 Arming timing (one answer for P2's G1-G3 arming and P5-d, fix 2); P6 general-purpose subagents.
2. How merged code reaches the live homes: no hook pulls, /pull is human-only, P7b forbids an automatic pull, and only a
   manually started fswatch daemon pulls. Every "live landing" acceptance assumes the merge arrives. Also unanswered:
   whether a home already pulled P7 alone and sits in S3/S4, where P7b can never reach it (P7b fact 9; the reviewer's
   2026-10-18 09:18 request is open).
3. Later-phase human steps that O44 refuses: UD-CM (apply the CLAUDE.md diff; PLAN forbids agent CLAUDE.md edits),
   H-Q10 (local score stores), P10 "run doctor on each home before stub deletion", P11 (every step human-run; who
   deletes the 255 refs, STATE 8.15). Decide before those prompts are written.
4. Off-site backup of the tmpfs live home (STATE 8.22; asked 2026-10-17, unanswered): push is off and P7b disables the
   legacy push hooks, so nothing leaves the machine; P7b lists it out of scope.
5. P8 row 4e: the 733-case git-clean matrix needs a file only the owner's machine has; the module keeps skipping on
   clean checkouts (PLAN C4.e undelivered). Accept, or provide the file.
6. Defaults the prompts apply without asking (veto possible): C3.d delete the paseo teachings record (P8); Q1 no todo
   scripts for /commit, /merge, /push (P5); Q7, Q-D7b, H-Q6, H-Q7 (P4).
7. Confirmations never given explicitly: D4b's refined wording (STATE 8.18); D4's extra exits and /redev (C11); the
   reading of "好的" (O45) as consent for the reviewing session to implement and merge P7b itself, while the P7b prompt
   is written for a separate session that never merges its own PR.

## (e) Addendum 2026-10-24: P1b and P1c

Inputs: prompts/P1b.md and prompts/P1c.md (each ends with prompts/_common.md byte for byte), inventory/ (the d625284
map), audit/2026-10-23/, reviews/P1b-plan-sync.md.

| Requirement (DECISIONS.md D24, D25; only quoted words are the owner's) | Delivered by | Test |
|---|---|---|
| D24: one producer, at least one consumer, consumers trust one conclusion | P1b Goals 1-4, scope rows 0-18, E1-E14 | P1b acceptance 3, 6, 10-13 |
| D24: proved every time, no hand list | P1b Goal 5, row 19 (CI check, trace runner, ten compliant drivers) | P1b acceptance 2, 3 |
| D25 (1) ten pipelines compliant, 0 blocks, 0 hook errors | P1c Goal 1, row 2, "The suite" (1): 16 scenarios in 2 settings modes | P1c acceptance 3 |
| D25 (2) faults return to their producer, next round passes, zero human action | P1c rows 3 and 7-17; F1, F1q (missing), F2, F2j, F2g (malformed), F3a, F3q, F3b (old version, E1), F4, F4c, F4s (index.lock), F5, F5f (interrupted), F6, F6o (usage limit, X8), F7, F7b (fan-out lane), F8, F8q, F8p, F8c (an unfinished cycle met by the human's /close or /commit; P1b's routing loops, replayed): 21 faults, each in 2 modes | P1c acceptance 4 (aside: the human /restart of F5, F5f and F6, D22, register RD4; the human /close or /commit of each F8 fault, D7, register CC4) |
| D25 (3) no dead end apart from /stop | P1c X6, row 4 (block sites enumerated at test time; classes G, D, H, U) | P1c acceptance 5 |
| D25 (4) a regression replay per fixed defect | P1c row 5: R-P1, R-E1, R-N1 (X9, row 20), R-V1 (P7b's V1-1/NV-1 fix, commits 96bcb8f and 921b512, replayed with index.lock held) | P1c acceptance 6 |
| D25 merge rule | P1c "Merge rule from P1c on", row 6 (fault-coverage step); P2-P6 and P9-P11 acceptance items (this sync) | P1c acceptance 8; each later PR |
| Earlier words CC4, CC8, DT2, DT3, DT4, HC2 | P1c "Owner decisions" (quoted with sources); DT4 against CLAUDE.md #5: P9 (C12) | P9 acceptance 16 |

What moved from later phases into P1b and P1c: PLAN-v2 section 15; P2-P6 name their share in their "P1b and P1c"
block, P9 in "Rows 1, 2, 4 and 5 after P1b" and P10 under "What earlier phases left to you".

Found while syncing:
- N1, V1-1 and NV-1 are recorded, with their before and after evidence, in reviews/P7b-PR-record.md (rows N1 :220,
  V1-1 :242, NV-1 :253; added in 4a9256a, after dac09ec9). P1c's X9 and R-V1 now reproduce them from that record
  and P7b's commits (N1: 8ab874b and 98d153a, "before" on 1d10ae0; V1-1: 96bcb8f; NV-1: 921b512). P1c also takes what
  the record left to the reviewer: N1's remaining window (a /pull before the next Stop, :1334-1342; X9 decides whether
  row 20 fixes it) and safe_pull's tee without pipefail (Fact 1, :1300-1304; row 20).
- docs/reference/paseo-daemon-teachings-20260910.md, the source of CC8, DT4 and HC2, is deleted on P8's branch; P1c reads
  it with `git show d625284:`.
- audit/2026-10-23/report-zh.md section 4 item 5 suggests giving the 13 artifacts with no owning phase to P9 or P10; P1b's
  rows own them now. report-zh.md is a dated audit record and is not edited.
- P1b and P1c both name the obligation-sourced overnight schema (P1b rows 6 and 13 through E13; P1c row 13) and G2's
  plain exit 2 (P1b row 3; P1c row 7). P1b lands first; P1c re-verifies on its base and adds only the replay ("A defect
  P1b or P8 already closed needs only its replay", P1c "Before you start").
