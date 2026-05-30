#!/usr/bin/env bash
# Description: Update agent score by appending an entry to the lifecycle JSONL log.
# Usage: score-update.sh --agent <name> --event <event_name> [--note <text>] [--lifecycle-file <path>] [--expected-prev-score <int>]
#        score-update.sh --agent <name> --delta <int> --reason <text> [--lifecycle-file <path>] [--expected-prev-score <int>]
#        score-update.sh --agent <name> --undo <ts> --reason <text> [--lifecycle-file <path>]
# Exit codes:
#   0 = success (score entry appended to lifecycle.jsonl)
#   1 = invalid argument or unknown agent/event (no modification made)
#   2 = file/IO error or malformed JSONL in existing log
#   3 = CAS conflict (--expected-prev-score supplied but does not match latest score)
#   4 = --undo target not found OR ambiguous (no modification made)
#   5 = close_success_* precondition unmet (close-report missing/NO/FORCED, or --note invalid)
#
# Root cause addressed (M1/M1b/M2 — task 20260529-210616): orchestrator
#   attempted to reverse a premature close_success_qa_fail_fixed score in
#   task 20260529-081014 via --delta -N and --undo, both rejected as
#   "Unknown argument" because no reversal interface existed. M1/M1b add
#   --delta+--reason and --undo+--reason as append-only reversal modes that
#   net to inverse of a prior entry, never mutating existing JSONL lines.
#   manual_reversal is an INTERNAL event label only — caller-supplied
#   --event manual_reversal is ALWAYS rejected (codex iter-2 C3/C4).
#
# Root cause addressed (M3 — task 20260529-210616): same task 20260529-081014
#   orchestrator issued close_success_qa_fail_fixed scoring BEFORE QA finalized
#   verdict. M3 adds a script-side precondition: close_success_* events require
#   --note matching ^[A-Za-z0-9][A-Za-z0-9_-]{2,80}$ (no / \ . traversal),
#   docs/dev/close-report-<note>.md must exist, last non-empty line must
#   classify as 'yes' per hooks/lib/close-verdict.py, and NOT contain FORCED.
#   Decision logic delegated to scripts/close-scoring-decide.py.
#
# Root cause addressed: arch-7 phase 2 (task 20260525-050824) — replace
# independent-flock overwrite model with append-only JSONL under single
# exclusive flock to prevent score drift between sequential close-cycle calls.

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIFECYCLE_FILE_DEFAULT="${HOME}/.claude/logs/lifecycle.jsonl"

usage() {
  cat >&2 <<EOF
Usage: ${SCRIPT_NAME} --agent <name> --event <event_name> [--note <text>] [--lifecycle-file <path>] [--expected-prev-score <int>]
       ${SCRIPT_NAME} --agent <name> --delta <int> --reason <text> [--lifecycle-file <path>] [--expected-prev-score <int>]
       ${SCRIPT_NAME} --agent <name> --undo <ts> --reason <text> [--lifecycle-file <path>]

Canonical events (caller-available):
  close_success_qa_pass, close_success_qa_fail_fixed,
  close_fail_qa_pass, close_fail_qa_fail,
  qa_first_pass, qa_reject_dev, qa_reject_ba, qa_second_pass,
  user_rating_5, user_rating_4, user_rating_3, user_rating_2, user_rating_1

Internal events (NEVER caller-supplied — rejected with exit 1):
  manual_reversal — only emitted by --delta / --undo modes

Reversal modes (M1/M2 — task 20260529-210616):
  --delta <int> --reason <text>
      Append a compensating entry with arbitrary integer delta and the
      internal event 'manual_reversal'. Mutually exclusive with --event
      and --undo. Empty --reason rejected with exit 1.

  --undo <ts> --reason <text>
      Find the prior entry matching (--agent, ts) and append the inverse
      (delta = -target.delta) with event 'manual_reversal'. Exit 4 if
      not found or ambiguous. Mutually exclusive with --event and --delta.

close_success_* precondition (M3 — both qa_pass and qa_fail_fixed):
  --note REQUIRED matching ^[A-Za-z0-9][A-Za-z0-9_-]{2,80}\$ (no /, \\, ., ..).
  <repo>/docs/dev/close-report-<note>.md MUST exist.
  Last non-empty line MUST classify as 'yes' (excludes FORCED).
  Decision delegated to scripts/close-scoring-decide.py.

Score has no lower bound (negative scores accumulate), upper bound 100.
Rank is recomputed from final score:
  <0 = rank-0 (Disgraced), 0-20 = rank-1 (Apprentice), 21-40 = rank-2 (Journeyman),
  41-60 = rank-3 (Skilled Craftsman), 61-80 = rank-4 (Senior Craftsman), 81-100 = rank-5 (Master)

--expected-prev-score: optional CAS guard. If supplied and latest score for agent
  does not match, exit 3 (no append). Normal callers omit this flag.
EOF
  exit 1
}

AGENT=""
EVENT=""
NOTE=""
LIFECYCLE_FILE="${LIFECYCLE_FILE_DEFAULT}"
EXPECTED_PREV_SCORE=""
DELTA=""
UNDO_TS=""
REASON=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent)                AGENT="${2:?missing value for --agent}"; shift 2 ;;
    --event)                EVENT="${2:?missing value for --event}"; shift 2 ;;
    --note)                 NOTE="${2:?missing value for --note}"; shift 2 ;;
    --lifecycle-file)       LIFECYCLE_FILE="${2:?missing value for --lifecycle-file}"; shift 2 ;;
    --expected-prev-score)  EXPECTED_PREV_SCORE="${2:?missing value for --expected-prev-score}"; shift 2 ;;
    --delta)                DELTA="${2:?missing value for --delta}"; shift 2 ;;
    --undo)                 UNDO_TS="${2:?missing value for --undo}"; shift 2 ;;
    --reason)               REASON="${2:?missing value for --reason}"; shift 2 ;;
    # Legacy --scores-file param: accepted but ignored (agent-scores.json write path removed)
    --scores-file)          shift 2 ;;
    -h|--help)              usage ;;
    *)                      echo "Unknown argument: $1" >&2; usage ;;
  esac
done

[[ -z "${AGENT}" ]] && { echo "Missing required --agent" >&2; usage; }

# -------- M1b: ALWAYS reject caller-supplied --event manual_reversal --------
# Fires BEFORE the mode-mutex check so callers cannot smuggle the internal
# event in any combination (codex iter-2 C3/C4).
if [[ "${EVENT}" == "manual_reversal" ]]; then
  echo "${SCRIPT_NAME}: manual_reversal is internal-only — caller-supplied --event manual_reversal is never valid; use --delta or --undo instead" >&2
  exit 1
fi

# -------- Mode determination + mutex (M1/M2) --------
# Modes: event (existing), delta (M1), undo (M2). Exactly one must be set.
mode_count=0
[[ -n "${EVENT}" ]] && mode_count=$((mode_count + 1))
[[ -n "${DELTA}" ]] && mode_count=$((mode_count + 1))
[[ -n "${UNDO_TS}" ]] && mode_count=$((mode_count + 1))

if [[ ${mode_count} -eq 0 ]]; then
  echo "${SCRIPT_NAME}: must specify exactly one of --event, --delta, or --undo" >&2
  usage
fi
if [[ ${mode_count} -gt 1 ]]; then
  echo "${SCRIPT_NAME}: --event, --delta, and --undo are mutually exclusive" >&2
  exit 1
fi

# --delta and --undo require --reason
if [[ -n "${DELTA}" || -n "${UNDO_TS}" ]]; then
  if [[ -z "${REASON}" ]]; then
    if [[ -n "${DELTA}" ]]; then
      echo "${SCRIPT_NAME}: --delta requires --reason" >&2
    else
      echo "${SCRIPT_NAME}: --undo requires --reason" >&2
    fi
    exit 1
  fi
fi

# --delta must be a valid integer (sign optional)
if [[ -n "${DELTA}" ]]; then
  if ! [[ "${DELTA}" =~ ^[+-]?[0-9]+$ ]]; then
    echo "${SCRIPT_NAME}: --delta must be a signed integer, got '${DELTA}'" >&2
    exit 1
  fi
fi

# Ensure lifecycle file directory exists
LIFECYCLE_DIR="$(dirname "${LIFECYCLE_FILE}")"
mkdir -p "${LIFECYCLE_DIR}"

# Touch the lifecycle file if it does not yet exist
if [[ ! -f "${LIFECYCLE_FILE}" ]]; then
  touch "${LIFECYCLE_FILE}"
fi

# -------- M3: close_success_* precondition gate (event mode only) --------
# Runs BEFORE lock acquisition — failed precondition exits without touching file.
if [[ "${EVENT}" == "close_success_qa_pass" || "${EVENT}" == "close_success_qa_fail_fixed" ]]; then
  # 1) --note must be present + match safe-stem regex with no path traversal
  if [[ -z "${NOTE}" ]]; then
    echo "${SCRIPT_NAME}: close_success_* events require --note=<close-report-stem> matching ^[A-Za-z0-9][A-Za-z0-9_-]{2,80}\$ (precondition unmet)" >&2
    exit 5
  fi
  # Path-traversal block — must NOT contain /, \, or . (which forbids '..' too)
  if [[ "${NOTE}" == *"/"* || "${NOTE}" == *"\\"* || "${NOTE}" == *"."* ]]; then
    echo "${SCRIPT_NAME}: --note '${NOTE}' contains forbidden path-traversal characters (/, \\, ., ..); regex requires safe stem (precondition unmet)" >&2
    exit 5
  fi
  # Safe-stem regex — first char alphanumeric, total length 3-81
  if ! [[ "${NOTE}" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{2,80}$ ]]; then
    echo "${SCRIPT_NAME}: --note '${NOTE}' fails safe-stem regex ^[A-Za-z0-9][A-Za-z0-9_-]{2,80}\$ (precondition unmet)" >&2
    exit 5
  fi

  # 2/3/4/5) Delegate to scripts/close-scoring-decide.py for verdict classification.
  # Returns events=[] with non-null skip_reason when the gate blocks. We pass
  # qa_ever_rejected=false arbitrarily — the gate decision is identical for both
  # close_success_qa_pass and close_success_qa_fail_fixed (both go through the
  # same close-report YES check); we only inspect WHETHER events[] is non-empty.
  # Canonical subshell-wrap (AC-10 / 20260520-221452): each python3 invocation
  # MUST appear on the same line as `source ~/.claude/venv/bin/activate && python3`.
  decide_out=""
  if ! decide_out="$( ( source ~/.claude/venv/bin/activate && python3 "${REPO_ROOT}/scripts/close-scoring-decide.py" --task-id "${NOTE}" --qa-ever-rejected false --repo-root "${REPO_ROOT}" ) 2>&1)"; then
    echo "${SCRIPT_NAME}: close-scoring-decide.py crashed: ${decide_out}" >&2
    exit 5
  fi
  # Parse events[] from decide_out — canonical subshell-wrap.
  events_count=$(printf '%s' "${decide_out}" | ( source ~/.claude/venv/bin/activate && python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('events') or []))" ) 2>/dev/null || echo "0")
  skip_reason=$(printf '%s' "${decide_out}" | ( source ~/.claude/venv/bin/activate && python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('skip_reason') or '')" ) 2>/dev/null || echo "")
  if [[ "${events_count}" != "1" ]]; then
    echo "${SCRIPT_NAME}: close_success_* precondition unmet — ${skip_reason}" >&2
    exit 5
  fi
fi

# Lock file for the lifecycle JSONL (separate from any legacy agent-scores.json.lock)
LOCK_FILE="${LIFECYCLE_FILE}.lock"

# Acquire exclusive lock; auto-release on FD close
exec 9>"${LOCK_FILE}"
if ! flock -w 10 9; then
  echo "${SCRIPT_NAME}: failed to acquire lock on ${LOCK_FILE} within 10s" >&2
  exit 2
fi

# Delegate event-name validation, CAS check, score arithmetic, and JSONL append to Python.
# Python exits 1 on unknown agent/event, 2 on IO/parse error, 3 on CAS conflict,
# 4 on --undo not-found/ambiguous (M2).
# venv activation is co-located on the same line as python3 per /dev Standard 3 — spec-20260518-225715 Cycle 2 P3.6.
( source ~/.claude/venv/bin/activate && python3 - \
    "${LIFECYCLE_FILE}" "${AGENT}" "${EVENT}" "${NOTE}" "${EXPECTED_PREV_SCORE}" "${DELTA}" "${UNDO_TS}" "${REASON}" <<'PYEOF'
import json
import os
import sys
import datetime

(lifecycle_file, agent, event, note, expected_prev_score_str,
 delta_str, undo_ts, reason) = sys.argv[1:9]

# Canonical event delta table (spec 5.1).
# Path A rebalance (task 20260524-205206 M1, cycle-total <= +5 across {dev,ba,qa}):
# - qa_first_pass / qa_second_pass zeroed (per-iteration nudges collapsed into close events)
# - close_success_qa_pass / close_success_qa_fail_fixed reduced to cross-agent sum = 4
# - user_rating_5 kept at {dev:1,ba:0,qa:0} so the cycle scenario
#   (qa_first_pass + close_success_qa_pass + user_rating_5) sums to 0+4+1 = 5
# - All negative-valued entries UNCHANGED (user directive: minimum stays -40)
# manual_reversal (task 20260529-210616 M1/M1b): all-zeros row exists only so the
#   EVENT_DELTAS sum-sweep tests trivially pass (NG1). Actual delta comes from
#   --delta CLI param or computed -target.delta in --undo mode. Caller-supplied
#   --event manual_reversal is ALWAYS rejected at the shell layer (M1b).
EVENT_DELTAS = {
    "close_success_qa_pass":       {"dev": 2,  "ba": 1,  "qa": 1},
    "close_success_qa_fail_fixed": {"dev": 2,  "ba": 1,  "qa": 1},
    "close_fail_qa_pass":          {"dev": -10, "ba": -5, "qa": -12},
    "close_fail_qa_fail":          {"dev": -10, "ba": -5, "qa": 0},
    "qa_first_pass":               {"dev": 0,  "ba": 0,  "qa": 0},
    "qa_reject_dev":               {"dev": -12, "ba": 0,  "qa": 0},
    "qa_reject_ba":                {"dev": -5, "ba": -8, "qa": 0},
    "qa_second_pass":              {"dev": 0,  "ba": 0,  "qa": 0},
    "user_rating_5":               {"dev": 1,  "ba": 0,  "qa": 0},
    "user_rating_4":               {"dev": -5, "ba": -3, "qa": -3},
    "user_rating_3":               {"dev": -15, "ba": -8, "qa": -8},
    "user_rating_2":               {"dev": -25, "ba": -12, "qa": -12},
    "user_rating_1":               {"dev": -40, "ba": -20, "qa": -20},
    "manual_reversal":             {"dev": 0,  "ba": 0,  "qa": 0},
}

CANONICAL_AGENTS = {
    "ba", "dev", "qa",
    "ui-specialist", "architect", "product-owner", "user", "pm",
    "changelog-analyst", "push-analyst", "merge-analyst", "pull-analyst",
    "cleanliness-inspector", "style-inspector", "prompt-inspector",
    "rule-inspector", "git-edge-case-analyst", "cleaner",
    "test-validator", "test-executor", "spec",
}

if agent not in CANONICAL_AGENTS:
    sys.stderr.write(
        f"score-update.sh: unknown agent '{agent}'. "
        f"Allowed agents: {', '.join(sorted(CANONICAL_AGENTS))}\n"
    )
    sys.exit(1)

# Determine mode from which CLI param is set (shell layer already enforced
# exactly-one-of and rejected caller manual_reversal).
mode = "event" if event else ("delta" if delta_str else "undo")

# Validate event name when in event mode
if mode == "event":
    if event not in EVENT_DELTAS:
        sys.stderr.write(
            f"score-update.sh: unknown event '{event}'. "
            f"Allowed events: {', '.join(sorted(k for k in EVENT_DELTAS.keys() if k != 'manual_reversal'))}\n"
        )
        sys.exit(1)
    if event == "manual_reversal":
        # Defense-in-depth — shell layer already rejected this, but guard at the
        # Python layer too in case the shell guard is ever bypassed (codex C3).
        sys.stderr.write(
            "score-update.sh: manual_reversal is internal-only — caller-supplied --event manual_reversal is never valid\n"
        )
        sys.exit(1)

# Read lifecycle.jsonl entries (under existing exclusive flock).
try:
    with open(lifecycle_file, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()
except OSError as e:
    sys.stderr.write(f"score-update.sh: cannot read {lifecycle_file}: {e}\n")
    sys.exit(2)

# Parse every line; collect (idx, entry) for parseable ones.
# Non-final malformed line -> exit 2. Final malformed line -> silently skip (crash-recovery).
parsed_entries = []  # list of (line_index, entry_dict)
for i, raw_line in enumerate(raw_lines):
    stripped = raw_line.rstrip("\n")
    if not stripped:
        continue
    is_final = (i == len(raw_lines) - 1)
    try:
        entry = json.loads(stripped)
    except json.JSONDecodeError:
        if is_final:
            continue
        sys.stderr.write(
            f"score-update.sh: malformed JSONL at line {i+1} of {lifecycle_file} (not final line)\n"
        )
        sys.exit(2)
    parsed_entries.append((i, entry))

# Find latest prior entry for this agent (for prev_score baseline 50 if none).
prev_score = 50
latest_entry_found = False
for _, entry in parsed_entries:
    if entry.get("agent") == agent:
        try:
            prev_score = int(entry.get("new_score", 50))
        except (TypeError, ValueError):
            sys.stderr.write(
                f"score-update.sh: prior entry for agent '{agent}' has non-numeric new_score\n"
            )
            sys.exit(2)
        latest_entry_found = True

# CAS check: --expected-prev-score honored in event AND delta modes.
# codex iter-1 F6: when no prior entry exists, baseline is 50; CAS must still
# work — so we compare against current prev_score regardless of latest_entry_found.
if expected_prev_score_str and mode in ("event", "delta"):
    try:
        expected = int(expected_prev_score_str)
    except ValueError:
        sys.stderr.write(f"score-update.sh: --expected-prev-score must be integer, got '{expected_prev_score_str}'\n")
        sys.exit(1)
    if prev_score != expected:
        sys.stderr.write(
            f"score-update.sh: CAS conflict — expected prev_score={expected} but latest is {prev_score} for agent '{agent}'\n"
        )
        sys.exit(3)

# -------- Compute delta + final event label per mode --------
if mode == "event":
    delta_map = EVENT_DELTAS[event]
    delta = delta_map.get(agent, 0)
    final_event = event
    final_reason = note or ""
elif mode == "delta":
    try:
        delta = int(delta_str)
    except ValueError:
        sys.stderr.write(f"score-update.sh: --delta must be integer, got '{delta_str}'\n")
        sys.exit(1)
    final_event = "manual_reversal"
    final_reason = reason
else:  # mode == "undo"
    # Find matching (agent, ts) entries among parseable rows.
    matches = [(i, e) for (i, e) in parsed_entries
               if e.get("agent") == agent and e.get("ts") == undo_ts]
    if len(matches) == 0:
        sys.stderr.write(
            f"score-update.sh: --undo target not found for ts={undo_ts} agent={agent}\n"
        )
        sys.exit(4)
    if len(matches) > 1:
        sys.stderr.write(
            f"score-update.sh: --undo target ambiguous — {len(matches)} entries match (ts={undo_ts}, agent={agent})\n"
        )
        sys.exit(4)
    target_idx, target_entry = matches[0]
    target_delta_raw = target_entry.get("delta")
    try:
        target_delta = int(target_delta_raw)
    except (TypeError, ValueError):
        sys.stderr.write(
            f"score-update.sh: --undo target row has non-numeric delta '{target_delta_raw}' "
            f"(ts={undo_ts}, agent={agent}, line={target_idx+1})\n"
        )
        sys.exit(2)
    delta = -target_delta
    final_event = "manual_reversal"
    final_reason = reason

# Compute unclamped_score BEFORE clamping (arch-7 clamp-audit field, mandatory per M1)
unclamped_score = prev_score + delta
# Apply clamp for new_score
new_score = min(100, unclamped_score)

# Build the 9-field mandatory JSONL entry (R9 verbatim: ts,agent,event,prev_score,new_score,delta,actor,reason + unclamped_score)
ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
entry_obj = {
    "ts": ts,
    "agent": agent,
    "event": final_event,
    "prev_score": prev_score,
    "new_score": new_score,
    "delta": delta,
    "unclamped_score": unclamped_score,
    "actor": "orchestrator",
    "reason": final_reason,
}
line = json.dumps(entry_obj, ensure_ascii=False) + "\n"

# Append to lifecycle.jsonl and fsync
try:
    with open(lifecycle_file, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
except OSError as e:
    sys.stderr.write(f"score-update.sh: failed to append to {lifecycle_file}: {e}\n")
    sys.exit(2)

print(f"{agent}:{final_event}:{prev_score}->{new_score} (delta={delta}, unclamped={unclamped_score})")
PYEOF
)
python_exit=$?
if [[ $python_exit -ne 0 ]]; then
  exit $python_exit
fi

# Lock auto-releases on shell exit
exit 0
