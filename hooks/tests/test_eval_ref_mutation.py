"""Direct ref mutation run through `eval` is refused as the direct form is (BS-26).

`eval` joins its arguments and runs them as a command line, so
`eval "git branch -D old"` deletes a branch. The privilege guard reads git
through lib/git_command_classifier, whose segment walk skipped `eval` as a
wrapper and then met the word `"git`, no command name: the guard saw no git
and the deletion passed every registered PreToolUse entry. The classifier now
reads eval's arguments as a layer of their own, as it reads a `-c` string.

Hook cases run the registered entries of this tree (hooks/pretool-launch.py,
which runs the privilege guard, and hooks/pretool-bash-safety.sh) with a
sandboxed HOME, state directory and global git config, one fresh sandbox per
run: a refusal leaves state behind that later runs would read.
"""
import json
import os
import subprocess
import time
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS / "lib"))

from git_command_classifier import classify_git_command  # noqa: E402

LAUNCH = "pretool-launch.py"
SAFETY = "pretool-bash-safety.sh"
GUARD = "pretool-git-privilege-guard.py"
ENTRIES = (LAUNCH, SAFETY)
SESSION = "eval-ref-mutation-test"

REFUSED = [
    'eval "git branch -D old"',
    "eval 'git branch -d old'",
    'bash -c "git branch -D old"',
    'eval "git branch -m a b"',
    'eval "git update-ref -d refs/heads/old"',
    'eval -- git branch -D old',
    'command eval "cd . && git branch -D old"',
    'eval "git branch -D $B"',
    'eval "git branch -D old" 2>/dev/null',
    'bash -c \'eval "git branch -D old"\'',
    "cat <<'EOF' | bash\ngit branch -D old\nEOF",
    'echo old | xargs git branch -D',
]
PASSED = [
    "git branch -a",
    "git branch --show-current",
    'eval "git branch --list"',
    'grep -rn "git branch -D" docs/',
    'eval "$(ssh-agent -s)"',
    'echo eval git branch -D old',
]


def _sandbox(tmp_path):
    home, state, repo, tmp = (tmp_path / n for n in ("home", "state", "repo", "tmp"))
    for d in (home / ".claude", state, repo, tmp):
        d.mkdir(parents=True)
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_STATE_DIR": str(state),
           "GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
    for step in (["init", "-q", "-b", "master"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", *step], cwd=repo, env=env, check=True, capture_output=True)
    return env, repo, state


def _run(tmp_path, hook, command, grant=None):
    env, repo, state = _sandbox(tmp_path)
    if grant is not None:
        grants = state / "claude-grants"
        grants.mkdir()
        now = time.time()
        (grants / ("%s.json" % SESSION)).write_text(json.dumps({
            "task_id": SESSION, "session_id": SESSION, "allowed_operations": grant,
            "created_at": now, "expires_at": now + 300}))
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": SESSION,
               "cwd": str(repo), "hook_event_name": "PreToolUse"}
    argv = ["bash" if hook.endswith(".sh") else sys.executable, str(HOOKS / hook)]
    return subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True,
                          env=env, cwd=repo, timeout=120)


def _refused(proc):
    return proc.returncode == 2 or (proc.returncode == 0 and '"deny"' in proc.stdout)


@pytest.mark.parametrize("command", REFUSED)
def test_registered_entries_refuse_ref_mutation(tmp_path, command):
    verdicts = {hook: _run(tmp_path / hook.replace(".", "_"), hook, command) for hook in ENTRIES}
    assert any(_refused(p) for p in verdicts.values()), (command, {
        h: (p.returncode, p.stderr[-400:]) for h, p in verdicts.items()})
    assert "direct git ref mutation" in verdicts[LAUNCH].stderr, verdicts[LAUNCH].stderr[-400:]


@pytest.mark.parametrize("command", PASSED)
def test_registered_entries_pass_harmless_forms(tmp_path, command):
    for hook in ENTRIES:
        proc = _run(tmp_path / hook.replace(".", "_"), hook, command)
        assert not _refused(proc), (hook, command, proc.returncode, proc.stderr[-400:])


def test_allow_grant_still_releases_direct_form(tmp_path):
    grant = [{"op": "git", "args_contain": ["branch", "-D", "old"]}]
    proc = _run(tmp_path / "granted", GUARD, "git branch -D old", grant=grant)
    assert proc.returncode == 0, proc.stderr[-400:]
    proc = _run(tmp_path / "ungranted", GUARD, "git branch -D old")
    assert proc.returncode == 2, proc.stderr[-400:]


@pytest.mark.parametrize("command, words", [
    ('eval "git branch -D old"', ("branch", ["-D", "old"])),
    ("eval 'git update-ref -d refs/heads/old'", ("update-ref", ["-d", "refs/heads/old"])),
    ('eval "git branch -m a b" >/dev/null', ("branch", ["-m", "a", "b"])),
])
def test_classifier_reads_eval_payload(command, words):
    invocations, residuals = classify_git_command(command)
    assert words in [(inv.subcommand, inv.args) for inv in invocations]
    assert residuals == []


@pytest.mark.parametrize("command", ['eval "$(ssh-agent -s)"', "eval $(dircolors -b)", "echo eval git push"])
def test_classifier_eval_without_git_stays_clear(command):
    assert classify_git_command(command) == ([], [])
