---
description: Close the current dev cycle (agent infers task-id from conversation). QA evaluates Workflow Integrity bullets and returns CLOSE YES/NO. Pass --codex to enable multi-round QA-codex debate; default is QA-only single-round assessment. Append --force to skip the debate entirely.
argument-hint: "[--codex | --force [--reason \"<text>\"]] [<task-id>|<path>]"
disable-model-invocation: true
---

# /close

True wrapper. Three TodoSteps (user-visible work):
1. Dispatch three inspectors (parallel for single-dev cycles; sequential for parallel-dev cycles).
2. Delegate close debate to QA subagent.
3. Generate close-report + spec/temp update (echo QA verdict + write report + emit next-step update).

Argument parsing (`--codex` / `--force`) and task-id resolution still happen
in this command body, but are no longer TodoSteps — they are command-internal
plumbing, not user-visible work.

The orchestration of rounds, the calls to codex, the evaluation of agreement, and the writing of the transcript all live INSIDE QAs invocation. /close itself does not call codex, does not manage rounds, and does not decide the verdict.

## Invocation

```
/close                                       # agent infers task-id from current /dev cycle (typical use)
/close --force                               # skip debate, audit-logged (escape hatch — see Forced override path below)
```

Power users may also pass an explicit task-id or path: `/close <task-id>` or `/close docs/dev/ticket-<ts>.md` (legacy: `/close docs/dev/ba-spec-<ts>.md`). The orchestrator parses these forms but the typical invocation is bare `/close` and lets the agent resolve the task-id from conversation context. No filesystem scan, no default-to-newest.

<!-- Cross-reference: BA spec /root/docs/dev/ba-spec-20260426-redev8.md § AC-CLOSE-FORCE-1..6 govern --force / --reason behavior. -->


## Workflow

**Sentinel-before-todo contract**: If `--force` is present in `$ARGUMENTS`, the sentinel file MUST be written BEFORE loading the preloaded todo list (i.e., before `close.py` is run). The forced-override path procedure (steps 1-8 below) is the canonical authority; "Load preloaded todo list" applies only to the normal (non-force) path.

Load preloaded todo list (non-force path only): activate venv and run `~/.claude/scripts/todo/close.py`.

### Argument parsing: `--codex` flag (applies to non-force paths)

Parse `--codex` from `$ARGUMENTS` BEFORE evaluating the forced-override path or task-id resolution:

- If `$ARGUMENTS` contains the literal token `--codex` (in any position), strip it and set `codex_required = true`.
- Otherwise set `codex_required = false` (default).

`codex_required` controls whether QA's internal multi-round debate (Step 2) consults codex via `Skill(codex)`:

- **`codex_required = true`**: dispatch prompt for QA includes the full multi-round QA-codex debate protocol as documented in Step 2 below. Verdict branches 1 / 2 / 3 / 6 / 7 apply.
- **`codex_required = false`** (default): dispatch prompt for QA SKIPS all `Skill(codex)` invocations and runs QA-only single-round assessment of the 4 Workflow Integrity bullets + step 1b cleanliness preconditions. Verdict branch 9 (codex disabled) applies; branches 3 / 6 / 7 are N/A.

When `--force` is also present, `--codex` is ignored (the forced-override path short-circuits the entire debate path; no QA invocation, no codex consultation, no verdict-branch evaluation). The two flags are not mutually exclusive parse-wise (orchestrator strips both), but `--force` wins.

### Forced-override path: `--force` flag short-circuit

If `$ARGUMENTS` contains the literal token `--force` (in any position), this short-circuits the entire debate path. **The model itself cannot trigger this** — `disable-model-invocation: true` (frontmatter line 3) prevents `SlashCommand`-based self-invocation regardless of arguments. Only a human invoking via the slash UI can trigger `--force`.

Argument parsing order (orchestrator parses at the slash-command layer):

```
```

Procedure when `--force` is present:

The forced-override todo list has exactly **2 steps** (no Step 2 / QA dispatch):
- Step 1: Write forced close-report
- Step 2: Write audit log entry + temp update + clean up sentinel

**Important**: Do NOT add a QA dispatch step to the forced-override todo list. The sentinel (written in step 1 below) is belt-and-suspenders; the primary protection is that the todo list never contains a QA dispatch step.

1. **Strip `--force` from `$ARGUMENTS`**. If `--reason "<text>"` follows, capture `<text>` (everything between the matched quotes) as `$REASON`. If absent, set `$REASON="no reason provided"`.

   **Immediately write force sentinel** (BEFORE any todo initialization and BEFORE loading close.py): resolve `DEV_SESSION_ID` from the dev-registry directory used for this session (the directory name under `.claude/dev-registry/` — format `dev-YYYYMMDD-HHMMSS`). Write an empty sentinel file at `/tmp/claude-close-force-<DEV_SESSION_ID>.flag`. If the write fails, proceed with the forced close (the primary protection is the 2-step todo; the sentinel is defense-in-depth).

2. **Resolve the task-id** from the remaining argument using the same Task-id resolution rules below (explicit path → derive from basename; timestamp → use directly; no argument → orchestrator infers from session context). Reuse the same task-id form-detection and TASK_ID derivation rules below; do NOT create a separate path/timestamp/no-argument resolution algorithm for `--force`. Artifact existence checks are path-specific: when this resolution is invoked from the Forced-override path, skip `qa-report-<task-id>.json` verification.
3. **Skip Step 2 entirely** — no QA subagent invocation, no Skill(codex) call, no Workflow Integrity Dimension evaluation, no multi-round debate.
4. **Write the forced close-report** to `docs/dev/close-report-<task-id>.md` with this exact structure:

   ```
   # Close Debate Report (FORCED)
   Task-id: <task-id>
   Mode: --force (user override)
   Closed at: <ISO-8601 timestamp>
   Reason: <$REASON value, or "no reason provided">

   **Verdict**: **CLOSE: YES — FORCED by user override**

   No multi-round debate occurred. The user explicitly invoked /close with
   --force, accepting full responsibility for any defects this verdict masks.

   ## Forced Override Audit
   - Timestamp: <ISO-8601>
   - Task-id: <task-id>
   - Invoker: human user (model cannot self-invoke /close; disable-model-invocation: true)
   - Workflow Integrity Dimension: ALL bullets OVERRIDDEN — not evaluated
     1. Downstream consumability: OVERRIDDEN
     2. task-id chain consistency: OVERRIDDEN
     3. Pre-existing-defect rule: OVERRIDDEN
     4. Self-deployability: OVERRIDDEN
   - Rationale (from invoker): <$REASON value>
   - User explicitly accepts the risk of closing without debate.

   ---
   CLOSE: YES (FORCED)
   ```

   This file MUST be written even if the task-id has no upstream BA spec / context / dev-report (per AC-CLOSE-FORCE-6). The close-report is itself the audit trail; absence of upstream artifacts becomes visible in the report and is intentional.

5. **Append audit log entry** to `~/.claude/logs/close-overrides.log` (best-effort):

   Append to `~/.claude/logs/close-overrides.log`: a line with ISO timestamp, task-id, mode=force, and the reason string. Create `~/.claude/logs/` if needed. If the append fails, the close-report write still succeeds; the audit log is best-effort.

6. **Create forced-path update and clean up sentinel**: Create the update using `/spec-update --temp`. Default to `mktemp -t update-XXXXXX.md`; do not write this update into the repo unless the user explicitly asks. It must state that closure was forced by the user, reference `docs/dev/close-report-<task-id>.md`, and suggest `/commit <task-id> -m "<summary>"` only if the user still intends to ship despite the skipped debate.

   After the update is created, remove the sentinel file by running `scripts/cleanup-close-force-sentinel.sh` with the resolved sentinel path (e.g. `/tmp/claude-close-force-<DEV_SESSION_ID>.flag`). Errors are swallowed so the close still completes. This cleanup is mandatory, not best-effort.

7. **Print the final stdout line** (this is the line consumers grep for):

   ```
   CLOSE: YES — FORCED
   ```

   The close-report's own final line remains `CLOSE: YES (FORCED)` per the template above (AC-CLOSE-FORCE-1 specifies the report's bottom line in that form). The two forms are intentional: the **stdout signal** uses the em-dash form (`CLOSE: YES — FORCED`) for downstream `/commit` / `/push` consumers; the **close-report final line** uses the parenthesized form (`CLOSE: YES (FORCED)`) so existing `grep "^CLOSE: YES$"` patterns also catch the prefix.

   Stop. Do NOT proceed to Task-id resolution / Step 1 / Step 2 / Step 3.

**When to use** (escape hatch — strongly discouraged for routine use):
- Codex hits its usage limit and Round 2 cannot complete (see redev7 close-debate stall).
- Workflow Integrity Dimension bullet flags a known-acceptable artifact (e.g., parallel-dev cycle pre-F-AGGREGATE).
- Operator has read all dissent and explicitly accepts the risk of shipping NOW.

**What it preserves**:
- `disable-model-invocation: true` — model cannot self-invoke /close (with or without --force). Only human via SlashCommand.
- Close-report artifact (every override is auditable).
- Audit log line (cross-task ledger of all overrides).

**What it skips**:
- Multi-round QA+codex debate (entire Step 2).
- Workflow Integrity Dimension evaluation (all four bullets recorded as `OVERRIDDEN`).

Every forced override is auditable and traceable. Routine use defeats the purpose of /close as a quality gate.

### Task-id resolution

Resolve the **task-id** for the report filename. The task-id is the SAME identifier used by the source `/dev` cycle (for example, a timestamp-style task id) — NOT a fresh `date +%Y%m%d-%H%M%S` at /close invocation time. Using a fresh timestamp would break /commit's PRIMARY-path lookup, which requires `close-report-<task-id>.md` and `dev-report-<task-id>.json` under the SAME `<task-id>`.

Resolve the spec to evaluate (in priority order):
- If `$ARGUMENTS` is an explicit path (ends in `.md`/`.json` or contains `/`): use that path. Verify it exists; fail clearly if not. Derive the task-id by stripping the `ticket-` prefix (or legacy `ba-spec-` prefix) and `.md`/`.json` suffix from the basename (e.g. `docs/dev/ticket-X.md` → task-id `X`; `docs/dev/ba-spec-X.md` → task-id `X`).
- Elif `$ARGUMENTS` matches a timestamp pattern (e.g. `20260424-103044`):
  - **Non-force path**: try `docs/dev/ticket-${ARGUMENTS}.md` first; if absent, fall back to legacy `docs/dev/ba-spec-${ARGUMENTS}.md`. Verify that the ticket/ba-spec file exists. Also resolve `docs/dev/qa-report-${ARGUMENTS}.json` and verify it exists. Both the ticket/ba-spec AND the qa-report must exist for normal-path resolution to succeed.
  - **Forced-override path**: use `$ARGUMENTS` directly as the task-id with NO file existence verification — neither ticket/ba-spec nor qa-report checks apply. The task-id is the argument itself; the close-report becomes the sole audit artifact for this task. This allows `/close <ts> --force` to work even when no ticket, spec, or qa-report file exists (e.g., purely manual `/do` work where no ticket was created).
  The task-id IS `$ARGUMENTS` directly (timestamp form is a valid task-id; this preserves backwards compatibility for `/close <ts>` invocations and works for both ticket- and ba-spec- artifact name conventions).
- Else (no argument): the orchestrator invoking /close MUST already know this conversation's dev artifacts from context (it just ran /dev in the same session). It embeds those paths directly into Step 5's QA prompt and resolves the task-id from the active dev cycle's artifacts. There is NO filesystem scan and NO default-to-newest. If the orchestrator cannot identify the spec from context, exit with: `No spec identified. Either run /close within a conversation that just completed /dev, or provide an explicit path/timestamp.`

If no task-id can be derived (no argument, no /dev context, no parseable filename), /close MUST exit with the same error message above. /close MUST NOT default to `date +%Y%m%d-%H%M%S` for the close-report filename — that would silently break the task-id chain.

Bind the resolved value as `TASK_ID` (e.g. `"$ARGUMENTS"` when timestamp form, or derived from path basename).

Also optionally note companion files if they exist at the same task-id: `context-<task-id>.json`, `dev-report-<task-id>.json`.

### Step 0 (Parallel-Dev Only): Auto-aggregate missing canonical

Before the Normal-path artifact preflight, detect and handle parallel-worker shard dev-reports.

Shard detection uses BOTH filename patterns (scoped to `$TASK_ID`'s bare timestamp `BARE_TID`):
- Role-first: `dev-report-<role>-<BARE_TID>.json` (role = alphanumeric, no dashes)
- Task-first: `dev-report-<BARE_TID>-<worker>.json` (worker = alphanumeric+dot, excluding NON_WORKER_LABELS: draft, final, fix, continuation, wip, iter*, retry*, attempt*)

Count matching shard files in `docs/dev/` scoped to `BARE_TID` only.

**Case 1 — canonical absent, 2+ task-scoped shards found**:
Invoke `source venv/bin/activate && python3 scripts/aggregate-dev-report.py --task-id $TASK_ID` to build the canonical aggregate.
Capture stdout JSON into `AGGREGATE_RESULT`. Parse `action` field from JSON.
If exit non-zero: abort with error — parallel shards exist but aggregate could not be written.
Set `PARALLEL_AGGREGATE_WRITTEN=true` (in-memory, used in Step 1 below).
Write `AGGREGATE_RESULT` to a temp file (`mktemp`) for Step 1 to read if needed.

**Case 2 — canonical present, 2+ task-scoped shards found**:
Invoke `source venv/bin/activate && python3 scripts/aggregate-dev-report.py --task-id $TASK_ID` to validate consistency.
Capture stdout JSON into `AGGREGATE_RESULT`. Parse `action` field.
Set `PARALLEL_AGGREGATE_WRITTEN=true` if action is `"aggregated"` or `"validated"`.

**Case 3 — ≤1 task-scoped shard found**:
Skip Step 0 entirely. Set `PARALLEL_AGGREGATE_WRITTEN=false`.

The `PARALLEL_AGGREGATE_WRITTEN` flag (and `AGGREGATE_RESULT` JSON) must be held in memory within the same close workflow and passed to Step 1's conditional logic below.

### Normal-path artifact preflight (non-force)

After `TASK_ID` is resolved and before Step 1 dispatches inspectors, `/close` MUST run the same Codex-native artifact contract used by `/dev` completion. This preflight applies to `/close <task-id>`, `/close <task-id> --claude-code`, and bare `/close` only when active workflow state/context already resolved `<task-id>`. Bare `/close` with no active task-id keeps the `No spec identified...` failure and MUST NOT scan/default-to-newest.

The preflight validates these exact same-task files: `docs/dev/ticket-<task-id>.md`, `context-<task-id>.json`, `dev-report-<task-id>.json`, `qa-report-<task-id>.json`, and `completion-<task-id>.md`. JSON artifacts must have top-level `request_id` and `task_id` equal to `<task-id>`; the dev report must have nested `dev.status == "completed"` plus `dev.files_modified` and `dev.files_created` arrays; the QA report must have nested `qa.status == "pass"`. Top-level-only `status` / `verdict` fields and subagent final messages are rejected.

Any missing, malformed, mismatched, status-only, or non-passing artifact blocks before inspector dispatch / QA debate and reports the exact path and reason. The forced path is unchanged: `/close --force` short-circuits before this normal-path preflight.

Resolve optional cp-state handoff for the QA close gate:

- If the resolved input spec path is `docs/dev/specs/<SPEC_ID>.md` and
  `.claude/specs/<SPEC_ID>/cp-state-qa.json` exists, bind `SPEC_ID`.
- Else if `context-<task-id>.json` contains a `spec_path`, `spec_file`, or
  `user_spec_path` pointing at `docs/dev/specs/<SPEC_ID>.md`, bind that `SPEC_ID`
  when `.claude/specs/<SPEC_ID>/cp-state-qa.json` exists.
- Else if `.claude/specs/<TASK_ID>/cp-state-qa.json` exists, bind `SPEC_ID="$TASK_ID"`.
- Else bind `SPEC_ID=""` and skip the QA cp-state `SECOND ACTION`.

When `SPEC_ID` is non-empty, `/close` MUST hand the QA subagent
`.claude/specs/<SPEC_ID>/cp-state-qa.json`; this is what makes the close gate
participate in the same check-in/checklist/Stop-block chain as `/dev`.

### Step 1: Agent dispatch — three inspectors (orchestrator authority — `commands/close.md` itself, NOT QA)

**TodoWrite ordering reminder (task 20260519-211515 R3 / AC3)**: TodoWrite mark-as-in_progress for step N must precede any Agent() call dispatched within step N.
The orchestrator MUST emit a TodoWrite call updating the Step-N todo item to `in_progress` BEFORE invoking any Agent() in Step N. REQUIRED ordering: TodoWrite first, then Agent(). Always update the in_progress marker BEFORE dispatch. Before dispatch of any inspector (or any subagent in any Step), the matching Todo item MUST already be in_progress; otherwise do not dispatch.

**Authority note**: inspector subagents (`style-inspector`, `cleanliness-inspector`, `prompt-inspector`) are orchestrator-only auditors. ONLY this `/close` command may dispatch them. Subagents (including QA in Step 2) have NO authority to dispatch inspectors. This Step 1 is the orchestrator-layer dispatch site.

**Compute the cycle-diff file list** before dispatch:

- **Closed-task path** (a `dev-report-<TASK_ID>.json` exists): read the `dev.files_modified` array (top-level non-null list per the dev-report contract); use that list verbatim as `<cycle-diff-file-list>`.
- **Irregular path** (no dev-report-<TASK_ID>.json — e.g., orchestrator-direct edits under `/do`, or hand-edits): run `git diff --name-only` against the relevant repo's cycle commit range to compute the file list. For nested-`.claude` edits the relevant repo is the nested git repo at `/root/.claude` (working-tree root); for parent-repo edits use `/root`.
- If both paths yield an empty list, record `<cycle-diff-file-list>=` (empty) and proceed with dispatch — inspectors will return findings=[] and Step 5 will treat all cleanliness branches as non-blocking.

**Parallel detection check** — before dispatch, evaluate whether a parallel-dev cycle was detected:

A parallel cycle is detected if ANY of the following hold:
- `PARALLEL_AGGREGATE_WRITTEN=true` (set by Step 0 when 2+ task-scoped shards were found)
- The canonical `docs/dev/dev-report-<TASK_ID>.json` has a non-empty `parallel_workers` array
- A fresh shard scan (same two patterns as Step 0, scoped to `TASK_ID`'s bare timestamp) finds 2+ valid worker shards in `docs/dev/`

**If a parallel cycle is detected** — dispatch inspectors SEQUENTIALLY (one Agent call at a time, wait for each to return before the next):

- Agent call 1: `subagent_type: style-inspector`, prompt includes `--changed-files <cycle-diff-file-list>`, instructs the inspector to write its report to `docs/dev/style-inspector-report-<TASK_ID>.json`, and (if `codex_required = true`) includes the literal line `codex_required: true`. Wait for completion.
- Agent call 2: `subagent_type: cleanliness-inspector`, prompt includes `--changed-files <cycle-diff-file-list>`, instructs the inspector to write its report to `docs/dev/cleanliness-inspector-report-<TASK_ID>.json`, and (if `codex_required = true`) includes the literal line `codex_required: true`. Wait for completion.
- Agent call 3: `subagent_type: prompt-inspector`, prompt includes `--changed-files <cycle-diff-file-list>`, instructs the inspector to write its report to `docs/dev/prompt-inspector-report-<TASK_ID>.json`, and (if `codex_required = true`) includes the literal line `codex_required: true`. Wait for completion.

**If no parallel cycle is detected** — dispatch all three inspectors in parallel (original behavior): emit ONE message containing THREE Agent tool calls (concurrent, not sequential):

- Agent tool call 1: `subagent_type: style-inspector`, prompt includes `--changed-files <cycle-diff-file-list>`, instructs the inspector to write its report to `docs/dev/style-inspector-report-<TASK_ID>.json`, and (if `codex_required = true`) includes the literal line `codex_required: true`.
- Agent tool call 2: `subagent_type: cleanliness-inspector`, prompt includes `--changed-files <cycle-diff-file-list>`, instructs the inspector to write its report to `docs/dev/cleanliness-inspector-report-<TASK_ID>.json`, and (if `codex_required = true`) includes the literal line `codex_required: true`.
- Agent tool call 3: `subagent_type: prompt-inspector`, prompt includes `--changed-files <cycle-diff-file-list>`, instructs the inspector to write its report to `docs/dev/prompt-inspector-report-<TASK_ID>.json`, and (if `codex_required = true`) includes the literal line `codex_required: true`.

**Wait** for all three Agent tool calls to return. Each inspector writes its findings JSON to its assigned report path; the orchestrator does not re-interpret or re-aggregate those findings here — Step 2's QA dispatch passes the three concrete report paths as inputs and QA applies the AC-2.6 verdict-plumbing logic against them.

The three concrete inspector report paths produced by Step 1 — for verbatim cross-reference by Step 2's QA dispatch prompt — are:

- `docs/dev/style-inspector-report-<TASK_ID>.json`
- `docs/dev/cleanliness-inspector-report-<TASK_ID>.json`
- `docs/dev/prompt-inspector-report-<TASK_ID>.json`

These exact path strings (with `<TASK_ID>` substituted) MUST appear verbatim inside the Step 2 QA dispatch prompt body so the cross-reference between Step 1 output and Step 2 input is mechanical, not narrative.

### Step 2: Delegate close debate to QA subagent

Use the Agent tool with `subagent_type: qa` ONCE. The entire debate happens inside this single subagent call. Pass this prompt (substitute paths and $TS):

```
FIRST ACTION: if a dev-registry sentinel for this session exists at $CLAUDE_PROJECT_DIR/.claude/dev-registry/<SESSION_ID>/qa.json, read it to register.
SECOND ACTION (only if SPEC_ID is non-empty): read $CLAUDE_PROJECT_DIR/.claude/specs/<SPEC_ID>/cp-state-qa.json to load your mandatory checklist before the debate. Mark each completed checkpoint with /root/.claude/scripts/spec-check.py mark --spec-id <SPEC_ID> --agent qa --agent-id $CLAUDE_AGENT_ID --cp-id <cp-NN>. Waive only with /root/.claude/scripts/spec-check.py waive --spec-id <SPEC_ID> --agent qa --agent-id $CLAUDE_AGENT_ID --cp-id <cp-NN> (auto-text records actor + ISO timestamp). You MUST leave zero pending checkpoints before Stop; subagentstop-cp-enforce.py blocks exit otherwise. If `$CLAUDE_AGENT_ID` is unavailable, use the `agent_id` value written into the cp-state file by the read.

You are the QA gatekeeper evaluating whether a completed development can be closed. The orchestrator passes a `codex_required: <true|false>` flag in this dispatch:

- **`codex_required: true`** (user passed `--codex` to /close): you run a MULTI-ROUND INTERNAL DEBATE with OpenAI Codex (via the Skill tool) yourself. Follow the full Debate protocol below (Round 1 + 1b + 1b' + Round 2/3 + verdict branches 1/2/3/4/5/6/7 with branch 9 N/A).
- **`codex_required: false`** (default — no `--codex` flag): SKIP all `Skill(codex)` invocations. Run a SINGLE-ROUND QA-ONLY ASSESSMENT covering the 4 Workflow Integrity Dimension bullets + 1b cleanliness-of-THIS-diff inspector preconditions. Apply verdict branch 9 (codex disabled by user) — see verdict rules below. Branches 3/6/7 are N/A in this mode.

In both modes, the caller does NOT orchestrate rounds; you own the loop.

Input artifacts (read them first):
- BA spec:     <BA_SPEC path or "none">
- QA report:   <QA_REPORT path or "none">
- Companions:  <context-<ts>.json / dev-report-<ts>.json if present, else omit>

Debate protocol (all runs INSIDE you):

Round 1:
  1a. Form your initial assessment (YES/NO) on whether the dev can close. Consider:
      - Are all acceptance criteria measurably met (evidence, not code review)?
      - Is the root cause addressed and the fix correct & complete?
      - Regression risks? Scope drift? Missed edge cases?

      WORKFLOW INTEGRITY DIMENSION (mandatory — evaluate ALL four bullets explicitly; report a per-bullet PASS / FAIL / N/A-with-reason in the transcript; ANY FAIL forces CLOSE: NO regardless of AC coverage):
        1. **Downstream consumability** — Can the artifacts under evaluation be consumed by downstream commands (`/commit`, `/push`, `/merge`) without manual patching of timestamps, names, or artifact contracts? Concretely: does `dev-report-<task-id>.json` exist with the SAME `<task-id>` as this close cycle? Does `close-report-<task-id>.md` end with `CLOSE: YES`? If a human would have to rename, copy, or hand-edit any artifact to make `/commit` succeed, this bullet is FAIL.
        2. **task-id chain consistency** — Are predecessor artifacts (BA spec → context → dev-report → completion → qa-report → close-report) ALL present under the SAME `<task-id>`? Mismatched task-ids across the chain → FAIL.
        3. **Pre-existing-defect rule** (rewritten per spec-20260503-091826 Section 5.4 rule 1+2 — out-of-scope-by-default UNLESS user-need-impact OR security OR cleanliness-of-THIS-diff) — If a Round-1 critique surfaces a "pre-existing architectural defect" or similar, the debate resolves as follows:
             (a) if THIS cycle's BA spec CLAIMS to address the defect AND the claim maps to user-need / path-dependent shared infrastructure / security / cleanliness-of-THIS-diff → the defect IS in scope and must be evaluated on its merits. If the BA-spec claim does NOT map to one of those four axes (i.e., BA over-expanded into path-external scope), the claim is itself out-of-scope and falls through to (d) — pre-existing-out-of-scope, NOT NO; the AC-deviation / out_of_scope_observations path applies instead.
             (b) if the pre-existing defect actively blocks user-need success in THIS cycle's spec (i.e., the user-stated requirement cannot be satisfied without addressing the defect) → it IS in scope; bullet evaluates on its merits and FAILS only if the defect remains;
             (c) if the pre-existing defect is a security hole (Section 5.4 rule 2: security holes are exceptions — must be fixed even when outside the user-need path) → it IS in scope and must be fixed; bullet FAILS unless addressed;
             (d) otherwise — the pre-existing defect is OUT of scope by default. Bullet PASSES. Recording in `out_of_scope_observations` is the correct disposition; the "pre-existing / out-of-scope" walkback is the default behavior, not a forbidden one. The user's binding directive: if something does not impede user experience, security, or the cleanliness of the repository as a whole, it is not necessarily a reason for NO — pre-existing defects that do not impact user needs / security / cleanliness-of-THIS-diff are NOT NO triggers.
        4. **Self-deployability** — Can the changes be committed and shipped via the project's own commit/push toolchain (`/commit`, `/push`, `/merge`) without out-of-band patching? Evaluate as the AND of these sub-items:
             (i) **/commit consumability** (PASS/FAIL) — `/commit` accepts the cycle's artifacts (dev-report, qa-report, completion) without orchestrator-side jq or Edit patches to fix artifact fields. FAIL if any manual artifact patch was required.
             (ii) **Push permission** (PASS/FAIL) — the orchestrator's git identity has write access to the target remote(s). FAIL if push was blocked by remote permissions or required a human to push from a different identity.
             (iii) **No commit-channel bypass** (PASS/FAIL) — no manual `git commit` outside agent context, no `CLAUDE_PROJECT_DIR` override to bypass repo-rooted hook gates, no `auto-bulk:` pattern abuse to smuggle changes past `pretool-git-privilege-guard.py`. FAIL if any of these bypass channels was used.
             (iv) **User-only physical filesystem actions** (N/A-with-reason — NEVER FAIL) — any sub-item that would require the user to perform a physical filesystem action the orchestrator structurally cannot perform itself is evaluated as N/A-with-reason, NOT FAIL. The canonical example is the user touching `.hook-refactor-allow` to authorize a hook-tree edit: human-in-the-loop is intentional anti-fabrication protection per Trap 11; orchestrator-creatable sentinels would defeat the protection's threat model. The N/A reason MUST cite Trap 11 verbatim. This clause covers ONLY user-only physical filesystem actions; it does NOT cover the bypasses listed in sub-item (iii), which remain FAIL.
           Bullet 4 is PASS when (i), (ii), and (iii) are each PASS (or N/A-with-reason where structurally inapplicable per (iv)). Any FAIL in (i)–(iii) is Bullet 4 FAIL.

  1b. **Cleanliness-of-THIS-diff preconditions — inspector reports as input** (per spec-20260503-091826 Section 5.4 rule 3 + Section 5.2: integrate clean tools such as style-inspector into the close steps). Inspector reports are ALREADY GENERATED by the orchestrator (`/close` Step 4) BEFORE this dispatch. Read them at the following exact paths:
      - `docs/dev/style-inspector-report-<TASK_ID>.json`
      - `docs/dev/cleanliness-inspector-report-<TASK_ID>.json`
      - `docs/dev/prompt-inspector-report-<TASK_ID>.json`
      **DO NOT attempt to dispatch inspector subagents — you do not have that authority; the orchestrator already did Step 4.** Inspector dispatch is `/close`-orchestrator-only by design (`agents/style-inspector.md` etc. are auditors invoked at the orchestrator layer). Treat the JSON contents of the three report files above as input to the AC-2.6 verdict-plumbing rules below. Inspector findings DO NOT directly force the verdict — `close.md`'s verdict-plumbing rules at AC-2.6 govern when a finding becomes a CLOSE: NO trigger. If any of the three report files is missing or unreadable, record the missing-report condition in the close-report transcript and treat the corresponding inspector's findings as empty (advisory) rather than attempting to invoke the inspector yourself.

  1b'. Invoke the Skill tool with skill=codex. Pass codex a prompt that includes:
      - The same input artifact paths
      - Your Round-1 position and rationale
      - Inspector findings from 1b above (so codex can weigh them)
      - Instruction (user-need + THIS-diff cleanliness scoped, per spec-20260503-091826 Section 5.4 rule 3 + 4): "Challenge whether this close grants YES on something that ACTUALLY satisfies the user-stated need (not just the BA AC's mechanical wording). Flag any cleanliness/style violations introduced by THIS diff (not pre-existing). Out-of-path observations and pre-existing technical debt are NOT grounds for CLOSE: NO under this scoping. Reply with exactly one line `CODEX: YES` or `CODEX: NO` followed by 3-8 sentences of rationale. **If CODEX: NO, you MUST also list 2–5 specific actionable items that would flip your verdict to YES — without this list, a NO verdict is incomplete and QA will treat it as an observation, not a blocker.**"
  1c. Parse codexs response. If parsing ambiguous, treat as NO.

  **Inspector-finding → CLOSE: NO verdict plumbing** (AC-2.6 — encodes Section 5.4 rule 3: cleanliness scope = only violations newly introduced in this diff = NO blocking close; pre-existing historical dirt is entirely ignored):

  - **(a) Diff-scoped invocation**: close passes `--changed-files <cycle-diff-changed-files>` (e.g., derived from `git diff --name-only $BASE..HEAD` or token-equivalent cycle-diff source — changed-line metadata for line-level inspectors / file list for file-level inspectors) to all three inspectors at Round-1.
  - **(b) NEW-violation → CLOSE: NO** (only **provably-new** findings; pre-existing/ambiguous/untagged default to **ignore**): an inspector finding forces `CLOSE: NO` with a cleanliness-failure reason ONLY when the finding is explicitly proven NEW (introduced by THIS cycle's diff). Findings that are pre-existing, untagged, ambiguous, or from non-diff-aware inspector runs default to **ignore** (cannot force CLOSE: NO):
    - **Line-level inspectors** (e.g., `style-inspector` emitting `file:line`): a finding is provably NEW when **(i) its line falls within the cycle diff's changed-line range / diff-hunk overlap for that file AND (ii) the finding is also absent from the pre-diff baseline of the same file** (the violation did not exist on the corresponding pre-diff line content). Overlap alone is **necessary but NOT sufficient** — a pre-existing violation preserved on a modified line is still pre-existing. Soft fallback when pre-diff baseline comparison is impractical: dev/inspector documents the proxy used (e.g., "overlap-only used because <reason>") and close treats overlap-only findings as **advisory** unless the proxy explicitly stipulates newness.
    - **File-level inspectors** (`cleanliness-inspector`, `prompt-inspector` — granularity = `file`, not `file:line`): the inspector's output MUST distinguish NEW vs pre-existing. Two acceptable mechanisms (dev's discretion; **may be implemented individually OR combined**):
      - **(i) Inspector-side filtering**: the inspector itself emits findings only for NEW violations (e.g., comparing its analysis against a pre-diff baseline of the same file, or analyzing diff hunks directly). Findings emitted under mechanism (i) in `--changed-files` mode count as NEW **only when the inspector's documentation explicitly declares the filtering contract** (per AC-12.1 documentation requirement); absent that explicit contract, untagged file-level findings fall under the default-safe ignore rule below.
      - **(ii) Inspector-side tagging**: the inspector emits findings for the listed files but tags each with an explicit `introduced_in_diff: bool` field (or token-equivalent positive marker like `is_new: true|false`). close honors that tag.
    - **Default-safe rule for ambiguity** (covers tag absence, null, unknown, missing field, untagged output): close.md verdict logic requires an **explicit positive marker** (`introduced_in_diff: true` or token-equivalent positive value) to force CLOSE: NO on a file-level finding. Findings where the marker is `false`, absent, null, unknown, or where the inspector emitted output without a marker at all, MUST default to **ignore** — they CANNOT force CLOSE: NO. `absent/unknown -> ignore` is the encoded default. Section 5.4 rule 3 requires explicit proof of newness, not absence of evidence.
    - **Default-safe rule for non-diff-aware mode** (covers no `--changed-files` arg / default full-repo run): file-level inspector findings produced in default/full-repo/non-diff-aware mode are **advisory and non-blocking** for cleanliness CLOSE: NO unless they carry an explicit positive new-in-this-diff marker per the rule above. Full-repo finding does not force CLOSE: NO. close.md's full-repo inspector runs (e.g., for orientation or audit) MUST NOT escalate to CLOSE: NO on file-level findings absent that marker.
    - close.md verdict logic honors whichever mechanism the inspector chose (or the combination thereof): if (i) with explicit-contract documentation, close treats every finding emitted in `--changed-files` mode as NEW; if (ii), close reads the explicit positive marker and applies the default-safe rule above.
  - **(c) Pre-existing-NOT → CLOSE: NO**: inspector findings whose `file:line` is **not in this diff**, OR whose file-level marker is `introduced_in_diff: false` / absent / null / untagged, OR which originate from a non-diff-aware full-repo run, MUST NOT cause `CLOSE: NO`. `pre-existing finding ignored`. `pre-existing technical debt` and historical dirt are out-of-scope for cleanliness verdict per Section 5.4 rule 3.

  **Worked example** (the three required paths α/β/γ are walked through; verdict outputs use the existing `CLOSE: NO - <reason>` format from Step 5 final-line contract):

  - Suppose `style-inspector --changed-files` returns a finding at `path/to/component.tsx:42` (line-level), and `cleanliness-inspector --changed-files` returns a file-level finding at `path/to/util.ts` with `introduced_in_diff: true`.
  - Close evaluates each finding against the cycle diff (changed-line metadata / diff hunk ranges for line-level inspectors; honors the file-level inspector's NEW vs pre-existing marker for file-level inspectors).
  - **diff-NEW finding (line-level)**: line 42 is within the diff's changed-line range AND was absent from the pre-diff baseline of `component.tsx` → `CLOSE: NO - new style violation introduced at component.tsx:42`.
  - **diff-NEW finding (file-level)**: `cleanliness-inspector` returned `introduced_in_diff: true` for `util.ts` under explicit-contract mechanism (i) or tagging mechanism (ii) → `CLOSE: NO - new cleanliness violation in util.ts`.
  - **(α) pre-existing finding in a changed file → ignore**: `style-inspector` returns a finding at `path/to/component.tsx:7` where line 7 IS within the diff's changed-line range BUT the pre-diff baseline of `component.tsx` already contained the same violation on the corresponding pre-diff line — overlap is necessary but not sufficient, and the pre-diff baseline shows the violation pre-existed. Outcome: ignore, do not block close. Continue evaluating other findings.
  - **(β) untagged / ambiguous finding → ignore**: `cleanliness-inspector` emits a file-level finding for `path/to/legacy.ts` with NO `introduced_in_diff` field, NO token-equivalent positive marker, and the inspector documentation does not declare an explicit-contract filtering claim — under the Default-safe rule for ambiguity, `absent/unknown -> ignore`; this `untagged finding ignored`. Outcome: do NOT force CLOSE: NO. Continue evaluating other findings.
  - **(γ) non-diff-aware mode finding → advisory / non-blocking**: `prompt-inspector` was invoked in default full-repo mode (no `--changed-files` argument) for an orientation pass; it returns a file-level finding for `path/to/agent.md`. Under the Default-safe rule for non-diff-aware mode, this is `advisory` / `non-blocking` for cleanliness CLOSE: NO. Outcome: record the finding, do NOT force CLOSE: NO; downstream cycles may address it through the `out_of_scope_observations` ledger if desired.

Round 2 (skip if Round 1 ended with both QA=YES and CODEX=YES):
  2a. Re-assess your position after reading codexs Round-1 challenge. If you still say YES, strengthen justification; if codex surfaced a real issue, update to NO.
  2b. Invoke Skill(codex) again with your updated position + codexs prior challenge + artifact paths. Ask codex to either confirm or press further, replying again with `CODEX: YES` / `CODEX: NO` + rationale.

Round 3 (skip if earlier unanimous YES):
  3a. Final reassessment.
  3b. Final Skill(codex) call with full history.

Verdict rule (UNANIMOUS CONSENT, with infrastructure-failure escape valve):

Track a single field about the codex consultation across all rounds:
  `codex_status`: `ok` | `failed_quota` | `failed_timeout` | `failed_parse`

- `ok` — at least one round received a parseable `CODEX: YES` or `CODEX: NO`.
- `failed_quota` — every round attempted hit a usage-limit / quota error.
- `failed_timeout` — every round attempted hung past the round's deadline.
- `failed_parse` — every round attempted returned content that could not be parsed into `CODEX: YES` / `CODEX: NO`. Unlike `failed_quota` / `failed_timeout`, the round produced output -- it just did not match the required format. QA MUST preserve the verbatim raw output and perform a manual dissent scan before branch 7 can grant CLOSE: YES (FINDING-4).

Verdict branches:

1. **Unanimous YES (normal happy path)**: QA position = YES AND codex position = YES (codex_status = ok) AND all four Workflow Integrity Dimension bullets PASS (or N/A-with-reason; never FAIL) → **CLOSE: YES**.

2. **AC-deviation-PASS branch** (per spec-20260503-091826 Section 5.4 rule 4: dev deviating from BA spec AC but empirically satisfying user requirement = PASS, provided dev report explicitly records the AC deviation reason). When QA's verdict is YES on user-need verification (i.e., `verified_against_complaint = true` AND `passed_user_requirement = true` per agents/qa.md report contract) but dev's diff deviated from one or more BA AC literal-wording → **CLOSE: YES** is allowed iff ALL of the following hold (necessary AND sufficient — codex-refined; citation alone is necessary but NOT sufficient):
    - **(a)** Dev report explicitly identifies the deviated AC by ID (e.g., `AC-3.1`, `AC-12.1`) — `ac_deviation_with_user_need_satisfied: true` is present in the dev report and the deviated AC IDs are listed.
    - **(b)** Dev report cites the verbatim user-need text from the BA spec that the implementation actually satisfies (the deviation is from AC mechanics, not from user need; the verbatim user-need text is reproduced).
    - **(c)** Dev report provides evidence (test result / measurement / observation) that the implemented behavior satisfies that need. Hand-wave reasoning is rejected.
    - **(d)** **QA SHALL reject this branch if the deviated AC directly encodes user-need / security / THIS-diff-cleanliness — for those, AC-deviation is plain AC-FAIL, NOT AC-deviation-PASS.** This prevents the branch becoming a downgrade vector. If the deviated AC's text encodes the user-need test itself, or a security check, or a cleanliness-of-THIS-diff check, deviation collapses back to AC-FAIL and the verdict follows branch 5 (QA dissent → CLOSE: NO).
    - When (a)–(c) hold and (d) does not trigger, the verdict is **CLOSE: YES** and the close-report records the deviation rationale verbatim.

3. **Substantive Codex dissent**: codex_status = ok AND any round ended with `CODEX: NO` AND the disagreement was not resolved by a later round → **CLOSE: NO**, with the dissent line citing codex's substantive objection. This branch is unchanged: a working codex saying NO still forces NO.

4. **Workflow Integrity FAIL**: any of the four bullets evaluates to FAIL (not N/A-with-reason) → **CLOSE: NO** regardless of QA / codex positions, with the failing bullet named in the dissent line. Unchanged.

5. **QA dissent**: QA position = NO at end of final round → **CLOSE: NO**, with QA's substantive objection in the dissent line. Unchanged.

6. **Codex infrastructure failure (BUG-CLOSE-2 escape valve)**: codex_status ∈ {`failed_quota`, `failed_timeout`} AND QA position = YES AND all four Workflow Integrity Dimension bullets PASS → **CLOSE: YES (degraded codex consultation)**. The verdict is granted on QA's substantive YES alone because codex never produced a substantive opinion to disagree with. Document the codex_status value verbatim in the close-report transcript under a new "Degraded codex consultation" section. The dissent line is replaced by an annotation: `degraded codex consultation: codex_status=<value>, codex contributed no substantive position`. This branch ONLY applies when the failure mode is unambiguous mechanical / infrastructural transport failure (the request never produced any output at all); a successful CODEX: NO still falls under branch 3. `failed_quota` and `failed_timeout` are unambiguous (the round produced no body to inspect). `failed_parse` is NOT in this branch -- see branch 7.

7. **Codex parse failure (FINDING-4 hardening for `failed_parse`)**: codex_status = `failed_parse` AND QA position = YES AND all four Workflow Integrity Dimension bullets PASS → conditional **CLOSE: YES (degraded codex consultation)**, BUT ONLY when QA also attests in the close-report:
    - **(a)** the verbatim raw codex output text from each `failed_parse` round is recorded in the "Degraded codex consultation" section;
    - **(b)** QA performed a manual scan of that verbatim output for substantive dissent signals -- including but not limited to: `CODEX: NO`, `Codex: NO`, the literal substring `NO`, the words `bug`, `defect`, `regression`, `wrong`, `incorrect`, `must not`, `should not`, `does not work`, `fails`, `broken`, or any prose explicitly objecting to the proposed close;
    - **(c)** QA explicitly states the determination: `manual parse: NO substantive dissent signal found in failed_parse output` (verbatim wording required).

    `failed_parse` differs from `failed_quota`/`failed_timeout` because the request DID complete and the codex CLI DID emit content -- the parser merely could not map it to the `CODEX: YES` / `CODEX: NO` format. Skipping the manual scan would create a downgrade vector: a substantive `NO` could ride a malformed response into a YES verdict. If the manual parse finds ANY dissent signal, this branch fails over to **CLOSE: NO** (treat as substantive Codex dissent under branch 3 with the verbatim signal as the dissent line). If QA omits the verbatim attestation, fail over to branch 8 (conservative NO).

8. **Other ambiguity / parse failure on QA's side / unresolved disagreement after final round**: → **CLOSE: NO** (conservative default). Distinct from branch 6: the failure is on QA's reasoning side, not codex's transport.

9. **Codex disabled by user (no `--codex` flag)** — `codex_required = false` from Step 1 → QA runs **single-round QA-only assessment** of the 4 Workflow Integrity bullets + 1b cleanliness preconditions; no `Skill(codex)` invocations attempted; `codex_status` is set to the literal sentinel `disabled_by_user`. Verdict logic collapses to:
   - QA position = YES AND all four Workflow Integrity bullets PASS (or N/A-with-reason; never FAIL) AND no NEW-violation cleanliness inspector finding → **CLOSE: YES** (annotation: `codex_disabled_by_user: codex consultation skipped because --codex flag was not passed; verdict granted on QA's substantive YES + 4 bullets PASS alone`).
   - QA position = NO at end of single round → **CLOSE: NO** (branch 5 reasoning applies; QA's substantive objection is the dissent line).
   - Any of the four bullets FAIL → **CLOSE: NO** (branch 4 reasoning applies; the failing bullet name is the dissent line).
   - AC-deviation-PASS branch 2 is fully applicable in the codex-disabled path — when QA verdict is YES on user-need verification AND dev report contains a valid `ac_deviation_with_user_need_satisfied: true` block satisfying clauses (a)–(d) of branch 2, **CLOSE: YES** is granted with the deviation rationale recorded.
   - Branches 3 / 6 / 7 / 8 are all N/A in the codex-disabled path (codex was never invoked; there is no codex dissent to weigh, no infrastructure failure to handle, no parse failure to scan).
   - The close-report MUST record `codex_status: disabled_by_user` in the "Codex consultation" section (NOT `failed_*`), and the per-round entries record `[Codex] consultation skipped: --codex flag not passed; QA-only assessment performed`. The final verdict line MUST use the form `CLOSE: YES — codex disabled by user` (when YES) or the standard `CLOSE: NO — <reason>` (when NO); the em-dash form distinguishes branch 9 YES from branch 1 unanimous YES for downstream `/commit` consumers.

The /close --force escape hatch (Step 2) is unchanged. It bypasses Step 5 entirely; none of the verdict branches above run on the forced path.

Transcript file: write the full debate to `docs/dev/close-report-<task-id>.md` (substitute `<task-id>` with the value resolved in Step 3 — e.g. the source `/dev` cycle's task-id; do NOT use a fresh `date +%Y%m%d-%H%M%S` here, that would break /commit's PRIMARY-path lookup) with this structure:
  # Close Debate Report
  Task-id, Input files, Rounds run, Verdict.
  Workflow Integrity Dimension: explicit per-bullet status (1. Downstream consumability: PASS/FAIL/N/A; 2. task-id chain consistency: PASS/FAIL/N/A; 3. Pre-existing-defect rule: PASS/FAIL/N/A; 4. Self-deployability: PASS/FAIL/N/A) — with one-sentence reason for each FAIL or N/A.
  Codex consultation: explicit `codex_status` value (`ok` | `failed_quota` | `failed_timeout` | `failed_parse`). When the value is one of the failure modes, include a "Degraded codex consultation" section that records: which rounds failed, the verbatim error / timeout / parse-issue from each attempt, and the explicit acknowledgement that the verdict was granted on QA's substantive YES alone (per Verdict rule branch 6). For `failed_parse` specifically (FINDING-4), the section MUST additionally include: (i) the verbatim raw codex output text from EACH failed_parse round, (ii) QA's explicit per-round manual scan note, and (iii) the verbatim attestation `manual parse: NO substantive dissent signal found in failed_parse output`. Without all three, branch 7 is not satisfied and the verdict falls to branch 8 (CLOSE: NO).
  For each round: [QA] position + rationale; [Codex] position + rationale (or "consultation failed: <reason>" when codex_status was failed-* in that round).
  At bottom: the LAST non-empty line of the file MUST be EXACTLY one of the legal CLOSE: forms listed in the Return value section below (e.g., a bare line `CLOSE: YES` or `CLOSE: NO - <reason>`). Do NOT prefix it with `Final verdict:`, `Verdict:`, or any other label — the runtime parser (`hooks/lib/close-verdict.py`) reads the last non-empty line and requires it to start literally with `CLOSE: `; any prefix breaks `/commit`'s admission check.

Overwrite policy: if `docs/dev/close-report-<task-id>.md` already exists with a `CLOSE:` line in it (a prior closure attempt for the same task-id), do NOT silently overwrite — append a fresh debate as a new section dated by ISO timestamp, OR (if your tooling cannot append cleanly) treat the prior closure as authoritative and do not re-close.

Return value: print to stdout exactly ONE of these lines as the final line of your response. Runtime consumers classify the last non-empty `CLOSE:` line through the shared close-verdict helper: `YES`, `YES` with a suffix (including degraded consultation or codex-disabled annotations), and `YES (FORCED)` map to `yes`; `NO` with or without a reason maps to `no`; anything else maps to `unknown` and fails closed.
  CLOSE: YES
  CLOSE: YES - degraded codex consultation: codex_status=<failed_quota|failed_timeout|failed_parse>
  CLOSE: YES — codex disabled by user
  CLOSE: YES (FORCED)
  CLOSE: NO - <one-sentence reason naming the dissenting party and their objection>
```

### Step 3: Generate close-report + workflow update

Take the final line QA returned (`CLOSE: YES` or `CLOSE: NO - ...`) and echo it as the verdict line in the orchestrator's text message to the user. The close-report itself is written by QA inside Step 2; this step is the verdict echo + ensures the report file exists at `docs/dev/close-report-<task-id>.md`.

**Two distinct final-line contracts — DO NOT confuse**:
- **Close-report FILE** (`docs/dev/close-report-<task-id>.md`): the LAST non-empty line of the FILE must be EXACTLY one of the legal `CLOSE:` forms listed in Step 2's Return value section. This is the runtime-parser contract consumed by `hooks/lib/close-verdict.py` and `/commit`'s admission check. This contract is enforced INSIDE the file QA wrote in Step 2; nothing in Step 3 alters it.
- **Orchestrator's stdout text message to the user**: the orchestrator's response stream in Step 3 begins with the `CLOSE:` verdict echo, continues with the Session Summary (CLOSE:YES branch only — see below), and ends with the rating `<options>` XML block (CLOSE:YES branch only — see below). On the CLOSE:NO and CLOSE:YES (FORCED) paths there is no Session Summary and no `<options>` block, so the verdict echo is itself the last line of the orchestrator's message. The `<options>` block being the literal final stdout content on CLOSE:YES does NOT violate the close-report FILE contract — they are two different output channels.

**Mascot scoring — close outcome (spec-20260518-225715 §5.1; M4 — task 20260529-210616)**:

Scoring runs ONLY AFTER the close-report file is written (Step 2 wrote it) AND AFTER the verdict line is echoed. The decision of WHICH `close_success_*` event to issue (if any) is delegated to the executable helper `scripts/close-scoring-decide.py` — NOT inline orchestrator reasoning. This ordering prevents the premature-scoring bug seen in task 20260529-081014, where `close_success_qa_fail_fixed` was issued before QA finalized its verdict.

Procedure:

1. Determine `qa_ever_rejected` from `docs/dev/qa-report-<task-id>.json` history (true if any iteration was rejected).
2. Invoke the helper to decide which close_success_* event (if any) is permitted:

   ```
   bash -c 'source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/close-scoring-decide.py --task-id "<task-id>" --qa-ever-rejected "<true|false>"'
   ```

   The helper reads the close-report at `docs/dev/close-report-<task-id>.md`, classifies its last non-empty line via `hooks/lib/close-verdict.py`, and emits stdout JSON `{"events": [...], "skip_reason": "<string|null>"}`:
   - missing close-report → `events=[]`, `skip_reason` contains "missing"
   - last-line `CLOSE: NO` → `events=[]`, `skip_reason` non-null
   - last-line `CLOSE: YES (FORCED)` → `events=[]`, `skip_reason` contains "FORCED"
   - last-line `CLOSE: YES` + qa_ever_rejected=false → `events=["close_success_qa_pass"]`, `skip_reason=null`
   - last-line `CLOSE: YES` + qa_ever_rejected=true → `events=["close_success_qa_fail_fixed"]`, `skip_reason=null`

3. The orchestrator MUST ONLY issue the events returned by the helper. If `events[]` is empty, log `skip_reason` and SKIP all `close_success_*` score updates. Tests MUST invoke `scripts/close-scoring-decide.py` directly against fixtures; tests MUST NOT reimplement the decision logic in a parallel test harness.

4. For each event name returned by the helper, issue three `score-update.sh` calls (ba, dev, qa). Example for the qa_pass branch:

   ```
   bash ~/.claude/scripts/score-update.sh --agent dev --event close_success_qa_pass --note "<task-id>"
   bash ~/.claude/scripts/score-update.sh --agent ba  --event close_success_qa_pass --note "<task-id>"
   bash ~/.claude/scripts/score-update.sh --agent qa  --event close_success_qa_pass --note "<task-id>"
   ```

   (dev +2, ba +1, qa +1 — Path A rebalance task 20260524-205206 M1; cycle-total cross-agent sum = +4.)

   For the qa_fail_fixed branch the event name is `close_success_qa_fail_fixed` (same deltas).

5. `close_fail_*` branches are NOT routed through the helper — the orchestrator issues them directly when the verdict is `CLOSE: NO`:
   - `CLOSE: NO` AND QA had passed (PM/inspector or codex caught issue post-QA) → `score-update.sh --event close_fail_qa_pass` for ba/dev/qa. (dev -10, ba -5, qa -12.)
   - `CLOSE: NO` AND QA had failed (rejection upstream) → `score-update.sh --event close_fail_qa_fail` for ba/dev/qa. (dev -10, ba -5, qa 0.)

6. `CLOSE: YES (FORCED)` (the `--force` short-circuit path) → SKIP close-event score updates entirely; --force bypasses scoring just as it bypasses QA debate. The helper enforces this by returning `events=[]` for FORCED lines, so even if the orchestrator forgets, the script-side gate (`scripts/score-update.sh` M3 precondition) and the helper-side gate are defense-in-depth.

Defense-in-depth: `scripts/score-update.sh` itself enforces the same precondition (M3 — task 20260529-210616). Any `close_success_*` call without a legal `CLOSE: YES` last-line in `docs/dev/close-report-<note>.md` exits 5 ("precondition unmet"), so even if the orchestrator skips the helper or the helper is bypassed, the lifecycle log cannot be polluted with premature success entries.

**Session Summary — CLOSE:YES branch only (mandatory before rating)**:

- If the verdict is **`CLOSE: YES`** (non-forced YES forms) AND `--force` was NOT passed in `$ARGUMENTS`:
  - The orchestrator MUST produce a `## Session Summary` section in its text output to the user.
  - Format: chronological order, 6 buckets, each entry CONCISE (1–2 sentences max per bullet):
    - **Accomplished**: what was done this session
    - **Not accomplished**: gaps, deferred items, out-of-scope decisions
    - **User needs satisfied**: which stated user requirements were met
    - **User needs not satisfied**: which stated user requirements remain unmet
    - **Bugs encountered**: bugs surfaced during the session (if none, omit or write "none")
    - **Improvement opportunities**: technical debt, UX gaps, or follow-up items worth noting
  - **Conciseness rule**: each bullet MUST be exactly 1 sentence. Narrative paragraphs are FORBIDDEN. The entire summary MUST fit within 20 lines including the heading. Exception: if the bullet contains a verbatim user quote, reproduce it exactly as stated (no paraphrase, no truncation), then the quote itself counts as the sentence.
  - **Source binding**: read `docs/dev/dev-report-<task-id>.json`, `docs/dev/qa-report-<task-id>.json`, `docs/dev/user-requirement-<DEV_SESSION_ID>.md`, and `docs/dev/close-report-<task-id>.md`. Do NOT improvise outcomes not present in these artifacts. `docs/dev/user-requirement-<DEV_SESSION_ID>.md` is the primary source for "User needs satisfied" and "User needs not satisfied" bullets.
  - This summary appears in the orchestrator's text message to the user, AFTER the `CLOSE:` verdict echo and BEFORE the rating `<options>` block below.
- If the verdict is **`CLOSE: NO`** or **`CLOSE: YES (FORCED)`**: SKIP the session summary.

**User rating prompt — CLOSE:YES branch only (spec-20260518-225715 §5.1 line 136 verbatim: "Only fires after CLOSE:YES; CLOSE:NO does NOT prompt." (translated from spec))**:

- If the verdict is **`CLOSE: YES`** (the non-forced YES forms — `YES`, `YES - degraded ...`, `YES — codex disabled ...`) AND `--force` was NOT passed in `$ARGUMENTS`:
  - Output the following `<options>` XML block at the VERY END of the orchestrator's text message to the user (after the verdict echo and session summary above). This block is in the orchestrator's text output only — NOT in the close-report file, which retains its `CLOSE:` final-line contract:

    ```
    <options>
        <option>5 stars -- Excellent</option>
        <option>4 stars -- Good</option>
        <option>3 stars -- Average</option>
        <option>2 stars -- Below average</option>
        <option>1 star -- Poor</option>
        <option>Skip rating</option>
    </options>
    ```

  - **Post-option handling contract**: the task-id MUST be retained in the orchestrator's context across the user's response. Parse the selected option text to extract the star count: "5 stars" → N=5, "4 stars" → N=4, etc. When N ∈ {1,2,3,4,5}, the orchestrator runs three `score-update.sh` calls:
    - `bash ~/.claude/scripts/score-update.sh --agent ba --event user_rating_<N> --note "<task-id>"`
    - `bash ~/.claude/scripts/score-update.sh --agent dev --event user_rating_<N> --note "<task-id>"`
    - `bash ~/.claude/scripts/score-update.sh --agent qa --event user_rating_<N> --note "<task-id>"`
  - When the user selects "Skip rating": NO score-update calls are made. (Skip does NOT produce a separate event — spec 5.1.)
- If the verdict is **`CLOSE: NO`** in ANY form: SKIP the rating entirely. Per spec 5.1 line 136 verbatim, the rating prompt fires only after CLOSE:YES, NOT after CLOSE:NO.
- If the verdict is **`CLOSE: YES (FORCED)`** (`--force` was passed): SKIP the rating entirely. The --force short-circuit at Step 2 line 54 means no QA debate occurred, so no user rating is collected and no score is updated.

Then branch the workflow update:

- If the final verdict is `CLOSE: YES*`, create a compact temp update using
  `/spec-update --temp`. The update is for the next `/commit` attempt and MUST
  reference, not duplicate: `docs/dev/close-report-<task-id>.md`,
  `docs/dev/dev-report-<task-id>.json`, `docs/dev/qa-report-<task-id>.json`,
  and the three inspector report paths from Step 1. Next action: `/commit
  <task-id> -m "<real session summary>"`.
- If the final verdict is `CLOSE: NO`, create or update a continuation spec
  using `/spec-update` default continuation-spec mode. If the dev context has a
  source spec, append the close dissent and unresolved gaps to that spec;
  otherwise create a new spec. Next action: `/dev --spec <spec_path>`. Do NOT
  direct a failed close to `/commit`.

## Constraints

- /close does NOT call Skill(codex). QA does, internally.
- /close does NOT manage rounds. QA does, internally.
- /close does NOT evaluate verdict. QA does, internally.
- QA is invoked EXACTLY ONCE (non-force path) or ZERO times (forced path).
- **Scoped default-NO** (per spec-20260503-091826 Section 5.1: if something does not impede user experience, security, or the overall cleanliness of the repository, it is not necessarily a reason for NO): Default to CLOSE: NO when error / ambiguity / tool-unavailability **blocks evaluation of user-need satisfaction OR security OR cleanliness-of-THIS-diff**. Errors / ambiguity / tool-unavailability that do NOT impede those three evaluation axes are NOT automatic NO triggers. Codex-refined: "Unknown but relevant" still defaults to NO — when the error blocks the evaluation itself (i.e., we cannot determine whether the user need is satisfied), default remains NO. Recoverable transient infrastructure failures (e.g., Codex quota / timeout) follow the existing branch-6/7 graceful-degradation logic — this clause does NOT override branches 6/7. EXCEPT when `--force` is explicitly passed by a human user, in which case CLOSE: YES (FORCED) is the result regardless of upstream artifact state (Forced-override path short-circuit).
- `disable-model-invocation: true` (frontmatter) means the model cannot self-invoke /close via SlashCommand — this applies equally to the forced path. Only a human can trigger `--force`.
