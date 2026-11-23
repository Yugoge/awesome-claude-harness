"""OB-L16: a mention of session_dirs.txt is no longer refused as a search pattern or in a commit message;
reading, writing or executing the file stays refused at the permission layer.

Root cause: the single deny `Bash(*session_dirs.txt*)` matched any command whose text names the file, so
`grep -rn session_dirs.txt docs/`, `git log -S session_dirs.txt` and a commit message naming it were
refused with the reads. The owner decided (L16) to allow the name as a grep / rg / git grep pattern, as a
`git log -S`/`-G` pickaxe and inside a commit message.

An allow entry cannot do that: "Rules are evaluated in order: deny, then ask, then allow ... An allow
rule can't carve an exception out of a deny rule" (code.claude.com/docs/en/permissions.md, "Manage
permissions"). So the blanket is replaced by deny entries keyed on the command word (STEMS): each
interpreter, shell, evaluator, pager, editor and file-touching command, and each git form that reads,
writes or stages a path, refuses a text that spells the file's name or a glob of it. Two tails per stem
(TAILS): `session_dirs.t*` (the name, `.tx?`, `.t*`, a `'session_dirs.t'+'xt'` split) and
`session_dirs?*` (a `?` glob in place of the dot); neither matches a mere `session_dirs` substring
(`hooks/lib/session_dirs.py`, `tests/test_session_dirs_permission.py`, `/tmp/session_dirs_backup`), so
those keep their base decision (BASE_KEPT). grep, rg, `git grep`, `git log -S`/`-G` and `git commit -m`
are left to `Read(**/session_dirs.txt)` and `Edit(**/session_dirs.txt)`, which "apply to ... file
commands Claude Code recognizes in Bash ... and to the targets of Bash redirections" (same page, "What
Read and Edit rules cover"): a file operand or `-f FILE` stays refused, a pattern does not.

Bash rule matching is modelled after the docs ("Bash rules match the whole command text, with `*`
standing in for any text"; "Deny and ask rules apply when any subcommand matches them, including a
command nested inside a subshell, a command substitution, or a control-flow body"; a deny rule "matches
past any leading assignment"; wrappers such as timeout are stripped). Where the docs are silent the point
was measured on Claude Code 2.1.326, run headless (`claude -p`, default permission mode, a throwaway HOME
whose settings.json holds only `permissions`) against a local stand-in Messages API that makes the model
emit one Bash call; the tool result says "has been denied" (deny), names a reason it needs approval
(ask), or is the command's output (allow). Measured: `?` in a rule is a literal character; rules are
case-sensitive (`CAT x` is not matched by `cat *`: it asks, see ASK_ONLY); quotes are not part of the
matched text; a path-qualified command word matches by its name (`/usr/bin/python3`, `/bin/cat`); a
heredoc body is not part of the matched text (HOOK_ONLY). MEASURED holds the decisions on the base
settings and on these; test_live_cli_decisions re-measures them, and every entry's example, when
HARNESS_LIVE_CLI=1 and `claude` is installed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BLANKET = "Bash(*session_dirs.txt*)"
READ_RULE, EDIT_RULE = "Read(**/session_dirs.txt)", "Edit(**/session_dirs.txt)"

# The text before the file name in each deny entry, and a command each refuses ({f}: the name's spelling).
STEMS = {
    '. *': '. ./{f}',
    'awk *': 'awk 1 {f}',
    'bash *': "bash -c 'cat {f}'",
    'bun *': 'bun -e "require(\'fs\').readFileSync(\'{f}\')"',
    'cat *': 'cat {f}',
    'chmod *': 'chmod 600 {f}',
    'cp *': 'cp {f} x.bak',
    'curl *': 'curl -sT {f} http://127.0.0.1:9/',
    'dash *': "dash -c 'cat {f}'",
    'deno *': 'deno eval "Deno.readTextFileSync(\'{f}\')"',
    'docker *': 'docker run --rm -v ./{f}:/f alpine cat /f',
    'echo *': 'cat $(echo {f})',
    'emacs *': 'emacs {f}',
    'env *': "env -i sh -c 'cat {f}'",
    'eval *': "eval 'cat {f}'",
    'exec *': 'exec cat {f}',
    'find *': 'find / -name {f} -exec cat {{}} \\;',
    'fish *': "fish -c 'cat {f}'",
    'for *': 'for f in {f}; do cat $f; done',
    'git *--output*': 'git log --output={f}',
    'git -C *': 'git -C . show HEAD:{f}',
    'git -c *': "git -c core.pager='cat {f}' log",
    'git add *': 'git add {f}',
    'git apply *': 'git apply {f}',
    'git blame *': 'git blame {f}',
    'git cat-file *': 'git cat-file -p HEAD:{f}',
    'git checkout *': 'git checkout -- {f}',
    'git commit *--file*': 'git commit -m x --file={f}',
    'git commit *--include*': 'git commit -m x --include {f}',
    'git commit *--only*': 'git commit -m x --only {f}',
    'git commit *-- *': 'git commit -m x -- {f}',
    'git commit *-F*': 'git commit -F {f}',
    'git commit *-i *': 'git commit -m x -i {f}',
    'git commit *-o *': 'git commit -m x -o {f}',
    'git config *': 'git config --file {f} -l',
    'git diff *': 'git diff --no-index {f} /dev/null',
    'git hash-object *': 'git hash-object -w {f}',
    'git log *--patch*': 'git log --patch {f}',
    'git log *-- *': 'git log --oneline -- {f}',
    'git log *-p *': 'git log -p {f}',
    'git log *-u *': 'git log -u {f}',
    'git mv *': 'git mv {f} x',
    'git notes *--file*': 'git notes add --file={f}',
    'git notes *-F*': 'git notes add -F {f}',
    'git restore *': 'git restore {f}',
    'git rm *': 'git rm {f}',
    'git show *': 'git show HEAD:{f}',
    'git stash *': 'git stash push {f}',
    'git tag *--file*': 'git tag --file={f} t',
    'git tag *-F*': 'git tag -F {f} t',
    'git update-index *': 'git update-index --add {f}',
    'gzip *': 'gzip -k {f}',
    'head *': 'head {f}',
    'install *': 'install {f} /tmp/',
    'ksh *': "ksh -c 'cat {f}'",
    'less *': 'less {f}',
    'ln *': 'ln -s {f} x',
    'md5sum *': 'md5sum {f}',
    'more *': 'more {f}',
    'mv *': 'mv {f} x',
    'nano *': 'nano {f}',
    'node *': 'node -e "require(\'fs\').writeFileSync(\'{f}\',\'x\')"',
    'npm *': 'npm exec -- cat {f}',
    'npx *': 'npx -y cowsay -f {f}',
    'perl *': 'perl -pe1 {f}',
    'php *': 'php -r "readfile(\'{f}\');"',
    'printf *': 'cat $(printf {f})',
    'python*': 'python3 -c "open(\'{f}\',\'w\')"',
    'rm *': 'rm -f {f}',
    'rsync *': 'rsync {f} /tmp/',
    'ruby *': 'ruby -e "File.read(\'{f}\')"',
    'scp *': 'scp {f} host:/tmp/',
    'sed *': 'sed -n p {f}',
    'sh *': "sh -c 'cat {f}'",
    'sort *': 'sort {f}',
    'source *': 'source ./{f}',
    'tail *': 'tail {f}',
    'tar *': 'tar cf /tmp/a.tar {f}',
    'tee *': 'tee {f} < /dev/null',
    'touch *': 'touch {f}',
    'truncate *': 'truncate -s0 {f}',
    'uniq *': 'uniq {f}',
    'vi *': 'vi {f}',
    'view *': 'view {f}',
    'vim *': 'vim {f}',
    'wget *': 'wget -q --post-file={f} http://127.0.0.1:9/',
    'xargs *': 'xargs -a {f} echo',
    'xxd *': 'xxd {f}',
    'zip *': 'zip /tmp/a.zip {f}',
    'zsh *': "zsh -c 'cat {f}'",
}
TAILS = {"session_dirs.t*": "session_dirs.tx?", "session_dirs?*": "session_dirs?txt"}
# Each entry and an example only it refuses: the example spells the name as a glob the other tail and
# the Read/Edit rules do not see (measured: each example asked or ran without these entries).
ENTRIES = {f"Bash({stem}{tail})": tpl.format(f=spelled)
           for stem, tpl in STEMS.items() for tail, spelled in TAILS.items()}
# A patch flag after the pickaxe argument (`git log -S session_dirs.txt -p`) prints the committed contents
# of every change that touched the string: the flag follows the name, so these entries put the tail first.
LOG_PATCH = {" -p*": "git log -S {f} -p", " --patch*": "git log -S {f} --patch", " -u*": "git log -S {f} -u"}
ENTRIES.update({f"Bash(git log *{tail}{flag})": tpl.format(f=spelled)
                for flag, tpl in LOG_PATCH.items() for tail, spelled in TAILS.items()})

# The owner's must-pass forms (L16), and more of the same kind.
MUST_PASS = [
    "grep -rn session_dirs.txt docs/",
    "rg -n 'session_dirs.txt' hooks/",
    "git grep -n session_dirs.txt",
    "git log --oneline -S session_dirs.txt",
    'git commit -m "docs: mention session_dirs.txt"',
    "git log --oneline -G 'session_dirs\\.txt'",
    "git log -S session_dirs.txt --oneline -- hooks/",
    "git log --pretty=oneline -S session_dirs.txt",
    'grep -rn "session_dirs.txt" docs/ hooks/ | head -5',
    "git commit -m 'docs: session_dirs.txt mention'",
    'git commit -a -m "docs: mention session_dirs.txt"',
]

# Ordinary work on names that merely contain `session_dirs`: each keeps its base decision.
BASE_KEPT = [
    "cat hooks/lib/session_dirs.py",
    "sed -n 1,20p scripts/session_dirs_util.sh",
    "python3 -m pytest tests/test_session_dirs_permission.py",
    "python3 -m pytest hooks/tests/test_env_configured_defaults.py -k session_dirs_ban_stays",
    "git add tests/test_session_dirs_permission.py",
    "git diff -- tests/test_session_dirs_permission.py",
    "git show HEAD:tests/test_session_dirs_permission.py",
    "head -40 tests/test_session_dirs_permission.py",
    "echo session_dirs",
    "rm -f /tmp/session_dirs_backup",
    "cp tests/test_session_dirs_permission.py /tmp/x.py",
]

# The audit's must-still-refuse examples (L16) and the layer that refuses each after the change: a Bash
# entry, or the Read/Edit rule on a file operand, `-f FILE` or a redirect target.
MUST_REFUSE = {
    "cat session_dirs.txt": [READ_RULE, "Bash(cat *session_dirs.t*)"],
    "grep -f session_dirs.txt x": [READ_RULE],
    "python3 -c \"open('session_dirs.txt','w')\"": ["Bash(python*session_dirs.t*)"],
    "bash -c 'cat session_dirs.txt'": ["Bash(bash *session_dirs.t*)"],
    "find / -name session_dirs.txt -exec cat {} \\;": ["Bash(find *session_dirs.t*)"],
    "cat $(echo session_dirs.txt)": ["Bash(cat *session_dirs.t*)", "Bash(echo *session_dirs.t*)"],
    "cat session_dirs.tx?": ["Bash(cat *session_dirs.t*)"],
    "echo x > session_dirs.txt": [EDIT_RULE, "Bash(echo *session_dirs.t*)"],
    "rg -f session_dirs.txt x": [READ_RULE],
    "grep pat session_dirs.txt": [READ_RULE],
}

# Denied on the base, allowed or only prompted by an earlier cut of this change; each denied again.
REGAINED = [
    "git log -p -- session_dirs.txt", "git log --patch -- session_dirs.txt", "git log -p session_dirs.txt",
    "git commit -m \"x\" -- session_dirs.txt", "git commit -m x -i session_dirs.txt",
    "git commit -m x -o session_dirs.txt", "git commit -a -m x -- session_dirs.txt",
    "less session_dirs.txt", "more session_dirs.txt", "xxd session_dirs.txt", "vi session_dirs.txt",
    "vim session_dirs.txt", "nano session_dirs.txt", "tar cf /tmp/a.tar session_dirs.txt",
    "rsync session_dirs.txt /tmp/", "install session_dirs.txt /tmp/",
    "git -C . show HEAD:session_dirs.txt", "git -C . diff -- session_dirs.txt",
    "git -C . add session_dirs.txt", "git -C . log -p -- session_dirs.txt",
    "git log -S session_dirs.txt -p", "git log -S session_dirs.txt --patch", "git log -S session_dirs.txt -u",
    "git log -G session_dirs.txt -p", "git notes add -F session_dirs.txt", "git notes add --file=session_dirs.txt",
    "git tag -F session_dirs.txt t", "git tag --file=session_dirs.txt t", "git config --file session_dirs.txt -l",
    "git config -f session_dirs.txt -l",
]

# Refused on the base, not denied now, by choice (ledger S-018):
# - a bare pathspec after the message cannot be told from the message, since quotes are not part of the
#   matched text; it commits only a file already tracked, and `git add` of it is denied;
# - an upper-case command word (rules are case-sensitive): it asks;
# - git with a global option before the subcommand, or a subcommand without a stem: it asks.
NOT_DENIED_NOW = {
    "git commit -m x session_dirs.txt": "allow",
    "CAT session_dirs.txt": "ask",
    "git -p log -p -- session_dirs.txt": "ask",
    "git --no-pager log -p -- session_dirs.txt": "ask",
    "git whatchanged -p -- session_dirs.txt": "ask",
    "git format-patch -1 -- session_dirs.txt": "ask",
    "git archive HEAD session_dirs.txt": "ask",
    "git difftool -- session_dirs.txt": "ask",
}

# The permission layer lets these through on the base and after alike: a heredoc body is not in the matched
# text; only hooks/pretool-bash-safety.sh refuses them. The rest name the file through a glob no rule
# here spells (grep's file operand, `session_dirs*`, `session_dir?.txt`, ...) or build the name at run time.
HOOK_ONLY = [
    "bash <<'EOF'\ncat session_dirs.txt\nEOF",
    "python3 - <<'EOF'\nopen('session_dirs.txt','w')\nEOF",
]
NO_LAYER = ["grep pat session_dirs.tx?", "cat session_dirs*", "cat session_dir?.txt", "cat session_*.txt",
            "python3 -c \"open('session_dirs'+'.txt').read()\""]

# Claude Code 2.1.326's decisions (method in the module docstring): base = origin/claude/train-c's
# settings.json, after = this one.
MEASURED = {  # command: (base, after)
    'grep -rn session_dirs.txt docs/': ('deny', 'allow'),
    'git log --oneline -S session_dirs.txt': ('deny', 'allow'),
    "rg -n 'session_dirs.txt' hooks/": ('deny', 'allow'),
    'git grep -n session_dirs.txt': ('deny', 'allow'),
    'git commit -m "docs: mention session_dirs.txt"': ('deny', 'allow'),
    'cat session_dirs.txt': ('deny', 'deny'),
    'grep -f session_dirs.txt x': ('deny', 'deny'),
    'python3 -c "open(\'session_dirs.txt\',\'w\')"': ('deny', 'deny'),
    "bash -c 'cat session_dirs.txt'": ('deny', 'deny'),
    'find / -name session_dirs.txt -exec cat {} \\;': ('deny', 'deny'),
    'cat $(echo session_dirs.txt)': ('deny', 'deny'),
    'cat session_dirs.tx?': ('allow', 'deny'),
    'cat hooks/lib/session_dirs.py': ('allow', 'allow'),
    'sed -n 1,20p scripts/session_dirs_util.sh': ('allow', 'allow'),
    'python3 -m pytest tests/test_session_dirs_permission.py': ('allow', 'allow'),
    'python3 -m pytest hooks/tests/test_env_configured_defaults.py -k session_dirs_ban_stays': ('allow', 'allow'),
    'git add tests/test_session_dirs_permission.py': ('allow', 'allow'),
    'git diff -- tests/test_session_dirs_permission.py': ('allow', 'allow'),
    'git show HEAD:tests/test_session_dirs_permission.py': ('allow', 'allow'),
    'head -40 tests/test_session_dirs_permission.py': ('allow', 'allow'),
    'echo session_dirs': ('allow', 'allow'),
    'rm -f /tmp/session_dirs_backup': ('ask', 'ask'),
    'git diff HEAD~1 -- hooks/tests/test_obligation.py': ('allow', 'allow'),
    'cp tests/test_session_dirs_permission.py /tmp/x.py': ('ask', 'ask'),
    'less session_dirs.txt': ('deny', 'deny'),
    'od -c session_dirs.txt': ('deny', 'deny'),
    'xxd session_dirs.txt': ('deny', 'deny'),
    'strings session_dirs.txt': ('deny', 'deny'),
    'cut -c1-80 session_dirs.txt': ('deny', 'deny'),
    'nl session_dirs.txt': ('deny', 'deny'),
    'wc -l session_dirs.txt': ('deny', 'deny'),
    'diff session_dirs.txt /dev/null': ('deny', 'deny'),
    'base64 session_dirs.txt': ('deny', 'deny'),
    'tac session_dirs.txt': ('deny', 'deny'),
    'jq . session_dirs.txt': ('deny', 'deny'),
    'grep -c "" session_dirs.txt': ('deny', 'deny'),
    'rg -f session_dirs.txt x': ('deny', 'deny'),
    'git grep -f session_dirs.txt': ('deny', 'deny'),
    'git log -p -- session_dirs.txt': ('deny', 'deny'),
    'git -C . show HEAD:session_dirs.txt': ('deny', 'deny'),
    '/bin/cat session_dirs.txt': ('deny', 'deny'),
    'command cat session_dirs.txt': ('deny', 'deny'),
    'timeout 5 cat session_dirs.txt': ('deny', 'deny'),
    'CAT session_dirs.txt': ('deny', 'ask'),
    'python session_dirs.txt': ('deny', 'deny'),
    'vi session_dirs.txt': ('deny', 'deny'),
    'tar cf /tmp/a.tar session_dirs.txt': ('deny', 'deny'),
    'rsync session_dirs.txt /tmp/': ('deny', 'deny'),
    'install session_dirs.txt /tmp/': ('deny', 'deny'),
    'paste session_dirs.txt': ('deny', 'deny'),
    'while read l; do echo $l; done < session_dirs.txt': ('ask', 'ask'),
    'git commit -m "x" -- session_dirs.txt': ('deny', 'deny'),
    'cat session_dirs.t*': ('allow', 'deny'),
    'cat session_dirs*': ('allow', 'allow'),
    'cat session_dir?.txt': ('allow', 'allow'),
    'cat session_*.txt': ('allow', 'allow'),
    'python3 -c "open(\'session_dirs.t\'+\'xt\').read()"': ('allow', 'deny'),
    'cat session_dirs.txt.bak': ('deny', 'deny'),
    'echo x > session_dirs.txt': ('deny', 'deny'),
    'grep pat session_dirs.txt': ('deny', 'deny'),
    "git log --oneline -G 'session_dirs\\.txt'": ('allow', 'allow'),
    'git log -S session_dirs.txt --oneline -- hooks/': ('deny', 'allow'),
    'grep -rn "session_dirs.txt" docs/ hooks/ | head -5': ('deny', 'allow'),
    "git commit -m 'docs: session_dirs.txt mention'": ('deny', 'allow'),
    '/usr/bin/python3 -c "open(\'session_dirs.txt\',\'w\')"': ('deny', 'deny'),
    '/tmp/x-venv/bin/python -c "open(\'session_dirs.txt\',\'w\')"': ('deny', 'deny'),
    'env python3 -c "open(\'session_dirs.txt\',\'w\')"': ('deny', 'deny'),
    'timeout 5 python3 -c "open(\'session_dirs.txt\',\'w\')"': ('deny', 'deny'),
    'FOO=1 python3 -c "open(\'session_dirs.txt\',\'w\')"': ('deny', 'deny'),
    "sh -c 'cat session_dirs.txt'": ('deny', 'deny'),
    "bash <<'EOF'\ncat session_dirs.txt\nEOF": ('allow', 'allow'),
    "python3 - <<'EOF'\nopen('session_dirs.txt','w')\nEOF": ('allow', 'allow'),
    'cd docs && python3 -c "open(\'session_dirs.txt\',\'w\')"': ('deny', 'deny'),
    "awk '{print}' session_dirs.txt": ('deny', 'deny'),
    'node -e "require(\'fs\').writeFileSync(\'session_dirs.txt\',\'x\')"': ('deny', 'deny'),
    'xargs -a session_dirs.txt echo': ('deny', 'deny'),
    'git add session_dirs.txt': ('deny', 'deny'),
    'git show HEAD:session_dirs.txt': ('deny', 'deny'),
    'git log --output=session_dirs.txt': ('deny', 'deny'),
    'git commit -F session_dirs.txt': ('deny', 'deny'),
    'git commit -m x --file=session_dirs.txt': ('deny', 'deny'),
    'cp session_dirs.txt /tmp/x': ('deny', 'deny'),
    'md5sum session_dirs.txt': ('deny', 'deny'),
    'grep pat session_dirs.tx?': ('allow', 'allow'),
    'for f in session_dirs.tx?; do cat $f; done': ('ask', 'deny'),
    'git log --patch -- session_dirs.txt': ('deny', 'deny'),
    'git log -p session_dirs.txt': ('deny', 'deny'),
    'git log -- session_dirs.txt': ('deny', 'deny'),
    'git commit -m x -- session_dirs.txt': ('deny', 'deny'),
    'git commit -m x -i session_dirs.txt': ('deny', 'deny'),
    'git commit -m x -o session_dirs.txt': ('deny', 'deny'),
    'git commit -a -m x -- session_dirs.txt': ('deny', 'deny'),
    'git commit -a -m "docs: mention session_dirs.txt"': ('deny', 'allow'),
    'git commit -m x session_dirs.txt': ('deny', 'allow'),
    'git -C . diff -- session_dirs.txt': ('deny', 'deny'),
    'git -C . add session_dirs.txt': ('deny', 'deny'),
    'git -C . log -p -- session_dirs.txt': ('deny', 'deny'),
    'more session_dirs.txt': ('deny', 'deny'),
    'vim session_dirs.txt': ('deny', 'deny'),
    'nano session_dirs.txt': ('deny', 'deny'),
    'git log --pretty=oneline -S session_dirs.txt': ('deny', 'allow'),
    'git log -S session_dirs.txt -p': ('deny', 'deny'),
    'cat session_dirs?txt': ('allow', 'deny'),
    'python3 -c "open(\'session_dirs\'+\'.txt\').read()"': ('allow', 'allow'),
    'git log -S session_dirs.txt --patch': ('deny', 'deny'),
    'git log -S session_dirs.txt -u': ('deny', 'deny'),
    'git log -G session_dirs.txt -p': ('deny', 'deny'),
    'git notes add -F session_dirs.txt': ('deny', 'deny'),
    'git notes add --file=session_dirs.txt': ('deny', 'deny'),
    'git tag -F session_dirs.txt t': ('deny', 'deny'),
    'git tag --file=session_dirs.txt t': ('deny', 'deny'),
    'git config --file session_dirs.txt -l': ('deny', 'deny'),
    'git config -f session_dirs.txt -l': ('deny', 'deny'),
    'git -p log -p -- session_dirs.txt': ('deny', 'ask'),
    'git --no-pager log -p -- session_dirs.txt': ('deny', 'ask'),
    'git whatchanged -p -- session_dirs.txt': ('deny', 'ask'),
    'git format-patch -1 -- session_dirs.txt': ('deny', 'ask'),
    'git archive HEAD session_dirs.txt': ('deny', 'ask'),
    'git difftool -- session_dirs.txt': ('deny', 'ask'),
}

WRAPPERS = {"timeout", "time", "nice", "nohup", "stdbuf", "command", "builtin", "noglob"}


def _deny(settings: Path = REPO / "settings.json") -> list[str]:
    """settings.json's own entries, and for the shipped file the hook rule's (policies/cli-deny.v1.json)."""
    own = json.loads(settings.read_text(encoding="utf-8"))["permissions"]["deny"]
    if settings != REPO / "settings.json":
        return own
    return own + json.loads((REPO / "policies" / "cli-deny.v1.json").read_text(encoding="utf-8"))["deny"]


def bash_rule_matches(entry: str, text: str) -> bool:
    """`*` is any text; everything else, `?` included, is literal and case-sensitive (measured)."""
    rule = entry[5:-1]
    if rule.endswith(":*"):
        rule = rule[:-2] + " *"
    return re.fullmatch(".*".join(re.escape(p) for p in rule.split("*")), text, re.S) is not None


def texts(cmd: str) -> list[str]:
    """The texts a deny rule is checked against, as modelled: the whole command, each subcommand at the
    documented separators, each `$(...)` body, leading assignments and wrappers stripped, a path-qualified
    command word reduced to its name; each with and without quotes. A superset of what the CLI matches,
    so a must-pass command that no entry matches here is matched by none there. A heredoc body is dropped
    first: the CLI does not match it (measured)."""
    cmd = re.sub(r"(<<-?\s*['\"]?(\w+)['\"]?[^\n]*)\n.*?\n\2(?=\n|$)", r"\1", cmd, flags=re.S)
    out, todo = [], [cmd] + re.findall(r"\$\(([^()]*)\)", cmd)
    for t in todo:
        for part in re.split(r"\|\||&&|\|&|[;|&\n]", t):
            words = part.split()
            while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in WRAPPERS):
                words = words[1:] if words[0] not in ("timeout",) else words[2:]
            if not words:
                continue
            words[0] = words[0].rsplit("/", 1)[-1] or words[0]
            s = " ".join(words)
            out += [part.strip(), s, s.replace('"', "").replace("'", "")]
    return out + [cmd, cmd.replace('"', "").replace("'", "")]


def bash_denies(deny: list[str], cmd: str) -> list[str]:
    return [e for e in deny if e.startswith("Bash(") and any(bash_rule_matches(e, t) for t in texts(cmd))]

# ------------------------------------------------------------------ the entries
def test_the_blanket_mention_deny_is_gone_and_the_file_rules_stay():
    deny = _deny()
    assert BLANKET not in deny
    assert READ_RULE in deny and EDIT_RULE in deny


def test_the_session_dirs_bash_entries_are_exactly_these():
    assert sorted(e for e in _deny() if "session_dirs" in e and e.startswith("Bash(")) == sorted(ENTRIES)


@pytest.mark.parametrize("entry", sorted(ENTRIES))
def test_each_entry_refuses_its_example_and_no_search_commit_or_lookalike_form(entry):
    assert entry in _deny()
    assert any(bash_rule_matches(entry, t) for t in texts(ENTRIES[entry])), ENTRIES[entry]
    others = [e for e in ENTRIES if e != entry]
    assert not any(bash_rule_matches(e, t) for e in others for t in texts(ENTRIES[entry])
                   if e.split("session_dirs")[0] == entry.split("session_dirs")[0]), "the two tails overlap"
    hit = [c for c in MUST_PASS + BASE_KEPT if any(bash_rule_matches(entry, t) for t in texts(c))]
    assert not hit, f"{entry} matches {hit}"


# ------------------------------------------------------------------ must pass / must refuse
@pytest.mark.parametrize("cmd", MUST_PASS)
def test_a_mention_as_search_pattern_or_commit_message_passes(cmd):
    assert not bash_denies(_deny(), cmd)
    assert MEASURED[cmd][1] == "allow"


def test_the_blanket_is_what_refused_the_mentions():
    """Red side: on the base the blanket matched every must-pass form except the `-G` regex spelling."""
    for cmd in MUST_PASS:
        assert bash_rule_matches(BLANKET, cmd) == (MEASURED[cmd][0] == "deny"), cmd


@pytest.mark.parametrize("cmd", BASE_KEPT)
def test_a_name_that_merely_contains_session_dirs_keeps_its_base_decision(cmd):
    assert not bash_denies(_deny(), cmd)
    assert MEASURED[cmd][1] == MEASURED[cmd][0] != "deny"


@pytest.mark.parametrize("cmd", sorted(MUST_REFUSE))
def test_reading_writing_or_executing_stays_refused(cmd):
    deny = _deny()
    for layer in MUST_REFUSE[cmd]:
        assert layer in deny, layer
        if layer.startswith("Bash("):
            assert any(bash_rule_matches(layer, t) for t in texts(cmd)), (layer, cmd)
    assert MEASURED[cmd][1] == "deny"


@pytest.mark.parametrize("cmd", REGAINED)
def test_a_form_the_base_denied_is_denied_again(cmd):
    assert bash_denies(_deny(), cmd), cmd
    assert MEASURED[cmd] == ("deny", "deny")


def test_every_base_deny_stays_denied_but_the_recorded_exceptions():
    lost = {c: a for c, (b, a) in MEASURED.items() if b == "deny" and a != "deny" and c not in MUST_PASS}
    assert lost == NOT_DENIED_NOW


def test_measured_after_decisions_agree_with_the_model():
    deny = _deny()
    for cmd, (_, after) in MEASURED.items():
        if after == "allow":
            assert not bash_denies(deny, cmd), cmd
        elif after == "deny" and not bash_denies(deny, cmd):
            # a file operand, `-f FILE` or redirect target the CLI recognizes: the Read/Edit rule
            assert READ_RULE in deny and EDIT_RULE in deny, cmd
        elif after == "ask":
            assert not bash_denies(deny, cmd), cmd


def test_hook_only_and_no_layer_forms_are_recorded_as_such():
    """A heredoc body is not in the text the CLI matches (measured), so these stay with the bash-safety
    hook; they were allowed at the permission layer on the base too, as were the globs in NO_LAYER."""
    for cmd in HOOK_ONLY + NO_LAYER:
        assert MEASURED[cmd] == ("allow", "allow"), cmd
        assert not bash_denies(_deny(), cmd), cmd


# ------------------------------------------------------------------ live re-measurement (opt-in)
_MOCK = textwrap.dedent('''
    import json, sys
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    CMD = sys.argv[2]
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _json(self, o):
            b = json.dumps(o).encode(); self.send_response(200)
            self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b)))
            self.end_headers(); self.wfile.write(b)
        def do_GET(self): self._json({"data": [], "has_more": False})
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
            if not self.path.startswith("/v1/messages") or "count_tokens" in self.path:
                return self._json({"input_tokens": 1})
            last = (body.get("messages") or [{}])[-1].get("content")
            done = isinstance(last, list) and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in last)
            tools = any(t.get("name") == "Bash" for t in body.get("tools", []))
            if tools and not done:
                blocks, stop = [{"type": "tool_use", "id": "toolu_1", "name": "Bash",
                                 "input": {"command": open(CMD).read(), "description": "probe"}}], "tool_use"
            else:
                blocks, stop = [{"type": "text", "text": "done"}], "end_turn"
            msg = {"id": "msg_1", "type": "message", "role": "assistant", "model": body.get("model", "m"),
                   "content": blocks, "stop_reason": stop, "stop_sequence": None,
                   "usage": {"input_tokens": 1, "output_tokens": 1}}
            if not body.get("stream"):
                return self._json(msg)
            self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers()
            def ev(t, d): self.wfile.write(("event: %s\\ndata: %s\\n\\n" % (t, json.dumps(d))).encode())
            ev("message_start", {"type": "message_start", "message": dict(msg, content=[], stop_reason=None)})
            for i, b in enumerate(blocks):
                if b["type"] == "text":
                    ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
                    ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": b["text"]}})
                else:
                    ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": dict(b, input={})})
                    ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}})
                ev("content_block_stop", {"type": "content_block_stop", "index": i})
            ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 1}})
            ev("message_stop", {"type": "message_stop"})
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
''')


def _cli_decision(perms: dict, cmd: str, work: Path, port: int, cmdfile: Path) -> str:
    home = Path(tempfile.mkdtemp(dir=work))
    proj = home / "proj"
    (proj / "docs").mkdir(parents=True)
    (proj / "hooks").mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(json.dumps({"permissions": perms}))
    (home / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding": True,
                                                   "projects": {str(proj): {"hasTrustDialogAccepted": True}}}))
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    cmdfile.write_text(cmd)
    env = {"HOME": str(home), "PATH": os.environ["PATH"], "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}",
           "ANTHROPIC_API_KEY": "sk-ant-placeholder", "NO_PROXY": "127.0.0.1,localhost",
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1", "TERM": "dumb"}
    r = subprocess.run(["claude", "-p", "go", "--output-format", "stream-json", "--verbose",
                        "--permission-mode", "default", "--max-turns", "3"],
                       cwd=proj, env=env, capture_output=True, text=True, timeout=180)
    for line in r.stdout.splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        for c in (o.get("message") or {}).get("content", []) if o.get("type") == "user" else []:
            if isinstance(c, dict) and c.get("type") == "tool_result":
                res = c.get("content")
                res = res if isinstance(res, str) else json.dumps(res)
                if "has been denied" in res:
                    return "deny"
                return "allow" if res.startswith("Exit code") or not c.get("is_error") else "ask"
    raise AssertionError(f"no tool result for {cmd!r}: {r.stderr[-400:]}")


def _wait_listening(port: int, limit: float = 60.0) -> None:
    """Wait for the mock server itself: connect until it accepts (the limit is an outer one, reached only by a
    server that never comes up), instead of a pause that stands for "it is listening by now"."""
    end = time.monotonic() + limit
    while True:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=2).close()
            return
        except OSError:
            if time.monotonic() > end:
                raise AssertionError(f"the mock server did not listen on port {port} within {limit:g} s")
            time.sleep(0.05)


@pytest.mark.skipif(os.environ.get("HARNESS_LIVE_CLI") != "1" or not shutil.which("claude"),
                    reason="live CLI re-measurement is opt-in: HARNESS_LIVE_CLI=1 with `claude` installed")
def test_live_cli_decisions(tmp_path):
    perms = dict(json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["permissions"], deny=_deny())
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    (tmp_path / "mock.py").write_text(_MOCK)
    cmdfile = tmp_path / "cmd"
    cmdfile.write_text("true")
    srv = subprocess.Popen([sys.executable, "-I", str(tmp_path / "mock.py"), str(port), str(cmdfile)])
    try:
        _wait_listening(port)
        cases = dict(MEASURED)
        cases.update({ex: (None, "deny") for ex in ENTRIES.values()})
        got = {cmd: _cli_decision(perms, cmd, tmp_path, port, cmdfile) for cmd in cases}
    finally:
        srv.kill()
    wrong = {c: (got[c], cases[c][1]) for c in cases if got[c] != cases[c][1]}
    assert not wrong, wrong
