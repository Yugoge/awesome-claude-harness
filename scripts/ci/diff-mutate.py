#!/usr/bin/env python3
"""Diff-scoped mutation: do the tests check the lines this change made? (P15 decision (b)).

Mutates only the changed lines (``git diff -U0 <base>`` against the working tree) of
``hooks/**/*.py`` and ``scripts/**/*.py``, one mutant at a time, spliced in place and restored
after each run. Each mutant runs the change's own changed unit tests plus every unit test file that names
the mutated file (``<stem>.py``, a ``lib.<stem>``-style path or module, an import of ``<stem>``).
A mutant the tests do not fail is a survivor: a changed line no test checks. Report-only: survivors are printed as ``SURVIVED <file>:<line> <operator>`` and the exit
status is 0; it is 2 only when the script cannot judge (git error, the unmutated run is red).

Operators: ``compare`` (== != < <= > >= in is swapped for their negation), ``boolean`` (and/or
swapped, a ``not`` removed), ``constant`` (True/False flipped, an int n made n+1, a string
emptied or filled), ``return-value`` (a returned value made None). Equivalent mutants are
avoided by operator, never by a list: no docstring, annotation or f-string part is mutated, and
neither is an index argument of ``sys.path`` (``sys.path.insert(0, ..)``, ``sys.path[0]``).

Bounds: at most ``--max-mutants`` (40) per run, spread so every changed line gets a mutant before
any line gets a second; each mutant's run is ``pytest -x`` with a timeout of ``--timeout-factor``
(4) times the unmutated run; a mutant that times out counts as killed. ``--shard i/n`` runs the
i-th of n disjoint parts of the selection, for parallel jobs on separate checkouts.
"""
from __future__ import annotations

import argparse
import ast
import copy
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

TARGET_ROOTS = ("hooks", "scripts")
TEST_ROOTS = ("hooks/tests", "tests")
# What the unit step of baseline.yml leaves out: the replay suites, run by their own sharded jobs. A mutant
# never runs them (plan P15 (b): about 23 shard-minutes a mutant), so a mutant runs only unit tests.
REPLAY_SUITES = ("tests/generated/", "tests/replay/", "tests/test_artifact_graph.py", "tests/artifact_graph/test_mutations.py")
MAX_MUTANTS = 40
TIMEOUT_FACTOR = 4.0
OPERATOR_ORDER = ("compare", "boolean", "return-value", "constant")
NEGATE = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE,
          ast.LtE: ast.Gt, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")


@dataclass
class Mutant:
    path: str
    line: int
    operator: str
    detail: str
    source: bytes


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def is_unit_test(path: str) -> bool:
    return path.rsplit("/", 1)[-1].startswith("test_") and not path.startswith(REPLAY_SUITES)


def is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return "tests" in path.split("/")[:-1] or name.startswith("test_") or name == "conftest.py"


def changed_lines(base: str, only: list[str] | None = None) -> dict[str, set[int]]:
    """{path: added or modified line numbers} of the working tree against base, for target files."""
    out, path = {}, None
    for line in git("diff", "-U0", "--no-color", "--no-ext-diff", base, "--", *(only or TARGET_ROOTS)).splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            path = path if path and path.split("/", 1)[0] in TARGET_ROOTS and path.endswith(".py") and not is_test(path) else None
        elif path and (m := HUNK.match(line)):
            start, count = int(m.group(1)), int(m.group(2) or 1)
            out.setdefault(path, set()).update(range(start, start + count))
    return {p: lines for p, lines in out.items() if lines and Path(p).is_file()}


def changed_tests(base: str) -> list[str]:
    names = git("diff", "--name-only", "--diff-filter=AMR", base, "--", "*.py").splitlines()
    return [p for p in names if is_unit_test(p) and Path(p).is_file()]


def tests_naming(stem: str) -> list[str]:
    """Test files that name the file: as ``<stem>.py``, as a ``lib.``/``hooks/``/``scripts/`` path or module, or in an import."""
    s = re.escape(stem)
    patterns = [re.compile(r"(?<![\w-])" + s + r"\.py\b"),
                re.compile(r"(?<![\w-])(?:lib|hooks|scripts)[./]" + s + r"(?![\w-])"),
                re.compile(r"^\s*(?:from\s+\S+\s+)?import\s+[^\n#]*(?<![\w-])" + s + r"(?![\w-])", re.M)]
    found = []
    for root in TEST_ROOTS:
        for test in sorted(Path(root).rglob("test_*.py")):
            text = test.read_text(encoding="utf-8", errors="replace")
            if is_unit_test(test.as_posix()) and any(p.search(text) for p in patterns):
                found.append(test.as_posix())
    return found


def _is_sys_path(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "path"
            and isinstance(node.value, ast.Name) and node.value.id == "sys")


def _skipped(tree: ast.AST) -> set[int]:
    """ids of nodes no operator touches: docstrings, annotations, f-string parts, sys.path indexes."""
    roots: list[ast.AST] = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            roots.append(body[0].value)
        if isinstance(node, ast.JoinedStr):
            roots.append(node)
        for field in ("annotation", "returns"):
            if getattr(node, field, None) is not None:
                roots.append(getattr(node, field))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and _is_sys_path(node.func.value):
            roots.extend(node.args[:1] if node.func.attr in ("insert", "pop") else [])
        if isinstance(node, ast.Subscript) and _is_sys_path(node.value):
            roots.append(node.slice)
    return {id(sub) for root in roots for sub in ast.walk(root)}


def _variants(node: ast.AST):
    """(operator, detail, replacement node, node replaced) for one AST node."""
    if isinstance(node, ast.Compare):
        for k, op in enumerate(node.ops):
            new = copy.deepcopy(node)
            new.ops[k] = NEGATE[type(op)]()
            yield "compare", f"{type(op).__name__} -> {type(new.ops[k]).__name__}", new, node
    elif isinstance(node, ast.BoolOp):
        new = copy.deepcopy(node)
        new.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        yield "boolean", f"{type(node.op).__name__} -> {type(new.op).__name__}", new, node
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        yield "boolean", "not removed", node.operand, node
    elif isinstance(node, ast.Return) and node.value is not None and not (
            isinstance(node.value, ast.Constant) and node.value.value is None):
        yield "return-value", f"{ast.unparse(node.value)[:40]} -> None", ast.Constant(None), node.value
    elif isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            yield "constant", f"{value} -> {not value}", ast.Constant(not value), node
        elif isinstance(value, int):
            yield "constant", f"{value} -> {value + 1}", ast.Constant(value + 1), node
        elif isinstance(value, str):
            new = "" if value else "x"
            yield "constant", f"{value[:20]!r} -> {new!r}", ast.Constant(new), node


def _splice(source: bytes, starts: list[int], old: ast.AST, new: ast.AST) -> bytes:
    """Replace old's source span with new, in parentheses, keeping every later line number."""
    begin = starts[old.lineno - 1] + old.col_offset
    end = starts[old.end_lineno - 1] + old.end_col_offset
    text = "(" + ast.unparse(new) + "\n" * (old.end_lineno - old.lineno) + ")"
    return source[:begin] + text.encode("utf-8") + source[end:]


def mutants_for(path: str, lines: set[int]) -> list[Mutant]:
    source = Path(path).read_bytes()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    starts, offset = [], 0
    for raw in source.splitlines(keepends=True):
        starts.append(offset)
        offset += len(raw)
    skip, out = _skipped(tree), []
    for node in ast.walk(tree):
        if getattr(node, "lineno", None) not in lines or id(node) in skip:
            continue
        for operator, detail, new, old in _variants(node):
            mutated = _splice(source, starts, old, new)
            try:
                ast.parse(mutated)
            except SyntaxError:
                continue
            out.append(Mutant(path, node.lineno, operator, detail, mutated))
    return sorted(out, key=lambda m: (m.line, OPERATOR_ORDER.index(m.operator)))


def select(mutants: list[Mutant], cap: int) -> list[Mutant]:
    """At most cap mutants: round by round, one more per changed line; a round that does not fit is
    thinned evenly across the changed lines, never cut at the end of the diff."""
    by_line: dict[tuple[str, int], list[Mutant]] = {}
    for m in mutants:
        by_line.setdefault((m.path, m.line), []).append(m)
    chosen, depth = [], 0
    while len(chosen) < cap and any(len(group) > depth for group in by_line.values()):
        this_round = [group[depth] for group in by_line.values() if len(group) > depth]
        room = cap - len(chosen)
        if len(this_round) > room:
            this_round = [this_round[k * len(this_round) // room] for k in range(room)]
        chosen += this_round
        depth += 1
    return chosen


def pytest_command(python: str, tests: list[str]) -> list[str]:
    """pytest -x, serial: under xdist -x waits for every worker's files, so a killed mutant would cost a whole run."""
    return [python, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *tests]


def run_tests(command: list[str], env: dict, timeout: float | None) -> str:
    """'pass', 'fail' or 'timeout' for one run of the selected tests."""
    proc = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    try:
        return "pass" if proc.wait(timeout=timeout) == 0 else "fail"
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        return "timeout"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--base", required=True, help="revision the change is diffed against")
    ap.add_argument("--max-mutants", type=int, default=MAX_MUTANTS)
    ap.add_argument("--timeout-factor", type=float, default=TIMEOUT_FACTOR)
    ap.add_argument("--python", default=sys.executable, help="interpreter that runs pytest")
    ap.add_argument("--shard", default="1/1", help="i/n: run every n-th selected mutant from the i-th (parallel jobs on separate checkouts)")
    ap.add_argument("--list", action="store_true", help="print the selected mutants and run nothing")
    ap.add_argument("paths", nargs="*", help="limit the mutated files to these paths (still only hooks/ and scripts/)")
    args = ap.parse_args(argv)
    try:
        os.chdir(git("rev-parse", "--show-toplevel").strip())
        targets, own_tests = changed_lines(args.base, args.paths), changed_tests(args.base)
    except subprocess.CalledProcessError as exc:
        print(f"diff-mutate: git failed: {exc.stderr.strip()}", file=sys.stderr)
        return 2
    candidates = [m for path, lines in sorted(targets.items()) for m in mutants_for(path, lines)]
    index, _, count = args.shard.partition("/")
    if not (index.isdigit() and count.isdigit() and 1 <= int(index) <= int(count)):
        ap.error("--shard takes i/n with 1 <= i <= n")
    chosen = select(candidates, args.max_mutants)[int(index) - 1::int(count)]
    print(f"diff-mutate: base {args.base}; {len(targets)} file(s), {len(candidates)} candidate mutant(s), "
          f"{len(chosen)} selected (cap {args.max_mutants}, shard {args.shard})")
    if args.list:
        for m in chosen:
            print(f"MUTANT   {m.path}:{m.line} {m.operator} ({m.detail})")
        return 0
    tests_for = {path: sorted(set(own_tests) | set(tests_naming(Path(path).stem))) for path in targets}
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(2))
    counts = {"killed": 0, "survived": 0, "timeout": 0, "untested": 0}
    with tempfile.TemporaryDirectory(prefix="diff-mutate-pyc-") as pyc:
        # No bytecode is read or written: a same-size mutant in the same second must not run a stale .pyc.
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": pyc}
        baselines: dict[tuple[str, ...], float] = {}
        for m in chosen:
            tests = tests_for[m.path]
            if not tests:
                counts["untested"] += 1
                print(f"UNTESTED {m.path}:{m.line} {m.operator} ({m.detail})")
                continue
            command = pytest_command(args.python, tests)
            if tuple(tests) not in baselines:
                began = time.monotonic()
                red = subprocess.run(command, env=env, capture_output=True, text=True)
                if red.returncode != 0:
                    print(f"diff-mutate: the unmutated tests fail: {' '.join(command)}", file=sys.stderr)
                    print("\n".join(red.stdout.splitlines()[-15:]), file=sys.stderr)
                    return 2
                baselines[tuple(tests)] = time.monotonic() - began
                print(f"diff-mutate: {len(tests)} test file(s) for {m.path}; unmutated run "
                      f"{baselines[tuple(tests)]:.1f}s, timeout {args.timeout_factor * baselines[tuple(tests)]:.1f}s")
            original = Path(m.path).read_bytes()
            try:
                Path(m.path).write_bytes(m.source)
                result = run_tests(command, env, args.timeout_factor * baselines[tuple(tests)])
            finally:
                Path(m.path).write_bytes(original)
            word = {"pass": "SURVIVED", "fail": "KILLED", "timeout": "TIMEOUT"}[result]
            counts[{"pass": "survived", "fail": "killed", "timeout": "timeout"}[result]] += 1
            print(f"{word:<8} {m.path}:{m.line} {m.operator} ({m.detail})", flush=True)
    print("diff-mutate: " + ", ".join(f"{n} {k}" for k, n in counts.items()) + " (report only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
