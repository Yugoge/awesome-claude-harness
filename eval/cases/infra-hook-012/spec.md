# Infra-Hook Eval Case infra-hook-012: subagentstop-validate-artifacts.py

## Trigger
SubagentStop hook (no matcher). Hook fires when a subagent invocation
completes, before the orchestrator receives the result.

## Behavior Required
- Reads SubagentStop hook input JSON on stdin and parses the subagent
  type from `agent_type`.
- Locates the expected terminal artifact path declared in the
  subagent's cp-state file at
  `~/.claude/specs/<spec>/cp-state-<agent>.json`.
- Verifies the artifact file exists, is non-empty, and parses as JSON
  if its extension is `.json`.
- Validates the artifact against the schema referenced by the agent
  type (e.g., `dev-report.v1.json` for dev).
- Emits structured stderr listing missing required fields when the
  schema check fails.

## Exit Code Contract
- exit 0: artifact present, valid JSON, schema-compliant.
- exit 2: artifact missing OR invalid JSON OR schema-violation.

## Acceptance
- AC-1: missing artifact path yields exit 2 with stderr containing the
  expected path.
- AC-2: artifact missing required field `task_id` yields exit 2 with
  stderr listing the field.
- AC-3: fully-compliant artifact yields exit 0 with empty stderr.
