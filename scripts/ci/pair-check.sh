#!/usr/bin/env bash
# Description: Pair check between two open PRs (P15 lane L12, plan section 2(f)). Builds the
#   mechanical merge of two heads with `git merge-tree --write-tree` (an object in the local
#   object store only: no ref is written, no commit is made, nothing is pushed), extracts that
#   tree into a scratch directory, and runs the union of both PRs' changed test files there.
#   Each PR's CI judges its own head; this judges the two together, which is where a semantic
#   conflict (one PR adds a rule, the other adds a case breaking it) first shows.
# Usage: bash scripts/ci/pair-check.sh [--base REF] [--out DIR] [--python PY] [--timeout SEC] HEAD_A HEAD_B
#   --base     the branch both PRs target (default origin/master, else the merge base of the
#              heads). Each PR's changed files are those of merge-base(base, head)..head.
#   --out      directory for result.json and summary.md (default: a scratch dir, printed).
#   --python   interpreter whose pytest runs the tests (default python3).
#   --timeout  seconds for the test run (default 1800).
# Test files: any changed, still-present file named test_*.py or *_test.py (run by pytest in
#   one session) or test_*.sh (each run by bash). A test file with textual merge conflicts is
#   reported as conflicted and not run: it holds conflict markers, so its result means nothing.
# Exit codes / result.json "status":
#   0 green     every test of the union passed, no textual conflict
#   1 failed    a test of the union failed or errored (failures listed by node id)
#   2 conflict  the heads conflict textually and nothing that ran failed
#   3 error     bad usage, a git error, or a test run that did not finish (timeout, crash)
#   4 no-tests  neither PR changes a test file and the heads merge cleanly

set -uo pipefail

usage() { sed -n '8,12p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 3; }

BASE="" OUT="" PY="python3" TIMEOUT=1800
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="${2:?--base needs a ref}"; shift 2 ;;
    --out) OUT="${2:?--out needs a directory}"; shift 2 ;;
    --python) PY="${2:?--python needs an interpreter}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?--timeout needs seconds}"; shift 2 ;;
    -h|--help) usage ;;
    --) shift; break ;;
    -*) echo "pair-check: unknown option $1" >&2; usage ;;
    *) break ;;
  esac
done
[ $# -eq 2 ] || usage

die() { echo "pair-check: $*" >&2; exit 3; }
A="$(git rev-parse --verify --quiet "$1^{commit}")" || die "not a commit: $1"
B="$(git rev-parse --verify --quiet "$2^{commit}")" || die "not a commit: $2"
if [ -z "$BASE" ]; then
  if git rev-parse --verify --quiet origin/master >/dev/null; then BASE=origin/master; else BASE="$(git merge-base "$A" "$B")" || die "no merge base"; fi
fi
BASE_C="$(git rev-parse --verify --quiet "$BASE^{commit}")" || die "not a commit: $BASE"

[ -n "$OUT" ] || OUT="$(mktemp -d "${TMPDIR:-/tmp}/pair-check-out.XXXXXX")"
mkdir -p "$OUT" || die "cannot create $OUT"
OUT="$(cd "$OUT" && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/pair-check-tree.XXXXXX")" || die "cannot create a scratch dir"
trap 'rm -rf "$WORK"' EXIT

# The merged tree. Exit 0 = clean, 1 = textual conflicts (the tree carries conflict markers),
# anything else = git could not merge at all.
mt="$(git merge-tree --write-tree --name-only --no-messages "$A" "$B")"; mt_rc=$?
[ "$mt_rc" -le 1 ] || die "git merge-tree failed (exit $mt_rc); git 2.38 or later is required"
TREE="$(printf '%s\n' "$mt" | head -n1)"
printf '%s\n' "$mt" | tail -n +2 | sed '/^$/d' | sort -u > "$OUT/conflicts.txt"

is_test() { case "${1##*/}" in test_*.py|*_test.py|test_*.sh) return 0 ;; esac; return 1; }
: > "$OUT/union.txt"
for head in "$A" "$B"; do
  mb="$(git merge-base "$BASE_C" "$head")" || die "no merge base of $BASE and $head"
  git diff --name-only --no-renames --diff-filter=d "$mb" "$head" | while IFS= read -r f; do
    is_test "$f" && printf '%s\n' "$f"
  done >> "$OUT/union.txt"
done
sort -u -o "$OUT/union.txt" "$OUT/union.txt"
: > "$OUT/run.txt"; : > "$OUT/conflicted-tests.txt"
while IFS= read -r f; do
  [ -n "$f" ] || continue
  if grep -qxF -- "$f" "$OUT/conflicts.txt"; then echo "$f" >> "$OUT/conflicted-tests.txt"
  elif git cat-file -e "$TREE:$f" 2>/dev/null; then echo "$f" >> "$OUT/run.txt"; fi
done < "$OUT/union.txt"

# The scratch copy is a git repository of its own that borrows this repository's objects (an
# alternates file, no copy; a shallow boundary is carried over) and is checked out at a merge
# commit of A and B made there, so tests that read history (git log, A^1, git ls-files) see what a
# real merge would give them. Its commit and HEAD live in the scratch dir; this repository gets
# no ref.
OBJ="$(cd "$(git rev-parse --git-path objects)" && pwd)" || die "cannot find the object store"
SHALLOW="$(git rev-parse --git-path shallow)"
git init -q "$WORK" || die "cannot init the scratch dir"
echo "$OBJ" > "$WORK/.git/objects/info/alternates"
[ -f "$SHALLOW" ] && cp "$SHALLOW" "$WORK/.git/shallow"
MERGE="$(cd "$WORK" && GIT_AUTHOR_NAME=pair-check GIT_AUTHOR_EMAIL=pair-check@localhost \
  GIT_COMMITTER_NAME=pair-check GIT_COMMITTER_EMAIL=pair-check@localhost \
  git -c commit.gpgsign=false commit-tree "$TREE" -p "$A" -p "$B" -m "pair-check merged tree")" \
  || die "cannot make the merge commit"
( cd "$WORK" && git -c advice.detachedHead=false -c core.hooksPath=/dev/null checkout -q --detach "$MERGE" ) \
  || die "cannot check out the merged tree"

pytest_rc=0 sh_failed=0 ran_error=0
: > "$OUT/failed.txt"
grep '\.py$' "$OUT/run.txt" > "$OUT/run-py.txt"
grep '\.sh$' "$OUT/run.txt" > "$OUT/run-sh.txt"
if [ -s "$OUT/run-py.txt" ]; then
  xdist=()
  "$PY" -c 'import xdist' 2>/dev/null && xdist=(-n auto --dist loadfile)
  mapfile -t pyfiles < "$OUT/run-py.txt"
  ( cd "$WORK" && PYTHONDONTWRITEBYTECODE=1 timeout "$TIMEOUT" "$PY" -m pytest -p no:cacheprovider \
      -q -rfE "${xdist[@]}" -- "${pyfiles[@]}" ) > "$OUT/pytest.log" 2>&1
  pytest_rc=$?
  # Short test summary lines: "FAILED <nodeid> - <message>" / "ERROR <nodeid> - <message>".
  # A parametrized id may hold spaces inside its brackets.
  sed -n -E -e 's/^(FAILED|ERROR) ([^ []+\[.*\])( - .*)?$/\2/p;t' -e 's/^(FAILED|ERROR) ([^ ]+)( - .*)?$/\2/p' \
    "$OUT/pytest.log" | sort -u >> "$OUT/failed.txt"
  case "$pytest_rc" in
    0|5) ;;
    1) [ -s "$OUT/failed.txt" ] || ran_error=1 ;;
    *) ran_error=1 ;;
  esac
fi
while IFS= read -r f; do
  [ -n "$f" ] || continue
  ( cd "$WORK" && timeout "$TIMEOUT" bash "$f" ) >> "$OUT/shell.log" 2>&1 || { echo "$f" >> "$OUT/failed.txt"; sh_failed=1; }
done < "$OUT/run-sh.txt"

if [ "$ran_error" -eq 1 ]; then status=error rc=3
elif [ -s "$OUT/failed.txt" ]; then status=failed rc=1
elif [ -s "$OUT/conflicts.txt" ]; then status=conflict rc=2
elif [ -s "$OUT/run.txt" ]; then status=green rc=0
else status=no-tests rc=4; fi

STATUS="$status" A="$A" B="$B" BASE_C="$BASE_C" TREE="$TREE" PYTEST_RC="$pytest_rc" OUT="$OUT" "$PY" - <<'PYEOF' || die "cannot write result.json"
import json, os
out = os.environ["OUT"]
def lines(name):
    try:
        with open(os.path.join(out, name)) as fh:
            return [l.rstrip("\n") for l in fh if l.strip()]
    except FileNotFoundError:
        return []
result = {
    "status": os.environ["STATUS"], "head_a": os.environ["A"], "head_b": os.environ["B"],
    "base": os.environ["BASE_C"], "merged_tree": os.environ["TREE"],
    "conflicts": lines("conflicts.txt"), "conflicted_tests": lines("conflicted-tests.txt"),
    "tests_run": lines("run.txt"), "failed": lines("failed.txt"),
    "pytest_exit": int(os.environ["PYTEST_RC"]),
}
with open(os.path.join(out, "result.json"), "w") as fh:
    json.dump(result, fh, indent=2)
s = [f"Pair check of {result['head_a'][:12]} + {result['head_b'][:12]} (base {result['base'][:12]}): **{result['status']}**", ""]
if result["failed"]:
    s += ["Failing on the merged tree:", ""] + [f"- `{n}`" for n in result["failed"]] + [""]
if result["conflicts"]:
    s += ["Textual conflicts (a conflicted test file is not run):", ""] + [f"- `{n}`" for n in result["conflicts"]] + [""]
s += [f"Test files run ({len(result['tests_run'])}):", ""] + [f"- `{n}`" for n in result["tests_run"]]
with open(os.path.join(out, "summary.md"), "w") as fh:
    fh.write("\n".join(s) + "\n")
PYEOF
cat "$OUT/summary.md"
echo "pair-check: $status (results in $OUT)"
exit "$rc"
