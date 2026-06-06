#!/usr/bin/env bash
set -u
TMPDIR_SELF=$(mktemp -d -t ac5-verify-XXXXXX)
trap 'rm -rf "$TMPDIR_SELF" 2>/dev/null' EXIT INT TERM
STEP7_MD="$TMPDIR_SELF/step7.md"
awk '
  /^#{2,3}[[:space:]]+Step 8/ { in_section = 1; print; next }
  /^#{2,3}[[:space:]]+Step [0-9]/ && in_section { in_section = 0 }
  in_section { print }
' commands/commit.md > "$STEP7_MD"

echo "=== V1 ==="
awk '
  { line = $0 }
  /context\.spec_path first/ { if (!s1) s1 = NR }
  /\(2\)[[:space:]]*Continuation spec/ { if (!s2) s2 = NR }
  /Continuation spec\(\\s\*\\\([\^)]\*\\\)\)\?\\s\*:/ { if (!s2) s2 = NR }
  /^[-*+]?[[:space:]]*Continuation spec[[:space:]]*(\([^)]*\))?[[:space:]]*:/ { if (!s2) s2 = NR }
  /(mtime[[:space:]]*\+[[:space:]]*literal-task-id|mtime.*close.report.*24h|mtime.*\[close.report)/ { if (!s3) s3 = NR }
  /spec produced this cycle but not linked in context/ { if (!s4a) s4a = NR }
  /multiple specs produced this cycle without context linkage/ { if (!s4b) s4b = NR }
  END {
    if (!s1) { print "AC5-V1 FAIL: step 1 marker missing"; exit 1 }
    if (!s2) { print "AC5-V1 FAIL: step 2 marker missing"; exit 1 }
    if (!s3) { print "AC5-V1 FAIL: step 3 marker missing"; exit 1 }
    if (!s4a) { print "AC5-V1 FAIL: single-match outcome missing"; exit 1 }
    if (!s4b) { print "AC5-V1 FAIL: multi-match outcome missing"; exit 1 }
    if (!(s1 < s2 && s2 < s3 && s3 < s4a && s3 < s4b)) { print "AC5-V1 FAIL: step markers out of order: s1=" s1 " s2=" s2 " s3=" s3 " s4a=" s4a " s4b=" s4b; exit 1 }
    print "AC5-V1 PASS s1=" s1 " s2=" s2 " s3=" s3 " s4a=" s4a " s4b=" s4b
    exit 0
  }
' "$STEP7_MD"

echo "=== V2 ==="
grep -nE 'fence-aware|fenced code block|skip ranges between' "$STEP7_MD" | head -3

echo "=== V3 ==="
if grep -niE 'dev chooses|one of:|either.*mtime.*or.*filename|pick latest|prefer newest|select any|most recent wins|any matching|the right one' "$STEP7_MD"; then
  echo "AC5-V3 FAIL: nondeterminism phrase found"
  exit 1
else
  echo "AC5-V3 PASS"
fi

echo "=== V4 ==="
grep -nF "spec produced this cycle but not linked in context" commands/commit.md | head -1
grep -nF "multiple specs produced this cycle without context linkage" commands/commit.md | head -1

echo "=== V5(a) ==="
grep -nF 'Continuation spec(\s*\([^)]*\))?\s*:' "$STEP7_MD" >/dev/null && echo "V5(a-i) PASS" || echo "V5(a-i) FAIL"
grep -nE '\^\[-\*\+\]\?|markdown list marker|list marker|bullet' "$STEP7_MD" >/dev/null && echo "V5(a-ii) PASS" || echo "V5(a-ii) FAIL"
grep -nF '`?(docs/dev/specs/spec-' "$STEP7_MD" >/dev/null && echo "V5(a-iii) PASS" || echo "V5(a-iii) FAIL"

echo "=== V5(b) ==="
python3 - <<'PYEOF'
import re, sys
line = open('docs/dev/close-report-20260519-175339.md').read().splitlines()[150]
expected = '- Continuation spec (from prior NO): `docs/dev/specs/spec-20260520-044700.md`'
if line != expected:
    sys.exit('V5(b) sanity FAIL: real-world line drifted: ' + repr(line))
pattern = r'^[-*+]?\s*Continuation spec(\s*\([^)]*\))?\s*:\s*`?(docs/dev/specs/spec-[^\s`]+\.md)`?\s*$'
m = re.match(pattern, line)
if not m:
    sys.exit('V5(b) FAIL: permissive regex does NOT match: ' + repr(line))
captured = m.group(2)
if captured != 'docs/dev/specs/spec-20260520-044700.md':
    sys.exit('V5(b) FAIL: wrong captured path: ' + repr(captured))
print('AC5-V5(b) PASS — captured:', captured)
PYEOF
