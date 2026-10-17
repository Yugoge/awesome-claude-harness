#!/usr/bin/env bash
# Description: One-time idempotent migration — import current agent scores from agent-scores.json
#              into logs/lifecycle.jsonl as score_baseline_import entries.
# Usage: lifecycle-baseline-import.sh [--lifecycle-file <path>] [--scores-file <path>]
# Exit codes: 0=success, 1=argument error, 2=IO error
#
# Idempotency: skips any canonical agent that already has any entry (any event type)
# in lifecycle.jsonl — determined by scanning for matching "agent" field.
# All 21 canonical agents are processed under a single exclusive flock acquisition.
# Root cause ref: arch-7 phase 2 (task 20260525-050824)

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
LIFECYCLE_FILE_DEFAULT="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}/logs/lifecycle.jsonl"
SCORES_FILE_DEFAULT="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}/agent-scores.json"

usage() {
  cat >&2 <<EOF
Usage: ${SCRIPT_NAME} [--lifecycle-file <path>] [--scores-file <path>]

Reads current agent scores from agent-scores.json and appends a score_baseline_import
entry for each canonical agent not yet present in lifecycle.jsonl.
Safe to run multiple times (idempotent).
EOF
  exit 1
}

LIFECYCLE_FILE="${LIFECYCLE_FILE_DEFAULT}"
SCORES_FILE="${SCORES_FILE_DEFAULT}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lifecycle-file) LIFECYCLE_FILE="${2:?missing value for --lifecycle-file}"; shift 2 ;;
    --scores-file)    SCORES_FILE="${2:?missing value for --scores-file}"; shift 2 ;;
    -h|--help)        usage ;;
    *)                echo "Unknown argument: $1" >&2; usage ;;
  esac
done

# Ensure lifecycle directory exists and touch the file if missing
LIFECYCLE_DIR="$(dirname "${LIFECYCLE_FILE}")"
mkdir -p "${LIFECYCLE_DIR}"
if [[ ! -f "${LIFECYCLE_FILE}" ]]; then
  touch "${LIFECYCLE_FILE}"
fi

LOCK_FILE="${LIFECYCLE_FILE}.lock"
LOCK_TIMEOUT="${LOCK_TIMEOUT:-10}"

# Acquire exclusive lock; auto-release on FD close
exec 9>"${LOCK_FILE}"
if ! flock -w "${LOCK_TIMEOUT}" 9; then
  echo "${SCRIPT_NAME}: failed to acquire lock on ${LOCK_FILE} within ${LOCK_TIMEOUT}s" >&2
  exit 2
fi

# Delegate migration logic to Python; all 21 agents processed under single flock.
( source "$(dirname "${BASH_SOURCE[0]}")/../venv/bin/activate" && python3 - \
    "${LIFECYCLE_FILE}" "${SCORES_FILE}" <<'PYEOF'
import json
import os
import sys
import datetime

lifecycle_file, scores_file = sys.argv[1:3]

CANONICAL_AGENTS = [
    "ba", "dev", "qa",
    "ui-specialist", "architect", "product-owner", "user", "pm",
    "changelog-analyst", "push-analyst", "merge-analyst", "pull-analyst",
    "cleanliness-inspector", "style-inspector", "prompt-inspector",
    "rule-inspector", "git-edge-case-analyst", "cleaner",
    "test-validator", "test-executor", "spec",
]

# Read current scores from agent-scores.json (migration input only)
current_scores = {}
if os.path.isfile(scores_file):
    try:
        with open(scores_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        agents_data = data.get("global", {}).get("agents", {})
        for ag, info in agents_data.items():
            current_scores[ag] = int(info.get("score", 50))
    except Exception as e:
        sys.stderr.write(f"lifecycle-baseline-import.sh: warning — could not read {scores_file}: {e}\n")

# Scan lifecycle.jsonl to find agents already present (any event type)
agents_already_imported = set()
try:
    with open(lifecycle_file, "r", encoding="utf-8") as f:
        for i, raw_line in enumerate(f):
            stripped = raw_line.rstrip("\n")
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
                ag = entry.get("agent")
                if ag:
                    agents_already_imported.add(ag)
            except json.JSONDecodeError:
                # Skip unparseable lines during baseline scan
                pass
except OSError as e:
    sys.stderr.write(f"lifecycle-baseline-import.sh: cannot read {lifecycle_file}: {e}\n")
    sys.exit(2)

# Append baseline entries for agents not yet in lifecycle.jsonl
ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
appended = 0
try:
    with open(lifecycle_file, "a", encoding="utf-8") as f:
        for agent in CANONICAL_AGENTS:
            if agent in agents_already_imported:
                continue
            score = current_scores.get(agent, 50)
            entry_obj = {
                "ts": ts,
                "agent": agent,
                "event": "score_baseline_import",
                "prev_score": score,
                "new_score": score,
                "delta": 0,
                "unclamped_score": score,
                "actor": "migration",
                "reason": "baseline import from agent-scores.json",
            }
            f.write(json.dumps(entry_obj, ensure_ascii=False) + "\n")
            appended += 1
        f.flush()
        os.fsync(f.fileno())
except OSError as e:
    sys.stderr.write(f"lifecycle-baseline-import.sh: failed to append to {lifecycle_file}: {e}\n")
    sys.exit(2)

print(f"lifecycle-baseline-import: appended {appended} baseline entries ({len(agents_already_imported)} agents already present)")
PYEOF
)
python_exit=$?
if [[ $python_exit -ne 0 ]]; then
  exit $python_exit
fi

# Lock auto-releases on shell exit
exit 0
