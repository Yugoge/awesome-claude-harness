"""A tokenizer and parser for the shell the harness writes (bash), with no
dependency beyond the standard library.

It produces a small syntax tree: simple commands with their assignments, words
and redirections; pipelines; and-or lists; if, while/until, for, case, brace
groups, subshells, function definitions, ``[[ ]]`` tests and ``(( ))``.
Words keep their parts (literal text, quoted or not; parameter expansions with
their operator and argument; command substitutions as parsed sub-scripts;
arithmetic; process substitutions), and every node carries its source line.
Heredoc bodies are attached to their redirection with their first line.

The parser recovers from a statement it cannot parse by skipping to the next
line, and records each such line in ``Script.errors``.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

RESERVED = {"if", "then", "elif", "else", "fi", "for", "in", "do", "done", "while",
            "until", "case", "esac", "function", "{", "}", "!", "[[", "]]", "select", "time"}
META = set(" \t\n;&|<>()")
OPERATORS = sorted([";;&", ";;", ";&", "&&", "||", "|&", "&>>", "&>", "<<<", "<<-", "<<", "<>",
                    "<&", ">&", ">>", ">|", "((", "(", ")", "|", "&", ";", "<", ">"],
                   key=len, reverse=True)
REDIR_OPS = {"<", ">", ">>", ">|", "<>", "<&", ">&", "&>", "&>>", "<<", "<<-", "<<<"}


class ShellParseError(Exception):
    pass


# ----------------------------------------------------------------- word parts

@dataclass
class Lit:
    text: str
    quoted: bool = False


@dataclass
class Tilde:
    user: str = ""


@dataclass
class Var:
    name: str
    op: str = ""          # '', ':-', '-', ':=', ':+', '+', '#', '##', '%', '%%', '/', '//', 'len', ':?', '^', ',' ...
    arg: "Word | None" = None
    quoted: bool = False
    index: str | None = None


@dataclass
class CmdSub:
    script: "Script"
    quoted: bool = False


@dataclass
class Arith:
    text: str


@dataclass
class ProcSub:
    direction: str
    script: "Script"


@dataclass
class ArrayLit:
    words: list


@dataclass
class Word:
    parts: list
    line: int
    raw: str = ""

    def literal(self) -> str | None:
        """The word's text when it has no expansion, else None."""
        out = []
        for p in self.parts:
            if isinstance(p, Lit):
                out.append(p.text)
            else:
                return None
        return "".join(out)

    def is_quoted(self) -> bool:
        return any(isinstance(p, (Lit, Var, CmdSub)) and getattr(p, "quoted", False) for p in self.parts)


# --------------------------------------------------------------------- nodes

@dataclass
class HereDoc:
    delim: str
    quoted: bool
    strip_tabs: bool
    body: str = ""
    body_line: int = 0
    word: "Word | None" = None     # expanded body when the delimiter is unquoted


@dataclass
class Redir:
    fd: str | None
    op: str
    target: Word | None
    line: int
    heredoc: HereDoc | None = None


@dataclass
class Simple:
    assigns: list           # [(name, op, Word|None, line)]
    words: list             # [Word]
    redirs: list            # [Redir]
    line: int


@dataclass
class Pipeline:
    cmds: list
    negated: bool
    line: int


@dataclass
class AndOr:
    first: object
    rest: list              # [(op, node)]
    line: int


@dataclass
class If:
    clauses: list           # [(cond list, body list)]
    else_: list | None
    line: int
    redirs: list = field(default_factory=list)


@dataclass
class Loop:
    kind: str               # while | until
    cond: list
    body: list
    line: int
    redirs: list = field(default_factory=list)


@dataclass
class For:
    var: str
    words: list | None
    body: list
    line: int
    redirs: list = field(default_factory=list)
    arith: str | None = None


@dataclass
class Case:
    word: Word
    arms: list              # [(patterns [Word], body list, line)]
    line: int
    redirs: list = field(default_factory=list)


@dataclass
class Group:
    body: list
    subshell: bool
    line: int
    redirs: list = field(default_factory=list)


@dataclass
class FuncDef:
    name: str
    body: object
    line: int


@dataclass
class Test:
    words: list
    line: int


@dataclass
class ArithCmd:
    text: str
    line: int


@dataclass
class Script:
    body: list
    errors: list = field(default_factory=list)


# --------------------------------------------------------------------- lexer

@dataclass
class Tok:
    kind: str               # WORD | OP | NL | EOF
    value: object
    line: int
    pos: int


class Lexer:
    def __init__(self, src: str, line0: int = 1):
        self.src = src
        self.pos = 0
        self.line0 = line0
        self.starts = [0]
        for i, ch in enumerate(src):
            if ch == "\n":
                self.starts.append(i + 1)
        self.pending: list[HereDoc] = []
        self.peeked: list[Tok] = []

    def line_at(self, pos: int) -> int:
        return bisect.bisect_right(self.starts, pos) - 1 + self.line0

    # -- token stream
    def peek(self) -> Tok:
        if not self.peeked:
            self.peeked.append(self._next())
        return self.peeked[0]

    def next(self) -> Tok:
        if self.peeked:
            return self.peeked.pop(0)
        return self._next()

    def _skip_blank(self) -> None:
        src = self.src
        while self.pos < len(src):
            ch = src[self.pos]
            if ch in " \t\r":
                self.pos += 1
            elif ch == "\\" and src.startswith("\\\n", self.pos):
                self.pos += 2
            elif ch == "#":
                while self.pos < len(src) and src[self.pos] != "\n":
                    self.pos += 1
            else:
                break

    def _next(self) -> Tok:
        self._skip_blank()
        src = self.src
        if self.pos >= len(src):
            return Tok("EOF", None, self.line_at(len(src)), self.pos)
        ch = src[self.pos]
        start = self.pos
        if ch == "\n":
            self.pos += 1
            if self.pending:
                self._read_heredocs()
            return Tok("NL", "\n", self.line_at(start), start)
        # fd-prefixed redirection: 2> 2>> 1>&2 2>&1 0<
        j = self.pos
        while j < len(src) and src[j].isdigit():
            j += 1
        if j > self.pos and j < len(src) and src[j] in "<>":
            fd = src[self.pos:j]
            self.pos = j
            op = self._match_op()
            return Tok("OP", (fd, op), self.line_at(start), start)
        if src.startswith("<(", self.pos) or src.startswith(">(", self.pos):
            w = self._read_word()
            return Tok("WORD", w, self.line_at(start), start)
        if ch in "<>;&|()":
            op = self._match_op()
            return Tok("OP", (None, op), self.line_at(start), start)
        w = self._read_word()
        return Tok("WORD", w, self.line_at(start), start)

    def _match_op(self) -> str:
        for op in OPERATORS:
            if self.src.startswith(op, self.pos):
                self.pos += len(op)
                return op
        raise ShellParseError(f"unknown operator at {self.line_at(self.pos)}")

    # -- words
    def _read_word(self, stop: str | None = None) -> Word:
        """Read one word. `stop` adds terminator characters (for ${...} args)."""
        src = self.src
        start = self.pos
        line = self.line_at(start)
        parts: list = []
        buf: list[str] = []

        def flush():
            if buf:
                parts.append(Lit("".join(buf), False))
                buf.clear()

        first = True
        while self.pos < len(src):
            ch = src[self.pos]
            if stop is not None:
                if ch in stop:
                    break
            elif ch in META:
                if ch in "<>" and src.startswith("(", self.pos + 1) and not buf and not parts:
                    pass
                elif ch == "(" and (buf and "".join(buf).endswith("=") and not parts
                                    or buf and buf[-1] in "@!?*+" ):
                    pass
                else:
                    break
            if ch == "\\":
                if self.pos + 1 < len(src):
                    nxt = src[self.pos + 1]
                    if nxt == "\n":
                        self.pos += 2
                        continue
                    flush()
                    parts.append(Lit(nxt, True))
                    self.pos += 2
                else:
                    self.pos += 1
                first = False
                continue
            if ch == "'":
                flush()
                end = src.find("'", self.pos + 1)
                if end < 0:
                    raise ShellParseError(f"unterminated ' at line {line}")
                parts.append(Lit(src[self.pos + 1:end], True))
                self.pos = end + 1
            elif ch == '"':
                flush()
                self.pos += 1
                parts.extend(self._read_dq('"'))
            elif ch == "$":
                flush()
                parts.append(self._read_dollar(quoted=False))
            elif ch == "`":
                flush()
                parts.append(self._read_backtick(quoted=False))
            elif ch == "~" and first and not buf:
                self.pos += 1
                user = []
                while self.pos < len(src) and (src[self.pos].isalnum() or src[self.pos] in "_-"):
                    user.append(src[self.pos])
                    self.pos += 1
                parts.append(Tilde("".join(user)))
            elif ch in "<>" and src.startswith("(", self.pos + 1):
                flush()
                direction = ch
                self.pos += 2
                sub = self._parse_nested(")")
                parts.append(ProcSub(direction, sub))
            elif ch == "(" and buf and "".join(buf).endswith("=") and not parts:
                # array assignment NAME=( ... )
                self.pos += 1
                words = []
                while True:
                    self._skip_blank_nl()
                    if self.pos >= len(src):
                        raise ShellParseError("unterminated array")
                    if src[self.pos] == ")":
                        self.pos += 1
                        break
                    words.append(self._read_word())
                flush()
                parts.append(ArrayLit(words))
            elif ch == "(":
                # extglob @( ) !( ) etc.
                depth = 0
                while self.pos < len(src):
                    c = src[self.pos]
                    buf.append(c)
                    self.pos += 1
                    if c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                        if depth == 0:
                            break
            else:
                buf.append(ch)
                self.pos += 1
            first = False
        flush()
        return Word(parts, line, src[start:self.pos])

    def _skip_blank_nl(self) -> None:
        while self.pos < len(self.src):
            self._skip_blank()
            if self.pos < len(self.src) and self.src[self.pos] == "\n":
                self.pos += 1
                continue
            break

    def _read_dq(self, close: str | None) -> list:
        """Parts of a double-quoted string (or a heredoc body when close is None)."""
        src = self.src
        parts: list = []
        buf: list[str] = []

        def flush():
            if buf:
                parts.append(Lit("".join(buf), True))
                buf.clear()

        while self.pos < len(src):
            ch = src[self.pos]
            if close is not None and ch == close:
                self.pos += 1
                flush()
                return parts
            if ch == "\\" and self.pos + 1 < len(src):
                nxt = src[self.pos + 1]
                if nxt in ("$", "`", "\\", "\n") or (close is not None and nxt == '"'):
                    if nxt != "\n":
                        buf.append(nxt)
                    self.pos += 2
                    continue
                buf.append(ch)
                self.pos += 1
                continue
            if ch == "$" and self.pos + 1 < len(src) and (src[self.pos + 1].isalnum() or src[self.pos + 1] in "_{(@*#?$!-"):
                flush()
                parts.append(self._read_dollar(quoted=True))
                continue
            if ch == "`":
                flush()
                parts.append(self._read_backtick(quoted=True))
                continue
            buf.append(ch)
            self.pos += 1
        if close is not None:
            raise ShellParseError("unterminated double quote")
        flush()
        return parts

    def _read_dollar(self, quoted: bool):
        src = self.src
        assert src[self.pos] == "$"
        nxt = src[self.pos + 1] if self.pos + 1 < len(src) else ""
        if src.startswith("$((", self.pos):
            self.pos += 3
            depth = 2
            start = self.pos
            while self.pos < len(src) and depth > 0:
                c = src[self.pos]
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                self.pos += 1
            return Arith(src[start:self.pos - 2])
        if nxt == "(":
            self.pos += 2
            sub = self._parse_nested(")")
            return CmdSub(sub, quoted)
        if nxt == "{":
            return self._read_brace(quoted)
        if nxt == "'":
            self.pos += 2
            out = []
            while self.pos < len(src) and src[self.pos] != "'":
                if src[self.pos] == "\\" and self.pos + 1 < len(src):
                    e = src[self.pos + 1]
                    out.append({"n": "\n", "t": "\t", "'": "'", "\\": "\\"}.get(e, "\\" + e))
                    self.pos += 2
                    continue
                out.append(src[self.pos])
                self.pos += 1
            self.pos += 1
            return Lit("".join(out), True)
        if nxt == '"':
            self.pos += 2
            parts = self._read_dq('"')
            return parts[0] if len(parts) == 1 else Lit("".join(p.text for p in parts if isinstance(p, Lit)), True)
        if nxt.isalpha() or nxt == "_":
            j = self.pos + 1
            while j < len(src) and (src[j].isalnum() or src[j] == "_"):
                j += 1
            name = src[self.pos + 1:j]
            self.pos = j
            return Var(name, quoted=quoted)
        if nxt and (nxt.isdigit() or nxt in "@*#?$!-"):
            self.pos += 2
            return Var(nxt, quoted=quoted)
        self.pos += 1
        return Lit("$", quoted)

    def _read_brace(self, quoted: bool) -> Var:
        src = self.src
        self.pos += 2  # ${
        length = False
        if self.pos < len(src) and src[self.pos] == "#" and self.pos + 1 < len(src) and src[self.pos + 1] not in "}":
            length = True
            self.pos += 1
        if self.pos < len(src) and src[self.pos] == "!":
            self.pos += 1
        j = self.pos
        if j < len(src) and (src[j].isalpha() or src[j] == "_"):
            while j < len(src) and (src[j].isalnum() or src[j] == "_"):
                j += 1
        elif j < len(src) and (src[j].isdigit() or src[j] in "@*#?$!-"):
            j += 1
            while j < len(src) and src[j].isdigit():
                j += 1
        name = src[self.pos:j]
        self.pos = j
        index = None
        if self.pos < len(src) and src[self.pos] == "[":
            end = src.find("]", self.pos)
            index = src[self.pos + 1:end]
            self.pos = end + 1
        if length:
            self._expect_char("}")
            return Var(name, "len", None, quoted, index)
        if self.pos < len(src) and src[self.pos] == "}":
            self.pos += 1
            return Var(name, "", None, quoted, index)
        op = ""
        for cand in (":-", ":=", ":+", ":?", "##", "%%", "//", "/#", "/%", "^^", ",,", "-", "=", "+", "?", "#", "%", "/", "^", ",", ":"):
            if src.startswith(cand, self.pos):
                op = cand
                self.pos += len(cand)
                break
        arg = self._read_brace_arg()
        return Var(name, op, arg, quoted, index)

    def _read_brace_arg(self) -> Word:
        src = self.src
        start = self.pos
        line = self.line_at(start)
        parts: list = []
        buf: list[str] = []

        def flush():
            if buf:
                parts.append(Lit("".join(buf), False))
                buf.clear()

        depth = 0
        while self.pos < len(src):
            ch = src[self.pos]
            if ch == "}" and depth == 0:
                self.pos += 1
                flush()
                return Word(parts, line, src[start:self.pos - 1])
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            if ch == "\\" and self.pos + 1 < len(src):
                buf.append(src[self.pos + 1])
                self.pos += 2
                continue
            if ch == "'":
                flush()
                end = src.find("'", self.pos + 1)
                if end < 0:
                    raise ShellParseError("unterminated ' in ${}")
                parts.append(Lit(src[self.pos + 1:end], True))
                self.pos = end + 1
                continue
            if ch == '"':
                flush()
                self.pos += 1
                parts.extend(self._read_dq('"'))
                continue
            if ch == "$":
                flush()
                parts.append(self._read_dollar(quoted=False))
                continue
            if ch == "`":
                flush()
                parts.append(self._read_backtick(quoted=False))
                continue
            if ch == "~" and not buf and not parts:
                self.pos += 1
                parts.append(Tilde(""))
                continue
            buf.append(ch)
            self.pos += 1
        raise ShellParseError("unterminated ${")

    def _expect_char(self, c: str) -> None:
        if self.pos < len(self.src) and self.src[self.pos] == c:
            self.pos += 1
            return
        raise ShellParseError(f"expected {c!r} at line {self.line_at(self.pos)}")

    def _read_backtick(self, quoted: bool) -> CmdSub:
        src = self.src
        start = self.pos + 1
        j = start
        out = []
        while j < len(src) and src[j] != "`":
            if src[j] == "\\" and j + 1 < len(src) and src[j + 1] in "`$\\":
                out.append(src[j + 1])
                j += 2
                continue
            out.append(src[j])
            j += 1
        self.pos = j + 1
        sub = parse("".join(out), self.line_at(start))
        return CmdSub(sub, quoted)

    def _parse_nested(self, close: str) -> "Script":
        saved_peek = self.peeked
        self.peeked = []
        p = Parser(self)
        body = p.parse_list(stops={close})
        tok = self.next()
        if not (tok.kind == "OP" and tok.value[1] == close):
            raise ShellParseError(f"expected {close} at line {tok.line}")
        self.peeked = saved_peek
        return Script(body, p.errors)

    # -- heredocs
    def _read_heredocs(self) -> None:
        src = self.src
        for hd in self.pending:
            hd.body_line = self.line_at(self.pos)
            lines = []
            while self.pos <= len(src):
                end = src.find("\n", self.pos)
                if end < 0:
                    end = len(src)
                raw = src[self.pos:end]
                check = raw.lstrip("\t") if hd.strip_tabs else raw
                self.pos = min(end + 1, len(src) + 1)
                if check.rstrip("\r") == hd.delim:
                    break
                lines.append(check if hd.strip_tabs else raw)
                if end >= len(src):
                    break
            hd.body = "\n".join(lines) + ("\n" if lines else "")
            if not hd.quoted:
                sub = Lexer(hd.body, hd.body_line)
                hd.word = Word(sub._read_dq(None), hd.body_line, hd.body)
        self.pos = min(self.pos, len(src))
        self.pending = []

    # -- raw readers for [[ ]] and (( ))
    def read_test_words(self) -> list:
        words = []
        while True:
            self._skip_blank_nl()
            if self.pos >= len(self.src):
                raise ShellParseError("unterminated [[")
            if self.src.startswith("]]", self.pos):
                self.pos += 2
                return words
            ch = self.src[self.pos]
            if ch in "()<>!" or self.src.startswith("&&", self.pos) or self.src.startswith("||", self.pos):
                n = 2 if self.src.startswith(("&&", "||"), self.pos) else 1
                words.append(Word([Lit(self.src[self.pos:self.pos + n])], self.line_at(self.pos), self.src[self.pos:self.pos + n]))
                self.pos += n
                continue
            words.append(self._read_word(stop=" \t\n"))

    def read_arith(self) -> str:
        src = self.src
        depth = 2
        start = self.pos
        while self.pos < len(src) and depth > 0:
            c = src[self.pos]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            self.pos += 1
        return src[start:self.pos - 2]

    def skip_line(self) -> None:
        self.peeked = []
        end = self.src.find("\n", self.pos)
        self.pos = len(self.src) if end < 0 else end


# -------------------------------------------------------------------- parser

class Parser:
    def __init__(self, lexer: Lexer):
        self.lx = lexer
        self.errors: list[int] = []

    def _is_word(self, tok: Tok, text: str) -> bool:
        if tok.kind != "WORD":
            return False
        w: Word = tok.value
        return w.literal() == text and not w.is_quoted()

    def _is_op(self, tok: Tok, text: str) -> bool:
        return tok.kind == "OP" and tok.value[1] == text and tok.value[0] is None

    def _skip_nl(self) -> None:
        while self.lx.peek().kind == "NL":
            self.lx.next()

    def _at_stop(self, tok: Tok, stops: set) -> bool:
        if tok.kind == "EOF":
            return True
        if tok.kind == "OP" and tok.value[0] is None and tok.value[1] in stops:
            return True
        if tok.kind == "WORD":
            w = tok.value
            lit = w.literal()
            if lit in stops and not w.is_quoted():
                return True
        return False

    def parse_list(self, stops: set, recover: bool = False) -> list:
        items = []
        while True:
            tok = self.lx.peek()
            while tok.kind == "NL" or (tok.kind == "OP" and tok.value == (None, ";")):
                self.lx.next()
                tok = self.lx.peek()
            if self._at_stop(tok, stops):
                return items
            if recover:
                try:
                    node = self.parse_andor()
                except (ShellParseError, IndexError, AssertionError, RecursionError):
                    self.errors.append(tok.line)
                    self.lx.skip_line()
                    continue
            else:
                node = self.parse_andor()
            items.append(node)
            tok = self.lx.peek()
            if tok.kind == "OP" and tok.value[0] is None and tok.value[1] in (";", "&"):
                self.lx.next()
            elif tok.kind == "NL":
                self.lx.next()
            elif self._at_stop(tok, stops):
                return items
            elif tok.kind == "EOF":
                return items
            elif recover:
                self.errors.append(tok.line)
                self.lx.skip_line()
            else:
                raise ShellParseError(f"unexpected token at line {tok.line}")

    def parse_andor(self):
        tok = self.lx.peek()
        first = self.parse_pipeline()
        rest = []
        while True:
            t = self.lx.peek()
            if t.kind == "OP" and t.value[0] is None and t.value[1] in ("&&", "||"):
                self.lx.next()
                self._skip_nl()
                rest.append((t.value[1], self.parse_pipeline()))
            else:
                break
        return AndOr(first, rest, tok.line) if rest else first

    def parse_pipeline(self):
        tok = self.lx.peek()
        negated = False
        if self._is_word(tok, "!"):
            self.lx.next()
            negated = True
        elif self._is_word(tok, "time"):
            self.lx.next()
        cmds = [self.parse_command()]
        while True:
            t = self.lx.peek()
            if t.kind == "OP" and t.value[0] is None and t.value[1] in ("|", "|&"):
                self.lx.next()
                self._skip_nl()
                cmds.append(self.parse_command())
            else:
                break
        if len(cmds) == 1 and not negated:
            return cmds[0]
        return Pipeline(cmds, negated, tok.line)

    def _redirs(self) -> list:
        out = []
        while True:
            t = self.lx.peek()
            if t.kind == "OP" and t.value[1] in REDIR_OPS:
                out.append(self._redir())
            else:
                return out

    def _redir(self) -> Redir:
        t = self.lx.next()
        fd, op = t.value
        if op in ("<<", "<<-"):
            dt = self.lx.next()
            if dt.kind != "WORD":
                raise ShellParseError(f"heredoc delimiter at {dt.line}")
            w: Word = dt.value
            quoted = any(getattr(p, "quoted", False) for p in w.parts)
            delim = "".join(p.text for p in w.parts if isinstance(p, Lit))
            hd = HereDoc(delim, quoted, op == "<<-")
            self.lx.pending.append(hd)
            return Redir(fd, op, None, t.line, hd)
        nt = self.lx.next()
        if nt.kind != "WORD":
            raise ShellParseError(f"redirection target at line {nt.line}")
        return Redir(fd, op, nt.value, t.line)

    def parse_command(self):
        tok = self.lx.peek()
        if tok.kind == "WORD":
            lit = tok.value.literal()
            if not tok.value.is_quoted():
                if lit == "if":
                    return self._with_redirs(self._parse_if())
                if lit in ("while", "until"):
                    return self._with_redirs(self._parse_loop(lit))
                if lit in ("for", "select"):
                    return self._with_redirs(self._parse_for())
                if lit == "case":
                    return self._with_redirs(self._parse_case())
                if lit == "{":
                    self.lx.next()
                    body = self.parse_list({"}"})
                    self._expect_word("}")
                    return self._with_redirs(Group(body, False, tok.line))
                if lit == "function":
                    self.lx.next()
                    nt = self.lx.next()
                    name = nt.value.literal() or ""
                    name = name.rstrip("()")
                    t2 = self.lx.peek()
                    if self._is_op(t2, "("):
                        self.lx.next()
                        self._expect_op(")")
                    self._skip_nl()
                    body = self.parse_command()
                    return FuncDef(name, body, tok.line)
                if lit == "[[":
                    self.lx.next()
                    self.lx.peeked = []
                    words = self.lx.read_test_words()
                    return self._with_redirs(Test(words, tok.line))
        if tok.kind == "OP" and tok.value == (None, "("):
            self.lx.next()
            body = self.parse_list({")"})
            self._expect_op(")")
            return self._with_redirs(Group(body, True, tok.line))
        if tok.kind == "OP" and tok.value == (None, "(("):
            self.lx.next()
            self.lx.peeked = []
            text = self.lx.read_arith()
            return self._with_redirs(ArithCmd(text, tok.line))
        return self._parse_simple()

    def _with_redirs(self, node):
        rs = self._redirs()
        if rs and hasattr(node, "redirs"):
            node.redirs.extend(rs)
        return node

    def _expect_word(self, text: str) -> None:
        t = self.lx.next()
        if not self._is_word(t, text):
            raise ShellParseError(f"expected {text} at line {t.line}")

    def _expect_op(self, text: str) -> None:
        t = self.lx.next()
        if not (t.kind == "OP" and t.value[1] == text):
            raise ShellParseError(f"expected {text} at line {t.line}")

    def _parse_if(self) -> If:
        tok = self.lx.next()
        clauses = []
        cond = self.parse_list({"then"})
        self._expect_word("then")
        body = self.parse_list({"elif", "else", "fi"})
        clauses.append((cond, body))
        else_ = None
        while True:
            t = self.lx.next()
            if self._is_word(t, "elif"):
                cond = self.parse_list({"then"})
                self._expect_word("then")
                body = self.parse_list({"elif", "else", "fi"})
                clauses.append((cond, body))
            elif self._is_word(t, "else"):
                else_ = self.parse_list({"fi"})
            elif self._is_word(t, "fi"):
                break
            else:
                raise ShellParseError(f"bad if at line {t.line}")
        return If(clauses, else_, tok.line)

    def _parse_loop(self, kind: str) -> Loop:
        tok = self.lx.next()
        cond = self.parse_list({"do"})
        self._expect_word("do")
        body = self.parse_list({"done"})
        self._expect_word("done")
        return Loop(kind, cond, body, tok.line)

    def _parse_for(self) -> For:
        tok = self.lx.next()
        t = self.lx.peek()
        if t.kind == "OP" and t.value == (None, "(("):
            self.lx.next()
            self.lx.peeked = []
            text = self.lx.read_arith()
            self._skip_seps()
            self._expect_word("do")
            body = self.parse_list({"done"})
            self._expect_word("done")
            return For("", None, body, tok.line, arith=text)
        nt = self.lx.next()
        var = nt.value.literal() if nt.kind == "WORD" else ""
        self._skip_nl()
        words = None
        t = self.lx.peek()
        if self._is_word(t, "in"):
            self.lx.next()
            words = []
            while True:
                t = self.lx.peek()
                if t.kind == "WORD" and not self._is_word(t, "do"):
                    words.append(self.lx.next().value)
                else:
                    break
        self._skip_seps()
        self._expect_word("do")
        body = self.parse_list({"done"})
        self._expect_word("done")
        return For(var or "", words, body, tok.line)

    def _skip_seps(self) -> None:
        while True:
            t = self.lx.peek()
            if t.kind == "NL" or (t.kind == "OP" and t.value == (None, ";")):
                self.lx.next()
            else:
                return

    def _parse_case(self) -> Case:
        tok = self.lx.next()
        wt = self.lx.next()
        if wt.kind != "WORD":
            raise ShellParseError(f"case word at line {wt.line}")
        self._skip_nl()
        self._expect_word("in")
        arms = []
        while True:
            self._skip_nl()
            t = self.lx.peek()
            if self._is_word(t, "esac"):
                self.lx.next()
                break
            if t.kind == "EOF":
                raise ShellParseError("unterminated case")
            if self._is_op(t, "("):
                self.lx.next()
            pats = []
            pt = self.lx.next()
            if pt.kind != "WORD":
                raise ShellParseError(f"case pattern at line {pt.line}")
            pats.append(pt.value)
            while self._is_op(self.lx.peek(), "|"):
                self.lx.next()
                pt = self.lx.next()
                if pt.kind != "WORD":
                    raise ShellParseError(f"case pattern at line {pt.line}")
                pats.append(pt.value)
            self._expect_op(")")
            body = self.parse_list({";;", ";&", ";;&", "esac"})
            arms.append((pats, body, pt.line))
            t = self.lx.peek()
            if t.kind == "OP" and t.value[1] in (";;", ";&", ";;&"):
                self.lx.next()
        return Case(wt.value, arms, tok.line)

    def _parse_simple(self):
        tok = self.lx.peek()
        assigns = []
        words: list[Word] = []
        redirs: list[Redir] = []
        while True:
            t = self.lx.peek()
            if t.kind == "OP" and t.value[1] in REDIR_OPS:
                redirs.append(self._redir())
                continue
            if t.kind != "WORD":
                break
            w: Word = t.value
            if not words:
                a = _assignment(w)
                if a is not None:
                    self.lx.next()
                    assigns.append((a[0], a[1], a[2], t.line))
                    continue
                # function definition: name ( )
                lit = w.literal()
                if lit and not w.is_quoted():
                    self.lx.next()
                    t2 = self.lx.peek()
                    if self._is_op(t2, "("):
                        self.lx.next()
                        self._expect_op(")")
                        self._skip_nl()
                        body = self.parse_command()
                        return FuncDef(lit, body, t.line)
                    words.append(w)
                    continue
            self.lx.next()
            words.append(w)
        if not assigns and not words and not redirs:
            raise ShellParseError(f"empty command at line {tok.line}")
        return Simple(assigns, words, redirs, tok.line)


def _assignment(w: Word):
    """(name, op, value Word) when the word is NAME=value or NAME+=value."""
    if not w.parts or not isinstance(w.parts[0], Lit) or w.parts[0].quoted:
        return None
    text = w.parts[0].text
    i = 0
    while i < len(text) and (text[i].isalnum() or text[i] == "_"):
        i += 1
    if i == 0 or text[0].isdigit():
        return None
    name = text[:i]
    rest = text[i:]
    if rest.startswith("["):
        end = rest.find("]")
        if end < 0:
            return None
        rest = rest[end + 1:]
    if rest.startswith("+="):
        op, after = "+=", rest[2:]
    elif rest.startswith("="):
        op, after = "=", rest[1:]
    else:
        return None
    parts = ([Lit(after, False)] if after else []) + list(w.parts[1:])
    return name, op, Word(parts, w.line, w.raw)


def parse(src: str, line0: int = 1) -> Script:
    lx = Lexer(src, line0)
    p = Parser(lx)
    body = p.parse_list(set(), recover=True)
    return Script(body, p.errors)


def word_from_text(text: str, line: int) -> Word:
    """Parse text as one double-quoted-like word (for -c code and heredocs)."""
    lx = Lexer(text, line)
    return Word(lx._read_dq(None), line, text)
