#!/usr/bin/env bash
# Description: Self-verifying headline-claims gate. Recomputes the wired-hook entry count and
#   lifecycle-event count from settings.json (the single source of truth) and fails if
#   README.md / ARCHITECTURE.md state a different number; then runs BOTH hero-provenance
#   audits in --strict mode so any source-verification downgrade is a hard failure.
# Usage: bash scripts/verify-claims.sh
# Exit codes: 0 = all checks pass, 1 = one or more checks failed (count drift and/or audit
#   violation). Runs identically in CI and locally.
# Root cause (git): headline counts were hand-maintained prose with no cross-check against
#   settings.json, so they silently drifted (40 -> 67); the provenance audit was never run in
#   CI and exited 0 even when source verification was downgraded to warnings.
#
# The enforced numbers are NEVER hardcoded — they are recomputed from settings.json every run,
# so adding/removing a hook (with the docs updated in step) changes the enforced value
# automatically.

set -uo pipefail   # deliberately NOT -e: an explicit accumulator runs every check so ALL drift
                   # is reported at once instead of aborting on the first failure.

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || { echo "ERROR: cannot cd to repo root" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required" >&2; exit 1; }
command -v node    >/dev/null 2>&1 || { echo "ERROR: node (>=18) is required for audit.mjs" >&2; exit 1; }

rc=0
fail() { echo "FAIL: $*"; rc=1; }
pass() { echo "PASS: $*"; }

# ---------------------------------------------------------------------------
# 1. Recompute wired_entries + lifecycle_events from settings.json (schema-validated).
#    settings.json.hooks is an object keyed by lifecycle event; each value is a LIST of
#    matcher-entries; each matcher-entry has a `hooks` array of command objects.
#      wired_entries   = sum(len(entry.hooks)) over every matcher-entry of every event
#      lifecycle_events = number of top-level keys under hooks
# ---------------------------------------------------------------------------
counts="$(python3 - "$ROOT/settings.json" <<'PY'
import json, sys
path = sys.argv[1]
try:
    d = json.load(open(path, encoding="utf8"))
except Exception as e:
    sys.stderr.write(f"settings.json unreadable / invalid JSON: {e}\n"); sys.exit(3)
hooks = d.get("hooks")
if not isinstance(hooks, dict) or not hooks:
    sys.stderr.write("settings.json: 'hooks' is missing or not a non-empty object\n"); sys.exit(3)
entries = 0
for ev, lst in hooks.items():
    if not isinstance(lst, list):
        sys.stderr.write(f"settings.json: hooks[{ev!r}] is not a list of matcher-entries\n"); sys.exit(3)
    for e in lst:
        h = e.get("hooks") if isinstance(e, dict) else None
        if not isinstance(h, list):
            sys.stderr.write(f"settings.json: a matcher-entry under {ev!r} has no 'hooks' array\n"); sys.exit(3)
        entries += len(h)
events = len(hooks)
if entries <= 0:
    sys.stderr.write("settings.json: computed 0 wired entries — refusing (schema anomaly)\n"); sys.exit(3)
print(f"{entries} {events}")
PY
)"
if [ $? -ne 0 ]; then
  fail "count-recompute: settings.json schema/parse error (see message above)"
  WIRED=""; EVENTS=""
else
  WIRED="${counts% *}"; EVENTS="${counts#* }"
  pass "recomputed from settings.json: wired_entries=${WIRED} lifecycle_events=${EVENTS}"
fi

# ---------------------------------------------------------------------------
# 2. Verify the doc claims against the recomputed numbers.
#    Typed, tolerant scan: each number is bound to its metric noun (wired/entries vs events),
#    so different-metric numbers (distinct files, files-on-disk, permissions, slash entry
#    points) are never coerced to the wired-entry count. Anchors are short (not full
#    sentences) so a peer's prose rewording of the surrounding text does not break the check.
#    Every occurrence is compared; a configured doc with zero enforced occurrences fails
#    (fail-closed).
# ---------------------------------------------------------------------------
if [ -n "$WIRED" ]; then
  python3 - "$WIRED" "$EVENTS" "README.md" "ARCHITECTURE.md" <<'PY'
import re, sys, urllib.parse

WIRED = int(sys.argv[1]); EVENTS = int(sys.argv[2]); docs = sys.argv[3:]

# Fenced blocks whose info-string is a diagram/tree carry real claims and are kept; code
# examples (bash/json/...) are dropped so example numbers are never matched.
KEEP_FENCES = {"mermaid", "text"}

def strip_code_fences(text):
    out, in_fence, keep = [], False, True
    open_re = re.compile(r'^\s*```+\s*([A-Za-z0-9_+-]*)')
    close_re = re.compile(r'^\s*```+\s*$')
    for ln in text.split("\n"):
        if not in_fence:
            m = open_re.match(ln)
            if m:
                in_fence, keep = True, (m.group(1) or "").lower() in KEEP_FENCES
                out.append(ln if keep else "")
                continue
            out.append(ln)
        else:
            if close_re.match(ln):
                in_fence = False
                out.append(ln if keep else "")
            else:
                out.append(ln if keep else "")
    return "\n".join(out)

def normalize(text):
    # URL-decode badge text (%20 -> space, %2F -> /) and flatten <br/> so number<->keyword
    # bindings survive HTML/markdown separators. Neither step adds or removes newlines, so
    # 1-based line numbers stay accurate.
    return re.sub(r'<br\s*/?>', ' ', urllib.parse.unquote(text), flags=re.I)

def line_of(text, off):
    return text.count("\n", 0, off) + 1

# WIRED (entry-count) patterns as (regex, exclusion_eligible). EXPLICIT "... entries"
# phrasings ("N wired hook command entries", "N entries", table "entries wired ... **N**")
# are ALWAYS enforced. Only a BARE "N wired" (ambiguous with the distinct-files count) is
# subject to the different-metric left-context exclusion. A distinct-files phrasing
# ("N wired hook files") is never captured — the bare pattern's lookahead rejects it.
WIRED_PATS = [
    (re.compile(r'(\d+)\s+wired\s+(?:hook\s+)?(?:command\s+)?entries\b', re.I), False),
    (re.compile(r'(\d+)\s+(?:hook\s+)?(?:command\s+)?entries\b', re.I), False),
    (re.compile(r'entries\s+wired\b[^\n]*?\*\*(\d+)\*\*', re.I), False),
    (re.compile(r'(\d+)\s+wired\b(?!\s+(?:hook\s+|command\s+)*(?:entries|files))', re.I), True),
]
# EVENT (lifecycle-event) patterns — every one requires explicit lifecycle/hook context so a
# bare "N events" in unrelated prose is never matched (no false-fail). Covers "N lifecycle
# events", the "lifecycle events[-/used] N" table/badge form, and the README badge whose
# event count trails a "lifecycle hooks-... / N events" run.
EVENT_PATS = [
    (re.compile(r'(\d+)\s+lifecycle\s+events\b', re.I), False),
    (re.compile(r'lifecycle\s+events\b[\s\-|:*]*(?:used[\s\-|:*]*)?(\d+)', re.I), False),
    (re.compile(r'lifecycle\s+hooks-[^"\n]*?/\s*(\d+)\s+events\b', re.I), False),
]

def excluded(text, pos):
    # Skip a BARE "N wired" whose immediate left context is an explicit different-metric
    # clause ("... 88 files on disk; 66 wired") — that is the distinct-files count, not the
    # wired-entry count. Explicit "... entries" matches never reach this (excl_eligible=False).
    pre = text[max(0, pos - 24):pos].lower()
    return ('on disk' in pre) or ('on-disk' in pre) or ('distinct' in pre)

def collect(text, path, pats, expected, label):
    found, seen = [], set()
    for pat, excl_eligible in pats:
        for m in pat.finditer(text):
            pos = m.start(1)
            if pos in seen:
                continue
            if excl_eligible and excluded(text, pos):
                continue
            seen.add(pos)
            found.append((int(m.group(1)), line_of(text, pos)))
    ok = True
    if not found:
        print(f"  [{path}] MISSING {label}: no enforced occurrence found (fail-closed)")
        ok = False
    for val, ln in sorted(found, key=lambda x: x[1]):
        if val != expected:
            print(f"  [{path}:{ln}] {label} DRIFT: found {val}, expected {expected}")
            ok = False
        else:
            print(f"  [{path}:{ln}] {label} OK: {val}")
    return ok

overall = True
for path in docs:
    try:
        orig = open(path, encoding="utf8").read()
    except Exception as e:
        print(f"  [{path}] ERROR: cannot read ({e})"); overall = False; continue
    scanned = normalize(strip_code_fences(orig))
    w_ok = collect(scanned, path, WIRED_PATS, WIRED, "wired_entry_count")
    e_ok = collect(scanned, path, EVENT_PATS, EVENTS, "lifecycle_event_count")
    overall = overall and w_ok and e_ok

sys.exit(0 if overall else 1)
PY
  if [ $? -ne 0 ]; then
    fail "doc-claim check: a wired-hook / lifecycle-event claim drifted from settings.json (see above)"
  else
    pass "doc claims in README.md + ARCHITECTURE.md match the recomputed counts"
  fi
fi

# ---------------------------------------------------------------------------
# 3. Run BOTH hero-provenance audits in --strict mode (any provenance downgrade hard-fails).
# ---------------------------------------------------------------------------
run_audit() {
  local manifest="$1" svg="$2"
  if [ ! -f "$manifest" ] || [ ! -f "$svg" ]; then
    fail "audit(strict): missing asset — ${manifest} or ${svg} not found"; return
  fi
  if node tools/demo/audit.mjs "$manifest" "$svg" --strict; then
    pass "audit(strict): ${manifest} <-> ${svg}"
  else
    fail "audit(strict): ${manifest} <-> ${svg}"
  fi
}
run_audit .github/assets/demo-trace.json .github/assets/pipeline-hero.svg
run_audit .github/assets/hook-trace.json .github/assets/hook-hero.svg

# ---------------------------------------------------------------------------
# 4. Recompute the helper-script count from git and verify README + ARCHITECTURE.
#    Definition: tracked files directly under scripts/ (one level deep, top-level only),
#    excluding scripts/INDEX.md and scripts/README.md. NEVER hardcoded — recomputed from
#    git every run, so adding/removing a top-level script (docs updated in step) changes
#    the enforced value automatically, exactly like the wired/lifecycle counts above.
# ---------------------------------------------------------------------------
HELPERS="$(git ls-files scripts/ | grep -E 'scripts/[^/]+$' | grep -vE 'scripts/(INDEX|README)\.md$' | wc -l | tr -d ' ')"
if ! [ "${HELPERS:-0}" -gt 0 ] 2>/dev/null; then
  fail "helper-count recompute: git produced a non-positive count (${HELPERS:-empty}) — refusing (schema anomaly)"
else
  pass "recomputed from git: helper_scripts=${HELPERS}"
  python3 - "$HELPERS" "README.md" "ARCHITECTURE.md" <<'PY'
import re, sys, urllib.parse

EXPECTED = int(sys.argv[1]); docs = sys.argv[2:]

# Helper-count occurrences, each bound to the "helper" keyword or the badge/table label so
# unrelated numbers are never coerced: the "helper scripts-N" shields badge (URL-decoded),
# the "N helper(s)" prose / repo-tree comment, and the "**Helper scripts** ... **N**"
# metrics-table row. Every bound occurrence is compared; a doc with zero occurrences fails
# (fail-closed), matching the wired/lifecycle check's discipline above.
PATS = [
    re.compile(r'helper\s+scripts-(\d+)', re.I),
    re.compile(r'(\d+)\s+helpers?\b', re.I),
    re.compile(r'Helper\s+scripts\*\*[^\n|]*\|[^\n|]*?\*\*(\d+)\*\*', re.I),
]

def line_of(text, off):
    return text.count("\n", 0, off) + 1

overall = True
for path in docs:
    try:
        # URL-decode so the %20 in the shields badge becomes a space (number<->keyword
        # binding survives). unquote adds/removes no newlines, so line numbers stay accurate.
        text = urllib.parse.unquote(open(path, encoding="utf8").read())
    except Exception as e:
        print(f"  [{path}] ERROR: cannot read ({e})"); overall = False; continue
    found, seen = [], set()
    for pat in PATS:
        for m in pat.finditer(text):
            pos = m.start(1)
            if pos in seen:
                continue
            seen.add(pos)
            found.append((int(m.group(1)), line_of(text, pos)))
    if not found:
        print(f"  [{path}] MISSING helper_script_count: no enforced occurrence found (fail-closed)")
        overall = False
    for val, ln in sorted(found, key=lambda x: x[1]):
        if val != EXPECTED:
            print(f"  [{path}:{ln}] helper_script_count DRIFT: found {val}, expected {EXPECTED}")
            overall = False
        else:
            print(f"  [{path}:{ln}] helper_script_count OK: {val}")
sys.exit(0 if overall else 1)
PY
  if [ $? -ne 0 ]; then
    fail "helper-count check: a helper-script claim in README.md / ARCHITECTURE.md drifted from the git-recomputed count (${HELPERS}) (see above)"
  else
    pass "helper-script counts in README.md + ARCHITECTURE.md match the git-recomputed count (${HELPERS})"
  fi
fi

# ---------------------------------------------------------------------------
# Aggregated verdict.
# ---------------------------------------------------------------------------
echo "----------------------------------------------------------------------"
if [ "$rc" -eq 0 ]; then
  echo "verify-claims: ALL CHECKS PASSED (wired_entries=${WIRED} lifecycle_events=${EVENTS})"
else
  echo "verify-claims: FAILURES DETECTED — see FAIL lines above"
fi
exit "$rc"
