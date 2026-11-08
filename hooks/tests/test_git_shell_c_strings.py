"""A git command in a shell's `-c` string is judged as the plain command is.

`bash -c "git commit -m y"` runs git, but the shell segment's command token is
`bash`, so the shared classifier (lib.git_command_classifier) yielded no git
invocation for it and every hook built on it passed the git it runs: the
privilege guard (commit, push, merge, reset --hard, ref mutation, plumbing),
bash-safety (reset --hard, force push, ref mutation, bare stash, wide checkout
and restore) and the branch/PR/worktree guard. Measured through the registered
hooks: every wrapped form below missed every one of those refusals.

The classifier now resolves a shell's `-c` string and classifies it as a
command line of its own; a string it cannot resolve (an expansion the outer
shell performs, quoting it cannot follow, nesting past its limit) is the
residual `unresolved_shell_string`, which the privilege guard refuses.

PR #15's second review (finding 1) measured that residual refusing commands
with no git in them: every `-c` string holding an expansion, text the scan
could not lex, and every here-document body. Such a string is now a residual
only when it is git-shaped, and a here-document is shell text only when a
shell may read it (REVIEW_ROWS, GIT_SHAPED).

Hook cases run the real hook files of this tree with a sandboxed HOME,
CLAUDE_CONFIG_DIR, CLAUDE_STATE_DIR and git config, in a product repository.
"""
import importlib.util
import json
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS / "lib"))

import git_command_classifier  # noqa: E402
from git_command_classifier import classify_git_command, iter_git_invocations  # noqa: E402

WRAPPERS = {
    "bash -c": 'bash -c "{}"',
    "sh -c": "sh -c '{}'",
    "bash -lc": 'bash -lc "{}"',
    "bash -ec": 'bash -ec "{}"',
    "env bash -c": 'env bash -c "{}"',
    "/bin/bash -c": '/bin/bash -c "{}"',
    "bash -c twice": "bash -c \"bash -c '{}'\"",
    "cmd; bash -c": 'true; bash -c "{}"',
}

SAFETY = "pretool-bash-safety.sh"
PRIVILEGE = "pretool-git-privilege-guard.py"
BRANCH = "pretool-block-branch-pr-worktree.py"

# (hook, plain command the hook refuses), as measured on the base.
REFUSED = [
    (PRIVILEGE, "git commit -m y"),
    (PRIVILEGE, "git push origin master"),
    (PRIVILEGE, "git merge feature"),
    (PRIVILEGE, "git reset --hard HEAD"),
    (PRIVILEGE, "git update-ref refs/heads/x HEAD"),
    (PRIVILEGE, "git branch -D feature"),
    (PRIVILEGE, "git symbolic-ref HEAD refs/heads/x"),
    (PRIVILEGE, "git cherry-pick feature"),
    (PRIVILEGE, "git pull"),
    (PRIVILEGE, "git push --force origin master"),
    (PRIVILEGE, "git commit --no-verify -m y"),
    (PRIVILEGE, "git rebase master"),
    (PRIVILEGE, "git revert HEAD~1"),
    (SAFETY, "git reset --hard HEAD"),
    (SAFETY, "git update-ref refs/heads/x HEAD"),
    (SAFETY, "git branch -D feature"),
    (SAFETY, "git symbolic-ref HEAD refs/heads/x"),
    (SAFETY, "git push --force origin master"),
    (SAFETY, "git stash"),
    (SAFETY, "git checkout HEAD -- ."),
    (SAFETY, "git restore --source=HEAD -- ."),
    (BRANCH, "git update-ref refs/heads/x HEAD"),
    (BRANCH, "git checkout -b feat"),
    (BRANCH, "git switch -c feat"),
    (BRANCH, "git branch feat"),
    (BRANCH, "git worktree add ../wt"),
    (BRANCH, "git stash branch feat"),
    (BRANCH, "git fetch origin master:feat"),
    (BRANCH, "gh pr create --fill"),
]
SUBAGENT = [(PRIVILEGE, "git commit -m y"), (SAFETY, "git push --force origin master"),
            (BRANCH, "git checkout -b feat")]

UNRESOLVED = [
    'X="git commit -m y"; bash -c "$X"',
    'bash -c "$CMD"',
    'bash -c "$(cat cmd.txt)"',
    'bash -c "`cat cmd.txt`"',
    'bash -c "git $SUB"',
    "bash -c 'bash -c \"$X\"'",
    "bash -c $'git commit -m y'",
    'bash -c "git status',
]

# PR #15 review finding 1: the reviewer's table, (command, exit code of the
# privilege guard); 103a1b4, before P10's change, gave the same codes. Each row
# but the last has no git in it and was refused as an unresolved string.
REVIEW_ROWS = [
    ('bash -c "cd $DIR && npm test"', 0),
    ('timeout 30 bash -c "until curl -s localhost:$PORT; do sleep 1; done"', 0),
    ('bash -c "echo $HOME"', 0),
    ("cat > notes.md <<'EOF'\nWe don't wrap commands in sh -c any more.\nEOF", 0),
    ('cd $DIR && npm test', 0),
    ('bash -c "git commit -m x"', 2),
]
# Git run through those shapes stays refused: an expansion in a git-shaped -c
# string, a here-document a shell reads, and the substitution an unquoted
# here-document runs whoever reads it.
GIT_SHAPED = [
    'bash -c "cd $DIR && git commit -m x"',
    'bash -c "git commit -m $MSG"',
    'timeout 30 bash -c "until git push origin $BRANCH; do sleep 1; done"',
    'bash -c "$GIT commit -m x"',
    'bash -c "`which git` commit -m x"',
    'bash -c "$SUDO git commit -m x"',
    "bash -c \"bash -c '$X'\"",
    "sh <<'EOF'\ngit commit -m x\nEOF",
    "sh <<'EOF'\nbash -c \"git commit -m x\"\nEOF",
    "sh <<'EOF'\nbash -c \"git commit -m $MSG\"\nEOF",
    "sh <<EOF\nbash -c '$CMD'\nEOF",
    "cat <<'EOF' | sh\nbash -c 'git commit -m x'\nEOF",
    "cat <<EOF\n$(bash -c 'git commit -m x')\nEOF",
    "ssh host <<'EOF'\nbash -c 'git commit -m x'\nEOF",
    'sh -c "git commit -m x',
]


def _nest(command, levels):
    for _ in range(levels):
        command = "bash -c " + shlex.quote(command)
    return command


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("shell-c")
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


def _run(sandbox, hook, command, subagent=False):
    payload = {"tool_name": "Bash", "tool_input": {"command": command},
               "session_id": "shell-c-test", "cwd": sandbox["repo"],
               "hook_event_name": "PreToolUse"}
    if subagent:
        payload.update(agent_id="agent-shell-c-test", agent_type="dev")
    argv = ["bash" if hook.endswith(".sh") else sys.executable, str(HOOKS / hook)]
    proc = subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True,
                          env=sandbox["env"], cwd=sandbox["repo"], timeout=120)
    return proc.returncode


@pytest.fixture(scope="module")
def verdicts(sandbox):
    """Exit code of every (hook, command, subagent) run the hook cases below read."""
    runs = set()
    for actor, cases in ((False, REFUSED), (True, SUBAGENT)):
        for hook, plain in cases:
            runs.add((hook, plain, actor))
            runs.update((hook, tmpl.format(plain), actor) for tmpl in WRAPPERS.values())
    runs.update((PRIVILEGE, cmd, actor) for cmd in UNRESOLVED for actor in (False, True))
    runs.update((PRIVILEGE, cmd, actor) for cmd in [row for row, _code in REVIEW_ROWS] + GIT_SHAPED
                for actor in (False, True))
    runs = sorted(runs)
    with ThreadPoolExecutor(max_workers=8) as ex:
        codes = list(ex.map(lambda r: _run(sandbox, *r), runs))
    return dict(zip(runs, codes))


def _pairs(cases):
    return [pytest.param(hook, plain, form, id="%s|%s|%s" % (hook, plain, form))
            for hook, plain in cases for form in WRAPPERS]


@pytest.mark.parametrize("hook,plain,form", _pairs(REFUSED))
def test_wrapped_form_is_refused_like_the_plain_one(verdicts, hook, plain, form):
    assert verdicts[(hook, plain, False)] == 2, "the plain command is the hook's deciding case"
    wrapped = WRAPPERS[form].format(plain)
    assert verdicts[(hook, wrapped, False)] == 2, wrapped


@pytest.mark.parametrize("hook,plain,form", _pairs(SUBAGENT))
def test_wrapped_form_is_refused_like_the_plain_one_for_a_subagent(verdicts, hook, plain, form):
    assert verdicts[(hook, plain, True)] == 2
    wrapped = WRAPPERS[form].format(plain)
    assert verdicts[(hook, wrapped, True)] == 2, wrapped


def _calls(command):
    return [(inv.subcommand, tuple(inv.args)) for inv in iter_git_invocations(command)]


@pytest.mark.parametrize("plain", sorted({p for h, p in REFUSED if p.startswith("git ")}))
@pytest.mark.parametrize("form", list(WRAPPERS))
def test_the_classifier_yields_the_plain_invocation_inside_every_wrapper(plain, form):
    wrapped = WRAPPERS[form].format(plain)
    assert set(_calls(plain)) <= set(_calls(wrapped)), wrapped
    assert classify_git_command(wrapped)[1] == []


@pytest.mark.parametrize("command", [
    'bash -c -- "git commit -m y"', 'bash -o pipefail -c "git commit -m y"',
    'ksh -c "git commit -m y"', 'sudo -u root sh -c "git commit -m y"',
    'echo "$(bash -c "git commit -m y")"', 'bash -c "git status && git commit -m y"',
    'bash -c "git commit -m y">/dev/null', "xargs -I{} sh -c 'git commit -m y' < list",
    "cat <<'EOF'\nit's a note\nEOF\nbash -c 'git commit -m y'",
    'bash $OPTS -c "git commit -m y"', 'bash $X "git commit -m y"', _nest("git commit -m y", 4),
])
def test_other_spellings_of_a_shell_string_resolve(command):
    assert ("commit", ("-m", "y")) in _calls(command), command
    assert classify_git_command(command)[1] == []


@pytest.mark.parametrize("command", UNRESOLVED + [_nest("git commit -m y", 5)])
def test_a_string_the_scan_cannot_know_is_a_residual(command):
    kinds = [kind for kind, _seg in classify_git_command(command)[1]]
    assert "unresolved_shell_string" in kinds, command


@pytest.mark.parametrize("command", UNRESOLVED)
@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_privilege_guard_refuses_an_unresolved_string(verdicts, command, subagent):
    assert verdicts[(PRIVILEGE, command, subagent)] == 2, command


@pytest.mark.parametrize("command", [
    "bash -c 'echo hi; ls'", "bash -c 'echo $HOME'", "sh -c 'cat README.md'",
    "echo \"bash -c 'git commit -m y'\"", "grep -rn 'sh -c' docs", "./deploy.sh -c \"$CFG\"",
    "bash script.sh",
])
def test_a_resolvable_string_without_git_is_not_git(command):
    assert classify_git_command(command) == ([], []), command


@pytest.mark.parametrize("command,code", REVIEW_ROWS)
@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_review_rows_exit_as_before_p10(verdicts, command, code, subagent):
    assert verdicts[(PRIVILEGE, command, subagent)] == code, command


@pytest.mark.parametrize("command", GIT_SHAPED)
@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_privilege_guard_refuses_git_in_those_shapes(verdicts, command, subagent):
    assert verdicts[(PRIVILEGE, command, subagent)] == 2, command


@pytest.mark.parametrize("command", [row for row, code in REVIEW_ROWS if code == 0] + [
    'bash -c "$PYTHON -m pytest"', 'bash -c "cd $DIR; $MAKE test"', 'sh -c "cd $D && npm test',
    "cat > notes.md <<'EOF'\nTo publish:\nbash -c \"git push\"\nEOF",
    "tee notes.md <<EOF\nbash -c \"git push $REMOTE\"\nEOF",
    "python3 - <<'PY'\nprint(\"don't run sh -c 'git push'\")\nPY",
])
def test_a_git_free_string_with_a_run_time_value_or_a_data_here_document_is_not_git(command):
    assert classify_git_command(command) == ([], []), command


@pytest.mark.parametrize("command", [
    'bash -c "cd $DIR && git push"', 'bash -c "git $SUB"', 'bash -c "$G push"',
    'bash -c "`which git` push"', 'bash -c "$SUDO git push"', 'bash -c "$X $Y"', 'bash -c "$CMD"',
    "bash -c \"bash -c '$X'\"", 'bash -c "git status', "sh <<EOF\nbash -c '$CMD'\nEOF",
])
def test_a_git_shaped_string_is_a_residual(command):
    kinds = [kind for kind, _seg in classify_git_command(command)[1]]
    assert "unresolved_shell_string" in kinds, command


@pytest.mark.parametrize("command", [
    "sh <<'EOF'\nbash -c 'git push'\nEOF", "bash -s <<'EOF'\nbash -c 'git push'\nEOF",
    "cat <<'EOF' | sh\nbash -c 'git push'\nEOF", "{ cat <<'EOF'; } | sh\nbash -c 'git push'\nEOF",
    "cat <<'EOF' |\nbash -c 'git push'\nEOF\nsh", "ssh host <<'EOF'\nbash -c 'git push'\nEOF",
    "sudo -i <<'EOF'\nbash -c 'git push'\nEOF", "cat <<EOF\n$(bash -c 'git push')\nEOF",
])
def test_a_here_document_a_shell_may_read_is_shell_text(command):
    assert ("push", ()) in _calls(command), command


def test_a_here_document_no_shell_reads_is_data():
    command = "git commit -F - <<'EOF'\nFix the publish step:\nbash -c \"git push\"\nEOF"
    assert classify_git_command(command)[1] == []
    assert [inv.subcommand for inv in iter_git_invocations(command)] == ["commit"]


def test_a_run_time_value_reads_as_a_placeholder_in_its_layer():
    texts = list(git_command_classifier.iter_shell_texts('bash -c "git checkout -b $NAME"'))
    assert texts[1] == "git checkout -b ${__runtime__}"


def test_a_shell_named_in_a_commit_message_is_data():
    assert _calls("git commit -m 'run bash -c \"git push\" later'") == [
        ("commit", ("-m", "'run", "bash", "-c", '"git', 'push"', "later'"))]


def test_every_residual_kind_is_one_the_override_route_accepts():
    samples = ['g\\it push', '$GIT push', '$(which git) push', 'bash -c "$X"']
    kinds = {kind for cmd in samples for kind, _seg in classify_git_command(cmd)[1]}
    assert kinds == set(git_command_classifier.RESIDUAL_KINDS)
    spec = importlib.util.spec_from_file_location(
        "override", ROOT / "scripts" / "write-git-residual-override.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.VALID_KINDS == git_command_classifier.RESIDUAL_KINDS


def test_the_cli_marks_an_invocation_inside_a_shell_string(sandbox):
    def cli(stdin, raw=None):
        env = dict(sandbox["env"], **({"CMD_RAW": "stdin"} if raw is not None else {}))
        text = stdin if raw is None else stdin + "\n\0" + raw
        out = subprocess.run([sys.executable, str(HOOKS / "lib" / "git_command_classifier.py")],
                             input=text, capture_output=True, text=True, env=env, check=True)
        return json.loads(out.stdout)
    assert cli("git push --force") == [
        {"subcommand": "push", "args": ["--force"], "path_qualified": False, "nested": False}]
    # The stripped view bash-safety feeds has lost the string's end; the raw text holds it.
    assert cli("bash -c -- ", raw='bash -c -- "git push --force"') == [
        {"subcommand": "push", "args": ["--force"], "path_qualified": False, "nested": True}]
