"""The unresolved_shell_string refusal names a recovery route that works (OB-L28, GIT-4).

`for d in */; do bash -c "cd $d && git status"; done` stays refused: the outer
shell splices the directory name into the `-c` string, so a directory named
`x;git push` runs a push the guard never sees. The refusal used to offer only
"write the binary literally", which this command already does. It now names the
two routes that pass: hand the value to the `-c` string as a positional
argument, or drop the `bash -c` wrapper. Both are run through the guard here.

Hook cases run the real hook file of this tree with a sandboxed HOME,
CLAUDE_CONFIG_DIR, CLAUDE_STATE_DIR and git config, in a product repository.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "hooks" / "pretool-git-privilege-guard.py"

AUDIT_INPUT = 'for d in */; do bash -c "cd $d && git status"; done'
POSITIONAL_ROUTE = """bash -c 'cd "$1" && git status' _ "$d\""""
SUBSHELL_ROUTE = 'for d in */; do (cd "$d" && git status); done'
OLD_ROUTE = "Re-issue it with the binary written literally"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("residual-msg")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmp"
    for d in (home / ".claude", state, repo, tmp):
        d.mkdir(parents=True)
    gitconfig = base / "gitconfig"
    gitconfig.write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_STATE_DIR": str(state),
           "GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
    (repo / "README.md").write_text("toy\n")
    for step in (["init", "-q", "-b", "master"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *step], cwd=repo, env=env, check=True, capture_output=True)
    return {"env": env, "repo": str(repo)}


def _guard(sandbox, command, subagent):
    payload = {"tool_name": "Bash", "tool_input": {"command": command},
               "session_id": "residual-msg-test", "cwd": sandbox["repo"],
               "hook_event_name": "PreToolUse"}
    if subagent:
        payload.update(agent_id="agent-residual-msg", agent_type="dev")
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                          capture_output=True, text=True, env=sandbox["env"],
                          cwd=sandbox["repo"], timeout=120)


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_audit_input_is_still_refused_as_an_unresolved_shell_string(sandbox, subagent):
    proc = _guard(sandbox, AUDIT_INPUT, subagent)
    assert proc.returncode == 2, proc.stderr
    assert "unresolved_shell_string" in proc.stderr, proc.stderr


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_refusal_names_the_positional_and_subshell_routes_not_the_literal_binary(sandbox, subagent):
    err = _guard(sandbox, AUDIT_INPUT, subagent).stderr
    assert POSITIONAL_ROUTE in err, err
    assert '(cd "$d" && git status)' in err, err
    assert OLD_ROUTE not in err, err


@pytest.mark.parametrize("command", [
    "for d in */; do %s; done" % POSITIONAL_ROUTE,
    POSITIONAL_ROUTE,
    SUBSHELL_ROUTE,
])
@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_each_suggested_route_passes_the_guard(sandbox, command, subagent):
    proc = _guard(sandbox, command, subagent)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("command", [
    "for d in */; do bash -c 'cd \"$1\" && git push' _ \"$d\"; done",
    'for d in */; do (cd "$d" && git push); done',
])
def test_a_suggested_route_carrying_a_guarded_subcommand_is_judged_on_its_merits(sandbox, command):
    proc = _guard(sandbox, command, True)
    assert proc.returncode == 2, proc.stderr
    assert "unresolved_shell_string" not in proc.stderr, proc.stderr


@pytest.mark.parametrize("command", ["$GIT push origin master", "$(which git) push origin master"])
def test_a_binary_residual_keeps_the_literal_binary_route(sandbox, command):
    err = _guard(sandbox, command, True).stderr
    assert "written literally" in err, err
    assert POSITIONAL_ROUTE not in err, err


def test_an_escaped_binary_is_judged_as_the_git_it_runs(sandbox):
    # OB-L26 reads `g\it` as git receives it, so this is no binary residual
    # any more: the push rule refuses it as it refuses `git push`.
    proc = _guard(sandbox, "g\\it push origin master", True)
    assert proc.returncode == 2, proc.stderr
    assert "git push" in proc.stderr, proc.stderr
