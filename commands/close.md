---
description: Close the current dev cycle (agent infers task-id from conversation). Step 0 resolves the disposition and completes an unfinished cycle; QA judges and returns CLOSE YES; Step 3b asks the user to rate the cycle. --codex adds a Codex review to QA's judgment (default is QA alone); --auto closes every close_pending parent; --force is accepted and ignored.
argument-hint: "[--codex | --auto | --late-repair] [<task-id>|<path>]"
disable-model-invocation: true
summary: "Close the cycle: finish what is unfinished, have inspectors and QA judge it, end on `CLOSE: YES` or the findings, then ask you to rate it."
group: Ship
---

# /close

Five TodoSteps (`scripts/todo/close.py`): Step 0 resolves the disposition and completes an unfinished cycle; Step 1 dispatches three inspectors; Step 2 delegates the close judgment to QA; Step 3 echoes the verdict and names the next step; Step 3b asks the user to rate each landed cycle. Argument parsing and task-id resolution are part of this body, not TodoSteps.

`/close` dispatches, routes and echoes. It does not call Codex and does not decide the verdict: QA does, inside its own invocation.

## Invocation

```
/close                  # the task of this conversation's /dev or /do cycle (typical use)
/close <task-id>        # an explicit task; a /do task's do-report-<task-id>.json is read the same way
/close --auto           # every close_pending parent (see `--auto` mode below)
```

An explicit path also works: `/close docs/dev/ticket-<ts>.md` (legacy `ba-spec-<ts>.md`, or `do-report-<ts>.json`). No filesystem scan, no default-to-newest. Follow with `/commit <task-id>`.

`--force` (with an optional `--reason "<text>"`) is accepted and ignored: it changes nothing and nothing is logged. Two combinations ask a question first (below): `--auto` with it, and `--late-repair` with it.

## Workflow

Load the preloaded todo list: run `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/todo/close.py"`.

`<PROJECT_ROOT>` below is the `PROJECT_ROOT=` line the UserPromptSubmit hook printed for this `/close`.

**Owner questions.** Where this file asks the owner, it makes exactly one AskUserQuestion call: a header of at most 12 characters, 2-4 options that each name a concrete way on, `multiSelect: false`. The question is the pause: after the answer `/close` goes on in the same turn; an answer releases no gate, and no option offers to stop, to end, or to leave the cycle unfinished.

### Argument parsing

- `--codex` anywhere in `$ARGUMENTS`: strip it and set `codex_required = true`; otherwise `false`. It decides whether QA's judgment includes a Codex review (Step 2); the inspectors get the literal line `codex_required: true` when it is set.
- `--auto`: strip it and set `auto = true`; otherwise `false`, and every `--auto` rule is inert. A legal `--auto` skips Task-id resolution (control passes to the `--auto` mode section); it combines with `--codex`.
- `--auto` together with an explicit task-id or path, `--force` or a `--reason` value (the combinations `validate_auto_flag_combination()` in `scripts/dev-lifecycle.py` rejects): ask before any other action (header `Close mode`) which close runs. Options: `/close --auto` (every close_pending parent) and `/close <task-id>` for the task named (when none was named: one option per candidate parent of "Task candidates" below, at most three). Go on with the chosen form.

### Task-id resolution

The task-id is the one the source `/dev` or `/do` cycle used, never a fresh `date` stamp: `/commit` looks up `close-report-<task-id>.md` beside `dev-report-<task-id>.json`.

- An explicit path (ends in `.md`/`.json` or contains `/`): the task-id is its basename without the `ticket-` (legacy `ba-spec-`) or `do-report-` prefix and the suffix; a `do-report-` path also binds `DO_REPORT` to it. A path that does not exist: ask "Which task?" (below).
- A timestamp argument (e.g. `20260424-103044`): `TASK_ID=$ARGUMENTS`, with no parent ticket or QA-report check first (a fan-out cycle has no parent ticket).
- No argument: the parent task-id of this conversation's `/dev` cycle, or the `/do` task-id. No filesystem scan, no default-to-newest.

A `/do` task: bind `DO_REPORT` to `docs/dev/do-report-<TASK_ID>.json` when that file exists, or when a GAP line of Step 0 names it (a `/do` that stopped before it wrote the do-report). A dev-report that dev wrote along its route (Routes) leaves `DO_REPORT` bound.

**Which task?** When no task-id can be bound, ask (header `Task`) which task to close. The options are the task candidates, at most four: the first word of each stdout line, then the task-id of each `<task-id>: skipped: <reason>` stderr line, of `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/dev-lifecycle.py" list-actionable --next-action close --project-dir "<PROJECT_ROOT>"`. A skipped task has a gap no dispatch owes; `/close <task-id>` takes it, so offer it with its reason. Fewer than two candidates: add `/close --auto` and the tasks `list-actionable --next-action commit` prints (a closed task closing again). The dialog's own answer box takes any other task-id or path. Never default the close-report filename to a fresh timestamp.

### Late-repair route

Deliberately invoked, never automatic: without `--late-repair`, nothing in this section runs.

- `--late-repair` anywhere in `$ARGUMENTS`: strip it and set `LATE_REPAIR=true`; otherwise `false`.
- `--late-repair` with `--force`: before any eligibility check, run record or dispatch, ask (header `Repair mode`) which route runs, with the options `/close --late-repair <task-id>` and `/close <task-id>`; go on with the chosen one.
- With `LATE_REPAIR=true`, Step 0 first runs `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/late-repair-controller.py" init --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>"` once. It re-derives `late_repair_eligible` from the resolver's own output (never recompute it here) and either **declines** (`outcome: refuse`; zero run records, zero dispatch; that is no verdict: record the reason, set `LATE_REPAIR=false` and run Step 0's disposition call, the ordinary route) or **creates or reuses the controller-owned run record** (`docs/dev/late-repair-run-<task-id>.json`) before any dispatch.
- On an eligible chain, dispatch BA, then dev, then QA against the CURRENT state of the work, each from the cycle command's own template (Routes, "Cycle templates"); a measured no-change dev result is acceptable, a skipped stage is not. After each stage returns, run `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/late-repair-controller.py" record-stage --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>" --stage <ba|dev|qa> --report-path <path> --repair-run-id <id>`: the controller records the stage, its report path and the dispatch that declared it, enforces the order ba, dev, qa and refuses a second call for a dispatch already recorded. A stage dispatched again to repair its report (here or at `/commit`) is recorded again the same way; the dev report recorded again clears finalize's outcome, so Step 0's finalize runs again.
- After the three stages, Step 0 itself (the main agent's own step, whose todo item under `--late-repair` declares the effective report) runs `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/late-repair-controller.py" finalize --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>" --repair-run-id <id>`: drift detection over each declared file's recorded provenance, then a non-destructive `docs/dev/dev-report-<task-id>.effective.json` written afresh on every run (never over the dev-report) when reconcilable, or a refusal. `finalized_pending_verification` is provisional.
- Only `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/late-repair-controller.py" verify-disclosure --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>"` returning `outcome: admitted` makes the chain eligible toward `/commit` (which runs the same verification through `resolve-effective-report`); no matching run record, or no finalize outcome, is refused, naming the run record's `path`. A lawful chain needs a run record created while the resolver reported the eligible shape, never a label added afterwards.
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

**cp-state handoff (optional data).** When `.claude/specs/<TASK_ID>/cp-state-qa.json` exists, bind `SPEC_ID="$TASK_ID"` and `CP_DIR=".claude/specs/$TASK_ID"`; Step 2 hands QA that file. Otherwise `SPEC_ID=""` and QA's SECOND ACTION line is left out. Nothing here is a finding.

### Routes

One rule for every gap Step 0 prints and every file a close-QA finding names (`path` below):

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/lib/obligation.py" declaring-dispatch --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>" --path "<path>"
```

It reads this task's dispatch records in every session the project's transcript store holds (a `/dev` of an earlier session included) and prints who owes `path` as JSON, or `null`. Act on the answer with one fresh synchronous dispatch: an `Agent` call with `run_in_background: false`, the same task id, lane and obligation, a new `dispatched_at`, the prompt carrying the gap or finding (path, problem, message):

- A `/do` task (`DO_REPORT` set), whatever the answer: the do-report, and a file the answer names no dispatch for (the `/do` main agent wrote it), go to dev, never to `/do`'s own steps: dispatch dev under the same task id with the obligation `<obligation v="1">{"task_id": "<TASK_ID>", "role": "dev", "pipeline": "do", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call>", "artifacts": [{"kind": "json", "path": "docs/dev/dev-report-<TASK_ID>.json", "schema": "dev-report.v2", "identity": {"task_id": "<TASK_ID>"}}]}</obligation>` to complete the `/do` work; its dev-report, which G2 verifies at dev's stop, concludes a `/do` task whose do-report is not `completed` (Step 0's call takes it), and the `/close` orchestrator writes no report.
- `source` `dispatch`, `lane` or `writer`: the answer's dispatch again, with its `subagent_type`, `lane` and obligation (a `lane` answer is a lane's dev, whose report write runs the hook that writes the canonical aggregate; a `writer` answer is the dispatch whose own tool calls wrote a product file).
- `source` `todo_step` with a `subagent_call`: a fresh dispatch of that role under the same task id, from the `template` (its obligation) of the answer's `step` in `commands/<command>.md`; a wholly missing lane is rebuilt in ba, dev, qa order.
- `source` `todo_step` with no `subagent_call` (the main agent's own step, as `/dev` Step 11 or the late-repair finalize): run that step yourself under the same task id.
- `null` for a close-QA finding, or a finding that cites no artifact: that round's own QA dispatch (the answer for `docs/dev/close-report-<TASK_ID>.md`) runs again and names the artifact; route that artifact.
- `null` otherwise: no dispatch or request exists to re-run. Ask (header `Request`) what the cycle should deliver, naming the task and the artifact; the options are the requests the task's own artifacts state (its ticket or user-requirement file) and the task candidates. Then dispatch dev under the same task id for the answer, from the cycle command's dev template (below).

**Cycle templates.** Where no record gives a template to repeat (the `null` bullet above, the late-repair route's stages), the template is the one the command that ran the cycle holds: `commands/dev.md` (`commands/dev-command.md` for a `/dev-command` task) Step 4 for BA, Step 10 for dev, and for the final-verification QA Step 13 (`commands/dev-command.md`: Step 12). Fill it for the bound `<TASK_ID>` with a new `dispatched_at`.

A close-QA round's findings, once routed, are followed by Step 0's call again, then a fresh close-QA round (Step 2). A dissent that would reopen a materially different scope is an owner decision: ask (header `Scope`) with the options the dissent names (this cycle's scope; the wider scope under the same task id), then route its findings.

### Step 1: Agent dispatch — three inspectors (orchestrator authority — `commands/close.md` itself, NOT QA)

Mark Step 1 `in_progress` (TodoWrite) before its first Agent call. The inspectors (`style-inspector`, `cleanliness-inspector`, `prompt-inspector`) are orchestrator-only auditors: only this `/close` dispatches them; QA and every other subagent never does.

**Cycle-diff file list**: `dev.files_modified` of the report `ARTIFACT_CHAIN.canonical_dev_report` names (the aggregate union in a fan-out cycle, used verbatim), or, for a `/do` task, `do.files_modified` of `DO_REPORT` with `dev.files_modified` of `docs/dev/dev-report-<TASK_ID>.json` when dev wrote one along its route (Routes); a do-report that does not exist adds nothing. An empty list is passed as empty; the inspectors then return no finding.

**Registry name**: `<SESSION_ID>` in the FIRST ACTION lines of Steps 1 and 2 is the registry directory name of `$TASK_ID`:

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/prompt-workflow.py" registry-dir "$TASK_ID"
```

A `/do` task (`DO_REPORT` set) has no registry directory: skip this call and leave the FIRST ACTION line out of every dispatch of Steps 1 and 2; the obligation names the role.

**Dispatch** each inspector with one Agent call whose prompt begins with its `FIRST ACTION` line, then its `<obligation v="1">` block (instantiated per dispatch from the bound `<TASK_ID>`, never hand-invented; `dispatched_at` from `date -u +%Y-%m-%dT%H:%M:%SZ` run immediately before the call), then `--changed-files <cycle-diff-file-list>`, the instruction to write its report to its path and, when `codex_required = true`, the literal line `codex_required: true`. A fan-out cycle (`ARTIFACT_CHAIN.mode == "fanout"`, the one fan-out authority) dispatches them one at a time, each after the previous returned; any other cycle dispatches all three in ONE message:

- Agent call 1: `subagent_type: style-inspector`, prompt begins with the literal line `FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<SESSION_ID>/style-inspector.json to register with the enforcement system. Do this BEFORE any other tool call.` followed by `<obligation v="1">{"task_id": "<TASK_ID>", "lane": null, "lane_set": null, "role": "style-inspector", "pipeline": "close", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call>", "artifacts": [{"kind": "json", "path": "docs/dev/style-inspector-report-<TASK_ID>.json", "schema": "style-inspector-report.v1", "identity": {"request_id": "<TASK_ID>"}}]}</obligation>`; it writes its report to `docs/dev/style-inspector-report-<TASK_ID>.json`.
- Agent call 2: `subagent_type: cleanliness-inspector`, prompt begins with the literal line `FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<SESSION_ID>/cleanliness-inspector.json to register with the enforcement system. Do this BEFORE any other tool call.` followed by `<obligation v="1">{"task_id": "<TASK_ID>", "lane": null, "lane_set": null, "role": "cleanliness-inspector", "pipeline": "close", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call>", "artifacts": [{"kind": "json", "path": "docs/dev/cleanliness-inspector-report-<TASK_ID>.json", "schema": "cleanliness-inspector-report.v1", "identity": {"request_id": "<TASK_ID>"}}]}</obligation>`; it writes its report to `docs/dev/cleanliness-inspector-report-<TASK_ID>.json`.
- Agent call 3: `subagent_type: prompt-inspector`, prompt begins with the literal line `FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<SESSION_ID>/prompt-inspector.json to register with the enforcement system. Do this BEFORE any other tool call.` followed by `<obligation v="1">{"task_id": "<TASK_ID>", "lane": null, "lane_set": null, "role": "prompt-inspector", "pipeline": "close", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call>", "artifacts": [{"kind": "json", "path": "docs/dev/prompt-inspector-report-<TASK_ID>.json", "schema": "prompt-inspector-report.v1", "identity": {"request_id": "<TASK_ID>"}}]}</obligation>`; it writes its report to `docs/dev/prompt-inspector-report-<TASK_ID>.json`.

G2 checks each report at its inspector's own stop; the orchestrator does not re-read, re-validate or re-aggregate it. Step 2 passes the three report paths to QA verbatim.

**Transient failure.** An inspector that returns without its report because of the API (`529 Overloaded`, rate limited, a 0-token return) is dispatched again — that one inspector, same prompt, a fresh `dispatched_at` — until its report exists; when the Agent call itself keeps failing on the API, print one `OPERATION_STALLED: <the error>` line as Step 0 does. A substantive result, findings or clean, is never re-dispatched.

### Step 2: Delegate close debate to QA subagent

`<SESSION_ID>` is the registry name Step 1 bound. Use the Agent tool with `subagent_type: qa` ONCE per independent judging round: a re-judge after producers fixed findings is a NEW round, dispatched fresh, and QA never fixes what it judges. The whole judgment of a round, Codex review included, happens inside that one QA call. Pass this prompt (a `/do` task leaves its FIRST ACTION line out, Step 1):

```
FIRST ACTION: Read <PROJECT_ROOT>/.claude/dev-registry/<SESSION_ID>/qa.json to register with the enforcement system. Do this BEFORE any other tool call.
SECOND ACTION (only if SPEC_ID is non-empty): read <PROJECT_ROOT>/$CP_DIR/cp-state-qa.json before the review and mark or waive its checkpoints as ${CLAUDE_HOME:-$HOME/.claude}/templates/prompt-includes/checkpoint-marking.md says.

<obligation v="1">
{"task_id":"<TASK_ID>","role":"qa","pipeline":"close","profile":"final_verification","dispatched_at":"<ISO-8601 UTC ending in Z, captured immediately before this call>","artifacts":[{"kind":"markdown","path":"docs/dev/close-report-<TASK_ID>.md","identity_anchor":"<TASK_ID>","terminal_line_regex":"^(CLOSE: YES([ \\-—(].*)?|CLOSE_FINDINGS: [0-9]+ items?)$","waived_by_response":"^CLOSE_REPORT_APPEND_(ERROR|CRITICAL): "},{"kind":"response_line","terminal_line_regex":"^(CLOSE: YES([ \\-—(].*)?|CLOSE_FINDINGS: [0-9]+ items?|CLOSE_REPORT_APPEND_(ERROR|CRITICAL): .*)$"}],"consistency":"verdict_class"}
</obligation>

codex_required: <true|false>

You are the QA gatekeeper: decide whether this completed development can close. You own the whole judgment; the caller only routes your findings and dispatches a fresh round once producers fixed them. With `codex_required: false` skip Codex and apply branch 8; with `true` also run the Codex review below.

Input artifacts (read them first):
- Disposition: chain_pass (Step 0's last run)
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
- Completed repairs: <one line per repair Routes completed in this /close (Step 0, an
  earlier round), in the `## Disclosures` format; [] when none>

ASSESSMENT. Form your YES or NO: are all acceptance criteria measurably met (evidence, not code review), is the root cause addressed and the fix correct and complete, and what are the regression risks, scope drift and missed edge cases?

WORKFLOW INTEGRITY DIMENSION. Evaluate all four bullets and write PASS, FAIL or N/A-with-reason for each in the report. Every FAIL is a finding, whatever the AC coverage.
1. Downstream consumability: can `/commit`, `/push` and `/merge` consume the artifacts without manual patching of timestamps, names or contracts? Cite Step 0's `chain_pass` for the exact `commit_whitelist_artifacts` (fan-out: the lane artifacts, with no copying, renaming or fabricated parent artifact) instead of re-checking the chain. FAIL only when this cycle needed a human to patch an artifact or manufacture a pseudo-parent artifact. /do task: N/A, changelog-analyst takes the do-report as its staging whitelist; judge the do-report and the planned close-report.
2. task-id chain consistency: cite Step 0's `chain_pass` for the identity of every artifact the matrix names. Singular: parent ticket, context, dev-report, QA-report and completion under one task-id. Fan-out: each `lanes[]` row under its lane task-id plus the parent canonical dev-report and completion under the parent task-id; parent ticket/context/QA are optional and their absence is PASS. /do task: N/A, the chain is do-report to close-report under one task-id.
3. Pre-existing defect: out of scope by default (PASS; record it in `out_of_scope_observations`), and no ground for NO when it touches no user need, security or cleanliness of THIS diff. It is in scope, and the bullet FAILS while it remains, only when (a) this cycle's BA spec claims to address it and the claim maps to user need, shared infrastructure on the user's path, security or cleanliness of THIS diff (a claim outside those is itself out of scope: the AC-deviation or `out_of_scope_observations` path applies, not NO), (b) it blocks the user-stated requirement, or (c) it is a security hole, which is fixed even off the user's path.
4. Self-deployability, PASS when (i) to (iii) are each PASS or N/A-with-reason: (i) `/commit` consumes the chain (cite `chain_pass`; FAIL on a manual artifact patch or a pseudo-parent artifact); (ii) the orchestrator's git identity can push to the target remote(s) (FAIL if a push was blocked or needed a human on another identity); (iii) no commit-channel bypass: no manual `git commit` outside agent context, no `CLAUDE_PROJECT_DIR` override past repo-rooted hook gates, no `auto-bulk:` abuse past `pretool-git-privilege-guard.py` (FAIL if one was used). A sub-item that needs a user-only filesystem action (for example the user creating `.claude/.hook-refactor-allow` to authorize a hook edit) is N/A-with-reason, never FAIL; say it is user-only by design. That never covers (iii).

INSPECTOR REPORTS. Step 1 ran the inspectors; you may not dispatch them. Read `docs/dev/style-inspector-report-<TASK_ID>.json`, `docs/dev/cleanliness-inspector-report-<TASK_ID>.json` and `docs/dev/prompt-inspector-report-<TASK_ID>.json` as input, never as the verdict: only what THIS diff introduced counts. A finding becomes a routed finding (on that file, via Routes; the inspectors then run again on the new diff and a fresh round re-judges) only when it is explicitly proven NEW in this diff; every other finding is ignored or advisory, never routed.
- Line-level (`style-inspector`, `file:line`): NEW when the line is inside the cycle diff's changed-line range and the finding is absent from the pre-diff baseline of that file; overlap alone is not enough. When a baseline comparison is impractical and the inspector documents its proxy, an overlap-only finding is advisory unless the proxy stipulates newness.
- File-level (`cleanliness-inspector`, `prompt-inspector`): NEW only with an explicit positive marker (`introduced_in_diff: true` or an equivalent), or when the inspector's documentation declares that in `--changed-files` mode it emits NEW findings only. A false, absent, null, unknown or missing marker means ignore.
- A finding outside the diff, one from a run without `--changed-files`, and any untagged or ambiguous finding is never routed.

CODEX REVIEW (only with `codex_required: true`). Codex calls follow ${CLAUDE_HOME:-$HOME/.claude}/templates/prompt-includes/codex-consultation.md; this adds only what /close needs. QA decides the verdict; Codex has no veto.
- Prelude: USER REQUIREMENT is the user's verbatim requirement (`docs/dev/user-requirement-<SESSION_ID>.md`, else the ticket's or do-report's text); SCOPE is whether closing grants YES on something that really satisfies that need, not only the AC wording, plus the cleanliness of THIS diff; OUT OF SCOPE is pre-existing code, technical debt and out-of-path observations. Also give Codex the input artifact paths, your assessment with its rationale and the inspector findings. Codex ends with one line, `CODEX: YES` or `CODEX: NO`.
- Round 1 is one complete pass: everything in scope at once, style of this diff included, one full list. Count rounds by the Codex consultations the close report records: this one is round n when n-1 are recorded.
- Flip items are the blocker, high and medium findings with a realistic trigger that you classify in_scope_real_bug. Only they send work back (branch 3).
- Rounds 2 and 3 are re-reviews: give Codex the earlier round's flip items from the close report (not the items already on the follow-up list) and the diff the repairs made since (the files `Completed repairs` names). It reports each of them as fixed or not fixed, and only new blocker or high defects the fix itself introduced; a flip item reported not fixed stays one. Never ask for a new complete pass.
- Classify every finding in_scope_real_bug, in_scope_minor, out_of_scope or nitpick with a one-line reason; you may reject one. Edge, style, in_scope_minor and out_of_scope findings go to the close report's follow-up list, never to a finding or another round; a nitpick stays in the transcript with its reason.
- After round 3 nothing below blocker reopens the cycle: what is still open and below blocker goes to the follow-up list and the close lands. A blocker still open is a finding (branch 3), re-judged as a re-review.
- No parseable `CODEX: YES` or `CODEX: NO` line: ask Codex once more for that line; if that fails too, your own verdict stands with a note (branch 6).
- `codex_status` of this round: `ok`, `failed_quota` (usage limit), `failed_timeout` (no reply by the deadline) or `failed_parse` (no verdict line after the second request).

FINDINGS. A negative result is a finding, never a negative verdict (what impedes no user need, no security and no cleanliness of the repository is not necessarily one). Record it in the close report with the artifact path it concerns (this round's own report, `docs/dev/close-report-<TASK_ID>.md`, when it names none) and count it. A round that opened a finding ends with `CLOSE_FINDINGS: <n> items`: it grants and lands nothing, and `/commit` reads it as not landed. The orchestrator routes each finding to the writer of its artifact under the same task id, runs Step 0's call again and dispatches a fresh round that re-judges from the artifacts; you never edit what you judge. A landed `CLOSE: YES` form comes only from a round that opened no finding. Findings go to the dispatch that owes the cited artifact (an unsatisfiable AC cites the acceptance criteria); a Workflow Integrity FAIL goes to the dispatch that owes the failing artifact (bullets 1, 2, 4i: the artifact itself; bullet 3: the dev lane's artifact; bullet 4iii: the files the bypass wrote, else this round's report). A completed repair is attached as one `## Disclosures` line, a record and never a substitute for the fix.

VERDICT BRANCHES.
1. Normal YES: your position is YES, the four bullets are PASS or N/A-with-reason, no NEW-violation inspector finding is open, and `codex_status` is `ok` with no flip item open (Codex answered YES, or only below-blocker items are on the follow-up list) -> `CLOSE: YES`.
2. AC-deviation PASS: your verdict is YES on user-need verification (`verified_against_complaint` and `passed_user_requirement` both true, per agents/qa.md) but dev deviated from an AC's literal wording -> `CLOSE: YES` only if (a) the dev report names the deviated AC by ID and carries `ac_deviation_with_user_need_satisfied: true`, (b) it cites the verbatim user-need text from the BA spec that the implementation satisfies (the deviation is in AC mechanics, not the need), (c) it gives evidence (test result, measurement, observation), not hand-waving, and (d) the deviated AC does not itself encode the user-need test, a security check or a cleanliness-of-THIS-diff check; if it does, that is a plain AC FAIL (branch 5). A citation alone is necessary, not sufficient. The report records the deviation rationale verbatim.
3. Codex flip items: `codex_status: ok` and at least one flip item is open after your classification -> one finding per flip item. A `CODEX: NO` with no flip item opens none. After round 3 a flip item below blocker is listed, not a finding.
4. Workflow Integrity FAIL: a bullet is FAIL (not N/A-with-reason) -> one finding per failing bullet, whatever the positions.
5. QA dissent: your position is NO -> name concrete items; each is a finding against the artifact it cites.
6. Codex unavailable: `codex_status` is `failed_quota`, `failed_timeout` or `failed_parse`, your position is YES and the four bullets are PASS -> `CLOSE: YES - degraded codex consultation: codex_status=<value>`. The verdict stands on your own judgment; the report's "Degraded codex consultation" section lists each failed attempt with its verbatim error, timeout or unparsable output.
7. Other ambiguity or an unresolved disagreement on your side: a defective close-report is a finding on `docs/dev/close-report-<TASK_ID>.md` with a one-sentence description; its declaring QA dispatch repairs it and the next round re-judges. Never absorb it silently.
8. Codex disabled (`codex_required: false`): `codex_status` is the literal `disabled_by_user`; branches 3 and 6 do not apply. Position YES, four bullets PASS or N/A-with-reason and no NEW-violation inspector finding -> `CLOSE: YES — codex disabled by user`, annotated `codex_disabled_by_user: codex consultation skipped because --codex flag was not passed; verdict granted on QA's substantive YES + 4 bullets PASS alone`. Position NO -> branch 5; a FAIL bullet -> branch 4; branch 2 applies as written. The report records `codex_status: disabled_by_user` and, per round, `[Codex] consultation skipped: --codex flag not passed; QA-only assessment performed`.

TRANSCRIPT. Write the full judgment to `docs/dev/close-report-<TASK_ID>.md` (the source cycle's task-id, never a fresh `date` stamp: `/commit` looks the file up by it), headed `# Close Debate Report`, with:
- task-id, artifact-chain mode, input files, rounds run, verdict; for fan-out also the supplied `lanes[]` matrix and `qa_inputs[]` paths;
- the Workflow Integrity Dimension: PASS, FAIL or N/A for each bullet, a one-sentence reason for each FAIL or N/A;
- `codex_status` (`ok`, `failed_quota`, `failed_timeout`, `failed_parse` or `disabled_by_user`) and, for a failure value, the "Degraded codex consultation" section of branch 6;
- per round, `[QA]` position and rationale, and `[Codex]` each finding with its severity (blocker, high, medium, edge, style), classification and one-line reason (a re-review is given its flip items), or `consultation failed: <reason>`;
- `## Follow-up list` (whenever an item is listed): one line per item with its severity and classification;
- `## Disclosures` (whenever routing completed a repair this cycle): one line per line of the dispatch's `Completed repairs` input, in the format `path: problem | 归因: role(lane) | 修复: fix evidence` (the labels stay in Chinese; no code prefix). The `<n>` of `CLOSE: YES - with disclosures: <n> items` equals the number of these lines. Omit the section when no repair was completed.
The LAST non-empty line of the file is exactly this attempt's verdict line (Return value), with no `Verdict:` or other label before it: `hooks/lib/close-verdict.py` reads that line and requires it to start with `CLOSE: `, and `/commit`'s admission check depends on it. A round-open section is appended like any other.

OVERWRITE POLICY. If `docs/dev/close-report-<TASK_ID>.md` already holds a `CLOSE:` line (an earlier attempt), never overwrite it: keep its bytes and append a fresh section dated by ISO timestamp, whose last non-empty line is exactly this attempt's own verdict line. Write the new section's full text to a temp file and append it with absolute paths rooted at `<PROJECT_ROOT>`, so the append can never reach another project's `docs/dev`: `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/close-report-append.py" --report-path "<PROJECT_ROOT>/docs/dev/close-report-<task-id>.md" --section-file "<absolute-temp-section-path>" --task-id "<task-id>"`. The helper appends atomically, reads back and verifies, and never changes an existing byte. On exit 0 its stdout is one JSON line `{"status":"ok","report_path":...,"verdict_line":...}`: check `status == "ok"` and use `verdict_line` (not the raw JSON) as your Return value. On a non-zero exit its stdout is the sentinel line `CLOSE_REPORT_APPEND_ERROR: <read|append|readback|verification>: <error detail>` (or `CLOSE_REPORT_APPEND_CRITICAL: ...`): return that exact line. Any other stdout shape is a verification failure: fail closed, never guess a verdict. A failure is never a reason to take the earlier attempt's verdict as this attempt's: the sentinel is this attempt's not-landed signal, and `/close` runs no Step 3 or Step 3b for it. A defective section text is a finding on the report, and this QA dispatch runs again (Routes).

RETURN VALUE. Your response ends with the verdict line your branch names (`CLOSE: YES - with disclosures: <n> items` replaces it once every finding the cycle routed was fixed and re-judged clean), or with `CLOSE_FINDINGS: <n> items` (NON-LANDING), or with the append sentinel above. Your obligation's `terminal_line_regex` declares the legal set; every reader classifies the last non-empty line through `hooks/lib/close-verdict.py`: a landed form reads `yes`, the round-open line `no`, anything else `unknown` (fail closed).
```

### Step 3: Echo the verdict and name the next step

Echo the final line QA returned in the orchestrator's text message. QA wrote the close-report in Step 2; make sure `docs/dev/close-report-<task-id>.md` exists.

- **Round-open** (`CLOSE_FINDINGS: <n> items`, or a `CLOSE_REPORT_APPEND_` line): route each finding (Routes), run Step 0's call again, then a fresh close-QA round (Step 2). A cause in the environment that persists (no space left, a read-only filesystem) is one owner question naming it (header `Append`), whose options are the remedies for that cause, each followed by the next round. Nothing below runs for a round-open echo.
- **Landed** (`CLOSE: YES*`, any suffix): the Session Summary, the next step, then Step 3b.

The close-report FILE ends with exactly the verdict line (Step 2); the message holds the `CLOSE:` echo and, landed only, the Session Summary and the next step. Step 3b's question is a tool call, in no output channel of the close-report.

**Session Summary** (landed only, before the rating question): a `## Session Summary` section in your text output, chronological, within 20 lines including the heading, six buckets, each bullet one sentence (a verbatim user quote counts as the sentence): **Accomplished**; **Not accomplished** (gaps, deferred items, out-of-scope decisions); **User needs satisfied**; **User needs not satisfied**; **Bugs encountered** (omit or "none"); **Improvement opportunities** (technical debt, UX gaps, the close report's follow-up list). Sources: the canonical report and every lane report `ARTIFACT_CHAIN.report_paths` / `qa_inputs` name (the do-report for `/do`), `docs/dev/user-requirement-<SESSION_ID>.md` (primary for the user-needs buckets) and `docs/dev/close-report-<task-id>.md`. Assume no parent QA-report in fan-out mode, and improvise no outcome the artifacts do not hold.

**Next step**: `/commit <task-id> -m "<real session summary>"`.

### Step 3b: Ask the user to rate each landed cycle

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

The dialog adds its own Skip control and free-text box; no other option is added. The question is asked, not answered: Skip, no answer or a denial is a complete Step 3b. The orchestrator does nothing with the answer — no parse, no echo, no score, log or script call; the PostToolUse hook that sees the call records it. One question per landed cycle (under `--auto`, one per landed parent, each with its own source). A round-open or `OPERATION_STALLED:` run asks nothing.

## `--auto` mode: close every close_pending parent

`--auto` closes every `close_pending` PARENT through the same unmodified Step 0 to Step 3b an explicit `/close <task-id>` runs. It is distinct from the human-only `--bulk` of `commands/commit.md`: it walks every parent THROUGH the close gate, never around it.

1. **Discover** the parents once, at the start (a parent discovered later is not added to the running batch):

   ```bash
   python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/dev-lifecycle.py" list-actionable --next-action close --project-dir "<PROJECT_ROOT>"
   ```

   Each stdout line's first word is a parent's task-id (sorted; lane rows and spec rows never appear); the rest of the line is not used here. A task with a gap no dispatch record or todo step owes is not listed (`/close <task-id>` takes it): its `<task-id>: skipped: <reason>` line is on stderr.

2. **Walk the steps over the parents.** Each TodoStep runs for every parent, in list order, before it is marked completed: Step 0 binds `TASK_ID` to the parent as Task-id resolution binds a timestamp argument (a `/do` parent's `DO_REPORT` included) and makes its own disposition call; Step 2 runs each parent's close judgment until it lands; Step 3b asks one rating question per landed parent. No two dispatches run at once; `codex_required` is shared by the batch.

3. **An owner decision** a parent meets — a hook rejection (CLAUDE.md Subagent Hook Discipline: the rejected operation is never retried, disguised or worked around) or a genuine choice — is one owner question naming the parent and the decision (header `Authorize` for a hook rejection: the rejected operation, the exact command the human may authorize, and declining it under Hook Discipline #4). The parent then goes on to its landed verdict; no parent is recorded and passed over.

4. **Batch line**: after Step 3, one line per parent (`<task-id>: <its landed CLOSE: line>`), then each `skipped:` line of the discovery, verbatim.
