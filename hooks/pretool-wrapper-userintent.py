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
import fnmatch
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
# The decision has two halves.
#   1. A RUN the parser can read: the harness home's own wrapper file executed
#      (matched by realpath after `~`, `$HOME`/`${HOME}`, globs, brace expansion
#      and `cd`) as the command word behind transparent wrappers, a shell or
#      python script operand or stdin file (also `exec <` before a shell), a
#      `python -m` runner given the wrapper's path or the wrapper's module name,
#      `source`/`.`, a `find -exec {}` over find's literal matches, and every
#      nested `bash -c` string, substitution, function body, alias and heredoc-fed
#      shell; or a command-carrying variable (BASH_ENV, ENV, PYTHONSTARTUP,
#      *EDITOR, *PAGER, *_COMMAND, SHELL ...) or persisted command (crontab, a
#      shell rc file, git config, git -c run-keys) that names the wrapper.
#   2. Otherwise the previous text rule (the base) still decides, unless the
#      guard PROVES every mention harmless: an operand or pattern of a known
#      reader whose output goes nowhere that runs (grep, rg, cat, ls, sed -n,
#      awk/perl/ruby code that calls nothing, git readers, shellcheck, `bash -n`
#      with no later `+n`, `command -v`, `type`, `which`), a commit/PR message,
#      a print-only interpreter string, or a run target that resolves to a file
#      that is not the harness home's wrapper (a project's own scripts/stop.sh).
# A mention that is not proven harmless next to a run the guard cannot read (a
# computed command word, piped stdin, opaque interpreter code, an unknown cwd)
# is refused as well. The single-use sentinel is consumed only on a refused or
# passed run decision, never on a proven-harmless command.
_GUARDED_WRAPPERS = {
    'stop': (('hooks', 'stop.sh'), ('scripts', 'break-overnight-lock.py')),
}
_MENTION_RE = re.compile(r'stop\.sh|break-overnight-lock')
_WRAPPER_MODULES = frozenset(('break-overnight-lock',))

# The base text rule: refuses a wrapper path after a command position or an
# interpreter word. It still decides whatever the guard cannot prove harmless.
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
_SUBST_KINDS = frozenset(('cmdsub', 'backtick', 'procsub_in', 'procsub_out'))
_UNSAFE_CONTEXTS = frozenset(('cmdsub', 'backtick', 'procsub', 'pipe_shell'))
# Builtins and keywords that run no file.
_NO_EXEC = frozenset((
    'cd', 'pushd', 'popd', 'dirs', 'echo', 'printf', 'test', '[', '[[', 'true', 'false',
    ':', 'export', 'declare', 'typeset', 'local', 'readonly', 'set', 'unset', 'shift',
    'read', 'wait', 'type', 'hash', 'command', 'alias', 'unalias', 'return', 'exit',
    'break', 'continue', 'let', 'getopts', 'umask', 'ulimit', 'jobs', 'fg', 'bg', 'kill',
    'history', 'shopt', 'times', 'trap', 'disown', 'help', 'logout', 'mapfile',
    'readarray', 'compgen', 'complete', 'caller', 'eval', 'which', 'whereis'))
# Readers: they never run an operand. Their operands, patterns and strings are
# harmless while their output goes nowhere that runs.
_PLAIN_READERS = frozenset((
    'grep', 'egrep', 'fgrep', 'zgrep', 'rg', 'ag', 'cat', 'tac', 'nl', 'head', 'tail', 'less',
    'more', 'wc', 'ls', 'stat', 'file', 'du', 'tree', 'sha1sum', 'sha224sum', 'sha256sum',
    'sha384sum', 'sha512sum', 'md5sum', 'b2sum', 'cksum', 'sum', 'diff', 'cmp', 'comm', 'sort',
    'uniq', 'cut', 'tr', 'od', 'xxd', 'hexdump', 'strings', 'readlink', 'realpath', 'basename',
    'dirname', 'column', 'paste', 'fold', 'fmt', 'expand', 'unexpand', 'rev', 'jq', 'echo',
    'printf', 'true', 'false', 'test', '[', 'shellcheck', 'type', 'which', 'whereis', 'find',
    'hash', 'pwd', ':'))
# Commands that never change a file's content (a run target they name is still
# the file on disk).
_CONTENT_KEEPING = frozenset(('chmod', 'chown', 'chgrp', 'touch'))
_PY_READER_MODULES = frozenset(('py_compile', 'json.tool', 'tabnanny', 'tokenize', 'ast',
                                'pyclbr', 'dis', 'compileall', 'pydoc_data'))
_PY_SAFE_MODULES = frozenset(('sys', 'pathlib', 'json', 're', 'ast', 'collections', 'itertools',
                              'math', 'string', 'textwrap', 'hashlib', 'base64', 'binascii',
                              'datetime', 'time', 'io', 'tokenize', 'difflib', 'pprint', 'csv',
                              'statistics', 'fnmatch', 'glob', 'unicodedata', 'decimal',
                              'fractions', 'random', 'uuid', 'tomllib', 'shlex', 'keyword'))
_PY_BAD = re.compile(
    r'__|\b(?:exec|eval|compile|getattr|setattr|delattr|globals|locals|vars|breakpoint|input|'
    r'help|system|popen|spawn\w*|fork\w*|execv\w*|modules|builtins|subprocess|os|runpy|'
    r'importlib|ctypes|cffi|pty|code|codeop|pdb|bdb|cProfile|profile|trace|timeit|doctest|'
    r'unittest|site|webbrowser|shutil|signal|multiprocessing|threading|concurrent|asyncio|'
    r'socket|pickle|marshal|shelve|zipimport|pkgutil|platform|sysconfig|inspect|gc|types|'
    r'operator|dis|load_module|exec_module|run_path|run_module|write_text|write_bytes|'
    r'symlink_to|hardlink_to|rename|replace|chmod|touch|unlink|mkdir|rmdir|write|'
    r'writelines|truncate)\b')
_PY_OPEN_WRITE = re.compile(r'''open\s*\([^)]*,\s*(?:mode\s*=\s*)?[rb]?['"][^'"]*[wax+]''')
_PY_IMPORT = re.compile(r'\bimport\s+([\w.]+(?:\s*(?:as\s+\w+\s*)?,\s*[\w.]+)*)|\bfrom\s+([\w.]+)\s+import')
_NODE_BAD = re.compile(
    r'\b(?:require|import|process|eval|Function|global|globalThis|constructor|child_process|'
    r'spawn\w*|exec\w*|fork|module|Deno|Bun|setTimeout|setInterval|setImmediate|fetch|'
    r'WebAssembly|prototype|__proto__|this|Reflect|Proxy|Worker|fs)\b|`|[\w\])]\s*\[')
_PERL_BAD = re.compile(
    r'\b(?:system|exec|qx|open|sysopen|eval|do|require|use|no|fork|pipe|syscall|readpipe|'
    r'glob|unlink|rename|symlink|link|chmod|chown|kill|socket|dbmopen|truncate|mkdir|rmdir|'
    r'utime|chdir|ENV|INC|CORE|UNIVERSAL|sub|tie|bless|pack|unpack|select|ioctl|fcntl|dump|'
    r'goto|STDOUT|STDERR)\b|`|\$0|::|&\s*[{$]|\*\s*\{|\bq[qwx]?\s*[^\w\s]')
_PERL_SUBST = re.compile(r'\bs\s*([^\w\s{(\[<])(?:\\.|(?!\1).)*\1(?:\\.|(?!\1).)*\1([a-zA-Z]*)'
                         r'|\bs\s*\{[^}]*\}\s*\{[^}]*\}([a-zA-Z]*)')
_RUBY_BAD = re.compile(
    r'\b(?:system|exec|spawn|fork|open|popen\w*|eval|instance_eval|class_eval|module_eval|'
    r'instance_exec|send|public_send|__send__|require|require_relative|load|autoload|Kernel|IO|'
    r'File|FileUtils|Process|PTY|Open3|ObjectSpace|method|define_method|const_get|binding|'
    r'syscall|trap|at_exit|ENV|Dir|Object|BasicObject|Class|Module|Signal)\b|`|%x|\$0|::')
_AWK_BAD = re.compile(r'\bsystem\b|\|&?|\bgetline\b|@\w+|\b(?:print|printf)\b[^;{}\n]*>|'
                      r'\bENVIRON\b|\bPROCINFO\b')
_AWK_NAMES = frozenset(('awk', 'gawk', 'mawk', 'nawk'))
_SED_SAFE = re.compile(
    r'^\s*(?:(?:\d+|\$|/(?:\\.|[^/])*/)(?:\s*,\s*(?:\d+|\$|/(?:\\.|[^/])*/|[+~]\d+))?\s*!?\s*)?'
    r'(?:[pd=lnq]|s(.)(?:\\.|(?!\1).)*\1(?:\\.|(?!\1).)*\1[gpiImM0-9]*)?\s*$')
# Interpreters whose code the guard does not read beyond the inert checks above.
_CODE_RUNNERS = frozenset(('perl', 'ruby', 'node', 'nodejs', 'php', 'lua', 'tclsh', 'wish',
                           'Rscript', 'julia', 'deno', 'bun', 'osascript', 'expect', 'gdb',
                           'awk', 'gawk', 'mawk', 'nawk', 'busybox', 'irb', 'jshell'))
# Commands that run what their stdin holds, later or now.
_STDIN_RUNNERS = frozenset(('at', 'batch', 'crontab'))
_OTHER_SHELLS = frozenset(('fish', 'tcsh', 'csh', 'elvish', 'nu', 'xonsh', 'rc', 'es'))
_PY_RUNNERS = frozenset(('pytest', 'py.test', 'coverage', 'ipython', 'ipython3', 'pdb', 'pdb3'))
# Variables whose value is a command or a file some program runs.
_CMD_VAR_RE = re.compile(
    r'^(?:BASH_ENV|ENV|PYTHONSTARTUP|PROMPT_COMMAND|PS[0-4]|SHELL|LESSOPEN|LESSCLOSE|'
    r'PERL5OPT|PERL5DB|RUBYOPT|NODE_OPTIONS|LD_PRELOAD|LD_AUDIT|BROWSER|TERMINAL|FCEDIT|'
    r'GIT_SSH|GIT_EXTERNAL_DIFF|GIT_EXEC_PATH|GIT_TEMPLATE_DIR|SSH_ASKPASS|SUDO_ASKPASS|'
    r'\w*(?:EDITOR|PAGER|_COMMAND|_CMD|ASKPASS|_PROGRAM|_HOOK|_HOOKS))$')
# git configuration keys whose value runs a command.
_GIT_RUN_KEY = re.compile(
    r'^(?:alias\..*|core\.(?:pager|editor|sshcommand|hookspath|fsmonitor|askpass|gitproxy)|'
    r'pager\..*|sequence\.editor|include\..*|includeif\..*|filter\..*|diff\..*|merge\..*|'
    r'gpg\..*|credential.*|uploadpack\..*|receive\..*|man\..*|web\..*|browser\..*|'
    r'sendemail\..*|interactive\..*|.*\.(?:pager|editor|command|cmd|textconv|program|helper|'
    r'external|path|tool|hook|sshcommand|difffilter|clean|smudge|process))$', re.IGNORECASE)
_GIT_READ_SUBS = frozenset(('log', 'show', 'diff', 'blame', 'annotate', 'grep', 'ls-files',
                            'ls-tree', 'status', 'cat-file', 'rev-parse', 'shortlog', 'describe',
                            'show-ref', 'whatchanged', 'rev-list', 'add', 'commit', 'diff-tree',
                            'diff-files', 'diff-index', 'name-rev', 'check-ignore',
                            'check-attr', 'count-objects', 'reflog', 'stash', 'restore',
                            'branch', 'tag', 'remote', 'fetch', 'push', 'pull', 'switch',
                            'checkout', 'mv', 'rm', 'init', 'clone', 'version', 'help'))
_GIT_GLOBAL_VALUE = frozenset(('-C', '-c', '--git-dir', '--work-tree', '--namespace',
                               '--config-env', '--super-prefix', '--exec-path'))
_GH_MESSAGE_SUBS = frozenset(('pr', 'issue', 'release'))
_RC_FILES = frozenset(('.bashrc', '.bash_profile', '.bash_login', '.profile', '.bash_logout',
                       '.zshrc', '.zprofile', '.zshenv', '.zlogin', '.kshrc', '.mkshrc',
                       '.cshrc', '.tcshrc', '.inputrc', 'config.fish', 'environment',
                       '.pam_environment', '.xprofile', '.xinitrc', 'crontab'))
_BRACE_LIST = re.compile(r'\{([^{}]*,[^{}]*)\}')
_BRACE_SEQ = re.compile(r'\{(-?\w+)\.\.(-?\w+)\}')
_FIND_CAP = 5000


def _brace_variants(text: str, cap: int = 64) -> list[str]:
    """``text`` with its brace expansions applied (at most ``cap`` variants)."""
    todo, done = [text], []
    while todo and len(done) + len(todo) <= cap:
        t = todo.pop()
        m = _BRACE_LIST.search(t)
        if m is not None:
            todo.extend(t[:m.start()] + alt + t[m.end():] for alt in m.group(1).split(','))
            continue
        m = _BRACE_SEQ.search(t)
        if m is not None:
            a, b = m.group(1), m.group(2)
            if a.lstrip('-').isdigit() and b.lstrip('-').isdigit():
                lo, hi = sorted((int(a), int(b)))
                alts = [str(i) for i in range(lo, min(hi, lo + cap) + 1)]
            elif len(a) == 1 and len(b) == 1:
                lo, hi = sorted((ord(a), ord(b)))
                alts = [chr(i) for i in range(lo, min(hi, lo + cap) + 1)]
            else:
                alts = [m.group(0)]
            if alts == [m.group(0)]:
                done.append(t)
                continue
            todo.extend(t[:m.start()] + alt + t[m.end():] for alt in alts)
            continue
        done.append(t)
    return done + todo


def _mentions(text: str | None) -> bool:
    if not text:
        return False
    return any(_MENTION_RE.search(v) for v in _brace_variants(text))


def _dequoted_mentions(text: str) -> bool:
    return _mentions(re.sub(r'[\\\'"]', '', text))


def _base_refuses(command: str) -> str | None:
    """The previous text rule (kept as the fallback for what is not proven harmless)."""
    try:
        scan = without_heredoc_bodies(command)
    except Exception:
        scan = command
    for name, patterns in _FALLBACK_PATTERNS.items():
        if any(pat.search(scan) for pat in patterns):
            return name
    return None


def _py_inert(code: str | None) -> bool:
    """Python code that only computes and prints: it calls nothing that runs code."""
    if code is None or _PY_BAD.search(code) or _PY_OPEN_WRITE.search(code):
        return False
    for m in _PY_IMPORT.finditer(code):
        mods = m.group(1) or m.group(2) or ''
        for mod in re.split(r'\s*,\s*', mods):
            root = mod.split()[0].split('.')[0] if mod.split() else ''
            if root and root not in _PY_SAFE_MODULES:
                return False
    return True


def _node_inert(code: str | None) -> bool:
    return code is not None and not _NODE_BAD.search(code)


def _perl_inert(code: str | None) -> bool:
    if code is None or _PERL_BAD.search(code):
        return False
    for m in _PERL_SUBST.finditer(code):
        flags = m.group(2) or m.group(3) or ''
        if 'e' in flags:
            return False
    return True


def _ruby_inert(code: str | None) -> bool:
    return code is not None and not _RUBY_BAD.search(code)


def _awk_inert(code: str | None) -> bool:
    return code is not None and not _AWK_BAD.search(code)


def _sh_join(vals: list[str]) -> str:
    import shlex
    return ' '.join(shlex.quote(v) for v in vals)


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


# A file of this size or more that has the wrapper's exact content IS the wrapper (a
# copy made earlier); a smaller one is too generic to tell apart from a project stub.
_CONTENT_MATCH_MIN = 64
_IDENTITY = None


def _wrapper_identity() -> tuple[dict, dict]:
    """(st_dev, st_ino) -> command-name and (size, sha256) -> command-name of the wrappers."""
    global _IDENTITY
    if _IDENTITY is None:
        import hashlib
        inodes, digests = {}, {}
        for name, files in _GUARDED_WRAPPERS.items():
            for rel in files:
                for home in _harness_homes():
                    p = os.path.join(home, *rel)
                    try:
                        st = os.stat(p)
                        inodes[(st.st_dev, st.st_ino)] = name
                        if st.st_size >= _CONTENT_MATCH_MIN:
                            with open(p, 'rb') as fh:
                                digests[(st.st_size, hashlib.sha256(fh.read()).hexdigest())] = name
                    except OSError:
                        continue
        _IDENTITY = (inodes, digests)
    return _IDENTITY


def _wrapper_of(path: str, by_path: dict) -> str | None:
    """The command-name when ``path`` is a guarded wrapper: the same path, the same
    file (a hard link), or a file with the wrapper's exact content (a copy)."""
    name = by_path.get(os.path.realpath(path))
    if name is not None:
        return name
    try:
        st = os.stat(path)
    except OSError:
        return None
    inodes, digests = _wrapper_identity()
    name = inodes.get((st.st_dev, st.st_ino))
    if name is not None:
        return name
    import stat as _stat
    if not _stat.S_ISREG(st.st_mode) or not any(size == st.st_size for size, _d in digests):
        return None
    import hashlib
    try:
        with open(path, 'rb') as fh:
            return digests.get((st.st_size, hashlib.sha256(fh.read()).hexdigest()))
    except OSError:
        return None


def _writes_file(red) -> bool:
    """A redirection that writes a file (not /dev/null, not an fd duplicate)."""
    try:
        if not red.writes():
            return False
    except Exception:
        return True
    tgt = red.target.value() if red.target is not None else None
    return tgt not in ('/dev/null', '/dev/stderr', '/dev/stdout', '/dev/tty')


class _Scan:
    """One read of a Bash command: the wrapper it runs (match), whether it runs
    something that cannot be read (unsure), and whether it mentions a wrapper
    anywhere that is not proven harmless (unproven)."""

    def __init__(self, command: str, cwd: str, depth: int = 0, cwds=None, cdpath=False):
        self.command = command
        self.depth = depth
        self.home = os.environ.get('HOME', '')
        self.by_path, self.by_name = _wrapper_index()
        self.cwds = set(cwds) if cwds else {cwd}
        self.cwd = cwd
        self.cwd_unknown = False
        self.cdpath = cdpath
        self.match = None
        self.unsure = False
        self.unproven = False
        self.persist = False
        self.path_assigned = False
        self.exec_stdin = None
        self.harmless = set()      # id() of run-target words resolved to a non-wrapper file
        self.others = []           # (word, value) of words a command may write or copy from
        self.outflow = {}          # id(SimpleCommand) -> (consumer, writes a file)
        self.mapped = set()
        self.inert_memo = {}
        self.site_of = {}
        self.covered = []          # spans of the command text whose mentions are accounted for
        self.word_mention = False
        self.lessopen = False      # LESSOPEN / LESSCLOSE set by the command: less runs it
        self.computed_run = False  # a run target built at run time ($(...), xargs, a loop)
        self.loops = []            # (variable, list words, body script) of for/select loops
        script = _sp.parse(command)
        if script.error is not None:
            self.unsure = True
            if _dequoted_mentions(command):
                self.unproven = True
        self._map_script(script, None, False)
        self.sites = list(_sp.walk(script))
        self.res = {}
        for site in self.sites:
            self._map_script(site.script, None, False)
            self.res[id(site)] = _sp.resolve(site.cmd)
            self.site_of.setdefault(id(site.cmd), site)
        self.nested = []
        for site in self.sites:
            for w in self._words(site.cmd):
                sp_ = self._span(w)
                if sp_ is not None:
                    self.nested.append((sp_, len(site.context), site))
        for site in self.sites:
            self._lessopen_scan(site)
        for site in self.sites:
            self._collect(site)
        for site in self.sites:
            self._site(site)
        for loop in self.loops:
            self._loop(*loop)
        for site in self.sites:
            self._classify(site)
        self._uncovered()
        if self.computed_run and self.match is None and self._harness_context():
            self.match = 'stop'  # fail closed: a run built at run time beside the wrapper

    # -- structure -----------------------------------------------------------
    def _map_script(self, script, consumer, writes):
        if script is None or id(script) in self.mapped:
            return
        self.mapped.add(id(script))
        for pl, _sep in script.items:
            n = len(pl.stages)
            for k, st in enumerate(pl.stages):
                cons = pl.stages[k + 1] if k + 1 < n else consumer
                if isinstance(st, _sp.Compound):
                    w = writes or any(_writes_file(r) for r in st.redirects)
                    if st.kind in ('for', 'select') and st.header and st.body:
                        var = st.header[0].value()
                        if var and re.match(r'^[A-Za-z_]\w*$', var):
                            self.loops.append((var, list(st.header[1:]), st.body))
                    for h in st.header:
                        sp_ = self._span(h)
                        if _mentions(self._own_text(h)):
                            self.word_mention = True
                            self.unproven = True
                            if sp_ is not None:
                                self.covered.append(sp_)
                    for body in st.body:
                        self._map_script(body, cons, w)
                else:
                    self.outflow[id(st)] = (cons, writes)

    def _wrapper_file(self, path):
        return _wrapper_of(path, self.by_path)

    def _span(self, word):
        try:
            a, b = word.span
        except Exception:
            return None
        if a is None or b is None or a < 0 or b > len(self.command) or self.command[a:b] != word.text:
            return None
        return (a, b)

    @staticmethod
    def _words(cmd):
        out = [a.word for a in cmd.assignments]
        out.extend(cmd.words)
        out.extend(r.target for r in cmd.redirects if r.target is not None)
        return out

    @staticmethod
    def _own_text(word) -> str:
        """The text of a word outside its substitutions (they are read as their own commands)."""
        try:
            return ''.join(p.text for p in word.parts if p.kind not in _SUBST_KINDS)
        except Exception:
            return word.text

    def _word_mentions(self, word) -> bool:
        return _mentions(self._own_text(word))

    # -- word reading --------------------------------------------------------
    def _values(self, word):
        """[(value, is_glob)] of a word after ~, $HOME, ${HOME} and brace expansion;
        None when computed."""
        if word is None:
            return None
        acc = [('', '', False)]  # (plain, glob pattern, is_glob)
        for k, p in enumerate(word.parts):
            if p.kind == 'lit':
                t = p.text
                if k == 0 and p.quote == _sp.BARE and t[:1] == '~' and (len(t) == 1 or t[1] == '/'):
                    t = self.home + t[1:]
                alts = [(t, glob.escape(t), False)]
            elif p.kind == 'param' and p.text in ('HOME', '{HOME}') and self.home:
                alts = [(self.home, glob.escape(self.home), False)]
            elif p.kind == 'glob':
                alts = [(p.text, p.text, True)]
            elif p.kind == 'brace':
                alts = [(v, glob.escape(v), False) for v in _brace_variants(p.text)]
            else:
                return None
            acc = [(a + t, ap + tp, ag or tg) for a, ap, ag in acc for t, tp, tg in alts][:64]
        return [(ap if ag else a, ag) for a, ap, ag in acc]

    def _expand(self, word):
        """(value, is_glob) of a word; (None, False) when computed. A brace word gives its first variant."""
        vals = self._values(word)
        if not vals:
            return None, False
        return vals[0]

    def _collect(self, site):
        cmd = site.cmd
        res = self.res[id(site)]
        for a in tuple(cmd.assignments) + tuple(res.assignments):
            if a.name == 'PATH':
                self.path_assigned = True
            if a.name == 'CDPATH' and (a.static_value() is None or a.static_value() != ''):
                self.cdpath = True
        reader = self._inert(cmd) or (res.name in _CONTENT_KEEPING)
        for w in list(cmd.words[1:]) + [r.target for r in cmd.redirects if r.target is not None]:
            v, _g = self._expand(w)
            if v is None:
                continue
            if v.startswith('PATH=') or v.startswith('PATH+='):
                self.path_assigned = True
            if (v.startswith('CDPATH=') and v != 'CDPATH=') and res.name in (
                    'export', 'declare', 'typeset', 'local', 'readonly'):
                self.cdpath = True
            if not reader:
                self.others.append((w, v))
        for red in cmd.redirects:
            if red.hd is not None and not reader:
                self.others.append((None, red.hd.body))

    def _named_elsewhere(self, word, value) -> bool:
        """The same command names this file in another word a command may write
        or copy (it may create, copy or link it), so its content on disk now is
        not what runs."""
        base = os.path.basename(value.rstrip('/'))
        norm = os.path.normpath(value)
        span = self._span(word) if word is not None else None
        for w, v in self.others:
            if w is word:
                continue
            if w is not None and span is not None:
                ws = self._span(w)
                if ws is not None and ws[0] <= span[0] and span[1] <= ws[1]:
                    continue  # the word that carries this one (a `bash -c` string)
            if os.path.normpath(v) == norm or (base and base in v):
                return True
        return False

    # -- reader proof --------------------------------------------------------
    def _reader(self, cmd) -> bool:
        """The command reads, prints or checks only: none of its operands runs."""
        if not isinstance(cmd, _sp.SimpleCommand):
            return False
        words = [w.value() for w in cmd.words]
        if not words:
            return True
        if words[0] == 'command' and len(words) > 1 and words[1] in ('-v', '-V'):
            return True
        res = _sp.resolve(cmd)
        last_open = res.unresolved == 'computed-shell-option' and self._last_quoted_param(cmd, res.args)
        if res.unresolved and not str(res.unresolved).startswith('xargs') and not last_open:
            return False
        if res.unresolved and not last_open and not self._xargs_safe(res):
            return False
        if res.head is None:
            return not res.args
        hv = res.head.value()
        if hv is None:
            return False
        name = os.path.basename(hv)
        vals = [w.value() for w in res.args]
        sv = [v for v in vals if v is not None]
        if name in _PLAIN_READERS:
            if name == 'rg' and any((v.startswith('--pre') and not v.startswith('--pre-glob')) or
                                    v.startswith('--hostname-bin') for v in sv):
                return False
            if name == 'less' and self.lessopen:
                return False
            if name == 'sort' and any(v.startswith('--compress-program') for v in sv):
                return False
            if name == 'find' and any(v in ('-exec', '-execdir', '-ok', '-okdir', '-delete',
                                            '-fprint', '-fprint0', '-fprintf', '-fls') for v in sv):
                return False
            if name == 'hash' and any(v.startswith('-') and 'p' in v for v in sv):
                return False
            if name == 'printf' and any(v.startswith('-v') for v in sv):
                return False
            return True
        if name in _sp.SHELLS:
            return self._shell_noexec(vals, self._last_quoted_param(cmd, res.args))
        if _PYTHON_RE.match(name):
            return self._py_reader(cmd, vals)
        if name in ('node', 'nodejs'):
            return self._code_opt(vals, ('-e', '--eval', '-p', '--print'), _node_inert, ())
        if name in _AWK_NAMES:
            return self._awk_reader(vals)
        if name == 'perl':
            return self._code_opt(vals, ('-e', '-E'), _perl_inert, ('-M', '-m', '-x', '-d', '-f'))
        if name == 'ruby':
            return self._code_opt(vals, ('-e',), _ruby_inert, ('-r', '-x', '-S', '-I'))
        if name == 'sed':
            return self._sed_reader(vals)
        if name == 'git':
            return self._git_reader(vals)
        if name == 'gh':
            return bool(sv) and sv[0] in _GH_MESSAGE_SUBS and len(sv) > 1 and \
                sv[1] in ('create', 'edit', 'comment', 'view', 'list', 'diff', 'checks', 'status')
        return False

    def _last_quoted_param(self, cmd, args) -> bool:
        """The last argument is one double-quoted variable (a single operand word) and the
        shell reads no stdin a `+n` in it could turn into a run."""
        if not args or not re.match(r'^"\$\{?[A-Za-z_]\w*\}?"$', args[-1].text or ''):
            return False
        site = self.site_of.get(id(cmd))
        if site is None or 'pipe' in site.fed or any(r.fd == 0 for r in cmd.redirects):
            return False
        return True

    @staticmethod
    def _shell_noexec(vals, last_open=False) -> bool:
        """`bash -n` (or `-o noexec`) with no later `+n` / `+o noexec`."""
        noexec = False
        k = 0
        while k < len(vals):
            v = vals[k]
            if v is None:
                return noexec and last_open and k == len(vals) - 1
            if v in ('--', '-'):
                break
            if v.startswith('--'):
                if v in ('--rcfile', '--init-file'):
                    k += 2
                    continue
                k += 1
                continue
            if len(v) > 1 and v[0] in '-+':
                letters = v[1:]
                if 'c' in letters and v[0] == '-':
                    return False
                if 'n' in letters:
                    noexec = v[0] == '-'
                if letters[-1:] in ('o', 'O'):
                    nxt = vals[k + 1] if k + 1 < len(vals) else None
                    if letters[-1] == 'o' and nxt == 'noexec':
                        noexec = v[0] == '-'
                    k += 2
                    continue
                k += 1
                continue
            break
        return noexec

    def _py_reader(self, cmd, vals) -> bool:
        k = 0
        while k < len(vals):
            v = vals[k]
            if v is None:
                return False
            if v == '-':
                return self._heredoc_inert(cmd, _py_inert)
            if v.startswith('--'):
                if v in ('--check-hash-based-pycs',):
                    k += 2
                    continue
                k += 1
                continue
            if v.startswith('-') and len(v) > 1:
                for j, ch in enumerate(v[1:], 1):
                    if ch in _PY_VALUE_OPTS:
                        rest = v[j + 1:]
                        val = rest if rest else (vals[k + 1] if k + 1 < len(vals) else None)
                        if ch == 'c':
                            return _py_inert(val)
                        if ch == 'm':
                            return val in _PY_READER_MODULES
                        if not rest:
                            k += 1
                        break
                k += 1
                continue
            return False  # a script operand runs
        return self._heredoc_inert(cmd, _py_inert)

    @staticmethod
    def _heredoc_inert(cmd, check) -> bool:
        for red in cmd.redirects:
            if red.fd == 0 and red.hd is not None:
                return check(red.hd.body)
            if red.fd == 0 and red.op == '<<<' and red.target is not None:
                return check(red.target.value())
        return False

    @staticmethod
    def _code_opt(vals, code_opts, check, bad_opts) -> bool:
        """An interpreter given its code with -e: inert code, no module loads, no script operand."""
        code = None
        k = 0
        while k < len(vals):
            v = vals[k]
            if v is None:
                return False
            if any(v == b or (len(b) == 2 and v.startswith(b)) for b in bad_opts):
                return False
            if v in code_opts or (v.startswith('-') and not v.startswith('--') and
                                  v[-1:] in ''.join(o[1] for o in code_opts if len(o) == 2)):
                if k + 1 >= len(vals) or vals[k + 1] is None:
                    return False
                code = vals[k + 1]
                if not check(code):
                    return False
                k += 2
                continue
            if v.startswith('-'):
                k += 1
                continue
            break
        return code is not None

    @staticmethod
    def _awk_reader(vals) -> bool:
        k = 0
        prog = None
        while k < len(vals):
            v = vals[k]
            if v is None:
                return False
            if v in ('-f', '--file', '-E', '--exec', '-l', '--load', '-i', '--include') or \
                    v.startswith('--file=') or v.startswith('--load='):
                return False
            if v in ('-F', '-v', '--assign', '--field-separator'):
                k += 2
                continue
            if v in ('-e', '--source'):
                if k + 1 >= len(vals) or not _awk_inert(vals[k + 1]):
                    return False
                prog = vals[k + 1]
                k += 2
                continue
            if v == '--':
                k += 1
                break
            if v.startswith('-') and len(v) > 1:
                k += 1
                continue
            break
        if prog is None:
            if k >= len(vals) or vals[k] is None:
                return False
            prog = vals[k]
        return _awk_inert(prog)

    @staticmethod
    def _sed_reader(vals) -> bool:
        scripts, quiet, k, have_e = [], False, 0, False
        while k < len(vals):
            v = vals[k]
            if v is None:
                return False
            if v in ('-n', '--quiet', '--silent'):
                quiet = True
            elif v in ('-e', '--expression'):
                if k + 1 >= len(vals) or vals[k + 1] is None:
                    return False
                scripts.append(vals[k + 1])
                have_e = True
                k += 2
                continue
            elif v.startswith('-') and len(v) > 1 and v != '--':
                if any(c in v for c in 'ifs') or v.startswith('--in-place') or \
                        v.startswith('--file'):
                    return False
                if 'n' in v[1:] and not v.startswith('--'):
                    quiet = True
            elif not have_e and not scripts:
                scripts.append(v)
            k += 1
        del quiet
        return bool(scripts) and all(
            all(_SED_SAFE.match(part) for part in s.split(';')) for s in scripts)

    def _git_reader(self, vals) -> bool:
        k, aliases = 0, {}
        while k < len(vals):
            v = vals[k]
            if v is None:
                return False
            if v in ('-c',) and k + 1 < len(vals):
                kv = vals[k + 1]
                if kv is None or not self._git_config_safe(kv, aliases):
                    return False
                k += 2
                continue
            if v.startswith('--exec-path') or v.startswith('--config-env'):
                return False
            if v in _GIT_GLOBAL_VALUE:
                k += 2
                continue
            if v.startswith('-'):
                k += 1
                continue
            break
        if k >= len(vals):
            return True
        sub = vals[k]
        rest = [x for x in vals[k + 1:] if x is not None]
        if sub in aliases:
            parts = aliases[sub].split()
            sub, rest = (parts[0] if parts else ''), parts[1:] + rest
        if sub not in _GIT_READ_SUBS:
            return False
        if sub == 'grep' and any(r.startswith('-O') or r.startswith('--open-files') for r in rest):
            return False
        if sub in ('diff', 'log', 'show') and any(r == '--ext-diff' for r in rest):
            return False
        if sub == 'rebase' or any(r in ('--exec', '-x') for r in rest):
            return False
        if sub in ('branch', 'tag', 'remote', 'stash', 'fetch', 'push', 'pull', 'clone') and \
                any(_mentions(r) for r in rest):
            return False
        return True

    @staticmethod
    def _git_config_safe(kv, aliases) -> bool:
        key, _eq, val = kv.partition('=')
        if key.lower().startswith('alias.'):
            if val.lstrip().startswith('!'):
                return False
            aliases[key[6:]] = val
            return True
        return not _GIT_RUN_KEY.match(key)

    def _inert(self, cmd) -> bool:
        """A reader whose output goes nowhere that runs: its mentions are harmless."""
        if not isinstance(cmd, _sp.SimpleCommand):
            return False
        key = id(cmd)
        if key in self.inert_memo:
            return self.inert_memo[key]
        self.inert_memo[key] = False
        site = self.site_of.get(key)
        ok = site is not None and not (set(site.context) & _UNSAFE_CONTEXTS) and \
            self._reader(cmd) and not any(_writes_file(r) for r in cmd.redirects)
        if ok:
            cons, writes = self.outflow.get(key, (None, False))
            if writes or (cons is not None and not self._inert(cons)):
                ok = False
        self.inert_memo[key] = ok
        return ok

    # -- targets -------------------------------------------------------------
    def _path_target(self, word, values=None):
        """A file a command runs: match it by realpath, or mark it unreadable."""
        if values is None:
            values = self._values(word)
        if not values:
            self.unsure = True
            if word is not None and self._built(word):
                self.computed_run = True
            return
        found_all, risky = [], False
        for value, is_glob in values:
            if not os.path.isabs(value) and self.cwd_unknown:
                self.unsure = True
                return
            bases = [''] if os.path.isabs(value) else sorted(self.cwds)
            found = []
            for base in bases:
                joined = os.path.join(base, value) if base else value
                found.extend(glob.glob(joined) if is_glob else ([joined] if os.path.exists(joined) else []))
            for f in found:
                name = self._wrapper_file(f)
                if name is not None:
                    self.match = self.match or name
            if word is not None and self._named_elsewhere(word, value):
                risky = True
            elif not found and (is_glob or os.path.basename(value) in self.by_name):
                risky = True
            found_all.extend(found)
        if risky:
            self.unsure = True
        elif word is not None and self.match is None:
            self.harmless.add(id(word))

    def _bare_target(self, word, value):
        """A command word without a slash, looked up on PATH."""
        found = shutil.which(value)
        if found is not None:
            name = self._wrapper_file(found)
            if name is not None:
                self.match = self.match or name
        if value in self.by_name and (found is None or self.path_assigned):
            self.unsure = True
        elif found is None and self._named_elsewhere(word, value):
            self.unsure = True
        elif self.path_assigned and self._named_elsewhere(word, value):
            self.unsure = True
        elif found is not None and value not in self.by_name:
            self.harmless.add(id(word))

    def _stdin(self, site, res, shell, inert=None):
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
                text = red.hd.body if red.hd is not None else (
                    red.target.value() if red.target is not None else None)
                if inert is not None and text is not None and inert(text):
                    return
                if text is None or _mentions(text):
                    self.unsure = True
                return
        if 'pipe' in site.fed:
            self.unsure = True
            return
        if self.exec_stdin is not None:
            self._path_target(self.exec_stdin)

    def _shell(self, site, res, args):
        vals = [self._expand(w)[0] for w in args]
        if self._shell_noexec(vals, self._last_quoted_param(site.cmd, args)):
            return  # read, never run (bash -n with no later +n)
        k = 0
        has_c = has_s = False
        while k < len(args):
            v = vals[k]
            if v is None:
                self.unsure = True
                if self._built(args[k]):
                    self.computed_run = True  # a script operand built at run time
                return
            if v in ('--', '-'):
                k += 1
                break
            if len(v) > 1 and v[0] in '-+' and not v.startswith('--'):
                letters = v[1:]
                if v[0] == '-' and 'c' in letters:
                    has_c = True
                if v[0] == '-' and 's' in letters:
                    has_s = True
                if v[-1] in 'oO' and k + 1 < len(args):
                    k += 2
                    continue
                k += 1
                continue
            if v.startswith('--'):
                if v in ('--rcfile', '--init-file') and k + 1 < len(args):
                    self._path_target(args[k + 1])
                    k += 2
                    continue
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
                if val is None or _mentions(val):
                    self.unsure = True
            return  # a parsed payload is walked as its own sites
        if k < len(args) and not has_s:
            self._operand(site, res, args[k], shell=True)
            return
        self._stdin(site, res, shell=True)

    def _operand(self, site, res, word, shell):
        v, _g = self._expand(word)
        if v in _STDIN_FILES or (v and v.startswith('/dev/fd/')):
            self._stdin(site, res, shell)
            return
        if any(p.kind.startswith('procsub') for p in word.parts):
            if res.payload is None or res.unresolved:
                self.unsure = True
                self.computed_run = True
            return
        self._path_target(word)

    def _python(self, site, res, args):
        vals = [self._expand(w)[0] for w in args]
        if self._py_reader(site.cmd, vals):
            return
        k = 0
        while k < len(args):
            v = vals[k]
            if v is None:
                self.unsure = True
                if self._built(args[k]):
                    self.computed_run = True  # a script operand built at run time
                return
            if v == '-':
                self._stdin(site, res, shell=False, inert=_py_inert)
                return
            if v == '--':
                k += 1
                break
            if v.startswith('--'):
                k += 2 if v == '--check-hash-based-pycs' else 1
                continue
            if v.startswith('-') and len(v) > 1:
                for j, ch in enumerate(v[1:], 1):
                    if ch in _PY_VALUE_OPTS:
                        rest = v[j + 1:]
                        val = rest if rest else (vals[k + 1] if k + 1 < len(vals) else '')
                        if ch == 'm':
                            self._py_module(site, res, val, args[k + (1 if rest else 2):])
                            return
                        if ch == 'c':
                            if val is None or _mentions(val):
                                self.unsure = True
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
            self._stdin(site, res, shell=False, inert=_py_inert)

    def _py_module(self, site, res, mod, rest):
        """`python -m <module> args`: the wrapper's module name, or a runner module given its path."""
        if mod is None:
            self.unsure = True
            return
        if mod in _PY_READER_MODULES:
            return
        if mod in _WRAPPER_MODULES or _mentions(mod):
            dirs = set(self.cwds)
            pp = None
            for a in tuple(site.cmd.assignments) + tuple(res.assignments):
                if a.name == 'PYTHONPATH':
                    pp = a.static_value()
                    if pp is None:
                        self.unsure = True
                        return
            if pp is None:
                pp = os.environ.get('PYTHONPATH', '')
            for d in pp.split(':'):
                if d:
                    if d[:1] == '~':
                        d = self.home + d[1:]
                    dirs.add(d)
            if self.cwd_unknown:
                self.unsure = True
            for d in dirs:
                f = os.path.join(d, mod.replace('.', '/') + '.py')
                name = self._wrapper_file(f) if os.path.exists(f) else None
                if name is not None:
                    self.match = self.match or name
            if self.match is None:
                self.unsure = True
            return
        self._args_naming_files(rest)

    def _args_naming_files(self, words):
        """A runner (cProfile, trace, pdb, pytest, coverage ...) given the wrapper's path runs it."""
        for w in words:
            vals = self._values(w)
            if vals is None:
                if self._word_mentions(w):
                    self.unsure = True
                continue
            for v, is_glob in vals:
                if not _mentions(v) and not is_glob:
                    continue
                bases = [''] if os.path.isabs(v) else sorted(self.cwds)
                for base in bases:
                    joined = os.path.join(base, v) if base else v
                    for f in (glob.glob(joined) if is_glob else [joined]):
                        if os.path.exists(f):
                            name = self._wrapper_file(f)
                            if name is not None:
                                self.match = self.match or name

    def _cd(self, args):
        vals = [self._expand(w)[0] for w in args]
        vals = [v for v in vals if v is None or not (v.startswith('-') and v != '-')]
        target = self.home if not vals else vals[0]
        if target is None or target == '-' or not target:
            self.cwd_unknown = True
            return
        if self.cdpath and not os.path.isabs(target) and not target.startswith(('./', '../')) \
                and target not in ('.', '..'):
            self.cwd_unknown = True
            return
        if os.path.isabs(target):
            self.cwds.add(os.path.normpath(target))
        else:
            self.cwds |= {os.path.normpath(os.path.join(c, target)) for c in list(self.cwds)}

    def _sub(self, text, cwds=None):
        """Read ``text`` as a command of its own (a command string an unknown runner may run)."""
        if self.depth >= 3:
            if _mentions(text):
                self.unsure = True
            return
        try:
            sub = _Scan(text, self.cwd, self.depth + 1, cwds or self.cwds, self.cdpath)
        except Exception:
            self.unsure = self.unsure or _mentions(text)
            return
        if sub.match is not None:
            self.match = self.match or sub.match
        if (sub.unsure and sub.unproven) or sub.persist:
            self.unsure = True

    def _find(self, site, res, args):
        """`find ... -exec {}`: the files find hands to a command that may run them."""
        vals = [self._expand(w)[0] for w in args]
        i = 0
        while i < len(vals) and vals[i] in ('-L', '-H', '-P'):
            i += 1
        starts = []
        while i < len(vals) and (vals[i] is None or not (vals[i].startswith('-') or vals[i] in ('(', '!', ')'))):
            starts.append(vals[i])
            i += 1
        names, blocks, simple = [], [], True
        j = i
        while j < len(vals):
            p = vals[j]
            if p in ('-exec', '-execdir', '-ok', '-okdir'):
                k = j + 1
                argv = []
                while k < len(vals) and vals[k] not in (';', '+'):
                    argv.append(vals[k])
                    k += 1
                blocks.append((p, argv))
                j = k + 1
                continue
            if p in ('-name', '-iname') and j + 1 < len(vals):
                names.append((p, vals[j + 1]))
                j += 2
                continue
            if p in ('-type', '-maxdepth', '-mindepth', '-xdev', '-mount', '-depth', '-print',
                     '-print0', '-follow', '-noleaf'):
                j += 2 if p in ('-type', '-maxdepth', '-mindepth') else 1
                continue
            simple = False
            j += 1
        risky = []
        for kind, argv in blocks:
            if any(a is None for a in argv):
                risky.append((kind, argv))
                continue
            if not any('{}' in a for a in argv):
                continue
            head = os.path.basename(argv[0]) if argv else ''
            if head in _PLAIN_READERS and head != 'find':
                continue
            risky.append((kind, argv))
        if not risky:
            return
        mentioned = any(self._word_mentions(w) for w in args)
        if not simple or not starts or any(s is None for s in starts) or \
                any(n is None for _k, n in names) or any(a is None for _k, b in risky for a in b):
            if mentioned:
                self.unsure = True
            return
        matches, seen = [], 0
        for s in starts:
            s = self.home + s[1:] if s[:1] == '~' and (len(s) == 1 or s[1] == '/') else s
            roots = [s] if os.path.isabs(s) else [os.path.join(c, s) for c in sorted(self.cwds)]
            if not os.path.isabs(s) and self.cwd_unknown:
                self.unsure = True
                return
            for root in roots:
                cands = [root]
                if os.path.isdir(root):
                    for dp, dns, fns in os.walk(root):
                        seen += len(dns) + len(fns)
                        if seen > _FIND_CAP:
                            self.unsure = self.unsure or mentioned
                            return
                        cands.extend(os.path.join(dp, n) for n in dns + fns)
                for c in cands:
                    bn = os.path.basename(c.rstrip('/')) or c
                    ok = True
                    for kind, pat in names:
                        if kind == '-iname':
                            ok = ok and fnmatch.fnmatch(bn.lower(), pat.lower())
                        else:
                            ok = ok and fnmatch.fnmatchcase(bn, pat)
                    if ok and os.path.exists(c):
                        if s.startswith('./') or s == '.':
                            c = os.path.join(s, os.path.relpath(c, root)) if c != root else s
                        matches.append(c)
        for kind, argv in risky:
            for m in matches[:200]:
                if kind in ('-execdir', '-okdir'):
                    absm = m if os.path.isabs(m) else os.path.join(sorted(self.cwds)[0], m)
                    rep, cwds = './' + os.path.basename(absm), {os.path.dirname(absm)}
                else:
                    rep, cwds = m, None
                self._sub(_sh_join([a.replace('{}', rep) for a in argv]), cwds)

    def _site(self, site):
        cmd = site.cmd
        res = self.res[id(site)]
        words = [w.value() for w in cmd.words]
        if words == ['exec']:
            for red in cmd.redirects:
                if red.fd == 0 and red.op in ('<', '<>') and red.target is not None:
                    self.exec_stdin = red.target
        if res.head is None:
            if res.args or (res.unresolved and words):
                self.unsure = True  # a wrapper whose command word could not be read
            return
        if res.unresolved and res.unresolved not in ('computed-shell-option', 'dynamic_head',
                                                     'script_file_computed', 'generated_code'):
            if not (str(res.unresolved).startswith('xargs') and self._reader(cmd)):
                self.unsure = True
                if str(res.unresolved).startswith('xargs'):
                    self.computed_run = True  # xargs hands its input to a command that may run it
        head, is_glob = self._expand(res.head)
        if head is None or (res.unresolved == 'dynamic_head' and _sp._ASSIGN_RE.match(head)):
            self.unsure = True  # a computed command word, or `env` stopped at an assignment
            if self._built(res.head):
                self.computed_run = True
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
        if name in _OTHER_SHELLS:
            ops = [w for w in args if not (w.value() or '-').startswith(('-', '+'))]
            if ops and not any((w.value() or '') in ('-c', '-n') for w in args):
                self._path_target(ops[0])
        if name in _PY_RUNNERS:
            self._args_naming_files(args)
        if name == 'find':
            self._find(site, res, args)
        reader = self._reader(cmd)
        vals = [self._expand(w)[0] for w in args]
        named = any(self._word_mentions(w) for w in args) or any(
            red.hd is not None and _mentions(red.hd.body) for red in cmd.redirects) or any(
            red.op == '<<<' and red.target is not None and self._word_mentions(red.target)
            for red in cmd.redirects)
        if name in _RC_FILES or name == 'crontab':
            if not (name == 'crontab' and vals and all(v in ('-l', '-u') or (v and not v.startswith('-'))
                                                       for v in vals[:1]) and vals[0] == '-l'):
                self.persist = True
        for red in cmd.redirects:
            if _writes_file(red) and red.target is not None:
                tv = self._expand(red.target)[0]
                if tv is None or os.path.basename(tv) in _RC_FILES or '/systemd/' in tv or \
                        '/autostart/' in tv or '/cron' in tv:
                    self.persist = True
        if name == 'tee' and any(v is None or os.path.basename(v) in _RC_FILES for v in vals):
            self.persist = True
        if name == 'git':
            self._git(vals)
        if name == 'rg':
            self._rg(args)
        if name == 'sed':
            self._sed(site, args)
        if name == 'less' and self.lessopen:
            self._less(args)
        if name in _NO_EXEC:
            return
        if name == 'parallel' and ':::' in vals:
            vals = [v for v in vals if v not in (':::', '::::')]
        if not reader and named:
            if name in _CODE_RUNNERS or name in _STDIN_RUNNERS or _sp._SCRIPT_INTERP_RE.match(name):
                self.unsure = True
            for w, v in zip(args, vals):
                if v is not None and _mentions(v) and re.search(r'[\s;&|`$()]', v):
                    self._sub(v.lstrip('!'))
            for idx, v in enumerate(vals):
                if v is None:
                    continue
                b = os.path.basename(v)
                if (b in _sp.SHELLS or _PYTHON_RE.match(b) or b in ('source', '.', 'env', 'exec')
                        or b in _sp.WRAPPERS or b in _sp.PEEL) and all(x is not None for x in vals[idx:]):
                    self._sub(_sh_join(vals[idx:]))
                    break
        if name in _STDIN_RUNNERS and ('pipe' in site.fed or any(r.fd == 0 for r in cmd.redirects)):
            self.persist = True
        if '/' in head or is_glob:
            self._path_target(res.head)
        else:
            self._bare_target(res.head, head)

    def _git(self, vals):
        """git -c run-keys, `!` aliases, rebase --exec and `git config` writes that name the wrapper."""
        k = 0
        while k < len(vals):
            v = vals[k]
            if v is None:
                return
            if v == '-c' and k + 1 < len(vals):
                kv = vals[k + 1] or ''
                key, _eq, val = kv.partition('=')
                if (_GIT_RUN_KEY.match(key) or key.lower().startswith('alias.')) and _mentions(val):
                    self._sub(val.lstrip('!'))
                    self.unsure = True
                k += 2
                continue
            if v in _GIT_GLOBAL_VALUE:
                k += 2
                continue
            if v.startswith('-'):
                k += 1
                continue
            break
        sub = vals[k] if k < len(vals) else None
        rest = [x for x in vals[k + 1:] if x is not None]
        if sub == 'config' and not any(r in ('--get', '--get-all', '--list', '-l', '--get-regexp',
                                             '--show-origin', '--unset') for r in rest):
            if any(_mentions(r) for r in rest):
                self.persist = True
        if sub in ('rebase', 'bisect', 'submodule', 'filter-branch', 'difftool', 'mergetool'):
            if any(_mentions(r) for r in rest):
                self.unsure = True

    # -- runs built at run time, rg --pre, sed e, LESSOPEN, loops -----------------
    # Readers that stay readers whatever words xargs appends (no option of theirs runs
    # a program or names one: not find, rg, ag, sort, sed, awk, git, less ...).
    _XARGS_SAFE = frozenset((
        'grep', 'egrep', 'fgrep', 'cat', 'tac', 'nl', 'head', 'tail', 'wc', 'ls', 'stat',
        'file', 'du', 'sha1sum', 'sha224sum', 'sha256sum', 'sha384sum', 'sha512sum', 'md5sum',
        'b2sum', 'cksum', 'sum', 'cmp', 'comm', 'uniq', 'cut', 'tr', 'od', 'xxd', 'hexdump',
        'strings', 'readlink', 'realpath', 'basename', 'dirname', 'column', 'paste', 'fold',
        'fmt', 'expand', 'unexpand', 'rev', 'echo', 'printf', 'true', 'false', 'test', '[',
        'shellcheck', 'type', 'which', 'whereis', 'pwd', ':', 'diff', 'jq', 'tree'))
    _RG_VALUE_SHORT = 'efgtTmABCMjrEd'
    _RG_VALUE_LONG = frozenset((
        '--regexp', '--file', '--glob', '--iglob', '--type', '--type-not', '--max-count',
        '--after-context', '--before-context', '--context', '--max-columns', '--threads',
        '--pre', '--pre-glob', '--type-add', '--type-clear', '--replace', '--colors',
        '--encoding', '--sort', '--sortr', '--max-depth', '--maxdepth', '--max-filesize',
        '--path-separator', '--ignore-file', '--dfa-size-limit', '--regex-size-limit',
        '--context-separator', '--field-match-separator', '--field-context-separator',
        '--engine', '--hostname-bin', '--hyperlink-format', '--color', '--generate'))

    @staticmethod
    def _built(word) -> bool:
        """The word is built at run time by a command substitution or backticks."""
        try:
            return any(p.kind in ('cmdsub', 'backtick') for p in word.parts)
        except Exception:
            return False

    def _xargs_safe(self, res) -> bool:
        if res.head is None:
            return False
        hv = res.head.value()
        if hv is None:
            return False
        name = os.path.basename(hv)
        if name in self._XARGS_SAFE:
            return True
        if _PYTHON_RE.match(name):
            vals = [w.value() for w in res.args]
            return len(vals) >= 2 and vals[0] == '-m' and vals[1] in _PY_READER_MODULES
        return False

    def _lessopen_scan(self, site):
        cmd = site.cmd
        res = self.res[id(site)]
        for a in tuple(cmd.assignments) + tuple(res.assignments):
            if a.name in ('LESSOPEN', 'LESSCLOSE'):
                self.lessopen = True
        for w in cmd.words:
            t = w.value()
            t = w.text if t is None else t
            if re.match(r'''^["']?(?:LESSOPEN|LESSCLOSE)\+?=''', t or ''):
                self.lessopen = True

    def _existing(self, value, is_glob):
        """Existing paths a word value names (relative to every known cwd); None when the cwd is unknown."""
        if not os.path.isabs(value) and self.cwd_unknown:
            return None
        bases = [''] if os.path.isabs(value) else sorted(self.cwds)
        out = []
        for base in bases:
            joined = os.path.join(base, value) if base else value
            if is_glob:
                out.extend(glob.glob(joined)[:500])
            elif os.path.exists(joined):
                out.append(joined)
        return out

    def _tree_holds_wrapper(self, path) -> bool | None:
        """True when ``path`` is a wrapper or a directory holding one; None past the walk cap."""
        if os.path.isfile(path):
            return self._wrapper_file(path) is not None
        if not os.path.isdir(path):
            return False
        real = os.path.realpath(path)
        for wp in self.by_path:
            if wp == real or wp.startswith(real.rstrip(os.sep) + os.sep):
                return True
        seen = 0
        for dp, dns, fns in os.walk(path):
            seen += len(dns) + len(fns)
            if seen > _FIND_CAP:
                return None
            for fn in fns:
                if self._wrapper_file(os.path.join(dp, fn)) is not None:
                    return True
        return False

    def _words_hold_wrapper(self, words, trees=False) -> None:
        """Set match when a word names the wrapper (a directory holding it with ``trees``);
        unsure when a word cannot be read."""
        for w in words:
            vals = self._values(w)
            if not vals:
                self.unsure = True
                if self._built(w):
                    self.computed_run = True
                continue
            for v, g in vals:
                found = self._existing(v, g)
                if found is None:
                    self.unsure = True
                    continue
                for f in found:
                    hit = self._tree_holds_wrapper(f) if trees else (
                        os.path.isfile(f) and self._wrapper_file(f) is not None)
                    if hit is None:
                        self.unsure = True
                    elif hit:
                        self.match = self.match or 'stop'

    def _rg(self, args):
        """`rg --pre PROG` runs PROG on every searched file (and --hostname-bin runs a program)."""
        progs, positional, given, k = [], [], False, 0
        vals = [self._expand(w)[0] for w in args]
        while k < len(args):
            v = vals[k]
            if v is None:
                positional.append(args[k])
                k += 1
                continue
            if v == '--':
                positional.extend(args[k + 1:])
                break
            if v.startswith('--'):
                name, eq, val = v.partition('=')
                takes = name in self._RG_VALUE_LONG
                vw = None if eq else (args[k + 1] if takes and k + 1 < len(args) else None)
                if name in ('--pre', '--hostname-bin'):
                    progs.append(vw if not eq else val)
                if name in ('--regexp', '--file'):
                    given = True
                k += 1 if (eq or not takes) else 2
                continue
            if v.startswith('-') and len(v) > 1:
                for j, ch in enumerate(v[1:], 1):
                    if ch in self._RG_VALUE_SHORT:
                        if ch in 'ef':
                            given = True
                        k += 1 if v[j + 1:] else 2
                        break
                else:
                    k += 1
                continue
            positional.append(args[k])
            k += 1
        if not progs:
            return
        for p in progs:
            if p is None:
                self.unsure = True
                self.computed_run = True
                continue
            pv = p if isinstance(p, str) else self._expand(p)[0]
            if pv is None:
                self.unsure = True
                self.computed_run = True
                continue
            if '/' in pv:
                pv = self.home + pv[1:] if pv[:1] == '~' and (len(pv) == 1 or pv[1] == '/') else pv
                for f in self._existing(pv, False) or []:
                    if self._wrapper_file(f) is not None:
                        self.match = self.match or 'stop'
            else:
                found = shutil.which(pv)
                if found is not None and self._wrapper_file(found) is not None:
                    self.match = self.match or 'stop'
                if pv in self.by_name:
                    self.unsure = True
        paths = positional if given else positional[1:]
        if not paths:
            if self.cwd_unknown:
                self.unsure = True
            for c in sorted(self.cwds):
                hit = self._tree_holds_wrapper(c)
                if hit is None:
                    self.unsure = True
                elif hit:
                    self.match = self.match or 'stop'
            return
        self._words_hold_wrapper([w for w in paths if w.value() != '-'], trees=True)

    @staticmethod
    def _sed_has_e(s: str) -> bool:
        """The sed script has an `e` command or an `s///e` flag (True too when it cannot be read)."""
        i, n = 0, len(s)

        def regex_end(i, delim):
            while i < n:
                c = s[i]
                if c == '\\':
                    i += 2
                    continue
                if c == delim:
                    return i + 1
                if c == '\n' and delim != '\n':
                    return -1
                i += 1
            return -1

        def to_eol(i):
            while i < n and s[i] != '\n':
                i += 2 if s[i] == '\\' else 1
            return i

        def address(i):
            if i < n and s[i].isdigit():
                while i < n and (s[i].isdigit() or s[i] == '~'):
                    i += 1
            elif i < n and s[i] == '$':
                i += 1
            elif i < n and s[i] in '/\\':
                delim = '/'
                if s[i] == '\\':
                    if i + 1 >= n:
                        return -1
                    delim, i = s[i + 1], i + 1
                i = regex_end(i + 1, delim)
                if i < 0:
                    return -1
                while i < n and s[i] in 'IM':
                    i += 1
            return i

        while i < n:
            c = s[i]
            if c in ' \t\n;{}!':
                i += 1
                continue
            if c == '#':
                i = to_eol(i)
                continue
            j = address(i)
            if j < 0:
                return True
            if j != i:
                i = j
                while i < n and s[i] in ' \t':
                    i += 1
                if i < n and s[i] == ',':
                    i += 1
                    while i < n and s[i] in ' \t':
                        i += 1
                    if i < n and s[i] in '+~':
                        i += 1
                        while i < n and s[i].isdigit():
                            i += 1
                    else:
                        j = address(i)
                        if j < 0 or j == i:
                            return True
                        i = j
                while i < n and s[i] in ' \t!':
                    i += 1
                continue
            if c == 'e':
                return True
            if c in 'sy':
                if i + 1 >= n or s[i + 1] in '\n\\':
                    return True
                delim = s[i + 1]
                k = regex_end(i + 2, delim)
                k = regex_end(k, delim) if k >= 0 else -1
                if k < 0:
                    return True
                i = k
                if c == 's':
                    while i < n and (s[i].isalnum()):
                        if s[i] == 'e':
                            return True
                        if s[i] in 'wW':
                            i = to_eol(i)
                            break
                        i += 1
                while i < n and s[i] in ' \t':
                    i += 1
                if i < n and s[i] not in ';\n}#':
                    return True
                continue
            if c in 'aic:btTrRwWv':
                if c in ':btTv':
                    while i < n and s[i] not in ';\n':
                        i += 1
                else:
                    i = to_eol(i)
                continue
            if c in 'qQlL':
                i += 1
                while i < n and (s[i].isdigit() or s[i] in ' \t'):
                    i += 1
                continue
            if c in '=dDgGhHnNpPxzF':
                i += 1
                continue
            return True
        return False

    def _sed_scripts(self, vals):
        """(scripts, operands) of a sed call; scripts is None when one cannot be read."""
        scripts, files, ops, k, given = [], [], [], 0, False
        while k < len(vals):
            v = vals[k]
            if v is None:
                if not given and not scripts and not files:
                    return None, ops
                ops.append(None)
                k += 1
                continue
            if v == '--':
                rest = vals[k + 1:]
                if not given and rest:
                    scripts.append(rest[0])
                    rest = rest[1:]
                ops.extend(rest)
                break
            if v.startswith('--'):
                name, eq, val = v.partition('=')
                if name in ('--expression', '--file'):
                    given = True
                    val = val if eq else (vals[k + 1] if k + 1 < len(vals) else None)
                    if val is None:
                        return None, ops
                    (scripts if name == '--expression' else files).append(val)
                    k += 1 if eq else 2
                    continue
                k += 2 if (name == '--line-length' and not eq) else 1
                continue
            if v.startswith('-') and len(v) > 1:
                adv = 1
                for j, ch in enumerate(v[1:], 1):
                    if ch in 'efl':
                        rest = v[j + 1:]
                        val = rest if rest else (vals[k + 1] if k + 1 < len(vals) else None)
                        if not rest:
                            adv = 2
                        if ch != 'l':
                            given = True
                            if val is None:
                                return None, ops
                            (scripts if ch == 'e' else files).append(val)
                        break
                    if ch == 'i':
                        break  # -i[SUFFIX]
                k += adv
                continue
            if not given and not scripts:
                scripts.append(v)
            else:
                ops.append(v)
            k += 1
        for f in files:
            if f == '-':
                return None, ops
            f = self.home + f[1:] if f[:1] == '~' and (len(f) == 1 or f[1] == '/') else f
            found = self._existing(f, False)
            if not found:
                return None, ops
            try:
                with open(found[0], errors='replace') as fh:
                    scripts.append(fh.read(1 << 20))
            except OSError:
                return None, ops
        return scripts, ops

    @staticmethod
    def _sed_unescape(text: str) -> str:
        """sed's own escapes (\\xHH, \\oNNN, \\dNNN, \\cX) decoded, as sed would before it runs a line."""
        def one(m):
            for grp, base in ((1, 16), (2, 8), (3, 10)):
                if m.group(grp) is not None:
                    return chr(int(m.group(grp), base))
            return m.group(0)
        return re.sub(r'\\(?:x([0-9A-Fa-f]{1,2})|o([0-7]{1,3})|d([0-9]{1,3}))', one, text)

    def _sed(self, site, args):
        """sed with an `e` command or `s///e` flag runs text as a shell command: when the
        command names the wrapper anywhere (escaped forms included, or an input file that
        is the wrapper or names it) it is a run; otherwise it is not proven harmless."""
        vals = [w.value() for w in args]
        scripts, ops = self._sed_scripts(vals)
        if scripts is not None and not any(self._sed_has_e(s) for s in scripts):
            return
        self.unsure = True
        text = self._sed_unescape(self.command)
        if _dequoted_mentions(text) or any(_dequoted_mentions(self._sed_unescape(s))
                                           for s in (scripts or [])):
            self.match = self.match or 'stop'
            return
        for v in ops:
            if v is None:
                self.computed_run = True
                continue
            v = self.home + v[1:] if v[:1] == '~' and (len(v) == 1 or v[1] == '/') else v
            for f in self._existing(v, False) or []:
                if not os.path.isfile(f):
                    continue
                if self._wrapper_file(f) is not None:
                    self.match = self.match or 'stop'
                    return
                try:
                    with open(f, errors='replace') as fh:
                        if _dequoted_mentions(self._sed_unescape(fh.read(1 << 20))):
                            self.match = self.match or 'stop'
                            return
                except OSError:
                    continue

    def _less(self, args):
        """less with a LESSOPEN/LESSCLOSE the command sets runs it over each file it opens."""
        ops = [w for w in args if not (w.value() or 'x').startswith(('-', '+'))]
        self._words_hold_wrapper(ops)

    def _loop(self, var, items, body):
        """`for v in LIST; do ... $v ...; done`: a body that runs the loop variable runs
        every file the list expands to."""
        pat = re.compile(r'^\{?[#!]?' + re.escape(var) + r'(?!\w)')
        runs = False
        for scr in body:
            for site in _sp.walk(scr):
                cmd = site.cmd
                uses = False
                for w in self._words(cmd):
                    try:
                        parts = w.parts
                    except Exception:
                        continue
                    if any(p.kind == 'param' and pat.match(p.text or '') for p in parts):
                        uses = True
                        break
                if uses and not self._inert(cmd):
                    runs = True
                    break
            if runs:
                break
        if not runs:
            return
        for w in items:
            vals = self._values(w)
            if not vals:
                self.unsure = True
                self.computed_run = True
                continue
            for v, g in vals:
                for f in self._existing(v, g) or []:
                    if os.path.isfile(f) and self._wrapper_file(f) is not None:
                        self.match = self.match or 'stop'

    def _harness_context(self) -> bool:
        """The command runs in the harness home's hooks/ or scripts/ directory, names one of
        them or a name directly in one, or names a file that is a wrapper."""
        dirs = set()
        for home in _harness_homes():
            for sub in ('hooks', 'scripts'):
                d = os.path.join(home, sub)
                dirs.add(os.path.normpath(d))
                dirs.add(os.path.realpath(d))

        def inside(p):
            """The directory itself, or a non-directory name directly in it."""
            for q in (os.path.normpath(p), os.path.realpath(p)):
                if q in dirs or (os.path.dirname(q) in dirs and not os.path.isdir(q)):
                    return True
            return False

        if any(os.path.normpath(c) in dirs or os.path.realpath(c) in dirs for c in self.cwds):
            return True
        words = []
        for site in self.sites:
            words.extend(self._words(site.cmd))
        for _v, items, _b in self.loops:
            words.extend(items)
        for w in words:
            vals = self._values(w) if w is not None else None
            for v, g in vals or ():
                bases = [''] if os.path.isabs(v) else sorted(self.cwds)
                for base in bases:
                    cand = os.path.join(base, v) if base else v
                    if inside(cand):
                        return True
                for f in self._existing(v, g) or []:
                    if os.path.isfile(f) and self._wrapper_file(f) is not None:
                        return True
        return False

    # -- mentions ------------------------------------------------------------
    def _transparent(self, word, site) -> bool:
        """The word carries code the parser read (a `bash -c` string, a find -exec argv):
        its mentions are accounted for by the nested commands' words."""
        span = self._span(word)
        if span is None:
            return False
        depth = len(site.context)
        for (a, b), d, other in self.nested:
            if other is site or d <= depth:
                continue
            if other.context[-1] in ('alias', 'pipe_shell'):
                continue
            if span[0] <= a and b <= span[1]:
                return True
        return False

    def _classify(self, site):
        cmd = site.cmd
        res = self.res[id(site)]
        inert = self._inert(cmd)
        assigns = list(cmd.assignments) + list(res.assignments)
        if res.name in ('export', 'declare', 'typeset', 'local', 'readonly', 'env'):
            for w in res.args:
                if _sp._ASSIGN_PARTS_RE.match(w.raw.text):
                    assigns.append(_sp.Assignment(w))
        for a in assigns:
            text = self._own_text(a.word)
            sp_ = self._span(a.word)
            if sp_ is not None:
                self.covered.append(sp_)
            if _mentions(text):
                self.word_mention = True
                self.unproven = True
                if _CMD_VAR_RE.match(a.name or ''):
                    self.match = self.match or 'stop'
        for w in list(cmd.words) + [r.target for r in cmd.redirects if r.target is not None]:
            sp_ = self._span(w)
            if sp_ is not None:
                self.covered.append(sp_)
            if not self._word_mentions(w):
                continue
            self.word_mention = True
            if inert or id(w) in self.harmless or self._transparent(w, site) or \
                    self._other_file(w):
                continue
            self.unproven = True
        for red in cmd.redirects:
            if red.hd is None:
                continue
            try:
                self.covered.append(red.hd.body_span)
            except Exception:
                pass
            if not _mentions(red.hd.body):
                continue
            self.word_mention = True
            if inert:
                continue
            if res.payload is not None and res.payload_kind == 'heredoc_shell' and not res.unresolved:
                continue
            self.unproven = True

    def _other_file(self, word) -> bool:
        """The word names existing files, none of them the harness home's wrapper, and
        nothing else in the command writes or copies them."""
        vals = self._values(word)
        if not vals or self.cwd_unknown:
            return False
        for v, is_glob in vals:
            if is_glob:
                return False
            bases = [''] if os.path.isabs(v) else sorted(self.cwds)
            for base in bases:
                f = os.path.join(base, v) if base else v
                if not os.path.exists(f) or self._wrapper_file(f) is not None:
                    return False
            if self._named_elsewhere(word, v):
                return False
        return True

    def _uncovered(self):
        """A mention the parse left outside every word (a loop list, a comment) is not proven."""
        for m in _MENTION_RE.finditer(self.command):
            a = m.start()
            if not any(s <= a < e for s, e in self.covered):
                self.unproven = True
                return
        if not self.word_mention and _dequoted_mentions(self.command):
            self.unproven = True


def _matched_wrapper(command: str, cwd: str | None = None) -> str | None:
    """Return the sentinel command-name when the command is a RUN decision: it
    runs a guarded wrapper of the harness home, or the base text rule refuses
    it and the guard cannot prove every mention harmless. A command whose
    mentions are all proven harmless returns None (and keeps the sentinel)."""
    cwd = cwd or os.getcwd()
    base = _base_refuses(command)
    if _sp is None:  # pragma: no cover - the parser is part of the harness
        return base
    try:
        s = _Scan(command, cwd)
    except Exception:  # fail closed on a reader failure over a mention
        return 'stop' if (base or _dequoted_mentions(command)) else None
    if s.match is not None:
        return s.match
    if s.unproven and (s.unsure or s.persist):
        return 'stop'
    if base is not None and s.unproven:
        return base
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
