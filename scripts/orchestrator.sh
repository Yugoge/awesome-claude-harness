#!/usr/bin/env bash
# Description: Agent orchestration coordinator for the /clean workflow
# Usage: orchestrator.sh <mode> <context-json-file> [args]
# Modes: clean-inspect, clean-merge-reports, record-checkpoint, rule-inspect (commands/clean.md)
# Exit codes: 0=success, 1=failure

set -euo pipefail

MODE="${1:?Missing mode (clean-inspect|clean-merge-reports|record-checkpoint|rule-inspect)}"
CONTEXT_FILE="${2:?Missing context JSON file}"

if [[ ! -f "$CONTEXT_FILE" ]]; then
  echo "Error: Context file not found: $CONTEXT_FILE" >&2
  exit 1
fi

if ! jq empty "$CONTEXT_FILE" 2>/dev/null; then
  echo "Error: Invalid JSON in context file: $CONTEXT_FILE" >&2
  exit 1
fi

# The printed output paths are in the session's own temp directory (hooks/session-scratch-init.sh), not system temp.
SESSION_TMP="${TMPDIR:-/var/tmp/claude-scratch}/${CLAUDE_CODE_SESSION_ID:-${CLAUDE_SESSION_ID:-unknown}}"

# Where one /clean request's files live (commands/clean.md: docs/clean/).
clean_output_dir() {
  echo "${ORCHESTRATOR_CLEAN_OUTPUT_DIR:-$(jq -r '.orchestrator.analysis.clean_output_dir // "docs/clean"' "$CONTEXT_FILE")}"
}

# Mode: clean-inspect
# Coordinates cleanliness-inspector and style-inspector execution
clean_inspect() {
  echo "=== Clean Inspection Orchestration ===" >&2
  echo "Context: $CONTEXT_FILE" >&2

  PROJECT_ROOT=$(jq -r '.orchestrator.analysis.project_root // "."' "$CONTEXT_FILE")
  echo "Project: $PROJECT_ROOT" >&2

  # Extract request ID for rule-context verification
  REQUEST_ID=$(jq -r '.request_id // ""' "$CONTEXT_FILE")
  CLEAN_OUTPUT_DIR=$(clean_output_dir)
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

  if ! jq -e '.orchestrator.requirement' "$CONTEXT_FILE" >/dev/null 2>&1; then
    echo "Error: Missing requirement in context" >&2
    exit 1
  fi

  # Signal ready for inspector subagents
  echo "Cleanliness inspector can now read context from: $CONTEXT_FILE" >&2
  echo "Style inspector can now read context from: $CONTEXT_FILE" >&2

  # Output paths for caller
  CLEANLINESS_OUTPUT="$SESSION_TMP/cleanliness-output-$(date +%s).json"
  STYLE_OUTPUT="$SESSION_TMP/style-output-$(date +%s).json"

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
# Merges the cleanliness, style, and prompt inspection reports of the request the /clean
# context names into the combined report /clean's later steps and the cleaner read.
clean_merge_reports() {
  echo "=== Clean Merge Reports Orchestration ===" >&2
  echo "Context: $CONTEXT_FILE" >&2

  REQUEST_ID=$(jq -r '.request_id // ""' "$CONTEXT_FILE")
  CLEAN_OUTPUT_DIR=$(clean_output_dir)
  CLEANLINESS_REPORT="${CLEAN_OUTPUT_DIR}/cleanliness-report-${REQUEST_ID}.json"
  STYLE_REPORT="${CLEAN_OUTPUT_DIR}/style-report-${REQUEST_ID}.json"
  PROMPT_REPORT="${CLEAN_OUTPUT_DIR}/prompt-report-${REQUEST_ID}.json"

  # The main agent writes the style report itself (/clean Step 9) and runs this merge,
  # so the merge checks it. The cleanliness and prompt reports are each checked at their
  # inspector's own stop (G2, the report its dispatch's obligation declares), so the
  # merge takes them as they are and decides nothing on them.
  if ! jq empty "$STYLE_REPORT" 2>/dev/null; then
    echo "Error: Missing or invalid report: $STYLE_REPORT" >&2
    exit 1
  fi
  # An inspector's report as it is: its first JSON value, or null where it holds none.
  inspector_report() { jq -c -n 'try input catch null' "$1" 2>/dev/null; }

  # Merge reports
  COMBINED_OUTPUT="${CLEAN_OUTPUT_DIR}/combined-report-${REQUEST_ID}.json"

  jq -n \
    --arg request_id "$REQUEST_ID" \
    --argjson c "$(inspector_report "$CLEANLINESS_REPORT")" \
    --slurpfile style "$STYLE_REPORT" \
    --argjson p "$(inspector_report "$PROMPT_REPORT")" \
    '$style[0] as $s | {
      request_id: $request_id,
      timestamp: (now | strftime("%Y-%m-%dT%H:%M:%SZ")),
      cleanliness_report: $c,
      style_report: $s,
      prompt_report: $p,
      combined_summary: {
        total_issues: (
          ($c.summary.total_issues // 0) +
          ($s.summary.violations_found // 0) +
          ($p.findings // [] | length)
        ),
        critical: (
          ($c.summary.critical // 0) +
          ($s.summary.critical // 0) +
          ($p.summary.critical // 0)
        ),
        major: (
          ($c.summary.major // 0) +
          ($s.summary.major // 0) +
          ($p.summary.major // 0)
        ),
        minor: (
          ($c.summary.minor // 0) +
          ($s.summary.minor // 0) +
          ($p.summary.minor // 0)
        )
      }
    }' > "$COMBINED_OUTPUT"

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

# Mode: record-checkpoint
# Prints the git checkpoint record the cleaner's context carries (commands/clean.md Step 16
# merges it into context-with-approvals); it rewrites no file, the context it reads included.
record_checkpoint() {
  echo "=== Record Checkpoint Orchestration ===" >&2
  echo "Context: $CONTEXT_FILE" >&2

  CHECKPOINT_COMMIT="${3:-}"
  if [[ -z "$CHECKPOINT_COMMIT" ]]; then
    echo "Error: Missing checkpoint commit hash" >&2
    exit 1
  fi

  echo "Checkpoint recorded: $CHECKPOINT_COMMIT" >&2

  jq -n \
    --arg commit "$CHECKPOINT_COMMIT" \
    '{
      status: "recorded",
      safety_checkpoint_created: true,
      checkpoint_commit: $commit
    }'

  return 0
}

# Mode: rule-inspect
# Coordinates rule-inspector subagent execution
rule_inspect() {
  echo "=== Rule Inspection Orchestration ===" >&2
  echo "Context: $CONTEXT_FILE" >&2

  PROJECT_ROOT=$(jq -r '.orchestrator.analysis.project_root // "."' "$CONTEXT_FILE")
  echo "Project: $PROJECT_ROOT" >&2

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

  RULE_OUTPUT="$SESSION_TMP/rule-output-$(date +%s).json"

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

case "$MODE" in
  clean-inspect)
    clean_inspect
    ;;
  clean-merge-reports)
    clean_merge_reports
    ;;
  record-checkpoint)
    record_checkpoint "$@"
    ;;
  rule-inspect)
    rule_inspect
    ;;
  *)
    echo "Error: Invalid mode: $MODE" >&2
    echo "Valid modes: clean-inspect, clean-merge-reports, record-checkpoint, rule-inspect" >&2
    exit 1
    ;;
esac

exit 0
