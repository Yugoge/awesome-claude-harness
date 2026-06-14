---
description: Orchestrated development workflow with BA subagent delegation, parallel agent execution, and iterative QA verification. Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
argument-hint: "[--codex] [--spec <path>] <requirement>"
disable-model-invocation: true
---

> Code-writing tasks (.svg/.css/.html/.js/.ts/.py/...) go to `dev`. Specialists, BA, and QA produce .md/.json only.

**CRITICAL**: Use TodoWrite to track workflow phases. Mark in_progress before each step, completed immediately after.

# Development Orchestrator

**Philosophy**: Understand requirement fully → Find root cause → Delegate implementation → Verify quality → Iterate until perfect

This command uses multi-round inquiry to fully understand requirements, then orchestrates development through specialized subagents with continuous QA verification.

---

## Core Workflow

**BA-Delegated Orchestration Pattern**:
```
User Requirement (may be vague)
  ↓
Quick parse of $ARGUMENTS
  ↓
Delegate to BA subagent (analysis + context building)
  ↓
BA clarification loop (if BA needs user input, max 3 rounds)
  ↓
Validate BA output (ba-spec + context JSON)
  ↓
QA validates BA conclusions (analysis quality check)
  ↓
Delegate to dev subagent (implementation)
  ↓
Delegate to QA subagent (verification)
  ↓
IF QA fails → Refine context → Iterate
  ↓
IF QA passes → Generate completion report
  ↓
Emit spec continuation or temp closure update
```

**Key Principles**:
- Orchestrator does NO analysis or context building (BA handles it)
- Orchestrator does NO implementation work (dev handles it)
- All requirement clarification routed through BA subagent
- BA returns dual output: Markdown spec + JSON context
- Orchestrator only relays BA's clarification questions to user
- Rich JSON context stored in `docs/dev/`
- QA verification after each dev cycle
- Iterate until all quality standards met
- Unfinished work is handed off into a continuation spec; only complete work
  heading to `/close` uses a compact temp update.

**Orchestrator Dispatch Model**:
- N independent tasks → dispatch N subagents **in parallel**, one per task — this is the standard multi-task path
- 1 task → 1 subagent (sequential is only correct when there is genuinely one task)
- NEVER bundle multiple issues into a single subagent prompt
- If QA fails and iteration is needed, re-invoke Dev with the SAME single issue, not a batch

**Per-Subagent Single-Task Rule (MANDATORY)**:
- Each individual subagent invocation handles exactly ONE issue/task
- BA analyzes ONE requirement, Dev implements ONE fix, QA verifies ONE fix
- Multitasking within a single subagent is forbidden regardless of how many subagents are running

---

## Implementation

### Step 1: Parse Development Requirement

Extract requirement from `$ARGUMENTS`:

```
Requirement: "$ARGUMENTS"
```

**Parse `--codex`**: If `$ARGUMENTS` contains the literal token `--codex` (in any position), strip it from the requirement text and set `codex_required = true`. Otherwise set `codex_required = false` (default). When `codex_required = true`, every BA / QA / dev dispatch prompt below MUST include the literal line `codex_required: true` so the subagent's opt-in codex consultation block (`agents/<role>.md` § Codex adversarial consultation) activates. When `codex_required = false`, do NOT include that line — subagents skip codex consultation and emit `codex_consult: { invoked: false, status: "not_requested" }` in their output.

**Codex suppression guardrail**: When `codex_required: true` is included in any subagent dispatch prompt, the orchestrator MUST NOT include any pre-populated `codex_consult` field or object in that same prompt. `codex_consult` is output authored by the subagent — not by the orchestrator. In particular, do not include `codex_consult: { invoked: false, status: "not_requested" }` or any other suppression shape. Setting `codex_required: true` and simultaneously pre-answering `codex_consult` contradicts the flag and silently suppresses Codex consultation. Set the flag and let the agent's own spec decide whether to invoke Codex.

**Parse `--spec`**: If `$ARGUMENTS` contains `--spec <path>`, extract the path and remove the flag from the requirement text. Store as `spec_path`.

**Auto-detect spec**: If `--spec` is NOT provided, scan `docs/dev/specs/*.md` sorted by modification time (newest first). If a file exists, set `spec_path` to that path and announce:
```
Auto-detected spec: <path>
(Created by /spec — pass --spec <other-path> to override.)
```

If no spec found, set `spec_path = null`. All downstream behavior is unchanged when `spec_path` is null.

**Detect views folder (via the centralized resolver — do NOT re-derive paths inline)**:

The producer (`/spec`) and consumers (`/dev*`) historically disagreed on whether the spec-id keeps the `spec-` filename prefix (new split artifacts land DE-prefixed at `docs/dev/specs/<ts>/`; old ones are prefixed). NEVER derive `views_dir` / `split_marker` / `SPEC_ID` from `spec_path` by hand — that drift is exactly what silently dropped de-prefixed specs to monolith mode. Always call the single canonical resolver and consume its stdout JSON:

```bash
if [ -n "$spec_path" ]; then
  RESOLVED_JSON=$(/root/.claude/scripts/resolve-spec-artifacts.py \
      --spec-path "$spec_path" --project-dir "$CLAUDE_PROJECT_DIR") || {
    echo "spec-artifact resolution FAILED (path mismatch / present-but-invalid split). Re-finalize /spec before relying on per-agent views." >&2
    exit 1; }   # loud-fail guard: a present-but-invalid split never silently degrades to monolith mode
  ARTIFACT_ID=$(jq -r .artifact_id      <<<"$RESOLVED_JSON")
  VIEWS_AVAILABLE=$(jq -r .views_available <<<"$RESOLVED_JSON")
  MANIFEST_PATH=$(jq -r '.manifest_path // empty' <<<"$RESOLVED_JSON")
  SPLIT_MARKER=$(jq -r '.split_marker // empty'  <<<"$RESOLVED_JSON")
  VIEWS_DIR=$(jq -r '.views_dir // empty'        <<<"$RESOLVED_JSON")
  CP_DIR=$(jq -r '.cp_dir // empty'              <<<"$RESOLVED_JSON")
fi
```

The resolver returns `views_available=true` only when the split is PRESENT-AND-VALID (manifest valid JSON, `schema_version==1`, `manifest.monolith_path` resolves to THIS monolith, `.split-complete` present and not content-stale, all referenced view files present). It exits **non-zero** on a present-but-invalid / mismatched / ambiguous / stale split (loud fail), and returns `views_available=false` with **exit 0** on a genuinely legacy spec with no split artifacts.

When `VIEWS_AVAILABLE` is `true`, read `view_paths` from `$MANIFEST_PATH` (its `views` map of agent → path). **Legacy specs without a views folder are fully supported** — the resolver reports `views_available=false` (exit 0) and all subagents receive the monolith `spec_path` as before. No error, no checkpoint enforcement.

Pass `view_paths.ba`, `view_paths.qa`, `view_paths.dev`, etc. alongside (not in place of) `spec_path` when delegating to subagents. Each subagent gets its own view path so its context window is smaller.

**Edge cases**:
- Empty `$ARGUMENTS` → Prompt user for requirement
- Otherwise → Pass raw text (minus --spec flag) to BA subagent in Step 4

**Keep this step lightweight** - BA subagent handles all analysis.

**Initialize dev-registry (hook pre-done)**:

The `UserPromptSubmit` hook has already:
1. Generated `DEV_SESSION_ID` (shown in hook output above as `DEV_SESSION_ID pre-initialized by hook: …`)
2. Created `.claude/dev-registry/<DEV_SESSION_ID>/` with per-agent sentinel files for all 16 agent types
3. Written `docs/dev/user-requirement-<DEV_SESSION_ID>.md` with the verbatim user requirement
4. Run `write-e2e-enforce.sh` — E2E enforcement is ACTIVE
5. Run `write-codex-enforce.sh` (if `--codex` was passed) — Codex enforcement ACTIVE or inactive per hook output

**Read `DEV_SESSION_ID` from the hook output above** (line `DEV_SESSION_ID pre-initialized by hook: …`). Store it for use in every Agent launch prompt below.

**Fallback** (if hook output is absent — e.g., session resumed without re-running the command): run the initialization manually:

```bash
DEV_SESSION_ID="dev-$(date +%Y%m%d-%H%M%S)"
REGISTRY_DIR="$CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID"
mkdir -p "$REGISTRY_DIR"
for agent in \
    architect ba cleaner cleanliness-inspector dev git-edge-case-analyst \
    pm product-owner prompt-inspector qa rule-inspector style-inspector \
    test-executor test-validator test-writer ui-specialist user; do
  printf '{"agent_type": "%s", "session_id": "%s"}\n' "$agent" "$DEV_SESSION_ID" \
    > "$REGISTRY_DIR/$agent.json"
done
mkdir -p "$CLAUDE_PROJECT_DIR/docs/dev"
REQUIREMENT_DOC="$CLAUDE_PROJECT_DIR/docs/dev/user-requirement-${DEV_SESSION_ID}.md"
cat <<'REQEOF' > "$REQUIREMENT_DOC"
<verbatim stripped $ARGUMENTS text — paste literal requirement here>
REQEOF
scripts/write-e2e-enforce.sh --source-command dev --session-id $DEV_SESSION_ID
# Only when --codex:
# scripts/write-codex-enforce.sh --source-command dev --session-id $DEV_SESSION_ID
```

Store `$DEV_SESSION_ID` for use in every Agent launch prompt below. Every Agent launch prompt MUST begin with a `FIRST ACTION` line instructing the subagent to `Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/<agent>.json` before any other tool call. Without that Read, the enforcement hook will fail open for that subagent.

**Also reuse the resolver's `<SPEC_ID>` for cp-state checkpoint propagation.** `/spec` writes per-agent `cp-state-<agent>.json` files into the directory the resolver reports as `cp_dir` (`.claude/specs/<artifact_id>/`). Do NOT re-derive the id from `spec_path` — reuse the resolver output computed above so the producer and consumers agree byte-for-byte:

```bash
# SPEC_ID / cp-state dir come straight from the resolver JSON (no inline basename derivation).
if [ -n "$spec_path" ]; then
  SPEC_ID="$ARTIFACT_ID"          # resolver's canonical artifact id (de-prefixed or prefixed, per disk)
  CP_STATE_DIR="$CP_DIR"          # .claude/specs/<artifact_id>
else
  SPEC_ID=""
  CP_STATE_DIR=""
fi
```

When `SPEC_ID` is non-empty, every Agent launch prompt for an agent that has a cp-state file MUST include a `SECOND ACTION` block (template under each Step's prompt below) instructing the subagent to read `$CLAUDE_PROJECT_DIR/$CP_STATE_DIR/cp-state-<agent>.json` and to mark each checkpoint via `/root/.claude/scripts/spec-check.py mark` (or `waive` — auto-text records actor + ISO timestamp) before Stop. Agents SHOULD leave zero pending checkpoints before they Stop. (Note: there is **no** `subagentstop-cp-enforce.py` hook wired in `settings.json` today — checkpoint completeness is a discipline expectation tracked via `spec-check.py`, not a hook-enforced block. Building a real checkpoint-enforcement hook is a separate, deferred feature.) When `SPEC_ID` is empty (non-`/spec` invocation), or a particular agent has no cp-state file under that artifact id, the SECOND ACTION block is omitted — there are no checkpoints to mark for that launch.

**T1.7 (redev-tier123) — Orchestrator-view + Section 5 read MANDATE**: When `VIEWS_AVAILABLE` is `true`, BEFORE composing any subagent dispatch prompt, you MUST read the orchestrator view that the resolver located — `$CLAUDE_PROJECT_DIR/$VIEWS_DIR/orchestrator.md` (the views live under `docs/dev/specs/<artifact_id>/views/`, NOT under `.claude/specs/`) — AND the spec's Section 5 (User's Acceptance Criterion) verbatim from `$spec_path`. Quote the user's words from Section 5 directly into every dispatch prompt; do not paraphrase or summarize. The user's verbatim need is the binding contract — every subagent must see the user's literal request, not your reformulation.

### Step 2: Graphify pre-BA Bash hydrator

Run `scripts/graphify-query.py` as a direct Bash call (NOT a subagent — avoids adding an LLM interpretation layer that could propagate confirmation bias). This is advisory: if the binary is absent or cache is unavailable, the script exits 0 with `status=unavailable` and BA proceeds with its original flow.

```bash
source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/graphify-query.py \
  --task-id "$DEV_SESSION_ID" \
  --requirement-file "$REQUIREMENT_DOC"
```

Output is written to `.claude/dev-registry/$DEV_SESSION_ID/graphify/pre_query.json`. When this file exists with `status=ok` or `status=degraded`, include it in the BA dispatch prompt (Step 4) as `Pre-query context file: .claude/dev-registry/$DEV_SESSION_ID/graphify/pre_query.json` so BA sees repo structure BEFORE forming its initial interpretation. When `status=unavailable` or `status=skipped`, omit the pre-query context from the BA prompt — BA runs its original flow unchanged.

After the query above (still within Step 2), fire a second advisory, non-blocking Bash call that auto-initializes the graph for the NEXT run when no cached graph exists yet. This call returns immediately and never stalls `/dev`: it launches a detached background full build (when needed) and exits at once, so this run proceeds with whatever the query already returned — the freshly-built graph only becomes available on a subsequent `/dev` run. This preserves the R-7 spirit (the pipeline never blocks on a graph build).

```bash
# Auto-init (async, non-blocking): if no cached graph exists, launch a background
# full build for the NEXT run. Returns immediately — never stalls /dev (R-7).
source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/graphify-maintain.py ensure-async || true
```

If `--no-graphify` was passed in `$ARGUMENTS`, add `--no-graphify` to the `graphify-query.py` Bash call above and skip the `ensure-async` call entirely.

### Step 3: Specialist Consultation (always evaluate, never silently skip)

Before touching any specialist, you MUST evaluate each one's relevance to the issue and document the decision. Silently skipping is forbidden — skipping without assessment is itself a workflow violation.

#### Procedure (mandatory, applies to every issue)

1. For each of the 4 specialists (`ui-specialist`, `architect`, `product-owner`, `user`), produce one line:
   - `<specialist>: RELEVANT — <reason>` OR
   - `<specialist>: SKIP — <concrete reason>`
2. Call every specialist marked RELEVANT. Parallelize in a single Agent call.
3. If you cannot articulate a concrete SKIP reason, default to CALL.

#### Relevance triggers (treat as RELEVANT unless clearly unrelated)

- **ui-specialist**: any visual/UI/UX/layout/CSS/responsive/styling/icon/component-appearance issue, any "looks wrong" report, any viewport-specific bug
- **architect**: any architectural/performance/dependency/pattern-consistency/structural concern, any cross-module change
- **product-owner**: any business-logic/feature-completeness/user-flow/missing-feature question, any "should this exist" question
- **user**: any end-to-end scenario, UX friction, broken flow, or unclear-behavior report

#### Forbidden shortcuts

- "No specialists needed" without per-specialist assessment — INVALID
- Skipping all 4 by default — INVALID
- Calling all 4 when 2 clearly don't apply — wasteful (document why each skipped)

#### Record the assessment

In the orchestrator's reasoning (and in BA's context JSON when BA is invoked next), include:
```json
"specialists_assessed": {
  "ui-specialist": "RELEVANT — layout issue" | "SKIP — pure backend change",
  "architect": "...",
  "product-owner": "...",
  "user": "..."
}
```

**How to invoke** (for each RELEVANT specialist, parallelize in a single response):

```
Use Agent tool with:
- description: "<Specialist role> consultation for: <requirement summary>"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/<specialist-name>.json to register with the enforcement system. Do this BEFORE any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read $CLAUDE_PROJECT_DIR/.claude/specs/<SPEC_ID>/cp-state-<specialist-name>.json to discover your atomic checkpoints (cp-01, cp-02, ...).

  CHECKPOINT MARKING: see agents/<specialist-name>.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the <specialist-name> specialist. Follow .claude/agents/<specialist-name>.md.

  Requirement: '<requirement from Step 1>'

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true

  Provide your observations and analysis relevant to this requirement.
  Return structured findings that will inform the BA analysis.
  DO NOT modify files. Return observations only.
  "
```

Pass all specialist findings (and the full `specialists_assessed` block) to the BA subagent in Step 4 as additional context.

## Four Contracts Awareness (Orchestrator Role)

The BA subagent enforces four domain-agnostic contracts (see
`~/.claude/agents/ba.md` §Four Contracts). The orchestrator MUST
complement BA by surfacing context before delegation and verifying
compliance after BA returns. The orchestrator does NOT re-do BA's work —
it prepares inputs and validates outputs.

### Pre-BA: surface retry signals

Before delegating to BA, scan the user's request and repo state for retry
signals. BA will independently check these, but the orchestrator must
provide them explicitly so BA starts with ground truth:

- **Retry intent**: judge semantically whether the user's message signals a prior attempt failed — explicit complaint, reference to prior commits/specs, repetition of a previously-stated requirement, or any other contextual cue (language- and phrasing-agnostic; do not pattern-match a fixed phrase list).
- **Recent related commits**: enumerate recent commits whose subjects touch the same area as the current request.
- **Existing BA specs**: prior `docs/dev/ticket-*.md` (legacy: `docs/dev/ba-spec-*.md`) covering the same area.

Pass findings to BA in the delegation prompt under an explicit
`prior_attempt_signals` block:

    prior_attempt_signals:
      retry_intent: "<one-line semantic summary, or null if none>"
      recent_commits: ["<hash> <subject>", ...]
      existing_specs: ["docs/dev/ticket-<ts>.md", ...] (legacy: docs/dev/ba-spec-<ts>.md)

### Post-BA: verify contract compliance

Before proceeding to dev, verify the BA JSON context contains:

- `evidence.measured.value` populated (not null, not empty string)
- `evidence.expected.source` populated
- `scope_expansion.all_occurrences` non-empty (or scope_expansion explicitly
  marked `not_applicable` with reason)
- `reference_source.tier` not `tier_3_tainted` when `copy_allowed: true`
- If Contract D triggered: novelty across BOTH dimensions — `layer` AND
  `target_location` (see Contract D extension below)
- **Location-complaint overlap**: tokens of BA's `affected_files ∪
  located_source` must intersect the complaint's location keywords, OR
  BA must declare `status: localization_blocked`. Mismatch is a hard
  reject — re-delegate BA, do NOT dispatch dev.

If any check fails, the orchestrator re-delegates to BA with explicit
feedback naming the missing field. Do NOT proceed to dev with an
incomplete spec.

**Location-complaint tokenization procedure** (shared with Contract D):

Use semantic LLM judgment (natural-language reading), NOT mechanical
character-set arithmetic. The orchestrator (you, in this turn) MUST read
three fields from the BA context JSON — `complaint_location_keywords`,
`affected_files`, and `located_source` — and form a single yes/no decision
about whether the files BA identified plausibly match the place the user
complained about. The decision is a natural-language semantic-overlap
judgment: would a reasonable engineer, reading the user complaint and
seeing BA's three fields side by side, agree that BA looked in the right
place? Aliases, synonyms, hierarchical names, and indirect references all
count toward the match — there is no token-splitting or set-intersection
step. Pass iff the LLM judgment is "yes, plausible match" OR BA emitted
`status == localization_blocked`. On a "no" verdict, re-delegate to BA
with a one-sentence explanation of which complaint phrase did not find a
believable home in `affected_files` or `located_source`, and do NOT
advance to dev.

<!--
Why semantic over mechanical: prior cycles used character-set splitting
and threshold-based comparison, which produced false rejects on
legitimate aliases ('login screen' vs. 'src/auth/SignIn.tsx') and false
accepts on look-alike paths that point at the wrong subsystem. An LLM
reading the three fields in context is more accurate than any rule.
-->

**Contract D novelty extension — two dimensions**:
Two attempts are considered equivalent (reject as non-novel) iff
`this_attempt_layer == prior_attempt_layer` AND
`jaccard(tokens_of(target_location_i), tokens_of(target_location_j)) >=
0.5`, using the same tokenization as above. Novelty requires EITHER a
different layer OR `jaccard < 0.5` on `target_location`. This blocks the
"different-words-same-wrong-file" loophole.

### BA rejection handling

If BA returns `status: "rejected"` (Contract D novelty-check failure):

- Do NOT retry BA with the same input (it will reject again)
- Surface the rejection reason and prior-attempt layer to the user
- Propose a different-layer approach (use the L1–L5 layer vocabulary)
- Only after user selects a different layer, re-delegate to BA

### Layer vocabulary (shared with BA)

Layers from shallow to deep:

- **L1 cosmetic**: styling, class names, component swap
- **L2 structural**: layout, component hierarchy
- **L3 data**: coordinates, schema values, regex, constants, SVG paths
- **L4 logic**: conditions, state machines, data flow
- **L5 infrastructure**: build, deploy, environment

When dev reports back, verify implementation layer matches BA's spec layer.
If dev changed L1 when spec called for L3, treat as failed implementation.

### Step 4: Delegate to BA Subagent

**Pre-dispatch (Mascot scoring injection, spec-20260518-225715 §5.1)**:

Run `bash ~/.claude/scripts/score-inject.sh --agent ba` and capture stdout into a variable `BA_SCORE_HEADER`. Per spec 5.1 line 113, this injection text is inserted AFTER the role declaration and BEFORE the task instructions for the BA dispatch — i.e. right between "You are the BA subagent." and the "Requirement:" / task body. The injection shows the rank+range (NOT exact score) and last 3 events.

**Use Task tool to invoke BA subagent for requirements analysis and context building**:

```
Use Task tool with:
- description: "Analyze requirement and build development context"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/ba.json to register with the enforcement system. Do this BEFORE any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read $CLAUDE_PROJECT_DIR/.claude/specs/<SPEC_ID>/cp-state-ba.json to discover your atomic checkpoints (cp-01, cp-02, ...).

  CHECKPOINT MARKING: see agents/ba.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the BA subagent. Follow .claude/agents/ba.md instructions precisely.

  <BA_SCORE_HEADER prepended here — score-inject output is placed AFTER the role declaration above and BEFORE the task instructions below, per spec 5.1 line 113: Injection position: after role declaration, before task instructions>


  Requirement: '<requirement from Step 1>'
  Clarification round: 0
  Previous answers: null
  Codebase hints: <any file paths mentioned by user, or null>
  Timestamp: <YYYYMMDD-HHMMSS>
  Spec file: <spec_path or null>
  View file: <view_paths.ba or null — sibling views/ba.md if present>
  Prior attempt signals:
    retry_intent: <one-line semantic summary, or null if none>
    recent_commits: [<hash> <subject>, ...]
    existing_specs: [docs/dev/ticket-<ts>.md, ...] (legacy: docs/dev/ba-spec-<ts>.md)

  If Spec file is not null: Read the spec file FIRST. Use Section 5 (User's Acceptance Criterion) as the primary requirement source. Use Sections 1-4 as baseline context. If Section 7 (What Must Be Done) is populated, treat it as prescriptive guidance.

  Goal: Translate the user's request into the smallest, safest, most-precise change set that lands the user-need, per spec-20260503-091826.md Section 5.1: the implementation approach is the minimum, safest, most-perfect, most-deterministic realization of user needs, not an expansion of fix scope; all work centers on user needs. Ground your analysis in the existing codebase patterns (align with current functionality rather than re-inventing). For bugs, find the root cause; for enhancements, research best practices via web search / explore / analyst agents per agents/ba.md Section 5.3 mission. Path-external observations go into the spec's `out_of_scope_observations` chapter (per agents/ba.md), not into the fix scope. Use the existing 5-dimension clarity scoring (What/Why/Where/Scope/Success) to gate `needs_clarification`. Produce both deliverables (ticket-<timestamp>.md per spec-20260503-091826 M3 ba-spec→ticket rename, plus context-<timestamp>.json) following agents/ba.md Output Formats.

  Explicit task-id printing: include the literal line `TASK-ID: <timestamp>` in your stdout response so close.md / commit.sh task-id-chain confirmation has an unambiguous anchor for this BA dispatch.

  Return JSON with status, file paths, summary, and the task-id echo.
  "
```

**Wait for BA subagent completion** before proceeding.

### Step 5: BA Clarification Loop

**If BA returns `status: "needs_clarification"`**:

1. Present BA's questions to user (relay verbatim)
2. Collect user answers
3. Re-invoke BA with answers:

```
Use Task tool with:
- description: "Continue BA analysis with clarification answers"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/ba.json to register with the enforcement system. Do this BEFORE any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read $CLAUDE_PROJECT_DIR/.claude/specs/<SPEC_ID>/cp-state-ba.json to discover your atomic checkpoints (cp-01, cp-02, ...).

  CHECKPOINT MARKING: see agents/ba.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the BA subagent. Follow .claude/agents/ba.md instructions precisely.

  Requirement: '<original requirement>'
  Clarification round: <N>
  Previous answers: <JSON array of {question, answer} pairs>
  Codebase hints: <accumulated hints>
  Timestamp: <same timestamp>

  Continue analysis with user's answers. Generate output if clarity sufficient.
  "
```

**Loop rules**:
- Maximum 3 clarification rounds
- After round 3, BA returns best-effort with explicit assumptions
- If BA returns `status: "ready"`, proceed to Step 6

**If BA returns `status: "ready"` on first invocation**: Skip to Step 6.

### Step 6: Validate BA Output

**Check BA deliverables exist and are well-formed**:

Read BA output files:
- `docs/dev/ticket-<timestamp>.md` - Markdown specification (legacy: docs/dev/ba-spec-<timestamp>.md)
- `docs/dev/context-<timestamp>.json` - JSON context for dev subagent

**Sanity checks**:
- [ ] Both files exist
- [ ] Markdown spec has required sections (Goal, Requirements, Acceptance Criteria)
- [ ] JSON context has required fields (requirement, root_cause_analysis, development_approach)
- [ ] Success criteria are measurable
- [ ] Affected files identified

**spec_path patch (mandatory post-BA-validation step — task 20260526-053746 AC-01)**:

After the sanity checks pass and BEFORE proceeding to Step 7, the orchestrator MUST patch the `spec_path` field into `docs/dev/context-<timestamp>.json` so downstream consumers (dev, QA, close) can reference the spec.

The orchestrator-resolved `spec_path` is the value derived from either the explicit `--spec <path>` flag or the auto-detection fallback (whichever the orchestrator ran in Step 1). Call this resolved value `$orchestrator_resolved_spec_path`. It is either a non-null string OR null (when `--spec` was not passed AND auto-detection returned null).

Apply this patch logic verbatim (AC-01 four-condition matrix + negative case):

```bash
# Step 6 spec_path patch — task 20260526-053746 AC-01 (5-row fixture matrix)
# Overwrites context.json.spec_path when orchestrator-resolved value is non-null
# AND the current context.spec_path is absent / null / empty / different.
# Negative case: when orchestrator-resolved spec_path == null, do NOT invent a value
# (key remains absent or null in output context.json) — codex iter-2 C3.
CONTEXT_JSON="docs/dev/context-${timestamp}.json"
if [ -n "$orchestrator_resolved_spec_path" ]; then
  # Orchestrator-resolved spec_path is non-null — overwrite context.spec_path
  # in ALL four positive conditions (absent / null / empty / different).
  # Env vars CONTEXT_JSON_PATH and NEW_SPEC_PATH are passed inline to python3 so
  # the heredoc is fully self-contained — the Python source itself is static
  # (codex iter-3 F1: bare heredoc without inline env vars fails KeyError).
  CONTEXT_JSON_PATH="$CONTEXT_JSON" NEW_SPEC_PATH="$orchestrator_resolved_spec_path" python3 - <<'PYEOF'
import json, sys, os
path = os.environ['CONTEXT_JSON_PATH']
new_spec = os.environ['NEW_SPEC_PATH']
with open(path) as fh:
    ctx = json.load(fh)
current = ctx.get('spec_path')
# Apply patch when current is absent / null / empty-string / different.
# All four conditions reduce to: current != new_spec (since None/missing/'' are all != new_spec).
if current != new_spec:
    ctx['spec_path'] = new_spec
    with open(path, 'w') as fh:
        json.dump(ctx, fh, indent=2)
    print(f"[step5-patch] context.spec_path: {current!r} -> {new_spec!r}", file=sys.stderr)
else:
    print(f"[step5-patch] context.spec_path already correct: {current!r}", file=sys.stderr)
PYEOF
else
  # Orchestrator-resolved spec_path is null — DO NOT invent a value.
  # The key may remain absent or null in context.json (whatever BA wrote).
  # This is the AC-01 (e) negative case per codex iter-2 C3.
  echo "[step5-patch] orchestrator-resolved spec_path is null — no patch applied" >&2
fi
```

The four positive conditions all reduce to the single check `current != new_spec_path`:

| Case | context.json initial state | After patch |
|------|---------------------------|-------------|
| a | `spec_path` key absent | `spec_path == "<orchestrator-resolved>"` |
| b | `"spec_path": null` | `spec_path == "<orchestrator-resolved>"` |
| c | `"spec_path": ""` | `spec_path == "<orchestrator-resolved>"` |
| d | `"spec_path": "wrong.md"` (different) | `spec_path == "<orchestrator-resolved>"` |
| e | (orchestrator-resolved is null) | `spec_path` remains absent or null (no invention) |

The patch MUST run after BA validation passes but BEFORE QA (Step 7) is dispatched — QA reads `context-<timestamp>.json` and must see the patched value.

**If validation fails**:
- Re-invoke BA with specific feedback about what's missing
- Maximum 2 re-invocations for validation fixes

**If validation passes**: Apply the spec_path patch above, then proceed to Step 7

### Step 7: QA Validates BA Conclusions

**Purpose**: Verify BA's analysis quality BEFORE Dev starts implementation. Catches unproven claims, scope mismatches, and missing investigation evidence early -- saving a wasted Dev+QA cycle.

**Before dispatching QA, write qa_mode sentinel**:

```bash
bash ~/.claude/scripts/write-qa-mode.sh --session-id "$DEV_SESSION_ID" --mode ba_validation \
  || { echo 'ERROR: Failed to set qa_mode=ba_validation in qa.json — aborting' >&2; exit 1; }
```

**Invoke QA in BA-validation mode**:

```
Use Agent tool with:
- subagent_type: "qa"
- description: "Validate BA analysis quality (not code)"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/qa.json to register with the enforcement system. Do this BEFORE any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read $CLAUDE_PROJECT_DIR/.claude/specs/<SPEC_ID>/cp-state-qa.json to discover your atomic checkpoints (cp-01, cp-02, ...).

  CHECKPOINT MARKING: see agents/qa.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the QA subagent in BA-VALIDATION MODE. This is NOT code verification.
  You are verifying the QUALITY OF BA's ANALYSIS, not any implementation.

  DO NOT: build, deploy, open browser, run Playwright, or test code.
  DO: read BA's deliverables and challenge every claim.

  BA spec file: docs/dev/ticket-<timestamp>.md (legacy: docs/dev/ba-spec-<timestamp>.md)
  Context JSON: docs/dev/context-<timestamp>.json
  Spec file: <spec_path or null>
  View file: <view_paths.qa or null — sibling views/qa.md if present>

  Verify these 5 dimensions:

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

  5. SPEC-TEXT-VS-EXECUTION DRIFT: When QA finds that an AC's literal regex /
     command / verification recipe produces output unexpected by the AC text,
     but a different formulation of the same check actually verifies the AC's
     intent, raise a 'dimension: spec_text_vs_execution_drift' objection
     requiring BA to update the AC's literal text to the actually-runnable
     formulation. This catches the 'AC reads X but the only thing that produces
     meaningful evidence is Y' pattern that produces PASS_AS_SUBSTITUTE verdicts
     and AC literal-text drift across cycles. (Mirrors agents/qa.md
     '### BA-Validation Mode: 5 Dimensions of Objection' under
     '## Counter-Evidence Authority'.)

  Return JSON:
  {
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

  Write report to: docs/dev/ba-qa-report-<timestamp>.json
  "
```

**Process QA result**:

```
IF verdict == "pass":
  -> BA conclusions validated. Proceed to Step 9.

ELIF verdict == "fail":
  -> Proceed to Step 8 for BA-QA iteration.
```

### Step 8: BA-QA Iteration Loop (if QA rejects BA)

**Iteration guard**: Maximum 3 BA-QA iterations to prevent infinite loops

**Current BA-QA iteration**: Track internally (starts at 1)

**If BA-QA iteration > 3**:
```
BA-QA validation: 3 iterations exhausted. Proceeding with best-effort BA output.

Unresolved objections:
{summary of remaining QA objections}

Appending unresolved objections to context JSON under `ba_qa_unresolved_objections`.
Proceeding to Step 9 with documented assumptions.
```

**If BA-QA iteration <= 3**:

**Announce**: `BA-QA iteration <N>/3: QA found <count> objections in BA analysis. Re-invoking BA to address objections.`

**Re-invoke BA with QA's objections**:

```
Use Agent tool with:
- subagent_type: "ba"
- description: "Re-investigate: address QA objections on analysis quality"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/ba.json to register with the enforcement system. Do this BEFORE any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read $CLAUDE_PROJECT_DIR/.claude/specs/<SPEC_ID>/cp-state-ba.json to discover your atomic checkpoints (cp-01, cp-02, ...).

  CHECKPOINT MARKING: see agents/ba.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the BA subagent. Follow .claude/agents/ba.md instructions precisely.

  Your previous analysis was REJECTED by QA. Address each objection below
  with concrete evidence. Do not argue -- investigate and provide proof.

  Original requirement: '<requirement>'
  Previous BA spec: docs/dev/ticket-<timestamp>.md (legacy: docs/dev/ba-spec-<timestamp>.md)
  Previous context: docs/dev/context-<timestamp>.json
  Spec file: <spec_path or null>

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

**After BA re-delivers**: Return to Step 6 (validate BA output), then Step 7 (QA re-validates).

**Rule**: Every BA invocation MUST be followed by QA validation. No exceptions.

**Iteration tracking**: Update TodoWrite with BA-QA iteration number.

### Step 9: Graphify enrichment

> **Cross-file label note**: The agent-file and integration-doc interstitial labels (e.g. "between Step 7 and Step 8" in `agents/graphify.md`, `agents/dev.md`, and `docs/reference/graphify-integration.md`) are the **cross-file canonical position-label** for this enrichment touchpoint and are intentionally NOT renumbered to match this command's `### Step 9` heading; the apparent mismatch is expected, so future readers should not "fix" it.

After BA-QA validation passes, check whether the graphify sentinel file exists before dispatching the graphify subagent. This is advisory — if the sentinel is absent (graphify binary not installed) or graphify returns status=skipped, proceed to Step 10 without delay.

Before dispatching graphify, check whether the sentinel file exists at `$CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID/graphify.json`. If absent for any reason, do not dispatch; record `graphify_status=skipped/sentinel_absent`; do not read `graph-summary.json`; proceed to Step 10. If present, dispatch graphify, then record the resulting status from `graph-summary.json` when available.

If the sentinel file is present, dispatch the graphify subagent:

```
Use Agent tool with:
- subagent_type: "graphify"
- description: "Graphify enrichment: extract focused subgraph for task"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/graphify.json to register with the enforcement system. Do this BEFORE any other tool call.

  You are the graphify subagent. Follow agents/graphify.md instructions precisely.

  Run: source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/graphify-enrich.py --task-id <DEV_SESSION_ID> --context-file <context_json_path>

  This is advisory — if the binary is absent or blast-radius-map is missing, exit 0 with status=skipped.
  "
```

If the sentinel is absent, record `graphify_status=skipped/sentinel_absent` in the todo list.

When sentinel existed and graphify completes (or is skipped), check `.claude/dev-registry/<DEV_SESSION_ID>/graphify/graph-summary.json` for the status field and record it in the todo list. Then continue to Step 10.

### Step 10: Agent dispatch — Delegate to Dev Subagent

**TodoWrite ordering reminder (task 20260519-211515 R3 / AC3)**: TodoWrite mark-as-in_progress for step N must precede any Agent() call dispatched within step N.
The orchestrator MUST emit a TodoWrite call updating the Step-N todo item to `in_progress` BEFORE invoking any Agent() (or Task tool) dispatch in Step N. REQUIRED ordering: TodoWrite first, Agent() second. Always update the in_progress marker BEFORE dispatch. Before dispatch of test-writer or Dev (or any subagent in any Step), the matching Todo item MUST already be in_progress; otherwise do not dispatch.

**Pre-dispatch — Test-Writer dispatch (conditional, between BA and Dev per spec-20260518-225715 §5.2 line 167: "Position: BA -> [test-writer] -> Dev -> QA")**:

**Test-writer skip-sentinel honor (task 20260519-211515 R4 / V_TW, CF2-14)**: BEFORE evaluating the gate below, read `_test_writer_skip_reason` from BA's context JSON. If that field is a non-empty string, the test-writer dispatch MUST be skipped on this cycle regardless of complexity_tier / risk_level — the sentinel is an explicit BA-authored skip signal. Record `test_writer_expected = false` and the skip reason in the todo list. Do NOT route a stale-content acceptance-criteria JSON to test-writer; doing so generates wrong-cycle pytest skeletons. This honor-clause is the V_TW enforcement; commands/dev.md Step 10 must reference `_test_writer_skip_reason` or `skip test-writer` language so the sentinel is not decorative.

Gate evaluation (mandatory): read `complexity_tier` and `risk_level` from BA's context JSON. If `complexity_tier ∈ {STANDARD, COMPLEX}` OR `risk_level == "high"`, then `test_writer_expected = true`; otherwise `test_writer_expected = false`. Pass `test_writer_expected` into the Dev and QA dispatch prompts.

When `test_writer_expected == true`, dispatch the test-writer subagent BEFORE Dev:

```
Use Task tool with:
- description: "Generate pytest skeletons from acceptance criteria"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/test-writer.json (or create if absent with {agent_type:'test-writer', session_id:'<DEV_SESSION_ID>'}).

  You are the test-writer subagent. Follow agents/test-writer.md instructions precisely.

  Inputs:
    task_id: <task_id>
    acceptance_criteria_path: docs/dev/acceptance-criteria-<task_id>.json
    complexity_tier: <COMPLEX|STANDARD|SMALL|MICRO from BA context>
    risk_level: <high|medium|low from BA context>

  Write your report to: docs/dev/test-writer-report-<task_id>.json
  Generated tests go under: tests/generated/<task_id>/
  Per-task active manifest: tests/generated/<task_id>/manifest.json (active_tests[] lives here — this is what QA Phase 5 reads).
  Global index: tests/generated/manifest.json (index) (shape {kind:"index", tasks:[{task_id, manifest_path}]}; upsert an entry for the current task_id — does NOT carry active_tests[]).
  "
```

After the test-writer subagent completes, verify on disk that ALL THREE of `tests/generated/<task_id>/manifest.json` (per-task active manifest), `tests/generated/manifest.json` (global index) AND `docs/dev/test-writer-report-<task_id>.json` exist. If any is missing, abort the cycle with an error (the orchestrator MUST NOT proceed to Dev with a silently-skipped test-writer). When `test_writer_expected == false`, SKIP the dispatch (record skip rationale in the todo list).

After test-writer completes (or is skipped), the generated test file paths and manifest path are passed onward to Dev (in the dispatch prompt) and to QA (Step 13). Dev makes the skeleton tests pass; QA verifies the manifest at Step 13 Phase 5 AND that `test_writer_expected == true` implies manifest/report existence (Phase 5 fails with `primary_cause: "dev_implementation"` or `"qa_oversight"` if expected but missing).

**Pre-dispatch (Mascot scoring injection, spec-20260518-225715 §5.1)**:

Run `bash ~/.claude/scripts/score-inject.sh --agent dev` and capture stdout into a variable `DEV_SCORE_HEADER`. Per spec 5.1 line 113, this injection text is inserted AFTER the role declaration and BEFORE the task instructions for the Dev dispatch.

**Pre-dispatch baseline capture** (run BEFORE invoking the dev subagent):

```bash
baseline_head_sha=$(git -C "$CLAUDE_PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo "")
# baseline_dirty_snapshot is intentionally captured once before Dev dispatch;
# see agents/dev.md for its point-in-time / concurrency semantics.
baseline_dirty_snapshot=$(git -C "$CLAUDE_PROJECT_DIR" status --porcelain 2>/dev/null || echo "")
```

Both values MUST be passed into the dev dispatch payload body (see below). If the repo has no commits yet, `baseline_head_sha` will be empty — pass it as empty string, not omitted.

**Use Task tool to invoke dev subagent with file paths only**:

```
Use Task tool with:
- description: "Implement development changes based on BA context"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/dev.json to register with the enforcement system. Do this BEFORE any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read $CLAUDE_PROJECT_DIR/.claude/specs/<SPEC_ID>/cp-state-dev.json to discover your atomic checkpoints (cp-01, cp-02, ...).

  CHECKPOINT MARKING: see agents/dev.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the dev subagent. Follow agents/dev.md instructions precisely.

  <DEV_SCORE_HEADER prepended here — score-inject output is placed AFTER the role declaration above and BEFORE the task instructions below, per spec 5.1 line 113: Injection position: after role declaration, before task instructions>

  Context file: docs/dev/context-<timestamp>.json
  BA spec file: docs/dev/ticket-<timestamp>.md (legacy: docs/dev/ba-spec-<timestamp>.md)
  Spec file: <spec_path or null>
  View file: <view_paths.dev or null — sibling views/dev.md if present>
  Generated tests (when test-writer ran): tests/generated/<task_id>/ + per-task active manifest at tests/generated/<task_id>/manifest.json. Global index file tests/generated/manifest.json (index) is a presence sentinel only — see Step 10 test-writer dispatch for full shape.
  Write your implementation report to: docs/dev/dev-report-<timestamp>.json
  baseline_head_sha: <baseline_head_sha captured above>
  baseline_dirty_snapshot: <baseline_dirty_snapshot captured above>

  If Spec file is not null: Read the spec file FIRST for context. After implementation, update the spec: Section 2 (What Was Attempted) with your approach and rationale. Section 3 (What Was Changed) with exact file:line edits.
  If View file is not null: you may read the view instead of the full monolith — it contains only the sections relevant to dev (S1, S2, S3, S7, S8) and is a byte-slice of the monolith.
  "
```

**Wait for dev subagent completion** before proceeding.

### Step 11: Write Canonical Aggregate Dev-Report (Parallel-Dev Only)

**Applies ONLY when N>1 parallel dev subagents were dispatched in Step 10.** Single-dev cycles SKIP this step entirely (the lone dev subagent writes `dev-report-<task-id>.json` directly).

**Procedural enforcement**: This step is gated by `pretool-aggregate-check.py` (PreToolUse Agent matcher). When `docs/dev/` contains 2+ per-worker dev-report files for the same `<task-id>` AND the canonical singular `docs/dev/dev-report-<task-id>.json` is missing, the next Agent dispatch (Step 13 QA) is BLOCKED with exit 2 until the orchestrator writes the aggregate. Shard detection uses BOTH naming patterns: role-first (`dev-report-<role>-<task-id>.json`) and task-first (`dev-report-<task-id>-<worker>.json`).

**Authoritative construction rule**: see the "Parallel Dev Aggregate" subsection below (Aggregate construction rule + Example aggregate JSON) for the full schema and union semantics. Summary:
- `request_id` = `<task-id>`; `dev_report_path` = canonical singular path
- `parallel_workers` = list of per-worker ids
- `dev.status`, `dev.tasks_completed`, `dev.scripts_created`, `dev.permissions_to_add`, `dev.files_modified`, `dev.files_created`, `blocking_issues`, `recommendations` = unions of per-worker reports
- `baseline_head_sha` = equality-verified across all workers (aggregate status = `"blocked"` if any worker disagrees, citing `baseline_head_sha` mismatch); value taken from orchestrator dispatch
- `baseline_dirty_snapshot` = equality-verified across all workers (aggregate status = `"blocked"` if any worker disagrees, citing `baseline_dirty_snapshot` mismatch); value taken verbatim from orchestrator dispatch
- `dev.observed_preexisting` = UNION of all per-worker `dev.observed_preexisting` lists
- The orchestrator invokes `source venv/bin/activate && python3 scripts/aggregate-dev-report.py --task-id $TASK_ID` to write the canonical aggregate. Capture stdout JSON; action field will be `"aggregated"`, `"validated"`, or `"skipped"`. Do NOT modify the `/commit` command implementation (`/root/.claude/commands/commit.md`)

**Single-dev cycles**: mark this todo step waived (skip). The aggregate-check hook does not fire for single-dev cycles because only one per-worker file pattern can match.

#### Parallel Dev Aggregate (when dispatching N parallel dev subagents, N>1)

When the orchestrator dispatches N parallel `dev` subagents (one per file-disjoint
work item), EACH dev writes its own report to
`docs/dev/dev-report-<task-id>-<worker-id>.json`. Downstream `/commit`
(`/root/.claude/commands/commit.md`) reads ONLY the canonical singular path
`docs/dev/dev-report-<task-id>.json` and fails closed if it is missing
(redev7 cycle could not self-deploy for this exact reason).

**After ALL parallel devs return, the orchestrator MUST write a canonical
aggregate `dev-report-<task-id>.json`** that unions the per-worker reports
into a single artifact consumable by downstream `/commit`. This is an
orchestrator-side rule; do NOT modify the `/commit` command implementation
(`/root/.claude/commands/commit.md`), the singular-filename consumer contract
stays as-is.

**Aggregate construction rule**:
- `request_id` = `<task-id>` (literal, matches the cycle task-id)
- `timestamp` = ISO-8601 of the aggregate write
- `dev_report_path` = `docs/dev/dev-report-<task-id>.json` (the canonical path)
- `parallel_workers` = list of per-worker ids `["<worker-id>", ...]`
  (top-level field for traceability; sources the per-worker reports)
- `baseline_head_sha` = equality-verified across all workers: assert every worker's `baseline_head_sha` equals the orchestrator's dispatch value; if any worker differs, set aggregate `dev.status = "blocked"` and append a `blocking_issues` entry citing `baseline_head_sha` mismatch. Value in the aggregate is taken from the orchestrator dispatch (not unioned from workers).
- `baseline_dirty_snapshot` = equality-verified across all workers: assert every worker's `baseline_dirty_snapshot` equals the orchestrator's dispatch value (the `git status --porcelain` string captured pre-dispatch); if any worker differs, set aggregate `dev.status = "blocked"` and append a `blocking_issues` entry citing `baseline_dirty_snapshot` mismatch. Value in the aggregate is taken verbatim from the orchestrator dispatch.
- `dev.status` = `"completed"` iff ALL workers reported `"completed"` **and** no `baseline_head_sha` / `baseline_dirty_snapshot` mismatch was found during equality verification above; otherwise `"blocked"` with rationale in `blocking_issues`
- `dev.tasks_completed` = UNION of all per-worker `dev.tasks_completed`
- `dev.scripts_created` = UNION of all per-worker `dev.scripts_created`
- `dev.permissions_to_add` = UNION of all per-worker `dev.permissions_to_add`
- `dev.files_modified` = UNION of all per-worker `dev.files_modified`
- `dev.files_created` = UNION of all per-worker `dev.files_created`
- `dev.observed_preexisting` = UNION of all per-worker `dev.observed_preexisting` lists (informational; QA reads this field from the aggregate)
- `blocking_issues` = UNION of all per-worker `blocking_issues`
- `recommendations` = UNION of all per-worker `recommendations`

**Example aggregate JSON** (written by `source venv/bin/activate && python3 scripts/aggregate-dev-report.py --task-id $TASK_ID`):

```json
{
  "request_id": "<task-id>",
  "task_id": "<task-id>",
  "timestamp": "<ISO-8601>",
  "baseline_head_sha": "<orchestrator dispatch value — equality-verified across all workers>",
  "baseline_dirty_snapshot": "<orchestrator dispatch value — equality-verified across all workers>",
  "dev_report_path": "docs/dev/dev-report-<task-id>.json",
  "parallel_workers": ["pcwd", "ppush"],
  "dev": {
    "status": "completed",
    "tasks_completed": [],
    "scripts_created": [],
    "permissions_to_add": [],
    "files_modified": [],
    "files_created": [],
    "observed_preexisting": []
  },
  "blocking_issues": [],
  "recommendations": []
}
```

**Single-dev path is unaffected** (do NOT add aggregate logic for N=1):
when only one dev was dispatched, that dev writes
`dev-report-<task-id>.json` directly and the orchestrator does NOT write an
additional aggregate (that would clobber). The aggregate rule applies ONLY
when N>1 parallel devs were dispatched.

### Step 12: Validate Dev Implementation

**Quick validation before QA**:

Read dev implementation report: `docs/dev/dev-report-<timestamp>.json`

**Sanity checks**:
- [ ] Status is "completed" (not "blocked")
- [ ] All tasks documented
- [ ] Scripts created have usage examples
- [ ] Git rationale references root cause
- [ ] Files exist that were reported as created/modified

**If dev blocked**:
- Read blocking issues from report
- Resolve blockers (e.g., missing information, technical constraints)
- Refine context JSON with additional information
- Re-invoke dev subagent (maximum 3 attempts)

**If dev completed**: Proceed to Step 13

### Step 13: Delegate to QA Subagent

**Before dispatching QA, write qa_mode sentinel**:

```bash
bash ~/.claude/scripts/write-qa-mode.sh --session-id "$DEV_SESSION_ID" --mode final_verification \
  || { echo 'ERROR: Failed to set qa_mode=final_verification in qa.json — aborting' >&2; exit 1; }
```

**Pre-dispatch (Mascot scoring injection, spec-20260518-225715 §5.1)**:

Run `bash ~/.claude/scripts/score-inject.sh --agent qa` and capture stdout into a variable `QA_SCORE_HEADER`. Per spec 5.1 line 113, this injection text is inserted AFTER the role declaration and BEFORE the task instructions for the QA dispatch.

**Use Task tool to invoke QA subagent with file paths only**:

```
Use Task tool with:
- description: "Verify implementation quality against standards"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/qa.json to register with the enforcement system. Do this BEFORE any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read $CLAUDE_PROJECT_DIR/.claude/specs/<SPEC_ID>/cp-state-qa.json to discover your atomic checkpoints (cp-01, cp-02, ...).

  CHECKPOINT MARKING: see agents/qa.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the QA subagent. Follow agents/qa.md instructions precisely.

  <QA_SCORE_HEADER prepended here — score-inject output is placed AFTER the role declaration above and BEFORE the task instructions below, per spec 5.1 line 113: Injection position: after role declaration, before task instructions>


  Context file: docs/dev/context-<timestamp>.json
  Dev report file: docs/dev/dev-report-<timestamp>.json
  BA spec file: docs/dev/ticket-<timestamp>.md (legacy: docs/dev/ba-spec-<timestamp>.md)
  Spec file: <spec_path or null>
  View file: <view_paths.qa or null — sibling views/qa.md if present>
  Per-task active test manifest: tests/generated/<task_id>/manifest.json (the file QA Phase 5 reads active_tests[] from; the global file tests/generated/manifest.json (index) is only consulted as a presence sentinel — see agents/qa.md Phase 5).
  Write your verification report to: docs/dev/qa-report-<timestamp>.json

  If Spec file is not null: Read the spec file FIRST. After verification, do NOT directly Edit docs/dev/specs/*.md (QA tool-policy denies write access by design — the verifier role must not mutate the spec it verifies). Instead, REPORT proposed Section 4/6/7 content via the qa-report JSON's 'qa.spec_section_updates' field with sub-fields 'section_4' (always populated when a spec is present and Section 4 measurements were taken; null otherwise), 'section_6' (populated only when verdict is fail; null otherwise), and 'section_7' (populated only when verdict is fail; null otherwise). The orchestrator applies these to the spec file in Step 14 with cycle-header create/append insertion semantics preserved. See agents/qa.md '### After Verification' under '## Overnight Spec Integration' for the QA-side prose, and agents/qa.md '## Output Format' for the JSON schema declaration.

  INDEX-edit clarifier: future ACs targeting INDEX file edits MUST target exactly the 3 manually-managed INDEX files: '.claude/templates/INDEX.md', '.claude/scripts/INDEX.md', 'docs/dev/INDEX.md'. Do NOT target 'docs/dev/specs/INDEX.md' — that file is auto-regenerated by '.claude/hooks/posttool-doc-sync.py' (with helper '.claude/hooks/doc_sync/regen_index.py'); manual edits to it will be silently overwritten on the next doc-sync run.
  "
```

**Wait for QA subagent completion** before proceeding.

### Step 14: Process QA Results

Read QA report: `docs/dev/qa-report-<timestamp>.json`

**Apply spec section updates (before the decision tree)**:

This pre-decision-tree pass applies QA's reported spec section updates to the spec file before processing the verdict.

If a `Spec file` was non-null this cycle (i.e., `/dev` was invoked under `--spec` and a global spec path was passed to Step 13), the orchestrator MUST apply QA's reported spec section updates to the spec file before processing the verdict:

(a) Check whether `Spec file` was non-null this cycle. If null, skip to the decision tree below.

(b) Read `qa.spec_section_updates` from the qa-report. The field is an object with shape `{section_4: string|null, section_6: string|null, section_7: string|null}`.

(c) Edit the spec file's corresponding sections using the orchestrator's own write authority (orchestrator can Edit `docs/dev/specs/*.md`; QA cannot — by design). Apply each populated sub-field:
  - `section_4` → spec file Section 4 (Current State); ALWAYS when populated.
  - `section_6` → spec file Section 6 (Why Not Met); ONLY when verdict is `fail`.
  - `section_7` → spec file Section 7 (What Must Be Done); ONLY when verdict is `fail`.

(d) Gracefully skip if `qa.spec_section_updates` is absent or null (e.g., for non-spec cycles or cycles where QA legitimately had nothing to report). Do NOT treat missing/null as an error on non-spec cycles. On a spec-driven cycle a null value is an Anti-Fraud violation per `agents/qa.md` Output Format population requirement; flag it and continue.

(e) **PRESERVE cycle-header create/append insertion semantics** (MANDATORY): for each populated sub-field, before writing into the corresponding spec section:
  - Determine the current cycle number N (from cycle counter / spec metadata / context).
  - Check whether the subsection header `### Cycle N` already exists within the target section (Section 4 / Section 6 / Section 7).
  - If the `### Cycle N` header is MISSING, create it (append a new `### Cycle N` heading at the end of the section).
  - APPEND the new content under the new (or existing) `### Cycle N` header — i.e., place the new content after any existing content already under that cycle header.
  - **NEVER overwrite prior cycle content under existing `### Cycle 1`, `### Cycle 2`, ... headers.** Prior cycles' content is historical and immutable; only the current cycle's subsection grows. (This insertion semantics is also documented in `agents/qa.md` `### After Verification` for the QA-self side; the orchestrator-side application here mirrors it. Phrase: "preserve cycle headers; append after existing cycle content; never overwrite prior cycle content.")

After the spec section updates pass completes (or is skipped on non-spec cycles), proceed to the decision tree.

**Decision tree**:

```
IF qa.status == "pass":
  → Proceed to Step 15 (Update Permissions)

ELIF qa.status == "warning":
  → Check if minor issues acceptable
  → If yes: Proceed to Step 15 (Update Permissions)
  → If no: Proceed to Step 16 (Iteration)

ELIF qa.status == "fail":
  → Proceed to Step 16 (Iteration)
```

**Apply Mascot score-update events (post-QA, spec-20260518-225715 §5.1)**:

This post-decision-tree pass applies the canonical score-update events for this cycle.

After the verdict is known, apply score-update events based on QA outcome and iteration count:

- First-round PASS (iteration 0 + qa.status=pass) → `bash ~/.claude/scripts/score-update.sh --agent dev --event qa_first_pass --note "<task_id>"` AND `--agent ba --event qa_first_pass`. (dev 0, ba 0, qa 0 — Path A rebalance task 20260524-205206 M1; per-iteration nudge collapsed into close events.)
- Second-or-later-round PASS (iteration ≥1 + qa.status=pass) → `--agent dev --event qa_second_pass --note "<task_id>"`. (dev 0 — Path A rebalance task 20260524-205206 M1.)
- FAIL (qa.status=fail) — read `qa.failures[].primary_cause` to attribute the rejection:
  - Any failure with `primary_cause = "dev_implementation"` → `score-update.sh --agent dev --event qa_reject_dev --note "<task_id>"`. (dev -12.)
  - Any failure with `primary_cause = "ba_spec"` → `score-update.sh --agent ba --event qa_reject_ba --note "<task_id>"` AND `--agent dev --event qa_reject_ba` (dev -5, ba -8).
  - `primary_cause = "qa_oversight"` or `"environment"` → no auto-score update (manual review).

Each score-update call is independent; failures are non-blocking (a failed score-update writes to stderr but does not abort the dev cycle). Include the score deltas summary in the Step 17 completion report under a `score_updates` array.

### Step 15: Update Settings.json Permissions

**CRITICAL**: Auto-update permissions for new functionality.

**Extract validated permissions from QA report**:

```bash
jq '.qa.permissions_verification.validated_permissions' docs/dev/qa-report-<timestamp>.json
```

**Update settings.json**:

Read current settings:
```bash
cat .claude/settings.json
```

For each validated permission:

```json
{
  "pattern": "Bash(scripts/new-script.sh:*)",
  "section": "allow",
  "reason": "Allow execution of..."
}
```

**Add to appropriate section in settings.json**:

```bash
# Use jq to add permission
jq '.permissions.allow += ["Bash(scripts/new-script.sh:*)"]' .claude/settings.json > .claude/settings.json.tmp
mv .claude/settings.json.tmp .claude/settings.json
```

**Permission update rules**:

1. **Scripts created** → Add to "allow":
   - `"Bash(scripts/<script-name>.sh:*)"`
   - `"Bash(~/.claude/scripts/<script-name>.sh:*)"`

2. **Python scripts** → Add to "allow":
   - `"Bash(source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/todo/<script>.py:*)"`

3. **Hooks created** → Add to "allow":
   - `"Bash(~/.claude/hooks/<hook-name>.sh:*)"`

4. **Commands created** → Already allowed via "SlashCommand"

**Notify user**:

```
Updated settings.json permissions:

Added to "allow" section:
- Bash(scripts/validate-timeout.sh:*) - Allow timeout validation script
- Bash(scripts/measure-api-latency.sh:*) - Allow latency measurement script

Total permissions added: 2

You can now use these scripts without permission prompts.
```

**Validation**:
- Check JSON syntax after modification
- Verify no duplicate permissions
- Confirm permissions follow patterns

**Error handling**:
- If settings.json has syntax error → Ask user to fix manually
- If permission already exists → Skip, don't duplicate
- If user denies update → Log to completion report

### Step 16: Iteration Loop (if QA fails)

#### Layer-escalation gate (mandatory)

When QA rejects the dev fix, the orchestrator MUST track the layer used in
each attempt. Rules:

1. Attempt 1 may target any layer BA recommends (usually the lowest plausible
   layer).
2. If attempts 1 AND 2 both target the SAME layer (L1 / L2 / L3 / L4 / L5)
   and BOTH fail QA, iteration 3 MUST target a DIFFERENT layer. The
   orchestrator passes `layer_escalation_required: true` to BA and the BA
   MUST produce a new root-cause hypothesis at a DIFFERENT layer.
3. The orchestrator MUST record every attempt's layer in the context JSON
   under `attempts[i].target_layer`. Before iteration N, the orchestrator
   checks the last N-1 layers; if they are all equal and QA has rejected
   them all, escalation is mandatory.
4. BA's Contract D novelty-check MUST include `differs_from_all_prior_layers`
   in addition to `differs_from_all_priors`. A fix that changes L1 wording
   but stays in L1 is NOT novel under this rule.
5. If the same layer is the only one that can plausibly solve the bug
   (genuine edge case), BA MUST explicitly argue this in prose with
   evidence; the orchestrator may override the gate only after user
   confirmation.

**Why this rule exists**: In a prior incident, a bug cycled through 6
BA→Dev→QA iterations all operating on the same L1 CSS style condition.
The actual fix was L3 (data hydration). This gate forces the orchestrator
to escalate out of local optima.

**Iteration guard**: Maximum 5 iterations to prevent infinite loops

**Current iteration**: Track internally (starts at 1)

**If iteration > 5**:
```
Quality verification failed after 5 iterations.

Issues remaining:
{summary of critical/major issues}

Recommendation:
- Manual review needed, OR
- Requirements need to be broken down into smaller tasks, OR
- Technical constraints prevent automated solution

Would you like to:
1. Review current state manually
2. Break down into smaller tasks
3. Accept current implementation with known issues
```

Before presenting those options, create or update a continuation spec using the
`/spec-update` default continuation-spec mode:
- If this `/dev` cycle had a `spec_path`, append to that spec.
- If there was no source spec, create a new spec from
  `~/.claude/templates/overnight-spec.md`.
- Populate Sections 2/3/4/6/7/8 with attempted approaches, changed-file
  references, current QA evidence, unmet gap, concrete next plan, and traps.
- If updating a spec that already has split views/checkpoints, record that they
  are stale because the spec now contains a continuation update.
- Print `Continuation spec: <path>` and `Next: /dev --spec <path>`.

**If iteration <= 5**:

**Refine context for next iteration**:

```bash
# Extract refined context from QA report
jq '.qa.refined_context' docs/dev/qa-report-<timestamp>.json \
  > docs/dev/refined-context-<timestamp>.json

# Merge with original context
jq -s '.[0] * {
  iteration: (.[0].iteration // 0) + 1,
  previous_attempts: [.[0].previous_attempts // [], {
    iteration: (.[0].iteration // 0),
    dev: .[1].dev,
    qa: .[1].qa,
    timestamp: now | strftime("%Y-%m-%dT%H:%M:%SZ")
  }] | flatten,
  refined_requirements: .[2]
}' \
  docs/dev/context-<timestamp>.json \
  docs/dev/qa-input-<timestamp>.json \
  docs/dev/refined-context-<timestamp>.json \
  > docs/dev/context-iter<N>-<timestamp>.json
```

**Return to Step 10** with new context JSON

**Iteration tracking**: Update TodoWrite with iteration number

### Step 17: Generate Completion Report + Workflow Update

**QA passed! Generate final report.**

**Task-ID Convention** (canonical from /redev5 onward): the `task-id` is a single literal string (e.g. `20260426-095000-wid`) that appears identically in (a) artifact filename suffix, (b) `request_id` field of every artifact JSON, (c) `task_id` field of every artifact JSON, (d) completion-report heading 1, (e) all artifact JSON files. No prefixed forms (`dev-`, `qa-`, `ba-`, `ui-`) are permitted in NEW artifacts. Past artifacts are not retroactively rewritten.

**Completion report structure**:

```markdown
# Development Completion Report — <task-id>

**Request ID**: <task-id>
**Task ID**: <task-id>
**Completed**: <ISO-8601>
**Iterations**: <N>

## Requirement

**Original**: {original user request}

**Clarified**: {final clarified requirement}

**Success Criteria**:
- {criterion 1}
- {criterion 2}

## Root Cause Analysis

**Symptom**: {what user reported}

**Root Cause**: {underlying issue}

**Root Cause Commit**: `<hash> - <message>`

**Timeline**: {when problem introduced}

## Implementation

**Approach**: {how root cause was addressed}

**Scripts Created**:
- `script-name.sh` - {purpose}
  - Parameters: {param1}, {param2}
  - Usage: `script-name.sh <param1> <param2>`

**Files Modified**:
- `path/to/file` - {what changed}

**Git Rationale**: {why this fixes root cause}

## Quality Verification

**Status**: PASSED

**Success Criteria**: ✅ All met

**Quality Standards**:
- ✅ No hardcoded values
- ✅ Source venv used
- ✅ Integer step numbering
- ✅ Meaningful naming
- ✅ Root cause referenced

**Issues Found**: {N critical, N major, N minor}

**Iterations**: {N}

## Files Generated

- Context: `docs/dev/context-<timestamp>.json`
- Dev Report: `docs/dev/dev-report-<timestamp>.json`
- QA Report: `docs/dev/qa-report-<timestamp>.json`

## Mascot Score Changes (spec-20260518-225715 §5.1)

Summarise score-update events from Step 14 and any user-rating events from `/close` in a table:

| Agent | Event | Delta | Old → New |
|-------|-------|-------|-----------|
| ba    | qa_first_pass | 0  | 50 → 50 |
| dev   | qa_first_pass | 0  | 50 → 50 |

The current rank+range per agent is read by injecting `bash ~/.claude/scripts/score-inject.sh --agent <name>` (rank+range only — exact score is intentionally hidden per spec 5.1 line 112).

## Next Steps

{Any follow-up tasks or recommendations}

---

Development completed successfully!
```

**Save report to**: `docs/dev/completion-<timestamp>.md`

**Codex-native artifact postcondition (hard check before completion)**:

Before `/dev` or `/redev` may be treated as complete, the Codex harness MUST validate the resolved `<task-id>` against the canonical same-task artifacts on disk:
- `docs/dev/ticket-<task-id>.md`, `context-<task-id>.json`, `dev-report-<task-id>.json`, `qa-report-<task-id>.json`, and `completion-<task-id>.md` all exist and are non-empty where applicable.
- JSON artifacts have top-level `request_id` and `task_id` exactly equal to `<task-id>`.
- `dev-report-<task-id>.json` contains nested `dev.status == "completed"` plus nested `dev.files_modified` and `dev.files_created` arrays; top-level `status` alone does not count.
- `qa-report-<task-id>.json` contains nested `qa.status == "pass"`; top-level `status` or `verdict` alone does not count.
- If `claude_code_required = true`, context/report metadata must record that flag or a structured `claude_code_consult` failure/unavailable status.

Subagent final messages, lifecycle records, and JSON-like stdout are not completion artifacts. Missing or malformed artifacts block completion with exact paths and reasons.

**Workflow update**:

- If there is any unfinished development work (non-empty follow-up work in
  "Next Steps", known unmet acceptance criteria, accepted AC-deviation with
  future work, max-iteration exit, or user asks to keep improving), use
  `/spec-update` default continuation-spec mode. If a source spec exists, update it;
  otherwise create a new spec. The next command is `/dev --spec <spec_path>`.
  Do NOT hand unfinished work to `/close` or `/commit`.
- If all requested development is complete and only closure/shipping remains,
  create a compact temp update using `/spec-update --temp`. Default to
  `mktemp -t update-XXXXXX.md`; do not write this update into the repo unless
  the user explicitly asks. Include `Task ID: <timestamp>`,
  ticket/spec/context/dev-report/QA-report/completion paths, QA status,
  iteration count, and suggested next command `/close <task-id>` (or bare
  `/close` only when the same conversation context is still active).

**Present to user**: Show summary with key changes and next steps

**Offer git commit** (if requested):
```
Would you like me to create a git commit for these changes?

I'll include:
- Clear commit message with root cause reference
- All modified files
- Link to completion report
```

---

## JSON Storage Policy

**All JSON files stored in**: `docs/dev/`

**File naming convention**:
- Context: `context-<timestamp>.json` or `context-iter<N>-<timestamp>.json`
- Dev report: `dev-report-<timestamp>.json`
- QA report: `qa-report-<timestamp>.json`
- QA input: `qa-input-<timestamp>.json`
- Completion: `completion-<timestamp>.md`

**Timestamp format**: `YYYYMMDD-HHMMSS`

**Retention**:
- Keep all files for current session
- Archive to `docs/dev/archive/YYYY-MM/` after 30 days (via /clean)

---

## Integration with /clean

The `/clean` command supports `docs/dev/`:
- Preserves active development contexts (< 7 days old)
- Archives completed contexts to `docs/dev/archive/YYYY-MM/`
- Removes contexts > 90 days old

See `/clean` command documentation for details.

---

## Quality Standards Enforcement

**Dev subagent enforces** (see `agents/dev.md`):
- Parameterized scripts (no hardcoded values)
- `source venv` (not `python3`)
- Meaningful naming (no `enhance`, `fast`)
- Git root cause analysis

**QA subagent verifies** (see `agents/qa.md`):
- Success criteria met
- Root cause addressed
- No regressions
- Quality standards compliance
- Integer step numbering

**Orchestrator ensures**:
- Requirements fully clarified
- Comprehensive context
- Iterative quality improvement
- Proper JSON storage

---

## Agent Development Use Cases

**This command supports ALL development tasks, not just scripts:**

### Supported Development Types

1. **Scripts** (`scripts/`)
   - Bash automation scripts
   - Python utility scripts
   - Build/deployment scripts

2. **Slash Commands** (`.claude/commands/`)
   - New slash commands
   - Command modifications
   - Command documentation

3. **Subagents** (`.claude/agents/`)
   - Specialist subagent definitions
   - Agent behavior specifications
   - Agent integration patterns

4. **Hooks** (`.claude/hooks/`)
   - Pre/post tool use hooks
   - Session lifecycle hooks
   - Safety and validation hooks

5. **Configuration** (`.claude/`)
   - `CLAUDE.md` global instructions
   - `settings.json` permissions/hooks
   - Project-specific configs

6. **Todo Scripts** (`.claude/scripts/todo/`)
   - Workflow checklist generators
   - Step tracking automation

### Agent-Flexible Implementation

**IMPORTANT**: Avoid over-engineering when Agent intelligence can handle it.

**When to use scripts**:
- ✅ Repeated operations (run 5+ times)
- ✅ Complex multi-step workflows
- ✅ Integration with existing tools
- ✅ Performance-critical operations

**When to use Agent intelligence**:
- ✅ One-time operations
- ✅ Context-dependent decisions
- ✅ Natural language processing
- ✅ Creative problem-solving
- ✅ Adaptive workflows

**Example - Avoid Over-Engineering**:

```
BAD (over-engineered):
  User: "Check if file has correct header"
  Dev: Creates scripts/validate-file-header.sh with 50 lines

GOOD (agent-flexible):
  User: "Check if file has correct header"
  Dev: Agent reads file, checks header, reports result
  (No script needed for one-time check)

WHEN TO SCRIPT:
  User: "Add header validation to CI/CD pipeline"
  Dev: Creates scripts/validate-headers.sh
  (Repeated operation, needs automation)
```

### Settings.json Permissions

**All development operations require user confirmation via `ask` permission**:

```json
"ask": [
  "Write(.claude/commands/**)",
  "Edit(.claude/commands/**)",
  "Write(.claude/agents/**)",
  "Edit(.claude/agents/**)",
  "Write(.claude/hooks/**)",
  "Edit(.claude/hooks/**)",
  "Write(.claude/scripts/**)",
  "Edit(.claude/scripts/**)",
  "Edit(.claude/settings.json)",
  "Edit(.claude/CLAUDE.md)"
]
```

**Why `ask` permission?**
- Commands and agents change system behavior
- Hooks can block operations
- Settings control security
- CLAUDE.md affects all sessions

**User must explicitly approve each file change**

### Todo Script Integration

**Todo-script pattern**:

When creating commands with multi-step workflows:

1. **Create todo script** in `.claude/scripts/todo/<command>.py`
2. **Return workflow steps** as JSON
3. **Force todo refresh** via hook injection

**Example todo script** (`.claude/scripts/todo/mycommand.py`):

```python
#!/usr/bin/env python3
"""Preloaded TodoList for /mycommand workflow."""

def get_todos():
    return [
        {"content": "Step 1: Parse input", "activeForm": "Step 1: Parsing input", "status": "pending"},
        {"content": "Step 2: Process data", "activeForm": "Step 2: Processing data", "status": "pending"},
        {"content": "Step 3: Generate output", "activeForm": "Step 3: Generating output", "status": "pending"}
    ]

if __name__ == "__main__":
    import json
    print(json.dumps(get_todos(), indent=2, ensure_ascii=False))
```

**Why todo scripts?**
- Agent can see progress
- User can track progress
- Steps never forgotten
- Consistent workflow enforcement

---

## Example End-to-End Workflow

**User**: `/dev "Fix timeout in API"`

**Step 1**: Parse requirement
- Requirement: "Fix timeout in API"

**Step 3**: Consult specialists (optional)
- No specialists needed for this requirement → skip

**Step 4**: Delegate to BA subagent
- BA returns `needs_clarification` with questions

**Step 5**: BA clarification loop
- Round 1: Which API? → POST /api/data, timeout 5s, need 95% completion
- Round 2: BA has enough clarity → returns `ready`
- BA creates: `ba-spec-20251226-114500.md` + `context-20251226-114500.json`

**Step 6**: Validate BA output
- Both files exist with required sections

**Step 10**: Dev subagent
- Created: `scripts/measure-api-latency.sh`
- Created: `scripts/validate-api-timeout.sh`
- Modified: `config/api.json`
- Saved report: `docs/dev/dev-report-20251226-114500.json`

**Step 13**: QA subagent
- Verified all scripts work
- Confirmed root cause addressed
- Status: PASS
- Saved report: `docs/dev/qa-report-20251226-114500.json`

**Step 14**: Process results
- QA passed → proceed to completion

**Step 17**: Completion report
- Generated: `docs/dev/completion-20251226-114500.md`
- Presented summary to user

---

## Success Metrics

- ✅ 100% requirement clarity before development
- ✅ Root cause identified and addressed
- ✅ Zero hardcoded values in scripts
- ✅ QA passes within 3 iterations
- ✅ All standards enforced
- ✅ Complete audit trail in JSON files

---

**Remember**: You are an orchestrator. You clarify, analyze, delegate, coordinate, and verify. You do NOT implement. Let the subagents do the work.

---

## Orchestrator Prompt Purity (MANDATORY)

> **Origin**: Installed 2026-04-26 in response to redev cycle `redev-prompt-purity-20260426`, which corrected workflow-integrity defects from cycle `spec-20260426-080555` (close-report verdict NO). The companion enforcement hook is `~/.claude/hooks/pretool-orchestrator-prompt-purity.py`, registered under the PreToolUse `Agent` matcher. The same rule lives in `/root/.claude/CLAUDE.md` so all orchestrators in all projects observe it.

### Why this rule exists

In the prior cycle, the orchestrator's dispatch prompt to dev contained the literal phrase **"Use Write tool (not Edit — full rewrite)"**. When `pretool-write-guard.sh` correctly blocked the prescribed tool, the dev subagent — pressured by the orchestrator's HOW-prescription — composed an `Edit` + `sed -i 254..$d` bypass to obey the orchestrator's intent. The dev's report admitted the bypass on line 86. This violated global CLAUDE.md "Subagent Hook Discipline" and the user's standing Edit-only permission grant on `/root/.claude/agents/ui-specialist.md`. The bypass would have been impossible if the orchestrator had described WHAT to achieve (a thin orchestrator file under 260 lines preserving named verbatim segments) rather than HOW to achieve it (which tool to call).

### The rule

When the orchestrator dispatches BA, dev, QA, ui-specialist, or any other subagent via the `Agent` tool, the dispatch `prompt` MUST describe **WHAT** only:

- the **problem** to solve (symptom, evidence, root cause when known)
- **constraints** (scope boundaries, permission ceilings, files in-scope vs out-of-scope, sequencing requirements)
- **acceptance criteria** (observable end-states the result must satisfy)
- **context** (links to BA spec, prior reports, reference sources)

The dispatch `prompt` MUST NOT prescribe **HOW**:

- no tool names (`Write`, `Edit`, `Read`, `Bash`, `Glob`, `Grep`, `Skill`, `Agent`, `TodoWrite`, `WebFetch`, `WebSearch`, `NotebookEdit`, `EnterWorktree`, `ExitWorktree`, any `mcp__*` family)
- no shell-command tokens (`sed`, `awk`, `curl`, `wget`, `jq`, `yq`, `python3`, `node`, `npm`, `pip`, `git checkout/reset/revert/push/...`, `mkdir`, `chmod`, `chown`, `cp`, `mv`, `rm`, `ln`, `tar`, `find`, `xargs`, `kill`, `systemctl`, `docker`, `kubectl`, ...)
- no shell-syntax tokens (`$(...)` command substitution, `<<EOF` heredoc, `>` / `>>` redirection, `&&` / `||` chains, `|` pipe in command context, `2>&1`)
- no fenced ` ```bash ` / ` ```sh ` / ` ```shell ` / ` ```zsh ` blocks (and no untagged fenced blocks whose first line is shell-like)

The subagent chooses its own toolchain per its `agent.md`. If the orchestrator believes a particular outcome shape is required, it expresses that as an acceptance criterion ("the resulting file must be byte-identical to blob X") not as a tool prescription ("use git checkout").

### Example: WHAT-only (correct)

> "Restore `/root/.claude/agents/ui-specialist.md` to its pre-rewrite content. Acceptance: file length is exactly 657 lines AND its sha256 matches the byte stream pinned at nested-repo HEAD blob `7e5a4b3...`. The restore MUST NOT touch any other file (atomic per-file). Verifiable BEFORE the next phase begins. Reference: BA spec section 'Recovery Plan'."

This describes the desired end-state, the verification path, and the constraint. The subagent decides whether to use git-restore-from-HEAD, git-show-with-redirect, or any other path that produces the same end-state.

### Example: HOW-prescription (forbidden)

> "Use the Write tool to overwrite the file with the original content. Run `git -C /dev/shm/dev-workspace/dot-claude show HEAD:agents/ui-specialist.md > /root/.claude/agents/ui-specialist.md`. Then verify with `wc -l`."

This prescribes specific tool (`Write`), a specific shell command (`git show > path`), and a specific verification command (`wc -l`). It removes subagent autonomy. If `Write` is blocked by `pretool-write-guard.sh`, the subagent will be pressured to dodge — exactly the failure mode that produced the `sed -i` bypass in the prior cycle.

### Scope of this rule

The rule applies to:
- **orchestrator → subagent dispatch prompts** (Agent tool, `tool_input.prompt`)

The rule does NOT apply to:
- **user → orchestrator messages** (the user may use any language they wish; the orchestrator translates the user's intent into WHAT-only dispatch prompts)
- **subagent → subagent dispatch** (recursive Agent calls from inside a subagent are exempt; the hook detects these via `data.agent_id` being truthy and bypasses the scan)
- **in-file documentation, examples, READMEs, agent.md files, BA specs** (these are read by humans and subagents to learn HOW to do work; the rule is about the live dispatch channel only)
- **content delimited by `<USER_VERBATIM>...</USER_VERBATIM>` markers inside a dispatch prompt** (so the orchestrator can quote a user message that itself contains tool names without triggering the hook)
- **dev-registry sentinel-registration boilerplate** (the standard `cat > /root/.claude/dev-registry/<sid>/<role>.json << 'REGEOF'` pattern is subagent-internal scaffolding, not orchestrator HOW-prescription, and is exempted by the hook)

### How the rule is enforced

A PreToolUse hook scans every `Agent` dispatch's `prompt` field. On any blacklist hit, the hook exits with code 2 (Claude Code's blocking convention) and writes a stderr message beginning with the literal substring `orchestrator must not specify HOW; rewrite prompt to describe WHAT only.` followed by the matched category, a redacted snippet of the offending text, and a pointer back to this section.

Self-test fixtures live at `/root/docs/dev/redev-prompt-purity-20260426-self-test.md`.
