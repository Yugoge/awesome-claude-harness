---
description: Test validation workflow with edge case detection, systematic validation, and quality enforcement
disable-model-invocation: true
---

# Test Command Orchestrator

Comprehensive testing and validation framework with orchestrated multi-agent workflow.

---

## Philosophy

Enforce documented standards through automated validation. Prevent recurring edge cases discovered in git history analysis.

---

## Workflow Overview

This command orchestrates two specialized subagents:

1. **test-validator**: Validates test syntax, dependencies, and quality
2. **test-executor**: Executes script-based and AI instruction-based tests

All agents communicate via JSON in `tests/reports/`.

---

## Execution Steps

### Step 1: Initialize Workflow and Load TodoList

Load TodoList checklist:

```bash
source "${CLAUDE_HOME:-$HOME/.claude}/venv/bin/activate" && python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/todo/test.py"
```

Set up working directory: create `tests/reports/`, generate `REQUEST_ID="test-$(date +%Y%m%d-%H%M%S)"` and `TIMESTAMP` in ISO-8601 format.

**Test folder structure**: If `tests/` does not exist, initialize it by creating subdirectories `tests/{scripts,instructions,data/fixtures,data/mocks,reports}` and copying template files from `<HARNESS_ROOT>/tests/` (README.md, INDEX.md, and instructions/*.md).

### Step 2: Analyze Git History for Edge Cases

Analyze git history to identify real edge cases from bug fix commits:

```bash
# Run git edge case analyzer
bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/analyze-git-edge-cases.sh" \
  --project-root "$(pwd)" \
  --since-date "90.days.ago" \
  --output "docs/test/edge-case-analysis.json"

# Check if analysis succeeded
if [[ $? -eq 0 ]]; then
  EDGE_CASES_FOUND=$(jq -r '.summary.total_edge_cases' docs/test/edge-case-analysis.json)
  echo "✅ Found $EDGE_CASES_FOUND edge cases from git history"
else
  echo "⚠️  Git edge case analysis failed - proceeding without cleanup"
fi
```

This analyzer:
- Searches git history for commits with keywords: fix, bug, error, issue, problem
- Extracts edge case identifiers (EC001, EC002, etc.)
- Groups by edge case and counts occurrences
- Generates JSON analysis for validator cleanup

### Step 3: Migrate test/ to tests/ if Needed

Check if old `test/` folder exists and migrate to `tests/`:

```bash
if [[ -d "test" ]] && [[ ! -d "tests" || "test" -nt "tests" ]]; then
  echo "Found test/ folder - migrating to tests/ (Python standard naming)"

  bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/migrate-test-to-tests.sh" --project-root "$(pwd)"

  if [[ $? -eq 0 ]]; then
    echo "✅ Migration complete - review tests/ folder"
    echo "   Remove test/ folder when ready: rm -rf test/"
  fi
elif [[ -d "test" ]] && [[ -d "tests" ]]; then
  echo "⚠️  Both test/ and tests/ exist - manual review recommended"
  echo "   Run: bash ${CLAUDE_HOME:-$HOME/.claude}/scripts/migrate-test-to-tests.sh --project-root $(pwd)"
fi
```

This migration:
- Merges all content from test/ into tests/
- Preserves files, avoids overwriting different content
- Creates backups for conflicts
- Idempotent (safe to run multiple times)

### Step 4: Cleanup tests/ Based on Git History

Remove validators that don't correspond to edge cases found in git history:

```bash
if [[ -f "docs/test/edge-case-analysis.json" ]] && [[ -d "tests" ]]; then
  echo "Cleaning tests/ folder based on git history analysis..."

  bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/cleanup-tests-folder.sh" \
    --project-root "$(pwd)" \
    --edge-case-analysis "docs/test/edge-case-analysis.json"

  if [[ $? -eq 0 ]]; then
    echo "✅ Tests folder cleanup complete"
  fi
else
  echo "⚠️  Skipping cleanup - missing edge case analysis or tests/ folder"
fi
```

This cleanup:
- Preserves validators matching edge cases from git history
- Removes validators for hypothetical edge cases not in git
- Always preserves reports/ and data/ folders
- Maintains documentation files (README.md, INDEX.md)

### Step 5: Check Test Folder Exists

Verify tests infrastructure in place:

```bash
# Check required directories
if [[ ! -d "tests/scripts" ]] || [[ ! -d "tests/reports" ]]; then
  echo "❌ ERROR: Test folder structure incomplete" >&2
  echo "Run Step 1 initialization or manually create tests/ directory" >&2
  exit 1
fi

# Count available validators
SCRIPT_VALIDATORS=$(find tests/scripts -name "validate-*.py" 2>/dev/null | wc -l)
INSTRUCTION_VALIDATORS=$(find tests/instructions -name "*.md" -not -name "*guide.md" 2>/dev/null | wc -l)
TOTAL_VALIDATORS=$((SCRIPT_VALIDATORS + INSTRUCTION_VALIDATORS))

echo "Found $TOTAL_VALIDATORS validators ($SCRIPT_VALIDATORS scripts, $INSTRUCTION_VALIDATORS instructions)"

if [[ $TOTAL_VALIDATORS -eq 0 ]]; then
  echo "⚠️  WARNING: No validators found in tests/scripts/ or tests/instructions/" >&2
  echo "Create validators based on edge case analysis in docs/test/edge-case-analysis.json" >&2
  exit 1
fi
```

### Step 6: Discover Validators

Scan tests directory for available validators:

```bash
# Discover script-based validators
SCRIPT_VALIDATORS=$(find tests/scripts -name "validate-*.py" -type f 2>/dev/null)

# Discover AI instruction-based validators
INSTRUCTION_VALIDATORS=$(find tests/instructions -name "*.md" -type f -not -name "*guide.md" 2>/dev/null)

# Parse validator metadata (edge case, priority)
# Extract from file headers using head/grep
# Build validator registry
```

Example validator registry:

```json
{
  "validators": [
    {
      "type": "script",
      "path": "tests/scripts/validate-venv-usage.py",
      "name": "validate-venv-usage",
      "edge_case": "EC002",
      "priority": "critical",
      "description": "Venv usage violations (8 instances)"
    },
    {
      "type": "instruction",
      "path": "tests/instructions/claude-md-protection.md",
      "name": "claude-md-protection",
      "edge_case": "EC001",
      "priority": "high",
      "description": "CLAUDE.md protection validation"
    }
  ]
}
```

Save to: `tests/reports/validator-registry-{REQUEST_ID}.json`

### Step 7: Build Validation Context

Create comprehensive JSON context for validator subagent:

```json
{
  "request_id": "test-YYYYMMDD-HHMMSS",
  "timestamp": "ISO-8601",
  "orchestrator": {
    "command": "test",
    "phase": "validation",
    "requirement": "Validate test syntax, dependencies, and quality before execution"
  },
  "context": {
    "project_root": "/absolute/path/to/project",
    "test_directory": "/absolute/path/to/project/tests",
    "venv_path": "<HARNESS_ROOT>/venv",
    "validators": [
      {
        "type": "script",
        "path": "tests/scripts/validate-venv-usage.py",
        "edge_case": "EC002",
        "priority": "critical"
      }
    ]
  },
  "validation_criteria": {
    "syntax": ["Python syntax valid", "No import errors", "Argparse defined"],
    "dependencies": ["All imports available in venv", "No circular dependencies"],
    "quality": ["Exit codes documented", "JSON output format", "Error handling present"],
    "edge_cases": ["Prevents documented edge case", "Covers patterns from git analysis"]
  }
}
```

Save to: `tests/reports/validation-context-{REQUEST_ID}.json`

### Step 8: Invoke Test Validator

Delegate to test-validator subagent. The validator performs syntax validation, dependency checks, quality checks, and edge case coverage verification. Expected output: `tests/reports/validation-report-{REQUEST_ID}.json` with fields: `status`, `validators_checked`, `syntax_errors`, `dependency_errors`, `quality_issues`, `edge_case_coverage`, `summary`.

### Step 9: Process Validation Results

Read the validation report status. If `fail`, present errors and stop. If `pass`, proceed.

**Decision tree**:

```
IF validation.status == "pass":
  → Proceed to Step 10 (Build Execution Context)

ELIF validation.status == "fail":
  → Present errors to user
  → Offer to fix automatically OR exit
  → If fix: Apply fixes → Re-validate (max 3 attempts)
  → If exit: Stop workflow

```

### Step 10: Build Execution Context

Create comprehensive JSON context for executor subagent:

```json
{
  "request_id": "test-YYYYMMDD-HHMMSS",
  "timestamp": "ISO-8601",
  "orchestrator": {
    "command": "test",
    "phase": "execution",
    "requirement": "Execute all validated tests and generate comprehensive report"
  },
  "context": {
    "project_root": "/absolute/path/to/project",
    "test_directory": "/absolute/path/to/project/tests",
    "venv_path": "<HARNESS_ROOT>/venv",
    "validators": [
      {
        "type": "script",
        "path": "tests/scripts/validate-venv-usage.py",
        "edge_case": "EC002",
        "priority": "critical"
      }
    ]
  },
  "parameters": {
    "fail_fast": false,
    "verbose": true,
    "report_path": "tests/reports/execution-report-{REQUEST_ID}.json"
  },
  "validation_report": {
    "status": "pass",
    "validators_checked": 10,
    "all_valid": true
  }
}
```

Save to: `tests/reports/execution-context-{REQUEST_ID}.json`

### Step 11: Create Safety Checkpoint

Before execution, create a safety checkpoint on `refs/checkpoints/<branch>`
(NOT on HEAD — preserves git blame hygiene). The checkpoint-core library
handles the no-changes case (exit 0) internally, so no guard is needed here.

```bash
bash "${CLAUDE_HOME:-$HOME/.claude}/hooks/checkpoint.sh" "Before /test execution"

# Record checkpoint ref in context (refs/checkpoints/<branch>, not HEAD)
CURRENT_BRANCH=$(git branch --show-current)
CHECKPOINT_REF="refs/checkpoints/${CURRENT_BRANCH}"
CHECKPOINT_COMMIT=$(git rev-parse "$CHECKPOINT_REF" 2>/dev/null || echo "none")
echo "✅ Checkpoint ref: ${CHECKPOINT_REF} @ ${CHECKPOINT_COMMIT}"
echo "   Rollback (file-level): git checkout ${CHECKPOINT_REF} -- <path>"
echo "   Rollback (full tree, destructive): git reset --hard ${CHECKPOINT_REF}"

# Record checkpoint in context
jq --arg commit "$CHECKPOINT_COMMIT" \
  '.context.checkpoint_commit = $commit' \
  tests/reports/execution-context-${REQUEST_ID}.json \
  > tests/reports/execution-context-${REQUEST_ID}.json.tmp
mv tests/reports/execution-context-${REQUEST_ID}.json.tmp tests/reports/execution-context-${REQUEST_ID}.json
```

### Step 12: Invoke Test Executor

Delegate to test-executor subagent using Task tool:

```
Use Task tool with:
- subagent_type: "test-executor"
- description: "Execute validated tests"
- prompt: "
  You are the test-executor subagent. Follow agents/test-executor.md instructions precisely.

  Read execution context from: tests/reports/execution-context-${REQUEST_ID}.json

  Your tasks:
  1. Read and validate execution context JSON
  2. Execute all script-based validators (tests/scripts/validate-*.py)
  3. Execute all AI instruction-based validators (tests/instructions/*.md)
  4. Capture results, exit codes, timing for each validator
  5. Aggregate summary statistics (total/passed/failed/errors)
  6. Analyze failed tests and generate recommendations
  7. Write execution report to: tests/reports/execution-report-${REQUEST_ID}.json

  Execution requirements:
  - Activate venv: source "${CLAUDE_HOME:-$HOME/.claude}/venv/bin/activate"
  - Pass --project-root parameter to all script validators
  - Capture stdout (JSON), stderr (errors), exit codes
  - Timeout: 30 seconds per validator
  - Continue execution even if individual tests fail (unless fail_fast=true)
  - Generate comprehensive execution report with all results

  Follow all execution procedures from agents/test-executor.md.
  "
```

Test executor performs script-based and AI instruction-based validation, captures exit codes/timing/JSON output, aggregates summary statistics. Expected output: `tests/reports/execution-report-{REQUEST_ID}.json` with `executor.status`, `executor.results[]`, `executor.summary` (total/passed/failed/errors, pass_rate, edge_cases_prevented, priority_breakdown), and `executor.failed_tests[]`.

### Step 13: Process Execution Results

Read `executor.status`, `executor.summary.total_tests`, `.passed`, `.failed`, and `.errors` from the execution report.

**Decision tree**:

```
IF executor.status == "completed" AND failed == 0 AND errors == 0:
  → All tests passed → Skip to Step 16 (Generate Success Report)

ELIF executor.status == "completed" AND failed > 0:
  → Tests failed → Proceed to Step 14 (Present Failures)

ELIF executor.status == "partial":
  → Some tests couldn't run → Proceed to Step 14 (Present Failures)

ELIF executor.status == "blocked":
  → Execution blocked → Present error → Exit
```

### Step 14: Present Test Failures to User

Format and display failures:

```markdown
# Test Execution Report

**Project**: <project_name>
**Tests Run**: <total_tests>
**Status**: <passed>/<total> passed (<pass_rate>%)

## ❌ Failed Tests (<failed> tests)

### Critical Priority (<count> failures)

#### EC002: Venv Usage Violations
**Validator**: validate-venv-usage.py
**Violations**: 3 files
**Affected Files**:
- settings.json:42
- commands/clean.md:36
- commands/dev.md:23

**Recommendation**: Use `source "${CLAUDE_HOME:-$HOME/.claude}/venv/bin/activate" && python3` pattern for all Python invocations

**Fix Command**:
Manual fix: edit each affected file and update venv usage to match the project's activation pattern.

---

### High Priority (<count> failures)

#### EC001: CLAUDE.md Protection
**Validator**: claude-md-protection
**Violations**: 1 file
**Affected Files**:
- agents/cleanliness-inspector.md:1050

**Recommendation**: Add CLAUDE.md to official file allow-list

---

## ✅ Passed Tests (<passed> tests)

- validate-step-numbering (EC004) - No decimal steps found
- validate-chinese-content (EC006) - No Chinese in functional code
- validate-file-naming (EC007) - All files use kebab-case
- validate-debug-file-age (EC008) - No old debug files
- validate-optionality-language (EC005) - No ambiguous optionality

---

## 📊 Summary

- **Total Tests**: <total>
- **Pass Rate**: <pass_rate>%
- **Edge Cases Prevented**: <covered> / 8
- **Execution Time**: <duration> seconds

## 🎯 Next Steps

1. Review failed tests above
2. Apply recommended fixes
3. Re-run tests: `/test`
4. When all pass, proceed with confidence

## 📁 Detailed Reports

- Validation: tests/reports/validation-report-{REQUEST_ID}.json
- Execution: tests/reports/execution-report-{REQUEST_ID}.json
- Registry: tests/reports/validator-registry-{REQUEST_ID}.json
```

### Step 15: Collect User Decision

Based on failures, offer options:

```markdown
## Test Execution Options

**Current Status**: {failed} tests failed

1. **Fix failures manually** - Review recommendations and update files
2. **Apply automated fixes** (if available) - Run fix scripts
3. **View detailed report** - Inspect JSON reports for full context
4. **Ignore failures** - Generate report and exit (NOT recommended)
5. **Cancel** - Exit without report

Select option [1-5]:
```

**Option 1: Fix manually**
- User makes changes
- Offer to re-run tests
- If re-run → Return to Step 10 (Execution)

**Option 2: Apply automated fixes**
- Check if fix scripts exist for failed validators
- Run fix scripts with user approval
- Re-run tests automatically
- If still fail → Show remaining failures

**Option 3: View detailed report**
- Display JSON report paths
- User inspects manually
- Return to option selection

**Option 4: Ignore failures**
- Proceed to Step 16 with failures noted
- NOT recommended for critical failures

**Option 5: Cancel**
- Exit workflow
- Preserve reports for manual review

### Step 16: Generate Completion Report

Create `tests/reports/completion-{REQUEST_ID}.md` summarizing: request ID, project path, timestamp, overall status; validation phase results (validators checked, syntax/dependency/quality issues); execution phase results (total/passed/failed/errors, pass rate, execution time); edge case prevention summary; per-failed-test details with recommendations; git checkpoint hash and rollback command; and paths to all related report files.

---

## Test Folder Initialization

If project has no `tests/` directory, initialize it: create subdirectories `{scripts,instructions,data/fixtures,data/mocks,reports}`, copy template README.md and INDEX.md from `<HARNESS_ROOT>/tests/`, and copy instruction templates from `<HARNESS_ROOT>/tests/instructions/`. Implement validators per `docs/test/edge-case-analysis.json`.

## Scripts

- `<HARNESS_ROOT>/scripts/todo/test.py` — Workflow checklist
- `<HARNESS_ROOT>/scripts/analyze-git-edge-cases.sh` — Git history edge case analyzer
- `<HARNESS_ROOT>/scripts/cleanup-tests-folder.sh` — Remove non-git validators
- `<HARNESS_ROOT>/scripts/migrate-test-to-tests.sh` — Migrate test/ to tests/
