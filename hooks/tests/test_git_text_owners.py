"""The git classifier reads search patterns, piped text and data here-documents as text (OB-L24).

Four readings, each with the inputs that must still be refused:

  - text owners: rg (without `--pre`/`--pre-glob`, or a config file it is
    pointed at), `git grep` (without `-O`) and `git log --grep`, with no
    `-c`/`--config-env` before the subcommand and no assignment before git
    (`GIT_EXTERNAL_DIFF=...`, `GIT_CONFIG_COUNT=...`, `GIT_PAGER=...`),
    leave their quoted arguments unexecuted, as grep does. ag and ack are not
    text owners: their `--pager` runs a shell;
  - stdin consumers: head, tail, wc, sort, uniq, cut, tr, column and nl read
    what a pipe feeds them as text, so a pipe into one keeps a grep pattern
    text. They are not text owners: their own arguments are read, and a sort
    given `--compress-program` (any spelling) is no consumer. less is not
    one: LESSOPEN, set inline or inherited, runs what it reads;
  - a here-document read only by cat, tee or another data reader is data:
    it runs only the substitutions its expansion performs. Written to a file
    (a redirection or tee), it is data only under a closed rule: every other
    command of the line is inert (cat, head, tail, wc, ls, echo, printf,
    test, true, false, mkdir, pwd, grep/rg as text owners), standing alone
    and writing nothing (an output redirection only to /dev/null or another
    descriptor; not `printf -v`), the file may land as data (no hidden
    component or `..`, not under `~`, no `hooks` component, absolute only
    under /tmp or /var/tmp, not a Makefile or gitconfig, in any case), and
    the here-document is the tool command's own: nested in a `-c` string, an
    eval or program-option string, a substitution or a process substitution
    it is code.
    Any other command keeps it code (`... && sh < x.sh`, `make`, `cd .git`,
    `git status`, which may run what a config names). Fed to
    bash, sh, ssh, `python3 -`, `source /dev/stdin`, a group, a compound
    command (for, while, until, if, case, select), an `exec` with
    redirections or a process substitution, copied by cp or dd, or captured
    by a substitution whose output may run, it stays code; a
    substitution is data when its command is text-only and keeps its input
    as data (`git commit -m "$(cat <<'EOF' ...)"`). A here-string is read
    the same way (`sh <<< 'git push'`);
  - a program option's value is a command line of its own (`rg --pre`,
    `ag --pager`, `sort --compress-program`, `git grep -O`), and what echo or
    printf print into a pipe a shell reads is shell text (`echo "git push" |
    sh`, `printf '%s' 'git push' | sh`), its backslash escapes decoded.

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

from lib.git_command_classifier import classify_git_command  # noqa: E402

NL = "\n"


def heredoc(head, body, delim="EOF", quote="'"):
    return f"{head} <<{quote}{delim}{quote}{NL}{body}{NL}{delim}"


MUST_PASS = [
    "rg -n 'git reset --hard|git push --force' .",
    "grep -rn 'git push origin\\|git merge origin' . | head -5",
    'rg -n "git rebase -i" docs',
    "grep -rn 'git revert HEAD~1' docs/",
    heredoc("cat > /tmp/notes.md", "notes" + NL + "git push origin master"),
    "git log --oneline -3  # newest first; git push is not needed",
    "git grep -n 'a; git push' -- docs",
    "git log --grep='x; git push' --oneline",
    heredoc("cat", "git push origin master"),
    "rg -n 'a|git push' . | wc -l",
    "grep -n 'x; git push' f | sort | uniq -c | tail -3",
    heredoc("tee /tmp/a.md > /dev/null", "git reset --hard origin/master"),
    "cat <<'EOF' | sort | nl" + NL + "git push origin master" + NL + "EOF",
    # A written file the rest of the line only reads with inert commands.
    "cat > x.sh <<'EOF' && cat x.sh" + NL + "git push origin master" + NL + "EOF",
    "mkdir -p /tmp/n && cat > /tmp/n/notes.md <<'EOF' && wc -l /tmp/n/notes.md" + NL
    + "git push origin master" + NL + "EOF" + NL + "ls -la /tmp/n 2>/dev/null",
    "tee x <<'EOF'" + NL + "git push origin master" + NL + "EOF" + NL + "cat x",
    "cat <<'EOF' > x" + NL + "git push origin master" + NL + "EOF" + NL + "wc -l x",
    "cat > docs/x <<'EOF' 2>&1" + NL + "git push origin master" + NL + "EOF",
    "grep -c x <<< 'a; git push origin master'",
]

# A commit's message is text; the guard still refuses an agent's commit without
# a /commit grant, so these are checked against the classifier alone.
COMMIT_MESSAGES = [
    heredoc("git commit -F -", "docs: say that git push is not needed"),
    'git commit -m "$(cat <<\'EOF\'' + NL + "docs: the push note" + NL
    + "git push origin master is the owner's" + NL + "EOF" + NL + ')"',
]

MUST_REFUSE = [
    'bash -c "x; git push"',
    'echo "git push" | sh',
    "echo -n 'git push origin master' | sh",
    "printf 'git push origin master\\n' | bash",
    heredoc("bash", "git push origin master"),
    "cat <<'EOF' | bash" + NL + "git push origin master" + NL + "EOF",
    heredoc("ssh host", "git push origin master"),
    heredoc("python3 -", "git push origin master"),
    heredoc("source /dev/stdin", "git push origin master"),
    "{ cat <<'EOF'; } | bash" + NL + "git push origin master" + NL + "EOF",
    "cat <<'EOF' | tee >(sh)" + NL + "git push origin master" + NL + "EOF",
    "cat <<'EOF' |" + NL + "git push origin master" + NL + "EOF" + NL + "bash",
    'eval "$(cat <<\'EOF\'' + NL + "git push origin master" + NL + "EOF" + NL + ')"',
    heredoc("cat > /tmp/x", "$(git push origin master)", quote=""),
    "ag --pager 'true; git push origin master' foo",
    "ack --pager 'true; git push origin master' foo",
    "rg --pre 'git push' x",
    "rg --pre='git push' x",
    "rg --pre-glob '*.md' 'a; git push' x",
    "RIPGREP_CONFIG_PATH=/tmp/c rg 'a; git push' x",
    "grep x f | sort --compress-program='sh -c \"git push\"'",
    "git grep -O'x; git push' foo",
    "git -c core.pager='x; git push' log --grep='a'",
    "grep 'x; git push' f | sh",
    'echo "$(cat <<\'EOF\'' + NL + "git push origin master" + NL + "EOF" + NL + ')" | sh',
    'X="$(cat <<\'EOF\'' + NL + "git push origin master" + NL + "EOF" + NL + ')"; $X',
    '"$(cat <<\'EOF\'' + NL + "git push origin master" + NL + "EOF" + NL + ')"',
    'git commit -m "$(cat <<EOF' + NL + "$(git push origin master)" + NL + "EOF" + NL + ')"',
]


PUSH = "git push origin master"


def _doc(head, tail=""):
    return head + NL + PUSH + NL + "EOF" + tail


# Inputs the independent verifier found allowed at 87bf6d9 although base
# refused them, and that really run git.
REGRESSIONS = [
    # A data here-document inside a compound command whose output a shell reads.
    _doc("for f in 1; do cat <<'EOF'; done | sh"),
    _doc("if true; then cat <<'EOF'; fi | sh"),
    _doc("while true; do cat <<'EOF'; break; done | bash"),
    _doc("until false; do cat <<'EOF'; break; done | sh"),
    _doc("case x in x) cat <<'EOF';; esac | sh"),
    _doc("select v in a; do cat <<'EOF'; break; done | sh"),
    "for f in 1; do" + NL + "  cat <<'EOF'" + NL + PUSH + NL + "EOF" + NL + "done | sh",
    "while true; do" + NL + "  cat <<'EOF'" + NL + PUSH + NL + "EOF" + NL + "  break" + NL + "done | bash",
    # less runs its input through LESSOPEN; a sort given a compressor feeds it.
    _doc("cat <<'EOF' | LESSOPEN='|-sh %s' less"),
    _doc("LESSOPEN='|-sh %s' less <<'EOF'"),
    _doc("export LESSOPEN='|-sh %s'; cat <<'EOF' | less"),
    _doc("sort -S 1 -T . --compress-program=sh - /usr/share/dict/words <<'EOF'"),
    _doc("cat <<'EOF' | sort -S 1 -T . --compress-program=sh - /usr/share/dict/words"),
    _doc("cat <<'EOF' | sort -S 1 --compress=sh -"),
    _doc("cat <<'EOF' | sort -S 1 --compress-prog sh -"),
    # An assignment before git log --grep or git grep may make git run a program.
    "GIT_EXTERNAL_DIFF='x; git push origin master' git log --grep=i -p --ext-diff",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=diff.external GIT_CONFIG_VALUE_0='x; git push origin master'"
    " git log --grep=i -p --ext-diff",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager GIT_CONFIG_VALUE_0='x; git push origin master'"
    " git grep -n i",
    "GIT_EXTERNAL_DIFF='x; git push origin master' git grep -n 'i'",
    "GIT_CONFIG_PARAMETERS=\"'core.pager'='x; git push origin master'\" git log --grep=i",
    "GIT_PAGER='x; git push origin master' git log --grep=i",
    "PAGER='x; git push origin master' git log --grep=i",
    "env GIT_EXTERNAL_DIFF='x; git push origin master' git log --grep=i -p --ext-diff",
    "export GIT_EXTERNAL_DIFF='x; git push origin master'; git log --grep=i -p --ext-diff",
    # A here-document written to a file, with a command on the line that runs it.
    _doc("cat > x.sh <<'EOF'", NL + "sh x.sh"),
    "cat > x.sh <<'EOF' && sh x.sh" + NL + PUSH + NL + "EOF",
    "cat <<'EOF' | tee -a x.sh >/dev/null && sh x.sh" + NL + PUSH + NL + "EOF",
    "cat > x.sh <<'EOF' && chmod +x x.sh && ./x.sh" + NL + PUSH + NL + "EOF",
    "cat > x.sh <<'EOF' && source x.sh" + NL + PUSH + NL + "EOF",
    "cat > x.sh <<'EOF' && . ./x.sh" + NL + PUSH + NL + "EOF",
    "cat > /tmp/x.sh <<'EOF' && bash /tmp/x.sh" + NL + PUSH + NL + "EOF",
    "cat > x.sh <<'EOF' && bash -c 'sh x.sh'" + NL + PUSH + NL + "EOF",
]

# A here-document written to a file is data only when every other command of
# the line is inert and the file is none run by itself; these run the body.
WRITTEN_AND_RUN = [
    _doc("cat > x.sh <<'EOF'", NL + "sh < x.sh"),
    _doc("cat > x.sh <<'EOF'", NL + "bash -s < x.sh"),
    _doc("cat > x.sh <<'EOF'", NL + "cat x.sh | sh"),
    _doc("cat > x.sh <<'EOF'", NL + "sh x.*"),
    _doc("cat > x.sh <<'EOF'", NL + "sh ./*.sh"),
    _doc("cat > x.sh <<'EOF'", NL + "cp x.sh y.sh && sh y.sh"),
    _doc("cat > x.sh <<'EOF'", NL + "mv x.sh y && sh y"),
    _doc("cat > x.sh <<'EOF'", NL + "s=x.sh; sh $s"),
    _doc("cat > x.sh <<'EOF'", NL + "xargs -a x.sh -I{} sh -c {}"),
    _doc("cat > x.sh <<'EOF'", NL + "xargs sh -c < x.sh"),
    _doc("cat > x.sh <<'EOF'", NL + "find . -name 'x.sh' -exec sh {} \\;"),
    _doc("cat > Makefile <<'EOF'", NL + "make"),
    "cat > Makefile <<'EOF'" + NL + "all:" + NL + "\t" + PUSH + NL + "EOF" + NL + "make",
    _doc("cp /dev/stdin x.sh <<'EOF'", NL + "sh x.sh"),
    _doc("cat <<'EOF' > ~/.bashrc", NL + "bash -i -c true"),
    _doc("cat <<'EOF' >> .git/hooks/post-checkout", NL + "chmod +x .git/hooks/post-checkout"),
    "cat > x.sh <<'EOF' ; sh < x.sh" + NL + PUSH + NL + "EOF",
    "cat > x.sh <<'EOF' && sh <x.sh" + NL + PUSH + NL + "EOF",
    # A file run or read by itself is code even alone on the line.
    _doc("cat > ~/.bashrc <<'EOF'"),
    _doc("cat >> ~/.zshenv <<'EOF'"),
    _doc("tee .git/hooks/pre-commit <<'EOF'"),
    _doc("cat > .husky/pre-push <<'EOF'"),
    _doc("cat > .envrc <<'EOF'"),
    # A stdin consumer with an assignment before it is no consumer.
    _doc("cat <<'EOF' | SORTOPTS=x sort"),
]

# The verifier's l10/l11 inputs that base refuses: inert commands that write or
# configure git, git itself, cd into a sensitive directory, sensitive
# destinations in any case, and written files a later command runs.
VERIFIER_L10_L11 = [
    "cd .git && cat > hooks/pre-commit <<'EOF'\ngit push origin master\nEOF",
    "cd .git/hooks && cat > pre-commit <<'EOF'\ngit push origin master\nEOF",
    "cd .husky && cat > pre-commit <<'EOF'\ngit push origin master\nEOF",
    "cd ~ && cat > .bashrc <<'EOF'\ngit push origin master\nEOF",
    "cat > ../.git/hooks/x <<'EOF'\ngit push origin master\nEOF",
    "cat > ./.bashrc <<'EOF'\ngit push origin master\nEOF",
    "cat > .GIT/hooks/pre-commit <<'EOF'\ngit push origin master\nEOF",
    "cat > .Bashrc <<'EOF'\ngit push origin master\nEOF",
    "cat >| .git/hooks/pre-push <<'EOF'\ngit push origin master\nEOF",
    "cat &> .git/hooks/pre-push <<'EOF'\ngit push origin master\nEOF",
    "cat >> .git/hooks/pre-push <<'EOF'\ngit push origin master\nEOF",
    "cat 2> .git/hooks/pre-push <<'EOF'\ngit push origin master\nEOF",
    "cat 3> .git/hooks/pre-push <<'EOF' >&3\ngit push origin master\nEOF",
    "exec cat > x <<'EOF'\ngit push origin master\nEOF",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\necho y > .git/hooks/post-checkout",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\nprintf y >> ~/.bashrc",
    "cat > notes.md <<'EOF'\ngit push origin master\nEOF\ngit status",
    "cat > notes.md <<'EOF'\ngit push origin master\nEOF\ngit log -1",
    "cat > notes.md <<'EOF'\ngit push origin master\nEOF\ngit diff",
    "cat > notes.md <<'EOF'\ngit push origin master\nEOF\ngit -P log -1",
    "cat > notes.md <<'EOF'\ngit push origin master\nEOF\ngit --no-pager diff",
    "cat > .git/hooks/x <<'EOF'\ngit push origin master\nEOF",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\nx.sh",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\nls; x.sh",
    "cat > ls <<'EOF'\ngit push origin master\nEOF\nPATH=.:$PATH ls",
    "cat > cat <<'EOF'\ngit push origin master\nEOF\nchmod +x cat",
    "cat > x <<'EOF'\ngit push origin master\nEOF\ncd x",
    "cat > x <<'EOF'\ngit push origin master\nEOF\necho $(sh x)",
    "cat > x <<'EOF'\ngit push origin master\nEOF\necho `sh x`",
    "cat > x <<'EOF'\ngit push origin master\nEOF\nrg --pre sh x .",
    "cat > x <<'EOF'\ngit push origin master\nEOF\nrg --pre=./x foo .",
    "cat > x <<'EOF'\ngit push origin master\nEOF\ngit log --grep=x -p --ext-diff",
    "cat > x <<'EOF'\ngit push origin master\nEOF\ngit diff --ext-diff",
    "cat > x <<'EOF'\ngit push origin master\nEOF\ngit log --format=%H",
    "cat > x <<'EOF'\ngit push origin master\nEOF\ngit diff --no-index x /dev/null",
    "cat > x <<'EOF'\ngit push origin master\nEOF\ngit diff --textconv",
    "cat > x <<'EOF'\ngit push origin master\nEOF\ngit log --output=.git/hooks/pre-commit",
    "cat > x <<'EOF'\ngit push origin master\nEOF\ngit diff --output=.git/hooks/pre-commit x",
    "cat > x <<'EOF'\ngit push origin master\nEOF\nhead -c 100 x > .git/hooks/pre-commit",
    "cat > x <<'EOF'\ngit push origin master\nEOF\ncat x > .git/hooks/pre-commit",
    "cat > x <<'EOF'\ngit push origin master\nEOF\ncat x >> ~/.bashrc",
    "cat > x <<'EOF'\ngit push origin master\nEOF\ncat x | tee .git/hooks/pre-commit",
    "cat > x <<'EOF'\ngit push origin master\nEOF\ncat x > ~/.config/git/config",
    "cat > x <<'EOF'\ngit push origin master\nEOF\nprintf '%s' x > Makefile",
    "cat > x <<'EOF'\ngit push origin master\nEOF\ncommand cat x",
    "tee x .git/hooks/pre-commit <<'EOF'\ngit push origin master\nEOF",
    "tee -a ~/.bashrc <<'EOF'\ngit push origin master\nEOF",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\nprintf '[core]\\n\\tfsmonitor = sh x.sh\\n' >> .git/config\ngit status",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\nprintf '[diff]\\n\\texternal = sh x.sh\\n' > ~/.config/git/config\ngit diff",
    "cat > x.sh <<'EOF' && echo '[diff] external = sh x.sh' >> .git/config && git diff\ngit push origin master\nEOF",
    "cat > x.sh <<'EOF' && echo '[core] fsmonitor = sh x.sh' >> .git/config && git status\ngit push origin master\nEOF",
]

# The verifier's l12/l13 inputs that base refuses: a written here-document
# nested in a `-c` string or a substitution (code at any depth but the tool
# command's own), `printf -v`, and destinations outside the closed set
# (hidden, home, `hooks`, absolute outside /tmp).
VERIFIER_L12_L13 = [
    "bash -c $'cat > x.sh <<EOF\\ngit push origin master\\nEOF' && sh x.sh",
    'bash -c "cat > x.sh <<\'EOF\'\ngit push origin master\nEOF" && sh x.sh',
    "sh -c 'cat > x.sh <<EOF\ngit push origin master\nEOF\n' ; sh x.sh",
    'echo "$(cat > x.sh <<\'EOF\'\ngit push origin master\nEOF\n)"; sh x.sh',
    'printf \'%s\' "$(cat > x.sh <<\'EOF\'\ngit push origin master\nEOF\n)" && sh x.sh',
    'git commit -m "$(cat > x.sh <<\'EOF\'\ngit push origin master\nEOF\n)" ; sh x.sh',
    "echo `cat > x.sh <<'EOF'\ngit push origin master\nEOF\n`; sh x.sh",
    "cat >(cat > x.sh <<'EOF'\ngit push origin master\nEOF\n) ; sh x.sh",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\ncat x.sh >/dev/fd/1",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\ncat x.sh >&3 3>.git/hooks/pre-commit",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\ncat x.sh >& .git/hooks/pre-commit",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\ncat x.sh 1<>.git/hooks/pre-commit",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\ncat x.sh >/proc/self/fd/1",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\nLS_COLORS=x ls",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\nprintf -v BASH_ENV x.sh",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\nprintf -v PATH .",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\nalias echo=sh; echo x.sh",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\necho() { sh x.sh; }; echo",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\nenable -n echo; echo x.sh",
    "cat > echo <<'EOF'\ngit push origin master\nEOF\necho hi",
    "cat > ./bin/cat <<'EOF'\ngit push origin master\nEOF\nPATH=./bin cat",
    "cat > /dev/fd/3 3>x.sh <<'EOF'\ngit push origin master\nEOF\ncat x.sh",
    "cat > /proc/self/fd/1 <<'EOF'\ngit push origin master\nEOF\ntrue",
    "cat > x.sh <<'EOF'\ngit push origin master\nEOF\nrg -n 'a' --pre ./x.sh",
    "cat > x.rc <<'EOF'\ngit push origin master\nEOF\nRIPGREP_CONFIG_PATH=x.rc rg a",
    "cat > ~/.ssh/rc <<'EOF'\ngit push origin master\nEOF",
    "cat > ~/.config/fish/config.fish <<'EOF'\ngit push origin master\nEOF",
    "cat > .vscode/tasks.json <<'EOF'\ngit push origin master\nEOF",
    "cat > .claude/settings.json <<'EOF'\ngit push origin master\nEOF",
    "cat > ~/.claude/settings.json <<'EOF'\ngit push origin master\nEOF",
    "cat > .pre-commit-config.yaml <<'EOF'\ngit push origin master\nEOF",
    "cat > .GiT/HoOkS/pre-commit <<'EOF'\ngit push origin master\nEOF",
    "cat > ~/.CONFIG/Git/config <<'EOF'\ngit push origin master\nEOF",
    "cat > ~/.config/git/attributes <<'EOF'\ngit push origin master\nEOF",
    "cat > .git/../.git/hooks/x <<'EOF'\ngit push origin master\nEOF",
    "cat > g/hooks/pre-commit <<'EOF'\ngit push origin master\nEOF",
]

# Every redirection that may write a file, on any descriptor, names a written
# path the destination rule checks: the last redirection of fd 1 wins.
WRITE_FORMS = [
    _doc("cat > docs/x <<'EOF' " + form)
    for form in ("1<>.git/config", "<>.git/config", "2<>.git/config", ">&.git/config",
                 ">& .git/config", "1>&.git/config", "&>.git/config", "&>>.git/config",
                 "1>|.git/config", "3>.git/config")
]

# Allowed at base too, closed on the way.
BASE_GAPS = [
    "git grep -O\"sh -c 'git push origin master'\" foo",
    "git grep --open-files-in-pager=\"sh -c 'git push origin master'\" foo",
    "printf '%s' 'git push origin master' | sh",
    "echo -e 'git\\x20push origin master' | sh",
    "printf 'git\\040push origin master' | sh",
    "sh <<< 'git push origin master'",
    "cat <<< 'git push origin master' | sh",
]

MUST_REFUSE += REGRESSIONS + WRITTEN_AND_RUN + VERIFIER_L10_L11 + VERIFIER_L12_L13 + WRITE_FORMS + BASE_GAPS

# less with LESSOPEN runs any body; each is a git invocation the guard reads.
LESS_BODIES = ["git reset --hard origin/master", "git branch -D master", "git commit -qam x"]


@pytest.mark.parametrize("body", LESS_BODIES)
def test_less_with_a_preprocessor_runs_its_input(body):
    for head in ("cat <<'EOF' | LESSOPEN='|-sh %s' less", "LESSOPEN='|-sh %s' less <<'EOF'"):
        invocations, residuals = classify_git_command(head + NL + body + NL + "EOF")
        assert [inv.subcommand for inv in invocations] == [body.split()[1]] or residuals, head


def pushes(command):
    invocations, residuals = classify_git_command(command)
    return [inv.subcommand for inv in invocations if inv.subcommand in ("push", "reset")], residuals


@pytest.mark.parametrize("command", MUST_PASS + COMMIT_MESSAGES)
def test_text_is_not_read_as_a_git_invocation(command):
    found, residuals = pushes(command)
    assert found == [] and residuals == [], (found, residuals)


@pytest.mark.parametrize("command", MUST_REFUSE)
def test_code_is_still_read_as_a_git_invocation(command):
    found, residuals = pushes(command)
    assert found or residuals, command


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
    return repo, env


def _run(hook, command, repo, env, subagent):
    payload = {"session_id": "text-owner-0001", "tool_name": "Bash",
               "tool_input": {"command": command}, "cwd": str(repo),
               "hook_event_name": "PreToolUse", "transcript_path": "",
               "permission_mode": "default"}
    if subagent:
        payload.update(agent_id="agent-text-owner", agent_type="general-purpose")
    return subprocess.run([sys.executable, "-B", str(hook)], input=json.dumps(payload),
                          text=True, capture_output=True, cwd=str(repo), env=env, timeout=120)


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_hooks_let_text_through(tmp_path, subagent):
    repo, env = _sandbox(tmp_path)
    for command in MUST_PASS:
        for hook in (GUARD,):
            proc = _run(hook, command, repo, env, subagent)
            assert proc.returncode == 0, (hook.name, command, proc.stderr)


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_guard_still_refuses_code(tmp_path, subagent):
    repo, env = _sandbox(tmp_path)
    for command in MUST_REFUSE:
        proc = _run(GUARD, command, repo, env, subagent)
        assert proc.returncode == 2, (command, proc.stdout, proc.stderr)
        assert "BLOCKED" in proc.stderr, (command, proc.stderr)
