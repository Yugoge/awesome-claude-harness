#!/usr/bin/env python3
"""
Stop Hook: Block spec agent from exiting with < 100% monolith coverage.

Logic:
  1. If stop_hook_active -> exit 0
  2. Read the transcript's active span to check if current workflow is /spec
  3. If NOT /spec -> exit 0 (allow)
  4. Derive the target spec from the stopping session's own transcript JSONL
     (transcript_path from stdin): the spec it last wrote (lib/spec_path.py,
     the one rule prompt-workflow.py's spec decision takes too).
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
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import claude_home  # noqa: E402  (shared WS1 harness-home resolver)
import command_span  # noqa: E402

# Relative path of the spec-verify helper under the resolved harness home. The
# absolute path is resolved at runtime via claude_home so a fresh non-root clone
# (whose home is NOT /root/.claude) still finds its verifier; when the verifier
# is absent the stop is ALLOWED (baseline skip — see main()).
SPEC_VERIFY_RELPATH = "scripts/spec-verify/spec-verify.py"

# Matches docs/dev/specs/spec-YYYYMMDD-HHMMSS in monolith or split-dir paths.
# Captures the bare spec_id (e.g. "spec-20260424-090315") with no trailing
# extension or subpath. Accepts absolute and relative file_path values.
SPEC_ID_RE = re.compile(r"docs/dev/specs/(spec-\d{8}-\d{6})(?:\.md|/|$)")


def read_stdin():
    """Parse stop hook JSON from stdin."""
    try:
        if not sys.stdin.isatty():
            return json.load(sys.stdin)
    except Exception:
        pass
    return {}


def get_workflow_command(transcript_path) -> str:
    """Return the command of the transcript's active span, or empty string
    once a TodoWrite in it came back with every step completed: the gate held
    from the command's start until its checklist was done, and still does."""
    span = command_span.active_span(transcript_path) if transcript_path else None
    if span is None:
        return ""
    for call in span.uses("TodoWrite"):
        todos = call.input.get("todos")
        if call.ok and isinstance(todos, list) and todos \
                and all(isinstance(t, dict) and t.get("status") == "completed" for t in todos):
            return ""
    return span.command


def derive_spec_id_from_transcript(transcript_path: str) -> Optional[str]:
    """The bare spec_id (e.g. ``spec-20260424-090315``) of the spec this session
    last wrote, by the rule prompt-workflow.py takes too (lib/spec_path.py: an
    ok Write/Edit/MultiEdit of docs/dev/specs/*.md, or a call of
    scripts/spec-write.py, the one writer of those files). A Read never selects
    a spec, so inspecting a foreign spec cannot override this session's own
    write. Returns None on any failure -- callers treat None as "allow stop".
    """
    from spec_path import last_spec_write  # hooks/lib, on sys.path above

    path = last_spec_write(transcript_path)
    match = SPEC_ID_RE.search(path) if path else None
    return match.group(1) if match else None


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


def run_coverage_check(
    monolith: Path, views_dir: Path, spec_verify: Path
) -> subprocess.CompletedProcess:
    """Run spec-verify.py and return the result."""
    return subprocess.run(
        ["python3", str(spec_verify), "--monolith", str(monolith),
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
    transcript_path = data.get("transcript_path")
    if get_workflow_command(transcript_path) != "spec":
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
    if monolith is None:
        # No monolith for a touched spec dir — nothing to verify, allow stop.
        sys.exit(0)

    # Resolve the spec-verify helper portably via claude_home (the de-hardcode).
    # When it cannot be located (home unresolved OR verifier absent), ALLOW the
    # stop — this is the baseline behavior. (Reverted from the WS1 exit-2, which
    # was a fail-open->fail-closed flip beyond path-cleanup that could wedge a
    # stop on a partial/fresh install; only the path resolution is kept.)
    spec_verify = claude_home.resolve_optional(SPEC_VERIFY_RELPATH)
    if spec_verify is None:
        sys.exit(0)

    # Non-blocking breadcrumb — stderr is only surfaced when the hook blocks.
    sys.stderr.write(f"[stop-spec-coverage-enforce] target spec: {spec_dir.name}\n")

    result = run_coverage_check(monolith, spec_dir / "views", spec_verify)
    if result.returncode == 0:
        sys.exit(0)

    block_with_message(result)


if __name__ == "__main__":
    main()
