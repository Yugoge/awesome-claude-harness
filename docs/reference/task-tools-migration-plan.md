# Task tools migration plan — TodoWrite → TaskCreate / TaskUpdate / TaskList / TaskGet

> Maintainer-facing planning document.
> Created: 2026-11-17 · Status: **deferred, not scheduled** (plan only, not executed)
> Baseline: every `path:line` below is on master `a21dcbf9`. Re-measure at the commit a lane
> starts from: the counts fix the scale, not a frozen contract.

---

## Not-now banner

**Owner decision (2026-11-17): the migration is a redesign, not a rename, so it is not done now;
this document is its plan.** Nothing in it changes a hook, a command, a test or `settings.json`.
Production stays on TodoWrite: `settings.json:21` (`CLAUDE_CODE_ENABLE_TASKS: "false"`) and
`settings.json:22` (`CLAUDE_CODE_ENABLE_TODO_TOOLS: "1"`) stay as they are.

Evidence labels used below:

- **code**: read on master `a21dcbf9` (`git show`, `git grep`), every citation re-checked when
  this document was written.
- **recorded**: a headless `claude -p` run of CLI 2.1.326 under a scratch `HOME` and
  `CLAUDE_CONFIG_DIR`, with a logging hook on every relevant event. The raw logs are not in the
  tree; lane L0 re-records them as fixtures (§4).
- **static**: read in the CLI 2.1.326 bundle only, never observed.
- **docs**: the official Claude Code documentation as fetched on 2026-11-17 (pages named in place).

Five defects the estimate found do not depend on the migration and are not part of this plan;
each is its own fix: `hooks/posttool-overnight-loop.py` does not check `agent_id`; its `:69` and
`:73` contradict each other; `commands/dev-overnight.md:19` contradicts `:882`;
`tests/replay/replay.py:934-936` returns the old list as `oldTodos` where 2.1.326 returns `[]`
once every step is completed; `commands/dev.md:448`, `:452` ask for a todo-list record TodoWrite
cannot hold.

---

## 0. Status and triggers

**Status: deferred, not scheduled.** No lane below is authorized. The harness keeps TodoWrite until
one of the triggers fires; the owner then decides to start the lanes of §4, at L1 if L0's
recordings were made meanwhile (§1).

**Triggers that start it (either one):**

1. **The CLI deprecates or removes TodoWrite**: a CHANGELOG entry says so, or the upgrade check of
   §1 goes red (TodoWrite no longer loads, or no longer behaves as recorded, under the shipped
   settings on the production model while the Task tools still load there).
2. **A Task-only capability is genuinely needed**: `metadata` on a step, the agent-teams shared
   list, or a `TaskCompleted` gate.

**Not triggers on their own:**

- The docs calling TodoWrite off by default and "legacy" (tools-reference, env-vars). They give no
  removal date.
- Task lists surviving compaction. The hooks read the checklist from the transcript
  (`hooks/lib/todo_canonical.py:272-282`), which already survives.

**Why the "forward-looking" argument is weaker than it looks (docs).** On newer models *both*
families need explicit enabling (tools-reference, "Task tool availability"; interactive-mode, "Task
list"). Migrating does not remove the dependency on `CLAUDE_CODE_ENABLE_TODO_TOOLS=1`.
Precedents for removing or renaming a tool exist, though none dates TodoWrite: `TaskOutput` was
removed in v2.1.277 (tools-reference), and the `Task` tool was renamed `Agent` in v2.1.63
(sub-agents).

**The shipped switch value is recorded, not documented.** The docs spell the switch back to
TodoWrite as `CLAUDE_CODE_ENABLE_TASKS=0` (env-vars, tools-reference). `settings.json:21` uses
`"false"`, which works on 2.1.326 by recording, not by documentation. The upgrade check (§1) runs
with the shipped value for that reason.

### 0.1 Benefits, as they stand

| Benefit | Value today | Why |
|---|---|---|
| Survives compaction and resume | **small** | Hook state is read from the transcript (`todo_canonical.py:272-282`). Survival across compaction is documented; restore on `--resume` is inferred (docs only say the expanded view returns when a session still has tasks). |
| Incremental updates | **net negative** | Smaller payloads and "at most one step completes per call" becomes structural, but calls grow from N+1 to 3N (§3.5). |
| `TaskCreated` / `TaskCompleted` can block (hooks) | **small** | PreToolUse already blocks TaskCreate/TaskUpdate (recorded). The events are a second layer, mainly against subagent writes. |
| `metadata` | **small** | Would give "record it in the todo list" instructions (`commands/dev.md:448`, `:452`; `commands/dev-overnight.md:584`) a place, since TodoWrite content is immutable (`hooks/pretool-todo-validate.py:19`). Discounted: `TaskGet` returns neither `metadata` nor `activeForm` (recorded); they live only in the transcript's TaskCreate input. |
| Forward compatibility | **the main reason** | See above: real, but no removal date and no escape from explicit enabling. |

---

## 1. Meanwhile (no hook change)

Two things are worth doing before any trigger fires. Neither touches a hook. Like every lane, each
starts only when the owner schedules it.

1. **Record Task-tool samples (lane L0).** Run the §5 probes once and commit the recordings as
   fixtures under `tests/fixtures/cli/<ver>/`, so the open facts become recorded
   facts and later lanes build on fixtures instead of memory. About 60 lines of recorder change plus
   one local recording. It needs P15-L1's recorder, which is **not on master at `a21dcbf9`**
   (branch `claude/p15-l1-cli-fixtures`; L0 waits for it to merge).
2. **Check TodoWrite on every CLI upgrade.** Two recorded runs on the production model: one under
   the shipped settings (`CLAUDE_CODE_ENABLE_TASKS="false"`, `CLAUDE_CODE_ENABLE_TODO_TOOLS="1"`,
   `ENABLE_TOOL_SEARCH="false"`), one with `CLAUDE_CODE_ENABLE_TASKS` unset for the second bullet,
   asserting that:
   - TodoWrite loads without ToolSearch and a whole-list write behaves as recorded;
   - the Task family loads in the second run (a task-tracking family is available on the
     production model at all);
   - the CLI CHANGELOG has no TodoWrite or Task-tool deprecation (F12).

   A failing first bullet while the second holds, or a TodoWrite deprecation, is trigger 1; a
   failing second bullet or a Task-tool deprecation is not a reason to migrate and goes to the
   owner as its own decision. The check fits P15-L1's CLI fixture canary once that is on master.

L1 (the dual-read adapter, §4) is the one lane that would pay off even without a migration: it
moves `pretool-subagent-enforce.py:63`, the one checklist reader outside the validator and the
stop gate that walks TodoWrite uses itself instead of `last_todos()`, onto the adapter, and tests
every checklist reader (§7). It is still not scheduled; pulling it forward is an owner decision.

---

## 2. Difficulty and size

**Difficulty: high.**

- **The state model changes; this is not a rename.** Today the checklist is a snapshot: the
  span's last ok TodoWrite. With Task tools it becomes a fold over TaskCreate/TaskUpdate events,
  and the validator moves from whole-list comparison to per-call transition checks (§3.1).
- **The CLI changes subagent isolation.** TodoWrite gives each agent its own list; the Task list is
  shared with foreground subagents in both directions (§3.2).
- **The switch must be atomic, and both families must coexist for a while** (§3.3, §3.4).
- **The cost is mostly tests.** About 75% of the work is unit tests and replay, and they need real
  CLI recordings, which CI cannot make (no key).

### 2.1 Counts (code)

| Measure | Value | Reproduce |
|---|---:|---|
| Files mentioning `TodoWrite` (case-sensitive) | **81** | `git grep -c TodoWrite a21dcbf9 \| wc -l` |
| Lines mentioning `TodoWrite` (case-sensitive) | **323** | `git grep -h TodoWrite a21dcbf9 \| wc -l` |
| Files / lines, case-insensitive | **85 / 345** | `git grep -i …` (adds `tests/INDEX.md`, `tests/TESTING.md`, `tests/scripts/INDEX.md`, `tests/scripts/README.md` and the `*_todowrite_call` helpers) |
| `/dev` canonical steps | **20** | `python3 scripts/todo/dev.py` |
| `/dev-overnight` canonical steps | **23** | `python3 scripts/todo/dev-overnight.py` |

Files that never name TodoWrite but depend on whole-list semantics are counted in the table below:
`hooks/tests/test_posttool_overnight_loop_terminal_gate.py`, `tests/test_dev_todo_accounting.py`,
`tests/replay/drivers/redev.py`.

### 2.2 Size by area

| Area | Files | Est. changed lines | Rename-class | Redesign / medium |
|---|---|---:|---|---|
| Core state and validation hooks | 6 | ~590 | none | redesign: `todo_canonical.py`, `command_span.py`, `pretool-todo-validate.py`; medium: workflow gate, `prompt-workflow.py`, stop gate |
| Other hooks and config | 12 + 1 new | ~110 | `settings.json:21`; launcher rules; orchestrator whitelist; prompt-purity `:74`; spec-block-foreground `:88` | new task-owner guard (~35); `.claude/tasks/` write refusal (new, L2b); `posttool-todo-tracker.py`; `posttool-overnight-loop.py`; `pretool-subagent-enforce.py`; frozen in-flight wording (`pretool-orchestrator-gate.py:199-205`, §3.6) |
| Command text and scripts | ~19 | ~50 (adapter route) / ~110 (reshaped canonical format) | `CLAUDE.md:48`; `dev.md:13`; `dev-command.md:8`; `close.md:103`; `restart.md:123`; `scripts/todo/*.py` docstrings | `dev-overnight.md:882` reset and `:627` Step 11 detour; ledger rows H-008, H-018, H-037, H-051, H-054 |
| Unit tests | 27 + 3 new | ~1,060 + ~360 | `tests/test_restart_command.py` docstring, validator script name | 8 existing files redesigned, frozen in-flight wording (`test_orchestrator_gate_in_flight.py:32-35`, §3.6), new risk tests, recorder extension, a shared recording-based task builder (~150) |
| Replay | ~20 | ~650 | driver step labels | simulator, pipeline, overnight driver, `_deadend`, `test_live_landing` |
| **First estimate** | **~85** | **~2,800** | ~10% of lines | ~90% of lines |
| Missed by the first estimate (review) | see §7 | **+400 to +700** | — | mixed-family spans, Step 11 transition rules, the dispatch gap, porting Rule 7 and `_counted_in_flight`, frozen in-flight wordings, one dead-end case per new refusal, the replay tests the review found |
| **Corrected total** | | **~3,200 to 3,500** | | |

The correction is the reviewer's estimate (30-100 lines per missed item), not an item-by-item
measurement.

**Not affected:** the readers that take only canonical steps (`hooks/lib/obligation.py:1310-1342`,
`hooks/lib/contract_runtime.py:89`, `:146-152`) and the logic of `scripts/todo/*.py` (docstrings
only). **The Codex path is not affected either:** it never calls `pretool-todo-validate.py`; it
mirrors the rules itself (`hooks/pretool-workflow-gate.py:383-389`, "Mirror TodoWrite sequence
rules for Codex update_plan payloads") with its own `run_canonical_todos` (`:117`). Deleting the
TodoWrite branch later (L7) leaves Codex alone.

---

## 3. The hard problems

### 3.1 State as an event fold

**Today (code).** The checklist is the whole-list snapshot of the span's last ok TodoWrite
(`hooks/lib/todo_canonical.py:272-282`, `hooks/lib/command_span.py:438-448`). The validator compares
the old and new whole lists: length, text and order unchanged, at most one step completed per call
(`hooks/pretool-todo-validate.py:13-20`, `:453-478`).

**With Task tools.**

- TaskCreate creates one task, always `pending`, with no status input; TaskUpdate changes one
  `taskId` (recorded schema). The task id appears only in TaskCreate's result,
  `toolUseResult.task.id` (recorded).
- The first-call rule (`todo_canonical.py:232-247`) no longer applies: a create has no status.
- The lock must stay `not_started` until all N creates exist. A naive port of
  `todo_canonical.py:298` unlocks at the first create.
- **The ok rule differs per tool (recorded).** A refused TaskCreate is `is_error: true` with a
  string `toolUseResult` ("Error: …"); a successful one has no `success` field. A TaskUpdate refused
  by a `TaskCompleted` hook has **no** `is_error`, its text starts "TaskCompleted hook feedback",
  its `toolUseResult` is `{"success": false, "updatedFields": []}`, and hooks receive PostToolUse,
  not PostToolUseFailure. `command_span.py:294` (`ok = not is_error`) would count that refused
  completion as done. The fold's rule: a create is ok when it is not `is_error` and has
  `toolUseResult.task.id`; an update is ok when `toolUseResult.success` is true.
- **Each tool result is written twice on 2.1.326 (recorded):** once in the `type: user` record
  with `toolUseResult`, once in a request-blob record without it. The fold reads the `type: user`
  record.
- Ids are not dense: a create refused by a `TaskCreated` hook still consumes an id (recorded: #2
  refused, the next create got #3). Whether a PreToolUse refusal consumes one is only indirectly
  evidenced (F16).
- `status: "deleted"` succeeds (recorded: `success: true, updatedFields: ["deleted"]`), and
  TaskUpdate can also edit subject, activeForm, description, owner, addBlocks and metadata: new
  mutation surface the whole-list rule never had.
- Parallel calls in one message all see the same stale fold at PreToolUse, creates and updates
  alike (F2).
- The fold is paid on every tool call: the workflow gate reads the checklist at each call
  (`todo_canonical.py:262-264` notes the cost), and the lazy reader's premise "the newest record
  is the state" no longer holds (`hooks/tests/test_span_lazy_reader.py`).

**How the guarantees are kept (L1, L2a).**

- A create's subject and activeForm must equal `canonical[k]`, k being the span's ok creates so far.
- An update allows only `pending → in_progress` (every earlier step completed, no other
  in_progress) and `in_progress → completed`. "At most one step per call" becomes structural.
- Deletion and field edits of the span's own tasks are refused (except inside the overnight reset
  window, §3.7).
- Parallel creates or updates in one message are refused, or queued by `tool_use_id` (decided on
  F2's answer).
- Rule 7 (`check_wake_step`, `pretool-todo-validate.py:423-434`) and the in-flight counting
  (`_counted_in_flight`, `:335-360`) are ported to the fold, as is Gate 4's `_started_at`
  (`:262-276`).
- The primary gate stays PreToolUse; `TaskCompleted` is a second layer only.

### 3.2 Subagents: writes into the parent list, and the parent list pushed into subagents

**Today (code).** Isolation rests on three things: the CLI gives each agent its own TodoWrite
list; the hooks read only the main transcript (`hooks/lib/command_span.py:270-275` skips
`isSidechain`); rules let calls with an `agent_id` through (`pretool-todo-validate.py:447-450`,
`posttool-todo-tracker.py:57`, `pretool-orchestrator-gate.py:254`).

**Direction 1: subagents write the parent's list.**

- A foreground subagent's TaskList shows the parent's task #1, and its own TaskCreate becomes the
  parent list's #2 (recorded). The sub-agents page does not mention this.
- Background subagents get no Task tools (docs: the sub-agents page lists TodoWrite, not Task*,
  among their tools; recorded: ToolSearch for them returns no match).
- The 23 harness roles are default-deny: `policies/tool-policy.v1.json` gives none of them Task*
  in `allowed_tools`, enforced by `hooks/lib/policy_registry.py:262-264`, run for every tool
  through the write gate (`hooks/lib/write_gate/__init__.py:77`).
- **The policy does not stop built-in or plugin agents (code).** `hooks/pretool-tool-policy.py:1582-1585`
  exits 0 for an unlisted role: Explore, general-purpose, Plan, plugin agents and calls whose
  `agent_type` does not resolve.
- On a shared list, the subagent bypass (`pretool-todo-validate.py:447-450`, labelled "F1" in the
  code; not fact F1 of §5) turns into an unvalidated write.
- **Agent teams share the leader's list by design (docs, agent-teams page):** a shared task list,
  teammates self-claiming unassigned, unblocked pending tasks, file locking, and the list at
  `~/.claude/tasks/{team-name}/`. `TaskCreated` and `TaskCompleted` inputs carry `teammate_name`
  and `team_name` (hooks page). `settings.json:23` turns agent teams on. The orchestrator's
  checklist steps are exactly the tasks a teammate is built to claim, and a teammate's own
  transcript holds no span, so today's validator would let its writes through.

**Direction 2: the CLI pushes the parent's list into subagents.** A foreground subagent receives the
parent's full task list in a CLI system reminder, with a nudge to use TaskCreate/TaskUpdate
(observed in a cloud session; CLI version not recorded). After a migration the orchestrator's
checklist would enter every foreground subagent's context, including the 23 roles the policy
forbids Task tools: wasted context, and refused calls the reminder itself invites. The harness has
no known switch for the reminder; F15 measures how often and how long, and L5 judges the cost.

**How isolation is kept (L2a).**

- A task-owner guard at PreToolUse refuses TaskCreate/TaskUpdate carrying an `agent_id`, or allows
  a subagent only the ids it created itself.
- Teammate writes are refused by `teammate_name`/`team_name`, or team creation is refused inside a
  gated span; a process whose `CLAUDE_CODE_TASK_LIST_ID` is not this session's list is refused.
- `TaskCreated` is the second layer (its payload carries `agent_id` for a subagent, recorded).
- State is still folded from the main transcript only; foreign or deleted tasks in the CLI list
  are tolerated and never taken for the span's steps.
- The role refusal for Task* names the list as the orchestrator's, so a nudged subagent has a
  reason to stop after one refused call (measured with F15 in L5).

### 3.3 The atomic switch

The two families cannot be enabled together (docs, tools-reference; static: the two `isEnabled`
checks exclude each other). Flipping `settings.json:21` alone wedges every gated command:

- `hooks/pretool-workflow-gate.py:1190` lets only TodoWrite/TodoRead through while the checklist
  is locked, so TaskCreate is locked out;
- `hooks/stop-command-gate.py:297-298` reports "checklist never written" at every stop;
- the launcher rules (`hooks/pretool-launch.py:47`, `hooks/posttool-launch.py:37-38`) match
  `TodoWrite` only, so the validator, tracker and overnight loop silently stop running (fail-open);
- the orchestrator gate allows a non-whitelisted tool once per turn
  (`hooks/pretool-orchestrator-gate.py:87`, `:237-238`), so the second TaskCreate is refused;
- **deferred loading**: every recording loaded Task*/TodoWrite through ToolSearch first, while
  `settings.json:20` sets `ENABLE_TOOL_SEARCH=false`. If Task tools are deferred in production,
  ToolSearch is locked by `:1190` and the session deadlocks (F13).

So the hooks become dual-family first (L1-L4), the flip is one line (L6) and so is the rollback.
`CLAUDE_CODE_ENABLE_TODO_TOOLS=1` stays required for both families on the production model (docs:
the task tools are on by default only on some older models), so the check at
`stop-command-gate.py:288-289` stays as it is. The family is read from the span's own records,
never from the environment (§3.4). `scripts/check-enforcement-evidence.py` recomputes the ledger's
matcher column from the launchers in CI, so launcher rules and ledger rows H-008, H-018, H-037,
H-051 and H-054 change in the same commit.

### 3.4 Mixed-family spans across `/restart`

- `/restart` resumes the session with `claude --resume <session-id>` (`commands/restart.md:32`),
  and the new process reads the settings again. After the L6 flip, a span opened with TodoWrite
  continues with Task tools; a rollback of `:21` does the reverse.
- What is recorded is narrow: within one `-p` turn, changing the **project-level** settings did
  not switch the family (one turn, a smaller model than production). User-level settings and the
  switch between turns are open (F7).
- The adapter (L1) must therefore define a span holding both TodoWrite snapshots and Task events,
  and the validator, the stop gate's first list (D15, `stop-command-gate.py:302-303`) and replay
  must cover it. A family switch decided from the environment reads such a span wrongly. F14
  records the real shape before L1's rule is fixed.

### 3.5 Call-count growth

TaskCreate makes one task per call; TaskUpdate changes one task. The "two updates per step"
(in_progress, then completed) comes from the harness's Rule 2 (`pretool-todo-validate.py:17`), not
from the CLI: the CLI accepts `pending → completed` directly (recorded). Rule 2 stays, because
`pretool-subagent-enforce.py:60-67` and Gate 4's `_started_at` key on the in_progress step.

| | TodoWrite today | Task tools |
|---|---:|---:|
| `/dev` (20 steps) | 21 | 60 |
| `/dev-overnight`, per cycle (23 steps) | ~24 | ~69 |
| Overnight reset | 1 | 23-27 (completed → pending) or 46 (delete + recreate; ~92 per cycle in all) |
| Step 11 detour (`dev-overnight.md:627`), several per cycle | 2 | 4 |
| Hook processes per call | 3 | 3 |

The three processes are `pretool-launch.py` and `pretool-worktree-guard.sh` (PreToolUse) and
`posttool-launch.py` (PostToolUse). The fold read is paid by `pretool-launch.py`'s workflow-gate
rule on every tool call, by its dispatch-gate readers on Agent calls (§7), and by the todo rules on
Task calls (the validator in `pretool-launch.py`; the tracker and the overnight loop in
`posttool-launch.py`); `pretool-worktree-guard.sh` never reads it.

The Step 11 detour today moves `in_progress` back to Step 11 before each graphify dispatch and
restores 12, 13 or 17 before the dev dispatch. Under Task tools that is four updates (13 → pending,
11 → in_progress, 11 → completed, 13 → in_progress), and it needs transitions §3.1's rule set
does not allow (11 completed → in_progress; 12/13/17 in_progress → pending). Either a narrow
Step-11-only transition is added, or L3 rewrites the detour.

**The dispatch gap.** `hooks/pretool-subagent-enforce.py:296-300` lets an Agent call through when
no step is in_progress. Two calls per step switch leave a gap between `k → completed` and
`k+1 → in_progress`; a `/dev-overnight` dispatch in the gap bypasses the cycle contract. One
TodoWrite does the switch atomically today, so the gap is new. Either Agent is refused in the gap,
or the next pending step counts as the current one.

### 3.6 Frozen refusal wordings for in-flight spans

- D15: a span whose loaded command text is no longer `commands/<command>.md` is in flight
  (`pretool-todo-validate.py:307`, `_in_flight`; reused by `pretool-orchestrator-gate.py:177-194`),
  and it is shown the refusal wording of its time.
- The orchestrator gate builds its permanent-block wording from the live `ALWAYS_ALLOWED`
  (`pretool-orchestrator-gate.py:199-205`), and `hooks/tests/test_orchestrator_gate_in_flight.py:32-35`
  pins the old list. Adding the Task tools to the whitelist changes that wording, so the old list
  is frozen for in-flight spans. This is not a rename.
- Every lane that changes a refusal text keeps the old text for in-flight spans.
- L3 rewrites `commands/*.md`; at its merge every running session becomes in flight, and every
  later lane carries the old wordings too. The first estimate did not count this.

### 3.7 Also hard: overnight reset and span scope

**Overnight reset.**

- Today an all-completed TodoWrite triggers the loop (`hooks/posttool-overnight-loop.py:40-45`),
  the reset is one whole-list write (`:69`; `commands/dev-overnight.md:882`), and the whole night is
  one turn.
- Two routes: `completed → pending` (unknown whether the CLI accepts it, F1), or delete and
  recreate.
- `completed → pending` done from the last step backwards keeps the completed steps a prefix after
  every call, and the harness already models a new cycle that way (`pretool-todo-validate.py:262-265`,
  "a step set back to pending and started again, as a new overnight cycle does"). Delete and
  recreate is not forced by the invariant; it costs 23 more calls per cycle and complicates the
  first list and the lock.
- Choose after **both** F1 and F6: if interactive mode clears an all-completed list, the old ids
  are gone and recreate is the only route.
- The reset window cannot be hook state: `posttool-overnight-loop.py:13-14` "writes no state", and
  P1b E7 (`todo_canonical.py:13-15`, `command_span.py:9-12`) keeps no hook copy of the checklist. The
  window is derived from the transcript (for example: open from the TaskUpdate that completed the
  last step while the loop's conditions hold, until N steps are pending again). While it is open,
  the stop gate reports "reset k/N".

**Span scope.** The CLI list belongs to the session, not the command (its id defaults to the
session id: recorded at `tasks/<session-id>/`; static: `ownTaskListId`), and survives compaction
(docs, interactive-mode), so a new command sees an earlier command's tasks. The fold counts only
creates inside the span; earlier tasks are deleted at the command's start or ignored, never held to
the step rules. The warning at `hooks/prompt-workflow.py:1141-1145` ("The previous workflow state
will be lost") stays true for the harness's span state; in the Task family it gains one sentence
saying the CLI list keeps the old tasks.

---

## 4. Lane plan

**Rules.**

- Until L6, production runs TodoWrite and `settings.json:21` is untouched; the harness works after
  every lane.
- One lane is one issue, handled by one subagent (CLAUDE.md, Production Lesson 13).
- **Preconditions:** P15-L1's recorder must be on master before L0 (branch
  `claude/p15-l1-cli-fixtures`, not merged at `a21dcbf9`). P15-L2/L3 touch
  `hooks/tests/test_command_span.py`, `hooks/tests/test_stop_command_gate.py` and
  `hooks/tests/_fixtures_obligation_terminal.py`; L1 and L2 go after them.

**Order:** L0 → L1 → {L2a, L2b, L3 in parallel} → L4 → L5 → L6 → (after a CLI deprecation) L7.

### L0 — probes and recordings

- Extend the recorder: Task tools on, PostToolUse/TaskCreated/TaskCompleted registered, ids and
  statuses not redacted. Run every §5 probe and write `tests/fixtures/cli/<ver>/`.
- Record under production conditions: the production model, `ENABLE_TOOL_SEARCH=false`, the
  harness hooks attached. The recordings so far used a smaller model, loaded the tools through
  ToolSearch and ran without harness hooks.

**Acceptance:** every §5 fact but F12 (a CHANGELOG read) has a recorded answer; the fixtures load
through the `cli_record` loader; no hook is changed.

### L1 — dual-family state adapter (dual read)

- `command_span` / `todo_canonical` produce one shape, `[{id, content, activeForm, status}]`, from
  either the TodoWrite snapshot or the fold of the span's TaskCreate/TaskUpdate events, and from a
  mixed span (§3.4). The family is read from the span's records.
- Only tasks created inside the span count. Ok rules as in §3.1 (create: not `is_error` and a
  `toolUseResult.task.id`; update: `toolUseResult.success`), read from the `type: user` record.
- `before` (the state before a given tool use) is supported; `first_list()` is added; the lock stays
  `not_started` until N creates exist.
- `pretool-subagent-enforce.py:60-67` walks TodoWrite uses itself (`:63`) and moves onto the
  adapter; the validator (`:267`, `:342`) and the stop gate's first list
  (`stop-command-gate.py:302`) do too and move in L2a and L2b. The readers already on it
  (`hooks/lib/requirement_round.py:156`, `span.last_todos()`;
  `hooks/pretool-block-background-tasks.py:74-88` and
  `hooks/pretool-spec-block-foreground-agent.py:32-40`, `checklist().todos` with the canonical
  fallback) get fold tests, including a partial list (k of N created: /spec's `total` stays N).
- Production still runs TodoWrite.

**Acceptance:** every existing test passes unchanged; new fold tests built on L0's recordings
cover deleted tasks, a failed update, tasks left by an earlier span, ignored subagent records and a
mixed span; an upper-bound test on the workflow gate's per-call read cost.

### L2a — write-side validation and isolation

- `pretool-todo-validate.py` gains per-call checks for TaskCreate/TaskUpdate (§3.1), the ports of
  Rule 7, `_counted_in_flight` and `_started_at`, and, if §3.5's narrow Step 11 transition is chosen,
  that rule. The TodoWrite branch stays as it is.
- The task-owner guard and the teammate rule (§3.2).
- The dispatch gap closed in `pretool-subagent-enforce.py:296-300` (§3.5).
- The reset window derived from the transcript, admitting the reset's deletes or status rollbacks
  only inside it (§3.7).

**Acceptance:** the shared builder has unit tests for both families; risk tests cover a subagent
write, a teammate write, deletion, field edits, parallel creates and updates, tasks left by an
earlier span and a dispatch in the gap; every new refusal has a dead-end case; replay results are
unchanged with `CLAUDE_CODE_ENABLE_TASKS=false`.

### L2b — gates and registration

- Workflow gate: the four Task tools pass while locked (`pretool-workflow-gate.py:1190`; ToolSearch
  too if F13 says the tools are deferred); the lock holds until N creates exist; the remedy text
  (`:1216`) is worded per family.
- Orchestrator gate: the four tools join `ALWAYS_ALLOWED` (`pretool-orchestrator-gate.py:66-79`) and
  `CLAUDE.md:48`, with the old wording frozen for in-flight spans (§3.6).
- Launchers: TaskCreate/TaskUpdate added next to TodoWrite (`pretool-launch.py:47`,
  `posttool-launch.py:37-38`), with ledger rows H-008, H-018, H-037, H-051 and H-054 in the same
  commit.
- Stop gate: the `CLAUDE_CODE_ENABLE_TODO_TOOLS` check (`stop-command-gate.py:288-289`) unchanged;
  `:292-306` reads the adapter, and a partial list reports "k of N created".
- `posttool-todo-tracker.py` and `posttool-overnight-loop.py` handle each family.
- Writes to `~/.claude/tasks/` by Write, Edit or Bash are refused: only the CLI writes the store.
  This is new protection, not a rename: `pretool-bash-safety.sh:1788` blocks only `rm`/`mv`, and
  its `.claude/todos/` rule guards, and `pretool-overnight-hook-guard.py:96` exempts from the
  overnight worktree boundary, a directory 2.1.326 no longer writes (docs, claude-directory;
  recorded: no `todos/` after a TodoWrite run); `.claude/tasks/` is not added to that exemption.

**Acceptance:** `scripts/check-enforcement-evidence.py --claims` passes; a test shows N TaskCreate
and 2 TaskUpdate in one turn are not refused by the orchestrator gate; the stop gate reports
"k of N created" on a partial list; an in-flight span sees the old wordings.

### L3 — instruction text per family

- `hooks/prompt-workflow.py`'s `checklist_message` and progress hints (`:304-352`, `:1118-1131`)
  are worded per family. The header line "CHECKLIST PRE-INITIALIZED for /X:" stays, since
  `_recorded_start` (`:1878`) splits on it. In the Task family, the warning at `:1141-1145` gains
  its sentence (§3.7).
- Command text: `commands/dev-overnight.md:882` (reset) and `:627` (Step 11 detour), `:21`, `:27`;
  `commands/dev.md:13`; `commands/dev-command.md:8`; `commands/restart.md:123`; `commands/close.md:103`.
- Docs: `docs/how-it-works.md:87`; `ARCHITECTURE.md:113`, `:150`, `:324`; `README.md:162`.

**Acceptance:** TodoWrite-family output is byte-identical to today's; Task-family text parses in the
replay pipeline; in-flight spans keep the old wordings (§3.6).

### L4 — replay in both families

- `tests/replay/replay.py` simulates the shared store (`tasks/<list-id>/<id>.json`, `.lock`,
  `.highwatermark`; `tasks/{team-name}/` for a team), the `TaskCreated`/`TaskCompleted` events and
  CLI-shaped `toolUseResult`.
- `tests/replay/pipeline.py:204-251` works per call; the overnight reset
  (`tests/replay/drivers/overnight.py:774-786`, `:2077-2087`) and `_deadend`'s X6 case
  (`tests/replay/drivers/_deadend.py:149-182`) are rewritten; `sites.py` and `recovery.py` learn
  Task calls.
- `test_live_landing.py` step labels stop naming the tool, and it runs "baseline TodoWrite → landed
  hooks"; `test_no_dead_end.py`, `test_live_arming.py` and `test_faults.py` gain Task cases; a
  mixed-span scenario is added; `suite.py`'s shard cost is re-measured.

**Acceptance:** the whole replay suite passes in both families; the landing scenario and the
mixed-span scenario pass.

### L5 — per-process canary

- Choose the canary route on F5: a `--settings` override, or a separate `CLAUDE_CONFIG_DIR` copy.
  Run one `/dev` and one `/dev-overnight` of at least two cycles live, and one `/restart` across the
  family switch. The shipped `settings.json:21` is untouched.

**Acceptance:** a live end-to-end run, not replay alone; the stop gate blocks and passes where it
should; no subagent write to the span's tasks is observed; the overnight reset completes at least
two cycles; the cost of the parent list pushed into harness-role subagents (F15) is measured and
judged.

### L6 — default flip

- Delete `settings.json:21`; keep `:22`; re-evaluate `:23` (agent teams). No `permissions.allow` entry
  is needed at `:171`: the Task tools and TodoWrite need no permission (docs, tools-reference).

**Acceptance:** replay and the canary re-run under the default settings; rollback is restoring
`:21` alone (the hooks are still dual-family, and the mixed spans a rollback creates are covered
by L1/L4).

### L7 — remove the TodoWrite path

- Only after the CLI announces TodoWrite's deprecation. The TodoWrite branches go; the Codex mirror
  stays (§2.2).

**Acceptance:** `git grep TodoWrite` hits only the Codex mirror and history documents;
`tests/test_codex_workflow_gate.py` passes.

---

## 5. Open facts and their probes

**Probe setup.** Scratch directories only, never the real home:

```
S=<scratch dir>; mkdir -p "$S/home/.claude"
HOME="$S/home" CLAUDE_CONFIG_DIR="$S/home/.claude" claude -p \
  --settings <recording-settings.json> \
  --output-format stream-json --verbose "<prompt>"
```

`<recording-settings.json>` logs the stdin of PreToolUse, PostToolUse, PostToolUseFailure,
TaskCreated, TaskCompleted, SubagentStart, SubagentStop and Stop. Each probe checks three places:
the hook log, the transcript, and `$S/home/.claude/tasks/<list-id>/`. Probes marked *interactive*
run in a tmux session instead of `-p`. L0 runs them under production conditions (§4).

| # | Fact | Decides | Probe | Evidence so far |
|---|---|---|---|---|
| F1 | Does TaskUpdate accept `completed → pending`? | reset route (§3.7) | create 2 tasks, complete both, set #1 back to pending; read `toolUseResult` and `1.json` | none |
| F2 | Several TaskCreate **or TaskUpdate** in one message: concurrent? PreToolUse order? id assignment? | parallel-call rule (§3.1) | ask for 3 TaskCreate in one message, then 2 TaskUpdate; log PreToolUse `tool_use_id` with timestamps | none |
| F3 | Can a foreground subagent update or delete a parent task? | task-owner guard scope | parent creates #1; a foreground general-purpose subagent sends `TaskUpdate status:"deleted"` on #1 | recorded: a subagent create became the parent's #2. Code: the policy does not stop built-in agents (`pretool-tool-policy.py:1582-1585`) |
| F4 | Do teammates share the leader's list under the harness settings? | teammate rule (§3.2) | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, start a teammate, read its environment and TaskList | docs (agent-teams): shared list, self-claim, file locks, `tasks/{team-name}/`; not recorded |
| F5 | Does `--settings` override a user-level `CLAUDE_CODE_ENABLE_TASKS=false`? | canary route (L5) | user settings `false`; `--settings '{"env":{"CLAUDE_CODE_ENABLE_TASKS":"true"}}'`; does TaskCreate load? | docs (settings precedence; tools-reference shows `--settings` with `env`); runtime not recorded |
| F6 | *Interactive:* is the task store cleared once every task is completed? | reset route; any store reader | complete every task, wait for a refresh, list `tasks/<list-id>/` | static only; in `-p` mode the files stay (recorded) |
| F7 | *Interactive:* are settings re-read between turns, switching the family? | length of the dual-family period | turn 1 uses TodoWrite; change user settings; turn 2 checks the tools | recorded: no switch within one `-p` turn after a project-level change |
| F8 | Shape of a failed TaskUpdate on a missing id (`is_error`? `toolUseResult.success`?) | ok rule (§3.1) | TaskUpdate on #99 | recorded for a hook-refused update (no `is_error`, `success: false`); missing-id case static only |
| F9 | `TaskCreated`/`TaskCompleted`: full input, matcher support, fired on delete and reset? PostToolUse shape after a blocked `TaskCompleted` | second-layer design | run each event once with exit 0 and once with exit 2 | docs: both can block, no matcher; recorded fields `task_id`, `task_subject`, `task_description`, `agent_id`; docs add `teammate_name`, `team_name` |
| F10 | TaskCreate schema variants; are `activeForm` and `metadata` kept? | whether the adapter can read activeForm back | create with both, read back with TaskGet and `1.json` | recorded: both accepted on input, TaskGet returns neither |
| F11 | *Interactive:* does `/clear` change the list id? Does `--resume` restore the list? | span scope; `/restart` | TaskList before and after `/clear`; `claude --resume` | static (`ownTaskListId`); docs state survival across compaction; restore on resume inferred only |
| F12 | Is there a deprecation or removal date for TodoWrite? | trigger 1 | read the CLI CHANGELOG at each upgrade | docs: off by default, "legacy" (env-vars); no date |
| F13 | With the production model and `ENABLE_TOOL_SEARCH=false`, are Task tools loaded directly or deferred? | workflow-gate deadlock (§3.3) | shipped env plus `CLAUDE_CODE_ENABLE_TASKS=1`; does TaskCreate run without ToolSearch? | recordings so far all went through ToolSearch, on a smaller model |
| F14 | After the flip, what does a resumed TodoWrite span look like? | mixed-span rule (§3.4) | in a scratch copy of the harness: open a span with TodoWrite, flip `:21`, `claude --resume`, continue | none |
| F15 | Is the parent's task-list reminder injected into harness-role subagents, how often, how long? | cost of direction 2 (§3.2) | parent creates N tasks, dispatches a harness role; read the subagent transcript | observed once in a cloud session, CLI version unrecorded |
| F16 | Does a TaskCreate refused at PreToolUse consume an id? | dense-id assumptions in the fold | refuse one create with exit 2, then create again; read the id and `.highwatermark` | blocking recorded; no-consumption only indirect (store state) |

---

## 6. Evidence cross-links (docs)

All fetched 2026-11-17 from `https://code.claude.com/docs/en/`:

- `tools-reference.md` — Task tool availability, TodoWrite off by default, `TaskOutput` removal,
  `--settings` with `env`, no permission needed.
- `env-vars.md` — `CLAUDE_CODE_ENABLE_TASKS`, `CLAUDE_CODE_ENABLE_TODO_TOOLS`, TodoWrite as legacy.
- `interactive-mode.md#task-list` — list ids, `CLAUDE_CODE_TASK_LIST_ID`, compaction, resume view.
- `hooks.md` — `TaskCreated`, `TaskCompleted` (blocking, inputs, reason returned as tool result).
- `sub-agents.md` — background subagents' tools; `Task` renamed `Agent` in v2.1.63.
- `agent-teams.md` — shared task list, self-claim, file locks, `~/.claude/tasks/{team-name}/`.
- `settings.md` — settings precedence (`--settings` above user, project, local).
- `claude-directory.md` — `tasks/`; `todos/` as a legacy directory.

---

## 7. Code sites (path:line on master `a21dcbf9`)

Stated as of `a21dcbf9`; re-check each before a lane edits it.

**Settings.** `settings.json:20` (`ENABLE_TOOL_SEARCH`), `:21` (`CLAUDE_CODE_ENABLE_TASKS`), `:22`
(`CLAUDE_CODE_ENABLE_TODO_TOOLS`), `:23` (agent teams), `:171` (`TodoWrite` in `permissions.allow`).

**State readers.**
- `hooks/lib/todo_canonical.py:13-15` (E7), `:232-247` (first-call rule), `:262-264` (read cost),
  `:272-282` (`todos`), `:292-298` (`lock`)
- `hooks/lib/command_span.py:9-12` (E7), `:270-275` (sidechain skip), `:290-296` (ok =
  `not is_error`, `:294`), `:438-448` (`last_todos`)

**Checklist readers L1 covers (of these, only subagent-enforce walks TodoWrite uses itself).**
- `hooks/pretool-subagent-enforce.py:60-67` (`_current_step_label`; `:63` reads TodoWrite uses),
  `:296-300` (fail-open)
- `hooks/lib/requirement_round.py:156` (`span.last_todos()`)
- `hooks/pretool-block-background-tasks.py:74-88` (`checklist().todos`, `:81-85`)
- `hooks/pretool-spec-block-foreground-agent.py:32-40` (`checklist().todos`, `:35-38`), `:88` (wording)

**Validator.** `hooks/pretool-todo-validate.py:13-20` (rules), `:262-276` (`_started_at`), `:307`
(`_in_flight`), `:335-360` (`_counted_in_flight`), `:423-434` (`check_wake_step`, Rule 7), `:447-450`
(agent bypass), `:453-478` (whole-list compare).

**Gates.**
- `hooks/pretool-workflow-gate.py:143` (`build_next_todowrite_call`), `:172` (`next_todowrite_call`), `:1190` (lock
  allow-list), `:1216` (remedy); Codex, unaffected: `:117`, `:383-389`
- `hooks/pretool-orchestrator-gate.py:66-79` (`ALWAYS_ALLOWED`), `:87`, `:177-194` (`in_flight`),
  `:199-205` (permanent-block wording), `:237-238`, `:254` (subagent exit)
- `hooks/stop-command-gate.py:283-287`, `:288-289`, `:292-306`
- `hooks/pretool-orchestrator-prompt-purity.py:74`

**Launchers and ledger.** `hooks/pretool-launch.py:47`; `hooks/posttool-launch.py:37-38`;
`docs/ENFORCEMENT-LEDGER.md:231` (H-008), `:240` (H-018), `:250` (H-037), `:257` (H-051), `:258`
(H-054).

**PostToolUse.** `hooks/posttool-todo-tracker.py:56-65`; `hooks/posttool-overnight-loop.py:13-14`,
`:40-45`, `:69`.

**Prompt text.** `hooks/prompt-workflow.py:304-352`, `:1118-1131` (`:1126-1127` the instruction),
`:1141-1145`, `:1878` (`_recorded_start`).

**Isolation.** `hooks/pretool-tool-policy.py:1582-1585`; `hooks/lib/policy_registry.py:262-264`;
`hooks/lib/write_gate/__init__.py:77`; `policies/tool-policy.v1.json` (23 roles);
`hooks/lib/overnight.py:33-35`.

**State-directory rules (bash-safety guard; overnight-hook-guard exemption).**
`hooks/pretool-bash-safety.sh:1786-1792`;
`hooks/pretool-overnight-hook-guard.py:93-97`.

**Command text and docs.** `CLAUDE.md:48`, `:49`; `commands/dev.md:13`, `:448`, `:452`;
`commands/dev-command.md:8`; `commands/close.md:103`; `commands/restart.md:32`, `:123`;
`commands/dev-overnight.md:21`, `:27`, `:584`, `:627`, `:882`; `docs/how-it-works.md:87`;
`ARCHITECTURE.md:113`, `:150`, `:324`; `README.md:162`.

**Unit tests.**
- Redesign: `hooks/tests/test_checklist_record.py`, `test_span_lazy_reader.py`,
  `test_overnight_wake.py`, `test_dual_runtime_lifecycle_e2e.py`, `test_command_span.py`,
  `_fixtures_obligation_terminal.py`, `test_posttool_overnight_loop_terminal_gate.py`;
  `tests/test_dev_todo_accounting.py`
- Frozen wording: `hooks/tests/test_orchestrator_gate_in_flight.py:32-35`
- Set `CLAUDE_CODE_ENABLE_TODO_TOOLS` (added by the review): `tests/replay/test_typed_corrections.py:81`,
  `hooks/tests/test_close_rating_no_tool.py:83`, `hooks/tests/test_close_stalled_stop.py:92`,
  `hooks/tests/test_overnight_window.py:82`

**Replay.**
- `tests/replay/replay.py` (simulator), `tests/replay/pipeline.py:204-251`,
  `tests/replay/drivers/overnight.py:774-786`, `:2077-2087`, `tests/replay/drivers/_deadend.py:149-182`,
  `tests/replay/drivers/redev.py`, `tests/replay/test_live_landing.py`, `tests/replay/suite.py`
- Medium: `tests/replay/sites.py:1158-1160`, `tests/replay/recovery.py:325-329`,
  `tests/replay/drivers/dev_command.py:313-319`, `tests/replay/drivers/clean.py:188-190`
- Added by the review: `tests/replay/test_no_dead_end.py:42-43`, `tests/replay/test_live_arming.py:143`,
  `:280`, `tests/replay/test_faults.py:319`

**Unaffected.** `hooks/lib/obligation.py:1310-1342`; `hooks/lib/contract_runtime.py:89`,
`:146-152`; `scripts/todo/*.py` (docstrings only); `tests/test_codex_workflow_gate.py`.
