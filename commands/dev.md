---
description: Orchestrated development workflow with BA subagent delegation, parallel agent execution, and iterative QA verification. Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
argument-hint: "[--codex] [--spec <path>] <requirement>"
disable-model-invocation: true
summary: "Build a requirement end to end: ask you first, then BA finds the root cause, QA checks it, dev builds in parallel one-issue lanes, QA verifies until it passes."
group: Develop
---

> Code (.svg/.css/.html/.js/.ts/.py/...) goes to `dev`; specialists, BA and QA write .md/.json only.

# Development Orchestrator

Track the steps with TodoWrite: mark a step `in_progress` before any dispatch under it and `completed` right after it.

## Core Workflow

The orchestrator does no analysis, context building or implementation: BA asks the owner first (the requirement round, Step 4), then analyses (all clarification goes through BA) into a Markdown spec plus a JSON context under `docs/dev/`, dev implements, QA verifies. A BA or dev question artifact is relayed to the owner with one AskUserQuestion (Step 5), only for a real, specific decision that the request, the code or a sensible default cannot settle; a question never stops or ends the cycle.

**Hook rejection (a process step, never a terminal):** neither the orchestrator nor any subagent retries, disguises or circumvents a hook-rejected operation (no other tool, wrapper or script for it). The subagent reports the rejected command and the hook's output (in its report, or in its producer question artifact when the operation needs the owner's decision). When the operation is needed, the orchestrator asks the owner one specific AskUserQuestion inside the turn that names the operation and the exact command: that is the pause, and it releases no gate. The answer authorizes no retry. An operation refused by a hook that reads `/allow` grants (`hooks/pretool-git-privilege-guard.py`, `hooks/pretool-block-branch-pr-worktree.py`) runs again only after the owner's `/allow` grant for it, typed as their own prompt (an AskUserQuestion answer writes no grant), which lets it through once; one refused by a hook that reads none (`hooks/pretool-tool-policy.py`) is not run again in this session: it is withdrawn. The orchestrator then re-dispatches that lane's role (same subagent_type, task_id, lane and obligation template, a fresh dispatched_at) with the outcome: it runs the granted command once, or, when the owner declines or the operation is withdrawn, goes on without it, which Subagent Hook Discipline #4 allows only while every acceptance criterion stays achievable without it (the question names any criterion that needs the operation, and the owner's answer decides that criterion, not the operation). A decline never ends the cycle: it continues to completion.

## Requirement Decomposition & Fan-Out

A single `/dev` cycle may carry more than one requirement. The orchestrator fans them out to N parallel one-issue lanes inside the SAME cycle; it never refuses the cycle, re-slices it into separate `/dev` invocations or bundles issues into one subagent. Multiplicity is a routing condition, never a contract violation (genuine safety or hard-contract violations stay enforceable for the affected lane only). Each subagent invocation handles exactly one issue; a QA fail re-invokes dev with the same single issue.

**One cycle, no phases.** Parallel lanes are how one cycle carries several outcomes; sequential phases are not. Every requested outcome is delivered in this cycle, and the cycle ends only when all of them are done. No spec, BA context, dev plan, report or message splits a requested outcome into sequential phases, defers a part of it (a "phase 2", an "MVP first", work "for a later cycle") or asks the owner to open another `/dev` session. An outcome that is not done goes back through Step 16 until it is; an accepted acceptance-criterion deviation never carries "future work" for a requested outcome. A follow-up suggestion outside the request (a new idea, or the owner later asking to keep improving) may still be offered as a suggestion.

**Decompose.** Split `$ARGUMENTS` into `requirements[] = [{requirement_id, text}]`, one per separately requested, independently verifiable OUTCOME (N of them); shared constraints, exclusions and implementation steps attach to the lanes as context and do not become lanes. The coverage map ties every requested outcome to exactly one `requirement_id`, none omitted or duplicated. Each lane gets a short stable suffix (`-a`/`-b`/`-c` or `-r01`/`-r02`, the `dev-report-<task-id>-<worker>.json` worker convention).

**Fan out.** The requirement round (Steps 4-4b) runs once for the cycle; Steps 4c, 7, 10 and 13 (BA, QA validates BA, dev, QA) dispatch exactly one subagent per lane in one parallel batch, bound to `lane.text` / `requirement_id` and writing lane-suffixed artifacts (the Step 10 test-writer runs per applicable lane only), then wait at a stage barrier. Steps 6 and 12 (validation) run for every lane; Steps 8 and 16 (iteration) retry only the affected or failed lanes. Clarification and retry outcomes are lane-local: a clarifying or failing lane never blocks or re-runs its siblings, and with N > 1 there is no whole-cycle singular dispatch. Step 11 is ONE parent-level join after the barrier, not a per-lane dispatch. Every lane's artifacts carry its lane suffix under ONE parent `DEV_SESSION_ID`, and the cycle emits ONE parent completion report, never a new cycle or session per lane; the parent passes only when every lane's QA passes. Steps 14 and 15 share Bash calls across lanes:

- **Steps 14 and 15 (Score updates, Permissions)** — each step is ONE Bash call for every lane that reaches it, its lanes' commands one per line, so a failed command does not stop the next: Step 14's score-update calls of every lane, then Step 15's permission merge of every passing lane. A call per lane and command (3N+1 in a row through Step 17's completion check) would exceed the Bash budget and lose Step 15 and the completion check.

**Lane-execution adapter (it takes precedence over the singular Step templates when N > 1).** Every placeholder (`<requirement>`, `<timestamp>`, session id), path, dispatch, wait, validation and result branch in Steps 4-16 is evaluated per lane. Each lane's dispatch prompt carries three explicit fields — `Lane requirement_id`, `Lane requirement text` (the authoritative execution scope), and `Parent requirement document (reference baseline)` — and the lane text overrides the parent document and any "context / BA-spec is absolute truth" clause for execution: the lane implements, verifies and edits only its own outcome without re-detecting multiplicity, and reports (never absorbs) a slice that contradicts the parent requirement, is coupled to a sibling or is a recurring-failure patch (handlers below; the charter's baseline check in `agents/<role>.md`). Every Step's result branch gains a `multi_issue_fanout_requested` and a `coupled_issues_merge_requested` route, which also apply at N == 1; otherwise N == 1 runs the Steps as written.

**`multi_issue_fanout_requested` (routing only, non-terminal).** A BA or dev subagent returns `status: multi_issue_fanout_requested`, a QA subagent `verdict: multi_issue_fanout_requested`, with `{issues: [{requirement_id, text}]}`, when handed a bundled multi-issue prompt. It is a routing enum, never a failure or `contract_violation_refused`: re-dispatch each enumerated issue exactly once as its own lane in the same cycle (no new session, no owner prompt), re-running the coverage map against the ORIGINAL bundled prompt so every lane inherits all shared constraints and exclusions; the returned boundaries are advisory.

**`coupled_issues_merge_requested` (routing only, non-terminal).** A lane's BA, dev or QA names it in its report's summary (and its `baseline_check` where its output has one; charter in `agents/<role>.md`) when its lane is one half of a coupled cross-lane issue, with the coupled `requirement_id`s, the underlying issue and cited evidence; its report still completes as its schema defines, the name being no status or verdict value. When the orchestrator reads a lane's report (Steps 6, 7, 12 and 14) and finds it named, it merges the named lanes into ONE lane (one `requirement_id`, `text` = the underlying issue covering every merged outcome) and re-dispatches it in the same cycle (no new session, no owner prompt), re-running the coverage map against the ORIGINAL parent document so the merged lane inherits every merged lane's shared constraints and exclusions and every requested outcome still maps to exactly one `requirement_id`. The baseline check also names `baseline_contradiction` (the lane's scope contradicts the parent requirement) and `recurring_mechanism_failure` (the Nth patch on a mechanism with recurring failures): the orchestrator re-scopes or redesigns the lane from the named evidence before re-dispatching it (one AskUserQuestion only where the evidence leaves a real decision open) and never forces the emitter to complete the mis-scoped work.

## Implementation

**Bash budget.** The orchestrator gate (`hooks/pretool-orchestrator-gate.py`) refuses a sixth Bash call since the last Agent dispatch or human prompt. Steps 1-4 use at most five before BA's dispatch: the start-function fallback (only when the hook output is gone), the spec resolver (only with a spec), Step 2's call, Step 3's one `git log`, Step 4's score header.

### Step 1: Parse Development Requirement

An empty `$ARGUMENTS` is asked for with one AskUserQuestion (the pause; the cycle stays open).

**`--codex`.** If `$ARGUMENTS` contains the literal token `--codex`, strip it and set `codex_required = true`, else `false`. When true, every BA, QA and dev dispatch carries the literal line `codex_required: true` (it activates the subagent's codex consultation, `templates/prompt-includes/codex-consultation.md`); when false, omit it. `codex_consult` is the subagent's output: pre-filling it in a prompt silently suppresses the consultation, so never do.

**Spec.** The `UserPromptSubmit` hook decided this run's spec once and printed it above as `Spec: <path>` or `Spec: none`: the `--spec <path>` of `$ARGUMENTS` when given, else the spec this session last wrote. Store it as `spec_path` (`null` for none), remove a `--spec <path>` flag from the requirement text and announce the spec; nothing else chooses a spec.

**Views.** With `spec_path` set, run the spec resolver once; it alone derives the artifact id, views folder, split marker and cp-state folder (a hand-derived name silently drops a de-prefixed spec to monolith mode):

```bash
[ -z "$spec_path" ] || python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/resolve-spec-artifacts.py" --spec-path "$spec_path" --project-dir "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
```

Its stdout JSON carries `artifact_id` (`SPEC_ID` below), `views_available`, `manifest_path`, `split_marker`, `views_dir` and `cp_dir`; keep them in your notes (a Bash call carries no variable to the next). A non-zero exit is an invalid, mismatched, ambiguous or stale split: have `/spec` re-finalized, never fall back to the monolith; `views_available=false` with exit 0 is a legacy spec (monolith `spec_path`, no checkpoint enforcement). When `views_available` is true, pass `view_paths.ba`, `.qa`, `.dev` (from `manifest_path`) beside, never in place of, `spec_path`; BEFORE composing any dispatch read `<views_dir>/orchestrator.md` and the spec's Section 5 (User's Acceptance Criterion) and quote Section 5 verbatim into every dispatch prompt.

**The cycle is hook-prepared.** The `UserPromptSubmit` hook (`hooks/prompt-workflow.py`) printed what it did above: it minted the ids, created `.claude/dev-registry/<DEV_SESSION_ID>/`, and wrote `docs/dev/user-requirement-<DEV_SESSION_ID>.md` with the verbatim requirement. Read `DEV_SESSION_ID` and `TASK_ID` from the hook output above (lines `DEV_SESSION_ID pre-initialized by hook: …` and `Task id: …`) and use them in every dispatch prompt.

**When those lines are not in your context** (a compaction removed the hook output, or the hook printed none), run the hook's own start function with this command's text exactly as typed and read the same lines from what it prints. Write `<HARNESS_ROOT>` as the literal path of the `HARNESS_ROOT=` line in your context: `prompt-workflow.py` prints it at the session's start and again after every compaction (`SessionStart`), so it survives the loss of the command's own output:

```bash
python3 "<HARNESS_ROOT>/hooks/prompt-workflow.py" start <<'CMDEOF'
<the command exactly as typed: /dev or /redev, then $ARGUMENTS>
CMDEOF
```

It finds this session's bookmark (`$CLAUDE_CODE_SESSION_ID`) and, when the hook recorded no start of this command, starts the cycle itself under a task id of its own. Never mint an id, pick a registry by name or age, or write a registry, requirement or flag file yourself.

**FIRST ACTION.** Every Agent launch prompt begins with a `FIRST ACTION` line: Read `<PROJECT_ROOT>/.claude/dev-registry/<DEV_SESSION_ID>/<agent>.json` before any other tool call; that Read registers the role (`hooks/pretool-cp-checkin.py`).

**SECOND ACTION.** For an agent whose `cp-state-<agent>.json` exists in the resolver's `cp_dir`, the dispatch also carries the templates' `SECOND ACTION` line (`SPEC_ID` is the resolver's `artifact_id`), and the subagent marks or waives each checkpoint of its own slot before it stops; otherwise omit it. As shipped (`CP_ENFORCE_MODE=block` in `settings.json`), `hooks/subagentstop-cp-enforce.py` blocks (exit 2) a stop while one of the stopping subagent's own running slots has a `pending` checkpoint; under any other mode it only warns.

### Step 2: Graphify pre-BA Bash hydrator

Run the pre-BA query as one direct Bash call, not a subagent. It is advisory: without graphify the script exits 0 with `status=unavailable`. The second command starts a detached background build for the NEXT run when no cached graph exists and returns at once:

```bash
source "${CLAUDE_HOME:-$HOME/.claude}/venv/bin/activate" && python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/graphify-query.py" --task-id "$DEV_SESSION_ID" --requirement-file "$REQUIREMENT_DOC"
python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/graphify-maintain.py" ensure-async || true
```

With the output `.claude/dev-registry/$DEV_SESSION_ID/graphify/pre_query.json` at `status=ok` or `degraded`, add `Pre-query context file: .claude/dev-registry/$DEV_SESSION_ID/graphify/pre_query.json` to the BA dispatch (Step 4); otherwise omit it. If `$ARGUMENTS` carries `--no-graphify`, add it to the query and drop the `ensure-async` line.

### Step 3: Specialist Consultation (always evaluate, never silently skip)

Assess each of the four specialists (`ui-specialist`, `architect`, `product-owner`, `user`) and write one line each: `<specialist>: RELEVANT — <reason>` or `<specialist>: SKIP — <concrete reason>`. Call every RELEVANT one, in parallel in one response, and call whenever you have no concrete SKIP reason; "no specialists needed" without the per-specialist lines, and skipping all four by default, are invalid.

Record the assessment in the BA context JSON as `specialists_assessed` (one string per specialist) and pass all findings to BA in Step 4 as additional context. For each RELEVANT specialist:

```
Use Agent tool with:
- description: "<Specialist role> consultation for: <requirement summary>"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<DEV_SESSION_ID>/<specialist-name>.json before any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read <PROJECT_ROOT>/.claude/specs/<SPEC_ID>/cp-state-<specialist-name>.json for your checkpoints.

  You are the <specialist-name> specialist. Follow .claude/agents/<specialist-name>.md.

  Requirement: '<requirement from Step 1>'

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true

  Return structured findings that inform the BA analysis; do not modify files.
  "
```

## Four Contracts Awareness (Orchestrator Role)

BA enforces four domain-agnostic contracts (`agents/ba.md`, "Four Contracts"); the orchestrator supplies context before delegation and verifies compliance after BA returns.

### Pre-BA: surface retry signals

Give BA ground truth under `Prior attempt signals` in the Step 4 dispatch:

- **Retry intent**: judge semantically (any language, no phrase list) whether the owner's message signals that a prior attempt failed: a complaint, a reference to earlier commits or specs, a repeated requirement.
- **Recent related commits**: from ONE call, `git log --oneline --grep="<keyword>" -20`.
- **Existing BA specs**: prior `docs/dev/ticket-*.md` covering the same area.

### Post-BA: verify contract compliance

Before dispatching dev (Step 6), verify in the BA JSON context: `evidence.measured.value` populated (neither null nor empty); `evidence.expected.source` populated; `scope_expansion.all_occurrences` non-empty (or `scope_expansion` marked `not_applicable` with a reason); `reference_source.tier` not `tier_3_tainted` when `copy_allowed: true`; when Contract D triggered, novelty across BOTH `layer` AND `target_location`; location-complaint overlap. On any failed check re-delegate to BA naming the missing field; never proceed to dev with an incomplete spec.

**Location-complaint overlap** is a semantic judgement, with no token splitting or set arithmetic: would a reasonable engineer, reading the complaint beside `complaint_location_keywords`, `affected_files` and `located_source`, agree that BA looked in the right place? It passes iff yes or the context records `localization_blocked` (set only after the owner answered BA's localization question). On no, re-delegate to BA with one sentence naming the complaint phrase that found no believable home.

**Contract D novelty** has two dimensions. Two attempts are equivalent (non-novel) iff `this_attempt_layer == prior_attempt_layer` AND `jaccard(tokens_of(target_location_i), tokens_of(target_location_j)) >= 0.5`; novelty needs a different layer OR `jaccard < 0.5`, which blocks the "different words, same wrong file" loophole. When the check rejects the attempt, BA writes `docs/dev/producer-question-<timestamp>-ba.json` (options: the candidate layers; default: BA's recommendation) instead of its report; relay it as in Step 5 and re-dispatch BA with the chosen layer (L1 cosmetic, L2 structural, L3 data, L4 logic, L5 infrastructure, shallow to deep; `agents/ba.md` "Layer differentiation guide"). When dev reports back, its implementation layer must match BA's spec layer: dev changing L1 when the spec called for L3 is a failed implementation.

### Step 4: The Requirement Round (D28, D29, D32)

Run `bash "<HARNESS_ROOT>/scripts/score-inject.sh" --agent ba` once per stage and capture stdout as `BA_SCORE_HEADER`; it goes after the role declaration and before the task instructions.

**Obligation blocks.** Every dispatch carries an `<obligation v="1">` block the orchestrator instantiates from the dispatch's own values (`task_id`, `lane`, `lane_set`, `role`, `pipeline`, `profile`, `dispatched_at` as ISO-8601 UTC ending in Z captured right before the Agent call, `artifacts[]`), never hand-invented; every `kind: "json"` entry names its `schema` (`schemas/registry.json`; grammar in `docs/reference/close-commit-zero-failure-mechanism-20260928.md` §1.2). Step 4c's template shows the worked example; the others declare theirs in one `embed ... here with` sentence.

Before any analysis for dev, the owner is asked about the requirement: its intent, scope, edge cases and acceptance. BA (or panel QA, for a panel's round 1) writes the questions; the orchestrator asks them verbatim (Step 4b); the PostToolUse AskUserQuestion hook writes the owner's answers. Until round 1 is asked, the dispatch gate refuses every dispatch but round 1's own producers (`ASK_FIRST`), and later any dispatch while a written round is not asked. The round runs once for the cycle, under `TASK_ID` (`<timestamp>` below), before the lanes' analyses (Step 4c runs per lane). Nothing is asked in plain text: a turn that ends with a question in text is a Stop gap.

**Without a spec: the BA panel.** Dispatch three BAs in ONE response (three Agent calls, each `run_in_background: false`), angles A (root cause first, traced to the code), B (the smallest change that meets the requirement) and C (the owner's intent, the product view). They are independent: none is given another's report. Then Step 4a.

```
Use Agent tool with:
- subagent_type: "ba"
- description: "BA panel <angle>: independent analysis of the requirement"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<DEV_SESSION_ID>/ba.json before any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="ba", pipeline="dev", profile="singular", task_id/dispatched_at bound to this dispatch (see Step 4), artifacts=[{"kind":"markdown","path":"docs/dev/ba-panel-<timestamp>-<angle>.md","identity_anchor":"<timestamp>","terminal_line_regex":"^BA PANEL [ABC]: DONE$"}].

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true

  You are the BA subagent. Follow .claude/agents/ba.md instructions precisely.
  Mode: panel
  Angle: <angle>

  Requirement: '<requirement from Step 1>'
  Codebase hints: <any file paths mentioned by user, or null>
  Timestamp: <YYYYMMDD-HHMMSS>
  Prior attempt signals:
    retry_intent: <one-line semantic summary, or null if none>
    recent_commits: [<hash> <subject>, ...]
    existing_specs: [docs/dev/ticket-<ts>.md, ...]

  Write your panel report only. Do not read another panel BA's report.
  "
```

**With a spec: one BA, intake.** It checks that the spec still matches the code and asks only what the spec left open (at least one question). Then Step 4b.

```
Use Agent tool with:
- subagent_type: "ba"
- description: "BA intake: the owner's questions the spec left open"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<DEV_SESSION_ID>/ba.json before any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read <PROJECT_ROOT>/.claude/specs/<SPEC_ID>/cp-state-ba.json for your checkpoints.

  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="ba", pipeline="dev", profile="singular", task_id/dispatched_at bound to this dispatch (see Step 4), artifacts=[{"kind":"json","path":"docs/dev/requirement-round-<timestamp>-r1.json","schema":"requirement-round.v1","identity":{"task_id":"<timestamp>"}}].

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true

  You are the BA subagent. Follow .claude/agents/ba.md instructions precisely.
  Mode: intake

  Requirement: '<requirement from Step 1>'
  Timestamp: <YYYYMMDD-HHMMSS>
  Spec file: <spec_path>
  Spec id: <SPEC_ID>
  "
```

### Step 4a: Panel QA Writes Round 1 (without a spec)

One QA dispatch reads the three panel reports, checks each cited piece of evidence, marks every root cause verified, unsupported or refuted, lists the agreements, and turns each disagreement into a decision point with its options, recommended first (`agents/qa.md` "Panel QA mode"). An unsupported or refuted root cause never becomes an option.

```
Use Agent tool with:
- subagent_type: "qa"
- description: "Panel QA: verify the three BA reports and write round 1"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<DEV_SESSION_ID>/qa.json before any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="qa", pipeline="dev", profile="ba_validation", task_id/dispatched_at bound to this dispatch (see Step 4), artifacts=[{"kind":"json","path":"docs/dev/ba-panel-<timestamp>-r1.json","schema":"requirement-round.v1","identity":{"task_id":"<timestamp>"}}].

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true

  You are the QA subagent in PANEL QA MODE. Follow .claude/agents/qa.md "Panel QA mode" precisely.
  Panel reports: docs/dev/ba-panel-<timestamp>-A.md, docs/dev/ba-panel-<timestamp>-B.md, docs/dev/ba-panel-<timestamp>-C.md
  Requirement: '<requirement from Step 1>'
  "
```

### Step 4b: Ask Each Round with AskUserQuestion

For each round file, in round order (`docs/dev/ba-panel-<TASK_ID>-r1.json` or `docs/dev/requirement-round-<TASK_ID>-r1.json`, then `docs/dev/requirement-round-<TASK_ID>-r<n>.json`), call ONE AskUserQuestion whose `questions` are the file's questions verbatim with `id`, `dimension`, `assume`, `spec_ref` and each option's `ba` removed, and whose `metadata.source` is `requirement-round:<TASK_ID>:r<n>`. Never paraphrase, reorder or add a question: an altered question is not the round, writes no answer file and leaves the round unasked. Skip, no answer or AFK is fine: the round counts as asked, and BA settles each unanswered question by its `assume`. Asking pauses only; the cycle goes on to Step 4c.

### Step 4c: BA Analysis (the final BA context)

The final BA context has one producer. Its dispatch lists the cycle's round files (`docs/dev/ba-panel-<TASK_ID>-r1.json` or `docs/dev/requirement-round-<TASK_ID>-r1.json`, then `docs/dev/requirement-round-<TASK_ID>-r<n>.json`) and the answer files the hook wrote (`docs/dev/requirement-answers-<TASK_ID>-r<n>.json`). With a panel: the BA whose option the owner chose (the chosen option's `ba` in the panel round, read beside the answer file); when the BAs agreed or the owner chose none, the BA whose root cause panel QA verified (A, then B, then C, when more than one). With a spec: one BA. Dispatch it in analysis mode; with lanes, one per lane, each reading the cycle's rounds. While a point still needs the owner, it writes the next round instead of its artifacts: ask it (Step 4b) and dispatch it again; rounds have no cap.

```
Use Task tool with:
- subagent_type: "ba"
- description: "Analyze requirement and build development context"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<DEV_SESSION_ID>/ba.json before any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read <PROJECT_ROOT>/.claude/specs/<SPEC_ID>/cp-state-ba.json for your checkpoints.

  Obligation block (worked example):
  <obligation v="1">
  {
    "task_id": "<timestamp>",
    "lane": null,
    "lane_set": null,
    "role": "ba",
    "pipeline": "dev",
    "profile": "singular",
    "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this Agent call>",
    "artifacts": [
      {"kind": "json", "path": "docs/dev/context-<timestamp>.json", "schema": "context.v1",
       "identity": {"task_id": "<timestamp>", "request_id": "<timestamp>"}},
      {"kind": "markdown", "path": "docs/dev/ticket-<timestamp>.md", "identity_anchor": "<timestamp>"},
      {"kind": "json", "path": "docs/dev/acceptance-criteria-<timestamp>.json", "schema": "acceptance-criteria.v1",
       "identity": {"task_id": "<timestamp>", "request_id": "<timestamp>"}}
    ]
  }
  </obligation>
  When the fan-out Lane-execution adapter is active (N>1): lane="<lane-suffix>" (e.g. "l6"), lane_set=[<all lane suffixes this cycle>], profile="fanout-lane", and <timestamp> above becomes "<TASK_ID>-<lane-suffix>".

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true

  You are the BA subagent. Follow .claude/agents/ba.md instructions precisely.
  Mode: analysis
  Angle: <A, B or C when you are the chosen panel BA, else null>
  Round files: <the cycle's round files, comma-separated>
  Answer files: <the cycle's answer files, comma-separated, or none>

  <BA_SCORE_HEADER prepended here>

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
    existing_specs: [docs/dev/ticket-<ts>.md, ...]

  If Spec file is not null: Read it FIRST; Section 5 (User's Acceptance Criterion) is the primary requirement source, Sections 1-4 baseline context, Section 7 (What Must Be Done), if populated, prescriptive.

  Goal: the smallest, safest, most precise change set that delivers every requested outcome in this cycle (no phases, nothing deferred). Path-external observations go into the spec's `out_of_scope_observations`, not the fix scope. Produce ticket-<timestamp>.md and context-<timestamp>.json per agents/ba.md Output Formats.

  Print the literal line `TASK-ID: <timestamp>` in your response.

  Return JSON with status, file paths, summary and the task-id echo.
  "
```

### Step 5: BA Clarification Loop

When BA needs clarification (`needs_clarification`) it writes its question artifact `docs/dev/producer-question-<timestamp>-ba.json` (schema producer-question.v1: one decision, 2-4 `options` of `{label, description}`, a `default` that is one of the labels, `why`) instead of its report, and ends.

1. Relay it with ONE AskUserQuestion: the artifact's options become the dialog's options, its default the recommended option, and `metadata.source` is `producer-question:<timestamp>:ba`. The hook writes the owner's answer to `docs/dev/producer-answer-<timestamp>-ba-<q8>.json` (q8: the first 8 hex digits of the question file's sha256); until it is asked, the dispatch gate refuses any other dispatch (`ASK_FIRST`). A question left unanswered (the dialog skipped or closed with no answer, the call denied, or no AskUserQuestion offered in this session, where the call is made all the same and its error result counts as asked) writes no answer file, never stalls the cycle and is not asked again: take the artifact's `default` as an assumption, say so in one line, and re-dispatch with `Previous answers: none`. The producer records it as an assumption: BA in its spec and the `assumptions` list it returns, dev in `implementation_notes` of its dev report.
2. Re-dispatch BA fresh and synchronously with the answer: same subagent_type, task_id, lane, pipeline, profile and obligation template, a fresh dispatched_at, the answer in the template's `Clarification round:` and `Previous answers:` lines:

```
Use Task tool with:
- description: "Continue BA analysis with clarification answers"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<DEV_SESSION_ID>/ba.json before any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read <PROJECT_ROOT>/.claude/specs/<SPEC_ID>/cp-state-ba.json for your checkpoints.

  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="ba", pipeline="dev", profile="singular"/"fanout-lane", task_id/dispatched_at bound to this dispatch (see Step 4), artifacts=[{"kind":"json","path":"docs/dev/context-<timestamp>.json","schema":"context.v1","identity":{"task_id":"<timestamp>"}},{"kind":"markdown","path":"docs/dev/ticket-<timestamp>.md","identity_anchor":"<timestamp>"},{"kind":"json","path":"docs/dev/acceptance-criteria-<timestamp>.json","schema":"acceptance-criteria.v1","identity":{"task_id":"<timestamp>"}}].

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true

  You are the BA subagent. Follow .claude/agents/ba.md instructions precisely.

  Requirement: '<original requirement>'
  Clarification round: <N>
  Previous answers: <the producer answer file the hook wrote, or none when the owner gave no answer>
  Codebase hints: <accumulated hints>
  Timestamp: <same timestamp>
  Spec file: <spec_path or null>

  Continue the analysis with the owner's answers.
  "
```

Repeat until BA writes its report (`status: "ready"`), then go to Step 6.

### Step 6: Validate BA Output

Read BA output files:
- `docs/dev/ticket-<timestamp>.md`: the Markdown specification
- `docs/dev/context-<timestamp>.json`: the JSON context for dev

Check that both exist, that the ticket has Goal, Requirements and Acceptance Criteria, that the context has `requirement`, `root_cause_analysis` and `development_approach`, that success criteria are measurable, affected files identified and the Post-BA contract checks pass, and that the plan delivers every requested outcome in this cycle: a plan that splits a requested outcome into sequential phases or defers any part of it (Requirement Decomposition & Fan-Out) fails validation. On any gap, re-dispatch BA with the gap named and validate again until it passes.

The context is BA's alone: BA records `spec_path` from the dispatch's `Spec file:` line (`agents/ba.md`), and the orchestrator never writes it. When validation passes, go to Step 7.

### Step 7: QA Validates BA Conclusions

Verify BA's analysis BEFORE dev starts. Dispatch one QA per lane in BA-validation mode (it checks the analysis, not code). The five dimensions and the `dimension` enum are the ones `agents/qa.md` ("BA-Validation Mode: 5 Dimensions of Objection") requires the dispatch to list.

```
Use Agent tool with:
- subagent_type: "qa"
- description: "Validate BA analysis quality (not code)"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<DEV_SESSION_ID>/qa.json before any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read <PROJECT_ROOT>/.claude/specs/<SPEC_ID>/cp-state-qa.json for your checkpoints.

  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="qa", pipeline="dev", profile="ba_validation", task_id/dispatched_at bound to this dispatch (see Step 4), artifacts=[{"kind":"json","path":"docs/dev/ba-qa-report-<timestamp>.json","schema":"ba-qa-report.v1","identity":{"task_id":"<timestamp>"}}].

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true

  You are the QA subagent in BA-VALIDATION MODE: you verify the quality of BA's analysis, not any implementation. Do not build, deploy, open a browser, run Playwright or test code; read BA's deliverables and challenge every claim.

  BA spec file: docs/dev/ticket-<timestamp>.md
  Context JSON: docs/dev/context-<timestamp>.json
  Spec file: <spec_path or null>
  View file: <view_paths.qa or null — sibling views/qa.md if present>

  Verify these 5 dimensions:

  1. EVIDENCE QUALITY: does every factual claim (root cause, affected files, component identification) have evidence (git blame output, path verification, grep results, import chain tracing)? 'BA says so' is not evidence.

  2. SCOPE ALIGNMENT: compare BA's bug title and acceptance criteria with the original requirement (and spec Section 5 if available). Did BA narrow, rename or redefine it? Is anything from the original requirement missing? Phasing or deferring a requested outcome is a narrowing of scope: FAIL any plan that splits a requested outcome into sequential phases or defers any part of it (a 'phase 2', an 'MVP first', work 'for a later cycle', a request that the owner open more /dev sessions). Every requested outcome is delivered in this cycle; parallel one-issue lanes are not phases.

  3. INVESTIGATION COMPLETENESS: if the requirement says 'audit X', 'investigate Y' or 'trace Z', did BA do it, or jump to a conclusion?

  4. AFFECTED-FILE ACCURACY: do the files BA identified exist, contain the code BA claims, and fit the import chain behind BA's component identification?

  5. SPEC-TEXT-VS-EXECUTION DRIFT: when an AC's literal regex, command or verification recipe gives output the AC text does not expect, while a different formulation of the same check verifies the AC's intent, raise a 'dimension: spec_text_vs_execution_drift' objection requiring BA to update the AC's literal text to the runnable formulation.

  Return JSON: {'task_id': '<timestamp>', 'verdict': 'pass' or 'fail', 'objections': [{'dimension': 'evidence_quality|scope_alignment|investigation_completeness|affected_file_accuracy|spec_text_vs_execution_drift', 'claim': 'what BA claimed', 'problem': 'what is wrong with the claim', 'required_evidence': 'what BA must provide'}], 'summary': 'one-line overall assessment'}

  Write the report to: docs/dev/ba-qa-report-<timestamp>.json
  "
```

Verdict `pass`: BA's conclusions are validated, go to Step 9. Verdict `fail`: go to Step 8.

### Step 8: BA-QA Iteration Loop (if QA rejects BA)

A BA-QA `fail` loops back to BA until QA's verdict is `pass`; pass is the only exit, and every BA invocation is followed by QA validation. Announce `BA-QA iteration <N>: QA found <count> objections in BA analysis. Re-invoking BA to address objections.`

```
Use Agent tool with:
- subagent_type: "ba"
- description: "Re-investigate: address QA objections on analysis quality"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<DEV_SESSION_ID>/ba.json before any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read <PROJECT_ROOT>/.claude/specs/<SPEC_ID>/cp-state-ba.json for your checkpoints.

  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="ba", pipeline="dev", profile="singular"/"fanout-lane", task_id/dispatched_at bound to this dispatch (see Step 4), artifacts=[{"kind":"json","path":"docs/dev/context-<timestamp>.json","schema":"context.v1","identity":{"task_id":"<timestamp>"}},{"kind":"markdown","path":"docs/dev/ticket-<timestamp>.md","identity_anchor":"<timestamp>"},{"kind":"json","path":"docs/dev/acceptance-criteria-<timestamp>.json","schema":"acceptance-criteria.v1","identity":{"task_id":"<timestamp>"}}].

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true

  You are the BA subagent. Follow .claude/agents/ba.md instructions precisely.

  Your previous analysis was REJECTED by QA; address each objection below with concrete evidence.

  Original requirement: '<requirement>'
  Previous BA spec: docs/dev/ticket-<timestamp>.md
  Previous context: docs/dev/context-<timestamp>.json
  Spec file: <spec_path or null>

  QA objections:
  <JSON array of objections from ba-qa-report>

  For each objection, do the investigation QA requested and give the evidence it asked for: correct the claim if it was wrong, prove it if it was right. Update the ticket and the context JSON and return JSON with status and the updated file paths.
  "
```

After BA re-delivers, return to Step 6, then Step 7. If BA writes its question artifact instead, relay it as in Step 5.

### Step 9: Graphify enrichment

After BA-QA validation passes, dispatch the graphify subagent (its sentinel, `graphify.json`, is in the registry the hook wrote). It is advisory: without graphify, or when BA wrote no blast-radius map, it records status=skipped or unavailable and you go on to Step 10 at once.

```
Use Agent tool with:
- subagent_type: "graphify"
- description: "Graphify enrichment: extract focused subgraph for task"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<DEV_SESSION_ID>/graphify.json before any other tool call.

  You are the graphify subagent. Follow agents/graphify.md instructions precisely.

  Run: source "${CLAUDE_HOME:-$HOME/.claude}/venv/bin/activate" && python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/graphify-enrich.py" --task-id <DEV_SESSION_ID> --context-file <context_json_path>

  This is advisory: if the binary is absent or the blast-radius map is missing, exit 0 with status=skipped.
  "
```

When graphify completes (or is skipped), read the `status` of its run record `.claude/dev-registry/<DEV_SESSION_ID>/graphify/graphify-run.json` and record it in the todo list. When that status is `ok` or `degraded`, add `Graph context file: .claude/dev-registry/<DEV_SESSION_ID>/graphify/focused-subgraph.json` to the dev dispatch (Step 10) and the QA dispatch (Step 13); otherwise omit the line.

### Step 10: Agent dispatch — Delegate to Dev Subagent

**Test-writer gate.** A non-empty `_test_writer_skip_reason` in BA's context JSON is BA's explicit skip signal: skip the test-writer whatever the tier or risk, record `test_writer_expected = false` and the reason in the todo list, and never route a stale acceptance-criteria JSON to it. Otherwise `test_writer_expected = true` iff `complexity_tier` is `STANDARD` or `COMPLEX`, or `risk_level` is `high`. Pass `test_writer_expected` into the dev and QA prompts. When true, dispatch the test-writer before dev:

```
Use Task tool with:
- description: "Generate pytest skeletons from acceptance criteria"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<DEV_SESSION_ID>/test-writer.json before any other tool call.

  You are the test-writer subagent. Follow agents/test-writer.md instructions precisely.

  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="test-writer", pipeline="dev", profile="singular"/"fanout-lane", task_id/dispatched_at bound to this dispatch (see Step 4), artifacts=[{"kind":"json","path":"docs/dev/test-writer-report-<task_id>.json","schema":"test-writer-report.v1","identity":{"task_id":"<task_id>"}},{"kind":"json","path":"tests/generated/<task_id>/manifest.json","schema":"test-writer-manifest.v1","identity":{"task_id":"<task_id>"}}].

  Inputs:
    task_id: <task_id>
    acceptance_criteria_path: docs/dev/acceptance-criteria-<task_id>.json
    complexity_tier: <COMPLEX|STANDARD|SMALL|MICRO from BA context>
    risk_level: <high|medium|low from BA context>

  Write your report to: docs/dev/test-writer-report-<task_id>.json
  Generated tests go under: tests/generated/<task_id>/ (each manifest entry's file, which dev writes from the entry's skeleton; you write no test file)
  Per-task active manifest: tests/generated/<task_id>/manifest.json (active_tests[] lives here, each entry with its skeleton; dev writes the tests from it and QA Phase 5 reads it).
  "
```

After the test-writer subagent completes, verify on disk that both `tests/generated/<task_id>/manifest.json` and `docs/dev/test-writer-report-<task_id>.json` exist; if either is missing, dispatch the test-writer again (this template, a fresh dispatched_at) until both do; never go on to dev after a silently skipped test-writer.

Before the dev dispatch, once per stage, run `bash "<HARNESS_ROOT>/scripts/score-inject.sh" --agent dev` and capture stdout as `DEV_SCORE_HEADER`, then capture the baseline dev's report is measured against (`agents/dev.md` gives its point-in-time semantics); both values go into the dev dispatch, `baseline_head_sha` as the empty string (never omitted) in a repository with no commits yet:

```bash
baseline_head_sha=$(git -C "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" rev-parse HEAD 2>/dev/null || echo "")
baseline_dirty_snapshot=$(git -C "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" status --porcelain 2>/dev/null || echo "")
```

Dispatch dev with file paths only:

```
Use Task tool with:
- description: "Implement development changes based on BA context"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<DEV_SESSION_ID>/dev.json before any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read <PROJECT_ROOT>/.claude/specs/<SPEC_ID>/cp-state-dev.json for your checkpoints.

  You are the dev subagent. Follow agents/dev.md instructions precisely.

  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="dev", pipeline="dev", profile="singular"/"fanout-lane", task_id/dispatched_at bound to this dispatch (see Step 4), artifacts=[{"kind":"json","path":"docs/dev/dev-report-<timestamp>.json","schema":"dev-report.v2","identity":{"task_id":"<timestamp>"}}].

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true

  <DEV_SCORE_HEADER prepended here>

  Context file: docs/dev/context-<timestamp>.json
  BA spec file: docs/dev/ticket-<timestamp>.md
  Spec file: <spec_path or null>
  View file: <view_paths.dev or null — sibling views/dev.md if present>
  Generated tests (when test-writer ran): tests/generated/<task_id>/ + per-task active manifest at tests/generated/<task_id>/manifest.json (write each active entry's file from its skeleton; agents/dev.md).
  Write your implementation report to: docs/dev/dev-report-<timestamp>.json
  baseline_head_sha: <baseline_head_sha captured above>
  baseline_dirty_snapshot: <baseline_dirty_snapshot captured above>

  If Spec file is not null: Read it FIRST and do not write it; your approach, rationale and exact file:line changes go in your report's dev.tasks_completed entries, where /spec-update and /commit Step 8 read them. If View file is not null, you may read it instead of the monolith (sections S1, S2, S3, S7, S8).
  "
```

### Step 11: Canonical Aggregate Dev-Report (Parallel-Dev Only)

This applies only when N > 1 dev subagents ran in Step 10; a single-dev cycle has nothing to aggregate (the lone dev writes `dev-report-<task-id>.json` itself): mark this todo step completed.

The canonical `docs/dev/dev-report-<task-id>.json` has one producer, `hooks/posttool-lane-completeness-watch.py`: when the lane report that completes its own `lane_set` lands, it runs the harness's `scripts/aggregate-dev-report.py`, whose code is the construction rule. The orchestrator writes no aggregate and runs no aggregator; it marks this step completed once every lane's dev has returned.

G3 (`hooks/pretool-aggregate-check.py`) refuses the Step 13 QA dispatch while every lane has reported and the canonical is missing; reach the producer through the lanes by dispatching one lane's dev again (its declaring dispatch: same subagent_type, task_id, lane and obligation template, a fresh `dispatched_at`), whose update of its own report runs the hook.

### Step 12: Validate Dev Implementation

Read dev implementation report: `docs/dev/dev-report-<timestamp>.json`

Check that its status is "completed", all tasks are documented, scripts created have usage examples, the git rationale references the root cause, and the files reported exist.

If dev wrote its question artifact (`docs/dev/producer-question-<timestamp>-dev.json`) instead of its report, relay it as in Step 5 (an unanswered question takes its `default` there) and re-dispatch dev fresh with the answer: Step 10's template, a fresh dispatched_at, and right after its `Context file:` line Step 5's two lines `Clarification round: <N>` and `Previous answers: <the producer answer file the hook wrote, or none when the owner gave no answer>` (the hook's `docs/dev/producer-answer-<timestamp>-dev-<q8>.json` for this question, its `metadata.source` `producer-question:<timestamp>:dev`; N the count of this lane's dev questions so far). If a check finds a gap, re-dispatch dev the same way with the gap named, until the checks pass. When dev completed, go to Step 13.

### Step 13: Delegate to QA Subagent

Run `bash "<HARNESS_ROOT>/scripts/score-inject.sh" --agent qa` once per stage and capture stdout as `QA_SCORE_HEADER`. Dispatch QA with file paths only:

```
Use Task tool with:
- description: "Verify implementation quality against standards"
- run_in_background: false
- prompt: "
  FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<DEV_SESSION_ID>/qa.json before any other tool call.
  User requirement document: docs/dev/user-requirement-<DEV_SESSION_ID>.md

  SECOND ACTION (only if SPEC_ID is non-empty and your cp-state file exists): Read <PROJECT_ROOT>/.claude/specs/<SPEC_ID>/cp-state-qa.json for your checkpoints.

  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="qa", pipeline="dev", profile="final_verification", task_id/dispatched_at bound to this dispatch (see Step 4), artifacts=[{"kind":"json","path":"docs/dev/qa-report-<timestamp>.json","schema":"qa-report.v2","identity":{"task_id":"<timestamp>","request_id":"<timestamp>"}}].

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true

  You are the QA subagent. Follow agents/qa.md instructions precisely.

  <QA_SCORE_HEADER prepended here>

  Context file: docs/dev/context-<timestamp>.json
  Dev report file: docs/dev/dev-report-<timestamp>.json
  BA spec file: docs/dev/ticket-<timestamp>.md
  Spec file: <spec_path or null>
  View file: <view_paths.qa or null — sibling views/qa.md if present>
  Per-task active test manifest: tests/generated/<task_id>/manifest.json (the file QA Phase 5 reads active_tests[] from; agents/qa.md Phase 5).
  Write your verification report to: docs/dev/qa-report-<timestamp>.json

  If Spec file is not null: Read it FIRST and do not Edit docs/dev/specs/*.md (the verifier must not mutate the spec it verifies); report proposed Section 4/6/7 content in the qa-report JSON's 'qa.spec_section_updates' instead, where /spec-update and /commit Step 8 read it (agents/qa.md '## Output Format').
  "
```

### Step 14: Process QA Results

Read QA report: `docs/dev/qa-report-<timestamp>.json`

- `qa.status == "pass"`: go to Step 15.
- `qa.status` is `warning` or `fail`: go to Step 16.

After the verdict, apply the score-update events for the outcome and iteration count (a failed call does not abort the cycle) and include the deltas in the completion report.

- First-round PASS (iteration 0 and `qa.status=pass`): `bash "<HARNESS_ROOT>/scripts/score-update.sh" --agent dev --event qa_first_pass --note "<task_id>"` and `--agent ba --event qa_first_pass`.
- Second-or-later-round PASS (iteration >= 1 and `qa.status=pass`): `--agent dev --event qa_second_pass --note "<task_id>"`.
- FAIL (`qa.status=fail`): read `qa.failures[].primary_cause` to attribute the rejection:
  - any failure with `primary_cause = "dev_implementation"`: `score-update.sh --agent dev --event qa_reject_dev --note "<task_id>"`;
  - any failure with `primary_cause = "ba_spec"`: `score-update.sh --agent ba --event qa_reject_ba --note "<task_id>"` and `--agent dev --event qa_reject_ba`;
  - `qa_oversight` or `environment`: no score update (manual review).

### Step 15: Update Settings.json Permissions

Apply the permissions QA validated (`qa.permissions_verification.validated_permissions[]`) to the project's `.claude/settings.json` through the harness's one writer of that file, as `/dev-overnight` does:

```bash
python3 "<HARNESS_ROOT>/scripts/aggregate-permissions.py" docs/dev/qa-report-<timestamp>.json | bash "<HARNESS_ROOT>/scripts/apply-permissions.sh" /dev/stdin .claude/settings.json
```

The applier merges each validated entry into `.permissions.<section>` (`allow`, `ask` or `deny`) and skips patterns already present; it creates a missing `.claude/settings.json`, and a file it cannot parse fails the merge (non-zero exit) and stays unchanged. Tell the owner which permissions were added; if the owner denies the update, log that in the completion report.

### Step 16: Iteration Loop (QA warning or fail)

On a QA warning or fail, re-dispatch this lane's dev with the QA report path, the same task_id, lane and obligation template, and a fresh dispatched_at; once it returns, Steps 12-14 run again for this lane, and the loop repeats until QA passes (then Step 15). Dispatch line: `QA report file: docs/dev/qa-report-<timestamp>.json`.

The Stop gate keeps the command open until the disposition is chain_pass, which needs the QA report's `qa.status` to be `pass` (`INVALID_QA_STATUS` until then). There is no other exit.

### Step 17: Generate Completion Report + Workflow Update

This step is reached only when every requested outcome passes (in a fan-out, every lane's QA).

**Task-ID convention.** The `task-id` is the single literal string of the hook's `Task id:` line, identical in the artifact filename suffix, the `request_id` and `task_id` fields of every artifact JSON and the completion report's heading 1; new artifacts carry no prefixed forms (`dev-`, `qa-`, `ba-`, `ui-`).

**Completion report:**

```markdown
# Development Completion Report — <task-id>

**Request ID**: <task-id>
**Task ID**: <task-id>
**Completed**: <ISO-8601>
**Iterations**: <N>

## Summary

{Original request; clarified requirement; each success criterion, delivered; root cause (symptom, underlying issue, root cause commit `<hash> - <message>`); implementation (approach, git rationale, scripts created with parameters and usage, files modified); quality: PASSED, issues found by severity.}

## Files Generated

*(Single-lane cycle, N == 1)*
- Ticket: `docs/dev/ticket-<timestamp>.md`
- Context: `docs/dev/context-<timestamp>.json`
- Dev Report: `docs/dev/dev-report-<timestamp>.json`
- QA Report: `docs/dev/qa-report-<timestamp>.json`

*(Fan-out cycle, N > 1 — index EVERY lane, then the aggregate)*
- Per lane `<lane>`: `docs/dev/ticket-<timestamp>-<lane>.md`, `context-<timestamp>-<lane>.json`, `dev-report-<timestamp>-<lane>.json`, `qa-report-<timestamp>-<lane>.json`
- Aggregate Dev Report: `docs/dev/dev-report-<timestamp>.json`

## Follow-up Suggestions (outside the request)

{New ideas outside the request, or none. Every requested outcome is reported delivered above; none is listed here as left for later.}
```

**Save report to**: `docs/dev/completion-<timestamp>.md`

**Codex-native artifact postcondition (hard check before completion)**

Before `/dev` or `/redev` is complete, run the shared read-only resolver from the project root and retain its JSON as `ARTIFACT_CHAIN`:

```bash
ARTIFACT_CHAIN="$(python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/resolve-dev-artifact-chain.py" \
  --task-id "<TASK_ID>" --project-dir "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}")" || exit 2
```

The fixed entrypoint contract is
`scripts/resolve-dev-artifact-chain.py --task-id <id> --project-dir <root>`.
Completion requires process exit 0 and top-level `status == "pass"`; exit 2 or any other status blocks, with the resolver's exact `errors[]`. Do not reproduce the validator with ad-hoc file tests. The same result object (`mode`, `lanes`, `report_paths`, `artifact_paths`, `commit_whitelist_artifacts`, `qa_inputs`) is the handoff `/close` and normal `/commit` use.

- **Single-lane cycle (N == 1):** `mode == "singular"` requires the parent ticket, context, dev-report, QA-report and completion, with the existing identity and nested-status checks.
- **Fan-out cycle (N > 1):** `mode == "fanout"` requires, for every entry in `lanes`, its lane ticket, context, dev-report and passing QA-report, plus only the parent canonical aggregate dev-report and parent completion; a failed lane fails the parent chain. Never create, copy, or invent a parent ticket/context/QA-report to satisfy a singular-shaped check. The completion must index the canonical report and every lane artifact.

Subagent final messages, lifecycle records and JSON-like stdout are not completion artifacts. The resolver is read-only: this completion check must not repair, refresh or fabricate any artifact.

**Next command.** With every requested outcome passed, the next command is `/close <task-id>` (bare `/close` only when the same conversation context is still active); show the owner a summary of the key changes and that command. A follow-up suggestion outside the request is a suggestion, never unfinished work: nothing requested is left for later.

## Orchestrator Prompt Purity

A dispatch prompt states WHAT (problem, constraints, acceptance criteria, context); the subagent picks its own toolchain. It prescribes no HOW: no tool names, shell commands or syntax (user text between `<USER_VERBATIM>` and `</USER_VERBATIM>` is exempt). `hooks/pretool-orchestrator-prompt-purity.py` (PreToolUse `Agent`, main-agent dispatches) only warns on stderr and exits 0; it never blocks.
