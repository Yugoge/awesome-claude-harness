"""The publish and apply verbs that have a harmless dry run prompt instead of being refused (OB-L21).

`Bash(kubectl apply:*)`, `Bash(kubectl create:*)` and `Bash(npm publish:*)` were whole-verb deny entries,
so `kubectl apply --dry-run=client -f k8s/deploy.yaml` was refused like a real apply, and a deny entry
cannot carry an exception: "An allow rule can't carve an exception out of a deny rule"
(code.claude.com/docs/en/permissions.md, "Manage permissions"). The owner moved exactly these three to
`permissions.ask`; every other entry (`Bash(kubectl delete:*)`, `Bash(yarn publish:*)` among them) stays.

The cases model the CLI's documented decision (code.claude.com/docs/en/permissions.md):

* "Rules are evaluated in order: deny, then ask, then allow. The first match in that order determines the
  outcome, and rule specificity doesn't change the order." and "a matching ask rule prompts even when a
  more specific allow rule also matches the same call." So `Bash(npm publish:*)` in ask prompts for
  `npm publish` although `Bash(npm:*)` in allow also matches it.
* "Deny and ask rules apply when any subcommand matches them" (separators `&&`, `||`, `;`, `|`, `|&`, `&`,
  newlines, and a command substitution's body); "Every subcommand must be allowed for a compound command
  to run without a prompt".
* "A deny or ask rule matches past any leading assignment." "An allow rule won't match past an assignment
  of any other variable." Wrappers stripped before matching: timeout, time, nice, nohup, stdbuf, command,
  builtin, noglob.
* A call no rule matches prompts (the default mode asks for a Bash command no allow rule covers).

The `:*` prefix rule (`P:*` matches `P` and `P <args>`) is `rule_covers` of tests/test_permission_coverage.py,
whose model was measured on Claude Code 2.1.319. The precedence and subcommand points above are modelled from
the quoted documentation, not measured.
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
MOVED = ["Bash(kubectl apply:*)", "Bash(kubectl create:*)", "Bash(npm publish:*)"]
KEPT_DENY = ["Bash(kubectl delete:*)", "Bash(yarn publish:*)"]
WRAPPERS = {"timeout", "time", "nice", "nohup", "stdbuf", "command", "builtin", "noglob"}
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=\S*\s+")

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
    "kubectl create namespace prod",
    "kubectl create -f k8s/deploy.yaml",
    # compound, wrapped and assignment-led forms of the same verbs
    "npm run build && npm publish",
    "cd pkg && npm publish --access public",
    "NPM_TOKEN=t npm publish",
    "timeout 60 kubectl apply -f k8s/deploy.yaml",
    "echo $(kubectl create secret generic s --from-literal=a=b)",
    "ls; kubectl apply -k overlays/prod",
]
# Unchanged refusals of this lane's neighbours.
STILL_DENIED = [
    "kubectl delete pod web",
    "kubectl delete -f k8s/deploy.yaml --dry-run=client",
    "yarn publish",
    "yarn publish --new-version 1.2.3",
]


def _perms(path: Path = SETTINGS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["permissions"]


def _bash(entries: list[str]) -> list[str]:
    return [e[5:-1] for e in entries if e.startswith("Bash(") and e.endswith(")")]


def _strip_wrappers(cmd: str) -> str:
    words = cmd.split()
    while words and words[0] in WRAPPERS:
        words = words[1:]
        while words and (words[0].startswith("-") or re.fullmatch(r"\d+[smhd]?", words[0])):
            words = words[1:]
    return " ".join(words)


def _for_deny_or_ask(sub: str) -> str:
    sub = _strip_wrappers(sub)
    while ASSIGNMENT.match(sub):
        sub = _strip_wrappers(ASSIGNMENT.sub("", sub, count=1))
    return sub


def decide(perms: dict, command: str) -> str:
    """deny, ask or allow for one Bash command line, in the documented order deny > ask > allow; a line
    with a subcommand no allow rule covers prompts (ask)."""
    subs = simple_commands(command)
    deny, ask, allow = (_bash(perms.get(k, [])) for k in ("deny", "ask", "allow"))
    if any(rule_covers(r, _for_deny_or_ask(s)) for s in subs for r in deny):
        return "deny"
    if any(rule_covers(r, _for_deny_or_ask(s)) for s in subs for r in ask):
        return "ask"
    if all(any(rule_covers(r, _strip_wrappers(s)) for r in allow) for s in subs):
        return "allow"
    return "ask"


# ------------------------------------------------------------------ the entries
def test_the_three_whole_verb_entries_moved_from_deny_to_ask():
    perms = _perms()
    for entry in MOVED:
        assert entry in perms["ask"], entry
        assert entry not in perms["deny"], entry
    assert sorted(perms["ask"]) == sorted(MOVED)  # exactly these three, nothing else asks


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
def test_kubectl_delete_and_yarn_publish_stay_refused(command):
    assert decide(_perms(), command) == "deny"


def test_the_ask_entry_beats_the_npm_allow_entry():
    """`Bash(npm:*)` is in allow and covers `npm publish`: only the ask rule, checked before allow
    ("a matching ask rule prompts even when a more specific allow rule also matches the same call"),
    keeps it from running unasked."""
    perms = _perms()
    assert "Bash(npm:*)" in perms["allow"]
    assert rule_covers("npm:*", "npm publish")
    without_ask = dict(perms, ask=[])
    assert decide(without_ask, "npm publish") == "allow"  # the hazard the ask entry closes
    assert decide(perms, "npm publish") == "ask"
    assert decide(perms, "npm install") == "allow"  # the allow entry still serves the rest of npm


def test_no_allow_entry_covers_kubectl_apply_or_create():
    allow = _bash(_perms()["allow"])
    kubectl = [c for c in DRY_RUNS + REAL_RUNS + ["kubectl apply", "kubectl create"]
               if c.startswith("kubectl")]
    for cmd in kubectl:
        assert [r for r in allow if rule_covers(r, cmd)] == [], cmd
    assert decide(dict(_perms(), ask=[]), "kubectl apply -f k8s/deploy.yaml") == "ask"


def test_the_decision_model():
    perms = {"deny": ["Bash(rm -rf:*)"], "ask": ["Bash(npm publish:*)"], "allow": ["Bash(npm:*)", "Bash(ls:*)"]}
    assert decide(perms, "ls && rm -rf build") == "deny"
    assert decide(perms, "FOO=1 npm publish") == "ask"
    assert decide(perms, "FOO=1 npm install") == "ask"  # allow does not match past an assignment
    assert decide(perms, "npm install && ls") == "allow"
    assert decide(perms, "npm install && make") == "ask"
    assert decide(perms, "nohup npm publish") == "ask"
    assert decide(perms, "npm publisher") == "allow"  # `P:*` needs a word boundary


# ------------------------------------------------------------------ readers of a non-empty ask
def test_the_settings_load_accepts_the_non_empty_ask_list():
    import importlib.util
    spec = importlib.util.spec_from_file_location("claude_home", REPO / "hooks" / "lib" / "claude_home.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    settings, problem = mod.load_settings(SETTINGS)
    assert problem is None and settings["permissions"]["ask"] == MOVED


def test_apply_permissions_keeps_the_ask_entries_when_it_merges(tmp_path):
    target = tmp_path / ".claude" / "settings.json"
    target.parent.mkdir()
    target.write_text(SETTINGS.read_text(encoding="utf-8"), encoding="utf-8")
    perms = tmp_path / "perms.json"
    perms.write_text(json.dumps([
        {"pattern": "Bash(npm publish:*)", "section": "ask"},  # already there: not doubled
        {"pattern": "Bash(scripts/purge-cache.sh:*)", "section": "ask"},
    ]), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(tmp_path), CLAUDE_PROJECT_DIR=str(tmp_path))
    proc = subprocess.run(["bash", str(REPO / "scripts" / "apply-permissions.sh"), str(perms), str(target)],
                          cwd=str(tmp_path), env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    after = _perms(target)
    assert after["ask"] == MOVED + ["Bash(scripts/purge-cache.sh:*)"]
    assert after["deny"] == _perms()["deny"] and after["allow"] == _perms()["allow"]
