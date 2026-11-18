#!/usr/bin/env python3
"""Red then green: show that a change's tests fail before it and pass after it.

Given a base and a head, the script finds their merge base and judges the diff merge-base..head:

- A diff that touches only tests (``test_*.py``, ``conftest.py``) and docs (``docs/``, ``*.md``,
  ``*.rst``, ``*.txt``) is exempt by path.
- Otherwise every changed ``test_*.py`` of the head, and every test id a ``Red-test: <nodeid>`` trailer
  names, runs twice, each in a real checkout (tests that read history need one; a ``git archive`` tree
  gives false failures):
  red: the merge base with only the head's changed ``test_*.py`` and ``conftest.py`` laid over it, so
  test helpers and fixtures stay the base's; green: the head.
- A ``Red-test: none: <reason>`` trailer says no red is possible; its reason is printed first in the
  summary and nothing runs, since the reason alone passes the job.

Trailers are read from the trailer block of each commit message of merge-base..head, and from any line
of ``--body-file`` (a PR body).

Output: a markdown summary on stdout (and in ``--summary`` when given), one row per test id. A collection
error on red counts as red, and is reported apart from a failing assertion. Exit 0 when some id goes red
then green, when the diff is exempt, or when a ``none`` trailer is present; 1 otherwise; 2 on a usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

DOC_SUFFIXES = (".md", ".rst", ".txt")
TRAILER_RE = re.compile(r"^[ \t]*Red-test:[ \t]*(.+?)[ \t]*$", re.MULTILINE | re.IGNORECASE)
NONE_RE = re.compile(r"^none\s*:\s*(.*)$", re.IGNORECASE)

# A pytest plugin written next to the run: it records each test id's outcome per phase, and each
# collection error, as JSON lines in the file RED_GREEN_REPORT names.
PLUGIN = '''
import json, os

def _write(rec):
    with open(os.environ["RED_GREEN_REPORT"], "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\\n")

def pytest_runtest_logreport(report):
    _write({"kind": "test", "nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
            "xfail": hasattr(report, "wasxfail")})

def pytest_collectreport(report):
    if report.failed:
        text = str(report.longrepr).strip().splitlines()
        _write({"kind": "collect", "nodeid": report.nodeid, "message": text[-1] if text else ""})
'''


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"red-green: git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return name == "conftest.py" or (name.startswith("test_") and name.endswith(".py"))


def is_doc_file(path: str) -> bool:
    return path.startswith("docs/") or path.lower().endswith(DOC_SUFFIXES)


def read_trailers(text: str) -> tuple[list[str], list[str]]:
    """Return (test ids, none reasons) from every ``Red-test:`` line of ``text``."""
    ids: list[str] = []
    reasons: list[str] = []
    for value in TRAILER_RE.findall(text):
        m = NONE_RE.match(value)
        if m:
            reasons.append(m.group(1).strip() or "(no reason given)")
        elif value not in ids:
            ids.append(value)
    return ids, reasons


def checkout(repo: Path, commit: str, dest: Path) -> None:
    """A real checkout of ``commit`` at ``dest``: a shared clone, so history is there and nothing is copied."""
    for args in (["clone", "--quiet", "--shared", "--no-checkout", str(repo), str(dest)],
                 ["-C", str(dest), "checkout", "--quiet", "--detach", commit]):
        r = subprocess.run(["git", *args], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"red-green: git {' '.join(args)} failed: {r.stderr.strip()}")


def run_target(tree: Path, target: str, plugin_dir: Path, python: str, timeout: int) -> dict:
    """Run one test file or id in ``tree``; return {"tests": {id: outcome}, "collect": [...], "rc": int}."""
    report = Path(tempfile.mkstemp(prefix="rg-", suffix=".jsonl", dir=plugin_dir)[1])
    env = dict(os.environ, RED_GREEN_REPORT=str(report), PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=os.pathsep.join(p for p in (str(plugin_dir), os.environ.get("PYTHONPATH", "")) if p))
    cmd = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", "-p", "red_green_plugin",
           "-o", "addopts=", target]
    try:
        r = subprocess.run(cmd, cwd=tree, env=env, capture_output=True, text=True, timeout=timeout)
        rc, tail = r.returncode, (r.stdout + r.stderr).strip().splitlines()[-1:]
    except subprocess.TimeoutExpired:
        rc, tail = -1, [f"timed out after {timeout}s"]
    tests: dict[str, str] = {}
    collect: list[dict] = []
    for line in report.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec["kind"] == "collect":
            collect.append(rec)
            continue
        nodeid, when, outcome = rec["nodeid"], rec["when"], rec["outcome"]
        if rec["xfail"]:
            outcome = "xfailed" if outcome == "skipped" else "xpassed"
        elif outcome == "failed" and when != "call":
            outcome = "error"
        # The call's outcome is the test's; a setup or teardown failure makes it an error.
        if outcome == "error" or (when == "call" and tests.get(nodeid) != "error"):
            tests[nodeid] = outcome
        elif when == "setup" or nodeid not in tests:
            tests.setdefault(nodeid, outcome)
    report.unlink()
    if rc not in (0, 1) and not tests and not collect:
        collect.append({"kind": "collect", "nodeid": target, "message": f"pytest exit {rc}: {' '.join(tail)}"})
    return {"tests": tests, "collect": collect, "rc": rc}


def verdict_for(red: str | None, red_collect: bool, green: str | None) -> str:
    if green != "passed":
        return f"not green ({green or 'not collected'})"
    if red == "failed":
        return "red then green"
    if red == "error":
        return "red then green (error on red)"
    if red is None and red_collect:
        return "red then green (collection error on red)"
    if red is None:
        return "not red (not collected on red)"
    return f"not red ({red} on red)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True, help="the base commit-ish (a PR's target branch)")
    ap.add_argument("--head", required=True, help="the head commit-ish")
    ap.add_argument("--repo", default=".", help="the repository (default: the current directory)")
    ap.add_argument("--body-file", help="a file (a PR body) whose Red-test: lines count as trailers")
    ap.add_argument("--summary", help="also write the markdown summary to this file")
    ap.add_argument("--python", default=sys.executable, help="the interpreter that runs pytest")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds per pytest run (default 1800)")
    args = ap.parse_args(argv)

    repo = Path(git(Path(args.repo), "rev-parse", "--show-toplevel").strip())
    base = git(repo, "rev-parse", "--verify", f"{args.base}^{{commit}}").strip()
    head = git(repo, "rev-parse", "--verify", f"{args.head}^{{commit}}").strip()
    mb = git(repo, "merge-base", base, head).strip()

    changed = [p for p in git(repo, "diff", "--name-only", "--no-renames", mb, head).splitlines() if p]
    present = [p for p in git(repo, "diff", "--name-only", "--no-renames", "--diff-filter=d", mb, head).splitlines()
               if p]
    # A commit's trailers are those git parses from its last paragraph; a body line that only starts
    # with "Red-test:" (a wrapped sentence) is not one.
    text = "".join(f"Red-test: {v}\n" for v in git(
        repo, "log", "--format=%(trailers:key=Red-test,valueonly,unfold)", f"{mb}..{head}").splitlines() if v.strip())
    if args.body_file:
        text += "\n" + Path(args.body_file).read_text(encoding="utf-8")
    ids, reasons = read_trailers(text)

    out: list[str] = []
    for reason in reasons:
        out.append(f"**Red-test: none:** {reason}")
    if reasons:
        out.append("")
    out += ["## Red then green", "",
            f"Base `{base[:12]}`, head `{head[:12]}`, merge base `{mb[:12]}`; {len(changed)} changed file(s).", ""]

    exempt = all(is_test_file(p) or is_doc_file(p) for p in changed)
    overlay = [p for p in present if is_test_file(p)]
    targets = [p for p in overlay if PurePosixPath(p).name != "conftest.py"] + [i for i in ids if i not in overlay]

    rows: list[tuple[str, str, str, str]] = []
    collect_errors: list[str] = []
    if exempt:
        status = "exempt: the diff changes only tests and docs"
    elif reasons:
        status = "exempt: Red-test: none"
    elif not targets:
        status = "no red: no changed test_*.py and no Red-test: <nodeid> trailer"
    else:
        scratch = Path(tempfile.mkdtemp(prefix="red-green-"))
        try:
            (scratch / "red_green_plugin.py").write_text(PLUGIN, encoding="utf-8")
            red_tree, green_tree = scratch / "red", scratch / "green"
            checkout(repo, mb, red_tree)
            for rel in overlay:
                dest = red_tree / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(subprocess.run(["git", "-C", str(repo), "cat-file", "blob", f"{head}:{rel}"],
                                                capture_output=True, check=True).stdout)
            checkout(repo, head, green_tree)
            for target in targets:
                red = run_target(red_tree, target, scratch, args.python, args.timeout)
                green = run_target(green_tree, target, scratch, args.python, args.timeout)
                for c in red["collect"]:
                    collect_errors.append(f"- `{c['nodeid']}`: {c['message']}")
                for nodeid in sorted(set(red["tests"]) | set(green["tests"])):
                    r, g = red["tests"].get(nodeid), green["tests"].get(nodeid)
                    shown_r = r or ("collection error" if red["collect"] else "not collected")
                    rows.append((nodeid, shown_r, g or "not collected", verdict_for(r, bool(red["collect"]), g)))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        n = sum(1 for row in rows if row[3].startswith("red then green"))
        status = f"{n} test id(s) red then green" if n else "no red: no test id fails on red and passes on green"

    passed = exempt or bool(reasons) or status.endswith("red then green")
    out.append(f"**{'PASS' if passed else 'FAIL'}**: {status}.")
    if ids:
        out += ["", "Red-test trailers: " + ", ".join(f"`{i}`" for i in ids)]
    shown = [row for row in rows if row[1:3] != ("passed", "passed")]
    if shown:
        out += ["", "| Test id | Red (merge base + head's tests) | Green (head) | Result |", "|---|---|---|---|"]
        out += [f"| `{a}` | {b} | {c} | {d} |" for a, b, c, d in shown]
    if len(rows) > len(shown):
        out += ["", f"{len(rows) - len(shown)} other test id(s) pass on red and on green."]
    if collect_errors:
        out += ["", "Collection errors on red (counted as red, apart from a failing assertion):"] + collect_errors
    summary = "\n".join(out) + "\n"
    sys.stdout.write(summary)
    if args.summary:
        Path(args.summary).write_text(summary, encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
