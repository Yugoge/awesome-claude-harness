"""X6's enumerator: every blocking site of the hooks settings.json registers, found at test time.

Nothing here lists a site, a hook or a class. Enumerator reads settings.json and follows each
registered hook into the hooks/lib modules it imports (by name or by path) or sources, and into the
hooks it runs as a child process (relayed() then runs the parent with that child exiting 2: only a
child whose exit the parent relays contributes gate blocks). It walks their code:

* Python (ast): `sys.exit(2)`, `exit(2)`, `os._exit(2)`, `raise SystemExit(2)` (2 as a literal or a
  module constant); a `return 2` (or a tuple holding 2) in a function whose value reaches an exit; a
  dict or JSON text holding a block decision (`decision: block`, `permissionDecision: deny|ask`,
  `continue: false`, as hookrun.interpret reads them). A path the registered invocation never takes
  (an `if __name__ == "__main__"` block of an imported module, a branch on `sys.argv` the registered
  command, which passes no argument, does not satisfy) and a function of an imported module the hook
  never calls are no path of the hook;
* shell (line scan, comments and here-documents aside): `exit 2`, and the same JSON decision text;
* helpers: a function that blocks unconditionally (the primitive in its own top-level body) is a
  helper; each call of it is the site, transitively, across the modules followed.

unaccounted() cross-checks the walk against a plain token scan of each registered hook's own file.
Each Site keeps its file, line, function, the source of the conditions guarding it (enclosing tests,
early returns), the string constants of its message, and the registrations (event, matcher) of the
hooks that reach it. classify() derives one class per site from that code and those registrations
(X6 (ii)), with the rule that fired; unreachable() proves a site no path runs. match() maps a block a
replay recorded to the sites whose message pieces its text holds (X6 (iv)).
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from dataclasses import dataclass, field

EXIT_FUNCS = {("sys", "exit"), ("os", "_exit")}
EXIT_NAMES = {"exit", "quit", "SystemExit"}
DECISION_TEXT = re.compile(r'"(?:decision)"\s*:\s*"block"|"permissionDecision"\s*:\s*"(?:deny|ask)"'
                           r'|"continue"\s*:\s*false')
DECISION_PAIRS = {("decision", "block"), ("permissionDecision", "deny"), ("permissionDecision", "ask"),
                  ("continue", False)}
TIME_CALLS = re.compile(r"\b(?:datetime\.now|time\.time|datetime\.utcnow)\b")


@dataclass
class Site:
    file: str            # repository-relative
    line: int
    func: str            # enclosing function ("<module>" at top level)
    kind: str            # exit2 | return2 | decision | call
    via: str = ""        # the helper a call site calls (file:function)
    conds: list = field(default_factory=list)   # source of the guarding conditions, outermost first
    text: list = field(default_factory=list)    # string constants of the message
    handler: bool = False  # inside an except handler (the code failed to decide)
    unconditional: bool = False
    regs: list = field(default_factory=list)    # (hook, event, matcher) that reach it
    helper_text: list = field(default_factory=list)  # a call site: its helper's message constants
    helper_conds: list = field(default_factory=list)
    dynamic: bool = False  # the message interpolates a value (it can name the call it refuses)
    role: str = ""

    @property
    def id(self) -> str:
        return f"{self.file}:{self.line}"

    def all_text(self) -> str:
        return "\n".join(self.text + self.helper_text)


# ------------------------------------------------------------------ registration

def registered(tree: str) -> dict[str, list[tuple[str, str]]]:
    """{hook file (repository-relative): [(event, matcher), ...]} from settings.json's hooks entries."""
    with open(os.path.join(tree, "settings.json")) as fh:
        settings = json.load(fh)
    out: dict[str, list] = {}
    for event, groups in (settings.get("hooks") or {}).items():
        for g in groups:
            for h in g.get("hooks", []):
                m = re.findall(r"""/((?:hooks|scripts)/[^"'\s]+)""", h.get("command") or "")
                if m and os.path.isfile(os.path.join(tree, m[-1])):
                    out.setdefault(m[-1], []).append((event, g.get("matcher") or ""))
    return out


# ------------------------------------------------------------------ Python

def _const_str(node) -> list[str]:
    """The string constants under node, docstrings and bare string statements left out."""
    out, skip = [], set()
    for n in ast.walk(node):
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
            skip.add(id(n.value))
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.strip() and id(n) not in skip:
            out.append(n.value)
    return out


def _flow_text(mod, func, call) -> list[str]:
    """The string constants a Name argument of `call` is built from inside `func`: the values
    assigned to it (transitively through the names they read) and the `return` values of the
    module's own functions those values call."""
    todo, seen, out = [a.id for a in call.args if isinstance(a, ast.Name)], set(), []
    assigns = [n for n in ast.walk(func) if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and n.value]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        for a in assigns:
            if not any(isinstance(t, ast.Name) and t.id == name for t in getattr(a, "targets", None) or [a.target]):
                continue
            out += _const_str(a.value)
            for n in ast.walk(a.value):
                if isinstance(n, ast.Name):
                    todo.append(n.id)
                elif isinstance(n, ast.Call) and _call_name(n.func)[0] is None and _call_name(n.func)[1] in mod.funcs:
                    out += [t for r in ast.walk(mod.funcs[_call_name(n.func)[1]])
                            if isinstance(r, ast.Return) and r.value is not None for t in _const_str(r.value)]
    return out


def _call_name(func) -> tuple:
    if isinstance(func, ast.Name):
        return (None, func.id)
    if isinstance(func, ast.Attribute):
        base = func.value
        if isinstance(base, ast.Name):
            return (base.id, func.attr)
        return ("?", func.attr)
    return (None, None)


class PyModule:
    def __init__(self, tree: str, rel: str):
        self.tree, self.rel = tree, rel
        with open(os.path.join(tree, rel)) as fh:
            self.src = fh.read()
        self.ast = ast.parse(self.src)
        self.lines = self.src.splitlines()
        self.consts = {}
        for st in self.ast.body:
            if isinstance(st, ast.Assign) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, int):
                for t in st.targets:
                    if isinstance(t, ast.Name):
                        self.consts[t.id] = st.value.value
        self.funcs: dict[str, ast.AST] = {}
        self.parent: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(self.ast):
            for ch in ast.iter_child_nodes(node):
                self.parent[ch] = node
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.funcs.setdefault(node.name, node)
        self.imports = self._imports()

    # ---- imports: local name -> (module rel, attr or None)
    def _resolve_mod(self, name: str) -> str | None:
        here = os.path.dirname(self.rel)
        parts = name.split(".")
        cands = []
        if parts[0] == "lib":
            cands.append(os.path.join("hooks", *parts) + ".py")
            cands.append(os.path.join("hooks", *parts, "__init__.py"))
        elif parts[0] == "hooks":
            cands.append(os.path.join(*parts) + ".py")
        else:
            cands += [os.path.join(here, *parts) + ".py", os.path.join("hooks", "lib", *parts) + ".py",
                      os.path.join(here, *parts, "__init__.py")]
        return next((c for c in cands if os.path.isfile(os.path.join(self.tree, c))), None)

    def _imports(self) -> dict:
        out = {}
        for node in ast.walk(self.ast):
            if isinstance(node, ast.Import):
                for a in node.names:
                    mod = self._resolve_mod(a.name)
                    if mod:
                        out[a.asname or a.name.split(".")[0]] = (mod, None)
            elif isinstance(node, ast.ImportFrom):
                base = ("." * node.level) + (node.module or "")
                for a in node.names:
                    if node.level:
                        pkg = os.path.dirname(self.rel)
                        modname = node.module.split(".") if node.module else []
                        sub = os.path.join(pkg, *modname, a.name) + ".py"
                        mod = os.path.join(pkg, *modname) + ".py"
                        if os.path.isfile(os.path.join(self.tree, sub)):
                            out[a.asname or a.name] = (sub, None)
                        elif os.path.isfile(os.path.join(self.tree, mod)):
                            out[a.asname or a.name] = (mod, a.name)
                        continue
                    sub = self._resolve_mod(f"{base}.{a.name}")
                    mod = self._resolve_mod(base)
                    if sub:
                        out[a.asname or a.name] = (sub, None)
                    elif mod:
                        out[a.asname or a.name] = (mod, a.name)
        return out

    def loaded_files(self) -> tuple[list[str], list[str]]:
        """(files it runs as a child process, files it imports by path): a constant naming a file in
        hooks/ or hooks/lib/, joined to a directory (`/` or os.path.join). A child is one the module
        hands to an interpreter (its tuple or list also holds sys.executable or a shell name)."""
        procs, loads = [], []
        for node in ast.walk(self.ast):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str) and
                    re.fullmatch(r"[\w.-]+\.(?:py|sh)", node.value)):
                continue
            par = self.parent.get(node)
            if not (isinstance(par, ast.BinOp) and isinstance(par.op, ast.Div)) and not (
                    isinstance(par, ast.Call) and _call_name(par.func)[1] == "join"):
                continue
            rel = next((os.path.join(d, node.value) for d in ("hooks", "hooks/lib")
                        if os.path.isfile(os.path.join(self.tree, d, node.value))), None)
            if rel is None or rel == self.rel:
                continue
            up, child = par, False
            for _ in range(4):
                up = self.parent.get(up)
                if isinstance(up, (ast.Tuple, ast.List)):
                    src = ast.get_source_segment(self.src, up) or ""
                    child = "sys.executable" in src or bool(re.search(r"[\"'](?:bash|sh|python3?)[\"']", src))
                    break
            (procs if child else loads).append(rel)
        return sorted(set(procs)), sorted(set(loads))

    def imported_files(self) -> list[str]:
        return sorted({m for m, _ in self.imports.values()} - {self.rel})

    # ---- structure helpers
    def enclosing_func(self, node) -> ast.AST | None:
        p = self.parent.get(node)
        while p is not None and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
            p = self.parent.get(p)
        return p

    def conds(self, node) -> tuple[list[str], bool]:
        """The source of the if/while tests guarding node within its function, and whether it lies in
        an except handler."""
        out, handler = [], False
        ch, p = node, self.parent.get(node)
        while p is not None and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            if isinstance(p, (ast.If, ast.While)) and ch is not p.test:
                neg = ch in p.orelse
                out.append(("not " if neg else "") + "(" + ast.get_source_segment(self.src, p.test) + ")")
            elif isinstance(p, ast.IfExp) and ch is not p.test:
                out.append(("not " if ch is p.orelse else "") + "(" + ast.get_source_segment(self.src, p.test) + ")")
            elif isinstance(p, ast.BoolOp):
                idx = p.values.index(ch) if ch in p.values else 0
                for v in p.values[:idx]:
                    out.append(("not " if isinstance(p.op, ast.Or) else "") + "(" +
                               ast.get_source_segment(self.src, v) + ")")
            elif isinstance(p, (ast.For, ast.AsyncFor)) and ch is not p.iter:
                out.append("for " + ast.get_source_segment(self.src, p.target) + " in " +
                           ast.get_source_segment(self.src, p.iter))
            elif isinstance(p, ast.ExceptHandler):
                handler = True
                out.append("except " + (ast.get_source_segment(self.src, p.type) if p.type else ""))
            elif type(p).__name__ == "match_case":
                out.append("case " + ast.get_source_segment(self.src, p.pattern))
            out += self._early_returns(ch, p)
            ch, p = p, self.parent.get(p)
        if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            out += self._early_returns(ch, p)
        return list(reversed(out)), handler

    def _early_returns(self, ch, p) -> list[str]:
        """`if <test>: return / exit(0) / continue` statements before ch in its block: the site runs only
        when each test is false (a `!=` / `not in` test read as its positive form)."""
        out = []
        for attr in ("body", "orelse", "finalbody"):
            b = getattr(p, attr, None)
            if not (isinstance(b, list) and ch in b):
                continue
            for st in b[:b.index(ch)]:
                if not (isinstance(st, ast.If) and not st.orelse and st.body and
                        isinstance(st.body[-1], (ast.Return, ast.Continue)) or isinstance(st, ast.If) and
                        not st.orelse and st.body and isinstance(st.body[-1], ast.Expr) and
                        isinstance(st.body[-1].value, ast.Call) and _call_name(st.body[-1].value.func) in EXIT_FUNCS
                        and st.body[-1].value.args and isinstance(st.body[-1].value.args[0], ast.Constant)
                        and st.body[-1].value.args[0].value == 0):
                    continue
                t = st.test
                src = ast.get_source_segment(self.src, t) or ""
                if isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], (ast.NotEq, ast.NotIn)):
                    out.append("(" + src.replace("not in", "in").replace("!=", "==") + ")")
                else:
                    out.append("not (" + src + ")")
        return list(reversed(out))

    def statement(self, node):
        p = node
        while p is not None and not isinstance(self.parent.get(p), (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                                                    ast.If, ast.For, ast.While, ast.Try,
                                                                    ast.ExceptHandler, ast.With)):
            p = self.parent.get(p)
        return p or node

    def top_level(self, node, func) -> bool:
        """node runs on every call of func: its statement lies in func's own body (a `with` allowed)."""
        st = self.statement(node)
        p = self.parent.get(st)
        while isinstance(p, ast.With):
            p = self.parent.get(p)
        return func is not None and p is func and st in func.body

    def message(self, node) -> list[str]:
        """The string constants of the statement holding node and of up to six statements before it in
        the same block (the print / write / helper call composing the message)."""
        st = self.statement(node)
        par = self.parent.get(st)
        body = None
        for attr in ("body", "orelse", "finalbody", "handlers"):
            b = getattr(par, attr, None)
            if isinstance(b, list) and st in b:
                body = b
                break
        out = _const_str(st)
        stmts = [st]
        if body is not None:
            i = body.index(st)
            stmts = body[max(0, i - 6):i + 1]
            for prev in body[max(0, i - 6):i]:
                out = _const_str(prev) + out
        for f in self._called_locals(stmts):
            out += _const_str(f)
        return [s for s in out if len(s.strip()) >= 4]

    def _called_locals(self, stmts) -> list:
        """The module's own functions the statements call (one level: the message writer a block
        statement calls before it exits)."""
        out = []
        for x in stmts:
            for n in ast.walk(x):
                if isinstance(n, ast.Call):
                    base, name = _call_name(n.func)
                    if base in (None, "self") and name in self.funcs and self.funcs[name] not in out:
                        out.append(self.funcs[name])
        return out

    def dynamic(self, node, own: bool = False) -> bool:
        """Whether the message statements around node interpolate a value (f-string, %, format, +)."""
        st = self.statement(node)
        par = self.parent.get(st)
        stmts = [st]
        for attr in ("body", "orelse", "finalbody"):
            b = getattr(par, attr, None)
            if isinstance(b, list) and st in b and not own:
                stmts = b[max(0, b.index(st) - 6):b.index(st) + 1]
        for x in stmts + self._called_locals(stmts):
            for n in ast.walk(x):
                if isinstance(n, ast.FormattedValue) or isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Mod, ast.Add)) \
                        and any(isinstance(o, ast.Constant) and isinstance(o.value, str) for o in (n.left, n.right)) \
                        or isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "format":
                    return True
        return False

    def value_is(self, expr, want: int, func) -> bool:
        if isinstance(expr, ast.Constant) and expr.value == want and not isinstance(expr.value, bool):
            return True
        if isinstance(expr, ast.Name) and self.consts.get(expr.id) == want:
            return True
        return False


@dataclass
class _Prim:
    node: ast.AST
    kind: str
    ok_main: bool = True     # reachable when the module runs as the hook's own process
    ok_import: bool = True   # reachable when the module is imported


_GUARD_NAMES = {"__name__", "sys", "len"}


def _guard(mod: "PyModule", node, as_main: bool, argv: list) -> bool:
    """False when an enclosing `if` tests only `__name__` / `sys.argv` and that test, evaluated for
    this invocation (as the hook's own process with its registered argv, or as an import), excludes
    node."""
    ch, p = node, mod.parent.get(node)
    ns = {"__name__": "__main__" if as_main else "imported", "len": len,
          "sys": type("S", (), {"argv": argv})}
    while p is not None:
        if isinstance(p, (ast.If, ast.IfExp)) and ch is not p.test:
            names = {n.id for n in ast.walk(p.test) if isinstance(n, ast.Name)}
            attrs = {n.attr for n in ast.walk(p.test) if isinstance(n, ast.Attribute)}
            if names and names <= _GUARD_NAMES and attrs <= {"argv"} and \
                    ("__name__" in names or "argv" in attrs):
                try:
                    val = bool(eval(compile(ast.Expression(p.test), "<guard>", "eval"), ns))  # noqa: S307
                except Exception:  # noqa: BLE001 - a test it cannot evaluate guards nothing here
                    val = None
                orelse = p.orelse if isinstance(p.orelse, list) else [p.orelse]
                if val is not None and val == (ch in orelse):
                    return False
        ch, p = p, mod.parent.get(p)
    return True


def _py_primitives(mod: PyModule, argv: list) -> list[_Prim]:
    """Every exit-2 / return-2 / decision node of one module (return-2 only in exit-reaching
    functions), each with whether it is reachable as the hook's process and as an import."""
    prims: list[_Prim] = []
    rc_funcs: dict[str, list] = {}

    def flags(node):
        return _guard(mod, node, True, argv), _guard(mod, node, False, argv)

    def seed(name, fl):
        cur = rc_funcs.get(name, [False, False])
        rc_funcs[name] = [cur[0] or fl[0], cur[1] or fl[1]]

    def exit_arg(call):
        if isinstance(call, ast.Call):
            mname = _call_name(call.func)
            if mname in EXIT_FUNCS or (mname[0] is None and mname[1] in EXIT_NAMES):
                return call.args[0] if call.args else None
        return None

    for node in ast.walk(mod.ast):
        if isinstance(node, ast.Call) and not isinstance(mod.parent.get(node), ast.Raise) or \
                isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            call = node.exc if isinstance(node, ast.Raise) else node
            arg = exit_arg(call)
            if arg is not None:
                fl = flags(node)
                if mod.value_is(arg, 2, None):
                    prims.append(_Prim(node, "exit2", *fl))
                elif isinstance(arg, ast.Call):
                    seed(_call_name(arg.func)[1], fl)
                elif isinstance(arg, ast.Name):
                    func = mod.enclosing_func(node)
                    for n in ast.walk(func or mod.ast):
                        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == arg.id
                                                             for t in n.targets):
                            if mod.value_is(n.value, 2, func):
                                prims.append(_Prim(n, "exit2", *fl))
                            elif isinstance(n.value, ast.Call):
                                seed(_call_name(n.value.func)[1], fl)
                            elif isinstance(n.value, ast.IfExp):
                                for b in (n.value.body, n.value.orelse):
                                    if mod.value_is(b, 2, func):
                                        prims.append(_Prim(b, "exit2", *fl))
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant) and \
                        (k.value, v.value) in DECISION_PAIRS and not (k.value == "continue" and v.value is not False):
                    prims.append(_Prim(node, "decision", *flags(node)))
                    break
        if isinstance(node, ast.Call) and _call_name(node.func) == (None, "dict"):
            for kw in node.keywords:
                if isinstance(kw.value, ast.Constant) and (kw.arg, kw.value.value) in DECISION_PAIRS:
                    prims.append(_Prim(node, "decision", *flags(node)))
                    break
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and DECISION_TEXT.search(node.value):
            if not isinstance(mod.parent.get(node), ast.Expr):  # a docstring describes, it does not print
                prims.append(_Prim(node, "decision", *flags(node)))

    # functions whose return value reaches an exit: their returns of 2
    done: dict[str, list] = {}
    while any(done.get(k) != v for k, v in rc_funcs.items()):
        fname = next(k for k, v in rc_funcs.items() if done.get(k) != v)
        fl = done[fname] = list(rc_funcs[fname])
        f = mod.funcs.get(fname)
        if f is None:
            continue
        for n in ast.walk(f):
            if not (isinstance(n, ast.Return) and n.value is not None and mod.enclosing_func(n) is f):
                continue
            v = n.value
            if mod.value_is(v, 2, f) or isinstance(v, ast.Tuple) and any(mod.value_is(e, 2, f) for e in v.elts):
                prims.append(_Prim(n, "return2", *fl))
            elif isinstance(v, ast.IfExp):
                for b in (v.body, v.orelse):
                    if mod.value_is(b, 2, f):
                        prims.append(_Prim(b, "return2", *fl))
            elif isinstance(v, ast.Call):
                seed(_call_name(v.func)[1], fl)
            elif isinstance(v, ast.Name):
                for a in ast.walk(f):
                    if not isinstance(a, ast.Assign):
                        continue
                    for t in a.targets:
                        names = [t] if isinstance(t, ast.Name) else list(getattr(t, "elts", []))
                        if not any(isinstance(x, ast.Name) and x.id == v.id for x in names):
                            continue
                        if isinstance(a.value, ast.Call):
                            seed(_call_name(a.value.func)[1], fl)
                        elif mod.value_is(a.value, 2, f):
                            prims.append(_Prim(a, "return2", *fl))
    uniq: dict[tuple, _Prim] = {}
    for p in prims:
        k = (p.node.lineno, p.kind)
        if k in uniq:
            uniq[k].ok_main |= p.ok_main
            uniq[k].ok_import |= p.ok_import
        else:
            uniq[k] = p
    return list(uniq.values())


def unreachable_after_exit(mod: PyModule) -> dict[int, int]:
    """{line of a statement no path runs: the line of the unconditional exit / raise / return before it
    in the same block}."""
    out = {}
    for node in ast.walk(mod.ast):
        for attr in ("body", "orelse", "finalbody"):
            body = getattr(node, attr, None)
            if not isinstance(body, list):
                continue
            stop = None
            for st in body:
                if stop is not None:
                    for n in ast.walk(st):
                        if hasattr(n, "lineno"):
                            out.setdefault(n.lineno, stop)
                    continue
                if isinstance(st, (ast.Return, ast.Raise)) or isinstance(st, ast.Expr) and \
                        isinstance(st.value, ast.Call) and (_call_name(st.value.func) in EXIT_FUNCS or
                                                            _call_name(st.value.func) == (None, "exit")):
                    stop = st.lineno
    return out


# ------------------------------------------------------------------ shell

_SH_FUNC = re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{?\s*(.*)$")
_SH_EXIT2 = re.compile(r"(?:^|[\s;&|{(])exit\s+2\b")
_SH_SOURCE = re.compile(r"""(?:^|[\s;&|])(?:source|\.)\s+"?([^"\s;]+\.sh)""")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")
_OPEN = re.compile(r"(?:^|[\s;(])(if|case|while|until|for|select)\b")
_CLOSE = re.compile(r"(?:^|[\s;])(fi|esac|done)\b")


def _quoted(line: str, pos: int) -> bool:
    """Whether position pos of a shell line lies inside a quoted string."""
    q, i = None, 0
    while i < pos:
        c = line[i]
        if q is None and c in "'\"":
            q = c
        elif q == c and (c == "'" or line[i - 1] != "\\"):
            q = None
        i += 1
    return q is not None


class ShModule:
    def __init__(self, tree: str, rel: str):
        self.tree, self.rel = tree, rel
        with open(os.path.join(tree, rel)) as fh:
            raw = fh.read().splitlines()
        self.raw = raw
        # code lines (comments, heredoc bodies blanked; heredoc text kept per opening line)
        self.code: list[str] = []
        self.heredoc: dict[int, str] = {}
        tag, strip, start = None, False, 0
        for i, line in enumerate(raw):
            if tag is not None:
                end = line.strip() if strip else line
                if end == tag:
                    tag = None
                else:
                    self.heredoc[start] = self.heredoc.get(start, "") + line + "\n"
                self.code.append("")
                continue
            s = line.lstrip()
            code = "" if s.startswith("#") else re.sub(r"\s#\s.*$", "", line) if "'" not in line and '"' not in line else line
            self.code.append(code)
            m = next((m for m in _HEREDOC.finditer(code) if not _quoted(code, m.start())), None)
            if m and "<<<" not in code:
                tag, strip, start = m.group(2), "<<-" in code, i
        self.funcs = self._funcs()

    def _funcs(self) -> dict[str, tuple[int, int]]:
        out, i = {}, 0
        while i < len(self.code):
            m = _SH_FUNC.match(self.code[i])
            if m:
                rest = m.group(2)
                if rest.rstrip().endswith("}") and rest.strip() not in ("", "{"):
                    out[m.group(1)] = (i, i)
                    i += 1
                    continue
                indent = len(self.code[i]) - len(self.code[i].lstrip())
                j = i + 1
                while j < len(self.code):
                    ln = self.code[j]
                    if re.match(r"^\s*\}\s*(?:[<>|&;].*)?$", ln) and len(ln) - len(ln.lstrip()) <= indent:
                        break
                    j += 1
                out[m.group(1)] = (i, j)
                i = j + 1
                continue
            i += 1
        return out

    def func_at(self, i: int) -> str | None:
        best = None
        for name, (a, b) in self.funcs.items():
            if a <= i <= b and (best is None or a > self.funcs[best][0]):
                best = name
        return best

    def depth(self, i: int) -> int:
        """Open if/case/loop blocks around line i within its function (or the file), and a conditional
        `&&` / `||` / case arm on the line itself counts as one."""
        f = self.func_at(i)
        a = self.funcs[f][0] + 1 if f else 0
        d = 0
        for k in range(a, i):
            ln = self.code[k]
            if f is None and self.func_at(k):
                continue
            d += len(_OPEN.findall(ln)) - len(_CLOSE.findall(ln))
        ln = self.code[i]
        pre = ln.split("exit")[0] if "exit" in ln else ln
        if "&&" in pre or "||" in pre or re.search(r"^\s*[^()]*\)\s", ln) or re.search(r"\bthen\b|\belse\b", pre):
            d += 1
        return max(d, 0)

    def sourced(self) -> list[str]:
        out = []
        for ln in self.code:
            for m in _SH_SOURCE.finditer(ln):
                base = os.path.basename(m.group(1))
                for d in ("hooks/lib", "hooks"):
                    p = os.path.join(d, base)
                    if os.path.isfile(os.path.join(self.tree, p)):
                        out.append(p)
                        break
        return sorted(set(out))

    def conds(self, i: int) -> list[str]:
        f = self.func_at(i)
        a = self.funcs[f][0] + 1 if f else 0
        stack = []
        for k in range(a, i + 1):
            ln = self.code[k].strip()
            if f is None and self.func_at(k):
                continue
            for _ in _CLOSE.findall(ln):
                if stack:
                    stack.pop()
            for m in _OPEN.finditer(ln):
                stack.append(ln[:160])
            if re.match(r"^(?:elif|else)\b", ln) and stack:
                stack[-1] = ln[:160]
        line = self.code[i].strip()
        if ("&&" in line or "||" in line) and "exit" in line:
            stack.append(line.split("exit")[0][:160])
        return stack

    def input_vars(self) -> set[str]:
        """Variables holding the hook's stdin (`$(cat)`) or anything computed from one."""
        if hasattr(self, "_inv"):
            return self._inv
        assigns = [(m.group(1), m.group(2)) for ln in self.code
                   for m in re.finditer(r"(?:^|[\s;])(?:local\s+|export\s+)?([A-Za-z_]\w*)=(.*)$", ln)]
        found = {v for v, rhs in assigns if re.match(r"""["']?\$\(\s*cat\s*-?\s*\)""", rhs)}
        changed = True
        while changed:
            changed = False
            for v, rhs in assigns:
                if v not in found and any(re.search(r"\$\{?" + re.escape(x) + r"\b", rhs) for x in found):
                    found.add(v)
                    changed = True
        self._inv = found
        return found

    def names_input(self, i: int) -> bool:
        """Whether the message lines before line i interpolate the hook's input (the refused call)."""
        inv = self.input_vars()
        for k in range(max(0, i - 8), i + 1):
            text = self.code[k] + "\n" + self.heredoc.get(k, "")
            if any(re.search(r"\$\{?" + re.escape(v) + r"\b", text) for v in inv):
                return True
        return False

    def message(self, i: int) -> list[str]:
        out = []
        for k in range(max(0, i - 8), i + 1):
            if k in self.heredoc:
                out.append(self.heredoc[k])
            out += re.findall(r"'([^']{4,})'|\"([^\"]{4,})\"", self.code[k]) and \
                [a or b for a, b in re.findall(r"'([^']{4,})'|\"([^\"]{4,})\"", self.code[k])]
        return out


# ------------------------------------------------------------------ the walk

def _walk_scope(scope):
    """The nodes of one scope: a module's top-level code, or a function's body with its nested
    functions (a class body at module level holds methods reached by name, not here)."""
    todo = list(ast.iter_child_nodes(scope))
    while todo:
        n = todo.pop()
        yield n
        if isinstance(scope, ast.Module) and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        todo.extend(ast.iter_child_nodes(n))


class Enumerator:
    """Per registered hook, the files it reaches with their role: `main` (the hook's own process, or a
    child process it runs and whose exit it relays), `import` (a module it imports, by name or by path,
    or a shell file it sources); and per Python import, the functions the hook can call."""

    def __init__(self, tree: str):
        self.tree = os.path.abspath(tree)
        self.regs = registered(self.tree)
        self.py: dict[str, PyModule] = {}
        self.sh: dict[str, ShModule] = {}
        self.children: dict[str, list[str]] = {}   # hook file -> child processes it runs
        self.roles: dict[str, dict[str, str]] = {}  # hook -> {file: main|child|import}
        for hook in self.regs:
            self.roles[hook] = self._closure(hook)

    def module(self, rel: str):
        if rel.endswith(".py"):
            if rel not in self.py:
                try:
                    self.py[rel] = PyModule(self.tree, rel)
                except (SyntaxError, OSError, UnicodeDecodeError):
                    return None
            return self.py[rel]
        if rel.endswith(".sh"):
            if rel not in self.sh:
                self.sh[rel] = ShModule(self.tree, rel)
            return self.sh[rel]
        return None

    def _closure(self, hook: str) -> dict[str, str]:
        roles = {hook: "main"}
        todo = [hook]
        while todo:
            rel = todo.pop()
            m = self.module(rel)
            if m is None:
                continue
            if isinstance(m, PyModule):
                procs, loads = m.loaded_files()
                if roles[rel] in ("main", "child"):
                    self.children[rel] = procs
                    for f in procs:
                        if f not in roles:
                            roles[f] = "child"
                            todo.append(f)
                nxt = [f for f in m.imported_files() if f.startswith("hooks/")] + loads
            else:
                nxt = m.sourced()
            for f in nxt:
                if f not in roles:
                    roles[f] = "import"
                    todo.append(f)
        return roles

    # ---- Python: which functions of an imported module a hook can call
    def _resolve(self, mod: PyModule, func) -> tuple | None:
        base, name = _call_name(func) if not isinstance(func, ast.Name) else (None, func.id)
        if name is None:
            return None
        if base is None:
            if name in mod.funcs:
                return (mod.rel, name)
            imp = mod.imports.get(name)
            return (imp[0], imp[1]) if imp and imp[1] else None
        if base in ("self", "cls") and name in mod.funcs:
            return (mod.rel, name)
        imp = mod.imports.get(base)
        return (imp[0], name) if imp and imp[1] is None else None

    def reachable(self, hook: str) -> set[tuple[str, str]]:
        """(file, function) the hook's processes can call: every function of a main or child file,
        then what they call or name, across imports; a method call on an object the walk cannot type
        reaches every function of that name in the imported modules (conservative)."""
        roles = self.roles[hook]
        out: set[tuple[str, str]] = set()
        todo = [(f, n) for f, r in roles.items() if r != "import" and f in self.py for n in self.py[f].funcs]
        todo += [(f, "<module>") for f, r in roles.items() if f in self.py]
        by_name: dict[str, list[tuple[str, str]]] = {}
        for f in roles:
            if f in self.py:
                for n in self.py[f].funcs:
                    by_name.setdefault(n, []).append((f, n))
        while todo:
            key = todo.pop()
            if key in out:
                continue
            out.add(key)
            mod = self.py.get(key[0])
            if mod is None:
                continue
            scope = mod.ast if key[1] == "<module>" else mod.funcs.get(key[1])
            if scope is None:
                continue
            as_main = roles.get(key[0]) != "import"
            for n in _walk_scope(scope):
                if key[1] == "<module>" and not _guard(mod, n, as_main, [hook]):
                    continue
                if isinstance(n, (ast.Name, ast.Attribute)) and not isinstance(getattr(n, "ctx", None), ast.Store):
                    tgt = self._resolve(mod, n)
                    if tgt and tgt not in out:
                        todo.append(tgt)
                    elif tgt is None and isinstance(n, ast.Attribute):
                        todo += [k for k in by_name.get(n.attr, []) if k not in out]
        return out

    # ---- Python sites with helper following
    def _py_sites(self, files: dict[str, str], argv: list) -> list[tuple[Site, bool, bool]]:
        """(site, ok as the hook's process, ok as an import) for the Python files of one hook."""
        helpers: dict[tuple[str, str], list] = {}
        leaf: list[tuple[Site, bool, bool]] = []

        def as_site(mod, node, kind):
            func = mod.enclosing_func(node)
            conds, handler = mod.conds(node)
            own = kind == "call"  # a helper call carries its message in its own arguments
            return Site(mod.rel, node.lineno, func.name if func else "<module>", kind, conds=conds,
                        text=_const_str(mod.statement(node)) if own else mod.message(node), handler=handler,
                        dynamic=mod.dynamic(node, own),
                        unconditional=func is not None and mod.top_level(node, func))

        mods = {rel: self.py[rel] for rel in files if rel in self.py}
        for rel, mod in mods.items():
            for p in _py_primitives(mod, argv):
                s = as_site(mod, p.node, p.kind)
                func = mod.enclosing_func(p.node)
                if s.unconditional and func is not None and func.name != "main" and p.kind != "return2":
                    helpers.setdefault((rel, func.name), []).append(s)
                else:
                    leaf.append((s, p.ok_main, p.ok_import))
        changed = True
        while changed:
            changed = False
            for rel, mod in mods.items():
                for node in ast.walk(mod.ast):
                    if not isinstance(node, ast.Call):
                        continue
                    tgt = self._resolve(mod, node.func)
                    func = mod.enclosing_func(node)
                    if tgt in helpers and func is not None and func.name != "main" and \
                            mod.top_level(node, func) and (rel, func.name) not in helpers and (rel, func.name) != tgt:
                        helpers[(rel, func.name)] = [as_site(mod, node, "call")]
                        changed = True
        # A helper's refusals off its top level (a helper call under a test, the helper still blocking
        # at its end) leave through the same call site as its own: their message pieces join the
        # helper's, the pieces of the values a variable message is assigned from included, so match()
        # maps a refusal one of them printed to the site calling the helper.
        for (rel, name), hs in helpers.items():
            mod, f = mods[rel], mods[rel].funcs.get(name)
            for node in ast.walk(f) if f is not None and hs and hs[0].kind == "call" else ():
                if isinstance(node, ast.Call) and self._resolve(mod, node.func) in helpers \
                        and mod.enclosing_func(node) is f and not mod.top_level(node, f):
                    hs[0].text += [t for t in _const_str(mod.statement(node)) + _flow_text(mod, f, node)
                                   if t not in hs[0].text]
        called = set()
        for rel, mod in mods.items():
            for node in ast.walk(mod.ast):
                if not isinstance(node, ast.Call):
                    continue
                tgt = self._resolve(mod, node.func)
                if tgt not in helpers:
                    continue
                called.add(tgt)
                func = mod.enclosing_func(node)
                if func is not None and (rel, func.name) in helpers:
                    continue
                s = as_site(mod, node, "call")
                s.via = f"{tgt[0]}:{tgt[1]}"
                hs = self._helper_leaves(helpers, tgt)
                s.helper_text = [t for h in hs for t in h.text]
                s.helper_conds = [c for h in hs for c in h.conds]
                s.dynamic = s.dynamic or any(h.dynamic for h in hs)
                s.handler = s.handler or any(h.handler for h in hs)
                leaf.append((s, _guard(mod, node, True, argv), _guard(mod, node, False, argv)))
        for key, hs in helpers.items():
            if key not in called:  # a helper nothing calls keeps its own primitive (unreachable() decides)
                leaf += [(h, True, True) for h in hs if h.kind != "call"]
        return leaf

    def _helper_leaves(self, helpers, key, seen=None) -> list[Site]:
        seen = seen if seen is not None else set()
        if key in seen:
            return []
        seen.add(key)
        out = []
        for h in helpers.get(key, []):
            if h.kind == "call":  # an intermediate helper: its own call carries message text too
                out.append(h)
                mod = self.py[h.file]
                for node in ast.walk(mod.ast):
                    if isinstance(node, ast.Call) and node.lineno == h.line:
                        out += self._helper_leaves(helpers, self._resolve(mod, node.func), seen)
            else:
                out.append(h)
        return out

    # ---- shell sites with helper following
    def _sh_sites(self, files: list[str]) -> list[Site]:
        mods = {rel: self.sh[rel] for rel in files if rel in self.sh}
        helpers: dict[tuple[str, str], list[Site]] = {}
        leaf: list[Site] = []
        for rel, m in mods.items():
            for i, ln in enumerate(m.code):
                ex = any(not _quoted(ln, mt.end() - 6) for mt in _SH_EXIT2.finditer(ln))
                kind = "exit2" if ex else "decision" if DECISION_TEXT.search(ln) else None
                if not kind:
                    continue
                f = m.func_at(i)
                s = Site(rel, i + 1, f or "<module>", kind, conds=m.conds(i), text=m.message(i),
                         unconditional=f is not None and m.depth(i) == 0, dynamic=m.names_input(i))
                (helpers.setdefault((rel, f), []) if s.unconditional else leaf).append(s)

        def pattern(name):
            return re.compile(r"(?:^|[;&|({!]\s*|\b(?:then|else|do)\s+|^\s+)" + re.escape(name) + r"(?:\s|;|$|\))")

        def visible(rel, hrel):
            return hrel == rel or hrel in mods[rel].sourced()

        changed = True
        while changed:
            changed = False
            for rel, m in mods.items():
                for (hrel, hname) in list(helpers):
                    if not visible(rel, hrel):
                        continue
                    a, b = m.funcs.get(hname, (-1, -1)) if hrel == rel else (-1, -1)
                    for i, ln in enumerate(m.code):
                        if a <= i <= b or not pattern(hname).search(ln):
                            continue
                        f = m.func_at(i)
                        if f is not None and m.depth(i) == 0 and (rel, f) not in helpers and (rel, f) != (hrel, hname):
                            helpers[(rel, f)] = [Site(rel, i + 1, f, "call", via=f"{hrel}:{hname}")]
                            changed = True
        out, called = [], set()
        for rel, m in mods.items():
            for (hrel, hname), hs in helpers.items():
                if not visible(rel, hrel):
                    continue
                a, b = m.funcs.get(hname, (-1, -1)) if hrel == rel else (-1, -1)
                for i, ln in enumerate(m.code):
                    if a <= i <= b or not pattern(hname).search(ln):
                        continue
                    called.add((hrel, hname))
                    f = m.func_at(i)
                    if f is not None and m.depth(i) == 0 and (rel, f) in helpers:
                        continue
                    leaves = [h for h in hs if h.kind != "call"]
                    out.append(Site(rel, i + 1, f or "<module>", "call", via=f"{hrel}:{hname}",
                                    conds=m.conds(i), text=m.message(i),
                                    helper_text=[t for h in leaves for t in h.text],
                                    dynamic=m.names_input(i) or any(h.dynamic for h in leaves)))
        for key, hs in helpers.items():
            if key not in called:
                leaf += [h for h in hs if h.kind != "call"]
        return leaf + out

    def hook_sites(self, hook: str) -> list[Site]:
        """The blocking sites one registered hook reaches."""
        roles = self.roles[hook]
        argv = [hook]  # registered commands pass no arguments (registered() keeps only the file)
        reach = self.reachable(hook)
        out = []
        for s, ok_main, ok_import in self._py_sites(roles, argv):
            role = roles.get(s.file)
            if role in ("main", "child") and not ok_main:
                continue
            if role == "import" and (not ok_import or (s.file, s.func) not in reach and s.func != "<module>"):
                continue
            out.append(s)
        out += self._sh_sites([f for f in roles if f.endswith(".sh")])
        for s in out:
            s.regs = [(hook, ev, m) for ev, m in self.regs[hook]]
            s.role = roles.get(s.file)
        return out

    def sites(self) -> list[Site]:
        """Every site, once per (file, line), with every registered hook that reaches it."""
        merged: dict[str, Site] = {}
        for hook in self.regs:
            for s in self.hook_sites(hook):
                if s.id in merged:
                    have = merged[s.id]
                    have.regs += [r for r in s.regs if r not in have.regs]
                else:
                    merged[s.id] = s
        return sorted(merged.values(), key=lambda s: (s.file, s.line))


def sites(tree: str) -> list[Site]:
    return Enumerator(tree).sites()


# ------------------------------------------------------------------ classes (X6 (ii))

# Rules, not lists: each names a kind of message or call, never a site or a hook.
# A hook reporting its own failure to decide (its install, engine or configuration), not the call's:
FAIL_CLOSED = re.compile(r"FAIL-CLOSED|bootstrap FAILED|\bis unavailable\b|invalid_phase|contract_error|_failed\b|"
                         r"hook\(s\) broken|capability issue failed|could not decide", re.I)
# ... unless what it cannot read is the refused call itself (a different call is the next round):
INPUT_UNREADABLE = re.compile(r"tokeniz|could not be resolved|unresolv", re.I)
# The overnight window a time-lock compares the clock with:
WINDOW = re.compile(r"\bwindow_(?:live|open)\b|\bend_time\b")
TOOL_TEST = re.compile(r"(?:tool_name|TOOL_NAME)\W{0,4}(?:==|=|in)\s*[({\[]?\s*([^)}\]]*)")
TOOLS = re.compile(r"[\"']([A-Z][A-Za-z]+)[\"']")
# The calls by which an actor discharges its own obligations: TodoWrite (the canonical step record a
# command keeps) and the Agent / Task dispatch that carries a producer's obligation.
OBLIGATION_TOOLS = {"TodoWrite", "Agent", "Task"}


def _site_tools(s: Site) -> set[str] | None:
    """The tools a PreToolUse site can refuse: its hooks' matchers, narrowed by a tool-name test in its
    guard; None when nothing narrows it (every tool)."""
    tools: set[str] | None = set()
    for _, ev, m in s.regs:
        if ev != "PreToolUse":
            continue
        if m in ("", "*") or not re.fullmatch(r"[A-Za-z0-9_|]+", m):
            tools = None
            break
        tools |= set(m.split("|"))
    for c in s.conds + s.helper_conds:
        if c.startswith("not ") or "!=" in c or "not in" in c:
            continue
        for mt in TOOL_TEST.finditer(c):
            named = set(TOOLS.findall(mt.group(1)))
            if named:
                tools = named if tools is None else (tools & named or named)
    return tools


def helper_source(e: "Enumerator", s: Site) -> str:
    if not s.via:
        return ""
    rel, name = s.via.split(":", 1)
    m = e.module(rel)
    if isinstance(m, PyModule) and name in m.funcs:
        return ast.get_source_segment(m.src, m.funcs[name]) or ""
    if isinstance(m, ShModule) and name in m.funcs:
        a, b = m.funcs[name]
        return "\n".join(m.code[a:b + 1])
    return ""


def unreachable(e: "Enumerator", s: Site) -> str:
    """A proof that no path runs the site, or ""."""
    m = e.module(s.file)
    if isinstance(m, PyModule):
        after = unreachable_after_exit(m).get(s.line)
        if after:
            return f"{s.file}:{s.line} follows the unconditional exit/return at line {after} in the same block"
        if s.func not in ("<module>", "main") and s.func in m.funcs:
            named = any(isinstance(n, ast.Name) and n.id == s.func or isinstance(n, ast.Attribute) and n.attr == s.func
                        for n in ast.walk(m.ast))
            if not named:
                return f"nothing in {s.file} names {s.func}() (it is no entry point)"
    return ""


def classify(e: "Enumerator", s: Site) -> tuple[str, str]:
    """(class, why) for one site, from its code and its registrations: G, D, H, U, or "-" (no class)."""
    proof = unreachable(e, s)
    if proof:
        return "U", proof
    events = {ev for _, ev, _ in s.regs}
    text = s.all_text()
    src = helper_source(e, s)
    guard = " ".join(s.conds + s.helper_conds)
    if "Stop" in events and (WINDOW.search(guard) or TIME_CALLS.search(src)):
        return "H", "Stop while the overnight window is open (its guard reads the window / its message the clock)"
    if "Stop" in events and re.search(r"(?:type|run|use)s? /stop\b", text):
        return "H", "a Stop instrument failure whose message names /stop as its release"
    if s.handler or FAIL_CLOSED.search(text):
        if "PreToolUse" in events and s.dynamic and INPUT_UNREADABLE.search(text):
            return "D", "fails closed on a call it cannot read, naming it; a call it can read is the next one"
        return "-", "fail-closed: the hook reports that it could not decide (a broken install or configuration)"
    if events & {"SessionStart", "SessionEnd", "Notification"} and not events & {"PreToolUse", "Stop", "SubagentStop"}:
        return "-", f"a {'/'.join(sorted(events))} exit 2 refuses no agent action"
    if events <= {"Stop", "SubagentStop"}:
        return "G", "a stop gate: what it names is the stopping actor's own; its next stop (stop_hook_active) is the next round"
    if events <= {"PostToolUse", "PostToolUseFailure"}:
        return "G", "after the call ran: the block returns its text to the same actor, whose next call is the next round"
    if "PreToolUse" in events:
        tools = _site_tools(s)
        if tools and tools <= OBLIGATION_TOOLS:
            return "G", f"refuses the actor's own {'/'.join(sorted(tools))} (its todo record or its dispatch); its next compliant call clears it"
        named = sorted(t for t in OBLIGATION_TOOLS if re.search(r"\b" + t + r"\b", text))
        if named and re.search(r"\b(?:Call|call|initiali[sz]e|fix|re-?run)\b", text):
            return "G", f"a lock on every call whose message names the actor's next {'/'.join(named)} call as its release"
        if not s.dynamic and re.search(r"(?m)^\s+(?:git|python3?|bash)\s+\S", text):
            return "G", "a lock on every call whose message names the command that releases it (the actor's next call)"
        if s.dynamic or tools:
            return "D", "refuses the call it is given, naming it" + (f" ({'/'.join(sorted(tools))})" if tools else "")
        return "-", "a PreToolUse refusal whose message names no operation"
    if events <= {"UserPromptSubmit"}:
        return "D", "refuses the prompt it is given"
    return "-", "no rule derives a class"


# ------------------------------------------------------------------ children, recall

def relayed(tree: str, parent: str, child: str, event: str, work: str) -> bool:
    """Whether `parent`'s own exit is a block when its child process `child` exits 2: run a copy of
    hooks/ in which the child exits 2, with an `event` payload for a session that typed nothing."""
    tree = os.path.abspath(tree)
    hooks = os.path.join(work, "hooks")
    if not os.path.isdir(hooks):
        import shutil
        shutil.copytree(os.path.join(tree, "hooks"), hooks, ignore=lambda d, n: [x for x in n if x == "tests"])
    stub = os.path.join(work, child)
    orig = stub + ".orig"
    os.replace(stub, orig)
    try:
        with open(stub, "w") as fh:
            fh.write("import sys\nsys.exit(2)\n" if child.endswith(".py") else "exit 2\n")
        for d in ("home", "state", "tmp", "proj"):
            os.makedirs(os.path.join(work, d), exist_ok=True)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.path.join(work, "home"),
               "CLAUDE_STATE_DIR": os.path.join(work, "state"), "TMPDIR": os.path.join(work, "tmp"),
               "CLAUDE_PROJECT_DIR": os.path.join(work, "proj"), "CLAUDE_HOME": work, "LANG": "C.UTF-8"}
        payload = {"session_id": "00000000-0000-4000-8000-000000000000", "hook_event_name": event,
                   "transcript_path": os.path.join(work, "none.jsonl"), "cwd": env["CLAUDE_PROJECT_DIR"],
                   "stop_hook_active": False}
        cmd = ["python3" if parent.endswith(".py") else "bash", os.path.join(work, parent)]
        p = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True, env=env,
                           cwd=env["CLAUDE_PROJECT_DIR"], timeout=120)
        return p.returncode == 2
    finally:
        os.replace(orig, stub)


_SPLIT = re.compile(r"\{[^{}]*\}|%[-#0-9.]*[sdrfix]|\$\{?\w+\}?|\\n|\n|\t")


def fragments(s: Site) -> list[str]:
    """The literal pieces of a site's message, long enough to identify it in a refusal's text."""
    out = []
    for t in s.text + s.helper_text:
        for piece in _SPLIT.split(t):
            piece = piece.strip()
            if len(piece) >= 10:
                out.append(piece)
    return sorted(set(out))


def match(hook: str, text: str, catalog: list[Site]) -> list[Site]:
    """The sites of `hook` whose message pieces the refusal `text` holds most of (ties: all of them)."""
    best, out = 0, []
    for s in catalog:
        if not any(r[0] == hook for r in s.regs):
            continue
        score = sum(len(f) if f in text else 40 if len(f) > 40 and f[:40] in text else 0 for f in fragments(s))
        if score > best:
            best, out = score, [s]
        elif score == best and score:
            out.append(s)
    return out


def unaccounted(e: "Enumerator", hook: str, found: list[Site]) -> list[str]:
    """A cross-check of the enumeration against a plain token scan of the hook's own file: each
    `exit(2)` / `_exit(2)` / `SystemExit(2)` call (Python tokens, strings and comments aside) or
    `exit 2` command (shell, comments and here-documents aside) must be a site, lie in a helper
    whose calls are sites, or lie on a path the registered invocation never takes."""
    import io
    import tokenize
    lines: list[int] = []
    m = e.module(hook)
    if isinstance(m, PyModule):
        toks = [t for t in tokenize.generate_tokens(io.StringIO(m.src).readline)
                if t.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)]
        for a, b, c, d in zip(toks, toks[1:], toks[2:], toks[3:]):
            if a.type == tokenize.NAME and a.string in ("exit", "_exit", "SystemExit") and b.string == "(" \
                    and c.type == tokenize.NUMBER and c.string == "2" and d.string == ")":
                lines.append(a.start[0])
    elif isinstance(m, ShModule):
        lines = [i + 1 for i, ln in enumerate(m.code)
                 if any(not _quoted(ln, mt.end() - 6) for mt in _SH_EXIT2.finditer(ln))]
    site_lines = {s.line for s in found if s.file == hook}
    helpers = {s.via.split(":", 1)[1] for s in found if s.via and s.via.startswith(hook + ":")}
    off = set()
    if isinstance(m, PyModule):
        off = {p.node.lineno for p in _py_primitives(m, [hook]) if not p.ok_main}
        todo = list(helpers)  # a helper's own helpers (it calls them at its top level) are accounted too
        while todo:
            f = m.funcs.get(todo.pop())
            for n in ast.walk(f) if f is not None else ():
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in m.funcs \
                        and n.func.id not in helpers:
                    helpers.add(n.func.id)
                    todo.append(n.func.id)
    out = []
    for ln in lines:
        if ln in site_lines or ln in off:
            continue
        if isinstance(m, PyModule):
            node = next((n for n in ast.walk(m.ast) if getattr(n, "lineno", None) == ln), None)
            func = m.enclosing_func(node) if node is not None else None
            if func is not None and func.name in helpers:
                continue
        elif isinstance(m, ShModule) and m.func_at(ln - 1) in helpers:
            continue
        out.append(f"{hook}:{ln}")
    return out
