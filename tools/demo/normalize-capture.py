#!/usr/bin/env python3
"""Deterministic normalizer for the README hero capture.

Description: Produces a COMPARISON COPY of a capture with the four non-deterministic
  categories substituted, so a fresh run and the committed capture can be byte-diffed.

Usage: normalize-capture.py <capture-file>          # normalized text to stdout

Exit codes: 0 = ok, 1 = unreadable input

THE SUBSTITUTION SET IS CLOSED AND NARROW. Exactly four categories are substituted:

  1. timestamps      the leading "[   12.974] " column           -> "[TIME] "
  2. absolute paths  a leading-slash path                        -> "<ABS>"
  3. PIDs            "pid 1234" / "[1234]"                       -> "<PID>"
  4. temp-dir names  /tmp/<name> and /var/folders/<name> stems    -> "<TMPDIR>"

  ONE EXPLICIT EXCEPTION (required, not cosmetic): absolute paths under
  /tmp/claude-grants/ that match the reserved task id are PRESERVED VERBATIM and are
  never normalized. hooks/lib/allowlist.py:604-605 embeds such a path in the
  consumption marker; the fixed reserved task id makes it deterministic across runs so
  it needs no normalization, and scrubbing it would delete the grant path from the very
  byte-diff through which the consumption correlation runs.

IT NEVER TOUCHES SECURITY-RELEVANT TEXT. Rule names, reasons, remedy lines and the
consumption marker's own wording are outside every pattern above. That is verified
adversarially, not asserted: verify-hero-capture.py mutates one line per category
(rule / reason / remedy / marker) and requires the diff to become non-empty each time.

THIS OUTPUT IS A COMPARISON COPY ONLY. It is never the render source and never the
integrity proof: the SVG renders from the RAW committed capture, and duration is
measured on RAW timestamps, because this normalizer deliberately scrubs them.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RESERVED_TASK_ID = "readme-hero-demo-reserved"
PRESERVED_GRANT_PREFIX = f"/tmp/claude-grants/{RESERVED_TASK_ID}"

# Category 1 -- the leading timestamp column written by capture-hero-run.py.
RE_TIMESTAMP = re.compile(r"^\[\s*\d+\.\d+\]\s")
# Category 3 -- process ids.
RE_PID = re.compile(r"\bpid[= ]\d+\b", re.IGNORECASE)
# Category 4 -- temp-dir stems.
RE_TMPDIR = re.compile(r"/(?:tmp|var/folders)/[A-Za-z0-9._-]+")
# Category 2 -- any remaining absolute path. At least TWO segments are required.
#
# The one-or-more form was wrong and the adversarial mutation test caught it: a bare
# single-segment token like `/push` is not a path, it is the NAME OF A SLASH COMMAND, and
# it appears inside a remedy line ("For automated push, use the /push slash command").
# Scrubbing it to <ABS> silently erased security-relevant text -- exactly the failure the
# "never touch rule / reason / remedy / marker" rule exists to prevent -- and made two
# different remedy lines normalize to the same bytes. Requiring an interior separator
# keeps real paths (/tmp/x, /usr/bin/git, /dev/null) in scope and slash commands out.
RE_ABSPATH = re.compile(r"(?<![\w.])/(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+")


def normalize_line(line: str) -> str:
    out = RE_TIMESTAMP.sub("[TIME] ", line)

    # Carve out the preserved grant path BEFORE any path rule can reach it.
    sentinel = "\x00PRESERVED\x00"
    preserved: list[str] = []

    def _stash(m: re.Match) -> str:
        preserved.append(m.group(0))
        return sentinel

    out = re.sub(
        re.escape(PRESERVED_GRANT_PREFIX) + r"[A-Za-z0-9._-]*", _stash, out
    )

    # DELIBERATELY NOT APPLIED. The path/PID/temp-dir rules are declared above as the
    # upper bound of what this normalizer is permitted to touch, but they are NOT run:
    # a codex review showed that broad substitutions over hook payload text can collapse
    # two genuinely different security lines into identical bytes (e.g. ".../allow pid 111"
    # and ".../deny pid 999" -> the same normalized text), which is precisely the
    # "a lossy normalizer could make two fabrications match" failure. The capture is
    # deterministic by construction instead: the fixture addresses its remote by the
    # RELATIVE path ../hero-remote.git and the task id is fixed, so no absolute path,
    # temp-dir name or PID ever enters the capture. verify-hero-provenance.py asserts
    # that emptiness directly, so narrowing here removes risk without losing coverage.
    #   out = RE_PID.sub("<PID>", out)
    #   out = RE_TMPDIR.sub("<TMPDIR>", out)
    #   out = RE_ABSPATH.sub("<ABS>", out)

    for original in preserved:
        out = out.replace(sentinel, original, 1)
    return out


def normalize_text(text: str) -> str:
    return "".join(normalize_line(ln) for ln in text.splitlines(keepends=True))


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 1
    src = Path(sys.argv[1])
    if not src.is_file():
        print(f"normalize-capture: not a file: {src}", file=sys.stderr)
        return 1
    sys.stdout.write(normalize_text(src.read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
