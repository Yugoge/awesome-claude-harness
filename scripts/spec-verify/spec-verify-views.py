#!/usr/bin/env python3
"""spec-verify-views.py -- verify agent views are verbatim subsets of monolith.

Usage:
  spec-verify-views.py --monolith <path> --views-dir <path>

Exit codes: 0 = all views pass, 1 = at least one view has non-verbatim lines.
"""

import argparse
import sys
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description="Verify agent views are verbatim subsets of monolith.")
    p.add_argument("--monolith", required=True, help="Path to monolith spec (.md)")
    p.add_argument("--views-dir", required=True, help="Path to views directory")
    return p.parse_args()


def skip_header(lines):
    """Skip the auto-generated header (up to first '---' after line 3)."""
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        if stripped == "---" and i > 2:
            return i + 1
    return 0


def check_view(view_path, monolith_text):
    with open(view_path, encoding="utf-8") as f:
        lines = f.readlines()

    start = skip_header(lines)
    failures = []
    content_lines = 0

    for i in range(start, len(lines)):
        stripped = lines[i].rstrip("\n")
        if not stripped:
            continue
        content_lines += 1
        if stripped not in monolith_text:
            failures.append((i + 1, stripped[:80]))

    return content_lines, failures


def main():
    args = parse_args()
    monolith_path = Path(args.monolith)
    views_dir = Path(args.views_dir)

    if not monolith_path.exists():
        sys.stderr.write(f"ERROR: monolith not found: {monolith_path}\n")
        return 1

    if not views_dir.exists():
        sys.stderr.write(f"ERROR: views dir not found: {views_dir}\n")
        return 1

    monolith_text = monolith_path.read_text(encoding="utf-8")
    view_files = sorted(views_dir.glob("*.md"))

    if not view_files:
        print("spec-verify-views: no .md files found in views directory")
        return 0

    print(f"spec-verify-views: checking {len(view_files)} view files against monolith\n")

    passed = 0
    failed = 0

    for vf in view_files:
        agent = vf.stem
        content_lines, failures = check_view(vf, monolith_text)

        if not failures:
            print(f"  {agent}.md: PASS ({content_lines} content lines, all verbatim)")
            passed += 1
        else:
            print(f"  {agent}.md: FAIL ({len(failures)} non-verbatim lines)")
            for ln, text in failures[:5]:
                print(f"    line {ln}: {text}")
            if len(failures) > 5:
                print(f"    ... and {len(failures) - 5} more")
            failed += 1

    print(f"\nSummary: {passed}/{passed + failed} passed, {failed} failed")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
