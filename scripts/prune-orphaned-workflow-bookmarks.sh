#!/usr/bin/env bash
# scripts/prune-orphaned-workflow-bookmarks.sh
#
# Purpose: report (and, only when explicitly asked, delete) root-level
# workflow-<session-id>.json bookmark files whose owning session no longer
# exists anywhere. A bookmark is a deletion candidate ONLY when BOTH hold:
#   1. no transcript for its session id exists under ANY account directory
#      (checking fewer than all of them has already produced a false
#      "orphan" verdict once in this repo's history — a transcript that
#      existed under a different account was missed)
#   2. its mtime is at least --min-age-days old (default: conservative),
#      so a session whose transcript simply has not landed yet is never
#      mistaken for a dead one
#
# Default mode reports only. Nothing is ever deleted unless --delete is
# passed explicitly.
#
# Usage:
#   prune-orphaned-workflow-bookmarks.sh [--delete] [--min-age-days N]
#   prune-orphaned-workflow-bookmarks.sh -h | --help
#
# Environment overrides (mirrors scripts/checkpoint-prune.sh's convention):
#   WORKFLOW_PRUNE_ACCOUNTS_DIR     default: /var/lib/claude-accounts
#   WORKFLOW_PRUNE_PROJECT_DIRNAME  default: -dev-shm-dev-workspace-dot-claude
#   WORKFLOW_PRUNE_MIN_AGE_DAYS     default: 14 (overridable by --min-age-days)
#
# Exit codes:
#   0  success (report printed, or delete completed with no errors)
#   1  environment error (not a git repo, or no account directories found —
#      an empty account set can never prove a bookmark orphaned, so this is
#      a hard failure, not treated as "everything is an orphan")
#   2  invalid arguments
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
prune-orphaned-workflow-bookmarks.sh — report or delete orphaned workflow-*.json bookmarks

Usage:
  prune-orphaned-workflow-bookmarks.sh [--delete] [--min-age-days N]
  prune-orphaned-workflow-bookmarks.sh -h | --help

Default mode reports only; nothing is deleted without --delete.

A workflow-<session-id>.json file at the repo root is a deletion candidate
ONLY when BOTH hold:
  - no transcript for <session-id> exists under ANY account directory
    (/var/lib/claude-accounts/*/claude/projects/<project-dirname>/<session-id>.jsonl)
  - its mtime is at least --min-age-days old (default 14)

Environment overrides:
  WORKFLOW_PRUNE_ACCOUNTS_DIR     default: /var/lib/claude-accounts
  WORKFLOW_PRUNE_PROJECT_DIRNAME  default: -dev-shm-dev-workspace-dot-claude
  WORKFLOW_PRUNE_MIN_AGE_DAYS     default: 14

Exit codes:
  0  success
  1  environment error (not a git repo, or no account directories found)
  2  invalid arguments
EOF
}

MODE="report"
MIN_AGE_DAYS="${WORKFLOW_PRUNE_MIN_AGE_DAYS:-14}"

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --delete) MODE="delete"; shift ;;
    --min-age-days)
      [ $# -ge 2 ] || { echo "Error: --min-age-days requires a value" >&2; usage >&2; exit 2; }
      MIN_AGE_DAYS="$2"; shift 2 ;;
    *) echo "Error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$MIN_AGE_DAYS" in
  ''|*[!0-9]*) echo "Error: --min-age-days / WORKFLOW_PRUNE_MIN_AGE_DAYS must be a non-negative integer (got: $MIN_AGE_DAYS)" >&2; exit 2 ;;
esac

REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "Error: $SCRIPT_DIR is not inside a git repository" >&2
  exit 1
}

ACCOUNTS_DIR="${WORKFLOW_PRUNE_ACCOUNTS_DIR:-/var/lib/claude-accounts}"
PROJECT_DIRNAME="${WORKFLOW_PRUNE_PROJECT_DIRNAME:--dev-shm-dev-workspace-dot-claude}"

ACCOUNT_NAMES=()
for acct_dir in "$ACCOUNTS_DIR"/*/; do
  [ -d "$acct_dir" ] || continue
  ACCOUNT_NAMES+=("$(basename "$acct_dir")")
done

if [ "${#ACCOUNT_NAMES[@]}" -eq 0 ]; then
  echo "Error: no account directories found under $ACCOUNTS_DIR — cannot prove any bookmark orphaned without checking every account. Refusing to proceed." >&2
  exit 1
fi

NOW_EPOCH="$(date +%s)"
MIN_AGE_SECONDS=$(( MIN_AGE_DAYS * 86400 ))

TOTAL_SCANNED=0
LIVE_COUNT=0
TOO_YOUNG_COUNT=0
CANDIDATE_COUNT=0
CANDIDATE_BYTES=0
SKIPPED_COUNT=0
DELETED_COUNT=0
DELETED_BYTES=0

CANDIDATES=()

echo "Accounts checked (${#ACCOUNT_NAMES[@]}): ${ACCOUNT_NAMES[*]}"
echo "Project dirname: $PROJECT_DIRNAME"
echo "Minimum age for a deletion candidate: ${MIN_AGE_DAYS} day(s)"
echo "Repo root: $REPO_ROOT"
echo ""

shopt -s nullglob
for f in "$REPO_ROOT"/workflow-*.json; do
  [ -f "$f" ] || continue
  base="$(basename "$f")"

  case "$base" in
    workflow-*.json) ;;
    *) echo "SKIP (name does not match expected pattern): $base" >&2; continue ;;
  esac

  sid="${base#workflow-}"
  sid="${sid%.json}"
  case "$sid" in
    ''|*[!A-Za-z0-9-]*) echo "SKIP (session id contains unexpected characters): $base" >&2; continue ;;
  esac

  TOTAL_SCANNED=$((TOTAL_SCANNED + 1))

  found_in=""
  for acct in "${ACCOUNT_NAMES[@]}"; do
    transcript="$ACCOUNTS_DIR/$acct/claude/projects/$PROJECT_DIRNAME/$sid.jsonl"
    if [ -f "$transcript" ]; then
      found_in="$acct"
      break
    fi
  done

  mtime_epoch="$(stat -c %Y "$f")"
  size_bytes="$(stat -c %s "$f")"
  mtime_iso="$(date -u -d "@$mtime_epoch" +%Y-%m-%dT%H:%M:%SZ)"
  age_days=$(( (NOW_EPOCH - mtime_epoch) / 86400 ))

  if [ -n "$found_in" ]; then
    LIVE_COUNT=$((LIVE_COUNT + 1))
    echo "LIVE          $base  mtime=$mtime_iso size=${size_bytes}B  (transcript found under account: $found_in)"
    continue
  fi

  if [ $(( NOW_EPOCH - mtime_epoch )) -lt "$MIN_AGE_SECONDS" ]; then
    TOO_YOUNG_COUNT=$((TOO_YOUNG_COUNT + 1))
    echo "ORPHAN(young) $base  mtime=$mtime_iso size=${size_bytes}B age=${age_days}d  (no transcript in any of: ${ACCOUNT_NAMES[*]} — but younger than ${MIN_AGE_DAYS}d floor, not a candidate)"
    continue
  fi

  CANDIDATE_COUNT=$((CANDIDATE_COUNT + 1))
  CANDIDATE_BYTES=$((CANDIDATE_BYTES + size_bytes))
  CANDIDATES+=("$f")
  echo "CANDIDATE     $base  mtime=$mtime_iso size=${size_bytes}B age=${age_days}d  (no transcript in any of: ${ACCOUNT_NAMES[*]})"
done

echo ""
echo "Scanned: $TOTAL_SCANNED   Live: $LIVE_COUNT   Orphaned-but-too-young: $TOO_YOUNG_COUNT   Candidates: $CANDIDATE_COUNT   Candidate bytes: $CANDIDATE_BYTES"

if [ "$MODE" = "report" ]; then
  echo ""
  echo "Report-only mode — nothing deleted. Re-run with --delete to remove the $CANDIDATE_COUNT candidate(s) above."
  exit 0
fi

LOG_DIR="$HOME/.claude/logs"
mkdir -p "$LOG_DIR" 2>/dev/null || true
LOG_FILE="$LOG_DIR/workflow-bookmark-prune.log"

for f in "${CANDIDATES[@]}"; do
  base="$(basename "$f")"

  real="$(realpath -e "$f" 2>/dev/null)" || { echo "SKIP (vanished before delete): $base" >&2; SKIPPED_COUNT=$((SKIPPED_COUNT + 1)); continue; }
  case "$real" in
    "$REPO_ROOT"/*) ;;
    *) echo "SKIP (resolves outside repo root, refusing): $base" >&2; SKIPPED_COUNT=$((SKIPPED_COUNT + 1)); continue ;;
  esac

  rel="${real#"$REPO_ROOT"/}"
  if git -C "$REPO_ROOT" ls-files --error-unmatch -- "$rel" >/dev/null 2>&1; then
    echo "SKIP (git-tracked, refusing to delete): $base" >&2
    SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    continue
  fi

  size_bytes="$(stat -c %s "$real")"
  mtime_iso="$(date -u -d "@$(stat -c %Y "$real")" +%Y-%m-%dT%H:%M:%SZ)"

  rm -f -- "$real"
  DELETED_COUNT=$((DELETED_COUNT + 1))
  DELETED_BYTES=$((DELETED_BYTES + size_bytes))
  printf '%s deleted %s mtime=%s size=%sB\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$base" "$mtime_iso" "$size_bytes" >> "$LOG_FILE" 2>/dev/null || true
  echo "DELETED       $base  mtime=$mtime_iso size=${size_bytes}B"
done

echo ""
echo "workflow-bookmark-prune: candidates=$CANDIDATE_COUNT deleted=$DELETED_COUNT deleted_bytes=$DELETED_BYTES skipped=$SKIPPED_COUNT"
