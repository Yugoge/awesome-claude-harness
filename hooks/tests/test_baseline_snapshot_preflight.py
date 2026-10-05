#!/usr/bin/env python3
"""Regression coverage for hooks/pretool-baseline-snapshot-preflight.py (backlog #119, lane "b").

agents/dev.md:535 declares that the orchestrator captures baseline_dirty_snapshot
before dev dispatch, but nothing verified this at runtime -- so "forgetting to
capture" could pass silently and the downstream ownership gate
(scripts/resolve-commit-repos.py) would later reject a fully compliant
dev-report as if it carried unaccounted edits. Real incident: backlog #119,
task 20260923-083731.

Every assertion below anchors on the subprocess exit code and/or the literal
token "baseline_dirty_snapshot" in stderr -- never solely on a full free-text
error sentence (backlog #118's control-flow-not-wording rule). AC1 also
requires proving the diagnostic avoids ownership-violation phrasing; that is a
targeted banned-phrase absence check, not a full-sentence match, and it is
never the sole or primary anchor of any test here.
"""

import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO_ROOT, "hooks", "pretool-baseline-snapshot-preflight.py")

# Shared preamble matching the fixed commands/dev.md Step 10 template markers
# (:825 "You are the dev subagent.", :835 "baseline_head_sha:"). Deliberately
# does NOT contain "baseline_dirty_snapshot:" -- individual tests append it.
DEV_ROLE_PREAMBLE = (
    "FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/"
    "dev-20260923-121345/dev.json to register with the enforcement system. "
    "Do this BEFORE any other tool call.\n"
    "User requirement document: docs/dev/user-requirement-dev-20260923-121345.md\n\n"
    "You are the dev subagent. Follow agents/dev.md instructions precisely.\n\n"
    "Context file: docs/dev/context-20260923-121345-b.json\n"
    "BA spec file: docs/dev/ticket-20260923-121345-b.md\n"
    "Write your implementation report to: docs/dev/dev-report-20260923-121345-b.json\n"
    "baseline_head_sha: 51f0484b3e5b4e46304064cfc7ff759e1f2d3f61\n"
)


def _run_hook(prompt):
    """Pipe a synthetic PreToolUse Agent payload into the hook via subprocess."""
    payload = json.dumps({"tool_name": "Agent", "tool_input": {"prompt": prompt}})
    return subprocess.run(
        [sys.executable, HOOK],
        input=payload,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_ac1_missing_field_dev_dispatch_blocks():
    """AC1 (cf34a7e22319f57a): dev-role dispatch missing baseline_dirty_snapshot: exits 2.

    GIVEN a dev-role-shaped prompt with no "baseline_dirty_snapshot:" line
    WHEN the hook runs THEN it exits 2, stderr names the missing field, and
    stderr avoids "foreign or unaccounted-for edit" phrasing.
    """
    result = _run_hook(DEV_ROLE_PREAMBLE)
    assert result.returncode == 2
    assert "baseline_dirty_snapshot" in result.stderr
    assert "foreign or unaccounted-for edit" not in result.stderr


def test_ac2_present_field_dev_dispatch_passes():
    """AC2 (fdc8c2059d16f606): dev-role dispatch WITH baseline_dirty_snapshot: exits 0."""
    prompt = DEV_ROLE_PREAMBLE + "baseline_dirty_snapshot: M CLAUDE.md\n"
    result = _run_hook(prompt)
    assert result.returncode == 0


def test_ac2_present_field_empty_value_dev_dispatch_passes():
    """AC2 (fdc8c2059d16f606): empty-string value is documented-legitimate (agents/dev.md:533)."""
    prompt = DEV_ROLE_PREAMBLE + "baseline_dirty_snapshot: \n"
    result = _run_hook(prompt)
    assert result.returncode == 0


def test_ac3_non_dev_dispatch_missing_field_not_blocked():
    """AC3 (b194ec946489b76f): negative control -- non-dev dispatch, also missing
    the field, must never be false-blocked (no "baseline_head_sha:" anchor, so
    the dispatch cannot be positively identified as dev-role)."""
    prompt = (
        "You are the BA subagent. Follow agents/ba.md instructions precisely.\n"
        "Write your context file to: docs/dev/context-20260923-999999.json\n"
    )
    result = _run_hook(prompt)
    assert result.returncode == 0


def test_ac4_real_incident_20260923_083731_reconstructed_blocks():
    """AC4 (a42f0b4175a72495): fixture reconstructed from the commands/dev.md
    Step 10 template plus backlog #119's confirmed real-incident shape (task
    20260923-083731): dev-role markers present, baseline_dirty_snapshot: line
    entirely absent. Demonstrates the checkpoint would have caught the actual
    historical incident.
    """
    prompt = (
        "You are the dev subagent. Follow agents/dev.md instructions precisely.\n\n"
        "Context file: docs/dev/context-20260923-083731.json\n"
        "BA spec file: docs/dev/ticket-20260923-083731.md\n"
        "Write your implementation report to: docs/dev/dev-report-20260923-083731.json\n"
        "baseline_head_sha: 51f0484b3e5b4e46304064cfc7ff759e1f2d3f61\n"
    )
    result = _run_hook(prompt)
    assert result.returncode == 2
    assert "baseline_dirty_snapshot" in result.stderr
