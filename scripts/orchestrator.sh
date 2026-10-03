#!/usr/bin/env bash
# Description: Agent orchestration coordinator for development and cleanup workflows
# Usage: orchestrator.sh <mode> <context-json-file> [args]
# Modes: dev-workflow, qa-verify, iterate, clean-inspect, clean-execute, clean-merge-reports, record-checkpoint
# Exit codes: 0=success, 1=failure, 2=iteration needed

set -euo pipefail

MODE="${1:?Missing mode (dev-workflow|qa-verify|iterate|clean-inspect|clean-execute|clean-merge-reports|record-checkpoint|rule-inspect)}"
CONTEXT_FILE="${2:?Missing context JSON file}"

# Validate context file exists
if [[ ! -f "$CONTEXT_FILE" ]]; then
  echo "Error: Context file not found: $CONTEXT_FILE" >&2
  exit 1
fi

# Validate JSON syntax
if ! jq empty "$CONTEXT_FILE" 2>/dev/null; then
  echo "Error: Invalid JSON in context file: $CONTEXT_FILE" >&2
  exit 1
fi

# Temporary files for agent communication
DEV_OUTPUT="/tmp/dev-output-$(date +%s).json"
QA_OUTPUT="/tmp/qa-output-$(date +%s).json"
ITERATION_CONTEXT="/tmp/iteration-context-$(date +%s).json"

cleanup() {
  rm -f "$DEV_OUTPUT" "$QA_OUTPUT" "$ITERATION_CONTEXT" 2>/dev/null || true
}
trap cleanup EXIT

# Mode: dev-workflow
# Coordinates dev subagent execution
dev_workflow() {
  echo "=== Dev Workflow Orchestration ===" >&2
  echo "Context: $CONTEXT_FILE" >&2

  # Extract requirement for logging
  REQUIREMENT=$(jq -r '.orchestrator.requirement // "unknown"' "$CONTEXT_FILE")
  echo "Requirement: $REQUIREMENT" >&2

  # Validate required fields in context
  if ! jq -e '.orchestrator.analysis.root_cause' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: Missing root_cause in context" >&2
    exit 1
  fi

  if ! jq -e '.orchestrator.analysis.success_criteria' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: Missing success_criteria in context" >&2
    exit 1
  fi

  # Signal ready for dev subagent
  echo "Dev subagent can now read context from: $CONTEXT_FILE" >&2
  echo "Dev subagent should write output to: $DEV_OUTPUT" >&2

  # Output paths for caller to use
  jq -n \
    --arg context "$CONTEXT_FILE" \
    --arg output "$DEV_OUTPUT" \
    '{
      status: "ready",
      context_file: $context,
      expected_output: $output,
      next_step: "invoke dev subagent with context"
    }'

  return 0
}

# Mode: qa-verify
# Coordinates QA subagent verification
qa_verify() {
  echo "=== QA Verification Orchestration ===" >&2
  echo "Context: $CONTEXT_FILE" >&2

  # Validate dev output exists in context
  if ! jq -e '.dev' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: Missing dev output in context for QA verification" >&2
    exit 1
  fi

  # Validate success criteria present
  if ! jq -e '.orchestrator.analysis.success_criteria' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: Missing success_criteria for QA verification" >&2
    exit 1
  fi

  # Signal ready for QA subagent
  echo "QA subagent can now read context from: $CONTEXT_FILE" >&2
  echo "QA subagent should write output to: $QA_OUTPUT" >&2

  # Output paths for caller to use
  jq -n \
    --arg context "$CONTEXT_FILE" \
    --arg output "$QA_OUTPUT" \
    '{
      status: "ready",
      context_file: $context,
      expected_output: $output,
      next_step: "invoke qa subagent with context"
    }'

  return 0
}

# Mode: iterate
# Prepares context for next iteration based on QA feedback
iterate() {
  echo "=== Iteration Orchestration ===" >&2
  echo "Context: $CONTEXT_FILE" >&2

  # Validate QA output exists in context
  if ! jq -e '.qa' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: Missing QA output in context for iteration" >&2
    exit 1
  fi

  # Check if iteration actually needed
  ITERATION_NEEDED=$(jq -r '.qa.iteration_needed // false' "$CONTEXT_FILE")
  if [[ "$ITERATION_NEEDED" != "true" ]]; then
    echo "No iteration needed (QA passed or no iteration flag)" >&2
    jq -n '{status: "complete", iteration_needed: false}'
    return 0
  fi

  # Extract refined context from QA output
  if ! jq -e '.qa.refined_context' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: QA requested iteration but no refined_context provided" >&2
    exit 1
  fi

  # Get current iteration number
  CURRENT_ITERATION=$(jq -r '.orchestrator.iteration // 1' "$CONTEXT_FILE")
  NEXT_ITERATION=$((CURRENT_ITERATION + 1))

  # Max iterations safety check (override via env var or context file)
  MAX_ITERATIONS="${ORCHESTRATOR_MAX_ITERATIONS:-$(jq -r '.orchestrator.max_iterations // 5' "$CONTEXT_FILE")}"
  if [[ $NEXT_ITERATION -gt $MAX_ITERATIONS ]]; then
    echo "Error: Maximum iterations ($MAX_ITERATIONS) exceeded" >&2
    jq -n \
      --arg reason "max iterations exceeded" \
      --argjson max "$MAX_ITERATIONS" \
      '{status: "failed", reason: $reason, max_iterations: $max}'
    exit 1
  fi

  # Build new context for next iteration
  jq \
    --argjson iteration "$NEXT_ITERATION" \
    '
    .orchestrator.iteration = $iteration |
    .orchestrator.analysis.additional_context = .qa.refined_context.additional_context |
    .orchestrator.analysis.failed_criteria = .qa.refined_context.failed_criteria |
    .orchestrator.analysis.recommended_approach = .qa.refined_context.recommended_approach |
    .previous_attempts = [
      (.previous_attempts // []),
      {
        iteration: ($iteration - 1),
        dev: .dev,
        qa: .qa,
        timestamp: (now | strftime("%Y-%m-%dT%H:%M:%SZ"))
      }
    ] | flatten
    ' "$CONTEXT_FILE" > "$ITERATION_CONTEXT"

  echo "Iteration context prepared: $ITERATION_CONTEXT" >&2

  jq -n \
    --arg context "$ITERATION_CONTEXT" \
    --argjson iteration "$NEXT_ITERATION" \
    '{
      status: "iteration_ready",
      iteration: $iteration,
      context_file: $context,
      next_step: "invoke dev subagent with refined context"
    }'

  return 0
}

# Mode: clean-inspect
# Coordinates cleanliness-inspector and style-inspector execution
clean_inspect() {
  echo "=== Clean Inspection Orchestration ===" >&2
  echo "Context: $CONTEXT_FILE" >&2

  # Extract project root
  PROJECT_ROOT=$(jq -r '.orchestrator.analysis.project_root // "."' "$CONTEXT_FILE")
  echo "Project: $PROJECT_ROOT" >&2

  # Extract request ID for rule-context verification
  REQUEST_ID=$(jq -r '.request_id // ""' "$CONTEXT_FILE")
  CLEAN_OUTPUT_DIR="${ORCHESTRATOR_CLEAN_OUTPUT_DIR:-$(jq -r '.orchestrator.analysis.clean_output_dir // "docs/clean"' "$CONTEXT_FILE")}"
  RULE_CONTEXT_FILE="${CLEAN_OUTPUT_DIR}/rule-context-${REQUEST_ID}.json"

  # CRITICAL PREREQUISITE CHECK: Verify rule-inspector was executed
  # Step 4 (rule-inspector completion) MUST complete before clean-inspect
  echo "Checking prerequisite: rule-inspector completion..." >&2

  # Check if key folders need documentation
  IFS=',' read -ra KEY_FOLDERS <<< "${ORCHESTRATOR_KEY_FOLDERS:-agents,scripts,docs,hooks,commands}"
  NEEDS_RULES=false

  for folder in "${KEY_FOLDERS[@]}"; do
    if [[ ! -f "$PROJECT_ROOT/$folder/INDEX.md" ]] || [[ ! -f "$PROJECT_ROOT/$folder/README.md" ]]; then
      NEEDS_RULES=true
      echo "⚠️  Missing documentation in $folder/" >&2
      break
    fi
  done

  # If rules are needed but rule-context doesn't exist, BLOCK execution
  if [[ "$NEEDS_RULES" == "true" ]] && [[ ! -f "$RULE_CONTEXT_FILE" ]]; then
    echo "❌ ERROR: Rule initialization required but not completed!" >&2
    echo "   Step 4 (rule-inspector) MUST execute before Step 5 (clean-inspect)" >&2
    echo "   Missing: $RULE_CONTEXT_FILE" >&2
    echo "" >&2
    echo "   Action required: Execute Step 4 first:" >&2
    echo "   ~/.claude/scripts/orchestrator.sh rule-inspect <rule-context-json>" >&2
    exit 1
  fi

  if [[ "$NEEDS_RULES" == "false" ]]; then
    echo "✅ Rule initialization not needed (all folders documented)" >&2
  else
    echo "✅ Rule initialization completed: $RULE_CONTEXT_FILE" >&2
  fi

  # Validate required fields
  if ! jq -e '.orchestrator.requirement' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: Missing requirement in context" >&2
    exit 1
  fi

  # Signal ready for inspector subagents
  echo "Cleanliness inspector can now read context from: $CONTEXT_FILE" >&2
  echo "Style inspector can now read context from: $CONTEXT_FILE" >&2

  # Output paths for caller
  CLEANLINESS_OUTPUT="/tmp/cleanliness-output-$(date +%s).json"
  STYLE_OUTPUT="/tmp/style-output-$(date +%s).json"

  jq -n \
    --arg context "$CONTEXT_FILE" \
    --arg cleanliness_out "$CLEANLINESS_OUTPUT" \
    --arg style_out "$STYLE_OUTPUT" \
    '{
      status: "ready",
      context_file: $context,
      cleanliness_output: $cleanliness_out,
      style_output: $style_out,
      next_step: "invoke cleanliness-inspector and style-inspector in parallel"
    }'

  return 0
}

# Mode: clean-merge-reports
# Merges cleanliness, style, and prompt inspection reports
clean_merge_reports() {
  echo "=== Clean Merge Reports Orchestration ===" >&2
  echo "Context: $CONTEXT_FILE" >&2

  # Validate all three reports exist in context -- prompt-inspector is
  # MANDATORY on every /clean run (commands/clean.md Step 10A), so its
  # report is required here on the same footing as the other two, not an
  # optional post-merge patch the orchestrator might forget to apply.
  if ! jq -e '.cleanliness_report' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: Missing cleanliness_report in context" >&2
    exit 1
  fi

  if ! jq -e '.style_report' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: Missing style_report in context" >&2
    exit 1
  fi

  if ! jq -e '.prompt_report' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: Missing prompt_report in context" >&2
    exit 1
  fi

  # Merge reports
  COMBINED_OUTPUT="/tmp/combined-report-$(date +%s).json"

  jq \
    '{
      request_id: .request_id,
      timestamp: (now | strftime("%Y-%m-%dT%H:%M:%SZ")),
      cleanliness_report: .cleanliness_report,
      style_report: .style_report,
      prompt_report: .prompt_report,
      combined_summary: {
        total_issues: (
          (.cleanliness_report.summary.total_issues // 0) +
          (.style_report.summary.violations_found // 0) +
          (.prompt_report.findings // [] | length)
        ),
        critical: (
          (.cleanliness_report.summary.critical // 0) +
          (.style_report.summary.critical // 0) +
          (.prompt_report.summary.critical // 0)
        ),
        major: (
          (.cleanliness_report.summary.major // 0) +
          (.style_report.summary.major // 0) +
          (.prompt_report.summary.major // 0)
        ),
        minor: (
          (.cleanliness_report.summary.minor // 0) +
          (.style_report.summary.minor // 0) +
          (.prompt_report.summary.minor // 0)
        )
      }
    }' "$CONTEXT_FILE" > "$COMBINED_OUTPUT"

  echo "Combined report: $COMBINED_OUTPUT" >&2

  jq -n \
    --arg output "$COMBINED_OUTPUT" \
    '{
      status: "merged",
      combined_report: $output,
      next_step: "present to user for approval"
    }'

  return 0
}

# Mode: clean-execute
# Coordinates cleaner subagent execution
clean_execute() {
  echo "=== Clean Execution Orchestration ===" >&2
  echo "Context: $CONTEXT_FILE" >&2

  # Validate required fields
  if ! jq -e '.user_approvals' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: Missing user_approvals in context" >&2
    exit 1
  fi

  if ! jq -e '.orchestrator.analysis.safety_checkpoint_created' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Warning: Safety checkpoint not confirmed in context" >&2
  fi

  # Signal ready for cleaner subagent
  echo "Cleaner can now read context from: $CONTEXT_FILE" >&2

  CLEANER_OUTPUT="/tmp/cleaner-output-$(date +%s).json"

  jq -n \
    --arg context "$CONTEXT_FILE" \
    --arg output "$CLEANER_OUTPUT" \
    '{
      status: "ready",
      context_file: $context,
      expected_output: $output,
      next_step: "invoke cleaner subagent with approvals"
    }'

  return 0
}

# Mode: record-checkpoint
# Records git checkpoint commit hash in context file
record_checkpoint() {
  echo "=== Record Checkpoint Orchestration ===" >&2
  echo "Context: $CONTEXT_FILE" >&2

  # Get checkpoint commit hash (3rd argument)
  CHECKPOINT_COMMIT="${3:-}"
  if [[ -z "$CHECKPOINT_COMMIT" ]]; then
    echo "Error: Missing checkpoint commit hash" >&2
    exit 1
  fi

  # Update context file with checkpoint information
  TMP_FILE="/tmp/context-checkpoint-$(date +%s).json"
  jq \
    --arg commit "$CHECKPOINT_COMMIT" \
    '.orchestrator.analysis.safety_checkpoint_created = true |
     .orchestrator.analysis.checkpoint_commit = $commit' \
    "$CONTEXT_FILE" > "$TMP_FILE"

  # Replace original context file
  mv "$TMP_FILE" "$CONTEXT_FILE"

  echo "Checkpoint recorded: $CHECKPOINT_COMMIT" >&2

  jq -n \
    --arg commit "$CHECKPOINT_COMMIT" \
    --arg context "$CONTEXT_FILE" \
    '{
      status: "recorded",
      checkpoint_commit: $commit,
      updated_context: $context
    }'

  return 0
}

# Mode: rule-inspect
# Coordinates rule-inspector subagent execution
rule_inspect() {
  echo "=== Rule Inspection Orchestration ===" >&2
  echo "Context: $CONTEXT_FILE" >&2

  # Extract project root
  PROJECT_ROOT=$(jq -r '.orchestrator.analysis.project_root // "."' "$CONTEXT_FILE")
  echo "Project: $PROJECT_ROOT" >&2

  # Validate required fields
  if ! jq -e '.orchestrator.requirement' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: Missing requirement in context" >&2
    exit 1
  fi

  if ! jq -e '.full_context.discovered_folders' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: Missing discovered_folders in context" >&2
    exit 1
  fi

  # Signal ready for rule-inspector subagent
  echo "Rule inspector can now read context from: $CONTEXT_FILE" >&2

  RULE_OUTPUT="/tmp/rule-output-$(date +%s).json"

  jq -n \
    --arg context "$CONTEXT_FILE" \
    --arg output "$RULE_OUTPUT" \
    '{
      status: "ready",
      context_file: $context,
      expected_output: $output,
      next_step: "invoke rule-inspector subagent with context"
    }'

  return 0
}

# Main execution
case "$MODE" in
  dev-workflow)
    dev_workflow
    ;;
  qa-verify)
    qa_verify
    ;;
  iterate)
    iterate
    ;;
  clean-inspect)
    clean_inspect
    ;;
  clean-merge-reports)
    clean_merge_reports
    ;;
  clean-execute)
    clean_execute
    ;;
  record-checkpoint)
    record_checkpoint "$@"
    ;;
  rule-inspect)
    rule_inspect
    ;;
  *)
    echo "Error: Invalid mode: $MODE" >&2
    echo "Valid modes: dev-workflow, qa-verify, iterate, clean-inspect, clean-merge-reports, clean-execute, record-checkpoint, rule-inspect" >&2
    exit 1
    ;;
esac

exit 0
