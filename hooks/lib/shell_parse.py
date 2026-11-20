#!/usr/bin/env python3
"""The one Bash parser every hook uses to read a Bash command.

Stdlib only. Nothing here executes, expands or evaluates the text it reads, and
no public function raises: a text the parser cannot read gives a Script whose
``error`` is a ParseError(code, offset), with the commands parsed before it.
A failed parse is a fact for the caller to decide on, never a guess.

Layers, bottom up:

* ``Src``: text plus a map from every character back to its raw offset, with
  line continuations removed first as bash does.
* ``lex``: the token stream ('W', Word) / ('OP', text, off) / ('R', Redir).
  A Word keeps two readings of its pieces: ``segs`` (kind, Src, offset) and
  ``parts`` (Part, with the quote each piece was written in).
* ``parse``: the tree Script -> Pipeline -> SimpleCommand | Compound.
* views over the tree: ``walk``, ``resolve``, ``argv``, ``split_options``,
  ``executable_view``, ``write_targets``, ``git_invocations``, ``argv_split``.
"""

from __future__ import annotations

import bisect
import importlib.util
import os
import re
import sys

try:
    from . import locations
except ImportError:  # loaded outside its package (by path, or from hooks/lib): its own directory holds it
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import locations

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BARE = "bare"
SINGLE = "single"
DOUBLE = "double"
ANSI_C = "ansi_c"
LOCALE = "locale"
ESCAPED = "escaped"

MAX_DEPTH = 24
MAX_LEN = 262_144

# A subscript runs to its ], quoted text and escapes in it included (`m["a]b"]=1`).
_SUBSCRIPT = r"""\[(?:[^\]'"\\]|\\.|'[^']*'|"(?:[^"\\]|\\.)*")*\]"""
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:%s)?\+?=" % _SUBSCRIPT, re.S)
_SUBSCRIPT_START_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\[")
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FD_VAR_RE = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")

RESERVED = frozenset({
    "if", "then", "elif", "else", "fi", "while", "until", "do", "done", "for",
    "select", "case", "esac", "in", "function", "{", "}", "[[", "]]", "!",
    "time", "coproc",
})
# The reserved words (and `!`) after which the grammar puts a command word, so a
# `[[` or a command name may follow (`time [[ a ]]`, `coproc [[ a ]]` run). for,
# select, case, in and function are followed by a name; fi, done, esac, }, ]] end
# a construct.
COMMAND_PREFIX_WORDS = frozenset({"!", "{", "if", "then", "elif", "else", "while", "until",
                                  "do", "time", "coproc"})


def _digits(text):
    """True for a non-empty run of ASCII digits (bash reads no other digit)."""
    return text.isascii() and text.isdigit()


class LexError(Exception):
    """A lexical error. ``str(err)`` is its code; ``offset`` its raw offset."""

    def __init__(self, code, offset=-1):
        super().__init__(code)
        self.code = code
        self.offset = offset


class ParseError:
    __slots__ = ("code", "offset", "context")

    def __init__(self, code, offset=-1, context=""):
        self.code = code
        self.offset = offset
        self.context = context

    def __repr__(self):
        return "ParseError(%r, %r)" % (self.code, self.offset)

    def as_dict(self):
        return {"code": self.code, "offset": self.offset, "context": self.context}


# ---------------------------------------------------------------------------
# Offset-preserving text slices
# ---------------------------------------------------------------------------

class Src:
    """Text plus a per-character map back to absolute offsets in the raw input.

    Every nested context (substitution body, heredoc body, ``-c`` payload)
    carries its offsets along, so an offset found deep inside the recursion
    still names a position in the text the hook received.
    """

    __slots__ = ("text", "idx")

    def __init__(self, text, idx):
        self.text = text
        self.idx = idx

    @classmethod
    def from_raw(cls, raw):
        """Remove line continuations first, as bash does.

        `$\\<nl>(` is a real substitution and `/bi\\<nl>n/rm` a real /bin/rm.
        A backslash-newline is a continuation only where the backslash is
        itself unescaped and unquoted (or in double quotes or an unquoted
        heredoc body); in single quotes, `$'...'`, a comment or the body of a
        quoted heredoc it stays as written.
        """
        keep = _continuations(raw)
        idx = [i for i in range(len(raw)) if keep[i]]
        return cls("".join(raw[i] for i in idx), idx)

    def slice(self, a, b):
        return Src(self.text[a:b], self.idx[a:b])

    def off(self, i):
        if 0 <= i < len(self.idx):
            return self.idx[i]
        return self.idx[-1] if self.idx else -1

    def end_off(self):
        """The raw offset just past the last character."""
        return self.idx[-1] + 1 if self.idx else -1

    def __len__(self):
        return len(self.text)


def _continuations(raw):
    """keep[i] is False for the two characters of each line continuation in ``raw``."""
    n = len(raw)
    keep = [True] * n
    i = 0
    sq = dq = ansi = False
    pending = []          # heredocs opened on this line: (delim, quoted, strip_tabs)
    while i < n:
        c = raw[i]
        if sq:
            sq = c != "'"
            i += 1
            continue
        if ansi:
            if c == "\\":
                i += 2
                continue
            ansi = c != "'"
            i += 1
            continue
        if c == "\\":
            if i + 1 < n and raw[i + 1] == "\n":
                keep[i] = keep[i + 1] = False
            i += 2
            continue
        if dq:
            dq = c != '"'
            i += 1
            continue
        if c == "'":
            ansi = i > 0 and raw[i - 1] == "$" and (i < 2 or raw[i - 2] != "\\")
            sq = not ansi
        elif c == '"':
            dq = True
        elif c == "#" and (i == 0 or raw[i - 1] in " \t\n;&|()<>"):
            j = raw.find("\n", i)
            i = n if j < 0 else j
            continue
        elif raw.startswith("<<", i) and not raw.startswith("<<<", i):
            strip = raw.startswith("<<-", i)
            j = i + (3 if strip else 2)
            while j < n and raw[j] in " \t":
                j += 1
            try:
                delim, quoted, j = _read_heredoc_delim(raw, j)
            except LexError:
                return keep
            pending.append((delim, quoted, strip))
            i = j
            continue
        elif c == "\n" and pending:
            i += 1
            for delim, quoted, strip in pending:
                while i < n:
                    e = raw.find("\n", i)
                    e = n if e < 0 else e
                    line = raw[i:e]
                    if not quoted:
                        k = line.find("\\")
                        while k >= 0:
                            if k == len(line) - 1 and e < n:
                                keep[i + k] = keep[e] = False
                            k = line.find("\\", k + 2)
                    i = e + 1
                    if _heredoc_line_ends(line, delim, strip):
                        break
            pending = []
            continue
        i += 1
    return keep


def src_concat(parts, filler=" "):
    """Join Src pieces with a synthetic separator carrying offset -1."""
    chars = []
    idx = []
    for k, p in enumerate(parts):
        if k:
            for ch in filler:
                chars.append(ch)
                idx.append(-1)
        chars.extend(p.text)
        idx.extend(p.idx)
    return Src("".join(chars), idx)


# ---------------------------------------------------------------------------
# Words, parts and redirections
# ---------------------------------------------------------------------------

class Part:
    """One piece of a word, with the quote it was written in.

    kind: lit, param, cmdsub, backtick, arith, procsub_in, procsub_out, glob,
    brace, arraylit. ``text`` is the decoded value for lit (ANSI-C decoded,
    escapes and quotes removed) and the raw body for every other kind.
    ``body`` parses the nested commands of cmdsub, backtick and procsub.
    """

    __slots__ = ("kind", "text", "quote", "span", "src", "depth", "_body")

    def __init__(self, kind, text, quote, span, src=None, depth=0):
        self.kind = kind
        self.text = text
        self.quote = quote
        self.span = span
        self.src = src
        self.depth = depth
        self._body = None

    @property
    def body(self):
        if self.kind not in SUBST_KINDS:
            return None
        if self._body is None:
            self._body = parse_src(self.src, self.depth + 1)
        return self._body

    def inner(self):
        """The active parts nested in a ${...}, arithmetic or array-literal body."""
        if self.kind not in ("param", "arith", "arraylit", "glob", "brace") or self.src is None:
            return ()
        return tuple(_heredoc_parts(self.src, self.depth))

    @property
    def reexpand(self):
        if self.kind != "param":
            return False
        t = self.text
        if t == "!":
            return False  # `$!` (and `${!}`): the last background job's pid, no indirection
        return t.startswith("!") or ("@" in t and t.rsplit("@", 1)[1][:1] in REEXPAND_OPS)

    def __repr__(self):
        return "Part(%s,%r,%s)" % (self.kind, self.text, self.quote)


class Word:
    """A shell word: literal chunks plus any active expansions inside it."""

    __slots__ = ("segs", "start", "raw", "parts")

    def __init__(self, segs, start, raw, parts=()):
        self.segs = segs        # list of (kind, Src, abs_offset)
        self.start = start
        self.raw = raw          # exact Src slice covering the word
        self.parts = tuple(parts)

    def literal(self):
        """The word's static value, or None when any part is computed or ANSI-C."""
        out = []
        for kind, s, _ in self.segs:
            if kind != "lit":
                return None
            out.append(s.text)
        return "".join(out)

    def value(self):
        """The word's static value with ANSI-C decoded, or None when computed."""
        out = []
        for p in self.parts:
            if p.kind != "lit":
                return None
            out.append(p.text)
        return "".join(out)

    def static_prefix(self):
        out = []
        for p in self.parts:
            if p.kind != "lit":
                break
            out.append(p.text)
        return "".join(out)

    def quoted(self):
        return any(p.quote != BARE for p in self.parts)

    def substitutions(self):
        return [p.body for p in active_parts(self.parts) if p.body is not None]

    def content(self):
        """Offset-preserving Src of the literal content (for -c payloads)."""
        return src_concat([s for kind, s, _ in self.segs if kind == "lit"], filler="")

    @property
    def text(self):
        return self.raw.text

    @property
    def span(self):
        return (self.raw.off(0), self.raw.end_off())

    def __repr__(self):
        return "Word(%r)" % self.raw.text


class Heredoc:
    __slots__ = ("delim", "quoted", "strip_tabs", "body_src", "terminated", "depth")

    def __init__(self, delim, quoted, strip_tabs, body_src, terminated, depth=0):
        self.delim = delim
        self.quoted = quoted
        self.strip_tabs = strip_tabs
        self.body_src = body_src
        self.terminated = terminated
        self.depth = depth

    @property
    def body(self):
        return self.body_src.text

    @property
    def body_span(self):
        return (self.body_src.off(0), self.body_src.end_off())

    @property
    def expansions(self):
        """The active parts of an unquoted body; empty when the delimiter is quoted."""
        if self.quoted:
            return ()
        return tuple(_heredoc_parts(self.body_src, self.depth))


class Redir:
    """One redirection.

    op: < > >> >| <> << <<- <<< >& <& &> &>>. ``io`` is the fd written before
    the operator as text (legacy), ``fd`` the same as int, ``fd_var`` the NAME
    of a `{NAME}>` form. ``heredoc`` is (delim, quoted, body Src) for << and <<-
    (legacy); ``hd`` the Heredoc object.
    """

    __slots__ = ("op", "io", "target", "off", "heredoc", "hd", "fd_var", "end")

    def __init__(self, op, io, off):
        self.op = op
        self.io = io
        self.off = off
        self.target = None
        self.heredoc = None
        self.hd = None
        self.fd_var = None
        self.end = off

    @property
    def fd(self):
        if self.io is not None and _digits(self.io):
            return int(self.io)
        if self.op in ("<", "<<", "<<-", "<<<", "<&", "<>"):
            return 0 if self.fd_var is None else None
        if self.op in BOTH_STREAMS_OPS:
            return None
        return 1 if self.fd_var is None else None

    @property
    def close(self):
        return self.op in DUP_OPS and self.target is not None and self.target.literal() == "-"

    @property
    def dup(self):
        if self.op in DUP_OPS and self.target is not None:
            lit = self.target.literal()
            if lit is not None and lit.endswith("-") and _digits(lit[:-1]):
                lit = lit[:-1]          # N>&M- moves M onto N
            if lit is not None and _digits(lit):
                return int(lit)
        return None

    @property
    def span(self):
        return (self.off, self.end)

    def writes(self):
        """True when this redirection opens a file for writing."""
        if self.op in WRITE_REDIRECT_OPS:
            return True
        return self.op == ">&" and self.dup is None and not self.close

    def __repr__(self):
        return "Redir(%s%s %r)" % (self.io or "", self.op,
                                   self.target.text if self.target else self.heredoc and self.heredoc[0])


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

_OP_CHARS = ";&|()"
_OPS = (";;&", ";;", ";&", "&&", "||", "|&", ";", "&", "|", "(", ")")
_REDIR_OPS = ("<<-", "<<<", "<<", ">>", "<>", ">&", "<&", ">|", ">", "<")
BOTH_STREAMS_OPS = ("&>>", "&>")  # redirect stdout and stderr together (they take no fd)
REDIRECT_OPS = BOTH_STREAMS_OPS + _REDIR_OPS  # every redirection operator, longest first
OUTPUT_REDIRECT_OPS = (">", ">>", ">|") + BOTH_STREAMS_OPS  # send output to their target
WRITE_REDIRECT_OPS = OUTPUT_REDIRECT_OPS + ("<>",)  # open their target for writing (<> read-write)
INPUT_REDIRECT_OPS = ("<", "<>")  # open their target for reading (<> read-write)
HEREDOC_OPS = ("<<", "<<-", "<<<")  # feed a here-document or a here-string
DUP_OPS = (">&", "<&")  # duplicate a file descriptor (or close one, with `-`)
AND_OR_OPS = ("&&", "||")  # run what follows depending on what precedes
STATIC_PART_KINDS = ("lit", "glob")  # word parts the shell does not compute (a glob only expands to names)
BODY_PART_KINDS = frozenset({"sub", "arith", "procsub"})  # word parts whose body the shell runs
DYNAMIC_PART_KINDS = BODY_PART_KINDS | {"param"}  # word parts the shell computes
PIPE_OPS = ("|", "|&")  # the operators that pipe one stage into the next
OPTION_SIGNS = ("-", "+")  # what starts an option word: -x switches on, +x off
OPTION_ENDS = ("--", "-")  # the words that end the options: `--`, and `-` (standard input)
CD_OPTIONS = ("-L", "-P", "-e", "-@", "--")  # bash: cd [-L|[-P [-e]] [-@]] [--] [dir]
CD_TARGET_BUILTINS = ("cd", "pushd")  # move to the directory their operand names (popd returns to one listed)
CWD_BUILTINS = ("cd", "pushd", "popd")  # change the working directory of what follows
LOOP_VAR_KINDS = ("for", "select")  # Compound kinds whose header binds a variable to each listed word
DEFINER_KINDS = ("function", "coproc")  # Compound kinds whose body runs later or apart, not in line
# the characters that open a quoted string: runtime_guard/pathmatch.py's, loaded by path (that leaf
# imports only the standard library; importing the runtime_guard package would load the guard)
_PATHMATCH = importlib.util.spec_from_file_location(
    "_shell_parse_pathmatch", os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime_guard", "pathmatch.py"))
_pathmatch = importlib.util.module_from_spec(_PATHMATCH)
_PATHMATCH.loader.exec_module(_pathmatch)
QUOTE_CHARS = _pathmatch.QUOTE_CHARS
COMMAND_OPTS = ("-c", "--command")  # su, runuser, flock, script: the option whose value is shell code
ENV_SPLIT_OPTS = ("-S", "--split-string")  # env: the option whose value env splits into the command line
GIT_RESTORE_SOURCE_OPTS = ("-s", "--source")  # git restore: the tree the files are restored from
COMMAND_LOOKUP_OPTS = ("-v", "-V")  # `command -v NAME` / `-V NAME` describe NAME, run nothing
ITEM_RUNNERS = ("xargs", "parallel")  # run their command once per input item, operands built at run time
REEXPAND_OPS = ("P", "E", "A")  # ${x@P} ${x@E} ${x@A}: the value is read again as shell text
PARALLEL_SEPARATORS = (":::", ":::+", "::::", "::::+")  # GNU parallel: the input sources after the command
SUBST_OPENERS = ("$(", "<(", ">(")  # open a command or process substitution (so does a lone backquote)
# The common POSIX-family shells, by the narrow readings that name them (SHELLS is every
# shell the parser knows), and with `source` and `.` the commands that run a script file
# operand as shell text in this or a new shell.
COMMON_SHELLS = ("bash", "sh", "dash", "zsh", "ksh")
SOURCE_BUILTINS = ("source", ".")  # run a script file in this shell
SCRIPT_RUNNERS = COMMON_SHELLS + SOURCE_BUILTINS
SHELL_VALUE_OPTS = ("-o", "+o", "-O", "+O", "--rcfile", "--init-file")  # a shell's options that take a value
DECLARATION_BUILTINS = ("export", "declare", "typeset", "local", "readonly")  # assign their NAME=value words
LOOKUP_BUILTINS = ("command", "builtin")  # run the next word as a builtin or a program, skipping functions
PRINTERS = ("echo", "printf")  # print their arguments and run nothing
FIND_EXEC_IN_MATCH_DIR = ("-execdir", "-okdir")  # find actions that run in each match's directory
MOVE_MECHANISMS = ("mv", "git-mv")  # WriteTarget mechanisms of a move: its sources follow as <mechanism>-source
NODE_NAMES = ("node", "nodejs")  # the names node is installed under (Debian: nodejs)
RUNUSER_USER_OPTS = ("-u", "--user")  # runuser: the option naming the user COMMAND runs as
SHELL_FILE_OPTS = ("--rcfile", "--init-file")  # bash: the options that read a startup file named by the next word
HERE_DOCUMENT_OPS = ("<<", "<<-")  # the redirections that open a here-document
LITERAL_PART_KINDS = ("lit", "glob", "brace")  # word parts whose text is written in the command
CMDSUB_KINDS = ("cmdsub", "backtick")  # word parts that run a command and splice its output
SUBST_KINDS = CMDSUB_KINDS + ("procsub_in", "procsub_out")  # word parts whose body runs as a command
GIT_CONFIG_OPTS = ("-c", "--config-env")  # git: the global options that set a configuration value
SEQUENCE_OPS = ("", ";", "&&", "||", "\n")  # list operators that run the next pipeline after this one, in the shell
# Package runners (pnpx is `pnpm dlx`) and the package-manager subcommands that run another
# command: their argv after `--`, and npm's `-c` / `--call` string, is a nested invocation.
NODE_PKG_MANAGERS = frozenset({"yarn", "npm", "pnpm", "bun"})  # the node package managers
PM_EXEC_RUNNERS = frozenset({"npx", "pnpx", "bunx"})
PM_EXEC_SUBCMDS = frozenset({"exec", "x", "dlx"})
PM_CALL_OPTS = ("-c", "--call")  # npm exec / npx: the option whose value is a shell command
# node's long options that take a value (`node --help`, v22: the options shown with `=...`;
# node reads the value attached or as the next word). Read by the git classifier and the
# runtime guard.
NODE_VALUE_OPTIONS = frozenset({
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
# Environment variables whose VALUE is executed by the command that follows
# them. An assignment prefix normally never executes -- `A=(/bin/rm) echo x` is
# a fixture-pinned safe row -- but these named vectors are documented command
# hooks, so `GIT_EXTERNAL_DIFF=/bin/rm git diff` runs the removal. Read by the
# removal analyzer and the git classifier.
EXEC_ASSIGNMENT_VARS = frozenset({
    "GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_SSH", "GIT_SSH_COMMAND",
    "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_ASKPASS", "GIT_MERGE_TOOL",
    "GIT_DIFF_TOOL", "GIT_TEXTCONV", "GIT_PROXY_COMMAND", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "PAGER", "MANPAGER", "LESSOPEN", "LESSCLOSE", "LESSEDIT", "EDITOR",
    "VISUAL", "FCEDIT", "BROWSER", "SSH_ASKPASS", "SUDO_EDITOR", "SUDO_ASKPASS",
    "DIFFPROG", "MERGE", "PERL5OPT", "PYTHONSTARTUP", "BASH_ENV", "ENV",
    "SHELL", "RSYNC_RSH", "CVS_RSH", "SVN_SSH", "HGEDITOR", "P4EDITOR",
    "SYSTEMD_PAGER", "SYSTEMD_EDITOR", "DEBUGINFOD_URLS", "LD_PRELOAD",
})


def _match_pair(t, i, opener, closer):
    """Index just past the balanced closer starting at ``t[i] == opener``, or -1.

    Inside the pair, quotes ('...', "...", $'...'), comments and heredoc
    bodies hold no closer, and for `(` the `)` that ends a case pattern does
    not close it.
    """
    depth = 0
    n = len(t)
    pending = []
    case = []           # per open case: "word" (before `in`), "pattern" or "body"
    while i < n:
        c = t[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            j = t.find("'", i + 1)
            if j < 0:
                return -1
            i = j + 1
            continue
        if c == '"':
            i += 1
            while i < n and t[i] != '"':
                i += 2 if t[i] == "\\" else 1
            if i >= n:
                return -1
            i += 1
            continue
        if c == "$" and i + 1 < n and t[i + 1] == "'":
            j = _find_ansi_end(t, i + 2)
            if j < 0:
                return -1
            i = j + 1
            continue
        if depth and opener == "(":
            if c == "#" and t[i - 1] in " \t\n;&|()":
                j = t.find("\n", i)
                i = n if j < 0 else j
                continue
            if t.startswith("<<", i) and not t.startswith("<<<", i):
                strip = t.startswith("<<-", i)
                j = i + (3 if strip else 2)
                while j < n and t[j] in " \t":
                    j += 1
                try:
                    delim, _q, j = _read_heredoc_delim(t, j)
                except LexError:
                    return -1
                pending.append((delim, strip))
                i = j
                continue
            if c == "\n" and pending:
                i += 1
                closing = False
                for delim, strip in pending:
                    while i < n:
                        e = t.find("\n", i)
                        e = n if e < 0 else e
                        line = t[i:e]
                        bare = line.lstrip("\t") if strip else line
                        if bare.startswith(delim) and bare[len(delim):].lstrip(" \t").startswith(")"):
                            # bash ends the body here and lets the `)` close the substitution
                            i += len(line) - len(bare) + len(delim)
                            closing = True
                            break
                        i = e + 1
                        if _heredoc_line_ends(line, delim, strip):
                            break
                    if closing:
                        break
                pending = []
                continue
            if (c.isalpha() and t[i - 1] in " \t\n;&|(") or c == "e":
                m = re.match(r"(case|in|esac)(?=[\s;&|()]|$)", t[i:])
                if m and (t[i - 1] in " \t\n;&|(" or i == 0):
                    word = m.group(1)
                    if word == "case":
                        case.append("word")
                    elif word == "in" and case and case[-1] == "word":
                        case[-1] = "pattern"
                    elif word == "esac" and case and case[-1] in ("pattern", "body"):
                        case.pop()
                    i += len(word)
                    continue
            if case and case[-1] == "body" and t.startswith(";;", i):
                case[-1] = "pattern"
                i += 3 if t.startswith(";;&", i) else 2
                continue
            if case and case[-1] == "body" and t.startswith(";&", i):
                case[-1] = "pattern"
                i += 2
                continue
            if case and case[-1] == "pattern":
                if c == ")":
                    case[-1] = "body"
                    i += 1
                    continue
                if c == "(":
                    i += 1
                    continue
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _arith_end(t, i):
    """For `((` at ``t[i]``: the index past the closing `))` when the text is
    arithmetic, or -1 when bash reads it as a nested subshell (`((a);(b))`)."""
    end = _match_pair(t, i, "(", ")")
    if end < 2 or t[end - 2] != ")":
        return -1
    return end if _match_pair(t, i + 1, "(", ")") == end - 1 else -1


def _find_ansi_end(t, i):
    n = len(t)
    while i < n:
        if t[i] == "\\":
            i += 2
            continue
        if t[i] == "'":
            return i
        i += 1
    return -1


def _lex_dollar(src, i, segs):
    """Lex a ``$``-introduced construct at ``i``; append one seg, return next i."""
    t = src.text
    n = len(t)
    off = src.off(i)
    if i + 1 >= n:
        segs.append(("lit", src.slice(i, i + 1), off))
        return i + 1
    nxt = t[i + 1]
    if nxt == "(":
        end = _match_pair(t, i + 1, "(", ")")
        if end < 0:
            raise LexError("cmdsub", off)
        if i + 2 < n and t[i + 2] == "(" and _arith_end(t, i + 1) == end:
            segs.append(("arith", src.slice(i + 3, end - 2), off))
        else:
            segs.append(("sub", src.slice(i + 2, end - 1), off))
        return end
    if nxt == "[":
        end = _match_pair(t, i + 1, "[", "]")
        if end < 0:
            raise LexError("arith_bracket", off)
        segs.append(("arith", src.slice(i + 2, end - 1), off))
        return end
    if nxt == "{":
        end = _match_pair(t, i + 1, "{", "}")
        if end < 0:
            raise LexError("param", off)
        segs.append(("param", src.slice(i + 2, end - 1), off))
        return end
    j = i + 1
    if t[j].isalpha() or t[j] == "_":
        while j < n and (t[j].isalnum() or t[j] == "_"):
            j += 1
    elif _digits(t[j]):
        j += 1
    elif t[j] in "@*#?-$!0":
        j += 1
    else:
        segs.append(("lit", src.slice(i, i + 1), off))
        return i + 1
    segs.append(("param", src.slice(i + 1, j), off))
    return j


def _lex_backtick(src, i, segs):
    t = src.text
    n = len(t)
    end = i + 1
    found = -1
    while end < n:
        if t[end] == "\\":
            end += 2
            continue
        if t[end] == "`":
            found = end
            break
        end += 1
    if found < 0:
        raise LexError("backtick", src.off(i))
    # Bash strips one level of backslash escaping inside backticks.
    chars = []
    idx = []
    k = i + 1
    while k < found:
        if t[k] == "\\" and k + 1 < found and t[k + 1] in "`$\\":
            chars.append(t[k + 1])
            idx.append(src.idx[k + 1])
            k += 2
            continue
        chars.append(t[k])
        idx.append(src.idx[k])
        k += 1
    segs.append(("sub", Src("".join(chars), idx), src.off(i)))
    return found + 1


def _span(src, a, b):
    return (src.off(a), src.off(b - 1) + 1 if b > a else src.off(a))


def _open_subscript(raw):
    """True when ``raw`` is NAME[ followed by an unclosed subscript (quotes and $( ) skipped)."""
    m = _SUBSCRIPT_START_RE.match(raw)
    if not m:
        return False
    level, j = 1, m.end()
    while j < len(raw):
        c = raw[j]
        if c == "\\":
            j += 1
        elif c in QUOTE_CHARS:
            k = raw.find(c, j + 1)
            j = len(raw) if k < 0 else k
        elif raw.startswith("$(", j):
            k = _match_pair(raw, j + 1, "(", ")")
            j = len(raw) if k < 0 else k - 1
        elif c == "[":
            level += 1
        elif c == "]":
            level -= 1
        j += 1
    return level > 0


def _lex_word(src, i, depth=0, assign=False):
    """One word from ``src`` at ``i``. ``assign``: the word stands where an assignment may
    (before a command's name), so a NAME[ subscript runs to its ] across blanks and
    operators, as bash reads `m[a b]=c`."""
    t = src.text
    n = len(t)
    start = i
    segs = []
    parts = []
    lit_chars = []
    lit_idx = []
    run = {"chars": [], "idx": [], "q": None}

    def pflush():
        if run["chars"]:
            idx = run["idx"]
            parts.append(Part("lit", "".join(run["chars"]), run["q"], (idx[0], idx[-1] + 1)))
            run["chars"] = []
            run["idx"] = []
        run["q"] = None

    def flush():
        pflush()
        if lit_chars:
            segs.append(("lit", Src("".join(lit_chars), list(lit_idx)), -1))
            del lit_chars[:]
            del lit_idx[:]

    def keep(k, q=BARE):
        lit_chars.append(t[k])
        lit_idx.append(src.idx[k])
        if run["q"] is not None and run["q"] != q:
            pflush()
        run["q"] = q
        run["chars"].append(t[k])
        run["idx"].append(src.idx[k])

    def add_seg(before, q, kind_hint=None):
        # Mirror the seg just appended by a sub-lexer into one Part.
        kind, s, off = segs[-1]
        span = (off if off >= 0 else s.off(0), src.off(i_after[0] - 1) + 1)
        if kind == "lit":
            parts.append(Part("lit", s.text, q, span))
            return
        pkind = {"sub": kind_hint or "cmdsub", "arith": "arith", "param": "param"}.get(kind, kind)
        parts.append(Part(pkind, s.text, q, span, s, depth))

    i_after = [i]
    while i < n:
        c = t[i]
        if c in " \t\n" or c in _OP_CHARS:
            if assign and _open_subscript(t[start:i]):
                keep(i)
                i += 1
                continue
            if c == "(" and lit_chars and _ASSIGN_RE.match("".join(lit_chars)):
                # NAME=( ... ) array assignment: the parens belong to the word.
                end = _match_pair(t, i, "(", ")")
                if end < 0:
                    raise LexError("array_assign", src.off(i))
                flush()
                segs.append(("arraylit", src.slice(i + 1, end - 1), src.off(i)))
                parts.append(Part("arraylit", t[i + 1:end - 1], BARE, _span(src, i, end),
                                  src.slice(i + 1, end - 1), depth))
                i = end
                continue
            if c == "(" and (
                    (lit_chars and lit_chars[-1] in "!@+")
                    or (not lit_chars and segs and segs[-1][0] == "glob"
                        and segs[-1][1].text in ("*", "?"))):
                # extglob pattern: ?(x) *(x) +(x) @(x) !(x)
                end = _match_pair(t, i, "(", ")")
                if end < 0:
                    raise LexError("extglob", src.off(i))
                if lit_chars:
                    del lit_chars[-1]
                    del lit_idx[-1]
                    if run["chars"]:
                        run["chars"].pop()
                        run["idx"].pop()
                else:
                    segs.pop()
                    if parts and parts[-1].kind == "glob":
                        parts.pop()
                flush()
                segs.append(("glob", src.slice(i - 1, end), src.off(i - 1)))
                parts.append(Part("glob", t[i - 1:end], BARE, _span(src, i - 1, end),
                                  src.slice(i - 1, end), depth))
                i = end
                continue
            break
        if c in "<>":
            if i + 1 < n and t[i + 1] == "(":
                end = _match_pair(t, i + 1, "(", ")")
                if end < 0:
                    raise LexError("procsub", src.off(i))
                flush()
                body = src.slice(i + 2, end - 1)
                segs.append(("procsub", body, src.off(i)))
                parts.append(Part("procsub_in" if c == "<" else "procsub_out", body.text, BARE,
                                  _span(src, i, end), body, depth))
                i = end
                continue
            break
        if c == "\\":
            if i + 1 < n:
                keep(i + 1, ESCAPED)
                i += 2
                continue
            keep(i)
            i += 1
            continue
        if c == "'":
            j = t.find("'", i + 1)
            if j < 0:
                raise LexError("single_quote", src.off(i))
            if j == i + 1:
                pflush()
                parts.append(Part("lit", "", SINGLE, _span(src, i, j + 1)))
            for k in range(i + 1, j):
                keep(k, SINGLE)
            pflush()
            i = j + 1
            continue
        if c == '"':
            q = DOUBLE
            if i > start and t[i - 1] == "$" and (not lit_chars or True) and _locale_mark(t, i, start):
                q = LOCALE
            open_at = i
            i += 1
            closed = False
            had = False
            while i < n:
                ch = t[i]
                if ch == '"':
                    closed = True
                    i += 1
                    break
                had = True
                if ch == "\\" and i + 1 < n and t[i + 1] in '"\\$`':
                    keep(i + 1, q)
                    i += 2
                    continue
                if ch == "$" and i + 1 < n:
                    flush()
                    i_after[0] = _lex_dollar(src, i, segs)
                    i = i_after[0]
                    add_seg(None, q)
                    continue
                if ch == "`":
                    flush()
                    i_after[0] = _lex_backtick(src, i, segs)
                    i = i_after[0]
                    add_seg(None, q, "backtick")
                    continue
                keep(i, q)
                i += 1
            if not closed:
                raise LexError("double_quote", src.off(open_at))
            if not had:
                pflush()
                parts.append(Part("lit", "", q, _span(src, open_at, i)))
            pflush()
            continue
        if c == "$":
            if i + 1 < n and t[i + 1] == "'":
                j = _find_ansi_end(t, i + 2)
                if j < 0:
                    raise LexError("ansi_quote", src.off(i))
                flush()
                segs.append(("ansi", src.slice(i + 2, j), src.off(i)))
                parts.append(Part("lit", ansi_decode(t[i + 2:j]), ANSI_C, _span(src, i, j + 1)))
                i = j + 1
                continue
            if i + 1 < n and t[i + 1] == '"':
                i += 1
                continue
            flush()
            i_after[0] = _lex_dollar(src, i, segs)
            i = i_after[0]
            add_seg(None, BARE)
            continue
        if c == "`":
            flush()
            i_after[0] = _lex_backtick(src, i, segs)
            i = i_after[0]
            add_seg(None, BARE, "backtick")
            continue
        if c in "*?":
            flush()
            segs.append(("glob", src.slice(i, i + 1), src.off(i)))
            parts.append(Part("glob", c, BARE, _span(src, i, i + 1)))
            i += 1
            continue
        if c == "[":
            j = t.find("]", i + 1)
            if j > 0 and not any(x in " \t\n" + _OP_CHARS + "$`'\"" for x in t[i:j]):
                flush()
                segs.append(("glob", src.slice(i, j + 1), src.off(i)))
                parts.append(Part("glob", t[i:j + 1], BARE, _span(src, i, j + 1)))
                i = j + 1
                continue
            keep(i)
            i += 1
            continue
        if c == "{":
            end = _match_pair(t, i, "{", "}")
            if end > 0:
                body = t[i + 1:end - 1]
                if ("," in body or ".." in body) and not any(ch in " \t\n;&|<>()" for ch in body):
                    flush()
                    segs.append(("brace", src.slice(i, end), src.off(i)))
                    parts.append(Part("brace", t[i:end], BARE, _span(src, i, end),
                                      src.slice(i, end), depth))
                    i = end
                    continue
            keep(i)
            i += 1
            continue
        keep(i)
        i += 1

    if assign and _open_subscript(t[start:i]):
        raise LexError("unterminated_subscript", src.off(start))  # bash: looking for matching `]'
    flush()
    return Word(segs, src.off(start), src.slice(start, i), parts), i


def _locale_mark(t, i, start):
    """True when the `"` at ``i`` opens a `$"..."` string (the `$` unescaped)."""
    k = i - 1
    bs = 0
    j = k - 1
    while j >= start and t[j] == "\\":
        bs += 1
        j -= 1
    return bs % 2 == 0


def _read_heredoc_delim(t, j, off=-1):
    n = len(t)
    quoted = False
    parts = []
    while j < n and t[j] not in " \t\n;&|<>()":
        ch = t[j]
        if ch == "'":
            k = t.find("'", j + 1)
            if k < 0:
                raise LexError("heredoc_delim", off)
            quoted = True
            parts.append(t[j + 1:k])
            j = k + 1
            continue
        if ch == '"':
            k = j + 1
            piece = []
            while k < n and t[k] != '"':
                if t[k] == "\\" and k + 1 < n and t[k + 1] in '$`"\\':
                    piece.append(t[k + 1])
                    k += 2
                    continue
                piece.append(t[k])
                k += 1
            if k >= n:
                raise LexError("heredoc_delim", off)
            quoted = True
            parts.append("".join(piece))
            j = k + 1
            continue
        if ch == "\\":
            quoted = True
            parts.append(t[j + 1:j + 2])
            j += 2
            continue
        parts.append(ch)
        j += 1
    return "".join(parts), quoted, j


def _strip_tabs(body):
    """``body`` with each line's leading tabs removed, offsets kept (for <<-)."""
    keep = []
    at_start = True
    for k, ch in enumerate(body.text):
        if at_start and ch == "\t":
            continue
        at_start = ch == "\n"
        keep.append(k)
    return Src("".join(body.text[k] for k in keep), [body.idx[k] for k in keep])


def _heredoc_line_ends(line, delim, strip_tabs):
    if strip_tabs:
        line = line.lstrip("\t")
    return line == delim


def _word_start(t, i):
    """True when position ``i`` begins a word (so a `#` there starts a comment)."""
    return i == 0 or t[i - 1] in " \t\n;&|()<>"


def lex(src, depth=0):
    """Tokenize ``src`` into ('W', Word) / ('OP', text, off) / ('R', Redir).

    Raises LexError on unreadable text; ``_lex_into`` keeps the tokens read
    before the error.
    """
    toks = []
    _lex_into(src, toks, depth)
    return toks


def _lex_into(src, toks, depth=0, comments=None):
    t = src.text
    n = len(t)
    pending_heredocs = []
    i = 0
    while i < n:
        c = t[i]
        if c in " \t":
            i += 1
            continue
        if c == "#" and _word_start(t, i):
            j = t.find("\n", i)
            j = n if j < 0 else j
            if comments is not None:
                comments.append((src.off(i), src.off(j - 1) + 1))
            i = j
            continue
        if c == "\n":
            toks.append(("OP", "\n", src.off(i)))
            i += 1
            if pending_heredocs:
                for redir, delim, quoted in pending_heredocs:
                    strip_tabs = redir.op == "<<-"
                    body_start = i
                    terminated = False
                    while i <= n:
                        line_end = t.find("\n", i)
                        if line_end < 0:
                            line_end = n
                        if _heredoc_line_ends(t[i:line_end], delim, strip_tabs):
                            body = _strip_tabs(src.slice(body_start, i)) if strip_tabs else \
                                src.slice(body_start, i)
                            redir.heredoc = (delim, quoted, body)
                            redir.hd = Heredoc(delim, quoted, strip_tabs, body, True, depth)
                            i = min(line_end + 1, n)
                            terminated = True
                            break
                        if line_end >= n:
                            i = n
                            break
                        i = line_end + 1
                    if not terminated:
                        body = src.slice(body_start, n)
                        redir.hd = Heredoc(delim, quoted, strip_tabs, body, False, depth)
                        raise LexError("unterminated_heredoc", redir.off)
                pending_heredocs = []
            continue
        if t.startswith("&>(", i):
            raise LexError("unexpected_token", src.off(i))
        if c == "&" and i + 1 < n and t[i + 1] == ">" and not (i + 2 < n and t[i + 2] == "("):
            op = "&>>" if t.startswith("&>>", i) else "&>"
            r = Redir(op, None, src.off(i))
            i += len(op)
            while i < n and t[i] in " \t":
                i += 1
            if i >= n or t[i] in "\n;&|()":
                raise LexError("redirect_missing_target", r.off)
            r.target, i = _lex_word(src, i, depth)
            r.end = r.target.raw.end_off()
            toks.append(("R", r))
            continue
        if c == "(" and t.startswith("((", i) and (
                not toks or toks[-1][0] == "OP"
                or (toks[-1][0] == "W" and toks[-1][1].literal() == "for")):
            end = _arith_end(t, i)
            if end > 0:
                toks.append(("OP", "(", src.off(i)))
                toks.append(("OP", "(", src.off(i + 1)))
                body = _expansion_word(src.slice(i + 2, end - 2), depth)
                if body is not None:
                    toks.append(("W", body))
                toks.append(("OP", ")", src.off(end - 2)))
                toks.append(("OP", ")", src.off(end - 1)))
                i = end
                continue
        if c in "();&|":
            for op in _OPS:
                if t.startswith(op, i):
                    toks.append(("OP", op, src.off(i)))
                    i += len(op)
                    break
            continue
        if c in "<>" and not (i + 1 < n and t[i + 1] == "("):
            io = None
            fd_var = None
            if toks and toks[-1][0] == "W":
                prev = toks[-1][1]
                plit = prev.literal()
                adjacent = prev.raw.idx and prev.raw.idx[-1] + 1 == src.idx[i]
                if plit is not None and adjacent and _digits(plit):
                    io = plit
                    toks.pop()
                elif plit is not None and adjacent and not prev.quoted() and _FD_VAR_RE.match(plit):
                    fd_var = _FD_VAR_RE.match(plit).group(1)
                    toks.pop()
            op = next(o for o in _REDIR_OPS if t.startswith(o, i))
            r = Redir(op, io, src.off(i))
            r.fd_var = fd_var
            i += len(op)
            if op in HERE_DOCUMENT_OPS:
                while i < n and t[i] in " \t":
                    i += 1
                delim, quoted, i = _read_heredoc_delim(t, i, r.off)
                r.end = src.off(i - 1) + 1
                pending_heredocs.append((r, delim, quoted))
            else:
                while i < n and t[i] in " \t":
                    i += 1
                if i >= n or t[i] in "\n;&|()#":
                    raise LexError("redirect_missing_target", r.off)
                r.target, i = _lex_word(src, i, depth)
                r.end = r.target.raw.end_off()
            toks.append(("R", r))
            continue
        w, i = _lex_word(src, i, depth, _assignment_position(toks))
        if not w.segs and not w.parts:
            i += 1
            continue
        if not w.segs:
            w.segs = [("lit", w.raw.slice(0, 0), w.start)]
        toks.append(("W", w))
    if pending_heredocs:
        raise LexError("unterminated_heredoc", pending_heredocs[0][0].off)
    return toks


def _assignment_position(toks):
    """True when a word lexed after ``toks`` stands where bash accepts an assignment: first in
    a command (after an operator, a reserved prefix word or an assignment; redirections aside)."""
    for tok in reversed(toks):
        if tok[0] == "R":
            continue
        if tok[0] == "OP":
            return True
        text = tok[1].raw.text
        return bool(_ASSIGN_RE.match(text)) or text in COMMAND_PREFIX_WORDS
    return True


def _expansion_word(body, depth=0):
    """A Word over ``body`` (arithmetic text) whose $-constructs and backticks are its
    active parts; quotes in it are text. None for an empty body."""
    t = body.text
    if not t.strip():
        return None
    segs, parts = [], []
    i = lit = 0
    n = len(t)

    def flush(upto):
        if upto > lit:
            piece = body.slice(lit, upto)
            segs.append(("lit", piece, -1))
            parts.append(Part("lit", piece.text, BARE, (piece.off(0), piece.end_off())))

    while i < n:
        c = t[i]
        if c == "\\":
            i += 2
            continue
        if c in "$`":
            mark = len(segs)
            try:
                j = _lex_dollar(body, i, segs) if c == "$" else _lex_backtick(body, i, segs)
            except LexError:
                i += 1
                continue
            seg = segs.pop(mark)
            flush(i)
            segs.append(seg)
            kind, sub, off = seg
            pkind = "backtick" if c == "`" else {"sub": "cmdsub"}.get(kind, kind)
            parts.append(Part(pkind, sub.text, BARE, (off, body.off(j - 1) + 1), sub, depth))
            i = lit = j
            continue
        i += 1
    flush(n)
    return Word(segs, body.off(0), body, parts)


def _heredoc_parts(body_src, depth=0):
    """The $-constructs and backticks of an unquoted heredoc body.

    Quotes are literal in a heredoc body; only `\\`, `$` and backticks act.
    """
    t = body_src.text
    n = len(t)
    out = []
    i = 0
    while i < n:
        c = t[i]
        if c == "\\":
            i += 2
            continue
        if c in "$`":
            segs = []
            try:
                j = _lex_dollar(body_src, i, segs) if c == "$" else _lex_backtick(body_src, i, segs)
            except LexError:
                i += 1
                continue
            kind, s, off = segs[-1]
            if kind != "lit":
                pkind = "backtick" if c == "`" else {"sub": "cmdsub"}.get(kind, kind)
                out.append(Part(pkind, s.text, DOUBLE, (off, body_src.off(j - 1) + 1), s, depth))
            i = j
            continue
        i += 1
    return out


# ---------------------------------------------------------------------------
# ANSI-C quoting
# ---------------------------------------------------------------------------

_ANSI_SIMPLE = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f",
                "n": "\n", "r": "\r", "t": "\t", "v": "\v", "\\": "\\",
                "'": "'", '"': '"', "?": "?"}


def ansi_decode(text):
    """Decode the escapes bash applies inside $'...'. Never executes anything.

    An escape bash does not know keeps its backslash (`\\m` stays `\\m`), and
    a NUL ends the string, as bash's C strings end there.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        nxt = text[i + 1]
        ch = None
        if nxt in _ANSI_SIMPLE:
            ch, i = _ANSI_SIMPLE[nxt], i + 2
        elif nxt in "xuU":
            width = {"x": 2, "u": 4, "U": 8}[nxt]
            j = k = i + 2
            while k < n and k < j + width and text[k] in "0123456789abcdefABCDEF":
                k += 1
            if k > j:
                try:
                    ch = chr(int(text[j:k], 16))
                except (ValueError, OverflowError):
                    ch = "\ufffd"
                i = k
        elif nxt in "01234567":
            j = k = i + 1
            while k < n and k < j + 3 and text[k] in "01234567":
                k += 1
            ch, i = chr(int(text[j:k], 8) & 0xFF), k
        elif nxt == "c" and i + 2 < n:
            ch, i = chr(ord(text[i + 2]) & 0x1F), i + 3
        if ch is None:
            out.append(c + nxt)
            i += 2
            continue
        if ch == "\x00":
            break
        out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------------------
# Option splitting
# ---------------------------------------------------------------------------

def _spec(bools=(), vals=(), nargs=None, attached=()):
    """An option spec: flags, options taking a value, and (``attached``) options whose
    value is optional and only ever attached (`-m/path`, `--mount=/path`), nargs 0."""
    return {"bool": set(bools), "val": set(vals) | set(attached),
            "nargs": {**dict(nargs or {}), **{o: 0 for o in attached}}}


def _resolve_long(name, spec):
    if name in spec["bool"] or name in spec["val"]:
        return name
    cands = [o for o in (spec["bool"] | spec["val"])
             if o.startswith("--") and o.startswith(name)]
    if len(cands) == 1:
        return cands[0]
    return None


def split_opts(ws, spec, start=0):
    """Return (first_operand_index, error). Unknown options are an error."""
    i = start
    n = len(ws)
    while i < n:
        lit = ws[i].literal()
        if lit is None:
            return i, None
        if lit == "--":
            return i + 1, None
        if lit in OPTION_SIGNS:
            return i, None
        if len(lit) > 1 and lit[:2] == "--":
            name = lit.split("=", 1)[0]
            res = _resolve_long(name, spec)
            if res is None:
                return i, "unknown_option:" + name
            if "=" in lit:
                i += 1
                continue
            i += 1 + (spec["nargs"].get(res, 1) if res in spec["val"] else 0)
            continue
        if len(lit) > 1 and lit[0] in "-+":
            j = 1
            extra = 0
            while j < len(lit):
                ch = lit[0] + lit[j]
                if ch in spec["val"]:
                    if j + 1 < len(lit):
                        j = len(lit)
                    else:
                        extra = spec["nargs"].get(ch, 1)
                        j = len(lit)
                    break
                if ch in spec["bool"]:
                    j += 1
                    continue
                return i, "unknown_option:" + ch
            i += 1 + extra
            continue
        return i, None
    if i > n:
        return n, "missing_option_value"
    return n, None


def split_options(words, spec, start=0, permute=False, lenient=False):
    """getopt reading of ``words[start:]`` against ``spec`` (see ``_spec``).

    Returns (opts, operands, error): opts is a list of (canonical option, value
    Word or None) with clustered short flags and unambiguous long-option
    abbreviations resolved; operands the remaining Words. ``permute`` keeps
    reading options after an operand, as GNU getopt does. An unknown option is
    the error ``unknown_option:<name>`` and stops the reading; ``lenient``
    reads it as a flag instead and returns the first such error at the end.
    """
    opts = []
    operands = []
    first_err = None
    i = start
    n = len(words)
    while i < n:
        w = words[i]
        lit = w.value()
        if lit is None or lit in OPTION_SIGNS or len(lit) < 2 or lit[0] not in "-+":
            operands.append(w)
            i += 1
            if not permute:
                operands.extend(words[i:])
                break
            continue
        if lit == "--":
            operands.extend(words[i + 1:])
            break
        if lit.startswith("--"):
            name, eq, val = lit.partition("=")
            res = _resolve_long(name, spec)
            if res is None:
                if not lenient:
                    return opts, operands, "unknown_option:" + name
                first_err = first_err or "unknown_option:" + name
                opts.append((lit, None))
                i += 1
                continue
            if res in spec["val"]:
                if eq or spec["nargs"].get(res, 1) == 0:
                    opts.append((res, _synthetic_word(val, w) if eq else None))
                    i += 1
                    continue
                if i + 1 >= n:
                    return opts, operands, "missing_option_value:" + res
                opts.append((res, words[i + 1]))
                i += 2
                continue
            opts.append((res, None))
            i += 1
            continue
        j = 1
        consumed_next = False
        while j < len(lit):
            ch = lit[0] + lit[j]
            if ch in spec["val"]:
                if j + 1 < len(lit):
                    opts.append((ch, _synthetic_word(lit[j + 1:], w)))
                elif spec["nargs"].get(ch, 1) == 0:
                    opts.append((ch, None))
                else:
                    if i + 1 >= n:
                        return opts, operands, "missing_option_value:" + ch
                    opts.append((ch, words[i + 1]))
                    consumed_next = True
                break
            if ch in spec["bool"]:
                opts.append((ch, None))
                j += 1
                continue
            if not lenient:
                return opts, operands, "unknown_option:" + ch
            first_err = first_err or "unknown_option:" + ch
            opts.append((ch, None))
            j += 1
        i += 2 if consumed_next else 1
    return opts, operands, first_err


def _synthetic_word(text, origin):
    """A literal Word holding ``text`` (an attached option value of ``origin``)."""
    s = Src(text, [origin.raw.end_off() - len(text) + k for k in range(len(text))])
    return Word([("lit", s, -1)], s.off(0), s, [Part("lit", text, BARE, (s.off(0), s.end_off()))])


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------

class Assignment:
    __slots__ = ("name", "index", "append", "value", "array", "word")

    def __init__(self, word):
        self.word = word
        m = _ASSIGN_PARTS_RE.match(word.raw.text)
        self.name = m.group(1) if m else ""
        self.index = m.group(2)[1:-1] if m and m.group(2) else None
        self.append = bool(m and m.group(3))
        self.array = None
        self.value = None
        if m:
            arr = [p for p in word.parts if p.kind == "arraylit"]
            if arr:
                self.array = arr[0]
            else:
                tail = word.raw.slice(len(m.group(0)), len(word.raw.text))
                try:
                    self.value = _lex_word(tail, 0)[0]
                except LexError:
                    self.value = None

    def static_value(self):
        if self.value is None:
            return None
        return self.value.value()

    def __repr__(self):
        return "Assignment(%s=%r)" % (self.name, self.value.text if self.value else self.array)


_ASSIGN_PARTS_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(%s)?(\+?)=" % _SUBSCRIPT, re.S)


class SimpleCommand:
    __slots__ = ("assignments", "words", "redirects", "span", "negated", "timed")

    def __init__(self, assignments, words, redirects, span):
        self.assignments = tuple(assignments)
        self.words = tuple(words)
        self.redirects = tuple(redirects)
        self.span = span
        self.negated = False
        self.timed = False

    def head(self):
        return self.words[0] if self.words else None

    def argv(self):
        return [w.value() for w in self.words]

    def __repr__(self):
        return "SimpleCommand(%r)" % [w.text for w in self.words]


class Compound:
    """kind: subshell, group, if, while, until, for, select, case, cond, arith, function, coproc."""

    __slots__ = ("kind", "header", "body", "redirects", "span", "name")

    def __init__(self, kind, header, body, redirects, span, name=None):
        self.kind = kind
        self.header = tuple(header)
        self.body = tuple(body)
        self.redirects = tuple(redirects)
        self.span = span
        self.name = name

    def __repr__(self):
        return "Compound(%s)" % self.kind


class Pipeline:
    __slots__ = ("stages", "pipes", "negated", "timed")

    def __init__(self, stages, pipes, negated=False, timed=False):
        self.stages = tuple(stages)
        self.pipes = tuple(pipes)
        self.negated = negated
        self.timed = timed


class Script:
    """A command list: items are (Pipeline, separator)."""

    __slots__ = ("items", "source", "span", "error", "depth")

    def __init__(self, items, source, span, error=None, depth=0):
        self.items = tuple(items)
        self.source = source
        self.span = span
        self.error = error
        self.depth = depth

    def errors(self):
        """Every ParseError in this script and in any nested script."""
        out = [self.error] if self.error is not None else []
        for sub in _nested_scripts(self):
            if sub.error is not None:
                out.append(sub.error)
        return out

    def __repr__(self):
        return "Script(%d items%s)" % (len(self.items), ", error=%r" % self.error if self.error else "")


_TERMINATORS = (";", "&", "&&", "||", "\n")
_CASE_ENDS = (";;", ";&", ";;&")


class _Grammar:
    def __init__(self, toks, src, depth):
        self.toks = toks
        self.src = src
        self.depth = depth
        self.pos = 0
        self.error = None

    def peek(self, k=0):
        j = self.pos + k
        return self.toks[j] if j < len(self.toks) else None

    def fail(self, code, off):
        if self.error is None:
            self.error = ParseError(code, off, self.src.text[:80])

    @staticmethod
    def reserved(tok, *names):
        if tok is None or tok[0] != "W":
            return False
        w = tok[1]
        if w.quoted() or len(w.segs) != 1:
            return False
        lit = w.literal()
        return lit in names if names else lit in RESERVED

    @staticmethod
    def is_op(tok, *ops):
        return tok is not None and tok[0] == "OP" and (tok[1] in ops if ops else True)

    @staticmethod
    def tok_off(tok):
        if tok is None:
            return -1
        if tok[0] == "W":
            return tok[1].raw.off(0)
        if tok[0] == "R":
            return tok[1].off
        return tok[2]

    def skip_newlines(self):
        while self.is_op(self.peek(), "\n"):
            self.pos += 1

    def parse_list(self, end_words=(), end_ops=()):
        items = []
        start_tok = self.peek()
        while self.error is None:
            self.skip_newlines()
            tok = self.peek()
            if tok is None:
                break
            if end_words and self.reserved(tok, *end_words):
                break
            if self.is_op(tok) and tok[1] in end_ops:
                break
            if self.is_op(tok) and tok[1] in (";", "&", "&&", "||", "|", "|&", ")") + _CASE_ENDS:
                self.fail("unexpected_token", tok[2])
                break
            if self.reserved(tok, "then", "elif", "else", "fi", "do", "done", "esac", "}", "in"):
                self.fail("unexpected_token", self.tok_off(tok))
                break
            pl = self.parse_pipeline()
            if pl is None:
                break
            sep = ""
            tok = self.peek()
            if self.is_op(tok, *_TERMINATORS):
                sep = tok[1]
                self.pos += 1
                if sep in AND_OR_OPS:
                    self.skip_newlines()
                    nxt = self.peek()
                    if nxt is None or (self.is_op(nxt) and nxt[1] in _TERMINATORS + end_ops + (")",)) or (
                            end_words and self.reserved(nxt, *end_words)):
                        self.fail("unexpected_token", tok[2])
            items.append((pl, sep))
            if not sep:
                break
        a = self.tok_off(start_tok)
        return items, a

    def parse_pipeline(self):
        negated = timed = False
        while True:
            tok = self.peek()
            if self.reserved(tok, "!"):
                negated = not negated
                self.pos += 1
                continue
            if self.reserved(tok, "time"):
                timed = True
                self.pos += 1
                while True:
                    nxt = self.peek()
                    if nxt is not None and nxt[0] == "W" and nxt[1].literal() in ("-p", "--"):
                        self.pos += 1
                        continue
                    break
                continue
            break
        stages = []
        pipes = []
        while self.error is None:
            cmd = self.parse_command()
            if cmd is None:
                break
            stages.append(cmd)
            tok = self.peek()
            if self.is_op(tok, "|", "|&"):
                pipes.append(tok[1])
                self.pos += 1
                self.skip_newlines()
                if self.peek() is None or self.reserved(self.peek(), "!"):
                    self.fail("unexpected_token", tok[2])
                    break
                continue
            break
        if not stages:
            if negated or timed:
                return Pipeline((), (), negated, timed)
            return None
        for st in stages:
            if isinstance(st, SimpleCommand):
                st.negated = negated
                st.timed = timed
        return Pipeline(stages, pipes, negated, timed)

    def trailing_redirects(self):
        out = []
        while True:
            tok = self.peek()
            if tok is not None and tok[0] == "R":
                out.append(tok[1])
                self.pos += 1
                continue
            break
        return out

    def expect_word(self, name, opener_off):
        tok = self.peek()
        if self.reserved(tok, name):
            self.pos += 1
            return True
        self.fail("unbalanced_group", opener_off)
        return False

    def sub(self, end_words=(), end_ops=()):
        items, a = self.parse_list(end_words, end_ops)
        return Script(items, self.src.text, (a, a), None, self.depth)

    def parse_command(self):
        tok = self.peek()
        if tok is None:
            return None
        off = self.tok_off(tok)
        if self.is_op(tok, "("):
            nxt = self.peek(1)
            if self.is_op(nxt, "(") and nxt[2] == tok[2] + 1:
                arith = self.parse_arith(tok)
                if arith is not None:
                    return arith
            self.pos += 1
            body = self.sub(end_ops=(")",))
            if not self.is_op(self.peek(), ")"):
                self.fail("unbalanced_group", off)
                return Compound("subshell", (), (body,), (), (off, off))
            end = self.peek()[2] + 1
            self.pos += 1
            return Compound("subshell", (), (body,), self.trailing_redirects(), (off, end))
        if tok[0] == "OP":
            return None
        if self.reserved(tok, "{"):
            self.pos += 1
            body = self.sub(end_words=("}",))
            end_tok = self.peek()
            if not self.expect_word("}", off):
                return Compound("group", (), (body,), (), (off, off))
            return Compound("group", (), (body,), self.trailing_redirects(),
                            (off, self.tok_off(end_tok) + 1))
        if self.reserved(tok, "if"):
            self.pos += 1
            bodies = []
            while self.error is None:
                bodies.append(self.sub(end_words=("then",)))
                if not self.expect_word("then", off):
                    break
                bodies.append(self.sub(end_words=("elif", "else", "fi")))
                nxt = self.peek()
                if self.reserved(nxt, "elif"):
                    self.pos += 1
                    continue
                if self.reserved(nxt, "else"):
                    self.pos += 1
                    bodies.append(self.sub(end_words=("fi",)))
                end_tok = self.peek()
                self.expect_word("fi", off)
                return Compound("if", (), bodies, self.trailing_redirects(),
                                (off, self.tok_off(end_tok) + 2))
            return Compound("if", (), bodies, (), (off, off))
        if self.reserved(tok, "while", "until"):
            kind = tok[1].literal()
            self.pos += 1
            cond = self.sub(end_words=("do",))
            if not self.expect_word("do", off):
                return Compound(kind, (), (cond,), (), (off, off))
            body = self.sub(end_words=("done",))
            end_tok = self.peek()
            self.expect_word("done", off)
            return Compound(kind, (), (cond, body), self.trailing_redirects(),
                            (off, self.tok_off(end_tok) + 4))
        if self.reserved(tok, "for", "select"):
            return self.parse_for(tok, off)
        if self.reserved(tok, "case"):
            return self.parse_case(off)
        if self.reserved(tok, "[["):
            return self.parse_cond(off)
        if self.reserved(tok, "function"):
            self.pos += 1
            name_tok = self.peek()
            name = name_tok[1].text if name_tok is not None and name_tok[0] == "W" else None
            if name is None:
                self.fail("unexpected_token", off)
                return None
            self.pos += 1
            if self.is_op(self.peek(), "(") and self.is_op(self.peek(1), ")"):
                self.pos += 2
            self.skip_newlines()
            body = self.parse_command()
            if not isinstance(body, Compound):
                self.fail("unexpected_token", off)
            return Compound("function", (name_tok[1],), (_as_script(body, self),), (), (off, off), name)
        if self.reserved(tok, "coproc"):
            self.pos += 1
            nxt = self.peek()
            name = None
            if (nxt is not None and nxt[0] == "W" and not self.reserved(nxt)
                    and (self.reserved(self.peek(1), "{") or self.is_op(self.peek(1), "("))):
                name = nxt[1].text
                self.pos += 1
            body = self.parse_command()
            return Compound("coproc", (), (_as_script(body, self),), (), (off, off), name)
        if (tok[0] == "W" and self.is_op(self.peek(1), "(") and self.is_op(self.peek(2), ")")
                and tok[1].literal() is not None and not _ASSIGN_RE.match(tok[1].literal() or "")):
            self.pos += 3
            self.skip_newlines()
            body = self.parse_command()
            if not isinstance(body, Compound):
                self.fail("unexpected_token", off)
            return Compound("function", (tok[1],), (_as_script(body, self),), (), (off, off),
                            tok[1].literal())
        return self.parse_simple()

    def parse_simple(self):
        assigns = []
        words = []
        redirs = []
        first = self.peek()
        last_end = self.tok_off(first)
        while True:
            tok = self.peek()
            if tok is None or tok[0] == "OP":
                break
            if tok[0] == "R":
                redirs.append(tok[1])
                last_end = tok[1].end
            else:
                w = tok[1]
                if not words and _ASSIGN_PARTS_RE.match(w.raw.text):
                    assigns.append(Assignment(w))
                else:
                    words.append(w)
                last_end = w.raw.end_off()
            self.pos += 1
        if not assigns and not words and not redirs:
            return None
        return SimpleCommand(assigns, words, redirs, (self.tok_off(first), last_end))

    def parse_arith(self, tok):
        t = self.src.text
        k = _src_index(self.src, tok[2])
        if k < 0:
            return None
        end = _arith_end(t, k)
        if end < 0:
            return None
        body = self.src.slice(k + 2, end - 2)
        end_off = self.src.off(end - 1)
        while self.peek() is not None and self.tok_off(self.peek()) <= end_off:
            self.pos += 1
        w = _plain_word(body, self.depth)
        return Compound("arith", (w,), (), self.trailing_redirects(), (tok[2], end_off + 1))

    def parse_for(self, tok, off):
        kind = tok[1].literal()
        self.pos += 1
        header = []
        nxt = self.peek()
        if kind == "for" and self.is_op(nxt, "("):
            arith = self.parse_arith(nxt) if self.is_op(self.peek(1), "(") else None
            if arith is None:
                self.fail("unexpected_token", self.tok_off(nxt))
                return None
            header.extend(arith.header)
        else:
            if nxt is None or nxt[0] != "W":
                self.fail("unexpected_token", off)
                return None
            header.append(nxt[1])
            self.pos += 1
            self.skip_newlines()
            if self.reserved(self.peek(), "in"):
                self.pos += 1
                while self.peek() is not None and self.peek()[0] == "W":
                    header.append(self.peek()[1])
                    self.pos += 1
        if self.is_op(self.peek(), ";", "\n"):
            self.pos += 1
        self.skip_newlines()
        if self.reserved(self.peek(), "{"):
            body_cmd = self.parse_command()
            return Compound(kind, header, (_as_script(body_cmd, self),), self.trailing_redirects(), (off, off))
        if not self.expect_word("do", off):
            return Compound(kind, header, (), (), (off, off))
        body = self.sub(end_words=("done",))
        end_tok = self.peek()
        self.expect_word("done", off)
        return Compound(kind, header, (body,), self.trailing_redirects(),
                        (off, self.tok_off(end_tok) + 4))

    def parse_case(self, off):
        self.pos += 1
        subject = self.peek()
        if subject is None or subject[0] != "W":
            self.fail("unexpected_token", off)
            return None
        header = [subject[1]]
        self.pos += 1
        self.skip_newlines()
        if not self.expect_word("in", off):
            return Compound("case", header, (), (), (off, off))
        bodies = []
        while self.error is None:
            self.skip_newlines()
            tok = self.peek()
            if tok is None:
                self.fail("unbalanced_group", off)
                break
            if self.reserved(tok, "esac"):
                self.pos += 1
                return Compound("case", header, bodies, self.trailing_redirects(),
                                (off, self.tok_off(tok) + 4))
            if self.is_op(tok, "("):
                self.pos += 1
            while True:
                tok = self.peek()
                if tok is None:
                    self.fail("unbalanced_group", off)
                    return Compound("case", header, bodies, (), (off, off))
                if tok[0] == "W":
                    header.append(tok[1])
                    self.pos += 1
                    continue
                if self.is_op(tok, "|"):
                    self.pos += 1
                    continue
                if self.is_op(tok, ")"):
                    self.pos += 1
                    break
                self.fail("unexpected_token", self.tok_off(tok))
                return Compound("case", header, bodies, (), (off, off))
            bodies.append(self.sub(end_words=("esac",), end_ops=_CASE_ENDS))
            if self.is_op(self.peek(), *_CASE_ENDS):
                self.pos += 1
        return Compound("case", header, bodies, (), (off, off))

    def parse_cond(self, off):
        self.pos += 1
        header = []
        while True:
            tok = self.peek()
            if tok is None:
                self.fail("unbalanced_group", off)
                return Compound("cond", header, (), (), (off, off))
            if tok[0] == "W" and tok[1].literal() == "]]":
                self.pos += 1
                return Compound("cond", header, (), self.trailing_redirects(),
                                (off, tok[1].raw.end_off()))
            if tok[0] == "W":
                header.append(tok[1])
            elif tok[0] == "R" and tok[1].target is not None:
                header.append(tok[1].target)
            elif tok[0] == "OP" and tok[1] in (";", "&", "|", "|&") + _CASE_ENDS:
                self.fail("unexpected_token", tok[2])
                return Compound("cond", header, (), (), (off, off))
            self.pos += 1


def _as_script(cmd, g):
    if cmd is None:
        return Script((), g.src.text, (-1, -1), None, g.depth)
    return Script(((Pipeline((cmd,), ()), ""),), g.src.text, cmd.span, None, g.depth)


def _src_index(src, off):
    k = bisect.bisect_left(src.idx, off)
    if k < len(src.idx) and src.idx[k] == off:
        return k
    return -1


def _plain_word(src, depth=0):
    """A Word over ``src`` whose $-constructs are parts (arithmetic text, for instance)."""
    parts = _heredoc_parts(src, depth)
    return Word([("lit", src, -1)], src.off(0), src, parts or [Part("lit", src.text, BARE,
                                                                    (src.off(0), src.end_off()))])


def parse(text, *, max_depth=MAX_DEPTH, max_len=MAX_LEN):
    """Parse ``text`` as Bash. Never raises."""
    if not isinstance(text, str):
        return Script((), "", (0, 0), ParseError("unexpected_token", 0, "not a string"))
    if len(text) > max_len:
        return Script((), text, (0, len(text)), ParseError("size_limit", max_len, ""))
    return parse_src(Src.from_raw(text), 0, max_depth)


def parse_src(src, depth=0, max_depth=MAX_DEPTH):
    """Parse an offset-carrying Src. Never raises."""
    span = (src.off(0), src.end_off())
    if depth > max_depth:
        return Script((), src.text, span, ParseError("depth_limit", src.off(0), src.text[:80]), depth)
    toks = []
    lex_error = None
    try:
        _lex_into(src, toks, depth)
    except LexError as exc:
        lex_error = ParseError(exc.code, exc.offset, src.text[:80])
    except (RecursionError, ValueError, IndexError) as exc:
        if isinstance(exc, RecursionError):
            _RECURSION_TRIPS[0] += 1
        lex_error = ParseError("unexpected_token", -1, type(exc).__name__)
    g = _Grammar(toks, src, depth)
    try:
        items, _a = g.parse_list()
        if g.error is None and g.pos < len(toks):
            g.fail("unexpected_token", g.tok_off(g.peek()))
    except RecursionError:
        _RECURSION_TRIPS[0] += 1
        items = []
        g.fail("depth_limit", src.off(0))
    error = lex_error or g.error
    return Script(items, src.text, span, error, depth)


# One payload, many readers: every rule resolves the commands of its own parse of the hook's text, so a shell's -c
# string (or eval's code) reaches the parser once per resolve call, about 30 times in one hook call, and a payload
# of 20,000 words cost seconds. The parse is a pure function of the payload's text, its raw offsets and its depth,
# and a returned tree is never mutated after construction (Part.body fills in lazily, to the same value), so the
# payload parse is memoised on exactly that content, raw offsets included, so two command nodes share a tree only
# when a fresh parse would build an identical one at the same offsets (a re-parse of the same text). A payload
# re-read from a joined string (offsets from 0) is not memoised: two identical ones would share a tree. A parse
# that hit Python's own recursion limit depends on the stack it ran on, not only on its input, so it is never stored.
_RECURSION_TRIPS = [0]
_PAYLOAD_MEMO = {}
_PAYLOAD_MEMO_MAX = 32


def _memoised(key, build):
    hit = _PAYLOAD_MEMO.get(key)
    if hit is not None:
        return hit
    trips = _RECURSION_TRIPS[0]
    script = build()
    if _RECURSION_TRIPS[0] == trips:
        if len(_PAYLOAD_MEMO) >= _PAYLOAD_MEMO_MAX:
            _PAYLOAD_MEMO.pop(next(iter(_PAYLOAD_MEMO)))
        _PAYLOAD_MEMO[key] = script
    return script


def _payload_parse_src(src, depth):
    """``parse_src(src, depth)``, memoised for a shell payload."""
    return _memoised(("src", src.text, tuple(src.idx), depth), lambda: parse_src(src, depth))


def _nested_scripts(script):
    """Every nested Script ``walk`` reaches (walk itself descends, so no recursion here)."""
    for site in walk(script):
        for w in _site_words(site.cmd):
            for p in active_parts(w.parts):
                if p.body is not None:
                    yield p.body
        for r in site.cmd.redirects:
            if r.hd is not None:
                for p in active_parts(r.hd.expansions):
                    if p.body is not None:
                        yield p.body
        res = resolve(site.cmd)
        if res.payload is not None:
            yield res.payload


# ---------------------------------------------------------------------------
# walk
# ---------------------------------------------------------------------------

class Site:
    """One simple command reached by ``walk``.

    context: the chain of contexts from the top (``("top",)``, ``("top",
    "cmdsub")``, ``("top", "shell_c")`` ...). fed: how its stdin is fed
    (pipe, heredoc, herestring, file). dynamic: its head word is computed.
    templated: it was read from a payload whose text is computed (``bash -c
    "$X"``), so it shows the shape of the code, not the code.
    """

    __slots__ = ("cmd", "context", "depth", "fed", "dynamic", "script", "templated")

    def __init__(self, cmd, context, depth, fed, dynamic, script, templated=False):
        self.templated = templated
        self.cmd = cmd
        self.context = context
        self.depth = depth
        self.fed = fed
        self.dynamic = dynamic
        self.script = script

    def __repr__(self):
        return "Site(%r, %s, fed=%s)" % (self.cmd, "/".join(self.context), sorted(self.fed))


_DEFAULT_INTO = ("cmdsub", "backtick", "procsub", "heredoc_shell", "pipe_shell", "shell_c", "eval",
                 "exec_argv", "alias")


def _site_words(cmd):
    out = []
    for a in cmd.assignments:
        out.append(a.word)
    out.extend(cmd.words)
    for r in cmd.redirects:
        if r.target is not None:
            out.append(r.target)
    return out


def _feed(cmd, piped):
    fed = set()
    if piped:
        fed.add("pipe")
    for r in cmd.redirects:
        if r.fd != 0:
            continue
        if r.op in HERE_DOCUMENT_OPS:
            fed.add("heredoc")
        elif r.op == "<<<":
            fed.add("herestring")
        elif r.op in INPUT_REDIRECT_OPS:
            fed.add("file")
    return frozenset(fed)


def walk(script, *, into=_DEFAULT_INTO, _context=("top",), _templated=False, _state=None):
    """Yield a Site for every simple command in ``script`` and what it runs.

    ``into`` names the nested code to descend into: cmdsub, backtick, procsub
    (substitution bodies, also those nested in ${...}, arithmetic, extglob and
    brace parts), heredoc_shell (a shell fed a heredoc or here-string, its own
    or one it inherits from a compound or `exec`), pipe_shell (a shell fed by
    the stage before it, or reading a generated script), shell_c (``-c``
    payloads), eval (eval, trap, let, PROMPT_COMMAND), exec_argv (find -exec),
    alias (an alias defined earlier in the text, and git alias bodies; see
    ``git_invocations``). Payloads come from ``resolve``. A compound command
    with redirections of its own (`{ ...; } > f`) yields a redirect-only Site
    for them, before its body.
    """
    state = _state if _state is not None else {"aliases": {}, "stdin": None}
    opts = (into, state)
    depth = len(_context) - 1
    for pl, _sep in script.items:
        for k, stage in enumerate(pl.stages):
            yield from _walk_command(stage, k > 0, opts, _context, depth, script,
                                     pl.stages[k - 1] if k else None, _templated, state["stdin"])
            if isinstance(stage, SimpleCommand) and len(stage.words) == 1 and \
                    stage.words[0].value() == "exec":
                fd0 = _stdin_redirect(stage.redirects)
                if fd0 is not None:
                    state["stdin"] = fd0


def _stdin_redirect(redirects):
    """The heredoc or here-string a command's stdin reads, from its redirections."""
    by_fd = {}
    for red in redirects:
        if red.fd == 0 and red.op == "<&" and red.dup is not None:
            if red.dup in by_fd:
                by_fd[0] = by_fd[red.dup]
            continue
        if red.fd is not None:
            by_fd[red.fd] = red
    red = by_fd.get(0)
    if red is not None and (red.hd is not None or red.op == "<<<"):
        return red
    return None


def _stage_output(cmd):
    """The static text a pipeline stage writes, when it is echo, printf or a cat of a heredoc."""
    if isinstance(cmd, Compound) and cmd.kind in ("group", "subshell") and len(cmd.body) == 1:
        items = cmd.body[0].items
        if len(items) == 1 and items[0][0].stages:
            return _stage_output(items[0][0].stages[-1])
        return None
    if not isinstance(cmd, SimpleCommand):
        return None
    res = resolve(cmd)
    if res.name == "cat" and not res.args:
        for red in cmd.redirects:
            if red.hd is not None:
                return red.hd.body_src
            if red.op == "<<<" and red.target is not None and red.target.value() is not None:
                return red.target.value()
        return None
    vals = [w.value() for w in res.args]
    if res.name not in PRINTERS or any(v is None for v in vals):
        return None
    while res.name == "echo" and vals and vals[0] in ("-n", "-e", "-E", "-ne", "-en"):
        vals = vals[1:]
    return " ".join(vals) if vals else None


_PROMPT_VARS = ("PS0", "PS1", "PS2", "PS4")


def _walk_command(cmd, piped, opts, context, depth, script, prev=None, templated=False, stdin=None):
    into, state = opts
    if isinstance(cmd, Compound):
        if cmd.redirects:
            # The compound's own redirections, as the command `> f` alone is read.
            bare = SimpleCommand((), (), cmd.redirects, cmd.span)
            yield Site(bare, context, depth, _feed(bare, piped), False, script, templated)
        inner_stdin = _stdin_redirect(cmd.redirects) or stdin
        for w in cmd.header:
            yield from _walk_parts(w.parts, opts, context, templated)
        for r in cmd.redirects:
            if r.target is not None:
                yield from _walk_parts(r.target.parts, opts, context, templated)
            if r.hd is not None and not r.hd.quoted:
                yield from _walk_parts(r.hd.expansions, opts, context, templated)
        for body in cmd.body:
            for pl, _sep in body.items:
                for k, stage in enumerate(pl.stages):
                    yield from _walk_command(stage, piped or k > 0, opts, context, depth,
                                             body, pl.stages[k - 1] if k else None, templated,
                                             inner_stdin)
        return
    fed = _feed(cmd, piped)
    head = cmd.head()
    dynamic = head is not None and head.value() is None
    words = _site_words(cmd)
    reexpands = any(p.reexpand for w in words for p in active_parts(w.parts))
    yield Site(cmd, context, depth, fed, dynamic, script, templated or reexpands)
    for w in words:
        yield from _walk_parts(w.parts, opts, context, templated)
    for r in cmd.redirects:
        if r.hd is not None and not r.hd.quoted:
            yield from _walk_parts(r.hd.expansions, opts, context, templated)
    for a in cmd.assignments:
        yield from _walk_assignment(a, opts, context, depth, templated)
    res = resolve(cmd)
    if res.name == "export" or res.name == "declare":
        for w in res.args:
            if _ASSIGN_PARTS_RE.match(w.raw.text):
                yield from _walk_assignment(Assignment(w), opts, context, depth, templated)
    if res.name == "alias":
        for w in res.args:
            v = w.value()
            if v and "=" in v and _NAME_RE.match(v.split("=", 1)[0]):
                name, body = v.split("=", 1)
                state["aliases"][name] = body
    hv = head.value() if head is not None else None
    if hv in state["aliases"] and "alias" in into:
        text = state["aliases"][hv] + " " + " ".join(w.text for w in cmd.words[1:])
        yield from walk(parse(text), into=into, _context=context + ("alias",), _templated=True,
                        _state=state)
    if res.payload is None and res.stdin_shell and stdin is not None and \
            _stdin_redirect(cmd.redirects) is None:
        _stdin_payload(res, SimpleCommand((), (), (stdin,), cmd.span), depth)
    if res.payload is not None and res.payload_kind in into:
        yield from walk(res.payload, into=into, _context=context + (res.payload_kind,),
                        _templated=templated or res.unresolved is not None, _state=state)
    elif res.payload is None and res.stdin_shell and piped and "pipe_shell" in into:
        text = _stage_output(prev)
        if text is not None:
            body = parse_src(text, depth + 1) if isinstance(text, Src) else parse(text)
            yield from walk(body, into=into, _context=context + ("pipe_shell",),
                            _templated=templated, _state=state)


def _walk_assignment(a, opts, context, depth, templated):
    """PROMPT_COMMAND's value is code; a prompt variable's value is expanded when shown."""
    into, state = opts
    v = a.static_value()
    if v is None:
        return
    if a.name == "PROMPT_COMMAND" and "eval" in into:
        yield from walk(parse(v), into=into, _context=context + ("eval",), _templated=templated,
                        _state=state)
    elif a.name in _PROMPT_VARS:
        w = _expansion_word(Src(v, [-1] * len(v)), depth)
        if w is not None:
            yield from _walk_parts(w.parts, opts, context, templated)


def active_parts(parts):
    """Every part of ``parts`` with the parts nested in ${...}, arithmetic and arrays."""
    for p in parts:
        yield p
        yield from active_parts(p.inner())


def _walk_parts(parts, opts, context, templated=False):
    into, state = opts
    for p in active_parts(parts):
        kind = "procsub" if p.kind.startswith("procsub") else p.kind
        if kind in into and p.body is not None:
            yield from walk(p.body, into=into, _context=context + (kind,), _templated=templated,
                            _state=state)


def iter_commands(script, **kw):
    """The SimpleCommands ``walk`` reaches, in order."""
    for site in walk(script, **kw):
        yield site.cmd


# ---------------------------------------------------------------------------
# resolve: wrappers and payloads
# ---------------------------------------------------------------------------

# Prefix wrappers: (option spec, fixed operands before the command). None marks
# a wrapper read by its own branch of ``resolve``. The removal analyzer reads
# the same table.
WRAPPERS = {
    "command": None,
    "exec": (_spec(("-c", "-l"), ("-a",)), 0),
    "env": (_spec(("-i", "-0", "--null", "--ignore-environment", "-v", "--debug"),
                  ("-u", "--unset", "-C", "--chdir", "-S", "--split-string")), 0),
    "nohup": (_spec(), 0),
    "setsid": (_spec(("-f", "--fork", "-w", "--wait", "-c", "--ctty")), 0),
    "nice": (_spec(("--help", "--version"), ("-n", "--adjustment")), 0),
    "ionice": (_spec(("-t", "--ignore"), ("-c", "--class", "-n", "--classdata",
                                          "-p", "--pid")), 0),
    "stdbuf": (_spec((), ("-i", "-o", "-e", "--input", "--output", "--error")), 0),
    "timeout": (_spec(("-f", "--foreground", "--preserve-status", "-v", "--verbose"),
                      ("-s", "--signal", "-k", "--kill-after")), 1),
    # each spec below from the program's --help (util-linux 2.39, strace 6.8, coreutils) or manual
    "chroot": (_spec(("--skip-chdir",), ("--userspec", "--groups")), 1),
    "strace": (_spec(("-f", "-ff", "-c", "-C", "-T", "-t", "-tt", "-ttt", "-y", "-yy", "-Y", "-D", "-i",
                      "-k", "-n", "-A", "-q", "-r", "-v", "-x", "-xx", "-z", "-Z", "-w", "-d"),
                     ("-e", "-E", "-p", "-u", "-I", "-b", "-P", "-a", "-o", "-s", "-X", "-O", "-S", "-U")),
               0),
    "ltrace": (_spec(("-f", "-c", "-C", "-S", "-t", "-tt", "-ttt", "-T", "-b", "-i", "-r", "-L"),
                     ("-a", "-A", "-D", "-e", "-F", "-l", "-n", "-o", "-p", "-s", "-u", "-w", "-x")), 0),
    "taskset": (_spec(("-a", "--all-tasks", "-p", "--pid", "-c", "--cpu-list")), 1),
    "prlimit": (_spec(("--noheadings", "--raw", "--verbose"), ("-p", "--pid", "-o", "--output"),
                      attached=("--core", "--cpu", "--data", "--fsize", "--nofile", "--nproc", "--as",
                                "--stack", "--locks", "--memlock", "--msgqueue", "--nice", "--rtprio",
                                "--rttime", "--sigpending", "--rss")), 0),
    "unshare": (_spec(("-f", "--fork", "-r", "--map-root-user", "-c", "--map-current-user",
                       "--map-auto", "--keep-caps"),
                      ("--map-user", "--map-group", "--map-users", "--map-groups", "--propagation",
                       "--setgroups", "-R", "--root", "-w", "--wd", "-S", "--setuid", "-G",
                       "--setgid", "--monotonic", "--boottime"),
                      attached=("-m", "--mount", "-u", "--uts", "-i", "--ipc", "-n", "--net", "-p",
                                "--pid", "-U", "--user", "-C", "--cgroup", "-T", "--time",
                                "--kill-child", "--mount-proc")), 0),
    "nsenter": (_spec(("-a", "--all", "-F", "--no-fork", "-e", "--env", "--preserve-credentials",
                       "-Z", "--follow-context"), ("-t", "--target", "-W", "--wdns"),
                      attached=("-m", "--mount", "-u", "--uts", "-i", "--ipc", "-n", "--net", "-p",
                                "--pid", "-U", "--user", "-C", "--cgroup", "-T", "--time", "-S",
                                "--setuid", "-G", "--setgid", "-r", "--root", "-w", "--wd")), 0),
    "setarch": (_spec(("-v", "--verbose", "-3", "--3gb", "-B", "--32bit", "-L",
                       "--addr-compat-layout", "-F", "--fdpic-funcptrs",
                       "-I", "--short-inode", "-R", "--addr-no-randomize",
                       "-S", "--whole-seconds", "-T", "--sticky-timeouts",
                       "-X", "--read-implies-exec", "-Z", "--mmap-page-zero",
                       "--uname-2.6")), 1),
    "fakeroot": (_spec(("-u", "--unknown-is-real", "-h", "--help", "-v", "--version"),
                       ("-l", "--lib", "-s", "--save-file", "-i", "--load-file",
                        "-b", "--fd-base")), 0),
    "eatmydata": (_spec(), 0),
    "valgrind": (_spec(("-q", "--quiet", "-v", "--verbose"),
                       ("--tool", "--log-file", "--error-exitcode")), 0),
    "xvfb-run": (_spec(("-a", "--auto-servernum", "-d", "--auto-display", "-h", "--help", "-l",
                        "--listen-tcp"),
                       ("-n", "--server-num", "-s", "--server-args", "-e", "--error-file", "-f",
                        "--auth-file", "-p", "--xauth-protocol", "-w", "--wait")), 0),
    "dbus-run-session": (_spec((), ("--config-file", "--dbus-daemon")), 0),
    "daemonize": (_spec(("-v",), ("-a", "-c", "-e", "-o", "-p", "-l", "-u", "-g",
                                  "-E", "-P")), 0),
    "systemd-run": (_spec(("--scope", "--user", "--system", "--pty", "-t", "--pipe",
                           "-q", "--quiet", "--wait", "-d", "--no-block",
                           "--send-sighup", "--collect", "-G"),
                          ("--unit", "-u", "--property", "-p", "--description",
                           "--slice", "--on-active", "--on-boot", "--on-calendar",
                           "--timer-property", "--setenv", "-E", "--service-type",
                           "--uid", "--gid", "--nice", "--working-directory",
                           "--machine", "-M", "--expand-environment", "--host", "-H",
                           "--on-startup", "--on-unit-active", "--on-unit-inactive")), 0),
    "chpst": (_spec(("-P", "-v", "-0", "-1", "-2", "-/"),
                    ("-u", "-U", "-b", "-e", "-m", "-d", "-o", "-p", "-f", "-c",
                     "-r", "-n", "-l", "-L")), 0),
    "s6-setuidgid": (_spec(), 1),
    "firejail": (_spec(("--noprofile", "--quiet", "--private", "--net=none",
                        "--seccomp", "--caps", "--nosound", "--x11"),
                       ("--profile", "--name", "--whitelist", "--read-only",
                        "--bind", "--env", "--chroot", "--net")), 0),
    "systemd-nspawn": (_spec(("-b", "--boot", "-q", "--quiet", "--private-network",
                              "-x", "--ephemeral", "-a", "--as-pid2", "-U"),
                             ("-D", "--directory", "-M", "--machine", "-i", "--image",
                              "-u", "--user", "--bind", "--bind-ro", "-E", "--setenv",
                              "--chdir", "--template", "--volatile", "--network-veth")),
                       0),
    "busybox": (_spec(), 0),
    "toybox": (_spec(), 0),
    "builtin": (_spec(), 0),
    "sudo": (_spec(("-n", "--non-interactive", "-S", "--stdin", "-b", "--background",
                    "-E", "--preserve-env", "-H", "--set-home", "-i", "--login",
                    "-s", "--shell", "-k", "--reset-timestamp", "-K", "--remove-timestamp",
                    "-v", "--validate", "-l", "--list", "-A", "--askpass", "-P",
                    "--preserve-groups", "-N", "--no-update"),
                   ("-u", "--user", "-g", "--group", "-p", "--prompt", "-C", "-U", "--other-user",
                    "--close-from", "-h", "--host", "-D", "--chdir", "-R", "--chroot",
                    "-T", "--command-timeout", "-r", "--role", "-t", "--type")), 0),
    "doas": (_spec(("-n", "-s", "-L"), ("-u", "-a", "-C")), 0),
    "run0": (_spec(("--pty", "--pipe", "--no-ask-password"),
                   ("-u", "--user", "-g", "--group", "--property", "-D", "--chdir",
                    "--setenv", "--slice", "--unit", "--description", "--nice",
                    "--background", "--machine", "-M")), 0),
    "time": (_spec(("-p", "--portability", "-v", "--verbose", "-a", "--append",
                    "-q", "--quiet"),
                   ("-f", "--format", "-o", "--output")), 0),
    "perf": (_spec((), ("-o", "--output", "-p", "--pid", "-e", "--event", "-C", "--cpu")), 1),
    "machinectl": None,
    "start-stop-daemon": None,
    "flock": None,
    "runuser": None,
    "su": None,
    "sg": None,
    "script": None,
    "bwrap": None,
    "ssh": None,
    "sshpass": (_spec(("-e",), ("-p", "-f", "-d", "-P")), 0),
    "kubectl": None,
    "watch": None,
    "xargs": None,
    "parallel": None,
    "find": None,
    "git": None,
    "docker": None,
    "podman": None,
    "coproc": None,
}

# GNU xargs (findutils 4.9): the options that take the next word as their value,
# and those whose value is optional and only ever attached (`-i{}`, `-e`, `-l5`,
# `--eof=E`, `--replace=R`, `--max-lines=N`): `xargs -i cmd` runs cmd.
XARGS_VALUES = ("-n", "--max-args", "-P", "--max-procs", "-I", "-L", "-s", "--max-chars",
                "-d", "--delimiter", "-E", "-a", "--arg-file", "--process-slot-var")
XARGS_ATTACHED = ("-i", "--replace", "-e", "--eof", "-l", "--max-lines")
XARGS_REPLACE_OPTS = ("-I", "-i", "--replace")  # run the command once per item, the item put in place
XARGS_SPEC = _spec(("-0", "--null", "-r", "--no-run-if-empty", "-t", "--verbose", "-p",
                    "--interactive", "-x", "--exit", "-o", "--open-tty", "--show-limits"),
                   XARGS_VALUES + XARGS_ATTACHED, {o: 0 for o in XARGS_ATTACHED})

# Wrappers the removal analyzer gives no generic reading but ``resolve`` peels:
# the option spec and the fixed operands before the command word.
PEEL = {
    "chrt": (_spec(("-a", "--all-tasks", "-m", "--max", "-v", "--verbose", "-b", "--batch",
                    "-d", "--deadline", "-f", "--fifo", "-i", "--idle", "-o", "--other",
                    "-r", "--rr", "-R", "--reset-on-fork"),
                   ("-p", "--pid", "-T", "--sched-runtime", "-P", "--sched-period",
                    "-D", "--sched-deadline")), 1),
    "unbuffer": (_spec(("-p",)), 0),
    "setpriv": (_spec(("-d", "--dump", "--nnp", "--no-new-privs", "--init-groups", "--keep-groups",
                       "--clear-groups", "--reset-env"),
                      ("--reuid", "--regid", "--ruid", "--euid", "--rgid", "--egid", "--groups",
                       "--securebits", "--pdeathsig", "--selinux-label", "--apparmor-profile",
                       "--inh-caps", "--ambient-caps", "--bounding-set", "--landlock-access",
                       "--landlock-rule")), 0),
    "choom": (_spec((), ("-n", "--adjust", "-p", "--pid")), 0),
    "runcon": (_spec(("-c", "--compute"), ("-u", "--user", "-r", "--role", "-t", "--type",
                                           "-l", "--range")), "context"),
    "systemd-inhibit": (_spec(("--list", "--no-pager", "--no-legend"),
                              ("--what", "--who", "--why", "--mode")), 0),
    "numactl": (_spec(("-a", "--all", "-l", "--localalloc", "-H", "--hardware", "-s", "--show",
                       "-b", "--balancing"),
                      ("-i", "--interleave", "-w", "--weighted-interleave", "-N", "--cpunodebind",
                       "-C", "--physcpubind", "-m", "--membind", "-p", "--preferred",
                       "-P", "--preferred-many")), 0),
    "xargs": (XARGS_SPEC, 0),
    "flock": (_spec(("-s", "--shared", "-x", "--exclusive", "-e", "-u", "--unlock", "-n",
                     "--nb", "--nonblock", "-o", "--close", "-F", "--no-fork", "--verbose"),
                    ("-w", "--wait", "--timeout", "-E", "--conflict-exit-code", "-c",
                     "--command")), 1),
    "command": (_spec(("-p",)), 0),
    # programs that only run the command after their options (each one's --help / manual)
    "watch": (_spec(("-b", "--beep", "-c", "--color", "-C", "--no-color", "-d", "--differences",
                     "-e", "--errexit", "-g", "--chgexit", "-t", "--no-title", "-x", "--exec",
                     "-p", "--precise", "-w", "--no-wrap", "-r", "--no-rerun", "-h", "--help",
                     "-v", "--version"),
                    ("-n", "--interval", "-q", "--equexit")), 0),
    "faketime": (_spec(("-m", "-f", "--exclude-monotonic", "--disable-shm"),
                       ("--date-prog", "-p")), 1),
    "pkexec": (_spec(("--keep-cwd", "--disable-internal-agent"), ("--user",)), 0),
    "proxychains": (_spec(("-q",), ("-f",)), 0),
    "proxychains4": (_spec(("-q",), ("-f",)), 0),
    "torsocks": (_spec(("-d", "--debug", "-i", "--isolate", "-q", "--quiet", "-6"),
                       ("-u", "--user", "-p", "--pass", "-a", "--address", "-P", "--port")), 0),
    "trickle": (_spec(("-h", "-v", "-V", "-s"), ("-d", "-u", "-w", "-t", "-l", "-n")), 0),
    "cpulimit": (_spec(("-z", "--lazy", "-i", "--include-children", "-k", "--kill", "-r",
                        "--restore", "-v", "--verbose", "-q", "--quiet"),
                       ("-l", "--limit", "-c", "--cpu", "-p", "--pid", "-e", "--exe")), 0),
    "tsp": (_spec(("-n", "-f", "-d", "-B", "-E", "-g"), ("-L", "-D", "-W", "-N")), 0),
    "ssh-agent": (_spec(("-c", "-s", "-D", "-d"), ("-a", "-E", "-O", "-P", "-t")), 0),
}

SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "ksh93", "mksh", "ash", "rbash", "yash",
                    "posh", "busybox-sh", "lksh", "pdksh", "oksh"})
# A command shaped like a shell (`*sh`, `*sh93`) that SHELLS does not name, given
# a -c option, is read as a shell, and its reading is unresolved.
_SHELL_LIKE_RE = re.compile(r"[a-z]*sh[0-9.]*")
# su and runuser (util-linux --help): runuser adds -u/--user; -c, --command and
# --session-command pass the command to the shell.
SU_COMMAND_OPTS = COMMAND_OPTS + ("--session-command",)
_SU_SPEC = _spec(("-l", "--login", "-m", "-p", "--preserve-environment", "-P", "--pty",
                  "-f", "--fast", "-", "-h", "--help", "-V", "--version"),
                 SU_COMMAND_OPTS + ("-s", "--shell", "-g", "--group", "-G", "--supp-group",
                                    "-w", "--whitelist-environment"))
PEEL["runuser"] = (_spec(_SU_SPEC["bool"], _SU_SPEC["val"] | set(RUNUSER_USER_OPTS)), 0)
_SCRIPT_SPEC = _spec(("-a", "--append", "-e", "--return", "-f", "--flush", "-q", "--quiet"),
                     ("-c", "--command", "-E", "--echo", "-I", "--log-in", "-O", "--log-out",
                      "-B", "--log-io", "-T", "--log-timing", "-m", "--logging-format",
                      "-o", "--output-limit"))
_SSH_SPEC = _spec(("-4", "-6", "-A", "-a", "-C", "-f", "-G", "-g", "-K", "-k", "-M", "-N",
                   "-n", "-q", "-s", "-T", "-t", "-V", "-v", "-X", "-x", "-Y", "-y"),
                  ("-B", "-b", "-c", "-D", "-E", "-e", "-F", "-I", "-i", "-J", "-L", "-l",
                   "-m", "-O", "-o", "-p", "-P", "-Q", "-R", "-S", "-W", "-w"))


def basename(text):
    return text.rsplit("/", 1)[-1] if text else text


class Resolved:
    """The command a SimpleCommand runs once its wrappers are peeled.

    head: the command Word (None when there is none); args: its arguments;
    wrappers: [(name, [(opt, value Word|None)])]; payload: the parsed code a
    shell ``-c``, ``eval``, ``su -c``, ``ssh``, ``flock -c`` or a fed shell
    runs; payload_kind: shell_c, eval or heredoc_shell; unresolved: why a
    wrapper or payload could not be read statically, else None.
    """

    __slots__ = ("head", "args", "wrappers", "payload", "payload_kind", "unresolved",
                 "assignments", "stdin_shell")

    def __init__(self):
        self.stdin_shell = False
        self.head = None
        self.args = ()
        self.wrappers = []
        self.payload = None
        self.payload_kind = None
        self.unresolved = None
        self.assignments = ()

    @property
    def name(self):
        if self.head is None:
            return None
        v = self.head.value()
        return basename(v) if v is not None else None

    def argv(self):
        return [w.value() for w in self.args]

    def __repr__(self):
        return "Resolved(%r, %r, wrappers=%r, payload=%r)" % (
            self.name, self.argv(), [w[0] for w in self.wrappers], self.payload)


def _payload_from_words(words, depth):
    """Parse the payload words of a shell ``-c`` or ``eval``.

    Static words give the exact code. A computed word gives its template (the
    text with each expansion left in place), which callers must treat as
    unresolved: see ``_payload_template``.
    """
    vals = [w.value() for w in words]
    if any(v is None for v in vals):
        return None
    if len(words) == 1:
        w = words[0]
        if all(p.quote != ANSI_C for p in w.parts) and w.literal() is not None:
            return _payload_parse_src(w.content(), depth + 1)
        return parse(vals[0])
    return parse(" ".join(vals))


def _payload_template(words, depth):
    """The code of computed payload words with every expansion kept as written."""
    if len(words) == 1:
        raw = words[0].raw
        t = raw.text
        if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
            return _payload_parse_src(raw.slice(1, len(t) - 1), depth + 1)
        if len(t) >= 2 and t[0] == "'" and t[-1] == "'":
            return _payload_parse_src(raw.slice(1, len(t) - 1), depth + 1)
    return parse(" ".join(w.text for w in words))


def _set_payload(r, words, kind, depth, why):
    r.payload = _payload_from_words(words, depth)
    r.payload_kind = kind
    if r.payload is None:
        r.payload = _payload_template(words, depth)
        r.unresolved = why


def resolve(cmd, depth=None):
    """Peel the wrappers of ``cmd`` and read the code it hands to a shell."""
    r = Resolved()
    if not isinstance(cmd, SimpleCommand):
        return r
    if depth is None:
        depth = 0
    r.assignments = cmd.assignments
    words = list(cmd.words)
    guard = 0
    while words and guard < 32:
        guard += 1
        head = words[0]
        hv = head.value()
        if hv is None:
            r.head = head
            r.args = tuple(words[1:])
            r.unresolved = "dynamic_head"
            return r
        name = basename(hv)
        if name == "env":
            opts, rest, err = split_options(words, WRAPPERS["env"][0], 1, lenient=True)
            r.wrappers.append((name, opts))
            if err:
                r.unresolved = "env:" + err
            while rest and (rest[0].value() or "").find("=") > 0 and not rest[0].value().startswith("-"):
                if _ASSIGN_RE.match(rest[0].value()):
                    r.assignments = r.assignments + (Assignment(rest[0]),)
                rest = rest[1:]
            split = [v for o, v in opts if o in ENV_SPLIT_OPTS]
            if not split and rest and rest[0].value() is None:
                for j in range(1, len(rest) - 1):
                    if rest[j].value() in ENV_SPLIT_OPTS:
                        split = [rest[j + 1]]
                        r.unresolved = "computed-env-option"
                        rest = rest[j + 2:]
                        break
            if split and split[0].value() is not None:
                # env -S splits by its own rules (\_ is a blank, and more escapes
                # than these): read as shell words, and the reading is unresolved.
                r.unresolved = r.unresolved or "env_split_string"
                text = split[0].value().replace("\\_", " ")
                sub = parse(text + " " + " ".join(w.text for w in rest))
                cmds = [s for s in walk(sub, into=())]
                if cmds:
                    return _merge(r, resolve(cmds[0].cmd, depth))
            words = rest
            continue
        if name in LOOKUP_BUILTINS and len(words) > 1:
            first = words[1].value()
            if name == "command" and first in COMMAND_LOOKUP_OPTS:
                r.head = head
                r.args = tuple(words[1:])
                return r
            spec = PEEL["command"][0] if name == "command" else WRAPPERS["builtin"][0]
            opts, rest, err = split_options(words, spec, 1)
            r.wrappers.append((name, opts))
            words = rest
            continue
        if name == "eval":
            r.head = head
            r.args = tuple(words[1:])
            code = words[2:] if len(words) > 1 and words[1].value() == "--" else words[1:]
            if code:
                _set_payload(r, list(code), "eval", depth, "eval_dynamic")
            return r
        if name == "trap":
            # trap's first operand is code run later (on a signal, EXIT, ERR, DEBUG ...)
            r.head = head
            r.args = tuple(words[1:])
            ops = list(words[1:])
            while ops and ops[0].value() in ("-p", "-l", "-P"):
                return r
            if ops and ops[0].value() == "--":
                ops = ops[1:]
            if len(ops) > 1 and ops[0].value() not in ("-", ""):
                _set_payload(r, [ops[0]], "eval", depth, "trap_dynamic")
            return r
        if name in SOURCE_BUILTINS:
            r.head = head
            r.args = tuple(words[1:])
            ops = list(words[1:])
            if ops and ops[0].value() == "--":
                ops = ops[1:]
            if ops:
                _script_operand(r, ops[0], cmd, depth)
            return r
        if name == "let":
            # let evaluates each operand as arithmetic: an array subscript's
            # substitution runs
            r.head = head
            r.args = tuple(words[1:])
            vals = [w.value() for w in words[1:]]
            if any(v is None for v in vals):
                r.unresolved = "let_dynamic"
            elif vals:
                r.payload = parse(" ".join(": $((%s))" % v for v in vals).replace(" : ", "; : "))
                r.payload_kind = "eval"
            return r
        if name == "xargs":
            words, replace = _peel_xargs(r, words)
            if replace is not None and any(replace in (w.value() or w.text) for w in words):
                r.unresolved = r.unresolved or "xargs_replace"
            fed = _stdin_redirect(cmd.redirects)
            text = None
            if fed is not None and fed.hd is not None and fed.hd.quoted:
                text = fed.hd.body
            elif fed is not None and fed.op == "<<<" and fed.target is not None:
                text = fed.target.value()
            if text is not None and replace is None:
                words = list(words) + [_synthetic_word(a, words[-1] if words else head)
                                       for a in argv_split(text)]
            elif replace is None:
                # the words xargs appends come from its input
                r.unresolved = r.unresolved or "xargs_appends"
            if not words:
                r.head = None
                return r
            continue
        if name in SHELLS:
            return _resolve_shell(r, head, words, cmd, depth)
        if name not in ("ssh", "hash") and _SHELL_LIKE_RE.fullmatch(name) and _has_c(words):
            _resolve_shell(r, head, words, cmd, depth)
            r.unresolved = r.unresolved or "unknown_shell"
            return r
        if name == "find":
            return _resolve_find(r, head, words, cmd, depth)
        if name in PM_EXEC_RUNNERS or (name in NODE_PKG_MANAGERS and len(words) > 1
                                       and words[1].value() in PM_EXEC_SUBCMDS):
            tail = words[1 if name in PM_EXEC_RUNNERS else 2:]
            vals = [w.value() for w in tail]
            call = next((k for k, v in enumerate(vals) if v in PM_CALL_OPTS), None)
            if call is not None and call + 1 < len(tail):
                r.head = head
                r.args = tuple(words[1:])
                _set_payload(r, [tail[call + 1]], "shell_c", depth, "pm_call_dynamic")
                return r
            if "--" in vals:
                r.wrappers.append((name, []))
                words = tail[vals.index("--") + 1:]
                continue
        if name == "sg":
            # sg [-] GROUP [-c] COMMAND: /bin/sh -c COMMAND with GROUP as the group
            ops = [w for w in words[1:] if w.value() not in ("-", "-c")]
            if len(ops) > 1:
                r.head = head
                r.args = tuple(words[1:])
                _set_payload(r, ops[1:], "shell_c", depth, "sg_dynamic")
                return r
        if name == "script":
            # script [options] [FILE]: -c/--command runs COMMAND in a shell (util-linux)
            opts, rest, err = split_options(words, _SCRIPT_SPEC, 1, permute=True, lenient=True)
            code = [v for o, v in opts if o in COMMAND_OPTS]
            if code:
                r.head = head
                r.args = tuple(words[1:])
                _set_payload(r, [code[-1]], "shell_c", depth, "script_c_dynamic")
                return r
        if name == "runuser" and not _has_c(words):
            # runuser -u USER [--] COMMAND [ARG...] runs COMMAND as USER, with no shell
            opts, rest, err = split_options(words, PEEL["runuser"][0], 1)
            if rest and any(o in RUNUSER_USER_OPTS for o, _v in opts):
                r.wrappers.append((name, opts))
                words = rest
                continue
        if name in ("su", "runuser", "sg") and not _has_c(words):
            r.head = head
            r.args = tuple(words[1:])
            _stdin_payload(r, cmd, depth)
            return r
        if name in ("su", "runuser") and _has_c(words):
            spec = _SU_SPEC if name == "su" else PEEL["runuser"][0]
            opts, rest, err = split_options(words, spec, 1, permute=True)
            r.head = head
            r.args = tuple(words[1:])
            code = [v for o, v in opts if o in SU_COMMAND_OPTS]
            if code:
                _set_payload(r, [code[-1]], "shell_c", depth, name + "_c_dynamic")
            return r
        if name == "ssh":
            opts, rest, err = split_options(words, _SSH_SPEC, 1)
            r.head = head
            r.args = tuple(words[1:])
            if err:
                r.unresolved = "ssh:" + err
            elif len(rest) > 1:
                _set_payload(r, rest[1:], "shell_c", depth, "ssh_dynamic")
            elif rest:
                _stdin_payload(r, cmd, depth)
            return r
        if name == "flock":
            opts, rest, err = split_options(words, PEEL["flock"][0], 1, permute=False)
            code = [v for o, v in opts if o in COMMAND_OPTS]
            if not code and len(rest) > 1:
                after = rest[1:]
                lead = after[0].value()
                if lead in COMMAND_OPTS and len(after) > 1:
                    code = [after[1]]
            if code:
                r.head = head
                r.args = tuple(words[1:])
                _set_payload(r, [code[-1]], "shell_c", depth, "flock_c_dynamic")
                r.wrappers.append((name, opts))
                return r
            r.wrappers.append((name, opts))
            if err:
                r.unresolved = "flock:" + err
            words = rest[1:]
            continue
        entry = WRAPPERS.get(name)
        if entry is None or name in ("command",):
            entry = PEEL.get(name)
        if entry is not None and name not in ("git", "find", "docker", "podman", "kubectl",
                                              "parallel", "su", "sg", "script",
                                              "bwrap", "ssh", "machinectl", "start-stop-daemon",
                                              "coproc", "runuser"):
            spec, fixed = entry
            opts, rest, err = split_options(words, spec, 1, lenient=True)
            r.wrappers.append((name, opts))
            if err:
                # An option the table does not know may take a value: the
                # command found past it is a guess, so the reading is unresolved.
                r.unresolved = r.unresolved or name + ":" + err
            if fixed == "context":
                # runcon CONTEXT COMMAND, unless options give the context's parts
                fixed = 0 if opts else 1
            if len(rest) < fixed:
                r.head = head
                r.args = tuple(words[1:])
                r.unresolved = name + ":missing_operand"
                return r
            words = rest[fixed:]
            if not words and name in ("sudo", "doas", "run0") and any(
                    o in ("-i", "--login", "-s", "--shell") for o, _v in opts):
                r.head = head
                _stdin_payload(r, cmd, depth)
                return r
            if name == "xargs" and not words:
                r.head = None
                return r
            continue
        break
    if not words:
        return r
    r.head = words[0]
    r.args = tuple(words[1:])
    return r


FIND_EXEC = ("-exec", "-execdir", "-ok", "-okdir")  # find actions that run a command
FIND_SYMLINK_OPTS = ("-H", "-L", "-P")  # find's symlink options, before the start paths
FIND_EXEC_ENDS = (";", "+")  # the words that end the command of a find -exec/-ok (every reader reads this one)
_FIND_FILE = ("-fprint", "-fprint0", "-fprintf", "-fls")  # the next word names a file the action writes
FIND_ACTIONS = FIND_EXEC + _FIND_FILE + ("-delete",)  # find actions that run a command, write a file or delete
FIND_OPERATORS = ("(", ")", "!")  # a word of find's expression that is no option: the start paths end before it
FIND_EXPRESSION_LEADS = ("-", "(", "!")  # a word led by one of these begins find's expression
SHELL_STARTUP_VARS = ("BASH_ENV", "ENV")  # the environment names a non-interactive shell sources at start
ROOTED = ("/", "~")  # a path led by one of these does not depend on the working directory
SED_SCRIPT_GIVEN_OPTS = ("-e", "--expression", "-f", "--file")  # sed's options that give it a script (text or file)
SED_SCRIPT_ATTACHED = ("--expression=", "--file=")  # the same, value attached


def _resolve_find(r, head, words, cmd, depth):
    """find's -exec/-execdir/-ok/-okdir run the words up to `;` or `+` as a command."""
    r.head = head
    r.args = tuple(words[1:])
    items = []
    k = 1
    while k < len(words):
        if words[k].value() in FIND_EXEC:
            j = k + 1
            while j < len(words) and words[j].value() not in FIND_EXEC_ENDS:
                j += 1
            argv_words = words[k + 1:j]
            if argv_words:
                span = (argv_words[0].span[0], argv_words[-1].span[1])
                items.append((Pipeline((SimpleCommand((), argv_words, (), span),), ()), ";"))
            k = j + 1
            continue
        k += 1
    if items:
        r.payload = Script(items, cmd_source(cmd), cmd.span, None, depth + 1)
        r.payload_kind = "exec_argv"
    return r


def cmd_source(cmd):
    return " ".join(w.text for w in cmd.words)




def _peel_xargs(r, words):
    """xargs's own options: -i, -e and -l take an optional attached value only."""
    k = 1
    replace = None
    opts = []
    while k < len(words):
        v = words[k].value()
        if v is None or not v.startswith("-") or v == "-":
            break
        if v == "--":
            k += 1
            break
        name = v.split("=", 1)[0]
        if name in XARGS_VALUES and "=" not in v and (v.startswith("--") or len(v) == 2):
            val = words[k + 1].value() if k + 1 < len(words) else None
            opts.append((name, words[k + 1] if k + 1 < len(words) else None))
            if name == "-I":
                replace = val
            k += 2
            continue
        if v[:2] in ("-I",) and len(v) > 2:
            replace = v[2:]
        elif v[:2] == "-i" or v.startswith("--replace"):
            replace = v[2:] if v[:2] == "-i" and len(v) > 2 else (v.split("=", 1)[1] if "=" in v else "{}")
        opts.append((v, None))
        k += 1
    r.wrappers.append(("xargs", opts))
    return words[k:], replace


def _merge(outer, inner):
    inner.wrappers = outer.wrappers + inner.wrappers
    inner.unresolved = inner.unresolved or outer.unresolved
    inner.assignments = outer.assignments + inner.assignments
    return inner


def _has_c(words):
    for w in words[1:]:
        v = w.value()
        if v in SU_COMMAND_OPTS or (v and v.startswith(("--command=", "--session-command="))):
            return True
        if v and len(v) > 1 and v[0] == "-" and v[1] != "-" and "c" in v[1:]:
            return True
    return False


def _resolve_shell(r, head, words, cmd, depth):
    """A shell's code: its -c string, a script file it reads, or its stdin.

    A short-option cluster ending in o/O takes the next word as its value
    (`-eo pipefail`); a lone `-` or `--` ends the options; -s reads the
    script from stdin even with operands. A script operand that is a process
    substitution, /dev/stdin or /dev/fd/N is code generated at run time.
    """
    r.head = head
    r.args = tuple(words[1:])
    k = 1
    has_c = has_s = False
    while k < len(words):
        v = words[k].value()
        if v is None and has_c:
            break
        if v is None:
            # A computed option: it may be anything, so a later -c string is
            # still read as the payload, and the reading is unresolved.
            later = [j for j in range(k + 1, len(words))
                     if (words[j].value() or "").startswith("-") and "c" in (words[j].value() or "")[1:]
                     and not (words[j].value() or "").startswith("--")]
            if later and later[0] + 1 < len(words):
                _set_payload(r, [words[later[0] + 1]], "shell_c", depth, "shell_c_dynamic")
            r.unresolved = "computed-shell-option"
            return r
        if v in OPTION_ENDS:
            k += 1
            break
        if len(v) > 1 and v[0] in "-+" and not v.startswith("--"):
            # bash and dash read `+c` (and a `+` cluster with c) as -c.
            if "c" in v[1:]:
                has_c = True
            if v[0] == "-" and "s" in v[1:]:
                has_s = True
            k += 2 if v[-1] in "oO" else 1
            continue
        if v.startswith("--"):
            k += 2 if v in SHELL_FILE_OPTS else 1
            continue
        break
    for a in r.assignments:
        if a.name in SHELL_STARTUP_VARS and a.value is not None:
            # the startup file runs before the shell's own code
            _script_operand(r, a.value, cmd, depth)
            if r.payload is not None:
                return r
    if has_c:
        if k < len(words):
            _set_payload(r, [words[k]], "shell_c", depth, "shell_c_dynamic")
        else:
            r.unresolved = "shell_c_missing"
        return r
    if k < len(words) and not has_s:
        _script_operand(r, words[k], cmd, depth)
        return r
    _stdin_payload(r, cmd, depth)
    return r


_STDIN_FILES = locations.STDIN_DEVICES + ("-",)


def _script_operand(r, w, cmd, depth):
    """A shell or `source` reading the file ``w``: stdin and process substitutions are code."""
    v = w.value()
    if v in _STDIN_FILES:
        _stdin_payload(r, cmd, depth)
        return
    procs = [p for p in w.parts if p.kind == "procsub_in"]
    if procs:
        body = procs[0].body
        text = None
        if body is not None and len(body.items) == 1 and len(body.items[0][0].stages) == 1:
            text = _stage_output(body.items[0][0].stages[0])
        if text is not None:
            r.payload = parse_src(text, depth + 1) if isinstance(text, Src) else parse(text)
        else:
            r.payload = parse("")
            r.unresolved = "generated_code"
        r.payload_kind = "pipe_shell"
        return
    if v is None or (v or "").startswith(locations.FD_DIR):
        r.unresolved = "script_file_computed"


def _heredoc_unescape(body):
    """An unquoted heredoc body as the reader gets it: `\\$`, `\\``, `\\\\` lose the backslash."""
    t = body.text
    keep = []
    k = 0
    while k < len(t):
        if t[k] == "\\" and k + 1 < len(t) and t[k + 1] in "$`\\":
            keep.append(k + 1)
            k += 2
            continue
        keep.append(k)
        k += 1
    return Src("".join(t[k] for k in keep), [body.idx[k] for k in keep])


def _stdin_payload(r, cmd, depth, inherited=None):
    """The code a shell reading its stdin gets from a heredoc or here-string."""
    r.stdin_shell = True
    by_fd = {}
    for red in cmd.redirects:
        fd = red.fd
        if fd == 0 and red.op == "<&" and red.dup is not None:
            src_red = by_fd.get(red.dup)
            if src_red is not None:
                by_fd[0] = src_red
            continue
        if fd is not None:
            by_fd[fd] = red
    red = by_fd.get(0, inherited)
    for red in ([red] if red is not None else []):
        if red.op in HERE_DOCUMENT_OPS and red.hd is not None:
            if red.hd.quoted:
                r.payload = parse_src(red.hd.body_src, depth + 1)
            else:
                r.payload = parse_src(_heredoc_unescape(red.hd.body_src), depth + 1)
                if red.hd.expansions:
                    r.unresolved = "heredoc_expansion"
            r.payload_kind = "heredoc_shell"
        elif red.op == "<<<" and red.target is not None:
            _set_payload(r, [red.target], "heredoc_shell", depth, "herestring_dynamic")
    return r


def argv(cmd):
    """The static argv of a SimpleCommand: one str per word, None where computed."""
    return cmd.argv() if isinstance(cmd, SimpleCommand) else []


# ---------------------------------------------------------------------------
# executable_view
# ---------------------------------------------------------------------------

_SCRIPT_INTERP_RE = re.compile(
    r"^(python|python[23]|node|nodejs|ruby|perl|php|lua|rscript|Rscript|r|R|java|kotlin|"
    r"scala|groovy|swift|dotnet)[\d.]*$")
_DATA_ARG_KEEP = frozenset({"killall", "pkill", "kill", "rm", "mv"})


def executable_view(text):
    """``text`` with its non-executable parts blanked, offsets kept.

    Blanked: comments; heredoc bodies of a command that is not a shell nor
    piped into one; the quoted arguments of a command that only reads them as
    data (substitutions inside them stay). Kept: every command word, every shell ``-c`` payload
    (its quotes blanked so the code reads bare), the arguments of the commands
    whose arguments are the target (kill, rm, mv ...), with their quotes
    blanked. A text that does not parse is returned unchanged (fail closed).
    """
    if not isinstance(text, str):
        return ""
    script = parse(text)
    if script.error is not None:
        return text
    out = list(text)
    _blank_comments(text, out)
    sites = list(walk(script, into=("cmdsub", "backtick", "procsub")))
    piped_code = _heredocs_piped_to_shell(sites)
    for site in sites:
        cmd = site.cmd
        res = resolve(cmd)
        name = res.name
        if name is None:
            continue
        is_shell = name in SHELLS
        for red in cmd.redirects:
            if red.hd is not None and not is_shell and id(red) not in piped_code:
                a, b = red.hd.body_span
                _blank(out, a, b, keep_newlines=True)
        if is_shell:
            if res.payload_kind == "shell_c":
                for w in res.args:
                    if w.quoted():
                        _blank_quotes(text, out, w)
            continue
        if name in _DATA_ARG_KEEP:
            for w in res.args:
                _blank_quotes(text, out, w)
            continue
        # An interpreter's plain arguments are data only where its own word is
        # the command word: behind a wrapper the view keeps them.
        script_interp = bool(_SCRIPT_INTERP_RE.match(name)) and not res.wrappers and \
            res.head is cmd.head()
        for w in res.args:
            opens_quoted = w.text[:1] in QUOTE_CHARS
            if script_interp and not opens_quoted and all(
                    p.kind == "lit" for p in w.parts) and not any(c in w.text for c in "<>()`"):
                _blank(out, *w.span)
                continue
            if not opens_quoted:
                continue
            if any(p.kind != "lit" for p in w.parts):
                for p in w.parts:
                    if p.kind == "lit" and p.quote in (SINGLE, DOUBLE):
                        _blank(out, *p.span)
                continue
            _blank(out, *w.span)
    return "".join(out)


def _heredocs_piped_to_shell(sites):
    """ids of the heredoc redirections of a pipeline stage whose output a shell
    reads as its code (`cat <<EOF | bash`, `... | /usr/bin/bash`)."""
    keep, seen = set(), set()
    for site in sites:
        if id(site.script) in seen:
            continue
        seen.add(id(site.script))
        for pl, _sep in site.script.items:
            for k in range(1, len(pl.stages)):
                nxt = pl.stages[k]
                if not isinstance(nxt, SimpleCommand):
                    continue
                res = resolve(nxt)
                if res.name in SHELLS and res.payload_kind != "shell_c" and res.stdin_shell and \
                        _stdin_redirect(nxt.redirects) is None:
                    _collect_heredocs(pl.stages[k - 1], keep)
    return keep


def _collect_heredocs(cmd, keep):
    for red in cmd.redirects:
        if red.hd is not None:
            keep.add(id(red))
    if isinstance(cmd, Compound):
        for body in cmd.body:
            for pl, _sep in getattr(body, "items", ()):
                for stage in pl.stages:
                    _collect_heredocs(stage, keep)


def without_heredoc_bodies(text):
    """``text`` without the lines of each heredoc's body and its closing line; the opener stays."""
    if not isinstance(text, str):
        return ""
    cut = []
    for site in walk(parse(text), into=("cmdsub", "backtick", "procsub", "shell_c", "eval")):
        for r in site.cmd.redirects:
            if r.hd is not None:
                a, b = r.hd.body_span
                end = text.find("\n", b) if r.hd.terminated else -1
                cut.append((max(a - 1, 0), len(text) if end < 0 else end))
    out, at = [], 0
    for a, b in sorted(cut):
        if a >= at:
            out.append(text[at:a])
        at = max(at, b)
    return "".join(out) + text[at:]


def _blank(out, a, b, keep_newlines=False):
    for k in range(max(a, 0), min(b, len(out))):
        if keep_newlines and out[k] == "\n":
            continue
        out[k] = " "


def _blank_quotes(text, out, w):
    a, b = w.span
    k = a
    while k < b and k < len(text):
        if text[k] in "'\"":
            out[k] = " "
        elif text[k] == "$" and k + 1 < b and text[k + 1] in "'\"":
            out[k] = " "
        k += 1


def _blank_comments(text, out):
    """Blank every comment, by the lexer's own rule for where one starts."""
    spans = []
    try:
        _lex_into(Src.from_raw(text), [], 0, spans)
    except LexError:
        return
    for a, b in spans:
        _blank(out, a, b)


# ---------------------------------------------------------------------------
# write_targets
# ---------------------------------------------------------------------------

TRUNCATE = "truncate"
APPEND = "append"
CREATE = "create"
LINK = "link"
COPY_DEST = "copy-dest"
MOVE_DEST = "move-dest"
DELETE = "delete"
IN_PLACE = "in-place"


class WriteTarget:
    """One path a command writes, with how.

    path: the static path text, or None when computed (decidable False);
    word: the Word it was read from; mode: truncate, append, create, link,
    copy-dest, move-dest, delete, in-place; mechanism: what writes it
    (redirect, tee, cp, mv, ...); fd: the redirected fd; source: the source
    path of a copy, move or link; context: the walk context; dirs: the directories its
    command may run in (CdScopes: '' the call's own, '?' unknown), set when
    write_targets is given the raw command.
    """

    __slots__ = ("path", "mode", "mechanism", "fd", "decidable", "word", "source", "context", "dirs")

    def __init__(self, path, mode, mechanism, fd=None, decidable=True, word=None, source=None,
                 context=("top",)):
        self.dirs = None
        self.path = path
        self.mode = mode
        self.mechanism = mechanism
        self.fd = fd
        self.decidable = decidable
        self.word = word
        self.source = source
        self.context = context

    def as_dict(self):
        return {"path": self.path, "mode": self.mode, "mechanism": self.mechanism, "fd": self.fd,
                "decidable": self.decidable, "source": self.source, "context": list(self.context)}

    def placed(self, path=None):
        """``path`` (default: the static path) where the write lands, once per directory in ``dirs``: as written
        when it is absolute or computed or its command runs in the call's own directory, joined to the directory
        a `cd` moved to, and `$(pwd)/path` where that directory is unknown, so a caller sees it is unresolved."""
        path = self.path if path is None else path
        if not path or not self.dirs or path.startswith(("/", "~", "$", "`")):
            return [path] if path else []
        return [path if d == "" else os.path.expanduser(os.path.join("$(pwd)" if d == "?" else d, path))
                for d in sorted(self.dirs)]

    def __repr__(self):
        return "WriteTarget(%r, %s, %s)" % (self.path, self.mode, self.mechanism)


_REDIR_MODE = {">": TRUNCATE, ">|": TRUNCATE, "&>": TRUNCATE, ">&": TRUNCATE,
               ">>": APPEND, "&>>": APPEND, "<>": CREATE}

WGET_OUTPUT_OPTS = ("-O", "--output-document")  # wget's option naming the file the download is written to

# Write verbs: name -> (option spec, reading). The reading names which operands
# are written and how: "all" every operand, "last" the last operand (with the
# others as sources), "first" the first operand, or an option whose value is
# the target.
VERBS = {
    "tee": (_spec(("-a", "--append", "-i", "--ignore-interrupts", "-p"),
                  ("--output-error",)), "all", TRUNCATE),
    "cp": (_spec(("-a", "--archive", "-b", "-d", "-f", "--force", "-i", "--interactive",
                  "-H", "-l", "--link", "-L", "--dereference", "-n", "--no-clobber", "-P",
                  "--no-dereference", "-p", "-R", "-r", "--recursive", "-s", "--symbolic-link",
                  "-T", "--no-target-directory", "-u", "--update", "-v", "--verbose", "-x",
                  "--one-file-system", "--parents", "--remove-destination", "--strip-trailing-slashes",
                  "--attributes-only", "--debug", "-Z", "--backup", "--preserve", "--reflink", "--context",
                  "--copy-contents", "--keep-directory-symlink", "--help", "--version"),
                 ("-t", "--target-directory", "-S", "--suffix", "--no-preserve", "--sparse")), "last", COPY_DEST),
    "mv": (_spec(("-b", "-f", "--force", "-i", "--interactive", "-n", "--no-clobber", "-T",
                  "--no-target-directory", "-u", "--update", "-v", "--verbose", "-Z",
                  "--strip-trailing-slashes", "--debug", "--exchange", "--no-copy", "--backup", "--context",
                  "--help", "--version"),
                 ("-t", "--target-directory", "-S", "--suffix")),
           "last", MOVE_DEST),
    "install": (_spec(("-b", "-C", "--compare", "-c", "-d", "--directory", "-D", "-p",
                       "--preserve-timestamps", "-s", "--strip", "-v", "--verbose", "-T",
                       "--no-target-directory", "-Z", "--backup", "--context", "--debug", "--preserve-context",
                       "--help", "--version"),
                      ("-g", "--group", "-m", "--mode", "-o", "--owner", "-S", "--suffix",
                       "-t", "--target-directory", "--strip-program")),
                "last", COPY_DEST),
    "ln": (_spec(("-b", "-d", "-F", "--directory", "-f", "--force", "-i", "--interactive",
                  "-L", "--logical", "-n", "--no-dereference", "-P", "--physical", "-r",
                  "--relative", "-s", "--symbolic", "-T", "--no-target-directory", "-v",
                  "--verbose", "--backup", "--help", "--version"),
                 ("-t", "--target-directory", "-S", "--suffix")), "last", LINK),
    "rsync": (_spec(("-a", "--archive", "-v", "--verbose", "-z", "--compress", "-r",
                     "--recursive", "-u", "--update", "-n", "--dry-run", "-q", "--quiet",
                     "-P", "-h", "--human-readable", "-c", "--checksum", "-l", "--links",
                     "-L", "-p", "--perms", "-t", "--times", "-g", "-o", "-D", "-H", "-A",
                     "-X", "-x", "-R", "--relative", "--delete", "--progress", "--partial",
                     "--inplace", "--append", "-W", "--whole-file", "-S", "--sparse",
                     "--existing", "--ignore-existing", "--remove-source-files", "-i",
                     "--itemize-changes", "-m", "--prune-empty-dirs", "-k", "-K", "-O",
                     "--stats", "--delete-after", "--delete-before", "--delete-excluded",
                     "--mkpath", "-b", "--backup"),
                    ("-e", "--rsh", "--exclude", "--include", "--exclude-from", "--include-from",
                     "-f", "--filter", "--files-from", "--rsync-path", "-T", "--temp-dir",
                     "--chmod", "--chown", "-B", "--block-size", "--log-file", "--bwlimit",
                     "--suffix", "--backup-dir", "--timeout", "--port", "--password-file",
                     "--compare-dest", "--copy-dest", "--link-dest", "--max-size",
                     "--min-size", "--partial-dir", "-M", "--remote-option", "--address", "--checksum-choice",
                     "--checksum-seed", "--compress-choice", "--compress-level", "--contimeout", "--copy-as",
                     "--debug", "--early-input", "--groupmap", "--iconv", "--info", "--log-file-format",
                     "--max-alloc", "--max-delete", "--modify-window", "--only-write-batch", "--out-format",
                     "--outbuf", "--protocol", "--read-batch", "--skip-compress", "--sockopts", "--stderr",
                     "--stop-after", "--stop-at", "--usermap", "--write-batch")), "last", COPY_DEST),
    "truncate": (_spec(("-c", "--no-create", "-o", "--io-blocks"),
                       ("-s", "--size", "-r", "--reference")), "all", TRUNCATE),
    "unlink": (_spec(), "all", DELETE),
    "rm": (_spec(("-f", "--force", "-i", "-I", "-r", "-R", "--recursive", "-d", "--dir",
                  "-v", "--verbose", "--one-file-system", "--no-preserve-root",
                  "--preserve-root"), ("--interactive",)), "all", DELETE),
    "rmdir": (_spec(("-p", "--parents", "-v", "--verbose", "--ignore-fail-on-non-empty")),
              "all", DELETE),
    "srm": (_spec(("-d", "--dod", "-D", "--doe", "-E", "--rcmp", "-f", "--force", "-i",
                   "--interactive", "-l", "--lessmode", "-r", "-R", "--recursive", "-s",
                   "--simple", "-P", "--openbsd", "-v", "--verbose", "-x",
                   "--one-file-system", "-z", "--zero")), "all", DELETE),
    "shred": (_spec(("-f", "--force", "-u", "--remove", "-v", "--verbose", "-x", "--exact",
                     "-z", "--zero"), ("-n", "--iterations", "-s", "--size")), "all", DELETE),
    "sed": (_spec(("-n", "--quiet", "--silent", "-E", "-r", "--regexp-extended", "-s",
                   "--separate", "-u", "--unbuffered", "-z", "--null-data", "--posix",
                   "--debug", "--sandbox", "--follow-symlinks"),
                  ("-e", "--expression", "-f", "--file", "-l", "--line-length")), "sed", IN_PLACE),
    "touch": (_spec(("-a", "-c", "--no-create", "-f", "-h", "--no-dereference", "-m"),
                    ("-d", "--date", "-r", "--reference", "-t", "--time")), "all", CREATE),
    "sort": (_spec(("-b", "--ignore-leading-blanks", "-d", "--dictionary-order", "-f", "--ignore-case",
                    "-g", "--general-numeric-sort", "-i", "--ignore-nonprinting", "-M", "--month-sort",
                    "-h", "--human-numeric-sort", "-n", "--numeric-sort", "-R", "--random-sort", "-r",
                    "--reverse", "-V", "--version-sort", "-c", "-C", "--check", "-m", "--merge", "-s",
                    "--stable", "-u", "--unique", "-z", "--zero-terminated", "--debug"),
                   ("-k", "--key", "-o", "--output", "-S", "--buffer-size", "-t", "--field-separator",
                    "-T", "--temporary-directory", "--batch-size", "--compress-program", "--files0-from",
                    "--parallel", "--random-source", "--sort")), "value:-o,--output", TRUNCATE),
    "uniq": (_spec(("-c", "--count", "-d", "--repeated", "-D", "--all-repeated", "--group", "-i",
                    "--ignore-case", "-u", "--unique", "-z", "--zero-terminated"),
                   ("-f", "--skip-fields", "-s", "--skip-chars", "-w", "--check-chars")), "second", TRUNCATE),
    "sponge": (_spec(("-a",)), "all", TRUNCATE),
    "perl": (None, "perl", IN_PLACE),
    "gawk": (None, "gawk", IN_PLACE),
    "dd": (_spec(), "dd", TRUNCATE),
    "curl": (_spec(), "opt:-o,--output", TRUNCATE),
    "wget": (_spec(), "opt:" + ",".join(WGET_OUTPUT_OPTS), TRUNCATE),
    "chmod": (None, "attr", IN_PLACE),
    "chown": (None, "attr", IN_PLACE),
    "chgrp": (None, "attr", IN_PLACE),
    "chattr": (None, "attr", IN_PLACE),
    "setfacl": (None, "attr", IN_PLACE),
}
VERBS["gsed"] = VERBS["sed"]  # GNU sed's name where sed is another one
# The copy, move and link verbs: cp and mv (CP_MV), the copiers (COPY_VERBS: cp, install), the
# coreutils that define -t/--target-directory (TARGET_DIR_VERBS), and those whose destination may be
# a directory the sources land in (INTO_DIR_VERBS: rsync too).
CP_MV = ("cp", "mv")
COPY_VERBS = ("cp", "install")
TARGET_DIR_VERBS = ("cp", "mv", "install", "ln")
INTO_DIR_VERBS = TARGET_DIR_VERBS + ("rsync",)
# cp, mv, ln and install's option that names the destination directory (every guard reads this one).
TARGET_DIR_OPTS = ("-t", "--target-directory")
NO_TARGET_DIR_OPTS = ("-T", "--no-target-directory")  # the destination is the written file, never a directory
INSTALL_DIR_OPTS = ("-d", "--directory")  # install makes every operand a directory (no source)
TAR_NAMES = ("tar", "bsdtar", "gtar")  # the program names that are tar
AWK_NAMES = ("awk", "gawk", "mawk", "nawk")  # the program names that are awk
GREP_NAMES = ("grep", "egrep", "fgrep")  # the program names that are grep
PYTHON_NAMES = ("python", "pypy")  # the names a Python interpreter starts with (python3.12, pypy3)
SED_SCRIPT_OPTS = ("-e", "--expression")  # sed: the option whose value is a script
SED_QUIET_OPTS = ("-n", "--quiet", "--silent")  # sed: print only what the script prints
SORT_OUTPUT_OPTS = ("-o", "--output")  # sort: the option whose value is the file it writes
GIT_REDIRECT_ENV_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")  # move git to another repository
GIT_MESSAGE_OPTS = ("-m", "--message")  # git commit, tag, stash: the option whose value is the message
FIND_NAME_TESTS = ("-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename")  # find: match a name glob
# The host names that are the local machine as a network client's destination (0.0.0.0 connects to it on
# Linux; ::1 is bare in a socket client's arguments and bracketed in a URL).
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]", "::1", "0.0.0.0")
# awk's options that take a value (POSIX awk and gawk), by what the value is:
AWK_DATA_OPTS = ("-F", "--field-separator", "-v", "--assign")  # a separator or an assignment
AWK_SOURCE_OPTS = ("-e", "--source")  # program text
AWK_PROGFILE_OPTS = ("-f", "--file", "-E", "--exec")  # a file holding the program
AWK_LIB_OPTS = ("-i", "--include", "-l", "--load")  # a source library or extension it loads
AWK_VALUE_OPTS = AWK_DATA_OPTS + AWK_SOURCE_OPTS + AWK_PROGFILE_OPTS + AWK_LIB_OPTS
# ripgrep: the options whose value is a program it runs, and every option that makes it run
# one (--search-zip, short -z, runs the decompressors; --pre-glob selects the files a --pre
# preprocessor, perhaps from a config file, is run on).
RG_PROGRAM_OPTS = ("--pre", "--hostname-bin")
# grep's (and rg's) options that carry the pattern, and a file of patterns; their long forms.
GREP_PATTERN_OPTS = ("-e", "--regexp")
GREP_PATTERN_FILE_OPTS = ("-f", "--file")
GREP_PATTERN_LONG = (GREP_PATTERN_OPTS[1], GREP_PATTERN_FILE_OPTS[1])
# Environment variables an assignment to which cannot change what a command runs (locale, terminal,
# identity, colour); the directory ones among them (DIR_ENV_VARS) do move where a command reads or writes.
INERT_ENV_VARS = frozenset({
    "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_COLLATE", "LC_MESSAGES", "LC_NUMERIC", "LC_TIME", "TZ", "TERM",
    "COLUMNS", "LINES", "PWD", "OLDPWD", "USER", "LOGNAME", "HOSTNAME", "TMPDIR", "DISPLAY", "NO_COLOR",
    "FORCE_COLOR", "CLICOLOR", "CLICOLOR_FORCE"})
DIR_ENV_VARS = frozenset({"PWD", "OLDPWD", "TMPDIR"})
# man's options whose value names a program it runs (man-db 2.12: the pager, the HTML browser).
MAN_PROGRAM_OPTS = ("-P", "--pager", "-H", "--html", "-B", "--browser")
# grep's options that take a value (GNU grep 3.11 --help; --color[=WHEN] takes one only after `=`): those
# every grep-like search shares, then GNU grep's own.
GREP_CORE_VALUE_OPTS = GREP_PATTERN_OPTS + GREP_PATTERN_FILE_OPTS + (
    "-m", "--max-count", "-A", "--after-context", "-B", "--before-context", "-C", "--context")
GREP_VALUE_OPTS = GREP_CORE_VALUE_OPTS + ("-d", "--directories", "-D", "--devices", "--binary-files", "--include",
                                          "--exclude", "--exclude-dir", "--exclude-from", "--label",
                                          "--group-separator")
RG_RUN_OPTS = RG_PROGRAM_OPTS + ("--search-zip", "--pre-glob")
# ripgrep's options that take a value: the short letters and the long names.
RG_VALUE_SHORT = frozenset("efgtTmABCMjrEd")
RG_VALUE_LONG = frozenset((
    "--regexp", "--file", "--glob", "--iglob", "--type", "--type-not", "--max-count", "--after-context",
    "--before-context", "--context", "--max-columns", "--threads", "--pre", "--pre-glob", "--type-add",
    "--type-clear", "--replace", "--colors", "--encoding", "--sort", "--sortr", "--max-depth", "--maxdepth",
    "--max-filesize", "--path-separator", "--ignore-file", "--dfa-size-limit", "--regex-size-limit",
    "--context-separator", "--field-match-separator", "--field-context-separator", "--engine", "--hostname-bin",
    "--hyperlink-format", "--color", "--generate"))
VERBS["awk"] = VERBS["gawk"]  # where awk is gawk, `awk -i inplace` edits in place

# The commands that change a file's mode, owner, attributes or ACL: the file
# keeps its bytes, but `chmod -x` of a hook turns the hook off, so each path
# operand is written in place. Per verb: the short flags (letters that take no
# value), the short options that take a value, the long options that take one
# (`--opt V` or `--opt=V`), and how a non-path operand is told apart: "first"
# (chmod's mode, chown's owner: the first operand unless --reference names the
# file to copy it from) or "signed" (chattr's modes: words starting + - =).
_ATTR_VERBS = {
    "chmod": ("cfvR", "", ("--reference",), "first"),
    "chown": ("cfvhHLPR", "", ("--from", "--reference"), "first"),
    "chgrp": ("cfvhHLPR", "", ("--reference",), "first"),
    "chattr": ("RVf", "vp", (), "signed"),
    "setfacl": ("bkndRLPvh", "mMxX",
                ("--modify", "--modify-file", "--remove", "--remove-file", "--set", "--set-file",
                 "--restore"), ""),
}


def _attr_operands(name, args):
    """The path operand words of one chmod / chown / chattr / setfacl."""
    flags, short_values, long_values, kind = _ATTR_VERBS[name]
    operands = []
    referenced = skip = ended = False
    for w in args:
        t = w.value()
        if t is None:
            t = w.static_prefix() or "$"
        if skip:
            skip = False
        elif ended or t == "-" or not t.startswith(("-", "+", "=")):
            operands.append(w)
        elif t == "--":
            ended = True
        elif t.startswith("--"):
            opt = t.split("=", 1)[0]
            referenced = referenced or opt == "--reference"
            skip = opt in long_values and "=" not in t
        elif t[0] == "-" and set(t[1:]) <= set(flags):
            continue
        elif t[0] == "-" and short_values and t[1] in flags + short_values:
            k = next((i for i, c in enumerate(t[1:], 1) if c in short_values), 0)
            skip = bool(k) and k == len(t) - 1
        elif kind == "first":
            operands.append(w)
    if kind == "first" and not referenced:
        operands = operands[1:]
    return operands



class CdScopes:
    """Where each part of the command runs: the possible (cwd, OLDPWD) pairs at each simple command,
    a `cd` applied only to what follows it in its own shell (not past a closing subshell, a pipeline
    stage or a background job, replaced by a later cd, `&&` and `||` followed), relative to the
    starting directory ''. A cd that cannot be followed exactly (`cd -` with no known OLDPWD, a
    computed target, CDPATH, popd, the body of a function the command defines but never calls where it is
    followed, more than LIMIT possibilities) leaves the unknown directory '?'. A brace group, loop, if or case body
    runs in the shell's own directory, and so do a compound's own redirections; a function called in the command
    runs its body where it is called.
    ``spell(word)`` is a cd operand's text (default: its static value, else as written, quotes removed);
    ``reached(dir)`` says a directory is there now, so one `cd` to it cannot fail (default: any cd may fail)."""

    UNKNOWN = ('?', '?')
    LIMIT = 64

    def __init__(self, raw: str, spell=None, reached=None):
        self.raw, self.spans, self.visited, self.unfollowed = raw, [], set(), []
        self.defs, self.calling = {}, set()  # functions defined in the command; those being followed
        self.cdpath = 'CDPATH' in raw
        self.functions = False  # a function or coprocess defined anywhere it walked
        self.spell = spell or (lambda w: w.text.replace('"', '').replace("'", '') if w.value() is None else w.value())
        self.reached = reached or (lambda d: False)

    def _target(self, cwd: str, word) -> str:
        arg = self.spell(word) if word is not None else '~'
        if any(c in arg for c in '$`*?[') or (self.cdpath and not arg.startswith(('/', '~', './', '../'))):
            return '?'
        if arg.startswith(ROOTED):
            return os.path.normpath(arg)
        if cwd == '?':
            return '?'
        target = os.path.normpath(os.path.join(cwd, arg)) if cwd else os.path.normpath(arg)
        return '' if target == '.' else target

    def _cd(self, name: str, args, states) -> tuple:
        """(the states after the cd, the states it may have failed in: all but those whose one operand is reached)."""
        if name == 'popd':
            return {self.UNKNOWN}, set(states)
        ops, k = [], 0
        while k < len(args):
            v = args[k].value()
            if v == '--':
                ops += args[k + 1:]
                break
            if v is None or v == '-' or not v.startswith('-') or v[1:2].isdigit() or v[1:2] == '+':
                ops.append(args[k])
            k += 1
        new, failed = set(), set(states)
        for cwd, old in states:
            if ops and ops[0].value() == '-' or (name == 'pushd' and not ops):
                new.add((old, cwd) if old != '?' else ('?', cwd))
            elif ops and (ops[0].value() or '').startswith(OPTION_SIGNS):
                new.add(self.UNKNOWN)  # a pushd/cd stack index
            else:
                new.add((self._target(cwd, ops[0] if ops else None), cwd))
                if len(ops) == 1 and self.reached(self._target(cwd, ops[0])):
                    failed.discard((cwd, old))
        return new, failed

    def _record(self, span, states):
        self.spans.append((span[0], span[1], frozenset(states)))

    def run_cmd(self, cmd, states):
        if isinstance(cmd, SimpleCommand):
            self.visited.add(cmd.span)
            res = resolve(cmd)
            here = set(states)
            for wname, opts in res.wrappers:
                for opt, val in opts:
                    if wname == 'env' and opt in ('-C', '--chdir') and val is not None:
                        here = {(self._target(cwd, val), cwd) for cwd, _old in here}
            self._record(cmd.span, here | set(states))  # its redirections open where the shell is
            if res.name in self.defs and res.name not in self.calling and res.payload is None:
                # a function defined in this command runs its body where it is called
                self.calling.add(res.name)
                succ, fail = set(), set()
                for s in self.defs[res.name]:
                    s_succ, s_fail = self.run_script(s, states)
                    succ, fail = succ | s_succ, fail | s_fail
                self.calling.discard(res.name)
                return succ, fail
            for r in cmd.redirects:
                if r.hd is not None:  # an unquoted body's substitutions run where its command does
                    self._record(r.hd.body_span, set(states))
            if res.name in CWD_BUILTINS and res.payload is None:
                return self._cd(res.name, res.args, states)
            if res.payload is not None:
                if res.payload_kind == 'eval':
                    return self.run_script(res.payload, states)
                self.run_script(res.payload, {self.UNKNOWN} if _runs_elsewhere(res) else here)
            return set(states), set(states)
        if isinstance(cmd, Compound):
            self.visited.add(cmd.span)  # its own redirections (`(...) > f`) run where it starts
            self._record(cmd.span, states)
            for r in cmd.redirects:
                if r.target is not None:
                    self._record(r.target.span, states)
            scripts = [s for s in tuple(cmd.header) + tuple(cmd.body) if isinstance(s, Script)]
            self.functions = self.functions or cmd.kind in DEFINER_KINDS
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
                self.defs[cmd.name] = scripts  # followed where it is called; never called: see run()
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
            if len(enter) > self.LIMIT:
                enter = {self.UNKNOWN}
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

    def run(self, script, start=''):
        """Follow ``script`` from ``start``; a `cd` it did not follow (in a substitution, a re-parsed payload) makes
        the directory of everything written after it unknown."""
        self.run_script(script, {(start, '?')})
        for name, scripts in self.defs.items():  # a body called nowhere it was followed: run where it may be
            if not any(s.span[0] <= a < s.span[1] for s in scripts for a, _b, _st in self.spans):
                for s in scripts:
                    self._record(s.span, {self.UNKNOWN})
                    self.run_script(s, {self.UNKNOWN})
        self.unfollowed = [s.cmd.span[0] if self.raw[slice(*s.cmd.span)].startswith(s.cmd.words[0].text) else 0
                           for s in walk(script) if s.cmd.words and s.cmd.span not in self.visited
                           and resolve(s.cmd).name in CWD_BUILTINS]
        return self

    def of(self, word) -> set:
        """The possible directories of the command ``word`` is written in; '?' when the word is not its own text
        in the command (an alias, a re-read payload) or follows an unfollowed cd."""
        if word is None or self.raw[slice(*word.span)] != word.text:
            return {'?'}
        return self.at(word.span[0]) | ({'?'} if any(word.span[0] > u for u in self.unfollowed) else set())

    def at(self, offset: int):
        """The possible directories at raw ``offset``: the innermost recorded command around it."""
        best, found = None, set()
        for a, b, states in self.spans:
            if a <= offset < b and (best is None or b - a <= best):
                found = (found if best == b - a else set()) | set(states)
                best = b - a
        return {cwd for cwd, _old in found} if best is not None else {'?'}



_PKG_MANAGERS = frozenset({
    "pip", "pip3", "npm", "pnpm", "yarn", "apt", "apt-get", "aptitude", "yum",
    "dnf", "apk", "zypper", "pacman", "brew", "cargo", "gem", "go", "poetry",
    "uv", "conda", "bundle", "composer", "nix-env", "opkg", "stack", "mix",
})


def write_targets(script, *, into=_DEFAULT_INTO, env=None, raw=None, reached=None):
    """Every path ``script`` writes, from redirections and from the VERBS table.

    Given the raw command (``raw``, or ``script`` as text), each target carries the
    directories its command may run in (``dirs``, by CdScopes; ``reached`` as there, never
    trusted in a command that removes or moves something).

    An assignment earlier in the same list (`X=/p; ... > $X`) projects into a
    later `$X` / `${X}` target when its value is static or projects itself.
    ``env`` gives the values of variables the caller knows before the command.
    A command whose name is computed and whose operands name a copy or a move
    (`"$CP" cp-01 dest`) is read as that copy: its last operand is the destination.
    Any other computed command word names each operand as an undecidable target
    (mechanism ``computed-command``, path known where the operand is static), and
    one with no operand names the head word itself: the verb is unknown.
    The redirections of a compound command come from walk's redirect-only Site.
    """
    if isinstance(script, str):
        raw, script = script, parse(script)
    out = []
    seed = dict(env or {})
    envs, exported, prefix = {}, set(), {}
    scope = _AssignScope(script)
    carriers, carrier = {}, None   # target -> the raw command whose payload it was read from
    for site in walk(script, into=into):
        first = len(out)
        env = None
        try:
            cmd = site.cmd
            if raw is not None:
                carrier = _payload_carrier(site, raw, carrier)
            # A shell started with -c or fed code sees the caller's variables, the ones exported before
            # it and its own command's prefix assignments; a templated payload's expansions are the
            # outer shell's.
            fresh = 0 if site.templated else max(
                (k for k, c in enumerate(site.context) if c in ("shell_c", "heredoc_shell", "pipe_shell")), default=0)
            key = site.context[:fresh + 1]
            if key not in envs:
                envs[key] = dict(seed)
                if fresh:
                    outer = envs.get(site.context[:fresh], {})
                    envs[key].update((k, v) for k, v in outer.items() if k in exported)
                    envs[key].update(prefix.get(site.context[:fresh], {}))
            env = envs[key]
            if cmd.words:
                for k in [k for k in envs if len(k) > len(site.context) and k[:len(site.context)] == site.context]:
                    del envs[k]
                prefix[site.context] = {a.name: v for a in cmd.assignments
                                        for v in [_assigned(a, env)] if v is not None}
            _track_assignments(site, cmd, env, seed, exported, scope)
            for red in cmd.redirects:
                if red.target is None or not red.writes():
                    continue
                if any(p.kind.startswith("procsub") for p in red.target.parts):
                    continue
                path, decidable = _project(red.target, env)
                if red.op == ">&" and path is not None and _digits(path):
                    continue
                mode = _REDIR_MODE.get(red.op, TRUNCATE)
                out.append(WriteTarget(path, mode, "redirect" + red.op, red.fd, decidable,
                                       red.target, None, site.context))
            res = resolve(cmd)
            name = res.name
            if name is None:
                if res.unresolved == "dynamic_head" and len(res.args) > 1 and any(
                        _COPY_MOVE_WORD_RE.match(w.value() or "") for w in res.args):
                    for t in _verb_targets("cp", VERBS["cp"], res.args, env, site.context):
                        t.decidable = False
                        out.append(t)
                elif res.head is not None:
                    # the verb is unknown: every operand may be written
                    ops = [w for w in res.args if not (w.value() or "").startswith("-")]
                    for word in ops or [res.head]:
                        path = _project(word, env)[0] if ops else None
                        out.append(WriteTarget(path, TRUNCATE, "computed-command", None, False,
                                               word, None, site.context))
                continue
            if name == "git":
                out.extend(_git_write_targets(res, env, site.context))
                continue
            if name == "find":
                out.extend(_find_write_targets(res.args, env, site.context))
                continue
            verb = VERBS.get(name)
            if verb is None:
                continue
            if name == "install" and _preceded_by_pkg_manager(cmd, res):
                continue
            if (res.unresolved or "").startswith("xargs_appends"):
                # the operands come from xargs's input: the verb writes something unknown
                out.append(WriteTarget(None, verb[2], name, None, False, res.head, None, site.context))
            found = [t for t in _verb_targets(name, verb, res.args, env, site.context)
                     if not any(p.kind.startswith("procsub") for p in t.word.parts)]
            if verb[1] == "last" and _appends_args(res):
                # xargs appends words: any operand may be a source or the
                # destination, so every role is undecidable, and a move may remove
                # what reads as its destination.
                for t in found:
                    t.decidable = False
                if name == "mv":
                    found += [WriteTarget(t.path, DELETE, "mv-source", None, False, t.word, None,
                                          site.context) for t in found if t.mode == MOVE_DEST]
            out.extend(found)
        finally:
            for t in out[first:] if env is not None else ():
                _carry_word(t, env)
            for t in out[first:] if raw is not None else ():
                carriers[id(t)] = carrier
    if raw is not None and out:
        gone = any(t.mode in (DELETE, MOVE_DEST) for t in out)
        scopes = CdScopes(raw, lambda w: _project(w, seed)[0] or w.text, None if gone else reached).run(script)
        for t in out:
            t.dirs = scopes.of(t.word)
            word = carriers.get(id(t))
            if t.dirs == {'?'} and word is not None and t.word is not None \
                    and raw[slice(*t.word.span)] != t.word.text:
                t.dirs = scopes.of(word)
    return out


def _payload_carrier(site, raw, carrier):
    """The first word of the raw command whose re-read payload (eval, env -S, a here-string or alias
    a shell reads, find -exec ...) ``site`` belongs to, as long as that code runs in the directory
    that command runs in; None once it may not: ssh runs it on another host, find -execdir or
    -okdir in each match's directory, and a cd, pushd or popd read from the payload moves it."""
    words = site.cmd.words
    if words and raw[slice(*words[0].span)] == words[0].text:
        return None if _runs_elsewhere(resolve(site.cmd)) else words[0]
    if words and resolve(site.cmd).name in CWD_BUILTINS + ("ssh",):
        return None
    return carrier


def _runs_elsewhere(res):
    """True when the code ``res`` hands on runs in another directory than its own command: ssh on
    another host, find's -execdir and -okdir in each match's directory."""
    return res.name == "ssh" or (res.name == "find" and any(w.value() in FIND_EXEC_IN_MATCH_DIR
                                                            for w in res.args))


_COPY_MOVE_WORD_RE = re.compile(r"(?:%s)(?!\w)" % "|".join(CP_MV))


def _appends_args(res):
    """True when xargs appends words after the written operands, so the last is no destination."""
    return any(name == "xargs" and not any(o in XARGS_REPLACE_OPTS or (o or "").startswith("--replace=")
                                           for o, _v in opts)
               for name, opts in res.wrappers)


# Commands that may set a shell variable in a way the parser does not follow: after one, only the
# caller's variables project.
_STATE_BUILTINS = frozenset({"read", "mapfile", "readarray", "declare", "typeset", "local", "readonly",
                             "unset", "printf", "eval", "source", ".", "getopts", "let", "export"})


class _AssignScope:
    """Which scripts are a compound's body, and which names are functions."""

    def __init__(self, script):
        self.seen, self.bodies, self.functions = set(), set(), set()
        self.scan(script)

    def scan(self, script):
        if id(script) in self.seen:
            return
        self.seen.add(id(script))
        for pl, _sep in script.items:
            for st in pl.stages:
                if isinstance(st, Compound):
                    if st.kind == "function" and st.name:
                        self.functions.add(st.name if isinstance(st.name, str) else str(st.name))
                    for body in st.body:
                        self.bodies.add(id(body))
                        self.scan(body)

    def certain(self, site, cmd):
        """True when an assignment in ``cmd`` surely holds after it: run unconditionally, not in
        a compound's body, a pipeline or the background."""
        self.scan(site.script)
        if id(site.script) in self.bodies:
            return False
        before = None
        for pl, sep in site.script.items:
            if any(st is cmd for st in pl.stages):
                return len(pl.stages) == 1 and sep != "&" and before not in AND_OR_OPS
            before = sep
        return False


def _assigned(a, env):
    """The value an assignment gives: static text, or the value Word itself
    when it is computed (`T=$HOME/x`), so a projected `$T` carries its parts."""
    v = a.static_value()
    if v is None and a.value is not None:
        v, dec = _project(a.value, env)
        v = v if dec else a.value
    return None if a.append else v


def _track_assignments(site, cmd, env, seed, exported, scope):
    if not cmd.words:
        for a in cmd.assignments:
            v = _assigned(a, env)
            if v is not None and scope.certain(site, cmd):
                env[a.name] = v
            else:
                env.pop(a.name, None)
        return
    name = basename(cmd.words[0].value() or "")
    if name == "printf" and not any((w.value() or "-v").startswith("-v") for w in cmd.words[1:]):
        return
    if name in _STATE_BUILTINS or name in scope.functions:
        if name == "export" and scope.certain(site, cmd):
            for w in cmd.words[1:]:
                m = _ASSIGN_PARTS_RE.match(w.raw.text)
                if m and not m.group(2) and not m.group(3):
                    a = Assignment(w)
                    v = _assigned(a, env)
                    exported.add(a.name)
                    if v is not None:
                        env[a.name] = v
                    else:
                        env.pop(a.name, None)
                elif w.value() and _NAME_RE.match(w.value()):
                    exported.add(w.value())
                else:
                    env.clear()
                    env.update(seed)
            return
        env.clear()
        env.update(seed)


def _preceded_by_pkg_manager(cmd, res):
    words = list(cmd.words)
    if res.head in words:
        k = words.index(res.head)
        if k > 0 and basename(words[k - 1].value() or "") in _PKG_MANAGERS:
            return True
    return False


def _project(word, env):
    v = word.value()
    if v is not None:
        return v, True
    out = []
    for p in word.parts:
        if p.kind == "lit":
            out.append(p.text)
            continue
        if p.kind == "param" and _NAME_RE.match(p.text) and isinstance(env.get(p.text), str):
            out.append(env[p.text])
            continue
        return None, False
    return "".join(out), True


def _carry_word(t, env):
    """A target written as `$T` / `${T}` where T holds a computed Word takes that Word."""
    w = t.word
    if t.path is None and w is not None and len(w.parts) == 1 and w.parts[0].kind == "param":
        v = env.get(w.parts[0].text)
        if isinstance(v, Word):
            t.word = v


def _verb_targets(name, verb, args, env, context):
    spec, reading, mode = verb
    out = []
    if reading == "dd":
        source = None
        for w in args:
            v = w.value() or ""
            if v.startswith("if="):
                source = v[3:]
        for w in args:
            v = w.value()
            if v is not None and v.startswith("of=") and v[3:]:
                out.append(WriteTarget(v[3:], TRUNCATE, "dd-of", None, True, w, source, context))
            elif v is None and w.static_prefix().startswith("of="):
                out.append(WriteTarget(None, TRUNCATE, "dd-of", None, False, w, source, context))
        return out
    if reading == "attr":
        for w in _attr_operands(name, args):
            path, dec = _project(w, env)
            out.append(WriteTarget(path, mode, name, None, dec, w, None, context))
        return out
    if reading.startswith("opt:"):
        short, long_opt = reading[4:].split(",")
        for w, path, dec in _flag_values(args, short, long_opt, env):
            out.append(WriteTarget(path, mode, name + "-output", None, dec, w, None, context))
        return out
    if reading in ("perl", "gawk"):
        for w in (_perl_in_place if reading == "perl" else _gawk_in_place)(args):
            path, dec = _project(w, env)
            out.append(WriteTarget(path, IN_PLACE, reading + "-in-place", None, dec, w, None, context))
        return out
    if reading == "sed":
        in_place = False
        script_given = False
        operands = []
        k = 0
        while k < len(args):
            w = args[k]
            v = w.value()
            if v is not None and (v == "-i" or v.startswith("--in-place") or
                                  (v.startswith("-") and not v.startswith("--") and "i" in v[1:]
                                   and not v[1:].startswith(("e", "f", "l")))):
                in_place = True
                k += 1
                continue
            if v in SED_SCRIPT_GIVEN_OPTS + ("-l", "--line-length"):
                script_given = script_given or v in SED_SCRIPT_GIVEN_OPTS
                k += 2
                continue
            if v is not None and v.startswith(SED_SCRIPT_ATTACHED):
                script_given = True
                k += 1
                continue
            if v is not None and v.startswith("-") and v != "-":
                k += 1
                continue
            operands.append(w)
            k += 1
        if not in_place:
            return out
        if not script_given and operands:
            operands = operands[1:]
        for w in operands:
            path, dec = _project(w, env)
            out.append(WriteTarget(path, IN_PLACE, "sed-in-place", None, dec, w, None, context))
        return out
    opts, operands, err = split_options(list(args), spec, 0, permute=True)
    if err:
        # An option this table does not know: every non-option word may be a
        # target, and none of them is decidable.
        out.extend(WriteTarget(_project(w, env)[0], mode, name, None, False, w, None, context)
                   for w in args if not (w.value() or "").startswith("-"))
        return out
    target_dir = [v for o, v in opts if o in TARGET_DIR_OPTS]
    if name == "tee":
        append = any(o in ("-a", "--append") for o, _v in opts)
        for w in operands:
            path, dec = _project(w, env)
            out.append(WriteTarget(path, APPEND if append else TRUNCATE,
                                   "tee-append" if append else "tee", None, dec, w, None, context))
        return out
    if name == "truncate":
        for w in operands:
            path, dec = _project(w, env)
            out.append(WriteTarget(path, TRUNCATE, "truncate", None, dec, w, None, context))
        return out
    if reading.startswith("value:"):
        for o, w in opts:
            if o in reading[6:].split(",") and w is not None:
                path, dec = _project(w, env)
                out.append(WriteTarget(path, mode, name + "-output", None, dec, w, None, context))
        return out
    if reading == "second":
        for w in operands[1:2]:
            if w.value() != "-":
                path, dec = _project(w, env)
                out.append(WriteTarget(path, mode, name + "-output", None, dec, w, None, context))
        return out
    if reading == "all":
        for w in operands:
            path, dec = _project(w, env)
            out.append(WriteTarget(path, mode, name, None, dec, w, None, context))
        return out
    if reading == "last":
        if name == "install" and any(o in INSTALL_DIR_OPTS for o, _v in opts):
            for w in operands:
                path, dec = _project(w, env)
                out.append(WriteTarget(path, CREATE, name, None, dec, w, None, context))
            return out
        if target_dir:
            dest = target_dir[-1]
            sources = operands
        elif operands:
            dest = operands[-1]
            sources = operands[:-1]
        else:
            return out
        path, dec = _project(dest, env)
        src_text = None
        if len(sources) == 1:
            src_text = _project(sources[0], env)[0]
        out.append(WriteTarget(path, mode, name, None, dec and not err, dest, src_text, context))
        if name == "mv" or (name == "rsync" and any(o == "--remove-source-files" for o, _ in opts)):
            for s in sources:
                sp, sdec = _project(s, env)
                out.append(WriteTarget(sp, DELETE, name + "-source", None, sdec, s, None, context))
    return out


def _find_write_targets(args, env, context):
    """The file each -fprint, -fprint0, -fprintf and -fls of one find writes. An -exec's words up to `;` or `+` are
    another command's (walk reads them); -delete removes the matches, names the command does not hold: no target."""
    out, k = [], 0
    while k < len(args):
        v = args[k].value()
        if v in FIND_EXEC:
            while k < len(args) and args[k].value() not in FIND_EXEC_ENDS:
                k += 1
        elif v in _FIND_FILE and k + 1 < len(args):
            k += 1
            path, dec = _project(args[k], env)
            out.append(WriteTarget(path, TRUNCATE, "find" + v, None, dec, args[k], None, context))
        k += 1
    return out


def perl_operands(args):
    """(in_place, code words, file operands) of one perl call: -i set in a cluster before its
    e/E code letter; the -e/-E code words; the operands after the code (after the script file
    operand when no -e/-E is given). The one reading of perl's command line."""
    inplace, code, k = False, [], 0
    while k < len(args):
        v = args[k].value() or ""
        if v == "--":
            k += 1
            break
        if not v.startswith("-") or v == "-":
            break
        if v == "-I":  # `-I dir`: the directory is the option's value, not the script
            k += 2
            continue
        flags = v[1:]
        if not v.startswith("--") and flags[:1] not in ("M", "m", "I", "x", "C", "d", "D"):
            inplace = inplace or "i" in re.split(r"[eE]", flags, 1)[0]
            if flags[-1:] in ("e", "E") and k + 1 < len(args):
                code.append(args[k + 1])
                k += 2
                continue
        k += 1
    return inplace, code, args[k:] if code else args[k + 1:]


def _perl_in_place(args):
    """The files `perl -i` edits in place."""
    inplace, _code, operands = perl_operands(args)
    return operands if inplace else []


def _gawk_in_place(args):
    """The files `gawk -i inplace` (also -iinplace, --include=inplace) edits: its file operands
    (not var=value), after the program text unless -e, -f or -E gave the program."""
    vals = [w.value() or "" for w in args]
    if not any(v in ("-iinplace", "--include=inplace") or (v in ("-i", "--include") and nxt == "inplace")
               for v, nxt in zip(vals, vals[1:] + [""])):
        return []
    given, operands, k = False, [], 0
    while k < len(args):
        v, k = vals[k], k + 1
        if v == "--":
            operands += args[k:]
            break
        if v in AWK_VALUE_OPTS:
            given, k = given or v in AWK_SOURCE_OPTS + AWK_PROGFILE_OPTS, k + 1
        elif v.startswith("-") and v != "-":
            given = given or v.startswith(("-e", "-f", "-E", "--source=", "--file=", "--exec="))
        else:
            operands.append(args[k - 1])
    return [w for w in operands[0 if given else 1:] if not _ASSIGN_RE.match(w.value() or "") and w.value() != "-"]


def _flag_values(args, short, long_opt, env):
    letter = short[1:]
    out = []
    take_next = False
    for w in args:
        v = w.value()
        if take_next:
            take_next = False
            if v is None or not v.startswith("-"):
                path, dec = _project(w, env)
                out.append((w, path, dec))
            continue
        if v is None:
            continue
        if v == short or v == long_opt:
            take_next = True
        elif v.startswith(long_opt + "="):
            if v[len(long_opt) + 1:]:
                out.append((w, v[len(long_opt) + 1:], True))
        elif v.startswith("-") and not v.startswith("--") and letter in v[1:]:
            attached = v[v.index(letter, 1) + 1:]
            if attached:
                out.append((w, attached, True))
            else:
                take_next = True
    return out


def _git_discarded_paths(sub, args, env, context):
    """The files a forced `git clean`, `checkout-index` or `stash push` names (none for a whole-tree form)."""
    vals = [a.value() for a in args]
    if None in vals:
        return []
    dd = vals.index("--") if "--" in vals else len(vals)
    head, tail = vals[:dd], list(args[dd + 1:])
    shorts = "".join(v[1:] for v in head if v.startswith("-") and not v.startswith("--"))
    kind = TRUNCATE
    if sub == "clean":
        if not ("--force" in head or "f" in shorts) or "--dry-run" in head or "n" in shorts:
            return []
        kind, skip = DELETE, ("-e", "--exclude")
    elif sub == "checkout-index":
        skip = ()
    elif head[:1] == ["push"] or (not head and tail):
        skip, head = ("-m", "--message", "--pathspec-from-file"), head[1:]
        args = args[1:] if vals[:1] == ["push"] else args
    else:
        return []
    ops, k = [], 0
    while k < len(head):
        v = head[k]
        if v in skip:
            k += 1
        elif not v.startswith("-"):
            ops.append(args[k])
        k += 1
    return [WriteTarget(path, kind, "git-" + sub, None, dec, w, None, context)
            for w in ops + tail for path, dec in [_project(w, env)]]


def _git_write_targets(res, env, context):
    out = []
    for inv in _git_from_resolved(res, context):
        sub = inv.subcommand
        args = inv.arg_words
        if sub in GIT_MV_RM:
            vals = [a.value() for a in args]
            resolved = list(inv.args)
            if sub == "rm" and "--cached" in resolved[:vals.index("--") if "--" in vals else len(vals)]:
                continue
            dd = vals.index("--") if "--" in vals else len(vals)
            ops = [a for a in args[:dd] if (a.value() or "x")[:1] != "-"] + list(args[dd + 1:])
            if sub == "rm":
                for w in ops:
                    path, dec = _project(w, env)
                    out.append(WriteTarget(path, DELETE, "git-rm", None, dec, w, None, context))
            elif ops:
                path, dec = _project(ops[-1], env)
                out.append(WriteTarget(path, MOVE_DEST, "git-mv", None, dec, ops[-1], None, context))
                for w in ops[:-1]:
                    sp, sdec = _project(w, env)
                    out.append(WriteTarget(sp, DELETE, "git-mv-source", None, sdec, w, None, context))
        elif sub in GIT_WORKTREE_DISCARDERS - GIT_RESTORE_PATHS:
            out += _git_discarded_paths(sub, args, env, context)
        elif sub in GIT_RESTORE_PATHS:
            vals = [a.value() for a in args]
            if sub == "checkout":
                if "--" not in vals:
                    continue
                paths = args[vals.index("--") + 1:]
            else:
                if "--staged" in vals and "--worktree" not in vals and "-W" not in vals:
                    continue
                paths = []
                after = False
                k = 0
                while k < len(args):
                    v = vals[k]
                    if after:
                        paths.append(args[k])
                    elif v == "--":
                        after = True
                    elif v in GIT_RESTORE_SOURCE_OPTS:
                        k += 1
                    elif v is not None and v.startswith("-"):
                        pass
                    else:
                        paths.append(args[k])
                    k += 1
            for w in paths:
                path, dec = _project(w, env)
                out.append(WriteTarget(path, TRUNCATE, "git-" + sub, None, dec, w, None, context))
    return out


# ---------------------------------------------------------------------------
# git_invocations
# ---------------------------------------------------------------------------

GIT_GLOBAL_VALUE_OPTS = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
    "--config-env", "--attr-source", "--shallow-file",
})
GIT_GLOBAL_FLAGS = frozenset({
    "-p", "--paginate", "-P", "--no-pager", "--bare", "--no-replace-objects",
    "--literal-pathspecs", "--no-literal-pathspecs", "--glob-pathspecs",
    "--noglob-pathspecs", "--icase-pathspecs", "--no-optional-locks",
    "--no-lazy-fetch", "--no-advice", "--html-path", "--man-path", "--info-path",
    "-v", "--version", "-h", "--help", "--exec-path", "--list-cmds",
})
# The global options that move where git finds the repository or the working tree.
GIT_LOCATION_OPTS = frozenset({"-C", "--git-dir", "--work-tree"})
# The global options that point git at another repository, work tree or ref namespace than its directory.
GIT_REDIRECT_OPTS = (GIT_LOCATION_OPTS - {"-C"}) | {"--namespace"}
# The global flags that change only how a pathspec matches.
GIT_PATHSPEC_FLAGS = frozenset({
    "--literal-pathspecs", "--no-literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs"})
# The global flags after which a subcommand still runs, on the same repository with the same programs.
GIT_INERT_FLAGS = GIT_PATHSPEC_FLAGS | {
    "-P", "--no-pager", "--no-optional-locks", "--no-replace-objects", "--no-lazy-fetch", "--no-advice"}


def git_global_options(args):
    """git's global options as git reads them from ``args`` (strings, None where computed):
    ([(option index, its value's index or None)], the subcommand's index or None)."""
    opts, i = [], 0
    while i < len(args):
        a = args[i]
        if a is None or not a.startswith("-"):
            return opts, i
        if a in GIT_GLOBAL_VALUE_OPTS:
            opts.append((i, i + 1 if i + 1 < len(args) else None))
            i += 2
            continue
        opts.append((i, None))
        i += 1
    return opts, None


def git_subcommand_index(args):
    """The index of the subcommand among git's arguments (see git_global_options), or None."""
    return git_global_options(args)[1]


def git_plain_subcommand_index(args, flags):
    """The subcommand's index when every global option before it is `-C <dir>` or in ``flags``, else None."""
    opts, k = git_global_options(args)
    return k if all(args[i] in flags or args[i] == "-C" and j is not None for i, j in opts) else None

# Long options of the git subcommands whose options the hooks read, so an
# abbreviation git accepts (`--har` for `--hard`) resolves to its full name.
GIT_LONG_OPTIONS = {
    "push": ("--all", "--branches", "--mirror", "--tags", "--follow-tags", "--atomic",
             "--dry-run", "--porcelain", "--delete", "--prune", "--force", "--force-with-lease",
             "--force-if-includes", "--no-force-with-lease", "--no-force-if-includes",
             "--repo", "--set-upstream", "--thin", "--no-thin", "--quiet", "--verbose",
             "--progress", "--no-verify", "--verify", "--recurse-submodules", "--signed",
             "--no-signed", "--push-option", "--receive-pack", "--exec", "--ipv4", "--ipv6"),
    "reset": ("--soft", "--mixed", "--hard", "--merge", "--keep", "--quiet", "--no-quiet",
              "--refresh", "--no-refresh", "--patch", "--recurse-submodules",
              "--no-recurse-submodules", "--pathspec-from-file", "--pathspec-file-nul",
              "--intent-to-add"),
    "branch": ("--delete", "--force", "--move", "--copy", "--list", "--all", "--remotes",
               "--show-current", "--verbose", "--quiet", "--track", "--no-track",
               "--set-upstream-to", "--unset-upstream", "--edit-description", "--contains",
               "--no-contains", "--merged", "--no-merged", "--column", "--no-column",
               "--sort", "--points-at", "--format", "--ignore-case", "--create-reflog",
               "--abbrev", "--no-abbrev", "--color", "--no-color", "--recurse-submodules",
               "--omit-empty"),
    "checkout": ("--quiet", "--progress", "--no-progress", "--force", "--ours", "--theirs",
                 "--track", "--no-track", "--guess", "--no-guess", "--detach", "--orphan",
                 "--ignore-skip-worktree-bits", "--merge", "--conflict", "--patch",
                 "--ignore-other-worktrees", "--overwrite-ignore", "--no-overwrite-ignore",
                 "--recurse-submodules", "--no-recurse-submodules", "--overlay",
                 "--no-overlay", "--pathspec-from-file", "--pathspec-file-nul"),
    "switch": ("--create", "--force-create", "--detach", "--guess", "--no-guess",
               "--force", "--discard-changes", "--merge", "--conflict", "--quiet",
               "--progress", "--no-progress", "--track", "--no-track", "--orphan",
               "--ignore-other-worktrees", "--recurse-submodules", "--no-recurse-submodules"),
    "restore": ("--source", "--patch", "--worktree", "--staged", "--quiet", "--progress",
                "--no-progress", "--ours", "--theirs", "--merge", "--conflict",
                "--ignore-unmerged", "--ignore-skip-worktree-bits", "--recurse-submodules",
                "--no-recurse-submodules", "--overlay", "--no-overlay",
                "--pathspec-from-file", "--pathspec-file-nul"),
    "clean": ("--dry-run", "--force", "--interactive", "--quiet", "--exclude"),
    "rm": ("--cached", "--force", "--dry-run", "--quiet", "--ignore-unmatch", "--sparse",
           "--pathspec-from-file", "--pathspec-file-nul"),
    "mv": ("--force", "--dry-run", "--verbose", "--sparse"),
    "commit": ("--all", "--patch", "--reuse-message", "--reedit-message", "--fixup",
               "--squash", "--reset-author", "--short", "--branch", "--porcelain", "--long",
               "--null", "--file", "--author", "--date", "--message", "--template",
               "--signoff", "--no-signoff", "--trailer", "--no-verify", "--verify",
               "--allow-empty", "--allow-empty-message", "--cleanup", "--edit", "--no-edit",
               "--amend", "--no-post-rewrite", "--include", "--only",
               "--pathspec-from-file", "--pathspec-file-nul", "--untracked-files",
               "--verbose", "--quiet", "--dry-run", "--status", "--no-status",
               "--gpg-sign", "--no-gpg-sign"),
    "tag": ("--annotate", "--sign", "--no-sign", "--local-user", "--force", "--delete",
            "--verify", "--list", "--sort", "--contains", "--no-contains", "--merged",
            "--no-merged", "--points-at", "--message", "--file", "--trailer", "--cleanup",
            "--create-reflog", "--column", "--no-column", "--format", "--color",
            "--ignore-case", "--omit-empty", "--edit", "--no-edit"),
    "rebase": ("--onto", "--keep-base", "--continue", "--abort", "--quit", "--skip",
               "--edit-todo", "--show-current-patch", "--apply", "--merge", "--strategy",
               "--strategy-option", "--interactive", "--exec", "--root", "--autosquash",
               "--no-autosquash", "--autostash", "--no-autostash", "--update-refs",
               "--no-update-refs", "--quiet", "--verbose", "--stat", "--no-stat",
               "--no-verify", "--verify", "--force-rebase", "--fork-point",
               "--no-fork-point", "--rebase-merges", "--no-rebase-merges",
               "--signoff", "--committer-date-is-author-date", "--ignore-date",
               "--reschedule-failed-exec", "--no-reschedule-failed-exec", "--empty",
               "--keep-empty", "--no-keep-empty", "--gpg-sign", "--no-gpg-sign"),
    "stash": ("--patch", "--staged", "--keep-index", "--no-keep-index", "--include-untracked",
              "--no-include-untracked", "--all", "--quiet", "--message", "--index",
              "--pathspec-from-file", "--pathspec-file-nul"),
    "fetch": ("--all", "--append", "--atomic", "--depth", "--deepen", "--shallow-since",
              "--shallow-exclude", "--unshallow", "--update-shallow", "--dry-run",
              "--force", "--keep", "--multiple", "--prune", "--prune-tags", "--no-tags",
              "--tags", "--refmap", "--recurse-submodules", "--jobs", "--update-head-ok",
              "--upload-pack", "--quiet", "--verbose", "--progress", "--set-upstream",
              "--write-fetch-head", "--no-write-fetch-head"),
    "worktree": ("--force", "--detach", "--checkout", "--no-checkout", "--lock", "--reason",
                 "--orphan", "--track", "--no-track", "--guess-remote", "--quiet",
                 "--verbose", "--expire", "--porcelain", "-z"),
    "config": ("--global", "--system", "--local", "--worktree", "--file", "--blob",
               "--get", "--get-all", "--get-regexp", "--get-urlmatch", "--replace-all",
               "--add", "--unset", "--unset-all", "--rename-section", "--remove-section",
               "--list", "--edit", "--type", "--bool", "--int", "--bool-or-int", "--path",
               "--expiry-date", "--null", "--name-only", "--includes", "--no-includes",
               "--show-origin", "--show-scope", "--default", "--fixed-value"),
}

# The git subcommands that move or remove working-tree files as mv and rm do.
GIT_MV_RM = frozenset({"rm", "mv"})
# The git subcommands that overwrite or remove working-tree files (stash setting the changes aside).
GIT_WORKTREE_DISCARDERS = frozenset({"checkout", "checkout-index", "clean", "reset", "restore", "stash"})
# The two that write the paths they name with their copy in the index or a tree.
GIT_RESTORE_PATHS = frozenset({"checkout", "restore"})


class GitInvocation:
    """One git invocation, read past wrappers and nested shells.

    word: the git Word; path_qualified: its text holds a '/'; global_opts:
    [(opt, value str|None)]; C_dirs: the -C values in order (None where
    computed); config_pairs: [(key, value)] from -c, --config-env (value
    ``$ENV``), GIT_CONFIG_COUNT/KEY_n/VALUE_n and GIT_CONFIG_PARAMETERS; env:
    {NAME: value} of GIT_* assignments; subcommand; args: the arguments with
    long options of known subcommands resolved to their full names (None where
    computed); arg_words: the same as Words; alias_body: the Script an
    ``alias.<sub>=!cmd`` runs; unresolved: why the invocation cannot be read
    statically, else None.
    """

    __slots__ = ("word", "path_qualified", "global_opts", "C_dirs", "config_pairs", "env",
                 "subcommand", "args", "arg_words", "alias_body", "unresolved", "context",
                 "cmd")

    def __init__(self):
        self.word = None
        self.path_qualified = False
        self.global_opts = []
        self.C_dirs = []
        self.config_pairs = []
        self.env = {}
        self.subcommand = None
        self.args = ()
        self.arg_words = ()
        self.alias_body = None
        self.unresolved = None
        self.context = ("top",)
        self.cmd = None

    def as_dict(self):
        return {"word": self.word.text if self.word else None,
                "path_qualified": self.path_qualified, "global_opts": self.global_opts,
                "C_dirs": self.C_dirs, "config_pairs": self.config_pairs, "env": self.env,
                "subcommand": self.subcommand, "args": list(self.args),
                "alias_body": self.alias_body.source if self.alias_body else None,
                "unresolved": self.unresolved, "context": list(self.context)}

    def __repr__(self):
        return "GitInvocation(%r, %r)" % (self.subcommand, list(self.args))


def _sh_quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def resolve_long_option(sub, opt):
    """``opt`` with an unambiguous abbreviation of ``sub``'s long options expanded."""
    if not opt.startswith("--") or opt == "--":
        return opt
    name, eq, val = opt.partition("=")
    table = GIT_LONG_OPTIONS.get(sub)
    if not table or name in table:
        return opt
    cands = [o for o in table if o.startswith(name)]
    if len(cands) == 1:
        return cands[0] + eq + val
    return opt


_QUOTED_RE = re.compile(r"'([^']*)'|\"([^\"]*)\"")


def git_invocations(script, *, into=_DEFAULT_INTO, strings=False, _depth=0, _aliases=()):
    """Every git invocation ``script`` runs, in walk order.

    ``strings`` also reads the static string arguments of every command whose
    code is not otherwise known (an interpreter's ``-c``, an unknown launcher)
    as shell text, and yields what they would run with context ``string`` and
    unresolved ``in_string``: a reading for callers that fail closed on text
    they cannot prove is data.
    """
    if isinstance(script, str):
        script = parse(script)
    out = []
    for site in walk(script, into=into):
        res = resolve(site.cmd)
        for inv in _git_from_resolved(res, site.context):
            inv.cmd = site.cmd
            if site.templated and inv.unresolved is None:
                inv.unresolved = "templated_payload"
            out.append(inv)
            if inv.subcommand in _aliases:
                inv.unresolved = inv.unresolved or "alias_loop"   # git refuses a looping alias
            elif "alias" in into and inv.alias_body is not None and _depth < 8:
                out.extend(git_invocations(inv.alias_body, into=into, strings=strings,
                                           _depth=_depth + 1, _aliases=_aliases + (inv.subcommand,)))
        if strings and res.payload is None and _depth < 4:
            for w in res.args:
                v = w.value()
                if v is None or "git" not in v or v == "git":
                    continue
                texts = [v] + [a or b for a, b in _QUOTED_RE.findall(v) if "git" in (a or b)]
                for text in texts:
                    for inv in git_invocations(parse(text), into=into, strings=True,
                                               _depth=_depth + 1):
                        inv.context = site.context + ("string",) + inv.context[1:]
                        inv.unresolved = inv.unresolved or "in_string"
                        out.append(inv)
    return out


def _git_from_resolved(res, context):
    if res.head is None or res.name != "git":
        return []
    inv = GitInvocation()
    inv.context = context
    inv.word = res.head
    inv.path_qualified = "/" in (res.head.value() or "")
    for a in res.assignments:
        if a.name.startswith("GIT_"):
            inv.env[a.name] = a.static_value()
    args = list(res.args)
    k = 0
    while k < len(args):
        v = args[k].value()
        if v is None:
            inv.unresolved = "dynamic_global_option"
            break
        if v in GIT_GLOBAL_VALUE_OPTS:
            val = args[k + 1].value() if k + 1 < len(args) else None
            if k + 1 >= len(args):
                inv.unresolved = "missing_option_value:" + v
                k += 1
                break
            _git_global(inv, v, val)
            k += 2
            continue
        if v.startswith("--") and "=" in v and v.split("=", 1)[0] in GIT_GLOBAL_VALUE_OPTS | {
                "--exec-path", "--list-cmds"}:
            name, _eq, val = v.partition("=")
            _git_global(inv, name, val)
            if name == "--exec-path":
                # git runs its subcommands from this directory
                inv.unresolved = inv.unresolved or "exec_path"
            k += 1
            continue
        if v[:2] in ("-c", "-C") and len(v) > 2:
            # git takes -c and -C only as separate words: `-C/p` is an unknown
            # option and git runs nothing.
            inv.unresolved = "invalid_global_option:" + v
            break
        if v in GIT_GLOBAL_FLAGS:
            inv.global_opts.append((v, None))
            k += 1
            continue
        break
    count = inv.env.get("GIT_CONFIG_COUNT")
    if count is not None and _digits(count):
        for n in range(int(count)):
            key = inv.env.get("GIT_CONFIG_KEY_%d" % n)
            if key is not None:
                inv.config_pairs.append((key, inv.env.get("GIT_CONFIG_VALUE_%d" % n)))
    params = inv.env.get("GIT_CONFIG_PARAMETERS")
    if params:
        for item in argv_split(params):
            key, _eq, val = item.partition("=")
            inv.config_pairs.append((key, val))
    if res.unresolved and inv.unresolved is None:
        inv.unresolved = "wrapper:" + res.unresolved
    if k < len(args) and (inv.unresolved is None or inv.unresolved.startswith(("wrapper:", "exec_path"))):
        sub = args[k].value()
        inv.subcommand = sub
        if sub is None:
            inv.unresolved = "dynamic_subcommand"
        rest = args[k + 1:]
        inv.arg_words = tuple(rest)
        inv.args = tuple(resolve_long_option(sub, w.value()) if w.value() is not None else None
                         for w in rest)
        for key, val in inv.config_pairs:
            if key is not None and key.lower() == "alias." + (sub or "").lower() and val:
                if val.startswith("!"):
                    inv.alias_body = parse(val[1:] + (" " + " ".join(
                        w.text for w in rest) if rest else ""))
                else:
                    carried = " ".join("-c " + _sh_quote("%s=%s" % (k_, v_))
                                       for k_, v_ in inv.config_pairs if k_ is not None and v_ is not None)
                    inner = parse("git " + carried + " " + val +
                                  (" " + " ".join(w.text for w in rest) if rest else ""))
                    inv.alias_body = inner
    elif inv.unresolved is not None:
        inv.args = tuple(w.value() for w in args[k:])
        inv.arg_words = tuple(args[k:])
    return [inv]


def _git_global(inv, opt, val):
    inv.global_opts.append((opt, val))
    if opt == "-C":
        inv.C_dirs.append(val)
    elif opt == "-c":
        if val is None:
            inv.config_pairs.append((None, None))
        else:
            key, eq, value = val.partition("=")
            inv.config_pairs.append((key, value if eq else "true"))
    elif opt == "--config-env":
        if val is None:
            inv.config_pairs.append((None, None))
        else:
            key, _eq, env = val.partition("=")
            inv.config_pairs.append((key, "$" + env))


# ---------------------------------------------------------------------------
# argv_split
# ---------------------------------------------------------------------------

def argv_split(text):
    """A shlex-compatible argv for a config or argument string (no expansion)."""
    if not isinstance(text, str):
        return []
    try:
        toks = lex(Src.from_raw(text))
    except LexError:
        import shlex
        try:
            return shlex.split(text)
        except ValueError:
            return text.split()
    out = []
    for tok in toks:
        if tok[0] == "W":
            v = tok[1].value()
            out.append(v if v is not None else tok[1].text)
        elif tok[0] == "OP" and tok[1] != "\n":
            out.append(tok[1])
        elif tok[0] == "R":
            r = tok[1]
            out.append((r.io or "") + r.op)
            if r.target is not None:
                v = r.target.value()
                out.append(v if v is not None else r.target.text)
    return out
