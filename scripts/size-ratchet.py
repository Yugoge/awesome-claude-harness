#!/usr/bin/env python3
"""Size ratchet: six size metrics of a committed tree, and a check of HEAD against a budget.

Usage:
    size-ratchet.py --measure [--ref <rev>]     the metrics of <rev>'s tree (default HEAD)
    size-ratchet.py --check --budget-ref <rev>  HEAD against the budget committed at <rev>

Both read git objects only, never the work tree. --check reads policies/size-budget.v1.json as
committed at <rev>, so a change cannot raise its own limit. It exits 1 when a metric at HEAD is
above that budget (naming the top growers of `git diff --numstat <rev> HEAD`), when the change
from <rev> to HEAD raises or removes a budget value and also changes any other path (a raise
travels alone, visible in review), or when a ref does not resolve. A change that only raises the
budget passes and names the raise. With no budget at <rev> it prints the metrics and exits 0.
"""
import argparse
import json
import os
import re
import subprocess
import sys

METRICS = ("tracked_files", "tracked_lines", "hooks_lines", "registered_hooks", "prompt_bytes",
           "docs_reference_bytes")
BUDGET = "policies/size-budget.v1.json"
PROMPT = re.compile(r"CLAUDE\.md|(?:commands|agents)/[^/]+\.md")


def git(*args: str, ok=(0,)) -> bytes:
    proc = subprocess.run(["git", *args], capture_output=True)
    if proc.returncode not in ok:
        sys.exit(f"size-ratchet: git {' '.join(args)}: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def tree(rev: str) -> str:
    return git("rev-parse", "--verify", "--end-of-options", rev + "^{tree}").decode().strip()


def show(tree_id: str, path: str):
    proc = subprocess.run(["git", "cat-file", "blob", f"{tree_id}:{path}"], capture_output=True)
    return proc.stdout if proc.returncode == 0 else None


def measure(tree_id: str) -> dict:
    size, lines = {}, {}
    for rec in git("ls-tree", "-r", "-l", "-z", tree_id).split(b"\0")[:-1]:
        meta, path = rec.split(b"\t", 1)
        size[os.fsdecode(path)] = int(meta.split()[3]) if meta.split()[1] == b"blob" else 0
    # `git grep -c ''` counts each text file's lines as `git diff --numstat` does; -I skips binaries.
    for rec in git("grep", "--no-color", "-I", "-c", "-z", "-e", "", tree_id, ok=(0, 1)).split(b"\n")[:-1]:
        path, count = rec.rsplit(b"\0", 1)
        lines[os.fsdecode(path)[len(tree_id) + 1:]] = int(count)
    try:  # the committed blob is the clean form (the settings filter applies to the work tree only)
        hooks = json.loads(show(tree_id, "settings.json") or b"{}").get("hooks") or {}
        registered = sum(1 for groups in hooks.values() for g in groups for h in g.get("hooks") or []
                         if h.get("command"))
    except (ValueError, AttributeError, TypeError):
        registered = 0
    return {
        "tracked_files": len(size),
        "tracked_lines": sum(n for p, n in lines.items() if not p.startswith("tests/generated/")),
        "hooks_lines": sum(n for p, n in lines.items() if p.startswith("hooks/")),
        "registered_hooks": registered,
        "prompt_bytes": sum(n for p, n in size.items() if PROMPT.fullmatch(p)),
        "docs_reference_bytes": sum(n for p, n in size.items() if p.startswith("docs/reference/")),
    }


def budget(tree_id: str):
    """The budget values committed in tree_id, or None when it holds no readable budget file."""
    try:
        data = json.loads(show(tree_id, BUDGET) or b"null")
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    return {m: v for m, v in data.items() if m in METRICS and type(v) is int}


def check(ref: str) -> int:
    base, head = tree(ref), tree("HEAD")
    now, limit = measure(head), budget(base)
    if limit is None:
        print(f"size-ratchet: no budget at {ref} ({BUDGET}): nothing to check")
        print("\n".join(f"{m} {now[m]}" for m in METRICS))
        return 0
    new = budget(head) or {}
    over = [m for m in limit if now[m] > limit[m]]
    raised = [m for m in limit if new.get(m) is None or new[m] > limit[m]]
    for m in METRICS:
        print(f"{m} {now[m]} budget {limit.get(m, '-')}" + (" OVER" if m in over else ""))
    rc = 0
    if raised:
        print("budget raised at HEAD: " + ", ".join(f"{m} {limit[m]} -> {new.get(m, 'removed')}" for m in raised))
        others = [p for p in git("diff", "--name-only", "--no-renames", "-z", base, head).decode().split("\0")
                  if p and p != BUDGET]
        if others:
            print(f"FAIL: a budget raise must be its own change; {len(others)} other path(s) changed since {ref}")
            rc = 1
    if over:
        print(f"FAIL: above the budget at {ref}: {', '.join(over)}; top growers since {ref}:")
        rows = []
        for line in git("diff", "--numstat", "--no-renames", base, head).decode(errors="replace").splitlines():
            added, deleted, path = line.split("\t", 2)
            if added != "-" and int(added) > int(deleted):
                rows.append((int(added) - int(deleted), path))
        print("\n".join(f"  +{n} {p}" for n, p in sorted(rows, key=lambda r: (-r[0], r[1]))[:10]))
        rc = 1
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--measure", action="store_true")
    mode.add_argument("--check", action="store_true")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--budget-ref")
    args = ap.parse_args()
    if args.check:
        if not args.budget_ref:
            ap.error("--check needs --budget-ref <rev>")
        return check(args.budget_ref)
    now = measure(tree(args.ref))
    print("\n".join(f"{m} {now[m]}" for m in METRICS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
