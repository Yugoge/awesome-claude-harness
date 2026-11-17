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


SENTINEL_NAME = '.hook-refactor-allow'
BLOCK_LITERAL = 'BLOCKED: claude config guard'

_HOOK_PATTERNS = [
    r'(?:echo|printf)\s+.*>\s*\S*\.claude/hooks/',
    r'cat\s+.*>\s*\S*\.claude/hooks/',
    r'cp\s+.*\.claude/hooks/',
    r'mv\s+.*\.claude/hooks/',
    r'tee\s+.*\.claude/hooks/',
    r'>\s*\S*\.claude/hooks/',
    r'>>\s*\S*\.claude/hooks/',
]
_CMD_PATTERNS = [
    r'(?:echo|printf)\s+.*>\s*\S*\.claude/commands/',
    r'cat\s+.*>\s*\S*\.claude/commands/',
    r'cp\s+.*\.claude/commands/',
    r'mv\s+.*\.claude/commands/',
    r'tee\s+.*\.claude/commands/',
    r'>\s*\S*\.claude/commands/',
    r'>>\s*\S*\.claude/commands/',
]


def _project_dir() -> Path:
    """Return the active project directory."""
    return Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))


def _sentinel_present() -> bool:
    """True iff the allow-list sentinel exists at the project root."""
    return (_project_dir() / '.claude' / SENTINEL_NAME).exists()


def _is_hooks_path(file_path: str) -> bool:
    """True iff file_path targets .claude/hooks/."""
    if not file_path:
        return False
    return '.claude/hooks/' in file_path.replace('\\', '/')


def _is_commands_path(file_path: str) -> bool:
    """True iff file_path targets .claude/commands/."""
    if not file_path:
        return False
    return '.claude/commands/' in file_path.replace('\\', '/')


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
# a file read): a protected folder named by one of them is not written.
_READERS = frozenset({
    'echo', 'printf', 'cat', 'grep', 'egrep', 'fgrep', 'head', 'tail', 'wc', 'ls', 'stat', 'file',
    'du', 'diff', 'cmp', 'realpath', 'readlink', 'basename', 'dirname', 'test', '[', 'true', 'false',
    ':', 'pwd', 'md5sum', 'sha1sum', 'sha256sum', 'sha512sum', 'cksum', 'b2sum', 'nl', 'cut', 'tr',
    'od', 'hexdump', 'strings', 'tac', 'comm', 'which', 'type',
})
# Commands that read their standard input as data, never as code: fed a protected folder's name or
# text, they write nothing through it (a write verb's targets come from the parser).
_STDIN_DATA = _READERS | {'tee', 'sed', 'sort', 'uniq', 'jq', 'xxd', 'less', 'more'}
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
    return True


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
    if name in _READERS:
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
        if name == 'perl' and any(_names(raw, w) for w in _perl_code(res.args)):
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


def _perl_code(args) -> list:
    """The code words of a perl call (-e/-E values, or the script operand)."""
    code, k = [], 0
    while k < len(args):
        v = args[k].value() or ''
        if v == '--' or not v.startswith('-'):
            break
        if v[-1:] in ('e', 'E') and not v.startswith('--') and k + 1 < len(args):
            code.append(args[k + 1])
            k += 2
            continue
        k += 1
    return code


_SED_WRITE = re.compile(r'(?:^|[;{}\n\d$!]|/[gpiImMe0-9]*)\s*[wW]\s*(\S+)')


def _site_writes(sp, raw: str, res) -> list:
    """(path text, word) writes of commands the shared parser has no write rule for: touch, perl -i,
    patch, tar -x -C, unzip -d, git checkout/apply into a folder, sed's w command, find's -fprint
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

    if name == 'touch':
        out += [(w.value() or w.text, w) for w in operands(takes=('-r', '--reference', '-d', '--date', '-t'))]
    elif name == 'perl':
        inplace, code, ops, k = False, False, [], 0
        while k < len(args):
            v = vals[k]
            if v == '--':
                ops = args[k + 1:]
                break
            if not v.startswith('-') or v == '-':
                ops = args[k:]
                break
            flags = v[1:]
            if not v.startswith('--') and flags[:1] not in ('M', 'm', 'I', 'x', 'C', 'd', 'D'):
                inplace = inplace or 'i' in re.split(r'[eE]', flags, 1)[0]
                if flags[-1:] in ('e', 'E') and k + 1 < len(args):
                    code, k = True, k + 2
                    continue
            k += 1
        if inplace:
            out += [(w.value() or w.text, w) for w in (ops if code else ops[1:])]
    elif name == 'patch':
        ops = operands(takes=('-p', '-d', '--directory', '-o', '--output', '-i', '--input', '-r',
                              '-B', '-z', '-D', '-F', '-V', '-g', '-Y'))
        outputs = option_values('-o', '--output')
        out += [] if outputs else [(w.value() or w.text, w) for w in ops[:1]]  # -o leaves it as is
        out += option_values('-d', '--directory') + outputs
    elif name in ('tar', 'bsdtar', 'gtar'):
        first = vals[0] if vals else ''
        extract = any(v in ('-x', '--extract', '--get') or (v.startswith('-') and not v.startswith('--') and 'x' in v)
                      for v in vals) or (first and not first.startswith('-') and 'x' in first)
        if extract:
            out += option_values('-C', '--directory')
    elif name == 'unzip':
        out += option_values('-d')
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
    elif name == 'find':
        for k, v in enumerate(vals):
            if v in ('-fprint', '-fprint0', '-fprintf', '-fls') and k + 1 < len(args):
                out.append((args[k + 1].value() or args[k + 1].text, args[k + 1]))
        if '-delete' in vals:
            for w in args:
                if (w.value() or '-').startswith(('-', '(', '!')):
                    break
                out.append((w.value() or w.text, w))
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
            self._record(cmd.span, states)
            scripts = [s for s in tuple(cmd.header) + tuple(cmd.body) if isinstance(s, sp.Script)]
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


def _parsed_kind(command: str) -> tuple:
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
                kinds.add(_protected_kind(candidate))
    # a hooks write is never exempt (the /clean approval covers commands/ only): it decides first
    kind = 'hooks' if 'hooks' in kinds else 'commands' if 'commands' in kinds else ''
    return kind, settled


def _classify_bash_target(command: str) -> str:
    """Return 'hooks', 'commands', or '' for a Bash command: the protected folder a path it writes,
    removes or moves away lies in (each relative one also read from every `cd` target), as the
    shared parser reads it; where the parser cannot settle it, the base reading of the raw text."""
    if not command:
        return ''
    try:
        kind, settled = _parsed_kind(command)
    except Exception:
        kind, settled = '', False
    if kind == 'hooks' or settled:
        return kind
    return _legacy_kind(command) or kind


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
    if _is_hooks_path(file_path):
        _block_path(tool_name, file_path, 'hooks')
    if (_is_commands_path(file_path) and not _dev_command_product_file(file_path, data)
            and not _clean_approved_edit(file_path, data)):
        _block_path(tool_name, file_path, 'commands')


def _evaluate_bash(tool_input: dict, data: dict) -> None:
    """Apply guard for Bash tool."""
    command = tool_input.get('command', '') or ''
    kind = _classify_bash_target(command)
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
