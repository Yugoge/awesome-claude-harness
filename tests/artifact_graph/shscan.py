"""Shell half of the static derivation, over shparse's syntax tree.

Words are evaluated into the same templates as Python values (variables by
their reaching assignments, ``${VAR:-default}``, command substitutions of the
root functions, dirname/basename/realpath, ``cd X && pwd``, ``date``...).
Commands and redirections give the file operations (``>``, ``>>``, ``<``,
``cat``, ``jq``, ``rm``, ``mv``, ``cp``, ``tee``, ``touch``, ``[ -f ]``,
``source`` ...). Code handed to ``python3 -c`` or to ``python3 -`` through a
heredoc is parsed by pyscan with the shell's exported values as its env, and
its operations carry the shell file and line.

The same walker serves hooks/ and scripts/ files and the fenced shell blocks
of commands/*.md and agents/*.md (their ``<PLACEHOLDER>`` words become
placeholder tokens, resolved through the variables the file's blocks assign).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import model as M
from . import patterns as P
from . import pyscan
from . import shparse as S
from . import values as V
from .values import Unk, Str, Num, Lst

ROOT_SHELL_FUNCTIONS = {
    ("hooks/lib/harness_state_dir.sh", "harness_state_dir"): "state",
    ("hooks/lib/claude_home.sh", "claude_home_resolve"): "harness",
}

_PREFIX_CMDS = {"command", "builtin", "exec", "nohup", "nice", "sudo", "time", "stdbuf", "setsid", "flock"}
_DECL = {"local", "declare", "typeset", "export", "readonly"}
_PY = re.compile(r"(^|/)(python3?(\.\d+)?|pypy3?)$")
_SH = re.compile(r"(^|/)(bash|sh|zsh|dash)$")
_READERS = {"cat", "head", "tail", "wc", "less", "more", "sort", "uniq", "cut", "md5sum", "sha256sum", "sha1sum",
            "shasum", "xxd", "od", "strings", "base64", "file", "stat", "nl", "tac", "cksum", "b2sum", "tr"}
_TEST_UNARY = {"-f", "-e", "-s", "-d", "-r", "-w", "-x", "-L", "-h", "-O", "-G", "-N", "-p", "-S", "-b", "-c", "-a"}


@dataclass
class ShFunc:
    file: "ShFile"
    name: str
    node: S.FuncDef


@dataclass
class ShSummary:
    param_effects: list = field(default_factory=list)
    printed: V.Val = field(default_factory=lambda: Unk("assembled:stdout"))
    decisions: list = field(default_factory=list)
    reads: list = field(default_factory=list)
    print_params: list = field(default_factory=list)   # (stream, template) printing a parameter
    sysmsg_params: list = field(default_factory=list)  # templates of a systemMessage printing a parameter


class ShFile:
    def __init__(self, component: str, script: S.Script, *, origin: str = "", self_path: str | None = None,
                 env: dict | None = None):
        self.component = component
        self.script = script
        self.origin = origin
        self.self_template = V.s(P.tok("harness") + "/" + self_path) if self_path else Unk("dynamic")
        self.env = env or {}
        self.parent: dict[int, tuple] = {}
        self.funcs: dict[str, S.FuncDef] = {}
        self.func_of: dict[int, str] = {}
        self.sourced: list[str] = []
        # rule (1): nothing after the script's own top-level exit runs, its function
        # definitions included (a disabled legacy installer's body)
        for i, n in enumerate(script.body):
            if _leaves_block(n):
                script.body = script.body[:i + 1]
                break
        self._build(script.body, None, None)

    def _build(self, body: list, owner, func: str | None, slot: str = "body") -> None:
        for i, n in enumerate(body):
            self.parent[id(n)] = (body, i, owner, slot)
            self.func_of[id(n)] = func or ""
            self._children(n, func)

    def _subs(self, n, func) -> None:
        """Command and process substitutions in n's words: their nodes get n
        as owner, so a variable inside resolves from n's position."""
        for w in node_words(n):
            for p in w.parts:
                if isinstance(p, (S.CmdSub, S.ProcSub)):
                    self._build(p.script.body, n, func, "cmdsub")
                elif isinstance(p, S.Var) and p.arg is not None:
                    for cs in words_cmdsubs(p.arg):
                        self._build(cs.script.body, n, func, "cmdsub")
                elif isinstance(p, S.ArrayLit):
                    for x in p.words:
                        for cs in words_cmdsubs(x):
                            self._build(cs.script.body, n, func, "cmdsub")

    def _children(self, n, func) -> None:
        self._subs(n, func)
        if isinstance(n, S.AndOr):
            items = [n.first] + [x for _, x in n.rest]
            for x in items:
                self.parent[id(x)] = (items, items.index(x), n, "andor")
                self.func_of[id(x)] = func or ""
                self._children(x, func)
        elif isinstance(n, S.Pipeline):
            for i, x in enumerate(n.cmds):
                self.parent[id(x)] = (n.cmds, i, n, "pipe")
                self.func_of[id(x)] = func or ""
                self._children(x, func)
        elif isinstance(n, S.If):
            for ci, (cond, body) in enumerate(n.clauses):
                self._build(cond, n, func, f"cond{ci}")
                self._build(body, n, func, f"body{ci}")
            if n.else_:
                self._build(n.else_, n, func, "else")
        elif isinstance(n, S.Loop):
            self._build(n.cond, n, func, "cond")
            self._build(n.body, n, func, "body")
        elif isinstance(n, S.For):
            self._build(n.body, n, func, "body")
        elif isinstance(n, S.Case):
            for ai, (pats, body, _) in enumerate(n.arms):
                self._build(body, n, func, f"arm{ai}")
        elif isinstance(n, S.Group):
            self._build(n.body, n, func, "body")
        elif isinstance(n, S.FuncDef):
            if n.name not in self.funcs:
                self.funcs[n.name] = n
            body = n.body
            self.parent[id(body)] = ([body], 0, n, "func")
            self.func_of[id(body)] = n.name
            self._children(body, n.name)


def iter_nodes(body: list):
    """Every node of a list, depth first, not entering function definitions."""
    for n in body:
        yield n
        yield from _iter_children(n)


def _iter_children(n):
    if isinstance(n, S.AndOr):
        yield from iter_nodes([n.first] + [x for _, x in n.rest])
    elif isinstance(n, S.Pipeline):
        yield from iter_nodes(n.cmds)
    elif isinstance(n, S.If):
        for cond, body in n.clauses:
            yield from iter_nodes(cond)
            yield from iter_nodes(body)
        if n.else_:
            yield from iter_nodes(n.else_)
    elif isinstance(n, S.Loop):
        yield from iter_nodes(n.cond)
        yield from iter_nodes(n.body)
    elif isinstance(n, S.For):
        yield from iter_nodes(n.body)
    elif isinstance(n, S.Case):
        for _, body, _ in n.arms:
            yield from iter_nodes(body)
    elif isinstance(n, S.Group):
        yield from iter_nodes(n.body)


def words_cmdsubs(word: S.Word):
    for p in word.parts:
        if isinstance(p, S.CmdSub):
            yield p
        elif isinstance(p, S.Var) and p.arg is not None:
            yield from words_cmdsubs(p.arg)
        elif isinstance(p, S.ArrayLit):
            for w in p.words:
                yield from words_cmdsubs(w)


def word_vars(word: S.Word) -> list:
    out = []
    for p in word.parts:
        if isinstance(p, S.Var):
            out.append(p.name)
            if p.arg is not None:
                out += word_vars(p.arg)
        elif isinstance(p, S.ArrayLit):
            for w in p.words:
                out += word_vars(w)
        elif isinstance(p, S.CmdSub):
            for n in iter_nodes(p.script.body):
                if isinstance(n, S.Simple):
                    for w in n.words:
                        out += word_vars(w)
                    for r in n.redirs:
                        if r.target is not None:
                            out += word_vars(r.target)
    return out


def node_words(n) -> list:
    ws: list = []
    if isinstance(n, S.Simple):
        ws = list(n.words) + [a[2] for a in n.assigns if a[2] is not None]
    elif isinstance(n, S.Test):
        ws = list(n.words)
    elif isinstance(n, S.Case):
        ws = [n.word]
    elif isinstance(n, S.For):
        ws = list(n.words or [])
    for r in getattr(n, "redirs", None) or []:
        if r.target is not None:
            ws.append(r.target)
        if r.heredoc is not None and r.heredoc.word is not None:
            ws.append(r.heredoc.word)
    return ws


class ShellAnalyzer:
    def __init__(self, py: pyscan.Analyzer, findings: M.Findings, file_set: set, read_text, chain_basename: str):
        self.py = py
        self.findings = findings
        self.file_set = file_set
        self.read_text = read_text
        self.chain_basename = chain_basename
        self.files: dict[str, ShFile] = {}
        self.summaries: dict[int, ShSummary] = {}
        self.in_progress: set = set()
        self.instantiated: dict[int, int] = {}
        self.all_param_effects: list = []
        self.memo: dict = {}
        self.prints: list = []
        self.id_forms: list = []
        self.depth = 0

    # ---------------------------------------------------------------- files
    def load(self, path: str) -> ShFile | None:
        if path in self.files:
            return self.files[path]
        try:
            src = self.read_text(path)
        except (OSError, UnicodeDecodeError):
            return None
        script = S.parse(src)
        f = ShFile(path, script, self_path=path)
        self.files[path] = f
        self.findings.files.append((path, "shell", "parsed" if not script.errors else "partial",
                                    ",".join(str(x) for x in script.errors[:20])))
        return f

    def analyze_file(self, f: ShFile) -> None:
        w = ShWalk(self, f, None)
        w.run(f.script.body)

    # ------------------------------------------------------------ functions
    def find_func(self, f: ShFile, name: str, seen=None) -> tuple | None:
        if name in f.funcs:
            return f, f.funcs[name]
        seen = seen or set()
        seen.add(f.component)
        for src in f.sourced:
            if src in seen:
                continue
            g = self.load(src)
            if g is not None:
                r = self.find_func(g, name, seen)
                if r:
                    return r
        return None

    def summary(self, f: ShFile, fd: S.FuncDef) -> ShSummary:
        key = id(fd)
        if key in self.summaries:
            return self.summaries[key]
        if key in self.in_progress:
            return ShSummary()
        self.in_progress.add(key)
        try:
            w = ShWalk(self, f, fd.name)
            w.run([fd.body])
            s = w.summary
        finally:
            self.in_progress.discard(key)
        self.summaries[key] = s
        return s


class ShWalk:
    def __init__(self, an: ShellAnalyzer, f: ShFile, func: str | None):
        self.an = an
        self.f = f
        self.func = func
        self.summary = ShSummary()
        self.ops: list[M.Op] = []
        self.reads: list = []          # (node, ReadInfo)
        self.decisions: list = []      # (node, Decision)
        self.chain: list = []          # (node, captured var or None, cond)
        self.printed: list = []
        self.captured_stack: list = []

    # ---------------------------------------------------------- evaluation
    def word(self, w: S.Word | None, at) -> V.Val:
        if w is None:
            return V.s("")
        vals, hints = [], []
        for p in w.parts:
            if isinstance(p, S.Lit):
                vals.append(V.s(p.text))
                hints.append(None)
            elif isinstance(p, S.Tilde):
                vals.append(V.s(P.tok("home")) if not p.user else Unk("dynamic"))
                hints.append(None)
            elif isinstance(p, S.Var):
                vals.append(self.var(p, at))
                hints.append(p.name)
            elif isinstance(p, S.CmdSub):
                vals.append(self.cmdsub(p.script, at))
                hints.append(None)
            elif isinstance(p, S.ArrayLit):
                return Lst(tuple(self.word(x, at) for x in p.words))
            else:
                vals.append(Unk("dynamic"))
                hints.append(None)
        if len(vals) == 1:
            return vals[0] if not isinstance(vals[0], Unk) else vals[0]
        if not vals:
            return V.s("")
        return V.concat(*vals, hints=hints)

    def var(self, p: S.Var, at) -> V.Val:
        base = self.var_base(p.name, at)
        if isinstance(base, Lst) and p.index is None and not p.op:
            # `$arr` is the array's first element (`"${arr[@]}"` stays every element)
            return base.items[0] if base.items else V.s("")
        op = p.op
        if op == "len":
            return Unk("dynamic")
        if op in (":-", "-", ":=", "="):
            if isinstance(base, Unk) and (base.reason.startswith("env") and base.hint is None) or isinstance(base, V.NoneV):
                d = self.word(p.arg, at)
                if isinstance(base, Unk) and isinstance(d, Str) and d.alts == ("",):
                    return base     # `${X:-}` says "unset is empty", not what X holds when set
                return d
            if isinstance(base, Str) and base.alts == ("",):
                return self.word(p.arg, at)
            return base
        if op in (":+", "+"):
            if isinstance(base, Unk) and base.reason.startswith("env"):
                return V.s("")
            return self.word(p.arg, at)
        if op in ("%", "%%", "#", "##") and isinstance(base, Str):
            pat = p.arg.literal() if p.arg is not None else None
            if pat is None:
                return base
            return V.map_str(base, lambda t: _trim(t, op, pat))
        if op in ("/", "//") and isinstance(base, Str) and p.arg is not None:
            raw = p.arg.literal()
            if raw and "/" in raw:
                a, b = raw.split("/", 1)
                if "*" not in a:
                    return V.map_str(base, lambda t: t.replace(a, b) if op == "//" else t.replace(a, b, 1))
            return base
        if op in ("^^", ",,"):
            fn = str.upper if op == "^^" else str.lower
            return V.map_str(base, lambda t: pyscan._apply_lit(t, fn)) if isinstance(base, Str) else base
        if op in (":",):
            return Unk("assembled:split")
        return base

    def var_base(self, name: str, at) -> V.Val:
        if name in ("0",) or name == "BASH_SOURCE":
            return self.f.self_template
        if name.isdigit() or name in ("@", "*"):
            if self.func is not None and name.isdigit() and name != "0":
                return V.s(P.param(str(int(name) + self._shifted(at))))
            if self.func is None and name.isdigit() and self.f.origin != "md-block" and name != "0" \
                    and not self._moves_args():
                return V.s(P.argv(int(name)))   # the script's own argument: bound per invocation
            return Unk("data:argv")
        if name in ("$", "!", "RANDOM", "BASHPID", "SRANDOM", "EPOCHREALTIME"):
            return V.s(P.WILD)
        if name in ("EPOCHSECONDS",):
            return V.s(P.tok("ts"))
        if name in ("?", "#", "-", "LINENO"):
            return Unk("dynamic")
        key = (id(at), name)
        if key in self.an.memo:
            return self.an.memo[key]
        if self.an.depth > 60:
            return Unk("assembled:recursive")
        self.an.memo[key] = Unk("assembled:recursive")
        self.an.depth += 1
        try:
            v = self._past_guard(name, at, self._var_lookup(name, at))
        finally:
            self.an.depth -= 1
        self.an.memo[key] = v
        return v

    def _past_guard(self, name: str, at, v: V.Val) -> V.Val:
        """In the branch of an `if` whose test says the variable differs from a literal
        (`[[ "$X" != "null" && ... ]]`, `[ "$X" != null ]`), the variable holds no such literal:
        that alternative of its value names nothing there."""
        if not isinstance(v, Str):
            return v
        excluded: set = set()
        cur = at
        for _ in range(200):
            info = self.f.parent.get(id(cur))
            if info is None:
                break
            _container, _idx, owner, slot = info
            if isinstance(owner, S.If) and slot.startswith("body"):
                for c in owner.clauses[int(slot[4:])][0]:
                    excluded |= _differs_from(c, name)
            if owner is None:
                break
            cur = owner
        alts = [a for a in v.alts if a not in excluded]
        if len(alts) == len(v.alts):
            return v
        # past the test only the values the static half could not name are left
        return V.make_str(alts) if alts else Unk("dynamic")

    def _moves_args(self) -> bool:
        """The script's top level shifts, resets or parses its arguments (shift, set --,
        getopts): $N there is no fixed position of an invocation's words."""
        moved = getattr(self.f, "_moves_args", None)
        if moved is None:
            moved = False
            for x in iter_nodes(self.f.script.body):
                if isinstance(x, S.Simple) and x.words:
                    w0 = x.words[0].literal()
                    if w0 in ("shift", "getopts") or w0 == "set" and any(w.literal() == "--" for w in x.words[1:]):
                        moved = True
                        break
            self.f._moves_args = moved
        return moved

    def _shifted(self, at) -> int:
        """How far `shift` moved the positional parameters before `at` in this
        function (shifts at the function's top level, in line order)."""
        fd = self.f.funcs.get(self.func or "")
        if fd is None:
            return 0
        line = getattr(at, "line", 0)
        n = 0
        body = fd.body.body if isinstance(fd.body, S.Group) else [fd.body]
        for x in body:
            items = [x] if not isinstance(x, S.AndOr) else [x.first] + [y for _, y in x.rest]
            for y in items:
                if isinstance(y, S.Simple) and y.words and y.words[0].literal() == "shift" and y.line < line:
                    k = y.words[1].literal() if len(y.words) > 1 else "1"
                    n += int(k) if (k or "").isdigit() else 1
        return n

    def _var_lookup(self, name: str, at) -> V.Val:
        defs = self.reaching(name, at)
        if defs:
            vals = [self.def_value(d, name) for d in defs[:6]]
            return vals[0] if len(vals) == 1 else V.union(vals)
        if name in self.f.env:
            return self.f.env[name]
        root = pyscan.ENV_ROOTS.get(name)
        if root:
            return V.s(P.tok(root))
        kind = P.classify_name(name)
        if kind in P.IDS:
            return Unk("env", hint=kind)
        if name.isupper():
            return Unk("env:" + name)
        return Unk("dynamic")

    # reaching definitions over the shell tree
    def reaching(self, name: str, at) -> list:
        out: list = []
        cur = at
        f = self.f
        guard = 0
        while cur is not None and guard < 200:
            guard += 1
            info = f.parent.get(id(cur))
            if info is None:
                break
            container, idx, owner, slot = info
            for n in reversed(container[:idx]):
                d, ds = self._defs_in(n, name)
                out += ds
                if d:
                    return out
            if owner is None:
                break
            if isinstance(owner, S.For) and owner.var == name:
                out.append(("for", owner, None))
                return out
            if isinstance(owner, S.Loop) and slot == "body":
                d, ds = self._defs_block(owner.cond, name)
                out += ds
            if isinstance(owner, S.If) and slot.startswith("body"):
                ci = int(slot[4:])
                d, ds = self._defs_block(owner.clauses[ci][0], name)
                out += ds
                if d:
                    return out
            if isinstance(owner, S.FuncDef):
                # globals as of the end of the file, those other functions
                # assign, then sourced files
                d, ds = self._defs_block(f.script.body, name)
                out += ds
                for fname in sorted(f.funcs):
                    if fname == owner.name:
                        continue
                    out += [x for x in self._defs_block([f.funcs[fname].body], name)[1]
                            if not self._is_local(x)]
                if not out:
                    out += self._sourced_defs(name)
                return out
            cur = owner
        if not out:
            out += self._sourced_defs(name)
        return out

    @staticmethod
    def _is_local(d) -> bool:
        node = d[1]
        return (d[0] == "assign" and isinstance(node, S.Simple) and bool(node.words)
                and node.words[0].literal() in ("local", "declare", "typeset"))

    def _sourced_defs(self, name: str) -> list:
        out = []
        for src in self.f.sourced:
            g = self.an.load(src)
            if g is None or g is self.f:
                continue
            d, ds = ShWalk(self.an, g, None)._defs_block(g.script.body, name)
            out += [("ext", g, x) for x in ds]
        return out

    def _defs_block(self, body: list, name: str):
        out = []
        for n in reversed(body or []):
            d, ds = self._defs_in(n, name)
            out += ds
            if d:
                return True, out
        return False, out

    def _defs_in(self, n, name: str):
        if isinstance(n, S.Simple):
            for a in n.assigns:
                if a[0] == name:
                    return (not n.words), [("assign", n, a)]
            if n.words:
                cmd = n.words[0].literal()
                if cmd in _DECL:
                    for w in n.words[1:]:
                        a = S._assignment(w)
                        if a and a[0] == name:
                            return True, [("assign", n, (a[0], a[1], a[2], n.line))]
                if cmd in ("read", "mapfile", "readarray"):
                    lits = [w.literal() for w in n.words[1:]]
                    if name in lits:
                        return True, [("read", n, None)]
                if cmd == "printf" and len(n.words) > 2 and n.words[1].literal() == "-v" and n.words[2].literal() == name:
                    return True, [("printfv", n, None)]
            return False, []
        if isinstance(n, S.AndOr):
            out = []
            items = [n.first] + [x for _, x in n.rest]
            definite = False
            for i, x in enumerate(reversed(items)):
                d, ds = self._defs_in(x, name)
                out += ds
                if d and i == len(items) - 1:
                    definite = True
            return definite, out
        if isinstance(n, S.Pipeline):
            out = []
            for x in n.cmds:
                out += self._defs_in(x, name)[1]
            return False, out
        if isinstance(n, S.If):
            out = []
            definite = n.else_ is not None
            for cond, body in n.clauses:
                out += self._defs_block(cond, name)[1]
                d, ds = self._defs_block(body, name)
                out += ds
                definite = definite and d
            if n.else_:
                d, ds = self._defs_block(n.else_, name)
                out += ds
                definite = definite and d
            return definite, out
        if isinstance(n, S.Loop):
            return False, self._defs_block(n.cond, name)[1] + self._defs_block(n.body, name)[1]
        if isinstance(n, S.For):
            out = [("for", n, None)] if n.var == name else []
            return False, out + self._defs_block(n.body, name)[1]
        if isinstance(n, S.Case):
            out = []
            for _, body, _ in n.arms:
                out += self._defs_block(body, name)[1]
            return False, out
        if isinstance(n, S.Group):
            if n.subshell:
                return False, []
            return self._defs_block(n.body, name)
        return False, []

    def def_value(self, d, name: str) -> V.Val:
        kind, node, extra = d
        if kind == "ext":
            g = node
            return ShWalk(self.an, g, None).def_value(extra, name)
        if kind == "assign":
            _, op, w, _ = extra
            val = self.word(w, node)
            if op == "+=":
                prev_defs = self.reaching(name, node)
                prev = V.union([self.def_value(x, name) for x in prev_defs[:4]]) if prev_defs else V.s("")
                if isinstance(prev, Lst) and isinstance(val, Lst):
                    return Lst(prev.items + val.items)
                return V.concat(prev, val, hints=[name, None])
            return val
        if kind == "read":
            for r in node.redirs:
                if r.op == "<<<" and r.target is not None:
                    v = self.word(r.target, node)
                    if isinstance(v, Unk):
                        return Unk(v.reason, hint=name)
                    return Unk("data:record", hint=name)
            return Unk("data:record", hint=name)
        if kind == "for":
            if node.words is None:
                return Unk("data:argv", hint=name)
            vals = [self.word(w, node) for w in node.words]
            flat = []
            for v in vals:
                if isinstance(v, Lst):
                    flat.extend(v.items)
                else:
                    flat.append(v)
            return V.union(flat) if flat else Unk("assembled:loop")
        if kind == "printfv":
            return Unk("dynamic", hint=name)
        return Unk("dynamic")

    # command substitution
    def cmdsub(self, script: S.Script, at) -> V.Val:
        body = script.body
        if not body:
            return V.s("")
        last = body[-1]
        if isinstance(last, S.AndOr):
            items = [last.first] + [x for _, x in last.rest]
            if len(items) >= 2 and isinstance(items[-1], S.Simple) and items[-1].words and items[-1].words[0].literal() == "pwd":
                cd = items[-2]
                if isinstance(cd, S.Simple) and cd.words and cd.words[0].literal() == "cd":
                    args = [w for w in cd.words[1:] if (w.literal() or "x")[:1] != "-"]
                    if args:
                        return self.word(args[0], cd)
            # first alternative that prints: `a || echo default`
            vals = [self.cmd_value(x, at) for x in items if isinstance(x, (S.Simple, S.Pipeline))]
            resolved = [v for v in vals if not isinstance(v, Unk) and not (isinstance(v, Str) and v.alts == ("",))]
            if resolved:
                return V.union(resolved)
            unk = [v for v in vals if isinstance(v, Unk)]
            return unk[0] if unk else (vals[0] if vals else Unk("assembled:stdout"))
        return self.cmd_value(last, at)

    def cmd_value(self, n, at) -> V.Val:
        if isinstance(n, S.Pipeline):
            first = n.cmds[0]
            lastc = n.cmds[-1]
            lv = self.cmd_value(lastc, at)
            names = [self._cmd_name(c) for c in n.cmds]
            if any(x in ("sha256sum", "md5sum", "sha1sum", "shasum", "cksum", "b2sum") for x in names):
                return V.s(P.WILD)
            if isinstance(lastc, S.Simple) and self._cmd_name(lastc) in ("jq", "python3", "python") and isinstance(first, S.Simple):
                src = self.cmd_value(first, at)
                if isinstance(src, Unk) and src.reason == "data:payload":
                    hint = lv.hint if isinstance(lv, Unk) else None
                    return Unk("data:payload", hint=hint)
            if names and names[-1] in ("tr", "sed", "cut", "awk", "head", "tail", "sort", "xargs", "grep"):
                if names[-1] in ("head", "tail") and len(n.cmds) >= 2:
                    prev = self.cmd_value(n.cmds[-2], at)
                    return prev if not isinstance(prev, Lst) else Unk("assembled:stdout")
                return Unk("assembled:stdout")
            return lv
        if isinstance(n, S.Group):
            return self.cmdsub(S.Script(n.body), at) if n.body else V.s("")
        if not isinstance(n, S.Simple) or not n.words:
            return Unk("assembled:stdout")
        words = self._strip_prefix(n.words)
        if not words:
            return Unk("assembled:stdout")
        name = self._cmd_name_words(words)
        args = words[1:]
        if name is None:
            return Unk("assembled:stdout")
        root = self._root_function(name)
        if root:
            return V.s(P.tok(root))
        fr = self.an.find_func(self.f, name)
        if fr is not None:
            g, fd = fr
            root = ROOT_SHELL_FUNCTIONS.get((g.component, name))
            if root:
                return V.s(P.tok(root))
            s = self.an.summary(g, fd)
            b = self._binding(args, n)
            return V.subst_val(s.printed, b) if not isinstance(s.printed, Unk) else s.printed
        if name in ("echo",):
            vals = [self.word(w, n) for w in args if not (w.literal() or "").startswith("-") or len(args) == 1]
            return self._join_words(vals) if vals else V.s("")
        if name == "printf":
            ws = list(args)
            if ws and ws[0].literal() == "-v":
                return V.s("")
            if not ws:
                return V.s("")
            fmt = self.word(ws[0], n)
            rest = [self.word(w, n) for w in ws[1:]]
            if isinstance(fmt, Str) and len(fmt.alts) == 1:
                return _printf(fmt.alts[0], rest)
            return Unk("assembled:stdout")
        if name == "dirname":
            ops = [w for w in args if not (w.literal() or "").startswith("-")]
            return V.dirname(self.word(ops[0], n)) if ops else Unk("dynamic")
        if name == "basename":
            ops = [w for w in args if not (w.literal() or "").startswith("-")]
            if not ops:
                return Unk("dynamic")
            v = V.basename(self.word(ops[0], n))
            if len(ops) > 1:
                sfx = ops[1].literal()
                if sfx:
                    v = V.map_str(v, lambda t: t[: -len(sfx)] if t.endswith(sfx) else t)
            return v
        if name in ("realpath", "readlink", "grealpath"):
            ops = [w for w in args if not (w.literal() or "").startswith("-")]
            return self.word(ops[0], n) if ops else Unk("dynamic")
        if name == "pwd":
            return V.s(P.tok("proj"))
        if name == "date":
            return V.s(P.tok("ts"))
        if name in ("uuidgen", "hostname", "whoami", "id", "openssl", "od"):
            return V.s(P.WILD)
        if name == "mktemp":
            return self._mktemp_value(args, n)
        if name == "git":
            lits = [w.literal() for w in args]
            top = P.tok("proj")
            if "-C" in lits and lits.index("-C") + 1 < len(args):
                # `git -C DIR`: the repository DIR lies in; a directory of the harness's own
                # checkout (the script's own directory) lies in the harness's repository
                d = V.as_templates(self.word(args[lits.index("-C") + 1], n))
                if d and all(t.startswith(P.tok("harness")) for t in d):
                    top = P.tok("harness")
            if "--show-toplevel" in lits:
                return V.s(top)
            if "--git-dir" in lits or "--git-common-dir" in lits or "--absolute-git-dir" in lits:
                return V.s(top + "/.git")
            return Unk("assembled:stdout")
        if name == "cat":
            ops = [w for w in args if not (w.literal() or "").startswith("-")]
            if not ops and not any(r.op in ("<", "<<<") for r in n.redirs):
                return Unk("data:payload")
            return Unk("data:record")
        if name == "jq":
            filt = None
            for w in args:
                lit = w.literal()
                if lit is not None and not lit.startswith("-"):
                    filt = lit
                    break
            hint = None
            if filt:
                m = re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)", filt)
                if m:
                    hint = m[-1]
            files = self._jq_files(args)
            src = "data:record" if files or any(r.op == "<" for r in n.redirs) else "data:payload"
            for r in n.redirs:
                if r.op == "<<<" and r.target is not None:
                    v = self.word(r.target, n)
                    if isinstance(v, Unk) and v.reason == "data:payload":
                        src = "data:payload"
                    elif isinstance(v, Unk):
                        src = v.reason
            return Unk(src, hint=hint)
        if _PY.search(name):
            code = " ".join(w.raw for w in args)
            hint = "session_id" if "session_id" in code else None
            return Unk("assembled:stdout", hint=hint)
        return Unk("assembled:stdout")

    def _root_function(self, name: str) -> str | None:
        """A root resolver the file sources: it wins over an inline fallback
        definition of the same name (`. lib/x.sh || x() { ...; }`)."""
        for (lib, fname), root in ROOT_SHELL_FUNCTIONS.items():
            if fname == name and (lib in self.f.sourced or self.f.component == lib):
                return root
        return None

    def _join_words(self, vals: list) -> V.Val:
        parts = []
        for i, v in enumerate(vals):
            if i:
                parts.append(V.s(" "))
            parts.append(v)
        return V.concat(*parts) if len(parts) > 1 else parts[0]

    def _mktemp_value(self, args, n) -> V.Val:
        tdir = None
        templ = None
        i = 0
        while i < len(args):
            lit = args[i].literal() or ""
            if lit in ("-p", "--tmpdir") and i + 1 < len(args):
                tdir = self.word(args[i + 1], n)
                i += 2
                continue
            if lit.startswith("--tmpdir="):
                tdir = V.s(lit.split("=", 1)[1])
            elif lit.startswith("-"):
                pass
            else:
                templ = self.word(args[i], n)
            i += 1
        if templ is not None:
            t = V.map_str(templ, lambda x: re.sub(r"X{3,}", P.RAND, x))
            if tdir is not None:
                return V.join(tdir, t)
            if isinstance(t, Str) and all("/" in a or a.startswith(P.L) for a in t.alts):
                return t
            return V.join(V.s(P.tok("tmpdir")), t)
        return V.join(tdir or V.s(P.tok("tmpdir")), V.s("tmp." + P.RAND))

    def _strip_prefix(self, words: list) -> list:
        i = 0
        while i < len(words):
            lit = words[i].literal()
            if lit in _PREFIX_CMDS:
                i += 1
                if lit == "flock":
                    while i < len(words) and (words[i].literal() or "").startswith("-"):
                        i += 1
                    i += 1
                continue
            if lit == "env":
                i += 1
                while i < len(words) and (S._assignment(words[i]) or (words[i].literal() or "").startswith("-")):
                    i += 1
                continue
            if lit == "timeout":
                i += 1
                while i < len(words) and (words[i].literal() or "").startswith("-"):
                    i += 1
                i += 1
                continue
            break
        return words[i:]

    def _cmd_name(self, n) -> str | None:
        if not isinstance(n, S.Simple) or not n.words:
            return None
        ws = self._strip_prefix(n.words)
        return self._cmd_name_words(ws) if ws else None

    def _cmd_name_words(self, words) -> str | None:
        if not words:
            return None
        lit = words[0].literal()
        if lit is not None:
            return lit.rsplit("/", 1)[-1] if "/" in lit and not lit.endswith((".sh", ".py")) else lit
        v = self.word(words[0], words[0])
        for t in V.as_templates(v):
            base = t.rsplit("/", 1)[-1]
            if _PY.search(base) or _SH.search(base):
                return base
        if any(isinstance(p, S.Var) and "PY" in p.name.upper() for p in words[0].parts):
            return "python3"
        ts = V.as_templates(v)
        return ts[0] if len(ts) == 1 else None

    def _binding(self, args, at) -> dict:
        b = {}
        for i, w in enumerate(args[:9], start=1):
            b[str(i)] = self.word(w, at)
        for i in range(len(args) + 1, 10):
            b[str(i)] = Unk("assembled:parameter")
        return b

    def _jq_files(self, args) -> list:
        """Operands of jq after its filter (options with values skipped)."""
        files = []
        filt_seen = False
        i = 0
        with_val = {"--arg": 2, "--argjson": 2, "--slurpfile": 2, "--rawfile": 2, "--indent": 1, "-f": 1, "--from-file": 1}
        while i < len(args):
            lit = args[i].literal()
            if lit in with_val:
                if lit in ("--slurpfile", "--rawfile") and i + 2 < len(args):
                    files.append(args[i + 2])
                if lit in ("-f", "--from-file"):
                    filt_seen = True
                i += 1 + with_val[lit]
                continue
            if lit is not None and lit.startswith("-") and lit != "-":
                if lit in ("-n", "--null-input"):
                    pass
                i += 1
                continue
            if _spread(args[i]):
                i += 1      # `"${ARGS[@]}"`: any number of words (here jq's own options), no operand
                continue
            if not filt_seen:
                filt_seen = True
            else:
                files.append(args[i])
            i += 1
        return files

    # ---------------------------------------------------------------- walk
    def run(self, body: list) -> None:
        self.walk(body, cond=False)
        self.finish()

    def walk(self, body: list, cond: bool) -> None:
        for n in body:
            self.node(n, cond)
            if _leaves_block(n):
                break   # rule (1): what follows an unconditional exit or return in its block never runs

    def node(self, n, cond: bool) -> None:
        if isinstance(n, S.Simple):
            self.simple(n, cond)
        elif isinstance(n, S.AndOr):
            self.node(n.first, True)
            for i, (op, x) in enumerate(n.rest):
                self.node(x, i < len(n.rest) - 1)
        elif isinstance(n, S.Pipeline):
            for x in n.cmds:
                self.node(x, cond)
        elif isinstance(n, S.If):
            for c, b in n.clauses:
                self.walk(c, True)
                self.walk(b, False)
            if n.else_:
                self.walk(n.else_, False)
            self.redirs(n, n.redirs)
        elif isinstance(n, S.Loop):
            self.walk(n.cond, True)
            self.walk(n.body, False)
            self.redirs(n, n.redirs)
        elif isinstance(n, S.For):
            for w in n.words or []:
                self.word_effects(w, n)
                v = self.word(w, n)
                if any(isinstance(p, S.Lit) and not p.quoted and ("*" in p.text or "?" in p.text) for p in w.parts):
                    self.emit("read", v, "list", "glob", n)
            self.walk(n.body, False)
            self.redirs(n, n.redirs)
        elif isinstance(n, S.Case):
            self.word_effects(n.word, n)
            for _, body, _ in n.arms:
                self.walk(body, False)
            self.redirs(n, n.redirs)
            self.case_literals(n)
        elif isinstance(n, S.Group):
            self.walk(n.body, cond)
            self.redirs(n, n.redirs)
        elif isinstance(n, S.Test):
            self.test(n.words, n)
        elif isinstance(n, S.FuncDef):
            pass

    def _cwd(self, line: int, n=None) -> V.Val | None:
        """The directory a `cd` before `line` moved the script to: the latest one before it in
        the innermost subshell around the operation that has one, else one earlier in the same
        function body, else a top-level one (any top-level cd for a function body, which runs
        after them). A cd to a directory the static half cannot root (a value computed at run
        time) leaves the relative paths after it under an unknown directory, never the project."""
        cache = getattr(self.f, "_cdcache", None)
        if cache is None:
            cache = self.f._cdcache = {}
        if n is not None:
            for scope in self._scopes(n):
                key = ("sub", id(scope))
                if key not in cache:
                    cache[key] = self._cds_in(scope.body, self.func, scope)
                own = [v for ln, v in cache[key] if ln < line]
                if own:
                    return own[-1]
        if self.func is not None:
            key = ("func", self.func)
            if key not in cache:
                fd = self.f.funcs.get(self.func)
                cache[key] = self._cds_in([fd.body], self.func, None) if fd is not None else []
            own = [v for ln, v in cache[key] if ln < line]
            if own:
                return own[-1]
        if "top" not in cache:
            cache["top"] = self._cds_in(self.f.script.body, None, None)
        before = [v for ln, v in cache["top"] if self.func is not None or ln < line]
        return before[-1] if before else None

    def _scope_of(self, x):
        """The innermost subshell group around x (None: the script's or a function's own shell;
        a pipeline or a command substitution: a shell of its own no cd here reaches)."""
        cur = x
        for _ in range(100):
            info = self.f.parent.get(id(cur))
            if info is None or info[2] is None:
                return None
            owner = info[2]
            if isinstance(owner, S.Group) and owner.subshell:
                return owner
            if isinstance(owner, S.Pipeline) or info[3] == "cmdsub":
                return False
            cur = owner
        return None

    def _scopes(self, n) -> list:
        """The subshell groups around n, innermost first."""
        out, cur = [], n
        for _ in range(100):
            sc = self._scope_of(cur)
            if not sc:
                break
            out.append(sc)
            cur = sc
        return out

    def _cds_in(self, body: list, func: str | None, scope) -> list:
        out = []
        for x in iter_nodes(body):
            if isinstance(x, S.Simple) and x.words and x.words[0].literal() == "cd" and len(x.words) > 1:
                args = [w for w in x.words[1:] if not (w.literal() or "").startswith("-")]
                if args and self._scope_of(x) is scope:
                    v = ShWalk(self.an, self.f, func).word(args[0], x)
                    temps = V.as_templates(v)
                    rooted = [t for t in temps if t.startswith(("/", P.L))]
                    if rooted:
                        out.append((x.line, V.make_str(rooted)))
                    elif not temps:
                        out.append((x.line, V.s(P.WILD)))
                    # a literal relative cd moves from the directory before it: kept as that one
        return out

    def _in_subshell(self, x) -> bool:
        cur = x
        for _ in range(100):
            info = self.f.parent.get(id(cur))
            if info is None or info[2] is None:
                return False
            owner = info[2]
            if (isinstance(owner, S.Group) and owner.subshell) or isinstance(owner, S.Pipeline) or info[3] == "cmdsub":
                return True
            cur = owner
        return False

    def _rebase(self, path: V.Val, line: int, n=None) -> V.Val:
        temps = V.as_templates(path)
        if not temps or not any(not t.startswith(("/", P.L, "~")) for t in temps):
            return path
        cwd = self._cwd(line, n)
        if cwd is None:
            return path
        return V.make_str([t if t.startswith(("/", P.L, "~")) else a
                           for t in temps for a in V.as_templates(V.join(cwd, V.s(t)))])

    def _feeds_tree_script(self, n) -> bool:
        """The command runs a script of the tree (`python3 <harness>/x`, `bash x.sh`, or the
        script itself)."""
        if not isinstance(n, S.Simple) or not n.words:
            return False
        ws = self._strip_prefix(n.words)
        if not ws:
            return False
        name = self._cmd_name_words(ws) or ""
        cand = ws[1:2] if (_PY.search(name) or name in ("bash", "sh")) else ws[:1]
        for w in cand:
            for t in V.as_templates(self.word(w, n)):
                if pyscan.tree_target(t, self.an.file_set):
                    return True
        return False

    def emit(self, op: str, path: V.Val, mode: str, via: str, n, src=None, chain=(), deciding=True) -> None:
        if isinstance(path, Lst):
            # an array expanded as an operand (`tail -f "${logs[@]}"`) is each of its elements
            # that names a path; option words and bare words in it (`--arg k v`) name none
            for item in path.items:
                alts = V.as_templates(item)
                if alts and all("/" in a and not a.startswith("-") for a in alts):
                    self.emit(op, item, mode, via, n, src=src, chain=chain)
            return
        line = getattr(n, "line", 0)
        if self.f.origin != "md-block":
            path = self._rebase(path, line, n)
            if src is not None:
                src = self._rebase(src, line, n)
        o = M.Op(self.f.component, line, op, path, mode, via, "shell", self.func or "", src, tuple(chain), self.f.origin)
        self.ops.append(o)
        if op == "read" and deciding:
            self.reads.append((n, pyscan.ReadInfo(path, mode, line, tuple(chain))))

    def redirs(self, n, redirs: list) -> None:
        for r in redirs:
            if r.heredoc is not None:
                if r.heredoc.word is not None:
                    self.word_effects(r.heredoc.word, n)
                continue
            if r.target is None:
                continue
            if r.op in (">&", "<&") and (r.target.literal() or "").strip("-").isdigit():
                continue
            if r.op == "<<<" or any(isinstance(p, S.ProcSub) for p in r.target.parts):
                self.word_effects(r.target, n)
                continue
            self.word_effects(r.target, n)
            v = self.word(r.target, n)
            if r.op in (">", ">|", "&>"):
                self.emit("write", v, "truncate", r.op, n)
            elif r.op in (">>", "&>>"):
                self.emit("write", v, "append", r.op, n)
            elif r.op == "<" and self._feeds_tree_script(n):
                # the harness script the command runs reads its standard input: the decision on
                # that content is the script's own, which the caller takes from its exit status
                self.emit("read", v, "stdin", "<", n, deciding=False)
            elif r.op == "<":
                self.emit("read", v, "content", "<", n)
            elif r.op == "<>":
                self.emit("read", v, "content", "<>", n)
                self.emit("write", v, "update", "<>", n)
            elif r.op == ">&":
                self.emit("write", v, "truncate", ">&", n)

    def word_effects(self, w: S.Word, n) -> None:
        for cs in words_cmdsubs(w):
            self.captured_stack.append(n)
            try:
                self.walk(cs.script.body, cond=False)
            finally:
                self.captured_stack.pop()
        for p in w.parts:
            if isinstance(p, S.ProcSub):
                self.walk(p.script.body, cond=False)

    def test(self, words: list, n) -> None:
        lits = [w.literal() for w in words]
        for i, lit in enumerate(lits):
            nxt = lits[i + 1] if i + 1 < len(lits) else None
            if lit in _TEST_UNARY and i + 1 < len(words) and not (nxt or "x").startswith("-") and nxt not in ("]", "]]"):
                self.emit("read", self.word(words[i + 1], n), "name", "test " + lit, n)
            if lit in ("-nt", "-ot", "-ef") and 0 < i < len(words) - 1:
                self.emit("read", self.word(words[i - 1], n), "name", "test " + lit, n)
                self.emit("read", self.word(words[i + 1], n), "name", "test " + lit, n)
        for w in words:
            self.word_effects(w, n)

    def simple(self, n: S.Simple, cond: bool) -> None:
        for a in n.assigns:
            if a[2] is not None:
                self.word_effects(a[2], n)
                if any(isinstance(p, (S.Var, S.CmdSub)) for p in a[2].parts):
                    for t in V.as_templates(self.word(a[2], n)):
                        form = pyscan.id_form_of(t)
                        if form:
                            self.an.id_forms.append((self.f.component, n.line, form, "shell"))
        for w in n.words:
            self.word_effects(w, n)
        self.redirs(n, n.redirs)
        words = self._strip_prefix(n.words)
        if not words:
            return
        name = self._cmd_name_words(words)
        args = words[1:]
        if [w.literal() for w in args[:2]] == ["-m", "venv"]:
            # `"$_PICK" -m venv DIR`: an interpreter picked at run time runs Python's venv module
            self._interpreter("python3", args, n)
            return
        if name is None:
            self._maybe_script(words, n)
            return
        if name in _DECL:
            return
        if name in ("[", "test", "[["):
            self.test(args, n)
            return
        if name in ("source", "."):
            if args:
                v = self.word(args[0], n)
                self.emit("read", v, "source", name, n)
                for t in V.as_templates(v):
                    tgt = pyscan.tree_target(t, self.an.file_set)
                    if tgt and tgt not in self.f.sourced:
                        self.f.sourced.append(tgt)
            return
        if name == "exit":
            code = self.word(args[0], n) if args else Num(0)
            self._exit(code, n)
            return
        fr = self.an.find_func(self.f, name)
        if fr is not None:
            self._call_func(fr, args, n)
            return
        self._command(name, words, args, n)

    def _exit(self, code: V.Val, n) -> None:
        val = None
        if isinstance(code, Num):
            val = code.value
        elif isinstance(code, Str) and len(code.alts) == 1 and code.alts[0].isdigit():
            val = int(code.alts[0])
        if val is None or val == 0:
            return
        d = M.Decision("exit2" if val == 2 else "exit", n.line, val)
        self.decisions.append((n, d))
        self.summary.decisions.append(d)

    def _call_func(self, fr, args, n) -> None:
        g, fd = fr
        if ROOT_SHELL_FUNCTIONS.get((g.component, fd.name)):
            return
        s = self.an.summary(g, fd)
        b = self._binding(args, n)
        for e in s.param_effects:
            self.an.instantiated[id(e)] = self.an.instantiated.get(id(e), 0) + 1
            p = V.subst_val(e.path, b)
            src = V.subst_val(e.src, b) if e.src is not None else None
            self.emit(e.op, p, e.mode, e.via, n, src=src, chain=(f"{e.component}:{e.line}",) + tuple(e.chain),
                      deciding=e.mode != "stdin")
        for r in s.reads:
            self.reads.append((n, pyscan.ReadInfo(V.subst_val(r.path, b), r.mode, n.line, (f"{g.component}:{r.line}",))))
        for d in s.decisions:
            nd = M.Decision(d.kind, n.line, d.code, fd.name, (f"{g.component}:{d.line}",))
            self.decisions.append((n, nd))
            self.summary.decisions.append(nd)
        if not self.captured_stack:
            for stream, t in s.print_params:
                for t2 in V.subst_params(t, b):
                    if self.func is not None and P.has_params(t2):
                        self.summary.print_params.append((stream, t2))
                    for shown in P.paths_in_text(P.shown_text(t2)):
                        self.an.prints.append((self.f.component, n.line, stream, shown, self.func or "", self.f.origin))
        for t in s.sysmsg_params:
            for t2 in V.subst_params(t, b):
                if self.func is not None and P.has_params(t2):
                    self.summary.sysmsg_params.append(t2)
                for shown in P.paths_in_text(P.shown_text(t2)):
                    self.an.findings.outputs.append(M.OwnerOutput(self.f.component, n.line, "system_message", shown))

    def _operands(self, args, with_value: set = frozenset()) -> list:
        out = []
        i = 0
        end_opts = False
        while i < len(args):
            lit = args[i].literal()
            if not end_opts and lit == "--":
                end_opts = True
                i += 1
                continue
            if not end_opts and lit is not None and lit.startswith("-") and lit != "-":
                if lit in with_value:
                    # an option never takes another option as its value (GNU `stat -f -c %T`
                    # beside BSD `stat -f %m`)
                    nxt = args[i + 1].literal() if i + 1 < len(args) else None
                    i += 1 if nxt is not None and nxt.startswith("-") and nxt != "-" else 2
                    continue
                i += 1
                continue
            if not end_opts and lit is None and _option_word(args[i]):
                i += 1      # `--exclude="$X"`: an option whose value is expanded, not an operand
                continue
            out.append(args[i])
            i += 1
        return out

    def _copy_targets(self, args, ops, ev) -> list:
        """(source word, destination value) of a cp, install, rsync or mv. The destination is a
        directory when -t names it, when it ends in '/', or when it receives two or more
        sources; a file copied or moved into a directory lands at the directory plus its name."""
        tdir = None
        for i, w in enumerate(args):
            lit = w.literal() or ""
            if lit in ("-t", "--target-directory") and i + 1 < len(args):
                tdir = ev(args[i + 1])
            elif lit.startswith("--target-directory="):
                tdir = V.s(lit.split("=", 1)[1])
        if tdir is not None:
            srcs, dst, into = ops, tdir, True
        elif len(ops) < 2:
            return []
        else:
            srcs, dst = ops[:-1], ev(ops[-1])
            into = len(srcs) > 1 or any(t.endswith("/") for t in V.as_templates(dst))
        return [(w, V.join(dst, V.basename(ev(w))) if into else dst) for w in srcs]

    def _command(self, name: str, words, args, n) -> None:
        ev = lambda w: self.word(w, n)  # noqa: E731
        if name in _READERS:
            value_opts = {"head": {"-n", "-c"}, "tail": {"-n", "-c"}, "sort": {"-k", "-t", "-o", "-S", "-T"},
                          "cut": {"-d", "-f", "-c", "-b"}, "stat": {"-c", "-f", "--format", "--printf"},
                          "wc": set(), "base64": {"-w"}, "xxd": {"-l", "-s", "-c"}, "od": {"-N", "-j", "-t", "-A"}}
            ops = self._operands(args, value_opts.get(name, set()))
            if name == "tr":
                return
            for w in ops:
                self.emit("read", ev(w), "content" if name not in ("stat", "file") else "name", name, n)
            return
        if name in ("grep", "egrep", "fgrep", "rg"):
            ops = self._operands(args, {"-e", "-f", "-m", "-A", "-B", "-C", "--include", "--exclude"})
            has_e = any((w.literal() or "") in ("-e", "-f") for w in args)
            files = ops if has_e else ops[1:]
            for w in files:
                self.emit("read", ev(w), "content", name, n)
            return
        if name == "sed":
            inplace = any((w.literal() or "").startswith("-i") or w.literal() == "--in-place" for w in args)
            ops = self._operands(args, {"-e", "-f"})
            has_e = any((w.literal() or "") in ("-e", "-f") for w in args)
            files = ops if has_e else ops[1:]
            for w in files:
                self.emit("read", ev(w), "content", name, n)
                if inplace:
                    self.emit("write", ev(w), "update", "sed -i", n)
            return
        if name in ("awk", "gawk"):
            ops = self._operands(args, {"-F", "-v", "-f"})
            for w in ops[1:]:
                if S._assignment(w) is None:
                    self.emit("read", ev(w), "content", name, n)
            return
        if name == "jq":
            for w in self._jq_files(args):
                self.emit("read", ev(w), "content", "jq", n)
            return
        if name in ("rm", "unlink"):
            recursive = any(re.match(r"^-[a-zA-Z]*[rR]", w.literal() or "") for w in args)
            for w in self._operands(args):
                self.emit("unlink", ev(w), "tree" if recursive else "file", name, n)
            return
        if name in ("rmdir",):
            return
        if name == "mv":
            ops = self._operands(args, {"-t", "--target-directory", "-S"})
            for w, dst in self._copy_targets(args, ops, ev):
                self.emit("rename", dst, "to", "mv", n, src=ev(w))
            return
        if name in ("cp", "install", "rsync"):
            ops = self._operands(args, {"-t", "-m", "-o", "-g", "--target-directory", "-e"})
            for w, dst in self._copy_targets(args, ops, ev):
                self.emit("read", ev(w), "content", name, n)
                self.emit("write", dst, "truncate", name, n)
            return
        if name == "ln":
            ops = self._operands(args, {"-t", "-S"})
            if len(ops) >= 2:
                self.emit("create", ev(ops[-1]), "link", "ln", n)
            return
        if name == "touch":
            for w in self._operands(args, {"-d", "-r", "-t"}):
                self.emit("create", ev(w), "touch", "touch", n)
            return
        if name == "tee":
            append = any((w.literal() or "") in ("-a", "--append") for w in args)
            for w in self._operands(args):
                self.emit("write", ev(w), "append" if append else "truncate", "tee", n)
            return
        if name in ("truncate", "shred"):
            for w in self._operands(args, {"-s", "--size", "-n"}):
                self.emit("write", ev(w), "truncate", name, n)
            return
        if name == "mktemp":
            if not any((w.literal() or "") in ("-d", "--directory") for w in args):
                self.emit("create", self._mktemp_value(args, n), "temp", "mktemp", n)
            return
        if name in ("find",):
            ops = []
            for w in args:
                lit = w.literal()
                if lit is not None and (lit.startswith("-") or lit in ("(", ")", "!")):
                    break
                ops.append(w)
            pat = None
            lits = [w.literal() for w in args]
            for i, lit in enumerate(lits):
                if lit in ("-name", "-iname") and i + 1 < len(args):
                    pat = ev(args[i + 1])
            for w in ops or []:
                p = V.join(ev(w), V.s("*"), pat) if pat is not None else V.join(ev(w), V.s("*"))
                self.emit("read", p, "list", "find", n)
                if "-delete" in lits:
                    self.emit("unlink", p, "file", "find -delete", n)
            return
        if name in ("ls",):
            for w in self._operands(args):
                self.emit("read", ev(w), "list", "ls", n)
            return
        if name in ("sqlite3",):
            ops = self._operands(args, {"-cmd", "-separator"})
            if ops:
                self.emit("read", ev(ops[0]), "db", "sqlite3", n)
                self.emit("write", ev(ops[0]), "db", "sqlite3", n)
            return
        if name in ("echo", "printf"):
            self._print(name, args, n)
            return
        if name in ("bash", "sh", "zsh", "dash") or _SH.search(name) or _PY.search(name) or name in ("node",):
            self._interpreter(name, args, n)
            return
        self._maybe_script(words, n)

    def _maybe_script(self, words, n) -> None:
        v = self.word(words[0], n)
        for t in V.as_templates(v):
            tgt = pyscan.tree_target(t, self.an.file_set)
            if tgt:
                self._invoked(tgt, "exec", words[1:], n)

    def _interpreter(self, name: str, args, n) -> None:
        is_py = bool(_PY.search(name))
        i = 0
        while i < len(args):
            lit = args[i].literal()
            if lit == "-c" and i + 1 < len(args):
                if is_py:
                    self._embedded_python(args[i + 1], n, args[i + 1].line)
                else:
                    code = self.word(args[i + 1], n)
                    if isinstance(code, Str) and len(code.alts) == 1 and P.L not in code.alts[0]:
                        sub = S.parse(code.alts[0], args[i + 1].line)
                        self.walk(sub.body, False)
                return
            if lit == "-m" and i + 1 < len(args) and is_py:
                mod = args[i + 1].literal()
                if mod == "venv":
                    # the venv module creates the tree it names (bin/activate, bin/python, ...)
                    for w in self._operands(args[i + 2:], {"--prompt"})[:1]:
                        self.emit("create", self.word(w, n), "tree", "python -m venv", n)
                    return
                if mod:
                    tgt = self.an.py.resolve_import(mod, self.f.component if not self.f.origin else "scripts/x.py")
                    if tgt:
                        self._invoked(tgt, "python3", args[i + 2:], n)
                return
            if lit == "-":
                if is_py:
                    for r in n.redirs:
                        if r.heredoc is not None:
                            self._embedded_python_heredoc(r.heredoc, n)
                return
            if lit is not None and lit.startswith("-") and len(lit) > 1:
                i += 2 if lit in ("-W", "-X", "-o", "-O") else 1
                continue
            v = self.word(args[i], n)
            for t in V.as_templates(v):
                tgt = pyscan.tree_target(t, self.an.file_set)
                if tgt:
                    self._invoked(tgt, "python3" if is_py else name, args[i + 1:], n)
                    if tgt.rsplit("/", 1)[-1] == self.an.chain_basename:
                        pass
            return
        if is_py:
            for r in n.redirs:
                if r.heredoc is not None:
                    self._embedded_python_heredoc(r.heredoc, n)

    def _invoked(self, target: str, interp: str, args, n) -> None:
        captured = bool(self.captured_stack)
        vals = tuple(self.word(w, n) for w in list(args)[:9])
        into = self._stdout_into(n)
        merged = any(r.fd == "2" and r.op == ">&" and r.target is not None and r.target.literal() == "1"
                     for r in getattr(n, "redirs", None) or [])
        self.an.findings.invocations.append(M.Invocation(self.f.component, n.line, target, interp, captured,
                                                         self.func or "", vals, into, bool(into) and merged))
        if self.an.chain_basename and target.rsplit("/", 1)[-1] == self.an.chain_basename:
            self.chain.append((n, self.captured_stack[-1] if self.captured_stack else None))

    def _stdout_into(self, n) -> tuple:
        """The files a command's stdout is written into: its own `>`/`>>` redirect, or, in a
        pipeline (`bash x 2>&1 | sed ... >> "$LOG"`), the last command's."""
        info = self.f.parent.get(id(n))
        cmds = info[0] if info and info[3] == "pipe" else [n]
        last = cmds[-1]
        out = []
        for r in getattr(last, "redirs", None) or []:
            if r.target is not None and r.op in (">", ">>", ">|", "&>", "&>>") and (r.fd in (None, "1")):
                v = self.word(r.target, last)
                if self.f.origin != "md-block":
                    v = self._rebase(v, getattr(last, "line", 0), last)
                out += V.as_templates(v)
        return tuple(sorted(set(out)))

    def _env_for_child(self, n) -> dict:
        env = {}
        for a in n.assigns:
            if a[2] is not None:
                env[a[0]] = self.word(a[2], n)
        for x in iter_nodes(self.f.script.body):
            if isinstance(x, S.Simple) and x.words and x.words[0].literal() == "export":
                for w in x.words[1:]:
                    a = S._assignment(w)
                    nm = a[0] if a else w.literal()
                    if nm and nm not in env:
                        v = self.word(a[2], x) if a else self.var_base(nm, n)
                        env[nm] = v
        return env

    def _code_text(self, w: S.Word, n) -> tuple[str, dict]:
        """The code with each shell expansion written as an identifier, and
        the identifiers' values (pyscan puts them back into string constants
        and binds the names)."""
        out = []
        values: dict = {}
        k = 0
        for p in w.parts:
            if isinstance(p, S.Lit):
                out.append(p.text)
                continue
            name = f"__sh_{k}__"
            k += 1
            if isinstance(p, S.Var):
                values[name] = self.var(p, n)
            elif isinstance(p, S.CmdSub):
                values[name] = self.cmdsub(p.script, n)
            else:
                values[name] = Unk("dynamic")
            out.append(name)
        return "".join(out), values

    def _embedded_python(self, w: S.Word, n, line: int) -> None:
        env = self._env_for_child(n)
        code, values = self._code_text(w, n)
        mod = self.an.py.add_embedded(self.f.component, code, line - 1, env, self.f.origin, values)
        if mod is not None:
            self._run_embedded(mod)
            return
        self.an.findings.files.append((self.f.component, "python-embedded", "syntax-error", str(line)))

    def _embedded_python_heredoc(self, hd: S.HereDoc, n) -> None:
        env = self._env_for_child(n)
        if hd.quoted or hd.word is None:
            mod = self.an.py.add_embedded(self.f.component, hd.body, hd.body_line - 1, env, self.f.origin)
        else:
            code, values = self._code_text(hd.word, n)
            mod = self.an.py.add_embedded(self.f.component, code, hd.body_line - 1, env, self.f.origin, values)
        if mod is None:
            self.an.findings.files.append((self.f.component, "python-embedded", "syntax-error", str(hd.body_line)))
            return
        self._run_embedded(mod)

    def _run_embedded(self, mod) -> None:
        py = self.an.py
        w = pyscan.FunctionWalk(py, mod, None)
        w.run()
        for q, fi in sorted(mod.funcs.items()):
            py.summary(fi)
        pyscan.literal_facts(mod, self.an.findings)

    def _print(self, name: str, args, n) -> None:
        stream = "stdout"
        for r in n.redirs:
            if r.op in (">&",) and (r.target.literal() or "") == "2":
                stream = "stderr"
            elif r.op in (">", ">>", ">|", "&>", "&>>") and r.target is not None:
                stream = "file"
        texts = []
        is_sysmsg = False
        for w in args:
            raw = w.raw
            if "systemMessage" in raw:
                is_sysmsg = True
            v = self.word(w, n)
            texts.extend(V.as_templates(v))
        if is_sysmsg:
            for t in texts:
                if self.func is not None and P.has_params(t):
                    self.summary.sysmsg_params.append(t)
                for shown in P.paths_in_text(P.shown_text(t)):
                    self.an.findings.outputs.append(M.OwnerOutput(self.f.component, n.line, "system_message", shown))
            self._relays(args, n)
        if stream in ("stdout", "stderr") and not self.captured_stack:
            for t in texts:
                if self.func is not None and P.has_params(t):
                    self.summary.print_params.append((stream, t))
                for shown in P.paths_in_text(P.shown_text(t)):
                    self.an.prints.append((self.f.component, n.line, stream, shown, self.func or "", self.f.origin))
        if stream == "stdout" and self.captured_stack == [] and self.func is not None:
            pass
        for t in texts:
            if re.search(r'"decision"\s*:\s*"(block|deny)"|"permissionDecision"\s*:\s*"deny"', t):
                d = M.Decision("block", n.line, None, "json-text")
                self.decisions.append((n, d))
                self.summary.decisions.append(d)

    def _relays(self, args, n) -> None:
        names = set()
        for w in args:
            names.update(word_vars(w))
        for nm in sorted(names):
            for d in self.reaching(nm, n):
                if d[0] != "assign":
                    continue
                w = d[2][2]
                if w is None:
                    continue
                for cs in words_cmdsubs(w):
                    for x in iter_nodes(cs.script.body):
                        if isinstance(x, S.Simple) and x.words:
                            ws = self._strip_prefix(x.words)
                            nm2 = self._cmd_name_words(ws) if ws else None
                            cands = []
                            if nm2 and (_SH.search(nm2) or _PY.search(nm2)):
                                for a in ws[1:]:
                                    if not (a.literal() or "").startswith("-"):
                                        cands.append(a)
                                        break
                            else:
                                cands.append(ws[0]) if ws else None
                            for c in cands:
                                for t in V.as_templates(self.word(c, x)):
                                    tgt = pyscan.tree_target(t, self.an.file_set)
                                    if tgt:
                                        self.an.findings.system_message_relays.append((self.f.component, n.line, tgt))

    def case_literals(self, n: S.Case) -> None:
        pairs = []
        alts = []
        for pats, body, line in n.arms:
            pl = [p.literal() for p in pats]
            pl = [p for p in pl if p is not None]
            if len(pl) >= 2:
                alts.append((line, tuple(pl)))
            val = None
            for x in body[:3]:
                if isinstance(x, S.AndOr):
                    x = x.first
                if isinstance(x, S.Simple) and x.words and x.words[0].literal() in ("echo", "printf"):
                    ws = [w.literal() for w in x.words[1:] if not (w.literal() or "").startswith("-")]
                    if ws and ws[-1] is not None:
                        val = ws[-1]
                        break
                if isinstance(x, S.Simple) and x.assigns and not x.words:
                    lit = x.assigns[0][2].literal() if x.assigns[0][2] is not None else None
                    if lit:
                        val = lit
                        break
            if val is not None:
                for p in pl:
                    pairs.append((p, val))
        for line, pl in alts:
            self.an.findings.literals.append(M.LiteralFact(self.f.component, line, "collection", pl, (), "shell"))
        if pairs:
            self.an.findings.literals.append(M.LiteralFact(self.f.component, n.line, "branch_map",
                                                           tuple(p for p, _ in pairs), tuple(pairs), "shell"))

    # ------------------------------------------------------------- finish
    def finish(self) -> None:
        for o in self.ops:
            temps = V.as_templates(o.path)
            if self.func is not None and temps and any(P.has_params(t) for t in temps):
                self.summary.param_effects.append(o)
                self.an.all_param_effects.append(o)
            else:
                self.an.findings.ops.append(o)
        if self.func is not None:
            self.summary.printed = self._printed_value()
            self.summary.reads = [r for _, r in self.reads if r.mode == "content"] if self._prints_any() else []
        self.decide()
        self.chain_uses()
        self.literals()
        self.env_reads()

    def _body(self) -> list:
        if self.func is None:
            return self.f.script.body
        fd = self.f.funcs.get(self.func)
        return [fd.body] if fd else []

    def _prints_any(self) -> bool:
        for x in iter_nodes(self._body()):
            if isinstance(x, S.Simple) and x.words and x.words[0].literal() in ("echo", "printf", "cat", "jq"):
                return True
        return False

    def _printed_value(self) -> V.Val:
        vals = []
        for x in iter_nodes(self._body()):
            if isinstance(x, S.Simple) and x.words and x.words[0].literal() in ("echo", "printf"):
                if any(r.target is not None and (r.op in (">", ">>") or (r.op == ">&" and r.target.literal() == "2")) for r in x.redirs):
                    continue
                vals.append(self.cmd_value(x, x))
        resolved = [v for v in vals if not isinstance(v, Unk)]
        if resolved:
            return V.union(resolved)
        return vals[0] if vals else Unk("assembled:stdout")

    def _taint(self, seeds: list) -> dict:
        """var -> set(seed index) through assignments in this body."""
        body = self._body()
        seed_ids = {id(s): i for i, s in enumerate(seeds)}
        assigns = []
        for x in iter_nodes(body):
            if isinstance(x, S.Simple):
                for a in x.assigns:
                    if a[2] is not None:
                        assigns.append((a[0], a[2], x))
                if x.words and x.words[0].literal() in _DECL:
                    for w in x.words[1:]:
                        a = S._assignment(w)
                        if a and a[2] is not None:
                            assigns.append((a[0], a[2], x))
                if x.words and x.words[0].literal() in ("read", "mapfile", "readarray"):
                    for w in x.words[1:]:
                        lit = w.literal()
                        if lit and not lit.startswith("-") and id(x) in seed_ids:
                            assigns.append((lit, None, x))
        tainted: dict = {}

        def seeds_in_word(w):
            out = set()
            for cs in words_cmdsubs(w):
                for y in iter_nodes(cs.script.body):
                    i = seed_ids.get(id(y))
                    if i is not None:
                        out.add(i)
            return out

        for _ in range(6):
            changed = False
            for name, w, x in assigns:
                src = set()
                if w is None:
                    src.add(seed_ids[id(x)])
                else:
                    src |= seeds_in_word(w)
                    for v in word_vars(w):
                        src |= tainted.get(v, set())
                if src:
                    cur = tainted.setdefault(name, set())
                    if not src <= cur:
                        cur |= src
                        changed = True
            if not changed:
                break
        return tainted

    def decide(self) -> None:
        if not self.reads:
            return
        nodes = [r[0] for r in self.reads]
        tainted = self._taint(nodes)
        read_idx: dict = {}
        for i, (node, info) in enumerate(self.reads):
            read_idx.setdefault(id(node), []).append(i)

        def reads_in(body: list) -> set:
            out = set()
            for x in iter_nodes(body):
                out.update(read_idx.get(id(x), []))
                if isinstance(x, S.Simple):
                    for w in node_words(x):
                        for cs in words_cmdsubs(w):
                            for y in iter_nodes(cs.script.body):
                                out.update(read_idx.get(id(y), []))
                for w in node_words(x):
                    for v in word_vars(w):
                        out |= tainted.get(v, set())
            return out

        def status_reads(body: list) -> set:
            # reads a condition tests by their command's own exit status (`if f; then`, `f || exit`):
            # the verdict of the function or command that read, not its output
            out = set()
            for x in iter_nodes(body):
                out.update(read_idx.get(id(x), []))
            return out

        dec_ids: dict = {}
        for node, d in self.decisions:
            dec_ids.setdefault(id(node), []).append(d)

        def decisions_in(body: list) -> list:
            out = []
            for x in iter_nodes(body):
                out += dec_ids.get(id(x), [])
            return out

        # the exits a guarded byte copy's failure takes (`cp "$X" "$B" || exit 1`): the branch's
        # existence test that guards the copy decides none of them (_guarded_copy)
        copy_failures = set()
        for x in iter_nodes(self._body()):
            if isinstance(x, S.AndOr):
                items = [x.first] + [y for _, y in x.rest]
                for k in range(len(items) - 1):
                    if any(self._guarded_copy(y) for y in iter_nodes([items[k]])):
                        copy_failures |= {id(d) for d in decisions_in(items[k + 1:])}
        paired = set()
        for x in iter_nodes(self._body()):
            if isinstance(x, S.If):
                for ci, (cond, body) in enumerate(x.clauses):
                    rs = reads_in(cond)
                    if not rs:
                        continue
                    later = []
                    for cj in range(ci, len(x.clauses)):
                        later += x.clauses[cj][1]
                    later += x.else_ or []
                    if not x.else_ and all(_sh_terminates(b) for _, b in x.clauses[ci:]):
                        info = self.f.parent.get(id(x))
                        if info is not None:
                            later += info[0][info[1] + 1:]
                    decs = [d for d in decisions_in(later) if id(d) not in copy_failures]
                    self._pair(rs, decs, x, paired, status_reads(cond))
            elif isinstance(x, S.Loop):
                rs = reads_in(x.cond)
                if rs:
                    self._pair(rs, decisions_in(x.body), x, paired, status_reads(x.cond))
            elif isinstance(x, S.AndOr):
                items = [x.first] + [y for _, y in x.rest]
                for k in range(len(items) - 1):
                    rs = {r for r in reads_in([items[k]]) if not self._guarded_copy(self.reads[r][0])}
                    if rs:
                        self._pair(rs, decisions_in(items[k + 1:]), x, paired, status_reads([items[k]]))
            elif isinstance(x, S.Case):
                rs = set()
                for v in word_vars(x.word):
                    rs |= tainted.get(v, set())
                for cs in words_cmdsubs(x.word):
                    for y in iter_nodes(cs.script.body):
                        rs.update(read_idx.get(id(y), []))
                if rs:
                    body = []
                    for _, b, _ in x.arms:
                        body += b
                    self._pair(rs, decisions_in(body), x, paired)
        for i, (node, info) in enumerate(self.reads):
            for dn, d in self.decisions:
                if d.kind in ("exit2", "block") and d.line > info.line and (i, id(d)) not in paired:
                    self._record(info, d, "order")

    def _pair(self, rs: set, decs: list, x, paired: set, whole: set = frozenset()) -> None:
        for r in sorted(rs):
            info = self.reads[r][1]
            if decs:
                for d in decs:
                    self._record(info, d, "branch", r in whole)
                    paired.add((r, id(d)))
            else:
                self._record(info, M.Decision("route", getattr(x, "line", 0)), "branch", r in whole)

    def _record(self, info, d, evidence: str, whole: bool = False) -> None:
        self.an.findings.deciding.append(M.Deciding(self.f.component, self.func or "", info.line, info.path,
                                                    info.mode, d, evidence, "shell", tuple(info.via), whole))

    def chain_uses(self) -> None:
        for node, holder in self.chain:
            uses, fields = set(), set()
            var = None
            if holder is not None and isinstance(holder, S.Simple):
                for a in holder.assigns:
                    if a[2] is not None and any(True for _ in words_cmdsubs(a[2])):
                        var = a[0]
                if var is None and holder.words and holder.words[0].literal() in _DECL:
                    for w in holder.words[1:]:
                        a = S._assignment(w)
                        if a:
                            var = a[0]
            if var is None:
                uses.add("verbatim")
            else:
                for x in iter_nodes(self._body()):
                    if x is holder:
                        continue
                    if not isinstance(x, (S.Simple, S.Test)):
                        continue
                    ws = node_words(x)
                    if isinstance(x, S.Simple):
                        ws += [r.target for r in x.redirs if r.target is not None]
                    if not any(var in _direct_vars(w) for w in ws):
                        continue
                    if isinstance(x, S.Simple) and not x.words:
                        continue  # copied into another variable
                    cmd = x.words[0].literal() if isinstance(x, S.Simple) and x.words else None
                    if cmd == "jq" or (isinstance(x, S.Simple) and self._cmd_name(x) == "jq"):
                        uses.add("fields")
                        for w in x.words[1:]:
                            lit = w.literal()
                            if lit and not lit.startswith("-"):
                                fields.update(re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)", lit))
                                break
                    elif cmd in ("echo", "printf", "cat"):
                        uses.add("verbatim")
                    elif cmd in ("[", "test") or isinstance(x, S.Test):
                        uses.add("fields")
                    else:
                        uses.add("verbatim")
                # jq on the var inside command substitutions anywhere
                for x in iter_nodes(self._body()):
                    for w in node_words(x):
                        for cs in words_cmdsubs(w):
                            for y in iter_nodes(cs.script.body):
                                if isinstance(y, S.Simple) and self._cmd_name(y) == "jq":
                                    hs = [r.target for r in y.redirs if r.target is not None]
                                    if any(var in word_vars(h) for h in hs):
                                        uses.add("fields")
                                        for wy in y.words[1:]:
                                            lit = wy.literal()
                                            if lit and not lit.startswith("-"):
                                                fields.update(re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)", lit))
                                                break
                if not uses:
                    uses.add("verbatim")
            # exit status used: the command sits in a condition
            if self._in_condition(holder or node):
                uses.add("status")
            self.an.findings.chain_calls.append(M.ChainCall(self.f.component, node.line, "exec", tuple(sorted(uses)),
                                                            tuple(sorted(fields)), self.func or ""))

    def _guarded_copy(self, n) -> bool:
        """A byte copy (`cp`, `install`, `rsync`) of a source that the condition of the branch
        it runs in has just found present (`if [ -f "$X" ]; then cp "$X" ...`): its exit status
        is the same for every content of the source, and the guard leaves it no absent source,
        so no mutation of the file changes the decision on its failure (E1)."""
        if not isinstance(n, S.Simple) or self._cmd_name(n) not in ("cp", "install", "rsync"):
            return False
        ws = self._strip_prefix(n.words)[1:]
        sources = {w.raw for w in ws[:-1] if w.raw and not w.raw.startswith("-")}
        cur = n
        for _ in range(50):
            info = self.f.parent.get(id(cur))
            if info is None:
                return False
            _container, _idx, owner, slot = info
            if isinstance(owner, S.If) and slot.startswith("body"):
                cond = owner.clauses[int(slot[4:])][0]
                for y in iter_nodes(cond):
                    tw = [w.raw for w in node_words(y)]
                    for i, t in enumerate(tw[:-1]):
                        if t in ("-f", "-e", "-s", "-r") and tw[i + 1] in sources:
                            return True
            if owner is None:
                return False
            cur = owner
        return False

    def _in_condition(self, n) -> bool:
        cur = n
        for _ in range(50):
            info = self.f.parent.get(id(cur))
            if info is None:
                return False
            container, idx, owner, slot = info
            if isinstance(owner, S.If) and slot.startswith("cond"):
                return True
            if isinstance(owner, S.Loop) and slot == "cond":
                return True
            if isinstance(owner, S.AndOr):
                return True
            if owner is None:
                return False
            cur = owner
        return False

    def literals(self) -> None:
        for x in iter_nodes(self._body()):
            if isinstance(x, S.For) and x.words:
                lits = [w.literal() for w in x.words]
                lits = [w for w in lits if w is not None]
                if len(lits) >= 2:
                    self.an.findings.literals.append(M.LiteralFact(self.f.component, x.line, "collection", tuple(lits), (), "shell"))
            if isinstance(x, S.Simple):
                for a in x.assigns:
                    w = a[2]
                    if w is not None:
                        for p in w.parts:
                            if isinstance(p, S.ArrayLit):
                                lits = [y.literal() for y in p.words if y.literal() is not None]
                                if len(lits) >= 2:
                                    self.an.findings.literals.append(M.LiteralFact(self.f.component, x.line, "collection", tuple(lits), (), "shell"))
                for w in x.words:
                    for p in w.parts:
                        if isinstance(p, S.Lit) and "|" in p.text and len(p.text) < 400:
                            toks = [t for t in re.split(r"[|()^$\s?:\\]+", p.text) if t]
                            if len(toks) >= 2:
                                self.an.findings.literals.append(M.LiteralFact(self.f.component, x.line, "alternation", tuple(toks), (), "shell"))

    def env_reads(self) -> None:
        seen = set()
        for x in iter_nodes(self._body()):
            ws = node_words(x)
            compared = []
            if isinstance(x, S.Test) or (isinstance(x, S.Simple) and x.words and x.words[0].literal() in ("[", "test")):
                compared = [w.literal() for w in ws if w.literal() not in (None, "[", "]", "=", "==", "!=", "-z", "-n", "test")]
            for w in ws:
                for p in _vars_with_default(w):
                    name, default = p
                    if not name.isupper() or len(name) < 3:
                        continue
                    if self.reaching(name, x):
                        continue
                    key = (x.line, name)
                    if key in seen:
                        continue
                    seen.add(key)
                    self.an.findings.env_reads.append(M.EnvRead(self.f.component, x.line, name, default,
                                                                tuple(sorted(c for c in compared if c))))
            if isinstance(x, S.Case):
                for v in word_vars(x.word):
                    if v.isupper() and not self.reaching(v, x):
                        pats = []
                        for ps, _, _ in x.arms:
                            pats += [p.literal() for p in ps if p.literal()]
                        self.an.findings.env_reads.append(M.EnvRead(self.f.component, x.line, v, None, tuple(sorted(set(pats)))))


def _spread(word: S.Word) -> bool:
    """A word that is one array or argument-list expansion ("${A[@]}", "$@"): zero or more words."""
    return len(word.parts) == 1 and isinstance(word.parts[0], S.Var) and (
        word.parts[0].index in ("@", "*") or word.parts[0].name in ("@", "*")) and not word.parts[0].op


def _option_word(word: S.Word) -> bool:
    """A word whose leading literal text is an option (`--exclude="$X"`, `-o"$out"`)."""
    first = word.parts[0] if word.parts else None
    return isinstance(first, S.Lit) and first.text.startswith("-") and len(first.text) > 1


def _direct_vars(word: S.Word) -> list:
    """Variables a word expands itself (not inside its command substitutions)."""
    out = []
    for p in word.parts:
        if isinstance(p, S.Var):
            out.append(p.name)
            if p.arg is not None:
                out += _direct_vars(p.arg)
    return out


def _differs_from(n, name: str) -> set:
    """The literals a test node (a `[[ ]]`, a `[`/`test` command, or an and-list of them) says
    $name differs from; none where an `||` or `-o` lets the test pass otherwise."""
    if isinstance(n, S.AndOr):
        if any(op != "&&" for op, _ in n.rest):
            return set()
        out: set = set()
        for x in [n.first] + [x for _, x in n.rest]:
            out |= _differs_from(x, name)
        return out
    if isinstance(n, S.Test):
        words = list(n.words)
    elif isinstance(n, S.Simple) and n.words and n.words[0].literal() in ("[", "test"):
        words = list(n.words[1:])
    else:
        return set()
    raws = [w.raw for w in words]
    if "||" in raws or "-o" in raws:
        return set()
    out = set()
    for i, w in enumerate(words):
        is_var = len(w.parts) == 1 and isinstance(w.parts[0], S.Var) and w.parts[0].name == name \
            and not w.parts[0].op and w.parts[0].index is None
        if not is_var:
            continue
        rest = raws[i + 1:i + 4]
        if rest[:1] == ["!="] and len(words) > i + 2:
            lit = words[i + 2].literal()
        elif rest[:2] == ["!", "="] and len(words) > i + 3:
            lit = words[i + 3].literal()
        else:
            continue
        if lit is not None:
            out.add(lit)
    return out


def _leaves_block(n) -> bool:
    """A command that is an `exit` or a `return` of its own (not one branch of an and-or list):
    nothing after it in the same block runs."""
    return isinstance(n, S.Simple) and bool(n.words) and n.words[0].literal() in ("exit", "return")


def _sh_terminates(body: list) -> bool:
    if not body:
        return False
    last = body[-1]
    if isinstance(last, S.AndOr):
        last = [last.first] + [x for _, x in last.rest]
        last = last[-1]
    return isinstance(last, S.Simple) and bool(last.words) and last.words[0].literal() in ("exit", "return", "continue", "break")


def _vars_with_default(w: S.Word) -> list:
    out = []
    for p in w.parts:
        if isinstance(p, S.Var):
            d = None
            if p.op in (":-", "-", ":=", "=") and p.arg is not None:
                d = p.arg.literal()
            out.append((p.name, d))
            if p.arg is not None:
                out += _vars_with_default(p.arg)
    return out


def _trim(t: str, op: str, pat: str) -> str:
    if "*" not in pat and "?" not in pat:
        if op in ("%", "%%"):
            return t[: -len(pat)] if pat and t.endswith(pat) else t
        return t[len(pat):] if t.startswith(pat) else t
    if op in ("%", "%%") and pat.endswith("*") and "*" not in pat[:-1]:
        lit = pat[:-1]
        idx = t.rfind(lit) if op == "%" else t.find(lit)
        return t[:idx] if idx >= 0 else t
    if op in ("#", "##") and pat.startswith("*") and "*" not in pat[1:]:
        lit = pat[1:]
        idx = t.find(lit) if op == "#" else t.rfind(lit)
        return t[idx + len(lit):] if idx >= 0 else t
    return t


def _printf(fmt: str, args: list) -> V.Val:
    fmt = fmt.replace("\\n", "").replace("\\t", "\t")
    pieces = re.split(r"(%[-#0 +]*\d*(?:\.\d+)?[sdqb])", fmt)
    vals = []
    i = 0
    for p in pieces:
        if re.fullmatch(r"%[-#0 +]*\d*(?:\.\d+)?[sdqb]", p):
            vals.append(args[i] if i < len(args) else V.s(""))
            i += 1
        else:
            vals.append(V.s(p.replace("%%", "%")))
    return V.concat(*vals) if vals else V.s("")
