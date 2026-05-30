---
description: Autonomous overnight development loop - continuously explores codebase, finds issues, fixes them, and repeats until end-time
disable-model-invocation: true
---

# Dev-Overnight: Autonomous Continuous Development

**Scope**: Code-writing tasks (.svg/.css/.html/.js/.ts/.py/...) go to `dev`. Specialists, BA, and QA produce .md/.json only. TodoWrite tracking discipline is codified in Hard Rule 6 below.

**Philosophy**: Explore autonomously, discover real issues, fix them systematically, loop until time expires, then summarize everything.

This command runs an unattended development loop. When `spec_mode == "autonomous"`, you are fully autonomous -- no user input is needed or expected. When `spec_mode == "user-provided"`, honor the orchestrator view's Hard Rule 10 user-pause gate; do not auto-loop past it. You discover issues yourself by scanning the codebase, fix each one through a simplified dev cycle, and keep going until the specified end time (autonomous mode) or until the next user-gate pause (user-provided spec mode).

**Quick status utility**: Use `bash ~/.claude/scripts/overnight-status.sh` for instant session status (zero LLM cost). Use this instead of reading/parsing the state JSON manually. Optionally pass session_id as argument.

---

## Standard Dispatch Envelope

> **Status**: reference material for the dispatch templates in Steps 2a/2b/2c/3-14. The per-dispatch templates in this file are NOT yet rewritten to reference this envelope — that compression is deferred to Cycle 2 (per architect Section D ordering: envelope MUST exist before templates can point at it). This section captures the truly-invariant prose so the next cycle can replace per-template duplicates with `<<envelope>>` references.

Every Agent dispatch from this orchestrator shares the following invariant prelude. The variant per-dispatch text (Requirement, Context file, Output path, role-specific instructions) is composed AFTER this prelude and remains in each step.

**Common prelude (invariant across all overnight dispatches)**:

1. **FIRST ACTION (sentinel registration, dev-registry enforcement)**:
   `FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID/<role>.json to register with the enforcement system. Do this BEFORE any other tool call.`
   Substitute `<role>` with the dispatched subagent type (`pm`, `ba`, `dev`, `qa`, `architect`, `product-owner`, `user`, `ui-specialist`, …). Without this Read, `pretool-cp-checkin.py` cannot map the subagent UUID to its `agent_type` and `pretool-subagent-code-block.py` falls open. The Step 1 sentinel-fanout loop creates the JSON files for every agent type before any dispatch runs.

2. **CHECKPOINT MARKING (cp-state checklist contract, only when `SPEC_ID` is non-empty AND that role's cp-state file exists)**:
   `CHECKPOINT MARKING: see agents/<role>.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop (discipline expectation tracked via spec-check.py; no hook blocks exit on pending checkpoints today).`
   The full SECOND ACTION semantics — read `cp-state-<role>.json`, mark checkpoints with `/root/.claude/scripts/spec-check.py mark`, waive with the `waive` subcommand, leave zero pending before Stop — are documented once in the Step 1 cp-state handoff section above and inside `agents/<role>.md` itself. The pointer keeps each dispatch one line wide while preserving the contract.

3. **Role declaration**:
   `You are the <role> subagent. Follow agents/<role>.md instructions precisely.` (For BA the file is `.claude/agents/ba.md`. For PM with explicit mode the line becomes `You are the PM subagent in <PM_MODE> mode. Follow agents/pm.md <Mode> Protocol.`)

4. **Project root**:
   `Project path: <worktree_path from state file if set, otherwise project_path>` — every subagent's file reads/writes/git ops MUST stay inside this root.

5. **Standard Return-JSON contract**:
   The dispatched subagent returns a JSON object whose required keys are `status`, `<role>_report_path` (or equivalent artifact path[s]), and `summary`. Subagents extend this shape per `agents/<role>.md`; this orchestrator does not redeclare per-role schemas inline.

**Variant per-dispatch text** (kept inline in each Step 2-20 dispatch template, NOT covered by this envelope):

- Requirement / clarified statement
- Spec file paths (overnight spec, BA spec, context JSON, view file, test-plan, route-map)
- Pipeline-specific timestamp suffix and pipeline_id
- Mode flags (e.g., `PM_MODE: TRIAGE`, `RETRO`, `BA-VALIDATION MODE`, `UI_MODE`)
- Iteration count, prior_attempt_signals, QA objections (when re-invoking after failure)
- Output report path (`docs/dev/<artifact>-<timestamp>.json` or per-cycle directory)

**Cycle 2 work (deferred)**: per-dispatch templates are rewritten to reference `<<envelope>>` and contain only the variant text. Spec compliance for that cycle: each dispatch template ≤ 12 lines (variant only), envelope expands at orchestrator-injection time.

---

## Overview

```
Hook creates state file + worktree + view detection (automatic)
  |
Step 1: Read state file + enter worktree (first run only)
  |
  +---> EXPLORATION PHASE (Step 2)
  |       Step 2: PM-Plan subagent (builds test plan with priorities + recommended_specialists)
  |       Main agent reads test plan, extracts priority context + recommended specialists
  |       Step 3: PM-recommended specialist subagents scan SERIALLY, one at a time (with priority context)
  |       Step 4: PM-Triage subagent (reads specialist reports, writes triage)
  |                |
  |       PIPELINE CREATION (Step 6)
  |       Main agent reads PM triage report, creates pipelines in triage order
  |                |
  |       PARALLEL BA PHASE (Step 8-9)
  |         Launch ALL N BA subagents in parallel → validate all outputs
  |                |
  |       BA-QA VALIDATION (Step 10)
  |         Launch ALL N QA-validates-BA subagents in parallel
  |                |
  |       BA-QA ITERATION (Step 11)
  |         Per-pipeline BA-QA iteration loop (max 3) if QA rejects
  |                |
  |       PARALLEL DEV PHASE (Step 12-13)
  |         Launch ALL N Dev subagents in parallel → validate all outputs
  |                |
  |       PARALLEL QA PHASE (Step 14-15)
  |         Launch ALL N QA subagents in parallel → process all results
  |                |
  |       ITERATION LOOPS (Step 17)
  |         Per-pipeline Dev→QA re-runs for failures (max 5 each)
  |                |
  |       PERMISSIONS (Step 18)
  |         Aggregate permissions from all N pipelines, apply once
  |                |
  |       LOG & TIME CHECK (Step 19)
  |       Log all N pipeline results to cycle_log file, check end-time
  |                |
  |       PM RETROSPECTIVE (Step 20)
  |       PM reads all results, writes retro-report, hands off to next cycle
  |                |
  |       SUMMARY OR LOOP (Step 21)
  |       Time remaining? → reset todos, loop to Step 2
  |       Time expired? → generate summary, cleanup
  |                |
  |       TODO COMPLETION DETECTION (PostToolUse hook)
  |       All 21 steps completed?
  |         YES + time remaining: reset todos, loop to Step 2
  |         YES + time expired: allow natural completion
  |         NO: continue current step
```

---

## IMPORTANT RULES

1. **Autonomy is gated by `spec_mode`**, with a third clause for autonomy-directive override.
   - **Clause A** — `spec_mode == "autonomous"`: do NOT ask the user anything; make decisions yourself.
   - **Clause B** — `spec_mode == "user-provided"` AND focus does NOT contain autonomy-directive tokens: honor the spec's user-gate pauses (orchestrator view Hard Rule 10) — pause the loop at every spec-defined user gate and do not auto-resume past it.
   - **Clause C (autonomy-directive override)** — `spec_mode == "user-provided"` AND focus contains any of `\b(autonomously|manual\s+interrupt|don.?t\s+ask|no\s+questions)\b` (case-insensitive): treat the run as autonomous regardless of spec_mode. The orchestrator MUST NOT emit `<options>` XML or interrogative endings. When genuine deadlock occurs (e.g., META-DEADLOCK where a hook blocks the very fix needed), the orchestrator MUST: (a) write a deadlock report to `docs/dev/overnight-deadlock-<ts>.md` with the situation summary; (b) skip the blocked work item; (c) continue with the next pipeline; (d) defer all user-input questions to the end-of-overnight summary. Asking the user mid-cycle is a Clause-C violation.
2. **Loop continuously in autonomous mode**. When `spec_mode == "autonomous"`, after each fix cycle the todo completion hook handles looping; this is non-negotiable. When `spec_mode == "user-provided"`, the loop pauses at every spec-defined user gate and only resumes after the user clears the gate.
3. **Cycles are user-pathway-filtered and priority-driven** (per spec-20260503-091826 Section 5.5 decision #2 — same user-need-centric philosophy as `/dev`, with explore-mode compatibility preserved per Section 5.7 anti-pattern #5). Specialists' free exploration behavior is unchanged — they continue to discover broadly. PM triage applies the user-need path-relevance filter (agents/pm.md Step 4): in **user-provided mode**, the user spec's Section 5 user-need IS the path; pipelines are gated to user-pathway-relevant findings. In **autonomous mode**, only Tier 1 blockers AND multi-agent-consensus findings get pipelines; remaining findings route to the cycle's `out_of_scope_observations` array (per agents/pm.md schema). Within the gated pipeline set, ordering remains by tier: Tier 1 (blockers) first, Tier 2 (major), Tier 3 (minor/cosmetic). Specialists continue to explore broadly — the gating is purely on what becomes a pipeline, not on what specialists are allowed to discover.
4. **ALL exploration and fixes via subagents**. Use Agent tool for ALL scanning, analysis, and implementation work. Main context only handles TodoWrite and loop control.
5. **Skip unfixable issues**. If a fix fails verification 3 times, mark it as skipped and move on.
6. **Track everything**. Use TodoWrite for per-cycle progress. Do NOT write to `.claude/overnight-state-<sid>.json` from the main agent — that file is owned by the orchestrator hooks. See `docs/dev/state-file-write-policy.md` for the full per-field write matrix.
7. **The Stop hook prevents premature exit**. The time-lock hook will block conversation termination until end-time. Do not try to circumvent it.
8. **Git checkpoint vs HEAD commit are distinct semantic layers**. The existing posttool-git-checkpoint.sh hook writes mid-cycle Write/Edit snapshots to `refs/checkpoints/*` only — these are NOT merge-ready commits and they do NOT advance any branch HEAD. They exist for crash recovery and audit, not for shipping. End-of-cycle Step 19 lands a real HEAD commit on the worktree branch by calling `commit.sh "chore(overnight): end-of-cycle commit for <branch>"` directly via Bash (single positional arg, CC-valid `chore` type, `(overnight)` scope identifies automated context) — that HEAD commit IS merge-ready and is the only artifact `/merge` consumes. See `/root/.claude/CLAUDE.md` (Auto-Commit Mechanism section) for the full checkpoint-ref vs HEAD-commit contract. Do NOT conflate "checkpoint after fix" (refs/checkpoints/*, recovery-only) with "ship upstream" (HEAD commit + `/merge`, distribution).
9. **Cycle-end deploy is autonomous-mode only** (canonical overnight Hard Rule 9). When `spec_mode == "autonomous"`, every cycle MUST end with QA rebuilding and redeploying via `docker compose build` and `docker compose up -d` for the project's own services (identified from `docker-compose.yml`); deploy verification is REQUIRED in this mode. When `spec_mode == "user-provided"`, deploy is NOT mandatory at the engine level — the user spec dictates whether to deploy (the orchestrator view's Pipeline Workflow may instruct deploy, may instruct skip, or may defer to a user gate). Regular `/dev` (single-pass, NOT `/dev-overnight`) MUST NOT auto-deploy regardless of spec_mode — `/dev` is a single-feature implementation pass, not an overnight cycle. Do NOT touch unrelated services or infrastructure.
10. **Deduplicate**. Check the state file's cycle_log before starting a fix -- do not re-fix issues already addressed.
11. **One issue per subagent, no exceptions**. Each BA subagent analyzes exactly ONE pipeline issue. Each Dev subagent implements exactly ONE pipeline fix. Each QA subagent verifies exactly ONE pipeline fix. The orchestrator launches N parallel subagents for N pipelines -- but each individual subagent handles only its own single pipeline. NEVER bundle multiple pipeline issues into one subagent prompt.

---

## Overnight Incident Lessons (2026-03-28)

**NON-NEGOTIABLE.** Full stories: `docs/incidents-2026-03-28.md`. Rules 1, 2, 4, 5, 6 are general dev hygiene already covered by `~/.claude/CLAUDE.md` (never weaken checks; PM prioritizes only; compare against reference before fixing; output quality > absence of errors; no unsolicited improvements). The overnight-specific rules below are load-bearing:

### Rule 3: Specialists report symptoms only — no root cause, no fix suggestions
Specialists observe and report. Root cause analysis is exclusively BA's job.

### Rule 7: Global agent files must be project-agnostic
Files in `~/.claude/agents/` and `~/.claude/commands/` apply to ALL projects. No project-specific examples.

### Rule 8: Autonomy-directive in focus overrides spec_mode (2026-04-26 incident)
When `spec_mode == "user-provided"` is auto-detected from a spec but the user's focus string explicitly demands autonomy (`autonomously`, `manual interrupt`, `don't ask`, `no questions`), Hard Rule 1 Clause C applies: behave as autonomous. Emitting `<options>` XML or interrogative endings under autonomy-directive override is a critical violation — it causes the chat UI to go idle awaiting user input even though the Stop hook is blocking termination. Source: BA spec `docs/dev/ba-spec-stop-hook-gap-20260426-2250.md` + architect report `docs/dev/architect-stop-hook-gap-20260426-2245.json`. Enforcement: `pretool-orchestrator-prompt-purity.py` rejects subagent dispatches containing `<options>` when overnight is active; main-agent text emission is unhookable, so this rule is the primary defense.

---

## Arguments

```
/dev-overnight [end-time] [focus] [--spec path/to/spec.md] [--codex]
```

**Examples**:
- `/dev-overnight 6:00` — run until 6:00, no focus (explore everything)
- `/dev-overnight 6:00 fix pipeline bugs` — run until 6:00, focus on pipeline bugs
- `/dev-overnight fix hooks` — default 8h, focus on hooks issues
- `/dev-overnight` — default 8h, no focus
- `/dev-overnight 6:00 --spec docs/my-spec.md` — run until 6:00, use user-provided spec
- `/dev-overnight 6:00 fix UI --spec docs/ui-spec.md` — focus + user spec
- `/dev-overnight 6:00 --codex` — run until 6:00 with Codex adversarial review enabled for all subagents

**Parse `--codex`**: If `$ARGUMENTS` contains the literal token `--codex` (in any position), strip it from the argument string and set `codex_required = true`. Otherwise set `codex_required = false` (default). When `codex_required = true`, every BA / QA / dev / PM dispatch prompt MUST include the literal line `codex_required: true` so each subagent's OPT-IN Codex consultation block activates. When `codex_required = false`, do NOT include that line.

**`--spec` argument**: If provided, the session operates in **user-spec mode**:
- The spec file is read by PM in PLAN mode (PM acts as supervisor, not full explorer)
- Issues described in the user's spec are automatically Tier 1
- Every subagent (BA, Dev, QA, PM-Retro) receives the spec path and reads it on startup
- PM validates agent output against the user's spec during RETRO

If `--spec` is NOT provided, the session operates in **autonomous mode** (default):
- PM explores the app and discovers issues normally
- After PM TRIAGE creates pipelines, the orchestrator creates spec files from the template at `~/.claude/templates/overnight-spec.md`
- Each pipeline gets its own spec file at `docs/dev/overnight/<session_id>/spec-pipeline-<index>.md`

**Argument parsing, spec auto-detection, and view detection are all performed by `create-overnight-state.sh` during session creation.** Read the resulting state file in Step 1 — it contains `user_spec_path`, `spec_mode`, and `view_paths` (manifest.views dict, or null when no views exist). Subagents receive their per-agent view path alongside the monolith spec path; null `view_paths` means legacy spec-only mode (still supported). When a spec was auto-detected from `docs/dev/specs/`, Step 1 announces it.

The `focus` string is stored in the state file and passed to all 4 specialist subagents as a discovery hint. It helps specialists focus their scans; specialists' free-exploration behavior is preserved per spec-20260503-091826 Section 5.7 anti-pattern #5 (specialists' free exploration must NOT be reduced). Pipeline creation, however, is gated by PM Step 4 User-Need Path Relevance Filter (agents/pm.md): user-pathway-relevant findings (in user-provided mode) or Tier 1 + multi-agent-consensus findings (in autonomous mode) become pipelines; the rest route to `out_of_scope_observations`. Additionally, in Step 7, the orchestrator converts the focus into quantitative QA verification criteria that are passed to QA subagents in Step 15 as mandatory pass/fail checks.

---

## Implementation

### Step 1: Read State File and Enter Worktree

The state file has already been created by the UserPromptSubmit hook at `.claude/overnight-state-<session_id>.json`, including `worktree_path`, `worktree_branch`, `view_paths`, `user_spec_path`, `spec_mode`, and `current_phase: "exploring"`. List `.claude/overnight-state-*.json` and read the file matching the current session.

**Read the state file** to get the end_time, session_id, worktree_path, spec_mode, user_spec_path, view_paths, and confirm initialization. If multiple state files exist, use the one matching the current session.

If no state file exists (edge case), create it manually using the v4 schema with a generated session_id.

**WORKTREE GUARD**: Check the state file's `worktree_path` field.
- If `worktree_path` is NOT null: `cd` into the worktree path.
- If `worktree_path` IS null (edge case: worktree creation failed during hook): log a warning and continue on the current branch.

**Spec announcement**: If `spec_mode` is `"user-provided"` and `user_spec_path` is set, announce:
```
Spec mode: user-provided
Spec path: <user_spec_path>
```
If `user_spec_path` was auto-detected (not passed via `--spec`), also announce:
```
(Auto-detected by session creation hook. Pass --spec <other-path> to override.)
```

**Announce initialization**:

```
Overnight development session initialized.
Start time: <start_time>
End time: <end_time>
Worktree: <worktree_path or "none (using current branch)">
Loop: todo-completion-driven (automatic reset on cycle complete)
Time-lock hook is active -- session will not terminate until end-time.
Beginning autonomous exploration...
```

**Codex enforcement flag** (only when `codex_required` field in state file is `true`): Read `codex_required` with `jq -r '.codex_required // false'` (defaults safely for old state files). When `true`, after binding `$DEV_SESSION_ID`, run `scripts/write-codex-enforce.sh`. If it exits non-zero, abort. When `codex_required = true`, every BA / QA / dev dispatch prompt below MUST include the literal line `codex_required: true`.

```
CODEX_REQUIRED=$(jq -r '.codex_required // false' "$STATE_FILE")
# ... (bind DEV_SESSION_ID from state file first, then) ...
[[ "$CODEX_REQUIRED" == "true" ]] && \
  scripts/write-codex-enforce.sh --source-command dev-overnight --session-id "$DEV_SESSION_ID"
```

**Initialize dev-registry for hard subagent enforcement** (MANDATORY — do this before ANY Agent launch):

The hook `pretool-subagent-code-block.py` blocks non-`dev` subagents from writing code files, but it needs the Claude-internal subagent UUID to be registered against an `agent_type`. Root cause of the /dev gap (see commit `e086ccb`): /dev-overnight sessions produce no `.claude/specs/` cp-state files, so the hook falls open and every subagent can write code. The fix is an orchestrator-provided sentinel file that each subagent reads as its FIRST ACTION; `pretool-cp-checkin.py` then writes the UUID→agent_type mapping into `.claude/dev-registry/agent-index.json`.

Reuse the overnight `session_id` from the state file (do NOT invent a new one — the same value is reused across cycles and continuations). Bind it as `$DEV_SESSION_ID` and derive the registry directory:

```bash
DEV_SESSION_ID="<reused-from-overnight-state.json>"
REGISTRY_DIR="$CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID"
```

**E2E enforcement flag** (unconditional — always-on): Now that `$DEV_SESSION_ID` is bound, run `scripts/write-e2e-enforce.sh` to activate the E2E gate for QA. If it exits non-zero, abort.

```bash
scripts/write-e2e-enforce.sh --source-command dev-overnight --session-id "$DEV_SESSION_ID"
```

Create sentinel files for every agent type this orchestrator can launch, including overnight-only specialists.

**Sentinel-write idiom (M10 harness-fixes 20260428)**: the worktree-guard's `_extract_bash_write_paths` static scan treats `$VAR` and `${VAR}` tokens as opaque (it intentionally cannot tell legitimate from adversarial `$VAR` writes — see arch-3). The orchestrator MUST therefore use one of the two acceptable forms below. Forms that interpose a same-line-assigned shell variable into the redirect target (e.g. `REG=$CLAUDE_PROJECT_DIR/...; > "$REG/$agent.json"`) will be blocked by the worktree boundary even though the harness-state exemption is active, because the static scan cannot resolve `$REG` and the realpath check fails.

**Acceptable form A — Write tool with literal absolute `file_path`** (one tool call per sentinel; the Write tool does NOT shell-expand env vars, so use a literal path):

```text
Write(file_path="/root/.claude/dev-registry/<session_id>/architect.json", content='{"agent_type": "architect", "session_id": "<session_id>"}')
Write(file_path="/root/.claude/dev-registry/<session_id>/ba.json", content='{"agent_type": "ba", "session_id": "<session_id>"}')
Write(file_path="/root/.claude/dev-registry/<session_id>/graphify.json", content='{"agent_type": "graphify", "session_id": "<session_id>"}')
... (one Write per agent type)
```

**NOTE (C6, redev-tier123)**: Write tool does not shell-expand env vars; use the literal `/root/...` path. Form B is allowed to use `$CLAUDE_PROJECT_DIR` because Bash redirect targets ARE expanded by the static scan in `lib/bash_write_targets.py:_resolve_path`.

**Acceptable form B — Bash redirect with `$CLAUDE_PROJECT_DIR`-prefixed target** (the static scan resolves `$CLAUDE_PROJECT_DIR` via `lib/bash_write_targets.py:_resolve_path`, lines 156-160). Inline the session_id literally; do NOT introduce intermediate variables in the redirect target:

```bash
mkdir -p "$CLAUDE_PROJECT_DIR/.claude/dev-registry/<session_id>"
printf '{"agent_type": "architect", "session_id": "<session_id>"}\n' > "$CLAUDE_PROJECT_DIR/.claude/dev-registry/<session_id>/architect.json"
printf '{"agent_type": "ba", "session_id": "<session_id>"}\n' > "$CLAUDE_PROJECT_DIR/.claude/dev-registry/<session_id>/ba.json"
printf '{"agent_type": "graphify", "session_id": "<session_id>"}\n' > "$CLAUDE_PROJECT_DIR/.claude/dev-registry/<session_id>/graphify.json"
# ... (one printf per agent type; substitute the literal session_id read from the state file)
```

Either form populates the same sentinel files. Form A is more verbose but tool-policy-cleanly preserves one Write per sentinel; form B is more concise but requires the orchestrator to inline the session_id verbatim into each target path.

Every Agent launch prompt in this orchestrator MUST begin with a `FIRST ACTION` line instructing the subagent to `Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID/<agent>.json` before any other tool call. Without that Read, the enforcement hook will fail open for that subagent. In continuation mode (after a hook-induced context reset), re-run the `mkdir -p` + sentinel loop above — it's idempotent, so re-running is safe and guarantees sentinels exist even if a cleanup step removed them.

**Initialize cp-state handoff when a user-provided `/spec` exists** (MANDATORY in `spec_mode == "user-provided"` when cp-state files exist):

Resolve the spec-id via the centralized resolver — never derive it from the
`user_spec_path` basename by hand (that prefix drift silently dropped de-prefixed
specs to monolith mode):

```bash
if [ -n "$user_spec_path" ]; then
  RESOLVED_JSON=$(/root/.claude/scripts/resolve-spec-artifacts.py \
      --spec-path "$user_spec_path" --project-dir "$CLAUDE_PROJECT_DIR") || {
    echo "spec-artifact resolution FAILED (path mismatch / present-but-invalid split)." >&2
    exit 1; }
  SPEC_ID=$(jq -r .artifact_id <<<"$RESOLVED_JSON")
  CP_DIR=$(jq -r '.cp_dir // empty'   <<<"$RESOLVED_JSON")
  VIEWS_DIR=$(jq -r '.views_dir // empty' <<<"$RESOLVED_JSON")
  [ -d "$CLAUDE_PROJECT_DIR/$CP_DIR" ] || { SPEC_ID=""; CP_DIR=""; }
else
  SPEC_ID=""; CP_DIR=""; VIEWS_DIR=""
fi
```

**T1.7 (redev-tier123) — Orchestrator-view + Section 5 read MANDATE**: When `SPEC_ID` is non-empty, BEFORE composing any subagent dispatch prompt, you MUST read the orchestrator view the resolver located — `$CLAUDE_PROJECT_DIR/$VIEWS_DIR/orchestrator.md` (views live under `docs/dev/specs/<artifact_id>/views/`, NOT under `.claude/specs/`) — AND the spec's Section 5 (User's Acceptance Criterion) verbatim from `$user_spec_path`. Quote the user's words from Section 5 directly into every dispatch prompt; do not paraphrase or summarize. The user's verbatim need is the binding contract — every subagent must see the user's literal request, not your reformulation.

If no spec/cp-state directory exists, set `SPEC_ID=""` and skip the `SECOND ACTION`
lines below. If a particular agent has no cp-state file under that SPEC_ID, omit that
agent's `SECOND ACTION` for this launch. When `SPEC_ID` is non-empty, every Agent launch prompt for an agent that has a
cp-state file MUST include a `SECOND ACTION` line immediately after the dev-registry `FIRST ACTION`:

```text
SECOND ACTION: Read $CLAUDE_PROJECT_DIR/$CP_DIR/cp-state-<agent>.json to load your mandatory checklist before doing substantive work. Mark each completed checkpoint with /root/.claude/scripts/spec-check.py mark --spec-id <SPEC_ID> --agent <agent> --agent-id $CLAUDE_AGENT_ID --cp-id <cp-NN>. Waive only with /root/.claude/scripts/spec-check.py waive --spec-id <SPEC_ID> --agent <agent> --agent-id $CLAUDE_AGENT_ID --cp-id <cp-NN> (auto-text records actor + ISO timestamp). You MUST leave zero pending checkpoints before Stop (a discipline expectation tracked via spec-check.py — no hook blocks exit on pending checkpoints today). If `$CLAUDE_AGENT_ID` is unavailable, use the `agent_id` value written into the cp-state file by the read.
```

This gives overnight specialists the same checklist semantics as BA/Dev/QA:
check-in happens on the cp-state read, and each specialist is expected to leave
the checklist fully done or waived before Stop (tracked via spec-check.py; no hook
blocks exit on pending checkpoints today).

**Write verbatim user requirement document** (MANDATORY — do this once in Step 1, before any Agent dispatch):

```bash
PROJECT_ROOT="${WORKTREE_PATH:-$CLAUDE_PROJECT_DIR}"
mkdir -p "$PROJECT_ROOT/docs/dev"
REQUIREMENT_DOC="$PROJECT_ROOT/docs/dev/user-requirement-${DEV_SESSION_ID}.md"
cat <<'REQEOF' > "$REQUIREMENT_DOC" || { echo "ERROR: Failed to write user requirement document — aborting." >&2; exit 1; }
<verbatim focus / requirement text from state file — paste literal text here, no shell variables inside heredoc>
REQEOF
```

When `user_spec_path` is non-null, also append the spec path and Section 5 verbatim to the same document (do not summarize):

```bash
if [ -n "$USER_SPEC_PATH" ]; then
  printf '\nUser spec path: %s\n' "$USER_SPEC_PATH" >> "$REQUIREMENT_DOC"
  printf '\nSection 5 (User Acceptance Criterion):\n' >> "$REQUIREMENT_DOC"
  # Read Section 5 verbatim from the spec file and append — do not paraphrase
fi
```

This document is the source-of-truth anchor for the entire overnight session. Every subagent reads it before interpreting any derived context or spec. Use a single-quoted heredoc delimiter (`'REQEOF'`) so `$`, backticks, and shell metacharacters are never expanded. This write is idempotent across continuation cycles (same `DEV_SESSION_ID` reused). When including this path in dispatch prompts, always substitute the resolved value of `$REQUIREMENT_DOC` — MUST NOT pass literal `<PROJECT_ROOT>` or `<DEV_SESSION_ID>` placeholders to subagents; expand them to actual values at dispatch time.

---

### Continuation Mode

When you see "OVERNIGHT CONTINUATION" injected by the prompt hook, you are in continuation mode with fresh context.

**In continuation mode**:
1. Read the state file to determine `current_phase`
2. Skip Step 1 entirely (worktree already exists)
3. Resume from the appropriate step based on current_phase:
   - `initializing` or `exploring` -> Step 2 (PM Plan)
   - `pipeline_creation` -> Step 6 (Create pipelines)
   - `analyzing` -> Step 8 (Parallel BA)
   - `implementing` -> Step 12 (Parallel Dev)
   - `verifying` -> Step 14 (Prepare QA Environment)
   - `iterating` -> Step 17 (Iteration loops)
   - `logging` -> Step 19 (Log)
   - `retrospective` -> Step 20 (PM Retro)
4. The hook has already injected the command specification and state summary into this prompt

---

## Four Contracts Awareness (Orchestrator Role)

The BA subagent enforces four domain-agnostic contracts (see
`~/.claude/agents/ba.md` §Four Contracts). The orchestrator MUST
complement BA by surfacing context before delegation and verifying
compliance after BA returns. The orchestrator does NOT re-do BA's work —
it prepares inputs and validates outputs.

In overnight mode this is especially load-bearing because many iterations
compound. A single L1-only fix that should have been L3 silently
propagates failure across the whole night.

### Pre-BA: surface retry signals

Before delegating to BA, scan the current iteration's input and repo state
for retry signals:

- **Retry phrasing** in the iteration prompt or triage report: "again",
  "still", "didn't fix", "Nth time", "again", "still broken", "not fixed"
- **Recent related commits from this overnight run** (example query: `git log --oneline --grep="<keyword>" HEAD~30..HEAD`)
- **Existing BA specs from earlier iterations**: files matching
  `docs/dev/ticket-*.md` (or legacy `docs/dev/ba-spec-*.md`) with keywords from the current issue
- **Prior-cycle failure reports**: any QA report flagged as failed in an
  earlier iteration that matches the current issue

Pass findings to BA in the delegation prompt under an explicit
`prior_attempt_signals` block:

    prior_attempt_signals:
      retry_phrase: "<matched phrase or null>"
      recent_commits: ["<hash> <subject>", ...]
      existing_specs: ["docs/dev/ticket-<ts>.md", ...] (legacy historical artifacts also accepted: docs/dev/ba-spec-<ts>.md)
      prior_qa_failures: ["docs/dev/qa-report-<ts>.md", ...]

### Post-BA: verify contract compliance

Before proceeding to dev, verify the BA JSON context contains:

- `evidence.measured.value` populated
- `evidence.expected.source` populated
- `scope_expansion.all_occurrences` non-empty (or explicit not_applicable)
- `reference_source.tier` not `tier_3_tainted` when `copy_allowed: true`
- If Contract D triggered: `prior_attempts.novelty_check.differs_from_all_priors = true`

If any check fails, the orchestrator re-delegates to BA with explicit
feedback. Do NOT proceed to dev with an incomplete spec. Do NOT skip
validation to keep the overnight loop running — a non-compliant spec in
overnight is worse than a stalled iteration.

### BA rejection handling in overnight mode

If BA returns `status: "rejected"` (Contract D novelty-check failure):

- Do NOT retry BA with the same input
- Record the rejection in the cycle retrospective
- Mark this issue as `blocked_same_layer_retry` and SKIP to the next
  issue in the triage queue — do not burn further iterations on a
  redesign-needed problem
- On RETRO, surface the blocked issue for user review next session

### Layer vocabulary (shared with BA)

Layers from shallow to deep:

- **L1 cosmetic**: styling, class names, component swap
- **L2 structural**: layout, component hierarchy
- **L3 data**: coordinates, schema values, regex, constants, SVG paths
- **L4 logic**: conditions, state machines, data flow
- **L5 infrastructure**: build, deploy, environment

The PM subagent MUST record the layer in its per-issue triage output so
the orchestrator can detect "same-layer retry" patterns across iterations.
When dev reports back, verify implementation layer matches BA's spec layer.

### UI Mode Detection

Parse the invocation flags:
- If invoked as `/dev-overnight --ui-spec <path>`, this is a UI Development workflow:
  - Read the ui-spec markdown (must have YAML frontmatter with `ui_target`, `viewport_targets`, `design_inputs`)
  - Skip autonomous discovery (PM-Plan does NOT call architect/product-owner/user — only ui-specialist DESIGN_MODE + BA + dev + qa UI_MODE)
  - Set workflow_type="ui_development" in cycle-contract.json
- Otherwise, run the existing autonomous overnight discovery flow (workflow_type="ui_audit" or "general", as decided by PM-Plan).

### Exploration Phase (Steps 2 - 5)

**CRITICAL: The exploration phase has four sub-steps. Step 2 launches the PM subagent to build a test plan (which includes a `recommended_specialists` field). The main agent then reads the test plan and extracts priority context. Step 3 launches ONLY the PM-recommended specialist subagents with that priority context. Step 4 launches PM again in TRIAGE mode to classify all findings.**

Read the state file's `addressed_issues` array first.

#### Step 2: Launch PM Subagent

Launch the PM (test plan manager) subagent to build a structured test plan. The PM
uses Playwright to explore the running app first (Phase 0), then reads CLAUDE.md
and the state file, and writes test-plan.json with firsthand browser evidence in
the `pm_experience` section.

```
Use Agent tool with:
- subagent_type: "pm"
- description: "Build test plan from project docs and session history"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID/pm.json to register with the enforcement system. Do this BEFORE any other tool call.
  CHECKPOINT MARKING: see agents/pm.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the PM subagent. Follow agents/pm.md instructions precisely.

  User requirement document: <PROJECT_ROOT>/docs/dev/user-requirement-<DEV_SESSION_ID>.md
  (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

  Project path: <worktree_path from state file if set, otherwise project_path>
  State file path: <path to overnight-state-*.json>
  Session ID: <session_id>
  Output test plan to: docs/dev/overnight/<session_id>/test-plan.json

  <If spec_mode == 'user-provided', include:>
  Overnight spec file: <user_spec_path from state file>
  Spec mode: user-provided
  You are in SUPERVISOR mode. Read the user's spec file first. Issues described
  in the spec are pre-validated -- skip full browser exploration for those issues.
  Focus your exploration on discovering ADDITIONAL issues not covered by the spec.
  Set spec_mode: 'user-provided' and spec_path in your test plan output.

  <If spec_mode == 'user-provided' AND view_paths['orchestrator'] is non-null, include:>
  Orchestrator view file: <view_paths['orchestrator']>

  Read the orchestrator view FIRST. It contains the project's Role Mandate,
  Pipeline Workflow, Anti-Patterns, and Hard Rules you must enforce as supervisor.
  Incorporate these into your test plan's priority_tiers and recommended_specialists.

  <If codex_required == true, include:>
  codex_required: true
  "
```

**Wait for PM subagent to complete.**

**Validate test plan**: Read `docs/dev/overnight/<session_id>/test-plan.json` and verify:
- File exists and is valid JSON
- Has `app_context` with at least `url` field
- Has `agent_assignments` with all 4 agent keys
- Has `core_flow_gate.owner` set to `"user"`
- Has `core_flow_gate.failure_is_cycle_failure` set to `true`
- Has `pm_experience` section with browser exploration evidence:
  - If `pm_experience.app_not_running` is false: verify `urls_visited` is non-empty
    and `actions_taken` has at least one entry (PM actually explored the app)
  - If `pm_experience.app_not_running` is true: acceptable (app was not running,
    PM fell back to doc-based planning)

If validation fails, re-invoke PM (maximum 2 retries). If still failing, proceed to Step 3 without a test plan (specialists will discover context themselves).

#### After PM-Plan Completes: Extract Priority Context

**Main agent reads test-plan.json** and builds a priority context string for specialists:

1. Read `priority_tiers` from the test plan
2. Read `unresolved_from_previous` from the test plan
3. Build a priority context block (included in each specialist's prompt):

```
Priority context from PM:
- Tier 1 (blockers): [list descriptions from priority_tiers.tier_1_blockers]
- Tier 2 (major): [list descriptions from priority_tiers.tier_2_major]
- Tier 3 (minor): [list descriptions from priority_tiers.tier_3_minor]
Unresolved from previous cycles: [list from unresolved_from_previous with cycle count]

PRIORITY RULE: Investigate Tier 1 issues FIRST. Report ALL issues you find,
but tag each with pm_tier: 1|2|3|new (where "new" = not in PM's list).
```

If the test plan has no `priority_tiers` (first cycle, no history), set the priority context to:
`"No priority tiers from PM -- this is the first cycle. Explore freely and report all issues."`

#### Step 3: Launch PM-Recommended Specialist Subagents

### CRITICAL: Specialists run SERIALLY, not in parallel

Launch specialists ONE AT A TIME (ui-specialist, architect, product-owner, user) — one Agent call per specialist, wait for each to complete before launching the next. NEVER put multiple specialists in a single Agent tool call and NEVER launch 2+ specialists in parallel. Specialists are expensive, one-at-a-time consultations; parallelizing them corrupts evidence ordering and wastes context budget. BA/Dev/QA may still be parallelized — they have instance-isolated state via `spec-check.py --instance-id`; specialists do not.

### Specialist Calling Rule

This step is EXPLORATION — the goal is to discover unknown issues. In exploration, cast a wide net.

**SUPERVISOR MODE (user-provided spec)**: Specialist routing is determined by the
orchestrator view manifest (Agent Relevance table). If the manifest marks N
specialists as relevant for this spec, launch those N specialists per the spec's
Pipeline Workflow. Do NOT default to ZERO. Only fall back to ZERO if the
orchestrator view manifest is missing or malformed (and log this fallback as an
anomaly in the cycle log so the user can fix the view). When the manifest IS
present and explicitly assigns specialists, ignoring it is a contract violation —
the spec's Pipeline Workflow is the authoritative routing source.

**Routing rule** (decide at runtime from the state file):

- **Exploration mode** (no user spec): launch all 4 specialists by default; broad coverage is the point. If PM's `recommended_specialists` field is present and non-empty (test plan), launch that narrowed subset instead. Do NOT use "evaluate then call" here — you cannot evaluate relevance to issues you haven't discovered yet.
- **Supervisor mode** (user-provided spec): issues are pre-known. Apply the dev.md evaluate-then-call rule — for each of the 4 specialists produce `RELEVANT — <reason>` or `SKIP — <concrete reason>`, launch each RELEVANT one sequentially. PM's `recommended_specialists` is advisory only; the assessment is authoritative. Record the assessment in the orchestrator's reasoning as:

```json
"specialists_assessed": {
  "ui-specialist": "RELEVANT — layout issue" | "SKIP — pure backend change",
  "architect": "...",
  "product-owner": "...",
  "user": "..."
}
```

**Supervisor-mode specialist prompts** (when `spec_mode == "user-provided"` AND `view_paths` is non-null):

Before launching specialists, the orchestrator MUST:
1. Read `view_paths["orchestrator"]` (the orchestrator view file)
2. Search for a `## Pipeline Workflow` section in that view
3. If found, extract the per-specialist prompt templates from that section
4. Use those templates as the specialist's focus/task description instead of the default exploration prompt
5. Pass `View file: {view_paths[specialist_type]}` to each specialist so they read their own view

If the orchestrator view contains prompt templates like:
  "When launching ui-specialist: Design <icon>, output SVG + motion CSS"
Then the specialist prompt MUST use that language, NOT the default exploration-mode language
(e.g. "Evaluate visual design quality, assess design system adherence").

Each specialist prompt in supervisor mode should follow this structure:
```
You are the <specialist_type> specialist.

View file: <view_paths[specialist_type]>
Read your view file FIRST — it contains your Role Mandate (what you ARE and ARE NOT)
and the content blocks relevant to your role.

<orchestrator-view prompt template for this specialist, if found in Pipeline Workflow section>

Overnight spec file: <user_spec_path>
Project path: <worktree_path>
Test plan: docs/dev/overnight/<session_id>/test-plan.json
Output report to: <report path>
Priority context from PM: <priorities>
```

If the orchestrator view does NOT contain a `## Pipeline Workflow` section or has no per-specialist templates, fall back to the default exploration prompt below (backward compatible).

**Exploration-mode specialist prompts** (when `spec_mode == "autonomous"` OR `view_paths` is null):

Use the default exploration prompt — same as existing behavior. No view file or spec file needed.

---

```
For each specialist in recommended_specialists (domain-matched only):

Agent(subagent_type: specialist.type)
  Write report to: docs/dev/overnight/<session_id>/<specialist.type>-report.json

Available specialists:
- "product-owner" → docs/dev/overnight/<session_id>/product-owner-report.json
- "architect" → docs/dev/overnight/<session_id>/architect-report.json
- "user" → docs/dev/overnight/<session_id>/user-report.json
- "ui-specialist" → docs/dev/overnight/<session_id>/ui-specialist-report.json

Each subagent receives, at the TOP of its prompt before any other content:
- FIRST ACTION line: "Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID/<specialist.type>.json to register with the enforcement system. Do this BEFORE any other tool call."
- CHECKPOINT MARKING line: "see agents/<specialist.type>.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit." (full SECOND ACTION SPEC_ID/cp-state semantics are defined once in the Step 1 cp-state handoff section above and need not be repeated per dispatch.)
- User requirement document: <PROJECT_ROOT>/docs/dev/user-requirement-<DEV_SESSION_ID>.md (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)
- Project path: <worktree_path from state file if set, otherwise project_path>
- Already addressed: <addressed_issues array from state file>
- Focus: <focus string from state file, or "none">
- Test plan: docs/dev/overnight/<session_id>/test-plan.json
- View file: {view_paths[specialist_type] or null}
- Overnight spec file: {user_spec_path or null}
- Priority context: <the priority context block built in the step above>
- Output report to: <path above>

**Specialist prompt rules** (enforced):
- Every specialist prompt MUST include the test plan path. Specialists have a mandatory Step 0 (read test plan — PM's `pm_experience` is ground truth) and Step 1 (execute the core E2E flow via Playwright) before specialized analysis.
- The priority context block is appended directly so specialists see PM's priorities immediately; their Step 0 read provides redundancy.
- Always use `worktree_path` as the project path when set; specialists must scan files inside the worktree, not the main project directory.
- Do NOT inline application context, credentials, flow steps, or sample data in the prompt — those live in the test plan file.
```

**Announce specialist selection**:
```
PM recommended {N} specialists for this cycle: {list of specialist types}
{If fallback: "No recommended_specialists in test plan -- selected {list} via domain trigger rules."}
Launching specialist subagents...
```

**Wait for all recommended subagents to complete** before proceeding.

**Validate reports** (main agent does NOT read project files, only validates report existence and structure): run `~/.claude/scripts/check-overnight-reports.sh docs/dev/overnight/<session_id>`.

**Sanity checks on each report** (only for specialists that were launched):
- [ ] File exists and is valid JSON
- [ ] Has `issues` array (may be empty)
- [ ] Each issue has required fields: `description`, `location`, `severity`, `category`, `estimated_effort`
- [ ] No duplicate issues within the same report
- [ ] Issues do not overlap with `addressed_issues` from state file

**Report JSON schema** (all 4 subagents output the same schema):
```json
{
  "agent": "product-owner|architect|user|ui-specialist",
  "timestamp": "ISO-8601",
  "project_path": "/path/to/project",
  "scan_duration_seconds": 42,
  "issues": [
    {
      "description": "Brief description of the issue",
      "location": "file/path:line or file/path or 'project-wide'",
      "severity": "critical|major|minor|cosmetic",
      "category": "agent-specific category string",
      "estimated_effort": "small|medium|large",
      "details": "Extended explanation with evidence",
      "observation_notes": "Factual observations and evidence (no fix suggestions)"
    }
  ],
  "summary": "One-line summary of findings"
}
```

**If validation fails** for any report:
- Log which reports failed and why
- Re-invoke only the failed subagent(s) (maximum 2 retries)
- If still failing after retries, proceed with available reports

**If zero issues found across all RELEVANT specialist reports** (reports from launched specialists only — skipped specialists do not count as clean):
- Log a "clean sweep" entry
- After 2 consecutive clean sweeps: generate summary and allow termination

**Core Flow Gate Check**:

After all RELEVANT specialists complete, check whether the user agent was launched this cycle (look up `user` in `specialists_assessed` — `RELEVANT` means its report should exist; `SKIP` means the gate is not applicable).

- If the user agent was SKIPPED this cycle: skip the core flow gate check entirely and proceed to Step 4. Record `core_flow_gate: "skipped — user specialist not launched"` in the cycle log.
- If the user agent was RELEVANT and its report exists: read the user agent's report and check `core_flow_completed`:
  - If `core_flow_completed: false` (or missing): the core flow gate has failed. Log this as a cycle-level failure. The user agent's core flow issues take top priority in Step 4.
  - If `core_flow_completed: true`: gate passed, proceed normally.

When applicable, this gate is non-negotiable: if the user cannot complete the core business flow, the entire cycle is considered failed regardless of other agents' findings.

**Route Map Extraction**: After the user agent completes, check if `route_map_file` exists in its report. If present, read the route map file and note the path for use in subsequent subagent prompts. This route map will be passed to:
- **Dev agent**: as context so it knows which pages might be affected by its changes
- **QA agent**: so it can verify changes don't break pages listed in the route map
- **PM agent** (next cycle only): so PLAN mode can skip browser discovery and use the existing route map

#### Step 4: Launch PM-Triage Subagent

After all RELEVANT specialists complete and their reports are validated, launch PM in
TRIAGE mode to classify and prioritize all findings.

**Dynamic specialist report list**: Build the PM-Triage prompt using the
`specialists_assessed` map recorded in Step 3. Only include report paths for specialists
whose value starts with `"RELEVANT"`. For specialists whose value starts with `"SKIP"`,
list them with their skip reason so PM understands why that perspective is absent and
does NOT attempt to read a non-existent file.

```
Use Agent tool with:
- subagent_type: "pm"
- description: "PM triage: classify and prioritize all specialist findings"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID/pm.json to register with the enforcement system. Do this BEFORE any other tool call.
  CHECKPOINT MARKING: see agents/pm.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  PM_MODE: TRIAGE

  You are the PM subagent in TRIAGE mode. Follow agents/pm.md Triage Protocol.

  User requirement document: <PROJECT_ROOT>/docs/dev/user-requirement-<DEV_SESSION_ID>.md
  (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

  Project path: <worktree_path from state file if set, otherwise project_path>
  Session ID: <session_id>
  Cycle number: <cycle_count + 1>

  You will receive reports ONLY from specialists that were RELEVANT and launched this
  cycle. Skipped specialists are listed below with their skip reason. Do NOT attempt to
  read report files for skipped specialists — those files do not exist.

  Specialist reports (only the specialists actually launched this cycle):
  <For each specialist in specialists_assessed where value starts with 'RELEVANT':>
  - <specialist>: docs/dev/overnight/<session_id>/<specialist>-report.json
  </For>
  <For each specialist in specialists_assessed where value starts with 'SKIP':>
  - <specialist>: SKIPPED — <skip reason from specialists_assessed[specialist]>
  </For>
  - test-plan: docs/dev/overnight/<session_id>/test-plan.json (your own plan for context)

  Core flow gate result: <core_flow_completed from user report>
  Core flow reliability: <core_flow_reliability from user report, if available>
  Time remaining: <calculated time remaining in minutes>

  <If spec_mode == 'user-provided' AND view_paths['orchestrator'] is non-null, include:>
  Orchestrator view file: <view_paths['orchestrator']>

  Read the orchestrator view FIRST. It contains the project's Role Mandate,
  Pipeline Workflow, Anti-Patterns, and Hard Rules you must enforce as supervisor.
  Incorporate these into your triage decisions (tier assignments, pipeline_order,
  recommended_specialists) so specialist invocations comply with the spec's constraints.

  <If codex_required == true, include:>
  codex_required: true

  Write triage report to: docs/dev/overnight/<session_id>/triage-report-cycle<N>.json
  "
```

**Wait for PM-Triage to complete.**

**Validate triage report**: Read `triage-report-cycle<N>.json` and verify:
- File exists and is valid JSON
- Has `mode` field (`focus` or `normal`)
- Has `issues` array (may be empty on clean sweep)
- Has `pipeline_order` array
- Each issue has `tier`, `pipeline_recommendation`, and required fields

If validation fails, re-invoke PM-Triage (maximum 2 retries). If still failing, fall back
to the legacy mechanical sort in Step 6 (read the RELEVANT specialist reports only — per
`specialists_assessed` — merge, sort by severity).

**Check pipeline_blocked**: Read the triage report's `pipeline_blocked` field.
- If `pipeline_blocked: true`: log `block_reasons` to the cycle log file, skip Steps 6-19, jump directly to Step 20 (PM Retrospective) with context that the pipeline was blocked. PM RETRO will analyze the block and recommend next steps. Then loop to Step 2 for the next cycle.
- If `pipeline_blocked: false` or field absent: proceed normally to Step 6.

### Cycle Contract Manifest

**MANDATORY for autonomous overnight cycles per spec-20260426-090235 (P0/M1 contract pipeline).**

Immediately after PM Triage completes (Step 4) and before pipeline creation (Step 6), the orchestrator writes the per-cycle contract manifest. This file is the single source of truth that the contract-aware hooks (`pretool-subagent-enforce.py`, `posttool-subagent-track.py`, `posttool-overnight-file-check.py`) and `check-overnight-reports.py` consume to enforce role/pipeline/artifact compliance for every subsequent Agent invocation in the cycle.

**Output paths** (write both — primary plus colocated mirror so hooks can resolve without scanning):

- Primary: `docs/dev/overnight/<session_id>/cycle-<N>/cycle-contract.json`
- Stable symlink for hooks: `docs/dev/overnight/<session_id>/cycle-current.json` → `cycle-<N>/cycle-contract.json`
- Colocated mirror: `.claude/overnight-contract-<session_id>-cycle<N>.json`

**Schema**: `/root/.claude/schemas/cycle-contract.v1.json` (Draft 7). The full shape is documented there; the orchestrator MUST populate at minimum:

- `schema_version: 1`
- `spec_id` (e.g. the spec id when `spec_mode == "user-provided"`, or `autonomous-<sid>` otherwise)
- `session_id`, `cycle_id` (1-indexed integer), `created_at` (ISO-8601 UTC with terminal `Z`)
- `monolith_sha256` (sha256 of the monolithic spec file when present, else `null`)
- `required_calls`: one entry per Agent call the orchestrator commits to making this cycle. Each entry: `{step, role, mode|null, pipeline_id|null, expected_output_path, schema_name, max_retries}`. Step ids align with the canonical todo (`2`, `3-<specialist>`, `4`, `8`, `10`, `12`, `15`, `20`). Step 14 (Prepare QA Environment) is orchestrator-direct and dispatches no subagent, so it is NOT listed here.
- `pipelines`: keyed by pipeline id with `{ba_status, dev_status, qa_status, artifact_paths {ba, dev, qa}}` — initialise all statuses to `pending`.
- `specialist_selection`: object keyed by specialist name with `{decision, reason, scope, budget {max_pages, max_viewports, max_minutes}}`. Specialists not chosen by PM Plan get `decision: "skip"` (or are omitted entirely — both forms are valid per AC12 variable-specialist-count).

**Sources for population**:

- `required_calls` derives from PM Triage's `pipeline_order` × the canonical pipeline workflow (each pipeline produces one BA call, one Dev call, one QA call) plus the cycle-level PM PLAN/TRIAGE/RETRO entries.
- `pipelines` derives from PM Triage's `issues` array.
- `specialist_selection` derives from PM Plan's `recommended_specialists` field (Step 2 output) reconciled with what was actually launched in Step 3.

**HARD CUTOVER**: this file is the trigger that switches the contract-aware hooks from silent passthrough into enforce mode. Until cycle-contract.json exists, the hooks behave like the legacy /spec single-cycle session. Once it exists, role/pipeline mismatches are exit-2 hard blocks (no warning-then-proceed). The contract's mere presence is the switch — there is no env-var override (per spec-20260426-090235 AC10 / user_decisions.rollout_strategy = HARD CUTOVER).

**Update cycle**: cycle-contract.json is append-only after publish. If pipeline ids change after Step 6 (e.g. on a re-plan), produce `cycle-contract.v2.json` in the same cycle dir; never edit the v1 file in place.

### Step 5: Create Overnight Spec Files

**After PM TRIAGE completes and before pipeline creation, create spec files for each pipeline.**

**Autonomous mode** (`spec_mode == "autonomous"`):
For each pipeline that will be created (from triage report's `pipeline_order`):

1. Copy the template from `~/.claude/templates/overnight-spec.md` to `docs/dev/overnight/<session_id>/spec-pipeline-<index>.md`
2. Replace `<issue_description>` with the pipeline's `description` from triage
3. Replace `<pipeline_index>` with the pipeline index
4. Replace `<session_id>` with the session ID
5. Replace `<ISO-8601>` with current timestamp
6. Store spec paths in the pipeline definitions: `pipeline.spec_path = "docs/dev/overnight/<session_id>/spec-pipeline-<index>.md"`

**User-spec mode** (`spec_mode == "user-provided"`):
1. The user's spec file at `user_spec_path` is the primary spec
2. For additional issues discovered beyond the user's spec, create new spec files from the template as in autonomous mode
3. For the pipeline matching the user's spec issue, set `pipeline.spec_path = user_spec_path`

**If Section 1 (Before) can be populated from specialist observations**:
Read specialist reports. For each pipeline, if a specialist provided screenshots or detailed observation notes about the current state, prepopulate Section 1 in the spec with that information.

### Step 6: Create Parallel Pipelines from PM Triage

**Read PM triage report**: `docs/dev/overnight/<session_id>/triage-report-cycle<N>.json`

**If triage report exists and is valid** (primary path):

**NOTE**: The PM triage report has already filtered out subjective improvements via the Improvement Quality Filter (PM triage Step 4). Only findings with objective justification (code errors, specification violations, regressions, data loss risks, measurable performance degradation) remain in the `issues` array. Rejected subjective suggestions are logged in the `rejected_improvements` array for audit purposes. The orchestrator trusts PM's filtering -- do NOT second-guess or re-add filtered items.

1. Use `pipeline_order` from triage report as the authoritative ordering
2. For each issue in `pipeline_order`:
   - If `pipeline_recommendation` is `"fix"`: create a pipeline
   - If `pipeline_recommendation` is `"skip"` or `"defer"`: add to skipped list with reason
3. Filter out any issue already in `addressed_issues` from state file
4. Filter out any issue that has failed 3 times (check `failed_attempts`)

**If triage report is missing or invalid** (fallback to legacy behavior):

Read JSON reports from `docs/dev/overnight/<session_id>/` for ONLY the specialists that
were RELEVANT (launched) this cycle. Determine the launched set from the
`specialists_assessed` map recorded in Step 3 — include a report path for each entry
whose value starts with `"RELEVANT"`, and skip (do NOT attempt to read) any entry whose
value starts with `"SKIP"`.

Candidate report paths (include only for RELEVANT specialists):
- `product-owner-report.json` (if `specialists_assessed["product-owner"]` starts with "RELEVANT")
- `architect-report.json` (if `specialists_assessed["architect"]` starts with "RELEVANT")
- `user-report.json` (if `specialists_assessed["user"]` starts with "RELEVANT")
- `ui-specialist-report.json` (if `specialists_assessed["ui-specialist"]` starts with "RELEVANT")

Merge the available reports into a single issue list, deduplicate, filter against addressed_issues and
failed_attempts. Prioritize by severity and impact. Every remaining issue gets a pipeline, ordered by: (1) severity: critical > major > minor > cosmetic, (2) impact scope: issues flagged by more agents rank higher within the same severity.

**Time guard** (severity-aware): If time remaining < 5 minutes, filter issues by severity+effort: (a) Drop cosmetic issues regardless of effort, (b) Drop minor issues with medium/large effort, (c) Keep major issues with small effort only, (d) Keep critical issues with small effort only. This ensures remaining time is spent on the highest-severity fixable issues.

**Create pipeline definitions** -- one per PM-recommended `fix` issue, with zero-indexed suffix. Run:

```bash
python3 ~/.claude/scripts/build-pipelines-from-triage.py <triage-report> <addressed-issues> <timestamp> <session_id> | tee docs/dev/overnight/<session_id>/pipelines.json
```

The script consumes the PM triage schema (`issues[]` keyed by `triage_index` + `pipeline_order[]` + `pipeline_recommendation` + `failed_attempts`). It iterates `pipeline_order`, keeps only `pipeline_recommendation == "fix"`, drops issues whose `<location>|<description>` key appears in addressed-issues, drops issues whose `failed_attempts[triage_index] >= 3`, and emits one pipeline object per remaining issue with: `index, triage_index, description, location, severity, category, agents_flagged, phase=pending, iteration=0, status=active, timestamp_suffix=<ts>-<index>, tier, pm_recommended=true, spec_path=docs/dev/overnight/<session_id>/spec-pipeline-<index>.md`.

**Announce pipeline creation**:
```
PM Triage: {mode} mode ({mode_reason})
Created {N} pipelines ({tier1_count} Tier 1, {tier2_count} Tier 2, {tier3_count} Tier 3):
  Pipeline 0 [T{tier}]: {description} ({severity}, {location})
  Pipeline 1 [T{tier}]: {description} ({severity}, {location})
  ...
Proceeding to parallel BA phase.
```

### Step 7: Convert Focus to QA Verification Criteria

**If the state file has a non-empty `focus` string, convert it into quantitative QA verification criteria before proceeding.**

The focus string is a qualitative directive from the user (e.g., "high quality output"). QA needs quantitative, measurable criteria to verify against. The orchestrator performs this conversion.

**Process**:
1. Read the `focus` field from the state file
2. If empty or null, skip this step (no focus criteria to convert)
3. Convert the qualitative focus into a `focus_verification_criteria` array of measurable criterion objects
4. Store the array in memory for use in Step 15 (QA prompt)

**Conversion example** (illustrative only — derive criteria from the focus and project context, not from this template):

| Focus string | QA verification criteria |
|---|---|
| `<qualitative focus>` | `[{"criterion":"<measurable threshold #1 with number>","required_evidence_level":"rendered_cached"}, {"criterion":"<fresh extraction assertion>","required_evidence_level":"extraction_verified"}]` |

**Rules**:
- Each criterion must be measurable (includes a number, threshold, or binary check)
- Each criterion must be verifiable by QA (observable in browser, API response, or file output)
- Each criterion must declare `required_evidence_level` as one of `rendered_cached`, `fresh_scan_triggered`, `fresh_scan_completed`, or `extraction_verified`
- Rendered/cached evidence must not satisfy criteria that require `extraction_verified`
- Aim for 3-5 criteria per focus string
- When in doubt, err on the side of stricter criteria

The `focus_verification_criteria` array will be passed to each QA subagent in Step 15.

### Step 8: Run All BA Subagents (Parallel)

**Launch BA subagents in batches of 1-3 per response, sequential between batches** (per pacing rule). For N pipelines, dispatch ceil(N/3) batches; wait for each batch to complete before launching the next. Each pipeline gets its own BA Agent call with unique file naming.

**ENFORCEMENT: One pipeline per subagent. Each BA Agent call receives exactly ONE pipeline's issue description and location. Do NOT combine multiple pipelines into a single BA prompt. The same rule applies to Dev (Step 12) and QA (Step 15) subagents.**

```
Launch N Agent tool calls simultaneously (one per pipeline):

For each pipeline[i] in current_issues:

Agent(subagent_type: "ba")
  description: "BA analysis for pipeline {i}: {pipeline.description}"
  prompt: "
    FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID/ba.json to register with the enforcement system. Do this BEFORE any other tool call.
    CHECKPOINT MARKING: see agents/ba.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

    You are the BA subagent. Follow .claude/agents/ba.md instructions precisely.

    User requirement document: <PROJECT_ROOT>/docs/dev/user-requirement-<DEV_SESSION_ID>.md
    (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

    Requirement: '{pipeline.description}'
    Clarification round: 3
    Previous answers: null
    Codebase hints: {pipeline.location}
    Timestamp: {pipeline.timestamp_suffix}
    Project root: <worktree_path from state file if set, otherwise project root>

    Overnight spec file: {pipeline.spec_path}
    View file: {view_paths[this-agent] or null — sibling views/<agent>.md if present}

    prior_attempt_signals:
      retry_phrase: <matched retry phrase or null, from triage/iteration prompt>
      recent_commits: [<hash> <subject>, ...]  # git log results for related keywords
      existing_specs: [docs/dev/ticket-<ts>.md, ...] (legacy: docs/dev/ba-spec-<ts>.md)  # earlier iteration specs matching this issue
      prior_qa_failures: [docs/dev/qa-report-<ts>.md, ...]  # prior failed QA reports on this issue

    This is a self-discovered issue from overnight exploration.
    No clarification is needed -- proceed directly to analysis.
    All file operations and git analysis must use paths inside the project root above.

    **FIRST**: Read the project's CLAUDE.md (if present at the project root or worktree root) -- it is the authority for the role table (CTA hex, neutral hex, etc.), naming conventions, and project-specific rules. Without this read, downstream Dev/QA cannot enforce role-token equality. If the file is absent, log "no project CLAUDE.md" and continue.
    **THEN**: Read the overnight spec file.
    **THEN**: perform full analysis:
    1. Parse and decompose requirement
    2. Perform git root cause analysis (if applicable)
    3. Identify affected files
    4. Generate MoSCoW requirements and BDD acceptance criteria
    5. Write ticket-{pipeline.timestamp_suffix}.md (legacy filename: ba-spec-{pipeline.timestamp_suffix}.md) to docs/dev/ (inside project root)
    6. Write context-{pipeline.timestamp_suffix}.json to docs/dev/ (inside project root)
    7. Update the overnight spec: write Section 5 (User's Acceptance Criterion) and Section 1 (Before) if empty

    Return JSON with status, file paths, and summary.
  "
```

**Wait for ALL N BA subagents to complete** before proceeding.

**NOTE**: Since this is autonomous mode, there is NO BA clarification loop. If any BA returns `needs_clarification`, treat it as `ready` and use best-effort output with explicit assumptions. Do NOT ask the user.

**Fallback**: If the Agent tool cannot handle N simultaneous calls, batch them in groups of 4 and wait for each batch to complete before starting the next.

### Step 9: Validate All BA Outputs

**For each pipeline[i]**, check BA deliverables exist and are well-formed:

Read BA output files:
- `docs/dev/ticket-{pipeline.timestamp_suffix}.md` - Markdown specification (legacy: `docs/dev/ba-spec-{pipeline.timestamp_suffix}.md`)
- `docs/dev/context-{pipeline.timestamp_suffix}.json` - JSON context for dev subagent

**Sanity checks per pipeline**:
- [ ] Both files exist
- [ ] Markdown spec has required sections (Goal, Requirements, Acceptance Criteria)
- [ ] JSON context has required fields (requirement, root_cause_analysis, development_approach)
- [ ] Success criteria are measurable
- [ ] Affected files identified

**If validation fails for pipeline[i]**:
- Re-invoke only the failed BA with specific feedback about what's missing
- Maximum 2 re-invocations per pipeline
- If still failing after retries: mark pipeline status as `"skipped"` with reason `"BA validation failed"`

**If all pipelines are skipped**: Skip to Step 19 (log results).

### Step 10: QA Validates BA Conclusions (All Pipelines, Parallel)

**Purpose**: Verify BA's analysis quality BEFORE Dev starts implementation. Catches unproven claims, scope mismatches, and missing investigation evidence early -- saving a wasted Dev+QA cycle. In overnight mode, this runs for ALL pipelines that passed Step 9 validation, with one QA subagent per pipeline launched in parallel.

**Filter**: Only launch BA-validation QA for pipelines with `phase == "ba_complete"` and `status == "active"`.

**Launch QA-validates-BA subagents in batches of 1-3 per response, sequential between batches** (per pacing rule):

```
For each active pipeline[i]:

# Write qa_mode sentinel immediately before each QA dispatch (preserve existing fields)
bash ~/.claude/scripts/write-qa-mode.sh --session-id "$DEV_SESSION_ID" --mode ba_validation \
  || { echo 'ERROR: Failed to set qa_mode=ba_validation in qa.json — aborting' >&2; exit 1; }

Agent(subagent_type: "qa")
  description: "Validate BA analysis quality for pipeline {i} (not code)"
  prompt: "
    FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID/qa.json to register with the enforcement system. Do this BEFORE any other tool call.
    CHECKPOINT MARKING: see agents/qa.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

    You are the QA subagent in BA-VALIDATION MODE. This is NOT code verification.
    You are verifying the QUALITY OF BA's ANALYSIS, not any implementation.

    DO NOT: build, deploy, open browser, run Playwright, or test code.
    DO: read BA's deliverables and challenge every claim.

    User requirement document: <PROJECT_ROOT>/docs/dev/user-requirement-<DEV_SESSION_ID>.md
    (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

    BA spec file: docs/dev/ticket-{pipeline.timestamp_suffix}.md (legacy: docs/dev/ba-spec-{pipeline.timestamp_suffix}.md)
    Context JSON: docs/dev/context-{pipeline.timestamp_suffix}.json
    Overnight spec file: {pipeline.spec_path}
    View file: {view_paths[this-agent] or null — sibling views/<agent>.md if present}
    Project root: <worktree_path from state file if set, otherwise project root>

    Verify these 4 dimensions:

    1. EVIDENCE QUALITY: For every factual claim BA makes (root cause, affected files,
       component identification), is there evidence? 'BA says so' is not evidence.
       Look for: git blame output, file path verification, code grep results,
       import chain tracing. Flag claims stated as fact without investigation proof.

    2. SCOPE ALIGNMENT: Compare BA's bug title and acceptance criteria against
       the original requirement (and spec Section 5 if available). Did BA narrow,
       rename, or redefine the bug? Is anything from the original requirement
       missing from BA's analysis?

    3. INVESTIGATION COMPLETENESS: If the requirement says 'audit X', 'investigate Y',
       or 'trace Z' -- did BA actually do it, or did BA skip the investigation and
       jump to a conclusion? Check for investigation deliverables the requirement
       explicitly asked for.

    4. AFFECTED-FILE ACCURACY: Are the files BA identified actually the right files?
       Quick-verify: do the file paths exist? Do they contain the code BA claims?
       Does the import chain support BA's component identification?

    Return JSON:
    {
      'verdict': 'pass' or 'fail',
      'objections': [
        {
          'dimension': 'evidence_quality|scope_alignment|investigation_completeness|affected_file_accuracy',
          'claim': 'what BA claimed',
          'problem': 'what is wrong with the claim',
          'required_evidence': 'what BA must provide to satisfy this objection'
        }
      ],
      'summary': 'one-line overall assessment'
    }

    Write report to: docs/dev/ba-qa-report-{pipeline.timestamp_suffix}.json
  "
```

**Wait for ALL BA-validation QA subagents to complete** before proceeding.

**Process QA results per pipeline**:

```
For each pipeline[i]:
  Read docs/dev/ba-qa-report-{pipeline.timestamp_suffix}.json

  IF verdict == "pass":
    -> BA conclusions validated for pipeline {i}. Pipeline proceeds to Step 12.

  ELIF verdict == "fail":
    -> Proceed to Step 11 for BA-QA iteration.
```

### Step 11: BA-QA Iteration Loop (if QA rejects BA)

**Iteration guard**: Maximum 3 BA-QA iterations per pipeline to prevent infinite loops

**Current BA-QA iteration**: Track internally per pipeline (starts at 1)

**If BA-QA iteration > 3**:
```
BA-QA validation: 3 iterations exhausted for pipeline <pipeline_id>. Proceeding with best-effort BA output.

Unresolved objections:
{summary of remaining QA objections}

Appending unresolved objections to context JSON under `ba_qa_unresolved_objections`.
Proceeding to Step 12 with documented assumptions.
```

**If BA-QA iteration <= 3**:

**Announce**: `BA-QA iteration <N>/3 for pipeline <pipeline_id>: QA found <count> objections in BA analysis. Re-invoking BA to address objections.`

**Re-invoke BA with QA's objections**:

```
Use Agent tool with:
- subagent_type: "ba"
- description: "Re-investigate: address QA objections on analysis quality"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID/ba.json to register with the enforcement system. Do this BEFORE any other tool call.
  CHECKPOINT MARKING: see agents/ba.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the BA subagent. Follow .claude/agents/ba.md instructions precisely.

  User requirement document: <PROJECT_ROOT>/docs/dev/user-requirement-<DEV_SESSION_ID>.md
  (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

  Your previous analysis was REJECTED by QA. Address each objection below
  with concrete evidence. Do not argue -- investigate and provide proof.

  Original requirement: '<requirement>'
  Previous BA spec: docs/dev/ticket-{pipeline.timestamp_suffix}.md (legacy: docs/dev/ba-spec-{pipeline.timestamp_suffix}.md)
  Previous context: docs/dev/context-{pipeline.timestamp_suffix}.json
  Spec file: {pipeline.spec_path}

  QA objections:
  <JSON array of objections from ba-qa-report>

  For each objection:
  - Perform the investigation QA requested
  - Provide the specific evidence QA asked for
  - If your original claim was wrong, CORRECT it
  - If your original claim was right, PROVE it with evidence

  Update ba-spec and context JSON with corrected/proven analysis.
  Return JSON with status and updated file paths.
  "
```

**After BA re-delivers**: Return to Step 9 (validate BA output), then Step 10 (QA re-validates).

**Rule**: Every BA invocation MUST be followed by QA validation. No exceptions.

**Note**: Each pipeline iterates independently. Pipeline A being in BA-QA iteration 2 does not affect Pipeline B.

**Iteration tracking**: Update TodoWrite with BA-QA iteration number per pipeline.

### Step 12: Run All Dev Subagents (Parallel)

**Filter**: Only launch Dev for pipelines with `phase == "ba_complete"` and `status == "active"`.

**Launch Dev subagents in batches of 1-3, sequential between batches** (per pacing rule):

```
For each active pipeline[i]:

Agent(subagent_type: "dev")
  description: "Dev implementation for pipeline {i}: {pipeline.description}"
  prompt: "
    FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID/dev.json to register with the enforcement system. Do this BEFORE any other tool call.
    CHECKPOINT MARKING: see agents/dev.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

    You are the dev subagent. Follow agents/dev.md instructions precisely.

    User requirement document: <PROJECT_ROOT>/docs/dev/user-requirement-<DEV_SESSION_ID>.md
    (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

    Context file: docs/dev/context-{pipeline.timestamp_suffix}.json
    BA spec file: docs/dev/ticket-{pipeline.timestamp_suffix}.md (legacy: docs/dev/ba-spec-{pipeline.timestamp_suffix}.md)
    Overnight spec file: {pipeline.spec_path}
    View file: {view_paths[this-agent] or null — sibling views/<agent>.md if present}
    Write your implementation report to: docs/dev/dev-report-{pipeline.timestamp_suffix}.json
    Project root: <worktree_path from state file if set, otherwise project root>

    Read the overnight spec file FIRST for cross-cycle context.
    After implementation, update the spec: Section 2 (What Was Attempted) and Section 3 (What Was Changed).

    IMPORTANT: All file reads, writes, and git operations must use absolute paths
    inside the project root above. Do not modify files in the main project directory.
  "
```

**Wait for ALL Dev subagents to complete** before proceeding.

**Fallback**: If the Agent tool cannot handle N simultaneous calls, batch them in groups of 4.

### Step 13: Validate All Dev Implementations

**For each active pipeline[i]**, validate dev output:

Read dev report: `docs/dev/dev-report-{pipeline.timestamp_suffix}.json`

**Sanity checks per pipeline**:
- [ ] Status is "completed" (not "blocked")
- [ ] All tasks documented
- [ ] Scripts created have usage examples
- [ ] Git rationale references root cause
- [ ] Files exist that were reported as created/modified

**If dev blocked for pipeline[i]**:
- Read blocking issues from report
- Resolve blockers (e.g., missing information, technical constraints)
- Refine context JSON with additional information
- Re-invoke only that pipeline's dev subagent (maximum 3 attempts)
- If still blocked: mark pipeline status as `"skipped"` with reason `"Dev blocked"`

### Step 14: Prepare QA Environment (Docker Rebuild + Verification Plan)

**This step bridges Dev and QA by:**
1. Reading ALL dev reports to understand what changed
2. Rebuilding Docker containers so QA tests the NEW code (autonomous-mode only — see Hard Rule 9)
3. Writing specific verification steps for each QA pipeline

**Without this step, QA tests stale code and produces false passes.**

**This step is performed by the orchestrator directly, NOT by a PM subagent.** The PM subagent only has three modes — `PLAN`, `TRIAGE`, `RETRO` — defined in `agents/pm.md`. There is no fourth PM mode for QA preparation. The orchestrator handles Step 14 inline:

1. **Read dev artifacts**: For each active pipeline, read `docs/dev/dev-report-{pipeline.timestamp_suffix}.json` and the corresponding `ticket-*.md` (or legacy `ba-spec-*.md`).
2. **Rebuild Docker (gated on `spec_mode == "autonomous"` per Hard Rule 9)**:
   - Identify affected services from `docker-compose.yml`. Backend changes require backend service rebuild; frontend changes require frontend service rebuild.
   - Verify build contexts point to the worktree, NOT the main project directory.
   - Run `docker compose build` then `docker compose up -d` for the affected services. Wait for services to be healthy.
   - When `spec_mode == "user-provided"`, skip the rebuild unless the spec's Pipeline Workflow explicitly requires it.
3. **Write QA verification plans**: For EACH pipeline, write concrete QA verification steps:
   - Exact URLs to visit
   - Exact actions (click, type, wait)
   - Exact assertions (text, element, state)
   - For backend pipeline fixes: MUST trigger E2E generation via browser
   - For frontend fixes: MUST do visual/interaction checks

Output: `qa-verification-plans.json` with per-pipeline steps and docker status. The orchestrator writes this file directly (no subagent dispatch).

**If Docker rebuild fails (autonomous mode)**: CYCLE BLOCKER. Debug and retry (max 3 attempts).
Do NOT proceed to QA with stale containers.

### Step 15: Run All QA Subagents (Parallel)

**Filter**: Only launch QA for pipelines with `phase == "dev_complete"` and `status == "active"`.

**Launch QA subagents in batches of 1-3, sequential between batches** (per pacing rule):

```
For each active pipeline[i]:

# Write qa_mode sentinel immediately before each QA dispatch (preserve existing fields)
bash ~/.claude/scripts/write-qa-mode.sh --session-id "$DEV_SESSION_ID" --mode final_verification \
  || { echo 'ERROR: Failed to set qa_mode=final_verification in qa.json — aborting' >&2; exit 1; }

Agent(subagent_type: "qa")
  description: "QA verification for pipeline {i}: {pipeline.description}"
  prompt: "
    FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID/qa.json to register with the enforcement system. Do this BEFORE any other tool call.
    CHECKPOINT MARKING: see agents/qa.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

    You are the QA subagent. Follow agents/qa.md instructions precisely.

    User requirement document: <PROJECT_ROOT>/docs/dev/user-requirement-<DEV_SESSION_ID>.md
    (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

    Context file: docs/dev/context-{pipeline.timestamp_suffix}.json
    Dev report file: docs/dev/dev-report-{pipeline.timestamp_suffix}.json
    BA spec file: docs/dev/ticket-{pipeline.timestamp_suffix}.md (legacy: docs/dev/ba-spec-{pipeline.timestamp_suffix}.md)
    Overnight spec file: {pipeline.spec_path}
    View file: {view_paths[this-agent] or null — sibling views/<agent>.md if present}
    Write your verification report to: docs/dev/qa-report-{pipeline.timestamp_suffix}.json
    Project root: <worktree_path from state file if set, otherwise project root>

    Read the overnight spec file FIRST for cross-cycle context and acceptance criteria.
    After verification, update the spec: Section 4 (Current State) with measured values.
    If verdict is fail, also update Section 6 (Why Not Met) and Section 7 (What Must Be Done).

    IMPORTANT: All file reads and verification must use the project root above.
    Verify that changes were made inside the worktree, not the main project.

    <If focus_verification_criteria array exists from Step 7, include:>
    Focus verification criteria (MANDATORY -- these are hard pass/fail from user's focus directive).
    QA must record `evidence_level` for every result; `rendered_cached` cannot satisfy `required_evidence_level: extraction_verified`:
    <list each criterion from focus_verification_criteria array>
    You MUST verify each criterion above. These are not optional hints. Failures count toward your QA verdict.
  "
```

**Wait for ALL QA subagents to complete** before proceeding.

**Fallback**: If the Agent tool cannot handle N simultaneous calls, batch them in groups of 4.

### Step 16: Process All QA Results

**For each active pipeline[i]**, read QA report and classify:

Read QA report: `docs/dev/qa-report-{pipeline.timestamp_suffix}.json`

**Per-pipeline decision tree**:

```
IF qa.status == "pass":
  → Mark pipeline phase = "done", status = "fixed"

ELIF qa.status == "warning":
  → Autonomous decision: if only minor/cosmetic issues, mark phase = "done", status = "fixed"
  → If major issues: mark phase = "qa_failed" (will enter iteration in Step 17)

ELIF qa.status == "fail":
  → Mark pipeline phase = "qa_failed" (will enter iteration in Step 17)
```

**Tally results**:
```
Pipelines passed: {count} of {total}
Pipelines needing iteration: {count}
Pipelines skipped: {count}
```

**If all pipelines are done (no qa_failed)**: Skip Step 17, proceed to Step 18.

### Step 17: Per-Pipeline Iteration Loops (if QA fails)

**Only runs for pipelines with `phase == "qa_failed"`**. Pipelines that passed QA are already finalized.

#### Layer-escalation gate (mandatory, per-pipeline)

When QA rejects a dev fix within a pipeline, the orchestrator MUST track the
layer used in each attempt for that pipeline. Rules:

1. Attempt 1 may target any layer BA recommends (usually the lowest plausible
   layer).
2. If attempts 1 AND 2 both target the SAME layer (L1 / L2 / L3 / L4 / L5)
   and BOTH fail QA, iteration 3 MUST target a DIFFERENT layer. The
   orchestrator passes `layer_escalation_required: true` to BA for that
   pipeline and the BA MUST produce a new root-cause hypothesis at a
   DIFFERENT layer.
3. The orchestrator MUST record every attempt's layer in the pipeline's
   context JSON under `attempts[i].target_layer`. Before iteration N for
   pipeline P, the orchestrator checks the last N-1 layers on that pipeline;
   if they are all equal and QA has rejected them all, escalation is
   mandatory for the next iteration.
4. BA's Contract D novelty-check MUST include `differs_from_all_prior_layers`
   in addition to `differs_from_all_priors`. A fix that changes L1 wording
   but stays in L1 is NOT novel under this rule.
5. If the same layer is the only one that can plausibly solve the bug on a
   given pipeline (genuine edge case), BA MUST explicitly argue this in
   prose with evidence. In overnight autonomous mode (no user available),
   the orchestrator MUST NOT override the gate -- instead mark the pipeline
   `blocked_same_layer_retry`, skip further iterations, and surface to the
   user on RETRO.

**Why this rule exists**: In a prior incident, a bug cycled through 6
BA→Dev→QA iterations all operating on the same L1 CSS style condition.
The actual fix was L3 (data hydration). This gate forces the orchestrator
to escalate out of local optima, which is especially load-bearing in
overnight mode where many iterations compound silently.

**Per-pipeline iteration guard**: Maximum 5 iterations per pipeline to prevent infinite loops.

**Sort failed pipelines by severity before iterating** (critical first, cosmetic last). Build the iteration plan:

```bash
python3 ~/.claude/scripts/iterate-failed-pipelines.py docs/dev/overnight/<session_id>/pipelines.json 5 > docs/dev/overnight/<session_id>/iteration-plan.json
```

For each entry in `iteration_plan[]`, the orchestrator runs the Dev+QA inner loop. On every iteration, increment `pipeline.iteration` first (so the first refinement after a QA failure runs with `<new-iter> = current_iteration + 1`, starting at 1), then refine the context:

```bash
bash ~/.claude/scripts/refine-context.sh \
  docs/dev/context-<timestamp_suffix>.json \
  docs/dev/qa-report-<timestamp_suffix>.json \
  <new-iter> \
  > docs/dev/context-iter<new-iter>-<timestamp_suffix>.json
```

The merged context records `iteration=<new-iter>` and appends a `previous_attempts[]` entry with `iteration=<new-iter>-1`. Then dispatch:
- `Agent(subagent_type: "dev")` with iteration context. Include in Dev prompt: `Overnight spec file: <pipeline.spec_path>`. Also include: `User requirement document: <resolved $REQUIREMENT_DOC path>`. Dev reads spec first for cross-cycle context, then updates Sections 2 and 3.
- Before dispatching QA, write qa_mode sentinel: `bash ~/.claude/scripts/write-qa-mode.sh --session-id "$DEV_SESSION_ID" --mode final_verification || { echo 'ERROR: Failed to set qa_mode=final_verification — aborting' >&2; exit 1; }`
- `Agent(subagent_type: "qa")` with new dev report. Include in QA prompt: `Overnight spec file: <pipeline.spec_path>`. Also include: `User requirement document: <resolved $REQUIREMENT_DOC path>`. QA reads spec first, then updates Section 4 (and Sections 6-7 if fail).

Loop termination:
- `qa.status == "pass"` OR `(qa.status == "warning" AND minor only)` → set `phase=done`, `status=fixed`, BREAK.
- `iteration >= 5` → set `phase=done`, BREAK; status is set per the "If iteration reaches 5 without passing" block below.

**If iteration reaches 5 without passing**:
```
Quality verification failed after 5 iterations for pipeline {i}: {description}.
Marking as skipped.
```
Mark pipeline: `phase = "done"`, `status = "skipped"`.
Record the failure in the cycle log.

### Step 18: Update Settings.json Permissions (Aggregated)

**CRITICAL**: Aggregate permissions from ALL pipelines before updating.

**Collect and apply permissions from all pipeline QA reports** with two one-line invocations:

```bash
python3 ~/.claude/scripts/aggregate-permissions.py docs/dev/ docs/dev/overnight/<session_id>/pipelines.json > docs/dev/overnight/<session_id>/aggregated-permissions.json
bash ~/.claude/scripts/apply-permissions.sh docs/dev/overnight/<session_id>/aggregated-permissions.json .claude/settings.json
```

The aggregator filters QA reports to those whose `timestamp_suffix` matches a `status: fixed` pipeline, extracts `qa.permissions_verification.validated_permissions[]`, and emits a deduplicated list (by `pattern`). The applier merges each entry into `.permissions.<section>` (allow/ask/deny) atomically, skipping patterns already present.

**Permission update rules**:

1. **Scripts created** -> Add to "allow":
   - `"Bash(scripts/<script-name>.sh:*)"`
   - `"Bash(~/.claude/scripts/<script-name>.sh:*)"`

2. **Python scripts** -> Add to "allow":
   - `"Bash(source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/todo/<script>.py:*)"`

3. **Hooks created** -> Add to "allow":
   - `"Bash(~/.claude/hooks/<hook-name>.sh:*)"`

4. **Commands created** -> Already allowed via "SlashCommand"

**Validation**:
- Check JSON syntax after modification
- Verify no duplicate permissions
- Confirm permissions follow patterns

**Error handling**:
- If settings.json has syntax error -> Log and skip (do not ask user -- autonomous mode)
- If permission already exists -> Skip, don't duplicate

### Step 19: Log All Cycle Results and Check Time

**Aggregate results from ALL pipelines** by tallying fixed vs skipped counts.

**Append to running log** at `docs/dev/overnight-log-<date>.md`:

```markdown
### Cycle <N>: {total_pipelines} pipelines ({fixed_count} fixed, {skipped_count} skipped)

| Pipeline | Issue | Status | Iterations |
|----------|-------|--------|------------|
| 0 | {description} | Fixed | 1 |
| 1 | {description} | Skipped | 5 |
| ... | ... | ... | ... |

**Time**: <timestamp>
```

**TIME CHECK**: invoke `~/.claude/scripts/overnight-status.sh` against the state file; it reports remaining wall-time relative to `end_time` and exits non-zero if the session has expired. If expired, proceed to Step 21 (session ending). Otherwise, mark Step 21 as completed via TodoWrite to trigger the loop reset.

**Per-cycle commit**:

After the time check, land a HEAD commit on the worktree branch covering this cycle's accumulated changes. Call `commit.sh "chore(overnight): end-of-cycle commit for <worktree_branch>"` directly via Bash (single positional arg; `chore` is a valid CC type so M3 lint passes; `(overnight)` scope identifies the automated context). The CAS engine and content-bound ledger still apply. If the invocation exits non-zero (empty ledger for this session, disk content changed, or other CAS refusal), log the failure to the cycle log and continue — per-fix `refs/checkpoints/*` snapshots remain intact and the operator can promote them manually.

If time expired: proceed to Step 20 (PM Retro) then Step 21 for final summary.
If time remains: proceed to Step 20 (PM Retro), then mark Step 21 as completed via TodoWrite. The posttool-overnight-loop.py hook will detect all 21 steps completed, reset todos to pending, and inject continuation instructions.

### Step 20: PM Retrospective

Determine if this is the final cycle:
- If time expired (from Step 19 time check): set `FINAL_CYCLE: true`
- If time remains: set `FINAL_CYCLE: false`

Launch PM in RETRO mode:

```
Use Agent tool with:
- subagent_type: "pm"
- description: "PM retrospective: cycle {N} summary and next-cycle handoff"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID/pm.json to register with the enforcement system. Do this BEFORE any other tool call.
  CHECKPOINT MARKING: see agents/pm.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  PM_MODE: RETRO
  FINAL_CYCLE: <true|false>

  You are the PM subagent in RETRO mode. Follow agents/pm.md Retrospective Protocol.

  User requirement document: <PROJECT_ROOT>/docs/dev/user-requirement-<DEV_SESSION_ID>.md
  (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

  Project path: <worktree_path from state file if set, otherwise project_path>
  Session ID: <session_id>
  Cycle number: <current cycle_count>

  Read your triage report: docs/dev/overnight/<session_id>/triage-report-cycle<N>.json
  Read pipeline results from state file cycle_log (current cycle entries)
  Read QA reports: docs/dev/qa-report-*.json (for this cycle's pipeline timestamp suffixes)
  Read Dev reports: docs/dev/dev-report-*.json (for this cycle's pipeline timestamp suffixes)

  Also read ALL previous retro reports for continuity:
  docs/dev/overnight/<session_id>/retro-report-cycle*.json

  Overnight spec files (one per pipeline -- read ALL, update unresolved ones):
  <For each pipeline in current_issues: {pipeline.spec_path}>

  For each UNRESOLVED pipeline, update its spec:
  - Section 7 (What Must Be Done): Prescriptive next step with exact file, line, action
  - Section 8 (Attention Notes): Issue-specific traps and warnings for next cycle

  <If spec_mode == 'user-provided' AND view_paths['orchestrator'] is non-null, include:>
  Orchestrator view file: <view_paths['orchestrator']>

  Read the orchestrator view FIRST. It contains the project's Role Mandate,
  Pipeline Workflow, Anti-Patterns, and Hard Rules you must enforce as supervisor.
  Use these constraints to shape Section 7 (What Must Be Done) and Section 8
  (Attention Notes) for each unresolved pipeline, and to evaluate whether
  specialist invocations in this cycle complied with the spec.

  <If codex_required == true, include:>
  codex_required: true

  Write retro report to: docs/dev/overnight/<session_id>/retro-report-cycle<N>.json
  "
```

**Wait for PM-Retro to complete.**

**Validate retro report**: Read `retro-report-cycle<N>.json` and verify:
- File exists and is valid JSON
- Has `plan_vs_outcome` array
- Has `unresolved_issues` array
- Has `cycle_stats` object
- If `FINAL_CYCLE: true`: has `final_summary` object

If validation fails, log warning and proceed (retro is informational, not blocking).

**Check qa_rerun_required**: Read the retro report's `qa_rerun_required` field.
- If `qa_rerun_required: true`: For each pipeline to be re-run, write qa_mode sentinel before dispatch: `bash ~/.claude/scripts/write-qa-mode.sh --session-id "$DEV_SESSION_ID" --mode final_verification || { echo 'ERROR: Failed to set qa_mode=final_verification — aborting' >&2; exit 1; }`. Then re-invoke QA for the pipelines listed in `qa_rerun_reasons`. Use the same QA invocation pattern as Step 14-16, but pass additional context: `"This is a PM-requested QA re-run. Reasons: <qa_rerun_reasons>. Focus on the specific concerns raised."` After QA re-run completes, proceed to Step 21 (do NOT re-invoke RETRO — avoid infinite loops).
- If `qa_rerun_required: false` or field absent: proceed normally to Step 21.

---

### Step 21: Generate Summary Report or Loop

**If time remains** (normal loop case):
Simply mark this step as completed via TodoWrite. The PostToolUse:TodoWrite hook (`posttool-overnight-loop.py`) will:
1. Detect all 21 steps are completed
2. Check overnight-state.json for future end_time
3. Reset all todos to pending
4. Print loop continuation instructions
5. You then resume from Step 2 (worktree already exists)

**If time expired** (session ending):
**Read the full state file** to get all cycle data.

**Generate summary report** at `docs/dev/overnight-summary-<date>.md`:

```markdown
# Overnight Development Summary

**Session**: <session_id>
**Start time**: <start_time>
**End time**: <end_time> (planned) / <actual_end> (actual)
**Duration**: <hours>h <minutes>m
**Cycles completed**: <cycle_count>
**Worktree**: <worktree_branch>

## Statistics

| Metric | Count |
|--------|-------|
| Issues found | <issues_found> |
| Issues fixed | <issues_fixed> |
| Issues skipped | <issues_skipped> |
| Fix rate | <percentage>% |

## Cycle Details

### Cycle 1: <issue>
- **Status**: Fixed / Skipped
- **Location**: <file>
- **Changes**: <summary>
- **Iterations**: <N>

## Skipped Issues (need manual attention)

<List of issues that failed 3+ times with error context>

## Files Generated

- Context files: `docs/dev/context-*.json`
- Dev reports: `docs/dev/dev-report-overnight-*.json`
- QA reports: `docs/dev/qa-report-overnight-*.json`
- Running log: `docs/dev/overnight-log-<date>.md`

## Recommendations

<Patterns noticed during exploration that need human decision-making>
```

**CRITICAL: DO NOT auto-merge to $DEFAULT_BRANCH.**

DO NOT squash merge. DO NOT manually copy files. DO NOT create a single commit on $DEFAULT_BRANCH with worktree changes. DO NOT cherry-pick commits. The worktree branch preserves full commit history. A proper `git merge` brings all commits to $DEFAULT_BRANCH with their original authorship and messages intact. Only the USER should trigger the merge, after reviewing the changes.

The overnight session does NOT merge anything. It preserves the worktree for user review.

**State file cleanup**: Automatic, owned by the orchestrator hooks listed under "Integration with Hooks" below. No manual deletion needed.

**Default-branch resolver** (run BEFORE producing the announcement):

Detects the repository's default branch dynamically (`main`, `master`, or any other) by reading `refs/remotes/origin/HEAD`. The announcement below references `$DEFAULT_BRANCH` rather than a hardcoded literal. Same resolver pattern as `/merge`. Per spec-20260424-233926 Section 5.2.1.1, all command-execution paths must derive the default branch dynamically.

```bash
# Detect default branch dynamically (handles main/master/any other)
DEFAULT_BRANCH="$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@')"
if [ -z "$DEFAULT_BRANCH" ]; then
  DEFAULT_BRANCH="$(git remote show origin 2>/dev/null | sed -n 's/.*HEAD branch: //p')"
fi
if [ -z "$DEFAULT_BRANCH" ]; then
  DEFAULT_BRANCH="master"  # final fallback
fi
echo "target=$DEFAULT_BRANCH"
```

**Announce completion**:

```
Overnight development session complete.

Duration: <hours>h <minutes>m
Cycles: <cycle_count>
Fixed: <issues_fixed> | Skipped: <issues_skipped>

Summary: docs/dev/overnight-summary-<date>.md
Log: docs/dev/overnight-log-<date>.md
--- Worktree preserved for review ---
Branch: <worktree_branch>
Path:   <worktree_path>

To review changes:
  git log $DEFAULT_BRANCH..<worktree_branch> --oneline
  git diff $DEFAULT_BRANCH...<worktree_branch>

To merge (when ready):
  /merge <worktree_branch>

Use the audited /merge command as the default and preferred merge path.
Do NOT recommend manual git merge as the primary workflow. The merge command
must run its audit first and stop on blocked files or predicted conflicts.

To ship the worktree end-to-end after overnight completes, see the
"Post-loop manual flow (human-in-the-loop)" subsection below. The user
manually runs three independent commands in this order:
  /commit -m "<summary>"   (optional — only for master-side touch-ups)
  /merge <worktree_branch>
  /push

independent so the user can inspect state between each step.

The time-lock has been released. The session can now end normally.
```

### Post-loop manual flow (human-in-the-loop)

After all overnight cycles complete, the user is expected to review results and run the following three commands MANUALLY, in this order:

1. **`/commit -m "<session summary>"`** (optional)
   - Use this if the user has master-branch touch-ups OUTSIDE the worktree cycles (e.g. README updates, doc fixes)
   - Skip if there's nothing to commit on master beyond what overnight cycles produced
   - The commit message MUST be a real session summary the agent writes (not a placeholder); per redev6 P-MSG, `-m` is REQUIRED in non-bridge modes
   - For `--force` overrides on `/commit` (e.g., spec-only commits without ceremony artifacts), see `commands/commit.md`

2. **`/merge <worktree-branch>`**
   - Merges the overnight worktree branch back into master
   - The blessed-bridge env-var (`CLAUDE_MERGE_COMMAND_ACTIVE=1`) handles privilege-guard authorization
   - If merge conflicts arise, the user resolves manually before continuing

3. **`/push`**
   - Pushes master to origin
   - Requires clean working tree post-merge and commits ahead of upstream
   - The push wrapper writes its own grant manifest; no further user action required


---

## State File Management

The state file is created by `create-overnight-state.sh` during session initialization and is **read-only** for the session thereafter. It serves three purposes:
1. **Configuration**: Provides worktree_path, worktree_branch, view_paths, spec_mode, user_spec_path, end_time
2. **Time-lock**: The Stop hook reads this file to determine if termination is allowed
3. **Continuation**: The UserPromptSubmit hook reads this to inject continuation context

**Do NOT write to the state file**. Use TodoWrite for progress tracking and the cycle log file (`docs/dev/overnight-log-<date>.md`) for cycle results.

**State file location**: `<project_dir>/.claude/overnight-state-<session_id>.json`

**Multi-session support**: Each overnight session uses its own state file keyed by `session_id` (from `$CLAUDE_SESSION_ID` env var or a generated UUID). This allows multiple concurrent overnight sessions on the same project. The Stop hook scans for ALL `overnight-state-*.json` files and blocks termination if ANY has a future end_time.

**Worktree naming**: Each session creates `overnight-<YYYYMMDD>-<session_id_short>` (first 8 chars of session_id) to avoid conflicts between concurrent sessions.

**Schema**:
```json
{
  "session_id": "string (from $CLAUDE_SESSION_ID or UUID)",
  "end_time": "ISO-8601 datetime",
  "start_time": "ISO-8601 datetime",
  "focus": "string (discovery hint from user, or empty)",
  "spec_mode": "autonomous|user-provided",
  "user_spec_path": "string (path to user-provided spec, or null)",
  "cycle_count": 0,
  "issues_found": 0,
  "issues_fixed": 0,
  "issues_skipped": 0,
  "current_phase": "initializing|exploring|pipeline_creation|analyzing|implementing|verifying|iterating|logging|retrospective|completed",
  "current_issues": [
    {
      "index": 0,
      "description": "issue description",
      "location": "file:line",
      "severity": "critical|major|minor|cosmetic",
      "category": "category string",
      "agents_flagged": ["product-owner", "architect"],
      "phase": "pending|ba_complete|dev_complete|qa_failed|done",
      "iteration": 0,
      "status": "active|fixed|skipped",
      "timestamp_suffix": "YYYYMMDD-HHMMSS-0",
      "spec_path": "docs/dev/overnight/<session_id>/spec-pipeline-<index>.md"
    }
  ],
  "failed_attempts": {"issue_desc": 2},
  "addressed_issues": ["issue_desc_1", "issue_desc_2"],
  "cycle_log": [
    {
      "cycle": 1,
      "pipeline_index": 0,
      "issue": "description",
      "location": "file:line",
      "severity": "critical|major|minor|cosmetic",
      "status": "fixed|skipped",
      "iterations": 1,
      "timestamp": "ISO-8601"
    }
  ],
  "consecutive_clean_sweeps": 0,
  "worktree_path": "/path/to/worktree or null",
  "worktree_branch": "overnight-YYYYMMDD-<session_id_short> or null",
  "pm_triage_reports": [],
  "pm_retro_reports": [],
  "unresolved_issues": [
    {
      "description": "issue description",
      "severity": "critical|major|minor|cosmetic",
      "cycles_unresolved": 0,
      "last_attempt_reason": "why it failed or was deferred",
      "recommended_approach": "what to try next"
    }
  ]
}
```

---

## Edge Cases

- **No issues found** — see Step 4 (clean-sweep handling, 2 consecutive sweeps end the session).
- **Unfixable issue (5 failed iterations per pipeline)** — see Step 17 (per-pipeline iteration cap).
- **Very short time remaining (< 5 minutes)** — see Step 6 (severity-aware time guard).
- **State file corruption** — create a fresh state file preserving `end_time`, continue.
- **Worktree creation failure / missing on continuation** — see Step 1 worktree guard (log warning, continue on current branch).

---

## Integration with Hooks

- **prompt-workflow.py** (UserPromptSubmit): Creates overnight-state-<session_id>.json (complete with worktree_path, worktree_branch, view_paths, spec detection) on /dev-overnight detection; injects continuation context with worktree guard
- **posttool-overnight-loop.py** (PostToolUse:TodoWrite): Detects all-completed state, resets todos for new cycle if end_time is future
- **pretool-overnight-hook-guard.py** (PreToolUse): Blocks Write/Edit/Bash targeting .claude/hooks/ during overnight sessions
- **pretool-workflow-gate.py** (PreToolUse): Gates tools until TodoWrite is called
- **posttool-todo-count.py** (PostToolUse:TodoWrite): Enforces step count
- **posttool-todo-sequence.py** (PostToolUse:TodoWrite): Enforces step ordering
- **codex_native_harness.py / stop-overnight-timelock.py** (Stop): Active Stop-chain workflow enforcement; do not cite absent legacy workflow-enforce hooks as active
- **stop-overnight-timelock.py** (Stop): Blocks stop until end_time reached
- **posttool-git-checkpoint.sh** (PostToolUse:Write|Edit): Auto-commits changes

### Loop Mechanism (v3)
- When all 21 todo steps are marked completed via TodoWrite, the posttool-overnight-loop.py hook fires
- It checks overnight-state.json: if end_time is in the future, it resets all todos to pending and injects loop continuation instructions
- The agent then resumes from Step 2 (exploration) since worktree already exists
- This provides natural context boundaries at each cycle without requiring external cron triggers

---

## JSON Storage Policy

All artifact filenames are defined inline in their owning steps (Steps 4-13). Timestamp format: `YYYYMMDD-HHMMSS`. Storage root: `docs/dev/`. Retention/archive rules are owned by `commands/clean.md` — see that file for the active retention policy.

---

## Quality Standards Enforcement

Per-agent responsibilities are owned by `agents/<name>.md` (pm, product-owner, architect, user, ui-specialist, ba, dev, qa) — see those files for current contracts. Orchestrator-only obligations: PM explores via Playwright before writing the test plan; specialist prompts always include the test-plan path; all RELEVANT specialists execute the E2E flow before specialized analysis; ALL issues become parallel pipelines ordered by PM triage; cycle deduplication via `addressed_issues`; multi-session isolation via `session_id`-keyed state files.

---

## Comparison: /dev vs /dev-overnight

| Aspect | /dev | /dev-overnight |
|--------|------|----------------|
| Input | User provides requirement | Agent discovers issues via 4 specialist subagents |
| BA phase | Full BA + clarification loop (max 3 rounds) | BA with clarification skipped (round=3) |
| BA validation | Step 8 | Step 9 |
| Dev validation | Step 12 | Step 13 |
| QA processing | Step 14 decision tree | Step 16 autonomous decision |
| Iteration loop | Step 10 (max 5, asks user after 5) | Step 17 (max 5 per pipeline, auto-skip after 5) |
| Settings update | Step 9 | Step 18 (aggregated from all pipelines) |
| Loop | Single pass | Continuous until end-time |
| Termination | After QA passes | After end-time expires |
| User interaction | Required (clarification, approval) | None (fully autonomous) |
| Scope per cycle | One complete feature/fix | User-pathway-filtered findings (parallel pipelines, gated by PM Step 4 — Tier 1 + multi-agent-consensus in autonomous mode; user-need-relevant in user-provided mode); specialists' free exploration is preserved per Section 5.7 anti-pattern #5 |
| Subagent usage | BA + dev + QA | product-owner + architect + user + ui-specialist + BA + dev + QA |
| Stop hook | Workflow enforcement only | Workflow + time-lock |
| Worktree | Not used | Created on first run, reused across cycles |
| Total steps | 13 | 21 |

---

## UI Development Workflow

**Trigger**: `/dev-overnight --ui-spec <path>` (parsed in the UI Mode Detection subsection above).

When `workflow_type="ui_development"` is set in cycle-contract.json, the cycle skips autonomous discovery and runs a focused UI build pipeline:

1. **ui-specialist DESIGN_MODE**: read the ui-spec markdown, gather design inputs (handoff JSON, screenshots, design system tokens), and emit `design-handoff.json` per `/root/docs/templates/design-handoff.example.json`. Bound by Phase 0 DESIGN_MODE budgets in `agents/ui-specialist.md` (max_pages_visited=3, max_screenshots=10, max_tool_calls=20–30).
2. **BA**: convert `design-handoff.json` into an implementable component spec — `context.json` with concrete `files_to_modify` referencing real component paths, plus role-table-grounded acceptance criteria per CLAUDE.md role tokens.
3. **dev**: implement the component(s) listed in BA's `files_to_modify`. Minimum-Diff Rule applies — no scope expansion beyond what BA's spec authorizes.
4. **qa UI_MODE**: dual-viewport screenshots (desktop 1440x900 + mobile 390x844), Playwright trace, `evidence_map` keyed by AC-NN, and the mandatory `ui_evidence` schema per `agents/qa.md` Section 5c.1. PM-Retro will run `/root/bin/ui-evidence-audit.py` against the qa-report.
5. **PM Retro UI_AUDIT**: false-pass audit — execute `/root/bin/ui-evidence-audit.py` against the qa-report; any FP-1..FP-13 failure or missing required field flags the cycle as a false-pass risk and feeds back into the spec for the next cycle.

In UI Development workflow, autonomous specialist discovery (architect / product-owner / user) is skipped — only `ui-specialist` runs, and only in DESIGN_MODE. The BA→dev→qa pipeline is otherwise unchanged from the standard cycle.

---
