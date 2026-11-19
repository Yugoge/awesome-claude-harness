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
`*` holds a space. The rule sees the text before the shell expands it, so a word without a space can still
expand into several: `git -C [ap]* log --force main` became `git -C a push log --force main` and force-pushed
under the space guards alone. `git -C *\\**`, `git -C *?*` and `git -C *[*` (a literal `*`, `?` or `[`) ask for
any glob in a `git -C` command, after the verb too (`git -C x log --outpu?=f`). The CLI itself asks for the
other expansions of an unquoted word (brace expansion, `$NAME` but `$HOME`, backticks, `$( )`, extglob
groups); `~` and `$HOME` expand to the home directory. So only a directory written as one word with no glob
or expansion runs unasked. `git -C *--output*` asks for diff/log/show writing a file. `rg --files` runs no
`--pre` program, but `--hostname-bin` runs its program even under `--files` (measured on ripgrep 14.1.0), so
`rg --files *--hostname-bin*` asks, and rg's glob asks keep a glob from expanding into that option.
`make -n` prints recipes without running them, except what make evaluates itself: under GNU make 4.3,
`--eval` (and its abbreviations, `--ev`), `-E`, a command-line `V:=$(shell ...)` and a makefile read with
`-f`/`--file`/`--makefile` (stdin included) all ran a command. `make *--e*`, `make *-*E*` (rules match case
sensitively, measured: `make -n -e` and `make -n test` still run), `make *$*`, `make *-*f*` and make's glob asks
ask for them. Every make and rg ask is anchored at the allowed prefix (`make -n *...`, `rg --files *...`):
the CLI strips a bare `xargs` before it matches an ask rule, so an unanchored `rg *\\**` asked for
`find src -name "*.py" | xargs rg -n "TODO.*fix"`, which the base's `Bash(xargs:*)` ran unasked (measured).
Leftovers behind a bare xargs, measured ask where the base ran them: `xargs make -n "t*"`, `xargs git -C
src log "--format=%h*"` (the glob asks) and `xargs git -C src log --grep x log` (the space asks). Residual: the project's own Makefile still runs its `$(shell ...)`, `+` recipe lines and
`$(MAKE)` lines under `-n`.

`decide` models that matching; `_wildcard` follows the CLI's own matcher (the 2.1.326 binary: `*` becomes `.*`
with the dot matching newlines, a lone trailing ` *` also matches the bare prefix, runs of spaces and tabs
read as one space). MEASURED is the installed CLI's own decision (Claude Code 2.1.326), taken offline: a
throwaway HOME whose ~/.claude/settings.json held only this file's `permissions`, a local stand-in for the
Messages API that answered with one Bash tool_use carrying the command, `claude -p --permission-mode default`
in an empty project dir, and gh/git/make/pytest/rg shims first on PATH that only print that they ran. A
command ran (allow) or its tool_result said it needs approval (ask: "requires approval" when no rule allowed
it, "haven't granted it yet" when an ask rule matched) or was denied ("has been denied"). The CLI's built-in
read-only set (not configurable, not modelled here) allows a few forms with no entry; MEASURED records them.

Since 2026-11-19 no ask rule remains (docs/how-it-works.md, "Permission prompts"): the 19 guard asks only
narrowed these allow entries, and bypassPermissions mode, the harness's mode, does not read allow entries at
all, so there they prompted a person for calls the hooks already decide. They are removed. Everything measured
above stays as history, checked against `_then()`: today's allow and deny (unchanged) with the ask list of
tests/fixtures/permissions-ask-until-20261119.json. The "now" tests check the shipped settings: the read-only
commands still run; a command no allow entry covers still does not run unasked, and in default mode the
PermissionRequest hook refuses it; the guarded forms (NOW_UNGUARDED) are let through by the allow entries in
default mode and decided by the PreToolUse hooks alone, as every call is in bypassPermissions mode.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from tests.test_permission_ask_dry_run import OLD_ASK
from tests.test_no_permission_prompt import _payload, _run

REPO = Path(__file__).resolve().parent.parent

GH_READ = ["gh issue view", "gh pr checks", "gh pr diff", "gh pr list", "gh pr view", "gh run view"]
GIT_C_READ = ["diff", "log", "show", "status"]

NEW_ALLOW = (
    [f"Bash({v}:*)" for v in GH_READ]
    + [e for v in GIT_C_READ for e in (f"Bash(git -C * {v})", f"Bash(git -C * {v} *)")]
    + ["Bash(make -n:*)", "Bash(rg --files:*)"]
)
GLOB_ASK = [r"*\**", "*?*", "*[*"]
NEW_ASK = (
    [f"Bash(git -C * * {v}*)" for v in GIT_C_READ]
    + [f"Bash(git -C {g})" for g in GLOB_ASK]
    + ["Bash(git -C *--output*)"]
    + [f"Bash(make -n {g})" for g in GLOB_ASK]
    + ["Bash(make -n *$*)", "Bash(make -n *--e*)", "Bash(make -n *-*E*)", "Bash(make -n *-*f*)"]
    + [f"Bash(rg --files {g})" for g in GLOB_ASK]
    + ["Bash(rg --files *--hostname-bin*)"]
)
# b0e51172's ask list, the first round of this lane.
ROUND1_ASK = ([f"Bash(git -C * * {v}*)" for v in GIT_C_READ]
              + ["Bash(git -C *--output*)", "Bash(rg *--hostname-bin*)"])

MUST_PASS = ["gh pr view 12", "gh run view 1", "git -C src log --oneline -3", "git -C src status",
             "rg --files", "make -n"]
ALSO_PASS = ["gh pr list --state open", "gh pr diff 3", "gh pr checks 3", "gh issue view 4",
             "git -C src diff HEAD~1 -- a.py", "git -C src show HEAD", "git -C src log",
             "git -C src status --porcelain", "rg --files src", "make -n test", "make -n -e", "make -n -k all",
             "git -C ~ log", "git -C ~/src log", "git -C $HOME log"]
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
    "rg --files -g '*.py' src": ("ask", "ask"), "make -n test": ("ask", "allow"),
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

# The verifier's finding and its kin: a glob or expansion in a word with no space. Claude Code 2.1.326's own
# decision, measured as above: (base settings.json, b0e51172's, this one's).
GLOB_ATTACKS = {
    "git -C [ap]* log --force main": ("ask", "allow", "ask"), "git -C -* log": ("ask", "allow", "ask"),
    "git -C [-]* status": ("ask", "allow", "ask"), "git -C ?? log": ("ask", "allow", "ask"),
    "git -C x* log": ("ask", "allow", "ask"), "git -C x log --outpu?=f": ("ask", "allow", "ask"),
    "git -C src log *": ("ask", "allow", "ask"),
    "rg --files *": ("ask", "allow", "ask"), "rg --files [-]*": ("ask", "allow", "ask"),
    "rg --files ?": ("ask", "allow", "ask"), "rg --files -g '*.py' src": ("ask", "allow", "ask"),
    "make -n *": ("ask", "allow", "ask"), "make -n ?": ("ask", "allow", "ask"),
    "make -n --eval 'all: ; +touch X'": ("ask", "allow", "ask"),
    "make -n -f /dev/null --eval='$(shell touch X)'": ("ask", "allow", "ask"),
    "make -n --ev='all: ; +touch X'": ("ask", "allow", "ask"),
    "make -n -E 'all: ; +touch X'": ("ask", "allow", "ask"),
    "make -nE'all: ; +touch X'": ("ask", "ask", "ask"),
    "make -n -f /dev/null 'V:=$(shell touch X)'": ("ask", "allow", "ask"),
    "make -n -f -": ("ask", "allow", "ask"), "make -nf /dev/stdin": ("ask", "ask", "ask"),
    "make -n --file=/dev/stdin": ("ask", "allow", "ask"), "make -n --makefile=x": ("ask", "allow", "ask"),
    "echo 'all: ; +touch X' | make -n -f -": ("ask", "allow", "ask"),
}
# Forms the CLI asks for by itself, whatever the rules ("Brace expansion", "A variable in this command can't be
# checked before it runs", command substitution, "`(...)` group directly follows ... a word"): measured ask
# under all three settings files. The model does not reproduce these checks.
CLI_ASKS_ITSELF = ["git -C {a,push} log --force main", "git -C x{,} log", "git -C $D log", "git -C `echo a` log",
                   "git -C $(echo a) log", "git -C @(push) log", "git -C !(x) log", "git -C +(a) log",
                   "git -C x log @(a|b)", "rg --files {a,b}", "make -n {a,b}"]
# Measured (base, b0e51172, this file): one-word expansions to the home directory and plain make flags run.
HOME_FORMS = {"git -C ~ log": ("ask", "allow", "allow"), "git -C ~/src log": ("ask", "allow", "allow"),
              "git -C $HOME log": ("ask", "allow", "allow"), "make -n -e": ("ask", "allow", "allow"),
              "make -n -k all": ("ask", "allow", "allow"), "rg --files src": ("ask", "allow", "allow")}


# ------------------------------------------------------------------ the model
def _now() -> dict:
    return json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["permissions"]


def _perms() -> dict:
    """The permissions the tables were measured under: today's allow and deny with the ask list of that time."""
    return dict(_now(), ask=OLD_ASK)


def _bash(entries: list[str]) -> list[str]:
    return [e[5:-1] for e in entries if e.startswith("Bash(") and e.endswith(")")]


def _wildcard(rule: str, cmd: str) -> bool:
    """`\\*` is a literal star, every other character but `*` is literal, and matching is case-sensitive."""
    rule, cmd = re.sub(r"[ \t]+", " ", rule.strip()), re.sub(r"[ \t]+", " ", cmd.strip())
    rule = rule.replace("\\*", "\x00")
    rx = ".*".join(re.escape(p).replace("\x00", r"\*") for p in rule.split("*"))
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


def _forms(part: str) -> list[str]:
    """A subcommand as written and, after a bare `xargs` (no option), as the command xargs runs."""
    m = re.match(r"xargs\s+(?!-)(.+)", part, re.S)
    return [part, m.group(1)] if m else [part]


def decide(perms: dict, cmd: str) -> str:
    parts = subcommands(cmd)
    deny, ask, allow = (_bash(perms.get(k, [])) for k in ("deny", "ask", "allow"))
    if any(matches(r, f) for p in parts for f in _forms(p) for r in deny):
        return "deny"
    if any(matches(r, f) for p in parts for f in _forms(p) for r in ask):
        return "ask"
    return "allow" if all(p in BUILTIN_PARTS or any(matches(r, f) for f in _forms(p) for r in allow)
                          for p in parts) else "ask"


# Subcommands the CLI's built-in read-only set allows with no entry (measured: `git ls-files | xargs ...` ran on
# the base, whose allow list has no `git ls-files` entry).
BUILTIN_PARTS = {"git ls-files"}


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
    assert entry in OLD_ASK  # history
    assert not _now().get("ask") and entry not in _now()["deny"]  # now: removed, not turned into a refusal


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
    words = ["push", "--force", "reset", "--hard", "origin", "-c", "core.pager=sh", "--exec-path=/e", "[ap]*", "??",
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


@pytest.mark.parametrize("cmd", sorted(GLOB_ATTACKS))
def test_a_glob_or_make_evaluation_asks(cmd):
    base, _old, now = GLOB_ATTACKS[cmd]
    perms = _perms()
    assert decide(perms, cmd) == now == "ask"
    assert decide(_base(perms), cmd) == base


@pytest.mark.parametrize("cmd", sorted(GLOB_ATTACKS))
def test_the_glob_asks_are_what_refuse_it(cmd):
    """With b0e51172's ask list, the measured CLI ran each form that commit allowed; the model agrees."""
    perms = _perms()
    assert decide({**perms, "ask": ROUND1_ASK}, cmd) == GLOB_ATTACKS[cmd][1]


@pytest.mark.parametrize("cmd", sorted(HOME_FORMS))
def test_home_forms_and_plain_make_flags_still_run(cmd):
    assert decide(_perms(), cmd) == HOME_FORMS[cmd][2]


# Behind a bare xargs (measured: base, 81f1a027 with unanchored make/rg asks, this file).
XARGS = {
    'find src -name "*.py" | xargs rg -n "TODO.*fix"': ("allow", "ask", "allow"),
    'git ls-files | xargs rg -l "foo[0-9]"': ("allow", "ask", "allow"),
    'find src | xargs make -n "t*"': ("allow", "ask", "ask"),
    'find src | xargs git -C src log "--format=%h*"': ("allow", "ask", "ask"),
    'find src -name "*.py" | xargs git -C src log': ("allow", "allow", "allow"),
    "find src | xargs git -C src log --grep x log": ("allow", "ask", "ask"),
    "echo a | xargs rg --files": ("allow", "allow", "allow"),
    "echo a | xargs make -n": ("allow", "allow", "allow"),
}
# Anchored guards still ask (measured ask under all three).
ANCHORED_STILL_ASK = ["rg --files x*", "rg --files --hostname-bin=sh", "rg --files --hostname-b?n=sh",
                      'make -n --eval "all: ; +touch p"', "make -n -f x.mk", "make -n x*"]
UNANCHORED_81F1 = (ROUND1_ASK[:-1] + [f"Bash(git -C {g})" for g in GLOB_ASK]
                   + [f"Bash(make {g})" for g in GLOB_ASK]
                   + ["Bash(make *$*)", "Bash(make *--e*)", "Bash(make *-*E*)", "Bash(make *-*f*)"]
                   + [f"Bash(rg {g})" for g in GLOB_ASK] + ["Bash(rg *--hostname-bin*)"])


@pytest.mark.parametrize("cmd", sorted(XARGS))
def test_behind_xargs_the_measured_decision_holds(cmd):
    base, at_81f1, now = XARGS[cmd]
    perms = _perms()
    assert decide(_base(perms), cmd) == base
    assert decide({**perms, "ask": UNANCHORED_81F1}, cmd) == at_81f1
    assert decide(perms, cmd) == now


@pytest.mark.parametrize("cmd", ['find src -name "*.py" | xargs rg -n "TODO.*fix"',
                                 'git ls-files | xargs rg -l "foo[0-9]"'])
def test_xargs_rg_keeps_its_base_decision(cmd):
    assert decide(_perms(), cmd) == decide(_base(_perms()), cmd) == "allow"


@pytest.mark.parametrize("cmd", ANCHORED_STILL_ASK)
def test_the_anchored_guards_still_ask(cmd):
    assert decide(_perms(), cmd) == "ask"


def test_rule_matching_is_case_sensitive():
    """`make *-*E*` asks for -E and leaves -e and a target with a lower-case e alone (measured)."""
    perms = _perms()
    assert decide(perms, "make -n -E x") == "ask"
    assert decide(perms, "make -n -e") == decide(perms, "make -n test") == "allow"


def test_every_example_is_measured():
    assert set(MUST_PASS + ALSO_PASS + MUST_REFUSE + WILDCARD_ATTACKS) <= set(MEASURED) | set(HOME_FORMS)
    assert not set(GLOB_ATTACKS) & set(MUST_PASS + ALSO_PASS)


# ------------------------------------------------------------------ now (no ask rule)
# No allow entry covers these two (`make -n:*` needs `-n` as its own word): still no run unasked.
NOW_UNCOVERED = ["make -nE'all: ; +touch X'", "make -nf /dev/stdin"]
NOW_UNGUARDED = sorted((set(ASK_GUARDED) | {c for c, v in GLOB_ATTACKS.items() if v[2] == "ask"}
                        | set(ANCHORED_STILL_ASK)) - set(NOW_UNCOVERED))


@pytest.mark.parametrize("cmd", MUST_PASS + ALSO_PASS)
def test_now_read_only_command_runs(cmd):
    assert decide(_now(), cmd) == "allow"


@pytest.mark.parametrize("cmd", MUST_REFUSE + NOW_UNCOVERED)
def test_now_an_uncovered_command_is_refused_in_default_mode(cmd):
    """No allow entry covers it: the CLI would ask, and the PermissionRequest hook refuses instead."""
    assert decide(_now(), cmd) == "ask"
    assert _run(_payload("Bash", {"command": cmd}, mode="default"))["behavior"] == "deny"


@pytest.mark.parametrize("cmd", NOW_UNGUARDED)
def test_now_the_guarded_forms_are_left_to_the_hooks(cmd):
    """Pinned: with the guard asks gone, the allow entries pass these in default mode; the PreToolUse hooks
    decide them (git pushes and resets: hooks/pretool-git-privilege-guard.py), as in bypassPermissions mode."""
    assert decide(_now(), cmd) == "allow"
    assert decide(_perms(), cmd) == "ask"
