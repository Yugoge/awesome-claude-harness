#!/usr/bin/env bash
# Description: Public/private boundary gate, the one privacy engine. Recomputes the top-level
#   tracked-path set from git and fails if PUBLIC-CORE.md does not classify every path (a new
#   file silently escaping classification) or a class label is invalid, and fails on personal
#   residue in ANY tracked file: generic author-home paths and e-mail addresses (allowlisted
#   by class) plus the literals of the untracked private-literal list. Companion to
#   PUBLIC-CORE.md (the ledger) and docs/reference/roadmap-decomposition-productization.md §4.
# Usage: bash scripts/check-public-core.sh [--private-literals]
#        bash scripts/check-public-core.sh --scan-root <dir> --release-manifest <file>
#   Default (no args): gate the git checkout — ledger completeness + residue and the
#   private-literal rule over every tracked file.
#   --private-literals: ONLY that rule, over what the staged change adds (pre-commit hook).
#   --scan-root: gate an EXTRACTED RELEASE ARCHIVE instead. The scanned path set is
#   asserted EQUAL to the release-membership manifest, then the same residue classes run
#   over those bytes. Git-derived ledger sections are skipped (an archive is not a clone).
# Exit codes: 0 = boundary clean + complete, 1 = one or more checks failed (unclassified
#   path, invalid class, residue leak, or archive/manifest path-set mismatch).
# Root cause (design): with only a prose boundary (roadmap §4) a new top-level file could
#   escape classification and author literals re-enter the core; this gate recomputes both
#   from git every run. Style as scripts/verify-claims.sh: pure bash (+awk/git/grep),
#   recompute-don't-hardcode, an explicit accumulator so ALL problems are reported at once.

set -uo pipefail   # deliberately NOT -e: run every check, aggregate, report all drift.

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || { echo "ERROR: cannot cd to repo root" >&2; exit 1; }

MANIFEST="PUBLIC-CORE.md"
# Set-based exemption ledger for the generic residue gate (section 5). Keyed on
# (path, fingerprint, ordinal) so it can never degrade into a bypassable aggregate count.
RESIDUE_ALLOWLIST="policies/public-core-residue-allowlist.v1.json"

SCAN_ROOT=""          # non-empty => archive mode (gate extracted bytes, not the checkout)
RELEASE_MANIFEST=""   # release-membership manifest (explicit; never a class wildcard)
LITERALS_ONLY=0       # 1 => --private-literals
while [ $# -gt 0 ]; do
  case "$1" in
    --scan-root)        SCAN_ROOT="${2:?--scan-root needs a directory}"; shift 2 ;;
    --release-manifest) RELEASE_MANIFEST="${2:?--release-manifest needs a file}"; shift 2 ;;
    --private-literals) LITERALS_ONLY=1; shift ;;
    -h|--help)          sed -n '2,17p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "check-public-core: unknown argument '$1'" >&2; exit 1 ;;
  esac
done

command -v git  >/dev/null 2>&1 || { echo "ERROR: git is required"  >&2; exit 1; }
command -v awk  >/dev/null 2>&1 || { echo "ERROR: awk is required"  >&2; exit 1; }

rc=0
fail() { echo "FAIL: $*"; rc=1; }
pass() { echo "PASS: $*"; }

# Private-literal rule (R7b). The list is private-literals.txt in the MAIN working tree (no
# override): one literal per line, trimmed, blank and #-lines ignored, fixed-string match.
# Scopes: index = all tracked content as committed; staged = lines and path names the staged
# change adds; archive = every file under $2. A hit names file:line and its list line only.
private_literal_rule() {
  local list l n=0 base; local -a lits=()
  list="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo "$ROOT/.git")")/private-literals.txt"
  [[ ! -e $list || ( -f $list && -r $list ) ]] || { fail "private-literal rule: cannot read private-literals.txt"; return 0; }
  [ -f "$list" ] && while IFS= read -r l || [ -n "$l" ]; do
    n=$((n + 1)); l="${l%$'\r'}"; l="${l#"${l%%[![:blank:]]*}"}"; l="${l%"${l##*[![:blank:]]}"}"
    case "$l" in ''|'#'*) ;; *) lits+=("$n:$l") ;; esac
  done < "$list"
  [ "${#lits[@]}" -gt 0 ] || { echo "SKIP: private-literal rule (no literal listed in $list)"; return 0; }
  base="$(git hash-object -t tree /dev/null)"   # the empty tree: every indexed line is "added"
  [ "$1" = staged ] && base="$(git rev-parse -q --verify 'HEAD^{tree}' || echo "$base")"
  if [ "$1" = archive ]; then   # names, a blank line, then the content as a pseudo-diff
    (cd "$2" && find . ! -type d | sed 's#^\./##' && echo && find . -type f -exec awk \
      'FNR == 1 { print "+++ " substr(FILENAME, 3) } { print "@@ -0 +" FNR " @@"; print "+" $0 }' {} +)
  else
    git -c core.quotePath=off diff-index --cached --no-renames --name-only --diff-filter=d "$base" && echo &&
      git -c core.quotePath=off diff-index --cached --no-renames -p -U0 --text --no-prefix "$base"
  fi | LC_ALL=C awk 'BEGIN { for (m = 1; m < ARGC; m++) { c = index(ARGV[m], ":")   # ARGV: "<list line>:<literal>"
        N[m] = substr(ARGV[m], 1, c - 1); L[m] = substr(ARGV[m], c + 1) }; ARGC = 1 }
    function scan(s, path, at,   k, j) { for (k = 1; k < m; k++) if (index(s, L[k])) {
        for (j = 1; j < m; j++) if (index(path, L[j])) path = "<path with private-literals.txt line " N[j] ">"
        print "FAIL: private literal (private-literals.txt line " N[k] ") -> " path at; bad = 1 } }
    !body { if ($0 == "") body = 1; else scan($0, $0, " (path name)"); next }
    d && /^\+/ { d--; scan(substr($0, 2), f, ":" n++); next }
    !d && /^\+\+\+ / { f = substr($0, 5); sub(/\t$/, "", f) }
    !d && /^@@ / { split($3, a, /[+,]/); n = a[2] + 0; d = (a[3] == "" ? 1 : a[3] + 0) }
    END { exit bad }' "${lits[@]}" && pass "no listed private literal (scope: $1)" ||
    fail "private-literal rule (scope: $1): see the lines above; a listed literal is never printed"
}
if [ "$LITERALS_ONLY" -eq 1 ]; then private_literal_rule staged; exit "$rc"; fi

# ---------------------------------------------------------------------------
# Shared generic residue audit (author-home paths, e-mail addresses). ONE engine,
# used for both the git checkout and an extracted release archive, so the two can
# never drift apart.
#
#   $1    : root directory the scanned paths are relative to
#   $2    : allowlist JSON path (relative to that root)
#   $3    : "git" (every file git ls-files lists) | "tree" (walk the root)
#   return: 0 clean, 1 residue/allowlist failure
#
# The file set is enumerated INSIDE this engine rather than piped in: the python
# program arrives on stdin via the heredoc, so stdin is not available for data.
#
# Every occurrence's exemption CLASS is re-derived from the live source structure
# (comment / docstring / heredoc / test tree / env `:-` default / the detector's
# own constant tables). A hand-written label the structure does not support is
# rejected, so the audit is not circular. Any residue literal that is a live
# code literal or a unit-file directive value is `operational` and can NEVER be
# allowlisted — it must be fixed. A FAIL line names file:line and the occurrence's
# allowlist key and derived classes, never the line itself (it may hold a personal value).
# ---------------------------------------------------------------------------
residue_audit() {
  python3 - "$@" <<'PY'
import ast, hashlib, io, json, os, re, subprocess, sys, tokenize

root, allowlist_rel, mode = sys.argv[1], sys.argv[2], sys.argv[3]
INDEX_READ = set(os.environ.get("PC_FILTERED", "").splitlines()) if mode == "git" else set()
if mode == "git":
    scan_paths = subprocess.run(["git", "-C", root, "ls-files", "-z"],
                                capture_output=True, text=True).stdout.split("\0")
else:
    scan_paths = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            scan_paths.append(os.path.relpath(os.path.join(dirpath, f), root))
    scan_paths.sort()
# Boundary-aware on BOTH sides. The previous form anchored every alternative on a
# TRAILING "/", so it matched a home directory's descendants but never the directory
# ROOT itself: `p = "<root-home>/.claude"` was caught while `EXACT_ROOT="<root-home>"`,
# `EXACT_HOME="<linux-home>"` and `MAC="<mac-home>"` walked straight through.
# (The bracketed "[t]" keeps this pattern from matching its own source line.)
#   right (?![A-Za-z0-9_-]) : the root form matches as well as the descendant form,
#                             while /homework and /rootkit still do not.
#   left  (?<![A-Za-z0-9])  : an author path must START a path component. Without it
#                             ordinary prose ("a protected workspace/root") reads as
#                             residue. It deliberately does NOT exclude a preceding
#                             "/", so `//home/<user>` is still caught — and it must
#                             NOT exclude "-" or "_" either: the shell default idiom
#                             `${VAR:-<author-path>}` places a "-" immediately before
#                             the path, so suppressing on "-" blinded the gate to the
#                             very form PUBLIC-CORE.md section 3 sanctions. The prose
#                             cases stay suppressed regardless, being preceded by
#                             alphanumerics.
RESIDUE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:/roo[t]|/home/[a-z][a-z0-9_-]*|/Users/[A-Za-z][A-Za-z0-9_-]*)"
    r"(?![A-Za-z0-9_-])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Allowed BY RULE, never personal: reserved example/test domains (RFC 2606, RFC 6761),
# no-reply trailers, systemd template units (name@instance.service); and, in email_ok,
# the `git@<host>:` SSH user form (a personal remote is the private list's job).
EMAIL_OK = re.compile(r"@(?:[A-Za-z0-9.-]+\.)?(?:example(?:\.com|\.org|\.net)?|invalid|test|localhost|local)$"
                      r"|^no-?reply@"                                                # no-reply local part
                      r"|^[0-9]+\+[A-Za-z0-9._-]+@users\.noreply\.[A-Za-z0-9.-]+$"   # forge no-reply form
                      r"|^[A-Za-z0-9_.:-]+@[A-Za-z0-9_:-]+\.(?:service|socket|timer|mount)$",  # unit@instance
                      re.I)

def email_ok(m, line):
    return bool(EMAIL_OK.search(m.group(0))) or (
        m.group(0).lower().startswith("git@") and line[m.end():m.end() + 1] == ":")
# A BARE top-level directory literal: "/" or "/name" with no second path component.
# "/home/<user>" can never satisfy it, which is what keeps a genuine author-home
# literal `operational` (and therefore non-allowlistable) under SYS_DIR classification.
SYS_DIR_LITERAL = re.compile(r"^/[A-Za-z0-9_.-]*$")
SYS_DIR_MIN_ELEMENTS = 3   # a table, not an incidental pair
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

def py_comment_spans(text):
    """lineno -> [(startcol, endcol)] for every COMMENT token, TRAILING ones included.

    Whole-line comment detection alone cannot see residue that sits after live code
    (`try:  # ... route the audit-log default off <root-home>`), so such an occurrence was
    misread as an operational code literal."""
    spans = {}
    try:
        for t in tokenize.generate_tokens(io.StringIO(text).readline):
            if t.type == tokenize.COMMENT:
                spans.setdefault(t.start[0], []).append((t.start[1], t.start[1] + len(t.string)))
    except Exception:
        pass
    return spans


def sh_comment_spans(lines):
    """Same idea for shell: an UNQUOTED '#' starting a word runs to end of line."""
    spans, quote = {}, None
    for i, ln in enumerate(lines, 1):
        quote = None
        for col, ch in enumerate(ln):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in ("'", '"'):
                quote = ch
            elif ch == "#" and (col == 0 or ln[col - 1] in " \t;&|()"):
                spans.setdefault(i, []).append((col, len(ln)))
                break
    return spans


def py_system_path_enum(text):
    """lineno -> {bare system-dir literals} that are elements of an ENUMERATION of
    absolute bare directories, e.g. `("/", "/boot", "/etc", "/usr", ...)`.

    Structurally derived from the AST, never from a hand-written label: the literal
    must sit in a list/tuple/set whose every element is a bare top-level directory
    string and which has at least SYS_DIR_MIN_ELEMENTS of them. A path carrying a
    second component (an actual author home such as "/home/<user>") can never
    qualify, so this class cannot launder a genuine residue literal."""
    out = {}
    try:
        tree = ast.parse(text)
    except Exception:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            continue
        elts = node.elts
        if len(elts) < SYS_DIR_MIN_ELEMENTS:
            continue
        if not all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                   and SYS_DIR_LITERAL.match(e.value) for e in elts):
            continue
        for e in elts:
            out.setdefault(e.lineno, set()).add(e.value)
    return out


def classify(path, lineno, content, lang, dspans, hspans, cspans, sspans, matches):
    tl = content.lstrip()
    # Occurrence-level: EVERY residue
    # occurrence on the line must sit inside a comment span, so one commented
    # occurrence can never whitelist a second, live one on the same line.
    line_cspans = cspans.get(lineno) or ()
    trailing_comment = bool(line_cspans) and all(
        any(s <= m.start() < e for s, e in line_cspans) for m in matches)
    is_comment = tl.startswith(COMMENT_STARTS) or trailing_comment
    sys_literals = sspans.get(lineno) or ()
    is_sysdir = bool(sys_literals) and all(m.group(0) in sys_literals for m in matches)
    is_doc = lang in DOC_EXTS
    is_docstring = lineno in dspans or tl.startswith(">>>")
    is_heredoc = lineno in hspans
    is_test = "/tests/" in "/" + path or os.path.basename(path).startswith("test_")
    is_env = bool(re.search(r':-\s*["\']?(/roo[t]|/home/|/Users/)', content))
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
    if is_sysdir:
        derived.add("system_path_constant_enumeration")
    operational = False
    if not is_scanner:
        if is_unit:
            operational = True
        elif lang in CODE_EXTS and not (is_comment or is_docstring or is_heredoc
                                        or is_env or is_test or is_sysdir):
            operational = True
    return derived, operational

failures = 0 if not dup else 1
live = set()
scanned = set()
for rel in scan_paths:
    if not rel:
        continue
    full = os.path.join(root, rel)
    try:   # a filtered file: its index blob (the checkout only if it has no stage-0 entry)
        blob = rel in INDEX_READ and subprocess.run(["git", "-C", root, "cat-file", "blob", ":" + rel], capture_output=True)
        text = blob.stdout.decode("utf8") if blob and not blob.returncode else open(full, encoding="utf8").read()
    except UnicodeDecodeError:   # not UTF-8: other 8-bit text (Latin-1, say) is still scanned
        data = blob.stdout if blob and not blob.returncode else open(full, "rb").read()
        if b"\0" in data:
            continue      # binary (git's NUL test): no textual residue to gate
        text = data.decode("latin-1")
    except OSError:
        continue          # unreadable: no textual residue to gate
    scanned.add(rel)
    lang = lang_of(rel, text)
    lines = text.splitlines()
    dspans = py_docstrings(text) if lang == ".py" else set()
    hspans = sh_heredocs(lines) if lang in (".sh", ".bash") else set()
    cspans = py_comment_spans(text) if lang == ".py" else (
        sh_comment_spans(lines) if lang in (".sh", ".bash") else {})
    sspans = py_system_path_enum(text) if lang == ".py" else {}
    ordinals = {}
    for lineno, content in enumerate(lines, 1):
        paths = list(RESIDUE.finditer(content))
        matches = paths + [m for m in EMAIL.finditer(content) if not email_ok(m, content)]
        if not matches:
            continue
        what = "author-path residue" if paths else "e-mail address"
        derived, operational = classify(rel, lineno, content, lang, dspans, hspans,
                                        cspans, sspans, matches)
        fp = hashlib.sha256(content.encode()).hexdigest()[:16]
        ordinals[(rel, fp)] = ordinals.get((rel, fp), 0) + 1
        key = (rel, fp, ordinals[(rel, fp)])
        live.add(key)
        where = f"{rel}:{lineno} [{fp}#{key[2]} derived: {','.join(sorted(derived)) or 'none'}]"
        if operational:
            print(f"FAIL: {what} (operational, NOT allowlistable) -> {where}")
            failures += 1
            continue
        entry = entries.get(key)
        if entry is None:
            print(f"FAIL: NEW un-allowlisted {what} -> {where}")
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

# ONE allowlist serves two scan scopes (every tracked file, and the release-archive
# subset). An entry is only judged against a scope that actually looked at its path:
# otherwise every non-shipped entry would read as "stale" in archive mode. Entries
# whose path was scanned must still match exactly; entries naming a path that exists
# nowhere are dangling.
for key, e in entries.items():
    if key in live:
        continue
    path = key[0]
    if not os.path.exists(os.path.join(root, path)):
        # Dangling entries are only meaningful against the full repository (git
        # mode). In archive mode an absent path is EXPECTED — the membership
        # manifest deliberately excludes the test net, so its entries do not ship.
        if mode == "git":
            print(f"FAIL: residue-allowlist entry references a path that no longer exists -> {path}")
            failures += 1
        continue
    if path in scanned:
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

  # `-type l` is defence in depth, NOT the load-bearing predicate an earlier
  # revision of this comment claimed. Measured: release.yml stages members with
  # `cp -p`, which (carrying none of -d/-P/-a) DEREFERENCES a symlink source, so
  # the staged tree holds a regular file and no symlink ever reaches `tar` — the
  # one tracked symlink, templates/overnight-spec.md, extracts as a regular file.
  # The predicate is retained so that a future staging step which does preserve
  # symlinks cannot silently drop a member from the ACTUAL set.
  ACTUAL="$(cd "$SCAN_ROOT" && find . \( -type f -o -type l \) | sed 's#^\./##' | sort)"
  EXPECTED="$(python3 "$ROOT/scripts/lib/release_membership.py" --from-tree \
                   --root "$SCAN_ROOT" --manifest "$RELEASE_MANIFEST" | sort)"
  if [ "$ACTUAL" != "$EXPECTED" ]; then
    fail "archive path set != release-membership manifest path set (set equality is required):"
    diff <(printf '%s\n' "$EXPECTED") <(printf '%s\n' "$ACTUAL") \
      | sed 's/^</    only-in-manifest: /;s/^>/    only-in-archive:  /' | grep -E 'only-in-' | head -40
  else
    pass "extracted archive path set EQUALS the release-membership manifest ($(printf '%s\n' "$ACTUAL" | wc -l | tr -d ' ') paths)"
  fi

  # Residue class 1: the private-literal rule over every archive member.
  private_literal_rule archive "$SCAN_ROOT"

  # Residue class 2: generic author-home paths and e-mail addresses — same engine as the checkout gate.
  if residue_audit "$SCAN_ROOT" "$RESIDUE_ALLOWLIST" tree; then
    pass "no un-allowlisted residue in the released archive"
  else
    fail "residue gate failed over the released archive (see FAIL lines above)"
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
  if ! grep -qxF -- "$p" <<< "$CLASSIFIED_PATHS"; then  # a here-string: `printf | grep -q` under pipefail fails at random (SIGPIPE)
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
  if ! grep -qxF -- "$p" <<< "$TOPLEVEL"; then
    STALE="${STALE}${p}"$'\n'
  fi
done <<< "$CLASSIFIED_PATHS"
if [ -n "$STALE" ]; then
  echo "INFO: ledger entr(y/ies) not currently a tracked top-level path (new/untracked or stale):"
  printf '%s' "$STALE" | sed '/^$/d;s/^/    /'
fi

# A file git filters (settings.json: init smudges its checkout into the machine form) is
# read from its index blob, the tracked content, in section 5; others as checked out.
FILTERED="$(git ls-files | git check-attr --stdin filter | awk -F': filter: ' '$2 != "unspecified" && $2 != "unset" { print $1 }')"

# ---------------------------------------------------------------------------
# 4. Private-literal rule — HARD GATE over the committed content of EVERY tracked file.
# ---------------------------------------------------------------------------
private_literal_rule index

# ---------------------------------------------------------------------------
# 5. Generic residue over EVERY tracked file: author homes (the root user's, a Linux
#    user's, a macOS user's) and e-mail addresses outside the classes allowed by rule
#    (EMAIL_OK) — HARD GATE, exemptions driven by a checked-in SET (not a count).
# ---------------------------------------------------------------------------
if [ ! -f "$RESIDUE_ALLOWLIST" ]; then
  fail "residue allowlist not found: $RESIDUE_ALLOWLIST"
elif PC_FILTERED="$FILTERED" residue_audit "$ROOT" "$RESIDUE_ALLOWLIST" git; then
  pass "no un-allowlisted residue in any tracked file"
else
  fail "residue gate failed (new/operational occurrence, unsupported class label, or stale allowlist entry)"
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
