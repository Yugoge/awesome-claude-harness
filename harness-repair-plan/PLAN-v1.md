# Harness fix plan (2026-10-13)

Built from the nine inventories in landscape/, the runtime verification and the armed core-architecture test; reviewed by a critic and revised. Producer-side only; /close and /commit only shrink.

## Principles

- Producer-side only. Each fix lands on the single producer of the artifact concerned (a hook, the launcher, the UserPromptSubmit hook, a producer prompt, the renderer) or in CI. /close and /commit only shrink, down to one disposition call each. Nothing is added to /close, /commit or the changelog-analyst: no scan, no cleanup class, no filter.
- Hooks are the enforcement primitive, and no phase adds a mutable state file. Stop bounds come from the CLI's stop_hook_active payload field, which allows one repair round per Stop chain and is already read by stop-spec-coverage-enforce.py:246 and stop-overnight-timelock.py:270. Otherwise they come from transcript records whose shape has been measured (Agent tool_use and tool_result records, subagent transcripts). The /do gate's /tmp block counter is deleted. settings.machine.json and the private-marker file are per-machine configuration that the human writes; they are not runtime state.
- Make it runnable before arming it. P1 fixes the gates with every switch still advisory. P2 makes every pipeline runnable in any repo, and only then arms G1-G3, in the live settings.json and the template in the same commit. P3 confirms the stop_hook_active bound in one real session before it arms G4. Hook code defaults stay advisory, so deleting an env line is an instant kill switch.
- Live sessions keep running on this tree (status quo). A running session keeps the hook list it loaded at start, and python3 on a missing file exits 2, which blocks. So a registered hook file is never deleted in the same change that unregisters it: it becomes an exit-0 stub for one phase. For the same reason, settings.json is untracked only as a human-run last step, after every home has rendered its own copy.
- Honest terminals always have a route. A terminal's meaning comes from one disposition (chain_pass, honest_blocked, forced, incomplete). Schemas own the legal terminal values: templates carry no required_values. Every block is bounded, goes back to the producer that owns the artifact, and ends as an honest 'dev cycle itself failed', never as a deadlock.
- Net-negative in code and in rules. Each phase states a cap on net code lines in hooks/, scripts/ and schemas/ (tests excluded), measured with git diff --numstat. Each PR lists the enforcement rules it adds and the ones it retires, and in every phase retired >= added. Apart from the user's own G1-G5, nothing new is larger than what it removes.
- Respect the decisions. The repo is a published product, so the template is the shipped configuration and the author's values go to an untracked overlay. No feature is retired, and no recommended default retires a capability: the /do commit/push bypass, fswatch and /pull on the harness home, and the human-only authority to remove rules all stay. CLAUDE.md is user-owned, so every CLAUDE.md line change is gathered into one decision (UD-CM) that comes with the exact diff.
- Few edits per file. A prompt file is edited at most three times: one mechanical path substitution (P2), the /close and /commit cut-over (P4, those two files only), and one prose pass (P8: include files, corrections, stamps, tutorials). Prompt-wording tests (X52) change in the same commit as the prose they pin.
- Recurrence fixes ride with the phase that owns the mechanism, and all of them are producer-side or CI. P7: CI green and run weekly; G2 runs py_compile or bash -n on harness hook and script edits. P9: recoverable git rm without -f; a size ratchet in CI only; BA's 'retire' verdict, which is a proposal the human decides.
- Human-only actions stay human. Deleting remote refs, rewriting history, untracking settings.json and changing CLAUDE.md wording are REQUESTs or decisions. Every decision comes with a recommended default, so the user can answer once.

## Phases at a glance

| Phase | Problems | Effort |
|---|---|---|
| P0 Hotfix: stop the origin leak, unblock CI collection, stop the prompt re-injection | D1, C4, E3, D3 | S (half a day) |
| P1 Make producer gates G1-G3 correct (every switch still advisory) | A1, A4, B1, B3 | M (about 16 small edits, roughly 2 days) |
| P2 Run in any repo; overnight starts and ends; arm G1-G3 | B1, B2, C1, A1 | L (prose qualification about 1.5 days; overnight producer about 2 days; arming commit S) |
| P3 One terminal disposition at the producer; arm G4 | A2, B1, B4 | L (resolver M, terminal anchors M, S7 M; about 4 days) |
| P4 /close and /commit consume the disposition; legacy checks and advisory sinks retired | A2, D4, D1, A1 | M (about 2 days; mostly deletions) |
| P5 Producer input and identity are measured | A3, A4 | M (about 2 days) |
| P6 Portable product: the template is the single settings source | C1, C2, C3, D3, F4 | M-L (about 3 days, plus the human-run untrack step) |
| P7 Private tree and green hermetic CI | C3, C4, E1, E4, F2, F3 | L (about 3.5 days; mostly mechanical) |
| P8 One producer per fact; one prose pass | D1, D2, D3, D4, E2, E3, F3 | L (about 3.5 days; prose S per file, D3.c M) |
| P9 Clean tree, product repos unpolluted, recoverable removal, size ratchet | E1, E2, E4, D1, D2, F1, F2, F4 | L (about 3 days; lands as two commits: deletions and hygiene first, then removal path, ratchet and BA verdict) |

## P0 Hotfix: stop the origin leak, unblock CI collection, stop the prompt re-injection

**Goal.** Three fixes. Dirty Stops stop pushing checkpoints of untracked files to the public origin by default. pytest collection stops aborting. Slash commands stop re-sending their whole command file (/dev 108 KB, /close 120 KB) in the UserPromptSubmit output.

**Why this order.** These are three independent defects of a few lines each, with no dependencies. (1) The checkpoint push leaks private data on every dirty Stop: checkpoint-core.sh:409 pushes refs/checkpoints/<branch> to origin and never reads GIT_AUTO_PUSH. The public origin already holds 255 such refs, and one tree in them lists .claude.json. (2) The collection breaker hides every test result the later phases rely on. (3) The re-injection is the largest single prompt cost. Shipping them first takes half a day and makes every later phase cheaper.

**Problems.** D1, C4, E3, D3

**Changes**

| File | Locations | Change |
|---|---|---|
| hooks/lib/checkpoint-core.sh | _checkpoint_rate_limited_push :321 (worker push :409) | D1.d. The function's first line becomes: return 0 unless GIT_AUTO_PUSH is '1' (unset means off). Checkpoints stay local recovery refs, and /push is the only route to a remote. fswatch is not touched: it is an opt-in daemon whose environment does not come from settings.json. |
| hooks/git-hooks/post-commit-auto-push | :16 | D3: change the default from ${GIT_AUTO_PUSH:-1} to the same rule, unset means off, so both readers of the switch agree. The in-repo copy is dead and P9 deletes it; removing the installed copies is a human REQUEST. |
| settings.template.json; settings.json | :14 in both | Change GIT_AUTO_PUSH from '1' to '0' in both. The author can re-enable remote backup through the P6 overlay (decision D1.d). |
| tests/test_tool_policy_inference_note.py | whole file (module-level pytest.fail at :39-40) | C4.a: delete it. It aborts collection because its baseline copy lives under a gitignored dev-registry path. The policy stays covered by hooks/tests/test_tool_policy_contracts.py and tests/test_bash_write_targets_verb_narrowing.py. |
| hooks/prompt-workflow.py; tests/test_prompt_workflow_injection_cadence.py; tests/test_prompt_workflow_liveness_tz.py | checklist_message :1278-1280; the expectations that pin the appended section | E3.a: delete the 3-line command-spec append. The overnight continuation re-send at :1090-1104 is unchanged. Update the two tests in the same commit. |

**Acceptance tests**

- Scratch repo with a local bare origin and GIT_AUTO_PUSH unset: a dirty Stop through hooks/auto-commit.sh -> `git ls-remote origin 'refs/checkpoints/*'` is empty, and refs/checkpoints/<branch> exists locally. With GIT_AUTO_PUSH=1 -> the ref is on origin.
- Running hooks/git-hooks/post-commit-auto-push in a scratch repo with GIT_AUTO_PUSH unset -> exit 0, no push
- grep -n GIT_AUTO_PUSH settings.template.json settings.json -> '0' in both
- PYTHONDONTWRITEBYTECODE=1 python3 -m pytest --collect-only -q (py3.12) -> exit 0, no collection errors
- A /dev UserPromptSubmit payload through hooks/prompt-workflow.py -> stdout has no 'COMMAND SPECIFICATION' section. An overnight continuation payload still re-sends it. The two updated tests pass.
- git diff --numstat -- hooks scripts schemas -> net code lines <= 0

**Effort.** S (half a day)

**Risk and rollback.** Risk: anyone relying on remote checkpoint backup loses it. The switch is documented in the PR, and the overlay or GIT_AUTO_PUSH=1 restores it. The command file is already loaded by the slash command itself, so removing the append loses no context. Rollback: revert the commit.

**Decisions (recommended default included)**

- D1.d: make remote checkpoint backup opt-in, with unset or '0' meaning off, including in the author's live settings. Recommended: yes. REQUEST for the human: delete the 252 refs/backups/claude/* and 3 refs/checkpoints/* refs on the public origin, review the .claude.json listed in refs/checkpoints/master@1fb1fc7, and remove the installed post-commit-auto-push copies from .git/hooks/post-commit.

## P1 Make producer gates G1-G3 correct (every switch still advisory)

**Goal.** Run in a sandbox with CLAUDE_OBLIGATION_GATE, STOPGATE and BARRIER set to block, under the real T1 transcript order. Every compliant producer dispatch and stop of /dev, /redev, /dev-command, /do, /close and /commit passes G1-G3. Honest terminals pass G2. Overnight dispatch families are evaluated correctly at hook level. Separately: the completion gate stops failing in product repos, the Stop coordinator shows its block reasons, and a blocked Stop no longer locks the next turn. Nothing is armed and settings files are untouched.

**Why this order.** The armed sandbox test of 2026-10-12/13 shows that arming today deadlocks every pipeline except the /do half. The causes:
- G3 blocks its own in-flight dispatch under T1.
- A refused dispatch poisons every later one.
- The templates mint dev-<ts>-l6 (dev.md:199 + :460), which fails TASK_ID_RE.
- required_values blocks honest fail and blocked outcomes.
- profile=repair is rejected by G1.
Separately, stop-completion-gate already blocks every /dev Stop in any product repo while unarmed. All of these fixes are behaviour-neutral in advisory mode, so they ship before anything is armed.

**Problems.** A1, A4, B1, B3

**Changes**

| File | Locations | Change |
|---|---|---|
| hooks/subagentstop-artifact-contract-enforce.py | waived_by_response match :928-933 | Match the waiver line-anchored with re.MULTILINE. A multi-line close-QA reply carrying CLOSE_REPORT_APPEND_ERROR or CRITICAL then waives the file obligation, which is the sanctioned honest terminal of design G5. |
| hooks/subagentstop-artifact-contract-enforce.py | _wire_qa_chain :498-572 | Drop MISSING_ARTIFACT findings for completion-<task>.md, which is written after QA by design. Otherwise, once escalations land where the terminal reads them, every compliant cycle gains an ESCALATION finding. |
| hooks/subagentstop-artifact-contract-enforce.py | _cycle_id :295-309; _cycle_dir :573-574; :604 | B1.a: write escalation records into the registry directory that the terminal scans, via obligation.registry_dir_for(task_id). |
| hooks/lib/obligation.py; schemas/obligation.v1.json | TASK_ID_RE :122-124; read_first_record_prompt :644; new canonical_task_id(), registry_dir_for(), PRODUCER_ROLES; schema properties.task_id.pattern | The grammar also accepts dev-<ts> and dev-<ts>-l<N>, the ids dev.md mints at :199 and :460; dev-command-<ts>-lN is already accepted. canonical_task_id() is one normaliser shared by G1, G3, the escalation writer and the completion gate, replacing three separate derivations. read_first_record_prompt returns the first type=user record and skips queue-operation records. PRODUCER_ROLES (ROLES minus spec and graphify, which carry no obligation per design 1.5.1) lives here. The schema pattern is updated for parity, which the existing parity test checks. |
| hooks/pretool-aggregate-check.py | _scan_transcript_for_prior_obligations :427-488; _run_obligation_barrier :597-668; REPAIR_PROFILE :387, :616; family :269-284, :483, :620 | A1.e plus T1. - A prior stage is an Agent/Task tool_use that has a non-error tool_result and whose id differs from payload.tool_use_id. This excludes the in-flight dispatch, parallel siblings and dispatches refused by any hook. - Parse obligations strictly with parse_obligation instead of _lenient_obligation_fields. - Retry rule: skip prior artifacts whose path the current obligation declares again. - Family: the same canonical_task_id, or its base without a trailing -l<N>. Overnight pipeline suffixes -<N> are separate families. - Delete the repair-profile bypass. |
| hooks/pretool-do-block-subagents.py | REPAIR_PROFILE :76; branch :118; docstring :35-44 | Delete the twin repair-profile bypass. No template emits it, and G1 rejects it. |
| hooks/pretool-obligation-gate.py | _evaluate :125-146; _dev_registry_dir_exists :86-87; :134; PRODUCER_ROLES :70-76 | A1.c plus A4.b. - A missing block is a violation when the latest slash command in the transcript is dev, redev, dev-command, dev-overnight, do, close or commit. This replaces the lookup keyed on the session UUID. - Load known_schema_ids from Path(__file__).resolve().parent.parent/'schemas'/'registry.json', the harness root and never the project. - Bound dispatched_at with obligation.dispatch_clock_within_bound (:584). - Validate any Agent prompt that contains '<obligation', whatever its subagent_type. - Reject the dispatch when obligation.role differs from tool_input.subagent_type. - Import PRODUCER_ROLES. The gate stays stateless. |
| schemas/ba-qa-report.v1.json (new); schemas/registry.json; hooks/lib/obligation.py; agents/qa.md | registry entry; TERMINAL_VOCABULARY :129; agents/qa.md BA-Validation section :81 | A1.d. Register the shape that all three dispatch templates prescribe: a top-level verdict of 'pass' or 'fail', objections[], summary, plus identity (commands/dev.md:682-691, dev-command.md:499, dev-overnight.md:1135). Add a TERMINAL_VOCABULARY entry {verdict: pass/fail}. agents/qa.md gets one line pointing at this shape. The dual-shape fallback in scripts/dev-lifecycle.py:160-164 stays for historic reports. |
| commands/dev.md; commands/dev-command.md; commands/dev-overnight.md | dev.md :510, :635, :743 (identity), :874, :1023 (required_values); dev-command.md :394, :460, :556 (identity), :607, :665 (required_values), postcondition :941-942; dev-overnight.md :1095, :1197 (identity), :1289, :1390, :1504, :1506 (required_values) | Add identity {task_id, request_id} to every json artifact. Delete required_values from the dev and qa obligations, so the schema enums (TERMINAL_VOCABULARY, drift-tested) are the single truth for legal terminal values. The dev-command postcondition passes the bare timestamp task id. |
| agents/dev.md; agents/qa.md | agents/dev.md:41; agents/qa.md:193 | Delete the R10 'required_values' sentences. The chain-level pass moves to the P3 disposition. |
| commands/close.md; commands/do.md | close.md:606, :567; do.md:53 | The /do-path close-QA uses profile do-close. Its response_line regex admits the ^CLOSE_REPORT_APPEND_(ERROR/CRITICAL): family. do.md:53 states the real default of the /do gate, which is block. |
| hooks/stop-completion-gate.py | _import_resolve_chain :211-226 (:218); task id :187, :331-333; exemption :161-167 | B1.a. - Load the resolver from Path(__file__).resolve().parent.parent/'scripts'. - Derive the task id with obligation.canonical_task_id. - The /close and /commit exemption works through the fixed read_first_record_prompt. P3 folds this gate into G4. |
| hooks/stop-workflow-coordinator.py; hooks/lib/checkpoint-core.sh | coordinator :157-177, :262-277, :328-338 (keep the fixed codes at :253-260, :296-303); checkpoint-core.sh:519 | B3.a. On a blocking phase, write failed_phase and the last 4 KB of that phase's stderr to stderr before exit 2. Only the timelock and coverage phases may block; auto_commit and cleanup failures are logged and allowed, which retires one rule. checkpoint-core runs mkdir -p on its log dir before the redirect. |
| hooks/prompt-workflow.py | main() :2001 | B3.c. At UserPromptSubmit, unlink <state_dir>/claude-tool-streak-<sid>.json, which deletes per-turn state instead of adding any. If UD2 makes /do single-turn, also unlink claude-orchestrator-consent-<sid>.flag when the new prompt is not /do. |
| hooks/tests/test_artifact_contract_enforce.py; hooks/tests/test_obligation_gate.py; hooks/tests/test_obligation.py; hooks/tests/test_stop_obligation_gate.py; tests/test_aggregate_dev_report.py; hooks/tests/test_laneb_stop_coordinator.py | test_artifact_contract_enforce.py :707-730, :941-978, :1269-1290, plus new cases | Add a regression case for every false block in the armed test: T1 self-record, poison, siblings, overnight families, the template grammar including dev-<ts>-l6, honest terminals, the sentinel. Update expectations for the removed repair profile and the coordinator's stderr relay. |

**Acceptance tests**

- PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q hooks/tests/test_artifact_contract_enforce.py hooks/tests/test_obligation.py hooks/tests/test_obligation_gate.py hooks/tests/test_stop_obligation_gate.py tests/test_aggregate_dev_report.py hooks/tests/test_laneb_stop_coordinator.py -> 0 failed
- G3 with CLAUDE_OBLIGATION_BARRIER=block:
- Last transcript record is the current Agent tool_use (id == payload.tool_use_id), obligating a not-yet-written docs/dev/context-<ts>.json -> exit 0.
- Prior tool_use with an is_error tool_result -> ignored.
- Parallel sibling with no tool_result -> ignored.
- Completed prior dispatch whose artifact is missing -> exit 2.
- A refused <ts>-0 QA dispatch does not block the <ts>-1 QA dispatch.
- Overnight pipelines -1 and -2 are separate families; lanes -l1 and -l2 share one.
- G1 with CLAUDE_OBLIGATION_GATE=block:
- /dev transcript plus a ba dispatch with no obligation -> exit 2 missing_block.
- Schema id ba-qa-report.v9 -> exit 2.
- dispatched_at two hours old -> exit 2.
- role=graphify with subagent_type=dev -> exit 2.
- A general-purpose dispatch carrying an obligation is validated.
- A /spec QA dispatch without an obligation -> exit 0.
- Running the gate with cwd in a product repo that has no schemas/ dir still loads the harness registry.
- Every '<obligation' block in commands/dev.md, dev-command.md, dev-overnight.md, close.md and commit.md, with placeholders filled, parses with obligation.parse_obligation(known_schema_ids from the harness registry). Ids dev-<ts>-l6 and dev-command-<ts>-l2 parse.
- G2 with CLAUDE_OBLIGATION_STOPGATE=block:
- qa.status=fail -> exit 0.
- dev.status=blocked, and dev.status=needs_review -> exit 0.
- A BA-QA report with verdict=fail -> exit 0.
- A close-QA multi-line reply ending 'CLOSE_REPORT_APPEND_ERROR: ...' -> exit 0.
- A missing artifact -> exit 2, with the message addressed to the producer.
- B1.a:
- Scratch product repo with no scripts/ dir plus a /dev transcript: stop-completion-gate output has no GATE_ERROR.
- A /close transcript beginning with two queue-operation records -> exempt.
- A compliant cycle produces no ESCALATION finding.
- B3.a:
- Coordinator with a HOME that has no logs/ dir and no git identity -> exit 0.
- A timelock-phase block -> stderr contains the timelock text.
- B3.c: after a blocked Stop, the next UserPromptSubmit removes claude-tool-streak-<sid>.json, and a following Edit is allowed.
- Sandbox-only armed replay: the patched tree is swapped into the scratchpad sandboxes arm-dev (bin/run_compliant.sh), arm-dev-command, arm-do (tools/compliant.py) and arm-close-commit-producers (tools/compliant.py). Each runs with settings.armed.json minus TERMINAL, under T1 order.
- Every compliant run reaches its terminal with 0 obligation-gate blocks.
- Matrix rows V2b, V2e, V3, V4 and V5 are still stopped at dispatch or at the producer stop.
Overnight is covered by the hook-level family cases above; its Step-2 deadlock is fixed in P2.
- git diff -- settings.json settings.template.json -> empty; git diff --numstat -- hooks scripts schemas -> net code lines <= +150

**Effort.** M (about 16 small edits, roughly 2 days)

**Risk and rollback.** Risk: in advisory mode the changes are behaviour-neutral, except B1.a, B3.a and B3.c, which are pure bug fixes. G1's role binding and its schema-registry check bite only once P2 arms the gate. Rollback: revert the commit.

**Decisions (recommended default included)**

- D-A1-1: delete required_values from the templates and delete the R10 sentences, so the schema enums are the single truth and the chain-level pass moves to the P3 disposition. Recommended: yes. It is the smallest change that lets STOPGATE block safely.
- D-A1-2: G1 enforces a missing block by the pipeline context derived from the transcript (dev, redev, dev-command, dev-overnight, do, close, commit), rather than unconditionally. Recommended: transcript context. Unconditional enforcement would force obligations onto /spec and free-form dispatches.
- UD2: /do consent scope, single turn (as in the code) or the whole session (CLAUDE.md:60). This decides whether B3.c also expires the consent flag at each prompt. Recommended: single turn.
- Confirm that the G1 role binding (A4.b) ships here, together with the other G1 edits. Recommended: yes; it closes the role_mismatch hole that disarms G2.

## P2 Run in any repo; overnight starts and ends; arm G1-G3

**Goal.** Every pipeline's own shell blocks find harness scripts in the harness and project files in the project, in any product repo, with CLAUDE_PROJECT_DIR unset (as it is in the Bash tool). /dev-overnight gets past Step 2 and enforces end_time correctly in every timezone. It has a producer for its cycle contract and its closeout facts, can end honestly or through the human /stop, and lands the way the user requires: /close only after the whole session ends. As the last commit, G1-G3 are armed in the live settings.json and the template together.

**Why this order.** These breakages fire with the gates unarmed: the Step-17 resolver exits 2, /close Step 0 fails, overnight Step 2 deadlocks, and in UTC+8 there is no time-lock at all. Arming before this point would turn path failures into G2/G3 'artifact missing' blocks for anyone working in a product repo, which breaks the runnable-before-armed principle. P3 needs this phase's contract producer, its main/working-root locator and state.worktree_path.

**Problems.** B1, B2, C1, A1

**Changes**

| File | Locations | Change |
|---|---|---|
| settings.template.json; settings.json | env | C1.c (export): add CLAUDE_HOME={{CLAUDE_HOME}}. The live file holds its own root until P6 renders it. This is the one harness-root channel for prose run through the Bash tool; claude_home.py already validates the hint. |
| hooks/prompt-workflow.py | PROJECT_DIR resolution :62-97; main :2001 | B1.g: for slash commands, print PROJECT_ROOT=<abs> and HARNESS_ROOT=<abs> in the injected context, for paths given to the Read tool. No new file. |
| commands/dev.md; commands/dev-command.md; commands/dev-overnight.md; commands/close.md; commands/commit.md; commands/spec.md; commands/codex.md; commands/tickets.md; commands/test.md; commands/restart.md; commands/pull.md; commands/spec-update.md | dev.md :160, :209-210, :865, :907, :945, :1386 (plus 28 CLAUDE_PROJECT_DIR uses without a fallback and 4 venv lines); dev-command.md :104, :159-160, :194, :604, :941 (plus 13); dev-overnight.md :1286, :1578 (plus 14); close.md :246-251, :338, :345, :508, :602, :776, :950; commit.md :313, :320, :965; spec.md :163, :428; codex.md (5 lines); tickets.md:35 | B1.e, B1.g and the C1.c prose, done as one mechanical substitution reviewed as such: - harness script -> $CLAUDE_HOME/scripts/<name> - venv -> source $CLAUDE_HOME/venv/bin/activate - project root -> ${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)} - Read-tool paths -> <PROJECT_ROOT>/... In close.md and commit.md, only the lines that survive P4 are touched, plus the two Step-0 resolver lines (close.md:338, :345) that keep /close runnable until P4 replaces that block. The commit.md:334 loop is left for P4 to replace. |
| agents/ba.md; agents/qa.md; agents/graphify.md; agents/changelog-analyst.md; agents/test-executor.md; agents/spec.md; agents/test-validator.md; agents/dev.md; agents/pm.md; agents/user.md; agents/product-owner.md; agents/architect.md | ba.md:780; qa.md :1137, :1138, :1146, :1155 (plus 6 venv lines); graphify.md :22, :28; changelog-analyst.md :399, :651, :669, :729, :1855, :1899, :1905; venv lines (test-executor 10, spec 7, test-validator 2, dev 2, others 1 each) | The same mechanical substitution. The changelog-analyst sites that use ${CLAUDE_PROJECT_DIR}/.claude/scripts become $CLAUDE_HOME/scripts, so the session-index fail-closed guard stops silently passing. |
| hooks/posttool-lane-completeness-watch.py; hooks/lib/specialist_yield.py | :216-218; :70-74 | Resolve harness scripts via Path(__file__).resolve().parent.parent, and policies via claude_home.resolve_optional('policies/...'). |
| scripts/write-qa-mode.sh; scripts/break-overnight-lock.py | write-qa-mode.sh:35; break-overnight-lock.py:30 | Fall back to ${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)} instead of exiting 1 or falling back to the harness home. |
| hooks/lib/overnight.py | candidate_project_dirs :63-92; _end_time_passed | B2.h: one locator. - Main root = parent of `git rev-parse --path-format=absolute --git-common-dir`, falling back to CLAUDE_PROJECT_DIR. - Working root = state.worktree_path. - cycle_index(state) = cycle_count + 1. - _end_time_passed is the only end_time parser, and it compares in UTC. |
| hooks/stop-overnight-timelock.py | :61-69, :72-87 (:84 drops tzinfo), :100-120, :138-150, :240-243, :245, :248-257, :270-278, :281 | B2.d plus B2.b. Use the shared locator and the UTC parser, and delete the local parser that drops the timezone. The closeout is recomputed from disk under the working root: - retro-report-cycle*.json exists under docs/dev/overnight/<sid>/; - an overnight-summary-*.md is newer than start_time; - the checkpoint status comes from git: a clean tree, or a refs/checkpoints/<branch> tree equal to the working snapshot. Delete the three self-declared state-field reads and the unresolved_backlog blocker, which has no writer. Both deletions retire rules. |
| hooks/posttool-overnight-loop.py; hooks/posttool-overnight-file-check.py; hooks/lib/closeout.py; hooks/pretool-subagent-enforce.py; hooks/lib/contract_runtime.py | loop :62-77, :120; file-check :66-79, :109-114, :117-119; closeout :45-55; subagent-enforce :86-99, :211-237, :329-339; contract_runtime :79-125 (:101-107) | B2.e(3,4) plus B2.h. Use the shared locator and cycle index, and resolve overnight artifacts against state.worktree_path. A malformed contract becomes a Case M block instead of silently switching enforcement off. |
| scripts/create-overnight-state.sh | :1026-1056 (required_calls: [] at :1051) | B2.e(1): the launcher seeds required_calls for step 2 (pm PLAN), steps 3-<specialist> and step 4 (pm TRIAGE), with schema names dev-report.v2 and qa-report.v2. |
| hooks/posttool-subagent-track.py; hooks/posttool-overnight-loop.py | PM TRIAGE completion handler; reset path :186-197 | B2.e(2). When the PM TRIAGE dispatch completes, the hook renders steps 8/10/11g/12/15/20 into the same hook-authored cycle-contract.json. It takes the pipelines from scripts/build-pipelines-from-triage.py and imports the step labels from scripts/todo/dev-overnight.py _STEPS rather than copying them, so there is one truth and no parity copy. At loop reset, posttool-overnight-loop renders the cycle-(N+1) seed. This is the only new code larger than a few lines in this phase. |
| scripts/update-overnight-state.sh; scripts/break-overnight-lock.py | update-overnight-state.sh IMMUTABLE_FIELDS :75-81; break-overnight-lock.py :37-101 | B2.b. Add status, terminal_status, end_time and start_time to IMMUTABLE_FIELDS, so the agent can no longer release the lock with one --set. The human /stop path writes the state file directly under the helper-auth token, so it is unaffected; it also sets terminal_status=cancelled_by_user. |
| commands/dev-overnight.md | :806-841, :826-827; Step 1 block; write-qa-mode call; :124, :1576-1578, :1721, :1765-1816 | B2.a plus the fixes from the armed test. - Delete the 'orchestrator writes the contract' prose and the v1 schema names. - Remove apostrophes from the Step 1 comment lines, which trip the bash-safety census. - Pass --task-id <pipeline-ts> to write-qa-mode.sh. - Delete the Step 19 per-cycle commit and the HEAD-commit claims; work is preserved in refs/checkpoints/<branch>. - Post-loop flow, after the session ends: /close --auto, then /commit --bulk, then /merge (isolated modes only), then /push. scripts/commit.sh becomes unreferenced and is kept (hold). |
| settings.template.json; settings.json | env (:3); template PreToolUse Agent group (~:582), SubagentStop, Stop (~:759); live registrations settings.json:611, :904, :835 | A1.a, as the last commit of this phase: add CLAUDE_OBLIGATION_GATE=block, CLAUDE_OBLIGATION_STOPGATE=block and CLAUDE_OBLIGATION_BARRIER=block to both files. Leave TERMINAL unset, which means advisory. Register pretool-obligation-gate.py, subagentstop-artifact-contract-enforce.py and stop-obligation-gate.py in the template with {{CLAUDE_HOME}}, mirroring the live file. Hook code defaults stay unchanged. |

**Acceptance tests**

- In a scratch product repo with no scripts/ dir, CLAUDE_PROJECT_DIR unset and CLAUDE_HOME set, run these shell blocks: close.md Step 0, the QA-arming block, commit.md Step 5, dev.md Step 17 (:1386) and the dev-command postcondition (:941) -> no 'No such file', no exit 127, no path-related exit 2.
- git grep -nF '.claude/venv' -- commands agents -> 0. git grep -n 'CLAUDE_PROJECT_DIR' -- commands agents | grep -v 'CLAUDE_PROJECT_DIR:-' -> only prose that names the variable. git grep -nE '(^|[ (])(python3 )?scripts/[a-z0-9_-]+[.](py|sh)' -- commands agents | grep -v CLAUDE_HOME -> only deliberate product-repo paths.
- Timelock: end_time = now+1h UTC, under TZ=Asia/Shanghai and TZ=America/Los_Angeles -> Stop blocked with the time-lock message in both zones. With end_time passed -> the closeout is evaluated.
- Closeout:
- retro-report-cycle1.json, an overnight-summary newer than start_time, and a clean tree -> Stop allowed.
- A missing retro report -> Stop blocked, with the reason visible on stderr through the P1 coordinator relay.
- scripts/update-overnight-state.sh --set status cancelled -> refused (immutable). break-overnight-lock.py with the helper-auth token -> terminal_status=cancelled_by_user, and Stop is allowed.
- Contract:
- A launcher-created contract lets the Step 2 PM PLAN dispatch pass pretool-subagent-enforce (exit 0).
- After a PM TRIAGE completion payload, cycle-contract.json holds steps 8/10/11g/12/15/20, with labels equal to scripts/todo/dev-overnight.py _STEPS.
- A malformed contract -> exit 2, Case M.
- A session whose CLAUDE_PROJECT_DIR is the worktree -> the timelock finds the state file in the main root.
- Armed replay with G1-G3 set to block, under T1 order: the P1 sandboxes plus arm-overnight (tools/compliant.py and multi.py), each run in a scratch product repo.
- Compliant /dev, /dev-command, /do, /close and /commit complete with 0 false blocks.
- Overnight 1-pipeline and 2-pipeline cycles complete with 0 false blocks, and the session ends after end_time.
- V2b, V2e, V3, V4 and V5 are still stopped.
- grep -c CLAUDE_OBLIGATION_ settings.template.json settings.json -> 3 in each; grep -n pretool-obligation-gate settings.template.json -> 1 match
- git diff --numstat -- hooks scripts schemas -> net code lines <= +200

**Effort.** L (prose qualification about 1.5 days; overnight producer about 2 days; arming commit S)

**Risk and rollback.** Risk: the overnight HARD CUTOVER blocks on any label mismatch, which is mitigated by importing _STEPS instead of copying the labels. Prompt-wording tests that pin the edited paths (X52) need updating in the same commit. Making the state fields immutable changes how sessions can end. Migration: live sessions keep running on this tree, so cycles will be in flight when the arming commit lands. The PR's release note says to finish or /close in-flight cycles before pulling it. A cycle resumed afterwards that predates the new templates resolves as incomplete, and /redev re-dispatches its missing stages under the new templates; the per-session kill switch also works. Rollback: delete the three CLAUDE_OBLIGATION_* env lines (instant), or revert. The prose commit, the overnight commit and the arming commit can be reverted separately.

**Decisions (recommended default included)**

- B2.a landing route after an overnight session: /close --auto then /commit --bulk (one bulk commit per session, as the architecture says), or a per-task /commit for each closed pipeline. Recommended: /close --auto then /commit --bulk.
- Confirm the CLAUDE_HOME env export as the single harness-path channel for prompts. Recommended: yes; P6 renders it per install.
- D-B2e: cycle-contract steps 8-20 rendered per pipeline by the hook (importing _STEPS), or role-wildcard entries seeded by the launcher (no renderer, weaker matching). Recommended: render per pipeline.
- When to merge the arming commit. Recommended: when none of your sessions has a /dev cycle in flight.

## P3 One terminal disposition at the producer; arm G4

**Goal.** The resolver computes one disposition (chain_pass, honest_blocked, forced or incomplete, with evidence). Each terminal anchor blocks only on incomplete, gives one repair round, and then leaves the incomplete disposition on disk for /close to report. The anchors are the Stop recompute in stop-obligation-gate, the overnight loop reset and the /do report gate. The completion gate folds into G4. The collection gates are generalized, G2 checks freshness and the lane_set echo, and CLAUDE_OBLIGATION_TERMINAL is armed after a real-session confirmation of the bound.

**Why this order.** This is rollout S7-S9, which may only follow gates that are armed (P2) and runnable (P2); the overnight recompute uses P2's contract and locator. P4's consumer cut-over must not land until this disposition is green (design M34). The armed test measured G4 as unbounded ([2,2,2,2,2], stop_hook_active ignored), so the bound has to exist and be confirmed before TERMINAL is armed.

**Problems.** A2, B1, B4

**Changes**

| File | Locations | Change |
|---|---|---|
| scripts/resolve-dev-artifact-chain.py | _base_result :1290; end of resolve_chain :1773; :1936, :2221, :2262 | S8. Add disposition and evidence[] to the result. - honest_blocked: the canonical dev-report parses, its identity is valid, and dev.status is blocked or needs_review; downstream artifacts are not required. - forced: the legacy 'CLOSE: YES (FORCED)' last line. - incomplete: everything else, including unresolved G2 escalation records under registry_dir_for(task). Also: - Add a do-report branch. - Derive the roster from shard lane_sets, and name both rosters when they diverge. - An explicit spec_path must resolve; an auto-detected spec is advisory only. - A new --disposition flag prints one flat line (DISPOSITION= TASK= REPORT= ...) and exits non-zero only on instrument failure. Default-mode output is unchanged. |
| tests/test_resolve_dev_artifact_chain.py; schemas/context.v1.json | :292; an additive spec_path_source field if absent | Disposition fixtures for each outcome; a default-mode regression test. |
| hooks/prompt-workflow.py | :1788 (_dev_report_reached_terminal), :1842, :1912 | S8 replay fix: replace the check, which reads dev-report-dev-<ts>.json, a file /dev never writes, with the design's 60 s window on the replay record's mtime. An identical bare /redev then no longer replays forever. |
| hooks/subagentstop-codex-enforce.py | :76 | Skip when the stopping agent's own obligation pipeline is close or commit (close #146). |
| hooks/stop-obligation-gate.py; hooks/lib/obligation.py | gate :81, :104, :138; find_unresolved_dispatch_obligations :900-1021; prefilter :960-968 | S9. - Scope: task_ids of obligation blocks in dev, redev, dev-command or dev-overnight dispatches made since the latest human prompt record (type=user, not a tool_result, not isMeta). An abandoned earlier cycle therefore does not cost every later turn a repair round. - Compute each task's disposition with the resolver imported from Path(__file__).parent.parent/'scripts'. - Ignore dispatches whose tool_result is_error. - Block (exit 2) only when a disposition is incomplete and stop_hook_active is false. - When stop_hook_active is true, exit 0. The incomplete disposition stays on disk and /close reports it. - No record and no counter. Drop the dev-registry token prefilter. |
| hooks/stop-completion-gate.py; settings.json | registration settings.json:843; whole file | D-A2-3 fold, which also covers B1.b. A missing completion now yields incomplete, so unregister the gate. Reduce the file to an exit-0 stub: live sessions keep the hook list they loaded, and a missing python file exits 2 and would block every Stop. P4 deletes the stub. Move its tests into hooks/tests/test_stop_obligation_gate.py. This retires one hook, its arbitration path and its two audit logs. |
| hooks/posttool-overnight-loop.py | :202, :268-293 (:274-275, :287-288) | S9 overnight. - Replace conditions (a) and (b) with per-pipeline dispositions for the contract's step-12 roster, resolved against state.worktree_path. - On incomplete, print repair instructions on the blocking channel and do not reset the cycle. - Retries are counted from the transcript, as the number of Agent tool_use records for that pipeline's task id after the first incomplete. They are capped at the cycle contract's max_retries (schemas/cycle-contract.v1.json:106). - Expiry precedence is unchanged. |
| hooks/stop-do-report-gate.py; commands/do.md | MAX_BLOCKS :57; counter sidecar :150-169; :172 (_rewrite_pending_to_blocked), :210-218, :236-256, :274-282; docstring :31-33; do.md:53 | B4. - Block when the report is non-compliant and stop_hook_active is false. - When stop_hook_active is true, finalise only the hook's own skeleton: an absent report is re-minted in the skeleton shape (prompt-workflow.py:1365) with do.status=blocked; a pending report becomes blocked (the existing :172 path). Then exit 0. - An agent-written non-compliant report is left unchanged, and the resolver's do-report branch returns incomplete, so the hook never becomes a second producer of the agent's artifact. - Delete MAX_BLOCKS and the /tmp counter sidecar; deleting a sidecar can then no longer disarm the gate. - Correct the docstring and do.md. |
| hooks/pretool-aggregate-check.py | main() :655; :247, :284, :356 | S7. - When the prompt has an obligation, scope to its canonical_task_id and never fall back to the global scan (close #139, commit #261). - The canonical aggregate must pass validate_artifact_for_obligation(dev-report.v2) plus an identity check. - Wherever shards carry lane_set, parallel_workers must equal both the union of the shard lane_sets and the obligation's lane_set. |
| hooks/pretool-gitignore-preflight.py | :652, :717, :810 | S7: exempt dispatches whose parsed obligation profile is commit-qa, commit-landing, do-close or final_verification. This is equivalent to the existing E5 grant exemption (commit #260, close #122/#140). |
| hooks/subagentstop-artifact-contract-enforce.py | G2 obligation branch (json-artifact verification) | Call obligation.artifact_freshness_satisfied (obligation.py:605), so stale artifacts from an earlier attempt fail (V5b). Check that dev shards echo lane and lane_set (V10), per design 1.2/1.6. |
| settings.template.json; settings.json | env | The last commit, after the measurement in the acceptance tests: add CLAUDE_OBLIGATION_TERMINAL=block to both files. |

**Acceptance tests**

- python3 scripts/resolve-dev-artifact-chain.py --disposition --task-id <ts> over fixture trees:
- full chain -> 'DISPOSITION=chain_pass'
- dev-report blocked, no qa-report -> honest_blocked
- missing qa-report -> incomplete, with evidence
- close report ending 'CLOSE: YES (FORCED)' -> forced
- do-report completed -> chain_pass
The output is exactly one line. An unimportable aggregator module -> non-zero exit.
- PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_resolve_dev_artifact_chain.py hooks/tests/test_stop_obligation_gate.py hooks/tests/test_stop_do_report_gate.py tests/test_aggregate_dev_report.py -> 0 failed. Default-mode resolver output is byte-identical to HEAD on the existing fixtures.
- stop-obligation-gate with TERMINAL=block:
- QA never dispatched (V9): stop_hook_active=false -> exit 2; stop_hook_active=true -> exit 0.
- honest_blocked -> exit 0 on the first Stop.
- Only a G3-refused dispatch present -> exit 0.
- An unresolved escalation record -> incomplete.
- An incomplete task dispatched before the latest human prompt -> not evaluated.
- Real-session confirmation, run by the human before the arming commit: in a scratch product repo, leave one /dev cycle incomplete. The first Stop is blocked by G4; on the next Stop the payload has stop_hook_active=true and G4 exits 0. Confirm via the hook's stderr debug line.
- An identical bare /redev submitted 2 minutes after a finished cycle starts a new cycle instead of replaying.
- stop-do-report-gate:
- absent report with stop_hook_active=true -> skeleton written with do.status=blocked, exit 0
- pending report -> blocked
- an agent-written 'completed' report with an empty summary -> unchanged on disk, and the resolver returns incomplete
- no file is created under /tmp by the gate
- Overnight loop:
- a pipeline missing its qa-report -> no cycle reset, and repair text on the blocking channel
- after max_retries repair dispatches in the transcript -> the honest path proceeds
- Aggregate check: an unrelated orphan shard plus a scoped obligation -> exit 0; a roster mismatch -> exit 2. gitignore-preflight: a commit-QA dispatch (profile commit-qa) -> exempt.
- grep -c stop-completion-gate settings.json -> 0; hooks/stop-completion-gate.py exits 0 on any payload
- Armed replay with all four switches set to block, under T1 order:
- compliant /dev, /dev-command, overnight (1 and 2 pipelines), /do, /close and /commit all complete
- V5b (stale) and V9 end with an incomplete disposition after one repair round
- git diff --numstat -- hooks scripts schemas -> net code lines <= 0 (the 604-line completion gate becomes a stub)

**Effort.** L (resolver M, terminal anchors M, S7 M; about 4 days)

**Risk and rollback.** Risk: a blocking main-session Stop hook has a wide blast radius. Mitigations:
- the bound is one round per Stop chain via stop_hook_active, confirmed in a real session first;
- the fail-open wrapper;
- the env kill switch;
- the resolver's new mode is opt-in, so existing callers are unaffected.
stop_hook_active is shared by all Stop hooks. During an overnight time-lock, G4 may therefore get no round at the final Stop; the overnight anchor is the loop reset, so this is accepted. Rollback: unset CLAUDE_OBLIGATION_TERMINAL at once. Reverting the commit re-registers the old completion gate, whose file is still present as a stub plus history.

**Decisions (recommended default included)**

- D-A2-3: fold stop-completion-gate's duty into the disposition-based G4 Stop hook (one terminal truth), or keep both hooks. Recommended: fold. Completion is still enforced, because a missing completion means incomplete.
- G4 bound: one repair round per Stop chain via stop_hook_active (stateless, documented field), or a larger N, which would need a transcript count whose per-task record format is unmeasured. Recommended: one round via stop_hook_active.

## P4 /close and /commit consume the disposition; legacy checks and advisory sinks retired

**Goal.** close.md and commit.md each make exactly one disposition call, and report only 'the dev cycle itself failed' (class a), naming the resume route. Every class-b/c/d/e check and every consumer-side routing or re-dispatch loop is deleted. The legacy correlation and guess paths in the stop hooks, the enforce-flag writers, the completion-gate stub, and the advisory log sinks of the now-armed gates are retired.

**Why this order.** These are rollout S10-S12, which the design orders last. Deleting consumer checks before the producers guarantee the evidence (P1-P3) would let /close and /commit trust facts nobody produces yet (M34). The advisory sinks become useless only once all four gates are armed. This is a separate change, so it can be reverted alone if the soak shows problems.

**Problems.** A2, D4, D1, A1

**Changes**

| File | Locations | Change |
|---|---|---|
| commands/close.md | Step 0 :334-408; :410-432; :434-491; :244-274 and :585-597 (keep SESSION_ID :582); :567, :668; routing loop :146-321; RSA :516; Workflow-Integrity bullets 1, 2, 4(i); --force/FORCED text :79, :762, :787, :843, :868, :892, :1013; flag writer :131 | S10 plus D4.f. - Step 0 becomes one call to $CLAUDE_HOME/scripts/resolve-dev-artifact-chain.py --disposition. - chain_pass proceeds. honest_blocked or incomplete gives the single class-a outcome per D-A2-2, naming /redev <task> or /restart; /close dispatches no producer. forced takes the legacy echo. - An instrument failure is retried once, then reported as OPERATION_STALLED with no verdict. - Delete: the do-report preflight, the schema gate, the QA-arming rule and Step-2 arming, the inspector re-validation, the routing loop for class-b findings (kept only for QA class-a findings), the --force short-circuit text, the unreachable FORCED landed form and the enforce-flag writer. - RSA becomes advisory. The WI bullets cite chain_pass. The disposition's path fields feed QA and Step 3. - Kept: every A and X row (bullets 3 and 4(iii), the verdict branches, the append helper, scoring, --auto, late-repair). |
| commands/commit.md | resolver loop :267-286, :331-339 (including the unbounded until-loop at :334); checks 1/2/4 :80, :204, :208, :230; :580-583; :587; :851-854; Step 8 :908-911; STEP7 markers :856, :866; late-repair :301-353 | S11 plus D4.f. - One disposition call (retried once, then OPERATION_STALLED); TASK_REPORT and the fan-out mode are taken from it. - Check 1 becomes AWAITING_INPUT 'run /close first'. - Check 2 keeps the class-a check but stops with not-landed instead of re-dispatching close-QA. - Delete check 4, the commit-QA file cross-check, the unparseable-verdict branch and the unknown-changelog-status branch; G2 enforces all of these at the producer's own stop. - Forced: add the verbatim echo. Step 8 spec-link routing becomes advisory. Rename the STEP7_* markers to Step 8. - The late-repair State-C loop stays flag-gated (hold). The RCR call, grants, QA rejection rules and status table are kept. |
| scripts/step7-spec-update.py; agents/changelog-analyst.md | step7-spec-update.py:23; changelog-analyst.md :161-192 | Rename the markers in the script output. The analyst's Phase-1 chain checks read the disposition fields instead of re-deriving the chain; this only removes checks. |
| hooks/subagentstop-artifact-contract-enforce.py | flag-gated legacy path :1149-1244; _find_correlated_reports :182; _forced_close_flag_present :340; LEGACY_FLAG_DIR :266 | S12, after STOPGATE has run green: delete the legacy correlation path, which is enabled only by .claude/dev-registry/<id>/artifact-contract-enforce.json, and its helpers. This also settles A1.b: armed G2 validates the schema itself, so no advisory fall-through is ever added. |
| hooks/subagentstop-e2e-enforce.py | :348, :387, :406-422 | S12: make _enforce_e2e_via_obligation the primary path. Delete the missing-report guess-block, which loops forever because it ignores stop_hook_active, and the force-sentinel skip. Keep the e2e content check. |
| hooks/prompt-workflow.py; commands/dev.md; commands/dev-command.md | prompt-workflow.py:1593; dev.md:215, :775-777; dev-command.md:160 | S12: retire the artifact-contract enforce-flag writers, whose readers were deleted above. D4.f: delete the Step 9 drift note. |
| hooks/stop-completion-gate.py | whole file (stub since P3) | Delete the stub. It was unregistered one phase earlier, so sessions that loaded it have since restarted. |
| hooks/pretool-obligation-gate.py; hooks/pretool-aggregate-check.py; hooks/stop-obligation-gate.py; hooks/posttool-overnight-loop.py; hooks/subagentstop-artifact-contract-enforce.py; hooks/stop-do-report-gate.py | _emit_advisory and log path pretool-obligation-gate.py:77; pretool-aggregate-check.py:385; stop-obligation-gate.py:56; posttool-overnight-loop.py:28; artifact-contract :61, :120 plus the obligation_verify_fail (~:1085) and obligation_unresolvable (~:1128) emits; stop-do-report-gate.py:58 | D1.e: delete the advisory jsonl sinks of the four armed gates and the /do gate (logs/obligation-gate-, obligation-barrier-, obligation-terminal-gate-, artifact-contract- and do-report-gate-advisory.jsonl), which have a writer and no reader. In advisory (kill-switch) mode the gates simply exit 0. This removes five runtime files and adds no reader. |
| hooks/tests/test_artifact_contract_enforce.py; tests/test_dev_artifact_chain_consumer_contracts.py; hooks/tests/test_e2e_enforce*.py; tests/test_late_repair_route.py | cases referencing correlation, flags, advisory logs and the old consumer wording | Update to the new contract, per decision U-E1e on prose-pinning tests. |

**Acceptance tests**

- grep -c 'resolve-dev-artifact-chain.py --disposition' commands/close.md commands/commit.md -> 1 in each; grep -nE 'close-route-select|jq |route_finding|aggregate-dev-report.py|write-enforce-flag' commands/close.md commands/commit.md -> 0
- grep -n 'CLOSE: YES (FORCED)' commands/close.md -> only the legacy-echo classification line; grep -n STEP7_ commands/commit.md scripts/step7-spec-update.py -> 0
- git grep -nE 'advisory[.]jsonl' -- hooks -> only lane-completeness-watch and cp-enforce (not armed gates); test -e hooks/stop-completion-gate.py -> false
- PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q hooks/tests/test_artifact_contract_enforce.py hooks/tests/test_e2e_enforce*.py tests/test_dev_artifact_chain_consumer_contracts.py tests/test_late_repair_route.py -> 0 failed
- Scratch product repo with all four gates armed:
- a compliant /dev -> /close prints CLOSE: YES -> /commit lands
- a cycle with a deleted qa-report -> /close prints only the single class-a line 'dev cycle itself failed - resume via /redev <task>' and dispatches no subagent
- the resolver made unimportable -> OPERATION_STALLED, no verdict
- Rerun the adversarial end-to-end drivers (scratchpad adv3-spec-dev-close-commit-push, adv3-do-close-commit-push): no repair dispatch originates from /close or /commit.
- git diff --numstat -- hooks scripts schemas -> net code lines <= -300

**Effort.** M (about 2 days; mostly deletions)

**Risk and rollback.** Risk: /close and /commit now trust the producers. A remaining producer gap shows up as a false 'cycle failed', which is honest, not as a false landing. The analyst's typed-handoff checks must keep the fields they read. Without the advisory logs, a kill-switch session leaves no trace, which is accepted. Rollback: revert this change alone; P1-P3 are unaffected and the old consumer checks come back.

**Decisions (recommended default included)**

- D-A2-2: what /close and /commit print for incomplete or honest_blocked. Recommended: a single class-a line, 'dev cycle itself failed - resume via /redev <task> or /restart' (AWAITING_INPUT cause (iv)), with no producer dispatch from /close; the routing loop is kept only for QA class-a findings.
- Confirm the late-repair route stays flag-gated and is not deleted (no-retirement hold). Recommended: yes.

## P5 Producer input and identity are measured

**Goal.** The dev and /do producers list exactly the files they wrote. G2 and the /do gate check that list against the write set derived from the CLI-written transcript of that producer: Write, Edit and NotebookEdit targets, plus paths named in its Bash commands. Every role-based hook takes the role from the CLI-supplied agent_type (or the CLI-written meta.json agentType), not from self-declared sentinel reads. Grant consumers bind to the role. By decision, the orchestrator can no longer write subagent-produced artifacts.

**Why this order.** The checks plug into G2 and the /do gate, so they bite only once STOPGATE and TERMINAL are armed and the chain is consumed (P1-P4). P7's harness predicate then uses this measured write set.

**Problems.** A3, A4

**Changes**

| File | Locations | Change |
|---|---|---|
| hooks/lib/agent_resolver.py | resolve_agent_type :245-255; registry fallback :173-197 | A4.a. First confirm with the existing hooks/capability-canary.py that the CLI in use sends agent_type in subagent PreToolUse, PostToolUse and SubagentStop payloads; the armed sandbox's 2.1.295-shaped payloads carry it. Then resolve the role in this order: payload.agent_type; <transcript>/subagents/agent-<id>.meta.json agentType (precedent subagent_restart.py:519-543); the registries only when both are absent. Agent types not listed in tool-policy keep 'allow'. |
| hooks/pretool-cp-checkin.py; hooks/subagentstop-artifact-contract-enforce.py; hooks/subagentstop-e2e-enforce.py | cp-checkin :167-178, :490-503; artifact-contract :794-815; e2e :347-365 | Stop writing agent-index files when agent_type is present (the existing files are kept). G2's expected_role = payload agent_type. e2e-enforce takes the role from the payload. |
| hooks/subagentstop-artifact-contract-enforce.py | _wire_ledger_judgment :443-495; journal-view sidecar :426-440, :494 | A3.a. Written set = file_path targets of Write, Edit and NotebookEdit tool_use records in payload.agent_transcript_path. Ignoring docs/dev/**, .claude/dev-registry/** and .claude/scratch/**: - each declared files_created/files_modified entry must be in the written set, or named in one of the agent's own Bash commands; - each written path must be declared. A mismatch is a blocking finding, returned to the dev with the exact expected list through G2's existing bounded path. Delete the journal-view sidecar write, which nothing reads. The attribution journal is not extended. |
| agents/dev.md; agents/qa.md | dev.md :520-535; qa.md :470-528 | Replace the git-status derivation with one rule: 'list exactly the files you wrote; the stop gate verifies them'. Delete QA's git re-derivation and under-report checks, which would false-FAIL correct reports. This retires two rules. |
| hooks/stop-do-report-gate.py; commands/do.md | gate :108-111, :264-268; do.md:80 | A3.c. Apply the same comparison over the main transcript records after the /do prompt record: do.files_* against the main agent's Write/Edit targets and the paths named in its Bash commands. Block with the exact expected list; the P3 bound applies. do.md gets the same single rule as dev. |
| hooks/pretool-git-privilege-guard.py; hooks/lib/commit_pipeline.py; hooks/pretool-push-analyst-grant-guard.py | guard :1441-1504 (:1480); commit_pipeline :77-85, :595-720; push-analyst-grant-guard :26, :73 | A4.d: require agent_type == changelog-analyst (or push-analyst / merge-analyst) before an attestation or grant is claimed. |
| hooks/pretool-tool-policy.py; policies/tool-policy.v1.json | tool-policy :9-15, :348-356; policy :157-176 | A4.c, only under decision (b). With no agent_id, a 'main' policy denies Write/Edit and Bash write-targets on the subagent-produced artifact prefixes: ticket-, context-, acceptance-criteria-, the dev-report shards, qa-report-, ba-qa-report-, close-report-, commit-qa-report-, *-inspector-report-, test-writer-report-. Orchestrator-owned outputs stay allowed (do-report-, the canonical dev-report aggregate). dev's allowed prefix '*' gains denies for other roles' artifacts. No journal backstop. |
| tests/test_bash_write_targets_verb_narrowing.py; tests/fresh-clone-bootstrap-smoke.sh; examples/guard-demo/run-demo.sh; hooks/tests/test_agent_resolver.py; hooks/tests/test_artifact_contract_enforce.py; hooks/tests/test_stop_do_report_gate.py | payload builders that use a top-level subagent_type | Switch the payloads to agent_type. Add declared-versus-written cases, including a Bash-created file and a pre-existing untracked file belonging to another session. |

**Acceptance tests**

- Replay of sandbox case T6 (scratchpad landscape-work/A-producer-input-identity/drive.py): one Write and one Bash-created file in a product repo that also holds 6 untracked files from other sessions.
- A dev report listing the 8 git-derived files -> SubagentStop exit 2, naming exactly the 2 real files.
- A report listing those 2 -> exit 0.
- A QA payload with agent_type=qa and no sentinel Read: an Edit of src/x.py -> pretool-tool-policy exit 2 (was rc=0). A QA that Reads the dev.json sentinel keeps role qa.
- Under A4.c (b):
- main-agent Write to docs/dev/qa-report-<ts>.json -> denied
- Write to docs/dev/do-report-<task>.json -> allowed
- dev Write to docs/dev/qa-report-<ts>.json -> denied (V8)
- A dev subagent claiming the commit attestation -> refused; changelog-analyst -> allowed.
- /do with 3 files written and an empty do.files_modified -> Stop blocked, listing the 3 paths.
- PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q hooks/tests/test_agent_resolver.py hooks/tests/test_artifact_contract_enforce.py hooks/tests/test_stop_do_report_gate.py tests/test_bash_write_targets_verb_narrowing.py -> 0 failed
- git diff --numstat -- hooks scripts schemas -> net code lines <= +80

**Effort.** M (about 2 days)

**Risk and rollback.** Risk: matching 'named in a Bash command' stops honest over-reporting but not deliberate forgery (out of scope). Writes by MCP or browser tools are not in the written set; they are covered by the docs/dev and scratch exclusions or must be declared. An older CLI without agent_type falls back to today's behaviour. A4.c could false-deny an orchestrator-owned file that matches a subagent prefix. Rollback: revert; the role resolver, the G2 comparison, the /do comparison and the tool-policy main policy are separate commits.

**Decisions (recommended default included)**

- A3 extends the design, which marked ownership as class-c and out of workstream (2:424-426). Confirm that G2 owns file-list authorship, checked against the CLI-written transcript, and approve deleting QA's git-provenance checks (agents/qa.md:470-528). Recommended: yes.
- A4.c trust boundary: (a) keep the design's content-trust boundary and skip it; (b) a preventive tool-policy deny for the main agent on subagent artifact prefixes; (c) adversarial-grade OS isolation (out of scope). Recommended: (b), which also closes the forge-after-ACK path (V7b).

## P6 Portable product: the template is the single settings source

**Goal.** A fresh non-root clone in any directory works after bootstrap. settings.json is rendered from settings.template.json plus an untracked settings.machine.json overlay. Untracking it is the last, human-run step. Shipped code carries no author values, protected-runtime.json has a producer, and bootstrap and doctor report the real state of the install.

**Why this order.** Shipping the producer gates in the public template only makes sense once they work (P1-P3) and the identity fixes are in (P5). P7's hermetic tests and CI render the template. Untracking settings.json breaks 8 tests unless they move in the same change, and it deletes the file from every clone that pulls, so it has to be the last, human-run step.

**Problems.** C1, C2, C3, D3, F4

**Changes**

| File | Locations | Change |
|---|---|---|
| settings.template.json | Stop group :759-779; env :23, :27-29; permissions :218-220 vs :284-286, :277-301 | C2.a(1). - Port the remaining live-only hooks, in live order, with {{CLAUDE_HOME}} (settings.json :321, :397, :424, :615, :662, :725, :734, :819, :827, :853). G1, G2 and G4 were ported in P2, and the completion gate was removed in P3/P4. - Replace the 4 direct Stop entries with stop-workflow-coordinator.py. - Set TMPDIR and CLAUDE_CODE_TMPDIR to /var/tmp/claude-scratch, and add CLAUDE_CODE_ENABLE_TODO_TOOLS=1. - Set the permission posture per U2 and remove the deny/ask duplicates. |
| scripts/install/render-settings | :46-51, :109-152, :195-197, :205-207, :226 | C2.a(2). - The home defaults to the renderer's own repo root, and REQUIRED_HOOK_SUFFIXES names stop-workflow-coordinator.py. - Merge the untracked <home>/settings.machine.json (permissions, env, top-level keys). - Carry over CLI-owned keys (model, theme, tui) from an existing settings.json. - --check compares the rendered file with template plus overlay, and prints live-only entries instead of dropping them. |
| settings.json; settings.machine.json (untracked, author machine only) | repo root | C1.a, C1.b. Move the author's values into the overlay first: model, tui, the 19 live-only allows including /root/bin at settings.json:185-187, TMPDIR, the C1.b env values, and GIT_AUTO_PUSH if the author wants remote backup. Then re-render settings.json and confirm that --check exits 0. In this PR settings.json stays tracked, as a rendered file. |
| .gitignore; settings.json | repo root | C2.a(3): a human-run final step (REQUEST U1), done after each of the user's homes has run render-settings once. Then git rm --cached settings.json, and ignore /settings.json and /settings.machine.json. A re-rendered local file differs from the tracked one, so a later pull refuses rather than silently deleting it. The release note tells published users to run scripts/bootstrap after pulling. |
| hooks/lib/claude_home.sh; hooks/lib/claude_home.py | claude_home.sh:40; claude_home.py:48-57 | C2.a(4): accept settings.template.json as the home sentinel, because settings.json can be absent before the first render. |
| scripts/bootstrap | :128-141, :166-169, :171-197, :243 | C2.b plus C2.c. - Render when settings.json is absent. When it is present, run render-settings --check and exit non-zero on failure; re-render only with --force. - Create, only if absent: <home>/logs, the TMPDIR root, and ~/.config/claude/protected-runtime.json with schema_version 1 and the 10 REQUIRED_KEYS as empty lists. |
| scripts/doctor | :17-21, :78-140 | Required checks: every hook path in settings.json exists under this home; render-settings --check passes; protected-runtime.json loads with all 10 keys. |
| hooks/pretool-bash-safety.sh; hooks/lib/subagent_restart.py; scripts/prune-orphaned-workflow-bookmarks.sh; scripts/paseo-daemon-ledger.py; scripts/paseo-daemon-timers.py; hooks/lib/checkpoint-core.sh; scripts/install/tmpfiles-claude-scratch.conf; scripts/install/tmp-cleanup-install.sh; commands/restart.md; commands/paseo-daemon.md; .claude/tmp-test-writer-gen-l7.py | bash-safety :8, :13, :79-341, :428, :496, :539, :549-558, :853, :975-977, :1037, :1765-1784, :1825-1827, :1860-1861; subagent_restart :820, :831; prune :23-24, :51-56, :89-90; ledger :133, :1626, :3010; timers :87, :144, :146, :678; checkpoint-core :668-671, :782-785; tmpfiles :60-61; tmp-cleanup :2; restart.md:96; paseo-daemon.md:20 | C1.b plus C3.c. Shipped defaults become empty or derived. The author's values move to the overlay env, written first in the same change: CLAUDE_DEV_CONTAINERS, CLAUDE_DAEMON_RESTART_GRANT_HELPER, CLAUDE_PROTECTED_DAEMON_PREFIX/TARGETS, CLAUDE_RESTART_ACCOUNTS_ROOT, WORKFLOW_PRUNE_ACCOUNTS_DIR, and the paseo accounts and model. The two happy-* hard bans become a configurable list that defaults to the generic recovery-script names. Also: - the prune slug is derived from the realpath of the resolved home; - node is found by PATH lookup; - the paseo registry sits under Path.home(); - the Happy Co-Authored-By trailer is dropped. Delete the stale tmpfiles line and the stray script. |
| hooks/auto-commit.sh; hooks/checkpoint.sh; hooks/posttool-git-checkpoint.sh; hooks/git-hooks/pre-commit; hooks/git-fswatch.sh; hooks/fswatch-manager.sh; hooks/pretool-runcode-watchdog.py; hooks/prompt-workflow.py; hooks/pretool-workflow-gate.py; scripts/canary-verify.sh; scripts/dev-lifecycle.py; scripts/execute-push.py; scripts/score-update.sh; scripts/score-inject.sh; scripts/detect-orphan-*.sh; scripts/detect-dead-functions.sh; scripts/overnight-init.sh; scripts/create-overnight-state.sh | auto-commit.sh:34; posttool-git-checkpoint.sh:61; pre-commit :20-33; runcode-watchdog :29; prompt-workflow.py:1542, :177 (plus the 6 todos sites); workflow-gate :54; canary-verify :18, :35-36; dev-lifecycle :112; score-update :193-220; overnight-init :222; create-overnight-state :874 | C1.c (code). Route the 26 harness-asset lookups of $HOME/.claude through script-relative or claude_home resolution. Change the 32 runtime-state paths, including the 7 todos sites, to ${CLAUDE_CONFIG_DIR:-$HOME/.claude}. |
| hooks/tests/test_runcode_watchdog_aliases.py; tests/test_paseo_usage_read.py; hooks/tests/test_obligation_gate.py; hooks/tests/test_stop_obligation_gate.py; hooks/tests/test_capability_gate.py; tests/test_restart_command.py; tests/test_prompt_workflow_injection_cadence.py; tests/test_paseo_daemon_ledger.py; hooks/tests/test_dual_runtime_lifecycle_e2e.py; tests/test_specialist_yield.py; tests/verify-stop-spec-session-isolation.sh; hooks/tests/test_git_residual_override.py; hooks/tests/test_overnight_gitenv_failclosed.py | watchdog :74-79; paseo_usage_read :148-158; obligation_gate :289; stop_obligation_gate :66; capability_gate :232; restart :718; ledger :3022-3023, :3793, :4278; dual_runtime :23-31; specialist_yield :18, :25 | C1.d. Tests render the template into tmp via render-settings, and derive paths from __file__ and tmp_path, so the human untracking step breaks none of them. Delete the assertion that enforces the drift (test_paseo_usage_read). |
| scripts/verify-claims.sh; .github/workflows/baseline.yml | verify-claims :336-400 (superset rule :337-344); baseline.yml :56-84 comment | C2.d plus F4.d: delete the template-sync section, which retires a rule. With one source, a hook removed from the shipped config is removed by construction. The CI render is now the real config. |
| README.md; ARCHITECTURE.md; PUBLIC-CORE.md; commands/close.md; commands/paseo-daemon.md; skills/ui-beauty-score/README.md; skills/ui-shared/anti-pattern-catalog.yml; skills/ui-shared/rule-map.json | README :58-101, :438-445, :471, :510-517; ARCHITECTURE :20, :28, :356; PUBLIC-CORE :44-75; close.md:32; paseo-daemon.md :514-516; ui-beauty-score README :43-44; anti-pattern-catalog :3; rule-map :17 | C1.e, C2.b and D3.i (docs). Document both install paths per U5, the overlay and the protected-runtime.json file. Correct the portability claims. Replace /root paths in examples with <harness-home>. Remove hand counts. The commands/dev.md example paths (:1723-1749) go with the P8 tutorial deletion. |

**Acceptance tests**

- Non-root user, clone to $HOME/claude-harness, then scripts/bootstrap -> exit 0 and settings.json rendered. scripts/install/render-settings --check -> exit 0. scripts/doctor -> all required checks pass. grep -c '/root/.claude' settings.json -> 0.
- Every hook command in the rendered settings.json points at an existing file (python3 loop over hooks[*][*].hooks[*].command). A UserPromptSubmit payload through every registered UserPromptSubmit hook -> no exit 2. `npm --version` through pretool-bash-safety with the bootstrap-created protected-runtime.json -> allowed.
- Author machine: rendering with the overlay gives a settings.json semantically equal to the pre-change live file, except for the listed intended diffs; doctor --strict handshake passes.
- git grep -nE '/root/[.]claude|/var/lib/claude-accounts|/dev/shm/dev-workspace|happy-(web|daemon)' -- hooks scripts ':!**/tests/**' -> no code defaults (comments excepted)
- bash scripts/verify-claims.sh -> exit 0. PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q on the C1.d test files -> 0 failed, also in a copy where settings.json was deleted.
- After the human-run U1 step: git ls-files settings.json -> empty; .gitignore contains /settings.json and /settings.machine.json; a second home that had re-rendered refuses the pull instead of losing its file.
- git diff --numstat -- hooks scripts schemas -> net code lines <= 0

**Effort.** M-L (about 3 days, plus the human-run untrack step)

**Risk and rollback.** Risk: re-rendering changes the bytes of settings.json, which invalidates capability state (capability_state.py:330), so a fresh doctor --strict handshake is needed. CLI permission accepts written into the generated file are lost at the next render unless moved to the overlay (the renderer prints them). The author's protections go silent if the overlay is not written before the defaults are emptied, so the overlay is written first, in the same change. The untrack step deletes settings.json from any clone where the file equals the tracked version, so it waits until every home has rendered; the release note covers published users. Rollback: revert the commit. Before the untrack step settings.json is still tracked; after it, re-track it from history.

**Decisions (recommended default included)**

- U1: untrack settings.json (against PUBLIC-CORE.md:49-53 'not authorized'), as a human-run step after each of your homes has rendered once. Recommended: yes; it is the only way to one truth.
- U2: public permission posture for the 23 conflicting entries. Recommended: the live deny set, plus 'ask' for curl, wget, docker and manifest edits; the author's allows go to the overlay. Also keep Skill(code-review:*), which blocks self-invocation of the built-in /code-review.
- U3: overlay name and location. Recommended: <harness>/settings.machine.json.
- U4: keep the author-specific features, but move every author value into the overlay so shipped defaults are empty. Recommended: yes.
- U5: which install path the README documents as the full install (clone plus bootstrap) and which as the installer core profile (guardrails only).

## P7 Private tree and green hermetic CI

**Goal.** No private data remains in tracked files, and one privacy engine scans every tracked file. CI collects and passes on every push and weekly. Tests are hermetic and machine-independent. A dev or test-writer producer that leaves a syntax-broken hook or script in the live harness is stopped at its own Stop.

**Why this order.** CI renders the real configuration only after P6, and the hermetic conftest relies on the template render. The harness predicate uses P5's measured write set. Private data has to be removed before the engine's scope widens to every tracked file. The bulk deletion of junk waits for P9, but junk that carries privacy residue or breaks CI goes here.

**Problems.** C3, C4, E1, E4, F2, F3

**Changes**

| File | Locations | Change |
|---|---|---|
| scripts/install/installer.py; hooks/tests/test_checkpoint_pii_gate.sh; README.md; ARCHITECTURE.md; docs/ENFORCEMENT-LEDGER.md | installer.py:1804; pii_gate.sh:185; README :139, :528, :535; ARCHITECTURE :20, :24, :121, :356, :363 | C4.b. - Make the f-string a single line, so it compiles on 3.10 and 3.11. - Build the AKIA placeholder from fragments. - Remove the hand-maintained counts. - Regenerate the ledger rows from the rendered settings with the existing check-enforcement-evidence tooling. |
| conftest.py | :9-13 plus a new collect_ignore list and an autouse fixture | C4.c plus C4.d. - One collect_ignore list, each entry with its reason and problem id. Entries: test_negative_evidence, test_dev_fix, test_dev_todo_accounting, test_dev_todo_codex_native_parse, test_spec_update_command_contracts, test_laneb_checkpoint_resources, test_laneb_integration_gate; plus, by decision, test_bash_write_targets_policy, test_tool_policy_contracts and test_dual_runtime_lifecycle_e2e. - One autouse hermetic fixture: HOME and CLAUDE_CONFIG_DIR point to tmp_path; CLAUDE_PYTHON_BIN=sys.executable; CLAUDE_PROTECTED_RUNTIME_FILE points to a tracked fixture; the harness state dir and the advisory log go under tmp_path. |
| .r05_part1.json; .r05_part2.json; .r05_part3.json; .scratch_subagentstop_ancestor.txt; stage; .claude/scratch_write_report.py; .claude/tmp-test-writer-gen-l7.py; .claude/quarantined-phantom-dev-cycles/ (5 files); tests/reports/edge-case-analysis.json; tests/generated/** (58 skeletons; manifest.json kept per E1.3); hooks/tests/test_ac1_verify.sh; hooks/tests/test_ac3_verify.sh; hooks/tests/test_ac5_verify.sh; hooks/tests/test_ac6_verify.sh; hooks/tests/test_ac9_verify.sh; hooks/tests/test_ac10_verify.sh; hooks/tests/test_final_sweep.sh; hooks/tests/test_laneb_pretool_composition.py; tests/integration-test.sh; tests/test-lock-detection.sh; tests/scripts/validate-posttool-ac-dev-20260524-205811.py; tests/baselines/default-run-failures.json; tests/test_mat_doc10_writer_order_contract.py; tests/test_write_qa_mode.py; tests/ws2_zero_literal_gate.py; tests/score-inject-contract/runtime-verify.sh; tests/fresh-clone-bootstrap-smoke.sh | whole files; fresh-clone-bootstrap-smoke.sh:489 (ws2 gate call); hooks/tests/test_laneb_stop_coordinator.py broker tests :121-211, :368-408 | C4.c, C4.g and C3.c: delete strays, tracked runtime output and broken one-off tests (E1 I1, I2 and I6 items that carry privacy residue or break CI). test_write_qa_mode.py is an abandoned-worktree variant (0/4 pass); the live script is covered by tests/test_subagentstop_e2e_enforce.py:105-134. ws2_zero_literal_gate.py is the third privacy detector. |
| hooks/tests/test_allowlist_consolidation.py; hooks/tests/test_obligation.py; test_pol_generative_sweeps.py; test_overnight_qa_sentinel_bind.py; test_bash_safety_git_clean.py; test_block_branch_pr_worktree.py; test_contract_runtime_version_dispatch.py; hooks/tests/test_artifact_contract_enforce.py; test_commit_multi_repo_plan.py; test_stage_owned_hunks_boundary.py; tests/test_late_repair_route.py; scripts/dev-lifecycle.py; hooks/tests/fixtures/git-clean-ac-matrix.json (new tracked fixture) | allowlist_consolidation :1304; obligation :433-442; pol_generative_sweeps :873-875; overnight_qa_sentinel_bind :198; bash_safety_git_clean :40-75, :126; block_branch_pr_worktree :384; contract_runtime_version_dispatch :232; artifact_contract_enforce :1288-1332, :2045; late_repair_route ac12; dev-lifecycle.py:112 | C4.d plus C4.e. - Use repo-relative paths. - skipif for /opt/paseo plus node, bwrap, rsync and $HOME/.paseo. - Live-transcript tests go behind an opt-in host marker. - Drop the PATH-coupled equality. - Copy the git-clean AC matrix into a tracked fixture, taken from the maintainer host. - Build reports in tmp_path. - Delete the cycle-local assertions. |
| hooks/tests/test_gitignore_preflight_close_contract.py; hooks/tests/test_artifact_contract_enforce.py; tests/test_completeness_channel_invariant.py; tests/test_refusal_record_consumers.py; hooks/tests/test_push_gate_ancestor_cross_session.sh; hooks/tests/test_attribution_journal.py; hooks/pretool-overnight-hook-guard.py; scripts/aggregate-dev-report.py | preflight sandbox :82-93; attribution :484-502; push_gate START_ANCHOR vs hooks/push.sh:212 | C4.f. - The preflight sandbox copies hooks/lib/. - Update 4 qa-report fixtures to the projected schema. - Drop the source-count and plan-row pins. - Fix the anchor. - Make the tmpfs probe monkeypatchable. Two real defects surfaced by these tests are fixed: the overnight guard denies, instead of failing open, writes into the main root from isolated or unregistered sessions; and the aggregator's main exits non-zero on unattributed bytes. |
| .github/workflows/baseline.yml | triggers :10-19; test and claims steps :123-135, :151-161, :189-207 | F2.b plus C4.g. Add schedule (cron '17 3 * * 1') and workflow_dispatch. Add non-root shell steps for test_checkpoint_pii_gate.sh, test_push_no_upstream_guard.sh, test_push_sentinel_abort.sh, the fixed test_push_gate_ancestor_cross_session.sh, and tests/fresh-clone-bootstrap-smoke.sh minus assertion 11. No tests are ported to pytest. |
| docs/reference/MORNING-20260907.md; docs/reference/abandoned-cycles-20260905.md; docs/reference/harness-defects-20260906-controller.md; docs/reference/harness-fix-status-20260905.md; docs/reference/dev-command-20261003-020648-takeover-record.md; docs/reference/quarantine-record-dev-20260915-020044.md; docs/reference/restart-detector-quota-text-match-false-positive-20260915.md; docs/reference/paseo-daemon-teachings-20260910.md; docs/reference/tmpfs-persistent-backups-20261005.md; NESTED-REPO.md; commands/restart.md; hooks/lib/interruption_signals.py; hooks/lib/subagent_restart.py; tests/test_restart_command.py | whole files; citations restart.md:81, interruption_signals.py:65, subagent_restart.py:111, test_restart_command.py:979 | C3.a, C3.d and E4.a (private): delete the private and incident records, including the verbatim chat transcript (paseo-daemon-teachings). The restart-detector doc is deleted, not redacted: it is an E1 I7 history doc, and its rule is already restated at restart.md:76-82. Its 4 citations are trimmed to one line each. Move NESTED-REPO.md out of the repo and drop its references. |
| docs/reference/harness-issues-backlog.md; docs/reference/close-commit-zero-failure-mechanism-20260928.md; hooks/tests/test_git_prefix_enumeration.py; hooks/tests/test_residual_false_positives.py; hooks/pretool-git-privilege-guard.py; hooks/userprompt-usage-snapshot.py; hooks/session-promote-hook.sh; hooks/pretool-gitignore-preflight.py; scripts/graphify-enrich.py; scripts/seal-attribution-journal.py; commands/dev-overnight.md; commands/paseo-daemon.md | backlog rows :42-248 per C3.a; mechanism :4; prefix_enumeration :348, :354; residual :125; privilege-guard :1401; usage-snapshot :15; dev-overnight.md:1085; paseo-daemon.md:516; other comment lines per C3.c | Redact the files that are kept: neutral paths in fixtures, reworded comments. |
| hooks/tests/test_git_residual_override.py; tests/test_paseo_daemon_ledger.py; tests/test_paseo_usage_read.py; tests/test_paseo_daemon_timers.py; tests/test_restart_command.py; tests/fixtures/paseo-usage-envelope-20260828.json; hooks/tests/test_userprompt_usage_snapshot.py; hooks/tests/test_runtime_guard.py; hooks/tests/test_unit_anchor.py | residual_override :134, :195, :204; timers :62; restart :839-854, :1044; unit_anchor :85-108 | C3.b plus C3.c: synthetic fixtures (maintainer@example.invalid, acct-a/acct-b/acct-c, synthetic unit names, a neutral remote). |
| scripts/check-public-core.sh; scripts/detect-hardcoded-paths.sh; hooks/lib/checkpoint-core.sh; PUBLIC-CORE.md; tests/test_public_core_residue_gate.py; policies/public-core-residue-allowlist.v1.json | check-public-core :54, :93, :111, :213, :366-369, :543-546; checkpoint-core :95; PUBLIC-CORE :66-100, :144, :159-162; residue tests :302, :506 | C3.e: one engine. - Generic rules only: /root/..., /home/<u>, /Users/<U> and an e-mail regex. - Private literals come from an untracked maintainer file named by env (a CI secret for the published gate); without it, the generic rules still apply. - Scan every tracked file. - Delete scripts/detect-hardcoded-paths.sh; ws2_zero_literal_gate.py is deleted above. checkpoint-core.sh:95 calls the engine. - Redact PUBLIC-CORE and correct its 'advisory only' text. - Tests use synthetic markers. Regenerate the allowlist after the redactions. Three detectors become one. |
| hooks/subagentstop-artifact-contract-enforce.py | one predicate in the G2 obligation branch, after the P5 written-set computation | F3.a, minimal: for dev and test-writer producers only, run py_compile on each .py file, and bash -n on each .sh file, in the producer's written set that resolves under claude_home.resolve()/hooks or /scripts. The predicate keys on the real path of the harness home, not on any project marker. A failure goes back to the producer through G2's existing bounded path. No tests, privacy scan or canary run inside the hook; CI covers those. Nothing runs at the changelog-analyst or /commit. |

**Acceptance tests**

- bash scripts/check-public-core.sh -> 0 FAIL over every tracked file, both with the private-marker file present (CLAUDE_PRIVATE_MARKERS_FILE=<untracked path>) and without it. If U1 was declined, settings.json is the one listed exception.
- CI-like sandbox (uid 1001, env -i, empty HOME, the existing py3.12 hashed lockfile, source mounted read-only): `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q` from the repo root -> collection succeeds, 0 failed, 0 errors. Repeat as root -> same result.
- conftest.py's collect_ignore list has at most 10 entries, each carrying a problem id
- python3.10 -m py_compile scripts/install/installer.py and python3.11 likewise -> ok; the baseline.yml secret-scan grep -> 0 hits; bash scripts/verify-claims.sh -> exit 0
- baseline.yml contains `schedule:` with cron '17 3 * * 1' and `workflow_dispatch:`; the live shell tests and fresh-clone-bootstrap-smoke run as steps; a workflow_dispatch run on the published repo is green on all three matrix legs
- G2 harness predicate with STOPGATE=block:
- a dev that edits <harness>/hooks/x.py into a syntax error -> stop blocked with the py_compile output
- the same edit in a product repo -> predicate not run
- the predicate adds under 1 s to a stop with 5 changed hook files
- git diff --numstat -- hooks scripts schemas -> net code lines < 0

**Effort.** L (about 3.5 days; mostly mechanical)

**Risk and rollback.** Risk: the autouse HOME override can expose tests that silently relied on the real home, so the suite is run as root and as non-root. Turning on the 738 previously skipped git-clean cases may reveal real bash-safety regressions; that is intended, but may need follow-up. The quarantine list must stay short, with a problem id per entry. Rollback: revert; the deleted private files stay recoverable from git history.

**Decisions (recommended default included)**

- C3.b: accept that the e-mail address and account names remain in published git history, or rewrite history with filter-repo and a force-push (which breaks every clone and fork). Recommended: accept; do not rewrite.
- C3.d: delete docs/reference/paseo-daemon-teachings-20260910.md, a transcript of your own chat. Recommended: yes.
- C3.a/E4: redact harness-issues-backlog.md now, and decide its fate in P9. Recommended: yes.
- C4.c: for hooks/tests/test_bash_write_targets_policy.py, implement assignment resolution in the security hook or delete the test. For hooks/tests/test_tool_policy_contracts.py, add the rules to policies/tool-policy.v1.json or delete the test. Recommended: delete both tests and record the gap.
- C4.d: move the 31 Codex tests in test_dual_runtime_lifecycle_e2e.py to the Codex harness repo (the 4 Claude tests fold into existing files), or keep them quarantined.
- C4.g: scripts/install/tests/installer-acceptance.py (fix and wire, or delete); tests/scripts/validate-*.py (keep as manual tools, or wire); tests/score-inject-contract/test-inject-branches.sh (fix or delete).
- U-F2b: weekly scheduled CI. Recommended: yes.

## P8 One producer per fact; one prose pass

**Goal.** Each fact gets one producer: spec_path, doc-sync output, the /do consent check, the task-id normaliser and the agent roster, the git option table, and each shared prompt block (one include file). Consumers with no producer are repaired or removed. In a single pass over every prompt file, prose in README, ARCHITECTURE, commands, agents and docstrings is made to match what the hooks do, and provenance stamps and tutorials are removed. CLAUDE.md changes are one user decision.

**Why this order.** Prose must describe final code, so this comes after P1-P5. The refactors of security-hook inputs need the green suite from P7. doc-sync must be update-only before P9 deletes the generated stubs, or they grow back. Doing every prose edit here means each prompt file gets one review.

**Problems.** D1, D2, D3, D4, E2, E3, F3

**Changes**

| File | Locations | Change |
|---|---|---|
| hooks/prompt-workflow.py; commands/dev.md; commands/dev-command.md; commands/dev-overnight.md; commands/spec.md; scripts/create-overnight-state.sh | _ordinary_dev_start :1840-1920; overnight path :1953-1955; dev.md :125-151; dev-command.md :89-95; create-overnight-state.sh :500-517; spec.md :483-489, :519 | D2.d. prompt-workflow becomes the single producer of spec_path. From the session transcript it takes the last Write/Edit to docs/dev/specs/*.md (excluding INDEX and README), and emits 'Spec: <abs>' or 'Spec: none' in the start output stored for replay. Delete the three mtime rules. /spec prints '/dev --spec <abs>' for the cross-session case. |
| hooks/doc_sync/regen_index.py; hooks/doc_sync/regen_readme.py; hooks/doc_sync/claude.py; hooks/doc_sync/patch.py; hooks/doc_sync/main.py; commands/test.md | regen_index :221-236; regen_readme :194-216; claude.py :18-30; patch.py :135, :154; main.py :35-41, :122-134; test.md :41, :494 | D1.c = E2.a. doc-sync becomes update-only: - skip when the target is absent; - never create or prepend CLAUDE.md; - drop the Last-updated rewrite of the user's CLAUDE.md; - delete _maybe_regen_global; - add docs/dev/ to EXCLUDED_PATTERNS. /test stops copying INDEX.md into product repos. |
| hooks/prompt-workflow.py; scripts/mint-git-blessed-token.sh | prompt-workflow.py :330-335; mint header :7-8 | D2.f: todo scripts are resolved from the harness root only, so product-repo code is never executed on prompt submit. Correct the mint header to say manual-only. |
| settings.template.json | Skill denies :244-271; allows :140-145, :164, :168, :173-177 | D2.a plus D2.b. - Delete the 16 Skill() denies that name nothing (code-review kept per U2). - Delete the 2 allows for missing scripts. - Rewrite the repo-relative allows for live scripts to {{CLAUDE_HOME}}/scripts/<x>. Allows for dead targets go in P9 together with their files. |
| agents/ba.md; agents/qa.md; agents/ui-specialist.md; agents/cleanliness-inspector.md; agents/spec.md; skills/ui-axe-injector/SKILL.md; commands/dev-command.md; commands/dev-overnight.md; commands/paseo-daemon.md; commands/commit.md; commands/dev.md; commands/test.md; scripts/aggregate-dev-report.py; hooks/git-fswatch@.service; hooks/fswatch-manager.sh; scripts/spec-verify/spec_verify_parsers.py | ba.md:649; qa.md :106, :1197; ui-specialist :16, :269; cleanliness-inspector :173; spec.md :55, :266, :448; SKILL.md:95; dev-command.md:69; dev-overnight.md :122, :1892; paseo-daemon :10-12, :257; commit.md:900; dev.md:1040; aggregate-dev-report.py:2364; service :3; fswatch-manager :261; spec_verify_parsers :3 | D2.c, D2.e and D1.f. - Inline the trigger-word list into ba.md and qa.md, the prompts that own the rule; today it points at a gitignored docs/dev ticket. - Delete references to never-built files and private clauses. - Correct the code-side paths. - Remove the false /test claim. - Resolve git-edge-case-analyst per U5, and the paseo blueprint and design-handoff template per U6/U7. |
| hooks/lib/allowlist.py; pretool-git-privilege-guard.py; pretool-bash-safety.sh; pretool-block-background-tasks.py; pretool-aggregate-check.py; pretool-block-branch-pr-worktree.py; pretool-block-enterworktree.sh; pretool-do-block-subagents.py; pretool-orchestrator-gate.py; pretool-read-size-guard.py; pretool-subagent-enforce.py; pretool-write-guard.sh; hooks/prompt-workflow.py; hooks/stop-overnight-timelock.py; commands/do.md | consent readers: privilege-guard :274 (literal /tmp), bash-safety :871-873, :2713, :2755, block-background-tasks :153, aggregate-check :684-686, branch-pr-worktree :589, enterworktree.sh :59-61, do-block-subagents :92, orchestrator-gate :77, read-size-guard :27, subagent-enforce :52, write-guard.sh :59-61; fallback stubs prompt-workflow.py:41-45, stop-overnight-timelock.py:37-40; do.md:57-59 | D3.c, minimal. Add allowlist.has_do_consent(payload): the state-dir resolver path, content == 'true', and a subagent check. Replace the 13 readers listed, which today use 3 semantics and 2 locations; the 4 shell hooks call it via `python3 -m lib.allowlist consent`. Delete the two fallback stubs that drop CLAUDE_STATE_DIR. do.md:57-59 reads the resolver path instead of literal /tmp. The grant and sentinel literals that already agree with their writers are left alone. |
| hooks/lib/obligation.py; hooks/pretool-cp-checkin.py; scripts/spec-check.py; hooks/prompt-workflow.py; hooks/pretool-obligation-gate.py; commands/dev.md; commands/dev-command.md | obligation ROLES/PRODUCER_ROLES (P1); cp-checkin :62; spec-check :91; prompt-workflow :1516; dev.md:202; dev-command.md:146 | D3.f: the agent roster is the ROLES constant in hooks/lib/obligation.py, imported by the other three. The prose fallback loops become 're-run the command'. |
| hooks/lib/git_command_classifier.py; hooks/lib/git_clean_guard.py; hooks/lib/runtime_guard/git_cmds.py; hooks/pretool-overnight-hook-guard.py; hooks/pretool-git-privilege-guard.py; hooks/lib/allowlist.py | classifier :62, :361, :577, :589; clean_guard :134; git_cmds :42; overnight guard :1125; privilege-guard :170-204, :2398; allowlist :455 | D3.a/D3.b, minimal. - classify_git_command and iter_git_invocations normalise their own input, so no caller can pass raw text. This fixes the privilege guard false-blocking a harmless 'echo git commit'. - One corrected git global-option table, imported by the four sites; GIT_GLOBAL_OPTION_RE is built from it. - Correct the allowlist grammar comment. |
| templates/prompt-includes/ (6 new include files); agents/*.md (23 files); commands/dev.md; commands/dev-command.md; commands/dev-overnight.md; commands/close.md; commands/commit.md; commands/clean.md; commands/spec.md; commands/redev.md; scripts/score-inject.sh | codex blocks (agents/qa.md:1317-1377 plus 11 copies); checkpoint contract and cp-state SOP (agents/ba.md:1335-1374 plus 16); anti-give-up (agents/qa.md:28-56 plus 5); overnight spec (agents/qa.md:1886-1930 plus 3); intake (agents/ba.md:1205-1251, agents/pm.md:1134-1190); score echo (score-inject.sh:51); charter (agents/ba.md:8-21 plus 17) | D3.g with E3.c's mechanism, not a render script. - Each shared family moves to one include file in a directory Claude Code does not load. The file is read only when its condition holds (codex_required, SPEC_ID set, overnight mode, and so on). - Each agent keeps a 1-2 line imperative pointer that states the condition. - The charter becomes 2 identical inline lines. - dev-command.md points at the same includes. Wording is unchanged apart from the D4 corrections. |
| commands/dev.md; commands/close.md; commands/commit.md; commands/dev-command.md; commands/dev-overnight.md; commands/paseo-daemon.md; agents/ba.md; agents/qa.md; agents/style-inspector.md; agents/dev.md; agents/changelog-analyst.md; agents/pm.md; agents/spec.md; agents/cleanliness-inspector.md; agents/merge-analyst.md; agents/prompt-inspector.md; agents/rule-inspector.md; agents/ui-specialist.md; agents/architect.md; agents/product-owner.md; agents/test-writer.md; agents/user.md; scripts/step7-spec-update.py | stamp lines per E3.c, e.g. dev.md :424, :481, :546, :555, :806-844, :1006, :1091-1098, :1282, :1345-1399; close.md :55, :102, :388, :531-567, :624-674, :724-870, :933, :1015; commit.md :22, :41, :279, :402, :431, :448, :866, :947, :1035; tutorials dev.md :1460-1698, :1699-1750; trace contract commit.md :866-911 | E3.b plus E3.c, in the same pass: - Remove the 169 provenance stamps (task ids, dated notes, dated-doc refs, commit SHAs), keeping the 20 citations of the binding design. - Delete the 239 tutorial lines. - Replace dev.md's false 'exits 2' purity section with the 3-line WHAT-not-HOW rule. - Move the test-only trace contract into the script's docstring. No refusal hook is added; the P9 prompt_bytes ratchet caps regrowth. |
| commands/clean.md; commands/dev.md; commands/dev-command.md; commands/dev-overnight.md; commands/redev.md; commands/do.md; commands/close.md; commands/allow.md; scripts/todo/dev.py; docs/reference/checkpoint-mechanism.md; agents/graphify.md | clean.md :45, :223; dev.md :235, :304, :1106, :1747; dev-command.md:127; redev.md:9; do.md:57; close.md:156; dev-overnight.md :1775, :1801; allow.md:6; todo/dev.py:20 | D4.c. - Every dispatch template carries run_in_background:false; in clean.md, true becomes false and parallelism stays as N synchronous calls. - Correct the purity, cp-enforce, code-block and layer-escalation claims. - Align the step models. Step 15 stops self-editing settings. - Drop the /commit -m and --force text. Correct the counts. - Move the /clean output paths per decision. |
| agents/dev.md; agents/qa.md; agents/cleaner.md; agents/style-inspector.md; agents/prompt-inspector.md | agents/dev.md :9-10, :497; cleaner.md:62; style-inspector.md:600 | D4.d: reword the charter's routing statuses to the existing v2 enums. No schema or TERMINAL_VOCABULARY change, so P1-P3 are not reopened. Baseline checks are reported in the summary. Delete dev.md's self-contradictory Authority Chain clause. Fix the cleaner's checkpoint check and blocked steps, and the inspectors' output paths. |
| README.md; ARCHITECTURE.md | README :243, :247, :250, :326, :564-598; ARCHITECTURE :118-121, :144-191, :166, :301 | D4.b plus D3.i. - Correct the enforcement rows to match the code, including the /do commit/push bypass, which is kept (UD5) and documented as it is (README :247). - Correct the stop-cleanup-allowlist claim (ARCHITECTURE :166): it runs as a coordinator phase. - Delete the hook tables and the sequential-ordering premise. Remove the counts. |
| hooks/pretool-quality-gate.py; hooks/pretool-bulk-commit-detector.py; hooks/posttool-command-frontmatter-validate.py; hooks/stop-do-report-gate.py; hooks/lib/allowlist.py; hooks/posttool-allowlist-consume.py; hooks/posttool-codex-skill-ledger.py; hooks/pretool-subagent-code-block.py; hooks/pretool-tool-policy.py; hooks/pretool-orchestrator-gate.py | quality-gate :19, :346; bulk-commit :24; frontmatter :11; allowlist :3, :20, :455; consume :24; codex-ledger :12; code-block :2; tool-policy :350; orchestrator-gate :166, :261 | D4.e: docstrings and messages match the code. The orchestrator gate's permanent-block message stops offering /do, and its 'runs FIRST' comment is dropped. No behaviour change. |
| CLAUDE.md (user-owned; applied only under decision UD-CM) | :4, :30, :49, :57-62, :86, :95, :98, :102, :117, :125, and Hook Discipline #2 | D4.a, D4.g, F3.d. A proposed diff, attached to the PR, that brings each line in line with the hooks or with the side chosen in UD2/UD6/UD7/UD8: - :102: stop-cleanup-allowlist.sh runs as a coordinator phase. - :98: the /do commit/push bypass, which is kept. - :117: the deep-search line, per U2. - :4: the dated note. - Hook Discipline #2, per U-F3c. The human applies or approves it; no agent edits CLAUDE.md on its own. |

**Acceptance tests**

- Spec hand-off: a transcript where /spec writes docs/dev/specs/foo.md, then /dev -> the UserPromptSubmit output contains 'Spec: <abs>/docs/dev/specs/foo.md'. No spec write -> 'Spec: none'. A write to docs/dev/specs/INDEX.md is ignored.
- doc-sync: a Write of src/foo.py in a fresh repo -> no CLAUDE.md, INDEX.md or README.md is created. An existing marked INDEX.md still updates. The user's CLAUDE.md is byte-identical after a session.
- A product repo with scripts/todo/dev.py that prints a marker -> the /dev UserPromptSubmit output does not contain the marker.
- With CLAUDE_STATE_DIR set and /do consent granted -> the orchestrator gate, the branch firewall and git-privilege-guard all honour /do (D-cluster cases T1-T3 now consistent). git grep -n 'orchestrator-consent' -- hooks -> only allowlist.py, the writer and the clearers.
- A subagent Bash `echo "git commit"` -> allowed by both bash-safety and git-privilege-guard. The differential corpus over bash-safety, the branch firewall and the privilege guard is identical before and after, except for this intended fix.
- Every Agent dispatch template in commands/*.md contains run_in_background: false; grep -n 'run_in_background: true' commands -> 0
- ls templates/prompt-includes | wc -l -> 6; grep for each include's first line in agents/ and commands/ -> pointer lines only
- git grep -nE '(dev-)?20[0-9]{6}-[0-9]{6}' -- commands agents -> only citations of the binding design doc
- In settings.template.json, every allow rule that names a script points at an existing file, and every Skill() deny names an existing command, skill or built-in (python3 loop)
- PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -> 0 failed, with the prompt-wording tests updated in the same commits
- git diff --numstat -- hooks scripts schemas -> net code lines < 0

**Effort.** L (about 3.5 days; prose S per file, D3.c M)

**Risk and rollback.** Risk: input normalisation in the git classifier changes allow/deny outcomes of security hooks; this is mitigated by the differential corpus and the green suite from P7. Unifying the existence-only consent readers to content=='true' can newly deny a /do whose flag file is empty (the writer always writes 'true'). Prompt edits break wording tests unless they are updated together. Rollback: revert. The change is split into commits: spec/doc-sync, settings rules, D3 refactors, prompt includes, prose and stamps. The CLAUDE.md diff is applied separately by the human.

**Decisions (recommended default included)**

- UD-CM: apply the attached CLAUDE.md diff (lines :4, :30, :49, :57-62, :86, :95, :98, :102, :117, :125 and Hook Discipline #2), which corrects each line to the hook behaviour or to your chosen side of UD2/UD6/UD7/UD8/U-F3c. Recommended: apply.
- UD1 cp-enforce: arm CP_ENFORCE_MODE=block, or rewrite the 18 claims as advisory. Recommended: rewrite now.
- UD3 honest terminal: keep CLAUDE.md #5 and design C5 (recommended), or adopt teachings:103.
- UD4 codex default: opt-in (recommended; the current agent blocks) or on for every command.
- UD5: the /do bypass that lets the main agent git commit/push (git-privilege-guard :2501). Recommended: keep it (no-retirement hold) and document it in README and CLAUDE.md.
- UD6 agent branch delete/rename allowed or blocked; UD7 /push on a dirty tree allowed or blocked; UD8 large Reads chunked or delegate-only. Recommended: document the current code behaviour for all three.
- U-F3c: Hook Discipline #2 wording for the live-editing status quo. Recommended: hook edits are allowed only inside a /dev cycle on the harness (validated at Stop by the P7 predicate), and never to escape a block.
- U2/U6/U7 dangling references: delete the CLAUDE.md:117 deep-search line (recommended); publish or remove the paseo blueprint and the dev-command tutorial; ship design-handoff.example.json or drop its references.
- U5: wire git-edge-case-analyst into /test, or stop agents/spec.md offering it a view. Recommended: stop offering it.
- /clean outputs: move them to the existing docs/dev/<role>- prefixes (prose only, recommended), or add docs/clean/ to the five roles' policy prefixes.
- D-D1e: the 13 registered hooks whose only output is exit-0 stderr (D1.e list, e.g. posttool-git-warn.sh, pretool-quality-gate.py) stay registered under the hold, with their 'enforcement' claims corrected; or unregister them. Recommended: keep and correct the prose.

## P9 Clean tree, product repos unpolluted, recoverable removal, size ratchet

**Goal.** Pure junk is gone, while feature-tied files are kept or left to decisions. Product repos are no longer polluted by runtime files, and the .gitignore is minimal. Dated records are retired, with their rationale inlined. Agents can remove tracked files recoverably with git rm without -f, and cleaner and /clean use it. CI enforces a size budget that only goes down. BA can propose retiring a rule, and the human decides.

**Why this order.** Last. The deletions need green CI (P7), and they need update-only doc-sync plus a deduplicated tree (P8) so nothing grows back. The size budget is measured right after this cleanup.

**Problems.** E1, E2, E4, D1, D2, F1, F2, F4

**Changes**

| File | Locations | Change |
|---|---|---|
| I3: hooks/.env.example, hooks/QUICKSTART.md, hooks/README-TODO-INJECTION.md, hooks/audit-slashcommand.sh, hooks/git-hooks/{INDEX.md,README.md,post-commit-auto-push}, hooks/hook-todo-injection.py, hooks/install-auto-sync.sh, hooks/install-git-hooks.sh, hooks/install-protection-all.sh, hooks/install.sh, hooks/post-commit-warn.sh, hooks/post_tool_use.sh, hooks/pre_slashcommand_validate.sh, hooks/pre_tool_use_safety.sh, hooks/pretool-baseline-snapshot-preflight.py, hooks/pretool-overwrite-guard.py, hooks/project-settings-template.json, hooks/session_start.sh, hooks/sessionstart-artifact-census.py. I4: scripts/todo/{code-review,deep-search,doc-gen,explain-code,file-analyze,optimize,playwright-helper,quick-prototype,refactor,reflect-search,research-deep,security-check,site-navigate}.py. I8: skills/.archive/frontend-design/ (4 files). E1.3: hooks/protection-status.sh, hooks/tests/fixtures/overwrite_corpus.json, hooks/tests/test_overwrite_guard.py, hooks/tests/test_sessionstart_artifact_census.py, scripts/regen-index-dirs.py, commands/{INDEX,README}.md, agents/{INDEX,README}.md. I1 rest: .claude/INDEX.md, .claude/README.md, hooks/tests/fixtures/pol_installed_program_allow_set.json | whole files (none of them is registered in settings) | E1.a and D1.a: never-run hooks, dead installers, checklists of deleted commands, the archived skill, and generated stubs inside the directories Claude Code loads as commands and agents. Companion edits: the start-fswatch-all.sh:90 echo; the scripts/todo/do.py:4 docstring; the aggregate-dev-report.py:1400 comment. |
| I5 (only if U3 confirms): docs/reference/mat-doc10-writer-order.v2.json; hooks/lib/{agent_temp_targets,checkpoint_resources,negative_evidence}.py; hooks/lib/runtime_guard/__main__.py; schemas/{negative-evidence,owned-edits-ledger,repair-map}.v1.json; scripts/{adjudicate-attribution-staging.py, analyze-folder-history.sh, attribution-aggregate-view.py, capture-dispatch-metadata.py, check-security-hook-drift.sh, check-todo-accounting.py, cleanup-close-force-sentinel.sh, close-commit-repair-orchestrate.py, dev-fix.py, gen-test-baseline.py, generate-repair-map.py, laneb-integration-gate.py, lifecycle-baseline-import.sh, negative-evidence.py, session-resources.py, spec-update-contract.py, verify-claims-extended.sh}; scripts/lib/{attribution_aggregate_view,dispatch_metadata}.py. I6 rest: hooks/tests/{test_baseline_snapshot_preflight.py, test_laneb_agent_temp_targets.py, test_laneb_checkpoint_resources.py, test_laneb_integration_gate.py, test_regen_index_dirs_script.py}; tests/fixtures/dev-todo-canonical-before.v1.json; tests/fixtures/late_repair_golden/spec-20260907-115508-lawful-commit-channel.pre-r4.md; tests/{test_changelog_analyst_declaration_categories.py, test_changelog_analyst_files_landed_whole_toctou.py, test_dev_fix.py, test_dev_todo_accounting.py, test_generate_repair_map.py, test_negative_evidence.py, test_no_artificial_lifecycle_ceremony.py, test_repair_map_call_site_coverage.py, test_repair_orchestrate.py, test_spec_update_command_contracts.py} | whole files. Explicitly KEPT: hooks/lib/session_resources.py (imported at module top by stop-workflow-coordinator.py:37), scripts/commit.sh (held), the 11 feature-tied hooks and 4 feature-tied scripts (E1 class F) | D1.b plus the abandoned-cycle code (LANE-B, negative-evidence, dev-fix, repair-map, spec-update-contract, attribution CLIs) and its tests. Companion edits in the same change: - the settings.template.json dead-target allows (:122-124, :141, :175, :180) and the matching settings.json rows (D2.b); - schemas/registry.json:16; schemas/dev-report.v2.json:46 wording; - tests/test_late_repair_route.py:1191-1195; hooks/tests/test_attribution_adjudicator.py:447, :472, :584; tests/score-lifecycle-contract/test-lifecycle-cas.sh:23; - conftest.py: drop the quarantine entries whose code is deleted; - tests/TESTING.md rows; NOTICE (adds axe-core MPL-2.0); - .gitignore:143-155 collapsed to tests/generated/. |
| scripts/graphify-enrich.py | :665 | E1.b: validate the written graphify-focused-subgraph against its schema at the producer, instead of deleting the schema. |
| hooks/session-gitignore-propagate.sh; .claude/.awesome-claude-harness; hooks/sessionend-scratch-sweep.sh | propagate :21-22, :29-32; sweep :1-18 | E2.b. Remove the marker gate. Idempotently append the harness runtime patterns to $(git -C "$PROJECT_DIR" rev-parse --git-path info/exclude), never to the tracked .gitignore. The patterns: .claude/workflow-*.json, workflow-locks/, workflow-history/, dev-start-replays/, dev-registry/, specs/*/cp-state-*.json, overnight-*.json, agent-bookmark-*.json, state/, cache/, locks/, logs/, scratch/, session-resources/, overnight-fresh-clones/, overnight-git-bin/, overnight-git-policy-bin/, worktrees/, paseo-daemon/, docs/dev/, docs/codex/, tests/generated/, graphify-out/, .playwright-mcp/. The SessionEnd sweep removes this session's own .claude/workflow-<sid>.json. |
| scripts/seal-attribution-journal.py; settings.template.json; .gitignore | seal :64-71; env; .gitignore :19, :49, :64, :66, :100-101, :140, :145-160, :165-167, :173, :176-184, :192-194 | E2.c. - The seal store defaults to the journal's own ignored state/ parent. - Add PYTHONDONTWRITEBYTECODE=1. - Delete the 11 dead or duplicate rules, anchor the 5 unanchored rules and *.png, and drop the doc-sync guard rules. |
| the remaining docs/reference HISTORY records: attribution-journal-consumer-cutover-20261004, attribution-journal-cutover-flip-plan-20261003, bash-safety-verb-anchoring-20261008, claim-verification-methodology-20260925, codex-sandbox-verification, commit-dryrun-close-gate-ruling, controller-error-taxonomy-20260924, infeasibility-without-execution-20261006, lane-pol-catchup-plan-20260808-035658-lanepolcatchup, master-origin-reconciliation-gap-20261005, monolith-split-plan, overnight-cycle-20260809-013317-shared-file-attribution-20260914, overnight-worktree-20260810-test-gaps-20261005, overnight-worktree-test-gaps-20261005, overwrite-prohibition, paseo-daemon-caller-id-rollout-20261004, paseo-daemon-concurrent-staging-triple-repro-20260904-181435-20260914, paseo-daemon-shared-file-attribution-20260913, recoverable-discard-register-20261005, slashcommand-quick-reference, test-suite-overhaul-plan, workspace-disposition-criteria-20261005, worktree-685c203b-remaining-18-disposition-20261005 (.md); RATIONALE: core-context-refactor-plan, push-gate-reconciliation-decision, attribution-journal-phase0-facility; citing comments in hooks/lib/runtime_guard/*.py, hooks/pretool-bash-safety.sh, hooks/posttool-push-gate-token-verify.py, hooks/lib/attribution_journal.py, commands/commit.md, conftest.py, pytest.ini, tests/TESTING.md, scripts/lib/attribution_adjudicator.py, scripts/resolve-commit-repos.py, policies/public-core-residue-allowlist.v1.json | runtime_guard (20 lines); bash-safety :58, :232, :1171, :1251; push-gate :18; attribution_journal :51, :57; commit.md:235; conftest.py:3; pytest.ini:8; TESTING.md:5; adjudicator :4-5; resolve-commit-repos :532 | E4.a. - Delete the history docs and trim the comments that cite them. - Inline the 3 rationale docs as docstrings of 15 lines or fewer, then delete them. - Each evidence or open-defect doc is deleted once the phase that closed it has landed: close-commit-failure-inventory (P4), subagentstop-payload-s0 and qa-status-gate-gap (P5), do-report-ledger (P3), workflow-bookmark-orphans (here). - The binding design doc stays under its name. |
| agents/ba.md; docs/reference/harness-issues-backlog.md | ba.md :18, :917; backlog :3, :27 | E4.b plus F4.c. - When the backlog exists, BA greps it for the affected file and hook names instead of reading all 697 KB. - The record-only rule binds /dev sessions, and its expired worktree scope is dropped. - The harness /spec session is named as the backlog's consumer, and an entry is deleted when its spec lands. - The docs_reference_bytes budget caps growth. |
| hooks/lib/bash_execution_boundary.py; hooks/pretool-bash-safety.sh; hooks/tests/test_bash_safety_context_rules.py; hooks/tests/test_bash_execution_boundary.py; hooks/tests/fixtures/pol_iteration5_qa_matrix.v1.json | boundary :1447-1450, :2741-2744; bash-safety :757-841, :864-878; context_rules :185, :206-209; matrix rows covering git rm (subset of POL-I5-QA-0256/0316/0318/0320/0321/0322) | F1.a. git rm without -f, or with -n, becomes PROVEN_SAFE_REMOVAL: git itself refuses to remove anything that differs from HEAD, and the file stays recoverable from history. Forced git rm (-f, -rf, -fr, --force, wrapped forms) stays forbidden. Plain rm/unlink is unchanged; there is no snapshot-then-rm path. Flip only the git-rm assertions and matrix rows, and add golden cases for the forced and wrapped forms. This relaxes one rule and adds none. |
| agents/cleaner.md; commands/clean.md | cleaner :72-73, :161; clean.md :2, :70, :94-95 | F1.c, producers only: the cleaner and /clean delete tracked byproducts with git rm (without -f), each printed as 'DISCARDED <path> - recover: git checkout <sha>^ -- <path>'. The changelog-analyst and /commit are not changed. |
| scripts/size-ratchet.py (new, about 60 lines, stdlib); policies/size-budget.v1.json (new); .github/workflows/baseline.yml | a new step before 'Run tests' (:123) | F2.a, in CI only. - Six metrics: tracked_files, tracked_lines (excluding tests/generated), hooks_lines, registered_hooks (template), prompt_bytes, docs_reference_bytes. - --check reads the budget from the merge base (git show <base>:policies/size-budget.v1.json), so a change cannot raise its own limit; a raise lands as its own human commit. - Values are measured right after this phase's cleanup and only go down. Nothing runs in a hook. |
| agents/ba.md | :19-20, :38-51, :1090-1098, :1199 | F4.b. The verdict becomes patch / redesign / retire, with retire evaluated first for a rule that has 2 or more false-positive or deadlock backlog entries. A retire verdict is only a proposal: it lists the git rm targets and registrations, and goes to the human as a decision. No agent removes or authorises the removal of a rule, and the >50-line clarification still applies. |

**Acceptance tests**

- For every deleted path, `git grep -n <basename> -- commands agents hooks scripts settings.template.json .github` -> 0 (scripted loop); git ls-files | wc -l -> about 690
- python3 -c 'import sys; sys.path.insert(0,"hooks"); import importlib; importlib.import_module("lib.session_resources")' -> ok; stop-workflow-coordinator.py runs a Stop payload -> exit 0
- PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -> 0 failed; the CI workflow is green
- Clean product repo: run /dev, /dev-command, /redev, /spec, /do, /close, /commit and /test prompts through UserPromptSubmit -> `git status --porcelain` is empty, and the tracked .gitignore is unchanged
- Subagent `git rm <tracked clean file>` -> allowed. `git rm -f x`, `git rm -rf x` and `git rm --force x` -> denied. `rm untracked.txt` -> still denied.
- python3 scripts/size-ratchet.py --check -> exit 0 at the budget. A scratch commit adding lines beyond the budget -> exit 1, listing the top growers. A commit that raises policies/size-budget.v1.json together with growth -> still exit 1, because the budget is read from the merge base. The CI step precedes 'Run tests'.
- agents/ba.md's verdict enum includes retire, routed to the human; agents/ba.md:18 is a grep instruction
- git diff --numstat -- hooks scripts schemas -> net code lines <= -40000

**Effort.** L (about 3 days; lands as two commits: deletions and hygiene first, then removal path, ratchet and BA verdict)

**Risk and rollback.** Risk: a hidden dynamic caller (X83). Mitigations: a reachability pass (AST imports, string literals, importlib, the dynamic todo load), the reference loop in the acceptance tests, and an explicit KEEP list (session_resources). bash-safety is security-critical, so only git-rm forms change, with golden cases. The ratchet blocks feature work until something is removed; the headroom left after the cleanup mitigates this. info/exclude must not hide a real deliverable. Rollback: revert either commit; deleted files are recoverable from history.

**Decisions (recommended default included)**

- U3 / U-E1a: confirm that LANE-B, negative-evidence, dev-fix, repair-map, the attribution CLIs and spec-update-contract are abandoned cycles, not held features. Recommended: yes. Otherwise the I5 row is skipped and their tests stay quarantined.
- U-E1b: retire the per-folder INDEX/README convention? Recommended: not now; update-only doc-sync stops the growth.
- U-E1c: the product docs (launch-plan, positioning, rename-execution-plan, roadmap) and ONE product name. U-E1d: repair-venv. U-E1e: replace prose-pinning tests. U-E1f: validate the graphify-prequery schema at its producer (recommended). Also push.sh, and the Q7 git pre-commit trio.
- E2.b: scripts/prune-orphaned-workflow-bookmarks.sh becomes unneeded once the SessionEnd sweep exists. Keep it under the hold (recommended) or delete it.
- U-E2a: may the harness append its runtime patterns to .git/info/exclude in product repos? Recommended: yes.
- U-E3b: trimming CLAUDE.md (about 43% hook internals) is your call.
- U-E4a: keep the backlog as a grep-only archive (recommended), or triage it into a short list. U-F4a: keep the record-only rule for /dev sessions, drop its worktree scope and cap it by the docs budget (recommended).
- U-F1a: allow git rm without -f for all agents. Recommended: yes.
- U-F2a: the 6 ratchet metrics, with the budget measured after this cleanup and raised only by a human commit. Recommended: yes.

## Coverage

| Problem | Handled in |
|---|---|
| A1 | P1: A1.c, A1.d, A1.e, A1.f (required_values deleted). P2: A1.a arming of GATE/STOPGATE/BARRIER plus template registration. P3: TERMINAL armed. A1.b is resolved without a fall-through: armed G2 validates the schema itself, and P4 deletes the flag-gated legacy path. |
| A2 | P3: S7 collection gates, S8 disposition, S9 terminal anchors, TERMINAL armed. P4: S10 /close, S11 /commit, S12 legacy deletions. The late-repair route stays flag-gated (hold). |
| A3 | P5: G2 and the /do gate compare the declared files with the write set derived from the CLI-written transcript; dev, qa and do prose updated. The attribution journal is not extended. |
| A4 | P1: A4.b, G1 binds role to subagent_type. P5: A4.a, role from payload agent_type or meta.json; A4.c main-agent deny (decision option b, no backstop); A4.d grant consumers bind the role. |
| B1 | P1: B1.a resolver root, task-id normaliser, escalation dir, exemption, QA chain-wire completion exclusion. P2: B1.e and B1.g path qualification, CLAUDE_HOME export, PROJECT_ROOT/HARNESS_ROOT literals. P3: B1.b, by folding the completion gate into G4 (stub in P3, deleted in P4). |
| B2 | P2: B2.a landing flow, B2.b closeout recomputed from disk plus immutable fields, B2.d UTC end_time, B2.e contract producer in code, B2.h main/working-root locator. P3: loop-reset disposition recompute with a transcript-counted retry cap. |
| B3 | P1: B3.a coordinator relays phase stderr, best-effort phases never block, logs dir created. B3.c: per-turn streak state deleted at UserPromptSubmit. |
| B4 | P3: the /do gate finalises only its own skeleton (absent or pending -> blocked) at stop_hook_active; an agent-written non-compliant report resolves as incomplete; the /tmp counter is deleted. |
| C1 | P2: CLAUDE_HOME export and prompt venv/harness paths (C1.c prose). P6: C1.a render plus human-run untrack, C1.b author values to the overlay, C1.c code paths, C1.d tests, C1.e docs. |
| C2 | P6: C2.a template as single source plus overlay plus human-run untrack; C2.b bootstrap and doctor; C2.c producer for protected-runtime.json; C2.d CI/verify-claims second truth removed. |
| C3 | P6: C3.c author names and infrastructure defaults (with C1.b). P7: C3.a deletions and redactions, C3.b synthetic fixtures, C3.d private transcript, C3.e one engine over every tracked file. History rewrite: user decision, recommended no. |
| C4 | P0: C4.a collection breaker deleted. P7: C4.b red CI steps, C4.c quarantine and junk tests, C4.d hermetic conftest, C4.e tracked fixtures, C4.f test rot, C4.g shell tests wired into CI. |
| D1 | P0: D1.d checkpoint push opt-in, one GIT_AUTO_PUSH default. P4: D1.e advisory sinks of the armed gates deleted. P8: D1.c doc-sync update-only; D1.f analyst decision; D1.e stderr-only hooks (prose corrected, decision D-D1e). P9: D1.a dead hooks, D1.b dead scripts. |
| D2 | P8: D2.a dead denies, D2.b missing and relative allows, D2.c dangling prompt refs, D2.d single spec_path producer, D2.e functional docs/dev refs, D2.f todo scripts from the harness only. P9: dead-target allows go with their files. P7: tests that read docs/dev. |
| D3 | P0: one GIT_AUTO_PUSH default. P1: one task-id normaliser and PRODUCER_ROLES. P6: D3.i settings versus template. P8: D3.a/D3.b minimal, D3.c consent readers, D3.f roster, D3.g include files. D3.d, D3.e and D3.h deferred (see not_doing). |
| D4 | P4: D4.f close --force/FORCED text and STEP7 markers. P8: D4.a via decision UD-CM, D4.b README/ARCHITECTURE, D4.c commands, D4.d agents (charter reworded, no enum change), D4.e docstrings, D4.g rulings documented (UD5 kept). |
| E1 | P7: privacy-carrying and CI-breaking junk (I1 strays, I2 tests/generated, broken I6 tests, private I7 docs). P9: E1.a the rest of the pure junk (explicit list, session_resources kept), E1.b feature-tied files kept with producer validation, E1.c decisions. |
| E2 | P8: E2.a doc-sync update-only (= D1.c). P9: E2.b .git/info/exclude via the existing SessionStart hook plus SessionEnd sweep; E2.c seal path, PYTHONDONTWRITEBYTECODE and .gitignore pruning. The repo-is-~/.claude model is unchanged (status quo). |
| E3 | P0: E3.a re-injection deleted. P8: E3.b stamps removed (no refusal hook), E3.c include files, tutorials and trace contract moved out. Growth is capped by the P9 prompt_bytes ratchet. |
| E4 | P7: private and incident records deleted or moved. P9: E4.a history deleted, rationale inlined, evidence docs closed by their phase; E4.b BA greps the backlog. |
| F1 | P9: F1.a git rm without -f allowed (recoverable from history); F1.c cleaner and /clean discard with git rm. F1.b (snapshot-then-rm) not done; see not_doing. |
| F2 | P7: F2.b weekly scheduled CI plus red steps fixed. P9: F2.a size ratchet in CI only. |
| F3 | P7: F3.a minimal py_compile/bash -n of harness hook and script edits at G2. P8: F3.d Hook Discipline #2 wording via UD-CM/U-F3c. F3.b, F3.c and concurrent-writer control are not done: live editing is the status quo (see not_doing). |
| F4 | Every phase: rules retired >= rules added, listed in each PR (principle 6). P6: F4.d removals reach the shipped config by construction. P9: F4.b BA retire verdict as a human decision, F4.c record-only rule scoped and capped. F4.a (Review-by) not done. |
| A1.a | P2 (arming commit) |
| A1.b | No fall-through added: armed G2 validates the schema (P2), and the flag-gated legacy path is deleted (P4) |
| A1.c | P1 |
| A1.d | P1 (ba-qa-report.v1 = the template shape, dev.md:682-691) |
| A1.e | P1 (plus T1 self-record and refused-dispatch exclusion) |
| A1.f | P1 (required_values deleted from the templates; schema enums are the single truth) |
| A2.S7 | P3 |
| A2.S8 | P3 |
| A2.S9 | P3 (bound = stop_hook_active; real-session confirmation before arming) |
| A2.S10 | P4 |
| A2.S11 | P4 |
| A2.S12 | P4 (late-repair kept flag-gated per hold; orphan repair-orchestrate script deleted in P9 if U3) |
| A3.a | P5 (CLI-written subagent transcript, not the journal) |
| A3.b | Not done: the attribution journal is not extended; P5 uses the CLI-written transcript instead |
| A3.c | P5 |
| A4.a | P5 |
| A4.b | P1 |
| A4.c | P5 (option b, deny only; skipped if the user keeps the design's trust boundary) |
| A4.d | P5 |
| B1.a | P1 |
| B1.b | P3 (folded into G4; stub deleted in P4) |
| B1.e | P2 |
| B1.g | P2 |
| B2.a | P2 |
| B2.b | P2 |
| B2.d | P2 |
| B2.e | P2 (labels imported from scripts/todo/dev-overnight.py _STEPS; loop-reset disposition in P3) |
| B2.h | P2 |
| B3.a | P1 |
| B3.c | P1 |
| C1.a | P6 (untrack is a human-run final step) |
| C1.b | P6 |
| C1.c | P2 (export and prompts) and P6 (code) |
| C1.d | P6 |
| C1.e | P6 |
| C2.a | P6 |
| C2.b | P6 |
| C2.c | P6 |
| C2.d | P6 |
| C3.a | P7 |
| C3.b | P7 (git history rewrite deferred: user decision, recommended no) |
| C3.c | P6 (code defaults) and P7 (tests, comments, tests/generated) |
| C3.d | P7 |
| C3.e | P7 (one engine in CI and checkpoint-core; no privacy predicate in G2, G5 or /commit) |
| C4.a | P0 |
| C4.b | P7 |
| C4.c | P7 (quarantined code deleted in P9 if U3) |
| C4.d | P7 |
| C4.e | P7 |
| C4.f | P7 |
| C4.g | P7 |
| D1.a | P9 |
| D1.b | P9 |
| D1.c | P8 |
| D1.d | P0 (remote ref deletion is a human-only REQUEST; fswatch untouched) |
| D1.e | P4 (advisory sinks of the armed gates deleted) and P8 (stderr-only hooks: prose corrected, decision D-D1e) |
| D1.f | P8 (decision U5) |
| D2.a | P8 |
| D2.b | P8 (missing-script and relative forms) and P9 (dead-target rules) |
| D2.c | P8 |
| D2.d | P8 |
| D2.e | P8 (prompts and code), P7 (tests), P9 (stray files) |
| D2.f | P8 |
| D3.a | P8 minimal (classifier normalises its own input); further lexer merges deferred |
| D3.b | P8 minimal (one git option table); iterator merge deferred |
| D3.c | P8 (13 consent readers, 2 fallback stubs, do.md paths; grant literals that already agree are left) |
| D3.d | Deferred: refactoring about 40 security hooks onto one subagent predicate costs more risk than its benefit for a user with limited energy |
| D3.e | Deferred: the 16 project-dir functions stay; P2's locator and P8's spec producer cover the cases that break |
| D3.f | P8 |
| D3.g | P8 (include files, no render script) |
| D3.h | Deferred: todo/protected-path/FORCED helper merges are cosmetic |
| D3.i | P6 (settings) and P8 (README/ARCHITECTURE) |
| D4.a | P8 (as decision UD-CM; CLAUDE.md is user-owned) |
| D4.b | P8 |
| D4.c | P8 |
| D4.d | P8 (charter reworded to the existing enums; no schema change) |
| D4.e | P8 |
| D4.f | P4 |
| D4.g | P8 (UD5 kept and documented) |
| E1.a | P7 (privacy/CI part) and P9 (explicit list) |
| E1.b | P9 (nothing deleted under the hold; producer schema validation) |
| E1.c | P9 (decisions) |
| E2.a | P8 |
| E2.b | P9 |
| E2.c | P9 |
| E3.a | P0 |
| E3.b | P8 (no refusal hook) |
| E3.c | P8 (block families, tutorials, trace contract); moving plumbing into scripts and splitting QA/PM modes deferred as later structural work |
| E4.a | P7 (private docs) and P9 |
| E4.b | P9 |
| F1.a | P9 |
| F1.b | Not done: snapshot-then-rm in bash-safety is too much security-critical churn; untracked junk is removed through /clean, and git rm covers tracked files |
| F1.c | P9 (cleaner and /clean only; not the changelog-analyst) |
| F2.a | P9 (CI only) |
| F2.b | P7 |
| F3.a | P7 (py_compile and bash -n only) |
| F3.b | Not done: fswatch and /pull on the harness home stay as they are (live-editing status quo) |
| F3.c | Dropped: a /commit-side peer-skip filter would be a consumer-side compensation |
| F3.d | P8 (decision U-F3c inside UD-CM) |
| F4.a | Not done: Review-by headers add standing upkeep; the per-phase retire >= add accounting and the BA retire verdict address rule growth instead |
| F4.b | P9 (retire is a proposal decided by the human) |
| F4.c | P9 |
| F4.d | P6 (one source; the verify-claims sync section is deleted) |

## Not doing

- No consumer-side checks. Nothing is added to /close, /commit or the changelog-analyst: no routing loop, re-validation, re-dispatch, cross-check, privacy scan, discard class or peer-skip filter. The user ruled consumer strengthening out of scope; P4 only deletes there.
- No new mutable state files: no ledgers, receipts, counters or sidecars. G4 and the /do gate are bounded by the CLI's stop_hook_active field, and the overnight retry cap counts Agent tool_use records in the transcript. The /do gate's /tmp counter and five advisory jsonl sinks are deleted. The design's stop-devcycle-recompute.py is not created; stop-obligation-gate.py is extended instead. settings.machine.json and the private-marker file are human-written per-machine configuration.
- No per-task Stop-block counting from transcript records. The stop_hook_summary record aggregates all Stop hooks, carries no task id, and its blocking form is unmeasured.
- No new subsystem larger than what it removes. The only new code files are scripts/size-ratchet.py (about 60 lines) and the ba-qa-report schema. The prompt dedupe uses include files instead of a render script. The attribution journal is not extended: A3 uses the CLI-written subagent transcript. Each phase carries a net code-line cap.
- No new enforcement in G2 beyond py_compile and bash -n of harness hook and script edits. Tests, the privacy scan, canary-verify and the size ratchet run in CI, not inside SubagentStop hooks, which have no timeout set and would fail open.
- No stamp-refusal hook, no Review-by headers, and no snapshot-then-rm path in bash-safety: each would add a standing rule for a recurrence that CI (the ratchet) or git history already covers.
- No feature retirement, and no recommended default that retires a capability. Kept: the /do commit/push bypass (UD5), fswatch auto-sync and /pull on the harness home, doc-sync and the INDEX convention, late-repair (flag-gated), /clean, paseo, keystone, dev-command, scripts/commit.sh, hooks/lib/session_resources.py and the 11 feature-tied hooks. Abandoned-cycle code is deleted only if U3 confirms it is not held. Agents never authorise rule removal: BA's retire verdict is a proposal to the human.
- No change to the live-editing model: no move of the source off ~/.claude or tmpfs (X40/X77/X79), and no concurrency control for several sessions or accounts writing one tree (F3 status quo). Building each phase in a clean clone and landing it with /commit is only a recommendation.
- No git history rewrite (C3.b decision), and no agent deletion of remote refs. The 255 auto-pushed refs are a human-only REQUEST.
- No agent edit of CLAUDE.md. All CLAUDE.md wording changes are one human decision (UD-CM) with the exact diff.
- No adversarial-grade isolation of hook state (A4.c option c), and no defence against an agent truncating its own transcript or forging Bash path mentions. These fixes stop honest shortcuts, not a deliberate attacker. Content forgery (V6) stays outside the design (M39).
- No schema enum additions for the charter's routing statuses (D4.d): the charter is reworded, so the P1-P3 dispositions and TERMINAL_VOCABULARY stay closed.
- No D3.d, D3.e or D3.h refactors, and no full unification of the shell lexers and git iterators beyond the minimal normaliser and the one option table. The risk to security hooks is not worth it for a user with limited energy.
- No hook-architecture performance work (interpreter launches per tool call, single-tool hooks registered for every tool) and no pipeline-shape redesign (X27/X28/X100); these are outside the 24 problems.
- No new Python lockfile and no porting of shell tests to pytest; neither is needed for any of the 24 problems.
- No per-pipeline arming granularity (design G10). One global env switch per gate is the kill switch.
- No generated README hook tables or counts; counts are removed from prose instead.
- No gates for /spec and graphify dispatches. They stay without obligations (null-degrading enrichment, design 1.5.1), and G1's context trigger excludes /spec.

## Metrics

| Metric | Now | Target |
|---|---|---|
| Compliant pipelines that complete with all four producer gates armed under the real T1 transcript order | 1 of 6 (only the /do half; /dev, /dev-command, overnight, /close and /commit deadlock or false-block) | 6 of 6 (G1-G3 after P2, G4 after P3) |
| Producer-gate switches set to block in the shipped config | 0 of 4 (none in settings.json or the template; the template does not register G1/G2/G4) | 4 of 4 (3 in P2, 1 in P3) |
| Honest terminals accepted at the producer stop when armed (QA fail, dev blocked, dev needs_review, BA-QA fail, close append-error) | 0 of 5 | 5 of 5 |
| Producer Stop gates that can block without bound | 3 (G4 [2,2,2,2,2], stop-completion-gate 6x, e2e-enforce guess-block 3x+) | 0 (G4 and the /do gate give one round via stop_hook_active; the completion gate is folded; the guess-block is deleted) |
| /dev-family Stops in a product repo blocked by stop-completion-gate GATE_ERROR | every Stop, unarmed | 0 |
| Disobedient-producer cases (V1-V5, V9, V10) stopped at dispatch or producer stop, or recorded as incomplete | V3, V4 and V5-identity only, each escapable via ESCALATION_ACK with no terminal consequence | all (V6 out by design; V7/V8 closed in P5 under A4.c option b) |
| Checks in /close and /commit beyond one disposition call | all class-b/c/d/e checks (close #11-138, #154-157; commit #6-52, #102-104), plus close.md:146-321, :567, :668 and commit.md:580-587 | 0; exactly one disposition call each |
| Pipeline steps that fail in a product repo on harness-relative paths | about 62 sites, plus 84 uses of CLAUDE_PROJECT_DIR with no fallback | 0 |
| A compliant overnight session reaches end_time and terminates | no (Step 2 deadlock; no time-lock in UTC+8; closeout fields have no producer; 2-pipeline G3 deadlock) | yes, for 1- and 2-pipeline cycles |
| dev files_created entries the dev did not write (sandbox T6) | 6 of 8 | 0 |
| Role-based hooks that take the role from the CLI-supplied agent_type | 0 (one advisory hook) | all |
| Pushes to origin outside /push with default settings | a checkpoint push on every dirty Stop (GIT_AUTO_PUSH ignored by checkpoint-core); 255 auto-pushed refs on the public origin | 0 after P0 (opt-in via GIT_AUTO_PUSH=1, one default across readers); remote refs deleted by the human |
| Hook commands with hard-coded /root/.claude in the tracked settings | 83 of 83 | 0 (settings.json rendered, then untracked by the human) |
| render-settings --check | exit 1 (4 failures) | exit 0 |
| Fresh non-root clone after bootstrap | every prompt blocked (python hooks exit 2), safety hook inert (exit 127), bootstrap prints SUCCESS | bootstrap and doctor pass; no hook exits because of a missing file |
| check-public-core.sh FAIL rows | 79 (80 output lines including the final banner; public-core subset only) | 0 over every tracked file |
| CI health | 0 tests run (collection abort); red on every run since 2026-07-26; behind the abort, tests/ 228 failed + 20 errors and hooks/tests 133 failed; 4 other steps red | collection fixed in P0; all steps green on push and weekly after P7; quarantine list of at most 10 entries, each with a problem id |
| Advisory log files with a writer and no reader | 14 (D1.e list) | 9 or fewer (the five armed-gate and /do-gate sinks deleted in P4, the completion-gate audit logs gone in P3/P4) |
| Known contradictions between prose and hook behaviour | about 79 rows | 0 outside CLAUDE.md; CLAUDE.md rows resolved by decision UD-CM |
| Hand-copied prompt blocks | 6 families, 59 copies, 1,658 lines (about 2,500 duplicated lines in total) | one include file per family |
| Prompt bytes re-sent per command by prompt-workflow | /close 119,653 B, /dev 108,226 B duplicated | 0 after P0 (overnight continuation excepted) |
| Always-loaded prompt layer | about 407k tokens | about 1,780 fewer always-loaded lines (roughly -35k tokens), then capped by the prompt_bytes ratchet |
| Net code lines (hooks/, scripts/, schemas/, tests excluded) per phase | no budget | P0 <= 0; P1 <= +150; P2 <= +200; P3 <= 0; P4 <= -300; P5 <= +80; P6 <= 0; P7 < 0; P8 < 0; P9 <= -40000 |
| Enforcement rules added versus retired, per phase | rules only accumulate (F4) | retired >= added in every phase, listed in each PR |
| Tracked files and pure-junk lines | 893 files; about 57,950 junk lines (55,270 plus 2,681 missed) | about 690 files; 0 pure junk (feature-tied files kept under the hold) |
| Untracked runtime files in a clean product repo after 8 slash commands | 75 | 0 |
| Recoverable removal by agents | git rm and rm denied for every agent (subagents always) | git rm without -f allowed; forced git rm and plain rm unchanged |
| Size budget | none | 6-metric ratchet in CI, read from the merge base; values only go down |
| Dated incident records in docs/reference | 37 dated plus 14 undated | the binding design doc, plus open-defect docs each closed by its phase |
| BA mandatory read | 697 KB backlog read in full | a targeted grep |

## Critic findings addressed in this revision

Mostly sound, and faithful to design S7-S12 and the producer-only rule. I checked about 45 file:line claims and most are accurate, for example: artifact-contract-enforce.py:1122-1123 and :928-933; obligation.py:122-124, :584, :605 and :644; pretool-aggregate-check.py:427-488 (it really does not exclude the in-flight dispatch); obligation-gate.py:70-76 and :86-87; dev.md :460, :510, :635, :743, :874 and :1023; stop-completion-gate.py:218 (project_dir/scripts, block by default); stop-workflow-coordinator phases :63-68 (so CLAUDE.md:102 is stale); stop-do-report-gate.py:57 and :193 (block by default, so do.md:53 is wrong); create-overnight-state.sh:1051; stop-overnight-timelock.py:84; posttool-overnight-loop.py:287-288; commit.md:334; close.md:606; dev-overnight.md :1095, :1197, :1289, :1390, :1504 and :1506.

Six problems to fix before execution:

1. **Consumer-side additions at /commit.** Remove the privacy scan by the changelog-analyst (P7), the analyst's 'discard' class (P9 F1.c) and the peer-skip rule (P5 F3.c).

2. **Recommended defaults that conflict with the hold and status-quo decisions.** Flip these: UD5 (removing the /do commit/push bypass), F3.b (disabling fswatch and /pull on the harness home), and F4.b (BA self-authorizing retirement). Also attach a decision to the CLAUDE.md edits.

3. **Three live-use breaks to re-sequence.**
   - P3 deletes a registered Python hook while live sessions are running. Python exits 2 on the missing file, so every Stop is blocked.
   - P6 untracks settings.json. Every pulling clone, including fswatch auto-pull, loses its settings.json.
   - P1 arms the shipped template before P2 makes product repos runnable.

4. **Measure the G4 bound before arming TERMINAL.** Measure the per-task transcript block count (stop_hook_summary carries no task id), and pin G1's schema registry to the harness root.

5. **Shrink.** Drop A1.b, replace the full-enum required_values with deletion, and drop the G2 pytest/canary predicates (CI already covers them), Review-by and F1.b.

6. **Add a P0 phase.** Pull D1.d (the active origin-push privacy leak), C4.a and E3.a forward into it.

With those changes the plan meets the architecture.