"""The CLI's deny list is a hook rule: policies/cli-deny.v1.json, decided by hooks/pretool-deny-list.py.

Claude Code applied settings.json's permissions.deny after the PreToolUse hooks, over a hook's allow, with no hook
event and no record, so an owner's /allow could not release it (docs/how-it-works.md, "Permission prompts"). Since
2026-11-21 the entries are the policy file's, in the CLI's own syntax and order, matched by hooks/lib/deny_list.py
as the CLI matched them; the refusal goes through the launcher, which records it and lets an /allow grant release it.
settings.json keeps the switch's own two rules, which the off form keeps while no hook runs.

Equivalence, mechanically: the models of the CLI's matching in the permission test suites are the oracle; over the
commands and paths those suites and the hook suites pin, and over one instance of every Bash entry, the rule refuses
exactly what the model with the same entries denies. The model's reading of the removal rules stays pinned to the
four probes of 2026-11-20 (CLI 2.1.322). DENY_TABLE keeps each general Bash entry's reason of that day.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "hooks"))
from lib.deny_list import POLICY, Policy, entries  # noqa: E402

sys.path.pop(0)
from tests.test_permission_pipe_to_shell import (DENIED_ON_BASE, KNOWN_COLLATERAL, KNOWN_GAPS,  # noqa: E402
                                                 LOCAL_STDIN_BASH, PIPE_TO_BASH, PROMPTED_ON_BASE, STILL_RUNS, decision)
from tests import test_home_secret_denies as home_model  # noqa: E402
from tests import test_secret_file_denies as file_model  # noqa: E402
from tests import test_session_dirs_permission as dirs_model  # noqa: E402

DOC = json.loads(Path(POLICY).read_text(encoding="utf-8"))
ENTRIES = DOC["deny"]
POL = Policy()
SETTINGS = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
KEPT_IN_SETTINGS = 2  # the switch's own rules, which the off form keeps
NO_HOOK = "no hook decides this family"
UNRELEASABLE = "a hook refuses it always; /do does not release it, only the owner's /allow does"

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
    "Bash(git push --force:*)": UNRELEASABLE,  # the git guard refuses every force push, /do or not
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
HOME = "/work/u"


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


def _instance(entry: str) -> str:
    """One command an entry's own text names: `P:*` as `P x`, every other `*` as `x` (`?` is literal in Bash rules)."""
    body = entry[5:-1]
    body = body[:-2] + " x" if body.endswith(":*") else body
    return body.replace("*", "x")


BASH_ENTRIES = [e for e in ENTRIES if e.startswith("Bash(")]
BASH_CORPUS = sorted(set(_allowed_commands() + PIPE_TO_BASH + PROMPTED_ON_BASE + DENIED_ON_BASE + LOCAL_STDIN_BASH
                         + KNOWN_GAPS + KNOWN_COLLATERAL + STILL_RUNS + dirs_model.MUST_PASS + dirs_model.BASE_KEPT
                         + dirs_model.HOOK_ONLY + dirs_model.NO_LAYER + list(dirs_model.MEASURED)
                         + list(dirs_model.ENTRIES.values()) + [_instance(e) for e in BASH_ENTRIES]))


# ------------------------------------------------------------------ the list moved
def test_settings_deny_list_holds_only_the_switch_rules():
    """What stays is the switch's own rules (render-settings SWITCH_PERMISSIONS): the off form keeps them, and
    while the harness is off no hook runs, so only the CLI can keep the model from the switch."""
    from importlib.machinery import SourceFileLoader
    render = SourceFileLoader("_render_settings_deny", str(REPO / "scripts" / "install" / "render-settings")).load_module()
    deny = SETTINGS["permissions"]["deny"]
    assert sorted(deny) == sorted(render.SWITCH_PERMISSIONS) and len(deny) == KEPT_IN_SETTINGS, deny
    assert not set(deny) & set(ENTRIES), deny


def test_every_entry_has_a_purpose_and_a_known_form():
    for entry in ENTRIES:
        assert re.fullmatch(r"(Bash|Read|Edit|Skill)\(.*\)", entry, re.S), entry
        assert any(re.search(p["match"], entry) for p in DOC["purposes"]), entry


def test_every_general_bash_deny_entry_stands_in_the_table():
    shipped = {e for e in BASH_ENTRIES if e.endswith(":*)")}
    assert shipped == set(DENY_TABLE), sorted(shipped ^ set(DENY_TABLE))
    assert set(DENY_TABLE.values()) <= {NO_HOOK, UNRELEASABLE}


def test_every_other_bash_deny_entry_guards_the_session_dirs_file():
    """The rest are the path rules around the session-directory registry; a new kind of entry needs a row above."""
    rest = [r for r in BASH_ENTRIES if not r.endswith(":*)")]
    assert rest and all("session_dirs" in r for r in rest), [r for r in rest if "session_dirs" not in r]


def test_the_rule_is_one_line_of_the_pre_tool_table():
    text = (REPO / "hooks" / "pretool-launch.py").read_text(encoding="utf-8")
    assert len(re.findall(r"Rule\('deny-list', 'pretool-deny-list.py'", text)) == 1


def test_the_lists_are_the_hook_suites_own():
    """Both hook suites read hooks/tests/allowed_by_design.py; neither holds a copy of its own."""
    for name, attr in (("test_removal_policy_own_scratch.py", "OWN_SCRATCH_REMOVALS"),
                       ("test_bash_safety_command_position.py", "COMMAND_POSITION_PASSES")):
        assert f"allowed_by_design.{attr}" in (REPO / "hooks" / "tests" / name).read_text(encoding="utf-8"), name


@pytest.mark.parametrize("cmd", _allowed_commands())
def test_a_command_the_hooks_allow_by_design_is_not_denied(cmd):
    assert decision(cmd, {"allow": [], "deny": BASH_ENTRIES}) != "deny", cmd
    assert POL.bash_entry(cmd) is None and POL.bash_paths(cmd, ROOT, HOME) is None, cmd


# ------------------------------------------------------------------ equivalence: Bash command entries
@pytest.mark.parametrize("cmd", BASH_CORPUS)
def test_the_rule_refuses_a_command_exactly_when_the_model_denies_it(cmd):
    model = decision(cmd, {"allow": [], "deny": BASH_ENTRIES}) == "deny"
    assert (POL.bash_entry(cmd) is not None) == model, cmd


def test_every_bash_entry_refuses_its_own_instance():
    assert [e for e in BASH_ENTRIES if POL.bash_entry(_instance(e)) is None] == []


# ------------------------------------------------------------------ equivalence: Read and Edit path entries
# The whole list the rule decides (entries: the policy plus the switch rules settings.json keeps), as the CLI holds it.
PATH_ENTRIES = [e for e, _ in entries() if e.startswith(("Read(", "Edit("))]
_FILE_PATHS = sorted({p for _, p, _, _ in file_model.MEASURED if not p.startswith("/") and " " not in p}
                     | set(file_model.MUST_PASS) | set(file_model.MUST_REFUSE) | set(file_model.KEPT_REFUSED)
                     | set(file_model.VERIFIER_DROP) | set(file_model.PROTECTED_WRITES))
FILE_CORPUS = [(tool, p) for p in _FILE_PATHS for tool in ("Read", "Write")]
HOME_CORPUS = [(cwd, tool, target) for cwd, tool, target, _, _ in home_model.MEASURED]


@pytest.mark.parametrize("tool,path", FILE_CORPUS)
def test_a_project_path_is_refused_exactly_when_the_model_denies_it(tool, path):
    model = file_model.denied(PATH_ENTRIES, tool, path)
    hit = POL.path_entry(f"{ROOT}/{path}", tool != "Read", ROOT, HOME)
    assert (hit is not None) == model, (tool, path, hit)


@pytest.mark.parametrize("cwd,tool,target", HOME_CORPUS)
def test_a_home_or_project_call_is_refused_exactly_when_the_model_denies_it(cwd, tool, target):
    model = home_model._measured_decision(PATH_ENTRIES, cwd, tool, target)
    where = f"{HOME}/{home_model.PROJ}" if cwd == "proj" else HOME
    target = target.replace("<HOME>", HOME)
    if tool == "Bash":
        hit = POL.bash_paths(target, where, HOME)
    else:
        hit = POL.path_entry(target if target.startswith("~/") else f"{HOME}/{home_model.PROJ}/{target}",
                             tool != "Read", where, HOME)
    assert (hit is not None) == model, (cwd, tool, target, hit)


# ------------------------------------------------------------------ the rule, run as the CLI runs it
@pytest.fixture
def env(tmp_path):
    state, home, proj = tmp_path / "state", tmp_path / "home", tmp_path / "proj"
    for d in (state, home, proj):
        d.mkdir()
    e = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "CODEX_"))}
    e.update(CLAUDE_STATE_DIR=str(state), HOME=str(home), CLAUDE_SESSION_ID="sess-0001",
             CLAUDE_PROJECT_DIR=str(proj), PYTHONDONTWRITEBYTECODE="1")
    return {"env": e, "home": home, "proj": proj, "tmp": tmp_path}


def _call(env, tool, tool_input, hook="pretool-launch.py", n=1):
    payload = {"hook_event_name": "PreToolUse", "session_id": "sess-0001", "tool_name": tool,
               "tool_input": tool_input, "tool_use_id": f"toolu_deny_{n}", "cwd": str(env["proj"]),
               "transcript_path": str(env["tmp"] / "none.jsonl"), "agent_id": "a1b2", "agent_type": "dev"}
    return subprocess.run([sys.executable, str(REPO / "hooks" / hook)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env["env"], timeout=600)


def _records(env):
    out = []
    for f in sorted(env["home"].rglob("refusals-*.jsonl")):
        out += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    return out


REFUSED = [("Bash", {"command": "sudo -n true"}, "privilege"),
           ("Bash", {"command": "systemctl enable neutral.service"}, "services"),
           ("Read", {"file_path": "{proj}/config/credentials.json"}, "secret file"),
           ("Skill", {"skill": "commit"}, "owner-only command")]


@pytest.mark.parametrize("tool,ti,word", REFUSED)
def test_the_rule_refuses_with_the_purpose(env, tool, ti, word):
    ti = {k: v.format(proj=env["proj"]) for k, v in ti.items()}
    p = _call(env, tool, ti, hook="pretool-deny-list.py")
    assert p.returncode == 2 and word in p.stderr and "policies/cli-deny.v1.json" in p.stderr, p.stderr


def test_a_refusal_is_recorded_and_a_grant_releases_it(env):
    ti = {"command": "systemctl enable neutral.service"}
    p = _call(env, "Bash", ti)
    assert p.returncode == 2 and "[deny-list] BLOCKED: the host's power or its services" in p.stderr, p.stderr
    rec = [r for r in _records(env) if "pretool-deny-list.py" in json.dumps(r)]
    assert rec and "the host's power or its services" in json.dumps(rec[-1]), _records(env)
    g = subprocess.run(["bash", str(REPO / "hooks" / "userprompt-consent-allowlist.sh")], capture_output=True,
                       text=True, env=env["env"], timeout=60,
                       input=json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "sess-0001",
                                         "prompt": "/allow", "cwd": str(env["proj"])}))
    assert g.returncode == 0, g.stderr
    p = _call(env, "Bash", ti, n=2)
    assert p.returncode == 0 and "RELEASED" in p.stdout and "pretool-deny-list.py" in p.stdout, (p.stdout, p.stderr)
    assert _call(env, "Bash", ti, n=3).returncode == 2  # the grant is spent


def test_the_rule_refuses_when_it_cannot_decide(env, tmp_path):
    """No policy file (a broken install): refused, not let through."""
    hooks = tmp_path / "copy" / "hooks"
    (hooks / "lib").mkdir(parents=True)
    for name in ("pretool-deny-list.py", "lib/deny_list.py", "lib/harness_switch.py", "lib/__init__.py"):
        if (REPO / "hooks" / name).exists():
            (hooks / name).write_bytes((REPO / "hooks" / name).read_bytes())
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"},
                          "cwd": str(env["proj"])})
    p = subprocess.run([sys.executable, str(hooks / "pretool-deny-list.py")], input=payload, capture_output=True,
                       text=True, env=env["env"], timeout=60)
    assert p.returncode == 2 and "reading the list" in p.stderr and "FileNotFoundError" in p.stderr, (p.returncode,
                                                                                                         p.stderr)


def test_the_added_cost_per_call_is_small():
    """The patterns prepared once and one call matched, in the rule's own process."""
    t0 = time.perf_counter()
    pol = Policy()
    prep = time.perf_counter() - t0
    calls = [{"tool_name": "Bash", "tool_input": {"command": c}, "cwd": ROOT} for c in BASH_CORPUS]
    calls += [{"tool_name": "Write", "tool_input": {"file_path": f"{ROOT}/{p}"}, "cwd": ROOT} for p in _FILE_PATHS]
    t0 = time.perf_counter()
    for c in calls:
        pol.refusal(c)
    per = (time.perf_counter() - t0) / len(calls)
    print(f"prepare {prep * 1000:.2f} ms, per call {per * 1000:.3f} ms over {len(calls)} calls")
    assert prep < 0.05 and per < 0.005, (prep, per)


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
