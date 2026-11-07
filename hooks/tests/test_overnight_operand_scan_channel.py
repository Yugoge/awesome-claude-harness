#!/usr/bin/env python3
"""The overnight guard's operand scan reads a harness script named through the CLAUDE_HOME channel (P2 R6).

The commands run harness scripts as `bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/x.sh"`. For an
overnight actor's interpreter call, hooks/pretool-overnight-hook-guard.py scans each script operand:
a readable script is read for a main-targeting git op, and a script it cannot read fails closed when
the command names the main root. The scan reads the channel spelling at the path the shell expands it
to (CLAUDE_HOME, else the harness home the hook runs from), so it gives the verdict the expanded path
gets: a clean harness script naming the main root passes, a script hiding a main-targeting git op and
an unreadable operand naming the main root are refused as before.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CH = '"${CLAUDE_HOME:-$HOME/.claude}'


def _guard():
    spec = importlib.util.spec_from_file_location("overnight_guard_channel_scan",
                                                  REPO / "hooks" / "pretool-overnight-hook-guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def main(tmp_path, monkeypatch):
    """A main root holding a session record, with no protected branch the scan could read."""
    root = tmp_path / "toy"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "overnight-state-s.json").write_text('{"session_id": "s", "main_root": "%s"}\n' % root)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return root


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A harness home named by CLAUDE_HOME: a clean status script and one hiding a main checkout."""
    h = tmp_path / "harness"
    (h / "scripts").mkdir(parents=True)
    (h / "scripts" / "status.sh").write_text('#!/bin/bash\npython3 -c "print(1)" "$1"\n')
    (h / "scripts" / "sneaky.sh").write_text('#!/bin/bash\ngit -C "$1" checkout other\n')
    monkeypatch.setenv("CLAUDE_HOME", str(h))
    return h


def _verdicts(guard, main: Path, script: str, expanded: str) -> tuple[bool, bool]:
    """The scan's verdict for the channel spelling and for the expanded path, the record as operand."""
    state = f"{main}/.claude/overnight-state-s.json"
    channel = guard._scan_script_files_for_main_git(f'bash {CH}/{script}" {state}', str(main))
    plain = guard._scan_script_files_for_main_git(f"bash {expanded} {state}", str(main))
    return channel, plain


def test_a_clean_harness_script_naming_the_main_root_passes(main, home):
    assert _verdicts(_guard(), main, "scripts/status.sh", home / "scripts" / "status.sh") == (False, False)


def test_a_harness_script_hiding_a_main_targeting_git_op_is_still_refused(main, home):
    assert _verdicts(_guard(), main, "scripts/sneaky.sh", home / "scripts" / "sneaky.sh") == (True, True)


def test_an_unreadable_channel_operand_fails_closed_when_the_main_root_is_named(main, home):
    guard = _guard()
    assert _verdicts(guard, main, "scripts/absent.sh", home / "scripts" / "absent.sh") == (True, True)
    assert guard._scan_script_files_for_main_git(f'bash {CH}/scripts/absent.sh" --help', str(main)) is False


def test_without_claude_home_the_channel_names_the_hook_s_own_harness_home(main, monkeypatch):
    monkeypatch.delenv("CLAUDE_HOME", raising=False)
    script = "scripts/overnight-status.sh"
    assert _verdicts(_guard(), main, script, REPO / script) == (False, False)
