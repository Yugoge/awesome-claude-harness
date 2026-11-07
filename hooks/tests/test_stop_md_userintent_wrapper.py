#!/usr/bin/env python3
"""/stop's wrapper call, as commands/stop.md spells it, is a run the user-intent guard recognizes (P2 R6).

commands/stop.md runs the release wrapper through the CLAUDE_HOME channel. hooks/pretool-wrapper-
userintent.py lets that wrapper run only after a human-typed /stop and refuses an agent's run of it; it
recognizes a run by the command's text, so the respelled call has to match its `stop` wrapper pattern.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _implementation_calls() -> list[str]:
    text = (REPO / "commands" / "stop.md").read_text(encoding="utf-8")
    section = text.split("\n## Implementation\n", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"```bash\n(.*?)```", section, re.S)


def test_stop_md_runs_the_wrapper_through_the_channel():
    assert _implementation_calls() == ['bash "${CLAUDE_HOME:-$HOME/.claude}/hooks/stop.sh"\n']


def test_the_userintent_guard_matches_the_stop_md_call():
    spec = importlib.util.spec_from_file_location("wrapper_userintent_stop_md",
                                                  REPO / "hooks" / "pretool-wrapper-userintent.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    for call in _implementation_calls():
        assert guard._matched_wrapper(call) == "stop"
