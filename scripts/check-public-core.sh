#!/usr/bin/env bash
# Description: Public/private boundary gate. Recomputes the top-level tracked-path set from
#   git and fails if PUBLIC-CORE.md does not classify every path (a new file silently
#   escaping classification), if any class label is invalid, or if a known author-environment
#   residue marker leaks into a public-core-classified file un-parameterized. Companion to
#   PUBLIC-CORE.md (the ledger) and docs/reference/roadmap-decomposition-productization.md §4.
# Usage: bash scripts/check-public-core.sh
#        bash scripts/check-public-core.sh --scan-root <dir> --release-manifest <file>
#   Default (no args): gate the git checkout — ledger completeness + residue over the
#   ledger-derived public-core set.
#   --scan-root: gate an EXTRACTED RELEASE ARCHIVE instead. The scanned path set is
#   asserted EQUAL to the release-membership manifest, then the same residue classes run
#   over those bytes. Git-derived ledger sections are skipped (an archive is not a clone).
# Exit codes: 0 = boundary clean + complete, 1 = one or more checks failed (unclassified
#   path, invalid class, residue leak, or archive/manifest path-set mismatch).
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
# Set-based exemption ledger for the generic author-path residue gate (section 5). Keyed on
# (path, fingerprint, ordinal) so it can never degrade into a bypassable aggregate count.
RESIDUE_ALLOWLIST="policies/public-core-residue-allowlist.v1.json"

SCAN_ROOT=""          # non-empty => archive mode (gate extracted bytes, not the checkout)
RELEASE_MANIFEST=""   # release-membership manifest (explicit; never a class wildcard)
while [ $# -gt 0 ]; do
  case "$1" in
    --scan-root)        SCAN_ROOT="${2:?--scan-root needs a directory}"; shift 2 ;;
    --release-manifest) RELEASE_MANIFEST="${2:?--release-manifest needs a file}"; shift 2 ;;
    -h|--help)          sed -n '2,14p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "check-public-core: unknown argument '$1'" >&2; exit 1 ;;
  esac
done

command -v git  >/dev/null 2>&1 || { echo "ERROR: git is required"  >&2; exit 1; }
command -v awk  >/dev/null 2>&1 || { echo "ERROR: awk is required"  >&2; exit 1; }

rc=0
fail() { echo "FAIL: $*"; rc=1; }
pass() { echo "PASS: $*"; }

WS_MARKER='/dev/shm/dev-workspace/dot-claude'

# ---------------------------------------------------------------------------
# Shared generic author-path residue audit. ONE engine, used for both the git
# checkout and an extracted release archive, so the two can never drift apart.
#
#   $1    : root directory the scanned paths are relative to
#   $2    : allowlist JSON path (relative to that root)
#   $3    : "git" (enumerate via git ls-files + pathspecs) | "tree" (walk the root)
#   $4... : pathspecs, in "git" mode only
#   return: 0 clean, 1 residue/allowlist failure
#
# The file set is enumerated INSIDE this engine rather than piped in: the python
# program arrives on stdin via the heredoc, so stdin is not available for data.
#
# Every occurrence's exemption CLASS is re-derived from the live source structure
# (comment / docstring / heredoc / test tree / env `:-` default / the detector's
# own constant tables). A hand-written label the structure does not support is
# rejected, so the audit is not circular. Any author-path literal that is a live
# code literal or a unit-file directive value is `operational` and can NEVER be
# allowlisted — it must be fixed.
# ---------------------------------------------------------------------------
residue_audit() {
  python3 - "$@" <<'PY'
import hashlib, io, json, os, re, subprocess, sys, tokenize

root, allowlist_rel, mode = sys.argv[1], sys.argv[2], sys.argv[3]
if mode == "git":
    scan_paths = subprocess.run(["git", "-C", root, "ls-files", "--", *sys.argv[4:]],
                                capture_output=True, text=True).stdout.split()
else:
    scan_paths = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            scan_paths.append(os.path.relpath(os.path.join(dirpath, f), root))
    scan_paths.sort()
RESIDUE = re.compile(r"/root/|/home/[a-z][a-z0-9_-]*/|/Users/[A-Za-z][A-Za-z0-9_-]*/")
DOC_EXTS = {".md", ".txt", ".rst"}
CODE_EXTS = {".py", ".sh", ".bash", ".mjs", ".js", ".ts"}
UNIT_EXTS = {".service", ".socket", ".timer", ".path", ".mount"}
# STRICT comment markers only: "-", "|", ">" and "*" also start YAML sequence
# nodes / block scalars, so accepting them would let a live config value pose as
# a comment. Whole-file prose is covered separately by DOC_EXTS.
COMMENT_STARTS = ("#", "//", "<!--", ";")
JSON_DOC_KEY = re.compile(
    r'"([A-Za-z0-9_]*(reference|doc|note|rationale|description|comment)[A-Za-z0-9_]*)"\s*:', re.I)
HD = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
PLACEHOLDER = {"", "tbd", "n/a", "na", "none", "todo", "-"}

try:
    doc = json.load(open(os.path.join(root, allowlist_rel), encoding="utf8"))
except Exception as exc:
    print(f"FAIL: residue-allowlist unreadable ({allowlist_rel}): {exc}")
    sys.exit(1)
SCANNER_PATHS = set(doc.get("self_exempt_paths") or [])
LEGIT = set(doc.get("legitimate_classes") or [])
entries, dup = {}, False
for e in doc.get("entries") or []:
    key = (e.get("path"), e.get("fingerprint"), e.get("ordinal"))
    if key in entries:
        print(f"FAIL: residue-allowlist duplicate key {key}"); dup = True
    entries[key] = e

def lang_of(path, text):
    ext = os.path.splitext(path)[1]
    if ext:
        return ext
    head = text.split("\n", 1)[0]
    if head.startswith("#!"):
        return ".py" if "python" in head else (".sh" if "sh" in head else "")
    return ""

def py_docstrings(text):
    spans = set()
    try:
        for t in tokenize.generate_tokens(io.StringIO(text).readline):
            if t.type == tokenize.STRING and t.string.lstrip("rbuRBUfF")[:3] in ('"""', "'''"):
                spans.update(range(t.start[0], t.end[0] + 1))
    except Exception:
        pass
    return spans

def sh_heredocs(lines):
    spans, term = set(), None
    for i, ln in enumerate(lines, 1):
        if term is None:
            m = HD.search(ln)
            if m:
                term = m.group(1)
        elif ln.strip() == term:
            term = None
        else:
            spans.add(i)
    return spans

def classify(path, lineno, content, lang, dspans, hspans):
    tl = content.lstrip()
    is_comment = tl.startswith(COMMENT_STARTS)
    is_doc = lang in DOC_EXTS
    is_docstring = lineno in dspans or tl.startswith(">>>")
    is_heredoc = lineno in hspans
    is_test = "/tests/" in path or os.path.basename(path).startswith("test_")
    is_env = bool(re.search(r':-\s*["\']?(/root/|/home/|/Users/)', content))
    is_unit = lang in UNIT_EXTS and bool(re.match(r"^[A-Za-z][A-Za-z0-9]*=", content.strip()))
    is_scanner = path in SCANNER_PATHS
    is_jsondoc = lang == ".json" and bool(JSON_DOC_KEY.search(content))
    derived = set()
    if is_comment or is_doc or is_jsondoc:
        derived.add("comment_or_narrative_doc")
    if is_docstring or is_heredoc:
        derived.add("doctest_or_docstring_example")
    if is_test:
        derived.add("test_fixture")
    if is_env:
        derived.add("env_parameterized_default")
    if is_scanner:
        derived.add("scanner_pattern_definition")
    operational = False
    if not is_scanner:
        if is_unit:
            operational = True
        elif lang in CODE_EXTS and not (is_comment or is_docstring or is_heredoc or is_env or is_test):
            operational = True
    return derived, operational

failures = 0 if not dup else 1
live = set()
for rel in (p.strip() for p in sys.stdin):
    if not rel:
        continue
    full = os.path.join(root, rel)
    try:
        text = open(full, encoding="utf8").read()
    except (OSError, UnicodeDecodeError):
        continue          # binary / unreadable: no textual residue to gate
    lang = lang_of(rel, text)
    lines = text.splitlines()
    dspans = py_docstrings(text) if lang == ".py" else set()
    hspans = sh_heredocs(lines) if lang in (".sh", ".bash") else set()
    ordinals = {}
    for lineno, content in enumerate(lines, 1):
        if not RESIDUE.search(content):
            continue
        derived, operational = classify(rel, lineno, content, lang, dspans, hspans)
        fp = hashlib.sha256(content.encode()).hexdigest()[:16]
        ordinals[(rel, fp)] = ordinals.get((rel, fp), 0) + 1
        key = (rel, fp, ordinals[(rel, fp)])
        live.add(key)
        if operational:
            print(f"FAIL: author-path residue (operational, NOT allowlistable) -> {rel}:{lineno}: {content.strip()[:120]}")
            failures += 1
            continue
        entry = entries.get(key)
        if entry is None:
            print(f"FAIL: NEW un-allowlisted author-path residue -> {rel}:{lineno}: {content.strip()[:120]}")
            failures += 1
            continue
        cls = entry.get("class")
        if cls not in LEGIT:
            print(f"FAIL: residue-allowlist entry declares unknown class {cls!r} -> {rel}:{lineno}")
            failures += 1
        elif cls not in derived:
            print(f"FAIL: residue-allowlist class {cls!r} is NOT supported by the source structure "
                  f"(structurally derived: {sorted(derived) or 'none'}) -> {rel}:{lineno}")
            failures += 1
        rat = (entry.get("rationale") or "").strip()
        if rat.lower() in PLACEHOLDER:
            print(f"FAIL: residue-allowlist entry has no per-entry rationale -> {rel}:{lineno}")
            failures += 1

for key, e in entries.items():
    if key in live:
        continue
    path = key[0]
    if not os.path.exists(os.path.join(root, path)):
        print(f"FAIL: residue-allowlist entry references a path that no longer exists -> {path}")
    else:
        print(f"FAIL: STALE residue-allowlist entry (fingerprint/ordinal no longer present) -> {path} {key[1]}#{key[2]}")
    failures += 1

print(f"  residue audit: {len(live)} occurrence(s) scanned, {len(entries)} allowlist entr(ies), {failures} failure(s)")
sys.exit(1 if failures else 0)
PY
}

if [ ! -f "$MANIFEST" ]; then
  echo "FAIL: boundary manifest not found: $MANIFEST" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# ARCHIVE MODE — gate the EXTRACTED RELEASE ARCHIVE rather than the checkout.
# Scanning the source checkout proves nothing about the bytes that are actually
# published, so the release pipeline runs the gate again over the extracted
# archive. The scanned path set is asserted EQUAL to the release-membership
# manifest, so no shipped path can escape the residue classes.
# ---------------------------------------------------------------------------
if [ -n "$SCAN_ROOT" ]; then
  [ -d "$SCAN_ROOT" ] || { echo "FAIL: --scan-root is not a directory: $SCAN_ROOT" >&2; exit 1; }
  [ -n "$RELEASE_MANIFEST" ] || { echo "FAIL: --scan-root requires --release-manifest" >&2; exit 1; }
  [ -f "$RELEASE_MANIFEST" ] || { echo "FAIL: release manifest not found: $RELEASE_MANIFEST" >&2; exit 1; }

  ACTUAL="$(cd "$SCAN_ROOT" && find . -type f | sed 's#^\./##' | sort)"
  EXPECTED="$(bash "$ROOT/scripts/release-membership.sh" --list --root "$SCAN_ROOT" \
                   --manifest "$RELEASE_MANIFEST" | sort)"
  if [ "$ACTUAL" != "$EXPECTED" ]; then
    fail "archive path set != release-membership manifest path set (set equality is required):"
    diff <(printf '%s\n' "$EXPECTED") <(printf '%s\n' "$ACTUAL") \
      | sed 's/^</    only-in-manifest: /;s/^>/    only-in-archive:  /' | grep -E 'only-in-' | head -40
  else
    pass "extracted archive path set EQUALS the release-membership manifest ($(printf '%s\n' "$ACTUAL" | wc -l | tr -d ' ') paths)"
  fi

  # Residue class 1: maintainer workspace/tmpfs marker — hard-gating over the archive.
  WS_EXEMPT="$(python3 -c 'import json,sys;print("\n".join(json.load(open(sys.argv[1])).get("workspace_marker_exempt_paths",[])))' "$RELEASE_MANIFEST")"
  ws_hits=0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    printf '%s\n' "$WS_EXEMPT" | grep -qxF "$f" && continue
    if grep -qF -- "$WS_MARKER" "$SCAN_ROOT/$f" 2>/dev/null; then
      fail "maintainer workspace-path residue in released archive -> $f"
      ws_hits=$((ws_hits + 1))
    fi
  done <<< "$ACTUAL"
  [ "$ws_hits" -eq 0 ] && pass "no un-exempted workspace-path residue in the released archive"

  # Residue class 2: generic author-home paths — same engine as the checkout gate.
  if printf '%s\n' "$ACTUAL" | residue_audit "$SCAN_ROOT" "$RESIDUE_ALLOWLIST"; then
    pass "no un-allowlisted author-path residue in the released archive"
  else
    fail "author-path residue gate failed over the released archive (see FAIL lines above)"
  fi

  echo "----------------------------------------------------------------------"
  if [ "$rc" -eq 0 ]; then
    echo "check-public-core(archive): RELEASE ARCHIVE CLEAN (path set == manifest, no residue leaks)"
  else
    echo "check-public-core(archive): FAILURES DETECTED — see FAIL lines above"
  fi
  exit "$rc"
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

# Concrete public-core FILE list for the section-5 residue audit. Unlike the marker
# scans above, this deliberately does NOT drop $SELF: the audit re-derives every
# exemption class structurally, and this detector's own constant tables are exempted
# by class (scanner_pattern_definition), not by being hidden from the scan.
mapfile -t PC_FILES < <(git ls-files -- "${PC_PATHSPECS[@]:0:${#PC_PATHSPECS[@]}-1}" 2>/dev/null)

# A public-core match line is an allowed (parameterized) use of marker M when the line is a
# comment (trimmed starts with #) OR EVERY occurrence of M on the line is an env default
# (":-M", ":-\"M", ":-'M"). The check is OCCURRENCE-level, not line-level: a single accepted
# ":-M" no longer whitelists a SECOND, bare (un-parameterized) M on the same line — every
# occurrence must sit in an accepted position or the line is reported as a leak.
param_line_ok() {
  local content="$1" marker="$2" trimmed rest before
  trimmed="${content#"${content%%[![:space:]]*}"}"
  [[ "$trimmed" == \#* ]] && return 0   # whole-line comment → every occurrence is inert
  rest="$content"
  while [[ "$rest" == *"$marker"* ]]; do
    before="${rest%%"$marker"*}"        # text preceding the FIRST remaining occurrence
    if [[ "$before" != *":-" && "$before" != *":-\"" && "$before" != *":-'" ]]; then
      return 1                          # a bare (un-parameterized) occurrence → leak
    fi
    rest="${rest#*"$marker"}"           # advance past this occurrence, keep scanning
  done
  return 0
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
  done < <(git grep -nF -- "$m" -- "${PARAM_PATHSPECS[@]}" 2>/dev/null)
done

if [ "$leaks" -eq 0 ]; then
  pass "no author-environment residue leaked into the public-core set"
fi

# ---------------------------------------------------------------------------
# 4. Maintainer workspace/tmpfs path — HARD GATE (was advisory until this cycle).
#    "Make CI FAIL (not advisory) on ... the tmpfs workspace path" — the advisory
#    branch never set rc=1, so a leak of this class could never turn CI red.
# ---------------------------------------------------------------------------
ws_hits="$(git grep -nF -- "$WS_MARKER" -- "${PC_PATHSPECS[@]}" 2>/dev/null)"
if [ -n "$ws_hits" ]; then
  while IFS= read -r hit; do
    [ -z "$hit" ] && continue
    fail "maintainer workspace-path residue in public-core: '$WS_MARKER'  ->  $hit"
  done <<< "$ws_hits"
else
  pass "no maintainer workspace-path residue in the public-core set"
fi

# ---------------------------------------------------------------------------
# 5. Generic author-home residue (/root/, /home/<user>/, /Users/<User>/) — HARD
#    GATE, exemptions driven by a checked-in SET (not an aggregate count).
# ---------------------------------------------------------------------------
if [ ! -f "$RESIDUE_ALLOWLIST" ]; then
  fail "residue allowlist not found: $RESIDUE_ALLOWLIST"
elif printf '%s\n' "${PC_FILES[@]}" | residue_audit "$ROOT" "$RESIDUE_ALLOWLIST"; then
  pass "no un-allowlisted author-path residue in the public-core set"
else
  fail "author-path residue gate failed (new/operational occurrence, unsupported class label, or stale allowlist entry)"
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
