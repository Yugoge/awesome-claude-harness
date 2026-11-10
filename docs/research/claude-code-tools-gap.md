# Claude Code tool changes (Task tools, SendMessage, Monitor) and the harness gaps

> Research only, 2026-11-10. No harness file was changed and no hook was run against a real `~/.claude`, `$HOME` or global git config: every hook replay below ran with `HOME` and `CLAUDE_HOME` pointing at a throwaway copy of this repository.
> Measured against Claude Code **2.1.322**, the installed CLI (`claude --version`), at master `3859589`.

## How to read the claims

Every claim is tagged.

- **[V]** (verified) means one of these sources states it, or it was observed:
  - the official docs, or a quoted CHANGELOG line;
  - the installed CLI's own tool schema or a literal string in its binary;
  - an experiment run in this session;
  - a repository `file:line`.
- **[I]** (inferred) means it is a reading of indirect evidence. That includes any reading of minified CLI code.

| Short form | Source |
|---|---|
| `CL x.y.z` | A line under that version heading in `CHANGELOG.md` (github.com/anthropics/claude-code, main, fetched 2026-11-10). The changelog is newest-first, so "first mention" means the oldest line that names the thing. |
| `docs:<page>#<anchor>` | code.claude.com/docs/en/<page> (fetched 2026-11-10) |
| `schema` | The tool's JSON schema as loaded by this 2.1.322 session |
| `bin` | `strings` of `/opt/claude-code/bin/claude` (2.1.322). Quoted fragments are minified JavaScript. |
| `exp` | An experiment run in this session (details in the [Appendix](#appendix-experiments-run-for-this-report)) |
| `path:line` | This repository at `3859589` |

## Summary

1. **On current models TodoWrite only exists because the harness switches it on.**
   - The task-tracking tools (TaskCreate, TaskGet, TaskUpdate, TaskList and TodoWrite) are offered by default only on Claude 3.x, Opus 4.0–4.7, Sonnet 4.0–4.6 and Haiku 4.5 (CL 2.1.268) [V].
   - Where they are offered, the default is the four Task tools. `CLAUDE_CODE_ENABLE_TASKS=0` gives TodoWrite instead (docs:tools-reference, TodoWrite row) [V].
   - The harness sets both switches: `CLAUDE_CODE_ENABLE_TASKS: "false"` and `CLAUDE_CODE_ENABLE_TODO_TOOLS: "1"` (`settings.json:21-22`) [V]. That is the owner's local switch, and it works on 2.1.322. The binary enables TodoWrite under `!r0()&&B9()`, where `r0` is false exactly when `CLAUDE_CODE_ENABLE_TASKS` is false, and `B9` is true when `CLAUDE_CODE_ENABLE_TODO_TOOLS` is true (bin) [I].
2. **Neither list is binding, and Claude Code stops no turn for open tasks.**
   - The task list only reminds: after 10 turns without task use the model gets a "gentle reminder" (bin `TURNS_SINCE_WRITE:10,TURNS_BETWEEN_REMINDERS:10`; the reminder arrived in this session) [V].
   - Stop hook input carries no task fields (docs:hooks#stop-input) [V].
   - So binding stays a Stop hook's job, and no binding script becomes redundant.
   - The one native blocking point is a `TaskCompleted` hook. Exit 2 refuses a `TaskUpdate` to completed (docs:hooks#taskcompleted; CL 2.1.33) [V].
3. **The task list's state lives on disk, not in the transcript.**
   - Each task is `~/.claude/tasks/<listId>/<id>.json` [V exp]. `listId` is `CLAUDE_CODE_TASK_LIST_ID`, else a team name, else the session id (bin `_T()`) [I].
   - The transcript keeps each call's input. The result keeps only `{task:{id,subject,description}}` or `{success,taskId,updatedFields,statusChange}` [V exp].
   - Foreground subagents write to the same list. A research subagent of this session received reminders that listed this session's tasks [V exp], and docs:tools-reference says a subagent has the tools when the session has them [V].
   - Background subagents get TodoWrite but not the Task tools (docs:sub-agents#available-tools) [V].
4. **The harness's own gates would break a move to the Task tools on the first turn.**
   - `hooks/pretool-orchestrator-gate.py` limits every tool outside its whitelist to once per turn (`:47-60`, `:68`). It blocked the second TaskCreate, the second TaskUpdate and the second Monitor of a turn [V exp].
   - `hooks/pretool-workflow-gate.py` lets only TodoWrite and TodoRead through while a checklist is unstarted (`:1150-1163`) [V].
   - Every todo reader parses TodoWrite records (`hooks/lib/command_span.py:438-448`, `hooks/lib/todo_canonical.py:261-298`) [V].
5. **SendMessage** is blocked for the main agent except for `/restart`'s exact `restart-v1` message (`hooks/pretool-block-background-tasks.py:130-152`).
   - Allowing it changes more than lesson 16. A resumed child does new work without passing the `Agent`-matcher dispatch gate (`settings.json:503-508`, H-090) [V].
   - Since CL 2.1.224 it can also reach other sessions and machines [V].
   - A policy that keeps the `/restart` guarantee and admits ordinary sends is in [section 5](#5-sendmessage).
6. **Monitor is inherently background, yet the no-background hook lets it through.** Only the once-per-turn rule limits it [V exp]. Its shell commands go through Bash hooks only from CL 2.1.314 [V]. Recommendations for Monitor and the other newer tools are in [section 6](#6-monitor-and-the-other-newer-tools).

**Recommendation for D18:** design A now: keep TodoWrite, pin the switch, and fix the gate inconsistencies listed in section 6. Prepare design B, the reader adapter, as the move to take when TodoWrite is deprecated. Design C, a native TaskCompleted-driven pipeline, is not recommended yet. Details are in [section 4](#4-migration-to-the-task-tools).

> Numbering note: `D18` already labels a different decision in the code: `hooks/pretool-overnight-hook-guard.py:2487` ("option (b) of P1c review 1, by D18"), `hooks/pretool-tool-policy.py:1507` and `hooks/tests/test_overnight_wake.py:377`. If this decision is recorded as D18, the old references become ambiguous.

---

## 1. Tool inventory

### 1.1 How a hook sees a tool

- **PreToolUse and PostToolUse** fire for every tool. The payload has the common fields (`session_id`, `transcript_path`, `cwd`, `hook_event_name`) plus `tool_name`, `tool_input` and, on PostToolUse, `tool_response`. A subagent's call also carries `agent_id` and `agent_type` (docs:hooks#common-input-fields) [V].
- **Main agent or subagent:** the harness tells them apart by a truthy `agent_id` (`hooks/pretool-block-background-tasks.py:113-118`; `hooks/lib/subagent.py`, `is_subagent_context`) [V].
- **Transcript:** every call is an assistant `tool_use` block followed by a user `tool_result`. The result row carries a `toolUseResult` object [V exp; shapes in [section 2.4](#24-how-hooks-and-the-stop-gate-would-read-task-state)].
- **Files on disk:** only the task list has its own state files (`~/.claude/tasks/…`). TodoWrite is held in memory per agent (bin `e.todos.set(n,…)` with `n=e.agentId??<sessionId>`) [I]. The docs call `~/.claude/todos/` "Legacy directories not written by current versions" (docs:claude-directory) [V].

### 1.2 Inventory

"Harness today" combines two hooks:

- **Gate** is `pretool-orchestrator-gate.py` for the main agent: *whitelist* (`:47-60`), *1/turn* (`:68`, the once-per-tool-per-turn budget) or *permanent* (`:62-65`).
- **BG** is `pretool-block-background-tasks.py`: *block*, *pass*, or *rib* (requires `run_in_background: false`).

Subagents are exempt from both (`pretool-orchestrator-gate.py:188`; `pretool-block-background-tasks.py:117`) [V].

| Tool | What it does | Arrived | Input fields (`tool_name` = the tool's name) | Harness today |
|---|---|---|---|---|
| TodoWrite | Replaces the agent's whole checklist on every call | Before 2.x (`/todos` command, CL 1.0.94). Off by default since the task system (CL 2.1.16 / 2.1.19); model-gated since CL 2.1.233 [V] | `todos[]: {content, status: pending\|in_progress\|completed, activeForm}` (docs:agent-sdk/typescript) [V] | Gate whitelist (`:49`). PreToolUse `pretool-todo-validate.py` and PostToolUse `posttool-todo-tracker.py` + `posttool-overnight-loop.py` (`settings.json:468-475`, `:551-562`) [V] |
| TaskCreate | Creates one task (status `pending`), returns an id | CL 2.1.16 "Added new task management system, including … dependency tracking" [V] | `subject`, `description` (required); `activeForm?`, `metadata?` (schema) [V] | Gate 1/turn [V exp]; BG pass [V exp]. No hook names it [V] |
| TaskUpdate | Changes status/fields/deps of one task; `deleted` removes it | CL 2.1.16; delete added in CL 2.1.20 [V] | `taskId` (required); `status? pending\|in_progress\|completed\|deleted`, `subject?`, `description?`, `activeForm?`, `owner?`, `metadata?` (merge; null deletes a key), `addBlocks?`, `addBlockedBy?` (schema) [V] | Gate 1/turn [V exp] |
| TaskList | Summary of every task: id, subject, status, owner, open blockedBy | CL 2.1.16 (first named in CL 2.1.119) [V] | `{}` (schema) [V] | Gate 1/turn [V exp] |
| TaskGet | One task in full | CL 2.1.16 [I] | `taskId` (schema) [V] | Gate 1/turn [I] |
| TaskStop | Stops a background task (Bash, Monitor), a teammate or a named background agent | First named in CL 2.1.30 [V] | `task_id?` (`shell_id?` deprecated) (schema) [V] | Gate 1/turn [I]. Named only in prompt-purity's advisory regex (`hooks/pretool-orchestrator-prompt-purity.py:75-77`) [V] |
| TaskOutput | Read a background task's output | CL 2.0.64; **removed in CL 2.1.277** ("Claude reads a background task's output file with Read instead") [V] | — | Not referenced [V] |
| Agent (alias `Task`) | Runs a subagent | Renamed from `Task`; the rename version was not found. The SDK says "`Task` is still accepted as an alias" (docs:agent-sdk/typescript#agent) [V] | `description`, `prompt`, `subagent_type?`, `model?`, `effort?`, `run_in_background?`, `name?`, `isolation? worktree\|remote` (docs:agent-sdk/typescript) [V]. PostToolUse `tool_response.status` is `completed` or `async_launched`, with `agentId` (docs:hooks) [V] | Gate whitelist; BG rib (`:172-179`). Dispatch gate on matcher `Agent` only (`settings.json:503-508`) [V] |
| SendMessage | Message or **resume** a subagent by name/agentId; teammates; other sessions | Resume: CL 2.1.77 "auto-resumes stopped agents in the background". Cross-session: CL 2.1.224 [V] | `to`, `message` (required); `summary?`, `notify_when_idle?` (schema) [V] | BG block except a validated `/restart` send (`:130-152`). Gate 1/turn except restart-authorized (`:199-207`). PostToolUse `posttool-restart-sendmessage.py` (`settings.json:613-617`) [V] |
| ListAgents | Lists messageable subagents, teammates and sessions | CL 2.1.224 [V] | `{}` [I] | Gate 1/turn [I] |
| Monitor | Background script or WebSocket; each stdout line or frame is a notification; ends on exit, expiry or TaskStop | CL 2.1.98 "Added Monitor tool for streaming events from background scripts" [V] | `description`, `timeout_ms` (required; default 300000, capped at 1800000); `command?` or `ws?{url, protocols?}` (schema) [V] | Gate 1/turn [V exp]; **BG pass** [V exp] |
| Workflow | Script that orchestrates "tens to hundreds of agents in the background" | Named in CL 2.1.152; launched in CL 2.1.154 [V] | `script?` \| `name?` \| `scriptPath?`, `args?`, `resumeFromRunId?` (docs:workflows) [V] | BG block, no `/allow` path (`:141-152`) [V exp]; `/do` lifts it (`:120-121`) [V] |
| ScheduleWakeup | Self-paced `/loop` wake (60–3600 s) | First named in CL 2.1.248; `/loop` in CL 2.1.71 [V] | `delaySeconds?`, `prompt?`, `reason?`, `noop?`, `stop?` (docs:agent-sdk/typescript) [V] | Gate whitelist. `pretool-tool-policy.py:1529-1554` refuses a prompt that types a harness command, except the overnight wake [V] |
| CronCreate / CronDelete / CronList | Session-scoped cron prompts; recurring jobs expire after 7 days | CL 2.1.71 [V] | `cron`, `prompt`, `recurring?`, `durable?` ("Has no effect" here, schema) / `id` / `{}` [V] | Gate whitelist. The overnight wake depends on them (`commands/dev-overnight.md:58-66`, `hooks/stop-command-gate.py:756-762`) [V] |
| EnterWorktree / ExitWorktree | Create or enter a worktree / leave it | ExitWorktree in CL 2.1.72; `path` in CL 2.1.105 [V] | `name?`, `path?` / `action: keep\|remove`, `discard_changes?` (schema) [V] | `pretool-block-enterworktree.sh` (`settings.json:477-483`) and Gate 1/turn [V] |
| Skill | Runs a skill or slash command | First named in CL 2.1.0; built-in commands via Skill since CL 2.1.108 [V] | `skill`, `args?` (schema) [V] | Gate whitelist. `Skill(<cmd>:*)` denies in `settings.json:250-269` [V] |
| PushNotification | Phone or desktop push | CL 2.1.110 [V] | `message`, `status: "proactive"` (schema) [V] | Gate 1/turn [I] |
| ToolSearch | Loads deferred tool schemas | Named in CL 2.1.20 (MCPSearch in 2.1.7) [V] | `query`, `max_results` (schema) [V] | Gate 1/turn [I]. `ENABLE_TOOL_SEARCH: "false"` (`settings.json:20`) [V] |
| EnterPlanMode / ExitPlanMode | Plan mode | — | — | Gate permanent [V] |
| SubagentHandback | Carries a subagent's final report to its parent; **auto mode only** | CL 2.1.271 (docs:tools-reference) [V] | `message` [V] | Not referenced. See [section 6](#6-monitor-and-the-other-newer-tools) |

### 1.3 Hook events for tasks and agents

The binary's list of hook events includes TeammateIdle, TaskCreated, TaskCompleted, SubagentStart, SubagentStop, Stop and StopFailure (bin) [V].

| Event | Added | Payload beyond the common fields | Can block |
|---|---|---|---|
| TaskCreated | CL 2.1.84; blocking documented in CL 2.1.89 [V] | `task_id`, `task_subject`, `task_description?`, `teammate_name?`, `team_name` (deprecated) (bin schema `VW`) [V] | Yes. Exit 2 deletes the task and returns the message as a tool error (docs:hooks) [V] |
| TaskCompleted | CL 2.1.33 [V] | Same as TaskCreated (bin schema `BW`) [V] | Yes. Exit 2 refuses the TaskUpdate to completed and feeds stderr back. It also fires when a teammate ends its turn with in_progress tasks (docs:hooks#taskcompleted) [V] |
| TeammateIdle | CL 2.1.33 [V] | `teammate_name`, `team_name` | Exit 2 keeps the teammate working [V] |
| SubagentStart | CL 2.0.43 [V] | `agent_id`, `agent_type` | No; `additionalContext` only [V] |
| SubagentStop | — | `agent_id`, `agent_type`, `agent_transcript_path`, `last_assistant_message`, `background_tasks`, `session_crons`, `stop_hook_active` [V] | Yes [V] |
| Stop | — | `stop_hook_active`, `last_assistant_message`, `background_tasks[]`, `session_crons[]`. **No task fields** (docs:hooks#stop-input) [V] | Yes. At most 8 consecutive continuations (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`) [V] |

The harness registers none of TaskCreated, TaskCompleted, TeammateIdle or SubagentStart (`settings.json` hooks block) [V].

---

## 2. Functional gap: TodoWrite against the task tools

### 2.1 What the task system has that TodoWrite does not

| Capability | Task tools | TodoWrite |
|---|---|---|
| Stable ids, per-item calls | Yes. Each task has an id; one call changes one task [V schema] | No. Each call replaces the whole list [V] |
| Dependencies | `blocks` / `blockedBy` [V schema]. **Not enforced.** A task blocked by an open task went straight from `pending` to `completed` [V exp] | None |
| Long description, owner, free metadata | `description`, `owner`, `metadata` (merge semantics) [V schema] | `content` + `activeForm` only |
| Delete | `status: "deleted"` [V schema] | Drop the item from the list |
| Survives compaction | "Tasks persist across context compactions" (docs:interactive-mode#task-list) [V] | Kept in memory and rebuilt from the transcript on resume (bin `!r0()&&e.messages…todos`) [I]. Compaction keeps the list in the reminder [I] |
| Survives resume | Same directory, keyed by session id, on `--resume`/`--continue` (docs:interactive-mode#task-list; bin `_T()`) [V/I] | Rebuilt from transcript records [I] |
| Shared across sessions | `CLAUDE_CODE_TASK_LIST_ID` "Share a task list across sessions" (docs:env-vars) [V] | No |
| Shared with subagents | Foreground subagents use the session's list [V exp: a subagent's reminders listed this session's tasks; docs:tools-reference "A subagent has the task-tracking tools only when your session has them"] | Each agent has its own list (bin `todos.set(agentId??sessionId, …)`) [I] |
| Native blocking hook | `TaskCreated` and `TaskCompleted` (exit 2) [V] | None. The harness uses PreToolUse on the TodoWrite matcher [V] |
| Agent teams | Shared list, self-claim, file locking (docs:agent-teams) [V] | No |

### 2.2 What TodoWrite has that the task tools do not

- **An atomic, self-contained record.**
  - Each TodoWrite `tool_use` holds the entire list, so one transcript row is the full state. The harness depends on this throughout: `Span.last_todos()` (`hooks/lib/command_span.py:438-448`) and the "first list" rule of the Stop gate (`hooks/stop-command-gate.py:298-302`) [V].
  - With the task tools, the full state exists only on disk. The transcript holds deltas, and the result rows do not echo the full task [V exp].
- **One call = one decision.**
  - `pretool-todo-validate.py` checks a whole proposed list in one PreToolUse: order, immutability, one completion per call, one `in_progress` (`:12-30`, `:442-463`) [V].
  - With the task tools, a 17-step checklist takes 17 TaskCreate calls. "The list is canonical" can only be checked by folding many calls [I].
- **Availability to background subagents.** A background subagent keeps `TodoWrite` but not the Task tools (docs:sub-agents#available-tools) [V].
- **No hidden deletion.** The CLI's UI store resets the task list after every task is completed (bin `#B(s){… if(e.length>0&&e.every((n)=>n.status==="completed")&&await gji(i,this.#r)) …}`, after a timer) [I]. In this cloud session the list was not reset within the observation window ([Appendix, experiment 3](#appendix-experiments-run-for-this-report)) [V exp]. A reader that relies on the disk files after completion must not assume they are still there [I].
- **Immutability is the harness's, not the CLI's.** TaskUpdate renamed a task that was already completed without complaint [V exp]. TodoWrite has the same property; the harness's validator supplies the immutability [V].

### 2.3 Persistence and binding

- **Across turns:** yes, for both. Task files sit on disk [V exp]; TodoWrite stays in memory for the session [I].
- **Across compaction:** yes for tasks (docs) [V]; TodoWrite is rebuilt from the record [I].
- **Across sessions:** tasks only through `CLAUDE_CODE_TASK_LIST_ID`. A new session id, which is also what `/clear` produces, starts an empty list (bin `_T()`) [I]. The `cleanupPeriodDays` sweep deletes old lists (CL 2.1.117) [V].
- **Binding:** neither tool is binding [V]. The CLI reminds every 10 turns (bin `fDe`; reminder observed in this session) [V], and `CLAUDE_CODE_TODO_REMINDER_MODE=off` silences the reminder (bin `G1n()`) [I]. No main-agent stop path checks open tasks (docs:hooks#stop-input lists no task fields) [V]. The only exception is teammates: their in_progress tasks run TaskCompleted hooks at their stop (bin; docs:hooks#taskcompleted) [V]. So "the command cannot end with open steps" stays `hooks/stop-command-gate.py`'s job.

### 2.4 How hooks and the Stop gate would read task state

Recorded shapes [V exp, this session's transcript]:

```text
assistant tool_use  {"name":"TaskCreate","input":{"subject":…,"description":…,"activeForm":…,"metadata":{…}}}
user toolUseResult  {"task":{"id":"1","subject":…,"description":…}}
assistant tool_use  {"name":"TaskUpdate","input":{"taskId":"1","status":"in_progress","owner":"main"}}
user toolUseResult  {"success":true,"taskId":"1","updatedFields":["owner","status"],"statusChange":{"from":"pending","to":"in_progress"}}
disk                ~/.claude/tasks/<session_id>/1.json  {"id","subject","description","activeForm","owner","status","blocks","blockedBy","metadata"}
disk                ~/.claude/tasks/<session_id>/.lock   (zero bytes)
```

Three ways to read the state:

- **(a) Fold the transcript.** Replay TaskCreate inputs (taking the id from the result) and TaskUpdate deltas. This works only for calls this agent made. It misses:
  - writes by subagents, which land in their own transcripts;
  - writes by other sessions sharing a `CLAUDE_CODE_TASK_LIST_ID`;
  - the CLI's auto-reset [I].
- **(b) Read `~/.claude/tasks/<listId>/*.json`.** This is the authoritative state. The hook must resolve `listId` the way the CLI does (bin `_T()`) [I], and take the lock (bin `lockfilePath`) [I].
- **(c) Hooks:**
  - PreToolUse on `TaskCreate|TaskUpdate` sees the proposed delta.
  - `TaskCompleted` sees `task_id` and `task_subject`, not metadata. It would have to read the file for `metadata` [V payload; I usage].
  - The Stop hook has no task data and must use (a) or (b) [V].

---

## 3. Dependency map

The literal `TodoWrite` appears 317 times in 74 files. Counting `todos`, `activeForm`, `scripts/todo` and the todo state files, the dependency covers about 130 files and 1,100 references, about 60% of them tests. `TaskCreate`, `TaskUpdate`, `TaskList` and `TaskGet` appear nowhere [V, repository search].

### 3.1 Record shape everything relies on

- **The transcript call:** `{"type":"tool_use","name":"TodoWrite","input":{"todos":[…]}}`, which counts as ok when its `tool_result` has no `is_error` (`hooks/lib/command_span.py:278-300`). There is also a byte prefilter on the literal `"TodoWrite"` (`:602-606`) [V].
- **Each item:** `{content, activeForm, status}`, plus harness keys passed through TodoWrite:
  - `subagent_call {agent, subagent_type[, mode]}`
  - `artifacts`
  - `wake_call` (`scripts/todo/dev.py:9-37`, `scripts/todo/dev-overnight.py:14-126`) [V]
- **The step label:** `content` starts `Step N[x]:`. It is parsed in four places [V]:
  - `hooks/stop-command-gate.py:110`
  - `hooks/pretool-subagent-enforce.py:53`
  - `hooks/check-todo-md-sync.py:52`
  - `tests/replay/pipeline.py:238`

### 3.2 Map

| # | Component | file:line | What it relies on |
|---|---|---|---|
| 1 | Settings | `settings.json:21-22` (switches), `:173` (allow), `:468-475` (PreToolUse `TodoWrite`), `:551-562` (PostToolUse `TodoWrite`) [V] | TodoWrite is the tool the CLI offers, and the matchers name it |
| 2 | Span reader | `hooks/lib/command_span.py:10-12, 400-448, 602-606` [V] | `uses('TodoWrite')`, `last_todos()`: the newest ok `input.todos` |
| 3 | Checklist hub | `hooks/lib/todo_canonical.py:261-298` (`Checklist.todos` / `.lock = 'not_started'`), `:146-177` (`run_todo_script`), `:180-247` (immutability, initial-status rules), `:328-373` (`write_bookmark`) [V] | The newest ok TodoWrite is the checklist; the canonical list comes from `scripts/todo/<cmd>.py` |
| 4 | Stop gate, todo half (S-008) | `hooks/stop-command-gate.py:275-305` (`todo_gaps`); `:284-285` refuses when `CLAUDE_CODE_ENABLE_TODO_TOOLS != "1"`; `:298-302` "first list" rule; `:843` call site [V]. Runner: `hooks/stop-launch.py:40-75` → `hooks/stop-workflow-coordinator.py:87` [V] | The last ok TodoWrite list matches the canonical list (or the span's first list) by `content`, and every item is `completed` |
| 5 | TodoWrite validator (H-037) | `hooks/pretool-todo-validate.py:12-30, 58-66, 253-285` (Gate 4: Agent after a step went `in_progress`), `:333-341`, `:414-424` (wake step + CronCreate), `:442-463` [V] | A whole proposed list is compared with the canonical list and the previous list |
| 6 | Workflow gate (H-018) | `hooks/pretool-workflow-gate.py:1150-1151` (TodoWrite/TodoRead pass), `:1157-1163` (lock), `:1175-1193` ("Call TodoWrite with this exact todos array"), `:163-205`; Codex path `:44, 57-131, 272-440, 933-947` [V] | Any other tool is blocked until a TodoWrite starts the checklist. **A TaskCreate would be blocked here** [I] |
| 7 | Orchestrator gate (H-015) | `hooks/pretool-orchestrator-gate.py:47-60` (`TodoWrite` at `:49`), `:68` [V] | TodoWrite is unlimited; the Task tools would be 1/turn [V exp] |
| 8 | Subagent step guard (R-007) | `hooks/pretool-subagent-enforce.py:53-67, 227-248` [V] | The `in_progress` item of the newest TodoWrite names the current step |
| 9 | /spec gates | `hooks/pretool-block-background-tasks.py:65-79`; `hooks/pretool-spec-block-foreground-agent.py:14-40, 85` [V] | /spec progress counted from `todos` |
| 10 | Obligation chain | `hooks/lib/obligation.py:1287-1320` (`_canonical_step`: `artifacts`, `subagent_call`, `content`), `scripts/resolve-dev-artifact-chain.py:1786-1810`, `hooks/lib/contract_runtime.py:89, 147-152`, `schemas/cycle-contract.v1.json:37, 51` [V] | The canonical step metadata from `scripts/todo/*.py`, **not** the TodoWrite records. This survives a tool change unchanged |
| 11 | PostToolUse tracker (H-054) | `hooks/posttool-todo-tracker.py:24-60` [V] | `tool_input.todos` → progress `additionalContext` |
| 12 | Overnight loop (H-051) | `hooks/posttool-overnight-loop.py:31-36, 60` [V] | An all-completed TodoWrite advances the overnight cycle ("Reset your todo list to all-pending") |
| 13 | Prompt injector (H-008) | `hooks/prompt-workflow.py:262-341, 535-551, 1053-1145, 1637-1653` [V] | It prints "FIRST ACTION: call TodoWrite with the todos array below", which the replay drivers parse |
| 14 | SessionStart sync (H-002) | `hooks/check-todo-md-sync.py:5-13, 46-52, 87-98, 183-186` [V] | `Step N` tokens in `scripts/todo/*.py` match `### Step N:` headings in `commands/*.md`. This is tool-independent |
| 15 | Canonical providers | `scripts/todo/{dev,dev-command,dev-overnight,close,do,spec,clean,test,redev}.py` (14 files) [V] | They print a TodoWrite-shaped list. The shape can be kept and mapped |
| 16 | Command step lists | `commands/dev.md:11, 349, 353, 423`, `commands/dev-command.md:6, 10`, `commands/dev-overnight.md:17-25, 623-625, 876`, `commands/close.md:9, 27, 101, 252`, `commands/spec.md:73`, `commands/clean.md:30`, `commands/test.md:14-17`, `commands/restart.md:14, 75, 121-123` [V] | The text tells the model to use TodoWrite |
| 17 | Codex runtime file | `~/.claude/todos/{sid}-agent-{sid}.json`, written only by `hooks/pretool-workflow-gate.py:97-105`; protected by `hooks/pretool-bash-safety.sh:1785-1787` and `hooks/pretool-overnight-hook-guard.py:96` [V] | The harness's own file for the Codex path, not the CLI's |
| 18 | Restart credit | `hooks/pretool-todo-validate.py:237-249`, `hooks/pretool-obligation-gate.py:153-178` (`completed_resumes`) [V] | A resumed SendMessage counts as the step's dispatch |
| 19 | CLAUDE.md | `CLAUDE.md:48` (whitelist), `:56` ("cannot end until code confirms their todo list") [V] | Rule text |
| 20 | Ledger and docs | `docs/ENFORCEMENT-LEDGER.md:221` (H-002), `:227` (H-008), `:234` (H-015), `:236` (H-018), `:246` (H-037), `:253` (H-051), `:254` (H-054), `:267` (H-088), `:301` (R-007), `:334, 408-420` (S-008); `ARCHITECTURE.md:113, 150, 158, 161, 305, 324, 372, 420`; `docs/how-it-works.md:87, 238`; `README.md:10, 80, 83` [V] | Descriptions |
| 21 | Hook tests (25 files) | e.g. `hooks/tests/test_stop_command_gate.py:117-120` (TodoWrite fixture), `:1757-1762` (`test_a11_todo_tools_disabled_is_one_gap`); `test_checklist_record.py`, `test_command_span.py:377-418`, `test_span_lazy_reader.py`, `test_todo_validate_*.py`, `test_overnight_*.py`, `test_workflow_bookmark_writer.py`, `test_dual_runtime_lifecycle_e2e.py` [V] | Hand-built TodoWrite records |
| 22 | Other tests | `tests/test_dev_todo_accounting.py`, `test_todo_md_sync.py`, `test_todo_root.py`, `test_codex_workflow_gate.py`, `test_restart_command.py:732-742`, `tests/scripts/validate-todowrite-requirement.py`, `tests/artifact_graph/declarations.py:43-59` [V] | Same |
| 23 | Replay framework and drivers | `tests/replay/pipeline.py:204-253` (parses the FIRST ACTION line), `replay.py:659-660, 856-869` (synthesises TodoWrite and `toolUseResult {oldTodos,newTodos}`), `sites.py:1143-1145` (`OBLIGATION_TOOLS`), `recovery.py:296-328`; drivers `_deadend.py`, `close.py`, `overnight.py`, `dev_command.py:295-307`, `dev.py`, `do.py`, `clean.py`, `spec.py`, `redev.py`, `_pathrule.py`, `smoke.py` [V] | Every replay advances the checklist with synthetic TodoWrite calls |

---

## 4. Migration to the task tools

### 4.1 Per dependency

**Binding scripts the task system makes redundant: none** [I, from section 2.3]. The task list is not binding, so `stop-command-gate.todo_gaps` and the validator stay. Only their input changes.

| # | Dependency | A: keep TodoWrite | B: adapter | C: native |
|---|---|---|---|---|
| 1 | Settings | Keep. Pin both switches in a test | Flip to `ENABLE_TASKS` unset; matchers `TaskCreate\|TaskUpdate` | Same as B, plus `TaskCreated` / `TaskCompleted` registrations |
| 2–3 | Span reader / checklist hub | Keep | **Adapt.** One reader returns a TodoWrite-shaped list folded from Task records (transcript fold, checked against `~/.claude/tasks/<listId>/`). Every caller is unchanged | Replace with a disk reader keyed by task metadata |
| 4 | Stop gate todo half | Keep. Add a gap for `CLAUDE_CODE_ENABLE_TASKS` not false (today it checks only `ENABLE_TODO_TOOLS`, `:284`) | Keep the logic; read via the adapter. Treat an auto-reset (empty list after all completed) through the transcript fold | Read disk; "first list" becomes the set of create calls |
| 5 | Validator | Keep | **Adapt.** Validate the delta: creates in canonical order with `subject == content`, `activeForm` fixed, `metadata.step` / `subagent_call` set; one completion per call (the tool already does one task per call); `in_progress` before `completed`; one `in_progress`. No TaskUpdate of `subject` / `activeForm` / `metadata` after create | Split. Order and evidence move to `TaskCompleted` (exit 2); `TaskCreated` refuses non-canonical tasks |
| 6 | Workflow gate lock | Keep | **Adapt.** Let `TaskCreate`, `TaskUpdate`, `TaskList`, `TaskGet` through while the lock is open; the lock lifts when all N canonical tasks exist | Same as B |
| 7 | Orchestrator gate | Keep | **Must change.** Add the four Task tools to `ALWAYS_ALLOWED` (a 17-step list needs 17 creates) | Same as B |
| 8 | Subagent step guard | Keep | Adapt: the `in_progress` task via the adapter | Same as B |
| 9 | /spec gates | Keep | Adapt via the adapter | Same as B |
| 10 | Obligation chain | Keep | Keep. It reads `scripts/todo` metadata | Keep |
| 11 | Tracker | Keep | Adapt (PostToolUse `TaskUpdate`) or retire, since the CLI shows the task list natively (docs:interactive-mode#task-list) [V] | Retire |
| 12 | Overnight loop | Keep | Adapt: PostToolUse `TaskUpdate` to completed with every task completed. "Reset to all-pending" becomes "delete and recreate" or "update all to pending" | Move to `TaskCompleted` |
| 13 | Prompt injector | Keep | Adapt the FIRST ACTION text to "create these N tasks in order" | Same as B |
| 14 | SessionStart sync | Keep | Keep | Keep |
| 15 | Canonical providers | Keep | Keep. The adapter maps `content` → `subject`, extras → `metadata` | Keep |
| 16 | Command text | Keep | Edit the TodoWrite wording in about 10 command files | Same as B |
| 17 | Codex file | Keep | Keep. The Codex path is separate | Keep |
| 18 | Restart credit | Keep | Keep | Keep |
| 19–20 | CLAUDE.md, ledger, docs | Keep | Edit `CLAUDE.md:48, 56`; ledger rows H-037 / H-051 / H-054 (matcher), H-015, H-018, S-008 | Same, plus new rows for the task hooks |
| 21–23 | Tests and replays | Keep; add the switch-pin tests | **Adapt.** Fixtures and `replay.py:659-660, 856-869` synthesise TaskCreate/TaskUpdate rows and the `toolUseResult` shapes of section 2.4; the drivers' FIRST ACTION parsers change. The artifact checks that replay obligations (`tests/replay/sites.py:1143-1145` `OBLIGATION_TOOLS`) add the Task tools | Rewrite |

### 4.2 Designs

**Design A: keep TodoWrite and pin the switch.**
- *Changes:*
  - A test that `settings.json` carries `CLAUDE_CODE_ENABLE_TASKS=false` and `CLAUDE_CODE_ENABLE_TODO_TOOLS=1`.
  - A Stop gate gap and a SessionStart warning when `CLAUDE_CODE_ENABLE_TASKS` is not false, because the gate checks only the other switch today (`hooks/stop-command-gate.py:284`).
  - The section 6 fixes.
- *Cost:* small; a handful of files.
- *Risk:*
  - TodoWrite is a fallback the CLI keeps. CL 2.1.19 introduced the switch "to keep the old system temporarily", and the docs say it is "Disabled by default" (docs:tools-reference) [V]. A future release may remove it, and every gate would then fail closed (`:284-285` already returns a gap) [I].
  - Machines that run without this `settings.json` get the Task tools or no list tool at all. Examples are cloud sessions and project-level overrides; this session is one (docs:tools-reference#task-tool-availability: in cloud sessions "the same tools on every model") [V].

**Design B: reader adapter (Task tools as transport, TodoWrite-shaped checklist inside).**
- *Changes:*
  - One new reader in `hooks/lib` that folds Task records into the `todos` shape and cross-checks the disk list.
  - Rows 4–9, 11–13, 16, 19–23 of the table above.
  - The orchestrator whitelist.
  - The PreToolUse delta validator.
- *Cost:* medium to high. About 10 hooks change; about 25 hook-test files and every replay driver change fixtures, mostly mechanically, because the folded shape is the old shape.
- *Risk:*
  - Subagents share and can change the list. The validator must refuse a subagent's `TaskUpdate` on a canonical step, or the guard must accept that a subagent marks steps. `policies/tool-policy.v1.json` default-deny covers listed roles only; Explore, general-purpose and plugins are unrestricted (`hooks/pretool-tool-policy.py:91-93`) [V].
  - The auto-reset can empty the disk list [I], so the transcript fold must stay the record of truth.
  - `CLAUDE_CODE_TASK_LIST_ID` sharing would let another session write the list. The harness should refuse to run gated commands with it set.
  - Background subagents lose list tools, which is harmless: the checklist is the orchestrator's.
- *Gain:* the harness works where only the Task tools exist; compaction-proof state; `owner` and `metadata` per step; a later move to C stays possible.

**Design C: native (TaskCreated/TaskCompleted as the gates, disk as the record).**
- *Changes:*
  - `TaskCreated` refuses tasks outside the canonical list.
  - `TaskCompleted` refuses a completion without its evidence: dispatch seen, artifacts present, the previous step completed. Hook payloads carry `task_id` and `task_subject`, so the hook reads `metadata.step` from the file.
  - The Stop gate reads the disk list.
  - The validator, the tracker and the overnight loop are retired or rewritten.
- *Cost:* high; a redesign of the checklist subsystem and its replays.
- *Risk:*
  - Blocking moves from "before the call" to "at completion", so ordering errors such as creating step 3 before step 2 must be caught by TaskCreated.
  - TaskCompleted fires only on TaskUpdate and teammate stops, not on deletion: a `deleted` status bypasses it [I].
  - The disk state can be reset or swept (CL 2.1.117) [V/I].
  - `blockedBy` is not enforced [V exp], so it cannot replace the order rule.
  - The replay suite must model disk state as well as the transcript.

**Recommendation:** A now; B as the planned move. C only after the auto-reset timing, the `deleted` path and TaskCompleted on the main agent have been measured.

Reasons:

- A costs almost nothing and keeps every pinned guarantee.
- B is the smallest move that survives the removal of TodoWrite. Because the folded list keeps the old shape, the Stop gate, the validator's rules and most tests keep their meaning.
- C trades proven PreToolUse gates for hooks whose edge cases are not yet measured.

The owner chooses (D18).

---

## 5. SendMessage

### 5.1 What the current block protects

1. **No background work by the orchestrator.**
   - "Orchestrator background tasks bypass harness monitoring and create unmanageable execution state" (`hooks/pretool-block-background-tasks.py:24-29`); "Unauthorized SendMessage resumes a background child" (`:141-142`) [V].
   - Since CL 2.1.77, a send to a stopped agent "auto-resumes stopped agents in the background" [V]. Any send can therefore restart a child in the background, which a `run_in_background: false` dispatch rule cannot see.
2. **Lesson 16: resume, never replace.**
   - The only send allowed is `/restart`'s fixed message, to a candidate taken from the transcript, once per candidate. The check is `authorize_send_message` (`hooks/lib/subagent_restart.py:1189-1285`): live grant, known candidate, origin transcript, the child has not ended its turn, exact `resume_message` prefix, status `pending` [V].
   - The exact prefix stops "a freshly reconstructed prompt" being passed off as a resume (`:1264-1270`) [V].
   - The journal (`hooks/posttool-restart-sendmessage.py`, H-049) and SubagentStop tracking (R-026) give the "response evidence for every candidate" (`CLAUDE.md:36`) [V].
3. **The dispatch gate.**
   - New work enters a subagent only through `Agent`, the one tool the dispatch gate checks: overnight contract, obligation G1, spec window, checklist-started, prompt-purity, and the dispatch witness (`hooks/pretool-dispatch-gate.py:42-54`; matcher `Agent`, `settings.json:503-508`) [V].
   - A free SendMessage to a finished child gives it a new task with none of those checks [I]. Lesson 13 (one issue per subagent) also has no other check on a resumed child [I].
4. **Other sessions.** Since CL 2.1.224 `to` can name another session on any of the user's machines [V]. The tool's own description warns against "cross-session permission laundering" (schema) [V]. Today's block covers this by accident.

### 5.2 What allowing it changes

- **Background resumes outside the dispatch record:** items 1 and 3 above.
- **Lesson 16 and the gates' credit for it:** these do not change as long as candidates keep the exact-message rule. Otherwise a free-form send to a candidate would resume it without a journal entry and break "response evidence" [I].
- **`hooks/pretool-orchestrator-gate.py:199-207`:** sends that are not restart sends would fall into the once-per-turn budget [V].

### 5.3 Smallest policy that keeps `/restart`'s guarantee

The main agent may call SendMessage when every condition below holds, checked by `pretool-block-background-tasks.py` in place of the blanket block at `:141-152`:

1. **Restart candidates keep today's rule.** If the session has restart state and `to` is a candidate in it, `authorize_send_message` decides, unchanged. The send must be exact, pending, and so on. This keeps the lesson 16 guarantee byte for byte.
2. **Only this session's own subagents.**
   - `to` must resolve to an agent id or name returned by an `Agent` result in this session's transcript (`tool_response.agentId`; docs:hooks) [V].
   - That rules out `main`, other sessions and `name [ref]` forms. A deny on anything else covers cross-session sends.
3. **Not to a child in a dev lane under `/dev-overnight` or a gated command,** unless the target's lane is the same issue. Practical form: refuse sends to children whose obligation is open or whose dispatch was witnessed under a gated span; allow them otherwise.
   - This keeps new work off the dispatch gate's blind path.
   - If the owner wants steering inside lanes too, the send must instead pass the same prompt-purity and contract checks as a dispatch. Route SendMessage through `pretool-dispatch-gate.py` by adding `SendMessage` to its matcher with the target's original `subagent_type`.
4. **Record every allowed send.** Widen `posttool-restart-sendmessage.py` (H-049) to journal non-restart sends as well, so a send leaves a witness the way a dispatch does.
5. **Budget.** Once per turn is fine for steering. Exempt sends that are restart-authorized, as now.

*Side finding:* a grant minted by an earlier wake is not revoked by `/stop`. `commands/stop.md:259-262` and `hooks/stop.sh` do not touch `restart-state`, so the grant lives until `finalize` or its TTL (default 7200 s, `hooks/lib/subagent_restart.py:403-430`). `CLAUDE.md:36`'s "a wake after `/stop`" is blocked only for a new mint [I, from the code path; untested]. Unlinking the grant on `/stop` would close this.

### 5.4 What changes

**Hooks**
- `hooks/pretool-block-background-tasks.py:123-152`: replace the blanket SendMessage block with the policy above. Workflow stays blocked.
- `hooks/pretool-orchestrator-gate.py:193-207`: unchanged unless the budget changes.
- `hooks/posttool-restart-sendmessage.py`: journal ordinary sends.
- Optionally `settings.json:503-508`: add SendMessage to the dispatch gate's matcher.

**Rules**
- `CLAUDE.md:36-38` (lesson 16's last sentence: "blocks every other `SendMessage` …").
- `CLAUDE.md:54` ("every `SendMessage` but lesson 16's recovery").
- `docs/how-it-works.md:85`.
- `commands/restart.md` needs no change.

**Ledger**
- H-014 (`docs/ENFORCEMENT-LEDGER.md:233`): new SendMessage rule text.
- H-049 (`:251`): scope widened from restart sends to all sends.
- H-015 (`:234`): only if the budget changes.
- If the dispatch gate gains the matcher: H-090 (`:269`) and R-012 (`:306`).

**Tests**
- `tests/test_restart_command.py:545` (`test_background_and_orchestrator_gates_allow_all_runtime_eligible_resumes`). Its `{"to":"agent-missing","message":"continue"}` → exit 2 case still holds, since that id is in no `Agent` result. Add cases:
  - a free-form send to a candidate is refused;
  - a send to this session's finished non-candidate child passes;
  - a send to `main` or another session's name is refused;
  - a send to an open-obligation child is refused.
- `tests/test_restart_command.py:438`, `:1308`: the exact-prefix rule must keep passing unchanged.
- `hooks/tests/test_overnight_wake.py:170-198`: unchanged.
- New tests for the journal of ordinary sends.

**Prerequisite**
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS: "1"` (`settings.json:23`, pinned by `tests/test_restart_command.py:731`) is not needed for SendMessage resume: "`SendMessage` doesn't require agent teams to be enabled" (docs:sub-agents#resume-subagents) [V]. It does turn on teams, named agents and the shared team task list. Whether to keep it is a separate choice; removing it would change `tests/test_restart_command.py:731`.

---

## 6. Monitor and the other newer tools

| Tool | What it is for | Blocked or limited today by | Allow? | Why |
|---|---|---|---|---|
| **Monitor** | Watch a log, a CI poll or a WebSocket; one notification per line; ends on exit, expiry (max 30 min) or TaskStop [V schema] | Orchestrator gate 1/turn [V exp]. **Not** blocked by the no-background hook [V exp], although it runs in the background | Yes for the main agent, with two conditions: (1) count each Monitor call against the Bash cap of 5, because its `command` is arbitrary shell; (2) require CLI ≥ 2.1.314, since before that "hooks matching Bash [were] not running on shell commands started by the Monitor tool" (CL 2.1.314) [V]. Otherwise Monitor bypasses `pretool-bash-safety.sh`. Decide explicitly whether the no-background rule (`CLAUDE.md:54`) covers it, because the hook does not today | It watches; it does no work, edits nothing and spawns no agent. It replaces the polling the harness does with ScheduleWakeup/Cron. The Bash cap and safety hooks keep their reach only with both conditions |
| **TaskStop** | Cancel a Monitor, a background Bash or a named background agent [V schema] | Gate 1/turn [I] | Yes, whitelist it with Monitor | Cancelling is safe and needed for every Monitor; one per turn is too few when several watches end together |
| **Workflow** | Multi-agent scripts, "tens to hundreds of agents in the background" (CL 2.1.154) [V] | No-background hook blocks it, no `/allow` path; `/do` lifts it (`hooks/pretool-block-background-tasks.py:120-121, 141-152`) [V] | No; keep blocked | Workflow agents are subagents and exempt from the orchestrator gates. They bypass the dispatch gate (matcher `Agent`), lesson 13 and the obligation chain. The CLI already requires user opt-in (docs:workflows) [V]. *Fix:* the orchestrator gate accepts `/allow Workflow` (`hooks/pretool-orchestrator-gate.py:234-238`) but the background hook ignores it, so the grant is a dead letter. Either honour `/allow` there or document that `/do` is the only lift |
| **SendMessage** | Resume/steer a subagent; message other sessions | Section 5 | Yes, under the section 5 policy | Section 5 |
| **ListAgents** | List messageable agents and sessions (CL 2.1.224) [V] | Gate 1/turn [I] | Yes if SendMessage is allowed; read-only | Needed to address named agents. Cross-session targets stay refused by the SendMessage policy |
| **TaskCreate / TaskUpdate / TaskList / TaskGet** | Task list | Gate 1/turn [V exp]; workflow-gate lock while unstarted [I] | Only with design B or C; then whitelist all four | See section 4 |
| **ScheduleWakeup** | `/loop` self-paced wakes [V] | Whitelisted; prompt policy (`hooks/pretool-tool-policy.py:1529-1554`) [V] | Keep | Already allowed with a content rule |
| **CronCreate / Delete / List** | Session cron; the overnight wake | Whitelisted [V] | Keep | Note: `durable` "Has no effect" here (schema) and jobs are session-only [V]. The overnight wake does not survive a CLI exit. `commands/dev-overnight.md:58-66` relies on the session staying up |
| **EnterWorktree / ExitWorktree** | Worktrees | `pretool-block-enterworktree.sh` + 1/turn [V] | Keep | Unchanged by this research. The `.sh` hook itself has no test (`hooks/tests/test_block_branch_pr_worktree.py:291` covers only the other hook ignoring it) [V] |
| **PushNotification** | Phone/desktop push (CL 2.1.110) [V] | Gate 1/turn [I] | Yes; whitelist optional | Harmless and useful at the end of `/dev-overnight`. Once per turn is enough |
| **ToolSearch** | Load deferred schemas [V] | Gate 1/turn [I]; `ENABLE_TOOL_SEARCH: "false"` (`settings.json:20`) [V] | Keep | One `select:` call loads several tools, so 1/turn is enough. Locally, tool search applies to MCP tools (docs:env-vars `ENABLE_TOOL_SEARCH`) [V] |
| **Agent alias `Task`** | Old name of Agent | Not in `ALWAYS_ALLOWED`; the Agent-clear checks `tool_name == "Agent"` only (`hooks/pretool-orchestrator-gate.py:219`); dispatch gate matcher `Agent` only [V] | Make consistent | If the CLI ever reports `Task` as `tool_name`, the dispatch gate, the witness and the Bash reset would all be skipped [I]. Treat `Task` like `Agent` everywhere, or pin by test that hooks see `Agent` |
| **SubagentHandback** | A subagent's final report, auto mode only (docs:tools-reference) [V] | Not referenced | Accommodate | In auto mode "the report is in `tool_input.message` of that tool call, not in `last_assistant_message`" (docs:hooks#subagentstop) [V]. `hooks/subagentstop-artifact-contract-enforce.py:759-953` reads response-line artifacts from `last_assistant_message`, so in auto mode it may miss a terminal line and block a correct producer [I]. The subagents of this research session used it [V exp] |
| **EnterPlanMode / ExitPlanMode** | Plan mode | Permanently blocked [V] | Keep | Unchanged. Note: no test pins the permanent block or the `ALWAYS_ALLOWED` set (no `EnterPlanMode\|ALWAYS_ALLOWED\|BASH_MAX` under `tests/`, `hooks/tests/`) [V] |
| **TaskOutput** | — | — | — | Removed in CL 2.1.277 [V]; nothing to do |

**Environment note.** In this cloud session every `Agent` dispatch with `run_in_background: false` still returned "Async agent launched" [V exp]. The environment sets `CLAUDE_AUTO_BACKGROUND_TASKS=true`. The documented effect of that variable is to background a subagent "after running for approximately two minutes" (docs:env-vars), so it does not fully explain an immediate async launch [I]. On such hosts the harness's synchronous-dispatch guarantee (`CLAUDE.md:52`) does not hold even when the hook passes. A capability check at SessionStart would make this visible.

---

## Appendix: experiments run for this report

1. **Task storage** (this session; it changed no harness file).
   - TaskCreate wrote `~/.claude/tasks/<session_id>/1.json` and a zero-byte `.lock`.
   - TaskUpdate `in_progress` with `owner` rewrote the file.
   - The transcript holds the `tool_use` inputs and `toolUseResult` `{task:{…}}` / `{success, taskId, updatedFields, statusChange}`.
2. **Dependencies and immutability.**
   - Created #3 and #4, then set #4 `addBlockedBy: ["3"]`.
   - `TaskUpdate #4 status=completed` succeeded while #3 was pending, going straight from `pending` to `completed`.
   - Renaming completed #4's `subject` also succeeded. File: `{"subject":"Probe B renamed after completion","status":"completed","blockedBy":["3"]}`.
3. **Auto-reset.**
   - Every task in the list was completed at 06:03 UTC (then #3/#4 were created) and again at about 06:06.
   - A watcher polled the list directory every 5 s from 06:04 to 06:14 and saw no reset. At the end the four files `1.json`–`4.json` were still on disk, and the CLI's reminder injected at about 06:12 still listed all four as `[completed]`.
   - So in this cloud session the bin's reset (`#B`, a UI-store timer) did not run within about eight minutes of the last completion [V exp]. Whether and when it runs in an interactive terminal session was not measured.
4. **Hook replays** (`HOME` and `CLAUDE_HOME` were a throwaway copy of this repository; synthetic PreToolUse payloads for a main-agent session):

   | Hook | Call | Result |
   |---|---|---|
   | `pretool-orchestrator-gate.py` | `TaskCreate` ×2 | exit 0, then exit 2 "TaskCreate used consecutively beyond limit (2/1)" |
   | | `TaskUpdate` ×2 | 0, 2 |
   | | `TaskList` | 0 |
   | | `Monitor` ×2 | 0, 2 |
   | | `SendMessage` | 0 (falls to the 1/turn budget) |
   | | `TodoWrite` ×2 | 0, 0 |
   | `pretool-block-background-tasks.py` | `SendMessage` | exit 2 "no valid /restart capability" |
   | | `Workflow` | exit 2 |
   | | `Monitor` | 0 |
   | | `TaskCreate` | 0 |
   | | `Agent` without `run_in_background` | exit 2 |
   | `pretool-workflow-gate.py` | `TaskCreate`, `TodoWrite` with no active command | 0 |
5. **Binary reading** (2.1.322):
   - `isEnabled(){return Nye()}` on TaskCreate, TaskGet and TaskUpdate.
   - `isEnabled(){return!r0()&&B9()}` (on TodoWrite, per the docs agent's reading).
   - `r0` is false iff `CLAUDE_CODE_ENABLE_TASKS===false`.
   - `B9` tests the model list, the launch opt-in and `CLAUDE_CODE_ENABLE_TODO_TOOLS===true`.
   - `_T()` resolves the list id.
   - `fDe={TURNS_SINCE_WRITE:10,TURNS_BETWEEN_REMINDERS:10}`; `G1n()` reads `CLAUDE_CODE_TODO_REMINDER_MODE ?? "baseline"`.
   - TaskCreated and TaskCompleted payload schemas.
6. **Checks run on this document** (venv in a scratch directory, `HOME` a throwaway directory, `HARNESS_LINT=1`): `pytest tests/lint tests/test_readme_facts.py tests/scripts` → 271 passed. `INDEX.md` was not regenerated. The doc-sync hook that would list `docs/research/` was not run, by this report's no-hook rule.
