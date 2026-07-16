#!/usr/bin/env bash
# Description: Public/private boundary gate. Recomputes the top-level tracked-path set from
#   git and fails if PUBLIC-CORE.md does not classify every path (a new file silently
#   escaping classification), if any class label is invalid, or if a known author-environment
#   residue marker leaks into a public-core-classified file un-parameterized. Companion to
#   PUBLIC-CORE.md (the ledger) and docs/reference/roadmap-decomposition-productization.md §4.
# Usage: bash scripts/check-public-core.sh
# Exit codes: 0 = boundary clean + complete, 1 = one or more checks failed (unclassified
#   path, invalid class, and/or residue leak). Advisory deferred-leak counts never affect rc.
# Root cause (design): the public-core surface was described in prose (roadmap §4) with no
#   machine check, so a new top-level file could escape classification and author-specific
#   literals could re-enter the shippable core unnoticed. This gate recomputes both from the
#   tree every run — the tracked-path list is derived from git, never hardcoded.
#
# Style mirrors scripts/verify-claims.sh: pure bash (+awk/git/grep), self-contained,
# recompute-don't-hardcode, and an explicit accumulator so ALL problems are reported at once.

set -uo pipefail   # deliberately NOT -e: run every check, aggregate, report all drift.

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || { echo "ERROR: cannot cd to repo root" >&2; exit 1; }

MANIFEST="PUBLIC-CORE.md"
SELF="scripts/check-public-core.sh"   # excluded from the residue scan: it enumerates the
                                       # markers by necessity (as does the manifest).

command -v git  >/dev/null 2>&1 || { echo "ERROR: git is required"  >&2; exit 1; }
command -v awk  >/dev/null 2>&1 || { echo "ERROR: awk is required"  >&2; exit 1; }

rc=0
fail() { echo "FAIL: $*"; rc=1; }
pass() { echo "PASS: $*"; }

if [ ! -f "$MANIFEST" ]; then
  echo "FAIL: boundary manifest not found: $MANIFEST" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 0. Parse the sentinel-delimited ledger region -> "path<TAB>class" pairs.
#    Row shape: | `path` | `class` | rationale |  (path = 1st back-ticked token,
#    class = 2nd). Trailing slash on directory paths is normalized off so the tokens
#    compare 1:1 against git's first-path-segment set.
# ---------------------------------------------------------------------------
PAIRS="$(awk '
  /<!-- BEGIN:public-core-manifest -->/ { inblk=1; next }
  /<!-- END:public-core-manifest -->/   { inblk=0 }
  inblk && /^\|/ {
    n = split($0, a, "`")
    if (n >= 4) {
      p = a[2]; c = a[4]
      sub(/\/+$/, "", p)                 # strip trailing slash(es) from dir paths
      if (p != "" && c != "") print p "\t" c
    }
  }
' "$MANIFEST")"

if [ -z "$PAIRS" ]; then
  fail "manifest-parse: no classification rows found between the BEGIN/END sentinels in $MANIFEST"
  echo "----------------------------------------------------------------------"
  echo "check-public-core: FAILURES DETECTED — see FAIL lines above"
  exit 1
fi

CLASSIFIED_PATHS="$(printf '%s\n' "$PAIRS" | cut -f1 | sort -u)"

# ---------------------------------------------------------------------------
# 1. Class-label validity — every class must be one of the three allowed labels.
# ---------------------------------------------------------------------------
BAD_CLASSES="$(printf '%s\n' "$PAIRS" \
  | awk -F'\t' '$2!="public-core" && $2!="private-lab" && $2!="shared/infra" {print $1" -> "$2}')"
if [ -n "$BAD_CLASSES" ]; then
  fail "invalid class label(s) in $MANIFEST (allowed: public-core | private-lab | shared/infra):"
  printf '%s\n' "$BAD_CLASSES" | sed 's/^/    /'
else
  pass "all ledger class labels are valid"
fi

# ---------------------------------------------------------------------------
# 2. Completeness — every git-tracked top-level path must be classified.
#    Top-level set = first path segment of every tracked file, unique.
# ---------------------------------------------------------------------------
TOPLEVEL="$(git ls-files | sed 's#/.*##' | sort -u)"

UNCLASSIFIED=""
while IFS= read -r p; do
  [ -z "$p" ] && continue
  if ! printf '%s\n' "$CLASSIFIED_PATHS" | grep -qxF "$p"; then
    UNCLASSIFIED="${UNCLASSIFIED}${p}"$'\n'
  fi
done <<< "$TOPLEVEL"

if [ -n "$UNCLASSIFIED" ]; then
  fail "unclassified top-level tracked path(s) — add a row to $MANIFEST for each:"
  printf '%s' "$UNCLASSIFIED" | sed '/^$/d;s/^/    /'
else
  pass "every top-level tracked path is classified in $MANIFEST"
fi

# Advisory (non-gating): ledger rows that no longer correspond to a tracked top-level path
# (e.g. a not-yet-committed new file, or a stale entry). Does NOT affect rc.
STALE=""
while IFS= read -r p; do
  [ -z "$p" ] && continue
  if ! printf '%s\n' "$TOPLEVEL" | grep -qxF "$p"; then
    STALE="${STALE}${p}"$'\n'
  fi
done <<< "$CLASSIFIED_PATHS"
if [ -n "$STALE" ]; then
  echo "INFO: ledger entr(y/ies) not currently a tracked top-level path (new/untracked or stale):"
  printf '%s' "$STALE" | sed '/^$/d;s/^/    /'
fi

# ---------------------------------------------------------------------------
# 3. Residue scan over the public-core-classified file set.
#    Hard markers  : author-environment identifiers that must NEVER appear in public-core;
#                    scanned across the WHOLE public-core set (test trees included).
#    Param markers : residue allowed ONLY as an env `:-` default or in a comment; any other
#                    (un-parameterized) use is a leak. Scanned across the public-core set
#                    MINUS test trees — a fixture string that names a guarded unit is test
#                    data, not shippable-harness residue (mirrors the ledger already
#                    classifying top-level `tests/` as shared/infra).
#    The protected daemon prefix `happy-daemon` is now a PARAM marker (env-overridable via
#    CLAUDE_PROTECTED_DAEMON_PREFIX; the default reproduces today's behavior) — see
#    PUBLIC-CORE.md §3. It was previously an un-scanned deliberately-literal exception.
# ---------------------------------------------------------------------------
HARD_MARKERS=(
  'git@github.com:Yugoge'      # maintainer git remote
  '/root/.claude.bak'          # maintainer rsync mirror
  '/root/sync-backup.sh'       # maintainer sync cron
)
PARAM_MARKERS=(
  'happy-web-dev'                    # CLAUDE_DEV_CONTAINERS default
  '/root/bin/claude-allow-restart'  # CLAUDE_DAEMON_RESTART_GRANT_HELPER default
  'happy-daemon'                     # CLAUDE_PROTECTED_DAEMON_PREFIX default
)

# public-core pathspecs, excluding this script (it names the markers by necessity).
PC_PATHSPECS=()
while IFS= read -r p; do
  [ -z "$p" ] && continue
  PC_PATHSPECS+=("$p")
done < <(printf '%s\n' "$PAIRS" | awk -F'\t' '$2=="public-core"{print $1}' | sort -u)
PC_PATHSPECS+=(":(exclude)$SELF")

# Param markers are productization defaults expected inside shippable code; a test fixture
# that names a guarded unit (e.g. hooks/tests/*) is test data, not residue. Scan param
# markers over the public-core set MINUS any test tree. Hard markers keep the full set.
PARAM_PATHSPECS=("${PC_PATHSPECS[@]}" ":(exclude)*/tests/*")

# A public-core match line is an allowed (parameterized) use of marker M when the line is a
# comment (trimmed starts with #) OR it uses M as an env default (":-M", ":-\"M", ":-'M").
param_line_ok() {
  local content="$1" marker="$2" trimmed
  trimmed="${content#"${content%%[![:space:]]*}"}"
  [[ "$trimmed" == \#* ]] && return 0
  [[ "$content" == *":-$marker"* ]] && return 0
  [[ "$content" == *":-\"$marker"* ]] && return 0
  [[ "$content" == *":-'$marker"* ]] && return 0
  return 1
}

leaks=0

for m in "${HARD_MARKERS[@]}"; do
  while IFS= read -r hit; do
    [ -z "$hit" ] && continue
    fail "hard residue marker in public-core: '$m'  ->  $hit"
    leaks=$((leaks + 1))
  done < <(git grep -nF -- "$m" -- "${PC_PATHSPECS[@]}" 2>/dev/null)
done

for m in "${PARAM_MARKERS[@]}"; do
  while IFS= read -r hit; do
    [ -z "$hit" ] && continue
    file="${hit%%:*}"; rest="${hit#*:}"; lineno="${rest%%:*}"; content="${rest#*:}"
    if ! param_line_ok "$content" "$m"; then
      fail "un-parameterized residue marker in public-core: '$m'  ->  ${file}:${lineno}: ${content}"
      leaks=$((leaks + 1))
    fi
  done < <(git grep -nF -- "$m" -- "${PC_PATHSPECS[@]}" 2>/dev/null)
done

if [ "$leaks" -eq 0 ]; then
  pass "no author-environment residue leaked into the public-core set"
fi

# ---------------------------------------------------------------------------
# 4. Advisory (non-gating): deferred broad path leaks tracked by roadmap phases P1/P2.
# ---------------------------------------------------------------------------
WS_MARKER='/dev/shm/dev-workspace/dot-claude'
ws_count="$(git grep -lF -- "$WS_MARKER" -- "${PC_PATHSPECS[@]}" 2>/dev/null | wc -l | tr -d ' ')"
if [ "${ws_count:-0}" -gt 0 ]; then
  echo "ADVISORY: $ws_count public-core file(s) still reference the maintainer workspace path"
  echo "          ('$WS_MARKER') — deferred to roadmap §4.3 phases P1/P2; not gated here."
fi

# ---------------------------------------------------------------------------
# Aggregated verdict.
# ---------------------------------------------------------------------------
echo "----------------------------------------------------------------------"
if [ "$rc" -eq 0 ]; then
  echo "check-public-core: BOUNDARY CLEAN + COMPLETE (all top-level paths classified, no residue leaks)"
else
  echo "check-public-core: FAILURES DETECTED — see FAIL lines above"
fi
exit "$rc"
