---
description: Test validation workflow with edge case detection, systematic validation, and quality enforcement
disable-model-invocation: true
---

# Test Command Orchestrator

Checks the project's `tests/` validators against the edge cases found in its git history, then runs them. Two subagents do the judging: `test-validator` (syntax, dependencies, quality) and `test-executor` (runs the validators). The validation context travels in the validator's dispatch; the reports and the execution context are JSON files in `tests/reports/`.

Steps 1-7, 10 and 11 are scripts in `<HARNESS_ROOT>/scripts/steps/` that print `key=value` facts, read below by key. `<request_id>` and `<timestamp>` are the values Step 1 prints; pass them to every later script. No step ends the command with a failure: each missing prerequisite has a repair named in its step, and the command goes on.

## Execution Steps

### Step 1: Initialize Workflow and Load TodoList

```bash
python3 "<HARNESS_ROOT>/scripts/todo/test.py"
python3 "<HARNESS_ROOT>/scripts/steps/test-prepare.py" init
```

`init` prints `request_id`, `timestamp`, `project_root` and `tests_dir` (`created` or `existing`). It creates `tests/reports/`; when `tests/` did not exist it creates `tests/{scripts,instructions,data/fixtures,data/mocks,reports}` and copies the instruction templates from `<HARNESS_ROOT>/tests/instructions/` (never README.md or INDEX.md).

### Step 2: Analyze Git History for Edge Cases

```bash
python3 "<HARNESS_ROOT>/scripts/steps/test-prepare.py" edge-cases
```

Runs `scripts/analyze-git-edge-cases.sh` over the last 90 days of fix, bug, error, issue and problem commits and groups them by edge case id (EC001, EC002, ...) into `docs/test/edge-case-analysis.json`. Prints `edge_cases=<count>`. On `edge_case_analysis=failed` go on: Step 4 skips the cleanup.

### Step 3: Migrate test/ to tests/ if Needed

```bash
python3 "<HARNESS_ROOT>/scripts/steps/test-prepare.py" migrate
```

When `test/` exists and `tests/` is absent or older, runs `scripts/migrate-test-to-tests.sh` (merges test/ into tests/, keeps a differing file as a `.from-test-folder` backup, safe to repeat). `migration=` is `migrated` (tell the user to review any `tests/<path>.from-test-folder`: it holds the copy from test/ that differed from the one in tests/), `none`, `failed` (go on; Step 5 checks the structure) or `both_exist` (tests/ is newer: leave both and tell the user the script can be run by hand). The command never removes `test/`; the user does once tests/ is reviewed.

### Step 4: Cleanup tests/ Based on Git History

```bash
python3 "<HARNESS_ROOT>/scripts/steps/test-prepare.py" cleanup
```

Runs `scripts/cleanup-tests-folder.sh`: removes validators whose edge case id is not in the analysis; keeps validators without an id, `reports/`, `data/`, README.md and INDEX.md. `cleanup=skipped` (analysis or `tests/` missing) and `cleanup=failed` need no action.

### Step 5: Check Test Folder Exists

```bash
python3 "<HARNESS_ROOT>/scripts/steps/test-validators.py" check
```

Prints `status`, `missing`, `script_validators`, `instruction_validators` and `total_validators`.

- `status=ok`: Step 6.
- `status=structure_incomplete` (`missing=` names the absent folders): run `python3 "<HARNESS_ROOT>/scripts/steps/test-prepare.py" init --full`, which creates the Step 1 structure, then `check` again.
- `status=no_validators`: create validators for the edge cases in `docs/test/edge-case-analysis.json`, one per edge case: `tests/scripts/validate-<name>.py` or `tests/instructions/<name>.md`, with the edge case id (EC###) in its first 20 lines. Then `check` again. When the analysis lists no edge case (or Step 2 failed) there is nothing to create: go on with zero validators and say so in the completion report.

### Step 6: Discover Validators

```bash
python3 "<HARNESS_ROOT>/scripts/steps/test-validators.py" discover --request-id <request_id>
```

Writes `tests/reports/validator-registry-<request_id>.json`: every script validator (`tests/scripts/validate-*.py`) and instruction validator (`tests/instructions/*.md` except `*guide.md`) with `type`, `path`, `name`, `edge_case` (first EC### in its first 20 lines), `priority` (its `Priority:` header, else medium) and `description` (its `Purpose:` header).

### Step 7: Build Validation Context

```bash
python3 "<HARNESS_ROOT>/scripts/steps/test-context.py" validation --request-id <request_id> --timestamp <timestamp>
```

Prints `status`, `validators` and `context`: the validation context as one JSON line, in the Input Format of `agents/test-validator.md` (that block is the contract; keep it there). It writes no file: Step 8 hands the JSON to the validator. `status=missing_registry`: run Step 6 again.

### Step 8: Invoke Test Validator

Delegate to the test-validator subagent (Agent tool, `run_in_background: false`), giving it the Step 7 `context` JSON unchanged as the context it receives: check the validators listed there. It writes `tests/reports/validation-report-<request_id>.json` as `agents/test-validator.md` defines (`validator.status`, `validators_checked`, `syntax_errors`, `dependency_errors`, `quality_issues`, `edge_case_coverage`, `summary`).

### Step 9: Process Validation Results

Read `validator.status` and `validator.validators_checked`. `pass`: Step 10. `fail`: present the errors, fix them, and re-run Step 8 until it passes. No readable report: re-run Step 8.

### Step 10: Build Execution Context

```bash
python3 "<HARNESS_ROOT>/scripts/steps/test-context.py" execution --request-id <request_id> --timestamp <timestamp> --validation-status pass --validators-checked N
```

Writes `tests/reports/execution-context-<request_id>.json`, the context `agents/test-executor.md` reads (this is its template):

```json
{
  "request_id": "test-YYYYMMDD-HHMMSS",
  "timestamp": "ISO-8601",
  "context": {
    "project_root": "<abs-path>",
    "test_directory": "<abs-path>/tests",
    "venv_path": "<HARNESS_ROOT>/venv",
    "validators": [{"type": "script|instruction", "path": "tests/scripts/<name>.py", "edge_case": "EC002", "priority": "critical"}]
  },
  "parameters": {"fail_fast": false, "verbose": true, "report_path": "tests/reports/execution-report-<request_id>.json"},
  "validation_report": {"status": "pass", "validators_checked": 10, "all_valid": true}
}
```

The validators come from the registry. `validation_report` holds the `status` and `validators_checked` you pass: `pass` (Step 9 sends only a pass here) and `N`, the `validator.validators_checked` you read in Step 9. Step 11 adds `context.checkpoint_commit`. `status=missing_registry`: run Step 6.

### Step 11: Create Safety Checkpoint

```bash
python3 "<HARNESS_ROOT>/scripts/steps/test-context.py" checkpoint --request-id <request_id>
```

Runs `<HARNESS_ROOT>/hooks/checkpoint.sh "Before /test execution"` (a snapshot on `refs/checkpoints/<branch>`, never on HEAD; nothing to snapshot is fine) and records the ref's commit as `context.checkpoint_commit` in the execution context. Prints `checkpoint_ref`, `checkpoint_commit` (`none` when the ref does not exist), `rollback_file` and `rollback_tree` (destructive); Step 16 reports them.

### Step 12: Invoke Test Executor

Delegate to the test-executor subagent (Agent tool, `subagent_type: "test-executor"`, `run_in_background: false`). Its prompt states the task, not the method: run every validator in `tests/reports/execution-context-<request_id>.json` against the project, go on when one fails unless `fail_fast` is true, and write `tests/reports/execution-report-<request_id>.json`. The procedure is in `agents/test-executor.md`.

Expected report: `executor.status`, `executor.results[]`, `executor.summary` (total, passed, failed, errors, pass_rate, edge_cases_prevented, priority_breakdown) and `executor.failed_tests[]`.

### Step 13: Process Execution Results

Read `executor.status` and `executor.summary.total_tests`, `.passed`, `.failed`, `.errors`.

- `executor.status == "completed"` with `failed == 0` and `errors == 0`: Step 16.
- `executor.status == "completed"` with `failed > 0` or `errors > 0`, or `executor.status == "partial"`: Step 14.
- No readable report, or any other status: present the executor's error, fix its cause, re-run Step 12.

### Step 14: Present Test Failures to User

Present, as plain text without emoji:

- the project, tests run, passed of total and pass rate;
- each failure, critical priority first: edge case id and title, validator, violation count, affected files as `path:line`, the recommendation, and the validator's fix command where it has one;
- the passed validators with their edge case ids;
- edge cases prevented of covered, and execution time;
- the paths of the validation, execution and registry reports in `tests/reports/`.

### Step 15: Fix Failures and Re-run

Fix every failure Step 14 presented, from its recommendation or the failed validator's fix script where one exists, then re-run from Step 10 (from Step 8 when a fix changed a validator). Step 13 routes the new report; repeat Steps 14-15 until it routes to Step 16.

Ask the owner only when a fix needs a decision the recommendation, the code or a sensible default cannot make (for example, two fixes that change the project's behaviour differently): one AskUserQuestion inside the turn that names that decision and offers the candidate fixes as its options. Every option is a fix that is applied and re-run; no option ends /test, skips a validator or accepts a failure. The answer only pauses: apply the chosen fix and continue.

### Step 16: Generate Completion Report

Create `tests/reports/completion-<request_id>.md` summarizing: request ID, project path, timestamp, overall status; validation results (validators checked, syntax, dependency and quality issues); execution results (total, passed, failed, errors, pass rate, execution time); edge cases prevented; each failure fixed in an earlier round, with its fix; the checkpoint ref, commit and rollback commands from Step 11; a `both_exist` migration or a zero-validator run if either happened; and the paths of all report files.
