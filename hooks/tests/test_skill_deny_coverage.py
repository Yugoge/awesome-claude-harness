"""P5 R5: every human-only harness command is denied to the agent's Skill tool.

`disable-model-invocation: true` blocks the SlashCommand route only; the `Skill(<stem>:*)` entry in
settings.json's permissions.deny is the barrier against an agent invoking a command itself (CLAUDE.md
lesson 15). Each commands/*.md stem (INDEX and README are no command) outside stop_contract's
CONTROL_COMMANDS needs its entry, so a new command file without one fails here, unless the harness's
own command or agent text invokes it through the Skill tool (`Skill(skill="<stem>")`): such a command
is the agents' by design, and a deny would refuse the call that text makes. The set is read from the
texts at test time, never listed here. Today it is codex: agents run the codex consultation under
`--codex`, and its ledger entry, which subagentstop-codex-enforce.py requires at each bound
subagent's stop, is written only by the Skill call's PostToolUse; a deny would leave every `--codex`
run's stops refused with no action that clears them (D25, D15).
"""
from __future__ import annotations

import glob
import json
import os
import re

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONTROL = {"allow", "restart", "checkpoint", "tickets", "rating"}
_SKILL_CALL = re.compile(r"""Skill\(skill=["']([a-z0-9_-]+)["']""")


def _deny() -> set:
    with open(os.path.join(ROOT, "settings.json"), encoding="utf-8") as fh:
        return set(json.load(fh)["permissions"]["deny"])


def _stems() -> set:
    return {name[:-3] for name in os.listdir(os.path.join(ROOT, "commands"))
            if name.endswith(".md") and name[:-3] not in ("INDEX", "README")}


def _agent_invoked() -> set:
    """Command stems the harness's own command, agent and skill texts call through the Skill tool."""
    found = set()
    for path in glob.glob(os.path.join(ROOT, "agents", "*.md")) + glob.glob(os.path.join(ROOT, "commands", "*.md")) \
            + glob.glob(os.path.join(ROOT, "skills", "**", "*.md"), recursive=True):
        with open(path, encoding="utf-8") as fh:
            found.update(_SKILL_CALL.findall(fh.read()))
    return found


def test_every_human_only_command_has_its_skill_deny():
    human_only = _stems() - CONTROL - _agent_invoked()
    missing = sorted(s for s in human_only if f"Skill({s}:*)" not in _deny())
    assert not missing, "human-only commands/*.md stems without a Skill(<stem>:*) deny: " + ", ".join(missing)


def test_a_human_only_control_command_keeps_its_skill_deny():
    """CONTROL_COMMANDS exempts a command from the requirement above; a control command whose own front
    matter says human-only (`disable-model-invocation: true`: allow, restart, checkpoint, rating) keeps its deny
    all the same, which the exemption would otherwise stop checking."""
    def human_only(stem: str) -> bool:
        with open(os.path.join(ROOT, "commands", f"{stem}.md"), encoding="utf-8") as fh:
            head = re.match(r"---\n(.*?)\n---", fh.read(), re.S)
        return bool(head and re.search(r"^disable-model-invocation:\s*true\s*$", head.group(1), re.M))

    guarded = sorted(s for s in CONTROL & _stems() if human_only(s))
    assert "rating" in guarded, guarded
    missing = [s for s in guarded if f"Skill({s}:*)" not in _deny()]
    assert not missing, "human-only control commands without a Skill(<stem>:*) deny: " + ", ".join(missing)


def test_no_command_the_texts_invoke_through_skill_is_denied():
    denied = sorted(s for s in _agent_invoked() & _stems() if f"Skill({s}:*)" in _deny())
    assert not denied, "commands the harness's own texts call with Skill(skill=...) are denied: " + ", ".join(denied)


def test_control_is_the_stop_contracts():
    import sys

    sys.path.insert(0, os.path.join(ROOT, "hooks"))
    try:
        from lib import stop_contract
    finally:
        sys.path.pop(0)
    assert set(stop_contract.CONTROL_COMMANDS) == CONTROL
