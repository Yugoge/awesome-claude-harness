"""The git privilege guard reads inline Python as code: what it starts counts, its strings do not.

Python given on standard input (a here-document or a here-string) was not read at all, so
`python3 - <<'EOF'` with `subprocess.run(["git", "push"])` passed; Python given with -c was read
lexically, so a string that only names git (`print("git push")`) was refused. Both now go through
the removal analyzer's one reading of Python (bash_execution_boundary.python_started_commands):
each program the code starts is judged as that command typed in the shell, a computed word or
f-string part reading as a shell expansion; a program whose name is computed stays unseen.

The recorded live refusal (day 2, line 46 of the refusal record) is here with neutral names: its
here-document only rewrites a JSON report and passes; the command is refused for its second line,
`bash -c "$(python -c ...)"`, a shell -c string computed at run time (unresolved_shell_string), as
f199dfb1e refused it.

Each case runs the real hook of this tree with a scratch HOME, CLAUDE_STATE_DIR and git config.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "hooks" / "pretool-git-privilege-guard.py"

WRITE_REPORT = """cd /srv/project; python - <<'EOF'
import json
P='docs/report.json'
d=json.load(open(P))
d['items'][0]['check']="cd /srv/project && ! grep -rnE '^\\\\s*(from|import)\\\\s+_schema' scripts tests --include=*.py | grep -v '^scripts/_schema.py' | grep . && echo nothing imports it"
open(P,'w').write(json.dumps(d,indent=1))
EOF
"""
RUN_IT = """bash -c "$(python -c "import json;print(json.load(open('docs/report.json'))['items'][0]['check'])")"\n"""

REFUSED = {
    "heredoc argv": "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['git', 'push'])\nEOF\n",
    "heredoc os.system": "python3 - <<'EOF'\nimport os\nos.system('git push origin master')\nEOF\n",
    "heredoc shell=True": "python3 - <<'EOF'\nimport subprocess\nsubprocess.run('git reset --hard', shell=True)\nEOF\n",
    "-c argv": "python3 -c \"import subprocess; subprocess.run(['git', 'push'])\"",
    "-c os.system": "python3 -c \"import os; os.system('git push origin master')\"",
    "-c shell=True": "python3 -c \"import subprocess; subprocess.run('git reset --hard', shell=True)\"",
    "unquoted heredoc": "python3 - <<EOF\nimport subprocess\nsubprocess.run(['git', 'push'])\nEOF\n",
    "here-string": "python3 - <<< \"import subprocess; subprocess.run(['git', 'push'])\"",
    "argv through bash -c": "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['bash', '-c', 'git push'])\nEOF\n",
    "f-string": "python3 - <<'EOF'\nimport os\nr = 'origin'\nos.system(f'git push {r} master')\nEOF\n",
    "computed word": "python3 - <<'EOF'\nimport subprocess\nb = 'm'\nsubprocess.run(['git', 'push', 'origin', b])\nEOF\n",
}
ALLOWED = {
    "the recorded here-document": WRITE_REPORT,
    "a read": "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['git', 'status'])\nEOF\n",
    "git text written to a file": "python3 - <<'EOF'\nopen('f', 'w').write('git push origin master')\nEOF\n",
    "git text written, -c": "python3 -c \"open('f', 'w').write('git push origin master')\"",
    "git text printed, -c": "python3 -c \"print('git push')\"",
    "a computed program": "python3 - <<'EOF'\nimport subprocess, sys\nsubprocess.run(sys.argv[1:])\nEOF\n",
}


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("inline-python")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmp"
    for d in (home / ".claude", state, repo, tmp):
        d.mkdir(parents=True)
    gitconfig = base / "gitconfig"
    gitconfig.write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_STATE_DIR": str(state),
           "GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
    for step in (["init", "-q", "-b", "master"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", *step], cwd=repo, env=env, check=True, capture_output=True)
    return env, str(repo)


def _guard(sandbox, command):
    env, repo = sandbox
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "inline-python",
               "cwd": repo, "hook_event_name": "PreToolUse", "agent_id": "agent-inline-python",
               "agent_type": "dev"}
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=repo, timeout=120)


@pytest.mark.parametrize("name", list(REFUSED))
def test_python_that_starts_guarded_git_is_refused(sandbox, name):
    proc = _guard(sandbox, REFUSED[name])
    assert proc.returncode == 2 and "hidden in python3 inline code" in proc.stderr, proc.stderr


@pytest.mark.parametrize("name", list(ALLOWED))
def test_python_that_starts_no_guarded_git_runs(sandbox, name):
    proc = _guard(sandbox, ALLOWED[name])
    assert proc.returncode == 0, proc.stderr


def test_the_recorded_command_is_refused_for_its_run_time_shell_string_only(sandbox):
    proc = _guard(sandbox, WRITE_REPORT + RUN_IT)
    assert proc.returncode == 2 and "unresolved_shell_string" in proc.stderr, proc.stderr
    assert "inline code" not in proc.stderr, proc.stderr
