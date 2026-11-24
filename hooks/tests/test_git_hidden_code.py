"""Git hidden in interpreter inline code or in a script file the command runs (GIT-2).

The classifier reads shell text, so `python3 -c 'subprocess.run(["git","push"])'`
and `bash push.sh` (push.sh runs `git push origin master`) passed every
PreToolUse hook. hidden_git_texts now yields the git such code names and the
text of a readable literal script file, and the guard judges them:

  - inline code (python/python3 -c, node -e, perl -e, ruby -e): the token `git`
    then a guarded subcommand, quotes and list punctuation between them. It is
    lexical and conservative for perl, ruby and node. Python is read as code
    (the removal analyzer's reading): only what it starts counts, so
    `python3 -c 'print("git push")'` passes (it was refused until 2026-11-20).
  - a script file (`bash`, `sh`, `source`, `.`, `./x.sh`) that exists and is
    readable relative to the payload's cwd, read as shell text.

Still passes: harmless code and scripts, a missing script (unseen, a documented
residual), and the harness's own wrappers in hooks/ and scripts/, which /push
and /merge run.

The guard runs as a subprocess with a scratch HOME, state dir and repository,
with a main-agent payload and a subagent payload.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
GUARD = HOOKS / "pretool-git-privilege-guard.py"
sys.path.insert(0, str(HOOKS))

SCRIPTS = {
    "push.sh": "#!/bin/bash\nset -e\ngit push origin master\n",
    "commit.sh": "git add -A\ngit commit -m wip\n",
    "inline.sh": "python3 -c 'import os; os.system(\"git reset --hard HEAD~1\")'\n",
    "scripts/harmless.sh": "#!/bin/sh\necho \"remember to git push later\"\ngit status\ngit log -1\n",
    "tool.py": "#!/usr/bin/env python3\nimport subprocess\nsubprocess.run(['git', 'push'])\n",
}

MUST_REFUSE = [
    # interpreter inline code
    "python3 -c 'import subprocess; subprocess.run([\"git\",\"push\"])'",
    "python -c 'import subprocess; subprocess.run([\"git\", \"push\", \"origin\", \"master\"])'",
    "python3 -c 'import os; os.system(\"git push\")'",
    "python3 -c \"import subprocess; subprocess.run('git push', shell=True)\"",
    "python3 -c 'import subprocess; subprocess.run([\"git\", \"-C\", \"x\", \"commit\", \"-m\", \"m\"])'",
    "node -e 'require(\"child_process\").execSync(\"git push origin master\")'",
    "node -e 'require(\"child_process\").execFileSync(\"git\", [\"merge\", \"feature\"])'",
    "node --eval='require(\"child_process\").execSync(\"git rebase main\")'",
    "perl -e 'system(\"git push\")'",
    "perl -e 'system(\"git\", \"branch\", \"-D\", \"master\")'",
    "perl -e '`git update-ref refs/heads/master HEAD~1`'",
    "ruby -e 'system(\"git commit -am x\")'",
    "ruby -e '`git reset --hard`'",
    "bash -c \"python3 -c 'import os; os.system(\\\"git push\\\")'\"",
    "python3 -X dev -c 'import os; os.system(\"git push\")'",
    "perl -I lib -e 'system(\"git push\")'",
    "timeout 5 python3 -c 'import os; os.system(\"git commit -m x\")'",
    # script files
    "bash push.sh",
    "sh push.sh",
    "source push.sh",
    ". push.sh",
    "./push.sh",
    "bash -e push.sh",
    "true && bash commit.sh",
    "bash inline.sh",
    "env bash push.sh",
    "sudo -u nobody bash push.sh",
]

MUST_PASS = [
    "python3 -c 'print(1)'",
    "python3 -c 'print(\"git push\")'",  # Python is read as code: a string it prints starts nothing
    "python3 -c 'import subprocess; subprocess.run([\"git\",\"status\"])'",
    "node -e 'console.log(1)'",
    "ruby -e 'system(\"git branch -a\")'",
    "perl -e 'print 1'",
    "python3 -m pytest -q",
    "bash scripts/harmless.sh",
    "sh scripts/harmless.sh",
    "source scripts/harmless.sh",
    "bash missing.sh",
    "python3 tool.py",
    "./tool.py",
    "bash -c 'git status'",
]


def _sandbox(tmp_path):
    home, state, repo = (tmp_path / n for n in ("home", "state", "proj"))
    for d in (home, state, repo):
        d.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_", "PYTHON"))}
    env.update(HOME=str(home), CLAUDE_STATE_DIR=str(state), CLAUDE_PROJECT_DIR=str(repo),
               PYTHONDONTWRITEBYTECODE="1", GIT_CEILING_DIRECTORIES=str(tmp_path),
               GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True, env=env,
                   capture_output=True)
    for rel, text in SCRIPTS.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755)
    return repo, env


def _run(command, cwd, env, subagent, hook_cwd=None):
    payload = {"session_id": "hidden-git-0001", "tool_name": "Bash",
               "tool_input": {"command": command}, "cwd": str(cwd),
               "hook_event_name": "PreToolUse", "transcript_path": "",
               "permission_mode": "default"}
    if subagent:
        payload.update(agent_id="agent-hidden-git", agent_type="general-purpose")
    return subprocess.run([sys.executable, "-B", str(GUARD)], input=json.dumps(payload),
                          text=True, capture_output=True, cwd=str(hook_cwd or cwd), env=env, timeout=120)


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_guard_refuses_git_hidden_in_code_or_a_script(tmp_path, subagent):
    repo, env = _sandbox(tmp_path)
    for command in MUST_REFUSE:
        proc = _run(command, repo, env, subagent)
        assert proc.returncode == 2, (command, proc.stdout, proc.stderr)
        assert "BLOCKED" in proc.stderr, (command, proc.stderr)


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_guard_lets_harmless_code_and_scripts_through(tmp_path, subagent):
    repo, env = _sandbox(tmp_path)
    for command in MUST_PASS:
        proc = _run(command, repo, env, subagent)
        assert proc.returncode == 0, (command, proc.stderr)


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_harness_wrappers_are_not_read(tmp_path, subagent):
    # /push and /merge run hooks/push.sh and hooks/merge.sh, which run git push
    # and git merge themselves.
    _repo, env = _sandbox(tmp_path)
    for command in ("bash hooks/push.sh", "bash hooks/merge.sh feature",
                    'bash "%s" feature' % (HOOKS / "merge.sh")):
        proc = _run(command, ROOT, env, subagent)
        assert proc.returncode == 0, (command, proc.stderr)


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_a_script_is_read_in_the_calls_directory_not_the_hooks(tmp_path, subagent):
    # The call runs in the repository, whose push.sh pushes; the hook process runs in another directory,
    # whose push.sh is harmless, or which has none. The script named relative is read where the call runs.
    repo, env = _sandbox(tmp_path)
    harmless, empty = tmp_path / "harmless", tmp_path / "empty"
    for d in (harmless, empty):
        d.mkdir()
    (harmless / "push.sh").write_text(SCRIPTS["scripts/harmless.sh"])
    (harmless / "push.sh").chmod(0o755)
    for hook_dir in (repo, harmless, empty):
        for command in ("bash push.sh", "./push.sh", "source push.sh", "bash %s" % (repo / "push.sh")):
            proc = _run(command, repo, env, subagent, hook_cwd=hook_dir)
            assert proc.returncode == 2 and "BLOCKED" in proc.stderr, (hook_dir, command, proc.stderr)
    # and the other way round: the call runs where push.sh is harmless, the hook where it pushes
    for command in ("bash push.sh", "./push.sh", "bash %s" % (harmless / "push.sh")):
        proc = _run(command, harmless, env, subagent, hook_cwd=repo)
        assert proc.returncode == 0, (command, proc.stderr)
    # A cd in the command moves where the script is read: to the literal directory it names; a cd the guard
    # cannot follow leaves the relative script unproven, refused, never read as empty.
    (harmless / "sub").mkdir()
    (harmless / "sub" / "push.sh").write_text(SCRIPTS["push.sh"])
    for command, rc in (("cd sub && bash push.sh", 2), ("cd sub; ./push.sh", 2), ("(cd sub) && bash push.sh", 0),
                        ('cd "$D" && bash push.sh', 2), ('cd "$D" && bash %s' % (harmless / "push.sh"), 0)):
        for hook_dir in (harmless, empty):
            proc = _run(command, harmless, env, subagent, hook_cwd=hook_dir)
            assert proc.returncode == rc, (hook_dir, command, proc.stderr)


def test_hidden_git_texts_reads_code_and_scripts(tmp_path):
    from lib.git_command_classifier import hidden_git_texts
    repo, _env = _sandbox(tmp_path)
    found = list(hidden_git_texts("python3 -c 'subprocess.run([\"git\",\"push\",\"--force\"])'"))
    assert found == [("python3 inline code", "git push --force")]
    assert list(hidden_git_texts("python3 -c 'print(1)'")) == []
    texts = [text for _o, text in hidden_git_texts("bash push.sh", str(repo))]
    assert texts and "git push origin master" in texts[0]
    assert list(hidden_git_texts("bash push.sh", str(tmp_path))) == []  # missing: unseen
    assert list(hidden_git_texts("bash push.sh", str(repo), (str(repo),))) == []  # trusted
