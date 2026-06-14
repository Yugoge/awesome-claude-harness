# CLAUDE.md

> Project-specific settings for .claude
> Last updated: 2026-04-29

---

# Global Claude Code Configuration

<!-- AUTO:last-updated -->
> Last updated: 2026-06-14
<!-- /AUTO:last-updated -->

---

## Production Catastrophe Lessons

**NON-NEGOTIABLE.**

### 11. Subagent prompts must explicitly list what is FORBIDDEN, not just what is allowed
Every infrastructure-touching subagent prompt needs an explicit "DO NOT" section; positive instructions alone are insufficient.

### 12. E2E verification requires LIVE browser rendering on BOTH desktop and mobile
Code review, bundle grep, and curl are NEVER sufficient. Trigger content via UI, then verify the rendered result.

### 13. NEVER let a single subagent handle multiple tasks (multitask)
Each subagent invocation handles exactly ONE issue. Launch multiple subagents in parallel for multiple issues — never bundle.

### 14. Subagent rejected by hook MUST PAUSE + report. See Subagent Hook Discipline.

### 15. `disable-model-invocation: true` blocks SlashCommand only — not `Skill` tool calls
Add `Skill(name:*)` to `settings.json` deny for every human-only command; that is the only real technical barrier against agent self-invocation.

---

## 🔄 Auto-Commit Mechanism (refs/checkpoints/*)

Automated snapshots go to `refs/checkpoints/<branch>`; HEADs never advance. `/push` requires clean tree. Full ops: `docs/reference/checkpoint-mechanism.md`.

---

## 🚨 Orchestrator-Only Rule

Main agent is the orchestrator; delegate real work to subagents. Enforced by `~/.claude/hooks/pretool-orchestrator-gate.py`.

- **Whitelist (always allowed)**: `Agent`, `TodoWrite`, `AskUserQuestion`, `Skill`, `CronCreate`, `CronDelete`, `CronList`, `ScheduleWakeup`, `Bash`, `Read` (≤600 lines, capped by `~/.claude/hooks/pretool-read-size-guard.py`), `Glob`, `Grep`. `Bash` capped at 5 consecutive same-name calls.
- **Non-whitelist (`Edit`, `Write`, `WebFetch`, `WebSearch`, `NotebookEdit`, `EnterWorktree`, `ExitWorktree`, `mcp__playwright__*`, …)**: allowed once TOTAL per tool name per turn; intervening different tool calls do NOT reset the count; 2nd same-name call blocks regardless.
- **Permanently blocked**: `EnterPlanMode`, `ExitPlanMode` — even with `/do`.
- **Bypass**: user invokes `/do` this session → gate exits 0 for everything except permanently-blocked tools.
- Subagents (`agent_id` present) bypass all checks. Streak state at `/tmp/claude-tool-streak-<sid>.json`. For files >600 lines, delegate and ask for a summary — never request raw contents.

---

## Core Principles

- **Read before Edit**: always read files before modifying.
- **Cite locations**: provide file paths with line numbers (e.g., `src/index.ts:42`).
- **Parallel execution**: run independent tool calls in parallel.
- **TodoWrite**: track multi-step tasks.
- **Communication**: concise, technical, no emojis, accuracy over validation.

---

## 🚫 Safety Enforcement

Enforced by `~/.claude/hooks/pretool-bash-safety.sh` (PreToolUse). Hook is the authoritative source — see hook for exact patterns and triggers.

---

## 🚳 No branch / PR / worktree creation outside dev-overnight

**NON-NEGOTIABLE (2026-06-04).** Creating any **branch**, **PR**, or **worktree** is forbidden by default in every context — interactive, subagent, automation. A live `/dev-overnight` session is the always-on exception. Two human-authorized escape hatches are preserved: `/do` consent (main agent) and an `/allow` grant for the specific command.

Enforced by two PreToolUse hooks. `~/.claude/hooks/pretool-block-branch-pr-worktree.py` (matcher `Bash`) blocks `git branch <name>` / `checkout -b` / `switch -c` (and `--orphan` / copy forms, path-qualified `git`, attached/clustered short options), `git worktree add`, and `gh pr create`. The `EnterWorktree` tool is blocked by `~/.claude/hooks/pretool-block-enterworktree.sh` (same overnight + `/do` + `/allow` bypass semantics). List / delete / rename / info forms of `git branch`, and `git worktree list/remove/prune`, remain allowed. Bypass: run inside `/dev-overnight` (a live `overnight-state-*.json` under `<project>/.claude/`), use `/do`, or `/allow` the command — or remove the hooks from `settings.json`.

---

## 🛡️ Subagent Hook Discipline

**NON-NEGOTIABLE.** When a hook (PreToolUse / PostToolUse / Stop) rejects a command, the subagent MUST:

1. **PAUSE** immediately and report the rejected command + hook output to the user.
2. **NOT** circumvent via shell wrappers, intermediary scripts, hook-source recon, or hook-file edits.
3. If the task genuinely requires the rejected operation, output a **REQUEST** message to the user describing exactly what needs to run and why; the user decides.

### Sentinel-grant mechanism (task 20260519-211515 R2)

`/allow` now writes a **structured sentinel grant** at `/tmp/claude-grants/<task_id>.json` containing `{task_id, session_id, allowed_operations[], created_at, expires_at}`. `allowed_operations[]` is a structured list of `{op, target?, args_contain?}` dicts — **NOT** a free-text pattern that grep matches against the command line. The hook reads this sentinel via `hooks/lib/allowlist.py::match_sentinel_grant_for_bash_command()` and matches structurally on the bash sub-command's first whitespace-separated word (`op`), optional second word (`target`), and optional `args_contain[]` arg-fragments. **Command-text grep is no longer the grant declaration channel** — substring matching against the raw command line is forbidden. The sentinel is unlinked on **any terminal result** (success, non-zero exit, malformed grant JSON, or comment-only attack) by `hooks/posttool-allowlist-consume.py`; `hooks/stop-cleanup-allowlist.sh` reaps expired sentinels at session end.

---

## 🌙 Long-Running Process Verification

A subagent MUST NOT restart a long-running daemon it itself depends on to verify a change. Use one of: (1) sandboxed parallel daemon against a throwaway state dir; (2) static read of the post-build artifact; (3) PAUSE-PENDING-USER — output a REQUEST naming the restart command and stop.

---

## Security, Style, MCP & Web Search

- Secrets via environment variables / `.env`; never commit credentials. Validate and sanitize all user input. Apply least privilege. Keep dependencies patched.
- Match existing project style; respect linter/formatter config. Comments explain *why*, not *what*.
- Library/framework named by user → fetch Context7 docs before generating library-specific code.
- Multi-source research (5+ sources, site exploration, reflection): delegate to `@deep-search` (`/deep-search`, `/research-deep`, `/search-tree`, `/reflect-search`, `/site-navigate`). Simple 1-3 search queries: WebSearch directly.

---

## 🚦 Orchestrator Prompt Purity

When dispatching a subagent via `Agent`, the prompt describes **WHAT** (problem, constraints, acceptance criteria) — not **HOW** (no tool names, shell commands, or shell syntax). The subagent picks its own toolchain.

Enforcement: `~/.claude/hooks/pretool-orchestrator-prompt-purity.py` (PreToolUse Agent matcher).

---

## 🔗 Nested .claude Repo

`/root/.claude` symlinks to `/dev/shm/dev-workspace/dot-claude` (separate git repo). For `.claude/*` commits, work inside that path — never push from `/root`.
