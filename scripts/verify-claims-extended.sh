#!/usr/bin/env bash
# Description: Extended headline-claims gate. Binds the slash-command count and the
#   permissions triple in README.md / ARCHITECTURE.md to their source. Each metric is
#   RECOMPUTED from source on every run and compared against every occurrence found in the
#   docs; no expected value is ever hardcoded. A separable check (check 6, the number
#   the run prints and the number --no-event-table skips) binds the per-event
#   breakdown TABLE by set equality plus per-addend comparison, which is the only way to catch
#   compensating errors among addends that sum to a correct aggregate (README at 71f5dfbc
#   claimed PreToolUse=31 and omitted the PostToolUseFailure row; the two errors cancelled and
#   the aggregate check passed).
#   Checks 3 and 5 (hook files on disk, distinct wired hook files) and the --interaction
#   self-test against verify-claims.sh's wired-entry patterns are retired with those counts:
#   the docs no longer carry them.
#
#   ANCHORING: every binding is a property anchor — a metric noun, a recomputed value, or a
#   runnable enumeration. No check anchors on a line number or a file position, because this
#   tree is edited concurrently and any positional anchor rots. Line numbers appear ONLY in
#   output diagnostics, derived via line_of().
#
# Usage: bash scripts/verify-claims-extended.sh [OPTIONS]
#   --readme PATH          README document to scan       (default: README.md)
#   --architecture PATH    ARCHITECTURE document to scan (default: ARCHITECTURE.md)
#   --no-event-table       Skip check 6 (the separable per-event addend check)
#   -h | --help            Show this help
#
#   Source values are ALWAYS recomputed from the CURRENT tree regardless of which documents
#   are passed, so historical document blobs can be scanned as regression fixtures:
#     git show <rev>:README.md > /tmp/f/README.md && bash scripts/verify-claims-extended.sh \
#       --readme /tmp/f/README.md --architecture /tmp/f/ARCHITECTURE.md
#
# Exit codes: 0 = all checks pass, 1 = one or more claims drifted from the recomputed value,
#   2 = usage error or unreadable/invalid source of truth (fail-closed).
#
# Root cause (git): verify-claims.sh never bound these metrics, so false claims survived at
#   HEAD for weeks with CI green: ARCHITECTURE.md at 468e38bc stated permissions 154/81/23
#   (truth 165/96/0) and 19 slash commands (truth 20).
#
# DELIVERY: standalone by design. This script is NOT wired into .github/workflows/baseline.yml,
#   NOT called from scripts/verify-claims.sh, and NOT invoked by any hook. See the integration
#   note at the foot of this file for the exact call site to use when wiring is wanted.

set -uo pipefail   # deliberately NOT -e: an explicit accumulator runs every check so ALL drift
                   # is reported at once instead of aborting on the first failure.

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || { echo "ERROR: cannot cd to repo root" >&2; exit 2; }

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required" >&2; exit 2; }

README_DOC="README.md"
ARCH_DOC="ARCHITECTURE.md"
DO_EVENT_TABLE=1

# --help emits the header STRUCTURALLY: every comment line after the shebang, stopping at the
# first line that is not one. The extent is derived from the block's own shape, so adding or
# removing a header line can neither truncate nor over-read. The previous `sed -n '2,40p'` was
# a positional anchor inside the file whose own ANCHORING paragraph forbids them because they
# rot — and it had already rotted: the header runs to 41, so help truncated mid-sentence.
show_help() { awk 'NR==1{next} /^#/{print; next} {exit}' "$0"; }

# A missing flag VALUE is a usage error, which the header documents as exit 2. `${2:?...}`
# aborted with bash's own status 1 — the code this script reserves for "a claim drifted" — so
# an operator typo was indistinguishable from a documentation drift.
need_value() { [ -n "${2:-}" ] || { echo "ERROR: $1 needs a value (try --help)" >&2; exit 2; }; }

while [ $# -gt 0 ]; do
  case "$1" in
    --readme)        need_value "$1" "${2:-}"; README_DOC="$2"; shift 2 ;;
    --architecture)  need_value "$1" "${2:-}"; ARCH_DOC="$2"; shift 2 ;;
    --no-event-table) DO_EVENT_TABLE=0; shift ;;
    -h|--help)       show_help; exit 0 ;;
    *) echo "ERROR: unknown option '$1' (try --help)" >&2; exit 2 ;;
  esac
done

for f in "$README_DOC" "$ARCH_DOC"; do
  [ -f "$f" ] || { echo "ERROR: document not found: $f" >&2; exit 2; }
done

rc=0
fail() { echo "FAIL: $*"; rc=1; }
pass() { echo "PASS: $*"; }

echo "======================================================================"
echo "verify-claims-extended: scanning"
echo "  README        : $README_DOC"
echo "  ARCHITECTURE  : $ARCH_DOC"
echo "  source of truth: CURRENT tree at $ROOT"
echo "======================================================================"

# ---------------------------------------------------------------------------
# 1. Recompute every metric from source. Never hardcoded.
#      slash_command_count   : commands/*.md excluding INDEX.md / README.md
#      permissions triple    : len of permissions.allow / .deny / .ask in settings.json
#      per-event table       : hook entries and matcher blocks per settings.json event
# ---------------------------------------------------------------------------
TRUTH="$(python3 - "$ROOT" <<'PY'
import json, os, sys
root = sys.argv[1]

# --- slash entry points -----------------------------------------------------
cmd_dir = os.path.join(root, "commands")
slash = [f for f in os.listdir(cmd_dir)
         if f.endswith(".md") and f not in ("INDEX.md", "README.md")] if os.path.isdir(cmd_dir) else []
if not slash:
    sys.stderr.write("commands/ produced 0 slash entry points — refusing (schema anomaly)\n"); sys.exit(3)

# --- settings.json, through the one load of a settings file -------------------
# hooks/lib/claude_home.py load_settings: the object with the shapes its readers rely on (a
# permissions object of string lists, a hooks object of lists), or its reason it is unusable.
sys.path.insert(0, os.path.join(root, "hooks", "lib"))
from claude_home import load_settings
cfg, problem = load_settings(os.path.join(root, "settings.json"))
if cfg is None:
    sys.stderr.write(f"settings.json unusable: {problem or 'absent'}\n"); sys.exit(3)

perms = cfg.get("permissions", {})
# An ABSENT key and a PRESENT-but-empty list both mean zero entries. The truthful claim is the
# number 0, never the word "absent"; presence is reported separately for diagnostics only.
p_allow, p_deny, p_ask = (len(perms.get(k, [])) for k in ("allow", "deny", "ask"))
ask_present = "ask" in perms

# What the counts cannot show is listed for the comparison below to fail on.
anomalies = [] if cfg.get("hooks") else ["settings.json: 'hooks' missing or empty"]
per_event_hooks, per_event_blocks = {}, {}
for ev, lst in cfg.get("hooks", {}).items():
    per_event_blocks[ev] = len(lst)
    n = 0
    for entry in lst:
        h = entry.get("hooks") if isinstance(entry, dict) else None
        if isinstance(h, list):
            n += len(h)
        else:
            anomalies.append(f"settings.json: a matcher-entry under {ev!r} has no 'hooks' array")
    per_event_hooks[ev] = n

print(json.dumps({
    "slash": len(slash),
    "perm_allow": p_allow, "perm_deny": p_deny, "perm_ask": p_ask, "ask_present": ask_present,
    "per_event_hooks": per_event_hooks,
    "per_event_blocks": per_event_blocks,
    "anomalies": anomalies,
}))
PY
)"
if [ $? -ne 0 ]; then
  echo "FAIL: source-recompute failed (see message above) — refusing to scan (fail-closed)" >&2
  exit 2
fi

python3 - "$TRUTH" <<'PY'
import json, sys
t = json.loads(sys.argv[1])
print(f"  recomputed: slash_entry_points      = {t['slash']}   (commands/*.md, excl. INDEX/README)")
print(f"  recomputed: permissions allow/deny/ask = {t['perm_allow']} / {t['perm_deny']} / {t['perm_ask']}"
      f"   ('ask' key present: {t['ask_present']})")
PY
echo "----------------------------------------------------------------------"

# ---------------------------------------------------------------------------
# 2 and 4. Bind every doc occurrence to its metric noun and compare.
# ---------------------------------------------------------------------------
python3 - "$TRUTH" "$README_DOC" "$ARCH_DOC" "$DO_EVENT_TABLE" <<'PY'
import json, re, sys, urllib.parse

T          = json.loads(sys.argv[1])
README_DOC, ARCH_DOC = sys.argv[2], sys.argv[3]
DO_TABLE   = sys.argv[4] == "1"

# Fence handling: diagram/tree fences carry real claims and are kept; bash/json example fences are dropped so example numbers never match.
KEEP_FENCES = {"mermaid", "text"}

def strip_code_fences(text):
    out, in_fence, keep = [], False, True
    open_re  = re.compile(r'^\s*```+\s*([A-Za-z0-9_+-]*)')
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
    return "\n".join(out)

def normalize(text):
    # URL-decode badge text and flatten <br/> so number<->keyword bindings survive HTML and
    # markdown separators. Neither step adds or removes newlines, so line numbers stay accurate.
    return re.sub(r'<br\s*/?>', ' ', urllib.parse.unquote(text), flags=re.I)

def line_of(text, off):
    return text.count("\n", 0, off) + 1

# --- metric patterns. Each is anchored on a METRIC NOUN, never a position. -----------------
# Group 1 is the number under test in every pattern.
SLASH_PATS = [
    re.compile(r'(\d+)\s+slash[\s\-]+command', re.I),          # "20 slash commands", "20 slash-command workflows"
    re.compile(r'(\d+)\s+entry\s+points?\b',   re.I),          # mermaid "Slash commands / 20 entry points"
    re.compile(r'command\s+surface[^\n]{0,20}?(\d+)\s+slash', re.I),
]
PERM_PAT = re.compile(
    r'permissions\.?`?\s*(?:\.|/)?\s*`?allow[^\n|]*\|[^\n|]*?(\d+)\s*/\s*(\d+)\s*/\s*(\d+)', re.I)

# Which doc is REQUIRED to carry which metric. This declares WHERE claims live (fail-closed on
# a doc that should carry the claim but has none); it declares no VALUE.
REQUIRED = {
    "slash_command_count":      {README_DOC, ARCH_DOC},
    "permissions_triple":       {ARCH_DOC},
}

overall = True
docs = {}
for path in (README_DOC, ARCH_DOC):
    try:
        raw = open(path, encoding="utf8").read()
    except Exception as e:
        print(f"  [{path}] ERROR: cannot read ({e})"); overall = False; continue
    docs[path] = normalize(strip_code_fences(raw))

def check_scalar(label, pats, expected):
    """Compare every bound occurrence of one metric against the recomputed value."""
    global overall
    any_found = False
    for path, text in docs.items():
        found, seen = [], set()
        for pat in pats:
            for m in pat.finditer(text):
                pos = m.start(1)
                if pos in seen:
                    continue
                seen.add(pos)
                found.append((int(m.group(1)), line_of(text, pos), pos))
        if found:
            any_found = True
        if not found and path in REQUIRED.get(label, set()):
            print(f"  [{path}] MISSING {label}: no enforced occurrence found (fail-closed)")
            overall = False
        for val, ln, _ in sorted(found, key=lambda x: x[1]):
            if val != expected:
                print(f"  [{path}:{ln}] {label} DRIFT: found {val}, expected {expected}")
                overall = False
            else:
                print(f"  [{path}:{ln}] {label} OK: {val}")
    if not any_found:
        print(f"  {label}: no occurrence in any scanned document (fail-closed)")
        overall = False

for anomaly in T["anomalies"]:
    print(f"  {anomaly}: the per-event counts cannot show it (fail-closed)")
    overall = False

print("--- check 2: slash entry points ---")
check_scalar("slash_command_count", SLASH_PATS, T["slash"])

print("--- check 4: permissions triple (allow / deny / ask) ---")
exp_triple = (T["perm_allow"], T["perm_deny"], T["perm_ask"])
found_any_perm = False
for path, text in docs.items():
    found = False
    for m in PERM_PAT.finditer(text):
        found = found_any_perm = True
        got = tuple(int(m.group(i)) for i in (1, 2, 3))
        ln = line_of(text, m.start(1))
        if got != exp_triple:
            bad = [n for n, g, e in zip(("allow", "deny", "ask"), got, exp_triple) if g != e]
            print(f"  [{path}:{ln}] permissions_triple DRIFT: found "
                  f"{got[0]}/{got[1]}/{got[2]}, expected {exp_triple[0]}/{exp_triple[1]}/{exp_triple[2]}"
                  f"  (wrong: {', '.join(bad)})")
            overall = False
        else:
            print(f"  [{path}:{ln}] permissions_triple OK: {got[0]}/{got[1]}/{got[2]}")
    if not found and path in REQUIRED["permissions_triple"]:
        print(f"  [{path}] MISSING permissions_triple: no enforced occurrence found (fail-closed)")
        overall = False
if not found_any_perm:
    print("  permissions_triple: no occurrence in any scanned document (fail-closed)")
    overall = False

# ---------------------------------------------------------------------------
# Check 6 (SEPARABLE): per-event breakdown table — set equality + per-addend comparison.
#   An aggregate-only check cannot detect compensating errors among its addends, and a
#   "cover every digit-bearing line" criterion cannot catch a MISSING row: an absent row has
#   no digits and no position. Only set equality against settings.json's event keys does.
# ---------------------------------------------------------------------------
if DO_TABLE:
    print("--- check 6 (separable): per-event breakdown table ---")
    EVENTS       = T["per_event_hooks"]
    BLOCKS       = T["per_event_blocks"]
    known        = set(EVENTS)
    row_re       = re.compile(r'^\s*\|([^|\n]+)\|([^|\n]+)\|([^|\n]*)\|', re.M)
    for path, text in docs.items():
        seen = {}
        for m in row_re.finditer(text):
            name = m.group(1).strip().strip('`*_ ')
            if name not in known:
                continue
            c2, c3 = m.group(2).strip().strip('`*_ '), m.group(3).strip().strip('`*_ ')
            if not c2.isdigit():
                continue
            # 3-column numeric shape = (matcher blocks, hook entries); otherwise col2 = entries.
            if c3.isdigit():
                seen[name] = {"entries": int(c3), "blocks": int(c2), "line": line_of(text, m.start(1))}
            else:
                seen[name] = {"entries": int(c2), "blocks": None, "line": line_of(text, m.start(1))}
        if not seen:
            print(f"  [{path}] MISSING per_event_table: no event rows found (fail-closed)")
            overall = False
            continue
        # Set equality FIRST — this is what catches a dropped row.
        missing = known - set(seen)
        extra   = set(seen) - known
        if missing:
            for ev in sorted(missing):
                print(f"  [{path}] per_event_table MISSING ROW: '{ev}' is wired in settings.json "
                      f"({EVENTS[ev]} entries) but has no row in the table")
            overall = False
        if extra:
            for ev in sorted(extra):
                print(f"  [{path}:{seen[ev]['line']}] per_event_table EXTRA ROW: '{ev}' is not a "
                      f"lifecycle event in settings.json")
            overall = False
        if not missing and not extra:
            print(f"  [{path}] per_event_table row set == settings.json event set "
                  f"({len(known)} events)")
        # Then per-addend values.
        for ev in sorted(seen, key=lambda e: seen[e]["line"]):
            if ev not in EVENTS:
                continue
            r = seen[ev]
            if r["entries"] != EVENTS[ev]:
                print(f"  [{path}:{r['line']}] per_event_table DRIFT: '{ev}' hook entries "
                      f"found {r['entries']}, expected {EVENTS[ev]}")
                overall = False
            else:
                print(f"  [{path}:{r['line']}] per_event_table OK: {ev} entries = {r['entries']}")
            if r["blocks"] is not None:
                if r["blocks"] != BLOCKS[ev]:
                    print(f"  [{path}:{r['line']}] per_event_table DRIFT: '{ev}' matcher blocks "
                          f"found {r['blocks']}, expected {BLOCKS[ev]}")
                    overall = False
                else:
                    print(f"  [{path}:{r['line']}] per_event_table OK: {ev} matcher blocks = {r['blocks']}")
        # Aggregate cross-check: proves the sum can be right while addends are wrong.
        tot_doc, tot_true = sum(v["entries"] for v in seen.values()), sum(EVENTS.values())
        note = "" if missing or extra else "  (complete row set)"
        print(f"  [{path}] per_event_table aggregate: doc rows sum to {tot_doc}, "
              f"settings.json total {tot_true}{note}")

sys.exit(0 if overall else 1)
PY
if [ $? -ne 0 ]; then
  fail "extended-claim check: a documented count drifted from the recomputed source value (see above)"
else
  pass "all extended claims match the recomputed source values"
fi

echo "----------------------------------------------------------------------"
if [ "$rc" -eq 0 ]; then
  echo "verify-claims-extended: ALL CHECKS PASSED"
else
  echo "verify-claims-extended: FAILURES DETECTED — see FAIL lines above"
fi
exit "$rc"

# ---------------------------------------------------------------------------
# INTEGRATION NOTE (deliberately NOT wired — see DELIVERY in the header).
#
# When this is to become blocking, add it to scripts/verify-claims.sh as its OWN numbered step
# after step 3c (the corpus check; steps 1, 2, 4 and 5 are retired), using the same
# accumulator so its failures aggregate rather than abort:
#
#     # 3d. Extended headline claims (slash commands / permissions / per-event table).
#     if bash scripts/verify-claims-extended.sh; then
#       pass "extended-claims: slash, permissions, per-event counts match source"
#     else
#       fail "extended-claims: see the FAIL lines above"
#     fi
#
# Join the EXISTING accumulator (rc/fail/pass) rather than running as a separate CI step: the
# accumulate-then-report contract means one invocation reports every drift at once, and a
# separate .github/workflows/baseline.yml step would report only the first failing gate.
# No baseline.yml edit is then needed — baseline.yml already invokes verify-claims.sh.
#
# Add --no-event-table to that call site if the separable check 6 is unwanted.
# ---------------------------------------------------------------------------
