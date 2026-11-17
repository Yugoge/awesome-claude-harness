"""The publish and apply verbs that have a harmless dry run prompt instead of being refused (OB-L21).

`Bash(kubectl apply:*)`, `Bash(kubectl create:*)` and `Bash(npm publish:*)` were whole-verb deny entries,
so `kubectl apply --dry-run=client -f k8s/deploy.yaml` was refused like a real apply, and a deny entry
cannot carry an exception: "An allow rule can't carve an exception out of a deny rule"
(code.claude.com/docs/en/permissions.md, "Manage permissions"). The owner moved these three verbs to
`permissions.ask`; every other entry (`Bash(kubectl delete:*)`, `Bash(yarn publish:*)` among them) stays.

Documented (code.claude.com/docs/en/permissions.md): deny, then ask, then allow ("a matching ask rule
prompts even when a more specific allow rule also matches the same call", so `Bash(npm:*)` in allow does
not let `npm publish` run); deny and ask apply to any subcommand of a compound command; deny and ask match
past a leading assignment, allow does not; the wrappers timeout, time, nice, nohup, stdbuf, command,
builtin and noglob are stripped.

Measured on Claude Code 2.1.326 and not documented, modelled below as TIERS: a rule that matches the
command text exactly (a rule with no `*`, or `P:*` against the bare `P`) is decided before any wildcard
match, deny before ask inside each tier, allow only when neither matched; ask and allow rules are also
matched past `sudo` (with its options) and `env`. So the first spelling, `Bash(npm publish:*)` in ask,
matched `sudo npm publish` (past `sudo`) in the exact tier and outranked the wildcard deny
`Bash(sudo:*)`: `sudo npm publish`, `sudo kubectl apply` and their wrapped forms fell from deny to ask.
Each verb is therefore spelled as two ask entries with a `*` inside the program name,
`Bash(n*pm publish)` for the bare verb and `Bash(n*pm publish *)` for the verb with arguments: both sit
in the wildcard tier, where `Bash(sudo:*)` is decided first. One entry `Bash(n*pm publish *)` is not
enough: with a `*` before it, the trailing ` *` no longer matches the bare `npm publish` (measured: it ran
unasked). The inner `*` widens the match only to commands that end in `npm publish`, `kubectl apply` or
`kubectl create` (with or without arguments) after other text: `nXpm publish` or `npx npm publish` now
ask, which only adds a prompt; `kubectl applyset`, `kubectl create-foo` and `npm publisher` do not match.

Method of the measurement: claude -p --permission-mode default, a throwaway HOME holding only a
`permissions` block, a throwaway cwd, a local mock Messages API issuing one Bash tool_use, and stand-in
`npm`/`kubectl` programs on PATH. MEASURED records the decisions; the model must reproduce them.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.test_permission_coverage import rule_covers, simple_commands

REPO = Path(__file__).resolve().parent.parent
SETTINGS = REPO / "settings.json"
LEFT_DENY = ["Bash(kubectl apply:*)", "Bash(kubectl create:*)", "Bash(npm publish:*)"]
ASK_ENTRIES = ["Bash(k*ubectl apply *)", "Bash(k*ubectl apply)", "Bash(k*ubectl create *)",
               "Bash(k*ubectl create)", "Bash(n*pm publish *)", "Bash(n*pm publish)"]
KEPT_DENY = ["Bash(kubectl delete:*)", "Bash(yarn publish:*)", "Bash(sudo:*)"]
DOC_WRAPPERS = re.compile(r"^(?:(?:timeout|nice|stdbuf)(?:\s+-\S+)*(?:\s+\d\S*)?|time|nohup|command|builtin|noglob)\s+")
MEASURED_WRAPPERS = re.compile(r"^(?:sudo(?:\s+(?:-[uUgCh]\s+\S+|--\w[\w-]*=\S+|-\w+))*|env)\s+")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*\s+")
READ_ONLY = {"ls", "cat", "echo", "pwd", "head", "tail", "grep", "find", "wc", "which", "diff", "stat", "du", "cd"}

# Must become a prompt, not a refusal.
DRY_RUNS = [
    "kubectl apply --dry-run=client -f k8s/deploy.yaml",
    "kubectl create deployment web --image=nginx --dry-run=client -o yaml",
    "npm publish --dry-run",
]
# Must still prompt or be refused: these forms never run unasked. Not covered, and measured running unasked on
# the base and after OB-L21 alike (outside this lane): `bash -c "npm publish"` (allow Bash(bash:*)),
# `npm --registry=URL publish` and `npm pub` (allow Bash(npm:*)), `echo publish | xargs npm` (allow Bash(xargs:*)).
REAL_RUNS = [
    "kubectl apply -f k8s/deploy.yaml",
    "kubectl apply --dry-run=none -f x",
    "npm publish --dry-run=false",
    "npm publish",
    "kubectl apply",
    "kubectl create",
    "kubectl create namespace prod",
    "kubectl create -f k8s/deploy.yaml",
    # compound, wrapped and assignment-led forms of the same verbs
    "npm run build && npm publish",
    "cd pkg && npm publish --access public",
    "NPM_TOKEN=t npm publish",
    "nohup npm publish",
    "timeout 60 kubectl apply -f k8s/deploy.yaml",
    "echo $(kubectl create secret generic s --from-literal=a=b)",
    "ls; kubectl apply -k overlays/prod",
]
# Denied on the base and denied still: kubectl delete, yarn publish, and every sudo form of the three verbs,
# bare ones included (the first spelling let the bare sudo forms fall to ask).
STILL_DENIED = [
    "kubectl delete pod web",
    "kubectl delete -f k8s/deploy.yaml --dry-run=client",
    "yarn publish",
    "yarn publish --new-version 1.2.3",
    "sudo npm publish",
    "sudo -u root npm publish",
    "echo a | sudo npm publish",
    "timeout 5 sudo npm publish",
    "sudo env npm publish",
    "nohup sudo npm publish",
    "FOO=1 sudo npm publish",
    "sudo kubectl apply",
    "sudo kubectl create",
    "sudo -E kubectl create",
    "echo a | sudo -u root kubectl apply",
    "sudo npm publish --dry-run",
]

# Measured on 2.1.326: deny, ask (an ask rule matched), prompt (the CLI's own approval request for a command
# no rule allows), allow (ran). Columns: the base, the first spelling (P:* ask entries), this spelling.
MEASURED = {
    "sudo npm publish": ("deny", "ask", "deny"),
    "sudo -u root npm publish": ("deny", "ask", "deny"),
    "echo a | sudo npm publish": ("deny", "ask", "deny"),  # in a compound the CLI words the ask as
    # "This Bash command contains multiple operations. The following part requires approval: ..."
    "timeout 5 sudo npm publish": ("deny", "ask", "deny"),
    "sudo env npm publish": ("deny", "ask", "deny"),
    "nohup sudo npm publish": ("deny", "ask", "deny"),
    "FOO=1 sudo npm publish": ("deny", "ask", "deny"),
    "sudo kubectl apply": ("deny", "ask", "deny"),
    "sudo kubectl create": ("deny", "ask", "deny"),
    "sudo -E kubectl create": ("deny", "ask", "deny"),
    "echo a | sudo -u root kubectl apply": ("deny", "ask", "deny"),
    "sudo npm publish --dry-run": ("deny", "deny", "deny"),
    "kubectl apply --dry-run=client -f k8s/deploy.yaml": ("deny", "ask", "ask"),
    "kubectl create deployment web --image=nginx --dry-run=client -o yaml": ("deny", "ask", "ask"),
    "npm publish --dry-run": ("deny", "ask", "ask"),
    "npm publish": ("deny", "ask", "ask"),
    "kubectl apply": ("deny", "ask", "ask"),
    "kubectl create": ("deny", "ask", "ask"),
    "kubectl apply -f k8s/deploy.yaml": ("deny", "ask", "ask"),
    "kubectl apply --dry-run=none -f x": ("deny", "ask", "ask"),
    "npm publish --dry-run=false": ("deny", "ask", "ask"),
    "NPM_TOKEN=t npm publish": ("deny", "ask", "ask"),
    "timeout 60 kubectl apply -f k8s/deploy.yaml": ("deny", "ask", "ask"),
    "npm run build && npm publish": ("deny", "ask", "ask"),
    "npm publisher": ("allow", "allow", "allow"),
    "npm install": ("allow", "allow", "allow"),
    "kubectl get pods": ("allow", "allow", "allow"),
    "nXpm publish": ("prompt", "prompt", "ask"),
    "kubectl applyset": ("prompt", "prompt", "prompt"),
    "kubectl create-foo": ("prompt", "prompt", "prompt"),
    "kubectl delete pod web": ("deny", "deny", "deny"),
    "yarn publish": ("deny", "deny", "deny"),
}


def _perms(path: Path = SETTINGS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["permissions"]


def _bash(entries: list[str]) -> list[str]:
    return [e[5:-1] for e in entries if e.startswith("Bash(") and e.endswith(")")]


def _forms(sub: str, measured: bool, assignments: bool = True) -> list[str]:
    """The subcommand, then past each wrapper (and leading assignment) in turn."""
    cur = re.sub(r"\s+", " ", sub).strip()
    forms = [cur]
    while True:
        nxt = DOC_WRAPPERS.sub("", cur, count=1)
        if assignments:
            nxt = ASSIGNMENT.sub("", nxt, count=1)
        if measured:
            nxt = MEASURED_WRAPPERS.sub("", nxt, count=1)
        if nxt == cur:
            return forms
        forms.append(nxt)
        cur = nxt


def exact_tier(rule: str, cmd: str) -> bool:
    """Measured: a match is exact-tier when the rule has no `*`, or it is `P:*` against the bare `P`."""
    return ("*" not in rule and cmd == rule) or (rule.endswith(":*") and "*" not in rule[:-2] and cmd == rule[:-2])


def _sub_decision(perms: dict, sub: str) -> str:
    rules = {k: _bash(perms.get(k, [])) for k in ("deny", "ask", "allow")}
    forms = {"deny": _forms(sub, False), "ask": _forms(sub, True), "allow": _forms(sub, True, assignments=False)}
    for tier in (True, False):
        for kind in ("deny", "ask"):
            if any(rule_covers(r, f) and exact_tier(r, f) == tier for r in rules[kind] for f in forms[kind]):
                return kind
    if forms["allow"][-1].split()[0] in READ_ONLY:
        return "allow"
    if any(rule_covers(r, f) for r in rules["allow"] for f in forms["allow"]):
        return "allow"
    return "prompt"


def decide(perms: dict, command: str) -> str:
    """deny, ask (an ask rule matched), prompt (no rule allows a subcommand) or allow for one Bash line."""
    got = [_sub_decision(perms, s) for s in simple_commands(command)]
    for kind in ("deny", "ask", "prompt"):
        if kind in got:
            return kind
    return "allow"


def _variant(column: int) -> dict:
    """Column 0: the base (the three entries in deny); 1: the first spelling (in ask); 2: settings.json."""
    perms = _perms()
    if column == 2:
        return perms
    ask = [e for e in perms["ask"] if e not in ASK_ENTRIES]
    if column == 0:
        return dict(perms, deny=perms["deny"] + LEFT_DENY, ask=ask)
    return dict(perms, ask=ask + LEFT_DENY)


# ------------------------------------------------------------------ the entries
def test_the_three_whole_verb_entries_left_deny_for_wildcard_tier_ask_entries():
    perms = _perms()
    for entry in LEFT_DENY:
        assert entry not in perms["deny"] and entry not in perms["ask"], entry
    for entry in ASK_ENTRIES:
        assert entry in perms["ask"], entry


def test_no_ask_entry_sits_in_the_exact_tier():
    """An exact-tier ask outranks a wildcard deny past a wrapper (measured): every ask entry needs a `*`
    that is not a trailing `:*`."""
    for rule in _bash(_perms()["ask"]):
        assert "*" in (rule[:-2] if rule.endswith(":*") else rule), rule


def test_the_neighbouring_deny_entries_stay():
    deny = _perms()["deny"]
    for entry in KEPT_DENY:
        assert entry in deny, entry


# ------------------------------------------------------------------ the decisions
@pytest.mark.parametrize("command", DRY_RUNS)
def test_a_dry_run_prompts_instead_of_being_refused(command):
    assert decide(_perms(), command) == "ask"


@pytest.mark.parametrize("command", REAL_RUNS)
def test_a_real_apply_create_or_publish_never_runs_unasked(command):
    assert decide(_perms(), command) in ("ask", "deny")


@pytest.mark.parametrize("command", STILL_DENIED)
def test_kubectl_delete_yarn_publish_and_every_sudo_form_stay_refused(command):
    assert decide(_perms(), command) == "deny"
    assert decide(_variant(0), command) == "deny"  # as on the base


@pytest.mark.parametrize("command,want", sorted(MEASURED.items()))
def test_the_model_reproduces_the_measured_decisions(command, want):
    for column in range(3):
        assert decide(_variant(column), command) == want[column], (column, command)


def test_the_ask_entry_beats_the_npm_allow_entry():
    """`Bash(npm:*)` is in allow and covers `npm publish`: only the ask rules, checked before allow
    ("a matching ask rule prompts even when a more specific allow rule also matches the same call"),
    keep it from running unasked."""
    perms = _perms()
    assert "Bash(npm:*)" in perms["allow"]
    assert rule_covers("npm:*", "npm publish")
    without = dict(perms, ask=[e for e in perms["ask"] if e not in ASK_ENTRIES])
    assert decide(without, "npm publish") == "allow"  # the hazard the ask entries close
    assert decide(perms, "npm publish") == "ask"
    assert decide(perms, "npm install") == "allow"  # the allow entry still serves the rest of npm


def test_both_spellings_of_each_verb_are_needed():
    """Measured: with a `*` before it, a trailing ` *` no longer matches the bare verb."""
    perms = _perms()
    only_args = dict(perms, ask=[e for e in perms["ask"] if e != "Bash(n*pm publish)"])
    assert decide(only_args, "npm publish") == "allow"
    assert decide(perms, "npm publish") == "ask"


def test_no_allow_entry_covers_kubectl_apply_or_create():
    allow = _bash(_perms()["allow"])
    for cmd in [c for c in DRY_RUNS + REAL_RUNS if c.startswith("kubectl")]:
        assert [r for r in allow if rule_covers(r, cmd)] == [], cmd
    perms = _perms()
    assert decide(dict(perms, ask=[e for e in perms["ask"] if e not in ASK_ENTRIES]),
                  "kubectl apply -f k8s/deploy.yaml") == "prompt"


def test_the_decision_model():
    perms = {"deny": ["Bash(rm -rf:*)", "Bash(sudo:*)"], "ask": ["Bash(n*pm publish *)", "Bash(n*pm publish)"],
             "allow": ["Bash(npm:*)", "Bash(ls:*)"]}
    assert decide(perms, "ls && rm -rf build") == "deny"
    assert decide(perms, "FOO=1 npm publish") == "ask"
    assert decide(perms, "FOO=1 npm install") == "prompt"  # allow does not match past an assignment
    assert decide(perms, "npm install && ls") == "allow"
    assert decide(perms, "npm install && make") == "prompt"
    assert decide(perms, "nohup npm publish") == "ask"
    assert decide(perms, "npm publisher") == "allow"
    assert decide(perms, "sudo npm publish") == "deny"
    assert decide(dict(perms, ask=["Bash(npm publish:*)"]), "sudo npm publish") == "ask"  # exact tier
    assert decide(dict(perms, ask=["Bash(npm publish)"]), "sudo npm publish") == "ask"  # exact tier
    assert decide(dict(perms, ask=["Bash(npm publish:*)"]), "sudo npm publish x") == "deny"


# ------------------------------------------------------------------ readers of a non-empty ask
def test_the_settings_load_accepts_the_non_empty_ask_list():
    import importlib.util
    spec = importlib.util.spec_from_file_location("claude_home", REPO / "hooks" / "lib" / "claude_home.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    settings, problem = mod.load_settings(SETTINGS)
    assert problem is None and settings["permissions"]["ask"] == _perms()["ask"]


def test_apply_permissions_keeps_the_ask_entries_when_it_merges(tmp_path):
    target = tmp_path / ".claude" / "settings.json"
    target.parent.mkdir()
    target.write_text(SETTINGS.read_text(encoding="utf-8"), encoding="utf-8")
    perms = tmp_path / "perms.json"
    perms.write_text(json.dumps([
        {"pattern": "Bash(n*pm publish *)", "section": "ask"},  # already there: not doubled
        {"pattern": "Bash(scripts/purge-cache.sh:*)", "section": "ask"},
    ]), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(tmp_path), CLAUDE_PROJECT_DIR=str(tmp_path))
    proc = subprocess.run(["bash", str(REPO / "scripts" / "apply-permissions.sh"), str(perms), str(target)],
                          cwd=str(tmp_path), env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    after = _perms(target)
    assert after["ask"] == _perms()["ask"] + ["Bash(scripts/purge-cache.sh:*)"]
    assert after["deny"] == _perms()["deny"] and after["allow"] == _perms()["allow"]
