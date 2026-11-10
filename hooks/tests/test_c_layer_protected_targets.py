"""A -c layer is never decided more leniently than its command run plainly, for every program that writes.

d1b244f0 made a shell `-c` layer fail closed: run-time text given to a program outside
_DATA_ONLY_COMMANDS (hooks/lib/git_command_classifier.py) is refused. Nine programs on that list
write files: cp, mv, ln, rm, chmod, chown, tee, truncate and touch. A layer keeps their run-time
word, so whether their write is allowed is the path guards' question there, as it is at top level.
D18 kept mv, cp and chmod given a run-time word allowed inside a layer on the condition that the
layer form exits no lower than the top-level form at every hook.

The hooks run are the real ones, one subprocess each: every PreToolUse hook settings.json registers
for Bash (a merged gate as each of its refusing rules for Bash, run alone: the gate runs each in its
own try and refuses when one does, so a layer no rule decides lower is none the gate does), in a scratch HOME whose ~/.claude is this tree (its tests left out), so the harness home
the guards resolve is the scratch one, with a scratch state dir and product repository, for the
main agent and for a dev subagent. Each writing program is aimed at protected targets in the
spellings the guards know (TARGETS): a file under .git/hooks/ (the product repository's and the
harness home's), the harness home's hooks and settings files (`~/.claude/hooks/...`,
`$HOME/.claude/settings.json`, the scratch CLAUDE_CONFIG_DIR written out) and a push-gate token at
the path scripts/write-push-gate-token.py prints for it. Each command runs plainly and inside
`bash -c "..."`, in three forms (FORMS): as written, with the target a run-time word
(`T=<target>; ... $T`), and with another operand a run-time word (`$S`, `$M`, `$U`, `$N`). For each
program, target, form and actor the two are compared hook by hook, the privilege guard first: the
layer exits no lower than the top-level form, so every top-level refusal shows up in the layer.
bash-safety's analyzer is given time (CLAUDE_HOOK_BOUNDARY_TIMEOUT): its degraded mode, reached on
a timeout under load, refuses any `$`, which would say nothing about the layer, so a degraded
verdict fails the test.

Three hooks refuse any of these commands: bash-safety (every rm, plainly and in a layer alike), the
claude config guard (cp, mv and tee into `.claude/hooks/`, plainly and in a layer alike, its pattern
reading the raw text) and tool-policy. On 99b4d69e every case where a layer exited lower than its
plain command was one of tool-policy's (KNOWN_GAPS: tool-policy read no write inside a -c string;
on master a7d3a9fe each of those layer forms exits 0 at tool-policy too), held as strict xfails.
T2-16 has tool-policy read each layer as its command run plainly, so each of them now passes.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.replay import sites  # noqa: E402

PRIVILEGE = "pretool-git-privilege-guard.py"
SAFETY = "pretool-bash-safety.sh"
POLICY = "pretool-tool-policy.py"
CONFIG_GUARD = "pretool-claude-config-guard.py"
BRANCH = "pretool-block-branch-pr-worktree.py"
ACTORS = {"main": False, "subagent": True}
ANALYZER_TIME = {"CLAUDE_HOOK_BOUNDARY_TIMEOUT": "60s"}
DEGRADED = "the execution-boundary analyzer is unavailable or returned no usable verdict"
TOKEN_SESSION = "c-layer-targets"

# program: (a realistic writing form, the same with another operand a run-time word); {t} is the target.
WRITERS = {
    "cp": ("cp notes.txt {t}", "cp $S {t}"),
    "mv": ("mv notes.txt {t}", "mv $S {t}"),
    "ln": ("ln -sf notes.txt {t}", "ln -sf $S {t}"),
    "rm": ("rm -f {t}", "rm -f $S {t}"),
    "chmod": ("chmod 755 {t}", "chmod $M {t}"),
    "chown": ("chown root {t}", "chown $U {t}"),
    "tee": ("echo x | tee {t}", "echo $S | tee {t}"),
    "truncate": ("truncate -s 0 {t}", "truncate -s $N {t}"),
    "touch": ("touch {t}", "touch -r $S {t}"),
}
# {config} is the scratch CLAUDE_CONFIG_DIR written out; {token} the push-gate token's path.
TARGETS = {
    "repo .git/hooks": ".git/hooks/pre-commit",
    "home .git/hooks": "~/.claude/.git/hooks/pre-commit",
    "~/.claude/hooks": "~/.claude/hooks/git-hooks/pre-commit",
    "$HOME settings.json": "$HOME/.claude/settings.json",
    "config dir settings.machine.json": "{config}/settings.machine.json",
    "push-gate token": "{token}",
}
FORMS = ("plain", "target $T", "operand $S")

# The D18 data cases: a run-time word in a layer to a program none of whose options runs a command or
# loads code. 8f77f50 refused each at the privilege guard (P10 refused every -c string with an
# expansion); the train allows them, and at every hook the layer decides as the command run plainly.
D18_DATA_CASES = ['bash -c "mv $A $B"', 'bash -c "cp $A $B"', 'bash -c "chmod -R 777 $F"']
# The other writing programs given only run-time words in a layer: never lower than plainly.
RUNTIME_WORD_CASES = ['bash -c "ln -s $A $B"', 'bash -c "rm -rf $F"', 'bash -c "chown -R $U $F"',
                      'bash -c "echo $X | tee $F"', 'bash -c "truncate -s 0 $F"', 'bash -c "touch $F"']


def _plain(layer):
    """The command a `bash -c "..."` layer runs, as written at top level."""
    found = re.fullmatch(r'bash -c "(.*)"', layer)
    assert found, layer
    return found.group(1)


def _pair(program, target, form, spell):
    """(top-level form, layer form) of ``program`` aimed at ``target``; ``spell`` writes the target out."""
    plain, other = WRITERS[program]
    path = spell(TARGETS[target])
    if form == "plain":
        command = plain.format(t=path)
        return command, 'bash -c "%s"' % command
    if form == "target $T":
        command = plain.format(t="$T")
        return "T=%s; %s" % (path, command), 'T=%s; bash -c "%s"' % (path, command)
    command = other.format(t=path)
    return command, 'bash -c "%s"' % command


# -- the former gaps (T2-16) ----------------------------------------------------------------------
# tool-policy reads a Bash command's write targets with lib/bash_write_targets.py, which blanks
# quoted text before it looks for a write, so a write inside a -c string named no target there: up
# to T2-16 a layer exited 0 at tool-policy for every case below, where its top-level form exits 2.
# tool-policy now reads each -c layer (lib/git_command_classifier's walk) as its command run plainly,
# and the layer exits 2 as well (hooks/tests/test_tool_policy_c_layer_writes.py). Two of its
# stages refuse the top-level form: the protected stage (P5 R2/R3, both actors) for the harness
# home's protected files and the push-gate token, as cp, mv, tee, truncate and rm write or remove
# them; and the dev role's rows (subagent), whose reader names what cp, mv and tee write, for the
# shared protected prefixes and a path outside the allowed ones. Of the `$T` forms only tee's is
# refused plainly: that reader follows `T=<target>; tee $T` to its target (TC-47). On master
# a7d3a9fe each of these layer forms exits 0 at tool-policy too (master has no protected stage, and
# its role rows read the same blanked text): pre-existing, the follow-up "tool-policy reads no write
# inside a -c string" (T2-16).
_POLICY_PROTECTED = {"home .git/hooks", "~/.claude/hooks", "config dir settings.machine.json", "push-gate token"}
_POLICY_TOUCHED = {"cp", "mv", "tee", "truncate", "rm"}  # the protected stage's reader names their target
_POLICY_WRITTEN = {"cp", "mv", "tee"}  # the role rows' reader names their target


def _policy_refuses_plainly(program, target, form, actor):
    if form == "target $T" and program != "tee":
        return False
    stage = program in _POLICY_TOUCHED and target in _POLICY_PROTECTED
    rows = actor == "subagent" and program in _POLICY_WRITTEN
    return stage or rows


KNOWN_GAPS = {(program, target, form, actor, POLICY)
              for program in WRITERS for target in TARGETS for form in FORMS for actor in ACTORS
              if _policy_refuses_plainly(program, target, form, actor)}


# -- the sandbox ------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("c-layer-targets")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmp"
    for d in (home, state, repo, tmp):
        d.mkdir(parents=True)
    config = home / ".claude"
    shutil.copytree(ROOT, config, symlinks=True,
                    ignore=shutil.ignore_patterns("tests", "__pycache__", ".git", ".pytest_cache"))
    # Each hook imports its libraries afresh; compiled once here, as an installed tree has them, the
    # runs below do not compile them again (PYTHONDONTWRITEBYTECODE keeps a hook from writing them).
    for python in dict.fromkeys([sys.executable, shutil.which("python3")]):
        if python:
            subprocess.run([python, "-m", "compileall", "-q", str(config / "hooks"), str(config / "scripts")],
                           capture_output=True)
    gitconfig = base / "gitconfig"
    gitconfig.write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(config), "CLAUDE_STATE_DIR": str(state),
           "GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8", **ANALYZER_TIME}
    (repo / "README.md").write_text("toy\n")
    (repo / "notes.txt").write_text("notes\n")
    for step in (["init", "-q", "-b", "master"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *step], cwd=repo, env=env, check=True, capture_output=True)
    # The harness home is a checkout, as an installed one is: its .git/hooks/ exists.
    subprocess.run(["git", "init", "-q", "-b", "master"], cwd=config, env=env, check=True, capture_output=True)
    token = subprocess.run(
        [sys.executable, str(config / "scripts" / "write-push-gate-token.py"), "--repo-root", str(repo),
         "--branch", "master", "--commit", "HEAD", "--print-path"],
        env=dict(env, CLAUDE_SESSION_ID=TOKEN_SESSION), capture_output=True, text=True, check=True)
    settings = json.loads((config / "settings.json").read_text())
    hooks = []
    for entry in settings["hooks"]["PreToolUse"]:
        matcher = entry.get("matcher")
        if matcher in (None, "", "*") or re.fullmatch(matcher, "Bash"):
            for h in entry["hooks"]:
                name = re.search(r"/hooks/([^/\"]+)\"?\s*$", h["command"]).group(1)
                rules = [r.file[len("hooks/"):] for r in sites.gate_rules(str(ROOT), "hooks/" + name)
                         if r.relays and (r.tools is None or "Bash" in r.tools)]
                hooks += rules or [name]
    return {"env": env, "repo": str(repo), "state": str(state), "hooks_dir": config / "hooks",
            "hooks": hooks, "config": str(config), "token": token.stdout.strip()}


def _spell(sandbox):
    return lambda target: target.format(config=sandbox["config"], token=sandbox["token"])


def _hook(sandbox, hook, command, subagent, n):
    # A session of its own per run: the orchestrator gate counts a session's Bash calls.
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "c-layer-%d" % n,
               "cwd": sandbox["repo"], "hook_event_name": "PreToolUse"}
    if subagent:
        payload.update(agent_id="agent-c-layer-test", agent_type="dev")
    argv = ["bash" if hook.endswith(".sh") else sys.executable, str(sandbox["hooks_dir"] / hook)]
    proc = subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True,
                          env=sandbox["env"], cwd=sandbox["repo"], timeout=300)
    return proc.returncode, proc.stderr if hook == SAFETY else ""


@pytest.fixture(scope="module")
def verdicts(sandbox):
    """(exit code, bash-safety's stderr) of every (hook, command, subagent) run the tests read."""
    spell = _spell(sandbox)
    commands = {c for program in WRITERS for target in TARGETS for form in FORMS
                for c in _pair(program, target, form, spell)}
    commands |= {c for layer in D18_DATA_CASES + RUNTIME_WORD_CASES for c in (layer, _plain(layer))}
    runs = sorted((hook, command, subagent) for command in commands for hook in sandbox["hooks"]
                  for subagent in ACTORS.values())
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda nr: _hook(sandbox, *nr[1], nr[0]), enumerate(runs)))
    return dict(zip(runs, results))


def _lower(verdicts, top, layer, subagent, hooks):
    """(hook, top-level exit, layer exit) wherever ``layer`` exits lower than ``top``, or passes a
    refusal of it, at ``hooks``; the privilege guard is checked first."""
    lower = []
    for hook in sorted(hooks, key=lambda h: h != PRIVILEGE):
        (top_code, top_err), (layer_code, layer_err) = (verdicts[(hook, c, subagent)] for c in (top, layer))
        assert DEGRADED not in top_err + layer_err, ("bash-safety ran degraded", top, layer)
        if layer_code < top_code or (top_code and not layer_code):
            lower.append((hook, top_code, layer_code))
        if hook == PRIVILEGE:
            assert not lower, ("the privilege guard decides the layer lower", top, layer, lower)
    return lower


def test_the_sandbox_runs_the_guards_and_spells_the_token_as_its_writer_does(sandbox):
    assert {PRIVILEGE, SAFETY, POLICY, CONFIG_GUARD, BRANCH} <= set(sandbox["hooks"]), sandbox["hooks"]
    token = Path(sandbox["token"])
    repo_hash = hashlib.sha256(os.path.realpath(sandbox["repo"]).encode()).hexdigest()[:16]
    session = hashlib.sha256(TOKEN_SESSION.encode()).hexdigest()[:16]
    assert token == Path(sandbox["state"], "agentic-commit", "push", repo_hash, session, "master.json"), token


def _cases():
    return [pytest.param(program, target, form, actor, id="%s|%s|%s|%s" % (program, target, form, actor))
            for program in WRITERS for target in TARGETS for form in FORMS for actor in ACTORS]


@pytest.mark.parametrize("program,target,form,actor", _cases())
def test_a_layer_exits_no_lower_than_its_plain_command_at_every_hook(
        sandbox, verdicts, program, target, form, actor):
    top, layer = _pair(program, target, form, _spell(sandbox))
    hooks = [h for h in sandbox["hooks"] if (program, target, form, actor, h) not in KNOWN_GAPS]
    lower = _lower(verdicts, top, layer, ACTORS[actor], hooks)
    assert not lower, (top, layer, lower)


_GAP_IDS = ["%s|%s|%s|%s|%s" % gap for gap in sorted(KNOWN_GAPS)]


@pytest.mark.parametrize("program,target,form,actor,hook", sorted(KNOWN_GAPS), ids=_GAP_IDS)
def test_a_former_gap_the_layer_exits_no_lower_at(sandbox, verdicts, program, target, form, actor, hook):
    top, layer = _pair(program, target, form, _spell(sandbox))
    assert not _lower(verdicts, top, layer, ACTORS[actor], [hook]), (top, layer, hook)


@pytest.mark.parametrize("program,target,form,actor,hook", sorted(KNOWN_GAPS), ids=_GAP_IDS)
def test_a_known_gaps_top_level_form_is_refused(sandbox, verdicts, program, target, form, actor, hook):
    # Each former gap was a refusal the layer lost: its top-level form is refused, so KNOWN_GAPS stays exact.
    top, _layer = _pair(program, target, form, _spell(sandbox))
    assert verdicts[(hook, top, ACTORS[actor])][0] == 2, top


@pytest.mark.parametrize("layer", D18_DATA_CASES)
@pytest.mark.parametrize("actor", ACTORS)
def test_a_d18_data_case_decides_in_a_layer_as_plainly_at_every_hook(sandbox, verdicts, layer, actor):
    plain = _plain(layer)
    codes = {hook: (verdicts[(hook, plain, ACTORS[actor])][0], verdicts[(hook, layer, ACTORS[actor])][0])
             for hook in sandbox["hooks"]}
    assert codes[PRIVILEGE] == (0, 0), (layer, codes[PRIVILEGE])
    assert all(top == lay for top, lay in codes.values()), (layer, codes)


@pytest.mark.parametrize("layer", RUNTIME_WORD_CASES)
@pytest.mark.parametrize("actor", ACTORS)
def test_a_writer_given_only_run_time_words_in_a_layer_exits_no_lower_than_plainly(
        sandbox, verdicts, layer, actor):
    assert not _lower(verdicts, _plain(layer), layer, ACTORS[actor], sandbox["hooks"]), layer
