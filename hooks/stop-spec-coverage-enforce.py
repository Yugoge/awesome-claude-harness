#!/usr/bin/env python3
"""
Stop Hook: Block spec agent from exiting with < 100% monolith coverage.

Logic:
  1. If stop_hook_active -> exit 0
  2. Read workflow bookmark to check if current workflow is /spec
  3. If NOT /spec -> exit 0 (allow)
  4. Derive the target spec from the stopping session's own transcript JSONL
     (transcript_path from stdin). Scan last 500 lines in reverse for the most
     recent Write/Edit/MultiEdit tool_use targeting docs/dev/specs/spec-*.md.
     Read is intentionally excluded — see SPEC_TOOL_NAMES comment below.
  5. If no spec touched, or transcript missing, or no views/ dir -> exit 0
  6. Run spec-verify.py --monolith <path> --views-dir <path>
  7. If exit 0 (100% coverage) -> exit 0 (allow stop)
  8. If exit != 0 -> exit 2 (block stop)

Session isolation:
  The target spec is derived per-session from transcript_path, not via a global
  filesystem heuristic. Parallel /spec sessions no longer interfere with each
  other. See ba-spec-20260424-093644.md (revision 2) for rationale.

Exit codes:
  0: Allow stop
  2: Block stop
"""

import json
import os
import re
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Optional


SPEC_VERIFY = "/root/.claude/scripts/spec-verify/spec-verify.py"

# Matches docs/dev/specs/spec-YYYYMMDD-HHMMSS in monolith or split-dir paths.
# Captures the bare spec_id (e.g. "spec-20260424-090315") with no trailing
# extension or subpath. Accepts absolute and relative file_path values.
SPEC_ID_RE = re.compile(r"docs/dev/specs/(spec-\d{8}-\d{6})(?:\.md|/|$)")

# Tool names whose tool_use events establish spec authorship. Only authorship
# signals (Write/Edit/MultiEdit) drive target-spec selection. Read was excluded
# because inspecting another session's spec should not select it as this
# session's coverage target (see close-report-20260424-133333.md for the bug
# reproduction: Write(own) + Read(foreign) previously returned the foreign
# spec_id because Read was the most recent match in the reverse scan).
SPEC_TOOL_NAMES = frozenset({"Write", "Edit", "MultiEdit"})

# Cap transcript scan cost — most tool events live near the end anyway.
TRANSCRIPT_TAIL_LINES = 500


def read_stdin():
    """Parse stop hook JSON from stdin."""
    try:
        if not sys.stdin.isatty():
            return json.load(sys.stdin)
    except Exception:
        pass
    return {}


def get_workflow_command(project_dir: Path, session_id: str) -> str:
    """Return the workflow command name from bookmark, or empty string."""
    bookmark = project_dir / ".claude" / f"workflow-{session_id}.json"
    if not bookmark.exists():
        return ""
    try:
        state = json.loads(bookmark.read_text())
        return state.get("command", "")
    except Exception:
        return ""


def _extract_spec_id_from_tool_use(item) -> Optional[str]:
    """Return spec_id if this content item is a spec-targeting tool_use, else None."""
    if not isinstance(item, dict) or item.get("type") != "tool_use":
        return None
    if item.get("name") not in SPEC_TOOL_NAMES:
        return None
    tool_input = item.get("input")
    if not isinstance(tool_input, dict):
        return None
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str):
        return None
    match = SPEC_ID_RE.search(file_path)
    return match.group(1) if match else None


def _spec_id_from_message_content(content) -> Optional[str]:
    """Walk a message.content list (newest first) for a spec-targeting tool_use."""
    if not isinstance(content, list):
        return None
    for item in reversed(content):
        spec_id = _extract_spec_id_from_tool_use(item)
        if spec_id:
            return spec_id
    return None


def _spec_id_from_transcript_line(line: str) -> Optional[str]:
    """Parse one JSONL line and return the most recent spec_id referenced, or None."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    message = obj.get("message")
    if not isinstance(message, dict):
        return None
    return _spec_id_from_message_content(message.get("content"))


def _read_transcript_tail(transcript_path: str) -> Optional[deque]:
    """Return a deque with the last TRANSCRIPT_TAIL_LINES lines, or None on failure."""
    try:
        path = Path(transcript_path)
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return deque(fh, maxlen=TRANSCRIPT_TAIL_LINES)
    except Exception:
        return None


def derive_spec_id_from_transcript(transcript_path: str) -> Optional[str]:
    """Scan a session's JSONL transcript in reverse for the last spec it touched.

    Returns the bare spec_id (e.g. ``spec-20260424-090315``) from the most recent
    Write/Edit/MultiEdit tool_use whose ``file_path`` lives under
    ``docs/dev/specs/``. Read is intentionally excluded because inspecting a
    foreign spec must not override this session's own authorship signal.
    Returns None on any failure — callers treat None as "allow stop".
    """
    tail = _read_transcript_tail(transcript_path)
    if tail is None:
        return None
    for line in reversed(tail):
        spec_id = _spec_id_from_transcript_line(line)
        if spec_id:
            return spec_id
    return None


def find_monolith(specs_base: Path, spec_dir: Path) -> Path | None:
    """Locate the monolith .md file for a given spec directory."""
    spec_id = spec_dir.name
    # The split dir may be DE-prefixed (<ts>) while the monolith is the PREFIXED
    # flat file (spec-<ts>.md). Try the dir-name id and, when de-prefixed, the
    # prefixed monolith id too, so a de-prefixed views dir still resolves its
    # monolith (arch-8 companion fix).
    ids = [spec_id]
    if not spec_id.startswith("spec-"):
        ids.append(f"spec-{spec_id}")
    candidates = []
    for sid in ids:
        candidates += [
            specs_base / f"{sid}.md",
            specs_base / f"{sid}.monolith.md",
            spec_dir / f"{sid}.md",
            spec_dir / f"{sid}.monolith.md",
        ]
    for c in candidates:
        if c.is_file():
            return c
    for sid in ids:
        matches = list(specs_base.glob(f"{sid}*.md"))
        if matches:
            return matches[0]
    return None


def run_coverage_check(monolith: Path, views_dir: Path) -> subprocess.CompletedProcess:
    """Run spec-verify.py and return the result."""
    return subprocess.run(
        ["python3", SPEC_VERIFY, "--monolith", str(monolith),
         "--views-dir", str(views_dir), "--strict"],
        capture_output=True,
        text=True,
        timeout=30,
    )


def block_with_message(result: subprocess.CompletedProcess):
    """Write blocking message to stderr and exit 2."""
    sys.stderr.write(
        "\n⛔ SPEC COVERAGE ENFORCEMENT: spec-verify.py reports < 100% coverage.\n"
        "The spec agent MUST achieve 100% coverage before exiting.\n"
        "Run spec-verify.py --show-uncovered to see missing lines.\n"
        "Apply the deterministic coverage fallback from agents/spec.md Step 7.\n"
    )
    if result.stdout:
        sys.stderr.write(f"\nspec-verify.py output:\n{result.stdout}\n")
    if result.stderr:
        sys.stderr.write(f"\nspec-verify.py stderr:\n{result.stderr}\n")
    sys.exit(2)


def resolve_target_spec_dir(data: dict, project_dir: Path) -> Optional[Path]:
    """Given stdin payload, return the per-session spec dir, or None to allow stop."""
    session_id = data.get("session_id", "default")
    transcript_path = data.get("transcript_path")
    if get_workflow_command(project_dir, session_id) != "spec":
        return None
    if not transcript_path or not Path(transcript_path).is_file():
        return None
    spec_id = derive_spec_id_from_transcript(transcript_path)
    if spec_id is None:
        return None
    specs_base = project_dir / "docs" / "dev" / "specs"
    # The transcript yields the PREFIXED monolith id (spec-<ts>), but the splitter
    # finalizes views at the DE-prefixed id (<ts>, exactly one leading "spec-"
    # stripped — the current convention). Try the prefixed dir first (legacy
    # specs), then the de-prefixed dir; return whichever actually has a views/.
    # Without the de-prefixed candidate this hook silently no-ops on every
    # current-convention spec (arch-8), leaving Stop-time coverage unenforced.
    candidates = [spec_id]
    if spec_id.startswith("spec-"):
        candidates.append(spec_id[len("spec-"):])
    for cand in candidates:
        spec_dir = specs_base / cand
        if (spec_dir / "views").is_dir():
            return spec_dir
    return None


def main():
    data = read_stdin()
    if data.get("stop_hook_active", False):
        sys.exit(0)

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    spec_dir = resolve_target_spec_dir(data, project_dir)
    if spec_dir is None:
        sys.exit(0)

    specs_base = project_dir / "docs" / "dev" / "specs"
    monolith = find_monolith(specs_base, spec_dir)
    if monolith is None or not Path(SPEC_VERIFY).is_file():
        sys.exit(0)

    # Non-blocking breadcrumb — stderr is only surfaced when the hook blocks.
    sys.stderr.write(f"[stop-spec-coverage-enforce] target spec: {spec_dir.name}\n")

    result = run_coverage_check(monolith, spec_dir / "views")
    if result.returncode == 0:
        sys.exit(0)

    block_with_message(result)


if __name__ == "__main__":
    main()
