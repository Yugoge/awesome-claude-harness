"""P5 R5: every human-only harness command is denied to the agent's Skill tool.

`disable-model-invocation: true` blocks the SlashCommand route only; the `Skill(<stem>)` entry of the deny
list (policies/cli-deny.v1.json, decided by the pre-tool rule hooks/pretool-deny-list.py since 2026-11-21; it
was settings.json's permissions.deny) is the barrier against an agent invoking a command itself (CLAUDE.md
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


def _settings_deny() -> set:
    with open(os.path.join(ROOT, "settings.json"), encoding="utf-8") as fh:
        return set(json.load(fh)["permissions"].get("deny", []))


def _deny() -> set:
    with open(os.path.join(ROOT, "policies", "cli-deny.v1.json"), encoding="utf-8") as fh:
        return set(json.load(fh)["deny"]) | _settings_deny()


def test_the_only_skill_entry_left_in_settings_is_the_switchs():
    """Skill(harness) stays the CLI's: the off form keeps it (render-settings SWITCH_PERMISSIONS), when no hook runs."""
    assert {e for e in _settings_deny() if e.startswith("Skill(")} == {"Skill(harness)"}


def test_the_rule_refuses_every_human_only_command_as_owner_only():
    """The rule, not the matcher alone, refuses each human-only stem (bare, with `/`, with arguments)."""
    import subprocess
    import sys
    human_only = sorted(((_stems() - CONTROL - _agent_invoked()) | {s for s in CONTROL if f"Skill({s})" in _deny()})
                        - {s for s in _stems() if f"Skill({s})" in _settings_deny()})
    for stem in human_only:
        for ti in ({"skill": stem}, {"skill": "/" + stem, "args": "x y"}):
            p = subprocess.run([sys.executable, os.path.join(ROOT, "hooks", "pretool-deny-list.py")],
                               input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Skill",
                                                 "tool_input": ti, "cwd": ROOT}),
                               capture_output=True, text=True, timeout=60)
            assert p.returncode == 2 and "owner-only command" in p.stderr, (stem, ti, p.stderr)


def test_no_hook_makes_a_commands_effect_from_a_skill_call():
    """A model's Skill call, even one an /allow released, only loads the command's text: the effects of the
    owner's typed command (a grant, a consent, a command span) are written at UserPromptSubmit, from the prompt.
    The hooks that read a Skill call's tool_name either refuse it (harness switch, capability gate, this rule)
    or keep the codex ledger (agent-invoked by design)."""
    readers = set()
    for path in glob.glob(os.path.join(ROOT, "hooks", "*.py")) + glob.glob(os.path.join(ROOT, "hooks", "lib", "*.py")):
        with open(path, encoding="utf-8") as fh:
            if re.search(r"""tool_name\s*(==|!=|in)\s*\(?["']Skill["']|tool in \(["']Skill["']""", fh.read()):
                readers.add(os.path.relpath(path, ROOT))
    assert readers <= {"hooks/pretool-harness-switch-guard.py", "hooks/posttool-codex-skill-ledger.py",
                       "hooks/lib/capability_state.py"}, sorted(readers)


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
    missing = sorted(s for s in human_only if f"Skill({s})" not in _deny())
    assert not missing, "human-only commands/*.md stems without a Skill(<stem>) deny: " + ", ".join(missing)


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
    missing = [s for s in guarded if f"Skill({s})" not in _deny()]
    assert not missing, "human-only control commands without a Skill(<stem>) deny: " + ", ".join(missing)


def test_no_command_the_texts_invoke_through_skill_is_denied():
    denied = sorted(s for s in _agent_invoked() & _stems() if _denied(s))
    assert not denied, "commands the harness's own texts call with Skill(skill=...) are denied: " + ", ".join(denied)


def test_control_is_the_stop_contracts():
    import sys

    sys.path.insert(0, os.path.join(ROOT, "hooks"))
    try:
        from lib import stop_contract
    finally:
        sys.path.pop(0)
    assert set(stop_contract.CONTROL_COMMANDS) == CONTROL


# OB-L20: how the CLI matches a Skill rule against a Skill tool call. The docs give "`Skill(name)` for exact
# match, `Skill(name *)` for prefix match with any arguments" (https://code.claude.com/docs/en/skills.md,
# "Restrict Claude's skill access"); they say nothing on `Skill(name:*)` or on `Skill(name)` with arguments.
# Measured on the installed CLI 2.1.326, offline: a throwaway HOME whose settings.json held only the deny rule,
# probe skills and commands under it, a local stand-in for the Messages API answering with one Skill tool_use,
# `claude -p`; the tool_result read back was "Skill execution blocked by permission rules" or "Launching skill".
#   - `Skill(do)` refused {skill: do}, {skill: do, args: "fix the bug"}, {skill: /do} and {skill: /do, args};
#     it let docs run, and `Skill(dev)` let devops and dev-command run.
#   - `Skill(do:*)` and `Skill(do *)` both refused docs as well as do: each is a raw prefix of the skill name, so
#     the space of the documented `name *` form does not keep `docs` out. Neither is used for a deny here.
#   - The name is matched after a leading `/` is dropped; `DO`, `user:do` and `do fix the bug` resolve to no skill
#     ("Unknown skill"), so no other spelling of a command's name reaches it.
_RULE = re.compile(r"^Skill\(([^ :)]+)(:\*| \*)?\)$")


def _matches(rule: str, skill: str, args: str = "") -> bool:
    """The measured matcher: `Skill(x)` matches the name x with any arguments; `Skill(x:*)`/`Skill(x *)` any name
    that starts with x. `args` never changes the outcome; it is a parameter so the tests name the call they model."""
    m = _RULE.match(rule)
    if not m:
        return False
    name = skill[1:] if skill.startswith("/") else skill
    return name.startswith(m.group(1)) if m.group(2) else name == m.group(1)


def _denied(skill: str, args: str = "") -> bool:
    return any(_matches(rule, skill, args) for rule in _deny() if rule.startswith("Skill("))


# Names an agent must be able to call: skills a project or the owner commonly has whose name begins with a
# human-only command's stem, and codex (test_codex_skill_not_denied.py).
_MUST_PASS = ("docs", "devops", "commit-message", "domain-model", "testing", "codex")


def test_every_skill_deny_is_the_exact_form():
    loose = sorted(r for r in _deny() if r.startswith("Skill(") and not re.match(r"^Skill\([a-z0-9-]+\)$", r))
    assert not loose, "Skill denies that match as a raw name prefix (OB-L20): " + ", ".join(loose)


def test_skills_that_share_a_human_only_prefix_are_not_denied():
    assert [s for s in _MUST_PASS if _denied(s) or _denied(s, "some arguments")] == []


def test_human_only_commands_stay_denied_with_and_without_arguments():
    for skill, args in (("do", ""), ("do", "fix the bug"), ("/do", "fix the bug"), ("dev", ""), ("push", ""),
                        ("commit", ""), ("code-review", ""), ("code-review", "high")):
        assert _denied(skill, args), (skill, args)
    human_only = _stems() - CONTROL - _agent_invoked()
    assert [s for s in sorted(human_only) if not (_denied(s) and _denied(s, "x y") and _denied("/" + s))] == []


def test_each_skill_deny_refuses_its_own_name_and_no_other_known_name():
    # code-review is the CLI's built-in skill (tests/test_p9_parts_of_p10_rows.py BUILT_IN_SKILLS), not a command file.
    known = _stems() | set(_MUST_PASS) | {"code-review"} | {
        os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "skills", "*")) if os.path.isdir(p)}
    for rule in sorted(r for r in _deny() if r.startswith("Skill(")):
        hit = sorted(n for n in known if _matches(rule, n))
        assert hit == [_RULE.match(rule).group(1)], (rule, hit)


def test_the_model_reproduces_the_measured_prefix_over_block():
    """The red case of OB-L20, kept so the matcher above cannot drift into one that hides it."""
    assert _matches("Skill(do:*)", "docs") and _matches("Skill(do *)", "docs") and not _matches("Skill(do)", "docs")
    assert _matches("Skill(do)", "do", "fix the bug") and _matches("Skill(do)", "/do")
