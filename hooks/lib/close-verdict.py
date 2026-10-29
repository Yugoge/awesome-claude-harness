#!/usr/bin/env python3
"""Shared CLOSE verdict classifier for commit/close tooling.

The one rule every reader of a close verdict applies: classify the close
report's last non-empty line. An append-only report's earlier sections never
decide, so no reader scans the rest of the text.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def last_nonempty(text: str) -> str:
    line = ""
    for raw in text.replace("\r", "").splitlines():
        if raw.strip():
            line = raw.strip()
    return line


# Round-open literal (L5): `CLOSE_FINDINGS: <n> items` is the never-landing
# return of a QA judging round that opened findings. Read-side class `no`
# (not landed), recognised BEFORE the `CLOSE:` prefix test.
_ROUND_OPEN_RE = re.compile(r"^CLOSE_FINDINGS:\s*\d+\s+items?\b")


def classify_line(line: str) -> str:
    text = (line or "").strip()
    if _ROUND_OPEN_RE.match(text):
        return "no"
    if not text.upper().startswith("CLOSE:"):
        return "unknown"
    rest = text.split(":", 1)[1].strip().replace("—", "-")
    upper = rest.upper()
    if upper == "YES" or upper.startswith(("YES ", "YES-", "YES(")):
        return "yes"
    if upper == "NO" or upper.startswith(("NO ", "NO-", "NO(")):
        return "no"
    return "unknown"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: close-verdict.py classify-line <line> | classify-file <path> | last-line <path>", file=sys.stderr)
        return 2
    mode = argv[1]
    if mode == "classify-line":
        print(classify_line(" ".join(argv[2:])))
        return 0
    if mode in {"classify-file", "last-line"}:
        if len(argv) != 3:
            print(f"close-verdict.py: {mode} requires a path", file=sys.stderr)
            return 2
        line = last_nonempty(Path(argv[2]).read_text(encoding="utf-8", errors="replace"))
        print(line if mode == "last-line" else classify_line(line))
        return 0
    print(f"close-verdict.py: unknown mode: {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
