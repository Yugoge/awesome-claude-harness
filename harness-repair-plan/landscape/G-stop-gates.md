# G. One stop gate for /do /dev /dev-command /dev-overnight /close /commit /merge /push (D4)

Repo `/home/user/awesome-claude-harness` at HEAD 09ab15b (on the user's machine this is `~/.claude`). CLI 2.1.295.
Binding architecture: `docs/reference/close-commit-zero-failure-mechanism-20260928.md`. Each artifact has one producer, hooks enforce at the producer, consumers trust one disposition, and no new mutable state is added.
User decisions applied here: D2 (dev cannot honestly fail), D3 (question pause), D4 (no bound, no self-release), D5, D6, D7, D8, D9 and D10.

Evidence: every claim cites file:line in the repo. Runtime claims were re-run on a scratch copy at
`scratchpad/sgsc-work/G-stop-gates/`, with `PYTHONDONTWRITEBYTECODE=1`, `HOME=…/home` (where `.claude` points to `…/harness`), `CLAUDE_STATE_DIR=…/state` and a git product repo per scenario. Files there:
- `proto/run_scenarios.py` drives the scenarios.
- `proto/command_span.py` and `proto/stop_command_gate.py` are the prototype of the design, 424 lines.
- `run3.log` (S1-S7) and `run2.log` (S8-S11) hold the results.
- `coordinator-fresh.{out,err}` holds the silent coordinator block.

The prototype passed every scenario below.

---

## 1. Per-command inventory

### 1a. Todo list: where it comes from, how it is injected, how a Stop hook can see it

| Command | Canonical list | Injection |
|---|---|---|
| /dev | `scripts/todo/dev.py:16-35`, 17 steps | `hooks/prompt-workflow.py:1833-1922` `_ordinary_dev_start`: todos are written atomically at :1904; the bookmark carries `task_id` at :1888-1897 |
| /redev | `scripts/todo/redev.py:4`, which imports `dev.get_todos` | same as /dev, via :1931-1933 |
| /dev-command | `scripts/todo/dev-command.py:11-30`, 16 steps | same as /dev |
| /dev-overnight | `scripts/todo/dev-overnight.py:14-90`, 22 items (11g included) | `prompt-workflow.py:1925-1979`, after the launcher check at :1940-1974 |
| /do | `scripts/todo/do.py:9-15`, 5 steps | `prompt-workflow.py:1929-1930` runs handle_do_consent (consent flag :1412, task sidecar :1422, do-report skeleton :1435), then the generic path at :1934-1979 |
| /close | `scripts/todo/close.py:22-26`, 3 steps. It also carries a 2-step `--force` variant at :28-31 and :45-51, although `--force` is now a no-op alias (`commands/close.md:77`). Step 0 of close.md is missing from the script, which is why check-todo-md-sync warns at every SessionStart. | generic path |
| /commit, /merge, /push | **none**: there is no `scripts/todo/{commit,merge,push}.py`. | `prompt-workflow.py:1927-1928` writes only a user-intent sentinel. `run_todo_script` returns [] (:330-351), so no checklist is injected. This is confirmed by `landscape/E-junk-runtime-prompts.md:36`. |

There are three places a Stop hook could read checklist state from. Only one is evidence.
1. **Transcript TodoWrite records.** The CLI writes them and they are append-only: the assistant `tool_use` named TodoWrite with `input.todos[]`, then a user `tool_result`. When a PreToolUse hook refuses a call, the tool_result carries `is_error`. This is the only CLI-written record of the checklist.
   - The armed test measured the T1 ordering: the in-flight tool_use is already the last record when PreToolUse runs (`harness-cleanup/core-architecture-armed-test.md:104-105`). So a reader must take the last TodoWrite that **has a non-error tool_result**.
   - Slash commands are recorded as `<command-name>/x</command-name>`, followed by an isMeta body record. The real transcript of this session starts with queue-operation records: it has 178 of them.
2. **`~/.claude/todos/<sid>-agent-<sid>.json`** is not evidence:
   - The hooks write it themselves: `prompt-workflow.py:176-177`, :1904 and :1975-1977, and `posttool-todo-tracker.py:88-111`.
   - The tracker deletes it when every step is completed (`posttool-todo-tracker.py:90-99`). After deletion, "finished" cannot be told apart from "never started".
   - `/stop` force-completes it (`scripts/break-overnight-lock.py:105-114`).
   - The path ignores CLAUDE_CONFIG_DIR (`landscape/E-junk-runtime-prompts.md:651`).
   - The container's own `/root/.claude` has no `todos/` directory at all, so there is no proof that the CLI writes it.
3. **Bookmark `<project>/.claude/workflow-<sid>.json`** (`prompt-workflow.py:180-181`) is not evidence either:
   - `last_todos` is a hook-made copy of the transcript (`posttool-todo-sequence.py:167-173`).
   - `lock_reason` is set by `posttool-todo-count.py:44-52` and `posttool-todo-sequence.py:140-148`.
   - `subagent_calls` is set by `posttool-subagent-track.py:246-266`.
   - The file is agent-writable, and the tracker deletes it on completion (`posttool-todo-tracker.py:96-99`).

`CLAUDE_CODE_ENABLE_TASKS=false` and `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` in `settings.json:20-21` pin the TodoWrite tool. The template sets only the first of these (`settings.template.json:20`).

Hooks that already validate the checklist (none of them at Stop):
- `pretool-todo-validate.py`. Rules are listed at :11-18 and implemented at :160-168: one completion per call, through in_progress, a single in_progress, in order, content immutable. A count or length change triggers the canonical check at :296-300. Gate 4, the subagent guard, is at :227-270 and reads bookmark `subagent_calls`.
- `posttool-todo-sequence.py:27-129` runs the **same** rules after the tool has run, plus an initial-status rule at :116-129.
- `posttool-todo-count.py:95-103` runs the count check after the tool has run.
- `pretool-workflow-gate.py:1100-1180` requires a TodoWrite before any other tool and enforces lock_reason.
- `posttool-todo-tracker.py` prints progress.

Measured on the scratch copy: `pretool-todo-validate` alone already blocks both a 5-of-17 count (rc 2, 'Todo count mismatch: canonical has 17, submitted has 5') and a skip of two steps (rc 2, 'Completed 2 steps in one call').
- A TodoWrite blocked at PreToolUse never reaches PostToolUse, so the two PostToolUse checks never see such a call. They exist only to write `last_todos` and `lock_reason` into the bookmark.
- `pretool-workflow-gate.py:1091` claims that a "Stop hook enforces todo count >= blocking_count". No Stop hook does (`runtime-verification.md:194`).

### 1b. The artifact that proves each command finished, and the code that can verify it

| Command | Artifact(s) | Producer (enforced at) | Code that verifies it (consumer side, one call) |
|---|---|---|---|
| /dev, /redev, /dev-command | Every lane's ticket, context, dev-report and **QA-report with qa.status=pass**, plus the canonical dev-report and `completion-<task>.md` | ba, dev and qa via G1/G2 (P1-P3); completion comes from the orchestrator (`commands/dev.md:1278-1392`) | `scripts/resolve-dev-artifact-chain.py:1773` `resolve_chain(root, task)`. `validate_qa` requires 'pass' (:286-300), and fan-out mode requires a passing QA for every lane (`dev.md:1408-1416`). Status is computed at :2226-2245. D2 requires `status == "pass"`, never `pass_with_exceptions` (RECLASSIFIABLE_CODES :61-63). P3 adds `--disposition`, with chain_pass as the success value. |
| /do | `docs/dev/do-report-<task>.json` with do.status=completed | orchestrator (/do); the task id comes from the hook sidecar `<state>/claude-do-task-<sid>.json` (`prompt-workflow.py:1418-1426`) | Shape and schema: `stop-do-report-gate.py:78-124` (logic to be kept, gate retired); schema `do-report.v1` through `contract_runtime.validate_report_artifact` |
| /close | `docs/dev/close-report-<task>.md` whose last line is `CLOSE: YES` (D7 also requires the dev chain) | close-QA via G2 (`commands/close.md:577-790`); the orchestrator appends (Step 3) | `hooks/lib/close-verdict.py:21,37` `classify_line(last_nonempty(text)) == "yes"`. Targets: an explicit argument, or the `--auto` snapshot `dev-lifecycle.py list-actionable --next-action close` (`close.md:950`), or the close obligation's task_id |
| /commit | A HEAD-reachable commit carrying `Task-id: <task>` in every planned repo, with clean owned paths | changelog-analyst (`agents/changelog-analyst.md:990,1107`), status block `changelog-status.v1` checked by G2 | `scripts/dev-lifecycle.py:560` `derive_state(root, task).state == "committed"` (commit_detection :486-534, combined at :469-483). The commit journal is **unsuitable**: `find_attributable_event` requires `resulting_head == HEAD` exactly (`hooks/lib/commit_journal.py:494-588`, :561-562), so a later commit makes it unmatchable. For --bulk, use the changelog-analyst `response_block` commit_status (success set at `commands/commit.md:1003`). |
| /merge | The merged ref: SOURCE_TIP is contained in refs/heads/DEFAULT_BRANCH and no unmerged entries remain | `hooks/merge.sh`, invariant at `commands/merge.md:209` | git: `merge-base --is-ancestor <SOURCE_TIP> refs/heads/<DEFAULT_BRANCH>` and an empty `ls-files -u`. SOURCE_TIP, DEFAULT_BRANCH and REPO_ROOT come from the merge-analyst dispatch prompt (`merge.md:116-122`). |
| /push | HEAD is published: HEAD is an ancestor of `refs/remotes/<REMOTE>/<BRANCH>` | `hooks/push.sh` through `scripts/execute-push.py` | git, local refs only (a successful push updates the remote-tracking ref). BRANCH and REMOTE_NAME come from the push-analyst dispatch prompt (`commands/push.md:171-173`). "Nothing ahead" (`push.md:37`) also satisfies the check. |
| /dev-overnight | (a) The time-lock is released. (b) Every pipeline family dispatched in the session passes the dev predicate. (c) `docs/dev/overnight/<sid>/retro-report-cycle*.json` exists and an `overnight-summary-*.md` is newer than start_time (`dev-overnight.md:1617,1638,1672`). (d) D6 landing. | launcher state (`scripts/create-overnight-state.sh`), pm, ba, dev and qa | P2 B2.d already recomputes (c) from disk; (b) reuses the dev predicate; (d) composes the commit, merge and push predicates |

### 1c. Every existing Stop and SubagentStop gate on these commands, and its defects

Registration: `settings.json:814-850` registers four Stop entries, which Claude Code runs **in parallel**: the coordinator :819, do-report :827, obligation :835 and completion :843. The template registers four different direct entries, `settings.template.json:759-779`: timelock, spec-coverage, auto-commit and cleanup.

| Hook | What it does | Defects (file:line; scratch evidence) |
|---|---|---|
| `stop-workflow-coordinator.py` | Runs the phases timelock, coverage, auto_commit and cleanup in sequence; the first non-allow phase gives exit 2 (:40, :61-69, :262-277) | The phase's stderr is replaced by a sha256 (:160-177), so every block reason is invisible. **Reproduced:** with a fresh HOME, rc=2 with 0 stderr bytes and failed_phase=auto_commit (`coordinator-fresh.out`; cause at checkpoint-core.sh:519). The timelock-only stdout parser is at :111-127 and :167-170. Cleanup runs here, but the other three Stop hooks run in parallel, so cleanup can act while another hook blocks. |
| `stop-overnight-timelock.py` (coordinator phase 1) | Blocks until end_time and runs the closeout checks | The naive-local parser drops the timezone (:72-87). Closeout reads fields the agent declares itself (:138-150), including `unresolved_backlog`, which has no writer. An agent-settable `status=cancelled` releases the lock (:240-243, runtime-verification:187). `stop_hook_active` is honoured only after end_time (:270-278), so there is no bound, which is correct for D4. The continuation sentinel `/tmp/overnight-needs-continuation-<sid>` (:163-189) has **no reader** (grep: only this file). |
| `stop-spec-coverage-enforce.py` (phase 2) | /spec only; bounded by stop_hook_active (:246-247) | Outside D4's scope; kept unchanged. It reads the bookmark (:70-80). |
| `stop-cleanup-allowlist.sh` (phase 4) | Expires /allow grants, the /do consent flag and the streak file | Clears /do consent at **any** Stop that reaches cleanup (:32-38), while stop-do-report-gate may be blocking the same Stop in parallel. /do then loses consent mid-work (runtime-verification:185). |
| `stop-do-report-gate.py` | /do report shape at Stop | MAX_BLOCKS=2 force-allow (:57, :239-256). **Reproduced:** with the report still pending, stop #3 gives rc=0 'FORCED ALLOW' (run3.log S3). The counter lives in agent-writable /tmp (:150-169); deleting it resets the gate (armed-test:98). `_rewrite_pending_to_blocked` makes the hook a second producer of the agent's artifact (:172-189). It accepts 'blocked' as terminal (:59); **reproduced:** a report with status blocked gets rc=0 on every Stop. It clears consent (:127-147, :226-232, :245). |
| `stop-obligation-gate.py` (G4) | Re-checks the json obligations of dispatches | No bound; it never reads stop_hook_active (:103-145; armed test: [2,2,2,2]). Advisory by default (:104), fail-open on errors (:127-133, :148-156). It delegates to `obligation.find_unresolved_dispatch_obligations` (:900-1021), which has these gaps: every Agent call in the **whole transcript** (:946), so an abandoned earlier cycle poisons every later turn; no `is_error` filter, so refused dispatches count; a dev-registry token prefilter (:958-966); json kind only (:979); and D2-conflicting required_values (:997-1020). A stage that was never dispatched is invisible (V9). **Reproduced:** S1, a /dev at 1 of 17 with QA never dispatched, gives rc=0. |
| `stop-completion-gate.py` | 'Sole missing completion' plus ESCALATION records | Imports the resolver from `<project>/scripts` (:211-226, :218), giving GATE_ERROR in every product repo. **Reproduced:** S2 with a fully compliant chain gives rc=2 'GATE_ERROR\|FileNotFoundError'. The /close and /commit exemption never matches: it reads line 1 only (:150-167, through `obligation.py:644-676`), and real transcripts begin with queue-operation records. Its only exit is an agent-written `docs/dev/arbitration-<cycle>.json` (:293-311, :483-498), which is a self-release token, followed by `continue:false` (:509-517). It keeps mutable state in completion-gate-state.json, audit jsonl and logs/completion-gate-*.json (:47-50, :405-506). It fires only on the exact 'sole missing completion' signature (:229-249), so QA-fail and abandonment pass (runtime-verification:218). |
| `posttool-overnight-loop.py` (G4 loop anchor) | Blocks the cycle reset | It accepts 'blocked' as terminal (:31), against D2. Its "block" goes to stdout with exit 0 (:271-275), so it is not a blocking channel. It reuses find_unresolved_dispatch_obligations (:213-215). |
| `subagentstop-artifact-contract-enforce.py` (G2, SubagentStop) | Producer-side artifact check | It is the D3 waiver point: `waived_by_response` uses re.search without MULTILINE (:928-933; P1 fixes this). The gate depends on it but does not replace it. |
| Todo hooks | see 1a | The checks are duplicated (see 1a), and the bookmark is a second, mutable copy of the transcript. |

**Measured with the current hooks** (run3.log):
- S1, a /dev stop at 1 of 17 with QA never dispatched: do-report rc 0, obligation rc 0, coordinator rc 0. Only the completion gate blocks, and only because of its GATE_ERROR.
- S4, a /commit with nothing committed: all four hooks rc 0.
- S5, a /merge that was never executed: all rc 0.
- S6, a /push with nothing pushed: all rc 0.

D4 is therefore unenforced for 6 of the 8 commands, and wrongly enforced for /dev (it blocks compliant runs).

Defects from the armed test that this gate touches:
- no bound or deadlock poison: G4 at armed-test:73 and :106-107, G3 poison at :110-111;
- wrong roots: :80 and :116-117;
- the first-line exemption bug: :120-121.

### 1d. Detecting the D3 question pause at Stop, and preventing abuse without a bound

- **Native question (preferred).** `AskUserQuestion` is a tool. The question and its answer happen inside the turn, and the answer comes back as the tool_result, so **no Stop occurs** and the gate is never involved.
  - The orchestrator relays a "needs your decision" block from dev or BA this way, then re-dispatches the same producer.
  - A user interrupt (Esc) does not run Stop hooks.
  - It is already whitelisted by the orchestrator gate (`pretool-orchestrator-gate.py:47`).
- **Text pause (fallback).** Used when AskUserQuestion is unavailable or refused (headless or remote surface, or a denied permission). It is detected when the last non-empty line of the final assistant text matches the grammar the repo already uses, `^AWAITING_INPUT: need=<…>; why=<…>; addressee=(human|user|operator)$`, as in `commands/close.md:239` and `commit.md:44,75,848`.
  - commit.md:133 also allows `addressee=orchestrator`, which is meaningless at a main Stop and is excluded.
  - The source is the Stop payload's `last_assistant_message`, which the armed drivers model at drv.py:414-415. The fallback is the transcript's last assistant text block.
  - Matching only the final line prevents an old quoted line from counting.
- **Abuse without a bound.**
  1. A pause records nothing: no file, no counter and no token. The cycle stays incomplete on disk, and the user's plain-text answer continues the same command span, so the next Stop re-evaluates from the artifacts.
  2. A pause cannot produce completion. /close and /commit cannot land an incomplete cycle either, because their predicates include the dev predicate (D7).
  3. The user sees every pause verbatim and judges it (D3).
  4. In the /dev-overnight time-lock window the pause is not honoured (rec, Q3), because nobody is there to answer. Human `/stop` is the exit there.
  5. A CLI-written API-error record (`isApiErrorMessage: true`, classified by `hooks/lib/interruption_signals.py:381-412`) also allows the stop. This is not agent-controlled: the turn was aborted by the CLI, and /restart resumes it.

### 1e. D7: /close and /commit complete the cycle themselves

- `close_done(task) = origin_done(task) ∧ close-report YES`, where origin_done is the dev predicate, or the do predicate for /do-origin tasks.
- `commit_done(task) = close_done(task) ∧ derive_state == committed`.

Inside a /close or /commit span, the gate therefore lists the dev gaps with their owner role. The orchestrator dispatches the same producers with the same task id and obligations (the /redev continuation path), and the gate releases only when close (or commit) has actually landed.

Interfaces:
- G1's transcript-context rule (P1 A1.c) must accept dev-pipeline obligations while the latest command is close or commit.
- /close's todo list gains Step 0, "Resolve the dev disposition; complete the cycle when incomplete", which also fixes the check-todo-md-sync drift.

### 1f. Interruption

Killed or quota-interrupted sessions:
- No Stop runs on an interrupt. A CLI API-error terminal record is allowed (1d.5).
- Nothing is written, so the cycle simply stays incomplete on disk.
- Resuming the session continues the same transcript, so the span and the predicate are unchanged.
- `/restart` and `/allow` are CONTROL commands: they never open a span, so the dev span survives recovery.
- `/redev <task>` opens a /redev span whose obligations name the old task, so the predicate checks the old task.
- A later /close or /commit completes it per D7.

---

## 2. Design: one Stop gate (`hooks/stop-command-gate.py`, the coordinator's `completion` phase)

**Inputs** are the Stop payload, the CLI transcript, the harness code (resolved as `Path(__file__).resolve().parent.parent`), the project tree and git. **Outputs** are exit 0 or exit 2 with stderr. **Writes:** none, except unlinking the /do consent flag when a /do stop is allowed after completion. **Reads of hook-written files:** the /do sidecar and the overnight state, both existing. There is no counter, no record, no arbitration file and no `stop_hook_active` release.

Algorithm:
1. If the payload has `agent_id`, allow.
2. `span = command_span.active_span(transcript, openers)`.
   - The span opens at the latest human prompt record (type=user, not isMeta, not a tool_result) that is a slash command.
   - Only harness command files open a span (`commands/*.md` stems), minus CONTROL = {allow, restart, checkpoint, tickets}. Built-ins such as /model and plugin or skill commands never reset it.
   - Plain-text prompts continue the span.
   - The scan reads the whole file and skips queue-operation and attachment records.
3. If the last assistant record is a CLI API-error record, allow.
4. **Session time-lock (independent of the span).** If a live `overnight-state-<sid>.json` is not cancelled_by_user and its end_time (parsed by the single UTC parser from P2) is in the future, block. The pause is not honoured here.
5. If the span is missing or its command is not in RULES, allow. This includes the human release, i.e. typing `/stop` or `/spec`.
6. If the span's pause is honoured and the final line is the pause grammar, allow.
7. Compute `gaps = todo_gaps(span) + RULES[cmd].predicate(span)`.
   - todo_gaps compares the last ok TodoWrite in the span with `<harness>/scripts/todo/<cmd>.py`, run with CLAUDE_TODO_PROMPT. The content sequence must be equal and every status must be completed.
   - If any code fails after scoping, the result is a gap ('gate instrument failure'). It never releases the stop, and it never deadlocks because the pause remains available.
8. If there are no gaps, allow; for /do, also unlink the consent flag. Otherwise exit 2, with one line per gap in the form `<artifact>: <problem> | owner: <role> | fix: <action>`, plus the pause instruction.

Declarative table (RULES):

| cmd | todo | predicate | pause honoured |
|---|---|---|---|
| do | do.py | `do-report-<sidecar task>`: identity, source=do, **do.status=completed**, non-empty summary, file arrays, schema not fail | yes |
| dev, redev, dev-command | yes | For every task family named by a pipeline∈{dev,redev,dev-command} obligation dispatched in the span (with a non-error result, canonicalised by P1's `canonical_task_id`, with `-l<N>` stripped): `resolve_chain(...).status == "pass"`. There must be at least one family. | yes |
| dev-overnight | yes | Time-lock released (step 4), then every pipeline family dispatched in the session passes the dev predicate, plus the retro and summary (computed from disk), plus the D6 landing (commit, then merge when the worktree is isolated, then push) | only after end_time |
| close | close.py (+Step 0) | Targets = explicit argument, or the `--auto` snapshot (the tool_result of the span's `list-actionable --next-action close` Bash call), or the task_ids of close obligations. Each target must satisfy origin_done ∧ close-report `classify_line == yes`. | yes |
| commit | none (Q1) | Targets as for /close, with `--next-action commit`. Each target must satisfy close_done ∧ `derive_state == committed`. For --bulk: the changelog-status block shows success. | yes |
| merge | none | From the latest merge-analyst dispatch: SOURCE_TIP is an ancestor of refs/heads/DEFAULT_BRANCH, and there are no unmerged entries | yes |
| push | none | From the latest push-analyst dispatch: HEAD is an ancestor of refs/remotes/REMOTE_NAME/BRANCH | yes |

Interactions:
- D2: strict 'pass' at the gate, so `pass_with_exceptions` and 'blocked' have no accepting consumer, and the D2 lane deletes them.
- D3: one pause grammar for the orchestrator and for subagents (waived_by_response `^AWAITING_INPUT: need=`).
- D5: consent covers one /do span (Q4).
- D6: overnight composition (Q6).
- D8: the gate trusts artifacts that the P5 A4.c deny protects.
- D9: the /close rating via AskUserQuestion happens in-turn and is unaffected. The rating comes after CLOSE: YES, when the predicate is already true.

Prototype result: the scenarios cover /dev, /do, /close --auto, /commit, /merge and /push, together with the no-bound, pause, span, API-error and time-lock cases.

| Scenario | Current hooks | Prototype |
|---|---|---|
| S1: /dev at 1 of 17, no QA | no checklist or chain check (completion gate: GATE_ERROR) | rc 2 |
| S1 with stop_hook_active=true | | rc 2 |
| S1b: pause line | | rc 0 |
| S1c: plain answer, then a stop without a pause | | rc 2 |
| S1d: /allow | | rc 2 (span kept) |
| S1e: /stop | | rc 0 (release) |
| S2: QA fail | completion gate GATE_ERROR | rc 2 'INVALID_QA_STATUS' |
| S2: QA pass | completion gate GATE_ERROR | rc 0 |
| S3: /do report pending | current gate rc 2, 2, then 0 (forced) | rc 2 on every stop |
| S3: /do report blocked | current gate rc 0 | rc 2 |
| S3: /do report completed | | rc 0, and the consent flag is unlinked |
| S4: /commit with nothing committed | all rc 0 | rc 2 |
| S4b: after a commit with the trailer | | rc 0 |
| S5: /merge not executed | all rc 0 | rc 2 |
| S5b: after the merge | | rc 0 |
| S6: /push with nothing pushed | all rc 0 | rc 2 |
| S6b: after the push | | rc 0 |
| S7: agent_id | | rc 0 |
| S8: /model mid-cycle | | rc 2 (span kept) |
| S9: API-error record | | rc 0 |
| S10: time-lock plus pause, under Asia/Shanghai and America/Los_Angeles | | rc 2 |
| S10c: cancelled_by_user | | rc 0 |
| S11: /close --auto, snapshot task not closed | | rc 2 |
| S11b: after CLOSE: YES | | rc 0 |

---

## 3. Exact changes

**Commit G-a (gate; code default advisory; armed by an env line in the last commit)**

- **NEW `hooks/lib/command_span.py`** (~140 lines). It provides `active_span`, `Span.calls`, `last_todos` (last TodoWrite with an ok result, which excludes the in-flight call), obligations, `final_text`, `is_pause`, PAUSE_RE and CONTROL_COMMANDS. It is shared by the gate, `pretool-todo-validate`, `posttool-subagent-track`, `pretool-subagent-enforce` and P1 A1.c's "latest slash command" rule for G1.
- **NEW `hooks/stop-command-gate.py`** (~260 lines). It holds RULES, the predicates, the time-lock clause (it absorbs `stop-overnight-timelock.py`, using P2's `lib/overnight` locator and UTC parser and the recomputed closeout), the API-error allow, the /do consent release and `ROLE_BY_ARTIFACT`. ROLE_BY_ARTIFACT is the code home of the shell `artifact_role` at `commands/commit.md:100-116`, which P4 deletes. Mode comes from env `CLAUDE_COMMAND_GATE`: advisory by default, `block` when armed, `off` to disable.
- `hooks/stop-workflow-coordinator.py`:
  - PHASE_ORDER at :40 becomes ("coverage","auto_commit","completion","cleanup") (Q8).
  - `_default_phases` at :61-69 adds completion = stop-command-gate.py with timeout 60.
  - Delete `_structured_timelock_decision` (:111-127) and its use at :167-170.
  - Prerequisite: P1 B3.a, which relays the failing phase's stderr instead of the sha at :160-177.
- `hooks/stop-cleanup-allowlist.sh:32-38`: delete the /do consent clearing.
- `hooks/prompt-workflow.py` `handle_phase_a` (:1925): unlink `claude-orchestrator-consent-<sid>.flag` at any harness slash command that is neither /do nor CONTROL (D5 per span). This joins P1 B3.c.
- `settings.json:814-850`: the Stop group becomes **one** coordinator entry. `settings.template.json:759-779` gets the same, plus `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` at :20. The arming commit adds `CLAUDE_COMMAND_GATE=block` to both files.
- `hooks/stop-completion-gate.py`, `stop-obligation-gate.py`, `stop-do-report-gate.py` and `stop-overnight-timelock.py` become exit-0 stubs for one phase (live sessions keep their loaded hook list, `PLAN.md:10`). They are deleted in the next phase, together with `hooks/tests/test_stop_obligation_gate.py`, `test_stop_do_report_gate.py` and `test_laneb_stop_overnight_timelock_scoping.py`, whose surviving cases move to the new test.
- `hooks/lib/obligation.py:900-1021`: delete `find_unresolved_dispatch_obligations`; its callers are gone.
- `hooks/posttool-overnight-loop.py`: the dev predicate replaces `TERMINAL_DEV_STATUSES` (:31) and `_terminal_gate_block_reason` (:187-223), so one predicate serves two anchors. The block moves from stdout with exit 0 (:271-275) to stderr with exit 2.
- `scripts/break-overnight-lock.py:105-114,:129`: delete `_complete_todos`. Update `commands/stop.md:17-18` to match.
- `scripts/todo/close.py`: delete `_STEPS_FORCED`/`_is_forced` (:28-31, :45-51) and add Step 0.
- `scripts/dev-lifecycle.py:109-117`: load close-verdict only from the harness (`Path(__file__).resolve().parent.parent/'hooks/lib'`).
- Prose, routed through P8's single pass and listed here:
  - `commands/do.md:46-53`: no 'blocked' terminal; use the pause grammar.
  - `commands/dev.md:1204-1225`: the iteration guard becomes a question pause, and 'accept with known issues' is removed.
  - `dev.md:525-527`: the BA round cap becomes a question pause, not 'best-effort'.
  - `dev.md:1385-1392`: 'pass' only.
  - `close.md:797,:867-880`: AskUserQuestion (D9).
  - `merge.md:168` and `push.md` aborts become pauses.
- **NEW `hooks/tests/test_stop_command_gate.py`**: port of `proto/run_scenarios.py` (S1-S11), plus overnight after end_time. Update `hooks/tests/test_laneb_stop_coordinator.py` for the new PHASE_ORDER.

**Commit G-b (fold of the duplicated todo checks)**

- `hooks/pretool-todo-validate.py`:
  - The previous state comes from `command_span.last_todos`, not from the bookmark (:148-157, :293-300).
  - Add the initial-status rule from `posttool-todo-sequence.py:116-129`.
  - Gate 4 (:227-270) asks whether there is an ok Agent/Task call with a matching subagent_type after the TodoWrite that set step i to in_progress.
- Unregister and delete `hooks/posttool-todo-sequence.py` (264 lines) and `hooks/posttool-todo-count.py` (109 lines): `settings.json:686-690` and the template.
- `hooks/pretool-workflow-gate.py`: delete the lock_reason clear (:1110-1114), the lock branches (:1146-1180) and `build_sequence_fix_call` (:162-190); fix the comment at :1091.
- `hooks/prompt-workflow.py`: delete :388-439 (sequence/count formatters) and the lock fields at :467-478 and :1204-1226.
- `hooks/posttool-subagent-track.py`: drop the Path B bookkeeping (:246-266, plus the bookmark last_todos readers at :103-142 and :423-438); Path A reads `command_span`. `hooks/pretool-subagent-enforce.py:79-80` likewise.

**Net**: about -2,150 lines retired against about +450 added in hooks/ and scripts/ (tests excluded), so the net is about -1,700. Stop registrations go from 4 to 1 (live).

## 4. Retired (net-negative accounting)

The hook files and functions:
- `stop-completion-gate.py`, 604 lines. With it go its state (completion-gate-state.json, audit jsonl, logs/completion-gate-*.json), the arbitration verdict file (a self-release token), `continue:false` and its advisory log.
- `stop-obligation-gate.py`, 156 lines. With it go `find_unresolved_dispatch_obligations` (~122 lines) and its advisory log.
- `stop-do-report-gate.py`, 282 lines. With it go the MAX_BLOCKS force-allow, the /tmp counter, the hook-written 'blocked' rewrite, the 'blocked' terminal and its advisory log.
- `stop-overnight-timelock.py`, 294 lines: the naive-time parser, the self-declared closeout fields, the unresolved_backlog blocker and the continuation sentinel that nothing reads.

Coordinator, cleanup and todo hooks:
- The coordinator timelock stdout parser.
- The consent clearing in `stop-cleanup-allowlist.sh`.
- `posttool-todo-sequence.py` and `posttool-todo-count.py`.
- The bookmark fields `last_todos`, `lock_reason` and `subagent_calls`, and the code that reads and writes them in `pretool-workflow-gate`, `prompt-workflow` and `posttool-subagent-track` (Path B).

Overnight, /close and /stop:
- The overnight-loop 'blocked' terminal.
- `/stop`'s todo force-complete.
- `close.py`'s forced list.

PLAN.md items superseded by this design:
- P1 B1.a: patching stop-completion-gate, which is now folded instead.
- P3: the G4 stop_hook_active bound, the honest_blocked disposition, and B4's hook-written blocked skeleton (D2 and D4).
- P2 B2.d: its timelock edits move into the gate's time-lock clause, with the same logic.

## 5. Open questions (recommended default in brackets)

- Q1. Should /commit, /merge and /push get todo scripts? [No. The git predicate is stronger than self-declared checkboxes, and D10 favours fewer rules.]
- Q2. /do terminal: only `completed`, with 'blocked' becoming a pause? [Yes, applying D2 by analogy; /close already accepts only completed.]
- Q3. Is the pause honoured inside the overnight time-lock window? [No; the human /stop is the exit. Also deny AskUserQuestion while the lock is live, via the existing overnight PreToolUse guard.]
- Q4. D5 scope: one /do *span*, so consent survives pause answers and is cleared on the allowed completion Stop or the next harness slash command, or strictly one model turn? [One span. A strict turn makes /do unfinishable after a pause.]
- Q5. Which commands open a span? [Harness command files minus {allow, restart, checkpoint, tickets}. Built-ins and plugin commands never reset the span. A typed non-gated harness command such as /stop or /spec releases it, and the human judges.]
- Q6. Does /dev-overnight run D6's landing chain in-session, composed into its predicate, or end at the summary and leave each command to the human as its own span? [In-session composition, pending the D6 lane making those command bodies runnable from the overnight span.]
- Q7. /close on a /do-origin task whose do-report is pending, where there are no dev subagents to re-dispatch: what should it do? [Dispatch a dev producer under the same task id (pipeline do, profile do-close) to finish the work. The orchestrator then completes the do-report, which it owns, and closes.]
- Q8. Phase order: completion after auto_commit, so a checkpoint is taken at every Stop attempt and consent and grants are cleaned up only on an allowed Stop? [Yes. This is a D10 choice; revert by moving "completion" to the front of PHASE_ORDER.]
- Q9. Should `pretool-git-privilege-guard` require a `Task-id: <grant.task_id>` trailer in grant-authorized commits, to enforce the committed predicate's anchor at the producer? [Yes, together with P5 A4.d.]
- Q10. Is the transcript-forgery residual (Bash editing the transcript or the /tmp do sidecar) acceptable as out of scope (V6 class)? [Yes.]
