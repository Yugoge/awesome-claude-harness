"""The deny rules of settings.json and the guard hooks decide the same commands without contradicting each other.

Claude Code runs the PreToolUse hooks first and then its permission rules, and a deny match wins over everything, a
hook's allow included; such a denial names no means and reaches no hook, so it is in no refusal record
(docs/how-it-works.md, "Permission prompts"). A general Bash deny entry may therefore stand only where no hook decides
the family, or where the hook refuses it always and it must stay unreleasable by /do or /allow. Two checks hold that:

* every general Bash deny entry of the shipped settings.json stands in DENY_TABLE with its reason, and the table holds
  no entry the file lacks;
* every command the hook suites pin as allowed by design (hooks/tests/allowed_by_design.py, read by those suites too)
  goes through the model of the CLI's matching (tests/test_permission_pipe_to_shell.py) and is not denied.

The three entries that broke the second check until 2026-11-20 (the joined-flags removal rule without a path, dd,
fdisk) are gone; the model's reading of the removal rules is pinned to the four probes of that day (CLI 2.1.322).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests.test_permission_pipe_to_shell import _permissions, decision

REPO = Path(__file__).resolve().parent.parent
NO_HOOK = "no hook decides this family"
UNRELEASABLE = "the hook refuses it always and it must stay unreleasable"

DENY_TABLE = {
    "Bash(docker rm:*)": NO_HOOK,            # the analyzer proves docker rm no filesystem removal; no rule refuses it
    "Bash(halt:*)": NO_HOOK,
    "Bash(poweroff:*)": NO_HOOK,
    "Bash(reboot:*)": NO_HOOK,
    "Bash(shutdown:*)": NO_HOOK,
    "Bash(su:*)": NO_HOOK,                   # read as an opaque runner
    "Bash(sudo:*)": NO_HOOK,                 # peeled as a wrapper, the inner command judged
    "Bash(kubectl delete:*)": NO_HOOK,       # the outward rule covers kubectl apply and create only
    "Bash(yarn publish:*)": NO_HOOK,         # the outward rule covers npm publish only
    "Bash(systemctl disable:*)": NO_HOOK,    # the service rule judges stop and restart only
    "Bash(systemctl enable:*)": NO_HOOK,
    "Bash(systemctl kill:*)": NO_HOOK,
    "Bash(systemctl reload-or-restart:*)": NO_HOOK,
    "Bash(systemctl reload:*)": NO_HOOK,
    "Bash(systemctl try-restart:*)": NO_HOOK,
    "Bash(mkfs:*)": UNRELEASABLE,            # mkfs, mkfs.<type> and shred are refused by the disk rule
    "Bash(rm -rf /:*)": UNRELEASABLE,        # the removal policy refuses a removal of the root
    "Bash(rm -rf /*:*)": UNRELEASABLE,
    "Bash(git reset --hard:*)": UNRELEASABLE,
    "Bash(git push --force:*)": UNRELEASABLE,  # the git guard refuses every force push before /do and /allow
    "Bash(git push -f:*)": UNRELEASABLE,
    # Kept by the ruling of 2026-11-20. The service rule lets units listed in CLAUDE_DEV_SYSTEMD run (empty on the
    # shipped settings); a machine that sets it meets these two entries refusing what the hook allows.
    "Bash(systemctl restart:*)": UNRELEASABLE,
    "Bash(systemctl stop:*)": UNRELEASABLE,
}

# Placeholders for the hook suites' templates: a project, the actor's own scratch directory, a session scratch.
SID, AGENT = "5e6f7a8b-1c2d-4e3f-9a0b-1c2d3e4f5a6b", "a1b2c3d4e5f60718"
ROOT = "/work/proj"
OWN = f"{ROOT}/.claude/scratch/{SID}/dev/{AGENT}"
SESSION_OWN = f"/var/tmp/tmpdir/{SID}"


def _allowed_by_design():
    spec = importlib.util.spec_from_file_location("allowed_by_design", REPO / "hooks" / "tests" / "allowed_by_design.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _allowed_commands() -> list[str]:
    m = _allowed_by_design()
    cmds = [t.format(own=OWN, root=ROOT, sid=SID, agent=AGENT) for t in m.OWN_SCRATCH_REMOVALS]
    cmds += [t.format(own=SESSION_OWN) for t in m.SESSION_SCRATCH_REMOVALS]
    return cmds + m.COMMAND_POSITION_PASSES + m.WORD_OUTSIDE_VERB_PASSES + m.PROBE_PASSES


def _general_bash_deny() -> list[str]:
    return [r for r in _permissions()["deny"] if r.startswith("Bash(") and r.endswith(":*)")]


def test_every_general_bash_deny_entry_stands_in_the_table():
    shipped = set(_general_bash_deny())
    assert not shipped - set(DENY_TABLE), f"deny entries without a reason: {sorted(shipped - set(DENY_TABLE))}"
    assert not set(DENY_TABLE) - shipped, f"table rows the file lacks: {sorted(set(DENY_TABLE) - shipped)}"
    assert set(DENY_TABLE.values()) <= {NO_HOOK, UNRELEASABLE}


def test_every_other_bash_deny_entry_guards_the_session_dirs_file():
    """The rest are the path rules around the session-directory registry; a new kind of entry needs a row above."""
    rest = [r for r in _permissions()["deny"] if r.startswith("Bash(") and not r.endswith(":*)")]
    assert rest and all("session_dirs" in r for r in rest), [r for r in rest if "session_dirs" not in r]


def test_the_lists_are_the_hook_suites_own():
    """Both hook suites read hooks/tests/allowed_by_design.py; neither holds a copy of its own."""
    for name, attr in (("test_removal_policy_own_scratch.py", "OWN_SCRATCH_REMOVALS"),
                       ("test_bash_safety_command_position.py", "COMMAND_POSITION_PASSES")):
        assert f"allowed_by_design.{attr}" in (REPO / "hooks" / "tests" / name).read_text(encoding="utf-8"), name


@pytest.mark.parametrize("cmd", _allowed_commands())
def test_a_command_the_hooks_allow_by_design_is_not_denied(cmd):
    assert decision(cmd) != "deny", cmd


# The four probes of 2026-11-20 (CLI 2.1.322, the three removal rules as deny; <own> a scratch folder of the prober).
REMOVAL_RULES = {"allow": [], "deny": ["Bash(rm -rf /*:*)", "Bash(rm -rf /:*)", "Bash(rm -rf:*)"]}
PROBES = [
    ("rm -fr {own}/p1", "not denied"),
    ("rm -r -f {own}/p2", "not denied"),
    ("true && rm -rf {own}/p3", "deny"),
    ("rm -rf {own}/p4", "deny"),
]


@pytest.mark.parametrize("cmd,want", PROBES)
def test_the_model_reproduces_the_removal_probes(cmd, want):
    got = decision(cmd.format(own=OWN), REMOVAL_RULES)
    assert (got == "deny") == (want == "deny"), (cmd, got)
    # The root-glob rule alone is the literal prefix `rm -rf /*`: it denies none of them.
    assert decision(cmd.format(own=OWN), {"allow": [], "deny": REMOVAL_RULES["deny"][:2]}) != "deny"
