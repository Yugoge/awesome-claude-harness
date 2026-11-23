"""The removal policy's degraded path (lib/bash_safety_rules.py::removal_policy): the analyzer gave no verdict.

Until 2026-11-19 a command passed the degraded path only when it was provably plain: no removal reference, no
assembly channel (expansion, substitution, glob, brace, heredoc), balanced quoting, and, once any command ended on an
option, every head on an allowlist of some sixty programs. Ten review rounds grew that proof and the lists below.

The owner's rule replaced the proof with one question, the one the primary path asks of a command the analyzer
leaves UNRESOLVED: does the command text hold a removal word, by lib/pol_degraded_removal_reference.ere? If it does,
the command is refused; if not, it runs and is handed to the record. So the two paths give an unproven command the
same answer.

Every list of the earlier rounds is kept as input, with the rule's answer in place of the old one: a command of
those lists is refused by the removal policy when, and only when, its text holds a removal word. Most hold none (they
spell a removal with quotes, hand it to a shell through an option, or name no removal at all), so on the degraded
path they now run; with the analyzer available, a removal it finds is refused as before (FORBIDDEN_REMOVAL). All
hook runs use a throwaway HOME and global git config. No command is ever executed.
"""
import json
import os
import resource
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
# this checkout's hooks explicitly.
R.HOOKS, R.LIB = HOOKS_DIR, os.path.join(HOOKS_DIR, "lib")
from shell_parse import WRAPPERS  # noqa: E402

DEGRADED = "removal-policy FAIL-CLOSED"
MODES = {"timeout": {"CLAUDE_HOOK_BOUNDARY_TIMEOUT": "0.001s"}, "memory": {"CLAUDE_HOOK_BOUNDARY_MEM_KB": "4096"}}

# Everyday commands ending on an ordinary option, none naming a removal or an assembly channel: allowed before the
# rule and after it.
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

# Everyday commands the old allowlist refused in degraded mode because they run code the repository holds (a test
# suite, a Makefile, build scripts). None holds a removal word: they run.
ALLOWLIST_REFUSED_EVERYDAY = [
    "cargo build --release", "cargo fmt --check", "docker compose up -d", "make -j4", "make -n",
    "pytest --co -q", "pytest -q", "pytest -v", "pytest -x", "python3 -m pytest -q", "python3 -m pytest -x",
    "python3 -m pytest tests -v",
]

# Round 1's "must keep refusing" list: removals, assembly channels, and structurally incomplete forms, each also
# behind a wrapper, an assignment, a path, quoting or another command. Thirteen hold a removal word and are refused;
# three more meet another rule of the hook (destructive git clean, destructive disk operation); the rest run.
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

# Refused by the live analyzer as UNRESOLVED (missing_option_value). No removal word: they run on both paths.
ANALYZER_REFUSED_EXEC_OPTIONS = [
    "sg wheel -c", "chpst -u", "man -P", "man --pager", "man -B", "man -H", "man --browser", "man --html",
    "rg --pre", "rg --hostname-bin", "ack --pager", "ag --pager", "apropos -P", "apropos --pager", "whatis -P",
    "whatis --pager", "compgen -C", "compgen -F", "diff3 --diff-program", "sdiff --diff-program",
    "sort --compress-program", "split --filter", "ugrep --filter", "ugrep --pager", "grep -e", "rg -e",
    "git -c", "git -C", "docker run -v", "watch -n", "flock -w", "nice -n", "timeout -s", "sudo -u", "env -u",
]

# A quoted or escaped word holding a space (a head that is a command line, or an argument some program runs as one),
# and an option that ends a command before a redirection, a comment or a parenthesis. No removal word.
SHELL_STRING_WORDS = [
    "docker create -l 2>/dev/null", "xargs -d >x", "/usr/bin/docker --host # c", "(xargs -d)", "rg x --max-count''",
    "hyperfine 'grep -f' -N 2>/dev/null",
    "hyperfine 'bash -c' -N", "tmux new -d 'sh -c' -x", "fzf --preview 'bash -c' -m", "nodemon --exec 'env -S' -q",
    "foo --pager 'sh -c' -x", "ssh-agent 'bash -c' -x", "bash\\ -c", "\"bash -c\" -x", "env\\ -S", "'sh -c' -s",
    "sh\\ -c -x", "\"git -C\" . difftool x -n -x", "\"/usr/bin/sudo --close-from\" -x", "nsenter\\ -t", "\"rg -r\" -x",
    "\"xargs -0\" -x", "x 'a \"bash -c\"' -x", "x -d 'ls; sh -c' -x", "PAGER='sh -c' man ls -a",
    "PAGER=/bin/sh man ls -a",
]

# A removal spelled with quotes (`r''m`, `-de''lete`) beside a line ending on an ordinary option (\n is a real
# newline). The raw text names no removal, so the degraded path lets them run; the analyzer, when it answers, finds
# the removal and refuses it (test_removals_the_text_does_not_name_are_found_by_the_analyzer).
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
# and the fetchers' upload-pack options, also behind kubectl `--`. No removal word.
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

# Round 5's degraded-only refusals: unmodelled shells, interpreters and wrappers, a `-c key=value` or
# `--to-command=` naming a shell, g-prefixed removal programs, python -m on a code-running package. One holds a
# removal word (`cmake -E remove x -v`).
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


# Lines the old predicate admitted, and everyday multi-line scripts.
PLAIN_LINES = [
    "git commit -m 'fix the bug' --amend", "grep -n 'foo bar' file -r", "bash --version", "grep -rn find src -i",
    "ls src/ -la", "cp a out/ -v", "git log --grep=ssh --oneline -5", "python3 -m pip list -v", "python3 -V",
    "git status --short", "ls -la | grep x -i", "date -u 2>&1 -R",
]

MULTILINE_EVERYDAY = [
    "kubectl get pods -A\nkubectl get svc -n x", "git status --short\ngit log --oneline -5", "ls -la\n\ndate -u",
    "cd src && ls -la\ngit diff --stat", "git status --short\nfind . -name x -ls",
]


# Round 6: a program reading code from stdin, or a second `=` value. No removal word (`%s%s ... r m`).
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

# Heads that run code they read (an interpreter, a REPL, a database shell, a macro processor).
REPL_HEADS = ["python3 -m asyncio", "m4", "sqlite3", "duckdb", "psql", "mysql", "dc", "ed", "awk", "perl", "ruby",
              "lua", "tclsh", "jshell", "ghci", "node", "make -f -", "gawk", "php", "Rscript", "osascript"]

REPL_SHAPES = ["{h} -q", "printf x | {h} -s", "ls -l; {h} -batch", "{h} -v\nls -l", "ls -l\nprintf x | {h}"]
SENSITIVE_LINES = [
    "bash -c", "env -S", "nice bash -c", "xargs -0", "python3 -c", "git clean -f", "find . -exec", "sudo -i",
    "ls -la; sh -s", "grep 'x -n", "ls -l >", "rm -f",
]


# 100 KB commands: read in bounded time.
ADVERSARIAL_LONG = {  # name: (head, repeated unit, count, tail); the line is head + unit * count + tail
    "read_handler_words": ("ls ", "find ", 250, "-q\nr''m -rf /dev/shm/v/s"),
    "read_handler_words_100kb": ("ls ", "find git ssh ", 8000, "-q\nr''m -rf /dev/shm/v/s"),
    "kubectl_nesting": ("", "kubectl -- ", 5000, "find /x -de''lete -q"),
    "kubectl_nesting_with_comments": ("", "kubectl -- # ", 300, "ls -q"),
    "nested_quotes": ("x '", "a '\\''", 3000, "' -q\nr''m -rf /dev/shm/v/s"),
}


def adversarial_long(name, count=None):
    head, unit, full, tail = ADVERSARIAL_LONG[name]
    return head + unit * (full if count is None else count) + tail


# Round 7: abbreviations, clusters and attached values of options that run a program; writes outside the operands
# or code from a file through a formerly allowlisted head.
R7_OPTION_SPELLINGS = [
    "git grep -iOsh PWNED\nls -l", "git grep -iOsh -e PWNED --", "git grep -lOsh zzz -n",
    "git grep --open=/dev/shm/v7/x PWNED\nls -l", "git ls-remote --upload=/dev/shm/v7/x /dev/shm/v7/repo -q",
    "git fetch --upload=/dev/shm/v7/x -q", "git pull --upload=/dev/shm/v7/x -q", "fd -e py -xpython3 -H",
    "fd . -x./x -H", "fd . -X./x -H", "fd . --exec=./x -q", "fd . --exec-batch=./x -H",
    "kubectl get pods --kubeconfig=/dev/shm/v7/kc -A", "helm list --kubeconfig=/dev/shm/v7/kc -A",
    "git pull -s ours -q", "printf -v PATH %s /dev/shm/v/bin\nls -l", "apt list -o Dir::Bin::dpkg=/x -a",
    "pnpm ls --pnpmfile=/dev/shm/v/p.cjs -r", "ss -K dst 1.2.3.4 -n",
]

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

# Local forms round 7 restored. (`git commit --no-verify` meets the commit-hook-bypass rule, not this policy.)
R7_ALLOWED = [
    "ls -la | less", "git log -5 | less", "git switch main -q", "git checkout -b x -q", "git restore --staged x -q",
    "git merge --ff-only -q", "git stash pop -q", "bc -l", "tsc --noEmit", "date -Iseconds", "rg --pretty foo -i",
    "fd -e py -H", "fd -tf -H", "git commit --no-verify -m x -q", "git stash list -q", "git notes list -q",
    "git worktree list -v",
]

# Round 9: options of formerly allowlisted heads that write a file or load code. One holds a removal word
# (`git remote -v remove origin -q`).
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

# Round 10: cat as a pipe sink, positive option lists.
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

# Each positive-list head in a form the old lists allowed; each was refused with one unknown option added.
POSITIVE_FORMS = {
    "kubectl": "kubectl get pods {} -A", "pip": "pip list {} -v", "python3": "python3 -m pip list {} -v",
    "set": "set {} -e", "date": "date {} -u", "apt": "apt show git {} -a", "docker": "docker ps {} -a",
    "gpg": "gpg {} --list-keys", "ssh-add": "ssh-add {} -l", "ruff": "ruff check {} -q", "ss": "ss {} -t",
    "man": "man git {} -a", "less": "less {} f -N", "tree": "tree {} x -a", "fd": "fd {} x -H",
    "rg": "rg {} foo -i", "sort": "sort {} x -n", "find": "find . {} -print", "top": "top {} -b", "ps": "ps {} -e",
    "cat": "git diff | cat {} -n", "base64": "base64 {} -d",
}

UNKNOWN_OPTIONS = ("--zz-unknown", "--zz-unknown=1", "-Y", "-%", "--log_file=x")
PRUNED_HEADS = ["apt-cache", "yq", "helm", "info", "whatis", "apropos", "npm", "node", "pnpm", "yarn", "go", "openssl",
                "file", "more", "xxd", "printf", "cat", "mv", "ln"]

# Every command the earlier rounds fed to the degraded reading, by the list that held it.
ROUNDS = {
    "EVERYDAY_TRAILING_OPTION": EVERYDAY_TRAILING_OPTION, "ALLOWLIST_REFUSED_EVERYDAY": ALLOWLIST_REFUSED_EVERYDAY,
    "STILL_REFUSED": STILL_REFUSED, "ANALYZER_REFUSED_EXEC_OPTIONS": ANALYZER_REFUSED_EXEC_OPTIONS,
    "SHELL_STRING_WORDS": SHELL_STRING_WORDS, "MULTILINE_NEIGHBOURS": MULTILINE_NEIGHBOURS,
    "GIT_COMMAND_TEXT": GIT_COMMAND_TEXT, "MENTIONS": MENTIONS, "DEGRADED_ONLY_REFUSED": DEGRADED_ONLY_REFUSED,
    "PLAIN_LINES": PLAIN_LINES, "MULTILINE_EVERYDAY": MULTILINE_EVERYDAY,
    "STDIN_CODE_AND_NESTED_VALUES": STDIN_CODE_AND_NESTED_VALUES, "SENSITIVE_LINES": SENSITIVE_LINES,
    "REPL_HEADS": [shape.format(h=head) for head in REPL_HEADS for shape in REPL_SHAPES],
    "R7_OPTION_SPELLINGS": R7_OPTION_SPELLINGS, "R7_WRITES": R7_WRITES, "R8_SPELLINGS": R8_SPELLINGS,
    "R7_ALLOWED": R7_ALLOWED, "R9_REFUSED": R9_REFUSED, "PIPE_EVERYDAY": PIPE_EVERYDAY, "R10_REFUSED": R10_REFUSED,
    "POSITIVE_FORMS": [form.format(opt).replace("  ", " ") for form in POSITIVE_FORMS.values()
                       for opt in ("",) + UNKNOWN_OPTIONS],
    "PRUNED_HEADS": [head + " x -q" for head in PRUNED_HEADS],
}
# Other rules of the hook that refuse some commands of those lists whatever the removal policy answers: a destructive
# git clean or disk operation, a commit that skips its hooks, a write of a keystone git setting, and the runtime
# guard's own fail-closed refusal of package and build tools while no protected-runtime file is configured (these
# runs carry none).
# The hook's other rules, which may refuse a command before the removal policy reads it. "reads, but" is the
# read-made-to-run rule (outward_rule, ec3af2f5b, 2026-11-19): `rg --pre`, `git -c core.pager=sh log`.
OTHER_RULES = ("git clean", "Destructive disk operation", "commit-hook-bypass", "config-keystone-write",
               "protected-runtime-guard", " reads, but ")


def _rmref():
    with open(os.path.join(HOOKS_DIR, "lib", "pol_degraded_removal_reference.ere"), encoding="utf-8") as fh:
        return next(ln.strip() for ln in fh if ln.strip() and not ln.startswith("#"))


def holds_removal_word(command):
    """The single definition, read from its file, asked of each line as the hook asks it."""
    return R.grep(_rmref(), command)


def child_cpu():
    """CPU seconds of every finished child process: what a hook run costs, apart from how busy the runner is."""
    r = resource.getrusage(resource.RUSAGE_CHILDREN)
    return r.ru_utime + r.ru_stime


def run_hook(command, hook=None, timeout=None, **env_extra):
    home = tempfile.mkdtemp(prefix="degraded-home-")
    gitconfig = os.path.join(home, "gitconfig")
    open(gitconfig, "w").close()
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=home, GIT_CONFIG_GLOBAL=gitconfig, **env_extra)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    p = subprocess.run(["bash", hook or HOOK], input=payload, capture_output=True, text=True, cwd=home, env=env,
                       timeout=timeout)
    return p.returncode, p.stderr


def no_analyzer(monkeypatch):
    """Make removal_policy()'s analyzer process fail at once: the degraded path, without starting a process."""
    def run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 0.001)
    monkeypatch.setattr(R.subprocess, "run", run)


def answer(command):
    """removal_policy() in this process: (refused, the entry for the record or None, the refusal's text)."""
    import io
    real, sys.stderr = sys.stderr, io.StringIO()
    try:
        return False, R.removal_policy(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
                                       command), ""
    except SystemExit as exc:
        assert exc.code == 2, exc.code
        return True, None, sys.stderr.getvalue()
    finally:
        sys.stderr = real


def _crashing_hook(tmp_path):
    """A copy of the hooks whose analyzer exits 3 when run (its tables stay importable)."""
    dst = tmp_path / "hooks"
    shutil.copytree(HOOKS_DIR, str(dst), ignore=shutil.ignore_patterns("tests", "__pycache__"))
    analyzer = dst / "lib" / "bash_execution_boundary.py"
    analyzer.write_text(analyzer.read_text(encoding="utf-8").replace(
        'if __name__ == "__main__":', 'if __name__ == "__main__":\n    sys.exit(3)'), encoding="utf-8")
    return str(dst / "pretool-bash-safety.sh")


# ── The degraded path asks the one question ──────────────────────────────────

@pytest.mark.parametrize("name", sorted(ROUNDS))
def test_the_degraded_path_refuses_exactly_the_commands_whose_text_holds_a_removal_word(monkeypatch, name):
    no_analyzer(monkeypatch)
    for command in ROUNDS[name]:
        refused, entry, err = answer(command)
        assert refused == holds_removal_word(command), (name, command, err)
        if refused:
            assert "BLOCKED: " + DEGRADED in err, err
        else:
            assert entry == {"rule": "removal-policy", "kind": "let_through_unproven", "path": "degraded",
                             "reason": "NO_VERDICT analyzer unavailable or gave no usable verdict"}, (command, entry)


def test_the_lists_hold_both_answers():
    """Twenty-three lists of the earlier rounds; the rule refuses the few commands in them that name a removal."""
    every = [c for commands in ROUNDS.values() for c in commands]
    named = sorted({c for c in every if holds_removal_word(c)})
    assert len(every) > 700 and len(ROUNDS) == 23
    assert named == sorted({
        "rm -rf build", "rm build -rf", "rm -rf", "/bin/rm x -f", "unlink -x", "rmdir d -p", "shred x -u",
        "git rm -r --cached x -f", "rsync -a src/ dst/ --delete", "find . -name x -delete", "x=rm; $x -r",
        "$(echo rm) -rf", "`echo rm` -rf", "rm -f", "cmake -E remove x -v", "git remote -v remove origin -q",
    }), named


@pytest.mark.parametrize("mode", ["timeout", "memory", "crash"])
@pytest.mark.parametrize("names", [
    ("STILL_REFUSED",), ("ANALYZER_REFUSED_EXEC_OPTIONS", "SHELL_STRING_WORDS"), ("MULTILINE_NEIGHBOURS", "GIT_COMMAND_TEXT"),
    ("STDIN_CODE_AND_NESTED_VALUES", "DEGRADED_ONLY_REFUSED"), ("R7_OPTION_SPELLINGS", "R8_SPELLINGS"),
    ("R9_REFUSED",), ("R10_REFUSED", "R7_ALLOWED"),
], ids=lambda names: "+".join(names))
def test_through_the_hook_the_degraded_path_gives_the_rule_s_answer(mode, names, tmp_path):
    hook = _crashing_hook(tmp_path) if mode == "crash" else None
    commands = [c for name in names for c in ROUNDS[name]]
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(lambda c: (c, *run_hook(c, hook=hook, **MODES.get(mode, {}))), commands))
    wrong, unnamed, ran = [], 0, 0
    for command, code, err in results:
        other = any(rule in err for rule in OTHER_RULES) and "removal-policy" not in err
        if holds_removal_word(command):
            # Refused: by the removal policy on the degraded path, unless an earlier rule refuses the command first.
            ok = code == 2 and (DEGRADED in err or other)
        else:
            # Never refused by the removal policy; it runs unless another rule of the hook refuses it.
            unnamed += 1
            ran += code == 0
            ok = "removal-policy" not in err and (code == 0 or (code == 2 and other))
        if not ok:
            wrong.append((command, code, err.splitlines()[:1]))
    assert not wrong, (mode, wrong[:10])
    assert ran * 3 >= unnamed * 2, (mode, names, ran, unnamed)


@pytest.mark.parametrize("mode", sorted(MODES))
def test_everyday_trailing_options_pass_the_degraded_fallback(mode):
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(lambda c: (c, *run_hook(c, **MODES[mode])),
                              EVERYDAY_TRAILING_OPTION + ALLOWLIST_REFUSED_EVERYDAY + MULTILINE_EVERYDAY + PIPE_EVERYDAY))
    refused = [(c, err.splitlines()[:1]) for c, code, err in results if code != 0]
    assert not refused, "%d of %d refused under %s: %r" % (len(refused), len(results), mode, refused[:10])


@pytest.mark.parametrize("mode", sorted(MODES))
def test_read_handler_mentions_stay_allowed_end_to_end(mode):
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(lambda c: (c, *run_hook(c, **MODES[mode])), MENTIONS))
    assert not [c for c, code, _err in results if code != 0], (mode, results)


@pytest.mark.parametrize("body", [None, "import sys\nsys.exit(0)\n", "raise RuntimeError('x')\n",
                                  "import time\ntime.sleep(30)\n"])
def test_an_analyzer_module_that_is_absent_exits_raises_or_hangs_leaves_the_rule_s_answer(tmp_path, body):
    dst = tmp_path / "hooks"
    shutil.copytree(HOOKS_DIR, str(dst), ignore=shutil.ignore_patterns("tests", "__pycache__"))
    target = dst / "lib" / "bash_execution_boundary.py"
    if body is None:
        target.unlink()
    else:
        target.write_text(body, encoding="utf-8")
    hook = str(dst / "pretool-bash-safety.sh")
    code, err = run_hook("git status --short", hook=hook, CLAUDE_HOOK_BOUNDARY_TIMEOUT="1s")
    assert code == 0 and "removal-policy" not in err, err
    code, err = run_hook("rm -rf build", hook=hook, CLAUDE_HOOK_BOUNDARY_TIMEOUT="1s")
    assert code == 2 and DEGRADED in err, err
    code, err = run_hook("man rm", hook=hook, CLAUDE_HOOK_BOUNDARY_TIMEOUT="1s")
    assert code == 2 and DEGRADED in err, err


# ── What the degraded path cannot see, the analyzer finds ────────────────────

QUOTED_REMOVALS = [c for c in MULTILINE_NEIGHBOURS + GIT_COMMAND_TEXT
                   if eb.analyze(c)["verdict"] == eb.FORBIDDEN_REMOVAL and not R.grep(_rmref(), c)]


def test_most_of_the_quoted_removals_are_found_by_the_analyzer():
    assert len(QUOTED_REMOVALS) >= 14, QUOTED_REMOVALS


@pytest.mark.parametrize("command", QUOTED_REMOVALS)
def test_removals_the_text_does_not_name_are_found_by_the_analyzer(command):
    """The named prohibition does not rest on the text: with its analyzer, the hook refuses these as removals."""
    # The analyzer is given time: past its 15 s default on a loaded host, the hook is on the degraded path.
    code, err = run_hook(command, CLAUDE_HOOK_BOUNDARY_TIMEOUT="120s")
    assert code == 2 and ("removal-policy — FORBIDDEN_REMOVAL" in err or any(rule in err for rule in OTHER_RULES)), err


# ── The generated corpus ─────────────────────────────────────────────────────

def test_over_the_generated_corpus_the_two_paths_agree_on_every_unproven_command(monkeypatch):
    """Was: the degraded fallback is never laxer than the live analyzer. Over the same 80,000 generated forms, with
    the policy run in this process on both paths: every command the analyzer leaves UNRESOLVED gets the same answer
    with and without it; a command holding a removal word is never let through unproven; and the only commands
    refused with the analyzer and run without it are removals the analyzer found whose text names none."""
    corpus = analyzer_corpus()
    verdicts = {}

    def answered(argv, **kwargs):
        result = eb.analyze(kwargs["env"]["CMD_INPUT"])
        verdicts[kwargs["env"]["CMD_INPUT"]] = result["verdict"]
        return subprocess.CompletedProcess(argv, 0, json.dumps(result), "")

    monkeypatch.setattr(R.subprocess, "run", answered)
    primary = {c: answer(c)[:2] for c in corpus}
    no_analyzer(monkeypatch)
    degraded = {c: answer(c)[:2] for c in corpus}
    unresolved = [c for c in corpus if verdicts[c] == eb.UNRESOLVED]
    assert len(corpus) > 80000 and len(unresolved) > 1000, (len(corpus), len(unresolved))
    differing = [c for c in unresolved if not primary[c][0] == degraded[c][0] == holds_removal_word(c)]
    assert not differing, "%d unproven forms answered differently: %r" % (len(differing), differing[:20])
    let_through_named = [c for c in corpus if holds_removal_word(c) and (primary[c][1] or degraded[c][1])]
    assert not let_through_named, let_through_named[:20]
    assert not [c for c in corpus if holds_removal_word(c) and not degraded[c][0]]
    laxer = [c for c in corpus if primary[c][0] and not degraded[c][0]]
    assert laxer and all(verdicts[c] == eb.FORBIDDEN_REMOVAL and not holds_removal_word(c) for c in laxer), [
        (c, verdicts[c]) for c in laxer if verdicts[c] != eb.FORBIDDEN_REMOVAL][:20]


# ── Bounded reading ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", sorted(ADVERSARIAL_LONG))
def test_adversarial_long_lines_are_read_in_bounded_time(monkeypatch, name):
    command = adversarial_long(name)
    no_analyzer(monkeypatch)

    def cost(line):
        """(refused, CPU seconds): the least CPU of up to nine readings of line, until one CPU second is spent."""
        best, spent = None, 0.0
        for _ in range(9):
            started = time.process_time()  # CPU time: a busy runner slows the wall clock, not the work
            refused = answer(line)[0]
            took = time.process_time() - started
            best, spent = (took if best is None else min(best, took)), spent + took
            if spent > 1.0:
                break
        return refused, best

    # Bounded: twice the line costs well under four times as much (a reading that walks the line again from each
    # word grows with its square). Two measured readings are compared with each other: no fixed bound holds on
    # every runner.
    refused, large = cost(command)
    _, small = cost(adversarial_long(name, ADVERSARIAL_LONG[name][2] // 2))
    assert large < 3 * small, (name, small, large)
    assert refused is False and not holds_removal_word(command), name
    assert answer(command + "\nrm -rf /dev/shm/v/s")[0] is True


@pytest.mark.parametrize("mode", sorted(MODES))
def test_adversarial_long_line_is_answered_through_the_hook_in_bounded_time(mode):
    def cost(words):
        # No `find` word: the runtime guard's own find scan is slow on 100 KB of them on the base branch too.
        quoted = "ls " + "git ssh hash kubectl " * words + "-q\nr''m -rf /dev/shm/v/s"
        named = "ls " + "git ssh hash kubectl " * words + "-q\nrm -rf /dev/shm/v/s"
        started = child_cpu()
        code, err = run_hook(quoted, timeout=240, **MODES[mode])
        assert code == 0 and "removal-policy" not in err, err[:300]
        code, err = run_hook(named, timeout=240, **MODES[mode])
        assert code == 2 and DEGRADED in err
        return child_cpu() - started, len(quoted)

    (fixed, _), (half, _), (full, size) = cost(1), cost(2500), cost(5000)
    assert size > 100_000
    # Bounded, not fast: the whole PreToolUse pipeline reads the line twice per pair. Above the pipeline's fixed cost
    # (every hook's own start) the cost grows with the line's length: twice the line costs about twice as much, never
    # four times. The pairs are compared with each other, in CPU seconds, because no fixed bound holds on every
    # runner: the 100 KB pair took about 15 s here and 31 s on the slowest CI runner (2026-11-20). Each run also
    # ends within its own 240 s.
    assert full - fixed < 3 * (half - fixed), (fixed, half, full)


def test_analyzer_timeout_default_leaves_headroom_under_load():
    """15 s: the analyzer peaked at 3.4 s with 25 concurrent runs beside 25 CPU-bound processes on 4 cores, and at
    6.0 s (18 of 486 past 5 s) at 50 concurrent runs; the old 5 s default sent those calls to the fallback."""
    assert R.duration("", "15s") == 15.0
    src = open(os.path.join(HOOKS_DIR, "lib", "bash_safety_rules.py"), encoding="utf-8").read()
    assert 'duration(os.environ.get("CLAUDE_HOOK_BOUNDARY_TIMEOUT", ""), "15s")' in src
