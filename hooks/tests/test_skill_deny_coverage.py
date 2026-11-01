"""P5 R5: every harness command outside CONTROL is denied to the agent's Skill tool.

`disable-model-invocation: true` blocks the SlashCommand route only; the `Skill(<stem>:*)` entry in
settings.json's permissions.deny is the barrier against an agent invoking a command itself (CLAUDE.md
lesson 15). Each commands/*.md stem (INDEX and README are no command) outside stop_contract's
CONTROL_COMMANDS needs its entry, so a new command file without one fails here.
"""
from __future__ import annotations

import json
import os

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONTROL = {"allow", "restart", "checkpoint", "tickets"}


def _deny() -> set:
    with open(os.path.join(ROOT, "settings.json"), encoding="utf-8") as fh:
        return set(json.load(fh)["permissions"]["deny"])


def _stems() -> set:
    return {name[:-3] for name in os.listdir(os.path.join(ROOT, "commands"))
            if name.endswith(".md") and name[:-3] not in ("INDEX", "README")}


def test_every_command_outside_control_has_its_skill_deny():
    missing = sorted(s for s in _stems() - CONTROL if f"Skill({s}:*)" not in _deny())
    assert not missing, "commands/*.md stems outside CONTROL without a Skill(<stem>:*) deny: " + ", ".join(missing)


def test_control_is_the_stop_contracts_and_codex_is_denied():
    import sys

    sys.path.insert(0, os.path.join(ROOT, "hooks"))
    try:
        from lib import stop_contract
    finally:
        sys.path.pop(0)
    assert set(stop_contract.CONTROL_COMMANDS) == CONTROL
    assert "Skill(codex:*)" in _deny()
    assert "codex" in _stems()
