#!/usr/bin/env bash
# Final sweep — run inline AC checks and print PASS/FAIL summary.
set -u
TMPDIR_SELF=$(mktemp -d -t final-sweep-XXXXXX) || { echo "mktemp failed" >&2; exit 1; }
trap 'rm -rf "$TMPDIR_SELF" 2>/dev/null' EXIT INT TERM
PUSH_EXEC="$TMPDIR_SELF/push.sh.exec"
PHASE7_PY="$TMPDIR_SELF/push-analyst-phase7.py"
STEP7_MD="$TMPDIR_SELF/step7.md"
results=()

# AC7
miss=0
for f in agents/*.md; do
  role=$(basename "$f" .md)
  if grep -qE 'codex_required|Skill\(skill=["'"'"']codex["'"'"']\)|Skill\(name:codex\)|/codex\b|codex consultation|invoke codex|Skill\(codex\)' "$f"; then
    jq -e --arg r "$role" '.roles[$r].allowed_tools | (if type=="array" then index("Skill") else .Skill end) != null' policies/tool-policy.v1.json >/dev/null \
      || miss=$((miss+1))
  fi
done
[ "$miss" -eq 0 ] && results+=("AC7 V1 PASS") || results+=("AC7 V1 FAIL miss=$miss")
jq -e '.policy_version == 3' policies/tool-policy.v1.json >/dev/null && results+=("AC7 V3 PASS") || results+=("AC7 V3 FAIL")

# AC2
python3 -c "
import ast, sys
tree = ast.parse(open('hooks/tests/test_allowlist_consolidation.py').read())
required_substrings = ['success', 'failure', 'non_zero', 'malformed', 'comment_only', 'terminal_consume']
found = set()
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
        for dec in node.decorator_list:
            if hasattr(dec, 'attr') and dec.attr in ('skip', 'xfail', 'skipif'): sys.exit(2)
            if hasattr(dec, 'id') and dec.id in ('skip', 'xfail', 'skipif'): sys.exit(2)
        for s in required_substrings:
            if s in node.name: found.add(s)
sys.exit(0 if len(found) >= 4 else 1)
" && results+=("AC2 V2 PASS") || results+=("AC2 V2 FAIL")

python3 -m pytest hooks/tests/test_allowlist_consolidation.py -k 'success or failure or non_zero or malformed or comment_only or terminal_consume' --no-header -q >/dev/null 2>&1 && results+=("AC2 V3 PASS") || results+=("AC2 V3 FAIL")

# AC1 V1
sed -E 's/[[:space:]]*#.*$//' hooks/push.sh > "$PUSH_EXEC"
if awk '
  BEGIN { abort = 0 }
  /(^|[[:space:]]|;|&&|\|\|)exit[[:space:]]+[1-9]/ { abort = 1 }
  /(^|[[:space:]]|;|&&|\|\|)return[[:space:]]+[1-9]/ { abort = 1 }
  /(^|[[:space:]]|;|&&|\|\|)exec[[:space:]]+[^[:space:]]+push\.sh/ { abort = 1 }
  /(^|[[:space:]]|;|&&|\|\|)exec[[:space:]]+[^[:space:]]+/ { abort = 1 }
  /(^|[[:space:]]|;|&&|\|\||\$\(|\`)git[[:space:]]+push/ {
    if (!abort) exit 1
  }
  END { exit 0 }
' "$PUSH_EXEC" ; then
  results+=("AC1 V1 PASS")
else
  results+=("AC1 V1 FAIL")
fi
grep -qE '\.validated|REQUEST_ID.*sentinel|REQUEST_ID.*\.sentinel' hooks/push.sh && results+=("AC1 V2 PASS") || results+=("AC1 V2 FAIL")
grep -qE 'trap[[:space:]]+.+EXIT' hooks/push.sh && results+=("AC1 V3 PASS") || results+=("AC1 V3 FAIL")
grep -qE 'single.process|validator wrapper|exec[[:space:]]+.*push\.sh' commands/push.md && results+=("AC1 V4 PASS") || results+=("AC1 V4 FAIL")
bash hooks/tests/test_push_sentinel_abort.sh >/dev/null 2>&1 && results+=("AC1 V5 PASS") || results+=("AC1 V5 FAIL")

# AC4
grep -qE '^PUSH_ANALYST_GRANT_TTL_SECONDS[[:space:]]*=[[:space:]]*600[[:space:]]*$' agents/push-analyst.md && results+=("AC4 V1 PASS") || results+=("AC4 V1 FAIL")
awk '/^```python$/,/^```$/' agents/push-analyst.md | grep -v '^```' > "$PHASE7_PY"
python3 - "$PHASE7_PY" <<'PYEOF' && results+=("AC4 V2 PASS") || results+=("AC4 V2 FAIL")
import ast, sys
tree = ast.parse(open(sys.argv[1]).read())
const_assigns = [n for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'PUSH_ANALYST_GRANT_TTL_SECONDS' for t in n.targets)]
assert len(const_assigns) == 1
val = const_assigns[0].value
assert isinstance(val, ast.Constant) and val.value == 600
import_aliases = {'timedelta'}
for n in ast.walk(tree):
    if isinstance(n, ast.alias) and n.asname: import_aliases.add(n.asname)
for n in ast.walk(tree):
    if isinstance(n, ast.Call):
        func_name = None
        if isinstance(n.func, ast.Name): func_name = n.func.id
        elif isinstance(n.func, ast.Attribute): func_name = n.func.attr
        if func_name in import_aliases:
            for kw in n.keywords:
                assert isinstance(kw.value, ast.Name) and kw.value.id == 'PUSH_ANALYST_GRANT_TTL_SECONDS'
PYEOF
grep -qE '600[[:space:]]*(s|seconds?)|TTL.*600|PUSH_ANALYST_GRANT_TTL_SECONDS.*600' commands/push.md && results+=("AC4 V3 PASS") || results+=("AC4 V3 FAIL")
grep -qF 'GRANT_TTL_MINUTES = 30' scripts/write-commit-grant.py && results+=("AC4 V4 PASS") || results+=("AC4 V4 FAIL")

# AC5
awk '
  /^#{2,3}[[:space:]]+Step 8/ { in_section = 1; print; next }
  /^#{2,3}[[:space:]]+Step [0-9]/ && in_section { in_section = 0 }
  in_section { print }
' commands/commit.md > "$STEP7_MD"
if awk '
  /context\.spec_path first/ { if (!s1) s1 = NR }
  /\(2\)[[:space:]]*Continuation spec/ { if (!s2) s2 = NR }
  /(mtime[[:space:]]*\+[[:space:]]*literal-task-id|mtime.*close.report.*24h|mtime.*\[close.report)/ { if (!s3) s3 = NR }
  /spec produced this cycle but not linked in context/ { if (!s4a) s4a = NR }
  /multiple specs produced this cycle without context linkage/ { if (!s4b) s4b = NR }
  END {
    if (!s1 || !s2 || !s3 || !s4a || !s4b) exit 1
    if (!(s1 < s2 && s2 < s3 && s3 < s4a && s3 < s4b)) exit 1
    exit 0
  }
' "$STEP7_MD"; then
  results+=("AC5 V1 PASS")
else
  results+=("AC5 V1 FAIL")
fi
grep -qE 'fence-aware|fenced code block|skip ranges between' "$STEP7_MD" && results+=("AC5 V2 PASS") || results+=("AC5 V2 FAIL")
grep -qiE 'dev chooses|one of:|either.*mtime.*or.*filename|pick latest|prefer newest|select any|most recent wins|any matching|the right one' "$STEP7_MD" && results+=("AC5 V3 FAIL") || results+=("AC5 V3 PASS")
grep -qF "spec produced this cycle but not linked in context" commands/commit.md \
  && grep -qF "multiple specs produced this cycle without context linkage" commands/commit.md \
  && results+=("AC5 V4 PASS") || results+=("AC5 V4 FAIL")
grep -qF 'Continuation spec(\s*\([^)]*\))?\s*:' "$STEP7_MD" \
  && grep -qE '\^\[-\*\+\]\?|markdown list marker|list marker|bullet' "$STEP7_MD" \
  && grep -qF '`?(docs/dev/specs/spec-' "$STEP7_MD" \
  && python3 -c "
import re, sys
line = open('docs/dev/close-report-20260519-175339.md').read().splitlines()[150]
expected = '- Continuation spec (from prior NO): \`docs/dev/specs/spec-20260520-044700.md\`'
assert line == expected
pattern = r'^[-*+]?\s*Continuation spec(\s*\([^)]*\))?\s*:\s*\`?(docs/dev/specs/spec-[^\s\`]+\.md)\`?\s*\$'
m = re.match(pattern, line)
assert m and m.group(2) == 'docs/dev/specs/spec-20260520-044700.md'
" && results+=("AC5 V5 PASS") || results+=("AC5 V5 FAIL")

# AC6
PHR='if dev verification recipe differs from AC literal text, raise spec_text_vs_execution_drift regardless of equivalence judgment'
secs=$(awk -v PH="$PHR" '
  BEGIN { in_fence=0; section="" }
  /^```/ { in_fence = !in_fence; next }
  in_fence { next }
  /^## / { section = $0 }
  index($0, PH) > 0 { sections[section]++ }
  END { c = 0; for (s in sections) c++; print c }
' agents/qa.md)
[ "$secs" -ge 2 ] && results+=("AC6 V1 PASS ($secs sections)") || results+=("AC6 V1 FAIL ($secs sections)")
n=$(grep -nF -A5 "$PHR" agents/qa.md | grep -E 'MUST raise a blocking objection|verdict MUST be FAIL|MUST NOT downgrade to warning|is a blocking BA.validation objection' | wc -l)
[ "$n" -ge 2 ] && results+=("AC6 V4 PASS") || results+=("AC6 V4 FAIL ($n matches)")

# AC3
PHRASE='TodoWrite mark-as-in_progress for step N must precede any Agent() call dispatched within step N'
grep -qF "$PHRASE" commands/close.md && grep -qF "$PHRASE" commands/dev.md && results+=("AC3 V1 PASS") || results+=("AC3 V1 FAIL")
grep -F -A3 "$PHRASE" commands/close.md | grep -qE 'MUST|REQUIRED|Always|Before dispatch' \
  && grep -F -A3 "$PHRASE" commands/dev.md | grep -qE 'MUST|REQUIRED|Always|Before dispatch' \
  && results+=("AC3 V3 PASS") || results+=("AC3 V3 FAIL")

# AC9
awk '
  BEGIN { in_fence=0; in_phase6=0; found=0 }
  /^```/ { in_fence = !in_fence; next }
  in_fence { next }
  /^### Phase 6/ { in_phase6 = 1; next }
  /^### Phase 7/ { in_phase6 = 0 }
  in_phase6 && /Reverses <SHA>: <one-line rationale for why prior reasoning no longer holds>/ { found = 1 }
  END { exit found ? 0 : 1 }
' agents/changelog-analyst.md && results+=("AC9 V1 PASS") || results+=("AC9 V1 FAIL")
jq -e '.affected_files | index("agents/changelog-analyst.md") != null' docs/dev/context-20260519-211515.json >/dev/null && results+=("AC9 V4 PASS") || results+=("AC9 V4 FAIL")

# AC10
grep -qF "### Verification harness cleanup contract (MANDATORY)" agents/qa.md && results+=("AC10 V1 PASS") || results+=("AC10 V1 FAIL")
n=$(git diff d988d4a -- docs/dev/specs/spec-20260520-044700.md | wc -l)
[ "$n" -eq 0 ] && results+=("AC10 V4 PASS (zero diff)") || results+=("AC10 V4 FAIL ($n diff lines)")

# V_TW
jq -e '._test_writer_skip_reason | type == "string" and length > 0' docs/dev/context-20260519-211515.json >/dev/null \
  && grep -qE '_test_writer_skip_reason|test.writer.*skip|skip.*test.writer' commands/dev.md \
  && results+=("V_TW PASS") || results+=("V_TW FAIL")

printf '%s\n' "${results[@]}"
