# Artifact producer/consumer ledger (expected master: P0, P0b, P7, P1, P7b, P8 merged)

Tree audited: `/tmp/claude-0/-home-user/fc2a4e86-9f11-582c-8078-b4c463755b6b/scratchpad/p23/expected` (HEAD `abc58aa`).
Every `file:line` below is relative to that tree unless it names another file. Audit date 2026-10-23.
Method: code and prose read for every pipeline command (`/spec /dev /redev /dev-command /dev-overnight /do /close /commit /merge /push`), every registered hook (`settings.json` hooks block), and the scripts and agents they call. One experiment was run (section 3, E1). Anything not read in code is marked **inferred**.

---

## 1. Owner requirements this ledger is measured against (sourced; nothing else is assumed)

| # | Requirement | Source (file:line) | Date | Kind |
|---|---|---|---|---|
| R1 | "/close and /commit may only detect 'the development cycle itself failed' (class a). Every artifact-missing/schema (b), file-content/hash/ownership (c), environment/grant/lock (d), input/precondition (e) failure at close/commit is a defect; the guarantee must be established during /dev, /do, /redev, /dev-command, /dev-overnight." | docs/reference/close-commit-zero-failure-mechanism-20260928.md:13-16 ("User rulings") | 2026-09-27 | user ruling as recorded by the design doc |
| R2 | "artifact-missing detection belongs on the PRODUCER of each artifact (at the moment it finishes) and on the ORCHESTRATOR (at dispatch and collection points)." | same doc :17-18 | 2026-09-28 am | user ruling (recorded) |
| R3 | "the enforcement primitive is hooks; new mutable state files are themselves new failure surface; cross-event state via new files: zero." | same doc :19-20 (C1 :26-27) | 2026-09-28 pm | user ruling (recorded) |
| R4 | Cycles often start without a spec; the mechanism must not depend on spec presence. | same doc :21-23 | 2026-09-28 | user ruling (recorded) |
| R5 | C2 "zero new class-(b)/(c) checks at /close or /commit"; C5 "a blocking gate returns the artifact to its own producer". | same doc :28, :32-35 | 2026-09-28 | acceptance criteria derived from R1-R3 by the design driver (secondary) |
| R6 | The producer-side schema stop gate blocks immediately ("the user ordered immediate blocking on 2026-09-26"). | hooks/subagentstop-artifact-contract-enforce.py:59-60, :90-91 | 2026-09-26 | recorded in a docstring (secondary) |
| R7 | "artifact-completeness detection must move from /close and /commit time -- where the producing agent's context is already gone -- to the dispatch moment." | hooks/pretool-obligation-gate.py:5-8 ("User ruling (spec-20260930-092323 traceability rows 1-2)") | 2026-09-30 | recorded in a docstring (secondary) |
| R8 | Self-consistency axis: "one producer and one consumer per artifact" (goal phrase "彻底完整系统性干净实现目的不多不少"). | earlier session's compaction summary .../transcript/rec8.txt:5; COVERAGE.md:55 (row "O4/O6") on refs/remotes/origin/claude/vibrant-hopper-bazrn8:harness-repair-plan/ | owner messages O4/O6 (original wording lost) | paraphrase by the earlier session (secondary) |
| R9 | "producer-side only, consumers trust one conclusion" | COVERAGE.md:59 (row "O10/O12") | lost STATE file | paraphrase (secondary) |
| R10 | "Each fix lands on the single producer of an artifact ... Never add consumer-side checks: nothing new in /close, /commit or the changelog-analyst ... /close and /commit only shrink." | DECISIONS.md:13-16 | 2026-10-13 | written by the earlier session as owner decisions (secondary) |
| R11 | D8 "The orchestrator never writes a producer's artifact." | DECISIONS.md:49 | 2026-10-13 | secondary |
| R12 | D18 decide by experiment, never ask the owner to arbitrate (verbatim quote "...不要让我裁决任何事情了"); D19 no owner machine step ("我不做，没空，我不能停止claude"). | DECISIONS.md:120-125, :126-129 | 2026-10-19 / 2026-10-18 | verbatim owner quote inside a secondary file |
| R13 | Today's statements (relayed in this workflow's task text, no file): (1) overnight parking (D4b, DECISIONS.md:40-45) rejected, "Overnight must be unattended"; (2) P3's owner-tagged gaps / ROLE_BY_ARTIFACT table rejected as hardcoding, "a manual it can never align with or execute completely, 100%"; (3) /redev is "simply /dev when saving context", not a continuation (rejects D7, DECISIONS.md:46-48, and PLAN-v2.md:410); (4) the agent may pause by asking with AskUserQuestion; (5) "What I care about most is the artifact producer/consumer problem." | task text of this run | 2026-10-23 | relayed owner words |

Read together (R1-R3, R8-R10), the measurable rule each row is checked against is: **one producer writes the artifact; the producer's own stop (a hook) and the orchestrator's dispatch/collection (a hook) establish existence and correctness; there is one consumer that trusts that conclusion; /close and /commit add no class-b/c checks; no new mutable state file.** Problem labels used below:

- **MP** more than one producer (writer) of the same artifact or fact
- **MC** more than one consumer deciding on it (each with its own rule)
- **RD** a consumer re-derives or re-checks what the producer side already established (incl. checks at /close or /commit, R1/R5)
- **DEAD** no producer or no consumer
- **PROSE** existence/correctness rests on an agent-executed prose instruction instead of a code check
- **TABLE** a hardcoded table (artifact -> role, accepted-line list, regex family) that duplicates what an artifact or schema already declares
- **STATE** a mutable state file (R3)
- **MISMATCH** producer contract and consumer contract disagree (proved or inferred)

---

## 2. Ledger

Enforcement column legend: *producer-stop* = SubagentStop hook on the producing subagent; *dispatch* / *collection* = PreToolUse/PostToolUse hooks on the orchestrator's Agent call; *consumer* = a later pipeline (/close, /commit, Stop) re-checks. Default modes come from code, because settings.json sets none of the switches (settings.json env block has no `CLAUDE_OBLIGATION_*`, `ARTIFACT_CONTRACT_ENFORCE_MODE`, `DO_REPORT_GATE_MODE`).

### A. Cycle start (UserPromptSubmit)

**L01 Task identity (task_id / DEV_SESSION_ID / registry directory name)**
- Shape: three spellings of one fact: hook-minted `dev-<ts>` / `dev-command-<ts>` (hooks/prompt-workflow.py:1462-1480; /redev is minted exactly like /dev, :1929-1931), bare `<ts>` for /do (:1320-1360), bare `<timestamp>` in artifact names (commands/dev.md:1220 "No prefixed forms (`dev-`...) are permitted in NEW artifacts"), lane `<ts>-<lane>`, overnight `{pipeline.timestamp_suffix}`.
- Producers: prompt-workflow.py (two allocators); the orchestrator (fallback `dev-$(date ...)` commands/dev.md:199; substitutes `<timestamp>` into every obligation, dev.md:441-460); /do agent fallback `noclobber` mint (commands/do.md:58).
- Consumers that re-derive the mapping, each with its own rule: hooks/lib/obligation.py TASK_ID_RE :123-125, canonical_task_id :614-619, registry_dir_for :630-646; hooks/posttool-lane-completeness-watch.py:113-119; hooks/subagentstop-artifact-contract-enforce.py:220-232 (session_ts regex); hooks/pretool-aggregate-check.py:96-107 (prompt regexes); commands/dev.md:128 (strip `dev-`); commands/close.md:582 `SESSION_ID="dev-${TASK_ID}"` and :553-561 `.claude/dev-registry/dev-<TASK_ID>/...`; scripts/dev-lifecycle.py:37.
- Enforcement: none of its own; each consumer guesses.
- Problem: MP, MC, RD. One identity fact, at least 8 independent derivations. **Inferred:** close.md:582 maps a /dev-command cycle (`dev-command-<ts>`) to `dev-<ts>`, and `write-qa-mode.sh --init-if-missing` (scripts/write-qa-mode.sh:38-45, armed by close.md:244-252) then creates a second registry for the same task.
- Plan: P6 (identity measured), P9 (one producer per fact).

**L02 `docs/dev/user-requirement-<DEV_SESSION_ID>.md`**
- Producers: hooks/prompt-workflow.py:1573-1574 (O_EXCL); orchestrator fallback heredoc commands/dev.md:209-213.
- Consumers: every BA/QA/dev dispatch prompt (dev.md:435, :621, :844, :993); scripts/graphify-query.py (`--requirement-file`, dev.md:244-247); /close session summary (close.md:861).
- Enforcement: existence by construction (O_EXCL) when the hook runs; nothing when the fallback runs.
- Problem: MP (hook + prose fallback). Otherwise the cleanest artifact in the tree.
- Plan: none.

**L03 Dev-registry agent sentinels `.claude/dev-registry/<sid>/<agent>.json` (incl. `qa.json` fields `qa_mode`, `task_id`)**
- Producers: prompt-workflow.py:1546-1553 (O_EXCL, 18 roles); orchestrator fallback printf commands/dev.md:202-208 (17 roles, no graphify); scripts/overnight-init.sh; prompt-workflow `_repair_overnight_registry` :1668; scripts/write-qa-mode.sh:58-90 (mutates `qa_mode`/`task_id` in place; `--init-if-missing` creates, :38-45), called from dev.md:609, :978, close.md:244-252; the test-writer subagent itself ("or create if absent", dev.md:799).
- Consumers: hooks/pretool-cp-checkin.py (FIRST ACTION Read -> agent-index, :40-48); subagentstop-artifact-contract-enforce.py:1218-1221 (`qa_mode == ba_validation` skip), :237-246 (`task_id` anchor); subagentstop-e2e-enforce.py (`task_id`, `expected_absent`, :166-205); hooks/lib/obligation.py:978-982 (directory existence classifies a dispatch as dev-family for the terminal gate).
- Enforcement: write-qa-mode.sh refuses foreign/absent sentinels (:66-84) except with `--init-if-missing`.
- Problem: MP (6 writers), STATE (`qa_mode` is a mutable mode switch flipped by the orchestrator between dispatches, dev.md:606-611 vs :975-980), PROSE (identity is bound only if the subagent obeys the "FIRST ACTION: Read" line, dev.md:220; every resolver-dependent hook fails open otherwise, hooks/lib/agent_resolver.py:17-21).
- Plan: P6 (CLI role binding replaces FIRST ACTION, per COVERAGE.md:35).

**L04 `.claude/dev-registry/agent-index.json`**
- Producer: hooks/pretool-cp-checkin.py:155-190 (on the FIRST ACTION Read, flock).
- Consumers: hooks/lib/agent_resolver.py (used by subagentstop-e2e-enforce, -codex-enforce, -artifact-contract legacy path, pretool-tool-policy, pretool-subagent-code-block, pretool-git-privilege-guard, pretool-overnight-hook-guard, posttool-codex-skill-ledger, hooks/lib/commit_pipeline.py, hooks/doc_sync/hook_ledger.py).
- Enforcement: fail-open by contract (agent_resolver.py:17-21); stale agent-id reuse documented (:23-40).
- Problem: STATE (project-global mutable index across all sessions), MC (10 consumers), PROSE-dependent (populated only through the prose FIRST ACTION read).
- Plan: P6.

**L05 Enforcement flags `.claude/dev-registry/<sid>/{e2e,codex,artifact-contract}-enforce.json`**
- Producers: scripts/write-enforce-flag.sh:71-95 called by prompt-workflow.py:1576-1619, by the orchestrator fallback (dev.md:214-217), by /close's QA-arming prose (close.md:244-274), by scripts/overnight-init.sh:296-322 (arms e2e and codex only, never artifact-contract).
- Consumers: subagentstop-e2e-enforce.py (step 5), subagentstop-codex-enforce.py:12-16, subagentstop-artifact-contract-enforce.py:1206-1211 (legacy path).
- Enforcement: none on the flag; absence silently disables the consumer gate.
- Problem: STATE (switch files), MP (4 writers), PROSE (close.md:244-274 is a prose arming protocol with its own retry/arbitration rules; "QA MUST NOT be dispatched unless every one of the three scripts reached exit 0" :271-272). Overnight never arms artifact-contract (overnight-init.sh:304-305), so the legacy producer gate is off for every overnight dev/qa stop.
- Plan: P2 (arm G1-G3), P4 row 8 per COVERAGE.md:55 ("flag writers lose their reader").

**L06 Dev-start replay store and history: `.claude/dev-start-replays/<sid>/<digest>.json`, `.claude/workflow-locks/<sid>.lock`, `.claude/workflow-history/<sid>/<gen>-<task>/`**
- Producer: hooks/prompt-workflow.py:1775-1781, :1802-1828, :1910-1918.
- Consumer: the same hook only (replay decision :1840-1856; history collision check :1823-1828). The replay decision also reads dev-report terminal status with its own vocabulary (L22).
- Problem: STATE (three new mutable stores), DEAD consumer for workflow-history (nothing reads it), MC (dev-report terminal decided here too).
- Plan: P3 per PLAN-v2.md:411 ("the replay bug is fixed").

**L07 Workflow bookmark `.claude/workflow-<sid>.json` (command, task_id, generation, `subagent_calls`, `last_todos`, `todo_acknowledged`)**
- Producers (9): prompt-workflow.py:1897, :1994; hooks/pretool-subagent-enforce.py:141-150; hooks/posttool-subagent-track.py:247-260; hooks/posttool-todo-count.py:50; hooks/posttool-todo-sequence.py:146, :171; hooks/posttool-todo-tracker.py:97 (unlink), :120; hooks/pretool-workflow-gate.py:908, :998, :1116; hooks/lib/contract_runtime.py:1208-1250 (`reconcile_accepted_artifact`).
- Consumers: hooks/pretool-todo-validate.py:151; hooks/pretool-block-background-tasks.py:91; hooks/pretool-spec-block-foreground-agent.py:38; hooks/stop-spec-coverage-enforce.py (coverage phase); prompt-workflow handle_phase_b.
- Problem: MP (9 writers of one mutable JSON, several without a lock), STATE, MC.
- Plan: P5 ("the todo checks fold into pretool-todo-validate", PLAN-v2.md:525).

**L08 Canonical todo list `~/.claude/todos/<sid>-agent-<sid>.json`**
- Producers: prompt-workflow.py:1896, :1975; hooks/posttool-todo-tracker.py:93, :110; hooks/pretool-workflow-gate.py:901; the Claude Code CLI itself (TodoWrite).
- Consumers: pretool-todo-validate.py, posttool-todo-count.py, posttool-todo-sequence.py, pretool-spec-block-foreground-agent.py:17, hooks/lib/subagent_restart.py, scripts/break-overnight-lock.py.
- Problem: MP (harness hooks write a file the CLI also owns), MC.
- Plan: P5.

### B. Dispatch record

**L09 Obligation block `<obligation v="1">{...}</obligation>` inside each producer dispatch prompt (persisted in the parent transcript and in the subagent's first transcript record)**
- Producer: the orchestrator, by instantiating prose templates (commands/dev.md:441-460, :509, :627, :721, :803, :852, :999; close.md:605-607; commit.md:501-517, :611-628; dev-overnight.md:998, :1106, :1196, :1288, :1390, :1502-1504).
- Consumers: G1 hooks/pretool-obligation-gate.py:135-167 (dispatch; **advisory by default**, :176); G2 subagentstop-artifact-contract-enforce.py:856-1170 via obligation.resolve_own_obligation (producer-stop; `CLAUDE_OBLIGATION_STOPGATE` **advisory by default**, :859); G3 hooks/pretool-aggregate-check.py:558-633 (collection barrier, advisory default :568); G4 hooks/stop-obligation-gate.py:103-145 and hooks/posttool-overnight-loop.py:202-218 (terminal, advisory default); subagentstop-e2e-enforce.py fallback (:271-290); hooks/lib/obligation.py:915-1036 (shared re-scan).
- Enforcement: everything advisory except the legacy correlation path (L18) and the e2e gate.
- Problem: PROSE (the dispatch contract is hand-written by the orchestrator from prose templates: "Orchestrator instantiates per-dispatch — never hand-invented", dev.md:509); MC/RD (G4 `find_unresolved_dispatch_obligations` re-validates every json artifact G2 already validated, obligation.py:1001-1012); TABLE (two role lists: PRODUCER_ROLES pretool-obligation-gate.py:80-86 vs ROLES obligation.py:74-80); this block is also the one place that already names, per artifact, the role that owes it (`role`, `artifacts[].path`) — see L35.
- Plan: P1 (merged, templates), P2 (arming), P3/P5.

### C. BA stage

**L10 `docs/dev/context-<ts>[-<lane>].json` (+ `context-iter<N>-<ts>.json`, `refined-context-<ts>.json`)**
- Producers: BA (agents/ba.md:145, :1016); the orchestrator patches `spec_path` in place (commands/dev.md:540-584); scripts/graphify-enrich.py patches `graph_context` in place (:17, :413-491); the orchestrator records `attempts[i].target_layer` (dev.md:1163-1166) and builds `refined-context`/`context-iter<N>` with jq from the QA report (dev.md:1177-1199).
- Consumers: QA BA-validation and final QA prompts; dev; scripts/resolve-dev-artifact-chain.py; graphify; test-writer gate (`complexity_tier`, `_test_writer_skip_reason`, dev.md:789-791); orchestrator post-BA checks (dev.md:352-389, semantic LLM judgment); close cp-state handoff (close.md:497-503); G2 (schema `context.v1`).
- Enforcement: producer-stop G2 (advisory) + orchestrator prose "sanity checks" (dev.md:527-538).
- Problem: MP (BA + orchestrator + graphify script; R11 says the orchestrator never writes a producer artifact), RD (orchestrator re-checks fields the schema could check), PROSE.
- Plan: P9 (spec_path single producer, PLAN-v2.md:770).

**L11 `docs/dev/ticket-<ts>.md` (legacy `ba-spec-<ts>.md`)**
- Producer: BA (agents/ba.md:144, :822).
- Consumers: QA BA-validation, dev, QA final, resolver (singular chain requires it), close QA, pretool-aggregate-check (task-id scoping regex :98, :107), orchestrator "existing_specs" scan (dev.md:342).
- Enforcement: G2 markdown kind (advisory); resolver at /dev end, /close Step 0, /commit Step 5.
- Problem: MC/RD (existence re-checked by the resolver at three later points).
- Plan: P3/P4.

**L12 `docs/dev/acceptance-criteria-<task>.json`**
- Producer: BA (agents/ba.md:799).
- Consumers: test-writer, QA, G2 (`acceptance-criteria.v1`).
- Problem: backlog records no entry check and three logic defects found only at run time (docs/reference/harness-issues-backlog.md:133, #91). Otherwise single producer.
- Plan: none.

**L13 Question artifact `docs/dev/producer-question-<task>-<role>.json` (role ba or dev)**
- Producers: BA (agents/ba.md:116-140), dev (agents/dev.md:692).
- Consumers: G2 accepts it as a stand-in for every declared artifact (subagentstop-artifact-contract-enforce.py:719-744, :901-911); the orchestrator relays it with AskUserQuestion and re-dispatches (commands/dev.md:493-496, :967).
- Enforcement: G2 only (advisory default). No code checks that the relay happened.
- Problem: PROSE (relay is prose only). It exists because BA/dev are not the ones asking; R13(4) says the agent may pause by asking with AskUserQuestion. Whether a subagent's own AskUserQuestion is usable was not measured here (open; D18 says measure).
- Plan: P1 (merged), P3 relay include (rejected by R13(3) as a /redev continuation).

**L14 `docs/dev/ba-qa-report-<ts>.json`**
- Producer: QA in BA-validation mode (dev.md:687). The tool policy also lets BA write it (policies/tool-policy.v1.json `roles.ba.allowed_write_path_prefixes` contains `*/docs/dev/ba-qa-report-`).
- Consumers: orchestrator verdict branch (dev.md:691-699); G2 (`ba-qa-report.v1`); resolver (P3 plans the BA-QA pass into the disposition, PLAN-v2.md:407).
- Problem: MP by permission (the producer it validates may overwrite it).
- Plan: P3, P5 (D8 deny derived from ROLE_BY_ARTIFACT, PLAN-v2.md:86, rejected by R13(2)).

**L15 Graphify artifacts: `.claude/dev-registry/<sid>/graphify/pre_query.json`, `.../graphify/graph-summary.json`, overnight `docs/dev/overnight/<sid>/cycle-<N>/graphify-run.json`**
- Producers: scripts/graphify-query.py (orchestrator Bash, dev.md:243-249); graphify subagent running scripts/graphify-enrich.py (dev.md:772).
- Consumers: BA prompt (pre_query), orchestrator todo note (dev.md:780), overnight cycle contract entry (dev-overnight.md:840) and its fingerprint-based skip (dev-overnight.md:1246).
- Problem: MP on context (L10); PROSE (idempotency by fingerprint is prose, dev-overnight.md:1246).
- Plan: none.

**L16 Test-writer artifacts: `docs/dev/test-writer-report-<task>.json`, `tests/generated/<task>/manifest.json`, global index `tests/generated/manifest.json`**
- Producer: test-writer (dev.md:803-814). The global index is upserted by every test-writer of every task.
- Consumers: orchestrator existence check of all three ("abort the cycle", dev.md:818); QA Phase 5; G2 (two json kinds).
- Problem: RD (orchestrator re-checks what G2 checks), MP (global index has one writer per task across sessions: STATE).
- Plan: none.

### D. Dev stage

**L17 Lane/singular dev report `docs/dev/dev-report-<ts>[-<lane>].json` (dev-report.v2, `report_version: 2`, agents/dev.md:602)**
- Producers: dev (agents/dev.md:594); scripts/late-repair-controller.py embeds `retrospective_disclosure` into existing reports (:15, :94; close.md:141).
- Consumers deciding on it (each with its own reading): G2 obligation path (advisory) and legacy correlation path (blocks, `ARTIFACT_CONTRACT_ENFORCE_MODE` default `block`, subagentstop-artifact-contract-enforce.py:1252) plus its downstream wires that run /commit's own planner and the ownership adjudicator at the producer's stop (:415-438, :468-521); posttool-overnight-file-check.py:134-145 (overnight, schema from the cycle contract); pretool-aggregate-check.py (shard existence); posttool-lane-completeness-watch.py; scripts/aggregate-dev-report.py; scripts/resolve-dev-artifact-chain.py (called from 15 places, L28); stop-obligation-gate/obligation.py:1001; posttool-overnight-loop.py:156-200; prompt-workflow replay (:1786-1799); scripts/dev-lifecycle.py:201-252; /close cycle-diff list (close.md:538-541); scripts/resolve-commit-repos.py; changelog-analyst; QA.
- Enforcement: producer-stop (legacy block + obligation advisory), collection (aggregate-check block, overnight file-check block), consumer (/close Step 0 + schema gate, /commit Step 5).
- Problem: MC (more than 12 deciders), RD (re-checked at /dev end, /close, /commit, R1/R5), MP (late-repair writes into it), MISMATCH under /dev-overnight (E1 below).
- Plan: P1 (v2 producer, merged), P3 (one disposition), P4 (consumers call it once).

**L18 Canonical aggregate `docs/dev/dev-report-<task>.json` for fan-out (+ `superseded-<task>/`, `dev-report-iter<N>-<task>-<lane>.json`)**
- Producers: scripts/aggregate-dev-report.py run by the orchestrator (dev.md:885) and again by /close Step 0 (close.md:334-343) and /commit row 1 (commit.md:105); dev.md:898-903 also says "the orchestrator MUST write" it; the aggregate sets `dev.status = "blocked"` on baseline mismatch (dev.md:911-913), a value dev-report.v2 forbids (schemas/dev-report.v2.json `dev.status` enum `["completed"]`). `superseded-<task>/` is read (aggregate-dev-report.py:965-1010) but no command, agent or hook writes it (DEAD producer; inferred hand-moved).
- Consumers: QA dispatch gate pretool-aggregate-check.py:1-12, :319; resolver; /close; /commit; changelog-analyst.
- Problem: MP (orchestrator-run script at three pipelines, R11), MISMATCH (aggregate status vocabulary vs v2 schema), DEAD (`superseded-` producer), RD (/close and /commit re-run the writer).
- Plan: P3 (aggregator row), P4.

**L19 Ownership facts: self-reported `owned_edits` / `pre_edit_snapshots` in the dev report vs the write-time attribution journal `<harness>/state/attribution-journal/journals/<sid>.jsonl`**
- Producers: dev prose (agents/dev.md:555-592) for the report maps; hooks pretool-attribution-pre.py / posttool-attribution-post.py (hooks/lib/attribution_journal.py:1-30, :89-95, :300) for the journal; aggregate-dev-report.py unions the maps (34 references).
- Consumers: changelog-analyst + scripts/stage-owned-hunks.py; scripts/resolve-commit-repos.py ownership gate (scripts/lib/attribution_adjudicator.py); G2 wire `_wire_ledger_judgment` (subagentstop-artifact-contract-enforce.py:468-521); /commit Step 5 `verify-attribution-chain.py` (commit.md:378); scripts/check-late-repair-provenance.py.
- Problem: MP (two producers of the same fact, one prose, one hook), MC, PROSE. Backlog records the two disagreeing in practice: "self-proof and adjudication read different files" (harness-issues-backlog.md:103), and owned_edits presence excluding modified files (:85).
- Plan: P6 (A3.a), P9.

**L20 Baseline `baseline_head_sha` / `baseline_dirty_snapshot`**
- Producers: orchestrator Bash before dispatch (dev.md:826-835), copied verbatim by dev (agents/dev.md:539-543) and by every lane; the aggregate takes the orchestrator's value (dev.md:911-912).
- Consumers: QA, changelog-analyst, aggregate equality check, resolve-commit-repos.
- Problem: PROSE (value travels through prompt text and an agent copy), MC.
- Plan: none.

**L21 Dev-report terminal vocabulary (`dev.status` legal terminal set)**
- Declared: schemas/dev-report.v2.json `["completed"]`; hooks/lib/obligation.py TERMINAL_VOCABULARY `dev-report.v2: {"completed"}` (:132-139).
- Re-declared differently by consumers: hooks/prompt-workflow.py:1783 `{"completed","blocked","needs_review"}`; hooks/posttool-overnight-loop.py:32 `{"completed","blocked"}`; scripts/dev-lifecycle.py:201-232 (`_blocked_report_is_released`); aggregate writes `blocked` (L18).
- Problem: TABLE + MC + MISMATCH (four consumer sets for one enum).
- Plan: P1 drift test (dev-report only, PLAN-v2.md:310), P9.

### E. QA stage

**L22 `docs/dev/qa-report-<ts>[-<lane>].json` (qa-report.v2; fields `qa.status`, `e2e_enforcement`, `permissions_verification`, `spec_section_updates`, `refined_context`)**
- Producer: QA (agents/qa.md:1405).
- Consumers: subagentstop-e2e-enforce.py (existence by "most recent" correlation + `e2e_enforcement.status`, :1-27, :115); subagentstop-artifact-contract-enforce.py (legacy block + obligation); its qa wire runs the whole chain resolver at QA's stop (:523-564); posttool-overnight-file-check.py (v1 schema); resolver; /close schema gate (close.md:434-491); orchestrator: verdict (dev.md:1052-1060), spec section edits (dev.md:1026-1048), permissions to settings (dev.md:1081-1110, L46), refined context (dev.md:1180-1182), score events (dev.md:1062-1075).
- Problem: MC (at least 6 deciders), RD (/close schema gate re-runs the producer-stop engine, close.md:436-437 says so), the orchestrator turns QA content into writes of other artifacts (spec, settings, context).
- Plan: P1, P3, P4.

**L23 `docs/dev/completion-<ts>.md`**
- Producer: orchestrator (dev.md:1314).
- Consumers: resolver (required in both modes, dev.md:1335-1344); G2 qa wire skips its absence (subagentstop-artifact-contract-enforce.py:527-529, :551-552).
- Problem: R11 (orchestrator-written artifact that gates /close); RD.
- Plan: P3/P4.

**L24 Spec monolith `docs/dev/specs/spec-<ts>.md` (sections 2-8)**
- Producers: /spec orchestrator (commands/spec.md:47); dev (Sections 2/3, dev.md:865); orchestrator applying QA's `spec_section_updates` (dev.md:1030-1048); /spec-update via the /commit Step 8 agent (commit.md:915-943).
- Consumers: /dev auto-detect by mtime (dev.md:125-138, R4 conflict noted by the design doc :356-362); resolve-spec-artifacts.py; stop-spec-coverage-enforce.py; BA/QA/dev prompts.
- Problem: MP (four writers), RD (consumers pick "the newest spec" by mtime).
- Plan: P9 (spec_path single producer).

### F. Records produced by gates themselves

**L25 Escalation records `.claude/dev-registry/<cycle>/escalations/<id>.json`, `escalation-admissions/<id>.json`, `progress/producer-stop-<agent>.json`, `deferred-checks/<agent>.json`; named arbiter `docs/dev/arbitration-<cycle_id>.json`**
- Producer: G2 hooks/subagentstop-artifact-contract-enforce.py:614-635, :659-702, :747-829 (block mode only).
- Consumers: the same hook (admission by nonce, :637-656); its comment names an orchestrator arbitration file (:292-297) that no code, command or agent writes or reads.
- Problem: STATE (four new mutable stores; R3), DEAD (no external consumer; `deferred-checks` never read; arbitration file nonexistent).
- Plan: P3 ("G2 escalation records are resolved only by producer evidence; arbitration is retired", PLAN-v2.md:409).

**L26 `docs/dev/journal-view-<task>.json`**
- Producer: G2 `_write_journal_view_sidecar` (subagentstop-artifact-contract-enforce.py:451-465).
- Consumers: none.
- Problem: DEAD (written into the product's docs/dev).
- Plan: none named.

**L27 `.claude/dev-registry/dev-<task>/aggregate-pending.json`**
- Producer: hooks/posttool-lane-completeness-watch.py:26-31, :129.
- Consumers: none.
- Problem: DEAD, STATE.
- Plan: none named.

**L28 Chain disposition (stdout JSON of `scripts/resolve-dev-artifact-chain.py`: `status`, `mode`, `lanes`, `report_paths`, `errors[]`, ...)**
- Producer: the resolver (pure function of disk).
- Consumers that each run it and decide: /dev and /dev-command end (dev.md:1316-1355, dev-command.md:889); /close Step 0 via close-route-select.py (close.md:344-398); /commit Step 5 twice (commit.md:274, :334); G2 qa wire (subagentstop-artifact-contract-enforce.py:523-564); subagentstop-e2e-enforce.py; pretool-gitignore-preflight.py; posttool-lane-completeness-watch.py; pretool-do-block-subagents.py; late-repair-controller.py; dev-lifecycle.py (and its SQLite cache `.claude/cache/dev-lifecycle.sqlite3`, :858-937); spec-update; changelog-analyst; (unregistered) sessionstart-artifact-census.py.
- Problem: MC + RD (more than 12 callers; each turns the same result into its own verdict); at /close and /commit this is exactly the class-b check R1 forbids there; STATE (SQLite cache).
- Plan: P3 (one `--disposition` function), P4 (close/commit call it once), P5 (Stop predicate).

### G. /do

**L29 `/do` consent flag `<state>/claude-orchestrator-consent-<sid>.flag`, task sidecar `<state>/claude-do-task-<sid>.json`, reservation markers `<state>/claude-do-resv-<ts>`**
- Producers: prompt-workflow.py:1400-1437, :1320-1360; agent fallback (do.md:58); cleared by prompt-workflow.py:1999-2016.
- Consumers: pretool-orchestrator-gate.py; pretool-do-block-subagents.py; stop-do-report-gate.py; "12 consent readers" (PLAN-v2.md:773).
- Problem: STATE, MC (12 readers of one consent fact).
- Plan: P9 D3.c (one `has_do_consent` reader).

**L30 `docs/dev/do-report-<task>.json` (+ gate counter `<state>/claude-do-report-gate-<sid>.json`)**
- Producers: prompt-workflow.py:1363-1397 (pending skeleton); the main agent rewrites it (do.md:46-60).
- Consumers deciding on `do.status`, each with a different legal set: stop-do-report-gate.py:20-29 (completed|blocked; **default block**, :12, :170, while do.md:53 says "advisory mode (default)"); /close lite preflight (completed only, close.md:414); obligation TERMINAL_VOCABULARY `do-report.v1: {"pending","completed","blocked"}` (obligation.py:132-139); /close schema gate (close.md:416, :491); subagentstop-e2e-enforce.py:166-205 (`expected_absent`); resolve-commit-repos.py:423-463 and /close (route chosen by which filename exists, pretool-do-block-subagents.py:5-18); dev-lifecycle.py do track.
- Problem: MP (hook skeleton + agent), MC with MISMATCH (three terminal sets), PROSE vs code (do.md:53 default contradicts code), RD (route selected by file existence instead of the report's own `source`), STATE (gate counter).
- Plan: P4/P5 (/do predicate vs transcript write set, PLAN-v2.md:524).

### H. /close

**L31 Inspector reports `docs/dev/{style,cleanliness,prompt}-inspector-report-<task>.json`**
- Producers: the three inspectors (close.md:553-561).
- Consumers: G2 (obligation json kind); the orchestrator re-validates the same reports with the same engine before QA (close.md:567); close QA (close.md:665-667).
- Problem: RD (orchestrator repeats the G2 check), PROSE.
- Plan: P4.

**L32 `docs/dev/close-report-<task>.md` (last line `CLOSE: YES*` / `CLOSE_FINDINGS: <n> items`) and close-QA's response line**
- Producers: close QA (close.md:764); scripts/close-report-append.py when one exists (close.md:775-776).
- Consumers deciding on the verdict: G2 markdown + response_line + verdict_class consistency (subagentstop-artifact-contract-enforce.py:937-1084); orchestrator echo (close.md:793-797); scripts/close-scoring-decide.py (close.md:815-823); scripts/score-update.sh precondition (close.md:845); /commit Step 3 checks 1/2/4 with its own accepted-line list (commit.md:204-233; the list adds `CLOSE: YES — FORCED`, absent from close.md:782-787); hooks/lib/commit_pipeline.py `_close_report_exists` (:294) via write-commit-grant.py; scripts/resolve-close-report.sh; scripts/dev-lifecycle.py stage 3; scripts/step7-spec-update.py; pretool-git-privilege-guard.py; pretool-gitignore-preflight.py.
- Problem: MC (more than 9 deciders), TABLE (accepted-line lists in prose and in hooks/lib/close-verdict.py:37-50), RD at /commit (class-b re-check, R1/R5).
- Plan: P4.

**L33 Artifact -> producing-role routing table (close.md:162-181; commit.md:99-116; P3 plans ROLE_BY_ARTIFACT in hooks/lib/obligation.py, PLAN-v2.md:421)**
- Producer: hand-written in two command files; claimed "no code table" (close.md:278, commit.md:83-84) while being one.
- Consumers: /close and /commit routing loops (close.md:282-317, commit.md:144-178).
- Problem: TABLE (duplicated; the `changelog-status*` row matches no file, because the analyst's status is a response block, commit.md:611-628, and no `changelog-status*` file is written anywhere); RD (re-derives from a filename what each dispatch's obligation already declares: `role` and `artifacts[].path`, L09). R13(2) rejects moving this table into code. **Inferred alternative (not tested):** the owing role of an unresolved artifact is read back from the dispatch record that declared it (obligation.py already scans those records with `_read_parent_calls`, :958), so no table is needed.
- Plan: P3 r1 (rejected by the owner today).

**L34 Late-repair artifacts `docs/dev/late-repair-run-<task>.json`, `docs/dev/dev-report-<task>.effective.json`, embedded `retrospective_disclosure`**
- Producer: scripts/late-repair-controller.py (close.md:137-143).
- Consumers: /commit `resolve-effective-report` (commit.md:302-321); resolve-commit-repos.py; stage-owned-hunks.py; changelog-analyst.
- Problem: MP (controller writes into BA/dev/QA artifacts, L17), a second report for the same task (effective vs canonical), a /close-only producer of /commit inputs.
- Plan: none named.

**L35 /close --auto inputs: `.claude/cache/dev-lifecycle.sqlite3`, `docs/dev/human-operator-transcript-<task>.md`**
- Producers: scripts/dev-lifecycle.py:858-937 (cache); the human (transcript, close.md:1002-1006).
- Consumers: /close --auto and /commit --auto (close.md:949-950).
- Problem: STATE (cache), RD (lifecycle re-derives every cycle's state from disk).
- Plan: P4 (D6 `/commit --auto`).

**L36 Forced-close flag `<state>/claude-close-force-<sid>.flag`**
- Producer: none (`--force` is a no-op alias, close.md:77-95; only a cleanup script removes it).
- Consumers: subagentstop-e2e-enforce.py:387, subagentstop-artifact-contract-enforce.py:365-373, :1215.
- Problem: DEAD (read path with no writer).
- Plan: P10.

### I. /commit

**L37 Dispatch-snapshot manifest `<state>/claude-commit-manifest-<sid>.json`**
- Producer: the orchestrator per prose (commit.md:401-417).
- Consumers: scripts/write-commit-grant.py via hooks/lib/commit_pipeline.py `verify_pipeline_dispatch` (:325-400).
- Problem: PROSE (an orchestrator-authored file is a mint precondition; commit_pipeline.py:34-47 itself says it proves only that the orchestrator chose to write it), STATE, RD (re-records the plan and chain the orchestrator just computed).
- Plan: P6 (grant binding).

**L38 Commit grants `<state>/claude-commit-grant-<sid>-<nonce>.json` (+ `-active-` pointer) and dispatch attestation `<state>/claude-commit-dispatch-<sid>-<nonce>.json`**
- Producers: scripts/write-commit-grant.py:10, :123, :478 (run by the orchestrator, commit.md:434-460; revoked by it, :568-572, :818-826); hooks/pretool-commit-dispatch-attest.py:1-30 (attestation).
- Consumers: hooks/pretool-git-privilege-guard.py `_find_grant` :318, attestation check :1456-1510.
- Problem: STATE (two files per commit), PROSE (mint/revoke lifecycle is orchestrator prose). The attestation is the one hook-written witness in the chain; the grant is orchestrator-run.
- Plan: P6.

**L39 Bulk-commit sentinel `/tmp/claude-bulk-commit-sentinel-<sid>-<nonce>.json`**
- Producer: hooks/userprompt-bulk-commit-capability.py:41-60 (via scripts/write-bulk-commit-sentinel.py).
- Consumers: pretool-git-privilege-guard.py:1344-1363; orchestrator `ls` check (commit.md:248).
- Problem: hardcoded `/tmp` in the guard (:1361-1363) while other state uses `harness_state_dir()`.
- Plan: D6 says never /commit --bulk (DECISIONS.md:61).

**L40 `docs/dev/commit-qa-report-<task|bulk>.md` and commit-QA's response line `COMMIT: APPROVE|REJECT`**
- Producer: commit QA (commit.md:558-563).
- Consumers: G2 (markdown + response_line kinds, commit.md:501-517; no `consistency` declared, and G2's consistency check only classifies CLOSE lines, subagentstop-artifact-contract-enforce.py:1050-1084); /commit's own file-vs-response cross-check (commit.md:579-583).
- Problem: RD (the /commit consumer performs the cross-channel check the producer-stop gate does for /close), MP of channels (file + response carry one verdict).
- Plan: P4.

**L41 changelog-analyst status (response block `changelog-status.v1`)**
- Producer: changelog-analyst (agents/changelog-analyst.md:1982).
- Consumers: G2 response_block (subagentstop-artifact-contract-enforce.py:1013-1039); /commit result handling (commit.md:673-855); scripts/step7-spec-update.py `--changelog-status` (:167).
- Problem: RD (/commit re-parses and routes an "unparseable" status, commit.md:851-853, that G2 already validated); TABLE row with no file (L33).
- Plan: P4.

**L42 Push-gate token `/tmp/agentic-commit/push/<repo-hash>/<sid-digest>/<branch>.json`**
- Producer: changelog-analyst by prose with the Write tool (commit.md:666; posttool-push-gate-token-verify.py:5-9 cites agents/changelog-analyst.md:1221-1225, :555-569).
- Consumers: hooks/posttool-push-gate-token-verify.py (re-derives HEAD after the write and renames the token on mismatch, :11-22); hooks/push.sh ancestor scan; /push Step 1 orchestrator prose (push.md:140-160); scripts/step7-spec-update.py (existence gates spec-update, commit.md:773-774).
- Problem: PROSE (correctness rests on the agent's prose checks), RD (PostToolUse re-check that cannot block; consumer mutates the artifact), MC (4 deciders), slot conflict recorded in harness-issues-backlog.md:138 (#96).
- Plan: none named.

### J. /push and /merge

**L43 Push-analyst grant `/tmp/agentic-commit/push-analyst/<repo-hash>/<sid>/<request>.json`, Chain-B sentinel `<repo-hash>/<branch>-chainB.validated.sentinel.json`, push grant manifest**
- Producers: push-analyst (grant); scripts/execute-push.py (Chain-B sentinel, :35); hooks/push.sh:358-360 (push grant).
- Consumers: execute-push.py (sole grant validator, push.md:184-200); push.sh reads the sentinel once (:107-111); pretool-git-privilege-guard.py (push grant).
- Problem: chained single-use files (STATE) but each has one consumer; the orchestrator is told not to touch the grant (push.md:184-186). Closest to the R8 rule in the tree.
- Plan: none.

**L44 Merge-analyst grant `/tmp/agentic-commit/merge-analyst/<repo-hash>/<sid>/<request>.json`**
- Producer: merge-analyst.
- Consumers: /merge Step 3 orchestrator prose validates 11 fields and then unlinks it (commands/merge.md:127-166); pretool-git-privilege-guard.py `_enforce_merge_grant` validates and unlinks the same grant (:1987-2010).
- Problem: MC + RD (two validators, both consume); **inferred:** the guard path is reachable only when `CLAUDE_MERGE_COMMAND_ACTIVE=1` is in the hook's environment, which merge.sh sets inside its own subprocess that "does not go through main-agent PreToolUse" (hooks/merge.sh:4-11), so the guard's grant check looks unreachable while the prose check deletes the grant first. Not run.
- Plan: none.

### K. /dev-overnight

**L45 Overnight state `.claude/overnight-state-<sid>.json`**
- Producers: scripts/create-overnight-state.sh (via prompt-workflow create_overnight_state :555-590); scripts/update-overnight-state.sh; hooks/posttool-overnight-loop.py:101-153 (`_mark_session_complete`, `_update_state_cycle`); scripts/break-overnight-lock.py; scripts/overnight-init.sh.
- Consumers: stop-overnight-timelock.py:1-15; prompt-workflow continuation (:1166); pretool-overnight-hook-guard.py; pretool-git-privilege-guard.py; merge.sh; posttool-overnight-loop.py; notification-idle-overnight.py; posttool-overnight-trace.py.
- Problem: MP (5 writers) while dev-overnight.md:1813-1818 says it is "read-only for the session thereafter"; STATE; MC.
- Plan: P2.

**L46 Cycle contract `docs/dev/overnight/<sid>/cycle-<N>/cycle-contract.json` + symlink `cycle-current.json` + mirror `.claude/overnight-contract-<sid>-cycle<N>.json`; `<state>/contract-bookmark-<sid>-<cycle>.json`; `<state>/artifact-status-<sid>-<cycle>.json`**
- Producers: the orchestrator writes three copies (dev-overnight.md:821-852); hooks/lib/contract_runtime.py:1208-1250 mutates `required_calls`/`pipelines` status in place (while dev-overnight.md:852 says append-only); pretool-subagent-enforce.py:138-150 (bookmark); posttool-overnight-file-check.py:161, :316-330 (sidecar).
- Consumers: pretool-subagent-enforce.py:294-300 (dispatch, block); posttool-overnight-file-check.py (collection, block, :367); posttool-subagent-track.py:360-377; scripts/check-overnight-reports.py; closeout (stop-overnight-timelock.py).
- Problem: PROSE (the orchestrator authors the contract that gates itself), MP (orchestrator + runtime writer), STATE (3 copies + 2 sidecars), MISMATCH (E1: `required_calls` names `dev-report.v1`/`qa-report.v1`, dev-overnight.md:837-838, while the same dispatches' obligations name `dev-report.v2`/`qa-report.v2`, dev-overnight.md:1288, :1390), and the collection check runs PostToolUse after the producer has stopped, so a failure lands on the orchestrator, not the producer (C5, R5).
- Plan: P2 ("arm G1-G3"); D6/D4b overnight route (D4b rejected today, R13(1)).

**L47 Overnight PM/specialist artifacts under `docs/dev/overnight/<sid>/`: `test-plan.json`, `<specialist>-report.json`, `triage-report-cycle<N>.json`, `pipelines.json`, `iteration-plan.json`, `retro-report-cycle<N>.json`, `aggregated-permissions.json`**
- Producers: PM/specialist subagents (dev-overnight.md:509, :645, :796, :1632); scripts build-pipelines-from-triage.py (:912), iterate-failed-pipelines.py (:1487), aggregate-permissions.py (:1518) run by the orchestrator.
- Consumers: orchestrator prose validation ("Validate test plan" :533, "Validate triage report" :802, "Validate retro report" :1638); cycle contract entries; apply-permissions.sh (:1519).
- Problem: PROSE (validation is prose), RD.
- Plan: P2, P9 (iterate-failed-pipelines.py deleted, PLAN-v2.md:775).

**L48 Overnight log/summary/deadlock `docs/dev/overnight-log-<date>.md`, `overnight-summary-<date>.md`, `overnight-deadlock-<ts>.md`; `<state>/overnight-needs-continuation-<sid>`**
- Producers: orchestrator (dev-overnight.md:1551, :1666); stop-overnight-timelock.py:163-190 (continuation sentinel).
- Consumers: humans; the continuation sentinel has none (its docstring names "watchdog, QA", :166-170; no code reads it).
- Problem: DEAD (continuation sentinel), STATE.
- Plan: P2.

### L. /spec and checkpoints

**L49 Checkpoint state `.claude/specs/<spec-id>/cp-state-<agent>[-N].json`**
- Producers: scripts/spec-check.py (writer, :344-350; subcommands run by agents via Bash, agents/*.md "Checkpoint Marking Contract"); hooks/pretool-cp-checkin.py:309-313, :423-430 (writes the payload on a Read).
- Consumers: subagentstop-cp-enforce.py (advisory by default, :4-6); hooks/lib/agent_resolver.py (role resolution); pretool-cp-state-write-guard.py.
- Problem: MP (two code writers + agent-run CLI), STATE, PROSE vs code (dev.md:235 and every dispatch template say SubagentStop "will block exit"; close.md:603 says "no hook blocks exit"; code is advisory).
- Plan: P9 (D3.f roster).

**L50 Spec split artifacts `docs/dev/specs/<id>/views/`, `manifest.json`, `.split-complete`, `.spec-binding.json`, `split-qa-unresolved.json`**
- Producers: spec subagent (views/manifest/.split-complete, commands/spec.md:420, :510); /spec orchestrator (.spec-binding.json, design/, evidence/, spec.md:500-503).
- Consumers: scripts/resolve-spec-artifacts.py (spec.md:424 finalize assertion; dev.md:157-172; close.md:504-519); stop-spec-coverage-enforce.py.
- Problem: RD (the producer runs the consumer's resolver at finalize, spec.md:424; acceptable as a producer-side check). Otherwise one producer per file.
- Plan: none.

### M. Grants, consent, intent

**L51 `/allow` grants: legacy flag `<state>/claude-bash-allowlist-<sid>.json` and structured sentinel `<state>/claude-grants/<task_id>.json`**
- Producer: hooks/userprompt-consent-allowlist.sh:21-24, :56-76 (both channels for one grant).
- Consumers: pretool-bash-safety.sh:923-957; pretool-git-privilege-guard.py:157, :294; pretool-block-branch-pr-worktree.py; pretool-block-enterworktree.sh; pretool-do-block-subagents.py; posttool-allowlist-consume.py:24 (consumes); stop-cleanup-allowlist.sh (reaper; run as a Stop coordinator phase, hooks/stop-workflow-coordinator.py:64-70, although CLAUDE.md says it is not registered).
- Problem: MP of channels (one grant, two files), MC.
- Plan: P9 (D3.c consent readers).

**L52 User-intent flags `<state>/claude-<cmd>-userintent-<sid>.flag` (commit, push, merge, stop), tool streak `<state>/claude-tool-streak-<sid>.json`**
- Producers: prompt-workflow.py:1440-1448, :1926; pretool-orchestrator-gate.py (streak).
- Consumers: pretool-wrapper-userintent.py; commit.sh/push.sh/merge.sh sentinel checks; pretool-orchestrator-gate.py.
- Problem: STATE; the commit user-intent flag alone allowed 14 commits without the pipeline (commit.md:418-432), which is why L37/L38 exist.
- Plan: P6.

### N. Logs read by code, scores, settings-derived files

**L53 Score ledger `~/.claude/logs/lifecycle.jsonl`**
- Producers: scripts/score-update.sh:412 (called from orchestrator prose, dev.md:1068-1073, close.md:830-889); scripts/lifecycle-baseline-import.sh:109.
- Consumers: scripts/score-inject.sh:61-124 (prepended to BA/dev/QA dispatches, dev.md:426, :824, :984); score-update.sh precondition re-reads the close-report (close.md:845).
- Problem: PROSE (events issued by orchestrator prose), RD (precondition re-checks the close verdict), and the agents' score-echo fields are a producer obligation with no decision consumer (agents/ba.md:807-820; effect never measured, DECISIONS.md:69-71).
- Plan: P9 (D9a scoring retirement, PLAN-v2.md:759).

**L54 Advisory JSONL logs `~/.claude/logs/{obligation-gate,obligation-terminal-gate,artifact-contract,obligation-barrier,cp-enforce,do-report-gate,lane-completeness-watch}-advisory.jsonl`**
- Producers: the seven gates (pretool-obligation-gate.py:91; stop-obligation-gate.py:56; posttool-overnight-loop.py:28; subagentstop-artifact-contract-enforce.py:124; pretool-aggregate-check.py:388; subagentstop-cp-enforce.py:36; stop-do-report-gate.py:58; posttool-lane-completeness-watch.py:68).
- Consumers: none in code (observability only).
- Problem: every gate on the producer side of the main path (G1, G2-obligation, G3-barrier, G4) currently only writes here; the rows above whose enforcement is "advisory" end in these files.
- Plan: P2 (arm), P5 (arm and delete advisory branch, PLAN-v2.md:526).

**L55 Settings-derived files: project `.claude/settings.json` permissions, `.claude/settings.local.json`, harness `settings.json` machine form**
- Producers: orchestrator jq edit from the QA report (dev.md:1081-1110); scripts/apply-permissions.sh:21 from aggregated-permissions (dev-overnight.md:1518-1519); scripts/create-worktree.sh:108-121 (settings.local.json); scripts/install/render-settings (machine form from tracked form + overlay, :1-40); the Claude Code CLI itself.
- Consumers: the CLI permission engine; pretool-claude-config-guard.py; render-settings `check`.
- Problem: MP (five writers), the orchestrator converts a verifier's report field into a permission write (R11).
- Plan: P7/P7b (merged, harness file); project-file writers untouched.

**L56 `docs/dev/qa-input-<ts>.json`**
- Producer: none (no command, agent or hook writes it; the QA tool policy permits `*/docs/dev/qa-input-`).
- Consumer: the context-iteration jq merge (dev.md:1196, dev-command.md:793).
- Problem: DEAD (consumed, never produced), so `context-iter<N>` is built from a missing input.
- Plan: P9 (D3.g Step 16 loops replaced).

---

## 3. Experiment

**E1 (run 2026-10-23, read-only, from the audit directory).** A minimal dev report shaped exactly like the producer template (agents/dev.md:602 `report_version: 2`, nested `dev`, owned_edits/pre_edit_snapshots/baselines) was validated with the tree's own engine `hooks/lib/contract_runtime.validate`:

- against `dev-report.v2` (what every /dev-overnight dev dispatch obligation declares, dev-overnight.md:1288): `ok=True`;
- against `dev-report.v1` (what the same cycle's contract tells `posttool-overnight-file-check.py` to enforce, dev-overnight.md:837): `ok=False`, first errors `flat field 'report_version' must be literal integer 1`, `flat field 'status' missing for canonical source 'dev.status'`.

So under /dev-overnight a producer that follows its own template is rejected at collection (PostToolUse, exit 2, posttool-overnight-file-check.py:36-38, :367) by a consumer contract that names a different schema. The same pairing exists for QA (`qa-report.v1` :838 vs `qa-report.v2` :1390; not run).

---

## 4. Counts and cross-cutting reading

56 rows. Rows carrying each label (counted from the Problem lines): MP 22, MC 20, RD 24 (L50's is a producer running its consumer's resolver at finalize, which fits R2), STATE 20, PROSE 18, DEAD 8 (L06 history, L18 `superseded-` producer, L25, L26, L27, L36, L48 continuation sentinel, L56; plus the `changelog-status*` table row in L33 that matches no file), TABLE 5 (L09 role lists, L21, L32, L33, L41), MISMATCH 5 (L17 and L46 via E1, L18, L21, L30).

What the rows show, against R1-R3 and R8:

1. **The producer side exists but is switched off.** G1 dispatch, G2 obligation stop, G3 barrier and G4 terminal all default to advisory in code and settings.json sets none of them (L09, L54). The only blocking producer-stop check is the older correlation path (L17), and overnight never arms it (L05).
2. **Consumers re-derive instead of trusting one conclusion.** The chain disposition has more than 12 callers (L28); the dev report more than 12 deciders (L17); the close verdict more than 9 (L32); task identity 8 derivations (L01). /close and /commit still run class-b checks (L28, L31, L32, L40, L41), which R1/R5 call defects.
3. **The routing table re-derives what the dispatch record already says.** Every obligation names its role and its artifact paths (L09). The two prose tables (L33) and the planned ROLE_BY_ARTIFACT re-derive the same thing from filenames; the owner rejected the latter today (R13(2)).
4. **Several artifacts have more than one writer, including the orchestrator** (context L10, aggregate L18, completion L23, spec L24, settings L55, cycle contract L46, overnight state L45, bookmark L07), against R11.
5. **New mutable state keeps growing** (escalation stores L25, replay store L06, enforce flags L05, manifest L37, aggregate-pending L27, SQLite cache L35), against R3.
6. **Producer and consumer contracts disagree** where two declarations of one artifact coexist (E1; terminal vocabularies L21, L30).

Rows touched by no phase of PLAN-v2: L02, L12, L15, L16, L20, L26, L27, L34, L42, L43, L44, L50, and L55's project-file writers.
