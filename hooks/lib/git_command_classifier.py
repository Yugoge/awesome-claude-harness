"""Git invocations in a Bash command, read through the shared shell parser.

classify_git_command(text) returns (invocations, residuals). Callers that
enforce policy must not read an empty invocation list as "no git runs":

  invocations  a GitInvocation(cmd_token, path_qualified, subcommand, args) per
               git command; cmd_token and args are the words as written, but
               an abbreviated long option reads as its full name.
  residuals    (kind, text) for a command the scan cannot resolve that may be
               git: obfuscated_git_token (`g\\it push`), dynamic_git_token
               (`$GIT push`), substituted_git_token (`$(which git) push`) and
               unresolved_shell_string (a shell `-c` string it cannot clear).

Where an invocation is found:
  - a simple command whose command word, past assignments, reserved words,
    redirections and wrappers (_command_token_index), is git: `/usr/bin/git`,
    `"git"`;
  - the commands of every substitution and process substitution, and of every
    here-document or here-string a reader may run (_here_docs_are_data: one
    only cat, tee or another data reader reads runs just its expansion's
    substitutions, unless the text holds a group, a compound command or an
    `exec` with redirections; one written to a file is data only when every
    other command of the text is inert and writes nothing (cat, ls, grep, ...),
    the file may land as data (_is_code_file: no hidden or `hooks` component,
    not under `~`, absolute only under /tmp), and the here-document is in the
    tool command itself, not in a `-c` string or substitution);
  - every shell `-c` string, every program option's value (`rg --pre`), and
    what echo or printf print into a pipe a shell reads, each read as a
    command line of its own (_shell_layers);
  - quoted text after a separator, given to a command that may run it
    (`python3 -c "x; git push"`), unless that command is known to leave its
    words unexecuted (_is_text_only: echo, printf, grep, rg, `git commit`,
    `git grep`, `git log --grep`), the command is one line with no
    substitution, and no pipe feeds a command that is neither text-only nor
    a stdin consumer (_is_stdin_consumer: head, sort, wc, ...; not less, and
    not a sort given `--compress-program`). `git grep` and `git log --grep`
    are text-only only with no assignment before git.

CLI usage:
  printf 'command text\\n' | python3 hooks/lib/git_command_classifier.py
  CMD_INPUT='command text' python3 hooks/lib/git_command_classifier.py
  Output: JSON array of {"subcommand": str, "args": list, "path_qualified": bool,
  "nested": bool}; `nested` marks an invocation inside a shell `-c` string.
  With CMD_RAW=stdin the input is a normalised view of the command, a NUL, then
  the raw command: the view is read for the command's own invocations, and the
  `-c` strings are resolved from the raw command and normalised the same way.
"""

import collections
import functools
import json
import os
import re
import sys

try:
    from lib import shell_parse
except ImportError:  # run as a script: hooks/lib is on sys.path
    import shell_parse

# One table each, in the parser.
GIT_GLOBAL_FLAGS = shell_parse.GIT_GLOBAL_FLAGS
GIT_GLOBAL_VALUE_OPTS = shell_parse.GIT_GLOBAL_VALUE_OPTS
LexError, Src, ansi_decode, lex = (shell_parse.LexError, shell_parse.Src,
                                   shell_parse.ansi_decode, shell_parse.lex)
resolve_long_option = shell_parse.resolve_long_option


# ---------------------------------------------------------------------------
# Segment splitter, for the callers that still read segments of their own
# ---------------------------------------------------------------------------


def _segments(c):
    """Split on shell separators ; \\n | & && || ` ( ) into command segments."""
    return [seg for seg, _kind, _in_quote in _segments_with_kind(c)]


def _segments_with_kind(c):
    """(segment_text, kind, in_quote) for each segment of c.

    The split ignores quoting. `(` opens a segment after `$`, `<`, `>` or in
    command position; a `)` closes only a boundary that was opened. kind is
    'start', 'separator', or 'subst_close' (opened by the `)` of a substitution
    in command position). in_quote: the boundary that opened the segment fell
    inside a ' or " string. A backslash-newline outside single quotes joins the
    lines, as bash does.
    """
    out, buf, i, n = [], [], 0, len(c)
    subshell_stack = []
    kind = 'start'
    sq = dq = esc = False
    in_quote = False

    def _buf_is_cmd_position():
        return all(ch.isspace() for ch in buf)

    def _flush(next_kind, cmd_pos_close=False):
        nonlocal buf, kind, in_quote, esc
        out.append((''.join(buf), kind, in_quote))
        buf = []
        kind = 'subst_close' if cmd_pos_close else next_kind
        in_quote = sq or dq
        esc = False

    while i < n:
        two = c[i:i + 2]
        if two in ('&&', '||'):
            _flush('separator'); i += 2; continue
        if two in ('$(', '<(', '>('):
            subshell_stack.append(_buf_is_cmd_position())
            _flush('separator'); i += 2; continue
        ch = c[i]
        if ch == '\n' and esc:
            buf.pop()
            esc = False
            i += 1
            continue
        if ch in ';\n|&`':
            _flush('separator'); i += 1; continue
        if ch == '(' and _buf_is_cmd_position():
            subshell_stack.append(False)
            _flush('separator'); i += 1; continue
        if ch == ')' and subshell_stack:
            was_cmd_position = subshell_stack.pop()
            _flush('separator', cmd_pos_close=was_cmd_position); i += 1; continue
        if esc:
            esc = False
        elif ch == '\\' and not sq:
            esc = True
        elif ch == "'" and not dq:
            sq = not sq
        elif ch == '"' and not sq:
            dq = not dq
        buf.append(ch); i += 1
    out.append((''.join(buf), kind, in_quote))
    return out


def _basename(tok):
    return tok.rsplit('/', 1)[-1]


def _unquote_token(tok):
    """Strip balanced surrounding quotes: `"/usr/bin/git"` -> `/usr/bin/git`."""
    t = tok.strip()
    while len(t) >= 2 and t[0] == t[-1] and t[0] in ('"', "'"):
        t = t[1:-1]
    return t


# ---------------------------------------------------------------------------
# The command word
# ---------------------------------------------------------------------------

# Wrappers that put the next word in command position, their flags that take
# the next word as a value, and the operands before the command word: the
# parser's wrapper tables (shell_parse.WRAPPERS, PEEL), plus `eval`, whose words
# are a command line.
_WRAPPER_SPECS = {name: entry for table in (shell_parse.WRAPPERS, shell_parse.PEEL)
                  for name, entry in table.items() if entry is not None}
_WRAPPERS = set(_WRAPPER_SPECS) | {'eval'}
_WRAPPER_VALUE_FLAGS = {name: spec['val'] for name, (spec, _fixed) in _WRAPPER_SPECS.items()}
_WRAPPER_POSITIONALS = {name: fixed for name, (_spec, fixed) in _WRAPPER_SPECS.items() if fixed}

# Reserved words (and `!`) after which the grammar puts a command word. `for`,
# `select`, `case`, `in` and `function` are followed by a name, and `fi`,
# `done`, `esac`, `}`, `]]`, `[[` end a construct, so they are not here.
_SHELL_PREFIX_KEYWORDS = {
    'if', 'elif', 'then', 'else', 'while', 'until', 'do', '!', '{', 'coproc',
}

# Leading redirections, attached (`2>/dev/null`, `{fd}>f`) or bare (`2> f`).
_REDIRECT_RE = re.compile(
    r'^(?:\{[A-Za-z_][A-Za-z0-9_]*\}|\d+)?'
    r'(?:<<<|<<-|<<|>>|&>>|&>|>&|<&|>\||<>|>|<)'
)

_ENV_ASSIGN_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(?:\[[^]]*\])?\+?=')


def _command_token_index(toks):
    """Index of the command word among toks, or None.

    Skips assignments (`FOO=1`, `arr[0]=1`), reserved words, redirections,
    wrappers, a wrapper's own flags and their values, and its positional
    argument (`timeout 30`, `flock /tmp/lock`).
    """
    i = 0
    n = len(toks)
    pending_positionals = 0
    last_wrapper = None
    while i < n:
        t = toks[i]
        if pending_positionals and not t.startswith('-'):
            pending_positionals -= 1
            i += 1
            continue
        if _ENV_ASSIGN_RE.match(t):
            i += 1
            continue
        if t in _SHELL_PREFIX_KEYWORDS:
            i += 1
            continue
        m = _REDIRECT_RE.match(t)
        if m:
            i += 1 if len(t) > m.end() else 2
            continue
        base = _basename(_unquote_token(t))
        if base in _WRAPPERS:
            last_wrapper = base
            pending_positionals = _WRAPPER_POSITIONALS.get(base, 0)
            i += 1
            continue
        if last_wrapper and t.startswith('-') and t != '--':
            i += 2 if t in _WRAPPER_VALUE_FLAGS.get(last_wrapper, ()) else 1
            continue
        if last_wrapper and t == '--':
            i += 1
            continue
        return i
    return None


def _git_subcommand_index(args):
    """Index of the subcommand among git's args (global options skipped), or None."""
    i = 0
    while i < len(args):
        a = args[i]
        if a in GIT_GLOBAL_VALUE_OPTS:
            i += 2
            continue
        if a.startswith('-'):
            i += 1
            continue
        return i
    return None


def _git_subcommand(args):
    """Return (subcommand, remaining_args) skipping git global options."""
    i = _git_subcommand_index(args)
    return (None, []) if i is None else (args[i], args[i + 1:])


# Git subcommands. Used only to decide whether an unresolvable command word is
# followed by a git verb: `$(cat f) status` is suspicious, `$(cat f) --version`
# is not.
_GIT_SUBCOMMANDS = frozenset("""
add am annotate apply archive bisect blame branch bundle checkout cherry
cherry-pick citool clean clone commit commit-tree config count-objects
describe diff diff-tree difftool fast-export fast-import fetch filter-branch
filter-repo for-each-ref format-patch fsck gc grep hash-object help init
instaweb log ls-files ls-remote ls-tree merge merge-base merge-file mergetool
mktag mktree mv name-rev notes pack-objects pull push range-diff read-tree
rebase reflog remote repack replace request-pull reset restore revert rev-list
rev-parse rm send-email shortlog show show-branch show-ref sparse-checkout
stash status stripspace submodule switch symbolic-ref tag update-index
update-ref verify-commit verify-pack whatchanged worktree write-tree
""".split())

_EXPANSION_RE = re.compile(r'\$[A-Za-z_{(]|\$\d|`')
_VARREF_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)')


def _resolves_to_non_git(tok, assigns):
    """True iff tok's expansions are pinned by this same text to something not git.

    `L="python3 ledger.py"; $L init` runs python3. Every path where the value
    is not pinned returns False: no assignment in this text, more than one
    distinct value, an empty value, or a value that is itself an expansion.
    Substitution is applied to the whole token and re-checked, so
    `G=g; ${G}it push` still reassembles to `git`. An assignment that does not
    execute (`false && G=echo`) still counts as pinning.
    """
    refs = _VARREF_RE.findall(tok)
    if not refs:
        return False
    resolved = tok
    for braced, bare in refs:
        name = braced or bare
        values = assigns.get(name)
        if not values or len(values) != 1:
            return False
        value = next(iter(values))
        if not value or _EXPANSION_RE.search(value):
            return False
        resolved = resolved.replace('${%s}' % name if braced else '$%s' % name, value)
    if _EXPANSION_RE.search(resolved):
        return False
    words = resolved.split()
    return bool(words) and os.path.basename(_unquote_token(words[0])) != 'git'


# ---------------------------------------------------------------------------
# Reading text with the shared lexer
# ---------------------------------------------------------------------------

_RUNTIME = '\x00'  # stands for text the shell computes at run time
# A run-time value as a layer's text shows it: an expansion no assignment pins.
_RUNTIME_PLACEHOLDER = '${__runtime__}'
_RUNTIME_PLACEHOLDER_RE = re.compile(re.escape(_RUNTIME_PLACEHOLDER))
# Word parts the shell computes at run time, and those that run commands.
_DYNAMIC_PARTS = frozenset({'param', 'sub', 'arith', 'procsub'})
_BODY_PARTS = frozenset({'sub', 'arith', 'procsub'})
# Text the lexer cannot read is read again with its quoting, then all its shell
# syntax, removed: the words survive.
_DEGRADE = (re.compile(r'[\'"`\\]'), re.compile(r'[\'"`\\$()<>]'))
_MAX_DATA_DEPTH = 16
# Characters without which quoted text holds no command after a separator.
_DATA_HINT_RE = re.compile(r'[;\n|&`(]')
_NOT_DROPPABLE_RE = re.compile(r'\n|\$\(|<\(|>\(|`')


class _Cmd:
    """One simple command: its words, its redirections, and the operator before it."""

    __slots__ = ('words', 'redirs', 'opener')

    def __init__(self, words, redirs, opener):
        self.words, self.redirs, self.opener = words, redirs, opener


def _lex(text, degrade=True):
    """(tokens, exact): lex() of text, degraded when it cannot be read as written."""
    try:
        return lex(Src.from_raw(text)), True
    except LexError:
        if not degrade:
            raise
    for pattern in _DEGRADE:
        try:
            return lex(Src.from_raw(pattern.sub(' ' if pattern is _DEGRADE[1] else '', text))), False
        except LexError:
            continue
    return [], False


def _group(toks):
    """The simple commands of a token list."""
    cmds, words, redirs, opener = [], [], [], None
    for tok in toks:
        if tok[0] == 'W':
            words.append(tok[1])
        elif tok[0] == 'R':
            redirs.append(tok[1])
        else:
            if words or redirs:
                cmds.append(_Cmd(words, redirs, opener))
                words, redirs = [], []
                opener = tok[1]
            elif tok[1] != '(' and not (tok[1] == '\n' and opener in ('|', '|&', '&&', '||')):
                # A group opened after a pipe is fed by it; a line ending in
                # an operator goes on to the next line's command.
                opener = tok[1]
    if words or redirs:
        cmds.append(_Cmd(words, redirs, opener))
    return cmds


def _value(word):
    """(value, runtime): the word as its command receives it, run-time parts _RUNTIME."""
    out, runtime = [], False
    for kind, src, _off in word.segs:
        if kind == 'ansi':
            out.append(ansi_decode(src.text))
        elif kind in _DYNAMIC_PARTS:
            out.append(_RUNTIME)
            runtime = True
        elif kind == 'arraylit':
            out.append('(' + src.text + ')')
        else:
            out.append(src.text)
    value = ''.join(out)
    return value, runtime or _RUNTIME in value


def _subst_bodies(cmd):
    """The substitution bodies of cmd's words and redirection targets."""
    out = []
    for word in cmd.words + [r.target for r in cmd.redirs if r.target is not None]:
        out.extend(src.text for kind, src, _off in word.segs if kind in _BODY_PARTS)
    return out


def _bodies(cmd):
    """The texts cmd runs as commands of their own: substitutions, then here-documents."""
    return _subst_bodies(cmd) + [r.heredoc[2].text for r in cmd.redirs if r.heredoc is not None]


def _here_doc_code(redir, code):
    """The texts a here-document runs as commands: its body when code, else its substitutions.

    An unquoted delimiter has the outer shell expand the body first, running its
    substitutions whoever reads it; a body whose expansions the lexer cannot
    read counts as code.
    """
    _delim, quoted, body = redir.heredoc
    if code:
        return [body.text]
    if quoted:
        return []
    try:
        return _expand_here_doc(body.text)[1]
    except LexError:
        return [body.text]


# Words that open or close a compound command. A here-document inside one
# (`for ...; do cat <<'EOF'; done | sh`) may reach whatever reads the
# compound's output, so, as with a group, the text's here-documents are code.
_COMPOUND_WORDS = frozenset({
    'for', 'select', 'while', 'until', 'if', 'then', 'elif', 'else', 'fi',
    'do', 'done', 'case', 'esac', 'function', 'coproc', '{', '}',
})
# Redirections that write a file.
_WRITE_REDIRS = frozenset({'>', '>>', '>|', '&>', '&>>'})


def _opens_compound(cmd):
    """True iff the simple command cmd opens or closes a group or compound command."""
    values = _values(cmd.words[:2])
    if values[:1] in (['!'], ['time']):
        values = values[1:]
    return bool(values) and values[0] in _COMPOUND_WORDS


# A here-document whose pipe writes a file is data only when nothing on the
# same line can run that file: every other command of the text is inert, and
# the file is none a shell, git, make or direnv runs or reads by itself. The
# rule is closed: a command not listed keeps the here-document code, so the
# many ways to run a file (`sh < x.sh`, `cat x.sh | sh`, `sh x.*`, `cp x.sh y
# && sh y`, `xargs`, `find -exec`, `make`) need no list of their own.
#
# Inert commands print, count, list, test or make directories, run nothing
# they are given and, as _is_inert requires, write nothing. chmod is absent
# (its +x is the step to running a file), cd (it moves the written file's
# relative path into `.git/` or a home directory), git (its config and
# attributes run programs: `core.fsmonitor`, `diff.external`), cp, mv, xargs,
# find, make, tee and every shell and interpreter.
_INERT_COMMANDS = frozenset({
    'cat', 'head', 'tail', 'wc', 'ls', 'echo', 'printf', 'test', '[',
    'true', 'false', 'mkdir', 'pwd',
})
# grep and rg are inert as text owners (_is_text_only).
_INERT_TEXT_OWNERS = frozenset({'grep', 'rg'})
# Where a written here-document may land as data. The rule is closed: a path
# with a hidden component (`.git/`, `.bashrc`, `.claude/`, `.vscode/`,
# `.config/`, and `..`, which leaves the tree), one under the home directory
# (`~`), one with a `hooks` component (`core.hooksPath`), an absolute one
# outside /tmp and /var/tmp, and one of these names (any case, files a tool
# runs by name) is code. Names a tool runs that need no dot:
_CODE_FILES = frozenset({'makefile', 'gnumakefile', 'gitconfig'})
_CODE_DIRS = frozenset({'hooks'})
_DATA_ROOTS = ('/tmp/', '/var/tmp/')
# Commands that copy their input to a file a word of theirs names.
_FILE_COPIERS = frozenset({'cp', 'mv', 'ln', 'install', 'truncate', 'dd'})
_NULL_FILES = frozenset({'/dev/null', '/dev/stdout', '/dev/stderr'})


def _written_paths(cmds, k, end):
    """(paths, unknown): the files the pipe cmds[k:end] writes, and whether one cannot be named.

    Paths come from write redirections and tee's operands. A command that
    copies its input to a file (`cp /dev/stdin x.sh`), or a path computed at
    run time, makes the set unknown.
    """
    paths, unknown = [], False
    for cmd in cmds[k:end]:
        targets = [r.target for r in cmd.redirs if r.op in _WRITE_REDIRS and r.target is not None]
        values = _values(cmd.words)
        idx, name = _command_name(cmd.words, values)
        if idx is not None and name in _FILE_COPIERS:
            unknown = True
        elif idx is not None and name == 'tee':
            targets += [w for w in cmd.words[idx + 1:] if not _value(w)[0].startswith('-')]
        for word in targets:
            value, runtime = _value(word)
            if runtime:
                unknown = True
            elif value not in _NULL_FILES:
                paths.append(value)
    return paths, unknown


def _is_code_file(path):
    """True iff a here-document written to path may be run or read as code by a tool (see _CODE_FILES)."""
    if path.startswith('~') or (path.startswith('/') and not path.startswith(_DATA_ROOTS)):
        return True
    parts = [part.lower() for part in path.split('/') if part and part != '.']
    return (not parts or parts[-1] in _CODE_FILES
            or any(p.startswith('.') or p in _CODE_DIRS for p in parts))


def _is_inert(cmd, written):
    """True iff the simple command cmd is inert (_INERT_COMMANDS and the rest), as written.

    It stands alone: no assignment, wrapper or reserved word before its
    command word, which is static, holds no `/` and names no written file
    (written, basenames), no substitution in its words, and it writes
    nothing: an output redirection only to /dev/null or another descriptor
    (`2>&1`, `>&2`).
    """
    for word in cmd.words + [r.target for r in cmd.redirs if r.target is not None]:
        if any(kind in ('sub', 'procsub') for kind, _src, _off in word.segs):
            return False
    for r in cmd.redirs:
        target = None if r.target is None else _value(r.target)[0]
        if r.op in _WRITE_REDIRS or r.op == '<>':
            if target != '/dev/null':
                return False
        elif r.op == '>&' and not (target is not None and (target.isdigit() or target == '-')):
            return False
    if not cmd.words:
        return True
    values = _values(cmd.words)
    if _command_token_index(values) != 0:
        return False
    name, runtime = _value(cmd.words[0])
    if runtime or '/' in name or name in written:
        return False
    if name == 'printf' and any(v == '-v' or v.startswith('-v') for v in values[1:2]):
        return False  # `printf -v PATH .` assigns a variable
    if name in _INERT_COMMANDS:
        return True
    return name in _INERT_TEXT_OWNERS and _is_text_only(cmd.words)


def _here_docs_are_data(toks, cmds, k, nested=False):
    """True iff the here-documents of cmds[k] are read as data.

    They are when every command of the pipe cmds[k] starts reads its input as
    data (_reads_input_as_data): `cat > notes.md <<'EOF'`, `cat <<'EOF' | sort`.
    A here-document in a text with a group or a compound command (`{ cat
    <<'EOF'; } | bash`, `for ...; do cat <<'EOF'; done | sh`) or an `exec`
    with redirections counts as code, as does one whose output a substitution
    captures (see _code_commands). One whose pipe writes a file is data only
    when the file is named, may land as data (_is_code_file), and every other command of
    the text is inert and writes nothing (_is_inert): `cat > x.sh <<'EOF' ...
    && sh < x.sh` and `... && git status` are code. nested: the text is not
    the tool command itself but a `-c` string, an eval or program-option
    string, a substitution or a here-document body, whose surroundings the
    rule cannot see (`bash -c "cat > x.sh <<'EOF' ..." && sh x.sh`), so a
    here-document there that writes a file is code.
    """
    if any(tok[0] == 'OP' and tok[1] == '(' for tok in toks) or any(map(_opens_compound, cmds)):
        return False
    if any(cmd.redirs and _values(cmd.words)[:1] == ['exec'] for cmd in cmds):
        return False
    j = k
    while True:
        if not _reads_input_as_data(cmds[j]):
            return False
        j += 1
        if j >= len(cmds) or cmds[j].opener not in ('|', '|&'):
            break
    paths, unknown = _written_paths(cmds, k, j)
    if not (paths or unknown):
        return True
    if nested or unknown or any(map(_is_code_file, paths)):
        return False
    written = {_basename(p) for p in paths}
    return all(_is_inert(cmd, written) for n, cmd in enumerate(cmds) if not k <= n < j)


def _code_commands(text, depth=0, captured=False, nested=False):
    """(commands, exact): every simple command text runs, its bodies' commands after it.

    A here-document read as data (_here_docs_are_data) runs only the
    substitutions its expansion performs; a here-string not read as data is
    read as commands too. captured: text is a substitution's
    body, whose output the outer command may run (`eval "$(cat <<'EOF' ...)"`),
    so its here-documents count as code. A substitution's output is data when
    its command is text-only and keeps its input as data, as is every command
    a pipe feeds from it (`git commit -m "$(cat <<'EOF' ...)"`).
    """
    toks, exact = _lex(text)
    cmds = _group(toks)
    out = []
    nested = nested or depth > 0
    for k, cmd in enumerate(cmds):
        out.append(cmd)
        if depth < _MAX_DATA_DEPTH:
            subst = _subst_bodies(cmd)
            held = bool(subst) and (captured or not (_is_text_only(cmd.words)
                                                     and _here_docs_are_data(toks, cmds, k, nested)))
            for body in subst:
                out.extend(_code_commands(body, depth + 1, held, nested)[0])
            docs = [r for r in cmd.redirs if r.heredoc is not None]
            strings = [r for r in cmd.redirs if r.op == '<<<' and r.target is not None]
            code = bool(docs or strings) and (captured or not _here_docs_are_data(toks, cmds, k, nested))
            for redir in docs:
                for body in _here_doc_code(redir, code):
                    out.extend(_code_commands(body, depth + 1, captured, nested)[0])
            if code:
                # A here-string is a here-document of one word: code when its
                # reader may run it (`sh <<< 'git push'`).
                for redir in strings:
                    out.extend(_code_commands(_value(redir.target)[0], depth + 1, captured, nested)[0])
    return out, exact


def _values(words):
    return [_value(w)[0] for w in words]


def _invocations(words, aliases=None, depth=0, seen=frozenset()):
    """The GitInvocation of a simple command whose command word is git, then its alias's.

    An alias the invocation defines with `-c alias.<name>=<value>` (or inherits
    from the git that ran it) is read too: a `!` value is shell text git runs
    with the arguments, any other value the git arguments the name stands for.
    """
    values = _values(words)
    idx = _command_token_index(values)
    if idx is None:
        return
    token = words[idx].raw.text
    if _basename(_unquote_token(token)) != 'git':
        return
    gvals = values[idx + 1:]
    graws = [w.raw.text for w in words[idx + 1:]]
    k = _git_subcommand_index(gvals)
    if k is None:
        yield GitInvocation(token, '/' in token, None, [])
        return
    static = not _value(words[idx + 1 + k])[1]
    sub = gvals[k] if static else graws[k]
    # An abbreviated long option git accepts reads as its full name (`--har`).
    args = [raw if full == value else full
            for raw, value, full in ((r, v, resolve_long_option(sub, v))
                                     for r, v in zip(graws[k + 1:], gvals[k + 1:]))]
    yield GitInvocation(token, '/' in token, sub, args)
    aliases = dict(aliases or {})
    i = 0
    while i < k:
        opt = gvals[i]
        pair = gvals[i + 1] if opt in ('-c', '--config-env') and i + 1 < k else (
            opt[len('--config-env='):] if opt.startswith('--config-env=') else '')
        key, eq, val = pair.partition('=')
        if eq and key.lower().startswith('alias.'):
            aliases[key[len('alias.'):].lower()] = val if opt == '-c' else None
        i += 2 if opt in GIT_GLOBAL_VALUE_OPTS else 1
    name = gvals[k].lower()
    body = aliases.get(name)
    # git refuses an alias that reaches itself again, so a loop runs nothing more.
    if body is None or name in seen or depth >= _MAX_SHELL_DEPTH:
        return
    rest = ' '.join(graws[k + 1:])
    text = body[1:] + ' ' + rest if body.startswith('!') else 'git %s %s' % (body, rest)
    for cmd in _code_commands(text, nested=True)[0]:
        yield from _invocations(cmd.words, aliases, depth + 1, seen | {name})


# Commands known to leave their arguments and their standard input unexecuted:
# echo and printf print them, grep reads its pattern as text. Every other
# command, a launcher (`python3 -c`, `su -c`, `find -exec`, `ssh`) included, may
# run quoted text it is given. ag and ack are absent: their `--pager` runs a
# shell.
_TEXT_ONLY_COMMANDS = frozenset({'echo', 'printf', 'grep'})
# git subcommands whose quoted arguments are text (`git commit -m "a; git push"`).
_TEXT_ONLY_GIT_SUBCOMMANDS = frozenset({'commit'})
# git subcommands whose quoted arguments are text when git is given no
# configuration on its command line (a `-c` value may name a program git runs)
# and no assignment before it (`GIT_EXTERNAL_DIFF=... git log`):
# `git grep` without `-O`/`--open-files-in-pager` (that option runs a pager),
# and `git log` reading a `--grep` pattern.
_TEXT_SEARCH_GIT_SUBCOMMANDS = frozenset({'grep', 'log'})
_GIT_CONFIG_OPTS = ('-c', '--config-env')
# rg reads its pattern as text, unless a preprocessor runs (`--pre`,
# `--pre-glob`) or a config file it is pointed at may add one.
_RG_PROGRAM_OPTS = ('--pre', '--pre-glob')
# Commands that read what a pipe feeds them as text and never run it. They are
# not text-only: their own arguments may name a program (`sort
# --compress-program`), and one given such an option (_PROGRAM_OPTIONS) is no
# consumer, whatever its value: sort hands its input to the compressor. less is
# absent: LESSOPEN and LESSCLOSE name an input preprocessor (`|-sh %s` runs
# what it reads), and they may come from the inherited environment, which the
# command line cannot show.
_STDIN_CONSUMERS = frozenset({
    'head', 'tail', 'wc', 'sort', 'uniq', 'cut', 'tr', 'column', 'nl',
})


def _long_opt_named(value, names):
    """True iff value is one of the long options names, or an abbreviation of one, `=value` aside."""
    opt = value.split('=', 1)[0]
    return len(opt) > 2 and opt.startswith('--') and any(name.startswith(opt) for name in names)


def _command_name(words, values):
    """(index, name) of the command word of words, or (None, None) when eval reads the line again."""
    idx = _command_token_index(values)
    if idx is None:
        return None, None
    # `eval echo "x; git push"` reads echo's quoted text again as shell code.
    if any(_basename(v) == 'eval' for v in values[:idx]):
        return None, None
    return idx, _basename(_unquote_token(words[idx].raw.text))


def _is_text_only(words):
    """True iff the command of words is known to leave its arguments and input unexecuted."""
    values = _values(words)
    idx, name = _command_name(words, values)
    if idx is None:
        return False
    if name == 'rg':
        if any(_ENV_ASSIGN_RE.match(v) and v.startswith('RIPGREP_CONFIG_PATH') for v in values[:idx]):
            return False
        return _basename(values[idx]) == 'rg' and not any(
            _long_opt_named(v, _RG_PROGRAM_OPTS) for v in values[idx + 1:])
    if name != 'git':
        return _basename(values[idx]) in _TEXT_ONLY_COMMANDS
    gargs = values[idx + 1:]
    k = _git_subcommand_index(gargs)
    sub = None if k is None else gargs[k]
    if sub in _TEXT_ONLY_GIT_SUBCOMMANDS:
        return True
    if sub not in _TEXT_SEARCH_GIT_SUBCOMMANDS:
        return False
    # An assignment before git may name a program it runs or the config it
    # reads (GIT_EXTERNAL_DIFF, GIT_CONFIG_COUNT/KEY_n/VALUE_n,
    # GIT_CONFIG_PARAMETERS, GIT_PAGER, PAGER, HOME, GIT_DIR, ...).
    if any(_ENV_ASSIGN_RE.match(v) for v in values[:idx]):
        return False
    if any(v in _GIT_CONFIG_OPTS or v.startswith('--config-env=') for v in gargs[:k]):
        return False
    rest = gargs[k + 1:]
    if sub == 'grep':
        return not any((v.startswith('-') and not v.startswith('--') and 'O' in v)
                       or _long_opt_named(v, ('--open-files-in-pager',)) for v in rest)
    return any(v == '--grep' or v.startswith('--grep=') for v in rest)


def _is_stdin_consumer(words):
    """True iff the command of words reads what a pipe feeds it as text: _STDIN_CONSUMERS.

    A consumer given an option whose value is a program (_PROGRAM_OPTIONS,
    `sort --compress-program=sh`, any spelling or abbreviation), or with an
    assignment before it (`SORTOPTS=x sort`), is not one.
    """
    values = _values(words)
    idx, name = _command_name(words, values)
    if idx is None or name not in _STDIN_CONSUMERS or _basename(values[idx]) != name:
        return False
    if any(_ENV_ASSIGN_RE.match(v) for v in values[:idx]):
        return False
    return not any(_long_opt_named(v, _PROGRAM_OPTIONS.get(name, ())) for v in values[idx + 1:])


def _reads_input_as_data(cmd):
    """True iff the simple command cmd keeps its standard input as data.

    A text-only command, a _DATA_ONLY_COMMANDS one (`cat`, `tee`), a stdin
    consumer, `git commit` (`-F -`), and a command of redirections alone do;
    a shell, an interpreter (`python3 -`), `source /dev/stdin`, `ssh`, a
    command named at run time and every command not known do not. A command
    that hands its input to a process substitution (`tee >(sh)`, `> >(sh)`) or
    to a descriptor of its own (`>&3`) does not either.
    """
    for word in cmd.words + [r.target for r in cmd.redirs if r.target is not None]:
        if any(kind == 'procsub' for kind, _src, _off in word.segs):
            return False
    for r in cmd.redirs:
        if r.op in ('>&', '<&', '&>', '&>>') and r.target is not None:
            if _value(r.target)[0] not in ('1', '2', '-') and r.op in ('>&', '<&'):
                return False
    if not cmd.words:
        return True
    values = _values(cmd.words)
    idx, name = _command_name(cmd.words, values)
    if idx is None or _value(cmd.words[idx])[1]:
        return False
    if _is_text_only(cmd.words) or _is_stdin_consumer(cmd.words):
        return True
    return name in _DATA_ONLY_COMMANDS and _basename(values[idx]) == name


def _data_invocations(value, depth=0):
    """Git invocations in quoted text a command is given, read as shell text.

    The text before its first separator continues the word it sits in; the
    commands after it, every substitution in it, and the same reading of each
    word in it count.
    """
    if depth > _MAX_DATA_DEPTH or not _DATA_HINT_RE.search(value):
        return
    toks, _exact = _lex(value)
    head = next((k for k, tok in enumerate(toks) if tok[0] == 'OP'), len(toks))
    for tok in toks[:head]:
        word = tok[1] if tok[0] == 'W' else tok[1].target
        if word is not None:
            yield from _word_invocations(word, depth + 1)
    for cmd in _group(toks[head + 1:]):
        yield from _invocations(cmd.words)
        for word in cmd.words:
            yield from _word_invocations(word, depth + 1)
        for body in _bodies(cmd):
            for inner in _code_commands(body, depth + 1)[0]:
                yield from _cmd_invocations(inner, depth + 1)


def _word_invocations(word, depth):
    """Invocations in one word of quoted text: its substitutions' commands, then its text."""
    for kind, src, _off in word.segs:
        if kind in _BODY_PARTS:
            for cmd in _code_commands(src.text, depth)[0]:
                yield from _cmd_invocations(cmd, depth)
    yield from _data_invocations(_value(word)[0], depth)


def _cmd_invocations(cmd, depth):
    yield from _invocations(cmd.words)
    for word in cmd.words:
        yield from _data_invocations(_value(word)[0], depth + 1)


def _segment_invocations(command_text, tagged=False, nested=False):
    """iter_git_invocations() for command_text itself, its `-c` strings aside.

    tagged: yield (invocation, quoted) instead, quoted when the invocation was
    read from quoted text a command is given.
    """
    cmds, exact = _code_commands(command_text, nested=nested)
    droppable = (exact and not _NOT_DROPPABLE_RE.search(command_text)
                 and not any(cmd.opener in ('|', '|&') and not _is_text_only(cmd.words)
                             and not _is_stdin_consumer(cmd.words) for cmd in cmds))
    for cmd in cmds:
        for inv in _invocations(cmd.words):
            yield (inv, False) if tagged else inv
        if droppable and _is_text_only(cmd.words):
            continue
        for word in cmd.words:
            for inner in _data_invocations(_value(word)[0]):
                yield (inner, True) if tagged else inner


def _segment_residual_shapes(command_text, nested=False):
    """Yield (kind, text) for command words that may be git but did not resolve.

    Only a command word raises one, so git in argument position (`grep git .`,
    `echo "git status"`) raises nothing:
      obfuscated_git_token   its value is `git` but its spelling is not
                             (`g\\it push`, `gi""t push`, `$'git' push`);
      dynamic_git_token      it holds an expansion and a git verb follows
                             (`$GIT push`, `${G}it commit`), unless an
                             assignment in the text pins it to something else;
      substituted_git_token  it is a command substitution and a git verb
                             follows (`$(which git) push`).
    """
    cmds, _exact = _code_commands(command_text, nested=nested)
    assigns = {}
    for cmd in cmds:
        raws = [w.raw.text for w in cmd.words]
        if raws[:1] == ['export']:
            raws = raws[1:]
        if raws and _ENV_ASSIGN_RE.match(raws[0]):
            name, _eq, value = raws[0].partition('=')
            assigns.setdefault(name.rstrip('+'), set()).add(_unquote_token(value))
    for cmd in cmds:
        values = _values(cmd.words)
        idx = _command_token_index(values)
        if idx is None:
            continue
        word = cmd.words[idx]
        raw = word.raw.text
        if _basename(_unquote_token(raw)) == 'git':
            continue
        text = ' '.join(w.raw.text for w in cmd.words)
        sub = _git_subcommand(values[idx + 1:])[0]
        kinds = {kind for kind, _src, _off in word.segs}
        if not kinds & _DYNAMIC_PARTS:
            if _basename(values[idx]) == 'git':
                yield ('obfuscated_git_token', text)
        elif sub in _GIT_SUBCOMMANDS:
            if kinds <= {'sub'}:
                yield ('substituted_git_token', text)
            elif not _resolves_to_non_git(raw, assigns):
                yield ('dynamic_git_token', text)


# ---------------------------------------------------------------------------
# Shell `-c` strings
# ---------------------------------------------------------------------------
# A shell's `-c` string is a command line the shell parses again, so it is read
# as one (_shell_layers). A string holding a value the outer shell computes at
# run time is read with each such value a placeholder, and is the residual
# `unresolved_shell_string` when it is git-shaped (_may_run_git) or may run
# run-time text as shell or code (_runs_runtime_code). `bash -c "git $SUB"` and
# `bash -c "$CMD"` are residuals; `bash -c "cd $DIR && npm test"` runs npm.
# Text whose quoting the scan cannot follow is a residual when what follows its
# shell `-c` is git-shaped; a string nested deeper than _MAX_SHELL_DEPTH always
# is. A here-document is shell text only when a shell may read it
# (_reads_as_shell); for any other reader it runs only the substitutions the
# outer shell performs to expand it, and none when its delimiter is quoted.
#
# _runs_runtime_code fails closed: a list of dangerous programs can never be
# complete, so a program it does not model, given a run-time word, runs it,
# unless the program keeps its words as data (_DATA_ONLY_COMMANDS). An
# exec-style launcher runs a run-time word unless its sub-command is a static
# data one; curl loads code through a run-time `--engine`/`-K`/`--config`; a
# run-time environment assignment may load code unless the variable cannot
# (_SAFE_ENV_VARS), and a bare one to an unsafe name reaches a later command;
# and a run-time `-c` value the outer shell built by running code
# (`bash -c "y=$(echo $X | sh)"`) is a residual too.

_MAX_SHELL_DEPTH = 4
# A shell is known by the shape of its name (bash, sh, dash, zsh, ksh93, ...).
# No dot before `sh`: `deploy.sh` is a script.
_SHELL_NAME_RE = re.compile(r'[^/\s.]*sh[0-9.]*\Z')
_SHELL_HINT_RE = re.compile(r'sh[0-9.]*["\']?\s')
# A shell word, its options, then an option cluster holding `c`.
_SHELL_C_SHAPE_RE = re.compile(r'sh[0-9.]*["\']?\s+(?:[-+]\S*\s+(?:\w+\s+)?)*-[A-Za-z]*c')
# Commands that hand their standard input to a shell, besides the shells.
_STDIN_SHELL_COMMANDS = frozenset({
    'ssh', 'su', 'runuser', 'source', '.', 'at', 'batch', 'parallel', 'script',
})

# Commands that run their arguments as shell text or code, or hand them to a
# shell, in ways the scan does not model: any run-time word among their
# arguments, and any input fed to them, may run.
_RUNTIME_ARG_COMMANDS = frozenset({
    'alias', 'trap', 'at', 'batch', 'parallel', 'runuser', 'screen', 'script',
    'ssh', 'su', 'tmux', 'watch', 'sed', 'gsed', 'ex', 'nvim', 'vi', 'view', 'vim',
})
# Programs known to keep their words and input as data: a filename, a URL, a
# host, a number, never a command or code. A program belongs here only when no
# option or operand of it runs a command or loads code, so `tar`, `rsync`,
# `nc`, `scp`, `find`, `sort`, `wget`, `curl`, the launchers and every
# interpreter are absent.
_DATA_ONLY_COMMANDS = frozenset({
    'cat', 'tee', 'cd', 'pwd', 'ls', 'head', 'tail', 'wc', 'uniq', 'cut',
    'tr', 'rev', 'tac', 'nl', 'fold', 'paste', 'join', 'comm', 'column', 'cp', 'mv',
    'rm', 'ln', 'mkdir', 'rmdir', 'touch', 'chmod', 'chown', 'chgrp', 'stat', 'file',
    'readlink', 'realpath', 'basename', 'dirname', 'mktemp', 'truncate', 'du', 'df',
    'date', 'seq', 'true', 'false', 'test', 'sleep', 'diff', 'cmp', 'base64', 'cksum',
    'md5sum', 'sha1sum', 'sha256sum', 'od', 'hexdump', 'xxd', 'strings',
    'ping', 'host', 'dig', 'nslookup',
})
# Exec-style launchers: `run`/`exec` take a command, `build` runs a Dockerfile.
_EXEC_LAUNCHERS = frozenset({'docker', 'podman', 'kubectl'})
# Their sub-commands whose remaining words are image, container, resource or
# file names, and that run no command and load no code.
_LAUNCHER_DATA_SUBCOMMANDS = frozenset({
    'push', 'pull', 'tag', 'save', 'load', 'images', 'ps', 'inspect', 'logs',
    'version', 'info', 'login', 'logout', 'history', 'port', 'top',
    'get', 'describe', 'cluster-info', 'api-resources', 'api-versions',
})
# curl options that load code when given a run-time value: `--engine` loads a
# shared library; `-K`/`--config` reads a file that can set any option.
_CURL_CODE_LONG_OPTS = frozenset({'--config', '--engine'})
_CURL_CODE_SHORT_OPTS = frozenset({'K'})
# Variables whose run-time value, assigned to a command's environment, cannot
# load code: locale names select a compiled locale, TZ/TERM name a data file,
# the rest are numbers, flags or plain strings. HOME is absent: the Python user
# site, `~/.node_modules` and `~/.ssh/config` live under it.
_SAFE_ENV_VARS = frozenset({
    'LANG', 'LANGUAGE', 'LC_ALL', 'LC_CTYPE', 'LC_COLLATE', 'LC_MESSAGES',
    'LC_NUMERIC', 'LC_TIME', 'TZ', 'TERM', 'COLUMNS', 'LINES', 'PWD',
    'OLDPWD', 'USER', 'LOGNAME', 'HOSTNAME', 'TMPDIR', 'DISPLAY', 'NO_COLOR',
    'FORCE_COLOR', 'CLICOLOR', 'CLICOLOR_FORCE',
})
# A shell named among another command's words (`find -exec sh -c`), by name:
# the shape _SHELL_NAME_RE reads also matches `push`.
_EMBEDDED_SHELL_RE = re.compile(r'(?:ba|rba|da|a|z|k|mk|c|tc|fi|y|pw)?sh[0-9.]*\Z')
# Interpreters whose option grammar the scan does not model.
_OPAQUE_INTERPRETERS = frozenset({
    'bun', 'deno', 'elixir', 'expect', 'groovy', 'guile', 'irb', 'julia',
    'osascript', 'powershell', 'racket', 'sbcl', 'scala', 'ts-node', 'tsx',
})
# Interpreters by the shape of their name, and how each is told its program
# (_interpreter_runs_runtime). program: short options whose value is the
# program; value: short options whose value may load code, unless `data` names
# them; both take the rest of their cluster, else the next word. attached:
# short options whose value is only the rest of their cluster. long_program,
# long_value: the long forms. stdin: with no program named it reads one from
# standard input. stop: an option naming the program ends the options.
_Interpreter = collections.namedtuple(
    '_Interpreter', 'program value attached long_program long_value data stdin stop')
_NODE_VALUE_OPTIONS = frozenset({  # `node --help`, v22: the options shown with `=...`
    '--allow-fs-read', '--allow-fs-write', '--build-snapshot-config', '--conditions',
    '--cpu-prof-dir', '--cpu-prof-interval', '--cpu-prof-name', '--diagnostic-dir',
    '--disable-proto', '--disable-warning', '--dns-result-order', '--env-file',
    '--env-file-if-exists', '--experimental-config-file', '--experimental-default-type',
    '--experimental-loader', '--experimental-sea-config', '--experimental-test-isolation',
    '--heap-prof-dir', '--heap-prof-interval', '--heap-prof-name',
    '--heapsnapshot-near-heap-limit', '--heapsnapshot-signal', '--icu-data-dir', '--import',
    '--input-type', '--inspect-publish-uid', '--loader', '--localstorage-file',
    '--max-http-header-size', '--max-old-space-size-percentage',
    '--network-family-autoselection-attempt-timeout', '--openssl-config',
    '--redirect-warnings', '--report-filename', '--report-signal', '--require',
    '--secure-heap', '--secure-heap-min', '--snapshot-blob', '--test-concurrency',
    '--test-coverage-branches', '--test-coverage-exclude', '--test-coverage-functions',
    '--test-coverage-include', '--test-coverage-lines', '--test-name-pattern',
    '--test-reporter', '--test-reporter-destination', '--test-shard', '--test-skip-pattern',
    '--test-timeout', '--title', '--tls-cipher-list', '--tls-keylog',
    '--trace-event-categories', '--trace-event-file-pattern', '--trace-require-module',
    '--unhandled-rejections', '--use-largepages', '--v8-pool-size', '--watch-kill-signal',
    '--watch-path',
})
_INTERPRETERS = (
    (re.compile(r'(?:python|pypy)[0-9.]*\Z'),
     _Interpreter('cm', 'QWX', '', (), ('--check-hash-based-pycs',), (), True, True)),
    (re.compile(r'perl[0-9.]*\Z'),
     _Interpreter('Ee', 'IMm', '0CDFVdilx', (), (), (), True, False)),
    (re.compile(r'ruby[0-9.]*\Z'),
     _Interpreter('e', 'CEIr', '0FKTWx', (), (), (), True, False)),
    (re.compile(r'node(?:js)?[0-9.]*\Z'),
     _Interpreter('ep', 'Cr', '', ('--eval', '--print', '--run'), _NODE_VALUE_OPTIONS, (), True, False)),
    (re.compile(r'php[0-9.]*\Z'),
     _Interpreter('FRfr', 'BEcdtSz', '', (), (), (), True, False)),
    (re.compile(r'lua(?:jit)?[0-9.]*\Z'),
     _Interpreter('', 'el', '', (), (), (), True, False)),
    (re.compile(r'[gmn]?awk\Z'),
     _Interpreter('Eef', 'FWilv', 'DLdop', ('--exec', '--file', '--source'),
                  ('--assign', '--field-separator', '--include', '--load'),
                  ('-F', '-v', '--assign', '--field-separator'), False, False)),
    (re.compile(r'Rscript\Z'), _Interpreter('e', '', '', (), (), (), False, False)),
)
# Paths that name standard input as a program or script.
_STDIN_PATHS = frozenset({'-', '/dev/stdin', '/dev/fd/0', '/proc/self/fd/0'})
_MAX_CODE_DEPTH = 64


def _shell_words(text, info=None):
    """Split shell text into simple commands of words, as the shell reads them.

    Returns (commands, bodies). A command is a list of (value, runtime) words,
    redirections left out: value is the word as the command receives it, each
    run-time part _RUNTIME; runtime is True when it holds one. bodies are the
    texts that run as commands of their own: substitution bodies, then what
    here-documents run (_here_doc_texts). Raises LexError on text the lexer
    cannot read.

    info, a dict, receives what may feed run-time text to each command's
    standard input: info['feeds'] holds a set per command, of 'pipe' (a pipe,
    or a group a pipe feeds), 'here-document' (one whose body holds a run-time
    value), 'here-string' and 'file' (a run-time word); info['body_fed'] a flag
    per body, True when its commands may read such input (a >( ) body, a
    substitution in a command a pipe feeds, what a shell runs from a run-time
    here-document); info['body_owner'] the command each body belongs to (None
    for a >( ) body) and info['body_subst_count'] how many leading bodies are
    substitutions.
    """
    toks = lex(Src.from_raw(text))
    cmds, bodies, owners, redirs_of, piped, groups, docs = [], [], [], [], [], [], []
    words, redirs = [], []
    opener = sep = None
    line_start = 0

    def end_cmd():
        nonlocal words, redirs
        if not (words or redirs):
            return False
        k = len(cmds)
        fed = opener in ('|', '|&') or any(groups)
        for word in words + [r.target for r in redirs if r.target is not None]:
            for kind, src, off in word.segs:
                if kind in _BODY_PARTS:
                    bodies.append(src.text)
                    outward = kind == 'procsub' and text[off:off + 1] == '>'
                    owners.append((None if outward else k, False))
        values = [_value(w) for w in words]
        cmds.append(values)
        redirs_of.append(redirs)
        piped.append(fed)
        if values and values[0][0] == '{':
            groups.append(fed)
        elif values and values[0][0] == '}' and groups:
            groups.pop()
        words, redirs = [], []
        return True

    for tok in toks:
        if tok[0] != 'OP':
            (words if tok[0] == 'W' else redirs).append(tok[1])
            sep = None
            continue
        op = tok[1]
        ended = end_cmd()
        if op == '\n':
            # A line ending in `|`, `&&` or `||` goes on past its here-documents.
            dangling = sep in ('|', '|&', '&&', '||')
            stop = len(cmds) + (1 if dangling else 0)
            for k in range(line_start, len(cmds)):
                docs.extend((r.heredoc[2].text, r.heredoc[1], k, stop)
                            for r in redirs_of[k] if r.heredoc is not None)
            line_start = len(cmds)
            if not dangling:
                opener = None
            continue
        if op == '(':
            groups.append(opener in ('|', '|&') and not ended)
        elif op == ')' and groups:
            groups.pop()
        sep = opener = op
    end_cmd()
    doc_fed = [False] * len(cmds)
    n_subst = len(bodies)
    for body, quoted, owner, stop in docs:
        texts = _here_doc_texts(body, quoted, any(map(_reads_as_shell, cmds[owner:stop])))
        bodies.extend(texts)
        runtime = info is not None and _here_doc_is_runtime(body, quoted)
        for k in range(owner, min(stop, len(cmds))):
            doc_fed[k] = doc_fed[k] or runtime
        owners.extend([(owner, runtime)] * len(texts))
    if info is not None:
        feeds = []
        for k, redirs in enumerate(redirs_of):
            kinds = {'pipe'} if piped[k] else set()
            if doc_fed[k]:
                kinds.add('here-document')
            for r in redirs:
                if r.target is None or not _value(r.target)[1]:
                    continue
                if r.op == '<<<':
                    kinds.add('here-string')
                elif r.op in ('<', '<>') and r.io in (None, '0'):
                    kinds.add('file')
            feeds.append(kinds)
        info['feeds'] = feeds
        info['body_fed'] = [owner is None or extra or (owner < len(piped) and piped[owner])
                            for owner, extra in owners]
        info['body_owner'] = [owner for owner, _extra in owners]
        info['body_subst_count'] = n_subst
    return cmds, bodies


def _reads_as_shell(words):
    """True iff the simple command `words` may run its standard input as shell commands.

    A shell (by the shape of its name), a command named at run time, a command
    that hands its input to a shell (_STDIN_SHELL_COMMANDS), one that names a
    shell among its words (`ssh host bash -s`), and a wrapper with no command
    (`sudo -i`) may; `cat`, `tee`, `python3` and `git commit -F -` read it as data.
    """
    values = [value for value, _runtime in words]
    idx = _command_token_index(values)
    if idx is None:
        return any(_basename(value) in _WRAPPERS for value in values)
    if words[idx][1]:
        return True
    names = [_basename(value) for value in values[idx:]]
    return names[0] in _STDIN_SHELL_COMMANDS or any(_SHELL_NAME_RE.match(name) for name in names)


def _here_doc_texts(body, quoted, shell_reads):
    """The texts a here-document's body runs as commands.

    With an unquoted delimiter the outer shell expands the body first, running
    its substitutions whoever reads it; a shell reading it then parses the
    expanded text. A quoted delimiter leaves the body as written. A body whose
    expansions the lexer cannot read is read as shell text, whoever reads it.
    """
    if quoted:
        return [body] if shell_reads else []
    try:
        text, subs = _expand_here_doc(body)
    except LexError:
        return [body]
    return subs + ([text] if shell_reads else [])


def _expand_here_doc(body):
    """(text, substitutions) of an unquoted here-document's body, each expansion _RUNTIME.

    Such a body expands as a double-quoted word does, its `"` characters plain
    text. Raises LexError on an expansion the lexer cannot read.
    """
    mark = '\x01'
    out, subs = [], []
    for tok in lex(Src.from_raw('"%s"' % body.replace('"', mark))):
        for kind, src, _off in tok[1].segs:
            if kind in _BODY_PARTS:
                subs.append(src.text.replace(mark, '"'))
            out.append(_RUNTIME if kind in _DYNAMIC_PARTS else src.text.replace(mark, '"'))
    return ''.join(out), subs


def _here_doc_is_runtime(body, quoted):
    """True iff a here-document's text, as its reader gets it, may hold a value computed at run time."""
    if quoted:
        return _RUNTIME in body
    try:
        return _RUNTIME in _expand_here_doc(body)[0]
    except LexError:
        return True


def _shell_c_operand(words, i):
    """Index of the `-c` command string among a shell's arguments from words[i], or None."""
    seen_c = maybe_c = False
    while i < len(words):
        value, runtime = words[i]
        if runtime:
            if seen_c:  # the -c string itself
                break
            maybe_c = True  # an unknown word may be any option, -c included
            i += 1
            continue
        if value in ('--', '-'):
            i += 1
            break
        if value.startswith('--'):
            i += 2 if value in ('--rcfile', '--init-file') else 1
        elif len(value) > 1 and value[0] in '-+':
            seen_c = seen_c or 'c' in value[1:]
            i += 1 + value[1:].count('o') + value[1:].count('O')  # -o / -O take a name
        else:
            break
    return i if (seen_c or maybe_c) and i < len(words) else None


def _shell_c_strings(text, fed=False):
    """Yield (kind, string, fed, built_by_code) for each shell `-c` string text runs.

    kind 'text': a string the scan resolved. 'runtime': one holding a value the
    outer shell computes at run time, each such value _RUNTIME in it.
    'unlexable', with text itself: text the lexer cannot read, with a shell's
    `-c` shape. fed: the string's shell may read run-time text on its standard
    input. built_by_code: a 'runtime' operand the outer shell built by running
    a substitution that runs run-time code (`-c "y=$(echo $X | sh)"`).
    """
    if not (_SHELL_HINT_RE.search(text) or _PROGRAM_HINT_RE.search(text)):
        return
    info = {}
    try:
        cmds, bodies = _shell_words(text, info)
    except Exception:  # text the lexer cannot read, or nesting past the interpreter's limit
        if _SHELL_C_SHAPE_RE.search(text):
            yield 'unlexable', text, fed, False
        return
    owner, n_subst = info['body_owner'], info['body_subst_count']
    for k, (words, feeds) in enumerate(zip(cmds, info['feeds'])):
        values = [v for v, _runtime in words]
        idx = _command_token_index(values)
        if idx is None or words[idx][1]:
            continue
        for value, runtime in _program_option_values(words, idx):
            yield ('runtime' if runtime else 'text'), value, fed or bool(feeds), False
        printed = _printed_to_shell(cmds, info['feeds'], k, idx)
        if printed is not None:
            yield ('runtime' if _RUNTIME in printed else 'text'), printed, fed or bool(feeds), False
        if not _SHELL_NAME_RE.match(_basename(values[idx])):
            continue
        op = _shell_c_operand(words, idx + 1)
        if op is None:
            continue
        value, runtime = words[op]
        built_by_code = runtime and any(
            owner[j] == k and _runs_runtime_code(bodies[j], info['body_fed'][j])
            for j in range(n_subst))
        yield ('runtime' if runtime else 'text'), value, fed or bool(feeds), built_by_code
    for body, body_fed in zip(bodies, info['body_fed']):
        yield from _shell_c_strings(body, fed or body_fed)


# Options whose value is a program the command runs, read as a command line of
# its own: rg's preprocessor, ag's and ack's pager (run by a shell), and
# sort's compressor. A long option may be abbreviated.
_PROGRAM_OPTIONS = {
    'rg': ('--pre',),
    'ag': ('--pager',),
    'ack': ('--pager',),
    'sort': ('--compress-program',),
}
_PROGRAM_HINT_RE = re.compile(r'(?:\A|[\s/;&|(`\'"])(?:rg|ag|ack|sort|git)\b')
# Commands that print their arguments, and the shell reads what they print
# when a pipe feeds it (`echo "git push" | sh`).
_PRINTERS = frozenset({'echo', 'printf'})
# The backslash escapes printf and `echo -e` print as characters: `\xHH`, an
# octal `\NNN` or `\0NNN`, and the letters. Read whatever the options say.
_ESCAPE_RE = re.compile(r'\\(x[0-9A-Fa-f]{1,2}|0?[0-7]{1,3}|[abefnrtv\\])')
_ESCAPE_LETTERS = {'a': '\a', 'b': '\b', 'e': '\x1b', 'f': '\f', 'n': '\n', 'r': '\r',
                   't': '\t', 'v': '\v', '\\': '\\'}


def _unescape(match):
    code = match.group(1)
    if code in _ESCAPE_LETTERS:
        return _ESCAPE_LETTERS[code]
    return chr(int(code[1:], 16) if code[0] == 'x' else int(code, 8))


def _program_option_values(words, idx):
    """Yield (value, runtime) for each option of words[idx] whose value is a program it runs."""
    if _basename(words[idx][0]) == 'git':
        yield from _git_grep_pager_values(words, idx)
        return
    names = _PROGRAM_OPTIONS.get(_basename(words[idx][0]))
    if not names:
        return
    i = idx + 1
    while i < len(words):
        value, runtime = words[i]
        if value == '--':
            return
        if _long_opt_named(value, names):
            if '=' in value:
                yield value.split('=', 1)[1], runtime
            elif i + 1 < len(words):
                i += 1
                yield words[i]
        i += 1


def _git_grep_pager_values(words, idx):
    """Yield (value, runtime) for each pager `git grep` is told to run: `-O<cmd>`, `--open-files-in-pager=<cmd>`."""
    values = [value for value, _runtime in words[idx + 1:]]
    k = _git_subcommand_index(values)
    if k is None or values[k] != 'grep':
        return
    for i in range(idx + 1 + k + 1, len(words)):
        value, runtime = words[i]
        if value == '--':
            return
        if _long_opt_named(value, ('--open-files-in-pager',)) and '=' in value:
            yield value.split('=', 1)[1], runtime
        elif value.startswith('-') and not value.startswith('--') and 'O' in value:
            rest = value[value.index('O') + 1:]
            if rest:
                yield rest, runtime


def _runs_c_string(words):
    """True iff the simple command `words` is a shell given a `-c` string, which it runs instead of its input.

    What that string does with the input is the string's own reading (_shell_layers, fed).
    """
    values = [value for value, _runtime in words]
    idx = _command_token_index(values)
    return (idx is not None and not words[idx][1] and bool(_SHELL_NAME_RE.match(_basename(values[idx])))
            and _shell_c_operand(words, idx + 1) is not None)


def _printed_to_shell(cmds, feeds, k, idx):
    """The text cmds[k], an echo or printf, prints into a pipe that a shell reads, else None.

    The pipe runs on from cmds[k] through each command a pipe feeds (a shell
    given a `-c` string runs that string, not its input); a printf's or `echo -e`'s escapes are read as the characters they stand for,
    a newline included.
    """
    words = cmds[k]
    if _basename(words[idx][0]) not in _PRINTERS:
        return None
    j = k + 1
    while j < len(cmds) and 'pipe' in feeds[j]:
        if _reads_as_shell(cmds[j]) and not _runs_c_string(cmds[j]):
            args = [value for value, _runtime in words[idx + 1:]]
            while args and _basename(words[idx][0]) == 'echo' and re.fullmatch(r'-[neE]+', args[0]):
                args = args[1:]
            text = ' '.join(args)
            if _basename(words[idx][0]) == 'printf':
                # A format may print its arguments each on a line of its own
                # (`printf '%s\n' 'git push'`) or as they stand (`'%s'`).
                text += '\n' + '\n'.join(args[1:])
            return _ESCAPE_RE.sub(_unescape, text)
        j += 1
    return None


def _may_run_git(text, runtime_re=_RUNTIME_PLACEHOLDER_RE):
    """True iff text, read as command lines, runs git or may: git-shaped.

    A git invocation or a residual command word, or a command word holding a
    run-time value (runtime_re) with no static word after it that is neither
    a git verb nor git: with nothing static after it, the subcommand is part of
    the value (`$CMD`, `$X $Y`, `$SUDO git push`).
    """
    if any(True for _ in _segment_invocations(text, nested=True)) or any(
            True for _ in _segment_residual_shapes(text, nested=True)):
        return True
    for cmd in _code_commands(text, nested=True)[0]:
        values = _values(cmd.words)
        idx = _command_token_index(values)
        if idx is None or not runtime_re.search(cmd.words[idx].raw.text):
            continue
        if idx + 1 >= len(values):
            return True
        nxt = cmd.words[idx + 1].raw.text
        if (runtime_re.search(nxt) or values[idx + 1] in _GIT_SUBCOMMANDS
                or _basename(_unquote_token(nxt)) == 'git'):
            return True
    return False


def _unlexable_may_run_git(text):
    """True iff, in text the lexer cannot read, what follows a shell's `-c` is git-shaped.

    That text is read as _may_run_git() reads a string, its quote characters
    dropped and every expansion a run-time value.
    """
    for m in _SHELL_C_SHAPE_RE.finditer(text):
        rest = re.sub(r'\A\S*', '', text[m.end():])  # past the rest of the option word
        if _may_run_git(re.sub('[\'"]', '', rest), _EXPANSION_RE):
            return True
    return False


def _runs_runtime_code(text, fed=False, depth=0):
    """True iff text may run text computed at run time as shell commands or code.

    text is a -c layer as its shell reads it (_RUNTIME for each value the outer
    shell computes; the expansions the layer's own shell performs are run-time
    too). fed: its standard input may carry run-time text, which every command
    in it inherits. A command (_command_runs_runtime_code), or one in a
    substitution or here-document it runs, that may run such text makes it
    True; so does text the lexer cannot read even with its quotes dropped.
    """
    if depth > _MAX_CODE_DEPTH:
        return True
    info = {}
    try:
        cmds, bodies = _shell_words(text, info)
    except Exception:
        try:
            cmds, bodies = _shell_words(re.sub(r'[\'"\\]', '', text), info)
        except Exception:
            return True
    if any(_command_runs_runtime_code(words, fed or bool(feeds))
           for words, feeds in zip(cmds, info['feeds'])):
        return True
    if _bare_runtime_assignment_reaches_command(cmds):
        return True
    return any(_runs_runtime_code(body, fed or body_fed, depth + 1)
               for body, body_fed in zip(bodies, info['body_fed']))


def _bare_runtime_assignment_reaches_command(cmds):
    """True iff a bare run-time assignment to an unsafe name reaches a later command.

    A bare assignment (`NODE_OPTIONS=$X` as a command of its own) sets no
    environment by itself, but its value reaches a later command through
    `set -a`, a later `export NAME`, or an already exported NAME. So once such
    an assignment to a name outside _SAFE_ENV_VARS has appeared, a later
    command that is not data-only may load that value as code.
    """
    pending = False
    for words in cmds:
        values = [value for value, _runtime in words]
        idx = _command_token_index(values)
        if idx is None:
            for value, runtime in words:
                if runtime and _ENV_ASSIGN_RE.match(value) and (
                        value.split('=', 1)[0].rstrip('+').split('[', 1)[0]
                        not in _SAFE_ENV_VARS):
                    pending = True
        elif pending:
            name = _basename(values[idx])
            if name not in _TEXT_ONLY_COMMANDS and name not in _DATA_ONLY_COMMANDS:
                return True
    return False


def _command_runs_runtime_code(words, fed):
    """True iff the simple command `words` may run run-time text as shell or code.

    fed: its standard input may carry run-time text. It may when eval comes
    before a run-time word; when a run-time value is assigned to its
    environment under a variable that can load code; when its program is named
    at run time and is fed, given a run-time word, or git-shaped; when it is
    source or `.` given a run-time file or fed; when it is one of
    _RUNTIME_ARG_COMMANDS given a run-time word or fed; and when it is a shell
    or an interpreter, or one is named among its words, that may run such text.
    echo, printf, grep and the _DATA_ONLY_COMMANDS keep their words and input
    as data. Any other command is assumed to run a run-time word of its own.
    """
    values = [value for value, _runtime in words]
    idx = _command_token_index(values)
    # eval reads every word after it as shell text again, the command word too.
    for j in range(len(values) if idx is None else idx):
        if _basename(values[j]) == 'eval' and any(runtime for _v, runtime in words[j + 1:]):
            return True
    if idx is None:  # `sudo -i`, a bare xargs: a wrapper with no command reads its input
        return fed and any(_basename(value) in _WRAPPERS for value in values)
    for v, runtime in words[:idx]:
        if runtime and _ENV_ASSIGN_RE.match(v) and (
                v.split('=', 1)[0].rstrip('+').split('[', 1)[0] not in _SAFE_ENV_VARS):
            return True
    args = words[idx + 1:]
    if words[idx][1]:
        # A wrapper (`chroot /jail $X arg`, `timeout 5 $X`) runs the run-time word.
        if any(_basename(v) in _WRAPPERS for v in values[:idx]):
            return True
        nxt = args[0][0] if args else None
        return bool(fed or nxt is None or any(runtime for _v, runtime in args)
                    or nxt in _GIT_SUBCOMMANDS or _basename(nxt) == 'git')
    name = _basename(values[idx])
    if name in _TEXT_ONLY_COMMANDS:
        return False
    if name in ('source', '.'):
        if args and args[0][0] == '--':
            args = args[1:]
        return bool(fed or (args and args[0][1]))
    if name in _RUNTIME_ARG_COMMANDS:
        return fed or any(runtime for _v, runtime in args)
    runs = _runner_runs_runtime(name, args, fed)
    if runs is not None:
        return runs
    # A launcher this module does not know: a shell or an interpreter among its words.
    if any(_runner_runs_runtime(_basename(value), words[p + 1:], fed, embedded=True)
           for p, (value, runtime) in enumerate(words) if p > idx and not runtime):
        return True
    if name in _EXEC_LAUNCHERS:
        return _launcher_runs_runtime(name, args)
    if name == 'curl':
        return _curl_runs_runtime(args)
    if name in _DATA_ONLY_COMMANDS:
        return False
    return any(runtime for _v, runtime in args)


def _launcher_runs_runtime(name, args):
    """True iff an exec-style launcher (docker/podman/kubectl) given args runs a run-time word.

    The first word that is neither an option nor a run-time value is the
    sub-command. A static data sub-command keeps the words after it as data
    (`docker push $IMAGE`); a run-time sub-command (`docker $X`), or a
    command-bearing one given a run-time word (`docker run img $X`), runs it.
    """
    for i, (value, runtime) in enumerate(args):
        if runtime:
            return True
        if value.startswith('-'):
            continue
        if value in _LAUNCHER_DATA_SUBCOMMANDS:
            return False
        return any(rt for _v, rt in args[i + 1:])
    return False


def _curl_runs_runtime(args):
    """True iff curl given args gets a run-time value that loads code.

    A run-time value of `--engine` or `-K`/`--config`, attached (`--engine=$X`,
    `-K$X`) or as the next word, is refused; a run-time operand (a URL) and a
    run-time value of any other option stay data.
    """
    for i, (value, _runtime) in enumerate(args):
        if value.startswith('--'):
            name = value.split('=', 1)[0]
            if name in _CURL_CODE_LONG_OPTS:
                if '=' in value:
                    if _RUNTIME in value:
                        return True
                elif i + 1 < len(args) and args[i + 1][1]:
                    return True
        elif value.startswith('-') and len(value) > 1:
            if any(ch in _CURL_CODE_SHORT_OPTS for ch in value[1:]):
                if _RUNTIME in value:
                    return True
                if i + 1 < len(args) and args[i + 1][1]:
                    return True
    return False


def _runner_runs_runtime(name, args, fed, embedded=False):
    """True iff the shell or interpreter `name`, given args, may run run-time text; None for any other name.

    embedded: name is one of another command's words; a shell is then known by
    name (_EMBEDDED_SHELL_RE) and its -c string is not a layer of its own.
    """
    if (_EMBEDDED_SHELL_RE if embedded else _SHELL_NAME_RE).match(name):
        return fed or _shell_args_run_runtime(args, as_command=not embedded)
    if name in _OPAQUE_INTERPRETERS:
        return fed or any(runtime for _v, runtime in args)
    for name_re, spec in _INTERPRETERS:
        if name_re.match(name):
            runtime, stdin = _interpreter_runs_runtime(spec, args)
            return runtime or (fed and stdin)
    return None


def _shell_args_run_runtime(args, as_command):
    """True iff a shell given args may run run-time text: as its script, its -c string or an option.

    A run-time word where the shell reads an option may be -c, -s or a script;
    --rcfile, --init-file, -o and -O take the next word. as_command: the
    shell is a command word, whose -c string _shell_layers() reads as a layer
    of its own; otherwise a run-time -c string runs here.
    """
    i, seen_c, seen_s = 0, False, False
    while i < len(args):
        value, runtime = args[i]
        if runtime:
            return True
        if value in ('--', '-'):
            i += 1
            break
        if value.startswith('--'):
            n = 1 if value in ('--rcfile', '--init-file') else 0
        elif len(value) > 1 and value[0] in '-+':
            seen_c = seen_c or 'c' in value[1:]
            seen_s = seen_s or 's' in value[1:]
            n = value[1:].count('o') + value[1:].count('O')
        else:
            break
        if any(runtime for _v, runtime in args[i + 1:i + 1 + n]):
            return True
        i += 1 + n
    if i >= len(args):
        return False
    if seen_c:
        return not as_command and args[i][1]
    return not seen_s and args[i][1]


def _interpreter_runs_runtime(spec, args):
    """(runtime, stdin) for an interpreter (_INTERPRETERS) given args.

    runtime: a run-time value may be code it runs: a word where it reads an
    option, the value of an option that names its program or may load code, or
    its program operand. The words after its program are the program's own.
    stdin: it reads its program from standard input.
    """
    named = False  # an option named the program: the first operand is an argument
    i = 0
    while i < len(args):
        value, runtime = args[i]
        if runtime:
            return True, False
        if value == '--':
            if named or i + 1 >= len(args):
                return False, not named and spec.stdin
            return args[i + 1][1], args[i + 1][0] in _STDIN_PATHS
        if value == '-' or not value.startswith('-'):
            return False, not named and value in _STDIN_PATHS
        option, operand, program = value, None, False
        if value.startswith('--'):
            name, eq, attached = value.partition('=')
            program = name in spec.long_program
            if program or name in spec.long_value:
                option = name
                if eq:
                    operand = (attached, False)
                elif i + 1 < len(args):
                    i += 1
                    operand = args[i]
                else:
                    operand = ('', False)
        else:
            letters = value[1:]
            for k, ch in enumerate(letters):
                if ch in spec.attached:
                    break
                if ch in spec.program or ch in spec.value:
                    option, program = '-' + ch, ch in spec.program
                    if letters[k + 1:]:
                        operand = (letters[k + 1:], False)
                    elif i + 1 < len(args):
                        i += 1
                        operand = args[i]
                    else:
                        operand = ('', False)
                    break
        i += 1
        if operand is None:
            continue
        if operand[1] and option not in spec.data:
            return True, False
        if program:
            if operand[0] in _STDIN_PATHS:
                return False, True
            named = True
            if spec.stop:
                return False, False
    return False, not named and spec.stdin


@functools.lru_cache(maxsize=32)
def _shell_layers(command_text):
    """(texts, unresolved) for command_text.

    texts: command_text, then the text of every shell `-c` string it runs, in
    order, resolved recursively up to _MAX_SHELL_DEPTH levels; a value the outer
    shell computes at run time reads as _RUNTIME_PLACEHOLDER. unresolved: the
    strings the scan cannot clear (see the section comment above).
    """
    texts, unresolved = [], []
    codes = []  # each text as its shell reads it, and whether its input is fed

    def visit(text, depth, fed=False):
        texts.append(text.replace(_RUNTIME, _RUNTIME_PLACEHOLDER))
        codes.append((text, fed))
        for kind, value, value_fed, built_by_code in _shell_c_strings(text, fed):
            if depth >= _MAX_SHELL_DEPTH:
                unresolved.append(value.replace(_RUNTIME, _RUNTIME_PLACEHOLDER))
            elif kind == 'unlexable':
                if _unlexable_may_run_git(value):
                    unresolved.append(value)
            else:
                first = len(texts)
                visit(value, depth + 1, value_fed)
                if kind == 'runtime' and (built_by_code or any(map(_may_run_git, texts[first:]))
                                          or any(_runs_runtime_code(*code) for code in codes[first:])):
                    unresolved.append(texts[first])

    try:
        visit(command_text, 0)
    except Exception:  # never let the scan cost the plain text its own checks
        shaped = _unlexable_may_run_git(command_text)
        return (command_text,), ((command_text,) if shaped else ())
    return tuple(texts), tuple(unresolved)


def iter_shell_texts(command_text):
    """Yield command_text, then the text of every shell `-c` string it runs."""
    return iter(_shell_layers(command_text)[0])


def _residual_shapes(command_text):
    """Yield (kind, text) for command words that may be git but did not resolve, in every layer."""
    texts, unresolved = _shell_layers(command_text)
    for k, text in enumerate(texts):
        yield from _segment_residual_shapes(text, nested=k > 0)
    for text in unresolved:
        yield ('unresolved_shell_string', text)


RESIDUAL_KINDS = frozenset({'obfuscated_git_token', 'dynamic_git_token',
                            'substituted_git_token', 'unresolved_shell_string'})


# ---------------------------------------------------------------------------
# GitInvocation and iter_git_invocations
# ---------------------------------------------------------------------------

GitInvocation = collections.namedtuple(
    'GitInvocation',
    ['cmd_token', 'path_qualified', 'subcommand', 'args'],
)


def iter_git_invocations(command_text):
    """Yield GitInvocation for every git invocation in command_text.

    path_qualified is True when the command word contains a '/'. The text of
    every shell `-c` string command_text runs is read the same way, after
    command_text's own commands. An invocation in such a string is read twice:
    as the shell runs the string, and as quoted text the shell is given; the
    quoted reading is not yielded again when a later text yields the same
    invocation, quotes and backslashes aside.
    """
    layers = [list(_segment_invocations(text, tagged=True, nested=k > 0))
              for k, text in enumerate(iter_shell_texts(command_text))]
    for k, layer in enumerate(layers):
        later = collections.Counter(_bare_invocation(inv) for rest in layers[k + 1:] for inv, _q in rest)
        for inv, quoted in layer:
            key = _bare_invocation(inv)
            if quoted and later[key]:
                later[key] -= 1
                continue
            yield inv


def _bare_invocation(inv):
    """inv's words with quotes and backslashes removed: what two readings of one invocation share."""
    words = [re.sub(r'[\'"\\]', '', w) for w in [inv.cmd_token, inv.subcommand or ''] + list(inv.args)]
    return tuple(w for w in words if w)


def classify_git_command(command_text):
    """Return (invocations, residuals): list(iter_git_invocations()), list(_residual_shapes()).

    The fail-closed test for a caller:

        invocations, residuals = classify_git_command(cmd)
        if residuals:
            refuse(...)          # unresolvable and git-shaped
        if not invocations:
            return               # git-free
    """
    return list(iter_git_invocations(command_text)), list(_residual_shapes(command_text))


if __name__ == '__main__':
    cmd_text = os.environ.get('CMD_INPUT', '')
    if not cmd_text:
        cmd_text = sys.stdin.read()

    if os.environ.get('CMD_RAW') == 'stdin':
        cmd_text, _nul, raw = cmd_text.partition('\0')
        try:
            from bash_context_strip import strip_non_executable_contexts as _norm
        except Exception:
            _norm = str
        layers = [cmd_text] + [_norm(text) for text in list(iter_shell_texts(raw))[1:]]
    else:
        layers = list(iter_shell_texts(cmd_text))
    results = []
    for k, text in enumerate(layers):
        for inv in _segment_invocations(text, nested=k > 0):
            results.append({
                'subcommand': inv.subcommand,
                'args': inv.args,
                'path_qualified': inv.path_qualified,
                'nested': k > 0,
            })
    print(json.dumps(results))
    sys.exit(0)
