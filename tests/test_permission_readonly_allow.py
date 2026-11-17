"""OB-L07: read-only commands the allow list lacked run without a prompt; nothing that writes gains an entry.

Root cause: settings.json's permissions.allow had no entry for a few everyday read-only commands, so the CLI
asked for each (and a headless or overnight run, where nobody answers, was refused): `gh pr view 12`,
`gh run view 1`, `git -C src log --oneline -3`, `git -C src status`, `rg --files`, `make -n`. The git entries
are anchored at `git <sub>`, so no `git -C <dir> ...` spelling matched one.

The owner's scope: gh's read verbs (pr view, pr list, pr diff, pr checks, run view, issue view), `git -C <dir>`
with a read verb (log, status, diff, show), `rg --files` and `make -n`. Test runners, builds and gh's
mutating verbs stay as they are.

How the CLI matches (code.claude.com/docs/en/permissions.md): "Bash rules match the whole command text, with
`*` standing in for any text"; "The `:*` suffix is an equivalent way to write a trailing wildcard"; "Rules are
evaluated in order: deny, then ask, then allow"; "Every subcommand must be allowed for a compound command to
run without a prompt" and "Deny and ask rules apply when any subcommand matches them"; "A push written another
way, such as `git -C . push`, isn't matched" by `Bash(git push *)`. A `*` also matches spaces, so an allow
`git -C * log *` alone would approve `git -C x push --force origin log` (a push of a ref named log; the
`git push --force` deny does not see the `-C` spelling) and `git -C x -c core.pager=sh log`. Each `git -C`
verb therefore has an ask rule `git -C * * <verb>*`, which matches exactly when the text at the directory's
`*` holds a space, so only a one-word directory runs unasked. `git -C *--output*` asks for diff/log/show
writing a file. `rg --files` runs no `--pre` program, but `--hostname-bin` runs its program even under
`--files` (measured on ripgrep 14.1.0), so `rg *--hostname-bin*` asks.

`decide` models that matching; `_wildcard` follows the CLI's own matcher (the 2.1.326 binary: `*` becomes `.*`
with the dot matching newlines, a lone trailing ` *` also matches the bare prefix, runs of spaces and tabs
read as one space). MEASURED is the installed CLI's own decision (Claude Code 2.1.326), taken offline: a
throwaway HOME whose ~/.claude/settings.json held only this file's `permissions`, a local stand-in for the
Messages API that answered with one Bash tool_use carrying the command, `claude -p --permission-mode default`
in an empty project dir, and gh/git/make/pytest/rg shims first on PATH that only print that they ran. A
command ran (allow) or its tool_result said it needs approval (ask: "requires approval" when no rule allowed
it, "haven't granted it yet" when an ask rule matched) or was denied ("has been denied"). The CLI's built-in
read-only set (not configurable, not modelled here) allows a few forms with no entry; MEASURED records them.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

GH_READ = ["gh issue view", "gh pr checks", "gh pr diff", "gh pr list", "gh pr view", "gh run view"]
GIT_C_READ = ["diff", "log", "show", "status"]

NEW_ALLOW = (
    [f"Bash({v}:*)" for v in GH_READ]
    + [e for v in GIT_C_READ for e in (f"Bash(git -C * {v})", f"Bash(git -C * {v} *)")]
    + ["Bash(make -n:*)", "Bash(rg --files:*)"]
)
NEW_ASK = (
    [f"Bash(git -C * * {v}*)" for v in GIT_C_READ]
    + ["Bash(git -C *--output*)", "Bash(rg *--hostname-bin*)"]
)

MUST_PASS = ["gh pr view 12", "gh run view 1", "git -C src log --oneline -3", "git -C src status",
             "rg --files", "make -n"]
ALSO_PASS = ["gh pr list --state open", "gh pr diff 3", "gh pr checks 3", "gh issue view 4",
             "git -C src diff HEAD~1 -- a.py", "git -C src show HEAD", "git -C src log",
             "git -C src status --porcelain", "rg --files -g '*.py' src", "make -n test"]
# The lane's must-still-refuse examples: none of them may run unasked.
MUST_REFUSE = ["git -C x push --force", "git -C x reset --hard", "gh api -X POST repos/o/r/pulls",
               "gh pr merge 1", "rg --pre sh x", "pytest -q", "make test"]
# A wildcard of the new entries reaching a mutating verb, an option that runs a program, or a file write.
WILDCARD_ATTACKS = [
    "gh pr view 1 && gh pr merge 1", "gh pr view 1; gh pr close 1",
    "git -C x log; git -C x push", "git -C x status && git -C x reset --hard",
    "git -C x push --force origin log", "git -C x reset --hard status", "git -C x push origin show",
    "git -C x checkout -- . diff", "git -C x -c core.pager=sh log", "git -C x --exec-path=/e status",
    "git -C x\tpush\t--force\torigin\tlog", 'git -C "a b" log',
    "git -C x diff --output=/tmp/f", "git -C x log --output=/tmp/f",
    "gh pr comment 1 -b x", "gh issue close 1", "gh run rerun 1", "gh pr viewer 1",
    "rg --files --hostname-bin ./e", "rg --files --hostname-bin=./e src",
    "make install", "make -n; make install", "make -nothing",
]
# Commands whose refusal comes from an ask rule of this lane (without it the new allow entries would pass them).
ASK_GUARDED = [
    "git -C x push --force origin log", "git -C x reset --hard status", "git -C x push origin show",
    "git -C x checkout -- . diff", "git -C x -c core.pager=sh log", "git -C x --exec-path=/e status",
    "git -C x\tpush\t--force\torigin\tlog", 'git -C "a b" log',
    "git -C x diff --output=/tmp/f", "git -C x log --output=/tmp/f",
    "rg --files --hostname-bin ./e", "rg --files --hostname-bin=./e src",
]

# Claude Code 2.1.326's own decision (method in the module docstring): (base settings.json, this settings.json).
# "allow" ran; "ask" needed approval; "deny" was denied.
MEASURED = {
    "gh pr view 12": ("ask", "allow"), "gh run view 1": ("ask", "allow"),
    "git -C src log --oneline -3": ("ask", "allow"), "git -C src status": ("ask", "allow"),
    "rg --files": ("ask", "allow"), "make -n": ("ask", "allow"),
    "gh pr list --state open": ("ask", "allow"), "gh pr diff 3": ("ask", "allow"),
    "gh pr checks 3": ("ask", "allow"), "gh issue view 4": ("ask", "allow"),
    "git -C src diff HEAD~1 -- a.py": ("ask", "allow"), "git -C src show HEAD": ("ask", "allow"),
    "git -C src log": ("ask", "allow"), "git -C src status --porcelain": ("ask", "allow"),
    "rg --files -g '*.py' src": ("ask", "allow"), "make -n test": ("ask", "allow"),
    "git -C x push --force": ("ask", "ask"), "git -C x reset --hard": ("ask", "ask"),
    "gh api -X POST repos/o/r/pulls": ("ask", "ask"), "gh pr merge 1": ("ask", "ask"),
    "rg --pre sh x": ("ask", "ask"), "pytest -q": ("ask", "ask"), "make test": ("ask", "ask"),
    "gh pr view 1 && gh pr merge 1": ("ask", "ask"), "gh pr view 1; gh pr close 1": ("ask", "ask"),
    "git -C x log; git -C x push": ("ask", "ask"), "git -C x status && git -C x reset --hard": ("ask", "ask"),
    "git -C x push --force origin log": ("ask", "ask"), "git -C x reset --hard status": ("ask", "ask"),
    "git -C x push origin show": ("ask", "ask"), "git -C x checkout -- . diff": ("ask", "ask"),
    "git -C x -c core.pager=sh log": ("ask", "ask"), "git -C x --exec-path=/e status": ("ask", "ask"),
    "git -C x\tpush\t--force\torigin\tlog": ("ask", "ask"), 'git -C "a b" log': ("ask", "ask"),
    "git -C x diff --output=/tmp/f": ("ask", "ask"), "git -C x log --output=/tmp/f": ("ask", "ask"),
    "gh pr comment 1 -b x": ("ask", "ask"), "gh issue close 1": ("ask", "ask"),
    "gh run rerun 1": ("ask", "ask"), "gh pr viewer 1": ("ask", "ask"),
    "rg --files-with-matches foo": ("allow", "allow"),  # the CLI's built-in read-only set, no entry
    "rg --files --hostname-bin ./e": ("ask", "ask"), "rg --files --hostname-bin=./e src": ("ask", "ask"),
    "make install": ("ask", "ask"), "make -n; make install": ("ask", "ask"), "make -nothing": ("ask", "ask"),
    "git push --force": ("deny", "deny"), "git log --oneline -3": ("allow", "allow"),
}
# With this file's allow list but no ask rules, each ASK_GUARDED command ran (measured the same way).
MEASURED_WITHOUT_ASK = {cmd: "allow" for cmd in ASK_GUARDED}
BUILTIN_READ_ONLY = {"rg --files-with-matches foo"}


# ------------------------------------------------------------------ the model
def _perms() -> dict:
    return json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["permissions"]


def _bash(entries: list[str]) -> list[str]:
    return [e[5:-1] for e in entries if e.startswith("Bash(") and e.endswith(")")]


def _wildcard(rule: str, cmd: str) -> bool:
    rule, cmd = re.sub(r"[ \t]+", " ", rule.strip()), re.sub(r"[ \t]+", " ", cmd.strip())
    rx = ".*".join(re.escape(p) for p in rule.split("*"))
    if rule.endswith(" *") and rule.count("*") == 1:
        rx = rx[: -len(re.escape(" ") + ".*")] + "( .*)?"
    return re.fullmatch(rx, cmd, re.S) is not None


def matches(rule: str, cmd: str) -> bool:
    if rule.endswith(":*") and "*" not in rule[:-2]:
        rule = rule[:-2] + " *"
    return _wildcard(rule, cmd)


def subcommands(cmd: str) -> list[str]:
    """Split at the documented separators (&&, ||, ;, |, |&, &, newline) outside quotes."""
    out, cur, i, q = [], "", 0, None
    while i < len(cmd):
        c = cmd[i]
        if q:
            q = None if c == q else q
            cur += c; i += 1; continue
        if c in "'\"":
            q = c; cur += c; i += 1; continue
        m = re.match(r"&&|\|\||\|&|[;|&\n]", cmd[i:])
        if m:
            out.append(cur); cur = ""; i += len(m.group(0)); continue
        cur += c; i += 1
    out.append(cur)
    return [s.strip() for s in out if s.strip()]


def decide(perms: dict, cmd: str) -> str:
    parts = subcommands(cmd)
    deny, ask, allow = (_bash(perms.get(k, [])) for k in ("deny", "ask", "allow"))
    if any(matches(r, p) for p in parts for r in deny):
        return "deny"
    if any(matches(r, p) for p in parts for r in ask):
        return "ask"
    return "allow" if all(any(matches(r, p) for r in allow) for p in parts) else "ask"


def _base(perms: dict) -> dict:
    """This file's permissions without the lane's entries: the base allow list and its empty ask list."""
    return {"allow": [e for e in perms["allow"] if e not in NEW_ALLOW],
            "ask": [e for e in perms.get("ask", []) if e not in NEW_ASK], "deny": perms["deny"]}


# ------------------------------------------------------------------ the entries
@pytest.mark.parametrize("entry", NEW_ALLOW)
def test_each_read_only_allow_entry_is_present(entry):
    assert entry in _perms()["allow"]


@pytest.mark.parametrize("entry", NEW_ASK)
def test_each_guarding_ask_entry_is_present(entry):
    assert entry in _perms()["ask"]


def test_no_entry_the_lane_forbids():
    allow = _perms()["allow"]
    assert "Bash(rg:*)" not in allow and "Bash(rg *)" not in allow
    assert "Bash(git -C:*)" not in allow and "Bash(git -C *)" not in allow
    assert [e for e in allow if e.startswith("Bash(rg")] == ["Bash(rg --files:*)"]
    assert [e for e in allow if e.startswith("Bash(make")] == ["Bash(make -n:*)"]
    assert not [e for e in allow if re.match(r"Bash\((pytest(?! tests/generated)|make test|npm test)", e)]
    gh = {e for e in allow if e.startswith("Bash(gh ")}
    assert gh == {"Bash(gh auth:*)"} | {f"Bash({v}:*)" for v in GH_READ}


def test_every_git_C_allow_is_a_read_verb_with_its_guard():
    """A `git -C` allow names a read verb and has the ask rule that stops its `*` reaching another verb."""
    perms = _perms()
    for entry in _bash(perms["allow"]):
        if entry.startswith("git -C"):
            m = re.fullmatch(r"git -C \* (\w+)(?: \*)?", entry)
            assert m and m.group(1) in GIT_C_READ, entry
            assert f"Bash(git -C * * {m.group(1)}*)" in perms["ask"], entry


# ------------------------------------------------------------------ the decisions
@pytest.mark.parametrize("cmd", MUST_PASS + ALSO_PASS)
def test_read_only_command_runs_without_prompt(cmd):
    assert decide(_perms(), cmd) == "allow"


@pytest.mark.parametrize("cmd", MUST_PASS + ALSO_PASS)
def test_read_only_command_asked_before(cmd):
    assert decide(_base(_perms()), cmd) == "ask"


@pytest.mark.parametrize("cmd", MUST_REFUSE + WILDCARD_ATTACKS)
def test_mutating_or_executing_command_still_refused(cmd):
    assert decide(_perms(), cmd) != "allow"


@pytest.mark.parametrize("cmd", ASK_GUARDED)
def test_the_ask_rules_are_what_refuse_a_wildcard_attack(cmd):
    perms = _perms()
    assert decide(perms, cmd) == "ask"
    assert decide({**perms, "ask": []}, cmd) == "allow"


def test_the_existing_force_push_deny_does_not_see_the_C_spelling():
    """Why the git -C allow must never cover push: the deny is prefix-anchored at `git push`."""
    perms = _perms()
    assert decide(perms, "git push --force") == "deny"
    assert decide(perms, "git -C x push --force") == "ask"


def test_no_spaced_directory_slot_reaches_an_allow():
    """Property: whatever text with a space sits in the directory's place, a git -C command never runs unasked."""
    perms = _perms()
    rng = random.Random(7)
    words = ["push", "--force", "reset", "--hard", "origin", "-c", "core.pager=sh", "--exec-path=/e",
             "checkout", "commit", "-am", "x", "log", "status", "diff", "show", "--", "."]
    for _ in range(2000):
        slot = " ".join(rng.choice(words) for _ in range(rng.randint(2, 5)))
        verb = rng.choice(GIT_C_READ)
        tail = rng.choice(["", " --oneline", " HEAD", " -3"])
        assert decide(perms, f"git -C {slot} {verb}{tail}") != "allow", slot


# ------------------------------------------------------------------ the measurement
@pytest.mark.parametrize("cmd", sorted(MEASURED))
def test_the_model_agrees_with_the_measured_cli(cmd):
    base, now = MEASURED[cmd]
    perms = _perms()
    if cmd in BUILTIN_READ_ONLY:
        return
    assert decide(_base(perms), cmd) == base
    assert decide(perms, cmd) == now


@pytest.mark.parametrize("cmd", sorted(MEASURED_WITHOUT_ASK))
def test_the_measured_cli_ran_the_attack_without_the_ask_rules(cmd):
    assert decide({**_perms(), "ask": []}, cmd) == MEASURED_WITHOUT_ASK[cmd]


def test_every_example_is_measured():
    assert set(MUST_PASS + ALSO_PASS + MUST_REFUSE + WILDCARD_ATTACKS) <= set(MEASURED)
