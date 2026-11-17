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
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
HOOK = os.path.join(HOOKS_DIR, "pretool-bash-safety.sh")
sys.path.insert(0, os.path.join(HOOKS_DIR, "lib"))

import bash_execution_boundary as eb  # noqa: E402
import bash_safety_rules as R  # noqa: E402

# bash_safety_rules takes its hooks directory from sys.argv[1], which under plain pytest is a test path: point it at
# this checkout's hooks explicitly, and drop tables another module may have loaded from the wrong place.
R.HOOKS, R.LIB = HOOKS_DIR, os.path.join(HOOKS_DIR, "lib")
R._DG_TABLES = None
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
    "python --version", "python3 -m pip --version", "pip --version", "ruff check src --fix", "ruff format --check",
    "cargo --version", "rustc --version", "java -version", "javac -version", "mvn -v", "cmake --version",
    "gcc --version", "clang --version", "docker ps -a", "docker stats --no-stream", "kubectl get pods -A",
    "kubectl version --client", "terraform fmt -check", "aws --version", "gcloud --version", "gh --version",
    "ss -tlnp", "netstat -tlnp", "set -e", "set -x", "set +x", "hash -r", "ls --help", "git --help", "psql -l",
    "mysql --version", "ssh -V", "ssh-add -l", "gpg --list-keys", "base64 -d",
    "git status --short && git diff --stat", "git log --oneline | head -5", "cd src && ls -la",
    "git diff | head -50", "history | tail -20", "git log -p -1", "sort file.txt | uniq -c | sort -rn",
    "bc -l",
]

# Everyday commands the allowlist refuses in degraded mode on purpose: they run code the repository holds (a test
# suite, a Makefile, build scripts, a compose file's containers, a cargo alias in the repository's config).
ALLOWLIST_REFUSED_EVERYDAY = [
    "cargo build --release", "cargo fmt --check", "docker compose up -d", "make -j4", "make -n",
    "pytest --co -q", "pytest -q", "pytest -v", "pytest -x", "python3 -m pytest -q", "python3 -m pytest -x",
    "python3 -m pytest tests -v",
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
    "\"xargs -0\" -x", "x 'a \"bash -c\"' -x", "x -d 'ls; sh -c' -x", "PAGER='sh -c' man ls -a",
    "PAGER=/bin/sh man ls -a",
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


# git text that runs a command: an ext:: remote (and the settings that enable or alias it), git grep's -O pager
# and the fetchers' upload-pack options, also behind kubectl `--`.
GIT_COMMAND_TEXT = [
    "git -c protocol.ext.allow=always ls-remote 'ext::r''m -rf /dev/shm/v/s' -q",
    "git -c protocol.ext.allow=always clone 'ext::r''m -rf /dev/shm/v/s' d -q",
    "git -c protocol.ext.allow=always fetch 'ext::find /x -de''lete' -q",
    "git -c protocol.ext.allow=always archive --remote='ext::r''m -rf /x' HEAD -v",
    "git -c url.ext::x.insteadOf=y ls-remote y -q",
    "kubectl x -- git -c protocol.ext.allow=always ls-remote 'ext::r''m -rf /x' -q",
    "git grep -Or''m x -n", "git grep -O'r''m -rf /dev/shm/v/s' x -n",
    "git ls-remote --upload-pack='touch x' origin -q", "git clone -u 'touch y' origin d -q",
]

# Mentions of a read-handler program as data: a search pattern, a name looked up, text echoed.
MENTIONS = [
    "grep -rn git . -i", "rg ssh -l", "rg -n 'ssh' . -i", "echo docker -n", "echo hash -n", "man ssh -a", "man git -a",
    "apt show git -a", "grep -rn hash src -l", "ls ssh -l", "ls find git docker kubectl ssh hash -l",
    "git push -u origin main", "ls src/ -la", "cp a out/ -v", "git log --grep=ssh --oneline -5",
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
    cmds = set(ANALYZER_REFUSED_EXEC_OPTIONS) | set(STDIN_CODE_AND_NESTED_VALUES)
    for head in REPL_HEADS:  # programs reading code from stdin or a file, fed or not, alone and beside a line
        cmds.update((f"{head} -q", f"printf x | {head} -s", f"{head} -v\nls -l", f"ls -l\nprintf x | {head}"))
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
                         + MULTILINE_NEIGHBOURS + GIT_COMMAND_TEXT)
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
        results = list(ex.map(lambda c: (c, *run_hook(c, hook=hook, **env)), MULTILINE_NEIGHBOURS + GIT_COMMAND_TEXT))
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


PLAIN_LINES = [
    "git commit -m 'fix the bug' --amend", "grep -n 'foo bar' file -r", "bash --version", "grep -rn find src -i",
    "ls src/ -la", "cp a out/ -v", "git log --grep=ssh --oneline -5", "python3 -m pip list -v", "python3 -V",
    "git status --short", "ls -la | grep x -i", "date -u 2>&1 -R",
]


@pytest.mark.parametrize("line", PLAIN_LINES)
def test_predicate_admits_plain_lines(line):
    assert R.degraded_trailing_option_is_plain(line)


MULTILINE_EVERYDAY = [
    "kubectl get pods -A\nkubectl get svc -n x", "git status --short\ngit log --oneline -5", "ls -la\n\ndate -u",
    "cd src && ls -la\ngit diff --stat", "git status --short\nfind . -name x -ls",
]


@pytest.mark.parametrize("command", MULTILINE_EVERYDAY)
def test_multiline_everyday_scripts_stay_allowed(command):
    assert not R.degraded_refuses(command, _rmref()), command


# Real deletions the denylist layers missed (round 6): a program reading code from stdin, or a second `=` value.
STDIN_CODE_AND_NESTED_VALUES = [
    "printf '%s%s -rf /dev/shm/v/s' r m | tar -cf /dev/null /etc/hostname --checkpoint=1 "
    "--checkpoint-action=exec=sh -v",
    "printf '%s%s -rf /dev/shm/v/s' r m | tar -cf /dev/null /etc/hostname --checkpoint=1 "
    "--checkpoint-action=exec=sh\ngit status --short",
    "printf 'x' | tar -cf /dev/null /etc/hostname --checkpoint=1 --checkpoint-action=exec=python3 -v",
    "echo 'import shutil;getattr(shutil,\"r\"+\"mtree\")(\"/dev/shm/v/s\")' | python3 -m asyncio -q",
    "echo 'import shutil;getattr(shutil,\"r\"+\"mtree\")(\"/dev/shm/v/s\")' | python3 -m asyncio\nls -l",
    "printf 'all:;%s%s -rf /dev/shm/v/s' r m | make -f - -s", "printf 'syscmd(%s%s -rf /dev/shm/v/s)' r m | m4 -s",
    "printf 'syscmd(%s%s -rf /dev/shm/v/s)' r m | m4\nls -l",
    "ls -l; printf '.shell %s%s -rf /dev/shm/v/s\\n' r m | sqlite3 -bail",
    "printf '.system %s%s -rf /dev/shm/v/s' r m | sqlite3 -batch", "kubectl x -- ls -la",
]

# Heads that run code they read (an interpreter, a REPL, a database shell, a macro processor) are not on the
# allowlist; any of them ending a command on an option refuses, stdin-fed or not.
REPL_HEADS = ["python3 -m asyncio", "m4", "sqlite3", "duckdb", "psql", "mysql", "dc", "ed", "awk", "perl", "ruby",
              "lua", "tclsh", "jshell", "ghci", "node", "make -f -", "gawk", "php", "Rscript", "osascript"]


@pytest.mark.parametrize("head", REPL_HEADS)
@pytest.mark.parametrize("shape", ["{h} -q", "printf x | {h} -s", "ls -l; {h} -batch", "{h} -v\nls -l",
                                   "ls -l\nprintf x | {h}"])
def test_code_reading_heads_refuse(head, shape):
    assert R.degraded_refuses(shape.format(h=head), _rmref()), shape.format(h=head)


@pytest.mark.parametrize("command", ALLOWLIST_REFUSED_EVERYDAY)
def test_everyday_code_runners_refuse_in_degraded_mode(command):
    assert R.degraded_refuses(command, _rmref()), command


def test_allowlist_holds_no_program_the_analyzer_models_as_running_code():
    """Every allowlisted head is outside the analyzer's shells, interpreters, awks, wrappers and removal programs; the
    handler-owned ones (git, docker, kubectl, find, hash, ssh) and python are read through their own narrow entry."""
    narrow = {"git", "docker", "kubectl", "find", "hash", "ssh", "python", "python3", "python2", "node", "deno",
              "bun", "set"}
    t = R._degraded_tables()
    for head in R._DG_ALLOW:
        if head in narrow:
            continue
        assert not (head in t["shells"] or head in t["interps"] or head in t["awks"] or head in t["wrappers"]
                    or head in t["removal"] or R._dg_handler(t, head)), head


@pytest.mark.parametrize("mode", ["timeout", "memory", "crash"])
def test_stdin_code_and_nested_values_refuse_end_to_end(mode, tmp_path):
    hook = None
    if mode == "crash":
        dst = tmp_path / "hooks"
        shutil.copytree(HOOKS_DIR, str(dst), ignore=shutil.ignore_patterns("tests", "__pycache__"))
        analyzer = dst / "lib" / "bash_execution_boundary.py"
        analyzer.write_text(analyzer.read_text(encoding="utf-8").replace(
            'if __name__ == "__main__":', 'if __name__ == "__main__":\n    sys.exit(3)'), encoding="utf-8")
        hook = str(dst / "pretool-bash-safety.sh")
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda c: (c, *run_hook(c, hook=hook, **MODES.get(mode, {}))),
                              STDIN_CODE_AND_NESTED_VALUES))
    assert not [c for c, code, _err in results if code != 2], (mode, results)


@pytest.mark.parametrize("mode", sorted(MODES))
def test_read_handler_mentions_stay_allowed_end_to_end(mode):
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda c: (c, *run_hook(c, **MODES[mode])), MENTIONS))
    assert not [c for c, code, _err in results if code != 0], (mode, results)


ADVERSARIAL_LONG = {
    "read_handler_words": "ls " + "find " * 250 + "-q\nr''m -rf /dev/shm/v/s",
    "read_handler_words_100kb": "ls " + "find git ssh " * 8000 + "-q\nr''m -rf /dev/shm/v/s",
    "kubectl_nesting": "kubectl -- " * 5000 + "find /x -de''lete -q",
    "kubectl_nesting_with_comments": "kubectl -- # " * 300 + "ls -q",
    "nested_quotes": "x '" + "a '\\''" * 3000 + "' -q\nr''m -rf /dev/shm/v/s",
}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL_LONG))
def test_adversarial_long_lines_are_read_in_bounded_time(name):
    command = ADVERSARIAL_LONG[name]
    started = time.monotonic()
    refused = R.degraded_refuses(command, _rmref())
    assert time.monotonic() - started < 2.0, name
    if "r''m" in command or "-de''lete" in command:
        assert refused, name


@pytest.mark.parametrize("mode", sorted(MODES))
def test_adversarial_long_line_refuses_through_the_hook_in_bounded_time(mode):
    # No `find` word: the runtime guard's own find scan is slow on 100 KB of them on the base branch too.
    command = "ls " + "git ssh hash kubectl " * 5000 + "-q\nr''m -rf /dev/shm/v/s"
    assert len(command) > 100_000
    started = time.monotonic()
    code, err = run_hook(command, **MODES[mode])
    assert code == 2 and DEGRADED in err
    assert time.monotonic() - started < 15.0


def test_a_degraded_reading_past_its_time_bound_refuses(monkeypatch):
    """The fallback's own reading is time-bounded, and running out of time refuses."""
    monkeypatch.setenv("CLAUDE_HOOK_BOUNDARY_TIMEOUT", "0.001s")
    monkeypatch.setattr(R, "_DG_TIME_LIMIT", 0.05)
    monkeypatch.setattr(R, "degraded_refuses", lambda command, rmref: time.sleep(5) or False)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status --short"}})
    started = time.monotonic()
    with pytest.raises(SystemExit) as exit_info:
        R.removal_policy(payload, "git status --short")
    assert exit_info.value.code == 2 and time.monotonic() - started < 3.0


def test_analyzer_timeout_default_leaves_headroom_under_load():
    """15 s: the analyzer peaked at 3.4 s with 25 concurrent runs beside 25 CPU-bound processes on 4 cores, and at
    6.0 s (18 of 486 past 5 s) at 50 concurrent runs; the old 5 s default sent those calls to the fallback."""
    assert R.duration("", "15s") == 15.0
    src = open(os.path.join(HOOKS_DIR, "lib", "bash_safety_rules.py"), encoding="utf-8").read()
    assert 'duration(os.environ.get("CLAUDE_HOOK_BOUNDARY_TIMEOUT", ""), "15s")' in src


# ── Round 7: every spelling of every refused option ──

# Where each allowlisted head's refused options are tried, and the same command without them (which must pass).
SPELLING_CONTEXT = {
    "kubectl": "kubectl get pods {} -A", "helm": "helm list {} -A", "pip": "pip list {} -v", "pip3": "pip3 list {} -v",
    "npm": "npm ls {} -a", "pnpm": "pnpm ls {} -r", "apt": "apt show x {} -a", "apt-cache": "apt-cache show x {} -a",
    "ruff": "ruff check {} -q", "less": "less {} f -n", "more": "more {} f -n", "hostname": "hostname {} -v",
    "man": "man ls {} -a", "info": "info ls {} -a", "go": "go version {} -m", "tsc": "tsc --noEmit {} --strict",
    "whatis": "whatis ls {} -l", "apropos": "apropos ls {} -l", "sort": "sort {} x -n", "tree": "tree {} x -a",
    "rg": "rg {} foo -i", "fd": "fd {} x -H", "date": "date {} -u", "ss": "ss {} -t",
}

# Letters that take a value but whose parser keeps scanning the rest of the cluster (tree hands -P/-I/-T/-H/-o the
# NEXT word; less, ss and apt are read letter by letter here): a refused letter after one of them still refuses.
SCANNED_VALUE_LETTERS = {"tree": "LPITHo", "less": "bhjxyz#", "ss": "fAFN", "apt": "ta", "rg": "", "fd": ""}


def _spellings(option, values, refused, fold=False, scanned=""):
    """Exact, `=value`, every abbreviation (and its case variants where the program folds case), in a cluster, with
    an attached value, and after a value letter whose parser keeps scanning."""
    if option.startswith("--"):
        out = [option, option + "=v"] + ["--" + option[2:k] for k in range(3, len(option))]
        if fold:
            out += [o.upper() for o in out] + ["--" + o[2:].capitalize() for o in out]
        return out
    if len(option) == 2 and option[0] == "-":
        filler = next(c for c in "uqvayzw" if c not in values and "-" + c not in refused)
        return [option, option + "val", "-" + filler + option[1], "-" + filler + option[1] + "val"] + [
            "-" + v + option[1] for v in scanned if v != option[1]]
    return [option]


def refused_spellings():
    cases = []
    for head, (refused, values, *fold) in sorted(R._DG_REFUSED_OPTS.items()):
        context = SPELLING_CONTEXT.get(head, head + " {} x -q")
        for option in refused:
            cases += [(context, context.format(sp)) for sp in _spellings(
                option, values, refused, bool(fold and fold[0]), SCANNED_VALUE_LETTERS.get(head, ""))]
    for sub, (options, words) in sorted(R._DG_GIT_SUB.items()):
        refused = R._DG_GIT_ALL + options
        for option in refused:
            cases += [(None, "git %s %s -q" % (sub, sp)) for sp in _spellings(option, "", refused)]
        cases += [(None, "git %s %s -q" % (sub, w)) for w in words]
    return cases


def test_every_spelling_of_every_refused_option_refuses():
    rmref, failures, contexts = _rmref(), [], set()
    cases = refused_spellings()
    assert len(cases) > 500, len(cases)
    for context, command in cases:
        if not R.degraded_refuses(command, rmref):
            failures.append(command)
        if context:
            contexts.add(context.format("").replace("  ", " "))
    assert not failures, failures[:20]
    # The refusal comes from the option: each context without it passes.
    assert not [c for c in contexts if R.degraded_refuses(c, rmref)], sorted(
        c for c in contexts if R.degraded_refuses(c, rmref))


# The verifier's round-7 inputs: abbreviations, clusters and attached values of options that run a program.
R7_OPTION_SPELLINGS = [
    "git grep -iOsh PWNED\nls -l", "git grep -iOsh -e PWNED --", "git grep -lOsh zzz -n",
    "git grep --open=/dev/shm/v7/x PWNED\nls -l", "git ls-remote --upload=/dev/shm/v7/x /dev/shm/v7/repo -q",
    "git fetch --upload=/dev/shm/v7/x -q", "git pull --upload=/dev/shm/v7/x -q", "fd -e py -xpython3 -H",
    "fd . -x./x -H", "fd . -X./x -H", "fd . --exec=./x -q", "fd . --exec-batch=./x -H",
    "kubectl get pods --kubeconfig=/dev/shm/v7/kc -A", "helm list --kubeconfig=/dev/shm/v7/kc -A",
    "git pull -s ours -q", "printf -v PATH %s /dev/shm/v/bin\nls -l", "apt list -o Dir::Bin::dpkg=/x -a",
    "pnpm ls --pnpmfile=/dev/shm/v/p.cjs -r", "ss -K dst 1.2.3.4 -n",
]

# Writes outside the operands, or code from a file, through an allowlisted head.
R7_WRITES = [
    "sort -o out f -n", "sort --output=out -n", "uniq a b -c", "xxd -r a b -g", "info -o out ls -a",
    "info --dribble=x ls -a", "git log --output=x -1", "git diff --out=x --stat", "git show --output x -q",
    "ruff check --output-file=x -q", "ruff check -o x -q", "tree -H . -a", "tree -R -H . -a", "file -C -m x -b",
    "man -C x ls -a", "man -X ls -a", "git branch --del x -q", "git branch -D x -q", "git tag -d x -q",
    "git add -p -q", "git add --pa -q", "git config edit -q", "git config --edit -q", "git config -e -q",
    "date --se=now -u", "date -s now -u", "hostname --file=x -v", "hostname --fi=x -v", "less +!id f -n",
    "less -k x f -n", "less --lesskey-src=x f -n", "tsc -b --noEmit", "git merge -s evil x -q",
]

# Round 8: a lesskey file in any case and spelling, tree's next-word values, xxd's -C flag, tsc's writing options,
# man's local-file operand.
R8_SPELLINGS = [
    "less --lesskey-file=/dev/shm/lk/k.bin /dev/shm/lk/f -N", "less --lesskey-fi=/dev/shm/lk/k.bin /dev/shm/lk/f -N",
    "less --LESSKEY-FILE=/dev/shm/lk/k.bin /dev/shm/lk/f -N", "less --LESSKEY-SRC=/dev/shm/lk/k.src /dev/shm/lk/f -N",
    "less --lesskey-file=/dev/shm/lk/k.bin /dev/shm/lk/f\nls -l", "tree -Lo 1 /dev/shm/ts/out /dev/shm/ts -a",
    "tree -L2o /dev/shm/ts/out /dev/shm/ts -a", "tree -Po x /dev/shm/ts/out /dev/shm/ts -a",
    "tree -Io x /dev/shm/ts/out /dev/shm/ts -a", "tree -To t /dev/shm/ts/out /dev/shm/ts -a",
    "xxd -C /dev/shm/ts/in /dev/shm/ts/out -u", "tsc --noEmit --generateCpuProfile /dev/shm/ts/v1 a.ts --pretty",
    "tsc --noEmit --incremental --tsBuildInfoFile /dev/shm/ts/v2 a.ts --strict", "tsc --noEmit --init -q",
    "tsc --NOEMIT --GENERATETRACE /dev/shm/ts/t -q", "man ./foo.1 -a", "go env -w GOFLAGS=x -json",
]


# Local forms restored after round 7 (they run nothing beyond what commit and pull already do).
R7_ALLOWED = [
    "ls -la | less", "git log -5 | less", "git switch main -q", "git checkout -b x -q", "git restore --staged x -q",
    "git merge --ff-only -q", "git stash pop -q", "bc -l", "tsc --noEmit", "date -Iseconds", "rg --pretty foo -i",
    "fd -e py -H", "fd -tf -H", "git commit --no-verify -m x -q", "git stash list -q", "git notes list -q",
    "git worktree list -v",
]


@pytest.mark.parametrize("command", R7_OPTION_SPELLINGS + R7_WRITES + R8_SPELLINGS)
def test_round7_forms_refuse(command):
    assert R.degraded_refuses(command, _rmref()), command


@pytest.mark.parametrize("command", R7_ALLOWED)
def test_round7_local_forms_stay_allowed(command):
    assert not R.degraded_refuses(command, _rmref()), command


@pytest.mark.parametrize("mode", ["timeout", "memory", "crash"])
def test_round7_option_spellings_refuse_end_to_end(mode, tmp_path):
    hook = None
    if mode == "crash":
        dst = tmp_path / "hooks"
        shutil.copytree(HOOKS_DIR, str(dst), ignore=shutil.ignore_patterns("tests", "__pycache__"))
        analyzer = dst / "lib" / "bash_execution_boundary.py"
        analyzer.write_text(analyzer.read_text(encoding="utf-8").replace(
            'if __name__ == "__main__":', 'if __name__ == "__main__":\n    sys.exit(3)'), encoding="utf-8")
        hook = str(dst / "pretool-bash-safety.sh")
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda c: (c, *run_hook(c, hook=hook, **MODES.get(mode, {}))),
                              R7_OPTION_SPELLINGS + R8_SPELLINGS))
    assert not [c for c, code, _err in results if code != 2], (mode, results)


# ── Round 9: the allowlist pruned to the heads the everyday lists need ──

R9_REFUSED = [
    "apt-cache policy -p /dev/shm/x/victim -q", "apt-cache policy --pkg-cache /dev/shm/x/victim -q",
    "apt-cache show -s /dev/shm/x/victim coreutils -q", "apt policy --pkg-cache /dev/shm/x/victim -q",
    "apt-cache depends -p /dev/shm/x/victim coreutils -i", "apt policy -p /dev/shm/x/victim -q",
    "apt show -s /dev/shm/x/victim coreutils -q", "apt-cache policy --CONFIG-FILE /dev/shm/x/cfg -q",
    "apt-cache policy --OPTION Dir::Cache::pkgcache=/dev/shm/x/victim -q", "apt policy --Config-File /dev/shm/x/cfg -q",
    "apt policy --OPTION Dir::Cache::pkgcache=/dev/shm/x/victim -q", "apt show --PKG-CACHE /dev/shm/x/victim x -a",
    "javac -version -J-javaagent:/dev/shm/x/a.jar -g", "javac --version -J-javaagent:/dev/shm/x/a.jar -g",
    "java -version -agentpath:/dev/shm/x/evil.so -Xmx1m", "rustc -V -Zcodegen-backend=/dev/shm/x/evil.so -v",
    "mvn -v -Dmaven.ext.class.path=/dev/shm/x/a.jar -q", "mvn -v -f /dev/shm/x/proj -q",
    "cargo --version --config build.rustc=/dev/shm/x/w -v", "node -v --require /dev/shm/x/e.js --trace-warnings",
    "ss -D /dev/shm/x/out -t -a", "ss --diag=/dev/shm/x/out -a", "ss -tD /dev/shm/x/out -a",
    "yq -s '\"/dev/shm/x/o\"' in.yaml -P", "kubectl cluster-info dump --output-directory /dev/shm/x/d -A",
    "kubectl get pods --log-file=/dev/shm/x/l -A", "npm view --git=/dev/shm/x/prog git+file:///dev/shm/x/r --json",
    "npm view --GIT=/dev/shm/x/prog git+file:///dev/shm/x/r --json", "npm outdated --git /dev/shm/x/prog --long",
    "uniq -- -f out; ls -l", "xxd -- -c out; ls -l", "ruff check --config cache-dir=/dev/shm/x/c . -q",
    "git remote -v add x /dev/shm/x/r -q", "git remote -v remove origin -q", "git remote --verbose set-url o x -q",
    "pip list --cache-dir /dev/shm/x/c -v",
]


@pytest.mark.parametrize("command", R9_REFUSED)
def test_round9_forms_refuse(command):
    assert R.degraded_refuses(command, _rmref()), command


@pytest.mark.parametrize("mode", ["timeout", "memory", "crash"])
def test_round9_forms_refuse_end_to_end(mode, tmp_path):
    hook = None
    if mode == "crash":
        dst = tmp_path / "hooks"
        shutil.copytree(HOOKS_DIR, str(dst), ignore=shutil.ignore_patterns("tests", "__pycache__"))
        analyzer = dst / "lib" / "bash_execution_boundary.py"
        analyzer.write_text(analyzer.read_text(encoding="utf-8").replace(
            'if __name__ == "__main__":', 'if __name__ == "__main__":\n    sys.exit(3)'), encoding="utf-8")
        hook = str(dst / "pretool-bash-safety.sh")
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda c: (c, *run_hook(c, hook=hook, **MODES.get(mode, {}))), R9_REFUSED))
    assert not [c for c, code, _err in results if code != 2], (mode, results)


def test_every_allowlisted_head_is_used_by_an_everyday_list():
    """The allowlist holds only heads an everyday fixture needs on a line where a command ends on an option."""
    t = R._degraded_tables()
    used = set()
    for command in (EVERYDAY_TRAILING_OPTION + MENTIONS + R7_ALLOWED + MULTILINE_EVERYDAY + PLAIN_LINES
                    + PIPE_EVERYDAY):
        for line in R.lines_of(command):
            parsed = R._dg_commands(line)
            for words in (parsed[0] if parsed else []):
                words = [w for w in words if w not in t["drop"]]
                if words:
                    used.add(words[0])
    assert not sorted(set(R._DG_ALLOW) - used), sorted(set(R._DG_ALLOW) - used)
    assert set(R._DG_REFUSED_OPTS) <= set(R._DG_ALLOW), sorted(set(R._DG_REFUSED_OPTS) - set(R._DG_ALLOW))


@pytest.mark.parametrize("head", ["apt-cache", "yq", "helm", "info", "whatis", "apropos", "npm", "node", "pnpm",
                                  "yarn", "go", "openssl", "file", "more", "xxd", "printf", "cat", "mv", "ln"])
def test_pruned_heads_refuse_on_a_trailing_option(head):
    assert R.degraded_refuses(head + " x -q", _rmref()), head


# ── Round 10: positive option lists ──

PIPE_EVERYDAY = ["git diff --stat | cat", "git log --oneline -5 | cat -n"]

R10_REFUSED = [
    "kubectl get pods --kuberc=/dev/shm/v/kuberc -A", "kubectl get pods --kuberc /dev/shm/v/kuberc -A",
    "kubectl version --kuberc=/dev/shm/v/kuberc --client",
    "kubectl cluster-info dump --output_directory=/dev/shm/v/od -A",
    "kubectl get pods --cache_dir=/dev/shm/v/cd -A", "pip list --local-log=/dev/shm/v/l -v",
    "pip freeze --local-log /dev/shm/v/l -l", "python3 -m pip list --local-log /dev/shm/v/l -v",
    "python -m pip show pip --local-log=/dev/shm/v/l -f", "set -k\nls LD_PRELOAD=/dev/shm/v/x.so",
    "set -ek; git diff GIT_EXTERNAL_DIFF=/dev/shm/v/x -q", "set -k; git log GIT_EXTERNAL_DIFF=/dev/shm/v/x -p",
    "date 01010101 -u", "kubectl get pods -o go-template-file=/dev/shm/v/t -A", "less -bk /dev/shm/v/k f -N",
    "git help -w log -a", "git help --web log -a", "git help -i log -a", "git config set core.hooksPath /x --get",
    "git config --global core.hooksPath /x -l", "git config set --global core.hooksPath /x -l",
    "base64 -i /dev/shm/v/a -o /dev/shm/v/b -D",
]


@pytest.mark.parametrize("command", PIPE_EVERYDAY)
def test_cat_as_a_pipe_sink_stays_allowed(command):
    assert not R.degraded_refuses(command, _rmref()), command


@pytest.mark.parametrize("command", R10_REFUSED)
def test_round10_forms_refuse(command):
    assert R.degraded_refuses(command, _rmref()), command


@pytest.mark.parametrize("mode", ["timeout", "memory", "crash"])
def test_round10_forms_refuse_end_to_end(mode, tmp_path):
    hook = None
    if mode == "crash":
        dst = tmp_path / "hooks"
        shutil.copytree(HOOKS_DIR, str(dst), ignore=shutil.ignore_patterns("tests", "__pycache__"))
        analyzer = dst / "lib" / "bash_execution_boundary.py"
        analyzer.write_text(analyzer.read_text(encoding="utf-8").replace(
            'if __name__ == "__main__":', 'if __name__ == "__main__":\n    sys.exit(3)'), encoding="utf-8")
        hook = str(dst / "pretool-bash-safety.sh")
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda c: (c, *run_hook(c, hook=hook, **MODES.get(mode, {}))), R10_REFUSED))
    assert not [c for c, code, _err in results if code != 2], (mode, results)


# Each positive-list head in an allowed form, and the same form with one unknown option (long, short, `_`-spelt).
POSITIVE_FORMS = {
    "kubectl": "kubectl get pods {} -A", "pip": "pip list {} -v", "python3": "python3 -m pip list {} -v",
    "set": "set {} -e", "date": "date {} -u", "apt": "apt show git {} -a", "docker": "docker ps {} -a",
    "gpg": "gpg {} --list-keys", "ssh-add": "ssh-add {} -l", "ruff": "ruff check {} -q", "ss": "ss {} -t",
    "man": "man git {} -a", "less": "less {} f -N", "tree": "tree {} x -a", "fd": "fd {} x -H",
    "rg": "rg {} foo -i", "sort": "sort {} x -n", "find": "find . {} -print", "top": "top {} -b", "ps": "ps {} -e",
    "cat": "git diff | cat {} -n", "base64": "base64 {} -d",
}


@pytest.mark.parametrize("head", sorted(POSITIVE_FORMS))
def test_positive_list_heads_refuse_an_unknown_option(head):
    form, rmref = POSITIVE_FORMS[head], _rmref()
    assert not R.degraded_refuses(form.format("").replace("  ", " "), rmref), form
    for unknown in ("--zz-unknown", "--zz-unknown=1", "-Y", "-%", "--log_file=x"):
        assert R.degraded_refuses(form.format(unknown), rmref), form.format(unknown)
