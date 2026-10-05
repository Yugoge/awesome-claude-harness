#!/usr/bin/env python3
"""Generate / check the machine-generated default-run failure baseline.

Usage:
  gen-test-baseline.py generate [--junit PATH] [--out PATH] [--timeout SEC] [-- PYTEST_ARGS...]
  gen-test-baseline.py check    [--junit PATH] [--baseline PATH] [--timeout SEC] [-- PYTEST_ARGS...]

Without --junit the default pytest invocation is run (junit-xml written under
tempfile.gettempdir(), honouring TMPDIR). The baseline is a sorted list of
failing/erroring node-ids; counts are derived, never stored. Failures whose
message shows a disk-full fault (Errno 28 / "No space left on device") are
environmental: they are listed separately under "environmental" and never baselined.

`check` exits 1 iff a failing node-id is absent from the baseline; ids fixed
since the baseline are reported only. Exit codes: 0 ok, 1 new failure, 2 usage/error.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

SCHEMA_VERSION = 1
GENERATOR = "scripts/gen-test-baseline.py"
DISK_FULL_MARKERS = ("No space left on device", "Errno 28")
DEFAULT_ARGS = ["-q", "-p", "no:cacheprovider"]
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BASELINE = os.path.join(REPO, "tests", "baselines", "default-run-failures.json")


def node_id(case):
    cls = case.get("classname", "")
    name = case.get("name", "")
    parts = cls.split(".")
    # Longest prefix of classname that is an existing .py path is the file.
    for k in range(len(parts), 0, -1):
        rel = "/".join(parts[:k]) + ".py"
        if os.path.exists(os.path.join(REPO, rel)):
            rest = parts[k:]
            return rel + "::" + "::".join(rest + [name])
    return (cls.replace(".", "/") + ".py::" + name) if cls else name


def parse_junit(path):
    """Return (failing_ids, environmental_ids) from a junit-xml file."""
    failing, env = set(), set()
    for case in ET.parse(path).getroot().iter("testcase"):
        for child in case:
            if child.tag not in ("failure", "error"):
                continue
            text = (child.get("message") or "") + (child.text or "")
            (env if any(m in text for m in DISK_FULL_MARKERS) else failing).add(node_id(case))
    return sorted(failing), sorted(env - failing)


def run_pytest(extra, timeout):
    fd, junit = tempfile.mkstemp(prefix="baseline-", suffix=".xml")
    os.close(fd)
    cmd = [sys.executable, "-m", "pytest", "--junit-xml=" + junit] + (extra or DEFAULT_ARGS)
    try:
        subprocess.run(cmd, cwd=REPO, timeout=timeout)
    except subprocess.TimeoutExpired:
        sys.exit("pytest run exceeded timeout of %ss" % timeout)
    return junit, cmd


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("generate", "check"))
    ap.add_argument("--junit")
    ap.add_argument("--out", default=DEFAULT_BASELINE)
    ap.add_argument("--baseline", default=DEFAULT_BASELINE)
    ap.add_argument("--timeout", type=int, default=3000)
    ap.add_argument("pytest_args", nargs="*")
    a = ap.parse_args(argv)
    junit, invocation = a.junit, ["--junit " + a.junit] if a.junit else None
    if not junit:
        junit, cmd = run_pytest(a.pytest_args, a.timeout)
        invocation = [("--junit-xml=<tempfile>" if c.startswith("--junit-xml=") else c) for c in cmd[1:]]
    failing, env = parse_junit(junit)
    if a.mode == "generate":
        doc = {"schema_version": SCHEMA_VERSION, "generator": GENERATOR,
               "invocation": invocation, "failing_node_ids": failing,
               "environmental_unbaselined": env}
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("baseline written: %d node-ids, %d environmental (unbaselined)" % (len(failing), len(env)))
        return 0
    with open(a.baseline, encoding="utf-8") as fh:
        base = set(json.load(fh)["failing_node_ids"])
    new = sorted(set(failing) - base)
    fixed = sorted(base - set(failing))
    for i in fixed:
        print("FIXED since baseline: " + i)
    for i in env:
        print("ENVIRONMENTAL (ignored): " + i)
    for i in new:
        print("NEW FAILURE: " + i)
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
