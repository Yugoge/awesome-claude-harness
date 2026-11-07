---
description: Close the current dev cycle (agent infers task-id from conversation). Step 0 resolves the cycle's disposition and completes an unfinished cycle; QA evaluates the Workflow Integrity bullets and returns CLOSE YES; Step 4 asks the user to rate the cycle. Pass --codex to enable multi-round QA-codex debate; default is QA-only single-round assessment. Pass --auto to close every close_pending parent (see `--auto mode` below). --force is accepted and ignored.
argument-hint: "[--codex | --auto | --late-repair] [<task-id>|<path>]"
disable-model-invocation: true
---

# /close

True wrapper. Five TodoSteps (user-visible work, `scripts/todo/close.py`):
0. Resolve the disposition; complete the cycle when incomplete.
1. Dispatch three inspectors (parallel for a singular cycle; one at a time for a fan-out cycle).
2. Delegate the close debate to the QA subagent.
3. Echo the verdict, write the Session Summary and name the next step.
4. Ask the user to rate each landed cycle.

Argument parsing and task-id resolution happen in this command body; they are not TodoSteps.

The orchestration of rounds, the calls to codex, the evaluation of agreement, and the writing of the transcript all live INSIDE QAs invocation. /close itself does not call codex, does not manage rounds, and does not decide the verdict.

## Invocation

```
/close                  # agent infers task-id from the current /dev or /do cycle (typical use)
/close <task-id>        # an explicit task; a /do task's do-report-<task-id>.json is read the same way
/close --auto           # every close_pending parent (see `--auto` mode below)
```

An explicit path also works: `/close docs/dev/ticket-<ts>.md` (legacy `ba-spec-<ts>.md`, or `do-report-<ts>.json`). No filesystem scan, no default-to-newest. Follow with `/commit <task-id>`.

`--force` (with an optional `--reason "<text>"`) is accepted and ignored: a deprecated no-op whose one effect is a best-effort line (ISO timestamp, task-id, the reason) appended to `~/.claude/logs/close-overrides.log`; a failed append changes nothing.
<!-- Cross-reference: BA spec <harness-home>/docs/dev/ba-spec-20260426-redev8.md § AC-CLOSE-FORCE-1..6 govern --force / --reason behavior. -->

## Workflow

Load preloaded todo list: run `source "${CLAUDE_HOME:-$HOME/.claude}/venv/bin/activate" && python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/todo/close.py"`.

`<PROJECT_ROOT>` below is the `PROJECT_ROOT=` line the UserPromptSubmit hook printed for this `/close`.

**Owner questions.** Where this file asks the owner, it makes exactly one AskUserQuestion call: a header of at most 12 characters, 2-4 options that each name a concrete way on, `multiSelect: false`. The question is the pause: after the answer `/close` goes on in the same turn; an answer releases no gate, and no option offers to stop, to end, or to leave the cycle unfinished.

### Argument parsing: `--codex` flag

Parse `--codex` from `$ARGUMENTS` before task-id resolution:

- If `$ARGUMENTS` contains the literal token `--codex` (in any position), strip it and set `codex_required = true`.
- Otherwise set `codex_required = false` (default).

`codex_required` controls whether QA's internal multi-round debate (Step 2) consults codex via `Skill(codex)`:

- **`codex_required = true`**: dispatch prompt for QA includes the full multi-round QA-codex debate protocol as documented in Step 2 below. Verdict branches 1 / 2 / 3 / 6 / 7 apply.
- **`codex_required = false`** (default): dispatch prompt for QA SKIPS all `Skill(codex)` invocations and runs QA-only single-round assessment of the 4 Workflow Integrity bullets + step 1b cleanliness preconditions. Verdict branch 9 (codex disabled) applies; branches 3 / 6 / 7 are N/A.

### Argument parsing: `--auto` flag

- If `$ARGUMENTS` contains the literal token `--auto`, strip it and set `auto = true`.
- Otherwise set `auto = false` (default — every rule below is inert).

When `auto = true` and `$ARGUMENTS` still holds an explicit task-id or path, `--force` or a `--reason` value (the combinations `scripts/dev-lifecycle.py`'s `validate_auto_flag_combination()` rejects), ask before any other action (header `Close mode`): which close runs, with the options `/close --auto` (every close_pending parent) and `/close <task-id>` for the task named (when none was named: one option per candidate parent of "Task candidates" below, at most three). Go on with the chosen form. `--auto` and `--codex` combine. A legal `--auto` skips Task-id resolution: control passes to the `--auto` mode section below.

### Task-id resolution

The task-id is the SAME identifier the source `/dev` or `/do` cycle used — never a fresh `date +%Y%m%d-%H%M%S`, which would break `/commit`'s lookup of `close-report-<task-id>.md` beside `dev-report-<task-id>.json`.

- An explicit path (ends in `.md`/`.json` or contains `/`): the task-id is its basename without the `ticket-` (legacy `ba-spec-`) or `do-report-` prefix and the suffix; a `do-report-` path also binds `DO_REPORT` to it. A path that does not exist: ask "Which task?" (below).
- A timestamp argument (e.g. `20260424-103044`): `TASK_ID=$ARGUMENTS`, with no parent ticket or QA-report check first (a fan-out cycle has no parent ticket).
- No argument: the parent task-id of this conversation's `/dev` cycle, or the `/do` task-id and its do-report. No filesystem scan, no default-to-newest.

A `/do` task: when `docs/dev/do-report-<TASK_ID>.json` exists, bind `DO_REPORT` to it (a dev-report dev wrote along its route, Routes, leaves it bound).

**Which task?** When no task-id can be bound, ask (header `Task`) which task to close; the options are the task candidates: the first word of each line `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/dev-lifecycle.py" list-actionable --next-action close --project-dir "<PROJECT_ROOT>"` prints, at most four (fewer than two: add `/close --auto` and the tasks `list-actionable --next-action commit` prints, a closed task closing again). The dialog's own answer box takes any other task-id or path. Never default the close-report filename to a fresh timestamp.

### Late-repair route (R4 — spec-20260907-115508-lawful-commit-channel.md)

A deliberately-invoked, never-automatic route: without `--late-repair`, nothing in this section runs.

- If `$ARGUMENTS` contains the literal token `--late-repair`, strip it and set `LATE_REPAIR=true`; otherwise `LATE_REPAIR=false`.
- `--late-repair` with `--force`: before any eligibility check, run record or dispatch, ask (header `Repair mode`) which route runs, with the options `/close --late-repair <task-id>` and `/close <task-id>`; go on with the chosen one.
- With `LATE_REPAIR=true`, Step 0 first runs `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/late-repair-controller.py" init --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>"` once. It re-derives `late_repair_eligible` from the resolver's own output (this section never recomputes it) and:
  - **declines** (`outcome: refuse`, reason `not a beyond-QA gap; use R1's route`; zero run records, zero dispatch) when the chain is not late-repair eligible. That is no verdict: record the reason, set `LATE_REPAIR=false` and run Step 0's disposition call (the ordinary route);
  - otherwise **creates or reuses the controller-owned run record** (`docs/dev/late-repair-run-<task-id>.json`: `repair_run_id`, the live eligibility snapshot, pre-route file hashes, `original_cycle_at`, `repair_started_at`) before any dispatch.
- On an eligible chain, dispatch BA, then Dev, then QA against the CURRENT state of the work (a measured no-change Dev result is acceptable; being skipped is not). After each stage completes, run `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/late-repair-controller.py" record-stage --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>" --stage <ba|dev|qa> --report-path <path> --repair-run-id <id>`: it recomputes the artifact's hash from its bytes and records it in the run record (it writes nothing into the artifact). Stage order (ba → dev → qa) is enforced; an out-of-order or duplicate call is refused.
- After the three stages, Step 0 itself (the main agent's own step, whose todo item under `--late-repair` declares the effective report) runs `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/late-repair-controller.py" finalize --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>" --repair-run-id <id>`: drift detection over each declared file's recorded provenance, then a non-destructive `docs/dev/dev-report-<task-id>.effective.json` written afresh on every run (never overwriting the dev-report) when reconcilable, or a refusal when not; it checks the file it wrote before recording its outcome and path. `finalized_pending_verification` is provisional.
- Only `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/late-repair-controller.py" verify-disclosure --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>"` returning `outcome: admitted` makes the chain eligible toward `/commit` (which runs the same verification through `resolve-effective-report`). It compares each recorded stage report with the run record's path and hash; each refusal names the artifact's `path`. A chain lawful on this route needs a run record created while the resolver reported the eligible shape, never a label added afterwards.
- `admitted`: run Step 0's disposition call and go on as Step 0 says, as the ordinary route does: its `CHAIN=` line binds `ARTIFACT_CHAIN`, the data Steps 1-3 use, and `chain_pass` goes to Step 1. A refusal of `verify-disclosure` or `finalize` (or unreconcilable drift) names an artifact: route it (Routes; finalize's own step runs again under the run record's `repair_run_id`), then run `verify-disclosure` again. The attempt stays on this route until admitted; it never reports a negative verdict.

### Step 0: Resolve the disposition; complete the cycle when incomplete

One call decides the cycle: no aggregator, no schema gate, no status rule of its own. `/close` runs no aggregator: a fan-out's canonical aggregate has one producer, the lane-completeness hook (`commands/dev.md` Step 11), and a gap on it is routed like any other. This order holds for explicit and bare `/close` alike: bind the task-id, then make this call, with no parent ticket/context/QA assumption before it (a fan-out cycle has no parent ticket). Parent ticket/context/QA are optional, never missing prerequisites.

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}"/scripts/resolve-dev-artifact-chain.py --disposition --stage dev --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>"
```

- **Exit 0** prints `DISPOSITION=<chain_pass|incomplete> STAGE=dev TASK=<task>`, one `GAP artifact=<path> problem=<code>: <message> lane=<lane or ->` line per gap, and, for a `/dev` task, the chain's data line `CHAIN=<JSON>`. Bind `ARTIFACT_CHAIN` to that JSON verbatim (empty for a `/do` task, whose run prints none): its `mode`, `lanes`, `report_paths`, `canonical_dev_report`, `artifact_paths`, `commit_whitelist_artifacts` and `qa_inputs` are the data Steps 1-3 use, never a second call, glob or filename guess.
- **`chain_pass`**: go to Step 1.
- **`incomplete`**: route each artifact the GAP lines name, in the order printed and with all of its problems at once (Routes, below), then run this call again; `chain_pass` goes to Step 1. A cycle missing an artifact, a lane or a whole stage completes this way; `/close` never copies lane data into, or fabricates, a parent artifact.
- **Non-zero exit** (the instrument failed; its reason is on stderr, no DISPOSITION line): run the same call once more. If it fails again, print exactly one line `OPERATION_STALLED: <the stderr reason>` and name that call as this session's next harness-repair item. Nothing else follows for this run: no question, no verdict line, no close-report section, no next step.

**cp-state handoff (optional data).** When `.claude/specs/<TASK_ID>/cp-state-qa.json` exists, bind `SPEC_ID="$TASK_ID"` and `CP_DIR=".claude/specs/$TASK_ID"`; Step 2 hands QA `$CP_DIR/cp-state-qa.json`. Otherwise `SPEC_ID=""` and QA's SECOND ACTION is left out. Nothing here is a finding.

### Routes

One rule for every gap Step 0 prints and every file a close-QA finding names (`path` below):

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/lib/obligation.py" declaring-dispatch --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>" --path "<path>"
```

It reads this task's dispatch records in every session the project's transcript store holds (a `/dev` of an earlier session included) and prints who owes `path` as JSON, or `null`. Act on the answer with one fresh synchronous dispatch: an `Agent` call with `run_in_background: false`, the same task id, lane and obligation, a new `dispatched_at`, the prompt carrying the gap or finding (path, problem, message):

- A `/do` task (`DO_REPORT` set), whatever the answer: the do-report, and a file the answer names no dispatch for (the `/do` main agent wrote it), go to dev, never to `/do`'s own steps: dispatch dev under the same task id with the obligation `<obligation v="1">{"task_id": "<TASK_ID>", "role": "dev", "pipeline": "do", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call>", "artifacts": [{"kind": "json", "path": "docs/dev/dev-report-<TASK_ID>.json", "schema": "dev-report.v2", "identity": {"task_id": "<TASK_ID>"}}]}</obligation>` to complete the `/do` work; its dev-report, which G2 verifies at dev's stop, concludes a `/do` task whose do-report is not `completed` (Step 0's call takes it), and the `/close` orchestrator writes no report.
- `source` `dispatch`, `lane` or `writer`: the answer's dispatch again — its `subagent_type`, `lane` and obligation (a `lane` answer is a lane's dev, whose report write runs the hook that writes the canonical aggregate; a `writer` answer is the dispatch whose own tool calls wrote a product file).
- `source` `todo_step` with a `subagent_call`: a fresh dispatch of that role under the same task id, from the `template` (its obligation) of the answer's `step` in `commands/<command>.md`; a wholly missing lane is rebuilt in ba → dev → qa order.
- `source` `todo_step` with no `subagent_call` (the main agent's own step, as `/dev` Step 11 or the late-repair finalize): run that step yourself under the same task id.
- `null` for a close-QA finding, or a finding that cites no artifact: that round's own QA dispatch (the answer for `docs/dev/close-report-<TASK_ID>.md`) runs again and names the artifact; route that artifact.
- `null` otherwise: no dispatch or request exists to re-run. Ask (header `Request`) what the cycle should deliver, naming the task and the artifact; the options are the requests the task's own artifacts state (its ticket or user-requirement file) and the task candidates; then dispatch dev under the same task id for the answer.

No default role. A close-QA round's findings, once routed, are followed by Step 0's call again, then a fresh close-QA round (Step 2). A dissent that would reopen a materially different scope is an owner decision: ask (header `Scope`) with the options the dissent names (this cycle's scope; the wider scope under the same task id), then route its findings.

### Step 1: Agent dispatch — three inspectors (orchestrator authority — `commands/close.md` itself, NOT QA)

**TodoWrite ordering reminder (task 20260519-211515 R3 / AC3)**: TodoWrite mark-as-in_progress for step N must precede any Agent() call dispatched within step N.
The orchestrator MUST emit a TodoWrite call updating the Step-N todo item to `in_progress` BEFORE invoking any Agent() in Step N. REQUIRED ordering: TodoWrite first, then Agent().

**Authority note**: inspector subagents (`style-inspector`, `cleanliness-inspector`, `prompt-inspector`) are orchestrator-only auditors. ONLY this `/close` command may dispatch them. Subagents (including QA in Step 2) have NO authority to dispatch inspectors.

**Cycle-diff file list**: `dev.files_modified` of the report `ARTIFACT_CHAIN.canonical_dev_report` names (the aggregate union in a fan-out cycle, used verbatim), or, for a `/do` task, `do.files_modified` of `DO_REPORT` with `dev.files_modified` of `docs/dev/dev-report-<TASK_ID>.json` when dev wrote one along its route (Routes). An empty list is passed as empty; the inspectors then return no finding.

**Registry name**: `<SESSION_ID>` in the FIRST ACTION lines of Steps 1 and 2 is the registry directory `obligation.registry_dir_for` names for `$TASK_ID` (`dev-<ts>` or `dev-command-<ts>`, from the task's canonical id):

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/prompt-workflow.py" registry-dir "$TASK_ID"
```

**Dispatch** each inspector with one Agent call whose prompt begins with its `FIRST ACTION` line, then its `<obligation v="1">` block (instantiated per dispatch from the bound `<TASK_ID>`, never hand-invented), then `--changed-files <cycle-diff-file-list>`, the instruction to write its report to its path and, when `codex_required = true`, the literal line `codex_required: true`. A fan-out cycle (`ARTIFACT_CHAIN.mode == "fanout"`, the one fan-out authority) dispatches them one at a time, each after the previous returned; any other cycle dispatches all three in ONE message:

- Agent call 1: `subagent_type: style-inspector`, prompt begins with the literal line `FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<SESSION_ID>/style-inspector.json to register with the enforcement system. Do this BEFORE any other tool call.` followed by `<obligation v="1">{"task_id": "<TASK_ID>", "lane": null, "lane_set": null, "role": "style-inspector", "pipeline": "close", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "json", "path": "docs/dev/style-inspector-report-<TASK_ID>.json", "schema": "style-inspector-report.v1", "identity": {"request_id": "<TASK_ID>"}}]}</obligation>`; it writes its report to `docs/dev/style-inspector-report-<TASK_ID>.json`.
- Agent call 2: `subagent_type: cleanliness-inspector`, prompt begins with the literal line `FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<SESSION_ID>/cleanliness-inspector.json to register with the enforcement system. Do this BEFORE any other tool call.` followed by `<obligation v="1">{"task_id": "<TASK_ID>", "lane": null, "lane_set": null, "role": "cleanliness-inspector", "pipeline": "close", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "json", "path": "docs/dev/cleanliness-inspector-report-<TASK_ID>.json", "schema": "cleanliness-inspector-report.v1", "identity": {"request_id": "<TASK_ID>"}}]}</obligation>`; it writes its report to `docs/dev/cleanliness-inspector-report-<TASK_ID>.json`.
- Agent call 3: `subagent_type: prompt-inspector`, prompt begins with the literal line `FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<SESSION_ID>/prompt-inspector.json to register with the enforcement system. Do this BEFORE any other tool call.` followed by `<obligation v="1">{"task_id": "<TASK_ID>", "lane": null, "lane_set": null, "role": "prompt-inspector", "pipeline": "close", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "json", "path": "docs/dev/prompt-inspector-report-<TASK_ID>.json", "schema": "prompt-inspector-report.v1", "identity": {"request_id": "<TASK_ID>"}}]}</obligation>`; it writes its report to `docs/dev/prompt-inspector-report-<TASK_ID>.json`.

Each inspector writes its findings JSON to its report path, and G2 checks that report at the inspector's own stop; the orchestrator does not re-read, re-validate or re-aggregate it. Step 2 passes the three report paths to QA verbatim.

**Transient failure.** An inspector that returns without its report because of the API (`529 Overloaded`, rate limited, a 0-token return) is dispatched again — that one inspector, same prompt, a fresh `dispatched_at` — until its report exists; when the Agent call itself keeps failing on the API, print one `OPERATION_STALLED: <the error>` line as Step 0 does. A substantive result, findings or clean, is never re-dispatched.

### Step 2: Delegate close debate to QA subagent

`<SESSION_ID>` is the registry name Step 1 bound.

Use the Agent tool with `subagent_type: qa` ONCE per independent judging round (a re-judge after producers fixed findings is a NEW round, dispatched fresh; QA never fixes what it judges). The entire debate of a round happens inside that single subagent call. Pass this prompt (substitute paths and $TS):

```
FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<SESSION_ID>/qa.json to register with the enforcement system. Do this BEFORE any other tool call.
SECOND ACTION (only if SPEC_ID is non-empty): read <PROJECT_ROOT>/$CP_DIR/cp-state-qa.json to load your mandatory checklist before the debate. Mark each completed checkpoint with python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/spec-check.py" mark --spec-id <SPEC_ID> --agent qa --agent-id $CLAUDE_AGENT_ID --cp-id <cp-NN>. Waive only with python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/spec-check.py" waive --spec-id <SPEC_ID> --agent qa --agent-id $CLAUDE_AGENT_ID --cp-id <cp-NN> (auto-text records actor + ISO timestamp). You MUST leave zero pending checkpoints before Stop (a discipline expectation tracked via spec-check.py — no hook blocks exit on pending checkpoints today). If `$CLAUDE_AGENT_ID` is unavailable, use the `agent_id` value written into the cp-state file by the read.

<obligation v="1">
{"task_id":"<TASK_ID>","role":"qa","pipeline":"close","profile":"final_verification","dispatched_at":"<ISO-8601 UTC ending in Z, captured immediately before this call, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>","artifacts":[{"kind":"markdown","path":"docs/dev/close-report-<TASK_ID>.md","identity_anchor":"<TASK_ID>","terminal_line_regex":"^(CLOSE: YES([ \\-—(].*)?|CLOSE_FINDINGS: [0-9]+ items?)$","waived_by_response":"^CLOSE_REPORT_APPEND_(ERROR|CRITICAL): "},{"kind":"response_line","terminal_line_regex":"^(CLOSE: YES([ \\-—(].*)?|CLOSE_FINDINGS: [0-9]+ items?|CLOSE_REPORT_APPEND_(ERROR|CRITICAL): .*)$"}],"consistency":"verdict_class"}
</obligation>

You are the QA gatekeeper evaluating whether a completed development can be closed. The orchestrator passes a `codex_required: <true|false>` flag in this dispatch:

- **`codex_required: true`** (user passed `--codex` to /close): you run a MULTI-ROUND INTERNAL DEBATE with OpenAI Codex (via the Skill tool) yourself. Follow the full Debate protocol below (Round 1 + 1b + 1b' + Round 2/3 + verdict branches 1/2/3/4/5/6/7 with branch 9 N/A).
- **`codex_required: false`** (default — no `--codex` flag): SKIP all `Skill(codex)` invocations. Run a SINGLE-ROUND QA-ONLY ASSESSMENT covering the 4 Workflow Integrity Dimension bullets + 1b cleanliness-of-THIS-diff inspector preconditions. Apply verdict branch 9 (codex disabled by user) — see verdict rules below. Branches 3/6/7 are N/A in this mode.

In both modes, the caller does NOT orchestrate rounds; you own the loop.

Input artifacts (read them first):
- Disposition: chain_pass (Step 0's last run, or the late-repair route's admitted verify-disclosure)
- Artifact-chain result: <the complete ARTIFACT_CHAIN JSON Step 0's CHAIN line printed, or "none" for /do>
- Mode: <ARTIFACT_CHAIN.mode, or "do">
- Lane matrix: <ARTIFACT_CHAIN.lanes JSON array; [] for singular or /do>
- Report paths: <ARTIFACT_CHAIN.report_paths JSON array; [] for /do>
- QA inputs: <ARTIFACT_CHAIN.qa_inputs JSON array; [] for /do>
- Singular inputs: <parent ticket/context/dev-report/QA-report/completion paths
  from artifact_paths when mode=singular; otherwise omit>
- Fan-out inputs: <for each lanes[] row, its task_id/ticket/context/dev_report/
  qa_report, plus canonical_dev_report and completion; never invent a parent
  ticket/context/QA-report>
- do-report: <do-report-<ts>.json for /do work, with dev-report-<ts>.json when dev wrote one, otherwise omit>

Treat the `lanes[]` array as a lane matrix for one parent close decision, not as
a bundled implementation-verification prompt. In fan-out mode read every row and
every `qa_inputs[]` entry; one missing/failing/inconsistent lane blocks closure.
The resolver's passed matrix is authoritative for membership and paths.

Debate protocol (all runs INSIDE you):

Round 1:
  1a. Form your initial assessment (YES/NO) on whether the dev can close. Consider:
      - Are all acceptance criteria measurably met (evidence, not code review)?
      - Is the root cause addressed and the fix correct & complete?
      - Regression risks? Scope drift? Missed edge cases?

      WORKFLOW INTEGRITY DIMENSION (mandatory — evaluate ALL four bullets explicitly; report a per-bullet PASS / FAIL / N/A-with-reason in the transcript; every FAIL is a finding that opens a round-open return regardless of AC coverage — see "Findings and return forms" below):
        1. **Downstream consumability** — Can the artifacts under evaluation be consumed by downstream commands (`/commit`, `/push`, `/merge`) without manual patching of timestamps, names, or artifact contracts? Step 0's `chain_pass` covers the chain `/commit` consumes: cite it for the exact `commit_whitelist_artifacts` (in fan-out mode the lane artifacts, consumable without copying/renaming them or fabricating parent ticket/context/QA artifacts) rather than re-checking the chain. This bullet is FAIL only when this cycle's work needed a human to patch an artifact or manufacture a pseudo-parent artifact. **For /do path** (DO_REPORT is set): N/A-with-reason — changelog-analyst accepts the do-report as its staging-whitelist source; evaluate consumability against do-report + planned close-report only.
        2. **task-id chain consistency** — Step 0's `chain_pass` covers the identity of every artifact the matrix names: cite it. `mode == "singular"` is the parent ticket → context → dev-report → QA-report → completion chain under one task-id; `mode == "fanout"` is every `lanes[]` row under that row's lane task-id plus the parent canonical dev-report and completion under the parent task-id; parent ticket/context/QA are optional and absence is PASS. **For /do path** (DO_REPORT is set): N/A-with-reason — chain is `do-report → close-report` under the same `<task-id>`; the `/dev` artifact chain is intentionally absent.
        3. **Pre-existing-defect rule** (rewritten per spec-20260503-091826 Section 5.4 rule 1+2 — out-of-scope-by-default UNLESS user-need-impact OR security OR cleanliness-of-THIS-diff) — If a Round-1 critique surfaces a "pre-existing architectural defect" or similar, the debate resolves as follows:
             (a) if THIS cycle's BA spec CLAIMS to address the defect AND the claim maps to user-need / path-dependent shared infrastructure / security / cleanliness-of-THIS-diff → the defect IS in scope and must be evaluated on its merits. If the BA-spec claim does NOT map to one of those four axes (i.e., BA over-expanded into path-external scope), the claim is itself out-of-scope and falls through to (d) — pre-existing-out-of-scope, NOT NO; the AC-deviation / out_of_scope_observations path applies instead.
             (b) if the pre-existing defect actively blocks user-need success in THIS cycle's spec (i.e., the user-stated requirement cannot be satisfied without addressing the defect) → it IS in scope; bullet evaluates on its merits and FAILS only if the defect remains;
             (c) if the pre-existing defect is a security hole (Section 5.4 rule 2: security holes are exceptions — must be fixed even when outside the user-need path) → it IS in scope and must be fixed; bullet FAILS unless addressed;
             (d) otherwise — the pre-existing defect is OUT of scope by default. Bullet PASSES. Recording in `out_of_scope_observations` is the correct disposition; the "pre-existing / out-of-scope" walkback is the default behavior, not a forbidden one. The user's binding directive: if something does not impede user experience, security, or the cleanliness of the repository as a whole, it is not necessarily a reason for NO — pre-existing defects that do not impact user needs / security / cleanliness-of-THIS-diff are NOT NO triggers.
        4. **Self-deployability** — Can the changes be committed and shipped via the project's own commit/push toolchain (`/commit`, `/push`, `/merge`) without out-of-band patching? Evaluate as the AND of these sub-items:
             (i) **/commit consumability** (PASS/FAIL) — PASS citing Step 0's `chain_pass`: `/commit` takes the exact `commit_whitelist_artifacts` plus the close/inspector outputs without orchestrator-side patches (for fan-out each lane artifact, with no optional parent ticket/context/QA artifact). FAIL if any manual artifact patch or pseudo-parent artifact was required.
             (ii) **Push permission** (PASS/FAIL) — the orchestrator's git identity has write access to the target remote(s). FAIL if push was blocked by remote permissions or required a human to push from a different identity.
             (iii) **No commit-channel bypass** (PASS/FAIL) — no manual `git commit` outside agent context, no `CLAUDE_PROJECT_DIR` override to bypass repo-rooted hook gates, no `auto-bulk:` pattern abuse to smuggle changes past `pretool-git-privilege-guard.py`. FAIL if any of these bypass channels was used.
             (iv) **User-only physical filesystem actions** (N/A-with-reason — NEVER FAIL) — any sub-item that would require the user to perform a physical filesystem action the orchestrator structurally cannot perform itself is evaluated as N/A-with-reason, NOT FAIL. The canonical example is the user touching `.hook-refactor-allow` to authorize a hook-tree edit: human-in-the-loop is intentional anti-fabrication protection per Trap 11; orchestrator-creatable sentinels would defeat the protection's threat model. The N/A reason MUST cite Trap 11 verbatim. This clause covers ONLY user-only physical filesystem actions; it does NOT cover the bypasses listed in sub-item (iii), which remain FAIL.
           Bullet 4 is PASS when (i), (ii), and (iii) are each PASS (or N/A-with-reason where structurally inapplicable per (iv)). Any FAIL in (i)–(iii) is Bullet 4 FAIL.

  1b. **Cleanliness-of-THIS-diff preconditions — inspector reports as input** (per spec-20260503-091826 Section 5.4 rule 3 + Section 5.2: integrate clean tools such as style-inspector into the close steps). Inspector reports are ALREADY GENERATED by the orchestrator (`/close` Step 1) BEFORE this dispatch. Read them at the following exact paths:
      - `docs/dev/style-inspector-report-<TASK_ID>.json`
      - `docs/dev/cleanliness-inspector-report-<TASK_ID>.json`
      - `docs/dev/prompt-inspector-report-<TASK_ID>.json`
      **DO NOT attempt to dispatch inspector subagents — you do not have that authority; the orchestrator already did Step 1.** Inspector dispatch is `/close`-orchestrator-only by design (`agents/style-inspector.md` etc. are auditors invoked at the orchestrator layer). Treat the JSON contents of the three report files above as input to the AC-2.6 verdict-plumbing rules below. Inspector findings DO NOT directly decide the verdict — `close.md`'s finding rules at AC-2.6 govern when an inspector finding becomes a routed finding.

  1b'. Invoke the Skill tool with skill=codex. Pass codex a prompt that includes:
      - The same input artifact paths
      - Your Round-1 position and rationale
      - Inspector findings from 1b above (so codex can weigh them)
      - Instruction (user-need + THIS-diff cleanliness scoped, per spec-20260503-091826 Section 5.4 rule 3 + 4): "Challenge whether this close grants YES on something that ACTUALLY satisfies the user-stated need (not just the BA AC's mechanical wording). Flag any cleanliness/style violations introduced by THIS diff (not pre-existing). Out-of-path observations and pre-existing technical debt are NOT grounds for a finding under this scoping. Reply with exactly one line `CODEX: YES` or `CODEX: NO` followed by 3-8 sentences of rationale. **If CODEX: NO, you MUST also list 2–5 specific actionable items that would flip your verdict to YES — without this list, a NO verdict is incomplete and QA will treat it as an observation, not a blocker.**"
  1c. Parse codexs response. If parsing ambiguous, treat as NO.

  **Inspector-finding → routed-finding plumbing** (AC-2.6 — encodes Section 5.4 rule 3: cleanliness scope = only violations newly introduced in this diff become findings; pre-existing historical dirt is entirely ignored):

  - **(a) Diff-scoped invocation**: close passes `--changed-files <cycle-diff-changed-files>` (e.g., derived from `git diff --name-only $BASE..HEAD` or token-equivalent cycle-diff source — changed-line metadata for line-level inspectors / file list for file-level inspectors) to all three inspectors at Round-1.
  - **(b) NEW-violation → routed finding** (only **provably-new** findings; pre-existing/ambiguous/untagged default to **ignore**): an inspector finding becomes a routed finding ONLY when it is explicitly proven NEW (introduced by THIS cycle's diff). It is a finding on that file, routed by Routes (the dispatch whose own tool calls wrote the file; none -> that round's own QA dispatch), that dispatch fixes it, the inspectors are re-run on the new diff (verifiers, independent), and a fresh QA round re-judges; the round that found it returns `CLOSE_FINDINGS: <n> items`. Findings that are pre-existing, untagged, ambiguous, or from non-diff-aware inspector runs default to **ignore** (cannot become a routed finding):
    - **Line-level inspectors** (e.g., `style-inspector` emitting `file:line`): a finding is provably NEW when **(i) its line falls within the cycle diff's changed-line range / diff-hunk overlap for that file AND (ii) the finding is also absent from the pre-diff baseline of the same file** (the violation did not exist on the corresponding pre-diff line content). Overlap alone is **necessary but NOT sufficient** — a pre-existing violation preserved on a modified line is still pre-existing. Soft fallback when pre-diff baseline comparison is impractical: dev/inspector documents the proxy used (e.g., "overlap-only used because <reason>") and close treats overlap-only findings as **advisory** unless the proxy explicitly stipulates newness.
    - **File-level inspectors** (`cleanliness-inspector`, `prompt-inspector` — granularity = `file`, not `file:line`): the inspector's output MUST distinguish NEW vs pre-existing. Two acceptable mechanisms (dev's discretion; **may be implemented individually OR combined**):
      - **(i) Inspector-side filtering**: the inspector itself emits findings only for NEW violations (e.g., comparing its analysis against a pre-diff baseline of the same file, or analyzing diff hunks directly). Findings emitted under mechanism (i) in `--changed-files` mode count as NEW **only when the inspector's documentation explicitly declares the filtering contract** (per AC-12.1 documentation requirement); absent that explicit contract, untagged file-level findings fall under the default-safe ignore rule below.
      - **(ii) Inspector-side tagging**: the inspector emits findings for the listed files but tags each with an explicit `introduced_in_diff: bool` field (or token-equivalent positive marker like `is_new: true|false`). close honors that tag.
    - **Default-safe rule for ambiguity** (covers tag absence, null, unknown, missing field, untagged output): close.md verdict logic requires an **explicit positive marker** (`introduced_in_diff: true` or token-equivalent positive value) to route a file-level finding. Findings where the marker is `false`, absent, null, unknown, or where the inspector emitted output without a marker at all, MUST default to **ignore** — they CANNOT become routed findings. `absent/unknown -> ignore` is the encoded default. Section 5.4 rule 3 requires explicit proof of newness, not absence of evidence.
    - **Default-safe rule for non-diff-aware mode** (covers no `--changed-files` arg / default full-repo run): file-level inspector findings produced in default/full-repo/non-diff-aware mode are **advisory** (never routed) unless they carry an explicit positive new-in-this-diff marker per the rule above. close.md's full-repo inspector runs (e.g., for orientation or audit) MUST NOT escalate file-level findings into routed findings absent that marker.
    - close.md verdict logic honors whichever mechanism the inspector chose (or the combination thereof): if (i) with explicit-contract documentation, close treats every finding emitted in `--changed-files` mode as NEW; if (ii), close reads the explicit positive marker and applies the default-safe rule above.
  - **(c) Pre-existing → never routed**: inspector findings whose `file:line` is **not in this diff**, OR whose file-level marker is `introduced_in_diff: false` / absent / null / untagged, OR which originate from a non-diff-aware full-repo run, MUST NOT become routed findings. `pre-existing finding ignored`. `pre-existing technical debt` and historical dirt are out-of-scope for cleanliness verdict per Section 5.4 rule 3.

  **Worked example** (the three required paths α/β/γ are walked through; a NEW finding is routed and counted in the round-open return `CLOSE_FINDINGS: <n> items`):

  - Suppose `style-inspector --changed-files` returns a finding at `path/to/component.tsx:42` (line-level), and `cleanliness-inspector --changed-files` returns a file-level finding at `path/to/util.ts` with `introduced_in_diff: true`.
  - Close evaluates each finding against the cycle diff (changed-line metadata / diff hunk ranges for line-level inspectors; honors the file-level inspector's NEW vs pre-existing marker for file-level inspectors).
  - **diff-NEW finding (line-level)**: line 42 is within the diff's changed-line range AND was absent from the pre-diff baseline of `component.tsx` → routed finding "new style violation introduced at component.tsx:42" to the dev lane that claims `component.tsx`.
  - **diff-NEW finding (file-level)**: `cleanliness-inspector` returned `introduced_in_diff: true` for `util.ts` under explicit-contract mechanism (i) or tagging mechanism (ii) → routed finding "new cleanliness violation in util.ts" to the dev lane that claims `util.ts`.
  - **(α) pre-existing finding in a changed file → ignore**: `style-inspector` returns a finding at `path/to/component.tsx:7` where line 7 IS within the diff's changed-line range BUT the pre-diff baseline of `component.tsx` already contained the same violation on the corresponding pre-diff line — overlap is necessary but not sufficient, and the pre-diff baseline shows the violation pre-existed. Outcome: ignore, not a finding. Continue evaluating other findings.
  - **(β) untagged / ambiguous finding → ignore**: `cleanliness-inspector` emits a file-level finding for `path/to/legacy.ts` with NO `introduced_in_diff` field, NO token-equivalent positive marker, and the inspector documentation does not declare an explicit-contract filtering claim — under the Default-safe rule for ambiguity, `absent/unknown -> ignore`; this `untagged finding ignored`. Outcome: not a routed finding. Continue evaluating other findings.
  - **(γ) non-diff-aware mode finding → advisory / non-blocking**: `prompt-inspector` was invoked in default full-repo mode (no `--changed-files` argument) for an orientation pass; it returns a file-level finding for `path/to/agent.md`. Under the Default-safe rule for non-diff-aware mode, this is `advisory` (never routed). Outcome: record the observation, do not route it; downstream cycles may address it through the `out_of_scope_observations` ledger if desired.

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

**Findings and return forms**: branches 3, 4, 5, 7's two fail-overs, 8 and 9's two sub-branches below never end in a negative verdict. Each one is a **finding**: QA records it in the close-report with the artifact path it concerns (that round's own report, `docs/dev/close-report-<TASK_ID>.md`, when it names none) and counts it. A round that opened at least one finding ends with the round-open return `CLOSE_FINDINGS: <n> items` (`<n>` = number of open findings): it is NON-LANDING (it grants nothing, lands nothing, and `/commit` reads it as not landed). The orchestrator then routes each finding to its file's writer under the same task id (Routes in `/close`: the dispatch the declaring-dispatch reader returns for the path), runs Step 0's disposition call again, and dispatches QA as a fresh independent judging round that re-judges from the artifacts (QA is a verifier; it NEVER edits the artifact it judges and never fixes a finding itself). No sentence in this command grants YES on a disclosure while a finding is unresolved: `CLOSE: YES*` is returned only by a round that opened no finding. The two legal returns are therefore exactly: landed (one of the four `CLOSE: YES` forms) or round-open (`CLOSE_FINDINGS: <n> items`). Findings routed by the branches: codex dissent items and QA dissent items go to the dispatch that owes the cited artifact (an unsatisfiable AC cites the acceptance criteria); a Workflow Integrity FAIL goes to the dispatch that owes the failing artifact (bullets 1, 2, 4i: the artifact itself; bullet 3: the dev lane's artifact; bullet 4iii bypass: the files the bypass wrote, else that round's own report). A completed repair is attached to the close-report as one `## Disclosures` line (below) — a record of the fix, never a substitute for it.

Verdict branches:

1. **Unanimous YES (normal happy path)**: QA position = YES AND codex position = YES (codex_status = ok) AND all four Workflow Integrity Dimension bullets PASS (or N/A-with-reason; never FAIL) → **CLOSE: YES**.

2. **AC-deviation-PASS branch** (per spec-20260503-091826 Section 5.4 rule 4: dev deviating from BA spec AC but empirically satisfying user requirement = PASS, provided dev report explicitly records the AC deviation reason). When QA's verdict is YES on user-need verification (i.e., `verified_against_complaint = true` AND `passed_user_requirement = true` per agents/qa.md report contract) but dev's diff deviated from one or more BA AC literal-wording → **CLOSE: YES** is allowed iff ALL of the following hold (necessary AND sufficient — codex-refined; citation alone is necessary but NOT sufficient):
    - **(a)** Dev report explicitly identifies the deviated AC by ID (e.g., `AC-3.1`, `AC-12.1`) — `ac_deviation_with_user_need_satisfied: true` is present in the dev report and the deviated AC IDs are listed.
    - **(b)** Dev report cites the verbatim user-need text from the BA spec that the implementation actually satisfies (the deviation is from AC mechanics, not from user need; the verbatim user-need text is reproduced).
    - **(c)** Dev report provides evidence (test result / measurement / observation) that the implemented behavior satisfies that need. Hand-wave reasoning is rejected.
    - **(d)** **QA SHALL reject this branch if the deviated AC directly encodes user-need / security / THIS-diff-cleanliness — for those, AC-deviation is plain AC-FAIL, NOT AC-deviation-PASS.** This prevents the branch becoming a downgrade vector. If the deviated AC's text encodes the user-need test itself, or a security check, or a cleanliness-of-THIS-diff check, deviation collapses back to AC-FAIL and the result follows branch 5 (QA dissent → routed finding, round-open return).
    - When (a)–(c) hold and (d) does not trigger, the verdict is **CLOSE: YES** and the close-report records the deviation rationale verbatim.

3. **Substantive Codex dissent**: codex_status = ok AND any round ended with `CODEX: NO` AND the disagreement was not resolved by a later round → codex's dissent is a finding set: codex MUST have listed 2-5 actionable flip items, and each item is a finding against the artifact it cites (that round's own report when it cites none), routed per "Findings and return forms". The round returns `CLOSE_FINDINGS: <n> items`; the producers fix; a fresh round re-judges. A codex NO without a flip list is an observation, not a finding. Trigger condition is unchanged.

4. **Workflow Integrity FAIL**: any of the four bullets evaluates to FAIL (not N/A-with-reason) → each failing bullet is a finding on the artifact it concerns (bullets 1, 2, 4i: the defective artifact's own path; bullet 3: the dev lane's artifact; bullet 4iii: the files the bypass wrote, else that round's own report), regardless of QA / codex positions; the round returns `CLOSE_FINDINGS: <n> items`. Trigger condition is unchanged.

5. **QA dissent**: QA position = NO at end of final round → QA MUST name concrete items; each is a finding against the artifact it cites (that round's own report when none), routed per "Findings and return forms"; the round returns `CLOSE_FINDINGS: <n> items`. Trigger condition is unchanged.

6. **Codex infrastructure failure (BUG-CLOSE-2 escape valve)**: codex_status ∈ {`failed_quota`, `failed_timeout`} AND QA position = YES AND all four Workflow Integrity Dimension bullets PASS → **CLOSE: YES (degraded codex consultation)**. The verdict is granted on QA's substantive YES alone because codex never produced a substantive opinion to disagree with. Document the codex_status value verbatim in the close-report transcript under a new "Degraded codex consultation" section. The dissent line is replaced by an annotation: `degraded codex consultation: codex_status=<value>, codex contributed no substantive position`. This branch ONLY applies when the failure mode is unambiguous mechanical / infrastructural transport failure (the request never produced any output at all); a successful CODEX: NO still falls under branch 3. `failed_quota` and `failed_timeout` are unambiguous (the round produced no body to inspect). `failed_parse` is NOT in this branch -- see branch 7.

7. **Codex parse failure (FINDING-4 hardening for `failed_parse`)**: codex_status = `failed_parse` AND QA position = YES AND all four Workflow Integrity Dimension bullets PASS → conditional **CLOSE: YES (degraded codex consultation)**, BUT ONLY when QA also attests in the close-report:
    - **(a)** the verbatim raw codex output text from each `failed_parse` round is recorded in the "Degraded codex consultation" section;
    - **(b)** QA performed a manual scan of that verbatim output for substantive dissent signals -- including but not limited to: `CODEX: NO`, `Codex: NO`, the literal substring `NO`, the words `bug`, `defect`, `regression`, `wrong`, `incorrect`, `must not`, `should not`, `does not work`, `fails`, `broken`, or any prose explicitly objecting to the proposed close;
    - **(c)** QA explicitly states the determination: `manual parse: NO substantive dissent signal found in failed_parse output` (verbatim wording required).

    `failed_parse` differs from `failed_quota`/`failed_timeout` because the request DID complete and the codex CLI DID emit content -- the parser merely could not map it to the `CODEX: YES` / `CODEX: NO` format. Skipping the manual scan would create a downgrade vector: a substantive `NO` could ride a malformed response into a YES verdict. If the manual parse finds ANY dissent signal, treat it as substantive Codex dissent (branch 3): a finding carrying the verbatim signal as its detail, routed per "Findings and return forms". If QA omits the verbatim attestation, the close-report is defective: a finding on `docs/dev/close-report-<TASK_ID>.md`, whose declaring QA dispatch repairs the report and re-attests in the next round (branch 8's target).

8. **Other ambiguity / parse failure on QA's side / unresolved disagreement after final round**: a defective close-report is a finding on `docs/dev/close-report-<TASK_ID>.md`, detail = a one-sentence description of the ambiguity / parse-failure / unresolved disagreement; its declaring QA dispatch repairs the report and the next round re-judges (conservative default — never silently absorbed). Distinct from branch 6: the failure is on QA's reasoning side, not codex's transport.

9. **Codex disabled by user (no `--codex` flag)** — `codex_required = false` from Step 1 → QA runs **single-round QA-only assessment** of the 4 Workflow Integrity bullets + 1b cleanliness preconditions; no `Skill(codex)` invocations attempted; `codex_status` is set to the literal sentinel `disabled_by_user`. Verdict logic collapses to:
   - QA position = YES AND all four Workflow Integrity bullets PASS (or N/A-with-reason; never FAIL) AND no NEW-violation cleanliness inspector finding → **CLOSE: YES** (annotation: `codex_disabled_by_user: codex consultation skipped because --codex flag was not passed; verdict granted on QA's substantive YES + 4 bullets PASS alone`).
   - QA position = NO at end of single round → findings per branch 5 (concrete items routed to the producers of the cited artifacts); the round returns `CLOSE_FINDINGS: <n> items`.
   - Any of the four bullets FAIL → findings per branch 4; the round returns `CLOSE_FINDINGS: <n> items`.
   - AC-deviation-PASS branch 2 is fully applicable in the codex-disabled path — when QA verdict is YES on user-need verification AND dev report contains a valid `ac_deviation_with_user_need_satisfied: true` block satisfying clauses (a)–(d) of branch 2, **CLOSE: YES** is granted with the deviation rationale recorded.
   - Branches 3 / 6 / 7 / 8 are all N/A in the codex-disabled path (codex was never invoked; there is no codex dissent to weigh, no infrastructure failure to handle, no parse failure to scan).
   - The close-report MUST record `codex_status: disabled_by_user` in the "Codex consultation" section (NOT `failed_*`), and the per-round entries record `[Codex] consultation skipped: --codex flag not passed; QA-only assessment performed`. The final line MUST be `CLOSE: YES — codex disabled by user` (when the round opened no finding; or the form `CLOSE: YES - with disclosures: <n> items` once every finding the cycle routed has been fixed and re-judged clean, `<n>` = the `## Disclosures` lines) or, when the round opened findings, `CLOSE_FINDINGS: <n> items`.

Transcript file: write the full debate to `docs/dev/close-report-<task-id>.md` (substitute `<task-id>` with the value Task-id resolution bound — the source `/dev` cycle's task-id; do NOT use a fresh `date +%Y%m%d-%H%M%S` here, that would break /commit's PRIMARY-path lookup) with this structure:
  # Close Debate Report
  Task-id, artifact-chain mode, Input files, Rounds run, Verdict. For fan-out,
  include the supplied `lanes[]` matrix and `qa_inputs[]` paths so the report
  records which independently-passed lanes were rolled into the parent decision.
  Workflow Integrity Dimension: explicit per-bullet status (1. Downstream consumability: PASS/FAIL/N/A; 2. task-id chain consistency: PASS/FAIL/N/A; 3. Pre-existing-defect rule: PASS/FAIL/N/A; 4. Self-deployability: PASS/FAIL/N/A) — with one-sentence reason for each FAIL or N/A.
  Codex consultation: explicit `codex_status` value (`ok` | `failed_quota` | `failed_timeout` | `failed_parse`). When the value is one of the failure modes, include a "Degraded codex consultation" section that records: which rounds failed, the verbatim error / timeout / parse-issue from each attempt, and the explicit acknowledgement that the verdict was granted on QA's substantive YES alone (per Verdict rule branch 6). For `failed_parse` specifically (FINDING-4), the section MUST additionally include: (i) the verbatim raw codex output text from EACH failed_parse round, (ii) QA's explicit per-round manual scan note, and (iii) the verbatim attestation `manual parse: NO substantive dissent signal found in failed_parse output`. Without all three, branch 7 is not satisfied and the result falls to branch 8 (a defective close-report: a finding on it, routed to its declaring QA dispatch).
  For each round: [QA] position + rationale; [Codex] position + rationale (or "consultation failed: <reason>" when codex_status was failed-* in that round).
  **`## Disclosures` (present whenever routing completed at least one repair this cycle):** one line per completed repair, as an attached record only, in the exact format `path: problem | 归因: role(lane) | 修复: fix evidence` (field labels stay in Chinese; no code prefix). The final line's `<n>` count (in the `CLOSE: YES - with disclosures: <n> items` form below) MUST equal the number of disclosure lines in this section. Omit the section entirely when no repair was completed.
  At bottom: the LAST non-empty line of the file MUST be EXACTLY this attempt's verdict line (Return value below: a landed `CLOSE: YES*` form such as a bare line `CLOSE: YES`, or the round-open line `CLOSE_FINDINGS: <n> items`). A round-open section is appended like any other (append-only) and never lands anything. Do NOT prefix it with `Final verdict:`, `Verdict:`, or any other label — the runtime parser (`hooks/lib/close-verdict.py`) reads the last non-empty line and requires it to start literally with `CLOSE: `; any prefix breaks `/commit`'s admission check.

Overwrite policy: if `docs/dev/close-report-<task-id>.md` already exists with a `CLOSE:` line in it (a prior closure attempt for the same task-id), do NOT silently overwrite: always preserve the existing bytes and append a fresh debate as a new section dated by ISO timestamp, then require the file's LAST non-empty line to be exactly THIS new attempt's own legal `CLOSE:` verdict line (see Return value below). Perform this append via the deterministic helper — write the new dated section's full text (ending in this attempt's own legal `CLOSE:` line) to a temp file, then invoke it with ABSOLUTE paths rooted at `<PROJECT_ROOT>` (the project root `/close` names in this prompt) so the helper can never target the wrong project's `docs/dev` tree regardless of QA's own working directory:
  `source "${CLAUDE_HOME:-$HOME/.claude}/venv/bin/activate" 2>/dev/null || true && python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/close-report-append.py" --report-path "<PROJECT_ROOT>/docs/dev/close-report-<task-id>.md" --section-file "<absolute-temp-section-path>" --task-id "<task-id>"`
  (activates the venv first). The helper performs an atomic, verified append and never mutates a byte of the file's existing content — see its own module docstring for the full read-append-readback-verification and atomicity design. Branch explicitly on its exit code:
  - **exit 0**: stdout is one line of JSON `{"status":"ok","report_path":...,"verdict_line":...}` — validate `status == "ok"`, then use `verdict_line` (NOT the raw JSON) as QA's own Return-value line.
  - **exit non-zero**: stdout is exactly the sentinel line below; propagate that exact line as QA's own Return-value output. Any other stdout shape (missing/malformed JSON on exit 0, or a non-sentinel line on exit non-zero) is a bug in the invocation itself — treat it as a verification failure and fail closed rather than guessing a verdict.
  Such a failure is NEVER a basis for falling back to treating the prior closure's verdict as authoritative for this new attempt: print the single non-`CLOSE:`-prefixed line `CLOSE_REPORT_APPEND_ERROR: <read|append|readback|verification>: <error detail>` as this attempt's not-landed signal; the pre-existing report's prior verdict is never reused as this attempt's result, and `/close` runs no Step 3 or Step 4 for it. A defective section text is a finding on `docs/dev/close-report-<task-id>.md`: this QA dispatch runs again (Routes) and the next round appends afresh. A cause in the environment that persists (no space left, a read-only filesystem) is one owner question naming it (header `Append`), whose options are the remedies for that cause, each followed by the next round.

Return value: print to stdout, as the final line of your response, the verdict line your verdict branch names — a landed `CLOSE: YES` form, or the round-open line `CLOSE_FINDINGS: <n> items` (NON-LANDING: findings are open and routed; nothing is granted); your obligation's `terminal_line_regex` declares the legal set — or the `CLOSE_REPORT_APPEND_ERROR: <read|append|readback|verification>: <error detail>` line of the Overwrite policy above. Every reader classifies the last non-empty line through `hooks/lib/close-verdict.py`: a landed form reads `yes`, the round-open line `no`, anything else `unknown` (fail closed).
```

### Step 3: Echo the verdict and name the next step

Take the final line QA returned and echo it in the orchestrator's text message to the user. The close-report itself is written by QA inside Step 2; this step echoes it and makes sure `docs/dev/close-report-<task-id>.md` exists.

- **Round-open** (`CLOSE_FINDINGS: <n> items`, or a `CLOSE_REPORT_APPEND_ERROR:` line): route each finding (Routes), run Step 0's call again, then a fresh close-QA round (Step 2). Nothing below runs for a round-open echo.
- **Landed** (`CLOSE: YES*`, any suffix): the Session Summary, the next step, then Step 4.

**Two distinct final-line contracts — DO NOT confuse**:
- **Close-report FILE** (`docs/dev/close-report-<task-id>.md`): the LAST non-empty line of the FILE must be EXACTLY the verdict line Step 2's Return value names. This is the runtime-parser contract consumed by `hooks/lib/close-verdict.py` and `/commit`'s admission check, enforced INSIDE the file QA wrote in Step 2; nothing in Step 3 alters it.
- **Orchestrator's text message to the user**: the `CLOSE:` verdict echo, then (landed only) the Session Summary and the next step. Step 4's rating question follows it as a tool call, in no output channel of the close-report.

**Session Summary — landed verdict only, before the rating question**:

- The orchestrator produces a `## Session Summary` section in its text output, chronological, 6 buckets, each bullet exactly 1 sentence (a verbatim user quote is reproduced exactly and counts as the sentence); the whole summary fits within 20 lines including the heading:
  - **Accomplished**: what was done this session
  - **Not accomplished**: gaps, deferred items, out-of-scope decisions
  - **User needs satisfied**: which stated user requirements were met
  - **User needs not satisfied**: which stated user requirements remain unmet
  - **Bugs encountered**: bugs surfaced during the session (if none, omit or write "none")
  - **Improvement opportunities**: technical debt, UX gaps, or follow-up items worth noting
- **Source binding**: the canonical report and every lane report `ARTIFACT_CHAIN.report_paths` / `qa_inputs` name (the do-report for `/do`), `docs/dev/user-requirement-<DEV_SESSION_ID>.md` (primary for the user-needs buckets) and `docs/dev/close-report-<task-id>.md`. Do NOT assume a parent QA-report exists in fan-out mode, and do not improvise outcomes the artifacts do not hold.

**Next step**: `/commit <task-id> -m "<real session summary>"`.

### Step 4: Ask the user to rate each landed cycle

After a landed `CLOSE: YES*` (any suffix), its Session Summary and its next step, make one AskUserQuestion call:

```json
{
  "questions": [{
    "question": "How well did cycle <task-id> meet what you asked for?",
    "header": "Rating",
    "multiSelect": false,
    "options": [
      {"label": "5 - Fully met", "description": "Everything you asked for, nothing missing."},
      {"label": "4 - Minor gaps", "description": "Small gaps or friction; usable as delivered."},
      {"label": "3 - Major gaps", "description": "Usable only after notable follow-up work."},
      {"label": "1-2 - Not met", "description": "Missed the request. Recorded as the lowest rating."}
    ]
  }],
  "metadata": {"source": "close-rating:<task-id>"}
}
```

The dialog adds its own Skip control and free-text box; no other option is added. The question is asked, not answered: Skip, no answer or a denial is a complete Step 4. The orchestrator does nothing with the answer — no parse, no echo, no score, log or script call; the PostToolUse hook that sees the call records it. One question per landed cycle (under `--auto`, one per landed parent, each with its own source). A round-open or `OPERATION_STALLED:` run asks nothing.

## `--auto` mode: close every close_pending parent

`--auto` closes every `close_pending` PARENT through the same unmodified Step 0 → Step 4 an explicit `/close <task-id>` runs. It is structurally distinct from the human-only `--bulk` of `commands/commit.md`: it walks every parent THROUGH the close gate, never around it.

1. **Discover** the parents once, at the start (a parent discovered later is not added to the running batch):

   ```bash
   mapfile -t CLOSE_PENDING_PARENTS < <(python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/dev-lifecycle.py" list-actionable --next-action close --project-dir "<PROJECT_ROOT>")
   ```

   Each line's first word is a parent's task-id (sorted; lane rows and spec rows never appear); the rest of the line is not used here.

2. **Walk the steps over the parents.** Each TodoStep runs for every parent, in list order, before it is marked completed: Step 0 completes each parent's cycle (`TASK_ID` bound to that parent as Task-id resolution binds a timestamp argument, a `/do` parent's `DO_REPORT` included, then its own disposition call), Step 1 dispatches each parent's inspectors, Step 2 runs each parent's close debate until it lands, Step 3 echoes each verdict with its Session Summary and next step, and Step 4 asks one rating question per landed parent. No two dispatches run at once; `codex_required` is shared by the batch.

3. **An owner decision** a parent meets — a hook rejection (CLAUDE.md Subagent Hook Discipline: the rejected operation is never retried, disguised or worked around) or a genuine choice — is one owner question naming the parent and the decision (header `Authorize` for a hook rejection: the rejected operation, the exact command the human may authorize, and declining it under Hook Discipline #4). The parent then goes on to its landed verdict; no parent is recorded and passed over.

4. **Batch line**: after Step 3, one line per parent (`<task-id>: <its landed CLOSE: line>`).

## Constraints

- /close does NOT call Skill(codex). QA does, internally.
- /close does NOT manage rounds. QA does, internally.
- /close does NOT evaluate verdict. QA does, internally.
- QA is invoked once per independent judging round. A re-judge after producers fixed findings is a new round; QA never fixes what it judges. `--auto` judges each parent in its own rounds, never concurrently.
- **Scoped findings** (per spec-20260503-091826 Section 5.1: if something does not impede user experience, security, or the overall cleanliness of the repository, it is not necessarily a finding): a finding is routed (Routes) to the dispatch that owes its artifact, fixed, and re-judged by a fresh independent round; never a silent, undocumented pass. Recoverable transient infrastructure failures (e.g., Codex quota / timeout) follow branches 6/7.
- `disable-model-invocation: true` (frontmatter) means the model cannot self-invoke /close via SlashCommand; only a human types it.
