"""Python half of the static derivation: the ast module, no execution.

For every module it evaluates path expressions (string literals, f-strings,
os.path.join / Path joins, module constants, known roots, helper functions that
return a path) and records each file operation with its site. Functions are
summarized: an operation whose path depends on a parameter is bound at each
call site, so a helper's write lands on the caller's literal path.

Per function it also finds the deciding-read candidates (a read whose value, or
whose failure, reaches an exit, a block decision, a raise or a branch), the
calls of the chain resolver and how their output is used, the prints and the
systemMessage values that show a path, the scripts it runs, the env switches it
reads and the literal collections rule (7) looks at.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from . import model as M
from . import patterns as P
from . import values as V
from .values import Unk, Str, Num, NoneV, Lst, Dct, Mod, Fn, Obj, Handle, Listing

# Root bindings: (module file, function) -> root token. These four functions
# are the harness's resolvers of the roots patterns.py names.
ROOT_FUNCTIONS = {
    ("hooks/lib/harness_state_dir.py", "harness_state_dir"): "state",
    ("hooks/lib/claude_home.py", "resolve"): "harness",
    ("hooks/lib/claude_home.py", "project_dir"): "proj",
}

# Environment variables that name a root.
ENV_ROOTS = {
    "HOME": "home",
    "CLAUDE_PROJECT_DIR": "proj",
    "PWD": "proj",
    "CLAUDE_HOME": "harness",
    "CLAUDE_CONFIG_DIR": "harness",
    "CLAUDE_STATE_DIR": "state",
    "TMPDIR": "tmpdir",
    "CLAUDE_TMPDIR": "tmpdir",
    "CLAUDE_CODE_TMPDIR": "tmpdir",
}

_EXIT_CALLS = {"sys.exit", "exit", "quit", "os._exit", "builtins.exit"}
_SUBPROCESS = {"subprocess.run", "subprocess.Popen", "subprocess.check_output",
               "subprocess.check_call", "subprocess.call", "os.system", "os.popen",
               "os.execv", "os.execvp", "os.execve", "os.execl", "os.execlp", "os.spawnv",
               "asyncio.create_subprocess_exec"}
_LOADERS = {"runpy.run_path", "importlib.util.spec_from_file_location",
            "importlib.machinery.SourceFileLoader", "importlib.import_module"}
_NAME_PROBES = {"os.path.exists", "os.path.isfile", "os.path.isdir", "os.path.islink",
                "os.path.lexists", "os.path.getmtime", "os.path.getsize", "os.path.getctime",
                "os.path.getatime", "os.stat", "os.lstat", "os.access", "os.path.samefile"}
_PATH_IDENTITY = {"str", "os.fspath", "os.path.abspath", "os.path.realpath", "os.path.normpath",
                  "os.path.expandvars", "os.fsdecode", "os.fsencode", "posixpath.normpath",
                  "posixpath.abspath"}
_PATH_CTORS = {"pathlib.Path", "pathlib.PurePath", "pathlib.PosixPath", "pathlib.PurePosixPath"}
_TS_CALLS = re.compile(r"(^|\.)(strftime|isoformat|time|time_ns|now|utcnow|today|monotonic|perf_counter)$")
_NONCE_MODS = ("uuid.", "secrets.", "random.", "os.urandom", "os.getpid", "os.getppid", "threading.get_ident")
_OPEN_FUNCS = {"open", "io.open", "codecs.open", "gzip.open", "bz2.open", "lzma.open", "builtins.open",
               "tarfile.open", "zipfile.ZipFile"}


@dataclass
class FuncInfo:
    module: "PyModule"
    qual: str
    node: ast.AST
    params: list
    defaults: dict
    cls: str | None
    vararg: str | None = None
    kwarg: str | None = None


@dataclass
class ReadInfo:
    path: V.Val
    mode: str
    line: int
    via: tuple = ()


@dataclass
class Summary:
    ret: V.Val = field(default_factory=lambda: Unk("dynamic"))
    param_effects: list = field(default_factory=list)   # [M.Op] with ‹@param› in path
    return_reads: list = field(default_factory=list)    # [ReadInfo]
    decisions: list = field(default_factory=list)       # [M.Decision] exit/block (not route)
    raises: list = field(default_factory=list)          # [M.Decision] kind raise
    chain_returned: bool = False
    prints: list = field(default_factory=list)


EMPTY = Summary()


def _names_in(node) -> set:
    out = set()
    if node is None:
        return out
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
    return out


def _target_names(t) -> list:
    out = []
    if t is None:
        return out
    for n in ast.walk(t):
        if isinstance(n, ast.Name):
            out.append(n.id)
    return out


def _const_str(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _hint_of(node) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        k = _const_str(node.slice)
        return k or _hint_of(node.value)
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "get" and node.args:
            k = _const_str(node.args[0])
            if k:
                return k
        if isinstance(f, ast.Attribute):
            return _hint_of(f.value) if f.attr in ("strip", "lower", "upper", "rstrip", "lstrip") else f.attr
        if isinstance(f, ast.Name):
            return f.id
    return None


class PyModule:
    def __init__(self, index: "Analyzer", path: str, source: str, *, line_offset: int = 0,
                 embedded: bool = False, env: dict | None = None, origin: str = ""):
        self.index = index
        self.path = path
        self.line_offset = line_offset
        self.embedded = embedded
        self.env = env or {}
        self.origin = origin
        self.injected: dict = {}
        self.option_values: dict = {}       # argparse dest -> its value (FunctionWalk._option_value)
        self.tree = ast.parse(source)
        self.mentions_chain = bool(index.chain_basename) and index.chain_basename in source
        self.source_hint = "systemMessage" if "systemMessage" in source else ""
        self.parent: dict[int, tuple] = {}
        self.stmt_of: dict[int, ast.stmt] = {}
        self.scope_of: dict[int, ast.AST] = {}
        self.funcs: dict[str, FuncInfo] = {}
        self.func_by_node: dict[int, FuncInfo] = {}
        self.classes: dict[str, ast.ClassDef] = {}
        self.class_bases: dict[str, list] = {}
        self.docstrings: set[int] = set()
        self._build()
        if embedded:
            self.file_template: V.Val = Unk("dynamic")
        else:
            self.file_template = V.s(P.tok("harness") + "/" + path)

    def ln(self, node) -> int:
        return getattr(node, "lineno", 0) + self.line_offset

    def _build(self) -> None:
        def visit_block(owner, fieldname, stmts, scope, qual_prefix, cls):
            for i, s in enumerate(stmts):
                self.parent[id(s)] = (owner, fieldname, i)
                self.scope_of[id(s)] = scope
                if i == 0 and isinstance(s, ast.Expr) and _const_str(s.value) is not None:
                    self.docstrings.add(id(s.value))
                visit_stmt(s, scope, qual_prefix, cls)

        def map_exprs(s, stmt):
            for fname, value in ast.iter_fields(s):
                items = value if isinstance(value, list) else [value]
                for it in items:
                    if isinstance(it, ast.expr):
                        for n in ast.walk(it):
                            self.stmt_of[id(n)] = stmt
                    elif isinstance(it, (ast.withitem, ast.comprehension, ast.arguments, ast.keyword, ast.arg)):
                        for n in ast.walk(it):
                            self.stmt_of[id(n)] = stmt

        def visit_stmt(s, scope, qual_prefix, cls):
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in s.decorator_list:
                    for n in ast.walk(d):
                        self.stmt_of[id(n)] = s
                for n in ast.walk(s.args):
                    self.stmt_of[id(n)] = s
                if s.returns is not None:
                    for n in ast.walk(s.returns):
                        self.stmt_of[id(n)] = s
                qual = qual_prefix + s.name
                a = s.args
                params = [x.arg for x in a.posonlyargs + a.args]
                defaults = {}
                pos = a.posonlyargs + a.args
                for arg, d in zip(pos[len(pos) - len(a.defaults):], a.defaults):
                    defaults[arg.arg] = d
                for arg, d in zip(a.kwonlyargs, a.kw_defaults):
                    params.append(arg.arg)
                    if d is not None:
                        defaults[arg.arg] = d
                fi = FuncInfo(self, qual, s, params, defaults, cls,
                              a.vararg.arg if a.vararg else None, a.kwarg.arg if a.kwarg else None)
                if qual not in self.funcs:
                    self.funcs[qual] = fi
                self.func_by_node[id(s)] = fi
                visit_block(s, "body", s.body, s, qual + ".", None)
                return
            if isinstance(s, ast.ClassDef):
                for n in ast.walk(s):
                    if n is s:
                        continue
                for d in s.decorator_list + s.bases + [k.value for k in s.keywords]:
                    for n in ast.walk(d):
                        self.stmt_of[id(n)] = s
                qual = qual_prefix + s.name
                self.classes[qual] = s
                self.class_bases[qual] = [b for b in s.bases]
                visit_block(s, "body", s.body, s, qual + ".", qual)
                return
            map_exprs(s, s)
            for fname in ("body", "orelse", "finalbody"):
                block = getattr(s, fname, None)
                if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                    visit_block(s, fname, block, scope, qual_prefix, cls)
            if isinstance(s, (ast.Try, getattr(ast, "TryStar", ast.Try))):
                for hi, h in enumerate(s.handlers):
                    self.parent[id(h)] = (s, "handlers", hi)
                    if h.type is not None:
                        for n in ast.walk(h.type):
                            self.stmt_of[id(n)] = s
                    visit_block(h, "body", h.body, scope, qual_prefix, cls)
            if isinstance(s, ast.Match):
                for ci, c in enumerate(s.cases):
                    self.parent[id(c)] = (s, "cases", ci)
                    for n in ast.walk(c.pattern):
                        self.stmt_of[id(n)] = s
                    if c.guard is not None:
                        for n in ast.walk(c.guard):
                            self.stmt_of[id(n)] = s
                    visit_block(c, "body", c.body, scope, qual_prefix, cls)

        visit_block(self.tree, "body", self.tree.body, self.tree, "", None)

    def enclosing_func(self, stmt) -> FuncInfo | None:
        scope = self.scope_of.get(id(stmt))
        while scope is not None and isinstance(scope, ast.ClassDef):
            scope = self.scope_of.get(id(scope))
        if scope is None or isinstance(scope, ast.Module):
            return None
        return self.func_by_node.get(id(scope))


# --------------------------------------------------------------- reaching defs

_TNAMES: dict = {}
_DEFS: dict = {}
_WALRUS: dict = {}


def _binds(target, name: str) -> bool:
    if target is None:
        return False
    k = id(target)
    names = _TNAMES.get(k)
    if names is None:
        names = _TNAMES[k] = frozenset(_target_names(target))
    return name in names


def _defs_in_stmt(s, name: str):
    key = (id(s), name)
    r = _DEFS.get(key)
    if r is None:
        r = _DEFS[key] = _defs_in_stmt_raw(s, name)
    return r


def _defs_in_stmt_raw(s, name: str):
    """(definite, [defs]) for one statement, scanning nested blocks."""
    if isinstance(s, ast.Assign):
        for t in s.targets:
            if _binds(t, name):
                return True, [("assign", s, t)]
        return False, _walrus_defs(s, name)
    if isinstance(s, ast.AnnAssign):
        if isinstance(s.target, ast.Name) and s.target.id == name and s.value is not None:
            return True, [("ann", s, s.target)]
        return False, []
    if isinstance(s, ast.AugAssign):
        if isinstance(s.target, ast.Name) and s.target.id == name:
            return True, [("aug", s, s.target)]
        return False, []
    if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return (True, [("funcdef", s, None)]) if s.name == name else (False, [])
    if isinstance(s, ast.ClassDef):
        return (True, [("classdef", s, None)]) if s.name == name else (False, [])
    if isinstance(s, (ast.Import, ast.ImportFrom)):
        for a in s.names:
            bound = a.asname or (a.name.split(".")[0] if isinstance(s, ast.Import) else a.name)
            if bound == name:
                return True, [("import", s, a)]
        return False, []
    if isinstance(s, (ast.For, ast.AsyncFor)):
        defs = []
        if _binds(s.target, name):
            defs.append(("for", s, s.target))
        defs += _block_defs(s.body, name)[1] + _block_defs(s.orelse, name)[1]
        return False, defs
    if isinstance(s, ast.While):
        return False, _walrus_defs_expr(s.test, name) + _block_defs(s.body, name)[1] + _block_defs(s.orelse, name)[1]
    if isinstance(s, ast.If):
        d1, defs1 = _block_defs(s.body, name)
        d2, defs2 = _block_defs(s.orelse, name)
        return bool(d1 and d2 and s.orelse), _walrus_defs_expr(s.test, name) + defs1 + defs2
    if isinstance(s, (ast.With, ast.AsyncWith)):
        defs = []
        definite = False
        for it in s.items:
            if it.optional_vars is not None and _binds(it.optional_vars, name):
                defs.append(("with", s, it))
                definite = True
        d, bdefs = _block_defs(s.body, name)
        if d:
            return True, bdefs
        return definite, bdefs + defs
    if isinstance(s, (ast.Try, getattr(ast, "TryStar", ast.Try))):
        defs = _block_defs(s.body, name)[1]
        for h in s.handlers:
            if h.name == name:
                defs.append(("except", h, None))
            defs += _block_defs(h.body, name)[1]
        defs += _block_defs(s.orelse, name)[1]
        df, fdefs = _block_defs(s.finalbody, name)
        return df, defs + fdefs
    if isinstance(s, ast.Match):
        defs = []
        for c in s.cases:
            defs += _block_defs(c.body, name)[1]
        return False, defs
    return False, _walrus_defs(s, name)


def _walrus_defs(s, name: str) -> list:
    k = id(s)
    found = _WALRUS.get(k)
    if found is None:
        found = []
        for n in ast.walk(s):
            if isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name):
                found.append((n.target.id, n))
        _WALRUS[k] = found
    return [("walrus", n, None) for nm, n in found if nm == name]


def _walrus_defs_expr(e, name: str) -> list:
    return _walrus_defs(e, name) if e is not None else []


def _block_defs(block, name: str):
    defs = []
    for s in reversed(block or []):
        d, ds = _defs_in_stmt(s, name)
        defs += ds
        if d:
            return True, defs
    return False, defs


# -------------------------------------------------------------------- analyzer

class Analyzer:
    """Python modules of one tree, their summaries and their findings."""

    def __init__(self, files: list[str], read_text, findings: M.Findings, chain_basename: str):
        self.files = files
        self.file_set = set(files)
        self.read_text = read_text
        self.findings = findings
        self.chain_basename = chain_basename
        self.modules: dict[str, PyModule] = {}
        self.failed: dict[str, str] = {}
        self.summaries: dict[int, Summary] = {}
        self.in_progress: set[int] = set()
        self.memo: dict[int, V.Val] = {}
        self.active: set[int] = set()
        self.depth = 0
        self.instantiated: dict[int, int] = {}
        self.all_param_effects: list[tuple] = []
        self.exit_funcs: dict[str, set] = {}
        self.calls_to: dict[tuple, list] = {}
        self.chain_proxies: set[tuple] = set()
        self.prints: list = []
        self.script_mentions: list = []
        self.id_forms: list = []
        self.id_samples: list = []
        self.py_by_suffix: dict[str, list[str]] = {}
        for f in files:
            if f.endswith(".py"):
                parts = f[:-3].split("/")
                for i in range(len(parts)):
                    key = ".".join(parts[i:])
                    self.py_by_suffix.setdefault(key, []).append(f)
                if parts[-1] == "__init__":
                    for i in range(len(parts) - 1):
                        key = ".".join(parts[i:-1])
                        self.py_by_suffix.setdefault(key, []).append(f)

    # -- modules
    def module(self, path: str) -> PyModule | None:
        if path in self.modules:
            return self.modules[path]
        if path in self.failed:
            return None
        try:
            src = self.read_text(path)
            mod = PyModule(self, path, src)
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            self.failed[path] = type(exc).__name__
            return None
        self.modules[path] = mod
        return mod

    def add_embedded(self, component: str, source: str, line_offset: int, env: dict, origin: str = "",
                     injected: dict | None = None) -> PyModule | None:
        key = f"{component}#{line_offset}"
        try:
            mod = PyModule(self, component, source, line_offset=line_offset, embedded=True, env=env, origin=origin)
        except (SyntaxError, ValueError):
            return None
        if injected:
            mod.injected = dict(injected)
            pat = re.compile(r"__sh_\d+__")

            def fill(m):
                ts = V.as_templates(injected.get(m.group(0), Unk("dynamic")))
                if len(ts) == 1:
                    return ts[0]
                v = injected.get(m.group(0))
                return P.hole(v.reason if isinstance(v, Unk) else "dynamic")
            for n in ast.walk(mod.tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and "__sh_" in n.value:
                    n.value = pat.sub(fill, n.value)
        self.modules[key] = mod
        return mod

    def resolve_import(self, dotted: str, from_file: str, level: int = 0) -> str | None:
        if level:
            base = from_file.rsplit("/", 1)[0] if "/" in from_file else ""
            for _ in range(level - 1):
                base = base.rsplit("/", 1)[0] if "/" in base else ""
            rel = (base + "/" if base else "") + dotted.replace(".", "/")
            for cand in (rel + ".py", rel + "/__init__.py"):
                if cand in self.file_set:
                    return cand
            return None
        cands = self.py_by_suffix.get(dotted, [])
        if not cands:
            return None
        here = from_file.rsplit("/", 1)[0] if "/" in from_file else ""
        top = from_file.split("/", 1)[0]

        def rank(c):
            d = c.rsplit("/", 1)[0] if "/" in c else ""
            return (0 if d == here or d.startswith(here + "/lib") else 1,
                    0 if c.split("/", 1)[0] == top else 1, len(c), c)
        return sorted(cands, key=rank)[0]

    # -- functions
    def func(self, module_path: str, qual: str) -> FuncInfo | None:
        mod = self.modules.get(module_path) or self.module(module_path)
        if mod is None:
            return None
        return mod.funcs.get(qual)

    def root_of(self, fn: Fn) -> str | None:
        name = fn.qual.rsplit(".", 1)[-1]
        return ROOT_FUNCTIONS.get((fn.module, name)) if "." not in fn.qual else None

    def summary(self, fi: FuncInfo) -> Summary:
        key = id(fi.node)
        if key in self.summaries:
            return self.summaries[key]
        if key in self.in_progress:
            return EMPTY
        self.in_progress.add(key)
        try:
            s = FunctionWalk(self, fi.module, fi).run()
        finally:
            self.in_progress.discard(key)
        self.summaries[key] = s
        return s

    def module_exit_funcs(self, mod: PyModule) -> set:
        key = mod.path + "#" + str(mod.line_offset)
        if key in self.exit_funcs:
            return self.exit_funcs[key]
        found: set = set()
        for n in ast.walk(mod.tree):
            call = None
            if isinstance(n, ast.Call):
                callee = _dotted(n.func)
                if callee in ("sys.exit", "exit", "os._exit", "quit") and n.args:
                    call = n.args[0]
            elif isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call) and _dotted(n.exc.func) == "SystemExit" and n.exc.args:
                call = n.exc.args[0]
            if call is None:
                continue
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                found.add(call.func.id)
            elif isinstance(call, ast.Name):
                stmt = mod.stmt_of.get(id(call))
                if stmt is not None:
                    for d in reaching(mod, call.id, stmt):
                        if d[0] == "assign" and isinstance(d[1].value, ast.Call) and isinstance(d[1].value.func, ast.Name):
                            found.add(d[1].value.func.id)
        changed = True
        while changed:
            changed = False
            for q in list(found):
                fi = mod.funcs.get(q)
                if fi is None:
                    continue
                for n in ast.walk(fi.node):
                    if isinstance(n, ast.Return) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name):
                        if n.value.func.id not in found and n.value.func.id in mod.funcs:
                            found.add(n.value.func.id)
                            changed = True
        self.exit_funcs[key] = found
        return found


def _dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


_REACH: dict = {}
_WALK: dict = {}


def reaching(mod: PyModule, name: str, stmt) -> list:
    key = (id(mod), name, id(stmt))
    r = _REACH.get(key)
    if r is None:
        r = _REACH[key] = _reaching(mod, name, stmt)
    return r


def clear_caches() -> None:
    for c in (_TNAMES, _DEFS, _WALRUS, _REACH, _WALK):
        c.clear()


def _reaching(mod: PyModule, name: str, stmt) -> list:
    """Definitions of `name` that may reach `stmt` (see module docstring)."""
    out: list = []
    cur = stmt
    while True:
        info = mod.parent.get(id(cur))
        if info is None:
            return out
        owner, fieldname, idx = info
        block = getattr(owner, fieldname)
        for s in reversed(block[:idx]):
            d, ds = _defs_in_stmt(s, name)
            out += ds
            if d:
                return out
        if isinstance(owner, ast.Module):
            return out
        if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fi = mod.func_by_node.get(id(owner))
            if fi and (name in fi.params or name in (fi.vararg, fi.kwarg)):
                out.append(("param", owner, name))
                return out
            # closure, then module scope (as of the end of the module)
            outer = mod.scope_of.get(id(owner))
            while isinstance(outer, ast.ClassDef):
                outer = mod.scope_of.get(id(outer))
            if outer is None or isinstance(outer, ast.Module):
                d, ds = _block_defs(mod.tree.body, name)
                return out + ds
            cur = owner
            continue
        if isinstance(owner, ast.ClassDef):
            d, ds = _block_defs(mod.tree.body, name)
            return out + ds
        if isinstance(owner, (ast.For, ast.AsyncFor)) and fieldname == "body" and _binds(owner.target, name):
            out.append(("for", owner, owner.target))
            return out
        if isinstance(owner, (ast.With, ast.AsyncWith)):
            for it in owner.items:
                if it.optional_vars is not None and _binds(it.optional_vars, name):
                    out.append(("with", owner, it))
                    return out
        if isinstance(owner, ast.ExceptHandler):
            if owner.name == name:
                out.append(("except", owner, None))
                return out
            cur = mod.parent.get(id(owner), (None,))[0]
            if cur is None:
                return out
            continue
        if isinstance(owner, ast.match_case):
            cur = mod.parent.get(id(owner), (None,))[0]
            if cur is None:
                return out
            continue
        cur = owner


def _moves_to_parent(loop, name: str) -> bool:
    """A loop that assigns NAME and takes NAME's parent directory (`os.path.dirname(NAME)`,
    `NAME.parent`): it walks NAME up the tree."""
    key = (id(loop), name)
    if key not in _WALK:
        _WALK[key] = _moves_to_parent_raw(loop, name)
    return _WALK[key]


def _moves_to_parent_raw(loop, name: str) -> bool:
    assigns = parents = False
    for n in ast.walk(loop):
        if isinstance(n, ast.Assign) and any(_binds(t, name) for t in n.targets):
            assigns = True
        elif isinstance(n, ast.Call) and _dotted(n.func) == "os.path.dirname" and n.args \
                and isinstance(n.args[0], ast.Name) and n.args[0].id == name:
            parents = True
        elif isinstance(n, ast.Attribute) and n.attr == "parent" and isinstance(n.value, ast.Name) \
                and n.value.id == name:
            parents = True
    return assigns and parents


def _walks_up(mod: PyModule, name: str, stmt) -> bool:
    """`stmt` lies in a loop of its function that walks NAME up the tree."""
    cur = stmt
    while True:
        info = mod.parent.get(id(cur))
        if info is None:
            return False
        owner = info[0]
        if isinstance(owner, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return False
        if isinstance(owner, (ast.While, ast.For)) and _moves_to_parent(owner, name):
            return True
        cur = owner


def _tests_empty(test, name: str) -> bool:
    """`not NAME`, `NAME is None`, `NAME == ""`, or an `or` of tests holding one: true
    whenever NAME is empty."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return isinstance(test.operand, ast.Name) and test.operand.id == name
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.left, ast.Name) \
            and test.left.id == name and isinstance(test.ops[0], (ast.Is, ast.Eq)):
        c = test.comparators[0]
        return isinstance(c, ast.Constant) and c.value in (None, "")
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        return any(_tests_empty(v, name) for v in test.values)
    return False


def _guarded_nonempty(mod: PyModule, name: str, stmt) -> bool:
    """An `if not NAME: return` (raise, continue, break, exit) after NAME's last definition and
    before `stmt`, in `stmt`'s block or one around it: NAME is not empty at `stmt`."""
    cur = stmt
    while True:
        info = mod.parent.get(id(cur))
        if info is None:
            return False
        owner, fieldname, idx = info
        for s in reversed(getattr(owner, fieldname)[:idx]):
            if isinstance(s, ast.If) and not s.orelse and _tests_empty(s.test, name) and _terminates(s.body):
                return True
            if _defs_in_stmt(s, name)[1]:
                return False
        if isinstance(owner, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return False
        cur = owner


class FunctionWalk:
    """Evaluates one function (or a module's top level) and collects its
    operations, decisions, reads, outputs and its summary."""

    def __init__(self, an: Analyzer, mod: PyModule, fi: FuncInfo | None):
        self.an = an
        self.mod = mod
        self.fi = fi
        self.fname = fi.qual if fi else ""
        self.ops: list[M.Op] = []
        self.reads: list[tuple] = []          # (call node, ReadInfo)
        self.decisions: list[tuple] = []      # (stmt, M.Decision)
        self.chain_seeds: list[tuple] = []    # (call node, how)
        self.summary = Summary()
        self.exit_funcs = an.module_exit_funcs(mod)
        self.overrides: dict = {}
        self.lock_sites: set = set()
        self.handlers: list = []

    # ------------------------------------------------------------ evaluation
    def ev(self, node, stmt=None) -> V.Val:
        if node is None:
            return V.NONE
        key = id(node)
        cacheable = not self.overrides
        if cacheable and key in self.an.memo:
            return self.an.memo[key]
        if key in self.an.active or self.an.depth > 120:
            return Unk("assembled:recursive")
        self.an.active.add(key)
        self.an.depth += 1
        try:
            v = self._ev(node, stmt or self.mod.stmt_of.get(key))
        except RecursionError:
            v = Unk("assembled:recursive")
        finally:
            self.an.depth -= 1
            self.an.active.discard(key)
        if cacheable:
            self.an.memo[key] = v
        return v

    def _ev(self, node, stmt) -> V.Val:
        if isinstance(node, ast.Constant):
            val = node.value
            if isinstance(val, str):
                return V.s(val)
            if isinstance(val, bytes):
                try:
                    return V.s(val.decode())
                except UnicodeDecodeError:
                    return Unk("dynamic")
            if isinstance(val, bool):
                return Num(int(val))
            if isinstance(val, int):
                return Num(val)
            if val is None:
                return V.NONE
            return Unk("dynamic")
        if isinstance(node, ast.JoinedStr):
            vals, hints = [], []
            for p in node.values:
                if isinstance(p, ast.Constant):
                    vals.append(V.s(str(p.value)))
                    hints.append(None)
                elif isinstance(p, ast.FormattedValue):
                    vals.append(self.ev(p.value, stmt))
                    hints.append(_hint_of(p.value))
            return V.concat(*vals, hints=hints)
        if isinstance(node, ast.Name):
            return self._name(node.id, stmt)
        if isinstance(node, ast.Attribute):
            return self._attribute(node, stmt)
        if isinstance(node, ast.Subscript):
            return self._subscript(node, stmt)
        if isinstance(node, ast.Call):
            return self._call(node, stmt)
        if isinstance(node, ast.BinOp):
            return self._binop(node, stmt)
        if isinstance(node, ast.IfExp):
            return V.union([self.ev(node.body, stmt), self.ev(node.orelse, stmt)], drop_empty=False)
        if isinstance(node, ast.BoolOp):
            vals = [self.ev(v, stmt) for v in node.values]
            if isinstance(node.op, ast.Or):
                keep = []
                for v, sub in zip(vals, node.values):
                    if isinstance(v, NoneV) or (isinstance(v, Str) and v.alts == ("",)):
                        continue
                    if isinstance(v, Unk) and v.reason.startswith("env"):
                        continue
                    keep.append((v, sub))
                if not keep:
                    unk = [v for v in vals if isinstance(v, Unk)]
                    return unk[0] if unk else vals[-1]
                first = keep[0][0]
                if (len(keep) > 1 and isinstance(first, Str) and all(P.has_params(t) for t in first.alts)
                        and all(isinstance(v, Str) and set(v.alts) <= {".", "./"} for v, _ in keep[1:])):
                    # `os.path.dirname(p) or "."`: the "." is the directory of a bare relative p,
                    # which p's own value already gives at each call site
                    return first
                strs = [v for v, _ in keep if isinstance(v, Str)]
                if strs and all(isinstance(v, (Str, Unk)) for v, _ in keep):
                    alts = []
                    for v, sub in keep:
                        alts.extend(V.piece(v, _hint_of(sub)))
                    return V.make_str(alts)
                return V.union([v for v, _ in keep])
            return vals[-1]
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            items = []
            for e in node.elts:
                if isinstance(e, ast.Starred):
                    inner = self.ev(e.value, stmt)
                    if isinstance(inner, Lst):
                        items.extend(inner.items)
                    else:
                        items.append(inner)
                else:
                    items.append(self.ev(e, stmt))
            return Lst(tuple(items[:64]))
        if isinstance(node, ast.Dict):
            items = []
            for k, v in zip(node.keys, node.values):
                if k is None:
                    continue
                items.append((self.ev(k, stmt), self.ev(v, stmt)))
            return Dct(tuple(items[:64]))
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return self._comp(node, stmt)
        if isinstance(node, ast.NamedExpr):
            return self.ev(node.value, stmt)
        if isinstance(node, (ast.Await, ast.Starred)):
            return self.ev(node.value, stmt)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            v = self.ev(node.operand, stmt)
            return Num(-v.value) if isinstance(v, Num) else Unk("dynamic")
        return Unk("dynamic")

    def _comp(self, node, stmt) -> V.Val:
        saved = dict(self.overrides)
        try:
            for gen in node.generators:
                it = self.ev(gen.iter, stmt)
                elem = self._elem(it)
                self._bind_target(gen.target, elem)
            return Lst((self.ev(node.elt, stmt),))
        finally:
            self.overrides = saved

    def _bind_target(self, target, val) -> None:
        if isinstance(target, ast.Name):
            self.overrides[target.id] = val
        elif isinstance(target, (ast.Tuple, ast.List)):
            for i, t in enumerate(target.elts):
                if isinstance(val, Lst) and i < len(val.items):
                    self._bind_target(t, val.items[i])
                elif isinstance(val, Obj) and val.kind == "walk":
                    self._bind_target(t, self._walk_part(val, i))
                else:
                    self._bind_target(t, Unk(V.reason_of(val) if not isinstance(val, Str) else "assembled:unpack"))

    def _walk_part(self, val: Obj, i: int) -> V.Val:
        base = val.data[0]
        if i == 0:
            return base
        return Listing(V.join(base, V.s("*")), names=True)

    def _elem(self, it: V.Val) -> V.Val:
        if isinstance(it, Lst):
            if not it.items:
                return Unk("assembled:loop")
            if len(it.items) == 1:
                return it.items[0]
            return V.union(list(it.items))
        if isinstance(it, Listing):
            if it.names:
                return Unk("assembled:listing")
            return it.pattern
        if isinstance(it, Dct):
            return V.union([k for k, _ in it.items]) if it.items else Unk("assembled:loop")
        if isinstance(it, Handle):
            return Unk("data:record")
        if isinstance(it, Obj) and it.kind == "walk":
            return Lst((it.data[0], Unk("assembled:listing"), Listing(V.join(it.data[0], V.s("*")), names=True)))
        if isinstance(it, Unk):
            return Unk(it.reason if it.reason.startswith("data") else "assembled:loop")
        return Unk("assembled:loop")

    def _name(self, name: str, stmt) -> V.Val:
        if name in self.overrides:
            return self.overrides[name]
        if name == "__file__":
            return self.mod.file_template
        if name in self.mod.injected:
            return self.mod.injected[name]
        if stmt is None:
            return Unk("dynamic")
        if _walks_up(self.mod, name, stmt):
            # rule (1): a walk up the tree (the nearest package.json above a command's working
            # directory) probes whichever directory holds the name, no fixed one: its start is
            # one probe among the directories above it
            return V.s(P.WILD)
        defs = reaching(self.mod, name, stmt)
        if not defs:
            if name in ("open", "print", "str", "sorted", "list", "tuple", "set", "frozenset", "len",
                        "int", "dict", "isinstance", "getattr", "next", "iter", "reversed", "max", "min",
                        "exit", "quit", "repr", "bool", "float", "any", "all", "enumerate", "zip", "map",
                        "filter", "range", "hasattr", "type", "super", "vars", "id", "abs", "sum", "round",
                        "Exception", "ValueError", "SystemExit", "RuntimeError", "OSError", "KeyError"):
                return Mod(None, name)
            return Unk("dynamic")
        vals = [self._def_value(d, name) for d in defs[:6]]
        val = vals[0] if len(vals) == 1 else V.union(vals)
        if isinstance(val, Str) and "" in val.alts and len(val.alts) > 1 and _guarded_nonempty(self.mod, name, stmt):
            # past `if not path: return`, the empty alternative (`p if c else ""`) names nothing
            val = V.make_str(a for a in val.alts if a != "")
        return val

    def _def_value(self, d, name: str) -> V.Val:
        kind, node, extra = d
        if kind == "assign":
            val = self.ev(node.value, node)
            return self._destructure(extra, name, val, node.value)
        if kind == "ann":
            return self.ev(node.value, node)
        if kind == "aug":
            prev_defs = reaching(self.mod, name, node)
            prev = V.union([self._def_value(x, name) for x in prev_defs[:4]]) if prev_defs else Unk("dynamic")
            rhs = self.ev(node.value, node)
            if isinstance(node.op, ast.Add):
                if isinstance(prev, Lst) and isinstance(rhs, Lst):
                    return Lst(prev.items + rhs.items)
                if isinstance(prev, Num) or isinstance(rhs, Num):
                    return V.s(P.WILD)      # a counter: varies at run time
                return V.concat(prev, rhs, hints=[name, _hint_of(node.value)])
            if isinstance(node.op, ast.Div):
                return V.join(prev, rhs)
            return Unk("dynamic")
        if kind == "for":
            it = self.ev(node.iter, node)
            elem = self._elem(it)
            return self._destructure(extra, name, elem, None)
        if kind == "with":
            v = self.ev(extra.context_expr, node)
            return self._destructure(extra.optional_vars, name, v, None)
        if kind == "except":
            return Unk("assembled:exception")
        if kind == "walrus":
            return self.ev(node.value, self.mod.stmt_of.get(id(node)))
        if kind == "funcdef":
            fi = self.mod.func_by_node.get(id(node))
            if fi is not None:
                return Fn(self.mod.path if not self.mod.embedded else self._mod_key(), fi.qual)
            return Unk("dynamic")
        if kind == "classdef":
            for q, c in self.mod.classes.items():
                if c is node:
                    return Obj("class", (self._mod_key(), q))
            return Unk("dynamic")
        if kind == "import":
            return self._import_value(node, extra)
        if kind == "param":
            return self._param(name, node)
        return Unk("dynamic")

    def _mod_key(self) -> str:
        if self.mod.embedded:
            return f"{self.mod.path}#{self.mod.line_offset}"
        return self.mod.path

    def _destructure(self, target, name, val, value_node) -> V.Val:
        if isinstance(target, ast.Name) or target is None:
            return val
        if isinstance(target, ast.Starred):
            return Unk("assembled:unpack")
        if isinstance(target, (ast.Tuple, ast.List)):
            for i, t in enumerate(target.elts):
                if _binds(t, name):
                    if isinstance(val, Lst) and i < len(val.items):
                        return self._destructure(t, name, val.items[i], None)
                    if isinstance(val, Obj) and val.kind == "walk":
                        return self._walk_part(val, i)
                    if isinstance(val, Obj) and val.kind == "partition":
                        return val.data[i] if i < len(val.data) else Unk("assembled:unpack")
                    return Unk(val.reason if isinstance(val, Unk) else "assembled:unpack")
        if isinstance(target, (ast.Attribute, ast.Subscript)):
            return val
        return Unk("assembled:unpack")

    def _param(self, name: str, owner=None) -> V.Val:
        fi = self.mod.func_by_node.get(id(owner)) if owner is not None else self.fi
        if fi is not None and fi.cls and fi.params and name == fi.params[0] and name in ("self", "cls"):
            return Obj("self", (self._mod_key(), fi.cls))
        if fi is not None and name in (fi.vararg, fi.kwarg):
            return Unk("assembled:parameter", hint=name)
        if fi is not self.fi:
            # a parameter of an enclosing function, seen from a closure
            return Unk("assembled:parameter", hint=name)
        if name in ("args", "ns", "namespace", "opts", "options", "parsed_args"):
            return Obj("args")
        return V.s(P.param(name))

    def _option_value(self, dest: str) -> V.Val | None:
        """E1's argv class for argparse options: `args.dir` of `add_argument("--dir",
        default=X)` is X where an invocation passes no `--dir`, and the value each invocation
        passes after `--dir` (the `argv:--dir` token, bound per invocation as sys.argv[N] is);
        None when the module declares no such option."""
        memo = self.mod.option_values
        if dest in memo:
            return memo[dest]
        memo[dest] = None       # a default that names its own option evaluates to no value
        found = None
        for n in ast.walk(self.mod.tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_argument"):
                continue
            kws = {k.arg: k.value for k in n.keywords if k.arg}
            names = [a.value for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            longs = [x for x in names if x.startswith("--")]
            own = _const_str(kws["dest"]) if "dest" in kws else (
                longs[0][2:].replace("-", "_") if longs else names[0].lstrip("-").replace("-", "_") if names else None)
            if own != dest:
                continue
            vals = []
            if "default" in kws:
                v = self.ev(kws["default"], self.mod.stmt_of.get(id(kws["default"])))
                if isinstance(v, Str):
                    vals.append(v)
            if longs:
                vals.append(V.s(P.tok("argv:" + longs[0])))
            found = V.union(vals) if vals else None
            break
        memo[dest] = found
        return found

    def _import_value(self, node, alias) -> V.Val:
        an = self.an
        if isinstance(node, ast.Import):
            target = an.resolve_import(alias.name, self.mod.path)
            if alias.asname:
                return Mod(target, alias.name) if target else Mod(None, alias.name)
            first = alias.name.split(".")[0]
            target = an.resolve_import(first, self.mod.path)
            return Mod(target, first) if target else Mod(None, first)
        modname = node.module or ""
        level = node.level or 0
        full = (modname + "." if modname else "") + alias.name
        sub = an.resolve_import(full, self.mod.path, level)
        if sub:
            return Mod(sub, full)
        base = an.resolve_import(modname, self.mod.path, level) if (modname or level) else None
        if base:
            return self._module_attr(base, alias.name)
        return Mod(None, full)

    def _module_attr(self, path: str, attr: str) -> V.Val:
        mod = self.an.module(path) if "#" not in path else self.an.modules.get(path)
        if mod is None:
            return Unk("dynamic")
        if attr in mod.funcs:
            return Fn(path, attr)
        if attr in mod.classes:
            return Obj("class", (path, attr))
        d, defs = _block_defs(mod.tree.body, attr)
        if not defs:
            return Unk("dynamic")
        walker = self.an_module_walker(mod)
        return V.union([walker._def_value(x, attr) for x in defs[:6]])

    def an_module_walker(self, mod: PyModule) -> "FunctionWalk":
        cache = getattr(self.an, "_mod_walkers", None)
        if cache is None:
            cache = self.an._mod_walkers = {}
        key = id(mod)
        if key not in cache:
            cache[key] = FunctionWalk(self.an, mod, None)
        return cache[key]

    def _attribute(self, node: ast.Attribute, stmt) -> V.Val:
        base = self.ev(node.value, stmt)
        attr = node.attr
        if isinstance(base, Mod):
            if base.path is None:
                full = base.name + "." + attr
                if full in ("os.devnull", "os.path.devnull"):
                    return V.s("/dev/null")
                return Mod(None, full)
            return self._module_attr(base.path, attr)
        if isinstance(base, Obj):
            if base.kind == "args":
                d = self._option_value(attr)
                return d if d is not None else Unk("data:argv", hint=attr)
            if base.kind == "proc":
                return Unk("assembled:stdout") if attr in ("stdout", "stderr") else Unk("dynamic")
            if base.kind in ("self", "instance", "class"):
                return self._class_attr(base.data[0], base.data[1], attr)
            if base.kind == "hash":
                return Unk("dynamic")
            return Unk("dynamic", hint=attr)
        if isinstance(base, Str) and _param_only(base) and attr not in ("parent", "name", "stem", "suffix", "path"):
            return V.access(base, "." + _safe_key(attr))
        if isinstance(base, (Str, Handle)) or (isinstance(base, Listing) and not base.names):
            if attr == "parent":
                return V.dirname(base)
            if attr == "name":
                return V.basename(base)
            if attr == "stem":
                return V.stem(base)
            if attr == "suffix":
                return V.suffix_of(base)
            if attr in ("path",):
                return base if not isinstance(base, Handle) else base.path
            return Unk("dynamic", hint=attr)
        if isinstance(base, Unk):
            return Unk(base.reason, hint=attr)
        return Unk("dynamic", hint=attr)

    def _class_attr(self, modkey: str, cls: str, attr: str, depth: int = 0) -> V.Val:
        mod = self.an.modules.get(modkey) or (self.an.module(modkey) if "#" not in modkey else None)
        if mod is None or depth > 4:
            return Unk("dynamic", hint=attr)
        cnode = mod.classes.get(cls)
        if cnode is None:
            return Unk("dynamic", hint=attr)
        walker = self.an_module_walker(mod)
        d, defs = _block_defs(cnode.body, attr)
        vals = []
        for x in defs[:4]:
            if x[0] == "funcdef":
                fi = mod.func_by_node.get(id(x[1]))
                is_prop = any(_dotted(dd) in ("property", "functools.cached_property", "cached_property") for dd in x[1].decorator_list)
                if fi is not None and is_prop:
                    vals.append(self.an.summary(fi).ret)
                elif fi is not None:
                    vals.append(Fn(modkey, fi.qual))
            else:
                vals.append(walker._def_value(x, attr))
        if vals:
            return V.union(vals)
        # self.attr = ... in methods
        for q, fi in sorted(mod.funcs.items()):
            if fi.cls != cls:
                continue
            for n in ast.walk(fi.node):
                if isinstance(n, (ast.Assign, ast.AnnAssign)):
                    targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                    for t in targets:
                        if (isinstance(t, ast.Attribute) and t.attr == attr and isinstance(t.value, ast.Name)
                                and t.value.id in ("self", "cls") and n.value is not None):
                            w = FunctionWalk(self.an, mod, fi)
                            vals.append(w.ev(n.value, n))
        if vals:
            return V.union(vals[:6])
        for b in mod.class_bases.get(cls, []):
            bname = _dotted(b)
            if bname and bname in mod.classes:
                return self._class_attr(modkey, bname, attr, depth + 1)
        return Unk("dynamic", hint=attr)

    def _subscript(self, node: ast.Subscript, stmt) -> V.Val:
        base = self.ev(node.value, stmt)
        key = node.slice
        if isinstance(base, Mod) and base.path is None:
            if base.name == "os.environ":
                k = self.ev(key, stmt)
                return self._env(k, None, has_default=False)
            if base.name == "sys.argv":
                if isinstance(key, ast.Constant) and isinstance(key.value, int) and key.value >= 1 \
                        and not self.mod.embedded:
                    # a script's own argument, bound at each invocation (static_half); an
                    # embedded `python3 -c` takes the arguments of its own command line
                    return V.s(P.argv(key.value))
                return Unk("data:argv")
        kv = self.ev(key, stmt) if not isinstance(key, ast.Slice) else Unk("dynamic")
        if isinstance(base, Str) and _param_only(base) and isinstance(kv, Str) and len(kv.alts) == 1 and P.L not in kv.alts[0]:
            return V.access(base, "." + _safe_key(kv.alts[0]))
        if isinstance(base, Dct) and isinstance(kv, Str):
            for k, v in base.items:
                if isinstance(k, Str) and k.alts == kv.alts:
                    return v
            return Unk("assembled:dict", hint=kv.alts[0] if len(kv.alts) == 1 else None)
        if isinstance(base, Lst) and isinstance(kv, Num):
            if -len(base.items) <= kv.value < len(base.items):
                return base.items[kv.value]
            return Unk("assembled:container")
        if isinstance(base, Lst) and isinstance(key, ast.Slice):
            return base
        if isinstance(base, Listing) and not base.names:
            return base if isinstance(key, ast.Slice) else base.pattern
        if isinstance(base, Str) and isinstance(key, ast.Slice):
            return Unk("assembled:split")
        hint = kv.alts[0] if isinstance(kv, Str) and len(kv.alts) == 1 else None
        if isinstance(base, Unk):
            return Unk(base.reason, hint=hint)
        if isinstance(base, Obj) and base.kind == "args":
            return Unk("data:argv", hint=hint)
        if isinstance(base, Dct):
            return Unk("assembled:dict", hint=hint)
        return Unk("assembled:container", hint=hint)

    def _binop(self, node: ast.BinOp, stmt) -> V.Val:
        a = self.ev(node.left, stmt)
        b = self.ev(node.right, stmt)
        if isinstance(node.op, ast.Add):
            if isinstance(a, Num) and isinstance(b, Num):
                return Num(a.value + b.value)
            if isinstance(a, Lst) and isinstance(b, Lst):
                return Lst(a.items + b.items)
            if V.is_strlike(a) or V.is_strlike(b):
                return V.concat(a, b, hints=[_hint_of(node.left), _hint_of(node.right)])
            return Unk(V.reason_of(a) if isinstance(a, Unk) else "dynamic")
        if isinstance(node.op, ast.Div):
            if isinstance(a, Num) or isinstance(b, Num):
                return Unk("dynamic")
            return V.join(a, b)
        if isinstance(node.op, ast.Mod) and isinstance(a, Str):
            args = b.items if isinstance(b, Lst) else (b,)
            hints = [_hint_of(e) for e in node.right.elts] if isinstance(node.right, ast.Tuple) else [_hint_of(node.right)]
            return self._percent(a, list(args), hints)
        return Unk("dynamic")

    def _percent(self, fmt: Str, args: list, hints: list) -> V.Val:
        out = []
        for t in fmt.alts:
            pieces = re.split(r"(%[-#0 +]*\d*(?:\.\d+)?[sdrifx])", t)
            vals, hs = [], []
            i = 0
            for p in pieces:
                if re.fullmatch(r"%[-#0 +]*\d*(?:\.\d+)?[sdrifx]", p):
                    vals.append(args[i] if i < len(args) else Unk("dynamic"))
                    hs.append(hints[i] if i < len(hints) else None)
                    i += 1
                else:
                    vals.append(V.s(p.replace("%%", "%")))
                    hs.append(None)
            r = V.concat(*vals, hints=hs)
            out.extend(V.as_templates(r))
        return V.make_str(out)

    def _format(self, fmt: Str, call: ast.Call, stmt) -> V.Val:
        args = [self.ev(a, stmt) for a in call.args]
        hints = [_hint_of(a) for a in call.args]
        kw = {k.arg: (self.ev(k.value, stmt), _hint_of(k.value) or k.arg) for k in call.keywords if k.arg}
        out = []
        for t in fmt.alts:
            vals, hs = [], []
            pos = 0
            auto = 0
            for m in re.finditer(r"\{([^{}]*)\}", t):
                vals.append(V.s(t[pos:m.start()]))
                hs.append(None)
                field_name = m.group(1).split(":")[0].split("!")[0]
                if field_name == "":
                    idx = auto
                    auto += 1
                    vals.append(args[idx] if idx < len(args) else Unk("dynamic"))
                    hs.append(hints[idx] if idx < len(hints) else None)
                elif field_name.isdigit():
                    idx = int(field_name)
                    vals.append(args[idx] if idx < len(args) else Unk("dynamic"))
                    hs.append(hints[idx] if idx < len(hints) else None)
                else:
                    base = field_name.split(".")[0].split("[")[0]
                    if base in kw:
                        vals.append(kw[base][0])
                        hs.append(kw[base][1])
                    else:
                        vals.append(Unk("dynamic"))
                        hs.append(base)
                pos = m.end()
            vals.append(V.s(t[pos:]))
            hs.append(None)
            out.extend(V.as_templates(V.concat(*vals, hints=hs)))
        return V.make_str(out) if out else Unk("dynamic")

    # -- environment
    def _env(self, k: V.Val, default: V.Val | None, has_default: bool) -> V.Val:
        if not isinstance(k, Str) or len(k.alts) != 1 or P.L in k.alts[0]:
            return default if has_default and default is not None else Unk("env")
        name = k.alts[0]
        if name in self.mod.env:
            return self.mod.env[name]
        root = ENV_ROOTS.get(name)
        if root:
            return V.s(P.tok(root))
        kind = P.classify_name(name)
        if kind in P.IDS:
            return Unk("env", hint=kind)
        if has_default and default is not None and not isinstance(default, NoneV):
            return default
        return Unk("env:" + name)

    # -- calls
    def callee(self, call: ast.Call, stmt):
        f = call.func
        if isinstance(f, ast.Attribute):
            recv = self.ev(f.value, stmt)
            if isinstance(recv, Mod):
                if recv.path is None:
                    return ("ext", recv.name + "." + f.attr, None)
                target = self._module_attr(recv.path, f.attr)
                if isinstance(target, Fn):
                    return ("tree", target, False)
                if isinstance(target, Obj) and target.kind == "class":
                    return ("class", target, None)
                return ("unknown", None, None)
            if isinstance(recv, Obj) and recv.kind in ("self", "instance", "class"):
                m = self._class_attr(recv.data[0], recv.data[1], f.attr)
                if isinstance(m, Fn):
                    return ("tree", m, recv.kind != "class")
            return ("method", recv, f.attr)
        if isinstance(f, ast.Name):
            v = self.ev(f, stmt)
            if isinstance(v, Fn):
                return ("tree", v, False)
            if isinstance(v, Mod):
                return ("ext", v.name, None) if v.path is None else ("unknown", None, None)
            if isinstance(v, Obj) and v.kind == "class":
                return ("class", v, None)
            return ("unknown", None, None)
        return ("unknown", None, None)

    def _call(self, call: ast.Call, stmt) -> V.Val:
        kind, a, b = self.callee(call, stmt)
        if kind == "tree":
            return self._call_tree(a, call, stmt, b)
        if kind == "ext":
            return self._call_ext(a, call, stmt)
        if kind == "method":
            return self._call_method(a, b, call, stmt)
        if kind == "class":
            return Obj("instance", a.data)
        return Unk("assembled:call")

    def _arg(self, call: ast.Call, i: int, kw: str | None = None):
        if i is not None and i < len(call.args) and not isinstance(call.args[i], ast.Starred):
            return call.args[i]
        if kw:
            for k in call.keywords:
                if k.arg == kw:
                    return k.value
        return None

    def _call_ext(self, name: str, call: ast.Call, stmt) -> V.Val:
        ev = lambda n: self.ev(n, stmt) if n is not None else None  # noqa: E731
        if name in _PATH_CTORS:
            if not call.args:
                return V.s(".")
            return V.join(*[self.ev(x, stmt) for x in call.args])
        if name in _PATH_IDENTITY:
            v = ev(self._arg(call, 0))
            return v if v is not None else Unk("dynamic")
        if name == "os.path.expanduser":
            v = ev(self._arg(call, 0))
            return v if v is not None else Unk("dynamic")
        if name in ("os.path.join", "posixpath.join"):
            return V.join(*[self.ev(x, stmt) for x in call.args])
        if name in ("os.path.dirname", "posixpath.dirname"):
            return V.dirname(ev(self._arg(call, 0)) or Unk("dynamic"))
        if name in ("os.path.basename", "posixpath.basename"):
            return V.basename(ev(self._arg(call, 0)) or Unk("dynamic"))
        if name in ("os.environ.get", "os.getenv", "os.environ.setdefault"):
            k = ev(self._arg(call, 0, "key"))
            dnode = self._arg(call, 1, "default")
            return self._env(k or Unk("env"), ev(dnode) if dnode is not None else None, dnode is not None)
        if name in ("pathlib.Path.home",) or name.endswith(".Path.home"):
            return V.s(P.tok("home"))
        if name in ("pathlib.Path.cwd", "os.getcwd") or name.endswith(".Path.cwd"):
            return V.s(P.tok("proj"))
        if name == "tempfile.gettempdir":
            return V.s(P.tok("tmpdir"))
        if name in ("tempfile.mkstemp", "tempfile.NamedTemporaryFile", "tempfile.mkdtemp", "tempfile.TemporaryDirectory"):
            d = ev(self._arg(call, None, "dir"))
            pre = ev(self._arg(call, None, "prefix"))
            suf = ev(self._arg(call, None, "suffix"))
            base = d if d is not None and not isinstance(d, NoneV) else V.s(P.tok("tmpdir"))
            p = V.join(base, V.concat(pre if isinstance(pre, Str) else V.s(""), V.s(P.RAND), suf if isinstance(suf, Str) else V.s("")))
            if name == "tempfile.mkstemp":
                return Lst((Unk("dynamic"), p))
            if name == "tempfile.NamedTemporaryFile":
                return Handle(p, "temp", self.mod.ln(call))
            return p
        if name in ("os.listdir",):
            d = ev(self._arg(call, 0)) or V.s(".")
            return Listing(V.join(d, V.s("*")), names=True)
        if name in ("os.scandir",):
            d = ev(self._arg(call, 0)) or V.s(".")
            return Listing(V.join(d, V.s("*")), names=False)
        if name == "os.walk":
            d = ev(self._arg(call, 0)) or V.s(".")
            return Obj("walk", (d,))
        if name in ("glob.glob", "glob.iglob"):
            return Listing(ev(self._arg(call, 0, "pathname")) or Unk("dynamic"))
        if name in ("sorted", "list", "tuple", "set", "frozenset", "reversed", "iter"):
            v = ev(self._arg(call, 0))
            return v if v is not None else Lst(())
        if name == "next":
            v = ev(self._arg(call, 0))
            return self._elem(v) if v is not None else Unk("dynamic")
        if name in _OPEN_FUNCS or name == "os.open":
            p = ev(self._arg(call, 0, "file")) or Unk("dynamic")
            if name == "os.open":
                p = self._dir_fd(call, stmt, p)
            return Handle(p, "open", self.mod.ln(call))
        if name in ("json.load", "json.loads", "yaml.safe_load", "yaml.load", "tomllib.load", "tomllib.loads", "pickle.load"):
            src = self._arg(call, 0)
            if src is not None:
                d = _dotted(src)
                if d == "sys.stdin" or "stdin" in ast.dump(src):
                    return Unk("data:payload")
                sv = self.ev(src, stmt)
                if isinstance(sv, Unk) and sv.reason == "data:payload":
                    return sv
            return Unk("data:record")
        if name in ("sys.stdin.read", "sys.stdin.readline", "sys.stdin.buffer.read"):
            return Unk("data:payload")
        if name in ("subprocess.check_output", "subprocess.getoutput", "os.popen"):
            return Unk("assembled:stdout")
        if name in ("subprocess.run", "subprocess.Popen"):
            return Obj("proc")
        if name in ("argparse.ArgumentParser",):
            return Obj("parser")
        if name in ("hashlib.sha256", "hashlib.sha1", "hashlib.md5", "hashlib.blake2b", "hashlib.new"):
            return Obj("hash")
        if name.startswith(_NONCE_MODS):
            return V.s(P.WILD)
        if _TS_CALLS.search(name) and (name.startswith(("time.", "datetime.")) or ".datetime." in name or name.startswith("_dt")):
            return V.s(P.tok("ts"))
        if name in ("int", "len", "float", "abs", "round", "sum"):
            v = ev(self._arg(call, 0))
            if isinstance(v, Str) and v.alts == (P.tok("ts"),):
                return v
            return v if isinstance(v, Num) else Unk("dynamic")
        if name in ("getattr",):
            obj = self._arg(call, 0)
            attr = _const_str(self._arg(call, 1))
            if obj is not None and attr:
                fake = ast.Attribute(value=obj, attr=attr, ctx=ast.Load())
                self.mod.stmt_of[id(fake)] = stmt
                return self._attribute(fake, stmt)
            return Unk("dynamic")
        if name in ("importlib.import_module",):
            n = ev(self._arg(call, 0))
            if isinstance(n, Str) and len(n.alts) == 1:
                path = self.an.resolve_import(n.alts[0], self.mod.path)
                return Mod(path, n.alts[0]) if path else Mod(None, n.alts[0])
            return Unk("dynamic")
        if name in ("re.sub", "re.match", "re.search", "re.findall", "re.fullmatch"):
            return Unk("assembled:regex")
        return Unk("assembled:call")

    def _call_method(self, recv: V.Val, attr: str, call: ast.Call, stmt) -> V.Val:
        ev = lambda n: self.ev(n, stmt) if n is not None else None  # noqa: E731
        if isinstance(recv, Handle) and attr not in ("read", "readline", "readlines", "fileno", "write", "close"):
            recv_path = recv.path
        else:
            recv_path = recv
        if isinstance(recv, Handle):
            if attr in ("read", "readline", "readlines", "read_text"):
                return Unk("data:record")
            if attr == "fileno":
                return recv
            if attr == "__enter__":
                return recv
            return Unk("dynamic")
        if isinstance(recv_path, Str) and recv_path.alts == (P.tok("ts"),) and attr not in ("split", "rsplit", "partition"):
            return recv_path
        if isinstance(recv_path, Str) and _param_only(recv_path):
            if attr == "get":
                k = ev(self._arg(call, 0))
                if isinstance(k, Str) and len(k.alts) == 1 and P.L not in k.alts[0]:
                    return V.access(recv_path, "." + _safe_key(k.alts[0]))
                return Unk("assembled:parameter")
            if attr in ("strip", "rstrip", "lstrip", "lower", "upper", "decode", "encode", "resolve",
                        "absolute", "expanduser", "as_posix"):
                return recv_path
            if attr in ("items", "keys", "values", "split", "splitlines"):
                return Unk("assembled:parameter")
        if V.is_strlike(recv_path) or isinstance(recv_path, Listing):
            if attr == "joinpath":
                return V.join(recv_path, *[self.ev(x, stmt) for x in call.args])
            if attr in ("resolve", "absolute", "expanduser", "as_posix", "__fspath__", "__str__", "encode", "decode"):
                return recv_path
            if attr == "with_suffix":
                a0 = self._arg(call, 0)
                if (isinstance(a0, ast.BinOp) and isinstance(a0.op, ast.Add) and isinstance(a0.left, ast.Attribute)
                        and a0.left.attr == "suffix" and isinstance(call.func, ast.Attribute)
                        and ast.dump(a0.left.value) == ast.dump(call.func.value)):
                    # p.with_suffix(p.suffix + X) appends X
                    return V.concat(recv_path, self.ev(a0.right, stmt))
                sfx = ev(a0)
                return V.with_suffix(recv_path, sfx.alts[0]) if isinstance(sfx, Str) and len(sfx.alts) == 1 else Unk("dynamic")
            if attr == "with_name":
                nm = ev(self._arg(call, 0))
                return V.with_name(recv_path, nm.alts[0]) if isinstance(nm, Str) and len(nm.alts) == 1 else Unk("dynamic")
            if attr in ("glob", "rglob"):
                pat = ev(self._arg(call, 0)) or V.s("*")
                if attr == "rglob":
                    pat = V.join(V.s("**"), pat)
                return Listing(V.join(recv_path, pat))
            if attr == "iterdir":
                return Listing(V.join(recv_path, V.s("*")))
            if attr in ("read_text", "read_bytes"):
                return Unk("data:record")
            if attr == "open":
                return Handle(recv_path, "open", self.mod.ln(call))
            if attr == "format" and isinstance(recv_path, Str):
                return self._format(recv_path, call, stmt)
            if attr == "join" and isinstance(recv_path, Str):
                seq = ev(self._arg(call, 0))
                if isinstance(seq, Lst) and seq.items and len(recv_path.alts) == 1:
                    sep = recv_path.alts[0]
                    vals = []
                    for i, it in enumerate(seq.items):
                        if i:
                            vals.append(V.s(sep))
                        vals.append(it)
                    return V.concat(*vals)
                return Unk("assembled:container")
            if attr in ("strip", "rstrip", "lstrip") and isinstance(recv_path, Str):
                chars = ev(self._arg(call, 0))
                cs = chars.alts[0] if isinstance(chars, Str) and len(chars.alts) == 1 else None
                fn = {"strip": str.strip, "rstrip": str.rstrip, "lstrip": str.lstrip}[attr]
                return V.map_str(recv_path, lambda t: fn(t, cs) if cs is not None else fn(t))
            if attr in ("lower", "upper", "casefold"):
                fn = str.lower if attr != "upper" else str.upper
                return V.map_str(recv_path, lambda t: _apply_lit(t, fn))
            if attr == "replace" and isinstance(recv_path, Str):
                a = ev(self._arg(call, 0))
                b2 = ev(self._arg(call, 1))
                if isinstance(a, Str) and isinstance(b2, Str) and len(a.alts) == 1 and len(b2.alts) == 1:
                    return V.map_str(recv_path, lambda t: t.replace(a.alts[0], b2.alts[0]))
                return Unk("dynamic")
            if attr in ("removeprefix", "removesuffix") and isinstance(recv_path, Str):
                a = ev(self._arg(call, 0))
                if isinstance(a, Str) and len(a.alts) == 1:
                    return V.map_str(recv_path, lambda t: getattr(t, attr)(a.alts[0]))
                return Unk("dynamic")
            if attr in ("split", "rsplit", "splitlines", "partition", "rpartition"):
                return Unk("assembled:split")
            if attr == "relative_to":
                return Unk("assembled:call")
            return Unk("dynamic")
        if isinstance(recv, Dct):
            if attr == "get":
                k = ev(self._arg(call, 0))
                if isinstance(k, Str):
                    for kk, vv in recv.items:
                        if isinstance(kk, Str) and kk.alts == k.alts:
                            return vv
                d = ev(self._arg(call, 1))
                return d if d is not None else V.NONE
            if attr in ("keys",):
                return Lst(tuple(k for k, _ in recv.items))
            if attr in ("values",):
                return Lst(tuple(v for _, v in recv.items))
            if attr == "items":
                return Lst(tuple(Lst((k, v)) for k, v in recv.items))
            return Unk("dynamic")
        if isinstance(recv, Unk):
            if attr == "get":
                k = ev(self._arg(call, 0))
                hint = k.alts[0] if isinstance(k, Str) and len(k.alts) == 1 else None
                return Unk(recv.reason, hint=hint)
            if attr in ("strip", "lower", "upper", "rstrip", "lstrip", "decode", "encode"):
                return recv
            return Unk(recv.reason if recv.reason.startswith("data") else "assembled:call")
        if isinstance(recv, Obj):
            if recv.kind == "parser" and attr in ("parse_args", "parse_known_args", "parse_intermixed_args"):
                return Obj("args")
            if recv.kind == "proc" and attr == "communicate":
                return Lst((Unk("assembled:stdout"), Unk("assembled:stdout")))
            if recv.kind == "hash" and attr in ("hexdigest", "digest"):
                return V.s(P.WILD)
            if recv.kind == "hash" and attr == "update":
                return V.NONE
            if recv.kind == "args":
                return Unk("data:argv")
        if isinstance(recv, Lst):
            if attr in ("copy",):
                return recv
            if attr == "pop":
                return V.union(list(recv.items)) if recv.items else Unk("assembled:container")
        return Unk("assembled:call")

    def _call_tree(self, fn: Fn, call: ast.Call, stmt, bound_self: bool) -> V.Val:
        root = self.an.root_of(fn)
        if root:
            return V.s(P.tok(root))
        fi = self.an.func(fn.module, fn.qual) if "#" not in fn.module else self.an.modules[fn.module].funcs.get(fn.qual)
        if fi is None:
            return Unk("assembled:call")
        s = self.an.summary(fi)
        binding = self.binding(fi, call, stmt, bound_self)
        return V.subst_val(s.ret, binding) if not isinstance(s.ret, Unk) else s.ret

    def binding(self, fi: FuncInfo, call: ast.Call, stmt, bound_self: bool) -> dict:
        params = list(fi.params)
        if bound_self and params and params[0] in ("self", "cls"):
            params = params[1:]
        elif fi.cls and params and params[0] in ("self", "cls") and isinstance(call.func, ast.Attribute):
            params = params[1:]
        b: dict = {}
        pos_args = [a for a in call.args if not isinstance(a, ast.Starred)]
        has_star = any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords)
        for i, p in enumerate(params):
            node = pos_args[i] if i < len(pos_args) else None
            if node is None:
                for k in call.keywords:
                    if k.arg == p:
                        node = k.value
            if node is not None:
                v = self.ev(node, stmt)
                if isinstance(v, Unk) and v.hint is None and _hint_of(node):
                    v = Unk(v.reason, hint=_hint_of(node) if P.classify_name(_hint_of(node)) else None)
                b[p] = v
            elif p in fi.defaults:
                w = self.an_module_walker(fi.module)
                dv = w.ev(fi.defaults[p], fi.node)
                b[p] = dv if not isinstance(dv, NoneV) else Unk("assembled:parameter")
            else:
                b[p] = Unk("assembled:parameter" if not has_star else "assembled:container")
        for p in fi.params:
            b.setdefault(p, Unk("assembled:parameter"))
        return b

    # ------------------------------------------------------------- the walk
    def body_statements(self):
        if self.fi is None:
            return self.mod.tree.body
        return self.fi.node.body

    def run(self) -> Summary:
        self._walk_block(self.body_statements())
        self._finish()
        return self.summary

    def _walk_block(self, stmts) -> None:
        for s in stmts:
            self._walk_stmt(s)

    def _walk_stmt(self, s) -> None:
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return
        if isinstance(s, ast.ClassDef):
            if self.fi is None:
                for x in s.body:
                    if not isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        self._walk_stmt(x)
            return
        # expressions of this statement (not nested blocks)
        for fname, value in ast.iter_fields(s):
            if fname in ("body", "orelse", "finalbody", "handlers", "cases"):
                continue
            items = value if isinstance(value, list) else [value]
            for it in items:
                if isinstance(it, (ast.expr, ast.withitem, ast.keyword)):
                    for n in ast.walk(it):
                        self._visit_expr(n, s)
        self._visit_stmt_specific(s)
        for fname in ("body", "orelse", "finalbody"):
            block = getattr(s, fname, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                self._walk_block(block)
        if isinstance(s, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            for h in s.handlers:
                self._walk_block(h.body)
        if isinstance(s, ast.Match):
            for c in s.cases:
                if c.guard is not None:
                    for n in ast.walk(c.guard):
                        self._visit_expr(n, s)
                self._walk_block(c.body)

    def _visit_stmt_specific(self, s) -> None:
        ln = self.mod.ln(s)
        if isinstance(s, ast.Raise):
            exc = s.exc
            if exc is not None:
                ename = _dotted(exc.func) if isinstance(exc, ast.Call) else _dotted(exc)
                if ename == "SystemExit":
                    code = self.ev(exc.args[0], s) if isinstance(exc, ast.Call) and exc.args else Num(0)
                    self._exit_decision(s, code, ln)
                else:
                    d = M.Decision("raise", ln, None, ename.rsplit(".", 1)[-1] if ename else "")
                    self.decisions.append((s, d))
                    self.summary.raises.append(d)
            else:
                d = M.Decision("raise", ln, None, "re-raise")
                self.decisions.append((s, d))
        elif isinstance(s, ast.Return) and s.value is not None and self.fi is not None:
            if self.fi.qual in self.exit_funcs:
                v = self.ev(s.value, s)
                if isinstance(v, Num):
                    self._exit_decision(s, v, ln)
        elif isinstance(s, ast.Assign):
            for t in s.targets:
                if isinstance(t, ast.Subscript) and _const_str(t.slice) == "systemMessage":
                    self._system_message(s.value, s)
        elif isinstance(s, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            for h in s.handlers:
                names = []
                if h.type is not None:
                    for n in ast.walk(h.type):
                        if isinstance(n, (ast.Name, ast.Attribute)):
                            names.append(_dotted(n).rsplit(".", 1)[-1])
                self.handlers.append((h, tuple(sorted(set(names)))))

    def _exit_decision(self, s, code: V.Val, ln: int) -> None:
        if isinstance(code, Num):
            if code.value == 0:
                return
            d = M.Decision("exit2" if code.value == 2 else "exit", ln, code.value)
        elif isinstance(code, NoneV):
            return
        else:
            return
        self.decisions.append((s, d))
        self.summary.decisions.append(d)

    def _visit_expr(self, n, s) -> None:
        if isinstance(n, ast.JoinedStr):
            self._id_form(n, s)
        if isinstance(n, ast.Call):
            self._visit_call(n, s)
        elif isinstance(n, ast.Dict):
            self._visit_dict(n, s)
        elif isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load) and _const_str(n.slice) == "systemMessage":
            self.an.findings.system_message_relays.append((self.mod.path, self.mod.ln(n)))
        elif isinstance(n, ast.Subscript) and _dotted(n.value) in ("os.environ", "environ"):
            k = self.ev(n.slice, s)
            if isinstance(k, Str) and len(k.alts) == 1 and P.L not in k.alts[0]:
                self.an.findings.env_reads.append(M.EnvRead(self.mod.path, self.mod.ln(n), k.alts[0], None, ()))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in self.mod.docstrings:
            t = n.value
            if re.search(r'"decision"\s*:\s*"(block|deny)"|"permissionDecision"\s*:\s*"deny"', t):
                d = M.Decision("block", self.mod.ln(n), None, "json-text")
                self.decisions.append((s, d))
                self.summary.decisions.append(d)

    def _id_form(self, n, s) -> None:
        """An f-string that builds an id-shaped name (no path, no extension)."""
        for t in V.as_templates(self.ev(n, s)):
            form = id_form_of(t)
            if form:
                self.an.id_forms.append((self.mod.path, self.mod.ln(n), form, "python"))

    def _visit_dict(self, n: ast.Dict, s) -> None:
        for k, v in zip(n.keys, n.values):
            key = _const_str(k)
            if key in ("decision", "permissionDecision"):
                val = self.ev(v, s)
                alts = V.as_templates(val)
                if any(a in ("block", "deny") for a in alts):
                    d = M.Decision("block", self.mod.ln(n), None, key)
                    self.decisions.append((s, d))
                    self.summary.decisions.append(d)
            elif key == "systemMessage":
                self._system_message(v, s)

    def _system_message(self, vnode, s) -> None:
        val = self.ev(vnode, s)
        for t in V.as_templates(val):
            for shown in P.paths_in_text(P.shown_text(t)):
                self.an.findings.outputs.append(M.OwnerOutput(self.mod.path, self.mod.ln(vnode), "system_message", shown))

    def _emit(self, op: str, path: V.Val, mode: str, via: str, call, s, src: V.Val | None = None, chain=()) -> None:
        o = M.Op(self.mod.path, self.mod.ln(call), op, path, mode, via, "python", self.fname, src, tuple(chain), self.mod.origin)
        self.ops.append(o)
        if op == "read":
            self.reads.append((call, ReadInfo(path, mode, self.mod.ln(call), tuple(chain))))

    def _visit_call(self, call: ast.Call, s) -> None:
        kind, a, b = self.callee(call, s)
        ln = self.mod.ln(call)
        if kind == "ext":
            self._ext_effects(a, call, s)
        elif kind == "method":
            self._method_effects(a, b, call, s)
        elif kind == "tree":
            self._tree_effects(a, call, s, b)
        self._chain_check(kind, a, call, s)
        self._print_check(kind, a, b, call, s)
        self._env_check(kind, a, b, call, s)
        if kind == "ext" and a in _EXIT_CALLS:
            arg = self._arg(call, 0, "code")
            if arg is not None and not isinstance(arg, ast.Call):
                code = self.ev(arg, s)
                self._exit_decision(s, code, ln)

    def _dir_fd(self, call, s, p, kw: str = "dir_fd"):
        """A path relative to an open directory descriptor (dir_fd=)."""
        for k in call.keywords:
            if k.arg == kw and not (isinstance(k.value, ast.Constant) and k.value.value is None):
                h = self.ev(k.value, s)
                base = h.path if isinstance(h, Handle) else V.s(P.hole("assembled:dir_fd"))
                return V.join(base, p) if p is not None else p
        return p

    def _ext_effects(self, name: str, call, s) -> None:
        ev = lambda n: self.ev(n, s) if n is not None else None  # noqa: E731
        if name in _OPEN_FUNCS:
            p = ev(self._arg(call, 0, "file"))
            if p is None:
                return
            mnode = self._arg(call, 1, "mode")
            mode = ev(mnode) if mnode is not None else V.s("r")
            self._open_effect(p, mode, name, call, s)
        elif name == "os.open":
            a0 = self._arg(call, 0, "path")
            p = self._dir_fd(call, s, ev(a0))
            flags = self._arg(call, 1, "flags")
            text = ast.dump(flags) if flags is not None else ""
            if p is None or "O_DIRECTORY" in text:
                return
            if (isinstance(a0, ast.Attribute) and a0.attr == "parent") or (
                    isinstance(a0, ast.Call) and _dotted(a0.func) in ("os.path.dirname", "posixpath.dirname")):
                return      # a directory opened for its descriptor (fsync, dir_fd)
            if "O_EXCL" in text and "O_CREAT" in text:
                self._emit("create", p, "exclusive", name, call, s)
            elif any(f in text for f in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC")):
                self._emit("write", p, "append" if "O_APPEND" in text else "truncate", name, call, s)
            else:
                self._emit("read", p, "content", name, call, s)
        elif name in ("os.unlink", "os.remove"):
            p = self._dir_fd(call, s, ev(self._arg(call, 0, "path")))
            if p is not None:
                self._emit("unlink", p, "file", name, call, s)
        elif name == "shutil.rmtree":
            p = ev(self._arg(call, 0, "path"))
            if p is not None:
                self._emit("unlink", V.join(p, V.s("*")), "tree", name, call, s)
        elif name in ("os.rename", "os.replace", "shutil.move"):
            src = self._dir_fd(call, s, ev(self._arg(call, 0, "src")), "src_dir_fd")
            dst = self._dir_fd(call, s, ev(self._arg(call, 1, "dst")), "dst_dir_fd")
            if dst is not None:
                self._emit("rename", dst, "to", name, call, s, src=src)
        elif name in ("shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.copytree"):
            src = ev(self._arg(call, 0, "src"))
            dst = ev(self._arg(call, 1, "dst"))
            if src is not None:
                self._emit("read", src, "content", name, call, s)
            if dst is not None:
                self._emit("write", dst, "truncate", name, call, s)
        elif name in ("os.symlink", "os.link"):
            dst = ev(self._arg(call, 1, "dst"))
            if dst is not None:
                self._emit("create", dst, "link", name, call, s)
        elif name in _NAME_PROBES:
            p = self._dir_fd(call, s, ev(self._arg(call, 0, "path")))
            if p is not None:
                self._emit("read", p, "name", name, call, s)
        elif name in ("glob.glob", "glob.iglob"):
            p = ev(self._arg(call, 0, "pathname"))
            if p is not None:
                self._emit("read", p, "list", name, call, s)
        elif name in ("os.listdir", "os.scandir", "os.walk"):
            p = ev(self._arg(call, 0, "path")) or V.s(".")
            self._emit("read", V.join(p, V.s("*")), "list", name, call, s)
        elif name == "sqlite3.connect":
            p = ev(self._arg(call, 0, "database"))
            if p is not None:
                self._emit("read", p, "db", name, call, s)
                self._emit("write", p, "db", name, call, s)
        elif name in ("runpy.run_path",):
            p = ev(self._arg(call, 0, "path_name"))
            if p is not None:
                self._emit("read", p, "source", name, call, s)
        elif name in ("importlib.util.spec_from_file_location", "importlib.machinery.SourceFileLoader"):
            p = ev(self._arg(call, 1, "location"))
            if p is not None:
                self._emit("read", p, "source", name, call, s)
        elif name in ("logging.FileHandler", "logging.handlers.RotatingFileHandler",
                      "logging.handlers.WatchedFileHandler", "logging.handlers.TimedRotatingFileHandler"):
            p = ev(self._arg(call, 0, "filename"))
            if p is not None:
                self._emit("write", p, "append", name, call, s)
        elif name in ("tempfile.mkstemp", "tempfile.NamedTemporaryFile"):
            v = self.ev(call, s)
            p = v.items[1] if isinstance(v, Lst) else (v.path if isinstance(v, Handle) else None)
            if p is not None:
                self._emit("create", p, "temp", name, call, s)
        elif name in ("os.utime",):
            p = ev(self._arg(call, 0, "path"))
            if p is not None:
                self._emit("write", p, "touch", name, call, s)
        elif name in ("fcntl.flock", "fcntl.lockf"):
            h = ev(self._arg(call, 0))
            if isinstance(h, Handle):
                self.lock_sites.add(h.site)
        elif name in _SUBPROCESS:
            self._invocation(name, call, s)

    def _open_effect(self, p: V.Val, mode: V.Val, via: str, call, s) -> None:
        m = mode.alts[0] if isinstance(mode, Str) and len(mode.alts) == 1 else None
        if m is None:
            self._emit("read", p, "open-dynamic", via, call, s)
            return
        if "x" in m:
            self._emit("create", p, "exclusive", via, call, s)
        elif "a" in m:
            self._emit("write", p, "append", via, call, s)
        elif "w" in m:
            self._emit("write", p, "truncate", via, call, s)
        elif "+" in m:
            self._emit("read", p, "content", via, call, s)
            self._emit("write", p, "update", via, call, s)
        else:
            self._emit("read", p, "content", via, call, s)

    def _method_effects(self, recv: V.Val, attr: str, call, s) -> None:
        if isinstance(recv, Handle):
            return
        path = recv
        if not (V.is_strlike(path) or isinstance(path, Unk)):
            return
        ev = lambda n: self.ev(n, s) if n is not None else None  # noqa: E731
        via = "Path." + attr
        if attr in ("read_text", "read_bytes"):
            self._emit("read", path, "content", via, call, s)
        elif attr in ("write_text", "write_bytes"):
            self._emit("write", path, "truncate", via, call, s)
        elif attr == "open":
            if isinstance(path, Unk) and not self._looks_pathy(call.func.value):
                return
            mnode = self._arg(call, 0, "mode")
            mode = ev(mnode) if mnode is not None else V.s("r")
            self._open_effect(path, mode, via, call, s)
        elif attr == "touch":
            self._emit("create", path, "touch", via, call, s)
        elif attr == "unlink":
            self._emit("unlink", path, "file", via, call, s)
        elif attr in ("rename", "replace") and (V.is_strlike(path) or self._looks_pathy(call.func.value)):
            if isinstance(path, Str) and attr == "replace" and not self._looks_pathy(call.func.value) and len(call.args) == 2:
                return  # str.replace(old, new)
            if attr == "replace" and len(call.args) != 1:
                return
            dst = ev(self._arg(call, 0, "target"))
            if dst is not None:
                self._emit("rename", dst, "to", via, call, s, src=path)
        elif attr in ("symlink_to", "hardlink_to"):
            self._emit("create", path, "link", via, call, s)
        elif attr in ("exists", "is_file", "is_dir", "is_symlink", "stat", "lstat") and not call.args:
            if isinstance(path, Unk) and not self._looks_pathy(call.func.value):
                return
            self._emit("read", path, "name", via, call, s)
        elif attr in ("glob", "rglob", "iterdir"):
            v = self.ev(call, s)
            if isinstance(v, Listing):
                self._emit("read", v.pattern, "list", via, call, s)

    def _looks_pathy(self, node) -> bool:
        h = (_hint_of(node) or "").lower()
        return any(w in h for w in ("path", "file", "dir", "root", "home", "report", "log", "lock", "out", "dest", "target", "src"))

    def _tree_effects(self, fn: Fn, call, s, bound_self) -> None:
        if self.an.root_of(fn):
            return
        fi = self.an.func(fn.module, fn.qual) if "#" not in fn.module else self.an.modules[fn.module].funcs.get(fn.qual)
        if fi is None:
            return
        key = (fi.module.path, fi.qual)
        self.an.calls_to.setdefault(key, []).append((self, call, s))
        summ = self.an.summary(fi)
        if not (summ.param_effects or summ.return_reads or summ.decisions):
            return
        binding = self.binding(fi, call, s, bound_self)
        ln = self.mod.ln(call)
        for e in summ.param_effects:
            self.an.instantiated[id(e)] = self.an.instantiated.get(id(e), 0) + 1
            p = V.subst_val(e.path, binding)
            src = V.subst_val(e.src, binding) if e.src is not None else None
            chain = (f"{e.component}:{e.line}",) + tuple(e.chain)
            self._emit(e.op, p, e.mode, e.via, call, s, src=src, chain=chain)
        for r in summ.return_reads:
            p = V.subst_val(r.path, binding)
            self.reads.append((call, ReadInfo(p, r.mode, ln, (f"{fi.module.path}:{r.line}",) + tuple(r.via))))
        for d in summ.decisions:
            nd = M.Decision(d.kind, ln, d.code, fi.qual, (f"{fi.module.path}:{d.line}",))
            self.decisions.append((s, nd))
            self.summary.decisions.append(nd)

    def _invocation(self, name: str, call, s) -> None:
        argv_node = self._arg(call, 0, "args")
        if argv_node is None:
            return
        val = self.ev(argv_node, s)
        items = val.items if isinstance(val, Lst) else (val,)
        templates = []
        for it in items:
            templates.extend(V.as_templates(it))
        captured = name in ("subprocess.check_output", "os.popen") or any(
            k.arg in ("stdout", "capture_output") for k in call.keywords)
        interp = ""
        for t in templates:
            if isinstance(t, str) and re.search(r"(^|/)(python3?|bash|sh)$", t):
                interp = t.rsplit("/", 1)[-1]
        for i, it in enumerate(items):
            for t in V.as_templates(it):
                target = tree_target(t, self.an.file_set)
                if target:
                    self.an.findings.invocations.append(M.Invocation(
                        self.mod.path, self.mod.ln(call), target, interp or "exec", captured, self.fname,
                        tuple(items[i + 1:i + 10])))

    def _chain_check(self, kind, a, call, s) -> None:
        base = self.an.chain_basename
        if not base or not self.mod.mentions_chain:
            return
        if kind == "ext" and not (a in _SUBPROCESS or a in _LOADERS):
            return
        if kind not in ("ext", "tree"):
            return
        if kind == "tree" and self.an.root_of(a):
            return
        found = False
        for node in list(call.args) + [k.value for k in call.keywords]:
            v = self.ev(node, s)
            items = v.items if isinstance(v, Lst) else (v,)
            for it in items:
                for t in V.as_templates(it):
                    if t.rstrip("/").rsplit("/", 1)[-1] == base:
                        found = True
        if found:
            self.chain_seeds.append((call, "exec" if kind == "ext" and a in _SUBPROCESS else "load"))

    def _print_check(self, kind, a, b, call, s) -> None:
        stream = None
        nodes = []
        if kind == "ext" and a == "print":
            stream = "stdout"
            for k in call.keywords:
                if k.arg == "file":
                    d = _dotted(k.value)
                    stream = "stderr" if "stderr" in d else ("stdout" if "stdout" in d else "file")
            nodes = list(call.args)
        elif kind == "ext" and a in ("sys.stdout.write", "sys.stderr.write"):
            stream = "stderr" if "stderr" in a else "stdout"
            nodes = list(call.args)
        if stream is None or stream == "file":
            return
        for n in nodes:
            v = self.ev(n, s)
            for t in V.as_templates(v):
                for shown in P.paths_in_text(P.shown_text(t)):
                    self.summary.prints.append((self.mod.ln(call), stream, shown))

    def _env_check(self, kind, a, b, call, s) -> None:
        if kind == "ext" and a in ("os.environ.get", "os.getenv"):
            k = self.ev(self._arg(call, 0, "key"), s) if self._arg(call, 0, "key") is not None else None
            if isinstance(k, Str) and len(k.alts) == 1 and P.L not in k.alts[0]:
                dnode = self._arg(call, 1, "default")
                dv = self.ev(dnode, s) if dnode is not None else None
                default = dv.alts[0] if isinstance(dv, Str) and len(dv.alts) == 1 else None
                self.an.findings.env_reads.append(M.EnvRead(self.mod.path, self.mod.ln(call), k.alts[0], default,
                                                            tuple(self._compared(call, s))))

    def _compared(self, call, s) -> list:
        out = []
        holder = s
        scope = self.fi.node if self.fi else self.mod.tree
        assigned = []
        if isinstance(holder, ast.Assign) and any(n is call for n in ast.walk(holder.value)):
            assigned = [t.id for t in holder.targets if isinstance(t, ast.Name)]
        for n in ast.walk(scope):
            if isinstance(n, ast.Compare):
                ops = [n.left] + list(n.comparators)
                hit = any(any(x is call for x in ast.walk(o)) for o in ops) or any(
                    isinstance(o, ast.Name) and o.id in assigned for o in ops)
                if hit:
                    for o in ops:
                        for x in ast.walk(o):
                            c = _const_str(x)
                            if c is not None:
                                out.append(c)
        return sorted(set(out))

    # ------------------------------------------------------------- finishing
    def _mentions(self) -> None:
        """Tree scripts the module names in a path expression."""
        div_parent = {id(m.right): m for m in ast.walk(self.mod.tree) if isinstance(m, ast.BinOp)}
        for n in ast.walk(self.mod.tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.endswith((".sh", ".py")) \
                    and id(n) not in self.mod.docstrings and len(n.value) < 200:
                holder = n
                parent_expr = div_parent.get(id(n))
                v = self.ev(parent_expr or holder, self.mod.stmt_of.get(id(holder)))
                for t in V.as_templates(v):
                    tgt = tree_target(t, self.an.file_set)
                    if tgt:
                        self.an.script_mentions.append((self.mod.path, tgt))

    def _finish(self) -> None:
        fi = self.fi
        an = self.an
        if fi is None and not self.mod.embedded and self.mod.source_hint:
            self._mentions()
        # lock marks
        for o in self.ops:
            if o.line in self.lock_sites and o.op in ("write", "read", "create"):
                o.mode = "lock"
        # split param-dependent operations from emitted ones
        for o in self.ops:
            temps = V.as_templates(o.path)
            if fi is not None and temps and any(P.has_params(t) for t in temps):
                self.summary.param_effects.append(o)
                an.all_param_effects.append(o)
            else:
                an.findings.ops.append(o)
        # return value and return reads
        if fi is not None:
            rets = []
            for n in self._stmts_in(fi.node.body):
                if isinstance(n, ast.Return) and n.value is not None:
                    rets.append(self.ev(n.value, n))
            if rets:
                self.summary.ret = V.union(rets)
        self._decide()
        self._chain_uses()
        dec_stmts = {id(st) for st, d in self.decisions if d.kind in ("exit2", "block")}
        for h, names in self.handlers:
            blocks = any(id(x) in dec_stmts for x in self._stmts_in(h.body))
            self.an.findings.raise_handlers.append((self.mod.path, self.mod.ln(h), names, blocks))
        for line, stream, shown in self.summary.prints:
            self.an.prints.append((self.mod.path, line, stream, shown, self.fname, self.mod.origin))

    def _stmts_in(self, block) -> list:
        """Statements of a block and its nested blocks, not of nested defs."""
        out = []
        for s in block or []:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            out.append(s)
            for fname in ("body", "orelse", "finalbody"):
                sub = getattr(s, fname, None)
                if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                    out.extend(self._stmts_in(sub))
            for h in getattr(s, "handlers", None) or []:
                out.extend(self._stmts_in(h.body))
            for c in getattr(s, "cases", None) or []:
                out.extend(self._stmts_in(c.body))
        return out

    def _own_nodes(self, st):
        """Expression nodes of one statement, not of its nested blocks."""
        for fname, value in ast.iter_fields(st):
            if fname in ("body", "orelse", "finalbody", "handlers", "cases"):
                continue
            items = value if isinstance(value, list) else [value]
            for it in items:
                if isinstance(it, (ast.expr, ast.withitem, ast.keyword, ast.comprehension)):
                    yield from ast.walk(it)

    def _taint(self, seeds: list[tuple]) -> dict:
        """name -> set of seed indices, from seed calls through assignments."""
        tainted: dict[str, set] = {}
        body = self.body_statements()
        stmts = self._stmts_in(body)
        call_ids = {id(c): i for i, (c, _) in enumerate(seeds)}

        def seeds_in(node) -> set:
            out = set()
            if node is None:
                return out
            for n in ast.walk(node):
                i = call_ids.get(id(n))
                if i is not None:
                    out.add(i)
            return out

        assigns = []
        for st in stmts:
            if isinstance(st, ast.Assign):
                assigns.append(([t for t in st.targets], st.value))
            elif isinstance(st, (ast.AnnAssign, ast.AugAssign)) and st.value is not None:
                assigns.append(([st.target], st.value))
            elif isinstance(st, (ast.For, ast.AsyncFor)):
                assigns.append(([st.target], st.iter))
            elif isinstance(st, (ast.With, ast.AsyncWith)):
                for it in st.items:
                    if it.optional_vars is not None:
                        assigns.append(([it.optional_vars], it.context_expr))
            for n in self._own_nodes(st):
                if isinstance(n, ast.NamedExpr):
                    assigns.append(([n.target], n.value))
        for _ in range(6):
            changed = False
            for targets, value in assigns:
                if value is None:
                    continue
                src = seeds_in(value)
                for nm in _names_in(value):
                    src |= tainted.get(nm, set())
                if not src:
                    continue
                for t in targets:
                    for nm in _target_names(t):
                        if isinstance(t, ast.Name) or isinstance(t, (ast.Tuple, ast.List)):
                            cur = tainted.setdefault(nm, set())
                            if not src <= cur:
                                cur |= src
                                changed = True
            if not changed:
                break
        return tainted

    def _decide(self) -> None:
        reads = self.reads
        if not reads:
            return
        an = self.an
        tainted = self._taint(reads)
        call_ids = {id(c): i for i, (c, _) in enumerate(reads)}

        def reads_of(node) -> set:
            out = set()
            if node is None:
                return out
            for n in ast.walk(node):
                i = call_ids.get(id(n))
                if i is not None:
                    out.add(i)
                if isinstance(n, ast.Name):
                    out |= tainted.get(n.id, set())
            return out

        dec_by_stmt: dict[int, list] = {}
        for st, d in self.decisions:
            dec_by_stmt.setdefault(id(st), []).append(d)

        def decisions_in(block) -> list:
            out = []
            for st in self._stmts_in(block):
                out += dec_by_stmt.get(id(st), [])
            return out

        # a test examines a part of a read's value when it subscripts it, takes an attribute of it
        # or `.get`s from it, or tests a name assigned from such a part: a test of the value whole
        # (`if has_consent(p):`) uses the verdict the reading function returned (rule (4))
        parted_names: dict[str, set] = {}

        def parts_in(node) -> set:
            out = set()
            if node is None:
                return out
            for n in ast.walk(node):
                base = None
                if isinstance(n, (ast.Subscript, ast.Attribute)):
                    base = n.value
                if base is not None:
                    out |= reads_of(base)
                if isinstance(n, ast.Name):
                    out |= parted_names.get(n.id, set())
            return out

        for _ in range(3):
            for st in self._stmts_in(self.body_statements()):
                if isinstance(st, ast.Assign) and st.value is not None:
                    src = parts_in(st.value)
                    if src:
                        for t in st.targets:
                            for nm in _target_names(t):
                                parted_names.setdefault(nm, set()).update(src)

        paired: set = set()
        body = self.body_statements()
        stmts = [x for x in self._stmts_in(body)]
        fi = self.fi
        for st in stmts:
            if isinstance(st, (ast.If, ast.While)):
                rs = reads_of(st.test)
                if not rs:
                    continue
                parted = parts_in(st.test)
                decs = decisions_in(st.body) + decisions_in(st.orelse)
                if isinstance(st, ast.If) and not st.orelse and _terminates(st.body):
                    # a guard clause: what follows it is the branch's else
                    info = self.mod.parent.get(id(st))
                    if info is not None:
                        owner, fieldname, idx = info
                        decs = decs + decisions_in(getattr(owner, fieldname)[idx + 1:])
                for r in sorted(rs):
                    if decs:
                        for d in decs:
                            self._deciding(reads[r][1], d, "branch", whole=r not in parted)
                            paired.add((r, id(d)))
                    else:
                        self._deciding(reads[r][1], M.Decision("route", self.mod.ln(st)), "branch",
                                       whole=r not in parted)
                if fi is not None:
                    for x in self._stmts_in(st.body) + self._stmts_in(st.orelse):
                        if isinstance(x, ast.Return) and x.value is not None:
                            for r in sorted(rs):
                                self.summary.return_reads.append(reads[r][1])
                            break
            elif isinstance(st, ast.Assert):
                parted = parts_in(st.test)
                for r in sorted(reads_of(st.test)):
                    self._deciding(reads[r][1], M.Decision("raise", self.mod.ln(st), None, "AssertionError"), "assert",
                                   whole=r not in parted)
            elif isinstance(st, ast.Match):
                rs = reads_of(st.subject)
                parted = parts_in(st.subject)
                for c in st.cases:
                    for d in decisions_in(c.body):
                        for r in sorted(rs):
                            self._deciding(reads[r][1], d, "branch", whole=r not in parted)
                            paired.add((r, id(d)))
            elif isinstance(st, (ast.Try, getattr(ast, "TryStar", ast.Try))):
                rs = set()
                for x in self._stmts_in(st.body):
                    for n in self._own_nodes(x):
                        i = call_ids.get(id(n))
                        if i is not None:
                            rs.add(i)
                if not rs:
                    continue
                for h in st.handlers:
                    for d in decisions_in(h.body):
                        for r in sorted(rs):
                            # the reading function raised: its own verdict on the content
                            self._deciding(reads[r][1], d, "except", whole=True)
                            paired.add((r, id(d)))
            elif isinstance(st, ast.Return) and st.value is not None and fi is not None:
                for r in sorted(reads_of(st.value)):
                    self.summary.return_reads.append(reads[r][1])
        # order: a decision after the read in the same function
        for i, (call, info) in enumerate(reads):
            for st, d in self.decisions:
                if d.kind in ("exit2", "block") and d.line > info.line and (i, id(d)) not in paired:
                    self._deciding(info, d, "order")
        # dedupe return reads
        seen = set()
        uniq = []
        for r in self.summary.return_reads:
            k = (tuple(V.as_templates(r.path)), r.line)
            if k not in seen:
                seen.add(k)
                uniq.append(r)
        self.summary.return_reads = uniq

    def _deciding(self, info: ReadInfo, d: M.Decision, evidence: str, whole: bool = False) -> None:
        self.an.findings.deciding.append(M.Deciding(self.mod.path, self.fname, info.line, info.path, info.mode,
                                                    d, evidence, "python", tuple(info.via), whole))

    def _chain_uses(self) -> None:
        seeds = list(self.chain_seeds)
        if not seeds:
            return
        for call, how in seeds:
            uses, fields = self.chain_use_of(call)
            self.an.findings.chain_calls.append(M.ChainCall(self.mod.path, self.mod.ln(call), how,
                                                            tuple(sorted(uses)), tuple(sorted(fields)), self.fname))
            if "returned" in uses and self.fi is not None:
                self.summary.chain_returned = True
                self.an.chain_proxies.add((self.fi.module.path, self.fi.qual))

    def chain_use_of(self, call, depth: int = 0) -> tuple[set, set]:
        tainted = self._taint([(call, None)])
        tnames = {n for n, v in tainted.items() if v}
        return self._uses_of(tnames, call, depth)

    def param_use_of(self, pname: str, depth: int) -> tuple[set, set]:
        tainted = self._taint_names({pname})
        return self._uses_of(tainted, None, depth)

    def _taint_names(self, names: set) -> set:
        out = set(names)
        body = self.body_statements()
        for _ in range(6):
            changed = False
            for st in self._stmts_in(body):
                pairs = []
                if isinstance(st, ast.Assign):
                    pairs = [(t, st.value) for t in st.targets]
                elif isinstance(st, (ast.AnnAssign, ast.AugAssign)) and st.value is not None:
                    pairs = [(st.target, st.value)]
                elif isinstance(st, (ast.For, ast.AsyncFor)):
                    pairs = [(st.target, st.iter)]
                elif isinstance(st, (ast.With, ast.AsyncWith)):
                    pairs = [(it.optional_vars, it.context_expr) for it in st.items if it.optional_vars is not None]
                for t, v in pairs:
                    if _names_in(v) & out:
                        for nm in _target_names(t):
                            if nm not in out:
                                out.add(nm)
                                changed = True
            if not changed:
                break
        return out

    def _uses_of(self, tnames: set, call, depth: int) -> tuple[set, set]:
        uses, fields = set(), set()
        body = self.body_statements()

        def touches(node) -> bool:
            return any((isinstance(n, ast.Name) and n.id in tnames) or (call is not None and n is call) for n in ast.walk(node))

        def field_of(n) -> str | None:
            if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load) and touches(n.value):
                return _const_str(n.slice)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" \
                    and touches(n.func.value):
                return _const_str(n.args[0]) if n.args else None
            return None

        # Rule (5): a field of the output is decided on where a test examines it (a branch's or an
        # assertion's test, a comparison, a boolean operation), directly or through a name assigned
        # or looped from it, or where it is returned for a caller to test; a field only carried on
        # (copied into a record, iterated for the next step, printed) is the output used, not a
        # decision of the reader's
        tests: set = set()
        returned: set = set()       # a field handed back to the caller, which may test it
        field_names: set = set()
        for st in self._stmts_in(body):
            roots = []
            if isinstance(st, (ast.If, ast.While, ast.Assert)):
                roots.append(st.test)
            elif isinstance(st, ast.Return) and st.value is not None:
                returned |= {id(x) for x in ast.walk(st.value)}
            elif isinstance(st, ast.Match):
                roots.append(st.subject)
            for n in self._own_nodes(st):
                if isinstance(n, (ast.Compare, ast.BoolOp, ast.IfExp)) or \
                        isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
                    roots.append(n)
                elif isinstance(n, ast.comprehension):
                    roots += n.ifs
            for r in roots:
                tests |= {id(x) for x in ast.walk(r)}
        for _ in range(3):
            for st in self._stmts_in(body):
                pairs = []
                if isinstance(st, ast.Assign):
                    pairs = [(t, st.value) for t in st.targets]
                elif isinstance(st, (ast.For, ast.AsyncFor)):
                    pairs = [(st.target, st.iter)]
                for t, v in pairs:
                    if any(field_of(x) is not None for x in ast.walk(v)) or _names_in(v) & field_names:
                        field_names |= set(_target_names(t))
            for st in self._stmts_in(body):
                for n in self._own_nodes(st):
                    if isinstance(n, ast.comprehension) and (
                            any(field_of(x) is not None for x in ast.walk(n.iter)) or _names_in(n.iter) & field_names):
                        field_names |= set(_target_names(n.target))
        for st in self._stmts_in(body):
            for n in self._own_nodes(st):
                k = field_of(n)
                if k is not None:
                    if id(n) in tests or id(n) in returned:
                        uses.add("fields")
                        fields.add(k)
                    else:
                        uses.add("data")
                elif isinstance(n, ast.Name) and n.id in field_names and id(n) in tests:
                    uses.add("fields")
                elif isinstance(n, ast.Attribute) and n.attr == "returncode" and touches(n.value):
                    uses.add("status")
                elif isinstance(n, ast.Call) and _dotted(n.func) in ("print", "sys.stdout.write") and any(touches(a) for a in n.args):
                    uses.add("verbatim")
            if isinstance(st, ast.Return) and st.value is not None and touches(st.value):
                uses.add("returned")
            # handed to a tree function: how that function uses its parameter
            if depth < 2:
                for n in self._own_nodes(st):
                    if not isinstance(n, ast.Call):
                        continue
                    for i, a in enumerate(n.args):
                        if isinstance(a, ast.Starred) or not touches(a) or a is call:
                            continue
                        kind, fn, bound = self.callee(n, st)
                        if kind != "tree" or self.an.root_of(fn):
                            continue
                        fi = self.an.func(fn.module, fn.qual) if "#" not in fn.module else None
                        if fi is None:
                            continue
                        params = list(fi.params)
                        if (bound or (fi.cls and isinstance(n.func, ast.Attribute))) and params and params[0] in ("self", "cls"):
                            params = params[1:]
                        if i >= len(params):
                            continue
                        self.an.summary(fi)
                        sub = FunctionWalk(self.an, fi.module, fi)
                        u2, f2 = sub.param_use_of(params[i], depth + 1)
                        uses |= {u for u in u2 if u != "verbatim"} | {"passed"}
                        fields |= f2
        if call is not None:
            for k in call.keywords:
                if k.arg == "check" and isinstance(k.value, ast.Constant) and k.value.value:
                    uses.add("status")
        if not uses:
            uses.add("verbatim")
        return uses, fields


def id_form_of(t: str) -> str | None:
    toks = P.tokens_in(t)
    ids = [x for x in toks if x in P.IDS or (x.startswith("@") and P.classify_name(V.param_hint(x) or "") in P.IDS)]
    lit = P.literal_text(t)
    if not ids or "/" in t or re.search(r"\.[A-Za-z]{1,5}$", lit) or not lit.strip() or len(lit) > 60:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.:-]*", lit) or len(re.sub(r"[^A-Za-z0-9]", "", lit)) < 2:
        return None
    return P.shown_text(t)


def _terminates(block) -> bool:
    if not block:
        return False
    last = block[-1]
    if isinstance(last, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
        return True
    if isinstance(last, ast.Expr) and isinstance(last.value, ast.Call) and _dotted(last.value.func) in _EXIT_CALLS:
        return True
    if isinstance(last, ast.If):
        return _terminates(last.body) and _terminates(last.orelse)
    return False


def _param_only(v) -> bool:
    return isinstance(v, Str) and bool(v.alts) and all(V._is_param_only(a) for a in v.alts)


def _safe_key(k: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", k)[:40]


def _apply_lit(t: str, fn) -> str:
    return "".join(P.tok(x) if is_tok else fn(x) for is_tok, x in P.split(t))


def tree_target(template: str, file_set: set) -> str | None:
    """The tree file a script path refers to: <harness>/x, <proj>/x or x."""
    pat, _, status = P.to_pattern(template)
    if status != "full":
        return None
    for root in ("<harness>/", "<proj>/"):
        if pat.startswith(root):
            rel = pat[len(root):]
            if rel in file_set:
                return rel
    return None


def literal_facts(mod: PyModule, findings: M.Findings) -> None:
    """Collections, mappings, alternations and branch maps of string literals."""
    comp = mod.path
    for n in ast.walk(mod.tree):
        if isinstance(n, (ast.List, ast.Tuple, ast.Set)):
            strs = [e.value for e in n.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(strs) >= 2:
                findings.literals.append(M.LiteralFact(comp, mod.ln(n), "collection", tuple(strs)))
        elif isinstance(n, ast.Dict):
            pairs = []
            for k, v in zip(n.keys, n.values):
                ks = _const_str(k)
                if ks is None:
                    continue
                vs = _const_str(v)
                pairs.append((ks, vs))
            if pairs:
                findings.literals.append(M.LiteralFact(comp, mod.ln(n), "mapping", tuple(p[0] for p in pairs), tuple(pairs)))
                vals = [p[1] for p in pairs if p[1] is not None]
                if len(vals) >= 2:
                    findings.literals.append(M.LiteralFact(comp, mod.ln(n), "collection", tuple(vals)))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and "|" in n.value and id(n) not in mod.docstrings:
            toks = [t for t in re.split(r"[|()^$\s?:\\]+", n.value) if t]
            if len(toks) >= 2 and len(n.value) < 400:
                findings.literals.append(M.LiteralFact(comp, mod.ln(n), "alternation", tuple(toks)))
        elif isinstance(n, ast.If):
            tests = [c.value for c in ast.walk(n.test) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
            if not tests:
                continue
            results = []
            for st in n.body[:3]:
                v = None
                if isinstance(st, ast.Return):
                    v = _const_str(st.value)
                elif isinstance(st, ast.Assign):
                    v = _const_str(st.value)
                if v is not None:
                    results.append(v)
            if results:
                pairs = tuple((t, results[0]) for t in tests)
                findings.literals.append(M.LiteralFact(comp, mod.ln(n), "branch_map", tuple(tests), pairs))
