#!/usr/bin/env python3
"""
PreToolUse Hook: Claude config (.claude/hooks + .claude/commands) protection.

Scope: Runs in EVERY session (NOT scoped to /dev-overnight). Closes the gap
that allowed b5d447e (2026-04-21 17:45 UTC) to silently rewrite four
checkpoint hooks as part of a 93-file sweep. Blocks Edit/Write/Bash
modifications targeting `.claude/hooks/*` and `.claude/commands/*` unless
the per-project sentinel `.claude/.hook-refactor-allow` exists at the
active project root.

Why exists:
  - The orchestrator-gate in `pretool-orchestrator-gate.py` is RATE-based
    (consecutive same-name tool count) and was bypassed at 2026-04-21
    17:44:54 with a Grep streak-reset before commit b5d447e succeeded.
  - This hook is SEMANTIC: it refuses ANY agent-driven edit to the
    config surface unless the user has affirmatively opted in by
    creating the sentinel file.
  - Spec reference: spec-20260424-233926 §5.2.4 (R4.2).
  - Note: Bash redirect regex tightened to ``\\S*`` per spec-20260424-233926
    §5.2.4 Mystery 4 to eliminate false-positives on read-only Bash
    containing `2>&1` together with `.claude/hooks/` in a non-redirect
    position (e.g. a path argument).

Allow-list mechanism: The sentinel file `.claude/.hook-refactor-allow` at
`$CLAUDE_PROJECT_DIR` (or cwd fallback). When present, this hook exits 0
and lets the underlying tool run. The user creates this file by hand
when they want to refactor hooks/commands; deleting it re-engages the
guard. Without it, two writes pass: /dev-command's dev writing the project
command file the cycle develops (_dev_command_product_file), and the cleaner
of an active /clean writing what that /clean's owner approved for it under
commands/ (_clean_approved_edit, _clean_approved_bash; hooks/pretool-tool-policy.py
holds the rule and refuses every other caller's write of those paths).

Exit codes:
  0: Allow tool use
  2: Block tool use

Fail-open: Any uncaught exception during hook evaluation results in
exit 0 — the hook never wedges the harness, even at the cost of skipping
its own check.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import bash_read_only  # noqa: E402 -- the one list of the programs that only read
from lib import locations  # noqa: E402


SENTINEL_NAME = '.hook-refactor-allow'
BLOCK_LITERAL = 'BLOCKED: claude config guard'

# The Bash write shapes the base reading counts as a write into a protected folder, written once for both.
_WRITE_SHAPES = (r'(?:echo|printf)\s+.*>\s*\S*{}', r'cat\s+.*>\s*\S*{}', r'cp\s+.*{}', r'mv\s+.*{}', r'tee\s+.*{}',
                 r'>\s*\S*{}', r'>>\s*\S*{}')
_HOOK_PATTERNS = [shape.format(r'\.claude/hooks/') for shape in _WRITE_SHAPES]
_CMD_PATTERNS = [shape.format(r'\.claude/commands/') for shape in _WRITE_SHAPES]


def _project_dir() -> Path:
    """Return the active project directory."""
    return Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))


def _sentinel_present() -> bool:
    """True iff the allow-list sentinel exists at the project root."""
    return (_project_dir() / '.claude' / SENTINEL_NAME).exists()


def _located_kind(path: str, base=None) -> str:
    """'hooks' or 'commands' when ``path`` (a relative one from ``base``) is or lies in a protected
    folder by where it is: its real path and an account's link count as `~/.claude/` does, and a
    folder that only ends in the text `.claude/hooks/` does not (lib/locations)."""
    return locations.config_folder(path.replace('\\', '/'), base or str(_project_dir())) if path else ''


def _matches_any(command: str, patterns: list) -> bool:
    """True iff command matches any of the regex patterns."""
    return any(re.search(p, command) for p in patterns)


# The harness home and the CLI's config dir named through a variable. The patterns above read raw
# text, so `"${CLAUDE_HOME:-$HOME/.claude}/commands/x.md"` (the spelling the prompts use) or
# `$CLAUDE_HOME/hooks/x.py` names no `.claude/<dir>/` and went through, where `~/.claude/...` is
# refused. Either variable may hold a protected root in the shell that runs the command (an
# assignment earlier in the same command, a profile), whatever the hook's own environment says,
# so each spelling of them counts as the home (fails closed), as an unknown prefix before a
# written-out `.claude/hooks/` is refused today.
_HOME = '~/.claude'
_HOME_VARS = ('CLAUDE_HOME', 'CLAUDE_CONFIG_DIR')
_BARE_HOME_VAR = re.compile(r'\$(?:CLAUDE_HOME|CLAUDE_CONFIG_DIR)(?![A-Za-z0-9_])')
_BRACE = re.compile(r'\$\{|\}')
_PARAMETER = re.compile(r'([A-Za-z_][A-Za-z0-9_]*|[0-9]+)(:?[-=?+])?(.*)\Z', re.S)


def _resolve_parameter(body: str) -> str:
    """The text a `${body}` expansion (its inner expansions resolved) may stand for, as far as it is
    known without running it: a home variable is the home (its `+` forms: the word used when it is
    set); another variable's `-`, `=` and `+` forms are their word (the branch readable here)."""
    found = _PARAMETER.match(body)
    if not found:
        return '${' + body + '}'
    name, op, word = found.groups()
    if name in _HOME_VARS:
        return word if op and op.endswith('+') else _HOME
    if op and op[-1] in '-=+':
        return word
    return '${' + body + '}'


def _expand_parameters(text: str) -> str:
    """``text`` with each balanced `${...}` replaced by _resolve_parameter, innermost first, in one
    pass without recursion (a deep nesting cannot raise and so fail open); an unclosed one stays."""
    stack, i = [[]], 0
    for mark in _BRACE.finditer(text):
        stack[-1].append(text[i:mark.start()])
        i = mark.end()
        if mark.group() == '${':
            stack.append([])
        elif len(stack) > 1:
            body = ''.join(stack.pop())
            stack[-1].append(_resolve_parameter(body))
        else:
            stack[-1].append('}')
    stack[-1].append(text[i:])
    while len(stack) > 1:
        body = ''.join(stack.pop())
        stack[-1].append('${' + body)
    return ''.join(stack[0])


def _home_spelled_out(command: str) -> str:
    """``command`` with the home variables written as ~/.claude and its quotes removed, so a
    home spelling reaches the patterns as `~/.claude/<dir>/` (`"$HOME/.claude"/commands/` too)."""
    text = _BARE_HOME_VAR.sub(lambda _m: _HOME, _expand_parameters(command))
    return text.replace('"', '').replace("'", '')


def _legacy_kind(command: str) -> str:
    """The base reading: 'hooks' or 'commands' when a write word (cp, mv, tee, a redirect) comes
    before a protected folder anywhere in the text, as written or with the home spelled out."""
    for text in dict.fromkeys((command, _home_spelled_out(command))):
        if _matches_any(text, _HOOK_PATTERNS):
            return 'hooks'
        if _matches_any(text, _CMD_PATTERNS):
            return 'commands'
    return ''


# A protected folder named in a path: `.claude/hooks` or `.claude/commands`, as the folder itself or
# anything below it (`cp -t .claude/hooks x`, `--target-directory=.claude/commands`).
_PROTECTED = re.compile(r'\.claude/(hooks|commands)(?![A-Za-z0-9_.-])')
_DOT_SEGMENTS = re.compile(r'/(?:\.?/)+')
_CD = frozenset({'cd', 'pushd', 'popd'})
_FED = frozenset({'pipe', 'heredoc', 'herestring'})
# Text in a word that makes it code or a command line rather than a path (`rsync -e 'cp x ...'`).
_CODE_CHARS = re.compile(r'[\s;|&<>`]|\$\(')

# Commands that write nothing a word of theirs names, whatever the words say (a message, a pattern,
# a file read), are hooks/lib/bash_read_only.py's readers (reads_only, pagers included): a protected
# folder named by one of them is not written.
# Commands that read their standard input as data, never as code: fed a protected folder's name or
# text, they write nothing through it (a write verb's targets come from the parser).
_STDIN_DATA = (bash_read_only.ANY_ARGS | frozenset(bash_read_only.PAGERS)
               | {'printf', 'test', '[', 'file', 'tee', 'sed', 'sort', 'uniq', 'xxd'})
# Commands whose path operands the guard reads (the parser's write verbs and the item-4 readers
# below): a protected folder they name as a plain path is read or is a write target the parser or
# _site_writes finds; one named inside code-looking text (`rsync -e 'cp x ...'`) is not settled.
_OPERAND_COMMANDS = frozenset({'rg', 'ag', 'tar', 'find', 'touch', 'sort', 'zip', 'unzip', 'patch',
                               'perl', 'cd', 'pushd', 'popd'})
_GIT_READS = frozenset({
    'log', 'diff', 'show', 'status', 'blame', 'annotate', 'ls-files', 'ls-tree', 'rev-parse',
    'shortlog', 'describe', 'cat-file', 'commit', 'add', 'grep', 'whatchanged', 'reflog',
    'check-ignore', 'show-ref',
})
_GIT_VALUE_GLOBALS = frozenset({'-C', '--git-dir', '--work-tree', '--namespace'})


def _protected_kind(text: str) -> str:
    """'hooks' or 'commands' when ``text`` (with the home spelled out, `/./` and `//` folded)
    names a protected folder."""
    if not text:
        return ''
    for form in dict.fromkeys((text, _home_spelled_out(text))):
        found = _PROTECTED.search(_DOT_SEGMENTS.sub('/', form.replace('\\', '/')))
        if found:
            return found.group(1)
    return ''


def _shell_parse():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from lib import shell_parse
    return shell_parse


def _site_words(cmd) -> list:
    words = [a.word for a in cmd.assignments] + list(cmd.words)
    return words + [r.target for r in cmd.redirects if r.target is not None]


def _names(raw: str, word) -> bool:
    """Whether ``word`` as written (its substitutions included) names a protected folder."""
    return bool(_protected_kind(word.text))


def _plain(word) -> bool:
    return not _CODE_CHARS.search(word.text)


def _git_settled(res, raw) -> bool:
    """A git call naming a protected folder is settled when it reads (log, diff, a commit message)
    with no `-c` setting, no config or alias, no pager, editor or output option."""
    vals = [w.value() for w in res.args]
    k = 0
    while k < len(vals) and (vals[k] or '').startswith('-'):
        v = vals[k]
        if v in ('-c', '--config-env', '--exec-path') or (v or '').startswith(('-c', '--config-env', '--exec-path=')):
            return False
        k += 2 if v in _GIT_VALUE_GLOBALS else 1
    if k >= len(vals) or vals[k] not in _GIT_READS:
        return False
    for v in vals[k + 1:]:
        if v is None or v.startswith(('--output', '--ext-diff', '-O', '--open-files-in-pager', '--exec')):
            return False
        if v.startswith('--') and any(_long_prefix(v, full, least) for full, least in _GIT_RUN_OPTIONS):
            return False  # an abbreviation (`--outp=`, `--ext-dif`, `--open-files-in=`)
    return True


# git options that write a file or run a program, with the shortest abbreviation git would take.
_GIT_RUN_OPTIONS = (('--output', 5), ('--ext-diff', 5), ('--open-files-in-pager', 4), ('--exec', 5))


def _site_settled(sp, raw: str, site, res, names_any: bool) -> bool:
    """Whether the guard knows every write of this simple command that a protected folder's name in
    it could make: the folder is an operand of a reader, a plain path operand of a command whose
    writes the parser or _site_writes reads, or the code of a payload walked on its own."""
    cmd = site.cmd
    named = [w for w in _site_words(cmd) if _names(raw, w)]
    heredoc = any(r.hd is not None and _protected_kind(r.hd.body) for r in cmd.redirects)
    stdin_code = (names_any and site.fed & _FED and res.payload is None and not res.stdin_shell
                  and res.name not in _STDIN_DATA)
    if stdin_code:
        return False  # code fed to an interpreter, a scheduler, `make -f -`
    if not named and not heredoc:
        return True
    if res.unresolved and not res.unresolved.startswith('xargs_appends'):
        return False
    if res.payload is not None:
        return not res.unresolved  # the payload's own commands are walked and judged
    if any(_names(raw, a.word) and not _plain(a.word) for a in cmd.assignments):
        return False  # a command string in a variable (GIT_EDITOR=..., PAGER=..., c='cp ...')
    if res.head is None:
        return True  # assignments and redirects only: the parser reads their targets
    name = res.name
    if name is None or site.dynamic:
        return False
    if name != 'git' and bash_read_only.reads_only(name, [w.value() for w in res.args], pagers=True):
        return True
    if name == 'git':
        return _git_settled(res, raw)
    if name == 'gh':
        return bool(res.args) and res.args[0].value() in ('pr', 'issue')
    if name in sp.VERBS or name in _OPERAND_COMMANDS:
        if heredoc and name not in _STDIN_DATA:
            return False
        if name == 'sed' and any(_names(raw, w) for w in _sed_scripts(res.args)):
            return False  # a sed script naming the folder: `e`, `w` and `r` commands
        if name == 'perl' and any(_names(raw, w) for w in sp.perl_operands(list(res.args))[1]):
            return False
        return all(_plain(w) for w in named)
    return False


def _sed_scripts(args) -> list:
    """The script words of a sed call: each -e/--expression value, else the first operand."""
    scripts, operands, k = [], [], 0
    while k < len(args):
        v = args[k].value() or ''
        if v in ('-e', '--expression', '-f', '--file') and k + 1 < len(args):
            if v in ('-e', '--expression'):
                scripts.append(args[k + 1])
            k += 2
            continue
        if v.startswith('--expression='):
            scripts.append(args[k])
        elif v.startswith('-e') and len(v) > 2:
            scripts.append(args[k])
        elif not v.startswith('-') or v == '-':
            operands.append(args[k])
        k += 1
    return scripts or operands[:1]


_SED_WRITE = re.compile(r'(?:^|[;{}\n\d$!]|/[gpiImMe0-9]*)\s*[wW]\s*(\S+)')
# perl code that may write the operands it is handed (`open F, ">", shift`, unlink, rename, a shell)
_PERL_WRITE = re.compile(r'open|unlink|rename|system|exec|`|qx|>|mkdir|rmdir|chmod|utime|truncate|link|copy|move|print\s*\{?\s*[A-Z$]')
_FIND_RUN = ('-exec', '-execdir', '-ok', '-okdir')


def _long_prefix(v: str, full: str, least: int) -> bool:
    """Whether ``v`` (before any `=`) is GNU getopt's abbreviation of ``full``: at least ``least``
    characters of it."""
    head = v.split('=', 1)[0]
    return len(head) >= least and full.startswith(head)


def _sed_long_in_place(args, vals) -> list:
    """sed's file operands when an abbreviation of --in-place (`--i`, `--in-pl`) asks for an in-place
    edit; the parser reads only the full spelling."""
    if not any(v.startswith('--') and _long_prefix(v, '--in-place', 3) for v in vals):
        return []
    script, ops, k = False, [], 0
    while k < len(args):
        v = vals[k]
        if v in ('-e', '--expression', '-f', '--file', '-l', '--line-length'):
            script = script or v in ('-e', '--expression', '-f', '--file')
            k += 2
            continue
        if v.startswith(('--expression=', '--file=')) or (v.startswith('-e') and len(v) > 2):
            script = True
        elif not v.startswith('-') or v == '-':
            ops.append(args[k])
        k += 1
    return [(w.value() or w.text, w) for w in (ops if script else ops[1:])]


_TAR_VALUE_LETTERS = 'fCbTXgKNVLH'


def _tar_writes(args, vals, head) -> list:
    """What a tar call writes: the archive (-f, --file and abbreviations, old-style `cf X`) when it
    creates or appends one, and the extraction directory (-C, --directory and abbreviations such as
    `--dir=`, --one-top-level=) when it extracts, the working directory when no -C is given."""
    letters, values, k = '', {}, 0
    first = vals[0] if vals else ''
    if first and not first.startswith('-'):
        letters, k = first, 1
        for c in first:
            if c in _TAR_VALUE_LETTERS and k < len(args):
                values.setdefault(c, []).append((vals[k] or args[k].text, args[k]))
                k += 1
    longs = []
    while k < len(args):
        v = vals[k]
        if v == '--':
            break
        if v.startswith('--'):
            name = v.split('=', 1)[0]
            longs.append(name)
            target = next((full for full, least in (('--file', 4), ('--directory', 5), ('--one-top-level', 4))
                           if _long_prefix(name, full, least)), None)
            if target:
                if '=' in v:
                    values.setdefault(target, []).append((v.split('=', 1)[1], args[k]))
                elif target != '--one-top-level' and k + 1 < len(args):
                    values.setdefault(target, []).append((vals[k + 1] or args[k + 1].text, args[k + 1]))
                    k += 1
        elif v.startswith('-') and len(v) > 1:
            for j, c in enumerate(v[1:], 1):
                letters += c
                if c in _TAR_VALUE_LETTERS:
                    if j < len(v) - 1:
                        values.setdefault(c, []).append((v[j + 1:], args[k]))
                    elif k + 1 < len(args):
                        values.setdefault(c, []).append((vals[k + 1] or args[k + 1].text, args[k + 1]))
                        k += 1
                    break
        k += 1
    creates = bool(set(letters) & set('cru')) or any(
        _long_prefix(n, full, 4) for n in longs for full in ('--create', '--append', '--update'))
    extracts = 'x' in letters or any(_long_prefix(n, '--extract', 4) or n == '--get' for n in longs)
    out = []
    if creates:
        out += values.get('f', []) + values.get('--file', [])
    if extracts:
        dirs = values.get('C', []) + values.get('--directory', [])
        out += dirs + values.get('--one-top-level', [])
        if not dirs and head is not None:
            out.append(('.', head))
    return out


def _site_writes(sp, raw: str, res) -> list:
    """(path text, word) writes of commands the shared parser has no write rule for: perl code that
    writes its operands, patch, tar -x -C, unzip -d, git checkout/apply into a folder, sed's w command, find's -fprint
    family and -delete."""
    name, args = res.name, list(res.args)
    vals = [w.value() or '' for w in args]
    out = []

    def operands(start=0, takes=()):
        k, ops = start, []
        while k < len(args):
            v = vals[k]
            if v == '--':
                ops += args[k + 1:]
                break
            if v in takes:
                k += 2
                continue
            if not v.startswith('-') or v == '-':
                ops.append(args[k])
            k += 1
        return ops

    def option_values(short, long_=None):
        found = []
        for k, v in enumerate(vals):
            if v and v in (short, long_) and k + 1 < len(args):
                found.append((args[k + 1].value() or args[k + 1].text, args[k + 1]))
            elif long_ and v.startswith(long_ + '='):
                found.append((v.split('=', 1)[1], args[k]))
            elif short and v.startswith(short) and len(v) > len(short) and not v.startswith('--'):
                found.append((v[len(short):], args[k]))
        return found

    if name == 'perl':
        _inplace, code, operand_words = sp.perl_operands(args)  # perl -i is the parser's write target
        if any(_PERL_WRITE.search(w.value() or w.text) for w in code):
            out += [(w.value() or w.text, w) for w in operand_words]
    elif name == 'patch':
        ops = operands(takes=('-p', '-d', '--directory', '-o', '--output', '-i', '--input', '-r',
                              '-B', '-z', '-D', '-F', '-V', '-g', '-Y'))
        outputs = option_values('-o', '--output')
        dirs = option_values('-d', '--directory')
        out += [] if outputs else [(w.value() or w.text, w) for w in ops[:1]]  # -o leaves it as is
        out += dirs + outputs
        if not (outputs or dirs or ops) and res.head is not None:
            out.append(('.', res.head))  # the files the diff names, below the working directory
    elif name in sp.TAR_NAMES:
        out += _tar_writes(args, vals, res.head)
    elif name == 'unzip':
        dirs = option_values('-d')
        out += dirs
        listing = any(v.startswith('-') and not v.startswith('--') and set(v[1:]) & set('ltvpcZz') for v in vals)
        if not dirs and not listing and res.head is not None:
            out.append(('.', res.head))
    elif name == 'wget':
        out_opts = sp.WGET_OUTPUT_OPTS
        if not any(v in out_opts or v.startswith((out_opts[0], out_opts[1] + '=')) for v in vals):
            prefix = option_values('-P', '--directory-prefix')
            out += prefix or ([('.', res.head)] if res.head is not None else [])
    elif name == 'git':
        k, cdir = 0, None
        while k < len(vals) and vals[k].startswith('-'):
            if vals[k] == '-C' and k + 1 < len(args):
                cdir = args[k + 1]
            k += 2 if vals[k] in _GIT_VALUE_GLOBALS else 1
        sub = vals[k] if k < len(vals) else ''
        if sub in ('checkout', 'restore', 'apply', 'reset', 'stash', 'clean', 'switch', 'am', 'merge',
                   'pull', 'cherry-pick', 'revert', 'rm', 'mv'):
            if cdir is not None:
                out.append((cdir.value() or cdir.text, cdir))
            if sub in ('checkout', 'restore'):
                out += [(w.value() or w.text, w) for w in args[k + 1:]
                        if not (w.value() or '-').startswith('-')]
            if sub == 'apply':
                out += option_values(None, '--directory')
    elif name == 'sed':
        for w in _sed_scripts(args):
            for found in _SED_WRITE.finditer(w.value() or w.text):
                out.append((found.group(1), w))
        out += _sed_long_in_place(args, vals)
    elif name == 'find':
        starts = []
        for w in args:
            if (w.value() or '-').startswith(('-', '(', '!')):
                break
            starts.append(w)
        for k, v in enumerate(vals):
            if v in ('-fprint', '-fprint0', '-fprintf', '-fls') and k + 1 < len(args):
                out.append((args[k + 1].value() or args[k + 1].text, args[k + 1]))
        runs = [vals[k + 1:k + 1 + next((j for j, x in enumerate(vals[k + 1:]) if x in sp.FIND_EXEC_ENDS), len(vals))]
                for k, v in enumerate(vals) if v in _FIND_RUN and k + 1 < len(vals)]
        if '-delete' in vals or any(not bash_read_only.reads_only(os.path.basename(r[0]), r[1:], pagers=True)
                                    for r in runs):
            # what find removes, or hands to a command that may write it: every start path
            out += [(w.value() or w.text, w) for w in starts]
    return [(text, word) for text, word in out if text]


class _CdScopes:
    """Where each part of the command runs: the possible (cwd, OLDPWD) pairs at each simple command,
    a `cd` applied only to what follows it in its own shell (not past a closing subshell, a pipeline
    stage or a background job, replaced by a later cd, `&&` and `||` followed), relative to the
    starting directory ''. A cd that cannot be followed exactly (`cd -` with no known OLDPWD, a
    computed target, CDPATH, popd, a function body) leaves the unknown directory '?'."""

    UNKNOWN = ('?', '?')

    def __init__(self, sp, raw: str):
        self.sp, self.raw = sp, raw
        self.spans = []
        self.visited = set()
        self.cdpath = 'CDPATH' in raw
        self.functions = False  # a function or coprocess defined anywhere it walked

    def _target(self, cwd: str, word) -> str:
        arg = _home_spelled_out(word.text) if word is not None else '~'
        if any(c in arg for c in '$`*?[') or (self.cdpath and not arg.startswith(('/', '~', './', '../'))):
            return '?'
        if arg.startswith(('/', '~')):
            return os.path.normpath(arg)
        if cwd == '?':
            return '?'
        return os.path.normpath(os.path.join(cwd, arg)) if cwd else os.path.normpath(arg)

    def _cd(self, name: str, args, states) -> set:
        if name == 'popd':
            return {self.UNKNOWN}
        ops, k = [], 0
        while k < len(args):
            v = args[k].value()
            if v == '--':
                ops += args[k + 1:]
                break
            if v is None or v == '-' or not v.startswith('-') or v[1:2].isdigit() or v[1:2] == '+':
                ops.append(args[k])
            k += 1
        new = set()
        for cwd, old in states:
            if ops and ops[0].value() == '-' or (name == 'pushd' and not ops):
                new.add((old, cwd) if old != '?' else ('?', cwd))
            elif ops and (ops[0].value() or '').startswith(('+', '-')):
                new.add(self.UNKNOWN)  # a pushd/cd stack index
            else:
                new.add((self._target(cwd, ops[0] if ops else None), cwd))
        return new

    def _record(self, span, states):
        self.spans.append((span[0], span[1], frozenset(states)))

    def run_cmd(self, cmd, states):
        sp = self.sp
        if isinstance(cmd, sp.SimpleCommand):
            self.visited.add(cmd.span)
            res = sp.resolve(cmd)
            here = set(states)
            for wname, opts in res.wrappers:
                for opt, val in opts:
                    if wname == 'env' and opt in ('-C', '--chdir') and val is not None:
                        here = {(self._target(cwd, val), cwd) for cwd, _old in here}
            self._record(cmd.span, here)
            if res.name in _CD and res.payload is None:
                return self._cd(res.name, res.args, states), set(states)
            if res.payload is not None:
                if res.payload_kind == 'eval':
                    return self.run_script(res.payload, states)
                self.run_script(res.payload, here)
            return set(states), set(states)
        if isinstance(cmd, sp.Compound):
            self.visited.add(cmd.span)  # its own redirections (`(...) > f`) run where it starts
            self._record(cmd.span, states)
            scripts = [s for s in tuple(cmd.header) + tuple(cmd.body) if isinstance(s, sp.Script)]
            self.functions = self.functions or cmd.kind in ('function', 'coproc')
            if cmd.kind in ('subshell', 'coproc'):
                for s in scripts:
                    self.run_script(s, states)
                return set(states), set(states)
            if cmd.kind == 'group':
                succ, fail = set(states), set(states)
                for s in scripts:
                    succ, fail = self.run_script(s, succ)
                return succ, fail
            if cmd.kind == 'function':
                for s in scripts:
                    self._record(s.span, {self.UNKNOWN})
                    self.run_script(s, {self.UNKNOWN})
                return set(states), set(states)
            acc = set(states)
            for s in scripts:
                succ, fail = self.run_script(s, acc)
                acc |= succ | fail
            return acc, acc
        return set(states), set(states)

    def run_pipeline(self, pl, states):
        if len(pl.stages) == 1:
            succ, fail = self.run_cmd(pl.stages[0], states)
        else:
            for stage in pl.stages:
                self.run_cmd(stage, states)  # each stage runs in a subshell
            succ, fail = set(states), set(states)
        return (fail, succ) if pl.negated else (succ, fail)

    def run_script(self, script, states):
        succ, fail, prev = set(states), set(states), None
        for pl, sep in script.items:
            if prev == '&&':
                enter = succ
            elif prev == '||':
                enter = fail
            elif prev is None:
                enter = set(states)
            else:
                enter = succ | fail
            if sep == '&':
                self.run_pipeline(pl, enter)  # a background job: its cd stays in it
                s, f = set(enter), set(enter)
            else:
                s, f = self.run_pipeline(pl, enter)
            if prev == '&&':
                succ, fail = s, f | fail
            elif prev == '||':
                succ, fail = s | succ, f
            else:
                succ, fail = s, f
            prev = sep
        return succ, fail

    def at(self, offset: int):
        """The possible directories at raw ``offset``: the innermost recorded command around it."""
        best = None
        for a, b, states in self.spans:
            if a <= offset < b and (best is None or b - a < best[1] - best[0]):
                best = (a, b, states)
        return {cwd for cwd, _old in best[2]} if best else {'?'}


def _cd_dirs(sp, sites) -> list:
    """Every directory a `cd`/`pushd` in the command may leave the shell in, as written (each `cd`
    taken from every directory an earlier one may have left; a CDPATH entry the command sets
    before each relative one), the starting directory first."""
    dirs = ['']
    cdpaths = [v for site, _res in sites for a in site.cmd.assignments if a.name == 'CDPATH'
               for v in (a.word.value() or '').split('=', 1)[-1].split(':') if v]
    for site, res in sites:
        if res.name not in _CD:
            continue
        ops = [w for w in res.args if not (w.value() or '').startswith('-')]
        if not ops:
            continue
        arg = _home_spelled_out(ops[0].text)
        if arg.startswith(('/', '~')):
            new = [arg]
        else:
            new = [os.path.join(d, arg) if d else arg for d in dirs]
            new += [os.path.join(c, arg) for c in cdpaths]
        dirs.extend(d for d in new if d not in dirs)
        if len(dirs) > 64:
            break
    return dirs


def _parsed_kind(command: str, start: str = None) -> tuple:
    """(kind, settled): the protected folder ('hooks', 'commands' or '') a path the shared parser
    (or _site_writes) reads ``command`` to write lies in, each relative path read from the
    directories a `cd` before it in its own shell may have left, and whether that reading settles
    it. It does not after a parse failure (the targets read still count), or where a simple command
    naming a protected folder is not one whose writes are known (_site_settled): code fed on stdin,
    an unknown command or runner, a function call, a command string in a variable, `-c`/`-e` code,
    git config, aliases, pagers and editors. The base reading of the raw text decides as well then."""
    sp = _shell_parse()
    script = sp.parse(command)
    settled = not script.errors()
    sites = [(site, sp.resolve(site.cmd)) for site in sp.walk(script)]
    names_any = bool(_protected_kind(command))
    settled = settled and all(_site_settled(sp, command, site, res, names_any) for site, res in sites)
    scopes = _CdScopes(sp, command)
    scopes.run_script(script, {('', '?')})
    every_dir = _cd_dirs(sp, sites)
    # a cd the scopes did not follow (inside a substitution, a re-parsed payload): every relative
    # write after it is read from every directory (fail closed)
    unfollowed = [site.cmd.span[0] if command[slice(*site.cmd.span)].startswith(site.cmd.words[0].text) else 0
                  for site, res in sites if res.name in _CD and site.cmd.words
                  and site.cmd.span not in scopes.visited]
    writes = []
    for t in sp.write_targets(script):
        if t.mechanism == 'computed-command':
            continue  # an operand of a command whose name is computed: no known write
        texts = [t.path or '', (t.word.text if t.word is not None else '')]
        if t.source and t.mode in (sp.COPY_DEST, sp.MOVE_DEST, sp.LINK) and t.path:
            texts.append(os.path.join(t.path, os.path.basename(t.source.rstrip('/'))))
        writes.append((texts, t.word, True))
    for site, res in sites:
        # a git write is the repository's paths, not the shell's directory
        writes += [([text], word, res.name != 'git') for text, word in _site_writes(sp, command, res)]
    kinds = set()
    for texts, word, joinable in writes:
        faithful = word is not None and command[slice(*word.span)] == word.text
        offset = word.span[0] if faithful else len(command)
        dirs = scopes.at(offset) if faithful else {'?'}
        if any(offset > u for u in unfollowed):
            dirs = dirs | {'?'}
        for text in texts:
            spelled = _home_spelled_out(text) if text else ''
            if not spelled:
                continue
            candidates = [spelled]
            if joinable and not spelled.startswith(('/', '~', '$')):
                for d in dirs:
                    for base in (every_dir if d == '?' else [d]):
                        if base:
                            candidates.append(os.path.normpath(os.path.join(base, spelled)))
            for candidate in candidates:
                kinds.add(_protected_kind(candidate) or _located_kind(candidate, start or os.getcwd()))
    # a hooks write is never exempt (the /clean approval covers commands/ only): it decides first
    kind = 'hooks' if 'hooks' in kinds else 'commands' if 'commands' in kinds else ''
    return kind, settled


# The proof that lets a command the base reading refuses go through (_proven_harmless).
# Commands that write nothing and run nothing, whatever their words say.
_PURE_READERS = bash_read_only.ANY_ARGS | {'test', '[', 'exit', 'sleep', 'wait'}
# Write verbs whose every written path the shared parser reads (with sed -i read here).
_PROOF_WRITERS = frozenset({'cp', 'mv', 'install', 'tee', 'rm', 'rmdir', 'unlink', 'truncate', 'touch', 'sed'})
_PROOF_WRAPPERS = frozenset({'env', 'timeout', 'nice', 'command', 'exec', 'setsid'})
# Variables a prefix assignment (`LC_ALL=C cp ...`) may set: none of them moves a directory, names a
# program to run, or changes where a command is looked up.
_SAFE_VARS = re.compile(r'(?:LC_[A-Z]+|LANG|LANGUAGE|TZ|TERM|COLUMNS|LINES|NO_COLOR)\Z')
_FIND_ACTIONS = frozenset({'-exec', '-execdir', '-ok', '-okdir', '-delete', '-fprint', '-fprint0',
                           '-fprintf', '-fls'})
_UNSAFE_TARGET_CHARS = re.compile(r'[$`*?\[\]{}!]')
# gh pr / gh issue subcommands that change nothing in the working tree (not checkout, merge).
_GH_READS = frozenset({'create', 'view', 'list', 'comment', 'edit', 'status', 'close', 'reopen', 'diff',
                       'checks', 'ready', 'review'})
_SED_BOOL_LONG = bash_read_only.SED_LONG_FLAGS


_ENV_PATH_WORD = re.compile(
    r'"(?:\$HOME|\$\{HOME\}|\$(?:CLAUDE_HOME|CLAUDE_CONFIG_DIR)|\$\{(?:CLAUDE_HOME|CLAUDE_CONFIG_DIR)\}'
    r'|\$\{(?:CLAUDE_HOME|CLAUDE_CONFIG_DIR):-\$HOME/[^"$`\\{}*?\[]*\})'
    r'/[^"$`\\]*"\Z')


def _env_path_word(word) -> bool:
    """Whether ``word`` is a double-quoted path built only from the home variables
    (`"$HOME/.claude/hooks/x"`, `"${CLAUDE_HOME:-$HOME/.claude}/commands/x.md"`): one word, an
    absolute path the environment gives, never an option. Such a word may be a copy's source."""
    return bool(_ENV_PATH_WORD.match(word.text))


def _protected_roots() -> set:
    """The protected folders as absolute paths (as written and real): the project's and the
    harness home's hooks/ and commands/."""
    bases = [os.path.join(str(_project_dir()), '.claude')] + list(locations.config_homes())
    roots = set()
    for base in bases:
        for sub in ('hooks', 'commands'):
            path = os.path.normpath(os.path.join(os.path.abspath(os.path.expanduser(base)), sub))
            roots.add(path)
            try:
                roots.add(os.path.realpath(path))
            except (OSError, ValueError):
                pass
    return roots


def _sed_proof(args) -> tuple:
    """(known, in-place operand words) of a sed call the proof can read: only options it knows,
    literal scripts with no w, W or e command or flag, no script file, a backup suffix with no `/`
    or `*`. known is False otherwise."""
    vals = [w.value() for w in args]
    if any(v is None for v in vals):
        return False, []
    scripts, ops, inplace, k = [], [], False, 0
    while k < len(vals):
        v = vals[k]
        if v == '--':
            ops += args[k + 1:]
            break
        if v.startswith('--'):
            name, _eq, val = v.partition('=')
            if name in _SED_BOOL_LONG and not _eq:
                pass
            elif name == '--in-place':
                inplace = True
                if '/' in val or '*' in val:
                    return False, []
            elif name in ('--expression', '--line-length'):
                if not _eq:
                    if k + 1 >= len(vals):
                        return False, []
                    val, k = vals[k + 1], k + 1
                if name == '--expression':
                    scripts.append(val)
            else:
                return False, []
        elif v.startswith('-') and v != '-':
            j = 1
            while j < len(v):
                c = v[j]
                if c in 'nErszu':
                    j += 1
                    continue
                if c == 'i':
                    inplace, suffix = True, v[j + 1:]
                    if '/' in suffix or '*' in suffix:
                        return False, []
                    break
                if c in 'el':
                    val = v[j + 1:]
                    if not val:
                        if k + 1 >= len(vals):
                            return False, []
                        val, k = vals[k + 1], k + 1
                    if c == 'e':
                        scripts.append(val)
                    break
                return False, []  # -f (a script file) or an option the proof does not know
        else:
            ops.append(args[k])
        k += 1
    if not scripts:
        if not ops:
            return False, []
        scripts, ops = [ops[0].value()], ops[1:]
    if any(re.search(r'[wWe]', script) for script in scripts):
        return False, []
    return True, (ops if inplace else [])


# git subcommands the proof takes: not commit (hooks), add (clean filters) or status (the fsmonitor
# and post-index-change hooks). The others may still run textconv, diff drivers or a pager the
# existing configuration names; the proof only makes sure the same command planted none of them.
_PROOF_GIT_READS = _GIT_READS - {'commit', 'add', 'status'}

# rg options the proof takes: the ones that search, filter and format. Nothing that runs a program
# (--pre, --pre-glob, --hostname-bin, --search-zip/-z, --hyperlink-format) and nothing unknown.
_RG_SHORT_FLAGS = frozenset('abcFHhiILlNnoPpqSsUuVvwx0.')
_RG_SHORT_VALUES = _shell_parse().RG_VALUE_SHORT
_RG_LONG_FLAGS = frozenset({
    '--line-number', '--no-line-number', '--ignore-case', '--smart-case', '--case-sensitive',
    '--files-with-matches', '--files-without-match', '--count', '--count-matches', '--word-regexp',
    '--invert-match', '--fixed-strings', '--hidden', '--no-hidden', '--no-ignore', '--no-ignore-vcs',
    '--no-ignore-dot', '--no-ignore-parent', '--no-ignore-global', '--no-ignore-exclude',
    '--no-ignore-files', '--follow', '--no-follow', '--only-matching', '--quiet', '--line-regexp',
    '--null', '--null-data', '--multiline', '--multiline-dotall', '--pcre2', '--no-pcre2', '--files',
    '--json', '--vimgrep', '--heading', '--no-heading', '--with-filename', '--no-filename', '--stats',
    '--text', '--no-text', '--trim', '--column', '--no-column', '--no-messages', '--type-list',
    '--unrestricted', '--binary', '--no-binary', '--no-config', '--passthru', '--byte-offset',
    '--crlf', '--no-crlf', '--mmap', '--no-mmap', '--one-file-system', '--pretty', '--line-buffered',
    '--block-buffered', '--no-unicode', '--glob-case-insensitive', '--include-zero',
    '--max-columns-preview', '--no-require-git', '--sort-files', '--version', '--help',
    '--no-search-zip', '--no-pre',
})
# the value options of shell_parse's table the proof takes: not the ones that run a program or name
# one (--pre, --pre-glob, --hostname-bin, --hyperlink-format) nor --generate, which prints no search
_RG_LONG_VALUES = _shell_parse().RG_VALUE_LONG - {'--pre', '--pre-glob', '--hostname-bin', '--hyperlink-format',
                                                  '--generate'}


def _rg_proof(vals) -> bool:
    """Whether an rg call uses only options that search and print (no program it runs, no
    config file RIPGREP_CONFIG_PATH names unless --no-config)."""
    if os.environ.get('RIPGREP_CONFIG_PATH') and '--no-config' not in vals:
        return False
    k = 0
    while k < len(vals):
        v = vals[k]
        k += 1
        if v == '--':
            break
        if v.startswith('--'):
            name, eq, _val = v.partition('=')
            if name in _RG_LONG_FLAGS and not eq:
                continue
            if name in _RG_LONG_VALUES:
                k += 0 if eq else 1
                continue
            return False
        if v.startswith('-') and v != '-':
            for j, c in enumerate(v[1:], 1):
                if c in _RG_SHORT_FLAGS:
                    continue
                if c in _RG_SHORT_VALUES:
                    k += 0 if v[j + 1:] else 1
                    break
                return False
    return True


def _git_subcommand(vals):
    """The subcommand word of a git call (after its global options), or None."""
    k = 0
    while k < len(vals) and (vals[k] or '').startswith('-'):
        k += 2 if vals[k] in _GIT_VALUE_GLOBALS else 1
    return vals[k] if k < len(vals) else None


def _copy_links(name: str, vals) -> tuple:
    """(refused, aliasing) for a cp, mv or install call. refused: an option that makes a link
    (cp -l/-s/--link/--symbolic-link, a BSD install -l) or runs a program (install -s/--strip,
    --strip-program). aliasing: the destination may come out a symlink or hold one (mv; cp
    recursive, archive, -d/-P/--no-dereference, --preserve), so a write under it may land wherever
    that symlink points."""
    aliasing = name == 'mv'
    value_letters = {'cp': 'St', 'mv': 'St', 'install': 'gmoSt'}[name]
    for v in vals:
        if v is None:
            continue  # a home-variable source word (`"$HOME/..."`): never an option
        if v == '--':
            break
        if v.startswith('--'):
            opt = v.split('=', 1)[0]
            if name == 'cp' and ((len(opt) >= 3 and '--link'.startswith(opt))
                                 or (len(opt) >= 4 and '--symbolic-link'.startswith(opt))):
                return True, aliasing
            if name == 'install' and opt.startswith('--st'):
                return True, aliasing
            if name == 'cp' and any(len(opt) >= least and full.startswith(opt) for full, least in (
                    ('--no-dereference', 6), ('--archive', 4), ('--recursive', 5), ('--preserve', 4))):
                aliasing = True
        elif v.startswith('-') and v != '-':
            for c in v[1:]:
                if c in value_letters:
                    break
                if (name == 'cp' and c in 'ls') or (name == 'install' and c in 'ls'):
                    return True, aliasing
                if name == 'cp' and c in 'dPaRr':
                    aliasing = True
    return False, aliasing


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip('/') + '/')


def _forms_of(path: str) -> set:
    forms = {os.path.normpath(path)}
    try:
        forms.add(os.path.realpath(path))
    except (OSError, ValueError):
        pass
    return forms


def _temp_path(path: str) -> bool:
    """Whether ``path`` is a scratch location no tool reads config or code from: a device sink, or
    a path under /tmp, /var/tmp or $TMPDIR that is not in the project, the home or the harness
    home, and has no git work tree or repository (`.git`) on the way up to the temp root."""
    if path in locations.TERMINAL_SINKS or path.startswith(locations.FD_DIR):
        return True
    roots = set()
    for root in locations.SYSTEM_TEMP_DIRS + (locations.temp_root(),):
        if os.path.isabs(root) and os.path.normpath(root) != '/':
            roots |= _forms_of(root)
    excluded = set()
    for base in [str(_project_dir()), os.path.expanduser('~'), os.path.expanduser('~/.claude')] + [
            os.environ[v] for v in _HOME_VARS if os.environ.get(v)]:
        if os.path.isabs(base):
            excluded |= _forms_of(base)
    for form in _forms_of(path):
        root = next((r for r in roots if form != r and _under(form, r)), None)
        if root is None or any(_under(form, e) for e in excluded):
            return False
        d = os.path.dirname(form)
        while d != root and _under(d, root):
            if os.path.lexists(os.path.join(d, '.git')):
                return False
            d = os.path.dirname(d)
    return True


def _git_config_path(path: str) -> bool:
    """Whether ``path`` is (or is in) a file git reads config, attributes, modules or hooks from:
    a `.git*` path component, ~/.config/git or $XDG_CONFIG_HOME/git."""
    xdg = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
    for form in _forms_of(path):
        if any(part.startswith('.git') for part in form.split('/')):
            return True
        if _under(form, os.path.join(xdg, 'git')) or _under(form, os.path.expanduser('~/.config/git')):
            return True
    return False


def _on_search_path(path: str) -> bool:
    """Whether writing ``path`` may plant a program a later command name runs: it lies in, is, or
    holds a directory on PATH, or PATH has a relative entry."""
    entries = os.environ.get('PATH', '').split(':')
    if any(not e or not os.path.isabs(e) for e in entries):
        return not locations.is_device(path)
    dirs = set()
    for e in entries:
        dirs |= _forms_of(e)
    for form in _forms_of(path):
        if os.path.dirname(form) in dirs or any(_under(d, form) for d in dirs):
            return True
    return False


def _proven_harmless(command: str, start: str) -> bool:
    """Whether ``command`` (run from directory ``start``) provably writes nothing into a protected
    folder: it parses cleanly; every simple command, also in a `bash -c` or `eval` payload, is a
    reader that writes or runs nothing (with no write or exec option) or one of the write verbs
    whose targets are read here, run under no wrapper but env/timeout/nice/command/exec/setsid,
    with no assignment but locale-like ones, no function, no substitution, no `source`; every
    `cd` on the way is followed (a computed one, CDPATH or popd leaves the directory unknown);
    and every written path is literal (no variable, `$_`, `!$`, glob or brace), resolves from the
    directory its command runs in outside the protected folders, and (a removal, a move, a
    recursive copy) is no ancestor of one. Anything unproven is False."""
    sp = _shell_parse()
    script = sp.parse(command)
    if script.errors():
        return False
    start = os.path.abspath(start)
    scopes = _CdScopes(sp, command)
    scopes.cdpath = scopes.cdpath or bool(os.environ.get('CDPATH'))
    scopes.run_script(script, {(start, '?')})
    if scopes.functions:
        return False
    sites = []
    aliasing = set()  # the spans of the copies and moves whose destination may be or hold a symlink
    config_readers = set()  # git, gh and a `bash -c` under BASH_ENV/ENV: they read files as config or code
    for site in sp.walk(script):
        cmd = site.cmd
        if cmd.span not in scopes.visited or site.dynamic or site.templated:
            return False  # a substitution's commands, a computed command name
        res = sp.resolve(cmd)
        if res.unresolved:
            return False
        assigns = list(cmd.assignments) + [a for a in res.assignments if a not in cmd.assignments]
        if assigns and res.head is None:
            return False  # a variable set for the rest of the command
        for a in assigns:
            if not _SAFE_VARS.match(a.name or '') or a.static_value() is None:
                return False
        for wname, opts in res.wrappers:
            if wname not in _PROOF_WRAPPERS or (wname == 'env' and any(
                    o not in ('-i', '--ignore-environment') for o, _v in opts)):
                return False
        if res.payload is not None:
            if res.payload_kind not in ('shell_c', 'eval'):
                return False
            if res.payload_kind == 'shell_c' and (os.environ.get('BASH_ENV') or os.environ.get('ENV')):
                config_readers.add('shell')
            continue  # its commands are walked and judged on their own
        if res.head is None:
            continue  # redirects only: their targets are judged below
        head = res.head.value()
        name = res.name
        if head is None or '/' in head or name is None:
            return False
        vals = [w.value() for w in res.args]
        if name in _CD:
            if assigns:
                return False
            continue
        if name in _PURE_READERS:
            sites.append((cmd, name, res, []))
            continue
        if any(v is None and not (name in _PROOF_WRITERS and _env_path_word(w))
               for v, w in zip(vals, res.args)):
            return False  # a computed word: it may split into options or other paths
        if name in ('printf', 'sort'):
            if not bash_read_only.reads_only(name, vals):
                return False  # printf -v; sort -o, --compress-program, -T
        elif name == 'find':
            if _FIND_ACTIONS & set(vals):
                return False
        elif name == 'rg':
            if not _rg_proof(vals):
                return False
        elif name == 'git':
            if not _git_settled(res, command) or 'add' in vals or any(
                    v.startswith(('--git-dir', '--work-tree', '--namespace')) for v in vals):
                return False  # another git directory or work tree (git writes its index there), an add
            if _git_subcommand(vals) not in _PROOF_GIT_READS:
                return False  # commit, add, status: they run hooks or filters
            config_readers.add('git')
        elif name == 'gh':
            if vals[:1] not in (['pr'], ['issue']) or len(vals) < 2 or vals[1] not in _GH_READS:
                return False
            config_readers.add('git')  # gh reads its own config and runs git
        elif name == 'sed':
            known, inplace = _sed_proof(list(res.args))
            if not known:
                return False
            sites.append((cmd, name, res, inplace))
            continue
        elif name in _PROOF_WRITERS:
            if name in sp.CP_MV + ('install',) and any(
                    (v or '').startswith(('-S', '--suffix', '--parents', '--su', '--pa')) for v in vals):
                return False  # a backup suffix or --parents: a written path not read here
            if name in sp.CP_MV + ('install',):
                refused, alias = _copy_links(name, vals)
                if refused:
                    return False  # a link into whatever the source is, or a strip program run
                if alias:
                    aliasing.add(cmd.span)
            sites.append((cmd, name, res, []))
            continue
        else:
            return False
        sites.append((cmd, name, res, []))
    roots = _protected_roots()

    def site_of(word):
        found = None
        for cmd, name, res, extra in sites:
            if cmd.span[0] <= word.span[0] < cmd.span[1] and (found is None or cmd.span[0] >= found[0].span[0]):
                found = (cmd, name, res, extra)
        return found

    def resolved(word, path=None):
        """The absolute paths ``word`` names from its command's directory, or None if unknown."""
        text = word.text
        path = word.value() if path is None else path
        if path is None or _UNSAFE_TARGET_CHARS.search(text) or not path:
            return None
        if path.startswith('~') and not (path == '~' or path.startswith('~/')):
            return None
        path = os.path.expanduser(path)
        if os.path.isabs(path):
            return {os.path.normpath(path)}
        if command[slice(*word.span)] != text:
            return None
        cwds = scopes.at(word.span[0])
        if any(c == '?' or c.startswith('~') and not (c == '~' or c.startswith('~/')) for c in cwds):
            return None  # an unknown directory (`cd ~-`, `cd ~+/x`, `cd ~user` included)
        return {os.path.normpath(os.path.join(os.path.expanduser(c), path)) for c in cwds}

    def outside(paths, subtree) -> bool:
        for path in paths:
            forms = {path}
            try:
                forms.add(os.path.realpath(path))
            except (OSError, ValueError):
                pass
            for form in forms:
                if _protected_kind(form) or _located_kind(form):
                    return False
                if subtree and any(r == form or r.startswith(form.rstrip('/') + '/') for r in roots):
                    return False
        return True

    def operand_names(res, name):
        spec = sp.VERBS[name][0]
        _opts, ops, err = sp.split_options(list(res.args), spec, 0, permute=True)
        return None if err else ops

    writes = []  # (written paths, the span of the copy or move that wrote them or None)
    for t in sp.write_targets(script):
        if not t.decidable or t.word is None or t.path is None:
            return False
        word = t.word
        if t.mechanism.startswith('redirect'):
            paths = resolved(word, t.path)
            if paths is None or not outside(paths, False):
                return False
            writes.append((paths, None))
            continue
        owner = site_of(word)
        if owner is None:
            return False
        cmd, name, res, _extra = owner
        paths = resolved(word, t.path)
        if paths is None:
            return False
        recursive = name in sp.COPY_VERBS and any(
            v and (v in ('--recursive', '--archive') or (v.startswith('-') and not v.startswith('--')
                                                        and set(v[1:]) & set('rRa')))
            for v in (w.value() for w in res.args))
        subtree = t.mode in (sp.DELETE, sp.MOVE_DEST) or recursive
        written = set(paths)
        if t.mode in (sp.COPY_DEST, sp.MOVE_DEST):
            ops = operand_names(res, name)
            if ops is None:
                return False
            for op in ops:
                text = op.value()
                if text is None:
                    text = op.text.strip('"')
                    if '$' in text.rsplit('/', 1)[-1]:
                        return False  # a copied name the guard cannot read
                base = os.path.basename(text.rstrip('/'))
                if base not in ('', '.', '..'):  # `cp -r src/. dest` writes dest itself, judged above
                    written |= {os.path.join(p, base) for p in paths}
        if not outside(written, subtree):
            return False
        writes.append((written, cmd.span))
    for cmd, name, res, extra in sites:
        words = list(extra)
        if name == 'mv':
            ops = operand_names(res, name)
            if ops is None:
                return False
            words += ops  # a moved source is removed: no protected folder may lie in it
        for word in words:
            paths = resolved(word)
            if paths is None or not outside(paths, name == 'mv'):
                return False
            writes.append((paths, cmd.span))  # its own operands: not a write through its own copy
    return _unchained(writes, aliasing, config_readers)


def _unchained(writes, aliasing, config_readers) -> bool:
    """Whether the proven writes of one command cannot be chained into a protected write: no write
    lands under the destination of another copy or move that may have left a symlink there (it may
    point into a protected folder); none plants a program on PATH; and when the command runs git, gh
    or a `bash -c` under BASH_ENV (all read files as config or code), every write is to a temp
    location, none is a git config, attributes, modules or hooks file, and no copy or move carried a
    directory (it may hold a `.git`)."""
    alias_dests = [(paths, span) for paths, span in writes if span in aliasing]
    for paths, span in writes:
        for dests, dspan in alias_dests:
            if span != dspan and any(_under(p, d) for p in paths for d in dests):
                return False  # a write through a copied symlink or hard link
        if any(_on_search_path(p) for p in paths):
            return False
        if config_readers and any(not _temp_path(p) or _git_config_path(p) for p in paths):
            return False
    if config_readers and aliasing:
        return False
    return True


def _classify_bash_target(command: str, start: str = None) -> str:
    """Return 'hooks', 'commands', or '' for a Bash command. A protected folder a path it writes,
    removes or moves away lies in, as the shared parser (or _site_writes) reads it, refuses it.
    Otherwise the base reading of the raw text decides, unless _proven_harmless proves from the
    directory ``start`` that no write of the command it can read reaches a protected folder (a bounded
    proof: configuration that existed before the command, hard links and symlinks made earlier stay residual)."""
    if not command:
        return ''
    try:
        kind, _settled = _parsed_kind(command, start)
    except Exception:
        kind = ''
    legacy = _legacy_kind(command)
    if kind == 'hooks' or not legacy:
        return kind
    if kind:
        return legacy if legacy == 'hooks' else kind  # a hooks write decides before a commands one
    try:
        if _proven_harmless(command, start or os.getcwd()):
            return ''
    except Exception:
        pass
    return legacy


def _block(message: str) -> None:
    """Write message to stderr and exit 2."""
    sys.stderr.write(message)
    sys.exit(2)


def _block_path(tool_name: str, file_path: str, kind: str) -> None:
    """Emit a block for a Write/Edit to a protected path."""
    _block(
        f'\n{BLOCK_LITERAL}: agent {tool_name} to .claude/{kind}/ '
        f'is forbidden outside an explicit refactor session.\n'
        f'Attempted: {tool_name} -> {file_path}\n'
        f'To override: create the sentinel file '
        f'`.claude/{SENTINEL_NAME}` at the project root, perform the '
        f'edit, then delete the sentinel.\n'
        f'Spec: spec-20260424-233926 §5.2.4 (R4.2). Closes the gap '
        f'that allowed b5d447e to rewrite checkpoint hooks during a '
        f'sweep commit.\n'
    )


def _block_bash(command: str, kind: str) -> None:
    """Emit a block for a Bash write to a protected path."""
    _block(
        f'\n{BLOCK_LITERAL}: agent Bash write to .claude/{kind}/ '
        f'is forbidden outside an explicit refactor session.\n'
        f'Command excerpt: {command[:200]}\n'
        f'To override: create the sentinel file '
        f'`.claude/{SENTINEL_NAME}` at the project root.\n'
        f'Spec: spec-20260424-233926 §5.2.4 (R4.2).\n'
    )


def _dev_command_product_file(file_path: str, data: dict) -> bool:
    """The write /dev-command exists for (X4 (b)): its dev, a subagent whose own
    dispatch (subagent_type dev, an obligation of role dev) lies in the span a
    human-typed /dev-command opened, writes <project>/.claude/commands/<name>.md,
    not the harness home's. Anything unread or unmatched is False (blocked)."""
    try:
        project = os.path.realpath(_project_dir())
        target = os.path.realpath(os.path.join(project, file_path))
        home = os.path.realpath(os.path.expanduser(os.environ.get('CLAUDE_HOME') or '~/.claude'))
        if (not data.get('agent_id') or not target.endswith('.md') or home == os.path.join(project, '.claude')
                or os.path.dirname(target) != os.path.join(project, '.claude', 'commands')):
            return False
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from lib import command_span, declared_paths, obligation
        transcript = Path(data['transcript_path'])
        if transcript.parent.name == 'subagents':  # <sid>/subagents/agent-x.jsonl -> <sid>.jsonl
            transcript = transcript.parent.parent.with_suffix('.jsonl')
        span = command_span.active_span(transcript)
        if span is None or span.command != 'dev-command':
            return False
        agent_transcript = declared_paths._agent_files(transcript, data['agent_id'])[0]
        prompt = obligation.read_first_record_prompt(agent_transcript)
        # the CLI's meta of the subagent, read by the one reader every gate takes its call id from
        call_id = obligation._read_meta_tool_use_id(agent_transcript)
        parsed = obligation.parse_obligation(prompt)
        return (isinstance(parsed, obligation.ParsedObligation) and parsed.obligation.get('role') == 'dev'
                and any(c.id == call_id and c.input.get('prompt') == prompt
                        and c.input.get('subagent_type') == 'dev' for c in span.iter_calls('Agent', 'Task')))
    except Exception:
        return False


def _clean_grant(data: dict) -> tuple:
    """(paths written, paths removed) the caller may write as the producer of what a
    human-typed /clean's owner approved (P9-4): the cleaner's approved moves, renames and
    fix_style edits of the active /clean span, read by hooks/pretool-tool-policy.py's one rule
    (clean_grant), which also refuses every other caller's write of them. A /clean run in the
    harness home approves moves and edits under commands/ (and agents/); nothing else is
    exempted here. Anything unread is empty (blocked)."""
    try:
        if not data.get('agent_id'):
            return frozenset(), frozenset()
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, here)
        spec = importlib.util.spec_from_file_location('_tool_policy_clean', os.path.join(here, 'pretool-tool-policy.py'))
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        project = os.path.abspath(str(_project_dir()))
        return policy.clean_grant(data, project)
    except Exception:
        return frozenset(), frozenset()


def _forms(path: str) -> set:
    path = os.path.join(str(_project_dir()), os.path.expanduser(path))
    forms = {os.path.normpath(path)}
    try:
        forms.add(os.path.realpath(path))
    except (OSError, ValueError):
        pass
    return forms


def _clean_approved_edit(file_path: str, data: dict) -> bool:
    """Whether file_path is a file /clean's owner approved for this caller to edit (above)."""
    written, _removed = _clean_grant(data)
    return bool(file_path) and bool(_forms(file_path) & written)


def _clean_approved_bash(command: str, data: dict) -> bool:
    """Whether every `.claude/commands/` the guard reads in ``command`` is spelled by a path
    /clean's owner approved for this caller (a move's source or destination, a fixed file):
    with each of those paths, as written absolute, real or below the home's spellings, taken
    out of the command and of its home-spelled-out text, neither names a protected directory."""
    written, removed = _clean_grant(data)
    paths = written | removed
    if not paths:
        return False
    home = os.path.realpath(os.path.expanduser(os.environ.get('CLAUDE_HOME') or '~/.claude'))
    spellings = set()
    for path in paths:
        spellings.add(path)
        rel = os.path.relpath(path, home)
        if rel != os.pardir and not rel.startswith(os.pardir + os.sep):
            spellings.update(f'{root}/{rel}' for root in (_HOME, '$HOME/.claude', '${HOME}/.claude'))
    for text in dict.fromkeys((command, _home_spelled_out(command))):
        for spelling in sorted(spellings, key=len, reverse=True):
            text = text.replace(spelling, ' ')
        if _classify_bash_target(text):
            return False
    return True


def _evaluate_write_edit(tool_name: str, tool_input: dict, data: dict) -> None:
    """Apply guard for Write/Edit/MultiEdit/NotebookEdit tools."""
    file_path = tool_input.get('file_path', '') or ''
    kind = _located_kind(file_path, data.get('cwd'))
    if kind == 'hooks':
        _block_path(tool_name, file_path, 'hooks')
    if (kind == 'commands' and not _dev_command_product_file(file_path, data)
            and not _clean_approved_edit(file_path, data)):
        _block_path(tool_name, file_path, 'commands')


def _evaluate_bash(tool_input: dict, data: dict) -> None:
    """Apply guard for Bash tool."""
    command = tool_input.get('command', '') or ''
    kind = _classify_bash_target(command, data.get('cwd') or None)
    if kind and not (kind == 'commands' and _clean_approved_bash(command, data)):
        _block_bash(command, kind)


def _evaluate(tool_name: str, tool_input: dict, data: dict) -> None:
    """Dispatch evaluation by tool_name."""
    if tool_name in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
        _evaluate_write_edit(tool_name, tool_input, data)
    elif tool_name == 'Bash':
        _evaluate_bash(tool_input, data)


def main() -> None:
    """Entry point: read JSON-from-stdin, evaluate, exit 0/2."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    try:
        if _sentinel_present():
            sys.exit(0)
        tool_name = data.get('tool_name', '') or ''
        tool_input = data.get('tool_input', {}) or {}
        _evaluate(tool_name, tool_input, data)
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == '__main__':
    main()
