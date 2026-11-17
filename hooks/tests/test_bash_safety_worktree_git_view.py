"""The working-tree git rules of lib/bash_safety_rules.py (git stash, wide checkout, restore from a ref, git clean)
judge the git invocations lib/shell_parse.py finds, not the raw text: a git subcommand named in data passes, one
that runs (past wrappers, in a shell payload, in interpreter code that spawns it) is refused.

Every case runs the real hook entry (pretool-bash-safety.sh fed a PreToolUse payload) with a scratch HOME, state dir,
git config and a valid empty protected-runtime file. No command is ever executed.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
sys.path.insert(0, str(HOOKS))
from lib.runtime_guard.config import REQUIRED_KEYS  # noqa: E402


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("worktree-git-view")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmp"
    for d in (home / ".claude", state, repo, tmp):
        d.mkdir(parents=True)
    (base / "gitconfig").write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    runtime = base / "protected-runtime.json"
    runtime.write_text(json.dumps({"schema_version": 1, **{k: [] for k in REQUIRED_KEYS}}))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "CLAUDE_STATE_DIR": str(state), "GIT_CONFIG_GLOBAL": str(base / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
           "CLAUDE_PROTECTED_RUNTIME_FILE": str(runtime)}
    return {"env": env, "repo": str(repo)}


def run(sandbox, command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "worktree-git-view",
               "cwd": sandbox["repo"], "hook_event_name": "PreToolUse"}
    return subprocess.run(["bash", str(HOOKS / "pretool-bash-safety.sh")], input=json.dumps(payload),
                          capture_output=True, text=True, env=sandbox["env"], cwd=sandbox["repo"], timeout=120)


# Data that names a git subcommand: refused before, passes now.
MUST_PASS = [
    'grep -rn "git stash push" docs/',
    "cat > docs/notes.md <<'EOF'\nBefore switching branches, run git stash\nEOF\n",
    "git restore --staged src/app.py && git show -s --format=%H HEAD && git diff -- docs/",
    "git restore --staged --source=HEAD -- src/",
    "echo Tip: git clean -n previews what would be removed",
    'git commit -m "git stash push docs"',
    "printf '%s\\n' \"git stash push\"",
    "cat > docs/clean.md <<'EOF'\nUse git clean -n to preview\nEOF\n",
]

# Still passes (pinned so the change widens nothing).
STILL_PASS = [
    "python3 -c 'print(1)'",
    'python3 -c \'print("git clean -fdx")\'',
    "git stash list",
    "git stash pop",
    "git checkout HEAD -- src/app.py",
    "git restore --source=HEAD -- src/app.py",
    "git clean -n",
    "git clean -nd",
    "git clean -n --exclude=build",
    "echo $(git clean -n)",
    'python3 -c \'import os; os.system("git clean -n")\'',
]

# (command, the refusal's first-line marker)
STASH = "git stash push/save/create/store"
BARE = "bare 'git stash'"
CHECKOUT = "git checkout <ref> -- ."
RESTORE = "git restore --source=<ref>"
CLEAN = "destructive 'git clean'"
MUST_REFUSE = [
    ("git stash", BARE),
    ("git stash push -u", STASH),
    ("git -C x stash push", STASH),
    ('bash -c "git stash push"', STASH),
    ('eval "git stash push"', STASH),
    ('python3 -c \'import os; os.system("git stash push -u")\'', STASH),
    ("sudo git stash push", STASH),
    ("echo push | xargs git stash", BARE),
    ("git checkout HEAD -- .", CHECKOUT),
    ("git restore --source=HEAD --worktree -- src/", RESTORE),
    ("git restore --source HEAD -- .", RESTORE),
    ("git clean -fd", CLEAN),
    ("sh -c 'git clean -n'", CLEAN),
    ('git rebase -x "git clean -fdx" main', CLEAN),
    ("git submodule foreach git clean -fdx", CLEAN),
    ('echo "git clean -fdx" | sh', CLEAN),
    # Section-5 under-defence: passed the whole pipeline before this change.
    ('eval "git clean -fdx"', CLEAN),
    ('python3 -c \'import os; os.system("git clean -fdx")\'', CLEAN),
    ('node -e \'require("child_process").execSync("git clean -fdx")\'', CLEAN),
    ('python3 -c \'import subprocess; subprocess.run(["git", "clean", "-fdx"])\'', CLEAN),
    ("python3 - <<'EOF'\nimport os\nos.system(\"git clean -fdx\")\nEOF\n", CLEAN),
    ('perl -e \'system("git clean -fdx")\'', CLEAN),
]


@pytest.mark.parametrize("command", MUST_PASS + STILL_PASS)
def test_data_naming_a_git_subcommand_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


@pytest.mark.parametrize("command,marker", MUST_REFUSE)
def test_a_running_git_working_tree_change_is_refused(sandbox, command, marker):
    r = run(sandbox, command)
    assert r.returncode == 2, (command, r.stderr)
    assert marker in r.stderr, (command, r.stderr)
