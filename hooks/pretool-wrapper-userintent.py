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
from lib import locations  # noqa: E402
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
# Harness scripts whose stdout is eval'd by the harness's own procedures (shell assignments only).
_EVAL_EMITTERS = frozenset(('session-index.py',))

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
from lib import bash_read_only as _bro  # noqa: E402 -- the programs that only read

# Directory holding the user-intent sentinels: where hooks/prompt-workflow.py writes them.
_SENTINEL_DIR = harness_state_dir()

_PYTHON_RE = re.compile(r'^(?:python[\d.]*|pypy[\d.]*)$')
_PY_VALUE_OPTS = 'cmWXQ'
_STDIN_FILES = locations.STDIN_DEVICES
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
# Readers that stay readers whatever words xargs appends (no option of theirs runs a program
# or names one: not find, rg, ag, sort, sed, awk, git, less ...): lib/bash_read_only's
# readers, and those of its checked ones whose other forms write but run nothing.
_XARGS_SAFE = _bro.ANY_ARGS | {'file', 'printf', 'test', '[', 'uniq', 'xxd', 'tree', 'shellcheck'}
# Readers: they never run an operand. Their operands, patterns and strings are
# harmless while their output goes nowhere that runs.
_PLAIN_READERS = _XARGS_SAFE | {'zgrep', 'rg', 'ag', 'less', 'more', 'sort', 'find', 'hash'}
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
_AWK_NAMES = frozenset(_sp.AWK_NAMES) if _sp is not None else frozenset()
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
# less runs these over each file it opens.
_LESS_HOOK_VARS = ('LESSOPEN', 'LESSCLOSE')
_HOME_PARAMS = ('HOME', '{HOME}')  # the parameter texts of $HOME and ${HOME}
# Variables whose value is a command or a file some program runs.
_CMD_VAR_RE = re.compile(
    r'^(?:BASH_ENV|ENV|PYTHONSTARTUP|PROMPT_COMMAND|PS[0-4]|SHELL|LESSOPEN|LESSCLOSE|'
    r'PERL5OPT|PERL5DB|RUBYOPT|NODE_OPTIONS|LD_PRELOAD|LD_AUDIT|BROWSER|TERMINAL|FCEDIT|'
    r'GIT_SSH|GIT_EXTERNAL_DIFF|GIT_EXEC_PATH|GIT_TEMPLATE_DIR|SSH_ASKPASS|SUDO_ASKPASS|'
    r'\w*(?:EDITOR|PAGER|_COMMAND|_CMD|ASKPASS|_PROGRAM|_HOOK|_HOOKS))$')
# git configuration keys whose value runs a command (lib/git_facts.py).
from lib.git_facts import GIT_RUN_CONFIG_KEY_RE as _GIT_RUN_KEY  # noqa: E402
_GIT_READ_SUBS = frozenset(('log', 'show', 'diff', 'blame', 'annotate', 'grep', 'ls-files',
                            'ls-tree', 'status', 'cat-file', 'rev-parse', 'shortlog', 'describe',
                            'show-ref', 'whatchanged', 'rev-list', 'add', 'commit', 'diff-tree',
                            'diff-files', 'diff-index', 'name-rev', 'check-ignore',
                            'check-attr', 'count-objects', 'reflog', 'stash', 'restore',
                            'branch', 'tag', 'remote', 'fetch', 'push', 'pull', 'switch',
                            'checkout', 'mv', 'rm', 'init', 'clone', 'version', 'help'))
_GIT_GLOBAL_VALUE = _sp.GIT_GLOBAL_VALUE_OPTS if _sp is not None else frozenset()  # read by _Scan, which needs _sp
from lib.git_facts import GIT_CONFIG_READ_OPTIONS as _GIT_CONFIG_READS  # noqa: E402
from lib.git_facts import GIT_CONFIG_READ_SUBCOMMANDS as _GIT_CONFIG_READ_SUBS  # noqa: E402
from lib.git_facts import GIT_SHELL_PAYLOAD_SUBCOMMANDS as _GIT_SHELL_PAYLOAD_SUBS  # noqa: E402
_GH_MESSAGE_SUBS = frozenset(('pr', 'issue', 'release'))
_RC_FILES = frozenset(('.bashrc', '.bash_profile', '.bash_login', '.profile', '.bash_logout',
                       '.zshrc', '.zprofile', '.zshenv', '.zlogin', '.kshrc', '.mkshrc',
                       '.cshrc', '.tcshrc', '.inputrc', 'config.fish', 'environment',
                       '.pam_environment', '.xprofile', '.xinitrc', 'crontab'))
_BRACE_LIST = re.compile(r'\{([^{}]*,[^{}]*)\}')
_BRACE_SEQ = re.compile(r'\{(-?\w+)\.\.(-?\w+)\}')
_FIND_CAP = 5000
_RG_CONF_UNKNOWN = object()  # an rg config whose programs the guard cannot read
_COMPUTED = object()  # a program name built at run time
_GIT_LESS = object()  # git's own pager when nothing sets one: `less`, looked up on PATH


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


def _harness_dirs() -> set:
    """The harness home's hooks/ and scripts/ directories (as given and by realpath)."""
    dirs = set()
    for home in _harness_homes():
        for sub in ('hooks', 'scripts'):
            d = os.path.join(home, sub)
            dirs.add(os.path.normpath(d))
            dirs.add(os.path.realpath(d))
    return dirs


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
    return tgt not in locations.TERMINAL_SINKS


class _Scan:
    """One read of a Bash command: the wrapper it runs (match), whether it runs
    something that cannot be read (unsure), and whether it mentions a wrapper
    anywhere that is not proven harmless (unproven)."""

    def __init__(self, command: str, cwd: str, depth: int = 0, cwds=None, cdpath=False,
                 rgprogs=None):
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
        self.feeders = {}          # id(pipeline stage) -> the stage piped into it
        self.mapped = set()
        self.inert_memo = {}
        self.site_of = {}
        self.covered = []          # spans of the command text whose mentions are accounted for
        self.word_mention = False
        self.lessopen = False      # LESSOPEN / LESSCLOSE set by the command: less runs it
        self.computed_run = False  # a run target built at run time ($(...), xargs, a loop)
        self.loops = []            # (variable, list words, body script) of for/select loops
        self.arrays = {}           # array name -> element words of `a=(...)` assignments
        self.rgconf = []           # RIPGREP_CONFIG_PATH values the command sets (Word, str or None)
        self.rgprogs = list(rgprogs or ())  # config programs inherited from the outer command
        self.pager_env = {}        # GIT_PAGER / PAGER the command sets (str or _COMPUTED)
        self.git_config_written = False  # git config the command writes or overrides
        self.computed_targets = []  # run-target words with a part computed at run time
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
            self._array_scan(site, script)
        for site in self.sites:
            self._collect(site)
        for site in self.sites:
            self._site(site)
        for loop in self.loops:
            self._loop(*loop)
        for site in self.sites:
            self._classify(site)
        self._uncovered()
        if self.match is None and any(self._names_harness(w) or self._resolves_harness(w)
                                      for w in self.computed_targets):
            self.match = 'stop'  # fail closed: a run target computed inside the harness dirs
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
                if k + 1 < n:
                    self.feeders[id(pl.stages[k + 1])] = st
                if isinstance(st, _sp.Compound):
                    w = writes or any(_writes_file(r) for r in st.redirects)
                    if st.kind in _sp.LOOP_VAR_KINDS and st.header and st.body:
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
            elif p.kind == 'param' and p.text in _HOME_PARAMS and self.home:
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
            if (v.startswith('CDPATH=') and v != 'CDPATH=') and res.name in _sp.DECLARATION_BUILTINS:
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
        if words[0] == 'command' and len(words) > 1 and words[1] in _sp.COMMAND_LOOKUP_OPTS:
            return True
        res = _sp.resolve(cmd)
        last_open = res.unresolved == 'computed-shell-option' and (
            self._last_quoted_param(cmd, res.args) or self._lead_open(cmd, res))
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
            if name == 'rg' and any(v.split('=', 1)[0] in _sp.RG_PROGRAM_OPTS for v in sv):
                return False
            if name == 'rg' and '--no-config' not in sv and self._rg_config_progs():
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
            return self._shell_noexec(vals, self._last_quoted_param(cmd, res.args),
                                       list(res.args), self._lead_checker(cmd, res, res.args))
        if _PYTHON_RE.match(name):
            return self._py_reader(cmd, vals)
        if name in _sp.NODE_NAMES:
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
    def _shell_noexec(vals, last_open=False, words=None, lead_ok=None) -> bool:
        """`bash -n` (or `-o noexec`) with no later `+n` / `+o noexec`. A computed word whose
        first character is a literal other than `-` / `+` is the script operand (every word
        after it is an argument of the script), so it cannot turn the check into a run;
        ``lead_ok(k)`` proves the same for a computed word whose values the guard reads."""
        noexec = False
        k = 0
        while k < len(vals):
            v = vals[k]
            if v is None:
                if noexec and words is not None and k < len(words):
                    try:
                        first = words[k].parts[0]
                        lead = first.text or '' if first.kind == 'lit' else ''
                    except Exception:
                        lead = ''
                    if lead and lead[0] not in '-+':
                        return True
                    if lead_ok is not None and lead_ok(k):
                        return True
                return noexec and last_open and k == len(vals) - 1
            if v in _sp.OPTION_ENDS:
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

    # -- `bash -n` with a computed operand: proven when no value can start an option ----------
    _FIELD_CAP = 2000

    def _lead_open(self, cmd, res) -> bool:
        """A shell whose computed option word is proven a script operand under -n."""
        head = res.head.value() if res.head is not None else None
        if head is None or os.path.basename(head) not in _sp.SHELLS:
            return False
        args = list(res.args)
        vals = [self._expand(w)[0] for w in args]
        return self._shell_noexec(vals, False, args, self._lead_checker(cmd, res, args))

    def _lead_checker(self, cmd, res, args):
        """lead_ok(k) for _shell_noexec: the computed word args[k] gives a first field whose
        first character is neither `-` nor `+` for every value the guard reads (the command's
        literal assignments, loop lists, `$(echo|ls|readlink -f|realpath ...)`), so it is the
        script operand and every later word is an argument of the script; a word that may
        expand to no field passes only as the last word (`bash -n` then reads stdin, still
        under -n). Never with BASH_ENV / ENV set by the command."""
        if any(a.name in ('BASH_ENV', 'ENV') for a in
               list(getattr(cmd, 'assignments', ())) + list(getattr(res, 'assignments', ()))):
            return None
        args = list(args)

        def check(k):
            try:
                return k < len(args) and self._lead_safe(args[k], k == len(args) - 1)
            except Exception:
                return False
        return check

    def _lead_safe(self, word, last) -> bool:
        for p in word.parts:
            split = p.quote == _sp.BARE and p.kind != 'lit'
            vals = self._part_values(p, first=p is word.parts[0])
            if vals is None:
                return False
            empty = False
            for v, complete in vals:
                s = v.lstrip(' \t\n') if split else v
                if not s:
                    if not complete:
                        return False
                    empty = True
                    continue
                firsts = [s]
                if split and p.kind != 'lit':
                    fld = s.split()[0] if (complete or re.search(r'\s', s)) else s
                    if any(c in fld for c in '*?['):
                        got = self._glob_rel(fld)
                        if got is None:
                            return False
                        firsts.extend(got)
                if any(f[:1] in _sp.OPTION_SIGNS for f in firsts):
                    return False
            if not empty:
                return True
        return last  # the word may expand to no field: `bash -n` alone reads stdin under -n

    def _part_values(self, p, first=False):
        """[(value, complete)] a word part may take; None when the guard cannot read it."""
        if p.kind == 'lit':
            t = p.text or ''
            if first and p.quote == _sp.BARE and t[:1] == '~' and (len(t) == 1 or t[1] == '/'):
                t = self.home + t[1:]
            return [(t, True)]
        if p.kind == 'glob':
            return [(p.text or '', True)]
        if p.kind == 'param':
            m = re.match(r'^\{?([A-Za-z_]\w*)\}?$', p.text or '')
            if not m:
                alts = self._pe_alts(p.text or '', 1)  # `${x OP ...}` on the command's values
                if len(alts) >= self._ALT_CAP:
                    return None
                return [self._alt_str(a) for a in alts]
            name = m.group(1)
            if name == 'HOME' and self.home:
                return [(self.home, True)]
            out = []
            lv = self._loop_values().get(name)
            amap = self._assign_map()
            if lv is None and name not in amap:
                return None
            if lv is not None:
                if lv is False:
                    return None
                out.extend((v, True) for v in lv)
            for val in amap.get(name, ()):
                if val is None:
                    return None
                alts = self._alts(val, 1)
                if len(alts) >= self._ALT_CAP:
                    return None
                out.extend(self._alt_str(alt) for alt in alts)
            return out
        if p.kind in ('cmdsub', 'backtick'):
            alts = self._echo_alts(p.text or '', 0)
            if not alts or len(alts) >= self._ALT_CAP:
                return None
            return [self._alt_str(a) for a in alts]
        return None

    @staticmethod
    def _alt_str(alt):
        s = ''
        for x in alt:
            if x is None:
                return (s, False)
            s += x
        return (s, True)

    def _glob_rel(self, v):
        """The strings an unquoted glob expands to as the shell gives them (the pattern itself
        too); None under an unknown cwd."""
        if os.path.isabs(v):
            return sorted(glob.glob(v))[:self._FIELD_CAP] + [v]
        if self.cwd_unknown:
            return None
        out = [v]
        for base in sorted(self.cwds):
            b = base.rstrip('/') + '/'
            out.extend(m[len(b):] for m in sorted(glob.glob(b + v))[:self._FIELD_CAP])
        return out

    def _loop_values(self) -> dict:
        """loop variable -> the fields its list gives (False when one cannot be read)."""
        memo = getattr(self, '_loopval_memo', None)
        if memo is not None:
            return memo
        out = {}
        self._loopval_memo = out
        for var, items, _body in self.loops:
            if out.get(var) is False:
                continue
            got = out.setdefault(var, [])
            for w in items:
                arr = self._array_ref(w)
                for item in (self.arrays[arr] if arr is not None else [w]):
                    fields = self._word_fields(item)
                    if fields is None:
                        out[var] = False
                        break
                    got.extend(fields)
                if out[var] is False:
                    break
        return out

    def _word_fields(self, word):
        """The fields a loop-list word expands to (word splitting, globs); None when unread."""
        vals = self._values(word)
        if vals:
            out = []
            for v, g in vals:
                if g:
                    got = self._glob_rel(v)
                    if got is None:
                        return None
                    out.extend(got)
                else:
                    out.append(v)
            return out
        alts = self._alts(word)
        out = []
        split = any(p.quote == _sp.BARE and p.kind != 'lit' for p in word.parts)
        for alt in alts:
            s, complete = self._alt_str(alt)
            if not complete:
                return None
            for f in (s.split() if split else [s]):
                if split and any(c in f for c in '*?['):
                    got = self._glob_rel(f)
                    if got is None:
                        return None
                    out.extend(got)
                else:
                    out.append(f)
            if len(out) > self._FIELD_CAP:
                return None
        return out

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
            if v in _sp.AWK_PROGFILE_OPTS + _sp.AWK_LIB_OPTS or \
                    v.startswith('--file=') or v.startswith('--load='):
                return False
            if v in _sp.AWK_DATA_OPTS:
                k += 2
                continue
            if v in _sp.AWK_SOURCE_OPTS:
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
            if word is not None:
                self.computed_targets.append(word)
                if self._built(word):
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
        if self._shell_noexec(vals, self._last_quoted_param(site.cmd, args), args,
                              self._lead_checker(site.cmd, res, args)):
            return  # read, never run (bash -n with no later +n)
        k = 0
        has_c = has_s = False
        while k < len(args):
            v = vals[k]
            if v is None:
                self.unsure = True
                self.computed_targets.append(args[k])
                if self._built(args[k]):
                    self.computed_run = True  # a script operand built at run time
                return
            if v in _sp.OPTION_ENDS:
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
        if v in _STDIN_FILES or (v and v.startswith(locations.FD_DIR)):
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
                self.computed_targets.append(args[k])
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
            self._cwd_changed()
            return
        if self.cdpath and not os.path.isabs(target) and not target.startswith(('./', '../')) \
                and target not in ('.', '..'):
            self.cwd_unknown = True
            self._cwd_changed()
            return
        if os.path.isabs(target):
            self.cwds.add(os.path.normpath(target))
        else:
            self.cwds |= {os.path.normpath(os.path.join(c, target)) for c in list(self.cwds)}
        self._cwd_changed()

    def _cwd_changed(self):
        """A `cd` widened the cwds: what was read against the old ones is read again (an rg
        config named by a relative RIPGREP_CONFIG_PATH, the reader proofs that used it)."""
        self._rgconf_memo = None
        self.inert_memo = {}

    def _sub(self, text, cwds=None):
        """Read ``text`` as a command of its own (a command string an unknown runner may run)."""
        if self.depth >= 3:
            if _mentions(text):
                self.unsure = True
            return
        try:
            sub = _Scan(text, self.cwd, self.depth + 1, cwds or self.cwds, self.cdpath,
                        self._rg_config_progs() if (self.rgconf or self.rgprogs) else None)
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
        while i < len(vals) and vals[i] in _sp.FIND_SYMLINK_OPTS:
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
                while k < len(vals) and vals[k] not in _sp.FIND_EXEC_ENDS:
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
            if head in _PLAIN_READERS and head != 'find' and not (
                    head == 'rg' and (self.rgconf or self.rgprogs) and '--no-config' not in argv):
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
            if head is None:
                self.computed_targets.append(res.head)
            if self._built(res.head):
                self.computed_run = True
            return
        name = os.path.basename(head)
        args = list(res.args)
        if name in _sp.CD_TARGET_BUILTINS:
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
            ops = [w for w in args if not (w.value() or '-').startswith(_sp.OPTION_SIGNS)]
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
            self._git_grep_pager(args, vals)
        if name in ('make', 'gmake', 'bmake'):
            self._make(site, args, vals)
        if name == 'rg':
            self._rg(args)
        if name == 'sed':
            self._sed(site, args)
        if name == 'less' and self.lessopen:
            self._less(args)
        if name in _NO_EXEC:
            return
        if name == 'parallel' and ':::' in vals:
            cut = vals.index(':::')
            if all(v is not None and (v.startswith('-') or v.isdigit()) for v in vals[:cut]):
                # no command before `:::`: parallel runs each input as a command
                for v in vals[cut + 1:]:
                    if v is None:
                        self.unsure = True
                    elif v not in _sp.PARALLEL_SEPARATORS:
                        self._sub(v)
            vals = [v for v in vals if v not in _sp.PARALLEL_SEPARATORS]
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
        if sub == 'config' and not (any(r in _GIT_CONFIG_READS for r in rest) or rest[:1] and rest[0] in
                                    _GIT_CONFIG_READ_SUBS):
            self.git_config_written = True  # it may set the pager git grep -O opens
            if any(_mentions(r) for r in rest):
                self.persist = True
        if sub in _GIT_SHELL_PAYLOAD_SUBS:
            if any(_mentions(r) for r in rest):
                self.unsure = True

    # -- runs built at run time, rg --pre, sed e, LESSOPEN, loops -----------------

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
        if name in _XARGS_SAFE:
            return True
        if _PYTHON_RE.match(name):
            vals = [w.value() for w in res.args]
            return len(vals) >= 2 and vals[0] == '-m' and vals[1] in _PY_READER_MODULES
        return False

    def _lessopen_scan(self, site):
        cmd = site.cmd
        res = self.res[id(site)]
        for a in tuple(cmd.assignments) + tuple(res.assignments):
            if a.name in _LESS_HOOK_VARS:
                self.lessopen = True
        for w in cmd.words:
            t = w.value()
            t = w.text if t is None else t
            if re.match(r'''^["']?(?:%s)\+?=''' % '|'.join(_LESS_HOOK_VARS), t or ''):
                self.lessopen = True
        # RIPGREP_CONFIG_PATH the command sets (prefix, env, export/declare/typeset/readonly)
        for a in tuple(cmd.assignments) + tuple(res.assignments):
            if a.name == 'RIPGREP_CONFIG_PATH':
                self.rgconf.append(a.value)
            self._pager_assign(a)
        if res.name in _sp.DECLARATION_BUILTINS:
            for w in res.args:
                if _sp._ASSIGN_PARTS_RE.match(w.raw.text or ''):
                    a = _sp.Assignment(w)
                    if a.name == 'RIPGREP_CONFIG_PATH':
                        self.rgconf.append(a.value)
                    self._pager_assign(a)
                    continue
                t = w.value()
                if t is None and 'RIPGREP_CONFIG_PATH' in (w.text or ''):
                    self.rgconf.append(None)
                elif t and t.startswith('RIPGREP_CONFIG_PATH='):
                    self.rgconf.append(t.split('=', 1)[1])

    def _pager_assign(self, a):
        """GIT_PAGER / PAGER set by the command (the pager `git grep -O` opens)."""
        if a.name.startswith('GIT_CONFIG'):
            self.git_config_written = True
        if a.name in ('GIT_PAGER', 'PAGER'):
            v = a.static_value()
            prev = self.pager_env.get(a.name)
            self.pager_env[a.name] = v if v is not None and prev in (None, v) else _COMPUTED

    def _array_scan(self, site, script):
        """`a=(LIST)` (also after declare/local/typeset/readonly): the array is read like a
        loop list, its uses anywhere in the command like a loop body's."""
        cmd = site.cmd
        res = self.res[id(site)]
        assigns = list(cmd.assignments) + list(res.assignments)
        if res.name in _sp.DECLARATION_BUILTINS:
            assigns.extend(_sp.Assignment(w) for w in res.args
                           if _sp._ASSIGN_PARTS_RE.match(w.raw.text or ''))
        for a in assigns:
            if a.array is None or not re.match(r'^[A-Za-z_]\w*$', a.name or ''):
                continue
            try:
                parsed = _sp.parse('_ ' + (a.array.text or ''))
                first = next(iter(_sp.walk(parsed))).cmd
                items = list(first.words[1:])
            except Exception:
                items = []
                self.unsure = True
                self.computed_run = True
            known = self.arrays.setdefault(a.name, [])
            if not known:
                self.loops.append((a.name, known, [script]))
            known.extend(items)

    def _array_ref(self, word):
        """The array name when the word is only a use of a known array (`"${a[@]}"`)."""
        try:
            parts = [p for p in word.parts if not (p.kind == 'lit' and p.text == '')]
        except Exception:
            return None
        if len(parts) == 1 and parts[0].kind == 'param':
            m = re.match(r'^\{?([A-Za-z_]\w*)\[[@*]\]\}?$', parts[0].text or '')
            if m and m.group(1) in self.arrays:
                return m.group(1)
        return None

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
                takes = name in _sp.RG_VALUE_LONG
                vw = None if eq else (args[k + 1] if takes and k + 1 < len(args) else None)
                if name in _sp.RG_PROGRAM_OPTS:
                    progs.append(vw if not eq else val)
                if name in _sp.GREP_PATTERN_LONG:
                    given = True
                k += 1 if (eq or not takes) else 2
                continue
            if v.startswith('-') and len(v) > 1:
                for j, ch in enumerate(v[1:], 1):
                    if ch in _sp.RG_VALUE_SHORT:
                        if ch in 'ef':
                            given = True
                        k += 1 if v[j + 1:] else 2
                        break
                else:
                    k += 1
                continue
            positional.append(args[k])
            k += 1
        if '--no-config' not in vals:
            progs.extend(self._rg_config_progs())
        if not progs:
            return
        for p in progs:
            if p is _RG_CONF_UNKNOWN:
                self.computed_run = True  # checked below against the searched paths
                continue
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
        ops = [w for w in args if not (w.value() or 'x').startswith(_sp.OPTION_SIGNS)]
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
        expanded = []
        for w in items:
            arr = self._array_ref(w)
            expanded.extend(self.arrays[arr] if arr is not None else [w])
        for w in expanded:
            vals = self._values(w)
            if not vals:
                self.unsure = True
                self.computed_run = True
                continue
            for v, g in vals:
                for f in self._existing(v, g) or []:
                    if os.path.isfile(f) and self._wrapper_file(f) is not None:
                        self.match = self.match or 'stop'

    def _names_harness(self, word) -> bool:
        """A run target with a computed part whose literal part names the harness home's
        hooks/ or scripts/ directory (`~/.claude/hooks/$n.sh`, `$(echo ~)/.claude/hooks/x`)
        or a wrapper basename: it may be the wrapper, and it cannot be read."""
        try:
            parts = list(word.parts)
        except Exception:
            return False
        if _mentions(''.join(p.text or '' for p in parts if p.kind in ('lit', 'glob', 'brace'))):
            return True
        dirs = _harness_dirs()
        # the literal prefix, up to the first part that is computed
        prefix = ''
        for k, p in enumerate(parts):
            if p.kind == 'lit':
                t = p.text or ''
                if k == 0 and p.quote == _sp.BARE and t[:1] == '~' and (len(t) == 1 or t[1] == '/'):
                    t = self.home + t[1:]
                prefix += t
            elif p.kind == 'param' and p.text in _HOME_PARAMS and self.home:
                prefix += self.home
            else:
                break
        if prefix and '/' in prefix:
            d = prefix.rstrip('/') if prefix.endswith('/') else os.path.dirname(prefix)
            for base in ([''] if os.path.isabs(d) else sorted(self.cwds)):
                cand = os.path.join(base, d) if base else d
                for q in (os.path.normpath(cand), os.path.realpath(cand)):
                    if any(q == h or q.startswith(h + os.sep) for h in dirs):
                        return True
        # a literal run after a computed part that spells the directory's last two names
        tails = {'/'.join(h.split(os.sep)[-2:]) for h in dirs if h.count(os.sep) >= 2}
        run = ''
        runs = []
        for p in parts:
            if p.kind in ('lit', 'glob', 'brace'):
                run += p.text or ''
            else:
                runs.append(run)
                run = ''
        runs.append(run)
        for r in runs[1:]:
            r = os.path.normpath('/' + r)
            for t in tails:
                i = r.find('/' + t)
                if i >= 0 and r[i + 1 + len(t):i + 2 + len(t)] in ('', '/'):
                    return True
        return False

    # -- computed run targets read with the command's own assignments ---------------
    _ALT_CAP = 64

    def _assign_map(self) -> dict:
        """name -> [value Word or None] of the plain assignments anywhere in the command
        (`n=stop`, `export p=...`); None for an append or an assignment it cannot read."""
        memo = getattr(self, '_assign_memo', None)
        if memo is not None:
            return memo
        out = {}
        for site in self.sites:
            cmd, res = site.cmd, self.res[id(site)]
            assigns = list(cmd.assignments) + list(res.assignments)
            if res.name in _sp.DECLARATION_BUILTINS:
                assigns.extend(_sp.Assignment(w) for w in res.args
                               if _sp._ASSIGN_PARTS_RE.match(w.raw.text or ''))
            for a in assigns:
                if not a.name or a.index is not None or a.array is not None:
                    continue
                out.setdefault(a.name, []).append(None if a.append else a.value)
        self._assign_memo = out
        return out

    def _alts(self, word, depth=0) -> list:
        """The values a word may take, as lists of segments (str, or None for a part the
        guard cannot read): the command's own literal assignments are substituted for its
        variables, and `$(echo ARGS)` / backticks with readable ARGS are evaluated."""
        if word is None or depth > 3:
            return [[None]]
        try:
            parts = list(word.parts)
        except Exception:
            return [[None]]
        acc = [[]]
        amap = self._assign_map()
        for k, p in enumerate(parts):
            if p.kind == 'lit':
                t = p.text or ''
                if k == 0 and p.quote == _sp.BARE and t[:1] == '~' and (len(t) == 1 or t[1] == '/'):
                    t = self.home + t[1:]
                choices = [[t]]
            elif p.kind == 'brace':
                choices = [[v] for v in _brace_variants(p.text)]
            elif p.kind == 'param':
                m = re.match(r'^\{?([A-Za-z_]\w*)\}?$', p.text or '')
                name = m.group(1) if m else None
                choices = [[None]]
                if name == 'HOME' and self.home:
                    choices = [[self.home]]
                elif name in amap:
                    for val in amap[name]:
                        choices.extend(self._alts(val, depth + 1) if val is not None else [[None]])
                elif name is None:
                    choices = self._pe_alts(p.text or '', depth)
            elif p.kind in ('cmdsub', 'backtick'):
                choices = self._echo_alts(p.text or '', depth) or [[None]]
            else:
                choices = [[None]]
            acc = [a + c for a in acc for c in choices][:self._ALT_CAP]
        return acc

    # `${x OP ...}`: the operators read on the command's own literal assignments
    _PE_RE = re.compile(r'^([A-Za-z_]\w*)(##?|%%?|//?|\^\^?|,,?|:[-=+]|[-=+]|:)(.*)$', re.S)

    def _pe_alts(self, text, depth) -> list:
        """The values of a parameter expansion with an operator on a variable the command
        assigns literally; a variable whose value cannot be evaluated through the operator
        and is in or names the harness hooks/ or scripts/ dir sets _pe_fail."""
        inner = text[1:-1] if text.startswith('{') and text.endswith('}') else text
        m = self._PE_RE.match(inner)
        name = m.group(1) if m else (re.match(r'^[!#]?([A-Za-z_]\w*)', inner) or [None, None])[1]
        amap = self._assign_map()
        if name == 'HOME' and self.home:
            vals = [[self.home]]
        elif name in amap:
            vals = []
            for val in amap[name]:
                vals.extend(self._alts(val, depth + 1) if val is not None else [[None]])
        else:
            vals = None  # not set by the command: its value comes from the environment
        if m is None or inner[:1] in '!#':
            if vals and any(self._alt_names_harness(a) for a in vals):
                self._pe_fail = True
            return [[None]]
        op, arg = m.group(2), m.group(3)
        if op in (':-', '-', ':=', '=', ':+', '+'):
            arg_alts = self._pe_arg_alts(arg, depth)
            if op in (':+', '+'):
                return (arg_alts if vals else []) + [['']]
            return (vals or []) + ([[None]] if vals is None else []) + arg_alts
        if vals is None:
            return [[None]]
        out = []
        for alt in vals:
            s, complete = self._alt_str(alt)
            r = self._pe_eval(s, op, arg) if complete else None
            if r is None:
                if self._alt_names_harness(alt):
                    self._pe_fail = True
                out.append([None])
            else:
                out.append([r])
        return out

    def _pe_arg_alts(self, arg, depth) -> list:
        try:
            sites = list(_sp.walk(_sp.parse(': ' + arg)))
            words = list(sites[0].cmd.words)[1:] if len(sites) == 1 else None
        except Exception:
            words = None
        if words is None or len(words) > 1:
            return [[None]]
        return self._alts(words[0], depth + 1) if words else [['']]

    @staticmethod
    def _pe_pattern(pat):
        """A regex for a literal shell pattern (`*`, `?`, `[...]`); None when it is computed."""
        if pat is None or re.search(r'[$`"\'\\]', pat):
            return None
        out, i = '', 0
        while i < len(pat):
            c = pat[i]
            if c == '*':
                out += '.*'
            elif c == '?':
                out += '.'
            elif c == '[':
                j = pat.find(']', i + 2)
                if j < 0:
                    out += re.escape(c)
                else:
                    body = pat[i + 1:j]
                    out += '[' + ('^' + re.escape(body[1:]) if body[:1] in '!^' else re.escape(body)) + ']'
                    i = j
            else:
                out += re.escape(c)
            i += 1
        return out

    def _pe_eval(self, s, op, arg):
        """`${x OP arg}` on the literal value s; None when the guard cannot evaluate it."""
        try:
            if op in ('#', '##', '%', '%%'):
                rx = self._pe_pattern(arg)
                if rx is None:
                    return None
                cands = range(len(s) + 1)
                if op in ('#', '##'):
                    order = cands if op == '#' else reversed(cands)
                    for i in order:
                        if re.fullmatch(rx, s[:i], re.S):
                            return s[i:]
                    return s
                order = reversed(cands) if op == '%' else cands
                for i in order:
                    if re.fullmatch(rx, s[i:], re.S):
                        return s[:i]
                return s
            if op in ('/', '//'):
                pat, _sl, rep = arg.partition('/')
                anchor = ''
                if op == '/' and pat[:1] in ('#', '%'):
                    anchor, pat = pat[0], pat[1:]
                rx = self._pe_pattern(pat)
                if rx is None or re.search(r'[$`"\'\\&]', rep) or not pat:
                    return None
                if anchor == '#':
                    mm = re.match('(?:' + rx + ')', s, re.S)
                    if mm is None:
                        return s
                    # longest match at the start
                    for i in range(len(s), -1, -1):
                        if re.fullmatch(rx, s[:i], re.S):
                            return rep + s[i:]
                    return s
                if anchor == '%':
                    for i in range(len(s) + 1):
                        if re.fullmatch(rx, s[i:], re.S):
                            return s[:i] + rep
                    return s
                out, i, done = '', 0, False
                while i <= len(s):
                    hit = None
                    if not done:
                        for j in range(len(s), i, -1):
                            if re.fullmatch(rx, s[i:j], re.S):
                                hit = j
                                break
                    if hit is not None:
                        out += rep
                        i = hit
                        done = op == '/'
                        continue
                    if i < len(s):
                        out += s[i]
                    i += 1
                return out
            if op in ('^', '^^', ',', ',,'):
                if arg:
                    return None
                f = str.upper if op[0] == '^' else str.lower
                return f(s) if len(op) == 2 else (f(s[:1]) + s[1:])
            if op == ':':
                mm = re.fullmatch(r'\s*(-?\d+)\s*(?::\s*(-?\d+)\s*)?', arg)
                if mm is None:
                    return None
                off = int(mm.group(1))
                if off < 0:
                    off = max(len(s) + off, 0)
                if mm.group(2) is None:
                    return s[off:]
                ln = int(mm.group(2))
                return s[off:off + ln] if ln >= 0 else s[off:len(s) + ln]
        except re.error:
            return None
        return None

    def _alt_names_harness(self, alt) -> bool:
        """A value (segments, None for a computed part) that names a wrapper or is in or
        names the harness hooks/ or scripts/ directory."""
        s = ''.join(x for x in alt if isinstance(x, str))
        if _mentions(s) or self._text_names_harness(s):
            return True
        prefix, _c = self._alt_str(alt)
        if '/' not in prefix:
            return False
        dirs = _harness_dirs()
        bases = [''] if os.path.isabs(prefix) else sorted(self.cwds)
        for base in bases:
            q = os.path.normpath(os.path.join(base, prefix) if base else prefix)
            for d in (q, os.path.dirname(q)):
                if any(d == h or d.startswith(h + os.sep) for h in dirs):
                    return True
        return False

    def _echo_alts(self, text, depth):
        """The output of `echo ARGS` with readable ARGS (no option), of `ls` with no option
        over readable names, and of `readlink -f` / `realpath` of one readable name; None
        otherwise."""
        try:
            sites = list(_sp.walk(_sp.parse(text)))
        except Exception:
            return None
        if len(sites) != 1 or sites[0].cmd.redirects or sites[0].cmd.assignments:
            return None
        words = list(sites[0].cmd.words)
        if words and words[0].value() in ('ls', 'readlink', 'realpath'):
            return self._path_cmd_alts(words)
        if not words or words[0].value() != 'echo':
            return None
        out = [[]]
        for i, w in enumerate(words[1:]):
            alts = self._alts(w, depth + 1)
            if i == 0 and any(a and isinstance(a[0], str) and a[0][:1] == '-' for a in alts):
                return None
            sep = [' '] if i else []
            out = [o + sep + a for o in out for a in alts][:self._ALT_CAP]
        return out

    def _path_cmd_alts(self, words):
        """`ls NAMES` (files print as given, one directory lists its entries) and
        `readlink -f|-e|-m NAME` / `realpath [-e|-m] NAME`, read on disk now."""
        name = words[0].value()
        ops, opts = [], []
        for w in words[1:]:
            v = w.value()
            if v is not None and v.startswith('-') and v != '-':
                opts.append(v)
            else:
                ops.append(w)
        if name == 'ls':
            if opts:
                return None
            if not ops:
                if self.cwd_unknown:
                    return None
                outs = []
                for base in sorted(self.cwds):
                    try:
                        outs.append([n for n in sorted(os.listdir(base)) if not n.startswith('.')])
                    except OSError:
                        outs.append([])
                return [['\n'.join(o)] for o in outs]
            fields = []
            for w in ops:
                got = self._word_fields(w)
                if got is None:
                    return None
                fields.extend(got)
            outs = []
            for base in ([''] if all(os.path.isabs(f) for f in fields) else sorted(self.cwds)):
                lines = []
                for f in fields:
                    full = os.path.join(base, f) if base else f
                    if os.path.isdir(full):
                        if len(fields) > 1:
                            return None
                        try:
                            lines.extend(n for n in sorted(os.listdir(full)) if not n.startswith('.'))
                        except OSError:
                            return None
                    elif os.path.lexists(full):
                        lines.append(f)
                outs.append(['\n'.join(sorted(lines))])
            if self.cwd_unknown and not all(os.path.isabs(f) for f in fields):
                return None
            return outs
        if name == 'readlink' and not (opts and all(re.fullmatch(r'-[fem]+n?|-n[fem]+', o) for o in opts)):
            return None
        if name == 'realpath' and any(o not in ('-e', '-m', '-q') for o in opts):
            return None
        if len(ops) != 1:
            return None
        outs = []
        for alt in self._alts(ops[0], 1):
            v, complete = self._alt_str(alt)
            if not complete:
                return None
            if os.path.isabs(v):
                outs.append([os.path.realpath(v)])
            elif self.cwd_unknown:
                return None
            else:
                outs.extend([os.path.realpath(os.path.join(b, v))] for b in sorted(self.cwds))
        return outs

    def _wrapper_paths(self) -> set:
        """The paths the harness home's wrappers have (as given and by realpath)."""
        out = set(self.by_path)
        for h in _harness_homes():
            for pairs in _GUARDED_WRAPPERS.values():
                for sub, base in pairs:
                    out.add(os.path.normpath(os.path.join(h, sub, base)))
        return out

    def _resolves_harness(self, word) -> bool:
        """A run target the command's own assignments and echo substitutions spell: it is
        the wrapper, or it still has a computed part and what can be read of it is
        consistent with a path to a wrapper in the harness hooks/ or scripts/ dir (its
        literal start holds a `/`)."""
        dirs = _harness_dirs()
        wpaths = self._wrapper_paths()
        self._pe_fail = False
        alts = self._alts(word)
        if self._pe_fail:
            return True  # an operator the guard cannot evaluate on a harness-path value
        for alt in alts:
            if all(isinstance(x, str) for x in alt):
                v = ''.join(alt)
                if '/' not in v:
                    continue
                for f in self._existing(v, False) or []:
                    if os.path.isfile(f) and self._wrapper_file(f) is not None:
                        return True
                bases = [''] if os.path.isabs(v) else sorted(self.cwds)
                for base in bases:
                    q = os.path.normpath(os.path.join(base, v) if base else v)
                    if os.path.dirname(q) in dirs and os.path.basename(q) in self.by_name:
                        return True  # the wrapper's own name in its directory
                continue
            prefix = ''
            for x in alt:
                if x is None:
                    break
                prefix += x
            if '/' not in prefix:
                continue
            bases = [''] if os.path.isabs(prefix) else [c.rstrip('/') + '/' for c in sorted(self.cwds)]
            for base in bases:
                pat = re.escape(base) + ''.join('.*' if x is None else re.escape(x) for x in alt)
                try:
                    rx = re.compile(pat, re.S)
                except re.error:
                    return True
                if any(rx.fullmatch(c) for c in wpaths):
                    return True
                head = os.path.normpath(base + prefix)
                d = head if prefix.endswith('/') else os.path.dirname(head)
                if any(d == h or d.startswith(h + os.sep) for h in dirs):
                    return True
        return False

    def _rg_config_progs(self) -> list:
        """Programs (`--pre`, `--hostname-bin`) of the rg configs the command sets (or the
        outer command set, for an rg it runs through find -exec); _RG_CONF_UNKNOWN for a
        config the guard cannot read (computed, or written by the same command). A config
        file that does not exist runs no program (rg ignores it)."""
        memo = getattr(self, '_rgconf_memo', None)
        if memo is not None:
            return memo
        out = list(self.rgprogs)
        for conf in self.rgconf:
            if conf is None:
                out.append(_RG_CONF_UNKNOWN)
                continue
            word = conf if not isinstance(conf, str) else None
            vals = self._values(conf) if word is not None else [(conf, False)]
            if not vals:
                out.append(_RG_CONF_UNKNOWN)
                continue
            for v, g in vals:
                if not v:
                    continue  # an empty path turns the config off
                if v[:1] == '~' and (len(v) == 1 or v[1] == '/'):
                    v = self.home + v[1:]
                if g or (word is not None and self._named_elsewhere(word, v)) or \
                        (word is None and any(os.path.normpath(o) == os.path.normpath(v)
                                              for _w, o in self.others)):
                    out.append(_RG_CONF_UNKNOWN)
                    continue
                found = self._existing(v, False)
                if found is None:
                    out.append(_RG_CONF_UNKNOWN)  # a relative name under an unknown cwd
                    continue
                for f in found:
                    try:
                        with open(f, errors='replace') as fh:
                            lines = [ln.strip() for ln in fh.read(1 << 20).splitlines()]
                    except OSError:
                        out.append(_RG_CONF_UNKNOWN)
                        continue
                    lines = [ln for ln in lines if ln and not ln.startswith('#')]
                    for i, ln in enumerate(lines):
                        if ln in _sp.RG_PROGRAM_OPTS:
                            out.append(lines[i + 1] if i + 1 < len(lines) else None)
                        elif ln.startswith(tuple(o + '=' for o in _sp.RG_PROGRAM_OPTS)):
                            out.append(ln.split('=', 1)[1])
        self._rgconf_memo = out
        return out

    _GIT_GREP_VALUE_SHORT = 'efABCm'

    def _git_grep_pager(self, args, vals):
        """`git grep -O<prog>` / `--open-files-in-pager[=prog]` (any unique prefix) runs the
        program on every matching file: a run when git searches in the harness home, the
        searched paths hold the wrapper, or the program is the wrapper."""
        k, dirs, unknown = 0, set(self.cwds), self.cwd_unknown
        while k < len(vals):
            v = vals[k]
            if v is None:
                return
            if v == '-C' and k + 1 < len(vals):
                d = vals[k + 1]
                if d is None:
                    unknown = True
                else:
                    d = self.home + d[1:] if d[:1] == '~' and (len(d) == 1 or d[1] == '/') else d
                    dirs = {os.path.normpath(os.path.join(c, d)) for c in dirs}
                k += 2
                continue
            if v in ('--git-dir', '--work-tree') and k + 1 < len(vals):
                d = vals[k + 1]
                if d is None:
                    unknown = True
                else:
                    d = self.home + d[1:] if d[:1] == '~' and (len(d) == 1 or d[1] == '/') else d
                    dirs |= {os.path.normpath(os.path.join(c, d)) for c in dirs}
                k += 2
                continue
            if v.startswith(('--git-dir=', '--work-tree=')):
                d = v.split('=', 1)[1]
                d = self.home + d[1:] if d[:1] == '~' and (len(d) == 1 or d[1] == '/') else d
                dirs |= {os.path.normpath(os.path.join(c, d)) for c in dirs}
                k += 1
                continue
            if v in _GIT_GLOBAL_VALUE:
                k += 2
                continue
            if v.startswith('-'):
                k += 1
                continue
            break
        if k >= len(vals) or vals[k] != 'grep':
            return
        pager, prog, operands, j = False, None, [], k + 1
        while j < len(vals):
            v = vals[j]
            if v is None:
                lead = self._lead_literal(args[j])
                if lead.startswith('--'):
                    name = lead[2:].partition('=')[0]
                    if '=' in lead and len(name) >= 2 and 'open-files-in-pager'.startswith(name):
                        pager, prog = True, _COMPUTED  # --open-files-in-pager=$p
                elif lead.startswith('-') and len(lead) > 1:
                    for ch in lead[1:]:
                        if ch == 'O':
                            pager, prog = True, _COMPUTED  # -O$p, -O"$(...)", -O`...`
                            break
                        if ch in self._GIT_GREP_VALUE_SHORT:
                            break
                else:
                    operands.append(args[j])
                j += 1
                continue
            if v == '--':
                operands.extend(args[j + 1:])
                break
            if v.startswith('--'):
                name, eq, val = v[2:].partition('=')
                if len(name) >= 2 and 'open-files-in-pager'.startswith(name):
                    pager, prog = True, (val if eq else prog)
                elif name in ('regexp', 'file', 'max-count', 'after-context', 'before-context',
                              'context', 'max-depth', 'threads') and not eq:
                    j += 1
                j += 1
                continue
            if v.startswith('-') and len(v) > 1:
                letters = v[1:]
                for i, ch in enumerate(letters):
                    if ch == 'O':
                        pager, prog = True, (letters[i + 1:] or prog)
                        break
                    if ch in self._GIT_GREP_VALUE_SHORT:
                        if not letters[i + 1:]:
                            j += 1
                        break
                j += 1
                continue
            operands.append(args[j])
            j += 1
        if not pager:
            return
        if prog is None:
            # no program: git opens the files in its pager, which the command may set
            prog = self._git_pager_setting(vals[:k], dirs)
        if prog is _GIT_LESS:
            # git's own less, run from PATH: never a file of the directory the command names
            if self._plain_pager('less'):
                return
        elif prog is not None and prog is not _COMPUTED and self._plain_pager(prog):
            return  # less / more / cat only read the files
        if prog is not None and prog is not _COMPUTED and prog is not _GIT_LESS:
            pv = self.home + prog[1:] if prog[:1] == '~' and (len(prog) == 1 or prog[1] == '/') else prog
            if _dequoted_mentions(prog) or any(self._wrapper_file(f) is not None
                                               for f in (self._existing(pv, False) or [])):
                self.match = self.match or 'stop'
                return
        if prog is _COMPUTED:
            self.computed_run = True  # a program built at run time: it may be anything
        homes = set()
        for h in _harness_homes():
            homes.add(os.path.normpath(h))
            homes.add(os.path.realpath(h))
        for d in dirs:
            for q in (os.path.normpath(d), os.path.realpath(d)):
                if any(q == h or q.startswith(h + os.sep) for h in homes):
                    self.match = self.match or 'stop'
                    return
        if unknown:
            self.unsure = True
            self.computed_run = True
        saved = self.cwds
        self.cwds = dirs
        try:
            self._words_hold_wrapper(operands, trees=True)
        finally:
            self.cwds = saved

    @staticmethod
    def _lead_literal(word) -> str:
        """The literal text a word starts with, up to its first computed part."""
        out = ''
        try:
            for p in word.parts:
                if p.kind != 'lit':
                    break
                out += p.text or ''
        except Exception:
            return ''
        return out

    _PLAIN_PAGERS = frozenset(('less', 'more', 'cat'))

    def _plain_pager(self, prog) -> bool:
        """A pager that only reads the files git hands it: less, more or cat (with options),
        unless the command sets LESSOPEN / LESSCLOSE for less."""
        words = prog.split()
        if not words or re.search(r'[;&|`$()<>\\\'"\n*?{}\[\]]', prog):
            return False
        head = words[0]
        if '/' in head and os.path.dirname(head) not in locations.SYSTEM_BIN_DIRS:
            return False
        name = os.path.basename(head)
        if name not in self._PLAIN_PAGERS or (name in ('less', 'more') and (
                self.lessopen or re.search(r'\b(?:LESS|MORE)\w*\+?=', self.command))):
            return False  # LESS / LESSKEY* / MORE set by the command may hold commands
        return all(w.startswith('-') and 'k' not in w.lstrip('-')[:1] and 'lesskey' not in w
                   for w in words[1:])

    _GIT_BOOL = frozenset(('true', 'false', 'yes', 'no', 'on', 'off', '1', '0', ''))

    def _git_pager_setting(self, gvals, dirs):
        """The pager `git grep -O` with no program opens. git takes GIT_PAGER, then
        pager.grep / core.pager (from `-c` or the git config on disk), then PAGER, then
        less; every one of them is read, and the first that is not a plain pager (or is
        computed) is returned, else _GIT_LESS (git's own less). A `git config` write, a
        GIT_CONFIG_* variable or a write to a git config file in the same command makes the
        pager computed."""
        cands = []
        k = 0
        while k < len(gvals):
            if gvals[k] == '-c' and k + 1 < len(gvals):
                kv = gvals[k + 1]
                if kv is None:
                    return _COMPUTED
                key, _eq, val = kv.partition('=')
                key = key.lower()
                if key == 'core.pager' or (key.startswith('pager.') and
                                           val.lower() not in self._GIT_BOOL):
                    cands.append(val)
                k += 2
                continue
            if gvals[k] in ('--config-env',) or (gvals[k] or '').startswith('--config-env='):
                return _COMPUTED
            k += 1
        if self.git_config_written or any(
                ov and (os.path.basename(ov) in ('.gitconfig', 'gitconfig') or
                        re.search(r'(?:^|/)(?:\.git|git)/config$', ov))
                for _w, ov in self.others):
            return _COMPUTED
        for name in ('GIT_PAGER', 'PAGER'):
            seen = self.pager_env.get(name)
            if seen is not None:
                cands.append(seen)
            elif os.environ.get(name):
                cands.append(os.environ[name])
        cands.extend(self._git_disk_pagers(dirs))
        for c in cands:
            if c is _COMPUTED or not self._plain_pager(c):
                return c
        return _GIT_LESS

    @staticmethod
    def _git_disk_pagers(dirs) -> list:
        """core.pager and a non-boolean pager.grep from the git config on disk (repository,
        global, system) for each directory git grep searches in."""
        import subprocess
        out = []
        for d in sorted(dirs)[:4]:
            if not os.path.isdir(d):
                continue
            for key in ('core.pager', 'pager.grep'):
                try:
                    p = subprocess.run(['git', '-C', d, 'config', '--get', key],
                                       capture_output=True, text=True, timeout=5)
                except Exception:
                    out.append(_COMPUTED)
                    continue
                v = p.stdout.strip()
                if p.returncode == 0 and v and not (key == 'pager.grep' and
                                                    v.lower() in _Scan._GIT_BOOL):
                    out.append(v)
        return out

    _MAKE_DRY = ('--just-print', '--dry-run', '--recon')
    _MAKE_ASSIGN = re.compile(r'^([A-Za-z_.][\w.-]*)\s*(?:::=|:::=|:=|\?=|\+=|!=|=)')
    _MAKE_SHELLS = frozenset(('SHELL', 'MAKESHELL', '.SHELLFLAGS'))
    # what make still runs under -n: `+` recipe lines, $(MAKE) lines, $(shell ...), `!=`
    _MAKE_DRY_RUNS = re.compile(r'(?m)(?:^\t|;)[ \t]*[@\-+ \t]*\+|\bMAKE\b|\bshell\b|!=')
    _COMPUTED_TEXT = re.compile(r'\$|`')
    _MAKE_INCLUDE = re.compile(r'(?m)^[ \t]*(?:-include|sinclude|include)(?:[ \t]|$)')

    def _make(self, site, args, vals):
        """make reads a makefile from stdin (`-f -`, `-f /dev/stdin`, a heredoc or here-string)
        or one the same command writes: a recipe naming the wrapper, or naming the harness
        hooks/ or scripts/ directory (in the harness home: any text) with a computed part, is
        a run (not under -n, unless a line runs anyway); a makefile, or a SHELL value, the
        guard cannot read is a run when the command names the wrapper or those directories,
        or runs in them or in the harness home. `SHELL=` naming the wrapper, as a make
        argument or in --eval, is a run."""
        cmd = site.cmd
        files, extra, dry, shell_unknown, k = [], [], False, False, 0
        while k < len(vals):
            v = vals[k]
            if v is None:
                lead = self._lead_literal(args[k])
                m = self._MAKE_ASSIGN.match(lead)
                if m and m.group(1) in self._MAKE_SHELLS:
                    shell_unknown = True  # SHELL=<computed>: read like an unreadable makefile
                if lead.startswith(('--eval', '-E')) or m:
                    extra.append(None)
                k += 1
                continue
            if v == '--':
                break
            if v.startswith('--'):
                name, eq, val = v.partition('=')
                if len(name) >= 5 and any(d.startswith(name) for d in self._MAKE_DRY):
                    dry = True
                    k += 1
                    continue
                if name in ('--file', '--makefile'):
                    files.append((val, None) if eq else (
                        (vals[k + 1], args[k + 1]) if k + 1 < len(vals) else ('', None)))
                    k += 1 if eq else 2
                    continue
                if name == '--eval':
                    extra.append(val if eq else (vals[k + 1] if k + 1 < len(vals) else ''))
                    k += 1 if eq else 2
                    continue
                if name in ('--directory', '--include-dir', '--old-file', '--assume-old',
                            '--what-if', '--new-file', '--assume-new') and not eq:
                    k += 2
                    continue
                k += 1
                continue
            if v.startswith('-') and len(v) > 1:
                letters = v[1:]
                for i, ch in enumerate(letters):
                    if ch == 'n':
                        dry = True
                        continue
                    if ch in 'fE':
                        rest = letters[i + 1:]
                        nxt = (vals[k + 1], args[k + 1]) if k + 1 < len(vals) else ('', None)
                        if ch == 'f':
                            files.append((rest, None) if rest else nxt)
                        else:
                            extra.append(rest if rest else nxt[0])
                        if not rest:
                            k += 1
                        break
                    if ch in 'CIoW':
                        if not letters[i + 1:]:
                            k += 1
                        break
                    if ch in 'jlO':
                        break  # an optional value attached (-j4, -l2, -Onone)
                k += 1
                continue
            m = self._MAKE_ASSIGN.match(v)
            if m:
                extra.append(v)  # a command-line variable: makefile text of its own
            k += 1
        # a -f operand that could not be read at all (computed)
        for idx, w in enumerate(args):
            if vals[idx] is None and idx > 0 and vals[idx - 1] in ('-f', '--file', '--makefile'):
                files.append((None, w))
        # SHELL / MAKESHELL / .SHELLFLAGS set to the wrapper runs it for every recipe line
        # and every $(shell ...), -n or not
        for t in extra:
            if t is None:
                continue
            for line in t.splitlines() or ['']:
                m = self._MAKE_ASSIGN.match(line.strip())
                if m and m.group(1) in self._MAKE_SHELLS:
                    val = line.split('=', 1)[1].strip()
                    if _dequoted_mentions(val) or self._make_value_harness(val):
                        self.match = self.match or 'stop'
                        return
        texts, unreadable, blind = [], shell_unknown, False
        if not files and any(os.path.basename(ov or '') in ('GNUmakefile', 'makefile', 'Makefile')
                             for _ow, ov in self.others):
            texts.append(self.command)  # the default makefile is written by this command
            for _ow, ov in self.others:
                if ov and os.path.basename(ov) not in ('GNUmakefile', 'makefile', 'Makefile'):
                    texts.extend(self._file_texts(ov))
        for v, w in files:
            if v is None:
                if 'pipe' in site.fed or any(r.fd == 0 for r in cmd.redirects):
                    blind = True  # a computed name beside a makefile on stdin
                else:
                    self.unsure = True
                    self.computed_run = True
                continue
            if v in ('-',) + _STDIN_FILES or v.startswith(locations.FD_DIR):
                got = False
                for red in cmd.redirects:
                    if red.fd != 0:
                        continue
                    got = True
                    if red.hd is not None:
                        texts.append(red.hd.body)
                    elif red.op == '<<<':
                        t = red.target.value() if red.target is not None else None
                        if t is None:
                            unreadable = True
                        else:
                            texts.append(t)
                    elif red.target is not None:
                        tv = self._expand(red.target)[0]
                        if tv is None or self._named_elsewhere(red.target, tv):
                            unreadable = True
                            if tv is not None:
                                texts.append(self.command)
                        else:
                            texts.extend(self._file_texts(tv))
                if not got and 'pipe' in site.fed:
                    fed = self._feeder_texts(self.feeders.get(id(cmd)))
                    if fed is None:
                        unreadable = True
                    else:
                        texts.extend(fed)
                continue
            if w is not None and self._named_elsewhere(w, v):
                texts.append(self.command)  # the makefile is written by this command
                for _ow, ov in self.others:
                    if ov and os.path.normpath(ov) != os.path.normpath(v):
                        texts.extend(self._file_texts(ov))
        if texts:
            texts.extend(t for t in extra if t is not None)
            if None in extra:
                unreadable = True  # a computed variable or --eval beside a makefile read here
        # GNU make remakes an `include`d makefile (include / -include / sinclude) and
        # re-executes even under -n, so its rule's recipe runs
        runs_dry = any(self._MAKE_DRY_RUNS.search(t) or self._MAKE_INCLUDE.search(t)
                       for t in texts)
        for t in texts:
            t = re.sub(r'\\\n\t?', '', t)
            hit = _dequoted_mentions(t) or _dequoted_mentions(self._sed_unescape(t))
            if not hit and self._COMPUTED_TEXT.search(t) and (
                    self._text_names_harness(t) or self._in_harness_home()):
                hit = True  # the harness hooks/ or scripts/ dir with a computed part
            if hit and (not dry or runs_dry):
                self.match = self.match or 'stop'
                return
        if blind or unreadable and (_dequoted_mentions(self.command) or
                           self._text_names_harness(self.command) or
                           self._in_harness_home() or self._harness_context()):
            self.match = self.match or 'stop'

    def _feeder_texts(self, st):
        """What a pipeline stage writes to the next one, when it is `cat FILE...` or
        `printf` / `echo` with readable arguments; None otherwise."""
        site = self.site_of.get(id(st)) if st is not None else None
        if site is None:
            return None
        stdin_file = None
        for red in site.cmd.redirects:
            if red.fd == 0 and red.op == '<' and red.hd is None and red.target is not None \
                    and stdin_file is None:
                stdin_file = red  # `cat < FILE`: read like `cat FILE`
                continue
            return None
        res = self.res.get(id(site))
        if res is None or res.head is None or res.unresolved:
            return None
        head = self._expand(res.head)[0]
        vals = [self._expand(w)[0] for w in res.args]
        if head is None or any(v is None for v in vals):
            return None
        name = os.path.basename(head)
        if name in _sp.PRINTERS:
            return ['\n'.join(vals)]
        if name != 'cat':
            return None
        ops = [(w, v) for w, v in zip(res.args, vals) if not v.startswith('-') or v == '-']
        if stdin_file is not None:
            if ops and any(v != '-' for _w, v in ops):
                return None  # cat reads its operands; stdin only at a `-`
            sv = self._expand(stdin_file.target)[0]
            if sv is None:
                return None
            ops = [(stdin_file.target, sv)]
        if not ops or any(v == '-' for _w, v in ops):
            return None
        out = []
        for w, v in ops:
            if self._named_elsewhere(w, v):
                return None
            got = self._file_texts(v)
            if not got:
                return None
            out.extend(got)
        return out

    def _make_value_harness(self, val) -> bool:
        """A make SHELL value that is the wrapper file, or names the harness hooks/ or
        scripts/ dir with a computed part."""
        v = val.strip().strip('\'"')
        for tok in v.split()[:1]:
            p = tok.replace('$(HOME)', self.home).replace('${HOME}', self.home).replace(
                '$HOME', self.home)
            p = self.home + p[1:] if p[:1] == '~' and (len(p) == 1 or p[1] == '/') else p
            for f in self._existing(p, False) or []:
                if os.path.isfile(f) and self._wrapper_file(f) is not None:
                    return True
        return bool(self._COMPUTED_TEXT.search(v) and self._text_names_harness(v))

    def _text_names_harness(self, text) -> bool:
        """The text spells the harness home's hooks/ or scripts/ directory: by its path, by
        `~/` or `$HOME/` + its path under $HOME, or by its last two names (`.claude/hooks`)."""
        forms = set()
        for d in _harness_dirs():
            forms.add(d)
            if d.count(os.sep) >= 2:
                forms.add('/'.join(d.split(os.sep)[-2:]))
            if self.home and d.startswith(self.home.rstrip('/') + '/'):
                rel = d[len(self.home.rstrip('/')) + 1:]
                forms.update(('~/' + rel, '$HOME/' + rel, '${HOME}/' + rel, '$(HOME)/' + rel))
        for f in forms:
            for m in re.finditer(re.escape(f), text):
                if text[m.end():m.end() + 1] in ('', '/', ' ', '\t', '\n', '"', "'", ';', ')'):
                    return True
        return False

    def _in_harness_home(self) -> bool:
        """The command runs in the harness home or below it."""
        homes = set()
        for h in _harness_homes():
            homes.add(os.path.normpath(h))
            homes.add(os.path.realpath(h))
        for c in self.cwds:
            for q in (os.path.normpath(c), os.path.realpath(c)):
                if any(q == h or q.startswith(h + os.sep) for h in homes):
                    return True
        return False

    def _file_texts(self, value) -> list:
        """The text of the existing regular files a value names (bounded)."""
        if value[:1] == '~' and (len(value) == 1 or value[1] == '/'):
            value = self.home + value[1:]
        out = []
        for f in (self._existing(value, False) or [])[:8]:
            if not os.path.isfile(f):
                continue
            if self._wrapper_file(f) is not None:
                out.append('stop.sh')
                continue
            try:
                with open(f, errors='replace') as fh:
                    out.append(fh.read(1 << 20))
            except OSError:
                continue
        return out

    def _harness_context(self) -> bool:
        """The command runs in the harness home's hooks/ or scripts/ directory, names one of
        them or a name directly in one, or names a file that is a wrapper."""
        dirs = _harness_dirs()

        def inside(p):
            """The directory itself, or a non-directory name directly in it. The harness's own eval
            emitters (/commit Phase 3's `eval "$(python3 .../session-index.py init ...)"`) print shell
            assignments, not a run: naming one is no context for the wrapper."""
            for q in (os.path.normpath(p), os.path.realpath(p)):
                if os.path.basename(q) in _EVAL_EMITTERS and os.path.dirname(q) in dirs:
                    return False
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
        for items in self.arrays.values():
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
        if res.name in _sp.DECLARATION_BUILTINS + ('env',):
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
