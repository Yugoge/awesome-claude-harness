#!/usr/bin/env python3
"""The /stop user-intent guard passes only what it PROVES is not a run (OB-L38 rework).

hooks/pretool-wrapper-userintent.py keeps the previous text rule as its fallback: a
command that rule refuses still needs the /stop sentinel unless every mention of the
wrapper is proven harmless (an operand or pattern of a known reader whose output goes
nowhere that runs, a commit message, a print-only interpreter string, a file that is not
the harness home's wrapper). On top of that it refuses runs the text rule never saw
(find -exec {} over find's matches, an exported BASH_ENV, `exec <` before a shell,
interpreter heredocs, a later +n, brace expansion, python -m runners and the wrapper's
module name, CDPATH, command-carrying variables and persisted commands). A harmless read
neither is refused nor burns a live sentinel.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "pretool-wrapper-userintent.py"
SID = "ob-l38-proof"


@pytest.fixture()
def env(tmp_path):
    home = tmp_path / "home"
    harness = home / ".claude"
    (harness / "hooks").mkdir(parents=True)
    (harness / "scripts").mkdir(parents=True)
    (harness / "hooks" / "stop.sh").write_text("#!/usr/bin/env bash\n# HELPER\nexit 0\n")
    (harness / "scripts" / "break-overnight-lock.py").write_text("print('x')\n")
    for f in ((harness / "hooks" / "stop.sh"), (harness / "scripts" / "break-overnight-lock.py")):
        f.chmod(0o755)
    project = tmp_path / "project"
    for rel in ("docs", "scripts", "hooks"):
        (project / rel).mkdir(parents=True)
    (project / "docs" / "a.md").write_text("bash hooks/stop.sh\n")
    (project / "scripts" / "stop.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    (project / "scripts" / "stop.sh").chmod(0o755)
    (project / "hooks" / "stop.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    (project / "scripts" / "break-overnight-lock.py").write_text("print('own')\n")
    state = tmp_path / "state"
    state.mkdir()
    return {"home": home, "harness": harness, "project": project, "state": state}


def _run(env, command):
    command = command.replace("{H}", str(env["harness"]))
    cwd = str(env["project"])
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": SID,
               "cwd": cwd}
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    run_env.update(HOME=str(env["home"]), CLAUDE_HOME=str(env["harness"]),
                   CLAUDE_STATE_DIR=str(env["state"]),
                   CLAUDE_USERINTENT_SENTINEL_DIR=str(env["state"]))
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=cwd, env=run_env, timeout=60)


def _sentinel(env):
    return env["state"] / f"claude-stop-userintent-{SID}.flag"


W = "~/.claude/hooks/stop.sh"
L = "~/.claude/scripts/break-overnight-lock.py"

# (A) the text rule refused these; a parser-only reading let them through.
HIDDEN_BEHIND_RUNNERS = [
    f"gdb -batch -ex run --args bash {W}",
    f"ssh-agent bash {W}",
    f"catchsegv bash {W}",
    f"cpulimit -l 50 -- bash {W}",
    f"trickle -d 10 bash {W}",
    f"linux64 bash {W}",
    f"rlwrap bash {W}",
    f"softlimit -m 100000000 bash {W}",
    f"schedtool -B -e bash {W}",
    f"cgexec -g cpu:x bash {W}",
    f"tini -- bash {W}",
    f"dumb-init bash {W}",
    f"gosu root bash {W}",
    f"su-exec root bash {W}",
    f"mpirun -n 1 bash {W}",
    f"srun bash {W}",
    f"torsocks bash {W}",
    f"proxychains bash {W}",
    f"xterm -e bash {W}",
    f"dbus-launch bash {W}",
    f"nix-shell --run 'bash {W}'",
    f"direnv exec . bash {W}",
    f"poetry run bash {W}",
    f"uv run bash {W}",
    f"uv run python {L}",
    f"pipenv run bash {W}",
    f"conda run bash {W}",
    f"pyenv exec python {L}",
    f"mise exec -- bash {W}",
    f"bundle exec bash {W}",
    f"npm exec -- bash {W}",
    f"npx bash {W}",
    f"pnpm exec bash {W}",
    f"ts bash {W}",
    f"nq bash {W}",
    f"tsp bash {W}",
    f"sem bash {W}",
    f"entr -n bash {W} < /dev/null",
]

CDPATH_AND_PYTHON_FORMS = [
    "CDPATH=~/.claude cd hooks && ./stop.sh",
    "export CDPATH=~/.claude; cd hooks && ./stop.sh",
    "CDPATH=~/.claude; cd hooks && ./stop.sh",
    "CDPATH=~/.claude cd scripts && python3 break-overnight-lock.py",
    f"python3 -mcProfile {L}",
    f"PYTHONSTARTUP={L} python3 -i",
]

COMMAND_CARRYING_AND_PERSISTED = [
    f"GIT_SSH_COMMAND='bash {W}' git fetch",
    f"GIT_EDITOR='bash {W}' git commit --amend",
    f"GIT_SEQUENCE_EDITOR='bash {W}' git rebase -i HEAD~1",
    f"EDITOR='bash {W}' crontab -e",
    f"SHELL={W} script -q /dev/null",
    f"GIT_PAGER='bash {W}' git log",
    f"PAGER='bash {W}' man ls",
    f"crontab -l | {{ cat; echo '* * * * * bash {W}'; }} | crontab -",
    f"git config core.pager 'bash {W}'",
    f"echo 'bash {W}' >> ~/.bashrc",
    f"git -c core.editor='bash {W}' commit",
]

# (A2) both the text rule and the parser-only reading passed these.
UNSEEN_RUNS = [
    "find ~/.claude/hooks -name stop.sh -exec {} \\;",
    "find ~/.claude/hooks -name 'stop.sh' -exec {} \\;",
    "find ~/.claude/hooks -name stop.sh -exec {} +",
    "find ~/.claude/hooks -name 'st*' -exec bash {} +",
    "find ~/.claude/hooks -name stop.sh -execdir ./{} \\;",
    f"export BASH_ENV={W}; bash -c true",
    f"exec < {W}; bash",
    "python3 <<'EOF'\nexec(open('{H}/scripts/break-overnight-lock.py').read())\nEOF",
    "python3 - <<'EOF'\nimport subprocess; subprocess.run(['bash','{H}/hooks/stop.sh'])\nEOF",
    f"perl <<'EOF'\nsystem(\"bash {W}\");\nEOF",
    f"node <<'EOF'\nrequire(\"child_process\").execSync(\"bash {W}\")\nEOF",
    f"bash -n +n {W}",
    f"bash -xn +n {W}",
    f"bash -o noexec +o noexec {W}",
    f"bash -n -o noexec +o noexec +n {W}",
    "bash ~/.claude/hooks/sto{p,q}.sh",
    "bash ~/.claude/hooks/{stop,x}.sh",
    "bash ~/.claude/hooks/s{s..t}op.sh",
    f"python3 -m cProfile {L}",
    f"python3 -m profile {L}",
    f"python3 -m trace --count {L}",
    f"python3 -m pdb -c continue {L}",
    f"python3 -m runpy {L}",
    "cd ~/.claude/scripts && python3 -m break-overnight-lock",
    "PYTHONPATH=~/.claude/scripts python3 -m break-overnight-lock",
]

MUST_REFUSE = HIDDEN_BEHIND_RUNNERS + CDPATH_AND_PYTHON_FORMS + COMMAND_CARRYING_AND_PERSISTED \
    + UNSEEN_RUNS


@pytest.mark.parametrize("command", MUST_REFUSE)
def test_a_run_is_refused_without_a_sentinel(env, command):
    proc = _run(env, command)
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    assert "USER-INTENT GUARD" in proc.stderr


@pytest.mark.parametrize("command", UNSEEN_RUNS[:3] + HIDDEN_BEHIND_RUNNERS[:2])
def test_a_run_consumes_the_sentinel(env, command):
    _sentinel(env).write_text("true")
    proc = _run(env, command)
    assert proc.returncode == 0, proc.stderr
    assert not _sentinel(env).exists(), "a run must consume the single-use sentinel"


# (B) harmless reads: they pass and leave a live sentinel in place.
HARMLESS = [
    "find . -name stop.sh | xargs grep -l HELPER",
    "grep -rl stop.sh docs | xargs grep -n bash",
    "grep stop.sh docs/a.md; $EDITOR --version",
    'grep stop.sh docs/a.md; "$PY" -V',
    "bash scripts/missing-runner.sh stop.sh",
    f"awk 'NR<5' {W}",
    f"awk '/HELPER/' {W}",
    "awk '/stop.sh/' docs/a.md",
    f"gawk -F: '{{print $1}}' {W}",
    "python3 -c \"print('stop.sh')\"",
    "python3 -c \"import pathlib; print(pathlib.Path('docs/a.md').read_text().count('stop.sh'))\"",
    f"python3 -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' {L}",
    "python3 - <<'EOF'\nprint(open('docs/a.md').read().count('stop.sh'))\nEOF",
    "node -e \"console.log('stop.sh')\"",
    f"perl -pe 's/x/y/' {W}",
    f"perl -ne 'print if /HELPER/' {W}",
    "perl -ne 'print if /stop\\.sh/' docs/a.md",
    f"ruby -ne 'puts $_ if /HELPER/' {W}",
    "make test ARGS=stop.sh",
    "make -n lint FILE=hooks/stop.sh",
    f"echo {W} | xargs ls -l",
    f"echo {W} | xargs cat",
    "git ls-files | grep stop.sh | xargs wc -l",
    "git -c color.ui=never log --oneline -- hooks/stop.sh",
    "git -c core.quotepath=off diff -- hooks/stop.sh",
    "git -c alias.lg='log --oneline' lg -- hooks/stop.sh",
    "watch -n 5 ls -l hooks/stop.sh",
    f"ssh host cat {W}",
    "docker run --rm -v $PWD:/w alpine cat /w/hooks/stop.sh",
    "tmux send-keys 'grep stop.sh docs' Enter",
    f"cat {W} | python3 -c 'import sys; print(len(sys.stdin.read()))'",
    f"cat {W} | wc -l",
    "cat hooks/stop.sh | bash -n",
    f"bash -n < {W}",
    "CDPATH= cd docs && grep stop.sh a.md",
    'bash scripts/stop.sh "$@"',
    "chmod +x scripts/stop.sh && ./scripts/stop.sh",
    f"bash -n -x {W}",
    f"bash -o pipefail -n {W}",
    'git commit -m "docs: mention bash ~/.claude/hooks/stop.sh"',
    f"python3 -m py_compile {L}",
]


@pytest.mark.parametrize("command", HARMLESS)
def test_a_harmless_read_passes_and_keeps_the_sentinel(env, command):
    assert _run(env, command).returncode == 0
    _sentinel(env).write_text("true")
    proc = _run(env, command)
    assert proc.returncode == 0, proc.stderr
    assert _sentinel(env).exists(), "a harmless read consumed the single-use /stop sentinel"


# Proof is narrow: a reader whose output feeds a run, or code that calls something, is not.
NOT_PROVEN = [
    f"cat {W} > /tmp/ob-l38-copy-$$ && bash /tmp/ob-l38-copy-$$",
    f"grep -h bash {W} | bash",
    f"bash \"$(cat {W})\"",
    f"awk 'BEGIN{{system(\"bash {W}\")}}'",
    f"perl -ne 'system(\"bash {W}\")' docs/a.md",
    f"perl -pe 's|^|bash {W}|e' docs/a.md",
    f"python3 -c \"import os; os.system('bash {W}')\"",
    f"node -e \"require('child_process').execSync('bash {W}')\"",
    f"git -c alias.x='!bash {W}' x",
    f"sed -n '1e bash {W}' docs/a.md",
    f"printf -v x 'bash %s' {W}; $x",
    f"x={W}; bash $x",
    f"echo {W} | xargs bash",
    f"grep -rn \"bash hooks/stop.sh\" docs/; bash {W}",
]


@pytest.mark.parametrize("command", NOT_PROVEN)
def test_a_read_that_feeds_a_run_is_not_proven(env, command):
    proc = _run(env, command)
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
