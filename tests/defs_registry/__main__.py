"""python3 -m tests.defs_registry [--tree DIR] [--register FILE] [--count] [--stale]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .check import REGISTER, RegisterError, describe, run

REPO = Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m tests.defs_registry",
                                 description="Fail when a fact is defined twice and the register does not allow it.")
    ap.add_argument("--tree", default=str(REPO), help="the harness tree (a git work tree; default: this checkout)")
    ap.add_argument("--register", help=f"the register (default: <tree>/{REGISTER})")
    ap.add_argument("--count", action="store_true", help="print only the number of uncovered groups")
    ap.add_argument("--stale", action="store_true", help="also list register definitions the tree no longer has")
    a = ap.parse_args(argv)
    tree = Path(a.tree)
    try:
        res = run(tree, Path(a.register) if a.register else None)
    except RegisterError as exc:
        print(exc, file=sys.stderr)
        return 2
    for err in res.errors:
        print(f"not parsed: {err}", file=sys.stderr)
    if a.count:
        print(len(res.uncovered))
    else:
        for n, g in enumerate(res.uncovered, 1):
            text = describe(res.defs, g)
            print(f"[{n}] {text[0]}")
            print("\n".join(text[1:]))
        print(f"uncovered groups: {len(res.uncovered)} ({res.n_definitions} definitions); "
              f"definitions scanned: {len(res.defs)}; register definitions not found: {len(res.stale)}")
        if a.stale:
            print("\n".join("  stale: " + s for s in res.stale))
    return 1 if res.uncovered or res.errors else 0


if __name__ == "__main__":
    sys.exit(main())
