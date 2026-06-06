"""Shared /dev-overnight session detection for PreToolUse hooks.

Single source of truth for "is a /dev-overnight session currently live?". A
session is live iff a `<project>/.claude/overnight-state-*.json` file exists with
a non-empty body, `current_phase` not in {complete, completed}, and an `end_time`
that has not yet passed.

Detection is deliberately session-agnostic: ANY live overnight-state file under a
candidate project dir counts. The "except dev-overnight" policy means the whole
overnight CONTEXT — the orchestrator AND the subagents it dispatches — is exempt,
and those subagents carry DIFFERENT session_ids than the orchestrator that wrote
the state file (see hooks/lib/allowlist.py). Binding the exemption to a single
owning session_id would therefore wrongly block legitimate overnight subagents.
Forgery of the state file is out of scope for this guardrail: writes to
.claude/overnight-state-*.json are already blocked by
pretool-overnight-hook-guard.py, and the /do and /allow escape hatches exist for
everything else.

Mirrors the canonical probe previously inlined in pretool-git-privilege-guard.py
(`_is_overnight_active` / `_state_file_is_live`). Stdlib-only; never raises (every
probe fails closed → "not active").
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _end_time_passed(end_str):
    """True iff end_str (ISO-8601) is in the past, or is missing/unparseable.

    A missing or malformed end_time is treated as "passed" so a half-written
    state file never counts as a live session (fail closed).
    """
    try:
        end = datetime.fromisoformat(str(end_str).replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        return True
    if end.tzinfo is None:
        return datetime.now() > end
    return datetime.now(timezone.utc) > end


def _state_file_is_live(sf):
    """True iff state file `sf` describes an in-progress overnight session."""
    try:
        if sf.stat().st_size == 0:
            return False
        state = json.loads(sf.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(state, dict):
        return False
    if state.get('current_phase', '') in ('complete', 'completed'):
        return False
    if _end_time_passed(state.get('end_time', '')):
        return False
    return True


def candidate_project_dirs(project_dir=None):
    """Ordered, de-duplicated dirs whose .claude/ may hold the state file.

    Precedence: explicit project_dir arg → $CLAUDE_PROJECT_DIR → cwd →
    git-toplevel. The state file lives in the MAIN repo's .claude/, so a subagent
    running inside a worktree still resolves it via $CLAUDE_PROJECT_DIR (set by
    the harness to the main repo).
    """
    dirs = []
    for d in (project_dir, os.environ.get('CLAUDE_PROJECT_DIR')):
        if d and d not in dirs:
            dirs.append(d)
    try:
        cwd = os.getcwd()
        if cwd and cwd not in dirs:
            dirs.append(cwd)
    except Exception:
        pass
    try:
        top = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=3,
        )
        if top.returncode == 0:
            t = (top.stdout or '').strip()
            if t and t not in dirs:
                dirs.append(t)
    except Exception:
        pass
    return dirs


def is_overnight_active(project_dir=None):
    """True iff a live overnight-state-*.json exists under any candidate project
    dir's .claude/. Fails closed (returns False) on any error."""
    try:
        for d in candidate_project_dirs(project_dir):
            try:
                state_files = Path(d).glob('.claude/overnight-state-*.json')
            except Exception:
                continue
            for sf in state_files:
                if _state_file_is_live(sf):
                    return True
        return False
    except Exception:
        return False
