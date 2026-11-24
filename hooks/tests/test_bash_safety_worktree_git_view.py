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
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
sys.path.insert(0, str(HOOKS))
from lib.runtime_guard.config import REQUIRED_KEYS  # noqa: E402

HANG_GUARD = 900  # seconds: a bound only a hung child reaches; a slow machine must never read as a failure


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


def run_counted(sandbox, command):
    """(result, steps): one run of the hook, and the Python call and return events of every Python process it starts,
    counted by a sitecustomize that the run's PYTHONPATH puts first (each process writes its count at exit). Work is
    counted, never timed: a busy runner changes how long a run takes, not how many steps it takes."""
    with tempfile.TemporaryDirectory(prefix="work-counter-") as counter:
        with open(os.path.join(counter, "sitecustomize.py"), "w", encoding="utf-8") as fh:
            fh.write("import atexit, os, sys\n_n = [0]\n"
                     "def _prof(frame, event, arg):\n    _n[0] += 1\n"
                     "def _dump():\n    sys.setprofile(None)\n"
                     "    with open(os.path.join(os.environ['WORK_COUNT_DIR'], str(os.getpid())), 'w') as fh:\n"
                     "        fh.write(str(_n[0]))\n"
                     "sys.setprofile(_prof)\natexit.register(_dump)\n")
        out = os.path.join(counter, "out")
        os.mkdir(out)
        r = run({**sandbox, "env": {**sandbox["env"], "PYTHONPATH": counter, "WORK_COUNT_DIR": out}}, command)
        steps = 0
        for name in os.listdir(out):
            with open(os.path.join(out, name), encoding="utf-8") as fh:
                steps += int(fh.read())
    return r, steps


def run(sandbox, command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "worktree-git-view",
               "cwd": sandbox["repo"], "hook_event_name": "PreToolUse"}
    return subprocess.run(["bash", str(HOOKS / "pretool-bash-safety.sh")], input=json.dumps(payload),
                          capture_output=True, text=True, env=sandbox["env"], cwd=sandbox["repo"], timeout=HANG_GUARD)


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


# Git global options (with their values) between git and the subcommand in a payload of a shell the parser does
# not read (fish, tcsh) do not hide the subcommand from the quote-neutralised pass.
MUST_REFUSE += [
    ("fish -c 'git -C x stash'", STASH),
    ('fish -c "git -C x stash"', STASH),
    ("fish -c 'git -C x stash push'", STASH),
    ("fish -c 'git -C x stash -u'", STASH),
    ("fish -c 'git --no-pager stash'", STASH),
    ("fish -c 'git -c core.pager=cat stash push'", STASH),
    ("fish -c 'git -C x checkout HEAD -- .'", CHECKOUT),
    ("fish -c 'git -C x restore --source=HEAD -- src/'", RESTORE),
    ("tcsh -c 'git -C x stash'", STASH),
]

# The same pass with other global-option spellings, shells and command positions, and safe subcommands behind the
# options, which keep passing.
MUST_REFUSE += [
    ("fish -c 'git --git-dir=.git stash'", STASH),
    ("fish -c 'git --work-tree x stash push'", STASH),
    ("fish -c 'git -P stash'", STASH),
    ("zsh -c 'git -C x stash'", STASH),
    ("ksh -c 'git -C x stash'", STASH),
    ("csh -c 'git -C x stash'", STASH),
    ("/usr/bin/fish -c 'git -C x stash'", STASH),
    ("fish -c 'cd y && git -C x stash'", STASH),
]
STILL_PASS += [
    "fish -c 'git -C x stash list'",
    "fish -c 'git --no-pager stash show'",
    "fish -c 'git -C x log --oneline'",
    "fish -c 'git -C x checkout -- src/app.py'",
    "tcsh -c 'git -C x stash pop'",
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


# The quote-neutralised pass scans git global options only from a `git` that starts a word, never again from a `git`
# inside an option run it already walked: a long run of option words holding `git` (-Pgit, a=bgit) costs linear time.
# Twice the run must cost well under four times as much, the two compared with each other in steps counted (as below).
@pytest.mark.parametrize("option,count,tail", [(" -Pgit", 10000, " !"), (" -c a=bgit", 5000, "")],
                         ids=["Pgit-x10000", "c-abgit-x5000"])
def test_quote_neutralised_option_scan_is_linear(option, count, tail):
    _, large = _option_scan_work("git" + option * count + tail)
    _, small = _option_scan_work("git" + option * (count // 2) + tail)
    assert large < 2.5 * small, (small, large)


def test_shell_payload_with_long_option_run_is_fast(sandbox):
    """Through the real hook: above the hook's fixed work (a one-option payload), 6000 options take well under
    sixteen times the steps 1500 do (linear: four times; a scan that walks the run again from every option: sixteen)."""
    def work(count):
        r, steps = run_counted(sandbox, "fish -c 'git" + " -Pgit" * count + "'")
        assert r.returncode in (0, 2), r.stderr
        return steps

    fixed, quarter, full = work(1), work(1500), work(6000)
    assert full - fixed < 8 * max(quarter - fixed, 1), (fixed, quarter, full)


# The option run between git and the subcommand has no length cap: a stash behind any number of global options in a
# shell payload is refused, as the classifier view of the lane head refused it (each case through the real hook).
LONG_OPTION_RUNS = [
    ("P-x33", "fish -c 'git" + " -P" * 33 + " stash'", STASH),
    ("C-a-x33", "fish -c 'git" + " -C a" * 33 + " stash'", STASH),
    ("c-ab-x40-push", "fish -c 'git" + " -c a=b" * 40 + " stash push'", STASH),
    ("c-ab-50KB", "fish -c 'git" + " -c a=b" * 7200 + " stash'", STASH),
    ("Pgit-x3000", "fish -c 'git" + " -Pgit" * 3000 + " stash'", STASH),
    ("c-abgit-x3000", "fish -c 'git" + " -c a=bgit" * 3000 + " stash'", STASH),
    ("C-git-x2000", "fish -c 'git" + " -C git" * 2000 + " stash'", STASH),
    ("checkout-x40", "fish -c 'git" + " -C a" * 40 + " checkout HEAD -- .'", CHECKOUT),
    ("restore-x40", "fish -c 'git" + " -P" * 40 + " restore --source=HEAD -- src/'", RESTORE),
]


@pytest.mark.parametrize("command,marker", [(c, m) for _i, c, m in LONG_OPTION_RUNS],
                         ids=[i for i, _c, _m in LONG_OPTION_RUNS])
def test_long_global_option_run_before_the_subcommand_is_refused(sandbox, command, marker):
    r = run(sandbox, command)
    assert r.returncode == 2, r.stderr[-300:]
    assert marker in r.stderr, r.stderr[-300:]


@pytest.mark.parametrize("command", ["fish -c 'git" + " -P" * 33 + " stash list'",
                                     "fish -c 'git" + " -c a=b" * 40 + " stash show'",
                                     "fish -c 'git" + " -Pgit" * 3000 + "'",
                                     "fish -c 'git" + " -c a=bgit" * 3000 + "'"],
                         ids=["P-x33-list", "c-ab-x40-show", "Pgit-x3000-no-sub", "c-abgit-x3000-no-sub"])
def test_long_global_option_run_before_a_safe_or_no_subcommand_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, r.stderr[-300:]


def _option_scan_work(command):
    """(result, steps) of one quote-neutralised scan of command: the Python calls and returns it makes, counted, not
    timed (a busy runner changes how long a scan takes, never how many steps)."""
    from lib.bash_safety_rules import _worktree_raw_fallback
    steps = [0]

    def count(frame, event, arg):
        steps[0] += 1
    before = sys.getprofile()
    sys.setprofile(count)
    try:
        got = _worktree_raw_fallback(command.replace("'", " "), globals_=True)
    finally:
        sys.setprofile(before)
    return got, steps[0]


# Twice the options must cost well under four times as much (a scan that walks the run again from every option grows
# with its square). The two scans are compared with each other, in steps counted: a clock would only measure the runner.
@pytest.mark.parametrize("head,option,count,tail,hit", [("git", " -C git", 10000, "", None),
                                                        ("fish -c 'git", " -C git", 10000, "'", None),
                                                        ("git", " -P", 20000, " stash", "bare"),
                                                        ("fish -c 'git", " -P", 20000, " stash'", "bare")],
                         ids=["C-git-x10000", "fish-C-git-x10000", "P-x20000-stash", "fish-P-x20000-stash"])
def test_uncapped_option_scan_is_linear(head, option, count, tail, hit):
    got, large = _option_scan_work(head + option * count + tail)
    _, small = _option_scan_work(head + option * (count // 2) + tail)
    assert large < 2.5 * small, (small, large)
    assert [k for k, v in got.items() if v] == ([hit] if hit else [])


def test_shell_payload_with_a_very_long_option_run_is_refused_fast(sandbox):
    steps = {}
    for options in (10000, 20000):
        r, steps[options] = run_counted(sandbox, "fish -c 'git" + " -P" * options + " stash'")
        assert r.returncode == 2 and STASH in r.stderr, r.stderr[-300:]
    # The re-lex this guards against grew with the square of the run (10.6 s for 20,000 options, N6); resolved, the
    # work grows with its length. Twice the options must take well under four times the steps (linear: twice). The two
    # runs are compared with each other, in steps counted: no clock holds on every runner.
    assert steps[20000] < 3 * steps[10000], steps
