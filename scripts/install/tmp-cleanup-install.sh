#!/usr/bin/env bash
# /usr/local/sbin/tmp-cleanup.sh
#
# Hourly cleanup (scripts/install/tmp-cleanup.cron): first the short-space rule, then the age rules.
#
# Usage:
#   tmp-cleanup.sh                  # remove (called from cron; silent)
#   tmp-cleanup.sh --dry-run        # list candidates only (stdout)
#   tmp-cleanup.sh --pressure PREV LAST  # the short-space rule (not again within REACT_EVERY s of LAST),
#                                   # then the space notice when the set of short volumes differs from PREV
#                                   # (hooks/userprompt-tmpfs-pressure.sh)
#
# Short-space rule. Watched: the volumes holding the state root (hooks/lib/harness_state_dir.sh), the session
# root (hooks/session-scratch-init.sh's), the CLI's command output root (both: hooks/lib/locations.py, from this
# process's environment) and the harness home. A volume is
# short at SHORT_PCT% used or with less than FLOOR_BYTES free (at most a quarter of its size). While one is short,
# what is on it and provably dead goes, if no live process uses it (its cwd or an open file): the temp entries of
# a session root whose owner mark (.owner) names a process proven gone, never its control state, which goes by
# its own age rule only; the command output (*.output, >10 min) of a session with no owner mark not proven gone;
# a live session's dispatch temp directories its dispatch_temp.py retired. "Gone" and "in use" are
# hooks/lib/dispatch_temp.py's (judge); where it cannot tell (no /proc, no process id recorded) nothing that
# depends on it goes, and the notice says so. A role directory (agents'
# own scratch and drafts, which a resumed session needs) is never removed with its root: of any session, those
# untouched for 24 h go, oldest first, while the volume stays short. Nothing else of a live
# session, nothing without this harness's owner mark, nothing in a project or in the harness home.
#
# Age rules:
#   codex outputs / prompts            >1 day
#   Playwright Chrome profiles         >1 day
#   hook state files                   >7 days  (under the state dir: hooks/lib/harness_state_dir.sh)
#   dev/test scratch dirs              >3 days  (incl. *-scratch-[0-9]*)
#   broader stale build/deploy/etc     >7 days
#   <CLI temp root>/claude-<uid>/**/*.output >1 day (deep, carve-out — see below)
#   /var/tmp/codex-outputs/            >7 days
#   session roots, whole directories   role dirs >7 days; a dead session's other entries >3 days
#
# EXCLUSION-FIRST: a single shared EXCLUDE_PRUNE bash array is applied as
# `\( ... \) -prune -o \( <predicates> -print \)` at the start of EVERY
# top-level /tmp find invocation. The `-print` (dry-run) or `-print0 | xargs -0r
# rm -rf --` (real) action lives INSIDE the right-hand non-prune branch — never
# appended after the whole expression — so excluded paths are never acted on.
#
# CARVE-OUT: the claude-<uid> deep .output query DOES NOT use EXCLUDE_PRUNE
# because its job is to descend INTO /tmp/claude-<uid> (which EXCLUDE_PRUNE prunes
# at the top level). This is the SOLE intentional exception.
#
# Anything not matched here is LEFT ALONE.

set -uo pipefail

DRY_RUN=0 PRESSURE=0 PREV="" LAST=0
case "${1:-}" in
  --dry-run) DRY_RUN=1 ;;
  --pressure) PRESSURE=1; PREV="${2:-}"; [[ "${3:-}" =~ ^[0-9]+$ ]] && LAST=$3 ;;
esac

# Output: a dry run lists its candidates to whoever runs it, --pressure prints the notice to its hook; a
# real run (cron) stays silent, as it always has. No log file is kept: nothing reads one (P1b E12).
if [ "$DRY_RUN" -ne 1 ] && [ "$PRESSURE" -ne 1 ]; then
  exec >/dev/null 2>&1
fi
exec 2>/dev/null

SHORT_PCT=90
REACT_EVERY=60  # seconds between two reactions at prompts: a prompt is not slowed by more than one
FLOOR_BYTES=$((1024 * 1024 * 1024))

# The harness home: this file's when it runs from one (the hook), else the settings' ${CLAUDE_HOME:-$HOME/.claude}.
HARNESS_HOME=$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd -P)
[ -f "$HARNESS_HOME/hooks/lib/harness_state_dir.sh" ] || HARNESS_HOME="${CLAUDE_HOME:-${HOME:-}/.claude}"
STATE_DIR=""
. "$HARNESS_HOME/hooks/lib/harness_state_dir.sh" && STATE_DIR="$(harness_state_dir)"
# The roots of this process's own installation, from its environment through hooks/lib/locations.py (the one place
# for locations): the session root and the CLI's command output root (<root>/claude-<uid>/<project>/<session>/
# tasks/*.output), of this user only. Nothing else is listed, measured or removed from; without an answer, none.
ROOTS=$(timeout 5s python3 -I -c 'import sys
sys.path.insert(0, sys.argv[1]); import locations as L; print(L.session_scratch_root()); print(L.cli_temp_root())' \
  "$HARNESS_HOME/hooks/lib") || ROOTS=""
SESSION_ROOT="${ROOTS%%$'\n'*}" CLI_ROOT="${ROOTS#*$'\n'}"
[ "$CLI_ROOT" != "$ROOTS" ] || CLI_ROOT=""
[ -f "$SESSION_ROOT/.owner" ] && SESSION_ROOT="${SESSION_ROOT%/*}"  # TMPDIR is one session's own directory
case "$SESSION_ROOT/" in  # never a root in a project or in the harness home
  "${CLAUDE_PROJECT_DIR:-//}"/*|*/.claude/scratch/*|"$HARNESS_HOME"/*|/) SESSION_ROOT="" ;;
esac
CLI_DIRS=()
[ -n "$CLI_ROOT" ] && [ -d "$CLI_ROOT/claude-$(id -u)" ] && CLI_DIRS=("$CLI_ROOT/claude-$(id -u)")
WATCH=("$STATE_DIR" "$SESSION_ROOT" "$CLI_ROOT" "$HARNESS_HOME")
# The hook state names: swept by age below (their one lifetime: a session's process being gone is none).
HOOK_STATE=( \( -name 'claude-tool-streak-*.json'
     -o -name 'claude-orchestrator-consent-*.flag'
     -o -name 'claude-do-task-*.json'
     -o -name 'claude-do-resv-*'
     -o -name 'claude-commit-grant-*.json'
     -o -name 'claude-pressure-warn-*' \) )

# volumes: one line per volume holding a watched path, "<device> <short 0|1> <avail> <size> <use%> <mount>".
volumes() {
  local p paths=()
  for p in "${WATCH[@]}"; do
    [ -n "$p" ] || continue
    while [ ! -e "$p" ] && [ -n "$p" ]; do p="${p%/*}"; done
    paths+=("${p:-/}")
  done
  timeout 2s df -B1 --output=avail,size,pcent,target "${paths[@]}" | tail -n +2 \
    | awk -v pct="$SHORT_PCT" -v floor="$FLOOR_BYTES" '{ t = $0; sub(/^ *[^ ]+ +[^ ]+ +[^ ]+ +/, "", t)
        if (seen[t]++) next; f = $2 / 4; if (f > floor) f = floor; u = $3 + 0
        print (u >= pct || $1 < f) ? 1 : 0, $1, $2, u, t }' \
    | while read -r s a z u t; do printf '%s %s %s %s %s %s\n' "$(stat -c %d "$t" || echo -)" "$s" "$a" "$z" "$u" "$t"; done
}
on_short() { case " $SHORT_DEVS " in *" $(stat -c %d "$1") "*) return 0 ;; esac; return 1; }

# judge <path>...: VERDICT[<path>] by hooks/lib/dispatch_temp.py's one definition: of an .owner alive|gone|unknown
# (its process), of anything else used|unused|unknown (a live process's cwd or open file at or below it);
# CONTROL[<path>] when it is a session's control state. Without that file or /proc: unknown, counted in UNSURE.
declare -A VERDICT CONTROL
UNSURE=0
judge() {
  local v
  [ "$#" -gt 0 ] || return 0
  while IFS= read -r -d '' v; do
    case ${v%% *} in control) CONTROL[${v#* }]=1 ;; *) VERDICT[${v#* }]=${v%% *} ;; esac
  done < <(timeout 5s python3 "$HARNESS_HOME/hooks/lib/dispatch_temp.py" --judge "$@")
  for v; do [ "${VERDICT[$v]:-unknown}" = unknown ] && VERDICT[$v]=unknown && UNSURE=$((UNSURE + 1)); done
}

# retired <live session dir>: its dispatch temp directories hooks/lib/dispatch_temp.py retired ("kept", line 2 of
# its .dispatch-tmp), to CANDS; the module drops a listed directory that is gone.
retired() {
  local line="" k ks=()
  { read -r _; read -r line; } < "$1/.dispatch-tmp"
  [[ "$line" =~ \"kept\":\ \[([^]]*)\] ]] && IFS=, read -ra ks <<<"${BASH_REMATCH[1]}"
  for k in "${ks[@]}"; do
    k="${k%\"}"; k="$1/${k##*/}"
    [[ "${k##*/}" == dispatch-* && -d "$k" && ! -L "$k" ]] && CANDS+=("$k") PROBES+=("$k")
  done
}
# react: remove (a dry run lists) what is on a short volume and provably dead; REMOVED holds what went.
REMOVED=()
# ours <.owner>: this harness's mark for its directory.
ours() {
  local d="${1%/.owner}" REC=""
  [ -f "$1" ] && [ ! -L "$1" ] && [ ! -L "$d" ] || return 1
  read -r -d '' REC < "$1"
  [[ "$REC" =~ \"sid\":\ *\"([^\"]*)\" && "${BASH_REMATCH[1]}" == "${d##*/}" && "${d##*/}" =~ ^[A-Za-z0-9_.-]{1,128}$ \
     && "${d##*/}" != *..* ]]
}
# split <session dir>: ROLES, its role directories (each holds an agent's own <role>/<agent id>/, as
# hooks/sessionend-scratch-sweep.sh keeps them), and REST, its other entries but the .owner.
split() {
  local e; ROLES=() REST=()
  for e in "$1"/* "$1"/.[!.]* "$1"/..?*; do
    [ -e "$e" ] || [ -L "$e" ] || continue
    [ "${e##*/}" = .owner ] && continue
    if [ -d "$e" ] && [ ! -L "$e" ] && compgen -G "$e/a[0-9a-f]*/" >/dev/null; then ROLES+=("$e"); else REST+=("$e"); fi
  done
}
# untouched <path>: seconds since anything in it was last written (a whole directory, never one file in it).
untouched() { echo $(( NOW - $(find "$1" -printf '%T@\n' | sort -n | tail -1 | cut -d. -f1) )); }
# short_now <path>: its volume is still short (unreadable: not).
short_now() {
  timeout 2s df -B1 --output=avail,size,pcent "$1" | awk -v pct="$SHORT_PCT" -v floor="$FLOOR_BYTES" \
    'NR == 2 { f = $2 / 4; if (f > floor) f = floor; exit !($3 + 0 >= pct || $1 < f) } END { if (NR < 2) exit 1 }'
}
react() {
  local owner d sid f i owners=() live=" " roles=()
  CANDS=() PROBES=()  # what may go, and the path whose use decides it
  for owner in "${SESSION_ROOT:-/nonexistent}"/*/.owner; do ours "$owner" && owners+=("$owner"); done
  judge "${owners[@]}"
  for owner in "${owners[@]}"; do
    d="${owner%/.owner}"
    [ "${VERDICT[$owner]}" = gone ] || live+="${d##*/} "  # alive, or cannot tell: not gone
    on_short "$d" || continue
    split "$d"; roles+=("${ROLES[@]}")  # its role directories: below
    if [ "${VERDICT[$owner]}" = gone ]; then CANDS+=("${REST[@]}") PROBES+=("${REST[@]}"); else retired "$d"; fi
  done
  for d in "${CLI_DIRS[@]}"; do
    on_short "$d" || continue
    while IFS= read -r -d '' f; do
      sid="${f%/tasks/*}"
      case "$live" in *" ${sid##*/} "*) continue ;; esac
      CANDS+=("$f") PROBES+=("$sid")
    done < <(find "$d" -mindepth 4 -maxdepth 4 -path "$d/*/*/tasks/*.output" -type f -mmin +10 -print0)
  done
  judge "${PROBES[@]}" "${roles[@]}"
  for i in "${!CANDS[@]}"; do
    f=${CANDS[i]} d=${PROBES[i]}
    [ "${VERDICT[$d]}" = unused ] && [ -z "${CONTROL[$d]:-}" ] || continue  # control state: its age rule only
    if [ "$DRY_RUN" -eq 1 ]; then echo "short space, dead: $f"; else timeout 5s rm -rf -- "$f" && REMOVED+=("$f"); fi
  done
  # Role directories, live session or not: untouched for 24 h, oldest first, while their volume stays short.
  while read -r d f; do
    [ "$d" -ge 86400 ] && [ "${VERDICT[$f]}" = unused ] || continue
    if [ "$DRY_RUN" -eq 1 ]; then echo "short space, untouched 24h: $f"
    elif short_now "$f"; then timeout 5s rm -rf -- "$f" && REMOVED+=("$f"); fi
  done < <(for f in "${roles[@]}"; do echo "$(untouched "$f") $f"; done | sort -rn)
}

VOLS=$(volumes)
SHORT_DEVS=$(awk '$2 == 1 && $1 != "-" { printf "%s ", $1 }' <<<"$VOLS")
printf -v NOW '%(%s)T' -1
REACTED=$LAST
if [ -n "$SHORT_DEVS" ] && { [ "$PRESSURE" -ne 1 ] || [ $((NOW - LAST)) -ge "$REACT_EVERY" ]; }; then
  react; REACTED=$NOW
fi

if [ "$PRESSURE" -eq 1 ]; then
  # The notice. Its first two lines are the set of short volumes and the time of the last reaction, which the
  # hook keeps; the rest only when the set changed.
  [ "${#REMOVED[@]}" -eq 0 ] || VOLS=$(volumes)
  sig="short:$(awk '$2 == 1 { printf " %s", $6 }' <<<"$VOLS")"
  printf '%s\n%s\n' "$sig" "$REACTED"
  [ "$sig" = "$PREV" ] && exit 0
  for m in ${PREV#short:}; do
    case "$sig " in *" $m "*) ;; *) echo "[space] OK: $m has room again." ;; esac
  done
  [ "${#REMOVED[@]}" -eq 0 ] || echo "[space] removed ${#REMOVED[@]} dead harness entries, among them: ${REMOVED[*]:0:3}"
  [ "$UNSURE" -eq 0 ] || echo "[space] could not judge $UNSURE harness entries (whether their session's process is" \
    "gone or a process uses them: no /proc, or no process id recorded), so they were kept."
  while read -r dev s a z u t; do
    [ "$s" = 1 ] || continue
    echo "[space] SHORT: $t has $(numfmt --to=iec "$a") free of $(numfmt --to=iec "$z") (${u}% used; short at" \
      "${SHORT_PCT}% or under $(numfmt --to=iec $(( z / 4 < FLOOR_BYTES ? z / 4 : FLOOR_BYTES ))) free)."
    dirs=(); for p in "${WATCH[@]}"; do [ -d "$p" ] && [ "$(stat -c %d "$p")" = "$dev" ] && dirs+=("$p"); done
    [ "${#dirs[@]}" -gt 0 ] || dirs=("$t")
    echo "[space] largest on $t (what the harness may not remove):"
    timeout 1s du -xak -d1 "${dirs[@]}" | awk -F'\t' 'NR == FNR { r[$0]; next } !($2 in r)' \
      <(printf '%s\n' "${dirs[@]}") - | sort -rn | head -5 | awk -F'\t' '{ printf "  %8dK  %s\n", $1, $2 }'
  done <<<"$VOLS"
  [ "$sig" = "short:" ] || echo "[space] To free it: delete or move what you no longer need among these; a" \
    "session whose command output is on a full volume needs a restart (resume the same session) once there is room."
  exit 0
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
  -path '/tmp/claude-[0-9]*' -o
  -path '*debug-profile*'
\) -prune )

# ── Run helper for /tmp top-level categories ──────────────────────────
# The caller's predicates go INSIDE the non-prune branch, the action with them:
#   find /tmp -maxdepth 1 "${EXCLUDE_PRUNE[@]}" -o \( <args> -print \)
# Each category prints its candidates first; a real run then removes them.
run_tmp() {
  local desc="$1"; shift
  echo "--- $desc ---"
  if [ "$DRY_RUN" -eq 1 ]; then
    # Every candidate of every tier is listed: no truncation.
    find "${SWEEP_ROOT:-/tmp}" -maxdepth 1 "${EXCLUDE_PRUNE[@]}" -o \( "$@" -print \) 2>/dev/null || true
  else
    # Candidate lists live on /var/tmp, not /tmp: a full /tmp must not stop its own cleanup.
    local tmpfile
    tmpfile=$(mktemp -p /var/tmp tmp-cleanup-cands-XXXXXX 2>/dev/null) || {
      echo "WARN: cannot create candidate temp file under /var/tmp; skipping category"
      return 0
    }
    find "${SWEEP_ROOT:-/tmp}" -maxdepth 1 "${EXCLUDE_PRUNE[@]}" -o \( "$@" -print0 \) 2>/dev/null > "$tmpfile" || true
    tr '\0' '\n' < "$tmpfile" | sed '/^$/d' || true
    xargs -0r rm -rf -- < "$tmpfile" 2>/dev/null || true
    rm -f "$tmpfile" 2>/dev/null || true
  fi
}

# ── Helper for non-/tmp-top-level categories ──────────────────────────
# Used by the claude-<uid> deep query (carve-out) and /var/tmp/codex-outputs.
# Does NOT use EXCLUDE_PRUNE because both targets are INSIDE paths that the
# shared clause prunes at the top level. The action still lives INSIDE the
# find expression (no trailing append).
run_path() {
  local desc="$1"; shift
  local path="$1"; shift
  echo "--- $desc ---"
  if [ "$DRY_RUN" -eq 1 ]; then
    find "$path" "$@" -print 2>/dev/null || true
  else
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
# (`chrome-debug-profile` is kept by EXCLUDE_PRUNE.)
run_tmp "Playwright profiles >1d in /tmp" \
  -mtime +1 \
  \( -name 'ui-specialist-chrome-*' \)

# ── Hook state files (>7 days) — small but accumulate; sessions long dead ──
# The state dir is hooks/lib/harness_state_dir.sh's (STATE_DIR above); without it this category is skipped.
[ -z "$STATE_DIR" ] || SWEEP_ROOT="$STATE_DIR" run_tmp "hook state >7d in $STATE_DIR" \
  -mtime +7 -type f "${HOOK_STATE[@]}"

# ── Dev/test scratch (>3 days) — known transient patterns only ──
# Patterns added 2026-05-19:
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
     -o -name 'ocr_env' \)

# ── CLI task outputs: deep .output sweep (>1 day) ──
# CARVE-OUT: this query does NOT use EXCLUDE_PRUNE — its purpose is to
# descend INTO claude-<uid> (which EXCLUDE_PRUNE protects at the top level of /tmp).
# CLI_DIRS: the CLI's command output directories (above). -mindepth 2 skips the claude-<uid> root
# itself; -type f ensures directories named *.output (if any) cannot match. -mtime +1 is the
# verified-safe threshold (BA+QA observed lsof intersection (open AND >1d) = 0).
for cli_dir in "${CLI_DIRS[@]}"; do
  run_path "CLI task outputs >1d in $cli_dir" "$cli_dir" -mindepth 2 -type f -name '*.output' -mtime +1
done

# ── /var/tmp/codex-outputs (>7 days) — on disk, less urgent but still bounded ──
# Separate path (not /tmp), so EXCLUDE_PRUNE does not apply. Existing sweep,
# preserved per AC7. Its delta IS counted toward `freed_total` below.
run_path "codex-outputs >7d in /var/tmp" /var/tmp/codex-outputs \
  -mindepth 1 -mtime +7

# ── Session roots (hooks/session-scratch-init.sh's .owner), by whole directory, never one file inside one ──
# A role directory untouched for 7 days; of a session whose process is gone, its other entries untouched for
# 3 days, and the root once only its .owner is left. (tmpfiles-claude-scratch.conf leaves session roots to this.)
echo "--- session roots by age in ${SESSION_ROOT:-(none)} ---"
owners=() olds=()
for owner in "${SESSION_ROOT:-/nonexistent}"/*/.owner; do ours "$owner" && owners+=("$owner"); done
judge "${owners[@]}"
for owner in "${owners[@]}"; do
  split "${owner%/.owner}"
  for f in "${ROLES[@]}"; do [ "$(untouched "$f")" -ge 604800 ] && olds+=("$f"); done
  if [ "${VERDICT[$owner]}" = gone ]; then
    for f in "${REST[@]}"; do [ "$(untouched "$f")" -ge 259200 ] && olds+=("$f"); done
    [ $(( ${#ROLES[@]} + ${#REST[@]} )) -eq 0 ] && [ "$(untouched "$owner")" -ge 259200 ] && olds+=("${owner%/.owner}")
  fi
done
judge "${olds[@]}"
for f in "${olds[@]}"; do
  [ "${VERDICT[$f]}" = unused ] || continue
  echo "$f"; [ "$DRY_RUN" -eq 1 ] || timeout 5s rm -rf -- "$f"
done

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
