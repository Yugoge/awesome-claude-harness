#!/usr/bin/env python3
"""PreToolUse Hook: user-intent sentinel guard for the /stop release wrapper.

The /stop slash command releases overnight isolation by running
`scripts/break-overnight-lock.py` (via `hooks/stop.sh`), the ONLY sanctioned
setter of `isolation_released_at`. An overnight ACTOR must NOT be able to
self-release isolation by invoking that helper directly from a Bash tool call.

Mechanism:
  * The UserPromptSubmit hook (`prompt-workflow.py::_write_userintent_sentinel`)
    writes `<state dir>/claude-stop-userintent-<sid>.flag` ONLY when the user actually
    typed `/stop`.
  * THIS PreToolUse hook fires on every Bash command. When the command invokes
    `break-overnight-lock.py` (or `hooks/stop.sh`), it REQUIRES a live sentinel
    for the calling session; absent -> BLOCK (exit 2). Present -> CONSUME it
    one-shot (unlink) and ALLOW (exit 0), so a replayed/stale sentinel is
    rejected on the next attempt.

This is the PreTool surface. The helper itself ALSO validates the sentinel
before mutating state (defense in depth), so a bypass of this hook still cannot
release isolation.

Exit codes:
  0: allow (not a guarded wrapper, or a valid live sentinel was consumed)
  2: block (guarded wrapper invoked without a valid live user-intent sentinel)
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import json
import os
import glob
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.harness_state_dir import harness_state_dir  # noqa: E402
try:
    from lib.shell_parse import without_heredoc_bodies
except Exception:  # pragma: no cover - fail-soft when lib missing
    def without_heredoc_bodies(text: str) -> str:  # type: ignore
        return text

# Wrapper scripts whose EXECUTION requires a matching user-intent sentinel. The
# key is the sentinel command-name (<state dir>/claude-<name>-userintent-); the
# value lists the wrapper files, relative to the harness home.
#
# IMPORTANT (no over-block): the guard decides on a parsed EXECUTION of the
# harness home's own wrapper file, never on a mention. A grep, a syntax check
# (`bash -n`), a lookup (`command -v`), a project's own `scripts/stop.sh` or a
# heredoc that carries the path as data is not a run: it passes and leaves the
# single-use sentinel in place. An execution is read from the parsed command
# (hooks/lib/shell_parse.py): the command word after transparent wrappers
# (env, command, exec, nice, timeout, setsid, nohup, sudo ...), the script a
# shell or python runs (operand, `-s`/stdin from a file, a heredoc or a pipe),
# `source`/`.`, and every nested `bash -c` string, substitution, function body
# and `find -exec`. Its target is matched by realpath against the harness
# home's wrapper files, after `~`, `$HOME`/`${HOME}`, globs and `cd` are
# applied. Fail closed: when the command mentions a wrapper and runs something
# the guard cannot read (an unparseable command, a computed command word or
# script, a file the same command creates or names elsewhere, stdin from a pipe,
# opaque interpreter code naming the wrapper), it is treated as a run.
_GUARDED_WRAPPERS = {
    'stop': (('hooks', 'stop.sh'), ('scripts', 'break-overnight-lock.py')),
}
_MENTION_RE = re.compile(r'stop\.sh|break-overnight-lock')

# Fallback when the parser cannot be imported: the previous text patterns.
_EXEC_PREFIX = (
    r'(?:'
    r'^|[;&|(\n]\s*'
    r'|(?<![\w./-])(?:python3?|bash|sh|zsh|dash|env|exec|command|source)\s+(?:-\S+\s+)*'
    r'|(?<![\w./-])\.\s+'
    r')')
_FALLBACK_PATTERNS = {
    'stop': (
        re.compile(_EXEC_PREFIX + r'(?:\S*/)?break-overnight-lock\.py\b'),
        re.compile(_EXEC_PREFIX + r'(?:\S*/)?stop\.sh\b'),
    ),
}

try:
    from lib import shell_parse as _sp
except Exception:  # pragma: no cover - fail-soft when lib missing
    _sp = None

# Directory holding the user-intent sentinels (overridable for sandbox tests).
_SENTINEL_DIR = os.environ.get('CLAUDE_USERINTENT_SENTINEL_DIR', harness_state_dir())

_PYTHON_RE = re.compile(r'^(?:python[\d.]*|pypy[\d.]*)$')
_PY_VALUE_OPTS = 'cmWXQ'
_STDIN_FILES = ('/dev/stdin', '/dev/fd/0', '/proc/self/fd/0')
# Builtins and keywords that run no file (`command -v`, `type`, `hash` lookups).
_NO_EXEC = frozenset((
    'cd', 'pushd', 'popd', 'dirs', 'echo', 'printf', 'test', '[', '[[', 'true', 'false',
    ':', 'export', 'declare', 'typeset', 'local', 'readonly', 'set', 'unset', 'shift',
    'read', 'wait', 'type', 'hash', 'command', 'alias', 'unalias', 'return', 'exit',
    'break', 'continue', 'let', 'getopts', 'umask', 'ulimit', 'jobs', 'fg', 'bg', 'kill',
    'history', 'shopt', 'times', 'trap', 'disown', 'help', 'logout', 'mapfile',
    'readarray', 'compgen', 'complete', 'caller', 'eval', 'which', 'whereis'))

# Commands that run code given in their arguments (a command string, a script
# body) which the parser does not read: one whose arguments name the wrapper is
# a run the guard cannot read.
_OPAQUE_RUNNERS = frozenset((
    'watch', 'parallel', 'script', 'tmux', 'screen', 'su', 'sg', 'runuser', 'bwrap',
    'docker', 'podman', 'kubectl', 'machinectl', 'start-stop-daemon', 'ssh', 'expect',
    'dtach', 'faketime', 'proot', 'flatpak-spawn', 'nsenter', 'perl', 'ruby', 'node',
    'nodejs', 'php', 'lua', 'awk', 'gawk', 'mawk', 'nawk', 'busybox', 'tclsh', 'make'))
# Commands that run what their stdin holds, later or now.
_STDIN_RUNNERS = frozenset(('at', 'batch'))
# git arguments that run a command string (`!` aliases, rebase --exec, bisect run ...).
_GIT_RUNS = re.compile(r'^(?:-c|--config-env|--exec|-x|run|filter-branch|filter-repo|'
                       r'alias\..*|.*\.(?:sshcommand|editor|pager|hookspath|fsmonitor)=.*)$',
                       re.IGNORECASE)


def _harness_homes() -> list[str]:
    """The harness home: this hook's own parent, CLAUDE_HOME and $HOME/.claude."""
    homes = [os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
             os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    for hint in (os.environ.get('CLAUDE_HOME', ''),
                 os.path.join(os.environ.get('HOME', ''), '.claude') if os.environ.get('HOME') else ''):
        if hint and os.path.isabs(hint):
            homes.append(hint)
    return homes


def _wrapper_index() -> tuple[dict, dict]:
    """realpath -> command-name, and wrapper basename -> command-name."""
    by_path, by_name = {}, {}
    for name, files in _GUARDED_WRAPPERS.items():
        for rel in files:
            by_name[rel[-1]] = name
            for home in _harness_homes():
                by_path[os.path.realpath(os.path.join(home, *rel))] = name
    return by_path, by_name


class _Scan:
    """One read of a Bash command: the wrapper it runs, or whether it runs
    something that cannot be read."""

    def __init__(self, command: str, cwd: str):
        self.home = os.environ.get('HOME', '')
        self.by_path, self.by_name = _wrapper_index()
        self.cwds = {cwd}
        self.cwd_unknown = False
        self.match = None
        self.unresolved = False
        self.path_assigned = False
        self.mention = bool(_MENTION_RE.search(without_heredoc_bodies(command)))
        self.others = []  # (word, expanded value) of every argument and redirect target
        script = _sp.parse(command)
        if script.error is not None:
            self.unresolved = True
            self.mention = self.mention or bool(_MENTION_RE.search(command))
        self.sites = list(_sp.walk(script))
        for site in self.sites:
            self._collect(site)
        for site in self.sites:
            self._site(site)

    # -- word reading --------------------------------------------------------
    def _expand(self, word):
        """(value, is_glob) of a word after ~, $HOME and ${HOME}; (None, False) when computed."""
        if word is None:
            return None, False
        out, pattern, is_glob = [], [], False
        for k, p in enumerate(word.parts):
            if p.kind == 'lit':
                t = p.text
                if k == 0 and p.quote == _sp.BARE and t[:1] == '~' and (len(t) == 1 or t[1] == '/'):
                    t = self.home + t[1:]
                out.append(t)
                pattern.append(glob.escape(t))
            elif p.kind == 'param' and p.text in ('HOME', '{HOME}') and self.home:
                out.append(self.home)
                pattern.append(glob.escape(self.home))
            elif p.kind == 'glob':
                is_glob = True
                pattern.append(p.text)
            else:
                return None, False
        return (''.join(pattern) if is_glob else ''.join(out)), is_glob

    def _collect(self, site):
        cmd = site.cmd
        res = _sp.resolve(cmd)
        for a in tuple(cmd.assignments) + tuple(res.assignments):
            if a.name == 'PATH':
                self.path_assigned = True
        for w in list(cmd.words[1:]) + [r.target for r in cmd.redirects if r.target is not None]:
            v, _g = self._expand(w)
            if v is not None:
                self.others.append((w, v))
                if _MENTION_RE.search(v):
                    self.mention = True
                if v.startswith('PATH=') or v.startswith('PATH+='):
                    self.path_assigned = True

    def _named_elsewhere(self, word, value) -> bool:
        """The same command names this file as an argument or redirect target
        (it may create, copy or link it), so its content on disk now is not
        what runs."""
        base = os.path.basename(value.rstrip('/'))
        norm = os.path.normpath(value)
        try:
            a, b = word.span
        except Exception:
            a = b = -1
        for w, v in self.others:
            if w is word:
                continue
            try:
                wa, wb = w.span
            except Exception:
                wa = wb = -2
            if a >= 0 and wa <= a and b <= wb:
                continue  # the word that carries this one (a `bash -c` string)
            if os.path.normpath(v) == norm or (base and os.path.basename(v.rstrip('/')) == base):
                return True
        return False

    # -- targets -------------------------------------------------------------
    def _path_target(self, word, value=None, is_glob=False):
        """A file a command runs: match it by realpath, or mark it unreadable."""
        if value is None:
            value, is_glob = self._expand(word)
        if value is None:
            self.unresolved = True
            return
        if not os.path.isabs(value) and self.cwd_unknown:
            self.unresolved = True
            return
        bases = [''] if os.path.isabs(value) else sorted(self.cwds)
        found = []
        for base in bases:
            joined = os.path.join(base, value) if base else value
            found.extend(glob.glob(joined) if is_glob else ([joined] if os.path.exists(joined) else []))
        for f in found:
            name = self.by_path.get(os.path.realpath(f))
            if name is not None:
                self.match = self.match or name
        if not found or (word is not None and self._named_elsewhere(word, value)):
            self.unresolved = True

    def _bare_target(self, word, value):
        """A command word without a slash, looked up on PATH."""
        found = shutil.which(value)
        if found is not None:
            name = self.by_path.get(os.path.realpath(found))
            if name is not None:
                self.match = self.match or name
        if value in self.by_name and (found is None or self.path_assigned):
            self.unresolved = True
        elif found is None and self._named_elsewhere(word, value):
            self.unresolved = True
        elif self.path_assigned and self._named_elsewhere(word, value):
            self.unresolved = True

    def _stdin(self, site, res, shell):
        """The code a shell or python reads on its stdin."""
        cmd = site.cmd
        for red in cmd.redirects:
            if red.fd != 0:
                continue
            if red.op in ('<', '<>') and red.target is not None:
                self._path_target(red.target)
                return
            if red.hd is not None or red.op == '<<<':
                if shell and res.payload is not None:
                    return  # the parser reads it; walk descends into it
                text = red.hd.body if red.hd is not None else (red.target.text if red.target else '')
                if _MENTION_RE.search(text):
                    self.unresolved = True
                return
        if 'pipe' in site.fed:
            self.unresolved = True

    def _shell(self, site, res, args):
        k = 0
        has_c = has_s = False
        while k < len(args):
            v, _g = self._expand(args[k])
            if v is None:
                self.unresolved = True
                return
            if v in ('--', '-'):
                k += 1
                break
            if len(v) > 1 and v[0] in '-+' and not v.startswith('--'):
                letters = v[1:]
                if v[0] == '-' and 'n' in letters:
                    return  # read, never run (bash -n)
                if v[0] == '-' and 'c' in letters:
                    has_c = True
                if v[0] == '-' and 's' in letters:
                    has_s = True
                if v[-1] in 'oO' and k + 1 < len(args):
                    if (self._expand(args[k + 1])[0] or '') == 'noexec' and v[0] == '-':
                        return
                    k += 2
                    continue
                k += 1
                continue
            if v.startswith('--'):
                if v in ('--rcfile', '--init-file') and k + 1 < len(args):
                    self._path_target(args[k + 1])
                    k += 2
                    continue
                if v in ('--help', '--version'):
                    return
                k += 1
                continue
            break
        for a in res.assignments:
            if a.name in ('BASH_ENV', 'ENV') and a.value is not None:
                self._path_target(a.value)
        if has_c:
            code = args[k] if k < len(args) else None
            if res.payload is None:
                val = self._expand(code)[0] if code is not None else ''
                if val is None or _MENTION_RE.search(val):
                    self.unresolved = True
            return  # a parsed payload is walked as its own sites
        if k < len(args) and not has_s:
            self._operand(site, res, args[k], shell=True)
            return
        self._stdin(site, res, shell=True)

    def _operand(self, site, res, word, shell):
        v, is_glob = self._expand(word)
        if v in _STDIN_FILES or (v and v.startswith('/dev/fd/')):
            self._stdin(site, res, shell)
            return
        if any(p.kind.startswith('procsub') for p in word.parts):
            if res.payload is None or res.unresolved:
                self.unresolved = True
            return
        self._path_target(word, v, is_glob)

    def _python(self, site, res, args):
        k = 0
        while k < len(args):
            v, _g = self._expand(args[k])
            if v is None:
                self.unresolved = True
                return
            if v == '-':
                self._stdin(site, res, shell=False)
                return
            if v == '--':
                k += 1
                break
            if v.startswith('--'):
                k += 1
                continue
            if v.startswith('-') and len(v) > 1:
                for j, ch in enumerate(v[1:], 1):
                    if ch in _PY_VALUE_OPTS:
                        rest = v[j + 1:]
                        val = rest if rest else (self._expand(args[k + 1])[0] if k + 1 < len(args) else '')
                        if ch == 'm':
                            return  # a module, not a file
                        if ch == 'c':
                            if val is None or _MENTION_RE.search(val):
                                self.unresolved = True
                            return
                        if not rest:
                            k += 1
                        break
                k += 1
                continue
            break
        if k < len(args):
            self._operand(site, res, args[k], shell=False)
        else:
            self._stdin(site, res, shell=False)

    def _cd(self, args):
        vals = [self._expand(w)[0] for w in args]
        vals = [v for v in vals if v is None or not (v.startswith('-') and v != '-')]
        if not vals:
            target = self.home
        else:
            target = vals[0]
        if target is None or target == '-' or not target:
            self.cwd_unknown = True
            return
        if os.path.isabs(target):
            self.cwds.add(os.path.normpath(target))
        else:
            self.cwds |= {os.path.normpath(os.path.join(c, target)) for c in list(self.cwds)}

    def _site(self, site):
        cmd = site.cmd
        res = _sp.resolve(cmd)
        if res.head is None:
            return
        if res.unresolved and res.unresolved not in ('computed-shell-option', 'dynamic_head',
                                                     'script_file_computed', 'generated_code'):
            self.unresolved = True
        head, is_glob = self._expand(res.head)
        if head is None:
            self.unresolved = True
            return
        name = os.path.basename(head)
        args = list(res.args)
        if name in ('cd', 'pushd'):
            self._cd(args)
            return
        if name in ('source', '.'):
            ops = args[1:] if args and args[0].value() == '--' else args
            if ops:
                self._operand(site, res, ops[0], shell=True)
            return
        if name in _sp.SHELLS:
            self._shell(site, res, args)
            return
        if _PYTHON_RE.match(name):
            self._python(site, res, args)
            return
        if name in _NO_EXEC:
            return
        if name in _OPAQUE_RUNNERS or name in _STDIN_RUNNERS or name == 'git' \
                or _sp._SCRIPT_INTERP_RE.match(name):
            vals = [self._expand(w)[0] for w in args]
            named = any(v is None or _MENTION_RE.search(v) for v in vals)
            if name == 'git':
                named = named and any(v is not None and _GIT_RUNS.match(v) for v in vals)
            if name in _STDIN_RUNNERS and ('pipe' in site.fed or any(
                    r.fd == 0 for r in cmd.redirects)):
                named = True
            if named:
                self.unresolved = True
        if '/' in head or is_glob:
            self._path_target(res.head, head, is_glob)
        else:
            self._bare_target(res.head, head)


def _matched_wrapper(command: str, cwd: str | None = None) -> str | None:
    """Return the sentinel command-name if the command EXECUTES a guarded
    wrapper of the harness home (or, mentioning one, runs something that cannot
    be read), else None. A mere mention returns None."""
    cwd = cwd or os.getcwd()
    if _sp is None:  # pragma: no cover - the parser is part of the harness
        scan = without_heredoc_bodies(command)
        for name, patterns in _FALLBACK_PATTERNS.items():
            if any(pat.search(scan) for pat in patterns):
                return name
        return None
    try:
        s = _Scan(command, cwd)
    except Exception:  # fail closed on a reader failure over a mention
        return 'stop' if _MENTION_RE.search(command) else None
    if s.match is not None:
        return s.match
    if s.unresolved and s.mention:
        return 'stop'
    return None


def _read_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        sys.exit(0)


def _get_session_id(data: dict) -> str:
    try:
        return str(data.get('session_id', '') or '')
    except Exception:
        return ''


def _command_text(data: dict) -> str:
    ti = data.get('tool_input', {}) if isinstance(data, dict) else {}
    if not isinstance(ti, dict):
        return ''
    return ti.get('command', '') or ''


def _sentinel_path(cmd_name: str, sid: str) -> Path:
    return Path(_SENTINEL_DIR) / f'claude-{cmd_name}-userintent-{sid}.flag'


# Short-lived helper-authorization token. When THIS PreTool hook consumes a
# valid user-intent sentinel it mints this token; break-overnight-lock.py
# validates + consumes it before mutating isolation_released_at (defense in
# depth: the helper never trusts being reached, only a fresh PreTool grant).
_HELPER_AUTH_TTL_SECONDS = 30


def _helper_auth_path(cmd_name: str, sid: str) -> Path:
    return Path(_SENTINEL_DIR) / f'claude-{cmd_name}-helper-auth-{sid}.json'


def _mint_helper_auth(cmd_name: str, sid: str) -> None:
    try:
        _helper_auth_path(cmd_name, sid).write_text(json.dumps({
            'cmd': cmd_name,
            'session_id': sid,
            'expires_at': int(time.time()) + _HELPER_AUTH_TTL_SECONDS,
        }))
    except OSError:
        pass


def _consume_sentinel(path: Path) -> bool:
    """One-shot consume: True iff the sentinel existed with value 'true' and was
    successfully unlinked. A stale/already-consumed sentinel returns False."""
    try:
        if not path.exists():
            return False
        ok = path.read_text().strip() == 'true'
        # Unlink regardless (one-shot): a second invocation finds nothing.
        try:
            path.unlink()
        except OSError:
            return False
        return ok
    except OSError:
        return False


def _block(cmd_name: str, command: str) -> None:
    sys.stderr.write(
        f'\nUSER-INTENT GUARD: direct invocation of the /{cmd_name} release '
        'wrapper is blocked. This wrapper (break-overnight-lock.py / stop.sh) '
        'is the only sanctioned setter of isolation_released_at and may run '
        f'ONLY via the /{cmd_name} slash command, which writes a single-use '
        'user-intent sentinel. No live sentinel was found for this session, so '
        'an overnight actor cannot self-release isolation.\n'
        f'Blocked command: {command[:200]}\n'
    )
    sys.exit(2)


def main() -> None:
    data = _read_payload()
    if data.get('tool_name', '') != 'Bash':
        sys.exit(0)
    command = _command_text(data)
    if not command:
        sys.exit(0)
    cwd = data.get('cwd') if isinstance(data.get('cwd'), str) and os.path.isabs(data.get('cwd')) \
        else os.getcwd()
    cmd_name = _matched_wrapper(command, cwd)
    if cmd_name is None:
        sys.exit(0)
    sid = _get_session_id(data)
    sentinel = _sentinel_path(cmd_name, sid)
    if _consume_sentinel(sentinel):
        # Valid live user-intent sentinel: mint a fresh helper-auth token so the
        # helper can validate it (defense in depth), then allow.
        _mint_helper_auth(cmd_name, sid)
        sys.exit(0)
    _block(cmd_name, command)


if __name__ == '__main__':
    main()
