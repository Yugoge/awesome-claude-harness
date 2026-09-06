#!/usr/bin/env bash
# Description: Extended headline-claims gate. Closes the four documented coverage gaps in
#   scripts/verify-claims.sh step 2, whose own comment names the metrics it deliberately does
#   NOT bind: "distinct files, files-on-disk, permissions, slash entry points". Each metric is
#   RECOMPUTED from source on every run and compared against every occurrence found in the
#   docs; no expected value is ever hardcoded. A sixth, separable check (check 6, the number
#   the run prints and the number --no-event-table skips) binds the per-event
#   breakdown TABLE by set equality plus per-addend comparison, which is the only way to catch
#   compensating errors among addends that sum to a correct aggregate (README at 71f5dfbc
#   claimed PreToolUse=31 and omitted the PostToolUseFailure row; the two errors cancelled and
#   the aggregate check passed).
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
#   --interaction          Also run the binding-disjointness self-test against the
#                          wired_entry_count patterns in scripts/verify-claims.sh
#   --upstream PATH        File the --interaction self-test READS that model out of
#                          (default: scripts/verify-claims.sh). Same fixture rationale as
#                          --readme/--architecture: it makes the divergence protection
#                          exercisable against a perturbed copy without editing upstream.
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
# Root cause (git): verify-claims.sh binds numbers to metric nouns for exactly three metrics
#   (wired_entry_count, lifecycle_event_count, helper_script_count). Numbers carrying any other
#   metric noun have no patterns at all, so three false claims survived at HEAD for weeks with
#   CI green: ARCHITECTURE.md at 468e38bc stated permissions 154/81/23 (truth 165/96/0), hook
#   files on disk 93 (truth 94), and 19 slash commands (truth 20).
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
VC_UPSTREAM="scripts/verify-claims.sh"
DO_EVENT_TABLE=1
DO_INTERACTION=0

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
    --upstream)      need_value "$1" "${2:-}"; VC_UPSTREAM="$2"; shift 2 ;;
    --no-event-table) DO_EVENT_TABLE=0; shift ;;
    --interaction)   DO_INTERACTION=1; shift ;;
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
# 1. Recompute all four metrics from source. Never hardcoded.
#      slash_command_count   : commands/*.md excluding INDEX.md / README.md
#      hook_files_on_disk    : hooks/ top level, *.py + *.sh, excluding *.bak
#      permissions triple    : len of permissions.allow / .deny / .ask in settings.json
#      distinct wired        : unique hook-script basenames across every wired entry, split
#                              into those resolving under hooks/ and the total path count
# ---------------------------------------------------------------------------
TRUTH="$(python3 - "$ROOT" <<'PY'
import json, os, re, sys
root = sys.argv[1]

# --- slash entry points -----------------------------------------------------
cmd_dir = os.path.join(root, "commands")
slash = [f for f in os.listdir(cmd_dir)
         if f.endswith(".md") and f not in ("INDEX.md", "README.md")] if os.path.isdir(cmd_dir) else []
if not slash:
    sys.stderr.write("commands/ produced 0 slash entry points — refusing (schema anomaly)\n"); sys.exit(3)

# --- hook files on disk -----------------------------------------------------
hook_dir = os.path.join(root, "hooks")
on_disk = [f for f in os.listdir(hook_dir)
           if os.path.isfile(os.path.join(hook_dir, f))
           and (f.endswith(".py") or f.endswith(".sh"))
           and not f.endswith(".bak")] if os.path.isdir(hook_dir) else []
if not on_disk:
    sys.stderr.write("hooks/ produced 0 files on disk — refusing (schema anomaly)\n"); sys.exit(3)

# --- settings.json ----------------------------------------------------------
try:
    cfg = json.load(open(os.path.join(root, "settings.json"), encoding="utf8"))
except Exception as e:
    sys.stderr.write(f"settings.json unreadable / invalid JSON: {e}\n"); sys.exit(3)

perms = cfg.get("permissions")
if not isinstance(perms, dict):
    sys.stderr.write("settings.json: 'permissions' missing or not an object\n"); sys.exit(3)
# An ABSENT key and a PRESENT-but-empty list both mean zero entries. The truthful claim is the
# number 0, never the word "absent"; presence is reported separately for diagnostics only.
p_allow, p_deny, p_ask = (len(perms.get(k) or []) for k in ("allow", "deny", "ask"))
ask_present = "ask" in perms

hooks = cfg.get("hooks")
if not isinstance(hooks, dict) or not hooks:
    sys.stderr.write("settings.json: 'hooks' missing or not a non-empty object\n"); sys.exit(3)

names, per_event_hooks, per_event_blocks = set(), {}, {}
for ev, lst in hooks.items():
    if not isinstance(lst, list):
        sys.stderr.write(f"settings.json: hooks[{ev!r}] is not a list\n"); sys.exit(3)
    per_event_blocks[ev] = len(lst)
    n = 0
    for entry in lst:
        h = entry.get("hooks") if isinstance(entry, dict) else None
        if not isinstance(h, list):
            sys.stderr.write(f"settings.json: a matcher-entry under {ev!r} has no 'hooks' array\n"); sys.exit(3)
        n += len(h)
        for cmd in h:
            m = re.findall(r'([^\s"\']+\.(?:py|sh))', cmd.get("command", ""))
            if m:
                names.add(m[-1].split("/")[-1])
    per_event_hooks[ev] = n

under_hooks = sorted(n for n in names if os.path.exists(os.path.join(hook_dir, n)))
outside     = sorted(n for n in names if not os.path.exists(os.path.join(hook_dir, n)))
if not names:
    sys.stderr.write("settings.json: 0 distinct wired hook files — refusing (schema anomaly)\n"); sys.exit(3)

print(json.dumps({
    "slash": len(slash),
    "on_disk": len(on_disk),
    "perm_allow": p_allow, "perm_deny": p_deny, "perm_ask": p_ask, "ask_present": ask_present,
    "wired_distinct_total": len(names),
    "wired_distinct_under_hooks": len(under_hooks),
    "wired_outside_hooks": outside,
    "per_event_hooks": per_event_hooks,
    "per_event_blocks": per_event_blocks,
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
print(f"  recomputed: hook_files_on_disk      = {t['on_disk']}   (hooks/ top level, *.py+*.sh, excl. .bak)")
print(f"  recomputed: permissions allow/deny/ask = {t['perm_allow']} / {t['perm_deny']} / {t['perm_ask']}"
      f"   ('ask' key present: {t['ask_present']})")
print(f"  recomputed: distinct wired hook files  = {t['wired_distinct_under_hooks']} under hooks/ "
      f"(+{len(t['wired_outside_hooks'])} = {t['wired_distinct_total']} distinct wired paths; "
      f"outside hooks/: {', '.join(t['wired_outside_hooks']) or 'none'})")
PY
echo "----------------------------------------------------------------------"

# ---------------------------------------------------------------------------
# 2-5. Bind every doc occurrence to its metric noun and compare.
# ---------------------------------------------------------------------------
python3 - "$TRUTH" "$README_DOC" "$ARCH_DOC" "$DO_EVENT_TABLE" "$DO_INTERACTION" "$VC_UPSTREAM" <<'PY'
import json, re, sys, urllib.parse

T          = json.loads(sys.argv[1])
README_DOC, ARCH_DOC = sys.argv[2], sys.argv[3]
DO_TABLE   = sys.argv[4] == "1"
DO_INTER   = sys.argv[5] == "1"
VC_UPSTREAM = sys.argv[6]

# Fence handling mirrors scripts/verify-claims.sh exactly: diagram/tree fences carry real
# claims and are kept; bash/json example fences are dropped so example numbers never match.
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
ONDISK_PATS = [
    re.compile(r'(\d+)\s+(?:hook\s+)?files?\s+on[\s\-]disk', re.I),          # "(94 files on disk; 69 wired)"
    re.compile(r'on\s+disk\s*\(\s*\*{0,2}(\d+)\*{0,2}\s*\)',  re.I),          # "exist on disk (**94**)"
    re.compile(r'Hook\s+files\s+present\s+on\s+disk[^\n|]*\|[^\n|]*?\*\*(\d+)\*\*', re.I),  # metrics-table row
]
# Distinct wired: the count of unique hooks/ files (69) and the total distinct wired paths (70).
DISTINCT_HOOKS_PATS = [                                        # -> wired_distinct_under_hooks
    re.compile(r'Distinct\s+hook\s+files\s+referenced[^\n|]*\|[^\n|]*?\*\*(\d+)\*\*', re.I),
    re.compile(r'\*{0,2}(\d+)\*{0,2}\s+hooks\s+files\b', re.I),               # "(**69** hooks files / 70 ...)"
    re.compile(r'(\d+)\s+distinct\s+`?hooks/`?\s+files', re.I),               # "69 distinct `hooks/` files"
    # The BARE "N wired" that verify-claims.sh deliberately EXCLUDES via its different-metric
    # left-context rule ("... 94 files on disk; 69 wired"). That exclusion left the number
    # bound to nothing at all; this pattern is what claims it. Required left context keeps
    # the two checkers from fighting: verify-claims.sh owns every OTHER "N wired".
    re.compile(r'(?:on[\s\-]disk|distinct)[^\n]{0,24}?(\d+)\s+wired\b(?!\s+(?:hook\s+|command\s+)*entries)', re.I),
]
# The "(+1 = **70** paths)" form carries TWO recomputed facts: the DELTA (wired executables that
# do not resolve under hooks/) and the total. The delta was written as the literal "1", encoding
# today's fact that exactly one such executable exists. That is fail-OPEN: a second one makes the
# document read "(+2 = **71** paths)", this pattern stops matching, the sibling patterns still
# match elsewhere so check_scalar's fail-closed MISSING branch never fires, and the claim drops
# coverage in silence. ONE shape, TWO bindings, neither hardcoded: the total pattern accepts ANY
# delta so it can never stop matching, and the delta itself is compared against the recomputed
# value by PATHS_DELTA_PAT below.
_PATHS_SUM      = r'\+\s*{d}\s*=\s*\*{{0,2}}{t}\*{{0,2}}\s*paths'
PATHS_DELTA_PAT = re.compile(_PATHS_SUM.format(d=r'(\d+)', t=r'\d+'), re.I)
DISTINCT_PATHS_PATS = [                                        # -> wired_distinct_total
    re.compile(_PATHS_SUM.format(d=r'\d+', t=r'(\d+)'), re.I),                # "(+1 = **70** paths)"
    re.compile(r'/\s*(\d+)\s+executable\s+entries', re.I),                    # "/ 70 executable entries"
    re.compile(r'(\d+)\s+distinct\s+wired\s+executable\s+paths', re.I),
]
PERM_PAT = re.compile(
    r'permissions\.?`?\s*(?:\.|/)?\s*`?allow[^\n|]*\|[^\n|]*?(\d+)\s*/\s*(\d+)\s*/\s*(\d+)', re.I)

# Which doc is REQUIRED to carry which metric. This declares WHERE claims live (fail-closed on
# a doc that should carry the claim but has none); it declares no VALUE.
REQUIRED = {
    "slash_command_count":      {README_DOC, ARCH_DOC},
    "hook_files_on_disk":       {ARCH_DOC},
    "permissions_triple":       {ARCH_DOC},
    "distinct_wired_hooks":     {ARCH_DOC},
    "distinct_wired_paths":     {ARCH_DOC},
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
    hits = {}
    for path, text in docs.items():
        found, seen = [], set()
        for pat in pats:
            for m in pat.finditer(text):
                pos = m.start(1)
                if pos in seen:
                    continue
                seen.add(pos)
                found.append((int(m.group(1)), line_of(text, pos), pos))
        hits[path] = found
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
    return hits

print("--- check 2: slash entry points ---")
check_scalar("slash_command_count", SLASH_PATS, T["slash"])

print("--- check 3: hook files on disk ---")
check_scalar("hook_files_on_disk", ONDISK_PATS, T["on_disk"])

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

print("--- check 5: distinct wired hook files ---")
dh = check_scalar("distinct_wired_hooks", DISTINCT_HOOKS_PATS, T["wired_distinct_under_hooks"])
check_scalar("distinct_wired_paths", DISTINCT_PATHS_PATS, T["wired_distinct_total"])

# The delta addend is a claim in its own right. Checking it catches a wrong delta that still
# sums to a right total — the compensating-error class check 6 exists for. Absence is not a
# failure: the phrasing is optional, and the total stays bound by REQUIRED + its two siblings.
exp_delta = T["wired_distinct_total"] - T["wired_distinct_under_hooks"]
for path, text in docs.items():
    for m in PATHS_DELTA_PAT.finditer(text):
        got, ln = int(m.group(1)), line_of(text, m.start(1))
        if got != exp_delta:
            print(f"  [{path}:{ln}] distinct_wired_paths_delta DRIFT: found +{got}, expected +{exp_delta}")
            overall = False
        else:
            print(f"  [{path}:{ln}] distinct_wired_paths_delta OK: +{got}")

# ---------------------------------------------------------------------------
# Interaction self-test: prove the new distinct-wired binding and verify-claims.sh's
# different-metric exclusion do not fight, in EITHER direction.
# ---------------------------------------------------------------------------
if DO_INTER:
    print("--- interaction self-test vs scripts/verify-claims.sh wired_entry_count ---")
    # DELEGATION, NOT DUPLICATION — the rule verify-claims.sh states for itself at its step 6:
    # "Adding a second enumerator here would have recreated it inside the mechanism meant to
    # prevent it." The upstream model is therefore NOT copied here. WIRED_PATS and excluded()
    # are READ OUT OF the upstream file at run time and evaluated, so an edit upstream is
    # tested on the next run instead of being silently asserted against a stale hand-copy —
    # assurance that has quietly stopped testing anything is worse than none. Extraction is
    # anchored on the SYMBOL NAMES (a property anchor, per ANCHORING above), never on a line
    # range, and fails CLOSED if either symbol is missing, moved, renamed, or unevaluable.
    def take_block(src, header_re):
        """The line matching header_re plus every following blank/indented line, plus a
        closing bracket in column 0 if the header opened one. Contains no position."""
        lines = src.split("\n")
        for i, ln in enumerate(lines):
            if header_re.match(ln):
                out = [ln]
                for nxt in lines[i + 1:]:
                    if nxt.strip() == "" or nxt[:1] in (" ", "\t"):
                        out.append(nxt)
                    elif nxt.startswith("]"):
                        out.append(nxt)
                        break
                    else:
                        break
                return "\n".join(out)
        return None

    VC_WIRED, vc_excluded = None, None
    try:
        vc_src = open(VC_UPSTREAM, encoding="utf8").read()
        blocks = [take_block(vc_src, re.compile(r'^WIRED_PATS\s*=\s*\[')),
                  take_block(vc_src, re.compile(r'^def\s+excluded\s*\('))]
        if any(b is None for b in blocks):
            raise ValueError("WIRED_PATS and/or excluded() not found (moved, renamed or removed)")
        ns = {"re": re}
        exec("\n".join(blocks), ns)
        VC_WIRED, vc_excluded = ns.get("WIRED_PATS"), ns.get("excluded")
        if not VC_WIRED or not callable(vc_excluded):
            raise ValueError("upstream model evaluated to an empty or invalid form")
        print(f"  upstream model READ from {VC_UPSTREAM} at run time (not copied): "
              f"{len(VC_WIRED)} WIRED_PATS + excluded()")
    except Exception as e:
        print(f"  [{VC_UPSTREAM}] INTERACTION MODEL ERROR: {e} — the self-test cannot assert "
              f"against the live upstream model, and will not assert against a stale one "
              f"(fail-closed)")
        overall = False

    for path, text in (docs.items() if VC_WIRED else []):   # no model loaded => nothing to assert
        claimed, excluded_positions, seen = set(), set(), set()
        # Mirrors upstream collect() exactly, including the `seen` precedence the hand-copy
        # dropped: a position already taken by an earlier pattern is never re-tested against
        # excluded(), and an excluded position is NOT added to `seen`, so a later pattern may
        # still claim it. Without this, a position matched by both an explicit "...entries"
        # pattern and the bare "N wired" pattern landed in BOTH sets and produced a spurious
        # direction-B orphan.
        for pat, excl_eligible in VC_WIRED:
            for m in pat.finditer(text):
                pos = m.start(1)
                if pos in seen:
                    continue
                if excl_eligible and vc_excluded(text, pos):
                    excluded_positions.add(pos)
                    continue
                seen.add(pos)
                claimed.add(pos)
        excluded_positions -= claimed   # claimed by any pattern => upstream enforces it
        mine = {pos for _, _, pos in dh.get(path, [])}
        # Direction A — no double-claim: nothing verify-claims.sh enforces as wired_entry_count
        # may also be enforced here as a distinct-files count.
        both = mine & claimed
        if both:
            for pos in sorted(both):
                print(f"  [{path}:{line_of(text, pos)}] INTERACTION CONFLICT: position claimed "
                      f"by BOTH wired_entry_count and distinct_wired_hooks")
            overall = False
        else:
            print(f"  [{path}] direction A OK: no position claimed by both checkers "
                  f"({len(claimed)} wired_entry_count, {len(mine)} distinct_wired_hooks)")
        # Direction B — no orphan: every bare "N wired" that verify-claims.sh EXCLUDES as a
        # different metric must be claimed here, or it is a number nobody checks.
        orphans = excluded_positions - mine
        if orphans:
            for pos in sorted(orphans):
                print(f"  [{path}:{line_of(text, pos)}] INTERACTION ORPHAN: excluded by "
                      f"verify-claims.sh as a different metric and bound by no check here")
            overall = False
        else:
            print(f"  [{path}] direction B OK: all {len(excluded_positions)} position(s) excluded "
                  f"by verify-claims.sh are claimed here")

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
# between the current step 4 (helper-script count) and step 5 (template sync), using the same
# accumulator so its failures aggregate rather than abort:
#
#     # 4b. Extended headline claims (slash / on-disk / permissions / distinct wired).
#     if bash scripts/verify-claims-extended.sh; then
#       pass "extended-claims: slash, on-disk, permissions, distinct-wired counts match source"
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
