#!/usr/bin/env bash
# /usr/local/sbin/tmp-cleanup.sh
#
# Daily cleanup of /tmp (4G tmpfs) and /var/tmp/codex-outputs/.
# Installed 2026-05-01; extended 2026-05-19 (dev-20260519-161035) with
# EXCLUSION-FIRST ordering, full pattern coverage, IEC-i freed-bytes total,
# per-category "what was removed" logging, and conditional dry-run output
# (tee-to-stdout-AND-log when DRY_RUN=1).
#
# Usage:
#   tmp-cleanup.sh            # delete (called from cron)
#   tmp-cleanup.sh --dry-run  # list candidates only (stdout AND log)
#
# Categories + retention:
#   codex outputs / prompts            >1 day
#   Playwright Chrome profiles         >1 day
#   hook state files                   >7 days
#   dev/test scratch dirs              >3 days  (incl. *-scratch-[0-9]*)
#   broader stale build/deploy/etc     >7 days
#   /tmp/claude-0/**/*.output          >1 day   (deep, carve-out — see below)
#   /var/tmp/codex-outputs/            >7 days
#
# EXCLUSION-FIRST: a single shared EXCLUDE_PRUNE bash array is applied as
# `\( ... \) -prune -o \( <predicates> -print \)` at the start of EVERY
# top-level /tmp find invocation. The `-print` (dry-run) or `-print0 | xargs -0r
# rm -rf --` (real) action lives INSIDE the right-hand non-prune branch — never
# appended after the whole expression — so excluded paths are never acted on.
#
# CARVE-OUT: the /tmp/claude-0 deep .output query DOES NOT use EXCLUDE_PRUNE
# because its job is to descend INTO /tmp/claude-0 (which EXCLUDE_PRUNE prunes
# at the top level). This is the SOLE intentional exception.
#
# Anything not matched here is LEFT ALONE.

set -uo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

LOG=/var/log/tmp-cleanup.log
mkdir -p "$(dirname "$LOG")"

# Conditional output redirect:
#   dry-run → tee to BOTH stdout AND log (SOLE acceptable shape per OBJ-2 — makes
#             candidate enumeration observable interactively AND preserves the
#             post-hoc audit record)
#   real    → log-only (preserves the original silent-cron behavior)
if [ "$DRY_RUN" -eq 1 ]; then
  exec > >(tee -a "$LOG") 2>&1
else
  exec >> "$LOG" 2>&1
fi

echo
echo "=== $(date '+%Y-%m-%d %H:%M:%S') tmp-cleanup.sh start dry_run=$DRY_RUN ==="

before_tmp=$(df --output=avail /tmp 2>/dev/null | tail -1 || echo 0)
before_var=$(df --output=avail /var/tmp 2>/dev/null | tail -1 || echo 0)

mkdir -p /var/tmp/codex-outputs

# ── Shared hard-exclusion clause (EXCLUSION-FIRST) ────────────────────
# Reused as "${EXCLUDE_PRUNE[@]}" by every TOP-LEVEL /tmp find call below.
# The trailing -prune flips the matched paths into the LEFT branch; the
# right-hand `-o \( ... -print/-print0 \)` branch then carries the action.
# `-path '*debug-profile*'` is a defensive wildcard that protects any future
# renamed debug profile across ALL sweep categories — not just Playwright.
EXCLUDE_PRUNE=( \(
  -path /tmp/chrome-debug-profile -o
  -path /tmp/happy-attachments -o
  -path /tmp/claude-0 -o
  -path '/tmp/claude-commit-plan-*' -o
  -path '/tmp/happy-p05-cdp-*' -o
  -path '*debug-profile*'
\) -prune )

# ── Run helper for /tmp top-level categories ──────────────────────────
# Rewritten 2026-05-19 (codex F3): the prior shape appended `-print` /
# `-exec rm -rf {} +` AFTER the caller's find expression, which short-circuits
# the EXCLUDE_PRUNE branch and would act on excluded paths. The new shape
# accepts the right-hand non-prune predicate as positional arguments and
# injects the action INSIDE that branch via shell composition:
#   find /tmp -maxdepth 1 "${EXCLUDE_PRUNE[@]}" -o \( <args> -print \)
#
# Per-category logging (AC6 / codex F6): we ALWAYS print the candidates first
# (this is the "what was removed" log line per category) — for real runs the
# rm follows; for dry-run nothing else happens. This shape satisfies AC6's
# "log either candidate paths OR per-category removed_count" requirement: we
# choose candidate-paths-before-rm, applied uniformly across all sweep
# categories.
run_tmp() {
  local desc="$1"; shift
  echo "--- $desc ---"
  if [ "$DRY_RUN" -eq 1 ]; then
    # Codex review F5: removed `| head -200` truncation — AC4/AC5 require
    # ALL candidates from every populated tier to be observable on stdout
    # (truncating after 200 entries would mask candidates from later tiers
    # in the same run and weaken the AC verification).
    find /tmp -maxdepth 1 "${EXCLUDE_PRUNE[@]}" -o \( "$@" -print \) 2>/dev/null || true
  else
    # Codex review F4: candidate temp files MUST NOT live under /tmp — the
    # purpose of this run is to FREE /tmp, and if /tmp is at ENOSPC the
    # mktemp would itself fail before any deletion happens. /var/tmp is on
    # the disk-backed root fs.
    local tmpfile
    tmpfile=$(mktemp -p /var/tmp tmp-cleanup-cands-XXXXXX 2>/dev/null) || {
      echo "WARN: cannot create candidate temp file under /var/tmp; skipping category"
      return 0
    }
    find /tmp -maxdepth 1 "${EXCLUDE_PRUNE[@]}" -o \( "$@" -print0 \) 2>/dev/null > "$tmpfile" || true
    tr '\0' '\n' < "$tmpfile" | sed '/^$/d' || true
    xargs -0r rm -rf -- < "$tmpfile" 2>/dev/null || true
    rm -f "$tmpfile" 2>/dev/null || true
  fi
}

# ── Helper for non-/tmp-top-level categories ──────────────────────────
# Used by the /tmp/claude-0 deep query (carve-out) and /var/tmp/codex-outputs.
# Does NOT use EXCLUDE_PRUNE because both targets are INSIDE paths that the
# shared clause prunes at the top level. The action still lives INSIDE the
# find expression (no trailing append).
run_path() {
  local desc="$1"; shift
  local path="$1"; shift
  echo "--- $desc ---"
  if [ "$DRY_RUN" -eq 1 ]; then
    # Codex review F5: removed `| head -200` (same rationale as run_tmp).
    find "$path" "$@" -print 2>/dev/null || true
  else
    # Codex review F4: candidate temp files under /var/tmp, not /tmp.
    local tmpfile
    tmpfile=$(mktemp -p /var/tmp tmp-cleanup-cands-XXXXXX 2>/dev/null) || {
      echo "WARN: cannot create candidate temp file under /var/tmp; skipping category"
      return 0
    }
    find "$path" "$@" -print0 2>/dev/null > "$tmpfile" || true
    tr '\0' '\n' < "$tmpfile" | sed '/^$/d' || true
    xargs -0r rm -rf -- < "$tmpfile" 2>/dev/null || true
    rm -f "$tmpfile" 2>/dev/null || true
  fi
}

# ── Codex outputs / prompts (>1 day) — heavy individually, accumulate fast ──
run_tmp "codex artifacts >1d in /tmp" \
  -mtime +1 \
  \( -name 'codex-output-*' -o -name 'codex-prompt-*' -o -name 'openai-codex' \)

# ── Playwright Chrome profiles (>1 day) — 50-150MB each, never reused ──
# NOTE: `chrome-debug-profile` literal REMOVED from this list (2026-05-19) —
# it is now protected by the shared EXCLUDE_PRUNE clause above. Removing the
# literal here eliminates dead code (EXCLUDE_PRUNE prunes it first anyway).
run_tmp "Playwright profiles >1d in /tmp" \
  -mtime +1 \
  \( -name 'happy-cdp-*' \
     -o -name 'happy-live-rerun-cdp-*' \
     -o -name 'happy-p05-chrome-*' \
     -o -name 'ui-specialist-chrome-*' \)

# ── Hook state files (>7 days) — small but accumulate; sessions long dead ──
# Includes `claude-pressure-warn-*` (added 2026-05-19) which sweeps BOTH the
# Layer-1.5 counter files (regular file) AND their paired `.lock` files
# (also regular file — flock is the SOLE acceptable lock primitive per OBJ-3
# specifically because the resulting lock file matches `-type f`).
run_tmp "hook state >7d in /tmp" \
  -mtime +7 -type f \
  \( -name 'claude-tool-streak-*.json' \
     -o -name 'claude-orchestrator-consent-*.flag' \
     -o -name 'claude-do-task-*.json' \
     -o -name 'claude-do-resv-*' \
     -o -name 'claude-commit-grant-*.json' \
     -o -name 'claude-push-grant-*.json' \
     -o -name 'contract-bookmark-*.json' \
     -o -name 'artifact-status-*.json' \
     -o -name 'claude-pressure-warn-*' \)

# ── Dev/test scratch (>3 days) — known transient patterns only ──
# NOTE: `happy-attachments` literal REMOVED from this list (2026-05-19) — it
# is now protected by the shared EXCLUDE_PRUNE clause. New patterns added:
# qa-semantic-*, tier-*, qa-*, dev-semantic-*, dev-same*, dev-root*,
# dev-broad*, *-scratch-[0-9]* (bounded by [0-9]* so the wildcard cannot match
# unrelated names like `foo-scratch-readme`).
run_tmp "dev/test scratch >3d in /tmp" \
  -mtime +3 \
  \( -name 'tier-test-*' \
     -o -name 'dev-verify-*' \
     -o -name 'qa-codex-verify-*' \
     -o -name 'p1514-*' \
     -o -name 'p09-check-*' \
     -o -name 'rednote-*' \
     -o -name 'metro-cache' \
     -o -name 'happy-test' \
     -o -name 'happy-test-runner.sh' \
     -o -name 'nm_backup_qa_prep' \
     -o -name 'dev-verify-*-*' \
     -o -name 'qa-semantic-*' \
     -o -name 'tier-*' \
     -o -name 'qa-*' \
     -o -name 'dev-semantic-*' \
     -o -name 'dev-same*' \
     -o -name 'dev-root*' \
     -o -name 'dev-broad*' \
     -o -name '*-scratch-[0-9]*' \)

# ── Broader stale-pattern tier (>7 days) ──
# Codex-enumerated patterns observed accumulating on disk: build artifacts,
# deploy scratch, playwright artifacts, expo bundles, etc.
run_tmp "broader stale >7d in /tmp" \
  -mtime +7 \
  \( -name 'map-*' \
     -o -name 'career-*' \
     -o -name '*-app-check' \
     -o -name '*-deploy' \
     -o -name 'playwright-artifacts-*' \
     -o -name 'expo-ui-*' \
     -o -name '.cleanup-staging-*' \
     -o -name 'sort[A-Za-z0-9]*' \
     -o -name '*-bundle.js' \
     -o -name '*-main.js' \
     -o -name 'happy-app-build-test' \
     -o -name 'ocr_env' \)

# ── /tmp/claude-0 deep .output sweep (>1 day) ──
# CARVE-OUT: this query does NOT use EXCLUDE_PRUNE — its purpose is to
# descend INTO /tmp/claude-0 (which EXCLUDE_PRUNE protects at the top level).
# Real .output files live at depth 6: /tmp/claude-0/<project>/<session>/tasks/*.output.
# -mindepth 2 skips the /tmp/claude-0 root itself; -type f ensures directories
# named *.output (if any) cannot match. -mtime +1 is the verified-safe
# threshold (BA+QA observed lsof intersection (open AND >1d) = 0).
run_path "claude-0 deep .output >1d" /tmp/claude-0 \
  -mindepth 2 -type f -name '*.output' -mtime +1

# ── /var/tmp/codex-outputs (>7 days) — on disk, less urgent but still bounded ──
# Separate path (not /tmp), so EXCLUDE_PRUNE does not apply. Existing sweep,
# preserved per AC7. Its delta IS counted toward `freed_total` below.
run_path "codex-outputs >7d in /var/tmp" /var/tmp/codex-outputs \
  -mindepth 1 -mtime +7

# ── Freed-bytes summary ────────────────────────────────────────────────
after_tmp=$(df --output=avail /tmp 2>/dev/null | tail -1 || echo 0)
after_var=$(df --output=avail /var/tmp 2>/dev/null | tail -1 || echo 0)

echo
# Per-mount deltas (KB; df --output=avail emits KB on this server). Preserved
# per AC6: the existing per-mount freed=...K lines remain unchanged.
echo "/tmp     avail before=${before_tmp}K  after=${after_tmp}K  freed=$((after_tmp - before_tmp))K"
echo "/var/tmp avail before=${before_var}K  after=${after_var}K  freed=$((after_var - before_var))K"

# TOTAL freed across BOTH mounts (per OBJ-4 / codex F4): the user's intent is
# "total bytes freed by this script's run", which AC7's enumeration of the
# /var/tmp/codex-outputs >7d category as one of the preserved sweep categories
# explicitly includes. Negative deltas (mount-busy noise where avail drops
# during the run) are clamped to 0 so the TOTAL is monotonic. numfmt
# --to=iec-i --suffix=B emits the IEC binary family (MiB/KiB/GiB) — plain
# --to=iec emits MB/KB/GB which would fail AC6's example-suffix match.
tmp_freed_kb=$(( after_tmp - before_tmp ))
var_freed_kb=$(( after_var - before_var ))
[ "$tmp_freed_kb" -lt 0 ] && tmp_freed_kb=0
[ "$var_freed_kb" -lt 0 ] && var_freed_kb=0
freed_total_kb=$(( tmp_freed_kb + var_freed_kb ))
freed_total=$(numfmt --to=iec-i --suffix=B $(( freed_total_kb * 1024 )) 2>/dev/null || echo "${freed_total_kb}KiB")
echo "freed_total=${freed_total}"

echo "=== end ==="
