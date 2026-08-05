#!/usr/bin/env python3
"""Build the hero trace manifest from the committed capture -- by bijection, not by taste.

Description: Emits a trace manifest (tools/demo/manifest.schema.md) in which every
  lines[].text is a byte-exact slice of the capture. Selection is not a judgement call:
  EVERY visible display line of the capture becomes exactly one manifest line, in
  capture order, so `|lines| + |omitted| == |capture lines|` closes by construction.

Usage: build-hero-manifest.py <capture-file> <out-manifest.json>

Exit codes: 0 = ok, 1 = input error, 2 = the bijection or a provenance rule failed

WHY A BIJECTION. Quoting a flattering subset of a genuine run is authoring by
selection -- it reopens, in a new register, the authored-not-captured defect this hero
exists to close. The demo is purpose-built for this hero, so its capture contains no
line that must be dropped, and `omitted[]` is expected to be empty. The only omission
class the schema here permits is explicitly declared, non-display harness
instrumentation; a visible line in omitted[] is a hard failure.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

CAPTURE_REF = ".github/assets/hero-capture.txt"

RE_LINE = re.compile(r"^\[\s*(\d+\.\d+)\]\s(.*)$")

# Non-display class: harness instrumentation that is not part of the terminal session.
# Every entry placed in omitted[] must name its class; nothing else may be omitted.
NON_DISPLAY_PREFIXES = ("capture-hero-run:",)

# Stage rail. Ranks must be NONDECREASING across the manifest array, so the rail tracks
# the arc rather than the actor: a second refusal is a later stage, not a return to the
# first one.
RAIL = ["blocked", "granted", "consumed"]

CONSUMPTION_MARKER = "[ALLOW-SENTINEL] grant CONSUMED for task_id="

# The `granted` transition. This MUST be a string the capture actually emits: the arc
# enters the granted stage the moment the verifier installs the single-use grant, and
# every line after it -- including the two reporting the SUCCESSFUL push -- belongs to
# that stage. A trigger that never fires leaves a declared stage empty and silently
# demotes those success lines into `blocked`, which renders the demo's central beat
# backwards: the hero would label a permitted push a refusal. The zero-line check below
# is what makes such a trigger impossible to reintroduce unnoticed.
GRANT_INSTALL_MARKER = "[verifier] installed one single-use grant"


def extract_hash(text: str) -> str:
    return hashlib.sha256(unicodedata.normalize("NFC", text).encode("utf-8")).hexdigest()


def classify(text: str, seen_grant: bool, seen_marker: bool) -> tuple[str, str, bool]:
    """-> (stage, kind, block).  Pure function of the captured text and arc position."""
    if seen_marker:
        stage = "consumed"
    elif seen_grant:
        stage = "granted"
    else:
        stage = "blocked"

    if text.startswith("$ "):
        return stage, "attempt", False
    if text.startswith("BLOCKED:"):
        return stage, "verdict", True
    if text.startswith(CONSUMPTION_MARKER):
        return stage, "verdict", False
    return stage, "artifact", False


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 1
    cap_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    raw_lines = cap_path.read_text(encoding="utf-8").splitlines()

    lines: list[dict] = []
    omitted: list[dict] = []
    seen_grant = False
    seen_marker = False

    for idx, raw in enumerate(raw_lines, start=1):
        m = RE_LINE.match(raw)
        if not m:
            omitted.append({"capture_line": idx, "class": "non-display",
                            "reason": "not a timestamped capture event"})
            continue
        text = m.group(2)
        if text.startswith(NON_DISPLAY_PREFIXES):
            omitted.append({"capture_line": idx, "class": "non-display",
                            "reason": "harness instrumentation, not terminal session"})
            continue

        stage, kind, block = classify(text, seen_push, seen_marker)
        entry = {
            "id": f"hero-{idx:03d}",
            "ordinal": len(lines) + 1,
            "stage": stage,
            "kind": kind,
            "text": text,
            "source_ref": CAPTURE_REF,
            "source_locator": f"{CAPTURE_REF}:{idx}",
            "extract_hash": extract_hash(text),
        }
        if block:
            entry["block"] = True
        lines.append(entry)

        if text.startswith("[git push exit"):
            seen_push = True
        if text.startswith(CONSUMPTION_MARKER):
            seen_marker = True

    # ---- hard checks (the manifest is refused rather than emitted if any fails) -----
    problems: list[str] = []
    if len(lines) + len(omitted) != len(raw_lines):
        problems.append(
            f"coverage arithmetic: {len(lines)} + {len(omitted)} != {len(raw_lines)}"
        )
    locs = [int(ln["source_locator"].rsplit(":", 1)[1]) for ln in lines]
    if locs != sorted(set(locs)) or len(locs) != len(set(locs)):
        problems.append("source_locator line numbers are not strictly increasing")
    ranks = [RAIL.index(ln["stage"]) for ln in lines]
    if any(b < a for a, b in zip(ranks, ranks[1:])):
        problems.append("stage rank is not nondecreasing across the manifest")
    for ln in lines:
        if ln["kind"] in ("condensation", "adaptation"):
            problems.append(f"{ln['id']}: forbidden kind {ln['kind']}")
    if problems:
        for p in problems:
            print(f"build-hero-manifest: FAIL: {p}", file=sys.stderr)
        return 2

    manifest = {
        "meta": {
            "session_title": "claude — guard demo (captured run)",
            "rail": RAIL,
            "footer": (
                "every line above is a byte-exact slice of "
                f"{CAPTURE_REF} · re-run: python3 scripts/capture-hero-run.py"
            ),
        },
        "capture": {
            "path": CAPTURE_REF,
            "capture_mode": "pipe (never a pseudo-terminal)",
            "capture_lines": len(raw_lines),
            "manifest_lines": len(lines),
            "coverage": "bijection over every visible display line, in capture order",
        },
        "omitted": omitted,
        "lines": lines,
    }
    out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"build-hero-manifest: OK  {len(lines)} lines, {len(omitted)} omitted "
          f"(of {len(raw_lines)} capture lines) -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
