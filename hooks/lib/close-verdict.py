#!/usr/bin/env python3
"""Shared CLOSE verdict classifier for commit/close tooling."""
from __future__ import annotations

import re
import sys
from pathlib import Path


# C1 (W5, ticket-20260511-070000): tolerant fallback regex. Matches any
# line containing `CLOSE: YES` or `CLOSE: NO` regardless of prefix
# decoration (markdown bold, list bullets, "Final verdict:" prose, quoted
# forms). The strict bare-line form remains canonical; this fallback runs
# only after the strict last-line check returns "unknown".
_FALLBACK_VERDICT_RE = re.compile(
    r"^.*?CLOSE:\s*(YES|NO)\b",
    re.IGNORECASE | re.MULTILINE,
)


def last_nonempty(text: str) -> str:
    line = ""
    for raw in text.replace("\r", "").splitlines():
        if raw.strip():
            line = raw.strip()
    return line


# Round-open literal (L5): `CLOSE_FINDINGS: <n> items` is the never-landing
# return of a QA judging round that opened findings. Read-side class `no`
# (not landed), recognised BEFORE the `CLOSE:` prefix test so classify_text's
# strict path returns it and the whole-text fallback never reads an earlier
# landed `CLOSE: YES` section of the append-only report.
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


def classify_text(text: str) -> str:
    """Classify verdict from a full close-report text.

    Strategy:
      1. Strict path -- classify the last non-empty line. If it begins
         with `CLOSE:` (canonical form), return its verdict.
      2. Tolerant fallback -- if strict returns "unknown", scan the
         entire text for the LAST line matching the fallback regex
         (`^.*?CLOSE:\\s*(YES|NO)\\b`, case-insensitive). This accepts
         decorated forms like:
           - `**Final verdict: CLOSE: YES** -- all checks passed`
           - `> CLOSE: NO -- see issue #42`
           - `- [x] CLOSE: YES`
           - `"CLOSE: YES"`
         The bare `CLOSE: YES`/`CLOSE: NO` line remains canonical.
      3. If neither path yields a match, return "unknown" as before.
    """
    if not text:
        return "unknown"
    strict_verdict = classify_line(last_nonempty(text))
    if strict_verdict != "unknown":
        return strict_verdict
    last_match = None
    for m in _FALLBACK_VERDICT_RE.finditer(text):
        last_match = m
    if last_match is None:
        return "unknown"
    return last_match.group(1).lower()


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
        text = Path(argv[2]).read_text(encoding="utf-8", errors="replace")
        if mode == "last-line":
            print(last_nonempty(text))
        else:
            # classify-file uses tolerant path (C1): strict last-line first,
            # then fallback regex scan over the full text.
            print(classify_text(text))
        return 0
    print(f"close-verdict.py: unknown mode: {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
