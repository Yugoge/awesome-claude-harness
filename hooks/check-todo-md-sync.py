#!/usr/bin/env python3
"""
check-todo-md-sync.py — Session-start drift detector for todo scripts.

For each ~/.claude/scripts/todo/<cmd>.py that has a matching
~/.claude/commands/<cmd>.md, compare the ordered list of "Step N[x]"
tokens between the two. Emit stderr warnings for:
  - tokens in .md but missing from .py (silent-dead-step bug)
  - tokens in .py but missing from .md (stale todo)
  - duplicate tokens present a different number of times on each side
  - tokens present in both but at different positions (order drift)

Non-blocking: always exits 0. Silent when everything is in sync.
Stdlib-only. Target runtime <500ms for ~20 commands.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
TODO_DIR = HOME / ".claude" / "scripts" / "todo"
COMMANDS_DIR = HOME / ".claude" / "commands"

# Matches workflow headings at Markdown levels 3 through 6, including nested
# steps such as "#### Step 7: foo".  Level 1/2 headings are section titles in
# command documents rather than executable checklist entries.
MD_HEADING_RE = re.compile(
    r"^#{3,6}\s+(Step\s+\d+[a-z]?):\s*(.+?)\s*$",
    re.MULTILINE,
)

# Matches the leading "Step N[x]:" prefix inside a todo item's `content` field.
PY_CONTENT_RE = re.compile(r"^(Step\s+\d+[a-z]?):")

# Never treat these as commands with todo scripts.
SKIP_MD_NAMES = {"INDEX.md", "README.md"}


def extract_md_steps(md_path: Path) -> list[str]:
    """Return ordered list of 'Step N[x]' tokens from a command .md file."""
    try:
        text = md_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [m.group(1).replace("  ", " ") for m in MD_HEADING_RE.finditer(text)]


def run_py_todo_script(py_path: Path) -> list | None:
    """Execute a todo script and return its parsed JSON list, or None on failure."""
    try:
        proc = subprocess.run(
            [sys.executable, str(py_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        items = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return items if isinstance(items, list) else None


def step_token_from_item(item: object) -> str | None:
    """Return 'Step N[x]' token from a todo item dict, or None if absent."""
    if not isinstance(item, dict):
        return None
    content = item.get("content")
    if not isinstance(content, str):
        return None
    m = PY_CONTENT_RE.match(content)
    return m.group(1).replace("  ", " ") if m else None


def extract_py_steps(py_path: Path) -> list[str] | None:
    """Return ordered list of 'Step N[x]' tokens from a todo script."""
    items = run_py_todo_script(py_path)
    if items is None:
        return None
    tokens = (step_token_from_item(item) for item in items)
    return [t for t in tokens if t is not None]


def order_drift_message(cmd: str, common_md: list[str], common_py: list[str]) -> str | None:
    """Return a formatted drift message for the first mismatched pair, or None."""
    if common_md == common_py:
        return None
    for idx, (a, b) in enumerate(zip(common_md, common_py)):
        if a != b:
            return f"{cmd}: order drift at position {idx} — .md has {a!r}, .py has {b!r}"
    return None


def _common_occurrences_in_order(
    steps: list[str], common_counts: Counter[str]
) -> list[str]:
    """Keep at most the shared number of occurrences, preserving order."""
    seen: Counter[str] = Counter()
    common: list[str] = []
    for token in steps:
        if seen[token] >= common_counts[token]:
            continue
        common.append(token)
        seen[token] += 1
    return common


def diff_steps(cmd: str, md_steps: list[str], py_steps: list[str]) -> list[str]:
    """Return a list of human-readable drift messages for one command."""
    warnings: list[str] = []
    md_set = set(md_steps)
    py_set = set(py_steps)
    md_counts = Counter(md_steps)
    py_counts = Counter(py_steps)

    # Missing in .py (today's concrete bug class — most important).
    warnings.extend(f"{cmd}: missing in .py — {tok}" for tok in md_steps if tok not in py_set)

    # Stale in .py (no corresponding .md heading).
    warnings.extend(f"{cmd}: stale in .py — {tok}" for tok in py_steps if tok not in md_set)

    # A set-only comparison hides duplicated labels. Report count drift when a
    # token exists on both sides but one side repeats it more often.
    for tok in dict.fromkeys(md_steps + py_steps):
        md_count = md_counts[tok]
        py_count = py_counts[tok]
        if md_count and py_count and md_count != py_count:
            warnings.append(
                f"{cmd}: duplicate count drift — {tok} appears "
                f"{md_count} time(s) in .md, {py_count} time(s) in .py"
            )

    # Compare only the shared multiplicity of each token so an extra duplicate
    # produces count drift without a misleading secondary order warning.
    common_counts = md_counts & py_counts
    common_md = _common_occurrences_in_order(md_steps, common_counts)
    common_py = _common_occurrences_in_order(py_steps, common_counts)
    drift_msg = order_drift_message(cmd, common_md, common_py)
    if drift_msg is not None:
        warnings.append(drift_msg)
    return warnings


def check_one(py_path: Path) -> list[str]:
    """Return drift warnings for a single todo script, or [] if in sync / skipped."""
    cmd = py_path.stem
    md_path = COMMANDS_DIR / f"{cmd}.md"
    if not md_path.is_file() or md_path.name in SKIP_MD_NAMES:
        return []
    py_steps = extract_py_steps(py_path)
    if py_steps is None:
        return []
    md_steps = extract_md_steps(md_path)
    if not md_steps:
        return []
    return diff_steps(cmd, md_steps, py_steps)


def main() -> int:
    if not TODO_DIR.is_dir() or not COMMANDS_DIR.is_dir():
        return 0
    warnings: list[str] = []
    for py_path in sorted(TODO_DIR.glob("*.py")):
        warnings.extend(check_one(py_path))
    for w in warnings:
        print(f"\u26a0\ufe0f [todo-md-sync] {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
