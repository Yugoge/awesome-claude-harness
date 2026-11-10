"""python3 -m tests.lint [--tree DIR] [--check NAME ...]: print the findings, exit 1 on any."""
from __future__ import annotations

import argparse
import sys

from .checks import CHECKS, run
from .tree import REPO, Tree


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m tests.lint", description=__doc__)
    ap.add_argument("--tree", default=str(REPO), help="the harness tree to lint (default: this checkout)")
    ap.add_argument("--check", action="append", choices=sorted(CHECKS), help="run only this check (repeatable)")
    a = ap.parse_args(argv)
    results = run(Tree(a.tree), a.check)
    total = 0
    for name, findings in results.items():
        print(f"{name}: {len(findings)}")
        for f in findings:
            print("  " + f.text())
        total += len(findings)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
