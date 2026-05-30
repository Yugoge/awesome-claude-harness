---
description: Enhanced development workflow with BA subagent delegation, command development best practices, Three-Party Architecture, and comprehensive automation patterns
disable-model-invocation: true
---

> Code-writing tasks (.svg/.css/.html/.js/.ts/.py/...) go to `dev`. Specialists, BA, and QA produce .md/.json only.

**CRITICAL**: Use TodoWrite to track workflow phases. Mark in_progress before each step, completed immediately after.

# Development Orchestrator for Command Development

**Philosophy**: Understand requirement fully → Find root cause → Delegate implementation → Verify quality → Iterate until perfect

This command uses multi-round inquiry to fully understand requirements, then orchestrates development through specialized subagents with continuous QA verification. Enhanced with proven command development patterns from successful implementations.

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

## Command Development Best Practices

The full tutorial — Three-Party Architecture, specialist subagent design, todo workflow scripts, the three-hook checklist enforcement chain, YAML frontmatter rules (including the 2026-04-25 `/redev` empty-body incident postmortem), complete automation patterns, script parameterization, the subagent-call enforcement gate, and the command-quality-audit case study — lives in `/root/docs/dev/command-development-patterns.md`. Read that document before authoring or editing slash commands, subagents, or todo scripts. The patterns there are normative for this orchestrator and any new commands it spawns.

---

## Implementation

### Step 1: Parse Development Requirement

Extract requirement from `$ARGUMENTS`:

```
Requirement: "$ARGUMENTS"
```

**Parse `--codex`**: If `$ARGUMENTS` contains the literal token `--codex` (in any position), strip it from the requirement text and set `codex_required = true`. Otherwise set `codex_required = false` (default). When `codex_required = true`, every BA / QA / dev dispatch prompt below MUST include the literal line `codex_required: true` so the subagent's opt-in codex consultation block (`agents/<role>.md` § Codex adversarial consultation) activates. When `codex_required = false`, do NOT include that line — subagents skip codex consultation and emit `codex_consult: { invoked: false, status: "not_requested" }` in their output.

**Codex suppression guardrail**: When `codex_required: true` is included in any subagent dispatch prompt, the orchestrator MUST NOT include any pre-populated `codex_consult` field or object in that same prompt. Setting `codex_required: true` and simultaneously pre-answering `codex_consult` contradicts the flag and silently suppresses Codex consultation.

**Parse `--spec`**: If `$ARGUMENTS` contains `--spec <path>`, extract the path and remove the flag from the requirement text. Store as `spec_path`.

**Auto-detect spec**: If `--spec` is NOT provided, scan `docs/dev/specs/*.md` sorted by modification time (newest first). If a file exists, set `spec_path` to that path and announce:
```
Auto-detected spec: <path>
(Created by /spec — pass --spec <other-path> to override.)
```

If no spec found, set `spec_path = null`. All downstream behavior is unchanged when `spec_path` is null.

**Detect views folder (via the centralized resolver — do NOT re-derive paths inline)**:

If `spec_path` is not null, call the single canonical resolver and consume its stdout JSON; never compute `views_dir` / `split_marker` / the spec-id from `spec_path` by hand (that prefix drift silently dropped de-prefixed specs to monolith mode):

```bash
if [ -n "$spec_path" ]; then
  RESOLVED_JSON=$(/root/.claude/scripts/resolve-spec-artifacts.py \
      --spec-path "$spec_path" --project-dir "$CLAUDE_PROJECT_DIR") || {
    echo "spec-artifact resolution FAILED (path mismatch / present-but-invalid split). Re-finalize /spec before relying on per-agent views." >&2
    exit 1; }   # loud-fail guard: a present-but-invalid split never silently degrades to monolith mode
  ARTIFACT_ID=$(jq -r .artifact_id      <<<"$RESOLVED_JSON")
  VIEWS_AVAILABLE=$(jq -r .views_available <<<"$RESOLVED_JSON")
  MANIFEST_PATH=$(jq -r '.manifest_path // empty' <<<"$RESOLVED_JSON")
  VIEWS_DIR=$(jq -r '.views_dir // empty'        <<<"$RESOLVED_JSON")
  CP_DIR=$(jq -r '.cp_dir // empty'              <<<"$RESOLVED_JSON")
fi
```

When `VIEWS_AVAILABLE` is `true`, read `view_paths` from `$MANIFEST_PATH` (`views` map of agent → path). The resolver returns `views_available=false` with exit 0 for a genuinely legacy spec with no split artifacts — those are fully supported, the monolith path alone is passed to subagents with no checkpoint enforcement.

Pass per-agent view paths alongside (not in place of) `spec_path` to subagents so each receives only its slice of the 8-section monolith.

**Edge cases**:
- Empty `$ARGUMENTS` → Prompt user for requirement
- Otherwise → Pass raw text (minus --spec flag) to BA subagent in Step 2

**Keep this step lightweight** - BA subagent handles all analysis.

**Initialize dev-registry for hard subagent enforcement** (MANDATORY — do this before ANY Agent launch):

The hook `pretool-subagent-code-block.py` blocks non-`dev` subagents from writing code files, but it needs the Claude-internal subagent UUID to be registered against an `agent_type`. Root cause of the /dev gap (see commit `e086ccb`): /dev-command sessions produce no `.claude/specs/` cp-state files, so the hook falls open and every subagent can write code. The fix is an orchestrator-provided sentinel file that the subagent reads as its FIRST ACTION; `pretool-cp-checkin.py` then writes the UUID→agent_type mapping into `.claude/dev-registry/agent-index.json`.

**Initialize dev-registry (hook pre-done)**:

The `UserPromptSubmit` hook has already:
1. Generated `DEV_SESSION_ID` (shown in hook output as `DEV_SESSION_ID pre-initialized by hook: …`)
2. Created `.claude/dev-registry/<DEV_SESSION_ID>/` with per-agent sentinel files
3. Written `docs/dev/user-requirement-<DEV_SESSION_ID>.md` with the verbatim user requirement
4. Run `write-e2e-enforce.sh` — E2E enforcement is ACTIVE
5. Run `write-codex-enforce.sh` (if `--codex` was passed)

**Read `DEV_SESSION_ID` from the hook output above.** Store it for use in every Agent launch prompt below.

**Fallback** (if hook output absent):
```bash
DEV_SESSION_ID="dev-command-$(date +%Y%m%d-%H%M%S)"
REGISTRY_DIR="$CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID"
mkdir -p "$REGISTRY_DIR"
for agent in \
    architect ba cleaner cleanliness-inspector dev git-edge-case-analyst \
    pm product-owner prompt-inspector qa rule-inspector style-inspector \
    test-executor test-validator ui-specialist user; do
  printf '{"agent_type": "%s", "session_id": "%s"}\n' "$agent" "$DEV_SESSION_ID" \
    > "$REGISTRY_DIR/$agent.json"
done
```

**Write verbatim user requirement document** (hook pre-done): The hook has already written `docs/dev/user-requirement-<DEV_SESSION_ID>.md` with the verbatim user requirement. Read `User requirement document:` from the hook output to get the path. **Fallback** (if hook absent): write the file manually per the bash heredoc pattern in the dev.md fallback block.

**E2E and Codex enforcement** (hook pre-done): The hook has already called `write-e2e-enforce.sh` and (if `--codex`) `write-codex-enforce.sh`. Both enforce flags are active. **Fallback** (if hook absent): call the scripts manually:
```bash
scripts/write-e2e-enforce.sh --source-command dev-command --session-id $DEV_SESSION_ID
# Only when --codex:
# scripts/write-codex-enforce.sh --source-command dev-command --session-id $DEV_SESSION_ID
```

Store `$DEV_SESSION_ID` for use in every Agent launch prompt below. Every Agent launch prompt MUST begin with a `FIRST ACTION` line instructing the subagent to `Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/<agent>.json` before any other tool call. Without that Read, the enforcement hook will fail open for that subagent.

**Initialize cp-state handoff when a `/spec` view exists** (MANDATORY when `views_available=true`):

Reuse the resolver output from the views-detection step — do NOT re-derive the
spec-id from `spec_path`. The cp-state directory is exactly the resolver's `cp_dir`:

```bash
if [ -n "$spec_path" ] && [ -d "$CLAUDE_PROJECT_DIR/$CP_DIR" ]; then
  SPEC_ID="$ARTIFACT_ID"          # resolver's canonical artifact id
else
  SPEC_ID=""                       # no cp-state dir -> skip SECOND ACTION below
fi
```

If no cp-state directory exists, set `SPEC_ID=""` and skip the `SECOND ACTION`
lines below. If a particular agent has no cp-state file under that SPEC_ID, omit that
agent's `SECOND ACTION` for this launch. When `SPEC_ID` is non-empty, every Agent launch prompt for an agent that has a
cp-state file MUST include a `SECOND ACTION` line immediately after the dev-registry `FIRST ACTION`:

```text
SECOND ACTION: Read $CLAUDE_PROJECT_DIR/$CP_DIR/cp-state-<agent>.json to load your mandatory checklist before doing substantive work. Mark each completed checkpoint with /root/.claude/scripts/spec-check.py mark --spec-id <SPEC_ID> --agent <agent> --agent-id $CLAUDE_AGENT_ID --cp-id <cp-NN>. Waive only with /root/.claude/scripts/spec-check.py waive --spec-id <SPEC_ID> --agent <agent> --agent-id $CLAUDE_AGENT_ID --cp-id <cp-NN> (auto-text records actor + ISO timestamp). You MUST leave zero pending checkpoints before Stop (a discipline expectation tracked via spec-check.py — no hook blocks exit on pending checkpoints today). If `$CLAUDE_AGENT_ID` is unavailable, use the `agent_id` value written into the cp-state file by the read.
```

This is the checklist-stop handoff: dev-registry handles role registration for
write-policy, while cp-state handles required atomic actions for Stop enforcement.

**Graphify pre-BA Bash hydrator** (between Step 1 and Step 2, mirrors commands/dev.md):

Run `scripts/graphify-query.py` as a direct Bash call to inject structural context before BA analysis. Advisory — skips silently when binary absent. Output: `.claude/dev-registry/$DEV_SESSION_ID/graphify/pre_query.json`. When `status=ok` or `status=degraded`, include the pre_query.json reference in the BA dispatch prompt. See `commands/dev.md` graphify hydrator block for the canonical Bash invocation.

### Step 2: Specialist Consultation (always evaluate, never silently skip)

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
  CHECKPOINT MARKING: see agents/<specialist-name>.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the <specialist-name> specialist. Follow .claude/agents/<specialist-name>.md.

  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md
  (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

  Requirement: '<requirement from Step 1>'

  Provide your observations and analysis relevant to this requirement.
  Return structured findings that will inform the BA analysis.
  DO NOT modify files. Return observations only.
  "
```

Pass all specialist findings (and the full `specialists_assessed` block) to the BA subagent in Step 3 as additional context.

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

- **Retry phrasing** in user text: "again", "still", "didn't fix", "Nth time"
- **Recent related commits**: `git log --oneline --grep="<keyword>" -20`
- **Existing BA specs**: files matching `docs/dev/ticket-*.md` (or legacy `docs/dev/ba-spec-*.md`) with
  keywords from the current request

Pass findings to BA in the delegation prompt under an explicit
`prior_attempt_signals` block:

    prior_attempt_signals:
      retry_phrase: "<matched phrase or null>"
      recent_commits: ["<hash> <subject>", ...]
      existing_specs: ["docs/dev/ticket-<ts>.md", ...] (legacy historical artifacts also accepted: docs/dev/ba-spec-<ts>.md)

### Post-BA: verify contract compliance

Before proceeding to dev, verify the BA JSON context contains:

- `evidence.measured.value` populated (not null, not empty string)
- `evidence.expected.source` populated
- `scope_expansion.all_occurrences` non-empty (or scope_expansion explicitly
  marked `not_applicable` with reason)
- `reference_source.tier` not `tier_3_tainted` when `copy_allowed: true`
- If Contract D triggered: `prior_attempts.novelty_check.differs_from_all_priors = true`

If any check fails, the orchestrator re-delegates to BA with explicit
feedback naming the missing field. Do NOT proceed to dev with an
incomplete spec.

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

### Step 3: Delegate to BA Subagent

**Use Task tool to invoke BA subagent for requirements analysis and context building**:

```
Use Task tool with:
- description: "Analyze requirement and build development context"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/ba.json to register with the enforcement system. Do this BEFORE any other tool call.
  CHECKPOINT MARKING: see agents/ba.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the BA subagent. Follow .claude/agents/ba.md instructions precisely.

  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md
  (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

  Requirement: '<requirement from Step 1>'
  Clarification round: 0
  Previous answers: null
  Codebase hints: <any file paths mentioned by user, or null>
  Timestamp: <YYYYMMDD-HHMMSS>
  Spec file: <spec_path or null>
  View file: <view_paths[this-agent] or null — sibling views/<agent>.md if present>
  Prior attempt signals:
    retry_phrase: <matched phrase or null>
    recent_commits: [<hash> <subject>, ...]
    existing_specs: [docs/dev/ticket-<ts>.md, ...] (legacy historical artifacts also accepted: docs/dev/ba-spec-<ts>.md)

  If Spec file is not null: Read the spec file FIRST. Use Section 5 (User's Acceptance Criterion) as the primary requirement source. Use Sections 1-4 as baseline context. If Section 7 (What Must Be Done) is populated, treat it as prescriptive guidance.

  Goal: Translate the user's request into the smallest, safest, most-precise change set that lands the user-need, per spec-20260503-091826.md Section 5.1: the implementation approach is the minimum, safest, most-perfect, most-deterministic realization of user needs, not an expansion of fix scope; all work centers on user needs. Ground your analysis in the existing codebase patterns (align with current functionality rather than re-inventing). For bugs, find the root cause; for enhancements, research best practices via web search / explore / analyst agents per agents/ba.md Section 5.3 mission. Path-external observations go into the spec's `out_of_scope_observations` chapter (per agents/ba.md), not into the fix scope. Use the existing 5-dimension clarity scoring (What/Why/Where/Scope/Success) to gate `needs_clarification`. Produce both deliverables (ticket-<timestamp>.md per spec-20260503-091826 M4 ba-spec→ticket rename, plus context-<timestamp>.json) following agents/ba.md Output Formats.

  Explicit task-id printing: include the literal line `TASK-ID: <timestamp>` in your stdout response so close.md / commit.sh task-id-chain confirmation has an unambiguous anchor for this BA dispatch.

  Return JSON with status, file paths, summary, and the task-id echo.
  "
```

**Wait for BA subagent completion** before proceeding.

### Step 4: BA Clarification Loop

**If BA returns `status: "needs_clarification"`**:

1. Present BA's questions to user (relay verbatim)
2. Collect user answers
3. Re-invoke BA with answers:

```
Use Task tool with:
- description: "Continue BA analysis with clarification answers"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/ba.json to register with the enforcement system. Do this BEFORE any other tool call.
  CHECKPOINT MARKING: see agents/ba.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the BA subagent. Follow .claude/agents/ba.md instructions precisely.

  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md
  (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

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
- If BA returns `status: "ready"`, proceed to Step 5

**If BA returns `status: "ready"` on first invocation**: Skip to Step 5.

### Step 5: Validate BA Output

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

**If validation fails**:
- Re-invoke BA with specific feedback about what's missing
- Maximum 2 re-invocations for validation fixes

**If validation passes**: Proceed to Step 6

### Step 6: QA Validates BA Conclusions

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
  CHECKPOINT MARKING: see agents/qa.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the QA subagent in BA-VALIDATION MODE. This is NOT code verification.
  You are verifying the QUALITY OF BA's ANALYSIS, not any implementation.

  DO NOT: build, deploy, open browser, run Playwright, or test code.
  DO: read BA's deliverables and challenge every claim.

  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md
  (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

  BA spec file: docs/dev/ticket-<timestamp>.md (legacy: docs/dev/ba-spec-<timestamp>.md)
  Context JSON: docs/dev/context-<timestamp>.json
  Spec file: <spec_path or null>
  View file: <view_paths[this-agent] or null — sibling views/<agent>.md if present>

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

  Write report to: docs/dev/ba-qa-report-<timestamp>.json
  "
```

**Process QA result**:

```
IF verdict == "pass":
  -> BA conclusions validated. Proceed to Step 8.

ELIF verdict == "fail":
  -> Proceed to Step 7 for BA-QA iteration.
```

### Step 7: BA-QA Iteration Loop (if QA rejects BA)

**Iteration guard**: Maximum 3 BA-QA iterations to prevent infinite loops

**Current BA-QA iteration**: Track internally (starts at 1)

**If BA-QA iteration > 3**:
```
BA-QA validation: 3 iterations exhausted. Proceeding with best-effort BA output.

Unresolved objections:
{summary of remaining QA objections}

Appending unresolved objections to context JSON under `ba_qa_unresolved_objections`.
Proceeding to Step 8 with documented assumptions.
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
  CHECKPOINT MARKING: see agents/ba.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the BA subagent. Follow .claude/agents/ba.md instructions precisely.

  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md
  (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

  Your previous analysis was REJECTED by QA. Address each objection below
  with concrete evidence. Do not argue -- investigate and provide proof.

  Original requirement: '<requirement>'
  Previous BA spec: docs/dev/ticket-<timestamp>.md (legacy: docs/dev/ba-spec-<timestamp>.md)
  Previous context: docs/dev/context-<timestamp>.json
  Spec file: <spec_path or null>
  View file: <view_paths[this-agent] or null — sibling views/<agent>.md if present>

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

**After BA re-delivers**: Return to Step 5 (validate BA output), then Step 6 (QA re-validates).

**Rule**: Every BA invocation MUST be followed by QA validation. No exceptions.

**Iteration tracking**: Update TodoWrite with BA-QA iteration number.

**Graphify enrichment** (between Step 7 and Step 8, mirrors commands/dev.md):

After BA-QA validation passes, dispatch the graphify subagent (mode=enrich) to extract a focused subgraph and patch the context JSON with `graph_context`. Advisory — if graphify is unavailable or returns status=skipped, proceed to Step 8 without delay. See `commands/dev.md` graphify enrichment block for the canonical dispatch prompt template.

### Step 8: Delegate to Dev Subagent

**Use Task tool to invoke dev subagent with file paths only**:

```
Use Task tool with:
- description: "Implement development changes based on BA context"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/dev.json to register with the enforcement system. Do this BEFORE any other tool call.
  CHECKPOINT MARKING: see agents/dev.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the dev subagent. Follow agents/dev.md instructions precisely.

  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md
  (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

  Context file: docs/dev/context-<timestamp>.json
  BA spec file: docs/dev/ticket-<timestamp>.md (legacy: docs/dev/ba-spec-<timestamp>.md)
  Spec file: <spec_path or null>
  View file: <view_paths[this-agent] or null — sibling views/<agent>.md if present>
  Write your implementation report to: docs/dev/dev-report-<timestamp>.json

  If Spec file is not null: Read the spec file FIRST for context. After implementation, update the spec: Section 2 (What Was Attempted) with your approach and rationale. Section 3 (What Was Changed) with exact file:line edits.
  "
```

**Wait for dev subagent completion** before proceeding.

### Step 9: Validate Dev Implementation

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

**If dev completed**: Proceed to Step 10

### Step 10: Delegate to QA Subagent

**Before dispatching QA, write qa_mode sentinel**:

```bash
bash ~/.claude/scripts/write-qa-mode.sh --session-id "$DEV_SESSION_ID" --mode final_verification \
  || { echo 'ERROR: Failed to set qa_mode=final_verification in qa.json — aborting' >&2; exit 1; }
```

**Use Task tool to invoke QA subagent with file paths only**:

```
Use Task tool with:
- description: "Verify implementation quality against standards"
- prompt: "
  FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/qa.json to register with the enforcement system. Do this BEFORE any other tool call.
  CHECKPOINT MARKING: see agents/qa.md §Checkpoint Marking Contract. Mark every cp-NN done or waived before Stop or SubagentStop hook will block exit.

  You are the QA subagent. Follow agents/qa.md instructions precisely.

  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md
  (Read this file before interpreting Requirement, Context file, BA spec, Dev report, or state-derived focus.)

  Context file: docs/dev/context-<timestamp>.json
  Dev report file: docs/dev/dev-report-<timestamp>.json
  BA spec file: docs/dev/ticket-<timestamp>.md (legacy: docs/dev/ba-spec-<timestamp>.md)
  Spec file: <spec_path or null>
  View file: <view_paths[this-agent] or null — sibling views/<agent>.md if present>
  Write your verification report to: docs/dev/qa-report-<timestamp>.json

  If Spec file is not null: Read the spec file FIRST. After verification, update the spec: Section 4 (Current State) with measured values. If verdict is fail, also update Section 6 (Why Not Met) and Section 7 (What Must Be Done) with prescriptive next steps.
  "
```

**Wait for QA subagent completion** before proceeding.

### Step 11: Process QA Results

Read QA report: `docs/dev/qa-report-<timestamp>.json`

**Decision tree**:

```
IF qa.status == "pass":
  → Proceed to Step 12 (Update Permissions)

ELIF qa.status == "warning":
  → Check if minor issues acceptable
  → If yes: Proceed to Step 12 (Update Permissions)
  → If no: Proceed to Step 13 (Iteration)

ELIF qa.status == "fail":
  → Proceed to Step 13 (Iteration)
```

### Step 12: Update Settings.json Permissions

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
   - `"Bash(source ~/.claude/venv/bin/activate && python ~/.claude/scripts/todo/<script>.py:*)"`

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

### Step 13: Iteration Loop (if QA fails)

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

**Return to Step 8** with new context JSON

**Iteration tracking**: Update TodoWrite with iteration number

### Step 14: Generate Completion Report

**QA passed! Generate final report.**

**Completion report structure**:

```markdown
# Development Completion Report

**Request ID**: dev-<timestamp>
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
- ✅ Command development patterns applied

**Issues Found**: {N critical, N major, N minor}

**Iterations**: {N}

## Files Generated

- Context: `docs/dev/context-<timestamp>.json`
- Dev Report: `docs/dev/dev-report-<timestamp>.json`
- QA Report: `docs/dev/qa-report-<timestamp>.json`

## Next Steps

{Any follow-up tasks or recommendations}

---

Development completed successfully!
```

**Save report to**: `docs/dev/completion-<timestamp>.md`

**Workflow update**:

- If there is any unfinished development work (non-empty follow-up work in
  "Next Steps", known unmet acceptance criteria, or max-iteration exit), use
  `/spec-update` default continuation-spec mode. If a source spec exists, update it;
  otherwise create a new spec. The next command is `/dev --spec <spec_path>`.
  Do NOT hand unfinished work to `/close` or `/commit`.
- If all requested development is complete and only closure/shipping remains,
  create a compact temp update using `/spec-update --temp`. Include `Task ID: <timestamp>`,
  artifact paths (ticket, context, dev-report, QA-report, completion), QA status,
  iteration count, and suggested next commands: `/close <task-id>` → `/commit <task-id>` → `/push`.

**Present to user**: Show summary with key changes and next steps. Suggest `/close <task-id>` as the next action.

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
- Command development patterns

**QA subagent verifies** (see `agents/qa.md`):
- Success criteria met
- Root cause addressed
- No regressions
- Quality standards compliance
- Integer step numbering
- Command patterns applied correctly

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

---

## Example End-to-End Workflow

**User**: `/dev-command "Create /analyze command that uses specialist subagent"`

**Step 1**: Parse requirement
- Requirement: "Create /analyze command that uses specialist subagent"

**Step 2**: Consult specialists (optional)
- No specialists needed → skip

**Step 3**: Delegate to BA subagent
- BA returns `needs_clarification` with questions about metrics and output format

**Step 4**: BA clarification loop
- Round 1: What metrics? → Complexity, maintainability, test coverage
- BA has enough clarity → returns `ready`
- BA creates: `ba-spec-20260206-120000.md` + `context-20260206-120000.json`

**Step 5**: Validate BA output
- Both files exist with required sections

**Step 8**: Dev subagent
- Created: `.claude/commands/analyze.md` (with YAML frontmatter)
- Created: `.claude/agents/code-analyzer.md` (specialist)
- Created: `.claude/scripts/todo/analyze.py` (workflow tracker)
- Applied: Three-Party Architecture pattern
- Applied: Complete Automation pattern
- Saved report: `docs/dev/dev-report-20260206-120000.json`

**Step 9-10**: QA subagent
- Verified YAML frontmatter complete
- Verified specialist returns JSON only
- Verified todo script works
- Verified all patterns applied correctly
- Status: PASS
- Saved report: `docs/dev/qa-report-20260206-120000.json`

**Step 11**: Process results
- QA passed → proceed to completion

**Step 12**: Update permissions
- Added: `SlashCommand(.claude/commands/analyze.md:*)`
- Added: `Bash(source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/todo/analyze.py:*)`

**Step 14**: Completion report
- Generated: `docs/dev/completion-20260206-120000.md`
- Presented summary to user

---

## Success Metrics

- ✅ 100% requirement clarity before development
- ✅ Root cause identified and addressed (when applicable)
- ✅ Zero hardcoded values in scripts
- ✅ QA passes within 3 iterations
- ✅ All command development patterns applied
- ✅ All standards enforced
- ✅ Complete audit trail in JSON files

---

**Remember**: You are an orchestrator. You clarify, analyze, delegate, coordinate, and verify. You do NOT implement. Let the subagents do the work.
