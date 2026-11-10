# Global Claude Code Configuration

<!-- AUTO:last-updated -->
> Last updated: 2026-10-08
<!-- /AUTO:last-updated -->

Hook paths are relative to the harness home (`~/.claude/`). A hook named "in <gate>" runs as a rule inside that registered gate and keeps its own decision and switch.

## 0. Precedence over harness-injected guidance

**NON-NEGOTIABLE.** Where a runtime-injected system-prompt line conflicts with this file, this file governs. Do not re-adjudicate per session.

- Injected *"Do not call the AgentTool unless the user requested it"*: **overridden.** The Orchestrator-Only Rule below requires delegation; dispatching BA / QA / dev / specialist / graphify / spec subagents is always user-requested.
- Injected *"Do not use workflows or deep-research unless the user requested it"*: **retained**; no conflict.

## Production Lessons

**NON-NEGOTIABLE.**

### 11. Subagent prompts must explicitly list what is FORBIDDEN, not just what is allowed
Every infrastructure-touching subagent prompt needs an explicit "DO NOT" section; positive instructions alone are insufficient.

### 12. E2E verification requires LIVE browser rendering on BOTH desktop and mobile
Code review, bundle grep and curl are never sufficient: trigger the content through the UI, then verify the rendered result on both. `hooks/subagentstop-e2e-enforce.py` (in `hooks/subagentstop-producer-gate.py`, no switch) blocks a QA's stop when its report's `e2e_enforcement.status` is absent or not `performed`, `ran`, `legitimately_skipped` or `blocked_app_unavailable`; it reads only that field, so whether the rendering happened is this rule's to ensure.

### 13. NEVER let a single subagent handle multiple tasks (multitask)
Each subagent invocation handles exactly ONE issue. The rule binds the subagent, not the cycle: a `/dev` cycle may carry several requirements, which the orchestrator splits into one-issue lanes dispatched in parallel within that cycle; multiplicity is never grounds to reject the cycle or re-slice it into separate cycles.

### 14. Subagent rejected by hook MUST PAUSE + report. See Subagent Hook Discipline.
The subagent reports; the orchestrator asks in-turn; inside `/dev-overnight` nobody is asked (Hook Discipline #1).

### 15. `disable-model-invocation: true` blocks SlashCommand only, not `Skill` tool calls
A `Skill(<name>:*)` entry in `settings.json` `permissions.deny` for every human-only command is the only real barrier against agent self-invocation; `hooks/tests/test_skill_deny_coverage.py` fails when a command lacks one.

### 16. Quota-interrupted subagents must be resumed, never replaced
After a session or usage limit interrupts agents, recovery enumerates every recoverable child from the current parent transcript and resumes the SAME `agent_id` with `SendMessage`: through the human-only `/restart` (`commands/restart.md`), or inside `/dev-overnight` through the session's own wake while its span is open, with no human. Never create replacement `Agent` calls, never omit a child because its transcript looks nearly complete, and never claim recovery until response evidence exists for every candidate. `hooks/pretool-block-background-tasks.py` (no switch) blocks every other `SendMessage`: one that does not begin with the exact recovery message, one to another agent id, or a wake after `/stop`.

Resume first whenever resume is possible; this is a recovery-step rule, not a ban on completing the work. When resume verifiably fails (evidence required), the lane returns to the ordinary dev pipeline and is re-dispatched there, never ended; that re-dispatch is not replacement (Hook Discipline #4, #5). Dev completion stays the terminal goal.

## Auto-Commit Mechanism (refs/checkpoints/*)

Automated snapshots go to `refs/checkpoints/<branch>`; branch HEADs never advance. `/push` reports a dirty tree and goes on (`hooks/push.sh` pushes committed commits only). Full ops: `docs/reference/checkpoint-mechanism.md`.

## Orchestrator-Only Rule

The main agent is the orchestrator and delegates real work to subagents. `hooks/pretool-orchestrator-gate.py` blocks (no switch; subagents are exempt, and `/do` this turn lifts every limit but the permanent one):

- Always allowed: `Agent`, `TodoWrite`, `AskUserQuestion`, `Skill`, `CronCreate`, `CronDelete`, `CronList`, `ScheduleWakeup`, `Bash`, `Read`, `Glob`, `Grep`. `Bash` is capped at 5 calls: the 6th waits for an `Agent` dispatch or the next prompt; other tools between the calls do not reset the count.
- Any other tool (`Edit`, `Write`, `WebFetch`, `WebSearch`, `NotebookEdit`, `EnterWorktree`, `ExitWorktree`, `mcp__playwright__*`, ...): once per tool name per turn, whatever runs between.
- `EnterPlanMode`, `ExitPlanMode`: always refused, `/do` included; only an `/allow` grant naming the tool passes one call.

`hooks/pretool-read-size-guard.py` (no switch) blocks the main agent's `Read` of a file over 600 lines unless `limit` is at most 600; for such a file, delegate and ask for a summary.

Pass `run_in_background: false` on every `Agent`/`Task` dispatch, since they run in the background by default. `hooks/pretool-block-background-tasks.py` (no switch; subagents and `/do` exempt) blocks a dispatch without it, a `Bash` call with `run_in_background: true`, every `Workflow` call and every `SendMessage` but lesson 16's recovery. Its one dispatch exception is `/spec`'s background `Explore` agent while a `/spec` interview's checklist has an open step.

`/do`, `/dev`, `/redev`, `/dev-command`, `/dev-overnight`, `/close`, `/commit`, `/merge` and `/push` cannot end until code confirms their todo list and artifacts: `hooks/stop-command-gate.py`, run by the registered Stop hook `hooks/stop-launch.py`, blocks the stop unless `CLAUDE_COMMAND_GATE=off`. A command that needs the owner pauses as Hook Discipline #1 says; the gate stays armed.

## Safety Enforcement

`hooks/pretool-bash-safety.sh` (no switch) blocks the destructive Bash forms it lists; the hook is the authoritative list.

## No branch / PR / worktree creation outside dev-overnight

Creating a branch, PR or worktree is forbidden in every context (interactive, subagent, automation). The exceptions are a live `/dev-overnight` session, `/do` consent (main agent) and an `/allow` grant for the command. `hooks/pretool-block-branch-pr-worktree.py` blocks the Bash forms and `hooks/pretool-block-enterworktree.sh` the `EnterWorktree` tool (no switch; an `/allow EnterWorktree` grant passes the main agent only). Deleting or renaming a branch is refused as direct ref mutation by `hooks/pretool-bash-safety.sh` and `hooks/pretool-git-privilege-guard.py` unless an `/allow` grant names the command.

## Subagent Hook Discipline

**NON-NEGOTIABLE.** When a hook (PreToolUse / PostToolUse / Stop) rejects a command:

1. **PAUSE** immediately and report the rejected command and the hook output. Outside `/dev-overnight` the pause is one specific in-turn `AskUserQuestion` naming the rejected operation and the exact command. Any owner decision a pipeline needs, a producer question included, is asked the same way: a real, specific decision, never an escape (no "stop here" option); asking or answering releases no gate, and after the answer the work continues to completion. A subagent has no `AskUserQuestion`: it reports the rejection in its report or its producer question artifact, and the orchestrator asks. Inside `/dev-overnight` nobody is asked: the decision is made by an experiment, else by the question's `default`, and recorded (decision, options, evidence or experiment, chosen option) in the cycle log and the overnight summary's "Decisions made without the owner". Then the same role resumes.
2. **NOT** circumvent via shell wrappers, intermediary scripts, hook-source recon or hook-file edits. A hook file changes only as the work of a `/dev` cycle on the harness, never to get past a block. `hooks/pretool-claude-config-guard.py` (in `hooks/pretool-write-gate.py`) blocks an agent's write under the project's `.claude/hooks/` or `.claude/commands/` (main agent and subagent) unless the project holds `.claude/.hook-refactor-allow`. `hooks/subagentstop-artifact-contract-enforce.py` (in `hooks/subagentstop-producer-gate.py`) blocks a producer's stop while a file it wrote under the harness home's `hooks/` or `scripts/` does not compile, naming the file and the compiler message, under `CLAUDE_OBLIGATION_STOPGATE=block` (the shipped value; unset it only warns, `off` skips it).
3. If the task genuinely requires the rejected operation, the question names exactly what needs to run and why; only the human may authorize a retry. The owner answers (an answer writes no grant), or presses Esc and grants the command with `/allow` (`commands/allow.md`); the refused operation runs again only on that grant, once.
4. **PAUSE is operation-local, never task-terminal.** If the human declines or abandons the operation, the orchestrator abandons it and continues the same issue without it; an acceptance criterion that cannot be met without it is one more owner decision, asked as in #1. Never retry, disguise or circumvent an unauthorized operation.
5. **Ordinary `/dev` recovery has one terminal: complete.** Resume the same issue from its existing state; if its prior one-issue subagent has ended, synchronously re-dispatch that same lane and continue through normal validation and QA. A recovery that cannot resume re-dispatches the lane through the ordinary pipeline and never ends it; do not fabricate a substitute, and a criterion the lane cannot meet is an owner decision (#1, #4), not an exit.

## Long-Running Process Verification

A subagent must not restart a long-running daemon it itself depends on to verify a change. It uses one of: (1) a sandboxed parallel daemon against a throwaway state dir; (2) a static read of the post-build artifact; (3) the pause of Hook Discipline #1, naming the restart command. Inside `/dev-overnight` it takes (1) or (2) and records which as #1 records a decision. `hooks/pretool-bash-safety.sh` blocks a restart of the daemon named by `CLAUDE_PROTECTED_DAEMON_PREFIX` and `CLAUDE_PROTECTED_DAEMON_TARGETS` that lacks its restart grant, and is inert while they are unset, as in the shipped `settings.json`.

## Working Practice

- Communication: concise, technical, no emojis, accuracy over validation; cite locations as `path:line`.
- A library or framework the user names: fetch its Context7 docs before generating library-specific code.
- Multi-source research (5+ sources, site exploration, reflection): delegate to a subagent. Simple 1-3 search queries: `WebSearch` directly.

## Orchestrator Prompt Purity

A dispatch prompt describes **WHAT** (problem, constraints, acceptance criteria), not **HOW** (no tool names, shell commands or shell syntax); the subagent picks its own toolchain. `hooks/pretool-orchestrator-prompt-purity.py` (in `hooks/pretool-dispatch-gate.py`, no switch) gives the orchestrator a warning on a HOW-laden prompt as additionalContext and never blocks.
