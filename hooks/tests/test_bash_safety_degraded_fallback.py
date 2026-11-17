"""The removal policy's degraded fallback (lib/bash_safety_rules.py::removal_policy) on a line ending in an option.

When the execution-boundary analyzer gives no verdict (timeout, memory ceiling, crash) the fallback once refused every
line ending on an option, which refused 143 of the everyday commands below (`git status --short`, `date -u`,
`python3 --version`). A trailing option is now plain unless a command of that line names a shell, an interpreter, an
exec wrapper or a removal program (degraded_trailing_option_is_plain). Every form whose missing operand is the danger,
every removal and every assembly channel stays refused. The refusal set is read from the analyzer's own tables, and
a generated differential pins that the fallback is never laxer than the live analyzer. All hook runs use a throwaway
HOME and global git config.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
HOOK = os.path.join(HOOKS_DIR, "pretool-bash-safety.sh")
sys.path.insert(0, os.path.join(HOOKS_DIR, "lib"))

import bash_execution_boundary as eb  # noqa: E402
import bash_safety_rules as R  # noqa: E402
from shell_parse import WRAPPERS  # noqa: E402

DEGRADED = "removal-policy FAIL-CLOSED"
MODES = {"timeout": {"CLAUDE_HOOK_BOUNDARY_TIMEOUT": "0.001s"}, "memory": {"CLAUDE_HOOK_BOUNDARY_MEM_KB": "4096"}}

# Everyday commands ending on an ordinary option, none naming a removal or an assembly channel.
EVERYDAY_TRAILING_OPTION = [
    "git status --short", "git status -s", "git status -sb", "git log --oneline", "git log --oneline -5",
    "git log -1", "git log --graph --oneline --all", "git log -n 3 --stat", "git diff --stat", "git diff --cached",
    "git diff --name-only", "git diff HEAD~1 --stat", "git show --stat", "git branch -a", "git branch -vv",
    "git branch --show-current", "git remote -v", "git fetch --all", "git fetch origin --prune",
    "git rev-parse --show-toplevel", "git describe --tags", "git tag -l", "git tag --list", "git config --list",
    "git shortlog -sn", "git ls-files -m", "git ls-files --others", "git reflog -5", "git cherry -v",
    "git log --since=yesterday --oneline", "git diff --check", "git count-objects -v", "git fsck --no-progress",
    "git --version", "git log --format=%H -1", "git add -A", "git commit --amend --no-edit", "git pull --rebase",
    "git pull --ff-only", "git log --author=me --oneline", "git diff main...HEAD --stat", "ls -la", "ls -l",
    "ls -a", "ls -lh", "ls -1", "ls -R", "ls -lt", "ls src -la", "ls --color=auto", "ls -ltr", "pwd -P", "id -u",
    "hostname -f", "uname -a", "uname -r", "uname -m", "date -u", "date -I", "date --iso-8601=seconds", "date -R",
    "uptime -p", "free -h", "free -m", "df -h", "du -h --max-depth=1", "nproc --all", "top -bn1", "ps -ef",
    "stty -a", "ulimit -a", "wc -l", "grep -n foo file -r", "grep foo file.txt -i", "grep -w foo -R", "rg --files",
    "rg foo --hidden", "rg --type-list", "find . -empty", "find . -size +1M", "find . -mtime -1",
    "find . -name foo -ls", "tree -a", "tree src -d", "uniq -c", "jq -c", "python3 --version", "python3 -V",
    "python --version", "python3 -m pytest -q", "python3 -m pytest -x", "python3 -m pytest tests -v",
    "python3 -m pip --version", "pip --version", "pytest -q", "pytest -x", "pytest -v", "pytest --co -q",
    "ruff check src --fix", "ruff format --check", "cargo --version", "cargo build --release", "cargo fmt --check",
    "rustc --version", "java -version", "javac -version", "mvn -v", "make -j4", "make -n", "cmake --version",
    "gcc --version", "clang --version", "docker ps -a", "docker compose up -d", "docker stats --no-stream",
    "kubectl get pods -A", "kubectl version --client", "terraform fmt -check", "aws --version", "gcloud --version",
    "gh --version", "ss -tlnp", "netstat -tlnp", "set -e", "set -x", "set +x", "hash -r", "ls --help",
    "git --help", "bc -l", "psql -l", "mysql --version", "ssh -V", "ssh-add -l", "gpg --list-keys", "base64 -d",
    "git status --short && git diff --stat", "git log --oneline | head -5", "cd src && ls -la",
    "git diff | head -50", "history | tail -20", "git log -p -1", "sort file.txt | uniq -c | sort -rn",
]

# Forms the degraded fallback must keep refusing: removals, assembly channels, and the structurally incomplete forms
# whose missing operand is the danger, each also behind a wrapper, an assignment, a path, quoting or another command.
STILL_REFUSED = [
    "rm -rf build", "rm build -rf", "rm -rf", "/bin/rm x -f", "unlink -x", "rmdir d -p", "shred x -u",
    "git clean -fdx", "git clean -n", "git -C . clean -f", "git rm -r --cached x -f", "rsync -a src/ dst/ --delete",
    "find . -name x -exec", "find . -name x -delete", "find . -name x -execdir", "find . -name x -ok",
    "truncate f -s", "dd if=a of=b -x", "xargs -0", "ls | xargs -r", "sudo -s", "sudo ls -l", "doas -s",
    "bash -c", "sh -c", "zsh -c", "dash -c", "bash -lc", "bash -s", "sh -", "/bin/bash -c", "\"bash\" -c",
    "b\\ash -c", "ba''sh -c", "FOO=1 bash -c", "nice -n 5 bash -c", "timeout 5 sh -c", "command -p sh -c",
    "exec -a x sh -c", "docker run img sh -c", "ls -la; bash -c", "bash -c; ls -la", "git status && bash -c",
    "env -S", "env --split-string", "env -i", "env FOO=1 -S", "python3 -c", "python3 -", "python3 -m code -i x -c",
    "perl -e", "ruby -e", "awk -f", "sed -i", "eval --", "eval echo -n", "source -x", ". -x", "npx -c",
    "echo >", "echo hi |", "ls &&", "ls ;", "cat <", "x=rm; $x -r", "$(echo rm) -rf", "`echo rm` -rf",
    "$X -r", "${X} -r", "r${E}m -rf", "eval \"$X\" -n", "ls -la \\", "cat <<EOF -n", "ls {a,b} -l",
    "ls * -l", "bash -c 'echo' -x", "grep foo 'unterminated -n",
]


# Refused by the live analyzer (missing_option_value) and, before the table-derived rule, allowed by the fallback.
ANALYZER_REFUSED_EXEC_OPTIONS = [
    "sg wheel -c", "chpst -u", "man -P", "man --pager", "man -B", "man -H", "man --browser", "man --html",
    "rg --pre", "rg --hostname-bin", "ack --pager", "ag --pager", "apropos -P", "apropos --pager", "whatis -P",
    "whatis --pager", "compgen -C", "compgen -F", "diff3 --diff-program", "sdiff --diff-program",
    "sort --compress-program", "split --filter", "ugrep --filter", "ugrep --pager", "grep -e", "rg -e",
    "git -c", "git -C", "docker run -v", "watch -n", "flock -w", "nice -n", "timeout -s", "sudo -u", "env -u",
]

# A quoted or escaped word holding a space (a head that is a command line, or an argument some program runs as one),
# and an option that ends a command before a redirection, a comment or a parenthesis.
SHELL_STRING_WORDS = [
    "docker create -l 2>/dev/null", "xargs -d >x", "/usr/bin/docker --host # c", "(xargs -d)", "rg x --max-count''",
    "hyperfine 'grep -f' -N 2>/dev/null",
    "hyperfine 'bash -c' -N", "tmux new -d 'sh -c' -x", "fzf --preview 'bash -c' -m", "nodemon --exec 'env -S' -q",
    "foo --pager 'sh -c' -x", "ssh-agent 'bash -c' -x", "bash\\ -c", "\"bash -c\" -x", "env\\ -S", "'sh -c' -s",
    "sh\\ -c -x", "\"git -C\" . difftool x -n -x", "\"/usr/bin/sudo --close-from\" -x", "nsenter\\ -t", "\"rg -r\" -x",
    "\"xargs -0\" -x", "x 'a \"bash -c\"' -x", "x -d 'ls; sh -c' -x", "PAGER='sh -c' man ls -a", "PAGER=/bin/sh man ls -a",
]


# A non-plain line beside a line ending on an ordinary option (\n is a real newline).
MULTILINE_NEIGHBOURS = [
    "r''m -rf x\nls -l", "ls -l\nr''m -rf x", "\"r\"m -rf x\ngit status --short", "r\\m -rf x\ndate -u",
    "un''link x\nls -l", "sh''red x\nls -l", "python3 -c 'import os; getattr(os,\"un\"+\"link\")(\"x\")'\nls -l",
    "hyperfine 'bash -c'\nls -l", "ls -l\nhyperfine 'bash -c'", "hyperfine 'bash -c'\n-N",
    "x --pager 'sh -c'\ngit status --short", "r''m -rf x\n\nls -l", "r''m -rf x\r\nls -l",
    "kubectl x -- find /dev/shm/vtest/sub -de''lete -print", "kubectl -- find /dev/shm/vtest/sub -de\"\"lete -q",
    "kubectl x -- find /dev/shm/vtest/sub -de''lete\nls -l", "ls -l\nkubectl x -- find /dev/shm/vtest/sub -de\\lete",
    "kubectl x -- kubectl y -- find /dev/shm/vtest/sub -de''lete -print", "kubectl -- ssh h find /x -de''lete -v",
]


# Degraded-only refusals the live analyzer does not make: unmodelled shells, interpreters and wrappers, a `-c
# key=value` or `--to-command=` naming a shell, g-prefixed removal programs, and python -m on a code-running package.
DEGRADED_ONLY_REFUSED = [
    "pwsh -c", "oksh -c", "osh -c", "ysh -c", "xonsh -c", "elvish -c", "nu -c", "rc -c", "R -e", "vim -c",
    "nvim -c", "ex -c", "emacs --eval", "guile -c", "racket -e", "sbcl --eval", "elixir -e", "erl -eval", "qjs -e",
    "octave --eval", "gnuplot -e", "cmake -P", "groovy -e", "scala -e", "clojure -e", "lldb -o", "pkexec -u",
    "unbuffer -p", "fd foo -x", "fd foo --exec", "nix develop -c", "xterm -e", "entr -s",
    "git -c core.pager=sh log -1", "git -c core.pager=/bin/bash log --oneline", "tar --to-command=sh -x",
    "grm x -f", "gunlink x -v", "gshred x -u", "gtruncate x -s", "grmdir d -p", "cmake -E remove_directory d -v",
    "cmake -E remove x -v", "python3 -m code.interact -i", "python3 -m pdb.x -c", "python3 -m runpy.foo -x",
]


def analyzer_corpus():
    """Every analyzer-known program with each declared and each common option ending the line, in several shapes."""
    common = ("-c -e -E -p -x -X -s -S -u -n -o -f -i -C -P -B -H -F -a -t -w -k -m -r -v -V -l -d -h -I -T -0 - -- "
              "--help --version --exec --eval --pager --filter --command --to-command --pre --browser --html").split()
    progs = {}
    for p, m in eb.INERT_ARGV_CONSUMERS.items():
        progs.setdefault(p, set()).update(m["bool"] | m["exec"] | m["val"])
    for p, v in WRAPPERS.items():
        progs.setdefault(p, set()).update((v[0]["bool"] | v[0]["val"]) if v else ())
    for p in eb.SHELLS:
        progs.setdefault(p, set()).update({"-" + c for c in eb.SHELL_SHORT_BOOL} | eb.SHELL_LONG_BOOL
                                          | eb.SHELL_LONG_VAL)
    for p, flags in eb.INTERPRETERS.items():
        progs.setdefault(p, set()).update(flags)
    for p in eb.AWKS:
        progs.setdefault(p, set()).update(("-f", "--file", "-v", "--assign", "-F"))
    for n in dir(eb.Analyzer):
        if n.startswith("_h_"):
            progs.setdefault(n[3:].replace("_", "-"), set())
    for p, opts in eb.SELECTOR_DATA_OPTIONS.items():
        progs.setdefault(p, set()).update(opts)
    for p in eb.REMOVAL_EXES:
        progs.setdefault(p, set())
    progs.setdefault("git", set()).update(eb.GIT_GLOBAL["bool"] | eb.GIT_GLOBAL["val"])
    progs.setdefault("docker", set()).update(eb.DOCKER_GLOBAL["bool"] | eb.DOCKER_GLOBAL["val"])
    cmds = set(ANALYZER_REFUSED_EXEC_OPTIONS)
    for p, opts in progs.items():
        for o in opts | set(common):
            cmds.update((f"{p} {o}", f"{p} x {o}", f"/usr/bin/{p} {o}", f"ls -la; {p} {o}", f"FOO=1 {p} x {o}"))
    # A quoted or escaped head holding a space, and an argument that is a shell string another program may run.
    for p, opts in progs.items():
        for o in sorted(opts | {"-c", "-e", "-S", "-x"}):
            cmds.update((f"'{p} {o}' -x", f"{p}\\ {o}", f"\"/usr/bin/{p} {o}\" -x", f"hyperfine '{p} {o}' -N",
                         f"x --pager '{p} {o}' -x", f"x -d 'y; {p} {o}' -x", f"X='{p} {o}' ls -l"))
        # The option ends the command, not the line: before a redirection, a comment or a parenthesis, or quoted.
        for o in opts | {"-c", "-e", "-S"}:
            cmds.update((f"{p} {o} 2>/dev/null", f"{p} {o} >x", f"{p} {o} # c", f"({p} {o})", f"{p} {o}''",
                         f"{p} '{o}'"))
    # A command on another line: a newline separates commands, so the plain line beside it must not carry it.
    stems = {"r''m -rf x", "\"r\"m -rf x", "r\\m -rf x", "un''link x", "sh''red x", "hyperfine 'bash -c'",
             "x --pager 'sh -c'", "python3 -c 'import os; getattr(os,\"un\"+\"link\")(\"x\")'"}
    for p, opts in progs.items():
        for o in opts | {"-c", "-e", "-S"}:
            stems.update((f"{p} {o}", f"hyperfine '{p} {o}'", f"{p}''"))
    for stem in stems:
        for other in ("ls -l", "git status --short"):
            cmds.update((f"{stem}\n{other}", f"{other}\n{stem}", f"{stem}\n\n{other}", f"{stem}\r\n{other}",
                         f"{other}\r\n{stem}", f"{stem} \\\n{other}"))
    # Forwarded commands: positions the analyzer evaluates as a command of their own (kubectl `--`, docker
    # run/exec, ssh's remote command, a read-handler word past the head), alone and beside an ordinary line.
    payloads = {"find /x -de''lete -print", "find /x -de\\lete", "r''m -rf x", "ssh h find /x -de''lete -v",
                "kubectl y -- find /x -de''lete -q", "git -c alias.l=r''m l x -q"}
    for p, opts in progs.items():
        for o in opts | {"-c", "-e", "-S"}:
            payloads.add(f"{p} {o}")
    for f in payloads:
        for fwd in (f"kubectl -- {f}", f"kubectl x -- {f}", f"docker run img {f}", f"docker exec c {f}",
                    f"ssh h {f}", f"x {f}", f"ls -l {f}"):
            # Alone only when it ends on an option: a single line that does not is the fallback's accepted gap.
            cmds.update(([fwd] if f.split()[-1][:1] in "-+" else []) + [f"{fwd} -q", f"{fwd}\nls -l", f"ls -l\n{fwd}"])
    for sub in eb.GIT_SUBCOMMANDS:
        for o in set(common) | set(eb.GIT_DATA_OPTIONS):
            cmds.update((f"git {sub} {o}", f"git -C . {sub} x {o}"))
    for sub in "run exec create ps images logs build compose container image volume network system inspect".split():
        for o in set(common) | eb.DOCKER_RUN["bool"] | eb.DOCKER_RUN["val"] | eb.DOCKER_EXEC["val"]:
            cmds.update((f"docker {sub} {o}", f"docker {sub} img {o}"))
    for sub in "get exec logs describe run apply delete debug attach cp".split():
        for o in common:
            cmds.update((f"kubectl {sub} {o}", f"kubectl {sub} pod {o}"))
    return sorted(cmds)


def _rmref():
    with open(os.path.join(HOOKS_DIR, "lib", "pol_degraded_removal_reference.ere"), encoding="utf-8") as fh:
        return next(ln.strip() for ln in fh if ln.strip() and not ln.startswith("#"))


def test_degraded_fallback_is_never_laxer_than_the_live_analyzer():
    rmref = _rmref()
    corpus = analyzer_corpus()
    refused = [c for c in corpus if not eb.analyze(c)["allowed"]]
    assert len(corpus) > 80000 and len(refused) > 1000, (len(corpus), len(refused))
    laxer = [c for c in refused if not R.degraded_refuses(c, rmref)]
    assert not laxer, "%d analyzer-refused forms pass the degraded fallback: %r" % (len(laxer), laxer[:20])


@pytest.mark.parametrize("command", ANALYZER_REFUSED_EXEC_OPTIONS + DEGRADED_ONLY_REFUSED + SHELL_STRING_WORDS
                         + MULTILINE_NEIGHBOURS)
def test_exec_option_and_unmodelled_program_forms_refuse_in_degraded_mode(command):
    assert R.degraded_refuses(command, _rmref()), command


@pytest.mark.parametrize("mode", sorted(MODES))
def test_analyzer_refused_exec_options_refuse_end_to_end(mode):
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda c: (c, *run_hook(c, **MODES[mode])),
                              ANALYZER_REFUSED_EXEC_OPTIONS + SHELL_STRING_WORDS))
    allowed = [c for c, code, _err in results if code != 2]
    assert not allowed, (mode, allowed)


@pytest.mark.parametrize("mode", ["timeout", "memory", "crash"])
def test_multiline_neighbours_refuse_end_to_end(mode, tmp_path):
    hook = None
    env = MODES.get(mode, {})
    if mode == "crash":
        dst = tmp_path / "hooks"
        shutil.copytree(HOOKS_DIR, str(dst), ignore=shutil.ignore_patterns("tests", "__pycache__"))
        analyzer = dst / "lib" / "bash_execution_boundary.py"
        src = analyzer.read_text(encoding="utf-8")
        # The tables stay importable; only running the analyzer crashes.
        analyzer.write_text(src.replace('if __name__ == "__main__":', 'if __name__ == "__main__":\n    sys.exit(3)'),
                            encoding="utf-8")
        hook = str(dst / "pretool-bash-safety.sh")
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda c: (c, *run_hook(c, hook=hook, **env)), MULTILINE_NEIGHBOURS))
    allowed = [c for c, code, _err in results if code != 2]
    assert not allowed, (mode, allowed)


@pytest.mark.parametrize("body", [None, "import sys\nsys.exit(0)\n", "raise RuntimeError('x')\n",
                                  "import time\ntime.sleep(30)\n"])
def test_unimportable_analyzer_tables_refuse_every_trailing_option(tmp_path, body):
    """No tables, no proof: an analyzer module that is absent, exits, raises or hangs on import refuses the line."""
    dst = tmp_path / "hooks"
    shutil.copytree(HOOKS_DIR, str(dst), ignore=shutil.ignore_patterns("tests", "__pycache__"))
    target = dst / "lib" / "bash_execution_boundary.py"
    if body is None:
        target.unlink()
    else:
        target.write_text(body, encoding="utf-8")
    code, err = run_hook("git status --short", hook=str(dst / "pretool-bash-safety.sh"),
                         CLAUDE_HOOK_BOUNDARY_TIMEOUT="1s")
    assert code == 2 and DEGRADED in err, err


def run_hook(command, hook=None, **env_extra):
    home = tempfile.mkdtemp(prefix="degraded-home-")
    gitconfig = os.path.join(home, "gitconfig")
    open(gitconfig, "w").close()
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=home, GIT_CONFIG_GLOBAL=gitconfig, **env_extra)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    p = subprocess.run(["bash", hook or HOOK], input=payload, capture_output=True, text=True, cwd=home, env=env)
    return p.returncode, p.stderr


@pytest.mark.parametrize("mode", sorted(MODES))
def test_everyday_trailing_options_pass_the_degraded_fallback(mode):
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda c: (c, *run_hook(c, **MODES[mode])), EVERYDAY_TRAILING_OPTION))
    refused = [(c, err.splitlines()[:1]) for c, code, err in results if code != 0]
    assert not refused, "%d of %d refused under %s: %r" % (len(refused), len(results), mode, refused[:10])


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("command", STILL_REFUSED)
def test_dangerous_neighbours_stay_refused_in_degraded_mode(mode, command):
    code, err = run_hook(command, **MODES[mode])
    assert code == 2, "%s allowed %r" % (mode, command)
    assert err.strip()


def test_the_lifted_corpus_is_exactly_what_question_3_refused():
    """Every corpus line ends on an option, so the old rule refused each one; only the new predicate admits it."""
    for command in EVERYDAY_TRAILING_OPTION:
        assert R.DEGRADED_TRAILING_OPTION.search(command), command
        assert R.degraded_trailing_option_is_plain(command), command


@pytest.mark.parametrize("line", [
    "bash -c", "env -S", "nice bash -c", "xargs -0", "python3 -c", "git clean -f", "find . -exec", "sudo -i",
    "ls -la; sh -s", "grep 'x -n", "ls -l >", "rm -f",
])
def test_predicate_refuses_sensitive_lines(line):
    assert not R.degraded_trailing_option_is_plain(line)


@pytest.mark.parametrize("line", [
    "git commit -m 'fix the bug' --amend", "grep -n 'foo bar' file -r", "bash --version",
    "kubectl x -- ls -la", "grep -rn find src -i", "python3 -V", "python3 -m pytest -q", "git status --short", "ls -la | grep x -i",
    "FOO=1 make -n", "make 2>&1 -j4",
])
def test_predicate_admits_plain_lines(line):
    assert R.degraded_trailing_option_is_plain(line)


@pytest.mark.parametrize("command", [
    "kubectl get pods -A\nkubectl get svc -n x", "git status --short\ngit log --oneline -5", "ls -la\n\ndate -u",
    "cd src && ls -la\npython3 -m pytest -q", "git status --short\nfind . -name x -ls",
])
def test_multiline_everyday_scripts_stay_allowed(command):
    assert not R.degraded_refuses(command, _rmref()), command


def test_analyzer_timeout_default_leaves_headroom_under_load():
    """15 s: the analyzer peaked at 3.4 s with 25 concurrent runs beside 25 CPU-bound processes on 4 cores, and at
    6.0 s (18 of 486 past 5 s) at 50 concurrent runs; the old 5 s default sent those calls to the fallback."""
    assert R.duration("", "15s") == 15.0
    src = open(os.path.join(HOOKS_DIR, "lib", "bash_safety_rules.py"), encoding="utf-8").read()
    assert 'duration(os.environ.get("CLAUDE_HOOK_BOUNDARY_TIMEOUT", ""), "15s")' in src
