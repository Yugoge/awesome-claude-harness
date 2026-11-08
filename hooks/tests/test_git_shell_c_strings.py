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

That narrowing let a layer hand its run-time text to a shell, an interpreter
or a sourced file inside it: `bash -c "echo $X | sh"` and six other rows exited
2 before it and 0 after, and `bash -c "watch $X"` exited below `watch $X` run
plainly. Such a layer is a residual again (RUNTIME_CODE); each shape's data
twin stays allowed (RUNTIME_CODE_TWINS).

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

# Run-time text reaching a shell, an interpreter or a sourced file inside a -c
# layer, and the same text run plainly. Each layer exited 2 at dfc90534 and 0
# at 1c6ba6ce over the privilege guard, bash-safety and the branch hook, for
# the main agent and for a subagent; `watch $X` exited 2 plainly on both heads.
RUNTIME_CODE = [
    ('bash -c "echo $X | sh"', 'echo $X | sh'),
    ('bash -c "sh <<< $X"', 'sh <<< $X'),
    ('bash -c "source $F"', 'source $F'),
    ('bash -c ". $F"', '. $F'),
    ('bash -c "bash $F"', 'bash $F'),
    ('bash -c "python3 -c $P"', 'python3 -c $P'),
    ('bash -c "watch $X"', 'watch $X'),
]
LAYER_HOOKS = (PRIVILEGE, SAFETY, BRANCH)
# The same rule over the other ways a layer runs run-time text as shell or
# code: a run-time value the layer's own shell expands, eval before one, trap,
# su, ssh, the interpreters' code options, a run-time script or module, a pipe
# into a group, input the layer itself is fed, a shell a launcher names.
RUNTIME_CODE_VARIANTS = [
    'bash -c "echo \\$X | sh; cd $DIR"', 'bash -c "eval echo $X"', 'bash -c "eval \\$X; cd $DIR"',
    'bash -c "trap $X EXIT"', 'bash -c "su -c $X"', 'bash -c "ssh host $X"',
    'bash -c "perl -e $X"', 'bash -c "ruby -e $X"', 'bash -c "node -e $X"', 'bash -c "php -r $X"',
    'bash -c "awk $X file"', 'bash -c "python3 -c \\"print($X)\\""', 'bash -c "python3 $F"',
    'bash -c "python3 -m $M"', "bash -c \"python3 - <<EOF\nx = '$X'\nEOF\"",
    'bash -c "sh < $F"', 'bash -c "source <(echo $X)"', 'bash -c "echo $X | (cd /; sh)"',
    'bash -c "echo $X | { cd /; sh; }"', 'bash -c "echo $X > >(sh)"', 'bash -c "sh <<EOF\ncd $DIR\nEOF"',
    'echo $X | bash -c "cd $DIR; sh"', 'bash -c "find . -exec sh -c $X \\\\;"',
    'bash -c "docker exec c bash -c $X"', 'bash -c "$PY -c $CODE"', 'bash -c "bash -x $F"',
    "bash -c 'sh -c \"echo $X | sh\"'", 'bash -c "for f in $FILES; do python3 $f; done"',
]
# (layer the rule refuses, its data twin a layer keeps): a pipe into grep, a
# here-string to cat, a static file sourced or run, a module, a static script
# given a run-time argument, here-documents only cat and tee read, `push`.
RUNTIME_CODE_TWINS = [
    ('bash -c "echo $X | sh"', 'bash -c "echo $X | grep sh"'),
    ('bash -c "sh <<< $X"', 'bash -c "cat <<< $X"'),
    ('bash -c "source $F"', 'bash -c "source ./env.sh && cd $DIR"'),
    ('bash -c ". $F"', 'bash -c ". ./env.sh && cd $DIR"'),
    ('bash -c "bash $F"', 'bash -c "bash ./run.sh $ARG"'),
    ('bash -c "python3 -c $P"', 'bash -c "python3 -m pytest -k $P"'),
    ('bash -c "watch $X"', 'bash -c "watch -n 5 ls; cd $DIR"'),
    ('bash -c "echo $X | python3"', 'bash -c "echo $X | python3 parse.py"'),
    ("bash -c \"python3 - <<EOF\nx = '$X'\nEOF\"", "bash -c \"cat > notes.py <<EOF\nx = '$X'\nEOF\""),
    ('bash -c "sh <<EOF\ncd $DIR\nEOF"', 'bash -c "tee notes.sh <<EOF\ncd $DIR\nEOF"'),
    ('bash -c "awk $X file"', "bash -c \"awk -v d=$DIR '{print d}' file\""),
    ('bash -c "trap $X EXIT"', "bash -c \"trap 'rm -f tmp' EXIT; cd $DIR\""),
    ('bash -c "eval echo $X"', 'bash -c "echo $X"'),
    ('bash -c "$PY -c $CODE"', 'bash -c "$PYTHON -m pytest"'),
    ('bash -c "docker exec c bash -c $X"', 'bash -c "docker push $IMAGE"'),
    ('echo $X | bash -c "cd $DIR; sh"', 'echo $X | bash -c "cd $DIR; cat"'),
]
# A list of dangerous programs can never be complete, so the -c layer rule fails
# closed: a run-time word given to a program it does not model may run as a
# command or as code. These eight exited 2 at the privilege guard on 8f77f50 (P10
# refused every -c string with an expansion) and 0 at every hook once that was
# narrowed: an interpreter the scan does not model given run-time code, an
# exec-style launcher given a run-time command, find -exec, a run-time environment
# assignment that loads code, and a run-time -c value the outer shell built by
# running code. Each is a residual again, over the privilege guard, bash-safety
# and the branch hook, for the main agent and for a subagent.
FAIL_CLOSED = [
    'bash -c "octave --eval $X"',
    'bash -c "erl -eval $X"',
    'bash -c "chroot / $X"',
    'bash -c "strace $X"',
    'bash -c "find . -exec $X \\;"',
    'bash -c "BASH_ENV=$F bash -c true"',
    'bash -c "NODE_OPTIONS=--require=$F node x.js"',
    'bash -c "y=$(echo $X | sh)"',
]
# More ways the fail-closed rule fires in a layer: an unknown program given a
# run-time word, a known code-loading environment variable, a launcher wrapping an
# unknown interpreter, a backtick substitution that runs code to build a value.
FAIL_CLOSED_VARIANTS = [
    'bash -c "octave $X"', 'bash -c "scilab -f $X"', 'bash -c "chroot /jail $X arg"',
    'bash -c "unshare $X"', 'bash -c "nsenter -t 1 $X"', 'bash -c "find . -execdir $X +"',
    'bash -c "find . -ok $X \\;"', 'bash -c "env strace $X"', 'bash -c "timeout 5 octave --eval $X"',
    'bash -c "PERL5OPT=$O perl x.pl"', 'bash -c "PYTHONSTARTUP=$F python3"',
    'bash -c "LD_PRELOAD=$L ls"', 'bash -c "ENV=$F sh -c true"', 'bash -c "GIT_SSH_COMMAND=$C git fetch"',
    'bash -c "y=`sh <<< $X`"', 'bash -c "z=$(bash $F)"', 'bash -c "for f in $FILES; do octave $f; done"',
]
# (the fail-closed layer the rule refuses, a data twin it keeps). The twin runs a
# program known to treat its run-time word as data (echo, printf, grep, cat, cd,
# curl, sleep, test), a static operand, or an environment variable that cannot
# load code (TZ, LANG), so it stays allowed.
FAIL_CLOSED_TWINS = [
    ('bash -c "octave --eval $X"', 'bash -c "printf %s $X"'),
    ('bash -c "erl -eval $X"', 'bash -c "grep $X file"'),
    ('bash -c "chroot / $X"', 'bash -c "cd $DIR"'),
    ('bash -c "strace $X"', 'bash -c "sleep $N"'),
    ('bash -c "find . -exec $X \\;"', 'bash -c "find . -name notes -print"'),
    ('bash -c "BASH_ENV=$F bash -c true"', 'bash -c "TZ=$Z date"'),
    ('bash -c "NODE_OPTIONS=--require=$F node x.js"', 'bash -c "LANG=$L node x.js"'),
    ('bash -c "y=$(echo $X | sh)"', 'bash -c "y=$(echo $X)"'),
    ('bash -c "strace $X"', 'bash -c "test -f $X"'),
    ('bash -c "chroot / $X"', 'bash -c "curl $X"'),
]
# Each data command listed in the message's example given a run-time word, allowed.
DATA_WORD_ALLOWED = [
    'bash -c "echo $X"', 'bash -c "printf %s $X"', 'bash -c "grep $X file"',
    'bash -c "cat $X"', 'bash -c "cd $X"', 'bash -c "curl $X"',
    'bash -c "sleep $X"', 'bash -c "test -f $X"',
]
# `watch` runs its operand as a command, so `watch $X` runs run-time text as
# code when run plainly too: (form, the hook that refuses it, the rule that hook
# names). bash-safety's analyzer falls on a timeout to a degraded mode that
# refuses any `$`, so the rule is read from runs that give the analyzer time.
WATCH_RULES = [
    ('watch $X', SAFETY, "UNRESOLVED dynamic_command_head:$X"),
    ('bash -c "watch $X"', PRIVILEGE, "unresolved_shell_string"),
]
ANALYZER_TIME = {"CLAUDE_HOOK_BOUNDARY_TIMEOUT": "60s"}


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


def _hook(sandbox, hook, command, subagent=False, env=None):
    payload = {"tool_name": "Bash", "tool_input": {"command": command},
               "session_id": "shell-c-test", "cwd": sandbox["repo"],
               "hook_event_name": "PreToolUse"}
    if subagent:
        payload.update(agent_id="agent-shell-c-test", agent_type="dev")
    argv = ["bash" if hook.endswith(".sh") else sys.executable, str(HOOKS / hook)]
    return subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True,
                          env=dict(sandbox["env"], **(env or {})), cwd=sandbox["repo"], timeout=120)


def _run(sandbox, hook, command, subagent=False):
    return _hook(sandbox, hook, command, subagent).returncode


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
    runs.update((hook, cmd, actor) for pair in RUNTIME_CODE for cmd in pair
                for hook in LAYER_HOOKS for actor in (False, True))
    runs.update((hook, cmd, actor) for cmd in FAIL_CLOSED
                for hook in LAYER_HOOKS for actor in (False, True))
    runs.update((hook, cmd, actor) for cmd, _decider, _rule in WATCH_RULES
                for hook in LAYER_HOOKS for actor in (False, True))
    runs = sorted(runs)
    with ThreadPoolExecutor(max_workers=8) as ex:
        codes = list(ex.map(lambda r: _run(sandbox, *r), runs))
    return dict(zip(runs, codes))


@pytest.fixture(scope="module")
def refusals(sandbox):
    """(exit code, stderr) of the hook WATCH_RULES names for each form, the analyzer given time."""
    runs = [(hook, cmd, actor) for cmd, hook, _rule in WATCH_RULES for actor in (False, True)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        procs = list(ex.map(lambda r: _hook(sandbox, *r, env=ANALYZER_TIME), runs))
    return {run: (proc.returncode, proc.stderr) for run, proc in zip(runs, procs)}


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


@pytest.mark.parametrize("layer,plain", RUNTIME_CODE, ids=[layer for layer, _plain in RUNTIME_CODE])
@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_a_layer_running_run_time_text_as_code_exits_2_and_never_below_its_plain_text(
        verdicts, layer, plain, subagent):
    # The guard first: on a loaded host bash-safety's analyzer can time out and
    # its degraded mode refuses any `$`, which says nothing about the classifier.
    assert verdicts[(PRIVILEGE, layer, subagent)] == 2, layer
    layer_code = max(verdicts[(hook, layer, subagent)] for hook in LAYER_HOOKS)
    plain_code = max(verdicts[(hook, plain, subagent)] for hook in LAYER_HOOKS)
    assert layer_code == 2, layer
    assert layer_code >= plain_code, (layer, plain)


@pytest.mark.parametrize("command,hook,rule", WATCH_RULES, ids=[cmd for cmd, _h, _r in WATCH_RULES])
@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_watch_of_run_time_text_exits_2_plainly_and_in_a_layer_on_the_rule_that_decides_it(
        verdicts, refusals, command, hook, rule, subagent):
    assert max(verdicts[(h, command, subagent)] for h in LAYER_HOOKS) == 2, command
    assert verdicts[(hook, command, subagent)] == 2, (command, hook)
    # The deciding hook's own rule, never a degraded mode's blanket `$` refusal.
    code, stderr = refusals[(hook, command, subagent)]
    assert code == 2, (command, hook, stderr)
    assert rule in stderr, (command, hook, stderr)


@pytest.mark.parametrize("command", [layer for layer, _plain in RUNTIME_CODE] + RUNTIME_CODE_VARIANTS)
def test_run_time_text_a_shell_or_an_interpreter_runs_in_a_layer_is_a_residual(command):
    kinds = [kind for kind, _seg in classify_git_command(command)[1]]
    assert "unresolved_shell_string" in kinds, command


@pytest.mark.parametrize("refused,twin", RUNTIME_CODE_TWINS, ids=[r for r, _t in RUNTIME_CODE_TWINS])
def test_a_layer_refuses_run_time_code_and_keeps_its_data_twin(refused, twin):
    kinds = [kind for kind, _seg in classify_git_command(refused)[1]]
    assert "unresolved_shell_string" in kinds, refused
    assert classify_git_command(twin) == ([], []), twin


@pytest.mark.parametrize("command", FAIL_CLOSED, ids=FAIL_CLOSED)
@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_a_fail_closed_layer_exits_2_over_the_guard_and_every_hook(verdicts, command, subagent):
    # The guard first: on a loaded host bash-safety's analyzer can time out and
    # its degraded mode refuses any `$`, which says nothing about the classifier.
    assert verdicts[(PRIVILEGE, command, subagent)] == 2, command
    assert max(verdicts[(hook, command, subagent)] for hook in LAYER_HOOKS) == 2, command


@pytest.mark.parametrize("command", FAIL_CLOSED + FAIL_CLOSED_VARIANTS)
def test_a_run_time_word_a_program_the_scan_does_not_model_gets_is_a_residual(command):
    kinds = [kind for kind, _seg in classify_git_command(command)[1]]
    assert "unresolved_shell_string" in kinds, command


@pytest.mark.parametrize("refused,twin", FAIL_CLOSED_TWINS, ids=[r for r, _t in FAIL_CLOSED_TWINS])
def test_the_fail_closed_rule_keeps_each_refused_shape_a_data_twin(refused, twin):
    kinds = [kind for kind, _seg in classify_git_command(refused)[1]]
    assert "unresolved_shell_string" in kinds, refused
    assert classify_git_command(twin) == ([], []), twin


@pytest.mark.parametrize("command", DATA_WORD_ALLOWED)
def test_a_data_command_given_a_run_time_word_in_a_layer_is_allowed(command):
    assert classify_git_command(command) == ([], []), command


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
