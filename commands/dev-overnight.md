---
description: Autonomous overnight development loop - continuously explores codebase, finds issues, fixes them, and repeats until end-time
disable-model-invocation: true
---

# Dev-Overnight: Autonomous Continuous Development

An unattended loop: explore the codebase, fix each real issue through one-issue subagents, repeat until `end_time`, then summarize. Nobody is asked and nothing waits for the owner, inside the time-lock window or after `end_time`: every decision a pipeline meets is made in the session and recorded (Hard Rule 5). The session commits nothing; the owner lands its work afterwards (Post-loop flow). Session status at zero LLM cost: `bash "<HARNESS_ROOT>/scripts/overnight-status.sh" <STATE_FILE>`.

## Delivery rule

Parallel pipelines inside one cycle stay. Every outcome the user's spec or request asks for is delivered in the same cycle: no sequential phases, no deferred part, no "phase 2", no "MVP first", no work "for a later cycle", and the owner is never asked to open more sessions. A pipeline leaves Step 17 only on a QA pass. No pipeline report, retro report or summary lists a requested outcome as left for a later cycle: `unresolved_issues` and the summary's Recommendations hold only findings the session discovered itself.

## IMPORTANT RULES

1. **Nobody is asked.** `spec_mode == "autonomous"`: decide each question yourself and record it (Hard Rule 5). `spec_mode == "user-provided"`: the spec's user gates (orchestrator view Hard Rule 10) are decision points that nobody answers overnight; decide each as Hard Rule 5 decides a producer question, list it first in the summary's "Decisions made without the owner", and let the pipeline it gates continue with the chosen option. A focus containing `autonomously`, `manual interrupt`, `don't ask` or `no questions` (case-insensitive) makes a user-provided run autonomous in every respect. Asking anything (AskUserQuestion, an options list, an interrogative ending) is a violation. On a deadlock (a hook blocks the very fix needed) decide as Hard Rule 5 and keep the other pipelines running.
2. **Loop until `end_time`.** The todo-completion hook resets the todos after each cycle. When every pipeline is done early the time-lock still holds to `end_time` and the next cycle's PM plans more work. `/stop` is the owner's early exit. A spec-defined user gate never pauses the loop.
3. **Pipelines are user-pathway-filtered and tier-ordered.** PM triage decides what becomes a pipeline (agents/pm.md Step 4): in user-provided mode the findings relevant to the spec's Section 5 user need; in autonomous mode Tier 1 blockers and multi-agent-consensus findings, the rest going to the cycle's `out_of_scope_observations`. Order: Tier 1, 2, 3. The issues the user's spec describes are Tier 1 and always get a pipeline. Specialists explore broadly regardless.
4. **All exploration and fixes go through subagents.** The main context handles TodoWrite and loop control. A file the main context writes itself (Step 5's spec copies, Step 16's completion reports, the pipeline marks of Steps 16-17 in `pipelines.json`, Step 19's cycle log, Step 21's summary) is written by a Bash call with a quoted heredoc (`cat > <path> <<'EOF'` ... `EOF`, or `>>` to append), never with Write or Edit: the orchestrator gate allows one Write and one Edit per turn, and the whole session is one turn.
5. **A producer question is decided without the owner and recorded; nothing waits for the owner and nothing is skipped.** A BA or dev producer that needs a real, specific decision, one the request, the code or a sensible default cannot settle, writes `docs/dev/producer-question-<task_id>-<role>.json` (schema producer-question.v1: `task_id` and `role` exactly as in its obligation, `need`, 2-4 `options` of `{label, description}`, a `default` that is one of the labels, `why`) instead of its report, and ends. That artifact is a subagent's only question path. QA has none: a QA fail or warning is a process step that sends the pipeline back to dev (Step 17). `hooks/pretool-overnight-hook-guard.py` denies AskUserQuestion to every caller in this session until the next human-typed prompt. Decide each question:
   - **by experiment** when one can settle it: re-dispatch the producer that asked with the decision, its options and the experiment to run; it runs the experiment, takes the option its result supports and records the decision, the options, the experiment, its result and the chosen option;
   - **else by the question's `default`**: re-dispatch that producer with the line `Decision without the owner: <need>; options <labels>; the question's default; chosen <default label>`.

   The producer records the decision in its report: BA in its spec and the `assumptions` list it returns, dev in `implementation_notes` of its dev report. Each re-dispatch is fresh and synchronous (same `subagent_type`, `task_id`, pipeline, profile and obligation template, a fresh `dispatched_at`). Copy each decision as recorded into the cycle log (Step 19) and the summary's "Decisions made without the owner" (Step 21): your own from the re-dispatch line, a subagent's from its report when you collect it. The pipeline continues with the chosen option until QA passes.
6. **Track everything with TodoWrite.** The state file `.claude/overnight-state-<session_id>.json` belongs to the hooks: read it, never write it. Cycle results go to the cycle log; artifacts live under `docs/dev/` (retention: `commands/clean.md`).
7. **The Stop gate holds the session open.** `hooks/stop-command-gate.py` (the Stop coordinator's `completion` phase, run by `hooks/stop-launch.py`) is the time-lock: the Stop is refused while the window is open, and after `end_time` until the closeout is on disk (Step 21) and the wake is deleted. Do not try to circumvent it.
8. **Nothing commits per cycle.** `posttool-git-checkpoint.sh` snapshots each Write/Edit to `refs/checkpoints/<worktree_branch>` and never moves a branch HEAD (`docs/reference/checkpoint-mechanism.md`). The session commits, merges and pushes nothing (`/close`, `/commit`, `/merge` and `/push` are human-typed): its work stays in the working tree at `worktree_path` until the owner lands it (Post-loop flow).
9. **Cycle-end deploy is autonomous-mode only.** When `spec_mode == "autonomous"`, every cycle ends with QA rebuilding and redeploying the project's own services (`docker compose build`, then `docker compose up -d`, services identified from `docker-compose.yml`) and verifying the deployment. In user-provided mode the spec decides. Touch no unrelated service or infrastructure.
10. **Deduplicate.** Check the state file's `addressed_issues` and the cycle log before starting a fix; do not re-fix an issue already addressed.
11. **One issue per subagent, no exceptions.** Each BA, dev and QA subagent handles exactly one pipeline; never bundle pipelines into one prompt. N pipelines mean N subagents per stage, dispatched in batches of up to 3 Agent calls per response, each call foreground (`run_in_background: false`), the next batch after the previous one completes; a stage waits for all its subagents.

## Supplementary Rules

- **Rule 3, specialists report symptoms only.** No root cause and no fix suggestions: root cause analysis is BA's job.
- **Rule 7, harness files are project-agnostic.** Files under `<HARNESS_ROOT>/agents/` and `<HARNESS_ROOT>/commands/` apply to every project: no project-specific examples.
- **Rule 8, an autonomy directive in the focus overrides `spec_mode`.** Inside this command nobody is asked anything, whatever `spec_mode` says (Hard Rule 1). `hooks/pretool-overnight-hook-guard.py` denies the AskUserQuestion tool, but no hook reads your text: an options list or an interrogative ending leaves the chat idle awaiting input, and only this rule prevents it.

## Arguments

```
/dev-overnight [end-time] [focus] [--spec path/to/spec.md] [--codex] [--worktree | --no-worktree]
```

Examples: `/dev-overnight 6:00 fix pipeline bugs` (until 6:00, with a focus); `/dev-overnight fix hooks` (default 8h); `/dev-overnight 6:00 --spec docs/my-spec.md`.

**Isolation is the owner's choice.** Without a flag (or with `--no-worktree`) the session runs `in_place` in the checkout it was typed in: nothing is created and `worktree_path` equals the main root. `--worktree` creates an isolated worktree, falling back through repair/prune to a durable fresh clone; if no durable isolation can be produced the launch is refused, never downgraded. Both flags together are refused. The launcher also refuses, writing no state, an in-place launch on a detached HEAD, on `protected_branch`, or on a host where bubblewrap does not run; the remedy (a working branch, bubblewrap, or `--worktree`) is the owner's. Two in-place sessions would collide on one working tree: run at most one per checkout. Never create a worktree yourself and never upgrade an `in_place` session.

**`--codex`**: strip the literal token wherever it appears and set `codex_required = true` (else false). When true, every BA, QA, dev and PM dispatch carries the literal line `codex_required: true`; when false it carries none.

**`--spec`**: user-spec mode. PM (PLAN) reads the spec as supervisor rather than full explorer, the issues the spec describes are Tier 1, every subagent (BA, dev, QA, PM-Retro) receives the spec path and reads it, and PM validates agent output against it in RETRO. Without `--spec` the session is autonomous: PM explores and discovers issues, and after TRIAGE the orchestrator creates a spec file per pipeline from `<HARNESS_ROOT>/templates/overnight-spec.md` (Step 5).

The `UserPromptSubmit` hook decides the spec once and prints `Spec: <path> (explicit)`, `Spec: <path>` (the spec this session last wrote, for example a `/spec` earlier in this session) or `Spec: none`, then hands it to `create-overnight-state.sh`; a `--spec` naming no readable file prints `Spec: <path> (unresolved)` and stops the prompt before anything launches. Nothing else chooses a spec: a spec written in another session reaches `/dev-overnight` only through `--spec`. The state file then holds `user_spec_path`, `spec_mode` and `view_paths` (null means legacy spec-only mode); each subagent gets its own view path beside the monolith spec path.

The `focus` string is stored in the state file and goes to every specialist as a discovery hint; it narrows no exploration. Step 7 turns it into QA pass/fail criteria.

## Implementation

### Step 0: Schedule the Wake

First, before Step 1, schedule the session's wake: one recurring `CronCreate` with exactly this input, the prompt verbatim:

```json
{"cron": "3,13,23,33,43,53 * * * *", "recurring": true, "prompt": "[awesome-claude-harness/overnight-wake-v1] Scheduled wake of this /dev-overnight session: resume what a usage limit cut (commands/restart.md's recovery), then carry on with the checklist step in progress."}
```

Keep the job id its result returns. The wake fires only while the session is idle, as after a usage limit ended the turn; the hooks then hand you `commands/restart.md`'s recovery, which you run with no human, then carry on (a wake that finds nothing cut finalizes with 0 candidates). `pretool-todo-validate.py` completes Step 0 only after this call. On a loop reset (Step 21) and in Continuation Mode the wake scheduled at launch still runs: mark Step 0 completed with no second `CronCreate`. The wake ends with a `CronDelete` of its id, the last step of Step 21's session-ending branch or of `/stop`; the Stop gate refuses the Stop after `end_time` until then.

### Step 1: Read State File and Establish the Working Root

The `UserPromptSubmit` hook has written `.claude/overnight-state-<session_id>.json` (`end_time`, `isolation_kind`, `worktree_path`, `worktree_branch`, `protected_branch`, `actor_git_env`, `view_paths`, `user_spec_path`, `spec_mode`, ...). If none exists, HARD ABORT: fabricate no state; the launcher fails closed, so a missing record means the actor must not run.

Bind and verify in ONE Bash call, before the `cd` below and before any Agent launch, on the first-run path and on the Continuation Mode path (every Bash call is a fresh shell, so a later call expands unbound variables empty):

```bash
STATE_FILE=""; PROJECT_DIR=""
SID="${CLAUDE_CODE_SESSION_ID:-${CLAUDE_SESSION_ID:-}}"
[ -n "$SID" ] || { echo "ERROR: no session id in environment" >&2; exit 1; }
{ read -r STATE_FILE; read -r PROJECT_DIR; } < <(python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/lib/overnight.py" session-root "$SID" "${CLAUDE_PROJECT_DIR:-}" "$PWD")
[ -n "$STATE_FILE" ] && [ -n "$PROJECT_DIR" ] || exit 1
export CLAUDE_PROJECT_DIR="$PROJECT_DIR"
DEV_SESSION_ID="$SID"
REGISTRY_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}/.claude/dev-registry/$DEV_SESSION_ID"
bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/overnight-init.sh" --verify-only --state-file "$STATE_FILE" --project-dir "$PROJECT_DIR"
```

`STATE_FILE` and `PROJECT_DIR` are absolute and canonical (the root the record names, not the directory it sits in), so they stay valid after the `cd`. The locator fails closed, naming both searched starts, when no readable session-matching record is reachable from `CLAUDE_PROJECT_DIR` or `$PWD` (for example an isolated-mode continuation after a launch from a subdirectory): re-issue the block from the main root, never hand-bind a path. `--verify-only` writes nothing: the launcher ran the mutating form before publishing the record. If the last line is not `OVERNIGHT_INIT_OK`, ABORT; do not attempt the initialization by hand (a damaged registry is repaired only by `/stop` plus relaunch). The output keys:

| Output key | Use |
|---|---|
| `SESSION_ID` | `$DEV_SESSION_ID`: reuse across cycles, never invent one |
| `PROJECT_ROOT` | the main root (`<MAIN_ROOT>`) |
| `REGISTRY_DIR` | the dev-registry directory subagents read their sentinel from |
| `CODEX_REQUIRED` | `true` means the `codex_required: true` line (Arguments) |
| `SPEC_MODE`, `USER_SPEC_PATH` | spec announcement and dispatch prompts |
| `SPEC_ID`, `CP_DIR`, `VIEWS_DIR` | cp-state handoff; all empty means legacy monolith mode |
| `REQUIREMENT_DOC` | the source-of-truth path passed to every subagent |

**Substitute literals.** A later Bash call or dispatch that needs `PROJECT_DIR`, `STATE_FILE` or `DEV_SESSION_ID` carries the resolved value, substituted as `{pipeline.index}` is. In this document `<DEV_SESSION_ID>` and `<MAIN_ROOT>` (= `PROJECT_DIR`, where the dev-registry lives) are substitution slots; `<PROJECT_ROOT>` is `worktree_path`, equal to `<MAIN_ROOT>` only in `in_place` mode. Never pass a literal placeholder or `$REQUIREMENT_DOC` unresolved to a subagent. A script that hard-requires an environment variable takes it as a `VAR='<value>' cmd` prefix.

**Working-root guard.** `cd` into `worktree_path` in every mode (the launcher sets it to the main root for `in_place`). If it is missing or invalid, HARD ABORT: create no state, call no EnterWorktree, create no worktree.

| `isolation_kind` | Selected by | Working root | Actor git-env |
|---|---|---|---|
| `in_place` | default, `--no-worktree` | the checkout (`worktree_path` == `main_root`) | marker only, no shim |
| `registered_worktree` | `--worktree` | the created linked worktree | shim + env helper |
| `fresh_clone_checkout` | `--worktree`, no worktree path available | the durable fresh clone | shim + env helper |

`isolation_kind` is the only field you branch on. `protected_branch` is fixed at launch; the keystone and the policy shim read it and refuse ref writes when no live record declares it (remedy: `/stop` and relaunch).

**Actor git-env guard** (after the `cd`, before any git op; defence in depth only, the hook guard derives actor status from the live state, so never strip `CLAUDE_OVERNIGHT_ACTOR`). Wire it at the start of EVERY command that runs git, joined with `&&` and never `;` (a `;` would run git anyway when the helper refuses):

- **`marker_only: true` (in place)**: `source "<env_helper>" --main-root "<main_root>" && git …`, with `env_helper` from `actor_git_env`. It exports `CLAUDE_OVERNIGHT_ACTOR=1` and unsets `CLAUDE_OVERNIGHT_MAIN_ROOT`. Set no `CLAUDE_OVERNIGHT_MAIN_ROOT` and put no shim on `PATH`: the policy shim denies every git op under the main root outside a worktree, which in place is all of them. The marker alone arms the keystone that keeps the protected branch protected.
- **`marker_only: false` (worktree / fresh clone)**: verify once with `source "<env_helper>" --main-root "<main_root>" --worktree "<worktree_path>" && command -v git`; the helper puts the shim dir first on `PATH` and exports `CLAUDE_OVERNIGHT_ACTOR=1`, `CLAUDE_OVERNIGHT_MAIN_ROOT` and `CLAUDE_OVERNIGHT_WORKTREE`, and returns non-zero without changing anything when the wrappers are absent or corrupt. `command -v git` must equal `actor_git_env.shim_git` and `git rev-parse --show-toplevel` must equal `worktree_path`. Compose every later git command the same way (`source … && git …`).

**Claim nothing stronger.** An `in_place` session has no worktree boundary (the keystone on the protected branch and the launcher's refusal to start on it protect); a `registered_worktree` session shares the repository's `.git` common-dir, so an actor that mutates shared git config or hooks can disable the keystone; the bubblewrap read-only bind covers only the guard's Bash branch and protects main working-tree content only when `worktree_path` differs from `main_root`. Never describe an in-place session as isolated or claim protection against shared-`.git` mutation.

**Announce** a user-provided spec (`spec_mode` `user-provided` and `user_spec_path` set) with `Spec mode: user-provided` and `Spec path: <user_spec_path>`, plus `(Spec written earlier in this session. Pass --spec <other-path> to override.)` when the hook's `Spec:` line has no `(explicit)` mark. Then announce initialization:

```
Overnight development session initialized.
Start time: <start_time>
End time: <end_time>
Isolation: <isolation_kind> (in_place = no worktree, working directly in the checkout)
Working root: <worktree_path from state file>
Branch: <worktree_branch from state file>
```

**Every Agent launch** opens with these lines (the templates below show only what is specific to each dispatch):

- `FIRST ACTION: Read <MAIN_ROOT>/.claude/dev-registry/$DEV_SESSION_ID/<agent>.json …` before any other tool call. Without that Read, `pretool-cp-checkin.py` cannot map the subagent to its `agent_type` and `pretool-subagent-code-block.py` falls open for it.
- `CHECKPOINT MARKING: …`, as each template spells it.
- When `SPEC_ID` is non-empty and the agent has a cp-state file under it, this line right after FIRST ACTION (omit it for any other agent):

```text
SECOND ACTION: Read <MAIN_ROOT>/$CP_DIR/cp-state-<agent>.json to load your mandatory checklist before doing substantive work; that read makes the file your slot and writes your agent id into its `agent_id`, the value you pass as `--agent-id` (no shell variable supplies it). Mark each completed checkpoint with python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/spec-check.py" mark --spec-id <SPEC_ID> --agent <agent> --agent-id <agent_id> --cp-id <cp-NN>. Waive only with python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/spec-check.py" waive --spec-id <SPEC_ID> --agent <agent> --agent-id <agent_id> --cp-id <cp-NN> (auto-text records actor + ISO timestamp). You MUST leave zero pending checkpoints before Stop: `subagentstop-cp-enforce.py` blocks your stop while a checkpoint of your own slot is still pending (`CP_ENFORCE_MODE=block`, as settings.json ships it).
```

- The obligation block, instantiated per dispatch and never hand-invented: `<TS>` and `dispatched_at` are the UTC time captured immediately before the Agent call, and each template's `artifacts` are what its hook-checked report must be. The `schema` of a `json` artifact is required and never omitted.
- `User requirement document: $REQUIREMENT_DOC` (resolved): the subagent reads it before interpreting anything else.
- `run_in_background: false` on the call itself.

With a non-empty `SPEC_ID`, before composing any dispatch read the orchestrator view `<MAIN_ROOT>/$VIEWS_DIR/orchestrator.md` (views live under `docs/dev/specs/<artifact_id>/views/`) and the spec's Section 5 from `$REQUIREMENT_DOC` (init already copied it there), and quote the user's Section 5 words verbatim into every dispatch prompt: the user's literal request is the binding contract, never your reformulation.

### Continuation Mode

"OVERNIGHT CONTINUATION" injected by the prompt hook means fresh context. Re-run the Step 1 block as one Bash call (a continuation has no other path to its variables), skip the rest of Step 1 (the working root exists), read the state file and resume by `current_phase`: `initializing` or `exploring` to Step 2; `pipeline_creation` to Step 6; `analyzing` to Step 8; `implementing` to Step 12 (the shared Step 11g precondition enriches before dev, so a resumed session still enriches); `verifying` to Step 14; `iterating` to Step 17; `logging` to Step 19; `retrospective` to Step 20.

A pipeline's stage on resume comes from the artifacts on disk, not from a recorded phase: BA output with a passing BA-QA report and no dev report is ready for Steps 11g and 12; a dev report that passed Step 13 without a QA report is ready for Steps 14 and 15. A pipeline whose recorded state and artifacts disagree is never skipped: resume at the step the artifacts show.

### Pre-BA: surface retry signals

Before each BA dispatch, scan the pipeline's input and the repository for signs of an earlier attempt and pass what you find under `prior_attempt_signals` in the BA prompt (Step 8):

- **Retry phrasing** in the triage entry: "again", "still", "didn't fix", "Nth time", "not fixed".
- **Recent related commits**: `git log --oneline --grep="<keyword>" HEAD~30..HEAD` (this run commits nothing, Hard Rule 8, so its own earlier attempts are the specs and QA reports below).
- **Existing BA specs** from earlier iterations: files matching `docs/dev/ticket-*.md` (or legacy `docs/dev/ba-spec-*.md`) with keywords from the current issue.
- **Prior-cycle QA fail reports** on the same issue: `docs/dev/qa-report-<ts>.json`.

### UI Mode

`/dev-overnight --ui-spec <path>` (a ui-spec markdown with YAML frontmatter `ui_target`, `viewport_targets`, `design_inputs`) runs a UI development cycle, `workflow_type="ui_development"`, named in each dispatch prompt of the cycle. Skip autonomous discovery: PM-Plan calls no architect, product-owner or user; the chain is ui-specialist (DESIGN_MODE, emitting `design-handoff.json`), BA (component spec from it), dev (the components BA lists, minimum diff), QA (UI_MODE: dual-viewport screenshots, trace and the `ui_evidence` fields of agents/qa.md), and a PM Retro UI_AUDIT that runs the ui-evidence audit (resolved from `$UI_EVIDENCE_AUDIT_BIN`) against the QA report; a false-pass finding feeds the next cycle's spec. Otherwise run the autonomous discovery flow (`workflow_type` `ui_audit` or `general`, as PM-Plan decides).

### Exploration (Steps 2 - 5)

Step 2 launches PM to build a test plan with a `recommended_specialists` field; you extract the priority context; Step 3 launches only the specialists the plan recommends, with that context; Step 4 launches PM in TRIAGE mode to classify every finding. Read the state file's `addressed_issues` first.

#### Step 2: Launch PM Subagent

```
Use Agent tool with:
- subagent_type: "pm"
- description: "Build test plan from project docs and session history"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <MAIN_ROOT>/.claude/dev-registry/$DEV_SESSION_ID/pm.json to register with the enforcement system. Do this BEFORE any other tool call.
  CHECKPOINT MARKING: follow your agent file's checkpoint pointer: mark or waive every cp-NN of your own slot; a pending one blocks your stop (subagentstop-cp-enforce.py).

  Obligation block (docs/reference/close-commit-zero-failure-mechanism-20260928.md §1.2): instantiated per dispatch; <TS> is the UTC time captured immediately before this Agent call (YYYYMMDD-HHMMSS) and dispatched_at is the same instant:
  <obligation v="1">
  {
    "task_id": "<TS>",
    "lane": null,
    "lane_set": null,
    "role": "pm",
    "pipeline": "dev-overnight",
    "profile": "overnight",
    "dispatched_at": "<ISO-8601 UTC ending in Z>",
    "artifacts": [
      {"kind": "json", "path": "docs/dev/overnight/<session_id>/test-plan.json", "schema": "test-plan.v1",
       "identity": {"task_id": "<TS>"}}
    ]
  }
  </obligation>

  PM_MODE: PLAN

  You are the PM subagent. Follow agents/pm.md instructions precisely.

  User requirement document: $REQUIREMENT_DOC

  Project path: <validated worktree_path from state file>
  State file path: <path to overnight-state-*.json>
  Session ID: <session_id>
  Output test plan to: docs/dev/overnight/<session_id>/test-plan.json

  <If spec_mode == 'user-provided', include:>
  Overnight spec file: <user_spec_path from state file>
  Spec mode: user-provided
  You are in SUPERVISOR mode. Read the user's spec first. The issues it describes are pre-validated: skip full browser exploration for them and look for ADDITIONAL issues the spec does not cover. Set spec_mode: 'user-provided' and spec_path in your test plan.

  <If spec_mode == 'user-provided' AND view_paths['orchestrator'] is non-null, include:>
  Orchestrator view file: <view_paths['orchestrator']>
  Read the orchestrator view FIRST (Role Mandate, Pipeline Workflow, Anti-Patterns, the Hard Rules you enforce as supervisor) and fold it into your test plan's priority_tiers and recommended_specialists.

  <If codex_required == true, include:>
  codex_required: true
  "
```

**Wait for PM to complete.** The report an obligation declares is checked against its schema when the producer stops (`hooks/subagentstop-artifact-contract-enforce.py` returns a missing or invalid report to its producer before it can end); the plan you read below is one that passed.

#### After PM-Plan Completes: Extract Priority Context

Read `test-plan.json` and build the priority context block that goes into every specialist prompt:

```
Priority context from PM:
- Tier 1 (blockers): [list descriptions from priority_tiers.tier_1_blockers]
- Tier 2 (major): [list descriptions from priority_tiers.tier_2_major]
- Tier 3 (minor): [list descriptions from priority_tiers.tier_3_minor]
Unresolved from previous cycles: [list from unresolved_from_previous with cycle count]

PRIORITY RULE: Investigate Tier 1 issues FIRST. Report ALL issues you find,
but tag each with pm_tier: 1|2|3|new (where "new" = not in PM's list).
```

If the plan has no `priority_tiers` (first cycle, no history), set the priority context to:
`"No priority tiers from PM -- this is the first cycle. Explore freely and report all issues."`

#### Step 3: Launch PM-Recommended Specialist Subagents

Launch only the specialists the plan's `agent_assignments` names (narrowed as the routing below says), ONE AT A TIME: one Agent call per specialist, and wait for each to complete before launching the next. Specialists are expensive consultations, parallel runs corrupt evidence ordering, and unlike BA, dev and QA (isolated through `spec-check.py --instance-id`) they have no instance-isolated state.

### Specialist Calling Rule

Exploration is for discovering unknown issues, so cast a wide net. Route at runtime from the state file:

- **Exploration mode** (no user spec): launch every specialist, or the narrower non-empty `recommended_specialists` subset when the plan has one. Do not "evaluate then call" here: you cannot judge relevance to issues you have not discovered.
- **Supervisor mode** (user-provided spec): the issues are pre-known. Assess every specialist as `RELEVANT — <reason>` or `SKIP — <concrete reason>` (a bare "no specialists needed" is invalid) and launch each RELEVANT one in turn. The orchestrator view manifest's Agent Relevance table is the authoritative routing source: launch the specialists it marks relevant and never default to zero; only a missing or malformed manifest allows zero, and then log that anomaly in the cycle log. PM's `recommended_specialists` is advisory. Record the assessment, one key per specialist:

```json
"specialists_assessed": {
  "<specialist>": "RELEVANT — <reason>" | "SKIP — <concrete reason>"
}
```

**Supervisor-mode prompts** (`spec_mode == "user-provided"` and `view_paths` non-null): read `view_paths["orchestrator"]`, find its `## Pipeline Workflow` section and use its per-specialist templates as that specialist's task description instead of the default exploration prompt, as written. Structure:

```
<FIRST ACTION, CHECKPOINT MARKING and Obligation block lines, as every specialist dispatch below receives them>

You are the <specialist_type> specialist.

View file: <view_paths[specialist_type]>
Read your view file FIRST: it holds your Role Mandate and the content blocks relevant to your role.

<orchestrator-view prompt template for this specialist, if found in Pipeline Workflow section>

Overnight spec file: <user_spec_path>
Project path: <worktree_path>
Test plan: docs/dev/overnight/<session_id>/test-plan.json
Output report to: <report path>
Priority context from PM: <priorities>
```

Without a `## Pipeline Workflow` section or per-specialist templates, and in exploration mode (`spec_mode == "autonomous"` or `view_paths` null), use the default exploration prompt below, which needs no view file or spec file.

```
For each specialist in recommended_specialists (domain-matched only):

Agent(subagent_type: specialist.type)
  run_in_background: false
  Write report to: docs/dev/overnight/<session_id>/<specialist.type>-report.json

The specialists are the agents the test plan's agent_assignments names (schemas/test-plan.v1.json requires each).

Each subagent receives, at the TOP of its prompt before any other content:
- FIRST ACTION line: "Read <MAIN_ROOT>/.claude/dev-registry/$DEV_SESSION_ID/<specialist.type>.json to register with the enforcement system. Do this BEFORE any other tool call."
- CHECKPOINT MARKING line: "follow your agent file's checkpoint pointer: mark or waive every cp-NN of your own slot; a pending one blocks your stop (subagentstop-cp-enforce.py)."
- Obligation block: embed `<obligation v="1">{...}</obligation>` with task_id="<TS>", lane=null, lane_set=null, role="<specialist.type>", pipeline="dev-overnight", profile="overnight", artifacts=[{"kind":"json","path":"docs/dev/overnight/<session_id>/<specialist.type>-report.json","schema":"specialist-report.v1","identity":{"task_id":"<TS>"}}]. <TS> and dispatched_at are captured immediately before this Agent call, as in Step 2
- User requirement document: $REQUIREMENT_DOC
- Project path: <validated worktree_path from state file>
- Already addressed: <addressed_issues array from state file>
- Focus: <focus string from state file, or "none">
- Test plan: docs/dev/overnight/<session_id>/test-plan.json
- View file: {view_paths[specialist_type] or null}
- Overnight spec file: {user_spec_path or null}
- Priority context: <the priority context block built in the step above>
- Output report to: <path above>
```

Every specialist prompt carries the test plan path (specialists begin with a mandatory Step 0, reading the plan, where PM's `pm_experience` is ground truth, and Step 1, the core E2E flow via Playwright, before specialized analysis) and the priority block. The project path is always `worktree_path`: an isolated tree under `--worktree`, the main checkout itself in place. Inline no application context, credentials, flow steps or sample data: they live in the test plan.

**Announce specialist selection**:

```
PM recommended {N} specialists for this cycle: {list of specialist types}
{If fallback: "No recommended_specialists in test plan -- selected {list} via domain trigger rules."}
Launching specialist subagents...
```

**Wait for all launched specialists to complete.** Each report is checked against `schemas/specialist-report.v1.json` when its specialist stops, as PM's plan is; its full shape is the one its agent file declares (Output Format). If every launched specialist's report holds zero issues (skipped specialists do not count as clean), log a clean sweep: the session does not end (Hard Rule 2).

**Core flow gate.** Look up `user` in `specialists_assessed`. `SKIP`: the gate does not apply; record `core_flow_gate: "skipped — user specialist not launched"` in the cycle log and go to Step 4. `RELEVANT`: read the user report's `core_flow_completed`; `false` (or missing) fails the gate, which is logged as a cycle-level failure and makes the user agent's core flow issues Step 4's top priority; `true` passes it. When it applies, the gate is absolute: if the user cannot complete the core business flow, the cycle counts as failed whatever the other agents found.

**Route map.** If the user report names a `route_map_file`, read it and pass its path to dev (which pages its changes might touch), QA (verify no listed page breaks) and, in the next cycle only, PM PLAN (skip browser discovery).

#### Step 4: Launch PM-Triage Subagent

After the specialists complete, launch PM in TRIAGE mode. Build the prompt from the `specialists_assessed` map of Step 3: list a report path only for a specialist whose value starts with `"RELEVANT"`; list each `"SKIP"` specialist with its reason so PM does not read a file that does not exist. `<N>` is the cycle number: the `Cycle:` line of `bash "<HARNESS_ROOT>/scripts/overnight-status.sh" <STATE_FILE>` (a cycle ends with its PM retrospective, Step 20; the state file holds no cycle count).

```
Use Agent tool with:
- subagent_type: "pm"
- description: "PM triage: classify and prioritize all specialist findings"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <MAIN_ROOT>/.claude/dev-registry/$DEV_SESSION_ID/pm.json to register with the enforcement system. Do this BEFORE any other tool call.
  CHECKPOINT MARKING: follow your agent file's checkpoint pointer: mark or waive every cp-NN of your own slot; a pending one blocks your stop (subagentstop-cp-enforce.py).

  Obligation block: embed `<obligation v="1">{...}</obligation>` here with task_id="<TS>", lane=null, lane_set=null, role="pm", pipeline="dev-overnight", profile="overnight", artifacts=[{"kind":"json","path":"docs/dev/overnight/<session_id>/triage-report-cycle<N>.json","schema":"triage-report.v1","identity":{"task_id":"<TS>"}}]. <TS> and dispatched_at are captured immediately before this Agent call, as in Step 2

  PM_MODE: TRIAGE

  You are the PM subagent in TRIAGE mode. Follow agents/pm.md Triage Protocol.

  User requirement document: $REQUIREMENT_DOC

  Project path: <validated worktree_path from state file>
  Session ID: <session_id>
  Cycle number: <N>

  You receive reports ONLY from specialists that were RELEVANT and launched this cycle. Skipped specialists are listed below with their reason: do not read report files for them, those files do not exist.

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
  Read the orchestrator view FIRST (Role Mandate, Pipeline Workflow, Anti-Patterns, the Hard Rules you enforce as supervisor) and apply it to your tier assignments, pipeline_order and recommended_specialists.

  <If codex_required == true, include:>
  codex_required: true

  Write triage report to: docs/dev/overnight/<session_id>/triage-report-cycle<N>.json
  "
```

**Wait for PM-Triage to complete**; its report is checked at PM's stop as the plan is. **Check `pipeline_blocked`** in the triage report: if `true`, log `block_reasons` to the cycle log, skip Steps 6-19 and go straight to Step 20 (PM Retrospective) with the block as context, then loop to Step 2 for the next cycle; if `false` or absent, go on to Step 6.

### Cycle Contract

The cycle contract is a hook's output; you never write, copy, link or edit it. When the PM TRIAGE dispatch returns, `hooks/posttool-subagent-track.py` writes `docs/dev/overnight/<session_id>/cycle-<N>/cycle-contract.json` under the working root, rendered from the canonical todo (`scripts/todo/dev-overnight.py`) and this cycle's triage report: one `required_calls` entry `{step, role, mode, pipeline_id}` per dispatch of Steps 8, 10, 11g, 12 and 15 for each pipeline the triage creates (counted by `scripts/build-pipelines-from-triage.py`, Step 6's builder), and one for Step 20. An entry names no artifact path and no schema: each dispatch's own obligation declares its artifacts, and `hooks/posttool-overnight-file-check.py` checks them against it when the dispatch returns. `hooks/pretool-subagent-enforce.py` checks every dispatch against the step in progress: Steps 2-4 are allowed in every cycle, later steps by the contract's entries; it refuses a role or mode the step in progress does not allow.

### Step 5: Create Overnight Spec Files

After PM TRIAGE and before pipeline creation, create a spec file per pipeline.

**Autonomous mode** (`spec_mode == "autonomous"`): for each pipeline from the triage report's `pipeline_order`:

1. Copy the template from `<HARNESS_ROOT>/templates/overnight-spec.md` to `docs/dev/overnight/<session_id>/spec-pipeline-<index>.md`.
2. Replace `<issue_description>` with the pipeline's `description` from triage, `<pipeline_index>` with its index, `<session_id>` with the session id and `<ISO-8601>` with the current timestamp.
3. Replace Section 5's `_Not yet populated._` with the pipeline's `description` from triage, verbatim.
4. If a specialist gave screenshots or detailed observations of the current state, prepopulate Section 1 (Before) of the copy with them.
5. Store `pipeline.spec_path = "docs/dev/overnight/<session_id>/spec-pipeline-<index>.md"` in the pipeline definition.

Write every copy in ONE Bash call, one quoted heredoc per copy (`cat > docs/dev/overnight/<session_id>/spec-pipeline-<index>.md <<'SPEC'`, the copy's text, `SPEC`; Hard Rule 4): one call keeps Steps 4-8 inside the orchestrator gate's five consecutive Bash calls before the first BA dispatch.

**User-spec mode** (`spec_mode == "user-provided"`): the user's spec at `user_spec_path` is the primary spec and `pipeline.spec_path = user_spec_path` for the pipeline matching its issue; additional issues discovered beyond it get template copies as above.

**One writer per spec.** A pipeline spec is written by its template copy alone; the user's spec only by `<HARNESS_ROOT>/scripts/spec-write.py` (`/spec`, `/spec-update`, `/commit` Step 8). No dispatch below writes either: BA's, dev's, QA's and PM-Retro's section text stays in their own reports (BA's context, `dev.tasks_completed`, `qa.spec_section_updates`, the retro report), which the next round and the spec's continuation read.

### Step 6: Create Parallel Pipelines from PM Triage

Read `docs/dev/overnight/<session_id>/triage-report-cycle<N>.json`. PM already filtered out subjective suggestions (rejected ones sit in `rejected_improvements`): trust it, and never second-guess or re-add them.

1. Take `pipeline_order` as the authoritative order.
2. For each issue, `pipeline_recommendation` `"fix"` creates a pipeline. `"skip"` and `"defer"` apply only to findings PM discovered on its own that nobody requested; they are never used for an outcome the user's spec or request asks for. Such an issue gets no pipeline and goes to the cycle's triage-deferred list with PM's reason: a planning decision before any pipeline starts, not a pipeline exit, counted and reported apart from the pipelines.
3. Drop any issue already in `addressed_issues`.

**Time guard** (severity-aware): with less than 5 minutes remaining, drop cosmetic findings regardless of effort and minor findings of medium or large effort, and keep major and critical findings of small effort only. The guard applies to findings the session discovered itself; an outcome the user's spec or request asks for is never dropped.

Create the pipeline definitions, one per `fix` issue, zero-indexed:

```bash
python3 "<HARNESS_ROOT>/scripts/build-pipelines-from-triage.py" <triage-report> <addressed-issues> <timestamp> <session_id> | tee docs/dev/overnight/<session_id>/pipelines.json
```

The builder keeps only `fix` issues absent from addressed-issues and emits one pipeline per issue: `index`, `triage_index`, `description`, `location`, `severity`, `category`, `agents_flagged`, `phase=pending`, `iteration=0`, `status=active`, `timestamp_suffix=<ts>-<index>`, `tier`, `pm_recommended=true` and `spec_path`.

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

If the state file's `focus` is empty or null, skip this step. Otherwise convert the qualitative focus (for example "high quality output") into a `focus_verification_criteria` array of 3-5 measurable criteria, derived from the focus and the project, held in memory for Step 15. Each criterion is a number, threshold or binary check; is observable by QA in the browser, an API response or a file; and declares `required_evidence_level` as one of `rendered_cached`, `fresh_scan_triggered`, `fresh_scan_completed` or `extraction_verified` (rendered or cached evidence never satisfies `extraction_verified`). When in doubt, be stricter.

### Step 8: Run All BA Subagents (Parallel)

**Graphify pre-BA hydrator** (per pipeline, before its BA dispatch): a direct read-only Bash call, not a subagent, advisory and fail-open (an absent binary or cache exits 0 with `status=unavailable` and BA proceeds unchanged). The pipeline-scoped task id and requirement file (the pipeline's `description`, `location` and `spec_path`) keep concurrent fan-out writes in disjoint `pre_query.json` files. Substitute the resolved session id and index:

```bash
mkdir -p ".claude/dev-registry/<DEV_SESSION_ID>-pipeline-{pipeline.index}/graphify"
printf '%s\n\nLocation: %s\n\nSpec: %s\n' "{pipeline.description}" "{pipeline.location}" "{pipeline.spec_path}" \
  > ".claude/dev-registry/<DEV_SESSION_ID>-pipeline-{pipeline.index}/graphify/requirement.txt"
source "${CLAUDE_HOME:-$HOME/.claude}/venv/bin/activate" && python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/graphify-query.py" \
  --task-id "<DEV_SESSION_ID>-pipeline-{pipeline.index}" \
  --requirement-file ".claude/dev-registry/<DEV_SESSION_ID>-pipeline-{pipeline.index}/graphify/requirement.txt" || true
```

When that pipeline's `pre_query.json` exists with `status=ok` or `status=degraded`, add `Pre-query context file: .claude/dev-registry/<DEV_SESSION_ID>-pipeline-{pipeline.index}/graphify/pre_query.json` to that pipeline's BA prompt only; otherwise omit it. These are sidecar artifacts, not contract-gated.

Each BA Agent call receives exactly ONE pipeline's issue and location; dispatch per Hard Rule 11.

```
For each pipeline[i] in current_issues:

Agent(subagent_type: "ba")
  description: "BA analysis for pipeline {i}: {pipeline.description}"
  run_in_background: false
  prompt: "
    FIRST ACTION: Read <MAIN_ROOT>/.claude/dev-registry/$DEV_SESSION_ID/ba.json to register with the enforcement system. Do this BEFORE any other tool call.
    CHECKPOINT MARKING: follow your agent file's checkpoint pointer: mark or waive every cp-NN of your own slot; a pending one blocks your stop (subagentstop-cp-enforce.py).

    Obligation block (docs/reference/close-commit-zero-failure-mechanism-20260928.md §1.2): instantiated per pipeline from the loop's {pipeline.timestamp_suffix}; dispatched_at is captured immediately before this Agent call:
    <obligation v="1">
    {
      "task_id": "{pipeline.timestamp_suffix}",
      "lane": null,
      "lane_set": null,
      "role": "ba",
      "pipeline": "dev-overnight",
      "profile": "overnight",
      "dispatched_at": "<ISO-8601 UTC ending in Z>",
      "artifacts": [
        {"kind": "json", "path": "docs/dev/context-{pipeline.timestamp_suffix}.json", "schema": "context.v1",
         "identity": {"task_id": "{pipeline.timestamp_suffix}", "request_id": "{pipeline.timestamp_suffix}"}},
        {"kind": "markdown", "path": "docs/dev/ticket-{pipeline.timestamp_suffix}.md", "identity_anchor": "{pipeline.timestamp_suffix}"}
      ]
    }
    </obligation>

    <If codex_required == true, include:>
    codex_required: true

    You are the BA subagent. Follow agents/ba.md instructions precisely.

    User requirement document: $REQUIREMENT_DOC

    Requirement: '{pipeline.description}'
    Clarification round: 0
    Previous answers: null
    Codebase hints: {pipeline.location}
    Timestamp: {pipeline.timestamp_suffix}
    Project root: <validated worktree_path from state file>

    Overnight spec file: {pipeline.spec_path}
    View file: {view_paths[this-agent] or null}

    prior_attempt_signals:
      retry_phrase: <matched retry phrase or null, from triage/iteration prompt>
      recent_commits: [<hash> <subject>, ...]
      existing_specs: [docs/dev/ticket-<ts>.md, ...] (legacy: docs/dev/ba-spec-<ts>.md)
      prior_qa_failures: [docs/dev/qa-report-<ts>.json, ...]

    This is a self-discovered issue from overnight exploration.
    Settle each unclear point from the requirement, the code or a sensible default and record it as an assumption.
    Only for a real, specific decision that none of these settles, write docs/dev/producer-question-{pipeline.timestamp_suffix}-ba.json (agents/ba.md) instead of your report, and end.
    All file operations and git analysis must use paths inside the project root above.
    Write ticket-{pipeline.timestamp_suffix}.md (legacy filename: ba-spec-{pipeline.timestamp_suffix}.md) and context-{pipeline.timestamp_suffix}.json to docs/dev/ (inside the project root).
    Do not write the overnight spec: the requirement and the before-state you establish go in your context.

    Return JSON with status, file paths, and summary.
  "
```

**Wait for ALL N BA subagents to complete.** A BA that wrote `docs/dev/producer-question-{pipeline.timestamp_suffix}-ba.json` instead of its report has its question decided and recorded by Hard Rule 5 and is re-dispatched with the decision; there is no BA clarification loop with the owner.

### Step 9: Validate All BA Outputs

For each pipeline[i], read `docs/dev/ticket-{pipeline.timestamp_suffix}.md` (legacy `docs/dev/ba-spec-{pipeline.timestamp_suffix}.md`) and `docs/dev/context-{pipeline.timestamp_suffix}.json` and check that:

- both files exist; the spec has Goal, Requirements and Acceptance Criteria; the context has `requirement`, `root_cause_analysis` and `development_approach`; the success criteria are measurable; the affected files are identified;
- the BA contracts of agents/ba.md (§Four Contracts) hold: `evidence.measured.value` and `evidence.expected.source` are populated; `scope_expansion.all_occurrences` is non-empty (or explicitly `not_applicable`); `reference_source.tier` is not `tier_3_tainted` when `copy_allowed: true`; and when prior-attempt reconciliation (Contract D) triggered, `prior_attempts.novelty_check.differs_from_all_priors` is true.

On a gap, re-invoke only that pipeline's BA with feedback naming what is missing (a fresh dispatch: same obligation template, fresh `dispatched_at`) and validate again. A BA output that passes is the only way forward: the pipeline is never dropped here, and no stalled iteration excuses dispatching dev on an incomplete spec. When Contract D's novelty check finds no candidate fix that differs from every prior attempt, BA writes a producer question whose options are the candidate layers (default: its recommendation, often a deeper one); decide it by Hard Rule 5 and re-dispatch BA with the chosen layer, never with the same input and no decision and never marking the issue blocked or skipped.

### Step 10: QA Validates BA Conclusions (All Pipelines, Parallel)

Verify BA's analysis quality BEFORE dev starts: unproven claims, scope mismatches and missing investigation evidence caught here save a wasted dev and QA round. Launch one BA-validation QA per active pipeline (`status == "active"`) whose BA output passed Step 9, dispatched per Hard Rule 11:

```
For each active pipeline[i]:

Agent(subagent_type: "qa")
  description: "Validate BA analysis quality for pipeline {i} (not code)"
  run_in_background: false
  prompt: "
    FIRST ACTION: Read <MAIN_ROOT>/.claude/dev-registry/$DEV_SESSION_ID/qa.json to register with the enforcement system. Do this BEFORE any other tool call.
    CHECKPOINT MARKING: follow your agent file's checkpoint pointer: mark or waive every cp-NN of your own slot; a pending one blocks your stop (subagentstop-cp-enforce.py).

    Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="qa", pipeline="dev-overnight", profile="ba_validation", task_id="{pipeline.timestamp_suffix}", artifacts=[{"kind":"json","path":"docs/dev/ba-qa-report-{pipeline.timestamp_suffix}.json","schema":"ba-qa-report.v1","identity":{"task_id":"{pipeline.timestamp_suffix}"}}]. dispatched_at is captured immediately before this Agent call; the schema of a json artifact is required

    <If codex_required == true, include:>
    codex_required: true

    You are the QA subagent in BA-VALIDATION MODE. This is NOT code verification: do not build, deploy, open a browser, run Playwright or test code. Read BA's deliverables and challenge every claim.

    User requirement document: $REQUIREMENT_DOC

    BA spec file: docs/dev/ticket-{pipeline.timestamp_suffix}.md (legacy: docs/dev/ba-spec-{pipeline.timestamp_suffix}.md)
    Context JSON: docs/dev/context-{pipeline.timestamp_suffix}.json
    Overnight spec file: {pipeline.spec_path}
    View file: {view_paths[this-agent] or null}
    Project root: <validated worktree_path from state file>

    Verify these 5 dimensions (agents/qa.md, BA-Validation Mode, defines each):

    1. EVIDENCE QUALITY: every factual claim BA makes (root cause, affected files, component identification) needs evidence; 'BA says so' is not evidence. Look for git blame output, path verification, grep results, import-chain tracing.

    2. SCOPE ALIGNMENT: compare BA's bug title and acceptance criteria with the original requirement (and spec Section 5 if available). Did BA narrow, rename or redefine the bug? Is anything from the requirement missing? Also FAIL a plan that splits a requested outcome into sequential phases or defers any part of it (a 'phase 2', an 'MVP first', work for a later cycle): raise a 'dimension: scope_alignment' objection and give verdict 'fail'.

    3. INVESTIGATION COMPLETENESS: if the requirement says 'audit X', 'investigate Y' or 'trace Z', did BA do it, or jump to a conclusion? Check for the investigation deliverables the requirement asked for.

    4. AFFECTED-FILE ACCURACY: do the files BA identified exist, contain the code BA claims, and fit the import chain BA relies on?

    5. SPEC-TEXT-VS-EXECUTION DRIFT: when an AC's literal regex, command or verification recipe gives output the AC text does not predict, but a different formulation of the same check does verify the AC's intent, raise a 'dimension: spec_text_vs_execution_drift' objection requiring BA to rewrite the AC text to the runnable formulation.

    Return JSON:
    {
      'task_id': '{pipeline.timestamp_suffix}',
      'verdict': 'pass' or 'fail',
      'objections': [
        {
          'dimension': 'evidence_quality|scope_alignment|investigation_completeness|affected_file_accuracy|spec_text_vs_execution_drift',
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

**Wait for ALL BA-validation QA subagents to complete.** Per pipeline, read `docs/dev/ba-qa-report-{pipeline.timestamp_suffix}.json`: verdict `pass` validates BA's conclusions and the pipeline proceeds to Step 12; verdict `fail` goes to Step 11.

### Step 11: BA-QA Iteration Loop (if QA rejects BA)

The only exit is QA's BA-validation verdict `pass`. A `fail` is a process step: it sends the pipeline back to BA with QA's objections, and Steps 9-10 run again, with no iteration cap. Every BA invocation is followed by QA validation. Each pipeline iterates independently; track the BA-QA iteration per pipeline (from 1) in TodoWrite and the cycle log. Announce `BA-QA iteration <N> for pipeline <pipeline_id>: QA found <count> objections in BA analysis. Re-invoking BA to address objections.` and re-invoke BA:

```
Use Agent tool with:
- subagent_type: "ba"
- description: "Re-investigate: address QA objections on analysis quality"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <MAIN_ROOT>/.claude/dev-registry/$DEV_SESSION_ID/ba.json to register with the enforcement system. Do this BEFORE any other tool call.
  CHECKPOINT MARKING: follow your agent file's checkpoint pointer: mark or waive every cp-NN of your own slot; a pending one blocks your stop (subagentstop-cp-enforce.py).

  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="ba", pipeline="dev-overnight", profile="overnight", task_id="{pipeline.timestamp_suffix}", artifacts=[{"kind":"json","path":"docs/dev/context-{pipeline.timestamp_suffix}.json","schema":"context.v1","identity":{"task_id":"{pipeline.timestamp_suffix}","request_id":"{pipeline.timestamp_suffix}"}},{"kind":"markdown","path":"docs/dev/ticket-{pipeline.timestamp_suffix}.md","identity_anchor":"{pipeline.timestamp_suffix}"}]. dispatched_at is captured immediately before this Agent call

  <If codex_required == true, include:>
  codex_required: true

  You are the BA subagent. Follow agents/ba.md instructions precisely.

  User requirement document: $REQUIREMENT_DOC

  Your previous analysis was REJECTED by QA. Address each objection below with concrete evidence. Do not argue: investigate and provide proof.

  Original requirement: '<requirement>'
  Previous BA spec: docs/dev/ticket-{pipeline.timestamp_suffix}.md (legacy: docs/dev/ba-spec-{pipeline.timestamp_suffix}.md)
  Previous context: docs/dev/context-{pipeline.timestamp_suffix}.json
  Spec file: {pipeline.spec_path}

  QA objections:
  <JSON array of objections from ba-qa-report>

  For each objection perform the investigation QA requested and provide the evidence it asked for: if your claim was wrong, CORRECT it; if it was right, PROVE it. Update the spec and the context JSON with the corrected or proven analysis.
  Return JSON with status and updated file paths.
  "
```

After BA re-delivers, return to Step 9, then Step 10; a producer question from BA is decided by Hard Rule 5.

### Step 11g: Graphify Dev-Dispatch Precondition (shared, idempotent, advisory/fail-open)

Graphify enrichment MUST have run, against the context dev will consume, before EVERY `Agent(subagent_type: "dev")` dispatch. It is keyed on the dev-dispatch boundary, not on Step 12: three sites route through it immediately before their dev call, **Step 12**'s dev loop (from BA-QA `pass` and from a resume), **Step 13**'s dev re-invoke and **Step 17**'s iteration dispatch at the pipeline's new `iteration`. It mirrors `commands/dev.md` Step 9 and fires for every pipeline about to go to dev.

Per site, for the one pipeline[i] about to go to dev:

1. Mark the `Step 11g` todo `in_progress` BEFORE the graphify `Agent` call, and restore the surrounding step (12, 13 or 17) `in_progress` before the dev call. Otherwise `hooks/pretool-subagent-enforce.py` resolves the step in progress as the dev step and refuses the graphify dispatch as a role mismatch.
2. **Idempotency by context fingerprint, never by bare existence.** graphify-enrich records `pipeline_index`, `iteration`, `context_path` (exactly as passed in `--context-file`) and `context_sha256` (the SHA-256 of that file's bytes) in `.claude/dev-registry/<DEV_SESSION_ID>-pipeline-{pipeline.index}/graphify/graphify-run.json`. Compute the same four values for the context dev will consume at the pipeline's current `iteration`. Skip the dispatch only when the record exists and all four match; if it is absent, a field is missing or any differs (the context changed, or Step 17 advanced `iteration`), re-run enrichment, which overwrites it.
3. Dispatch graphify (mode=enrich), always, so the `Step 11g` todo's `subagent_call` is satisfied: graphify itself fails open (exit 0 with `status=skipped` or `unavailable` when the sentinel, binary or blast-radius map is absent). The prompt opens with the FIRST ACTION read of graphify's registry file; a dropped line fails the subagent open with no error.

```
Use Agent tool with:
- subagent_type: "graphify"
- description: "Graphify enrichment (mode=enrich) for pipeline {i} before Dev dispatch"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <MAIN_ROOT>/.claude/dev-registry/$DEV_SESSION_ID/graphify.json to register with the enforcement system. Do this BEFORE any other tool call.

  You are the graphify subagent. Follow agents/graphify.md instructions precisely.

  Run: source "${CLAUDE_HOME:-$HOME/.claude}/venv/bin/activate" && python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/graphify-enrich.py" --task-id <DEV_SESSION_ID>-pipeline-{pipeline.index} --context-file <the context file Dev will consume for this pipeline> --pipeline-index {pipeline.index} --iteration {pipeline.iteration}

  This is advisory — if the binary is absent or blast-radius-map is missing, exit 0 with status=skipped.

  Note: overnight passes no `--blast-radius-map`, so graphify-enrich takes the map from the `--context-file`'s `blast_radius_map_path` field: the overnight BA records the map under its own `{pipeline.timestamp_suffix}` task id, which the `<task-id>`-derived default would never match.
  "
```

4. Enrichment never hard-blocks dev. Ran, skipped or unavailable, graphify-enrich writes the run record (`graphify-run.v1`: `status` of `ok|skipped|unavailable` and `task_id`, plus the fingerprint); you never write it. When its `status` is `ok` or `degraded`, the dev dispatch that follows adds `Graph context file: .claude/dev-registry/${DEV_SESSION_ID}-pipeline-{pipeline.index}/graphify/focused-subgraph.json` (resolved id substituted). The per-pipeline `graphify-run.json` and `focused-subgraph.json` are sidecar artifacts, not contract artifacts.

### Step 12: Run All Dev Subagents (Parallel)

Launch dev for every active pipeline whose BA-QA verdict is `pass`, dispatched per Hard Rule 11. Immediately before each pipeline's dev `Agent` call, inside the loop and not once before it, route that pipeline through Step 11g against `docs/dev/context-{pipeline.timestamp_suffix}.json`; this covers a resume that lands here too.

```
For each active pipeline[i]:

# Step 11g precondition for pipeline[i] runs HERE, immediately before the Dev dispatch
Agent(subagent_type: "dev")
  description: "Dev implementation for pipeline {i}: {pipeline.description}"
  run_in_background: false
  prompt: "
    FIRST ACTION: Read <MAIN_ROOT>/.claude/dev-registry/$DEV_SESSION_ID/dev.json to register with the enforcement system. Do this BEFORE any other tool call.
    CHECKPOINT MARKING: follow your agent file's checkpoint pointer: mark or waive every cp-NN of your own slot; a pending one blocks your stop (subagentstop-cp-enforce.py).

    Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="dev", pipeline="dev-overnight", profile="overnight", task_id="{pipeline.timestamp_suffix}", artifacts=[{"kind":"json","path":"docs/dev/dev-report-{pipeline.timestamp_suffix}.json","schema":"dev-report.v2","identity":{"task_id":"{pipeline.timestamp_suffix}"}}]. dispatched_at is captured immediately before this Agent call

    <If codex_required == true, include:>
    codex_required: true

    You are the dev subagent. Follow agents/dev.md instructions precisely.

    User requirement document: $REQUIREMENT_DOC

    Context file: docs/dev/context-{pipeline.timestamp_suffix}.json
    BA spec file: docs/dev/ticket-{pipeline.timestamp_suffix}.md (legacy: docs/dev/ba-spec-{pipeline.timestamp_suffix}.md)
    Overnight spec file: {pipeline.spec_path}
    View file: {view_paths[this-agent] or null}
    Write your implementation report to: docs/dev/dev-report-{pipeline.timestamp_suffix}.json
    Project root: <validated worktree_path from state file>

    Read the overnight spec file FIRST for cross-cycle context; do not write it.
    Your approach, its rationale and your exact file:line changes go in your report's dev.tasks_completed entries (description, rationale, changes).

    All file reads, writes and git operations use absolute paths inside the project root above. Under isolation_kind registered_worktree or fresh_clone_checkout that root is an isolated tree: do not modify files in the main project directory. Under in_place it IS the main checkout, where the work belongs.
  "
```

**Wait for ALL dev subagents to complete.**

### Step 13: Validate All Dev Implementations

For each active pipeline[i], read `docs/dev/dev-report-{pipeline.timestamp_suffix}.json` and check that: its status is `completed` (the only legal dev status); all tasks are documented; scripts created have usage examples; the git rationale references the root cause; the files reported created or modified exist; and the implementation layer matches the layer of BA's spec (a mismatch means the same layer is being retried).

If dev wrote a producer question (`docs/dev/producer-question-{pipeline.timestamp_suffix}-dev.json` instead of its report), decide and record it by Hard Rule 5 and re-dispatch dev with the decision as below.

On a gap, name it (missing information, an undocumented task, a reported file that does not exist) in the re-dispatch prompt; the context stays BA's, you never write it. BEFORE re-invoking, route the pipeline through Step 11g against the context dev will consume (BA's, unchanged, at the same `iteration`, so a run record whose fingerprint matches is skipped). Re-invoke only that pipeline's dev (a fresh dispatch: same obligation template, fresh `dispatched_at`) and validate again: a completed dev report that passes validation is the only way forward.

### Step 14: Prepare QA Environment (Docker Rebuild)

Without this step QA tests stale code and produces false passes. You do it inline; PM has no QA-preparation mode.

1. Read each active pipeline's dev report and its ticket.
2. In autonomous mode (Hard Rule 9), rebuild the affected services identified from `docker-compose.yml` (backend changes rebuild the backend, frontend changes the frontend), with build contexts pointing at `worktree_path` (the isolated worktree under `--worktree`; the same path as the main root in place): `docker compose build`, then `docker compose up -d`, then wait until the services are healthy. In user-provided mode skip the rebuild unless the spec's Pipeline Workflow requires it.

A failed rebuild is a process step, not an exit: debug and rebuild until the services are healthy, with no attempt cap. Never proceed to QA with stale containers.

### Step 15: Run All QA Subagents (Parallel)

Launch QA for every active pipeline whose dev report passed Step 13, dispatched per Hard Rule 11.

```
For each active pipeline[i]:

Agent(subagent_type: "qa")
  description: "QA verification for pipeline {i}: {pipeline.description}"
  run_in_background: false
  prompt: "
    FIRST ACTION: Read <MAIN_ROOT>/.claude/dev-registry/$DEV_SESSION_ID/qa.json to register with the enforcement system. Do this BEFORE any other tool call.
    CHECKPOINT MARKING: follow your agent file's checkpoint pointer: mark or waive every cp-NN of your own slot; a pending one blocks your stop (subagentstop-cp-enforce.py).

    Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="qa", pipeline="dev-overnight", profile="final_verification", task_id="{pipeline.timestamp_suffix}", artifacts=[{"kind":"json","path":"docs/dev/qa-report-{pipeline.timestamp_suffix}.json","schema":"qa-report.v2","identity":{"task_id":"{pipeline.timestamp_suffix}","request_id":"{pipeline.timestamp_suffix}"}}]. dispatched_at is captured immediately before this Agent call

    <If codex_required == true, include:>
    codex_required: true

    You are the QA subagent. Follow agents/qa.md instructions precisely.

    User requirement document: $REQUIREMENT_DOC

    Context file: docs/dev/context-{pipeline.timestamp_suffix}.json
    Dev report file: docs/dev/dev-report-{pipeline.timestamp_suffix}.json
    BA spec file: docs/dev/ticket-{pipeline.timestamp_suffix}.md (legacy: docs/dev/ba-spec-{pipeline.timestamp_suffix}.md)
    Overnight spec file: {pipeline.spec_path}
    View file: {view_paths[this-agent] or null}
    Write your verification report to: docs/dev/qa-report-{pipeline.timestamp_suffix}.json
    Project root: <validated worktree_path from state file>

    Read the overnight spec file FIRST for cross-cycle context and acceptance criteria; do not write it.
    Report Section 4 (Current State) measured values, and on a fail verdict Section 6 (Why Not Met) and Section 7 (What Must Be Done), in your report's qa.spec_section_updates (agents/qa.md Output Format).

    All file reads and verification use the project root above. Verify that changes were made under `worktree_path`: the isolated worktree under `--worktree`, the main checkout itself when `isolation_kind` is `in_place`.

    <If focus_verification_criteria array exists from Step 7, include:>
    Focus verification criteria (hard pass/fail from the user's focus directive). QA records `evidence_level` for every result; `rendered_cached` cannot satisfy `required_evidence_level: extraction_verified`:
    <list each criterion from focus_verification_criteria array>
    Verify each criterion above; a failure counts toward your QA verdict.
  "
```

**Wait for ALL QA subagents to complete.**

### Step 16: Process All QA Results

For each active pipeline[i], read `docs/dev/qa-report-{pipeline.timestamp_suffix}.json`. `qa.status` `pass`: mark the pipeline `phase = "done"`, `status = "fixed"` and write its completion report. `warning` or `fail`: mark `phase = "qa_failed"`, a process step that enters iteration in Step 17; only a pass ends the loop. Report `Pipelines passed: {count} of {total}` and `Pipelines needing iteration: {count}`. If no pipeline is `qa_failed`, skip Step 17 and go to Step 18.

**Completion report** (each pipeline whose QA passes, here or at its Step 17 loop exit): a pipeline's chain is a `/dev` chain under its own task id `{pipeline.timestamp_suffix}`: ticket and context (Step 8), dev report (Step 12), QA report (Step 15), and this report, which you write when its QA passes. `/close --auto` (Post-loop flow) finds a pipeline only through the artifact chain (`resolve-dev-artifact-chain.py`), and the chain names this report: a pipeline without it is never closed or committed. Write `docs/dev/completion-{pipeline.timestamp_suffix}.md` with one Bash call (Hard Rule 4): `cat > docs/dev/completion-{pipeline.timestamp_suffix}.md <<'REPORT'`, the report below, `REPORT`:

```markdown
# Development Completion Report — {pipeline.timestamp_suffix}

**Request ID**: {pipeline.timestamp_suffix}
**Task ID**: {pipeline.timestamp_suffix}
**Completed**: <ISO-8601>
**Source**: /dev-overnight session <session_id>, cycle <N>, pipeline {pipeline.index}

## Requirement

{pipeline.description}

## Quality Verification

**Status**: PASSED

## Files Generated

- Ticket: `docs/dev/ticket-{pipeline.timestamp_suffix}.md`
- Context: `docs/dev/context-{pipeline.timestamp_suffix}.json`
- Dev Report: `docs/dev/dev-report-{pipeline.timestamp_suffix}.json`
- QA Report: `docs/dev/qa-report-{pipeline.timestamp_suffix}.json`
```

### Step 17: Per-Pipeline Iteration Loops (if QA fails)

QA fail: re-dispatch this lane's dev (through Step 11g first) with the QA report path, the same task_id, lane and obligation template, and a fresh dispatched_at; once it returns, Steps 13-16 run again for that pipeline, and this loop repeats until its QA passes (Step 16 marks it done and writes its completion report). A producer question from BA or dev: Hard Rule 5, and the loop continues with the chosen option.
The Stop gate keeps the command open until the disposition is chain_pass: while the window is open outright, and after `end_time` until each pipeline's chain passes (its QA report's `qa.status` is `pass`) and the closeout is on disk (`hooks/stop-command-gate.py`, the Stop coordinator's `completion` phase). There is no iteration cap and no other exit.
Dispatch line: `QA report file: docs/dev/qa-report-{pipeline.timestamp_suffix}.json`.

### Step 18: Update Settings.json Permissions (Aggregated)

Aggregate the permissions of ALL pipelines before updating, and apply them in one invocation, the aggregator's list piped to the applier as `/dev` does:

```bash
python3 "<HARNESS_ROOT>/scripts/aggregate-permissions.py" docs/dev/ docs/dev/overnight/<session_id>/pipelines.json | bash "<HARNESS_ROOT>/scripts/apply-permissions.sh" /dev/stdin .claude/settings.json
```

The aggregator keeps the QA reports whose `timestamp_suffix` matches a `status: fixed` pipeline, extracts `qa.permissions_verification.validated_permissions[]` and emits a list deduplicated by `pattern`; the applier merges each entry into `.permissions.<section>` (allow, ask or deny) atomically and skips patterns already present.

### Step 19: Log All Cycle Results and Check Time

A pipeline leaves Step 17 only on a QA pass, so the tally is the cycle's fixed pipelines and their iterations.

**Append to running log** at `docs/dev/overnight-log-<date>.md`, one Bash call (Hard Rule 4): `cat >> docs/dev/overnight-log-<date>.md <<'LOG'`, the entry below, `LOG`.

```markdown
### Cycle <N>: {total_pipelines} pipelines ({fixed_count} fixed)

| Pipeline | Issue | Status | Iterations |
|----------|-------|--------|------------|
| 0 | {description} | Fixed | 1 |
| 1 | {description} | Fixed | 2 |
| ... | ... | ... | ... |

**Decisions made without the owner**: <pipeline> <task_id>: <decision>; options <labels>; <experiment and its result, or "the question's default">; chosen <label> (one line per decision of this cycle, spec-declared user gates first, each as recorded when it was made, Hard Rule 5; "none" when there was none)

**Time**: <timestamp>
```

**TIME CHECK**: invoke `bash "<HARNESS_ROOT>/scripts/overnight-status.sh" <MAIN_ROOT>/.claude/overnight-state-<session_id>.json`; it reads the record through `hooks/lib/overnight.py`, reports the window verdict with the wall-time remaining to `end_time`, and exits non-zero once the window has closed. Either way go on to Step 20 (PM Retro). If the window has closed, Step 21 then ends the session; otherwise mark Step 21 completed via TodoWrite to trigger the loop reset. Nothing commits: the cycle's work stays in the working tree, snapshotted in `refs/checkpoints/<worktree_branch>`, until the owner lands it (Hard Rule 8).

### Step 20: PM Retrospective

`FINAL_CYCLE` is `true` when the Step 19 time check found the window closed, else `false`.

```
Use Agent tool with:
- subagent_type: "pm"
- description: "PM retrospective: cycle {N} summary and next-cycle handoff"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <MAIN_ROOT>/.claude/dev-registry/$DEV_SESSION_ID/pm.json to register with the enforcement system. Do this BEFORE any other tool call.
  CHECKPOINT MARKING: follow your agent file's checkpoint pointer: mark or waive every cp-NN of your own slot; a pending one blocks your stop (subagentstop-cp-enforce.py).

  Obligation block: embed `<obligation v="1">{...}</obligation>` here with task_id="<TS>", lane=null, lane_set=null, role="pm", pipeline="dev-overnight", profile="overnight", artifacts=[{"kind":"json","path":"docs/dev/overnight/<session_id>/retro-report-cycle<N>.json","schema":"retro-report.v1","identity":{"task_id":"<TS>"}}]. <TS> and dispatched_at are captured immediately before this Agent call, as in Step 2

  PM_MODE: RETRO
  FINAL_CYCLE: <true|false>

  You are the PM subagent in RETRO mode. Follow agents/pm.md Retrospective Protocol.

  User requirement document: $REQUIREMENT_DOC

  Project path: <validated worktree_path from state file>
  Session ID: <session_id>
  Cycle number: <N>

  Read your triage report: docs/dev/overnight/<session_id>/triage-report-cycle<N>.json
  Read pipeline results from state file cycle_log (current cycle entries)
  Read QA reports: docs/dev/qa-report-*.json (for this cycle's pipeline timestamp suffixes)
  Read Dev reports: docs/dev/dev-report-*.json (for this cycle's pipeline timestamp suffixes)

  Also read ALL previous retro reports for continuity:
  docs/dev/overnight/<session_id>/retro-report-cycle*.json

  Overnight spec files (one per pipeline -- read ALL; do not write them):
  <For each pipeline in current_issues: {pipeline.spec_path}>

  For each UNRESOLVED finding, record in your retro report's unresolved_issues (PM reads it when it plans the next cycle):
  - What Must Be Done: prescriptive next step with exact file, line, action
  - Attention Notes: issue-specific traps and warnings for the next cycle
  Only findings the session discovered itself belong there: an outcome the user's spec or request asks for is never listed as left for a later cycle.

  <If spec_mode == 'user-provided' AND view_paths['orchestrator'] is non-null, include:>
  Orchestrator view file: <view_paths['orchestrator']>
  Read the orchestrator view FIRST (Role Mandate, Pipeline Workflow, Anti-Patterns, the Hard Rules you enforce as supervisor); use it to shape What Must Be Done and Attention Notes and to judge whether this cycle's specialist invocations complied with the spec.

  <If codex_required == true, include:>
  codex_required: true

  Write retro report to: docs/dev/overnight/<session_id>/retro-report-cycle<N>.json
  "
```

**Wait for PM-Retro to complete.** This dispatch is the cycle contract's Step 20 entry, so when it returns `hooks/posttool-overnight-file-check.py` checks `retro-report-cycle<N>.json` against the schema its obligation names (`schemas/retro-report.v1.json`: `plan_vs_outcome`, `unresolved_issues`, `cycle_stats` and, when `FINAL_CYCLE: true`, `final_summary`). If that check refuses the report (its message names the path and the failing rule), re-invoke PM-Retro (a fresh dispatch: same obligation template, fresh `dispatched_at`) until the report passes, with no retry cap: a retrospective report on disk is part of the session's closeout (Step 21).

**Check `qa_rerun_required`** in the retro report: if `true`, re-invoke QA, as Steps 14-16 do, for the pipelines in `qa_rerun_reasons`, adding `This is a PM-requested QA re-run. Reasons: <qa_rerun_reasons>. Focus on the specific concerns raised.`, then go to Step 21 without re-invoking RETRO (no infinite loop); if `false` or absent, go to Step 21.

### Step 21: Generate Summary Report or Loop

**If time remains**: mark this step completed via TodoWrite. `posttool-overnight-loop.py` (PostToolUse:TodoWrite) sees every todo completed (Step 11g included) and a future `end_time`, and hands you the continuation instructions as additionalContext: reset all todos to pending (the hook writes no todos itself), mark Step 0 (the wake still runs) and Step 1 completed, and resume from Step 2 (the working root exists).

**If time expired** (session ending): read the full state file (start time, end time, isolation) and the cycle data, which the state file does not hold: the PM retro reports (`docs/dev/overnight/<session_id>/retro-report-cycle*.json`) and the cycle log. Generate the summary at `docs/dev/overnight-summary-<date>.md`, one Bash call (Hard Rule 4): `cat > docs/dev/overnight-summary-<date>.md <<'SUMMARY'`, the report below, `SUMMARY`.

```markdown
# Overnight Development Summary

**Session**: <session_id>
**Start time**: <start_time>
**End time**: <end_time> (planned) / <actual_end> (actual)
**Duration**: <hours>h <minutes>m
**Cycles completed**: <cycle index - 1>
**Isolation**: <isolation_kind> — working root <worktree_path>, branch <worktree_branch>

## Statistics

| Metric | Count |
|--------|-------|
| Issues found | <issues_found> |
| Issues fixed | <issues_fixed> |
| Issues deferred by PM triage (skip/defer) | <issues_triage_deferred> |
| Fix rate | <percentage>% |

## Decisions made without the owner

| Pipeline | Task id | Decision | Options | Evidence or experiment | Chosen option |
|----------|---------|----------|---------|------------------------|---------------|
| <index> | <task_id> | User gate: <gate> | <labels> | <experiment and its result, or "the question's default"> | <label> |
| <index> | <task_id> | <decision> | <labels> | <experiment and its result, or "the question's default"> | <label> |

## Cycle Details

### Cycle <cycle>: <issue>
- **Status**: Fixed
- **Location**: <file>
- **Changes**: <summary>
- **Iterations**: <N>

## Files Generated

- Context files: `docs/dev/context-*.json`
- Dev reports: `docs/dev/dev-report-{pipeline.timestamp_suffix}.json`, one per pipeline
- QA reports: `docs/dev/qa-report-{pipeline.timestamp_suffix}.json`, one per pipeline
- Completion reports: `docs/dev/completion-{pipeline.timestamp_suffix}.md`, one per passed pipeline
- Running log: `docs/dev/overnight-log-<date>.md`

## Recommendations

<Patterns noticed during exploration that need human decision-making>
```

**Decisions made without the owner** lists every decision of the session, one row each, spec-declared user gates first (Hard Rule 1), each as recorded when it was made (Hard Rule 5); write "None" under the heading when there was none. One `### Cycle <cycle>: <issue>` entry per pipeline fixed, with its cycle number. Nothing in the summary, Recommendations included, lists a requested outcome as left for a later cycle (Delivery rule): the triage-deferred count and Recommendations hold only findings the session discovered itself.

**After `end_time` nobody is asked and nothing waits for the owner.** The Stop gate (`hooks/stop-command-gate.py`, behind `hooks/stop-launch.py`) lets the session end once every pipeline's disposition is chain_pass and the closeout is on disk (`closeout_gaps` in `hooks/lib/overnight.py`): a PM retrospective report (`retro-report-cycle*.json` under `docs/dev/overnight/<session_id>/`, Step 20) and this summary (a non-empty `overnight-summary-*.md` under `docs/dev/`) written since `start_time`. Until both exist its block names what is missing.

**The session lands nothing.** Do not merge, squash, cherry-pick, commit or copy files by hand: `/close`, `/commit`, `/merge` and `/push` are human-typed (`settings.json` denies their `Skill` calls). The work stays in the working tree at `worktree_path`, snapshotted in `refs/checkpoints/<worktree_branch>`; an isolated worktree is preserved for the owner's `/commit --auto` and `/merge`. Under `in_place` there is no session-created branch: the commits land on the working branch the checkout was already on.

**Announce completion**:

```
Overnight development session complete.

Duration: <hours>h <minutes>m
Cycles: <cycle index - 1>
Fixed: <issues_fixed> | Decisions made without the owner: <decision_count> (listed in the summary)

Summary: docs/dev/overnight-summary-<date>.md
Log: docs/dev/overnight-log-<date>.md
--- Isolation: <isolation_kind> ---
Branch: <worktree_branch>
Path:   <worktree_path>
<If isolation_kind != 'in_place', add the line: "--- Worktree preserved for review ---">

Nothing is committed yet: the work is in the working tree at <worktree_path>,
snapshotted in refs/checkpoints/<worktree_branch>. To review it first:
  git -C <worktree_path> status
  git -C <worktree_path> diff

To land it, type these commands yourself, in this order. This session runs none of them.

<If isolation_kind != 'in_place', include:>
In a session opened at <worktree_path>:
  /close --auto
  /commit --auto
Then in the main checkout (<main_root>):
  /merge <worktree_branch>
  /push

<If isolation_kind == 'in_place', include instead:>
In this checkout (<worktree_path>):
  /close --auto
  /commit --auto
  /push
There is no session-created branch, so there is nothing to /merge.

The closeout is on disk; the time-lock lets the session end.
```

**Delete the wake** (the last step of this branch): `CronDelete` with the job id Step 0's `CronCreate` returned, then mark Step 21 completed. The Stop gate refuses the Stop after `end_time` while the wake has no `CronDelete`.

### Post-loop flow (typed by the owner)

After the session ends the owner lands its work once, typing each command himself in this order (the session runs none of them): four commands under `registered_worktree` / `fresh_clone_checkout`, three under `in_place`, which has no branch to merge.

1. **`/close --auto`**, always first, in a session opened at `<worktree_path>` (isolated modes) or in the checkout (`in_place`): it closes every task waiting to be closed (`close_pending`), each completed pipeline among them (its chain ends in Step 16's completion report), through the normal `/close` route.
2. **`/commit --auto`**, not optional, in the same place: it commits every task waiting to be committed (`commit_pending`) through the normal `/commit` route; this is where the work becomes commits on `<worktree_branch>`.
3. **`/merge <worktree_branch>`**, isolated modes only, in the main checkout: it merges the session branch into the default branch (the owner resolves conflicts). Skip it under `in_place`: no session-created branch exists.
4. **`/push`**: in the main checkout it pushes the default branch (isolated); in the checkout it pushes the working branch, never the protected one (`in_place`). It needs a clean working tree and commits ahead of upstream.
