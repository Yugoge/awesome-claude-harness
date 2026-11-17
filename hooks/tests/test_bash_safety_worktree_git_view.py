"""The working-tree git rules of lib/bash_safety_rules.py (git stash, wide checkout, restore from a ref, git clean)
judge the git invocations lib/shell_parse.py finds, not the raw text: a git subcommand named in data passes, one
that runs (past wrappers, in a shell payload, in interpreter code that spawns it) is refused. The data lift holds
only inside the strict data shape (bash_safety_rules.data_shape); data handed on to a shell, interpreter, xargs, tee,
at, crontab, make or a written script keeps the base refusal, and so does a command that writes a hook location or
any file beside a git command (a hook it plants would fire) or whose git grep runs a pager.

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
    "cat <<'EOF'\ngit clean -fdx\nEOF\n",
    "cat > docs/notes.md <<'EOF'\nrun git stash before you switch\nEOF\n",
    "cat > ./docs/notes.md <<'EOF'\nrun git stash before you switch\nEOF\n",
    "git commit -F - <<'EOF'\navoid git stash\nEOF\n",
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
    # Data handed on to something that runs it: outside the strict data shape, so the base refusal stands.
    ("printf '%s\\n' \"git clean -fdx\" | bash", CLEAN),
    ('echo "git clean -fdx" > x.sh && bash x.sh', CLEAN),
    ("echo git clean -fdx > x.sh; sh x.sh", CLEAN),
    ('echo "git stash -u" > x.sh && bash x.sh', STASH),
    ('grep -e "git clean -fdx" notes.txt | sh', CLEAN),
    ('rg -o "git clean -fdx" f | sh', CLEAN),
    ("cat > x.sh <<'EOF'\ngit clean -fdx\nEOF\nbash x.sh", CLEAN),
    ("cat > x.sh <<'EOF'\ngit stash\nEOF\nbash x.sh", BARE),
    ("echo git clean -fdx | cat | sh", CLEAN),
    ("echo git clean -fdx | tee /dev/stderr | sh", CLEAN),
    ("echo git clean -fdx > /tmp/c && sh < /tmp/c", CLEAN),
    ("echo git clean -fdx | python3 -c 'import os,sys; os.system(sys.stdin.read())'", CLEAN),
    ("echo git clean -fdx | at now", CLEAN),
    ("echo git clean -fdx | batch", CLEAN),
    ("echo '* * * * * git clean -fdx' | crontab -", CLEAN),
    ("echo git stash | at now", BARE),
    ("echo git clean -fdx >> ~/.bashrc", CLEAN),
    ("make -f /dev/stdin <<'EOF'\nall:\n\tgit clean -fdx\nEOF\n", CLEAN),
    ("echo 'exec git clean -fdx' | tclsh", CLEAN),
    ("tclsh <<'EOF'\nexec git stash\nEOF\n", BARE),
    ("echo git stash | xargs -I{} sh -c '{}'", BARE),
    ("git bisect run git stash", BARE),
    ("fish -c 'git stash'", STASH),
    ('sh -c "$(echo git clean -fdx)"', CLEAN),
    ("cat > .git/hooks/pre-commit <<'EOF'\ngit clean -fdx\nEOF\ngit commit -m x", CLEAN),
    ("cat > notes.md <<'EOF'\ngit stash\nEOF\ngit -c alias.x='!sh notes.md' x", BARE),
    ("printf 'run git clean -fdx\\n' >> notes.md", CLEAN),
    ("tee notes.md <<'EOF'\ngit clean -fdx wipes\nEOF\n", CLEAN),
    # A git clean named in a commit message is still refused (only stash/checkout/restore text is lifted there).
    ('git commit -m "run git clean -fdx first"', CLEAN),
] + [
    # Round 2: git grep runs its pager option's value (any --o... abbreviation, or O in a short cluster).
    ("git grep --open-files-in-pager=\"sh -c 'git stash -u'\" a", STASH),
    ("git grep --open-files=\"sh -c 'git stash -u'\" a", STASH),
    ("git grep --open=\"sh -c 'git stash -u'\" a", STASH),
    ("git grep -iO\"sh -c 'git stash -u'\" a", STASH),
    ("git grep -O\"sh -c 'git stash -u'\" a", STASH),
    ("git grep --open=\"sh -c 'git clean -fdx'\" a", CLEAN),
    ("git grep -iO\"sh -c 'git clean -fdx'\" a", CLEAN),
    # Round 2: a hook written by the command, then fired by a git command in it.
    ("cat > .husky/post-checkout <<'EOF'\ngit stash -u\nEOF\ngit checkout -q HEAD", STASH),
    ("cat > .husky/pre-commit <<'EOF'\ngit stash -u\nEOF\ngit commit -qm x", STASH),
    ("cat > .pre-commit-config.yaml <<'EOF'\nrepos:\n- repo: local\n  hooks:\n  - id: x\n    entry: git stash -u\n"
     "EOF\ngit commit -qm x", STASH),
    ("cat > .git/hooks/post-checkout <<'EOF'\ngit stash -u\nEOF\ngit checkout -q HEAD", STASH),
    ("cat > tools/post-checkout <<'EOF'\ngit stash -u\nEOF\ngit checkout -q HEAD", STASH),
    ("cat > docs/notes.md <<'EOF'\ngit stash -u\nEOF\ngit commit -qm x", STASH),
    ("cat > bare.git/config <<'EOF'\n[core]\n\tpager = sh -c 'git stash -u'\nEOF\n", STASH),
    ("cat > sub/config <<'EOF'\n[core]\n\tpager = sh -c 'git stash -u'\nEOF\n", STASH),
    ("cat > .ackrc <<'EOF'\n--pager=sh -c 'git stash -u'\nEOF\nack a", STASH),
    ("cat > .vscode/tasks.json <<'EOF'\n{\"tasks\":[{\"command\":\"git stash -u\"}]}\nEOF\n", STASH),
    ("cat > .github/workflows/x.yml <<'EOF'\nrun: git stash -u\nEOF\n", STASH),
    ("cat > package.json <<'EOF'\n{\"scripts\":{\"precommit\":\"git stash -u\"}}\nEOF\n", STASH),
    ("cat > lefthook.yml <<'EOF'\npre-commit:\n  commands:\n    s:\n      run: git stash -u\nEOF\n", STASH),
    ("cat > .husky/pre-commit <<'EOF'\ngit clean -fdx\nEOF\ngit commit -qm x", CLEAN),
    ("git log -1 --format='tformat:git stash -u' --output=.git/hooks/post-checkout && git checkout -q HEAD", STASH),
    ("git log -1 --format='tformat:git stash -u' --outp=.git/hooks/post-checkout && git checkout -q HEAD", STASH),
    ("git log -1 --format='tformat:git stash -u' --out=.git/hooks/pre-commit && git commit -qm x", STASH),
    ("git show -s --format='git stash -u' --ou=.git/hooks/pre-commit HEAD && git commit -qm x", STASH),
    ("echo 'git stash -u' | uniq - .git/hooks/post-checkout && git checkout -q HEAD", STASH),
    ("echo 'git stash -u' | uniq - .git/hooks/pre-commit && git commit -qm x", STASH),
    ("echo 'git stash -u' | sort -o .git/hooks/pre-commit && git commit -qm x", STASH),
    ("echo 'git stash -u' | sort -uo.git/hooks/pre-commit && git commit -qm x", STASH),
    ("echo 'git stash -u' | sort --outp=.git/hooks/pre-commit && git commit -qm x", STASH),
    ("echo 'git stash -u' | sort --o .git/hooks/pre-commit && git commit -qm x", STASH),
] + [
    # Round 4: an option alone before `--` with a wide path overwrites the tree or its conflict resolutions.
    (f"git checkout {opt} -- {path}", CHECKOUT)
    for opt, path in [("--ours", "."), ("--theirs", "."), ("-m", "."), ("--merge", "."), ("--conflict=diff3", "."),
                      ("-f", "."), ("-p", "."), ("--no-overlay", "."), ("--ignore-skip-worktree-bits", "."),
                      ("--theirs", "src/"), ("-f", "src/"), ("--force", "*"), ("-q", "."), ("--patch", "."),
                      ("--conflict=merge", "src/")]
] + [
    ("git status && git checkout --ours -- .", CHECKOUT),
    ('echo "see git stash"; git checkout --theirs -- .', CHECKOUT),
    ("git checkout -m -- . | head", CHECKOUT),
    ("git checkout HEAD -- *", CHECKOUT),
    # Round 4: ack/ag take any unique abbreviation of a long option; only listed options stay in the data shape.
    ("ack --pag=\"sh -c 'git stash -u'\" a", STASH),
    ("ack --pa=\"sh -c 'git stash -u'\" a", STASH),
    ("ag --pag \"sh -c 'git stash -u'\" a", STASH),
    ("ag --pa=\"sh -c 'git stash -u'\" a", STASH),
    ('ag --pa=less "git stash push" docs/', STASH),
    ('ack --ackrc=x.rc "git stash push" docs/', STASH),
    ('ack --ackr=x.rc "git stash push" docs/', STASH),
]

# Round 4: the plain checkout of a wide path and listed ack/ag options keep passing.
STILL_PASS += [
    "git checkout -- .",
    "git checkout -- src/",
    "git checkout --ours -- src/app.py",
    'ack -i --type=md "git stash push" docs/',
    'ag -i "git stash push" docs/',
    'ack -A 3 "git stash" docs',
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
